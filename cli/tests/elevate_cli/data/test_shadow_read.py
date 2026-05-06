"""Tests for the Sprint 1D shadow-read wrapper + parity-report CLI.

The wrapper has three behaviors that matter:

1. Off by default — when ``ELEVATE_DATA_SHADOW_READ`` is unset, only
   the legacy function runs. No DB writes, no overhead.
2. On + ``db_fn=None`` — still a passthrough. Sprint 1D ships the
   wiring with ``db_fn=None``; Sprint 2 fills it in. We don't want
   noise in the parity table during 1D.
3. On + ``db_fn`` returns equal value — records a snapshot with
   ``diff_json IS NULL`` and returns the legacy result.
4. On + ``db_fn`` returns different value — records a snapshot with a
   non-null ``diff_json`` and still returns the legacy result.
5. On + ``db_fn`` raises — by default the wrapper swallows and returns
   the legacy result. ``fail-loud`` re-raises.
"""

from __future__ import annotations

import os

import pytest

from elevate_cli.data import (
    connect,
    parity_diff_count,
    parity_total_count,
    shadow_read,
    shadow_read_enabled,
)
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data_cli import cmd_parity_report


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def shadow_off(monkeypatch):
    monkeypatch.delenv("ELEVATE_DATA_SHADOW_READ", raising=False)


@pytest.fixture
def shadow_on(monkeypatch):
    monkeypatch.setenv("ELEVATE_DATA_SHADOW_READ", "1")


@pytest.fixture
def shadow_loud(monkeypatch):
    monkeypatch.setenv("ELEVATE_DATA_SHADOW_READ", "fail-loud")


def _legacy_response():
    return {"items": [{"id": "a"}, {"id": "b"}], "total": 2}


def test_passthrough_when_flag_is_off(shadow_off):
    assert shadow_read_enabled() is False
    db_called = []

    result = shadow_read(
        endpoint="GET /api/x",
        request_args={"k": 1},
        jsonl_fn=_legacy_response,
        db_fn=lambda: db_called.append(True) or {"items": [], "total": 0},
    )

    assert result == _legacy_response()
    assert db_called == []  # db side never invoked
    with connect() as conn:
        assert parity_total_count(conn) == 0


def test_passthrough_when_db_fn_is_none(shadow_on):
    assert shadow_read_enabled() is True

    result = shadow_read(
        endpoint="GET /api/x",
        request_args={"k": 1},
        jsonl_fn=_legacy_response,
        db_fn=None,
    )

    assert result == _legacy_response()
    with connect() as conn:
        # No snapshots recorded — wiring without a db_fn is silent.
        assert parity_total_count(conn) == 0


def test_records_clean_snapshot_when_responses_match(shadow_on):
    result = shadow_read(
        endpoint="GET /api/x",
        request_args={"k": 1},
        jsonl_fn=_legacy_response,
        db_fn=_legacy_response,
    )

    assert result == _legacy_response()
    with connect() as conn:
        assert parity_total_count(conn) == 1
        assert parity_diff_count(conn) == 0


def test_records_diff_when_responses_differ(shadow_on):
    result = shadow_read(
        endpoint="GET /api/x",
        request_args={"k": 1},
        jsonl_fn=_legacy_response,
        db_fn=lambda: {"items": [{"id": "a"}], "total": 1},
    )

    # Legacy result is what callers get even when the new path disagrees.
    assert result == _legacy_response()
    with connect() as conn:
        assert parity_total_count(conn) == 1
        assert parity_diff_count(conn) == 1


def test_swallows_db_fn_exception_by_default(shadow_on):
    def boom():
        raise RuntimeError("db side blew up")

    # Must not raise — legacy result still returns.
    result = shadow_read(
        endpoint="GET /api/x",
        request_args={"k": 1},
        jsonl_fn=_legacy_response,
        db_fn=boom,
    )
    assert result == _legacy_response()
    with connect() as conn:
        # No snapshot — there was no db response to compare against.
        assert parity_total_count(conn) == 0


def test_fail_loud_reraises_db_fn_exception(shadow_loud):
    def boom():
        raise RuntimeError("db side blew up")

    with pytest.raises(RuntimeError, match="db side blew up"):
        shadow_read(
            endpoint="GET /api/x",
            request_args={"k": 1},
            jsonl_fn=_legacy_response,
            db_fn=boom,
        )


# ─── parity-report CLI ─────────────────────────────────────────────────


class _Args:
    def __init__(self, **kw):
        self.days = kw.get("days", 3)
        self.limit = kw.get("limit", 20)
        self.json = kw.get("json", False)


def test_parity_report_returns_nonzero_with_no_snapshots(capsys, shadow_off):
    rc = cmd_parity_report(_Args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "total snapshots : 0" in out
    assert "ELEVATE_DATA_SHADOW_READ" in out


def test_parity_report_clean_window_returns_zero(capsys, shadow_on):
    shadow_read(
        endpoint="GET /api/x", request_args={},
        jsonl_fn=_legacy_response, db_fn=_legacy_response,
    )
    shadow_read(
        endpoint="GET /api/y", request_args={},
        jsonl_fn=lambda: {"v": 1}, db_fn=lambda: {"v": 1},
    )

    rc = cmd_parity_report(_Args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "total snapshots : 2" in out
    assert "diffs           : 0" in out
    assert "match rate      : 100.00%" in out
    assert "Window is clean" in out


def test_parity_report_dirty_window_returns_one_and_lists_diffs(capsys, shadow_on):
    shadow_read(
        endpoint="GET /api/x", request_args={"limit": 5},
        jsonl_fn=_legacy_response, db_fn=_legacy_response,
    )
    shadow_read(
        endpoint="GET /api/y", request_args={"limit": 5},
        jsonl_fn=lambda: {"v": 1}, db_fn=lambda: {"v": 2},
    )

    rc = cmd_parity_report(_Args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "diffs           : 1" in out
    assert "GET /api/y" in out
    # Match rate is 50% (1 of 2 snapshots clean)
    assert "match rate      : 50.00%" in out


def test_parity_report_json_mode(capsys, shadow_on):
    import json as _json

    shadow_read(
        endpoint="GET /api/x", request_args={},
        jsonl_fn=_legacy_response, db_fn=_legacy_response,
    )

    rc = cmd_parity_report(_Args(json=True))
    assert rc == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["totalSnapshots"] == 1
    assert payload["diffCount"] == 0
    assert payload["clean"] is True
    assert payload["matchRate"] == 1.0
    assert payload["windowDays"] == 3
    assert payload["recentDiffs"] == []
