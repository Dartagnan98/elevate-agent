"""Leads onboarding gate.

Mirrors the admin_setup pattern (per-item key/status/provider/value table +
required-keys completion check) but scoped to inbound lead capture:

- ``crm``  — read-only mirror of ``admin_setup_profile.crm_provider``. We
  don't store it here; the snapshot stitches it in so the agent sees a
  single source of truth.
- ``meta_lead_ads``, ``google_lead_forms``, ``website_form_webhook`` —
  inbound lead sources. At least one must be ``connected``/``configured``
  for the gate to lift (enforced by the ``lead_sources_quorum`` synthetic
  check).
- Outreach channels (Apple Messages, SMS Provider, Android Device SMS,
  RCS) are NOT stored here. They live as canonical Source Connectors
  under ``data/sources/<id>`` and are surfaced read-only inside the
  snapshot as ``outreachConnectors`` so the leads UI can render status +
  deep-link to ``/config#connectors``. ``outreach_quorum`` is satisfied
  by ANY of: a connected CRM (Lofty / GHL / kvCore / BoldTrail all have
  built-in messaging) OR any connected outreach source connector.
- ``auto_reply_policy`` — initial-touch behaviour (enabled flag + template +
  follow-up cadence days).

Kept deliberately lighter than admin_setup: no playbook seeding, no
verification ping requirement, no separate profile table. The realtor's
identity/province/brokerage all live in admin_setup_profile already.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping

from elevate_cli.data._util import now_iso


STATE_ID = "default"
READY_STATUSES = {"configured", "connected", "manual"}
VALID_STATUSES = READY_STATUSES | {"missing", "skipped"}


_DEFAULT_ITEMS: list[dict[str, Any]] = [
    {
        "key": "crm",
        "category": "crm",
        "label": "CRM connection",
        "description": "Inherited from Admin setup. Where leads are written and threads pulled from.",
        "required": True,
        "sort_order": 10,
    },
    {
        "key": "meta_lead_ads",
        "category": "lead_source",
        "label": "Meta Lead Ads (optional)",
        "description": "Facebook/Instagram lead-form ads. Skip if you don't run them — your CRM and website webhook cover the basics. Auth via the Meta Ads MCP (recommended) or page-token webhook.",
        "required": False,
        "sort_order": 20,
    },
    {
        "key": "google_lead_forms",
        "category": "lead_source",
        "label": "Google Lead Form Ads (optional)",
        "description": "Paid-search lead-form extensions. Skip if you don't run them. Just paste a Google Ads developer token — Elevate's CLI auto-discovers the customer ID and campaign IDs.",
        "required": False,
        "sort_order": 30,
    },
    {
        "key": "website_form_webhook",
        "category": "lead_source",
        "label": "Website form webhook",
        "description": "Catch-all webhook URL for landing-page and website contact forms.",
        "required": False,
        "sort_order": 40,
    },
    {
        "key": "auto_reply_policy",
        "category": "policy",
        "label": "Auto-reply policy",
        "description": "Whether Elevate sends an initial touch, and the follow-up cadence default.",
        "required": True,
        "sort_order": 90,
    },
]


def _ensure_seeded(conn: sqlite3.Connection) -> None:
    """Seed default items + state row exactly once."""
    now = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO leads_setup_state(id, created_at, updated_at) VALUES (?, ?, ?)",
        (STATE_ID, now, now),
    )
    for item in _DEFAULT_ITEMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO leads_setup_items
                (key, category, label, description, required, status, provider, value_json, notes, sort_order, updated_at)
            VALUES (?, ?, ?, ?, ?, 'missing', NULL, NULL, NULL, ?, ?)
            """,
            (
                item["key"],
                item["category"],
                item["label"],
                item.get("description"),
                1 if item["required"] else 0,
                item["sort_order"],
                now,
            ),
        )


def _encode_json(value: Any) -> str | None:
    import json
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _decode_json(value: str | None) -> Any:
    import json
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "required": bool(row["required"]),
        "status": row["status"],
        "provider": row["provider"],
        "value": _decode_json(row["value_json"]),
        "notes": row["notes"],
        "sortOrder": row["sort_order"],
        "updatedAt": row["updated_at"],
    }


def _resolve_crm_from_admin(conn: sqlite3.Connection) -> tuple[str | None, str]:
    """Pull crm provider + connection status from admin_setup.

    Returns ``(provider, status)``. Status is ``connected`` when admin's CRM
    item is in READY_STATUSES, else ``missing``. This is the source of truth
    for the leads gate; the leads_setup_items row for ``crm`` is just a
    mirror so the UI can render it in the same list as other items.
    """
    try:
        row = conn.execute(
            "SELECT crm_provider FROM admin_setup_profile WHERE id='default'"
        ).fetchone()
        provider = (row["crm_provider"] or "").strip() if row else ""
    except Exception:
        provider = ""
    try:
        item_row = conn.execute(
            "SELECT status FROM admin_setup_items WHERE key='crm'"
        ).fetchone()
        admin_status = (item_row["status"] or "missing") if item_row else "missing"
    except Exception:
        admin_status = "missing"
    if provider and admin_status in READY_STATUSES:
        return provider, "connected"
    return (provider or None), "missing"


def _item_counts_ready(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or "")
    return status in READY_STATUSES


OUTREACH_CONNECTOR_IDS: tuple[str, ...] = (
    "apple-messages",
    "sms-provider",
    "android-device",
    "rcs",
)


def _outreach_connectors_snapshot() -> list[dict[str, Any]]:
    """Read live state of the four outreach Source Connectors.

    Source Connectors are the canonical config surface (lives at
    ``data/sources/<id>``). The leads gate mirrors their state read-only
    so the UI can show status and deep-link to ``/config#connectors``
    instead of duplicating the configuration form.
    """
    try:
        # Local import to avoid pulling source_connectors at module import time
        # (it imports load_config which touches the filesystem).
        from elevate_cli.source_connectors import build_source_connectors_response
    except Exception:
        return []
    try:
        resp = build_source_connectors_response(include_prompts=False)
    except Exception:
        return []
    connectors = resp.get("connectors") if isinstance(resp, dict) else None
    if not isinstance(connectors, list):
        return []
    out: list[dict[str, Any]] = []
    for conn_view in connectors:
        if not isinstance(conn_view, dict):
            continue
        cid = str(conn_view.get("id") or "").strip()
        if cid not in OUTREACH_CONNECTOR_IDS:
            continue
        record_counts = conn_view.get("recordCounts") if isinstance(conn_view.get("recordCounts"), dict) else {}
        total_records = sum(int(v or 0) for v in record_counts.values() if isinstance(v, (int, float)))
        out.append({
            "id": cid,
            "label": conn_view.get("label") or cid,
            "state": conn_view.get("state") or "not_configured",
            "connected": bool(conn_view.get("connected") or conn_view.get("state") == "connected"),
            "importOnly": bool(conn_view.get("importOnly")),
            "blocked": bool(conn_view.get("blocked")),
            "nextOperatorStep": conn_view.get("nextOperatorStep"),
            "lastError": conn_view.get("lastError"),
            "ownerAgent": conn_view.get("ownerAgent") or "Outreach",
            "totalRecords": total_records,
        })
    # Stable ordering matching OUTREACH_CONNECTOR_IDS
    order = {cid: idx for idx, cid in enumerate(OUTREACH_CONNECTOR_IDS)}
    out.sort(key=lambda c: order.get(c["id"], 99))
    return out


def _snapshot(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> dict[str, Any]:
    crm_provider, crm_status = _resolve_crm_from_admin(conn)
    for item in items:
        if item["key"] == "crm":
            item["provider"] = crm_provider
            item["status"] = crm_status

    by_key = {it["key"]: it for it in items}
    # The CRM is itself a lead source AND an outreach lane — Lofty / FUB /
    # kvCore / BoldTrail / GHL all sync leads natively (from Meta/Google/
    # website forms) and have built-in messaging. If CRM is connected, that
    # alone satisfies the lead-source quorum; the dedicated Meta/Google/
    # webhook connectors are optional add-ons.
    crm_ready = bool(by_key.get("crm") and _item_counts_ready(by_key["crm"]))
    lead_source_keys = ("meta_lead_ads", "google_lead_forms", "website_form_webhook")
    any_direct_lead_source_ready = any(
        by_key.get(k) and _item_counts_ready(by_key[k]) for k in lead_source_keys
    )
    any_lead_source_ready = crm_ready or any_direct_lead_source_ready
    outreach_connectors = _outreach_connectors_snapshot()
    any_direct_outreach_ready = any(
        c.get("connected") or c.get("importOnly") for c in outreach_connectors
    )
    # Surfaced read-only for UI display; not part of the gate.
    any_outreach_ready = crm_ready or any_direct_outreach_ready

    required = [item for item in items if item["required"]]
    complete_required = [item for item in required if _item_counts_ready(item)]
    missing = [item for item in required if not _item_counts_ready(item)]
    missing_keys = [item["key"] for item in missing]
    if not any_lead_source_ready:
        missing_keys.append("lead_sources_quorum")

    state_row = conn.execute(
        "SELECT * FROM leads_setup_state WHERE id=?", (STATE_ID,)
    ).fetchone()
    completed_at = state_row["completed_at"] if state_row else None

    required_count = len(required) + 1
    completed_count = (
        len(complete_required)
        + (1 if any_lead_source_ready else 0)
    )
    complete = completed_count == required_count

    return {
        "items": items,
        "requiredCount": required_count,
        "completedRequiredCount": completed_count,
        "missingRequiredKeys": missing_keys,
        "completionPct": round((completed_count / required_count) * 100) if required_count else 100,
        "complete": complete,
        "completedAt": completed_at,
        "launchRequired": not complete,
        "leadSourcesReady": any_lead_source_ready,
        "outreachReady": any_outreach_ready,
        "outreachConnectors": outreach_connectors,
    }


_DEPRECATED_KEYS = frozenset({"outreach_imessage", "outreach_sms", "outreach_rcs"})


def get_leads_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    _ensure_seeded(conn)
    rows = conn.execute(
        "SELECT * FROM leads_setup_items ORDER BY sort_order ASC, key ASC"
    ).fetchall()
    items = [_row_to_item(row) for row in rows if row["key"] not in _DEPRECATED_KEYS]
    return _snapshot(conn, items)


def update_leads_setup(
    conn: sqlite3.Connection,
    *,
    items: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    _ensure_seeded(conn)
    now = now_iso()
    if items:
        for item in items:
            key = str(item.get("key") or "").strip()
            if not key:
                raise ValueError("leads setup item key is required")
            if key == "crm":
                # CRM is a mirror — do not write here; admin_setup owns it.
                continue
            if key in _DEPRECATED_KEYS:
                # Outreach channels moved to Source Connectors. Silently
                # ignore any stale UI writes targeting the legacy keys.
                continue
            row = conn.execute(
                "SELECT key FROM leads_setup_items WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                raise LookupError(f"leads setup item {key!r} not found")
            status = str(item.get("status") or "missing").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid leads setup status {status!r}")
            conn.execute(
                """
                UPDATE leads_setup_items
                SET status=?, provider=?, value_json=?, notes=?, updated_at=?
                WHERE key=?
                """,
                (
                    status,
                    _clean_text(item.get("provider")),
                    _encode_json(item.get("value")),
                    _clean_text(item.get("notes")),
                    now,
                    key,
                ),
            )
    conn.execute(
        "UPDATE leads_setup_state SET updated_at=? WHERE id=?",
        (now, STATE_ID),
    )
    return get_leads_setup(conn)


def complete_leads_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    """Mark the gate as complete if all required items are ready.

    Raises ``ValueError`` if there are still missing required keys — the
    caller should surface that as a 409 rather than silently mark green.
    """
    snapshot = get_leads_setup(conn)
    if not snapshot["complete"]:
        raise ValueError(
            "Leads setup is not complete. Missing: "
            + ", ".join(snapshot["missingRequiredKeys"])
        )
    now = now_iso()
    conn.execute(
        "UPDATE leads_setup_state SET completed_at=?, updated_at=? WHERE id=?",
        (now, now, STATE_ID),
    )
    return get_leads_setup(conn)


def reset_leads_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    """Re-open the gate without wiping item state. Used by 'Re-run onboarding'."""
    _ensure_seeded(conn)
    now = now_iso()
    conn.execute(
        "UPDATE leads_setup_state SET completed_at=NULL, updated_at=? WHERE id=?",
        (now, STATE_ID),
    )
    return get_leads_setup(conn)
