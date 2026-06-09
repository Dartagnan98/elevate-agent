from __future__ import annotations

import pytest

from elevate_cli.data import connect
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data import surface_state


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_registry_roundtrip_and_builtin_flag():
    with connect() as conn:
        surface_state.upsert_registry(
            conn, "leads", {"name": "Leads Heartbeat", "schedule": "0 8 * * *"}, builtin=True
        )
        surface_state.upsert_registry(conn, "custom", {"name": "Custom"}, created_by="agent")
        reg = surface_state.list_registry(conn)

    assert reg["leads"]["builtin"] is True
    assert reg["leads"]["schedule"] == "0 8 * * *"
    assert reg["custom"]["builtin"] is False
    assert reg["custom"]["created_by"] == "agent"


def test_registry_upsert_preserves_builtin_when_unspecified():
    with connect() as conn:
        surface_state.upsert_registry(conn, "admin", {"name": "Admin"}, builtin=True)
        surface_state.upsert_registry(conn, "admin", {"name": "Admin v2"})
        reg = surface_state.list_registry(conn)
        assert reg["admin"]["builtin"] is True
        assert reg["admin"]["name"] == "Admin v2"

        assert surface_state.remove_registry(conn, "admin") is True
        assert "admin" not in surface_state.list_registry(conn)


def test_config_roundtrip_and_tolerant_missing():
    with connect() as conn:
        assert surface_state.get_config(conn, "leads") == {}
        cfg = {"surface": "leads", "goal": "do leads", "enabled": False,
               "cycles": [{"name": "c1", "metric": "m"}]}
        surface_state.set_config(conn, "leads", cfg)
        out = surface_state.get_config(conn, "leads")

    assert out["goal"] == "do leads"
    assert out["cycles"][0]["name"] == "c1"


def test_patch_config_shallow_merges():
    with connect() as conn:
        surface_state.set_config(conn, "leads", {"goal": "a", "enabled": True})
        surface_state.patch_config(conn, "leads", {"enabled": False, "model": "x"})
        out = surface_state.get_config(conn, "leads")

    assert out == {"goal": "a", "enabled": False, "model": "x"}


def test_goals_default_shape_set_and_history():
    with connect() as conn:
        defaults = surface_state.get_goals(conn, "leads")
        assert defaults["goals"] == []
        assert defaults["bottleneck"] == ""

        surface_state.set_goals(
            conn,
            "leads",
            {"bottleneck": "follow-ups", "daily_focus": "drain queue",
             "goals": [{"id": "g1", "title": "t", "progress": 40, "order": 0}]},
        )
        out = surface_state.get_goals(conn, "leads")
        hist = surface_state.list_goals_history(conn, "leads")

    assert out["bottleneck"] == "follow-ups"
    assert out["goals"][0]["progress"] == 40
    assert len(hist) == 1
    assert hist[0]["bottleneck"] == "follow-ups"


def test_heartbeat_roundtrip_and_listing():
    with connect() as conn:
        assert surface_state.get_heartbeat(conn, "leads") is None
        surface_state.set_heartbeat(conn, "leads", {"at": "2026-06-09T01:00:00+00:00", "summary": "ok"})
        surface_state.set_heartbeat(conn, "admin", {"at": "2026-06-09T02:00:00+00:00", "summary": "later"})
        one = surface_state.get_heartbeat(conn, "leads")
        all_hb = surface_state.list_heartbeats(conn)

    assert one["summary"] == "ok"
    assert [h["agent"] for h in all_hb] == ["admin", "leads"]  # newest first


def test_activity_append_returns_row_and_lists_newest_first():
    with connect() as conn:
        first = surface_state.append_activity(conn, "leads", "draft_created", message="m1")
        surface_state.append_activity(
            conn,
            "admin",
            "task_done",
            message="m2",
            metadata={"task": "t1"},
            at="2099-01-01T00:00:00+00:00",
        )
        assert first["id"]
        assert first["agent"] == "leads"
        assert first["event"] == "draft_created"
        assert first["metadata"] == {}

        all_items = surface_state.list_activity(conn)
        leads = surface_state.list_activity(conn, agent="leads")
        limited = surface_state.list_activity(conn, limit=1)

    assert [item["agent"] for item in all_items] == ["admin", "leads"]  # newest first
    assert all_items[0]["metadata"] == {"task": "t1"}
    assert all_items[0]["at"] == "2099-01-01T00:00:00+00:00"
    assert leads == [first]
    assert len(limited) == 1


def test_activity_tolerant_metadata_and_required_agent():
    with connect() as conn:
        with pytest.raises(ValueError):
            surface_state.append_activity(conn, "", "event")
        # corrupt metadata TEXT degrades to {} on read
        conn.execute(
            "INSERT INTO surface_activity(id, agent, event, message, metadata, at) "
            "VALUES(?,?,?,?,?,?)",
            ("bad1", "leads", "corrupt", None, "{not json", "2026-06-09T00:00:00+00:00"),
        )
        rows = surface_state.list_activity(conn, agent="leads")

    assert rows[0]["metadata"] == {}
    assert rows[0]["message"] is None


def test_experiment_lifecycle_active_lookup_and_owner_vs_target():
    with connect() as conn:
        rec = surface_state.upsert_experiment(
            conn,
            "leads",
            {"id": "exp_1", "cycle": "rank-intent", "status": "proposed",
             "metric": "hot_leads", "surface": "playbook"},
        )
        assert rec["id"] == "exp_1"

        # active lookup without id
        active = surface_state.get_experiment(conn, "leads")
        assert active["id"] == "exp_1"
        by_cycle = surface_state.get_active_experiment_for_cycle(conn, "leads", "rank-intent")
        assert by_cycle["id"] == "exp_1"

        # the record's own "surface" field (target) must NOT leak into ownership
        assert surface_state.get_experiment(conn, "playbook") is None

        # complete it — no longer active
        surface_state.upsert_experiment(
            conn, "leads",
            {"id": "exp_1", "cycle": "rank-intent", "status": "completed",
             "decision": "keep", "completed_at": "2026-06-09T03:00:00+00:00"},
        )
        assert surface_state.get_experiment(conn, "leads") is None
        done = surface_state.get_experiment(conn, "leads", "exp_1")
        assert done["decision"] == "keep"

        listed = surface_state.list_experiments(conn, "leads")
        assert len(listed) == 1
        assert surface_state.list_experiments(conn, "leads", status="active") == []
        assert surface_state.list_experiments(conn, status="completed")[0]["id"] == "exp_1"


def test_list_state_surfaces_unions_registry_and_state():
    with connect() as conn:
        surface_state.upsert_registry(conn, "admin", {"name": "Admin"}, builtin=True)
        surface_state.set_config(conn, "leads", {"goal": "g"})
        assert surface_state.list_state_surfaces(conn) == ["admin", "leads"]


def test_runs_append_list_newest_first_and_kind_filter():
    with connect() as conn:
        first = surface_state.append_run(
            conn,
            "leads",
            summary="drafted 3 follow-ups",
            record={"ran_at": "2026-06-01T01:00:00+00:00", "found": "2 hot"},
            ran_at="2026-06-01T01:00:00+00:00",
        )
        assert first["id"]
        assert first["kind"] == "work"  # default
        assert first["status"] == "ok"  # default
        assert first["record"] == {"ran_at": "2026-06-01T01:00:00+00:00", "found": "2 hot"}

        surface_state.append_run(
            conn, "leads", kind="experiment", status="error",
            ran_at="2026-06-02T01:00:00+00:00",
        )
        surface_state.append_run(
            conn, "admin", summary="admin run", ran_at="2099-01-01T00:00:00+00:00"
        )

        leads = surface_state.list_runs(conn, "leads")
        everything = surface_state.list_runs(conn)
        limited = surface_state.list_runs(conn, "leads", limit=1)

    assert [r["kind"] for r in leads] == ["experiment", "work"]  # newest first
    assert leads[1] == first
    assert [r["surface"] for r in everything] == ["admin", "leads", "leads"]
    assert len(limited) == 1
    assert limited[0]["kind"] == "experiment"


def test_runs_count_kind_filter_and_defaults():
    with connect() as conn:
        surface_state.append_run(conn, "leads")
        surface_state.append_run(conn, "leads", kind="experiment")
        surface_state.append_run(conn, "leads", kind="bogus")  # coerces to work
        run = surface_state.append_run(conn, "leads")
        assert run["ran_at"]  # stamped via now_iso when not given

        assert surface_state.count_runs(conn, "leads") == 4
        assert surface_state.count_runs(conn, "leads", kind="work") == 3
        assert surface_state.count_runs(conn, "leads", kind="experiment") == 1
        assert surface_state.count_runs(conn, "never-ran") == 0


def test_runs_tolerant_record_and_required_surface():
    with connect() as conn:
        with pytest.raises(ValueError):
            surface_state.append_run(conn, "")
        # corrupt record TEXT degrades to {} on read
        conn.execute(
            "INSERT INTO surface_runs(id, surface, ran_at, kind, status, summary, record) "
            "VALUES(?,?,?,?,?,?,?)",
            ("bad1", "leads", "2026-06-09T00:00:00+00:00", "work", "ok", None, "{not json"),
        )
        rows = surface_state.list_runs(conn, "leads")

    assert rows[0]["record"] == {}
    assert rows[0]["summary"] is None
