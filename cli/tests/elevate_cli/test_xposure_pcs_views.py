"""Unit tests for xposure-pcs-views connector.

The heavy parser lives in the Node scraper
(``~/elevate-premium/scripts/pcs-listing-views-scraper.cjs``); the Python
module is the orchestrator + DB writethrough. These tests lock down:

  1. Connector wiring: blueprint, owner, UI surfaces, scheduler tuple,
     known-source list, and scaffold dispatch.
  2. Ingest helpers with a fake conn — _upsert_listing_views stale-marks
     missing MLS ids, _update_buyer_summary tolerates partial payloads,
     _ingest_records buckets buyers vs missing.
  3. The run_views_sync entry point short-circuits cleanly when there
     are no targets.

The DB walk (`_select_targets`) is integration-only — covered by the
live PG run-through.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from elevate_cli import xposure_pcs_views as views
from elevate_cli.xposure_pcs_views import (
    SOURCE_ID,
    _count_jsonl_lines,
    _ingest_records,
    _read_recent_records,
    _resolve_contact_id,
    _update_buyer_summary,
    _upsert_listing_views,
    run_views_sync,
)


# ─── Fake DB connection ──────────────────────────────────────────────


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)


class FakeConn:
    """Records every execute(sql, params) call. Returns canned rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.next_rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = ()) -> FakeCursor:
        self.calls.append((sql, tuple(params) if params else ()))
        rows, self.next_rows = self.next_rows, []
        return FakeCursor(rows)

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


# ─── Wiring ──────────────────────────────────────────────────────────


class TestConnectorWiring:
    def test_blueprint_present(self) -> None:
        from elevate_cli.source_connectors import SOURCE_CONNECTION_BLUEPRINTS

        ids = [b["id"] for b in SOURCE_CONNECTION_BLUEPRINTS]
        assert "xposure-pcs-views" in ids

    def test_owner_and_ui(self) -> None:
        from elevate_cli.source_connectors import OWNER_BY_SOURCE, UI_BY_SOURCE

        assert OWNER_BY_SOURCE["xposure-pcs-views"] == "Outreach"
        # Must reach Leads + Today + Outreach (the activity-flagger surface)
        for surface in ("Leads", "Today", "Outreach"):
            assert surface in UI_BY_SOURCE["xposure-pcs-views"]

    def test_known_source_id(self) -> None:
        from elevate_cli.data_cli import _KNOWN_SOURCE_IDS

        assert "xposure-pcs-views" in _KNOWN_SOURCE_IDS

    def test_source_prompt_is_registered_executable_agent_prompt(self) -> None:
        from elevate_cli.source_connectors import source_prompt_for

        with mock.patch.object(
            views, "_candidate_emails_for_prompt", return_value=["buyer@example.com"]
        ):
            prompt = source_prompt_for("xposure-pcs-views")
        assert "You are an automation agent driving the AOIR Xposure realtor portal" in prompt
        assert "buyer@example.com" in prompt
        assert "Client View" in prompt
        assert "DataTables model directly" in prompt
        assert "DOMParser" in prompt
        assert "listing-container" in prompt
        assert "xposure_pcs_views_cdp_writer" in prompt
        assert "--emails-file" in prompt
        assert "DO NOT create `/tmp/xposure_append_server.py`" in prompt
        assert "DO NOT fetch `127.0.0.1`" in prompt
        assert "/static/responsive/js/pcs-contacts.js" in prompt
        assert "DONE rows=<N>" in prompt
        assert "STATUS: No live pull code exists" not in prompt
        assert "Canonical contract" not in prompt

    def test_scheduler_tuple(self) -> None:
        from elevate_cli.sync_scheduler import _JOBS, jobs, generate_plist

        match = [j for j in _JOBS if j[1] == "xposure-pcs-views"]
        assert match, "xposure-pcs-views missing from sync_scheduler._JOBS"
        label, source_id, interval, desc = match[0]
        assert label == "sync-xposure-pcs-views"
        # Daily cadence; launchd plist pins it to the morning.
        assert interval == 86400
        assert desc  # non-empty description

        job = next(j for j in jobs() if j.source_id == "xposure-pcs-views")
        plist = generate_plist(job)
        assert "<key>StartCalendarInterval</key>" in plist
        assert "<key>Hour</key>" in plist
        assert "<integer>7</integer>" in plist
        assert "<key>Minute</key>" in plist
        assert "<integer>0</integer>" in plist
        assert "<key>StartInterval</key>" not in plist
        assert "<key>RunAtLoad</key>" in plist
        assert "<false/>" in plist

    def test_scaffold_source_dispatches(self) -> None:
        # We don't actually run the scraper here — just confirm the
        # dispatch branch in scaffold_source routes to run_views_sync.
        from elevate_cli import source_connectors

        with mock.patch.object(
            views, "run_views_sync", return_value={"ok": True, "source": SOURCE_ID, "stubbed": True}
        ) as patched:
            result = source_connectors.scaffold_source(
                "xposure-pcs-views", config={"batch": 0}
            )
        assert patched.called
        assert result.get("source") == SOURCE_ID

    def test_scaffold_source_honors_skip_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from elevate_cli import source_connectors

        monkeypatch.setenv("ELEVATE_XPOSURE_VIEWS_SKIP_SCRAPER", "1")
        with mock.patch.object(views, "run_views_sync", return_value={"ok": True}) as patched:
            source_connectors.scaffold_source("xposure-pcs-views", config={})
        kwargs = patched.call_args.kwargs
        assert kwargs.get("skip_scraper") is True


# ─── JSONL helpers ───────────────────────────────────────────────────


class TestJsonlHelpers:
    def test_count_missing_file(self, tmp_path: Path) -> None:
        assert _count_jsonl_lines(tmp_path / "nope.jsonl") == 0

    def test_count_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.jsonl"
        p.write_text("a\nb\nc\n")
        assert _count_jsonl_lines(p) == 3

    def test_read_recent_records_tails(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.jsonl"
        records = [
            {"buyer_email": "a@x.com", "search_id": "1"},
            {"buyer_email": "b@x.com", "search_id": "2"},
            {"buyer_email": "c@x.com", "search_id": "3"},
        ]
        p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        # Only the last two are "new this run"
        out = _read_recent_records(p, since_count=2)
        assert [r["buyer_email"] for r in out] == ["b@x.com", "c@x.com"]

    def test_read_recent_records_skips_bad_json(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.jsonl"
        p.write_text(
            json.dumps({"buyer_email": "a@x.com"}) + "\n"
            "not-json-line\n"
            + json.dumps({"buyer_email": "b@x.com"}) + "\n"
        )
        out = _read_recent_records(p, since_count=3)
        assert [r["buyer_email"] for r in out] == ["a@x.com", "b@x.com"]

    def test_read_recent_records_no_file(self, tmp_path: Path) -> None:
        assert _read_recent_records(tmp_path / "nope.jsonl", since_count=10) == []

    def test_read_recent_records_zero(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.jsonl"
        p.write_text(json.dumps({"buyer_email": "a@x.com"}) + "\n")
        assert _read_recent_records(p, since_count=0) == []


# ─── Contact resolution ──────────────────────────────────────────────


class TestResolveContactId:
    def test_no_email(self) -> None:
        conn = FakeConn()
        assert _resolve_contact_id(conn, None) is None
        assert _resolve_contact_id(conn, "") is None
        assert conn.calls == []

    def test_found(self) -> None:
        conn = FakeConn()
        conn.next_rows = [{"id": "ct_123"}]
        cid = _resolve_contact_id(conn, "Nancy@example.com")
        assert cid == "ct_123"
        # case-insensitive: we pass email through and rely on LOWER() in SQL
        sql, params = conn.calls[0]
        assert "LOWER(primary_email)" in sql
        assert params == ("Nancy@example.com",)

    def test_missing(self) -> None:
        conn = FakeConn()
        assert _resolve_contact_id(conn, "ghost@example.com") is None


# ─── Listing upsert ──────────────────────────────────────────────────


class TestUpsertListingViews:
    def test_empty_listings_is_noop(self) -> None:
        conn = FakeConn()
        n = _upsert_listing_views(conn, "ct_1", "search_1", [])
        assert n == 0
        assert conn.calls == []

    def test_inserts_each_listing(self) -> None:
        conn = FakeConn()
        listings = [
            {
                "mls_id": "10388863",
                "address": "11 Jasper Dr",
                "view_count": 3,
                "view_state": "viewed",
                "list_price_cents": 52490000,
                "beds": 4,
                "baths": 2,
            },
            {
                "mls_id": "10388900",
                "address": "376 Hollywood Cres",
                "view_count": 2,
                "view_state": "viewed",
            },
        ]
        n = _upsert_listing_views(conn, "ct_1", "search_1", listings)
        assert n == 2
        # First call is the stale-marker UPDATE, then one INSERT per row.
        assert len(conn.calls) == 3
        stale_sql, _ = conn.calls[0]
        assert "view_state = 'stale'" in stale_sql
        assert "NOT IN" in stale_sql
        insert_sql, _ = conn.calls[1]
        assert "INSERT INTO pcs_listing_views" in insert_sql
        assert "ON CONFLICT (contact_id, search_id, mls_id)" in insert_sql

    def test_skips_listings_without_mls(self) -> None:
        conn = FakeConn()
        listings = [
            {"mls_id": "10388863", "view_count": 1},
            {"address": "no mls here", "view_count": 5},  # skipped
        ]
        n = _upsert_listing_views(conn, "ct_1", "search_1", listings)
        assert n == 1

    def test_defaults_view_state_when_missing(self) -> None:
        conn = FakeConn()
        listings = [{"mls_id": "X1"}]
        n = _upsert_listing_views(conn, "ct_1", "search_1", listings)
        assert n == 1
        # The INSERT call params: last positional before NOW() is view_state.
        insert_call = conn.calls[1]
        params = insert_call[1]
        # last param in the tuple is view_state (NOW() is inlined in SQL)
        assert params[-1] == "older"


# ─── Buyer-summary patch ─────────────────────────────────────────────


class TestUpdateBuyerSummary:
    def test_no_summary_no_xposure_id_is_noop(self) -> None:
        conn = FakeConn()
        _update_buyer_summary(conn, "ct_1", summary=None, xposure_contact_id=None)
        assert conn.calls == []

    def test_writes_xposure_contact_id_only(self) -> None:
        conn = FakeConn()
        _update_buyer_summary(
            conn, "ct_1", summary=None, xposure_contact_id="626963"
        )
        assert len(conn.calls) == 1
        sql, params = conn.calls[0]
        assert "UPDATE contacts" in sql
        assert "xposure_contact_id" in sql
        assert params[0] == "626963"

    def test_summary_update_uses_coalesce(self) -> None:
        conn = FakeConn()
        _update_buyer_summary(
            conn, "ct_1",
            summary={"results": 140, "favorites": 2, "removed": 36, "queue": 0,
                     "last_access": "2026-05-22T14:44:00-07:00"},
            xposure_contact_id=None,
        )
        assert len(conn.calls) == 1
        sql, params = conn.calls[0]
        assert "UPDATE pcs_buyers" in sql
        assert "COALESCE(?, results_count)" in sql
        assert "views_scraped_at" in sql
        # final param is the contact_id
        assert params[-1] == "ct_1"

    def test_summary_prefers_total_found_over_results(self) -> None:
        conn = FakeConn()
        _update_buyer_summary(
            conn, "ct_1",
            summary={"total_found": 200, "results": 999},
            xposure_contact_id=None,
        )
        sql, params = conn.calls[0]
        # First placeholder is results_count
        assert params[0] == 200

    def test_summary_with_xposure_id_writes_both(self) -> None:
        conn = FakeConn()
        _update_buyer_summary(
            conn, "ct_1",
            summary={"results": 1},
            xposure_contact_id="626963",
        )
        assert len(conn.calls) == 2
        assert "UPDATE contacts" in conn.calls[0][0]
        assert "UPDATE pcs_buyers" in conn.calls[1][0]


# ─── Ingest orchestration ────────────────────────────────────────────


class TestIngestRecords:
    def test_buyers_missing_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = FakeConn()
        # Resolve always misses
        monkeypatch.setattr(views, "connect", lambda: conn)
        records = [
            {"buyer_email": "ghost@example.com", "search_id": "s1",
             "listings": [{"mls_id": "X"}]},
        ]
        counts = _ingest_records(records)
        assert counts["records"] == 1
        assert counts["buyers_missing"] == 1
        assert counts["buyers_touched"] == 0
        assert counts["listings_upserted"] == 0

    def test_skips_records_without_search_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = FakeConn()
        conn.next_rows = [{"id": "ct_1"}]  # first execute resolves contact
        monkeypatch.setattr(views, "connect", lambda: conn)
        records = [{"buyer_email": "a@x.com", "search_id": None,
                    "listings": [{"mls_id": "X"}]}]
        counts = _ingest_records(records)
        assert counts["records"] == 1
        assert counts["listings_upserted"] == 0
        assert counts["buyers_missing"] == 0


# ─── Entry-point guards ──────────────────────────────────────────────


class TestRunViewsSync:
    def test_empty_targets_returns_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = FakeConn()
        monkeypatch.setattr(views, "connect", lambda: conn)
        monkeypatch.setattr(views, "_select_targets", lambda *a, **k: [])
        # Should not call the scraper when there are no targets.
        with mock.patch.object(views, "_run_scraper") as scraper:
            result = run_views_sync({"batch": 5, "lookback_days": 30})
        scraper.assert_not_called()
        assert result["ok"] is True
        assert result["source"] == SOURCE_ID
        assert result["targets"] == 0
        assert result["ingested"]["records"] == 0
        assert "no eligible buyers" in result.get("note", "")

    def test_dry_run_short_circuits_ingest(self, monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
        conn = FakeConn()
        monkeypatch.setattr(views, "connect", lambda: conn)
        monkeypatch.setattr(
            views, "_select_targets",
            lambda *a, **k: [{"primary_email": "a@x.com", "id": "ct_1"}],
        )
        monkeypatch.setattr(
            views, "_run_scraper",
            lambda emails, skip, headless: {"ok": True, "snapshot_count": 1},
        )
        monkeypatch.setattr(
            views, "_read_recent_records",
            lambda snap, count: [{"buyer_email": "a@x.com",
                                  "search_id": "s1", "listings": []}],
        )
        with mock.patch.object(views, "_ingest_records") as ingest:
            result = run_views_sync({"batch": 1}, dry_run=True)
        ingest.assert_not_called()
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["targets"] == 1

    def test_scraper_failure_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = FakeConn()
        monkeypatch.setattr(views, "connect", lambda: conn)
        monkeypatch.setattr(
            views, "_select_targets",
            lambda *a, **k: [{"primary_email": "a@x.com", "id": "ct_1"}],
        )
        monkeypatch.setattr(
            views, "_run_scraper",
            lambda emails, skip, headless: {"ok": False, "error": "boom",
                                            "snapshot_count": 0},
        )
        result = run_views_sync({"batch": 1})
        assert result["ok"] is False
        assert result["scraper"]["error"] == "boom"
