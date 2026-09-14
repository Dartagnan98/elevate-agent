import json
from datetime import datetime, timedelta, timezone
import urllib.error

import pytest
from elevate_cli import source_connectors as sc
from elevate_cli.source_connector_modules.lofty_sync import _lofty_load_enrichment_progress, _lofty_enrich_one_lead


def test_legacy_completed_checkpoint_requires_refresh(tmp_path):
    (tmp_path / "enrichment_progress.json").write_text(json.dumps({"completed_lead_ids": ["1"], "events": [{"type": "crm_note"}]}))
    completed, events, _ = _lofty_load_enrichment_progress(tmp_path)
    assert completed == set()
    assert len(events) == 1


def test_only_recent_successful_leads_skip_refresh(tmp_path):
    now = datetime.now(timezone.utc)
    (tmp_path / "enrichment_progress.json").write_text(json.dumps({"refresh_version": 2, "refreshed_at": {
        "recent": now.isoformat(), "old": (now - timedelta(hours=2)).isoformat(), "invalid": "broken",
    }}))
    completed, _, _ = _lofty_load_enrichment_progress(tmp_path)
    assert completed == {"recent"}


def test_empty_supported_endpoint_does_not_fall_back(monkeypatch):
    calls = []
    def get(path, *a, **kw):
        calls.append(path)
        return {"notes": []}
    monkeypatch.setattr(sc, "_lofty_get", get)
    assert sc._lofty_get_notes("1", {}) == []
    assert len(calls) == 1


def test_all_404s_are_failure_not_successful_empty(monkeypatch):
    def get(*a, **kw):
        raise urllib.error.HTTPError("https://example.com", 404, "missing", {}, None)
    monkeypatch.setattr(sc, "_lofty_get", get)
    with pytest.raises(urllib.error.HTTPError):
        sc._lofty_get_notes("1", {})


def test_activity_pagination_fetches_all_pages(monkeypatch):
    def get(path, env, params, **kw):
        offset = params["offset"]
        return [{"id": i} for i in range(offset, min(offset + 2, 5))]
    monkeypatch.setattr(sc, "_lofty_get", get)
    rows = sc._lofty_get_first_ok(("activity",), {}, {"offset": 0, "limit": 2})
    assert [r["id"] for r in rows] == list(range(5))


def test_empty_communications_do_not_hide_property_activity(monkeypatch):
    def get(path, *a, **kw):
        return [] if path.startswith("v2") else [{"type": "Browse", "created": 12345}]
    monkeypatch.setattr(sc, "_lofty_get", get)
    assert sc._lofty_get_activities("1", {}) == [{"type": "Browse", "created": 12345}]


def test_legacy_site_feed_is_complete_unpaginated_array(monkeypatch):
    calls = []
    def get(path, env, params=None, **kw):
        calls.append((path, params))
        return [] if path.startswith("v2") else [{"type": "Browse", "created": i} for i in range(89)]
    monkeypatch.setattr(sc, "_lofty_get", get)
    assert len(sc._lofty_get_activities("1", {})) == 89
    assert len(calls) == 2
    assert calls[1][1] is None


def test_worker_preserves_note_body_and_counts_failures(monkeypatch):
    monkeypatch.setattr(sc, "_lofty_get_activities", lambda *a, **kw: [])
    monkeypatch.setattr(sc, "_lofty_get_notes", lambda *a, **kw: [{"id": "n", "content": "Actual note", "creatorName": "Agent"}])
    def failed(*a, **kw):
        raise TimeoutError()
    monkeypatch.setattr(sc, "_lofty_get_tasks", failed)
    _, events, stats = _lofty_enrich_one_lead(lead_id="1", record_id="lofty-lead:1",
        base_record={"text": "Generic lead summary"}, fallback_timestamp="2026-09-07T00:00:00+00:00", env_values={}, timeout=1)
    assert stats["errors"] == 1
    assert events[0]["body"] == "Actual note"
    assert events[0]["author"] == "Agent"


def test_sync_retries_failed_lead_then_reuses_fresh_success(tmp_path, monkeypatch):
    from elevate_cli.source_connector_modules.lofty_sync import sync_lofty_crm_source
    monkeypatch.setattr(sc, "get_source_root_info", lambda config=None: {"sourceRoot": str(tmp_path)})
    monkeypatch.setattr(sc, "_combined_env", lambda config: {"LOFTY_API_KEY": "test"})
    monkeypatch.setattr(sc, "_walk_jsonl_into_pg", lambda path: {})
    monkeypatch.setattr(sc, "_lofty_get", lambda *a, **kw: {"leads": [{"leadId": "1", "firstName": "Test"}]})
    monkeypatch.setattr(sc, "_lofty_get_activities", lambda *a, **kw: [])
    monkeypatch.setattr(sc, "_lofty_get_tasks", lambda *a, **kw: [])
    attempts = []
    def notes(*a, **kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError()
        return [{"id": "n", "content": "Recovered note"}]
    monkeypatch.setattr(sc, "_lofty_get_notes", notes)
    config = {"integrations": {"crm": {"provider": "lofty"}}}
    sync_lofty_crm_source(config)
    checkpoint = tmp_path / "crm/artifacts/enrichment_progress.json"
    assert json.loads(checkpoint.read_text())["refreshed_at"] == {}
    sync_lofty_crm_source(config)
    assert "1" in json.loads(checkpoint.read_text())["refreshed_at"]
    sync_lofty_crm_source(config)
    assert len(attempts) == 2
    events = json.loads(checkpoint.read_text())["events"]
    assert len(events) == 1
    assert events[0]["body"] == "Recovered note"
