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
        "label": "Meta Lead Ads",
        "description": "Facebook/Instagram lead-form ads. Forms land directly in Elevate via webhook.",
        "required": False,
        "sort_order": 20,
    },
    {
        "key": "google_lead_forms",
        "category": "lead_source",
        "label": "Google Lead Form Ads",
        "description": "Paid-search lead-form extensions piped into the inbound queue.",
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
        "sort_order": 50,
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
    except sqlite3.OperationalError:
        provider = ""
    try:
        item_row = conn.execute(
            "SELECT status FROM admin_setup_items WHERE key='crm'"
        ).fetchone()
        admin_status = (item_row["status"] or "missing") if item_row else "missing"
    except sqlite3.OperationalError:
        admin_status = "missing"
    if provider and admin_status in READY_STATUSES:
        return provider, "connected"
    return (provider or None), "missing"


def _item_counts_ready(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or "")
    return status in READY_STATUSES


def _snapshot(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> dict[str, Any]:
    crm_provider, crm_status = _resolve_crm_from_admin(conn)
    for item in items:
        if item["key"] == "crm":
            item["provider"] = crm_provider
            item["status"] = crm_status

    by_key = {it["key"]: it for it in items}
    lead_source_keys = ("meta_lead_ads", "google_lead_forms", "website_form_webhook")
    any_lead_source_ready = any(
        by_key.get(k) and _item_counts_ready(by_key[k]) for k in lead_source_keys
    )

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
    completed_count = len(complete_required) + (1 if any_lead_source_ready else 0)
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
    }


def get_leads_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    _ensure_seeded(conn)
    rows = conn.execute(
        "SELECT * FROM leads_setup_items ORDER BY sort_order ASC, key ASC"
    ).fetchall()
    items = [_row_to_item(row) for row in rows]
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
