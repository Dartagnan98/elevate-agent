"""Calendar transport recovery must preserve local events and stable identities."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from elevate_cli import events_sync as sync


def _response(payload, *, code=0):
    return SimpleNamespace(
        returncode=code,
        stdout="Using keyring backend: keyring\n" + json.dumps(payload) + "\n",
        stderr="private credential output must never be surfaced",
    )


@pytest.fixture
def gws(monkeypatch):
    monkeypatch.setattr(sync.shutil, "which", lambda *args, **kwargs: "/test/bin/gws")
    runner = MagicMock()
    monkeypatch.setattr(sync.subprocess, "run", runner)
    return runner


def test_gws_fetches_all_pages_with_bounded_read_only_requests(gws):
    gws.side_effect = [
        _response({"kind": "calendar#events", "items": [{"id": "one"}], "nextPageToken": "page2"}),
        _response({"kind": "calendar#events", "items": [{"id": "two"}]}),
    ]
    assert sync._gws_calendar_rows(21) == [{"id": "one"}, {"id": "two"}]
    first, second = gws.call_args_list
    assert first.args[0][:4] == ["/test/bin/gws", "calendar", "events", "list"]
    params = json.loads(first.args[0][-1])
    assert params["calendarId"] == "primary"
    assert params["maxResults"] == 250
    assert params["singleEvents"] is True
    assert "pageToken" not in params
    assert json.loads(second.args[0][-1])["pageToken"] == "page2"
    assert first.kwargs["timeout"] == 20


@pytest.mark.parametrize("payload", [
    {"kind": "calendar#events", "items": []},
    {"kind": "calendar#events"},
])
def test_gws_accepts_an_empty_calendar(gws, payload):
    gws.return_value = _response(payload)
    assert sync._gws_calendar_rows(21) == []


@pytest.mark.parametrize("payload", [
    {}, {"error": {"code": 401}}, {"kind": "unrelated#response"},
    {"kind": "calendar#events", "items": "bad"},
    {"kind": "calendar#events", "items": [None]},
])
def test_invalid_responses_never_write_or_prune_local_calendar(gws, monkeypatch, payload):
    gws.return_value = _response(payload)
    connection = MagicMock()
    monkeypatch.setattr(sync, "connect", connection)
    result = sync.sync_google_calendar_events(provider="gws")
    assert result["ok"] is False
    connection.assert_not_called()


def test_later_page_failure_does_not_commit_a_partial_calendar(gws, monkeypatch):
    gws.side_effect = [
        _response({"kind": "calendar#events", "items": [{"id": "one"}], "nextPageToken": "page2"}),
        _response({"error": "secret"}, code=1),
    ]
    connection = MagicMock()
    monkeypatch.setattr(sync, "connect", connection)
    result = sync.sync_google_calendar_events(provider="gws")
    assert result["ok"] is False
    assert "sign-in" in result["reason"]
    assert "secret" not in result["reason"]
    assert "credential" not in result["reason"]
    connection.assert_not_called()


def test_pagination_cannot_loop_forever(gws):
    gws.return_value = _response({"kind": "calendar#events", "items": [], "nextPageToken": "repeat"})
    with pytest.raises(RuntimeError, match="did not advance"):
        sync._gws_calendar_rows(21)
    assert gws.call_count == 2


def test_pagination_has_a_hard_page_limit(gws):
    gws.side_effect = [
        _response({"kind": "calendar#events", "items": [], "nextPageToken": str(i)})
        for i in range(10)
    ]
    with pytest.raises(RuntimeError, match="10-page"):
        sync._gws_calendar_rows(21)


def test_timeout_does_not_expose_cli_arguments(gws):
    gws.side_effect = subprocess.TimeoutExpired("private arguments", 20)
    result = sync.sync_google_calendar_events(provider="gws")
    assert result["ok"] is False
    assert "timed out" in result["reason"]
    assert "private" not in result["reason"]


def test_missing_cli_returns_an_actionable_failure(monkeypatch):
    monkeypatch.setattr(sync.shutil, "which", lambda *args, **kwargs: None)
    result = sync.sync_google_calendar_events(provider="gws")
    assert result["ok"] is False
    assert "not installed" in result["reason"]


@pytest.mark.parametrize("provider", ["gws", "composio"])
def test_providers_use_the_same_calendar_identity(monkeypatch, provider):
    event = {
        "id": "stable-google-event-id", "summary": "Showing",
        "start": {"dateTime": "2026-09-12T10:00:00-07:00"},
        "end": {"dateTime": "2026-09-12T11:00:00-07:00"},
    }
    rows = [event, dict(event, id="cancelled", status="cancelled"), {"summary": "incomplete"}]
    monkeypatch.setattr(sync, "_gws_calendar_rows", lambda days: rows)
    accounts = MagicMock(return_value=([{"id": "test-account", "user_id": "test-user"}], None))
    monkeypatch.setattr(sync, "_connected_accounts", accounts)
    monkeypatch.setattr(sync.composio_client, "execute_tool", lambda *args, **kwargs: {
        "ok": True, "data": {"data": {"items": rows}},
    })
    connection = MagicMock()
    monkeypatch.setattr(sync, "connect", connection)
    monkeypatch.setattr(sync, "match_deal_by_address", lambda *args, **kwargs: "deal-id")
    monkeypatch.setattr(sync, "prune_old_calendar_events", lambda conn: 0)
    upsert = MagicMock()
    monkeypatch.setattr(sync, "upsert_calendar_event", upsert)

    result = sync.sync_google_calendar_events(provider=provider)

    assert result["ok"] is True
    assert result["upserted"] == 1
    assert upsert.call_args.kwargs["source"] == "gcal"
    assert upsert.call_args.kwargs["source_event_id"] == "stable-google-event-id"
    assert upsert.call_args.kwargs["deal_id"] == "deal-id"
    if provider == "gws":
        accounts.assert_not_called()


def test_cli_requires_explicit_local_provider_selection(monkeypatch):
    monkeypatch.setattr(sync, "load_config", lambda: {})
    runner = MagicMock(return_value={"ok": True, "upserted": 0})
    monkeypatch.setattr(sync, "sync_google_calendar_events", runner)
    assert sync.main([]) == 0
    runner.assert_called_with(days=21, provider="composio")
    assert sync.main(["--provider", "gws"]) == 0
    runner.assert_called_with(days=21, provider="gws")


def test_saved_provider_survives_regenerated_system_job_scripts(monkeypatch):
    monkeypatch.setattr(sync, "load_config", lambda: {"admin_calendar": {"provider": "gws"}})
    runner = MagicMock(return_value={"ok": True, "upserted": 0})
    monkeypatch.setattr(sync, "sync_google_calendar_events", runner)
    assert sync.main([]) == 0
    runner.assert_called_with(days=21, provider="gws")
    assert sync.main(["--provider", "composio"]) == 0
    runner.assert_called_with(days=21, provider="composio")
