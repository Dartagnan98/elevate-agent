import json

from elevate_cli.data import connect, list_notes_for_contact
from .test_crm_snapshot_replay import crm, replay, snapshot


def note(**kw):
    return snapshot(type="crm_note", source_record_id="lofty-lead:1:note:123",
                    body="Needs a fenced yard. Call Friday.",
                    author="Agent Example", **kw)


def test_imported_note_is_visible_in_contact_notes_without_outbound_push(crm):
    replay(crm, [note()])
    with connect() as conn:
        cid = conn.execute("SELECT id FROM contacts WHERE display_name='Test 1'").fetchone()[0]
        rows = list_notes_for_contact(conn, cid)
        assert len(rows) == 1
        assert rows[0]["body"] == "Needs a fenced yard. Call Friday."
        assert rows[0]["authorName"] == "Agent Example"
        assert rows[0]["crmSyncState"] == "synced"
        assert rows[0]["crmRemoteId"] == "123"
    assert replay(crm, [note()]) == 0


def test_edited_note_updates_in_place_and_same_second_notes_stay_distinct(crm):
    replay(crm, [note()])
    changed = note()
    changed["body"] = "Call Monday instead."
    assert replay(crm, [changed]) == 0
    other = note()
    other["source_record_id"] = "lofty-lead:1:note:456"
    assert replay(crm, [changed, other]) == 1
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 2
        assert conn.execute("SELECT body FROM notes WHERE crm_remote_id='123'").fetchone()[0] == changed["body"]
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_task_keeps_due_date_status_and_activity_metadata(crm):
    task = snapshot(type="crm_task", source_record_id="lofty-lead:1:task:1",
                    dueAt="2026-09-12T19:00:00+00:00", status="completed", assignedUser="Agent")
    replay(crm, [task])
    with connect() as conn:
        payload = json.loads(conn.execute("SELECT payload_json FROM events").fetchone()[0])
    assert payload["dueAt"] == task["dueAt"]
    assert payload["status"] == "completed"
    assert payload["assignedUser"] == "Agent"


def test_legacy_event_is_adopted_and_local_pending_note_is_preserved(crm):
    legacy = note()
    legacy.pop("source_record_id")
    replay(crm, [legacy])
    assert replay(crm, [note()]) == 0
    with connect() as conn:
        conn.execute("UPDATE notes SET body='Local edit awaiting sync',crm_sync_state='pending'")
    replay(crm, [note()])
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "Local edit awaiting sync"
