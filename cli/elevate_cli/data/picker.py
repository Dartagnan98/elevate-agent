"""Sprint 4 — template picker.

Picks one template for a contact from the live pool, gated by:

1. **Eligibility**  — ``status='live' AND active=1`` plus lane/channel
   match. Channel ``'any'`` on the template matches any caller channel.
2. **Per-contact 7-day cooldown** — a template that's already been sent
   to this contact in the last 7 days is excluded so the realtor never
   double-taps the same lead with the same script.
3. **Thompson sampling** — for each surviving template, draw one sample
   from ``Beta(wins + 1, uses - wins + 1)`` and pick the highest. The
   ``+1`` smoothing keeps brand-new templates (uses=0) in the mix; their
   distribution is wide so they get exploration but rarely beat a proven
   template that has tightened up its distribution.

``wins`` is the confident-attribution counter from
:mod:`elevate_cli.data.templates` — Sprint 4B fills it from
:func:`record_reply_attributed`. ``replies`` (raw count, including
ambiguous attributions) is intentionally NOT used here so the picker
can't be poisoned by cross-channel guesses.

The AI ranker hook (Sprint 4 plan §4.1 stage 2) is deferred: the
picker accepts a ``ranker`` callable so the outreach worker can pass
in a Claude/Codex ranker when auth is healthy. When ``ranker=None``
(the default) Thompson sampling is the deterministic fallback.

Public surface:

* :func:`pick_template`
* :func:`eligible_templates` — list survivors without sampling (for
  /admin/templates "what would the picker see?" debugging).
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from elevate_cli.data import templates as _templates


_COOLDOWN_DAYS = 7


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "+00:00"
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _channel_matches(template_channel: str, request_channel: str) -> bool:
    """Template channel ``'any'`` matches any request; otherwise exact."""
    return template_channel == "any" or template_channel == request_channel


def _match_rules_pass(rules: Any, context: dict[str, Any]) -> bool:
    """V1 match-rules evaluator.

    The schema column is JSON-typed but the V1 contract only uses simple
    equality predicates (e.g. ``{"contactType": "buyer"}``). Anything
    more elaborate is V2 work — until then unknown rules pass through
    so the picker doesn't silently drop templates the realtor wrote.

    Empty / null rules → unconditional pass.
    """
    if rules in (None, "", {}):
        return True
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except json.JSONDecodeError:
            return True
    if not isinstance(rules, dict):
        return True
    for key, expected in rules.items():
        actual = context.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _recent_cooldown_template_ids(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    cutoff_iso: str,
) -> set[str]:
    """Templates already sent to this contact in the last 7 days.

    Reads ``events`` rows of kind ``send`` (the source-of-truth event
    for "we actually sent this template to this contact"). ``outbound``
    rows are excluded because not every outbound carries a template_id —
    backfilled history can have NULL template_id even for templated
    sends, and we don't want NULL collisions to leak through the filter.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT template_id
        FROM events
        WHERE contact_id = ?
          AND kind = 'send'
          AND template_id IS NOT NULL
          AND ts >= ?
        """,
        (contact_id, cutoff_iso),
    ).fetchall()
    return {r["template_id"] for r in rows}


def eligible_templates(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    lane: str,
    channel: str,
    context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return templates that pass eligibility + cooldown filters.

    Skips Thompson sampling — useful for diagnostics / /admin/templates
    "what would the picker see right now?" panel. ``context`` is the
    match_rules evaluation context (e.g. ``{"contactType": "buyer"}``).
    """
    cutoff = (now or _now()) - timedelta(days=_COOLDOWN_DAYS)
    cooldown_ids = _recent_cooldown_template_ids(
        conn, contact_id=contact_id, cutoff_iso=_iso_utc(cutoff)
    )
    candidates = _templates.list_templates(
        conn, lane=lane, status="live", active_only=True
    )
    out: list[dict[str, Any]] = []
    for tpl in candidates:
        if not _channel_matches(tpl["channel"], channel):
            continue
        if tpl["id"] in cooldown_ids:
            continue
        if not _match_rules_pass(tpl["matchRules"], context or {}):
            continue
        out.append(tpl)
    return out


def _thompson_score(
    template: dict[str, Any], *, rng: random.Random
) -> float:
    """Sample once from ``Beta(wins+1, uses-wins+1)`` for a template.

    Intentionally uses ``wins`` (confident-only) not ``replies`` (which
    includes ambiguous attributions) — see module docstring.
    """
    uses = max(0, int(template.get("uses") or 0))
    wins = max(0, int(template.get("wins") or 0))
    wins = min(wins, uses)
    alpha = wins + 1
    beta = uses - wins + 1
    return rng.betavariate(alpha, beta)


def pick_template(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    lane: str,
    channel: str,
    context: dict[str, Any] | None = None,
    ranker: Callable[
        [list[dict[str, Any]], dict[str, Any]], dict[str, Any] | None
    ] | None = None,
    now: datetime | None = None,
    seed: int | None = None,
) -> dict[str, Any] | None:
    """Pick one template for the realtor's next send.

    Returns the chosen template dict (with ``thompsonScores`` and
    ``pickRationale`` keys appended) or ``None`` when no template is
    eligible — caller falls back to a one-off draft (Sprint 5's pattern
    detector picks that up as a candidate).

    ``ranker`` (optional) is the AI hook: when provided, it receives the
    list of eligible templates (already enriched with Thompson scores)
    plus the context dict, and may return one. If it returns ``None``
    or raises, we fall back to the highest Thompson sample.

    ``seed`` makes the Thompson draw deterministic — used by tests.
    """
    eligible = eligible_templates(
        conn,
        contact_id=contact_id,
        lane=lane,
        channel=channel,
        context=context,
        now=now,
    )
    if not eligible:
        return None

    rng = random.Random(seed) if seed is not None else random.Random()
    scored: list[tuple[float, dict[str, Any]]] = []
    for tpl in eligible:
        score = _thompson_score(tpl, rng=rng)
        scored.append((score, tpl))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    thompson_scores = {tpl["id"]: round(score, 4) for score, tpl in scored}

    chosen: dict[str, Any] | None = None
    rationale = "thompson"
    if ranker is not None:
        try:
            ranker_pick = ranker(
                [tpl for _, tpl in scored],
                {**(context or {}), "thompsonScores": thompson_scores},
            )
            if ranker_pick is not None:
                # Trust the ranker only if it returned one of the
                # eligible templates — otherwise fall back to Thompson.
                eligible_ids = {tpl["id"] for tpl in eligible}
                if ranker_pick.get("id") in eligible_ids:
                    chosen = ranker_pick
                    rationale = "ai_override"
        except Exception:
            chosen = None

    if chosen is None:
        chosen = scored[0][1]

    enriched = dict(chosen)
    enriched["thompsonScores"] = thompson_scores
    enriched["pickRationale"] = rationale
    return enriched


__all__ = [
    "eligible_templates",
    "pick_template",
]
