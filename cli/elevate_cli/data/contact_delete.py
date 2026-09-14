"""Contact deletion and dependent-row cleanup in the operational store."""

import json as _json
import logging

_log = logging.getLogger(__name__)


def delete_contact_data(conn, contact_id: str) -> dict[str, int]:
    """Delete a contact and its dependent records in one transaction."""
    deleted: dict[str, int] = {}

    def _sp(label: str, sql: str, params: tuple) -> None:
        # Run one cleanup statement inside a savepoint so a single
        # failure (missing table/column on some install) rolls back
        # just that statement instead of aborting the whole delete.
        conn.execute("SAVEPOINT sp_del")
        try:
            cur = conn.execute(sql, params)
            deleted[label] = getattr(cur, "rowcount", 0) or 0
            conn.execute("RELEASE SAVEPOINT sp_del")
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT sp_del")
            _log.debug("delete_contact: %s cleanup skipped", label, exc_info=True)

    # Blockers (FK NO ACTION) + FK-less tables -> clear first.
    # events_summary/contact_items/contact_top25 key on contact_id;
    # lead_signals references via graduated_to_contact_id (null it so
    # the lead-gen signal row survives, just unlinked).
    _sp("events_summary", "DELETE FROM events_summary WHERE contact_id=?", (contact_id,))
    _sp("contact_items", "DELETE FROM contact_items WHERE contact_id=?", (contact_id,))
    _sp("contact_top25", "DELETE FROM contact_top25 WHERE contact_id=?", (contact_id,))
    _sp("lead_signals", "UPDATE lead_signals SET graduated_to_contact_id=NULL WHERE graduated_to_contact_id=?", (contact_id,))
    # events.conversation_id -> conversations is a NO-ACTION FK
    # (fk_events_2), so cascading the contact delete into its
    # conversations is blocked while any event still points at them.
    # Clear those events first. (The contact's own events cascade via
    # fk_events_1 anyway; this also catches any cross-referenced ones.)
    _sp(
        "events_by_conversation",
        "DELETE FROM events WHERE conversation_id IN "
        "(SELECT id FROM conversations WHERE contact_id=?)",
        (contact_id,),
    )

    # send_queue has no contact_id column: match on payload's contact_id.
    try:
        sq = conn.execute(
            "SELECT id, payload_json FROM send_queue WHERE payload_json LIKE ?",
            (f'%{contact_id}%',),
        ).fetchall()
        sq_ids = []
        for r in sq:
            try:
                p = _json.loads(r["payload_json"] or "{}")
            except Exception:
                p = {}
            rec = p.get("recipient") if isinstance(p.get("recipient"), dict) else {}
            if p.get("contact_id") == contact_id or rec.get("contact_id") == contact_id:
                sq_ids.append(r["id"])
        for sid in sq_ids:
            conn.execute("DELETE FROM send_queue WHERE id=?", (sid,))
        deleted["send_queue"] = len(sq_ids)
    except Exception:
        _log.debug("delete_contact: send_queue cleanup skipped", exc_info=True)

    # The contact row itself. FK CASCADE removes conversations, notes,
    # identities, events, lead_inquiries/properties, deal_contacts,
    # pcs_*; deals.primary_contact_id / agent_handoffs are SET NULL.
    cur = conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    deleted["contacts"] = getattr(cur, "rowcount", 0) or 0
    conn.commit()

    return deleted
