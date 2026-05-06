"""Sprint 4 — two-tier reply attribution.

When an inbound lands, we want to know whether it's a reply to a
specific templated outbound (so the template's ``wins`` counter can
move) or whether the credit is ambiguous (so the leaderboard isn't
poisoned by cross-channel guesses).

Rules from ``docs/central-data-model-v1-plan.md`` §4.2:

* **Confident attribution** — exactly one outbound exists in the same
  conversation, on the same channel, within the last 30 days, and that
  outbound has a non-null ``template_id``. Fire ``reply_attributed``,
  bump ``wins`` (via ``record_template_reply(confident=True)``).
* **Ambiguous** — any other shape: zero outbounds (cold reply we have
  no record of), multiple outbounds (which template gets credit?),
  cross-channel (replied to email-template via SMS), or outbound has
  ``template_id IS NULL`` (one-off, no template to credit). Fire
  ``attribution_ambiguous`` listing every candidate template_id +
  reason; bump each candidate's ``replies`` (NOT ``wins``) so the
  ambiguous-stats surface still has signal without poisoning Thompson.

The caller — typically the ingest pipeline right after
``record_inbound`` — passes the just-recorded inbound row in. We do
the analysis and emit the right bookkeeping events; we do not modify
the inbound itself.

Public surface:

* :func:`attribute_inbound_reply`
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data import events as _events
from elevate_cli.data import templates as _templates


_ATTRIBUTION_WINDOW_DAYS = 30


def _to_dt(ts: str) -> datetime:
    """Parse the canonical ISO timestamp the data module emits."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _outbound_payload_template(row: sqlite3.Row) -> str | None:
    """Defensive read of ``template_id`` — the column is the
    authoritative source, but legacy backfilled rows may have stuffed
    it into the JSON payload instead."""
    if row["template_id"]:
        return row["template_id"]
    raw = row["payload_json"]
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict):
        return payload.get("templateId") or payload.get("template_id")
    return None


def _outbound_body(row: sqlite3.Row) -> str | None:
    """Pull the human-written body out of an outbound row's payload."""
    raw = row["payload_json"]
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict):
        body = payload.get("body")
        if isinstance(body, str) and body.strip():
            return body
    return None


_ONEOFF_DETECTOR_ACTOR = "agent:oneoff_detector"


def _seed_oneoff_candidate(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    outbound_row: sqlite3.Row,
    inbound_ts: str,
    channel: str,
) -> dict[str, Any] | None:
    """Promote a successful freehand outbound into a ``proposed`` template.

    Triggered by :func:`attribute_inbound_reply` when a confident reply
    lands on a same-channel outbound that had ``template_id IS NULL``.
    The realtor sees the candidate on ``/admin/templates`` Proposed tab
    and either approves (with whatever lane/name they want) or rejects.

    Idempotent on the outbound event id — re-running attribution on the
    same inbound won't double-propose. We index by ``proposed_by_event_id``
    so the check is a single keyed lookup.

    Returns the new proposed template dict, or ``None`` when no body
    was recoverable / a candidate already exists.
    """
    body = _outbound_body(outbound_row)
    if not body:
        return None

    parent_id = outbound_row["id"]
    existing = conn.execute(
        "SELECT id FROM templates WHERE proposed_by_event_id = ?",
        (parent_id,),
    ).fetchone()
    if existing is not None:
        return None

    short_ts = inbound_ts[:16] if inbound_ts else ""
    proposed = _templates.propose_template(
        conn,
        lane="new-outreach",
        name=f"Freehand candidate {parent_id[:8]}",
        body=body,
        channel=channel,
        origin="ai_oneoff",
        rationale=(
            "Freehand outbound got a confident reply on "
            f"{short_ts} — candidate for templating. Realtor reviews + "
            "assigns lane on /admin/templates."
        ),
        proposed_by_event_id=parent_id,
        actor=_ONEOFF_DETECTOR_ACTOR,
    )
    _events.record_template_event(
        conn,
        kind="template_candidate",
        contact_id=contact_id,
        template_id=proposed["id"],
        actor=_ONEOFF_DETECTOR_ACTOR,
        payload={
            "sourceOutboundId": parent_id,
            "channel": channel,
            "rationale": "freehand_one_off_got_reply",
        },
    )
    return proposed


def attribute_inbound_reply(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    channel: str,
    ts: str,
) -> dict[str, Any]:
    """Run reply-attribution for one inbound and emit bookkeeping.

    Returns a small dict describing what happened:

    * ``{"verdict": "confident", "templateId": <id>, "draftAttemptId": <id|None>}``
    * ``{"verdict": "ambiguous", "candidateTemplateIds": [...], "reason": "..."}``
    * ``{"verdict": "no_outbound", ...}`` — no prior outbound at all

    The ``no_outbound`` case still emits ``attribution_ambiguous`` with
    an empty candidate list so the audit log shows the inbound was
    looked at; reviewing those rows is how we catch contacts that
    replied to outreach we never logged.
    """
    cutoff_dt = _to_dt(ts) - timedelta(days=_ATTRIBUTION_WINDOW_DAYS)
    cutoff_iso = cutoff_dt.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "+00:00")

    rows = conn.execute(
        """
        SELECT id, channel, template_id, payload_json, ts
        FROM events
        WHERE conversation_id = ?
          AND kind = 'outbound'
          AND ts >= ?
          AND ts < ?
        ORDER BY ts DESC
        """,
        (conversation_id, cutoff_iso, ts),
    ).fetchall()

    same_channel = [r for r in rows if r["channel"] == channel]
    cross_channel = [r for r in rows if r["channel"] != channel]

    # No outbound on any channel — nothing to attribute.
    if not rows:
        verdict = {
            "verdict": "no_outbound",
            "candidateTemplateIds": [],
            "reason": "no_prior_outbound_in_window",
        }
        _events.record_attribution_ambiguous(
            conn,
            contact_id=contact_id,
            conversation_id=conversation_id,
            candidate_template_ids=[],
            reason=verdict["reason"],
            ts=ts,
        )
        return verdict

    # Cross-channel reply (e.g., outbound on email, reply on SMS).
    if not same_channel:
        candidates = [
            tid for r in cross_channel
            if (tid := _outbound_payload_template(r))
        ]
        verdict = {
            "verdict": "ambiguous",
            "candidateTemplateIds": list(dict.fromkeys(candidates)),
            "reason": "cross_channel_reply",
        }
        _events.record_attribution_ambiguous(
            conn,
            contact_id=contact_id,
            conversation_id=conversation_id,
            candidate_template_ids=verdict["candidateTemplateIds"],
            reason=verdict["reason"],
            ts=ts,
        )
        for tid in verdict["candidateTemplateIds"]:
            _templates.record_template_reply(conn, tid, confident=False)
        return verdict

    # Multiple outbounds on the same channel within the window —
    # which template gets credit? Mark ambiguous, list every distinct
    # template we saw on the channel.
    if len(same_channel) > 1:
        candidates = [
            tid for r in same_channel
            if (tid := _outbound_payload_template(r))
        ]
        candidates = list(dict.fromkeys(candidates))
        verdict = {
            "verdict": "ambiguous",
            "candidateTemplateIds": candidates,
            "reason": "multiple_outbounds_in_window",
        }
        _events.record_attribution_ambiguous(
            conn,
            contact_id=contact_id,
            conversation_id=conversation_id,
            candidate_template_ids=candidates,
            reason=verdict["reason"],
            ts=ts,
        )
        for tid in candidates:
            _templates.record_template_reply(conn, tid, confident=False)
        return verdict

    # Exactly one outbound on the same channel.
    only = same_channel[0]
    template_id = _outbound_payload_template(only)

    # One-off (no template) — reply is real, but nothing to credit on
    # the leaderboard. We still capture the freehand body as a proposed
    # template so the realtor can templatize on /admin/templates if it
    # looks reusable. (Sprint 5.1: one-off detector.)
    if template_id is None:
        candidate = _seed_oneoff_candidate(
            conn,
            contact_id=contact_id,
            outbound_row=only,
            inbound_ts=ts,
            channel=channel,
        )
        verdict: dict[str, Any] = {
            "verdict": "ambiguous",
            "candidateTemplateIds": [],
            "reason": "outbound_has_no_template_id",
        }
        if candidate is not None:
            verdict["seededCandidateId"] = candidate["id"]
        _events.record_attribution_ambiguous(
            conn,
            contact_id=contact_id,
            conversation_id=conversation_id,
            candidate_template_ids=[],
            reason=verdict["reason"],
            ts=ts,
        )
        return verdict

    # Pull draft_attempt_id from the outbound payload if it was stamped.
    draft_attempt_id: str | None = None
    if only["payload_json"]:
        try:
            p = json.loads(only["payload_json"])
            if isinstance(p, dict):
                draft_attempt_id = p.get("draftAttemptId")
        except (json.JSONDecodeError, TypeError):
            pass

    _events.record_reply_attributed(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        template_id=template_id,
        draft_attempt_id=draft_attempt_id or "",
        ts=ts,
    )
    _templates.record_template_reply(conn, template_id, confident=True)
    return {
        "verdict": "confident",
        "templateId": template_id,
        "draftAttemptId": draft_attempt_id,
    }


__all__ = ["attribute_inbound_reply"]
