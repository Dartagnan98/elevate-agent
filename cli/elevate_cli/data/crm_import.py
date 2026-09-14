"""Idempotent local projections of remote CRM records; never queues CRM writes."""
import json

from elevate_cli.data._util import decode_payload, encode_payload, new_id, now_iso, sha256


def import_crm_record(conn, *, contact_id, source_id, row, ts):
    kind = "note" if row["type"] == "crm_note" else "lifecycle_change"
    remote_key = str(row["source_record_id"])
    event_hash = sha256(json.dumps(["crm-record-v1", source_id, row["contact_id"], row["type"], remote_key]))
    payload = {
        "legacyType": row["type"], "sourceRecordId": remote_key,
        "title": row.get("title"), "summary": row.get("summary"),
        "body": row.get("body") or row.get("summary"),
        "author": row.get("author"), "status": row.get("status"),
        "dueAt": row.get("dueAt"), "subtype": row.get("subtype"),
        "address": row.get("address"), "assignedUser": row.get("assignedUser"),
        "providerRecord": row.get("provider_record"),
    }
    pj, pref = encode_payload(payload)
    existing = conn.execute("SELECT id FROM events WHERE event_hash=?", (event_hash,)).fetchone()
    if not existing:
        # Adopt one matching pre-fix event. Comparing content (not just type and
        # timestamp) preserves distinct notes created during the same second.
        candidates = conn.execute(
            "SELECT id,payload_json,payload_ref FROM events "
            "WHERE contact_id=? AND source_id=? AND kind=? AND ts=?",
            (contact_id, source_id, kind, ts),
        ).fetchall()
        for candidate in candidates:
            old = decode_payload(candidate["payload_json"], candidate["payload_ref"])
            if (isinstance(old, dict) and not old.get("sourceRecordId")
                    and old.get("legacyType") == row["type"]
                    and old.get("summary") == row.get("summary")
                    and old.get("title") == row.get("title")):
                existing = candidate
                conn.execute("UPDATE events SET event_hash=? WHERE id=?", (event_hash, candidate["id"]))
                break
    event_id = existing["id"] if existing else new_id()
    conn.execute(
        "INSERT INTO events(id,contact_id,kind,source_id,actor,payload_json,payload_ref,event_hash,ts) "
        "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(event_hash) DO UPDATE SET "
        "payload_json=excluded.payload_json,payload_ref=excluded.payload_ref,ts=excluded.ts "
        "WHERE events.payload_json IS DISTINCT FROM excluded.payload_json "
        "OR events.payload_ref IS DISTINCT FROM excluded.payload_ref OR events.ts IS DISTINCT FROM excluded.ts",
        (event_id, contact_id, kind, source_id, "lofty:import", pj, pref, event_hash, ts),
    )
    # In a concurrent insert the winning row may have a different local UUID.
    event_id = conn.execute("SELECT id FROM events WHERE event_hash=?", (event_hash,)).fetchone()["id"]
    if row["type"] == "crm_note":
        body = str(row.get("body") or row.get("summary") or "").strip()
        remote_id = str(row.get("remote_id") or remote_key.rsplit(":note:", 1)[-1])
        if body:
            stamp = now_iso()
            conn.execute(
                "INSERT INTO notes(id,contact_id,body,author_kind,author_name,source_event_id,"
                "pinned,deleted,crm_provider,crm_remote_id,crm_sync_state,crm_synced_at,"
                "crm_attempt_count,created_at,updated_at) VALUES (?,?,?,'system',?,?,0,?,'lofty',?,'synced',?,0,?,?) "
                "ON CONFLICT(crm_provider,crm_remote_id) WHERE crm_remote_id IS NOT NULL DO UPDATE SET "
                "body=excluded.body,author_name=excluded.author_name,source_event_id=excluded.source_event_id,"
                "deleted=excluded.deleted,crm_synced_at=excluded.crm_synced_at,updated_at=excluded.updated_at "
                "WHERE notes.crm_sync_state IS DISTINCT FROM 'pending' AND notes.crm_sync_state IS DISTINCT FROM 'failed'",
                (new_id(), contact_id, body, str(row.get("author") or "Lofty"), event_id,
                 int(bool(row.get("deleted"))), remote_id, stamp, ts, ts),
            )
    return existing is None
