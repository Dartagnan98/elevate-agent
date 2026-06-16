"""Shared I/O for the per-platform metric fetchers.

Every fetcher writes one JSONL line per (post, fetch) to:

    ~/.elevate/state/<workspace>/social-metrics.jsonl

Append-only — re-pulling the same post on a later day creates a NEW line, so
the aggregator can compute deltas (engagement decay, late-loading views, etc).

Each line has:
  {
    "platform": "instagram",
    "post_id": "<platform native id>",
    "fetched_at": "<iso>",
    "posted_at": "<iso>",
    "media_type": "REEL | IMAGE | CAROUSEL | VIDEO | SHORT | STORY | TEXT",
    "permalink": "<url or null>",
    "caption": "<truncated to 500 chars>",
    "metrics": { ...platform native payload, all numeric fields preserved... },
    "raw": { ...full Composio/API response for debug, only on first fetch... }
  }
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _workspace_dir() -> Path:
    """Resolve <ELEVATE_HOME>/state/<workspace_id>/. Creates dir if missing."""
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    workspace = (
        os.environ.get("ELEVATE_WORKSPACE_ID")
        or os.environ.get("ELEVATE_WORKSPACE")
        or "default"
    )
    out = elevate_home / "state" / workspace
    out.mkdir(parents=True, exist_ok=True)
    return out


def metrics_path() -> Path:
    return _workspace_dir() / "social-metrics.jsonl"


def runs_path() -> Path:
    return _workspace_dir() / "social-runs.jsonl"


def snapshot_path() -> Path:
    return _workspace_dir() / "social-snapshot.json"


def append_metric(
    *,
    platform: str,
    post_id: str,
    posted_at: Optional[str],
    media_type: str,
    permalink: Optional[str],
    caption: Optional[str],
    metrics: dict[str, Any],
    raw: Optional[dict[str, Any]] = None,
    include_raw: bool = False,
) -> None:
    """Append one metric row to social-metrics.jsonl."""
    row = {
        "platform": platform,
        "post_id": str(post_id),
        "fetched_at": _now_iso(),
        "posted_at": posted_at,
        "media_type": media_type or "UNKNOWN",
        "permalink": permalink,
        "caption": (caption or "")[:500] if caption else None,
        "metrics": metrics or {},
    }
    if include_raw and raw is not None:
        row["raw"] = raw
    with metrics_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_run_log(payload: dict[str, Any]) -> None:
    """Append one run-summary line to social-runs.jsonl."""
    payload = dict(payload)
    payload.setdefault("run_at", _now_iso())
    with runs_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    """Overwrite social-snapshot.json with the latest aggregator output."""
    snapshot = dict(snapshot)
    snapshot.setdefault("generated_at", _now_iso())
    out = snapshot_path()
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def has_post_been_seen(platform: str, post_id: str) -> bool:
    """Cheap check: was this post already fetched at least once?

    Used to decide whether to include the full `raw` payload (only on first
    fetch — keeps the JSONL from ballooning on re-pulls).
    """
    path = metrics_path()
    if not path.exists():
        return False
    needle = f'"platform": "{platform}", "post_id": "{post_id}"'
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if needle in line:
                    return True
    except OSError:
        return False
    return False


# A connected account must be in one of these states to actually execute a
# tool. EXPIRED / REVOKED / ERROR accounts still come back from the list call,
# but every execute against them returns HTTP 410/422 — so treating them as
# "connected" just produced cryptic tool errors. Resolve only usable accounts
# and report the dead state instead.
_USABLE_ACCOUNT_STATES = {"ACTIVE", "INITIATED", ""}


def _list_connected_accounts(toolkit_slug: str) -> Optional[list[dict[str, Any]]]:
    """Return the raw account items for a toolkit, or None if Composio itself is
    unavailable (import/env failure or API error — NOT 'no account')."""
    try:
        from elevate_cli import composio_client
    except Exception as exc:
        # An import failure here is an ENVIRONMENT problem (wrong interpreter —
        # see _bootstrap), never a missing connection. _bootstrap should prevent
        # ever reaching this branch.
        print(
            f"[social-content-engine] composio_client unavailable "
            f"({type(exc).__name__}: {exc}) under {sys.executable} — "
            f"environment issue, not a missing connection.",
            file=sys.stderr,
        )
        return None
    resp = composio_client.list_all_connected_accounts(toolkit=toolkit_slug, page_size=10, max_pages=1)
    if not resp.get("ok"):
        print(
            f"[social-content-engine] composio API error for {toolkit_slug!r}: "
            f"{resp.get('error')}",
            file=sys.stderr,
        )
        return None
    return [i for i in (((resp.get("data") or {}).get("items")) or []) if isinstance(i, dict)]


def resolve_connected_account(toolkit_slug: str) -> tuple[Optional[dict[str, Any]], str]:
    """Resolve a USABLE connected account and a precise status label.

    Returns ``(account, status)``:
      - ``(account, "ok")``                — an ACTIVE/INITIATED account exists.
      - ``(None, "not_configured")``       — no account connected at all.
      - ``(None, "connection_<state>")``   — an account exists but is EXPIRED /
        REVOKED / etc.; the realtor must RECONNECT it. (Surfaces as e.g.
        ``connection_expired`` instead of a raw HTTP 410.)
      - ``(None, "composio_unavailable")`` — Composio import/API failure.
    """
    items = _list_connected_accounts(toolkit_slug)
    if items is None:
        return None, "composio_unavailable"
    if not items:
        return None, "not_configured"
    for item in items:
        if (item.get("status") or "").upper() in _USABLE_ACCOUNT_STATES:
            return item, "ok"
    state = (items[0].get("status") or "unknown").strip().lower() or "unknown"
    print(
        f"[social-content-engine] {toolkit_slug} connection is {state.upper()} "
        f"(account {items[0].get('id')}) — reconnect this platform; the token is "
        f"no longer valid.",
        file=sys.stderr,
    )
    return None, f"connection_{state}"


def find_composio_account(toolkit_slug: str) -> Optional[dict[str, Any]]:
    """Look up the first USABLE connected Composio account for a toolkit slug,
    or None. Backward-compatible wrapper over :func:`resolve_connected_account`
    (which also returns the precise status for callers that want it)."""
    account, _status = resolve_connected_account(toolkit_slug)
    return account
