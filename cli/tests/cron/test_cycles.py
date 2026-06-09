"""Tests for cron/cycles.py — experiment-cycle CRUD persisted to the account
database (surface_state, migration 0024) + legacy ``experiment`` migration."""

import pytest

from elevate_cli.data import connect
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data import surface_state

from cron.cycles import find_cycle_defaults, list_cycles, manage_cycle


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    """Per-test embedded PG bound to this test's isolated ELEVATE_HOME."""
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _set_config(surface: str, config: dict) -> None:
    with connect() as conn:
        surface_state.set_config(conn, surface, config)


def _get_config(surface: str) -> dict:
    with connect() as conn:
        return surface_state.get_config(conn, surface)


LEGACY_EXPERIMENT = {
    "every_n_runs": 5,
    "metric": "hot_leads",
    "metric_type": "quantitative",
    "direction": "higher",
    "window": "7d",
    "measurement": "Count hot leads after the run.",
    "approval_required": True,
}


# ─── create / modify / remove persist to PG ────────────────────────────────


def test_manage_cycle_create_persists_to_pg():
    result = manage_cycle(
        "leads", "create",
        name="rank-specific-intent", metric="draft_quality",
        metric_type="qualitative", direction="higher",
        window="7d", every_n_runs=3, approval_required=True,
    )
    assert result["ok"] is True
    assert len(result["cycles"]) == 1

    stored = _get_config("leads")["cycles"]
    assert stored[0]["name"] == "rank-specific-intent"
    assert stored[0]["metric"] == "draft_quality"
    assert stored[0]["every_n_runs"] == 3
    assert stored[0]["loop_interval"] == "every 3 runs"
    assert stored[0]["approval_required"] is True
    assert stored[0]["enabled"] is True

    assert list_cycles("leads") == stored


def test_manage_cycle_modify_and_remove_persist_to_pg():
    manage_cycle("leads", "create", name="c1", metric="m1")

    modified = manage_cycle("leads", "modify", name="C1", enabled=False, every_n_runs=9)
    assert modified["ok"] is True
    stored = _get_config("leads")["cycles"]
    assert stored[0]["enabled"] is False
    assert stored[0]["every_n_runs"] == 9

    removed = manage_cycle("leads", "remove", name="c1")
    assert removed["ok"] is True
    assert removed["cycles"] == []
    assert _get_config("leads")["cycles"] == []


def test_manage_cycle_validation_unchanged():
    assert manage_cycle("leads", "explode")["ok"] is False
    assert manage_cycle("leads", "create", name="x")["ok"] is False  # no metric
    assert manage_cycle("leads", "create", metric="m")["ok"] is False  # no name
    assert manage_cycle("leads", "create", name="x", metric="m", direction="sideways")["ok"] is False
    assert manage_cycle("leads", "create", name="x", metric="m", metric_type="vibes")["ok"] is False
    assert manage_cycle("leads", "modify", enabled=False)["ok"] is False  # no name
    assert manage_cycle("leads", "remove", name="ghost")["ok"] is False  # not found

    ok = manage_cycle("leads", "create", name="dup", metric="m")
    assert ok["ok"] is True
    assert manage_cycle("leads", "create", name="DUP", metric="m2")["ok"] is False  # ci-dupe
    assert manage_cycle("leads", "modify", name="dup", direction="sideways")["ok"] is False


# ─── legacy ``experiment`` block migration ─────────────────────────────────


def test_list_cycles_synthesizes_from_legacy_experiment_read_only():
    _set_config("admin", {"goal": "admin work", "experiment": LEGACY_EXPERIMENT})

    cycles = list_cycles("admin")
    assert len(cycles) == 1
    assert cycles[0]["name"] == "hot_leads"
    assert cycles[0]["metric"] == "hot_leads"
    assert cycles[0]["every_n_runs"] == 5
    assert cycles[0]["loop_interval"] == "every 5 runs"
    assert cycles[0]["approval_required"] is True

    # Read-only: list_cycles must NOT persist the migration.
    assert "cycles" not in _get_config("admin")


def test_mutating_action_persists_legacy_migration_and_keeps_experiment_key():
    _set_config("admin", {"goal": "admin work", "experiment": LEGACY_EXPERIMENT})

    result = manage_cycle("admin", "create", name="extra", metric="stale_blockers")
    assert result["ok"] is True
    assert len(result["cycles"]) == 2  # synthesized legacy cycle + the new one

    stored = _get_config("admin")
    # Legacy key NEVER deleted.
    assert stored["experiment"] == LEGACY_EXPERIMENT
    names = [c["name"] for c in stored["cycles"]]
    assert names == ["hot_leads", "extra"]


def test_empty_surface_has_no_cycles():
    assert list_cycles("nowhere") == []
    assert manage_cycle("nowhere", "list") == {"ok": True, "cycles": []}


# ─── find_cycle_defaults ───────────────────────────────────────────────────


def test_find_cycle_defaults_matches_metric():
    manage_cycle(
        "leads", "create",
        name="c1", metric="draft_quality", metric_type="qualitative",
        direction="lower", window="14d", measurement="self-score", every_n_runs=4,
    )
    defaults = find_cycle_defaults("leads", "draft_quality")
    assert defaults == {
        "surface": "playbook",
        "direction": "lower",
        "window": "14d",
        "measurement": "self-score",
        "metric_type": "qualitative",
        "every_n_runs": 4,
    }
    assert find_cycle_defaults("leads", "unknown_metric") is None
