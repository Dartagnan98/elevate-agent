from pathlib import Path

from elevate_cli.harness.ingestion import ingest_browser_page
from elevate_cli.harness.models import HarnessRun
from elevate_cli.harness.store import HarnessStore


def test_ingest_browser_page_saves_clean_snapshot(tmp_path: Path):
    store = HarnessStore(tmp_path / "state.db")
    store.migrate()
    store.upsert_run(HarnessRun(id="run_1", name="Extract", run_type="browser_extract", status="running"))

    page = {
        "url": "https://www.expagentcentre.ca/alberta",
        "title": "Alberta",
        "text": "Visible source text",
        "localStorage": {"okta-token-storage": "secret"},
        "links": [{"text": "Guide", "href": "https://exptransactionguide.com/AB"}],
    }
    snapshot = ingest_browser_page(
        store=store,
        run_id="run_1",
        page=page,
        output_root=tmp_path / "sources",
        account_context="Team Pilot/eXp",
        jurisdiction="canada.ab",
    )

    assert Path(snapshot.raw_text_path).read_text() == "Visible source text"
    metadata = Path(snapshot.json_path).read_text()
    assert "okta-token-storage" not in metadata
    assert store.list_source_snapshots("run_1")[0]["id"] == snapshot.id
