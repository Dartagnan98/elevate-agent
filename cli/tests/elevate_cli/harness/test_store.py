from pathlib import Path

from elevate_cli.harness.models import HarnessRun, new_id
from elevate_cli.harness.store import HarnessStore


def test_create_and_update_run(tmp_path: Path):
    store = HarnessStore(tmp_path / "state.db")
    store.migrate()
    run = HarnessRun(id=new_id("run"), name="Test", run_type="browser_extract", status="pending")
    store.upsert_run(run)

    loaded = store.get_run(run.id)
    assert loaded is not None
    assert loaded.name == "Test"
    assert loaded.allowed_domains == []

    store.update_run_status(run.id, "running")
    assert store.get_run(run.id).status == "running"


def test_append_event(tmp_path: Path):
    store = HarnessStore(tmp_path / "state.db")
    store.migrate()
    run = HarnessRun(id="run_123", name="Test", run_type="browser_extract", status="running")
    store.upsert_run(run)

    store.append_event("run_123", "started", "Started test run", {"x": 1})
    events = store.list_events("run_123")

    assert len(events) == 1
    assert events[0]["event_type"] == "started"
    assert events[0]["payload"] == {"x": 1}
