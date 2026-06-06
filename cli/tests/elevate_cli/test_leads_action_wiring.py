from __future__ import annotations

import json
from contextlib import contextmanager


def test_generated_thread_draft_uses_active_outreach_template(monkeypatch):
    from elevate_cli import outreach_db
    from elevate_cli import source_connectors as sc

    monkeypatch.setattr(
        outreach_db,
        "list_templates",
        lambda lane, include_inactive=False: [
            {
                "id": "tpl-1",
                "lane": lane,
                "name": "Warm intro",
                "body": "Hey {first_name}, saw you came through {source}. Want the short list for {area}?",
                "channel": "any",
                "active": True,
                "status": "active",
                "uses": 0,
                "replyRate": 0.0,
                "winRate": 0.0,
            }
        ],
    )

    draft = sc._draft_from_thread(
        {"id": "email", "label": "Gmail", "category": "messages"},
        {
            "sourceId": "email",
            "sourceLabel": "Gmail",
            "threadId": "thread-1",
            "personName": "Ava Buyer",
            "channel": "Email",
            "latestText": "Looking around Kits",
            "heatLabel": "warm",
            "outboundCount": 0,
            "record": {"area": "Kitsilano"},
        },
    )

    assert draft["draftText"] == "Hey Ava, saw you came through Gmail. Want the short list for Kitsilano?"
    assert draft["templateId"] == "tpl-1"
    assert draft["templateName"] == "Warm intro"
    assert draft["outreachLane"] == "new-outreach"
    assert draft["fallback"] is False
    assert draft["record"]["template_id"] == "tpl-1"


def test_thread_draft_state_persists_template_metadata_on_skip(tmp_path, monkeypatch):
    from elevate_cli import outreach_db
    from elevate_cli import source_connectors as sc

    source_root = tmp_path / "sources"
    source_dir = source_root / "email"
    source_dir.mkdir(parents=True)
    (source_dir / "source.json").write_text(
        json.dumps({"id": "email", "label": "Gmail", "category": "messages"}) + "\n",
        encoding="utf-8",
    )
    (source_dir / "conversations.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "thread-1",
                "display_name": "Ava Buyer",
                "direction": "inbound",
                "text": "Can you send Kits homes?",
                "area": "Kitsilano",
                "timestamp": "2026-05-26T10:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sc, "get_source_root_info", lambda config=None: {"sourceRoot": str(source_root)})
    monkeypatch.setattr(sc, "build_source_inbox_response", lambda config=None: {"ok": True})
    monkeypatch.setattr(
        outreach_db,
        "list_templates",
        lambda lane, include_inactive=False: [
            {
                "id": "tpl-1",
                "lane": lane,
                "name": "Area ask",
                "body": "Hey {first_name}, want the short list for {area}?",
                "channel": "any",
                "active": True,
                "status": "active",
                "uses": 0,
                "replyRate": 0.0,
                "winRate": 0.0,
            }
        ],
    )

    sc.update_source_task_state("email", "thread-draft:thread-1", "skip", config={})

    state = json.loads((source_dir / "ui-state.json").read_text(encoding="utf-8"))
    task = state["tasks"]["thread-draft:thread-1"]
    assert task["status"] == "skipped"
    assert task["template_id"] == "tpl-1"
    assert task["template_name"] == "Area ask"
    assert task["outreach_lane"] == "new-outreach"


def test_restore_source_task_removes_skipped_state(tmp_path, monkeypatch):
    from elevate_cli import source_connectors as sc

    source_root = tmp_path / "sources"
    source_dir = source_root / "email"
    source_dir.mkdir(parents=True)
    (source_dir / "ui-state.json").write_text(
        json.dumps({"tasks": {"task-1": {"status": "skipped"}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sc, "get_source_root_info", lambda config=None: {"sourceRoot": str(source_root)})
    monkeypatch.setattr(sc, "build_source_inbox_response", lambda config=None: {"ok": True})

    sc.update_source_task_state("email", "task-1", "restore", config={})

    state = json.loads((source_dir / "ui-state.json").read_text(encoding="utf-8"))
    assert "task-1" not in state["tasks"]


def test_update_profile_favorite_persists_flag(monkeypatch):
    from elevate_cli import source_connectors as sc
    from elevate_cli.data import connect

    monkeypatch.setattr(sc, "build_source_inbox_response", lambda config=None: {"ok": True})

    result = sc.update_profile_favorite(
        "thread:apple-messages:t-1",
        favorite=True,
        return_inbox=False,
    )

    assert result == {"ok": True}
    with connect() as conn:
        row = conn.execute(
            "SELECT favorite FROM lead_profile_flags WHERE profile_id=?",
            ("thread:apple-messages:t-1",),
        ).fetchone()
    assert row["favorite"] == 1


def test_approve_atomic_records_template_attempt_and_enqueue_payload(tmp_path, monkeypatch):
    from elevate_cli import outreach_db
    from elevate_cli import source_connectors as sc

    calls: dict[str, object] = {}

    @contextmanager
    def fake_connect():
        yield object()

    @contextmanager
    def fake_transaction(conn):
        yield conn

    def fake_record_use(conn, template_id, *, lane, source_id, thread_id, task_id):
        calls["record_use"] = {
            "template_id": template_id,
            "lane": lane,
            "source_id": source_id,
            "thread_id": thread_id,
            "task_id": task_id,
        }
        return "attempt-1"

    def fake_enqueue(conn, **kwargs):
        calls["enqueue"] = kwargs

    monkeypatch.setattr(outreach_db, "connect", fake_connect)
    monkeypatch.setattr(outreach_db, "transaction", fake_transaction)
    monkeypatch.setattr(outreach_db, "record_use_in_transaction", fake_record_use)
    monkeypatch.setattr(outreach_db, "enqueue_send", fake_enqueue)
    monkeypatch.setenv("ELEVATE_APPROVE_AUTO_TICK", "0")

    source_dir = tmp_path / "sources" / "email"
    source_dir.mkdir(parents=True)
    task_state = {
        "status": "approved",
        "draft_text": "Hey Ava, want the short list?",
        "template_id": "tpl-1",
        "template_name": "Area ask",
        "outreach_lane": "new-outreach",
    }
    state = {"tasks": {"thread-draft:thread-1": task_state}}

    sc._approve_atomic("email", "thread-draft:thread-1", task_state, source_dir, state)

    assert calls["record_use"] == {
        "template_id": "tpl-1",
        "lane": "new-outreach",
        "source_id": "email",
        "thread_id": "thread-1",
        "task_id": "thread-draft:thread-1",
    }
    enqueue = calls["enqueue"]
    assert isinstance(enqueue, dict)
    assert enqueue["attempt_id"] == "attempt-1"
    assert enqueue["payload"]["template_id"] == "tpl-1"
    assert enqueue["payload"]["attempt_id"] == "attempt-1"
