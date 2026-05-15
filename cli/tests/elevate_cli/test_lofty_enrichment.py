"""Lofty enrichment helpers + thread-context split tests.

Covers the helpers added to ``source_connectors.py`` so a Lofty lead's
activity feed, notes, and tasks land in ``lead-events.jsonl`` and split
cleanly inside ``build_thread_context_response``.

Hermetic: every test mocks ``_lofty_get`` and writes/reads fixture
JSONL inside a tmp source root — no live network and no real
``~/.elevate``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from elevate_cli import source_connectors as sc


# ── _lofty_extract_list ───────────────────────────────────────────────


class TestExtractList:
    def test_bare_list_passes_through(self):
        rows = [{"id": 1}, {"id": 2}]
        assert sc._lofty_extract_list(rows) == rows

    def test_drops_non_dict_entries(self):
        assert sc._lofty_extract_list([{"a": 1}, "junk", None, 3]) == [{"a": 1}]

    def test_unwraps_data_key(self):
        payload = {"data": [{"id": "x"}]}
        assert sc._lofty_extract_list(payload) == [{"id": "x"}]

    def test_unwraps_records_key(self):
        payload = {"records": [{"id": "y"}]}
        assert sc._lofty_extract_list(payload) == [{"id": "y"}]

    def test_unwraps_nested_data_records(self):
        payload = {"data": {"records": [{"id": "z"}]}}
        assert sc._lofty_extract_list(payload) == [{"id": "z"}]

    def test_unwraps_activities_key(self):
        payload = {"activities": [{"id": "a"}]}
        assert sc._lofty_extract_list(payload) == [{"id": "a"}]

    def test_returns_empty_for_unknown_shape(self):
        assert sc._lofty_extract_list({"foo": "bar"}) == []
        assert sc._lofty_extract_list(None) == []
        assert sc._lofty_extract_list("string") == []


# ── _lofty_get_first_ok ───────────────────────────────────────────────


class TestGetFirstOk:
    def test_returns_first_non_empty_payload(self, monkeypatch):
        calls: list[str] = []

        def fake_get(path: str, env: dict, params: dict | None = None, **_kwargs) -> Any:
            calls.append(path)
            if path == "v2.0/leads/abc/activities":
                return {"data": [{"id": "1"}]}
            return {}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_first_ok(
            ("v2.0/leads/abc/activities", "v1.0/leads/abc/activities"),
            {"LOFTY_API_KEY": "x"},
            {"limit": 50},
        )
        assert rows == [{"id": "1"}]
        # Should stop on first hit.
        assert calls == ["v2.0/leads/abc/activities"]

    def test_falls_through_404_to_next(self, monkeypatch):
        calls: list[str] = []

        def fake_get(path: str, env: dict, params: dict | None = None, **_kwargs) -> Any:
            calls.append(path)
            if path == "v2.0/leads/abc/activities":
                raise Exception("404 Not Found")
            return {"data": [{"id": "fallback"}]}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_first_ok(
            ("v2.0/leads/abc/activities", "v1.0/leads/abc/activities"),
            {"LOFTY_API_KEY": "x"},
        )
        assert rows == [{"id": "fallback"}]
        assert calls == [
            "v2.0/leads/abc/activities",
            "v1.0/leads/abc/activities",
        ]

    def test_raises_when_every_path_fails(self, monkeypatch):
        """Codex audit P1 (2026-05-05): all-paths-error must surface so
        callers can count it as a real enrichment failure instead of
        silently returning [] like a clean empty lead."""

        def fake_get(*_args, **_kwargs):
            raise Exception("boom")

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        try:
            sc._lofty_get_first_ok(("a", "b"), {"LOFTY_API_KEY": "x"})
        except Exception as exc:
            assert "boom" in str(exc)
        else:
            raise AssertionError("expected _lofty_get_first_ok to raise")

    def test_returns_empty_when_payloads_empty(self, monkeypatch):
        def fake_get(*_args, **_kwargs):
            return {}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_first_ok(("p1", "p2"), {})
        assert rows == []


# ── public helpers ─────────────────────────────────────────────────────


class TestPublicHelpers:
    def test_get_activities_blank_lead_returns_empty(self):
        assert sc._lofty_get_activities("", {}) == []

    def test_get_notes_blank_lead_returns_empty(self):
        assert sc._lofty_get_notes("", {}) == []

    def test_get_tasks_blank_lead_returns_empty(self):
        assert sc._lofty_get_tasks("", {}) == []

    def test_get_activities_threads_lead_id_into_path(self, monkeypatch):
        captured: dict[str, str] = {}

        def fake_get(path: str, env: dict, params: dict | None = None, **_kwargs) -> Any:
            captured["path"] = path
            return {"data": [{"id": "act1", "type": "page_view"}]}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_activities("lead-42", {"LOFTY_API_KEY": "x"})
        assert rows == [{"id": "act1", "type": "page_view"}]
        assert "lead-42/activities" in captured["path"]

    def test_get_notes_threads_lead_id_into_query(self, monkeypatch):
        captured: dict[str, str] = {}

        def fake_get(path: str, env: dict, params: dict | None = None, **_kwargs) -> Any:
            captured["path"] = path
            return {"notes": [{"id": "n1", "content": "hi"}]}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_notes("lead-7", {"LOFTY_API_KEY": "x"})
        assert rows == [{"id": "n1", "content": "hi"}]
        # Real Lofty shape is GET /v1.0/notes?leadId=<id>, not a path param.
        assert "leadId=lead-7" in captured["path"]
        assert captured["path"].startswith("v1.0/notes")

    def test_get_tasks_threads_lead_id_into_query(self, monkeypatch):
        captured: dict[str, str] = {}

        def fake_get(path: str, env: dict, params: dict | None = None, **_kwargs) -> Any:
            captured["path"] = path
            return {"taskList": [{"id": "t1", "subject": "Call"}]}

        monkeypatch.setattr(sc, "_lofty_get", fake_get)
        rows = sc._lofty_get_tasks("lead-9", {"LOFTY_API_KEY": "x"})
        assert rows == [{"id": "t1", "subject": "Call"}]
        assert "leadId=lead-9" in captured["path"]
        assert captured["path"].startswith("v1.0/tasks")


# ── normalizers ───────────────────────────────────────────────────────


class TestEpochMsToIso:
    def test_ms_epoch_int_converts(self):
        # 1775072765444 ms = 2026-...
        out = sc._lofty_epoch_ms_to_iso(1775072765444)
        assert out is not None
        assert out.startswith("2026-")
        assert "+00:00" in out

    def test_seconds_epoch_int_converts(self):
        # 1775072765 (seconds) — under the 1e11 threshold
        out = sc._lofty_epoch_ms_to_iso(1775072765)
        assert out is not None
        assert out.startswith("2026-")

    def test_gmt_suffix_replaced_with_offset(self):
        out = sc._lofty_epoch_ms_to_iso("2026-05-06T03:41:02GMT")
        assert out == "2026-05-06T03:41:02+00:00"

    def test_iso_passthrough(self):
        out = sc._lofty_epoch_ms_to_iso("2026-05-06T03:41:02Z")
        assert out == "2026-05-06T03:41:02Z"

    def test_none_in_none_out(self):
        assert sc._lofty_epoch_ms_to_iso(None) is None
        assert sc._lofty_epoch_ms_to_iso("") is None


class TestListingAddress:
    def test_combines_street_city_state(self):
        out = sc._lofty_listing_address(
            {"streetAddress": "123 Main St", "city": "Vernon", "state": "BC"}
        )
        assert out == "123 Main St, Vernon, BC"

    def test_handles_missing_pieces(self):
        out = sc._lofty_listing_address({"streetAddress": "123 Main St"})
        assert out == "123 Main St"

    def test_returns_none_for_non_dict(self):
        assert sc._lofty_listing_address(None) is None
        assert sc._lofty_listing_address("string") is None
        assert sc._lofty_listing_address({}) is None


class TestNormalizeActivity:
    def test_picks_id_from_first_available_field(self):
        norm = sc._lofty_normalize_activity({"id": "x", "type": "view"}, "lead-1")
        assert norm["id"] == "x"
        assert norm["lead_id"] == "lead-1"
        assert norm["subtype"] == "view"

    def test_falls_back_to_activity_id_then_event_id(self):
        norm = sc._lofty_normalize_activity(
            {"activityId": "a", "eventType": "saved-search"}, "lead-1"
        )
        assert norm["id"] == "a"
        assert norm["subtype"] == "saved-search"

    def test_address_appended_to_summary(self):
        norm = sc._lofty_normalize_activity(
            {
                "type": "property_view",
                "description": "Viewed listing",
                "propertyAddress": "123 Main St",
            },
            "lead-1",
        )
        assert "123 Main St" in norm["summary"]
        assert norm["address"] == "123 Main St"

    def test_address_unwraps_property_dict(self):
        norm = sc._lofty_normalize_activity(
            {"type": "view", "property": {"address": "456 Oak Ave"}},
            "lead-1",
        )
        assert norm["address"] == "456 Oak Ave"

    def test_picks_timestamp_from_alternatives(self):
        norm = sc._lofty_normalize_activity(
            {"type": "view", "ts": "2026-05-05T10:00:00Z"}, "lead-1"
        )
        assert norm["timestamp"] == "2026-05-05T10:00:00Z"

    def test_default_subtype_when_unknown(self):
        norm = sc._lofty_normalize_activity({"description": "thing"}, "lead-1")
        assert norm["subtype"] == "activity"

    def test_communication_text_outbound_uses_channel_for_title(self):
        norm = sc._lofty_normalize_activity(
            {
                "id": 1130947977875574784,
                "leadId": 1142409008547568,
                "channel": "Text",
                "communicationType": "Auto",
                "direction": "Outbound",
                "activityTime": "2025-09-24T14:50:19-07:00",
            },
            "1142409008547568",
        )
        assert norm["title"] == "Auto Text Outbound"
        assert norm["subtype"] == "text"
        assert norm["timestamp"] == "2025-09-24T14:50:19-07:00"

    def test_communication_email_with_subject(self):
        norm = sc._lofty_normalize_activity(
            {
                "id": 1,
                "channel": "Email",
                "communicationType": "Manual",
                "direction": "Inbound",
                "emailSubject": "Re: 4221 Wellington Drive",
                "activityTime": "2025-10-01T09:00:00-07:00",
            },
            "lead-1",
        )
        assert "Email" in norm["title"]
        assert "Inbound" in norm["title"]
        assert "Re: 4221 Wellington Drive" in norm["title"]

    def test_communication_call_with_outcome(self):
        norm = sc._lofty_normalize_activity(
            {
                "id": 1,
                "channel": "Call",
                "communicationType": "Manual",
                "direction": "Outbound",
                "callingOutcome": "connected",
                "activityTime": "2025-10-01T09:00:00-07:00",
            },
            "lead-1",
        )
        assert "Call" in norm["title"]
        assert "connected" in norm["title"]


class TestNormalizeNote:
    def test_pulls_body_from_content(self):
        norm = sc._lofty_normalize_note(
            {"id": "n1", "content": "Buyer cold-feet, called dad."},
            "lead-1",
        )
        assert norm["id"] == "n1"
        assert norm["summary"] == "Buyer cold-feet, called dad."

    def test_falls_back_to_body_then_text(self):
        norm = sc._lofty_normalize_note({"text": "raw text"}, "lead-1")
        assert norm["summary"] == "raw text"

    def test_truncates_long_titles(self):
        long = "a" * 200
        norm = sc._lofty_normalize_note({"content": long}, "lead-1")
        # 80 + ellipsis
        assert norm["title"].endswith("…")
        assert len(norm["title"]) == 81

    def test_picks_author_alternatives(self):
        for key in ("authorName", "author", "createdBy", "userName"):
            norm = sc._lofty_normalize_note(
                {"content": "x", key: "Demo Agent"}, "lead-1"
            )
            assert norm["author"] == "Demo Agent", key


class TestNormalizeTask:
    def test_default_status_when_completed_flag_present(self):
        norm = sc._lofty_normalize_task({"completed": True}, "lead-1")
        assert norm["status"] == "done"

    def test_default_status_when_no_signal(self):
        norm = sc._lofty_normalize_task({"title": "Call back"}, "lead-1")
        assert norm["status"] == "open"

    def test_picks_due_alternatives(self):
        for key in ("dueDate", "due_at", "dueAt", "scheduledFor"):
            norm = sc._lofty_normalize_task(
                {"title": "x", key: "2026-05-10"}, "lead-1"
            )
            assert norm["dueAt"] == "2026-05-10", key


# ── build_thread_context_response splits notes/tasks/activity ────────


@pytest.fixture
def fake_lofty_source(tmp_path: Path, monkeypatch):
    """Build a minimal source root with one Lofty contact + lead-events
    that includes a mix of activity/note/task event types so we can
    assert ``build_thread_context_response`` splits them correctly.

    Returns ``(source_id, thread_id, config)`` for the test to use.
    """
    source_root = tmp_path / "sources"
    crm_dir = source_root / "crm"
    crm_dir.mkdir(parents=True)
    artifacts = crm_dir / "artifacts"
    artifacts.mkdir()

    thread_id = "lofty-lead:42"
    contact = {
        "source_id": "crm",
        "source_record_id": thread_id,
        "conversation_id": thread_id,
        "contact_id": thread_id,
        "display_name": "Test Buyer",
        "channel": "Lofty CRM",
        "timestamp": "2026-05-05T10:00:00Z",
        "last_seen_at": "2026-05-05T10:00:00Z",
        "lead_id": "42",
        "stage": "qualified",
        "tags": ["lofty-crm"],
        "score": 80,
    }
    (crm_dir / "contacts.jsonl").write_text(json.dumps(contact) + "\n")
    (crm_dir / "messages.jsonl").write_text("")
    (crm_dir / "conversations.jsonl").write_text(json.dumps(contact) + "\n")
    (crm_dir / "tasks.jsonl").write_text("")

    events = [
        {
            "source_record_id": thread_id,
            "contact_id": thread_id,
            "conversation_id": thread_id,
            "type": "crm_lead_synced",
            "title": "Lofty lead synced",
            "summary": "synced",
            "timestamp": "2026-05-05T09:00:00Z",
        },
        {
            "source_record_id": f"{thread_id}:activity:a1",
            "contact_id": thread_id,
            "conversation_id": thread_id,
            "type": "lofty_activity",
            "subtype": "property_view",
            "title": "Viewed property",
            "summary": "Viewed 123 Main St",
            "address": "123 Main St",
            "timestamp": "2026-05-04T14:00:00Z",
        },
        {
            "source_record_id": f"{thread_id}:note:n1",
            "contact_id": thread_id,
            "conversation_id": thread_id,
            "type": "lofty_note",
            "title": "Cold feet",
            "summary": "Buyer second-guessing",
            "author": "Demo Agent",
            "timestamp": "2026-05-03T16:00:00Z",
        },
        {
            "source_record_id": f"{thread_id}:task:t1",
            "contact_id": thread_id,
            "conversation_id": thread_id,
            "type": "lofty_task",
            "title": "Call buyer back",
            "summary": "Confirm Saturday tour",
            "status": "open",
            "dueAt": "2026-05-07",
            "timestamp": "2026-05-02T12:00:00Z",
        },
    ]
    (crm_dir / "lead-events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )
    (crm_dir / "source.json").write_text(
        json.dumps(
            {
                "source_id": "crm",
                "provider": "Lofty CRM",
                "account_label": "Lofty CRM",
                "connection_type": "lofty_api",
                "auth_status": "api_key_configured",
                "owner_agent": "team",
                "enabled_ui_surfaces": ["Leads"],
                "setup_status": "connected",
                "last_sync_at": "2026-05-05T10:00:00Z",
            }
        )
    )
    (crm_dir / "status.json").write_text(
        json.dumps({"connected": True, "last_checked_at": "2026-05-05T10:00:00Z"})
    )

    config = {"source_root": str(source_root)}
    monkeypatch.setattr(sc, "load_config", lambda: config)
    monkeypatch.setattr(
        sc,
        "get_source_root_info",
        lambda cfg=None: {
            "toolsRoot": str(tmp_path),
            "toolsRootSource": "test",
            "toolsRootIo": "local",
            "sourceRoot": str(source_root),
        },
    )
    return ("crm", thread_id, config)


class TestThreadContextSplit:
    def test_notes_tasks_activity_separated(self, fake_lofty_source):
        source_id, thread_id, _config = fake_lofty_source
        resp = sc.build_thread_context_response(source_id, thread_id, limit=200)

        assert resp["sourceId"] == source_id
        assert resp["threadId"] == thread_id

        # notes filtered to lofty_note rows only
        notes = resp["notes"]
        assert len(notes) == 1
        assert notes[0]["title"] == "Cold feet"
        assert notes[0]["author"] == "Demo Agent"

        # tasks filtered to lofty_task rows only
        tasks = resp["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Call buyer back"
        assert tasks[0]["status"] == "open"
        assert tasks[0]["dueAt"] == "2026-05-07"

        # activity holds everything else (crm_lead_synced + lofty_activity)
        activity = resp["activity"]
        types = {row["type"] for row in activity}
        assert types == {"crm_lead_synced", "lofty_activity"}
        # property_view row should retain its address
        view_row = next(r for r in activity if r["type"] == "lofty_activity")
        assert view_row["address"] == "123 Main St"

    def test_no_stubs_field_in_response(self, fake_lofty_source):
        """The misleading 'stubs' placeholder is gone now that the
        endpoints are wired."""
        source_id, thread_id, _config = fake_lofty_source
        resp = sc.build_thread_context_response(source_id, thread_id, limit=200)
        assert "stubs" not in resp

    def test_lead_metadata_still_populated(self, fake_lofty_source):
        source_id, thread_id, _config = fake_lofty_source
        resp = sc.build_thread_context_response(source_id, thread_id, limit=200)
        assert resp["lead"]["leadId"] == "42"
        assert resp["lead"]["stage"] == "qualified"
        assert resp["lead"]["score"] == 80
