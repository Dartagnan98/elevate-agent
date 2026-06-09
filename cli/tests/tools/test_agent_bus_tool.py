import json

import pytest

from elevate_cli.data.connection import _reset_schema_cache
from tools.agent_bus_tool import _agent_bus_tool


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _call(body):
    return json.loads(_agent_bus_tool(body))


def test_agent_bus_task_lifecycle_uses_surface_tasks():
    created = _call(
        {
            "action": "create_task",
            "agent_id": "executive-assistant",
            "title": "Review Cortext parity",
            "description": "Check the native bus mapping.",
            "priority": "high",
        }
    )
    assert created["success"] is True
    task = created["task"]
    assert task["title"] == "Review Cortext parity"
    assert task["assignee"] == "executive-assistant"
    assert task["priority"] == "high"

    completed = _call(
        {
            "action": "complete_task",
            "agent_id": "executive-assistant",
            "task_id": task["id"],
            "result": "Mapped into native Elevate stores.",
        }
    )
    assert completed["success"] is True
    assert completed["task"]["status"] == "completed"
    assert completed["task"]["outputs"][0]["summary"] == "Mapped into native Elevate stores."


def test_agent_bus_approval_activity_and_heartbeat_are_native():
    approval = _call(
        {
            "action": "create_approval",
            "agent_id": "executive-assistant",
            "title": "Send external update",
            "category": "external-comms",
            "context": "Draft is ready for review.",
        }
    )
    assert approval["success"] is True
    assert approval["approval"]["status"] == "pending"
    assert approval["approval"]["surface"] == "executive-assistant"
    assert approval["approval"]["category"] == "external-comms"

    activity = _call(
        {
            "action": "post_activity",
            "agent_id": "executive-assistant",
            "event": "parity_check",
            "message": "Native bus parity checked.",
            "metadata": {"source": "test"},
        }
    )
    assert activity["success"] is True
    assert activity["event"]["event"] == "parity_check"

    heartbeat = _call(
        {
            "action": "update_heartbeat",
            "agent_id": "executive-assistant",
            "message": "WORKING ON: parity checks",
        }
    )
    assert heartbeat["success"] is True
    assert heartbeat["heartbeat"]["agent"] == "executive-assistant"

    listed = _call(
        {
            "action": "read_heartbeats",
            "agent_id": "executive-assistant",
        }
    )
    assert listed["success"] is True
    assert listed["items"][0]["summary"] == "WORKING ON: parity checks"


def test_agent_bus_experiment_create_run_evaluate_and_context():
    created = _call(
        {
            "action": "create_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "title": "Try native heartbeat summary",
            "hypothesis": "Visible heartbeat summaries reduce stale work.",
            "metric": "stale_items",
            "direction": "lower",
            "baseline_value": 5,
        }
    )
    assert created["success"] is True
    assert created["experiment"]["surface"] == "executive-assistant"
    assert created["experiment"]["status"] == "proposed"

    started = _call(
        {
            "action": "run_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "experiment_id": created["experiment"]["id"],
            "changes_description": "Show summaries on heartbeat cards.",
        }
    )
    assert started["success"] is True
    assert started["experiment"]["status"] == "running"
    assert started["experiment"]["changes_description"] == "Show summaries on heartbeat cards."

    evaluated = _call(
        {
            "action": "evaluate_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "experiment_id": created["experiment"]["id"],
            "measured_value": 3,
            "learning": "Useful enough to keep.",
        }
    )
    assert evaluated["success"] is True
    assert evaluated["experiment"]["decision"] == "keep"
    assert evaluated["experiment"]["status"] == "completed"
    assert evaluated["experiment"]["result_value"] == 3

    listed = _call(
        {
            "action": "list_experiments",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
        }
    )
    assert listed["success"] is True
    assert listed["experiments"]["active"] is None
    assert listed["experiments"]["history"][0]["decision"] == "keep"

    context = _call(
        {
            "action": "gather_experiment_context",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
        }
    )
    assert context["success"] is True
    assert context["context"]["keeps"] == 1
    assert "Useful enough to keep." in context["context"]["learnings"]


def test_agent_bus_cycle_management_is_native():
    created = _call(
        {
            "action": "create_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
            "metric": "stale_blockers",
            "metric_type": "quantitative",
            "direction": "lower",
            "window": "24h",
            "every_n_runs": 2,
            "measurement": "Count unresolved blockers after the heartbeat.",
            "approval_required": True,
        }
    )
    assert created["success"] is True
    assert created["surface"] == "admin"
    cycle = created["cycles"][0]
    assert cycle["name"] == "Admin stale blocker reduction"
    assert cycle["metric"] == "stale_blockers"
    assert cycle["approval_required"] is True

    modified = _call(
        {
            "action": "modify_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
            "enabled": False,
            "every_n_runs": 5,
        }
    )
    assert modified["success"] is True
    assert modified["cycles"][0]["enabled"] is False
    assert modified["cycles"][0]["every_n_runs"] == 5

    listed = _call(
        {
            "action": "list_cycles",
            "agent_id": "theta-wave",
            "surface": "admin",
        }
    )
    assert listed["success"] is True
    assert listed["cycles"][0]["name"] == "Admin stale blocker reduction"

    removed = _call(
        {
            "action": "remove_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
        }
    )
    assert removed["success"] is True
    assert removed["cycles"] == []


def test_agent_bus_memory_write_and_list_are_native():
    agent_id = "memory-bus-agent"
    written = _call(
        {
            "action": "write_memory",
            "agent_id": agent_id,
            "content": "Client prefers Friday updates. api_key=super-secret-value",
            "source": "test",
            "scopes": ["client-notes"],
        }
    )
    assert written["success"] is True
    assert written["memory"]["agent"] == agent_id
    assert written["memory"]["seeded"] == 1

    listed = _call(
        {
            "action": "list_memory",
            "agent_id": agent_id,
        }
    )
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["items"][0]["fact"] == "Client prefers Friday updates. api_key=[redacted]"
    assert "super-secret-value" not in json.dumps(listed)


def test_agent_bus_claim_audit_stale_and_archive_task_actions():
    created = _call(
        {
            "action": "create_task",
            "agent_id": "executive-assistant",
            "title": "Claimable native task",
            "assignee": "executive-assistant",
            "created_by": "orchestrator",
            "org": "ctrl",
            "due_date": "2030-01-01T00:00:00+00:00",
        }
    )
    assert created["success"] is True
    task_id = created["task"]["id"]
    assert created["task"]["createdBy"] == "orchestrator"
    assert created["task"]["dueDate"] == "2030-01-01T00:00:00+00:00"

    claimed = _call(
        {
            "action": "claim_task",
            "agent_id": "executive-assistant",
            "task_id": task_id,
        }
    )
    assert claimed["success"] is True
    assert claimed["task"]["status"] == "in_progress"
    assert claimed["task"]["claimOwner"] == "executive-assistant"

    completed = _call(
        {
            "action": "complete_task",
            "agent_id": "executive-assistant",
            "task_id": task_id,
            "result": "Task finished.",
        }
    )
    assert completed["success"] is True
    assert completed["task"]["result"] == "Task finished."

    audit = _call(
        {
            "action": "read_task_audit",
            "agent_id": "executive-assistant",
            "task_id": task_id,
        }
    )
    assert audit["success"] is True
    assert [event["event"] for event in audit["items"]] == ["create", "claim", "complete"]

    stale = _call({"action": "check_stale_tasks", "agent_id": "executive-assistant"})
    assert stale["success"] is True
    assert "stale_pending" in stale["report"]

    archive = _call({"action": "archive_tasks", "agent_id": "executive-assistant", "dry_run": True})
    assert archive["success"] is True
    assert archive["report"]["dry_run"] is True


def test_agent_bus_heartbeat_and_experiments_persist_in_surface_state():
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    _call(
        {
            "action": "update_heartbeat",
            "agent_id": "leads",
            "message": "WORKING ON: db-backed state",
        }
    )
    created = _call(
        {
            "action": "create_experiment",
            "agent_id": "leads",
            "surface": "leads",
            "title": "DB-backed experiment",
            "metric": "hot_leads",
            "cycle": "rank-intent",
            "baseline_value": 2,
        }
    )
    assert created["success"] is True
    exp_id = created["experiment"]["id"]

    with connect() as conn:
        hb = surface_state.get_heartbeat(conn, "leads")
        assert hb["summary"] == "WORKING ON: db-backed state"
        # heartbeat seeds a disabled config card for unknown surfaces
        assert surface_state.get_config(conn, "leads")["enabled"] is False
        stored = surface_state.get_experiment(conn, "leads", exp_id)
        assert stored["title"] == "DB-backed experiment"
        active = surface_state.get_active_experiment_for_cycle(conn, "leads", "rank-intent")
        assert active["id"] == exp_id


def test_agent_bus_activity_roundtrip_persists_in_surface_activity():
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    posted = _call(
        {
            "action": "post_activity",
            "agent_id": "leads",
            "event": "draft_created",
            "category": "outreach",
            "severity": "warn",
            "message": "Drafted 3 follow-ups.",
            "metadata": {"count": 3},
        }
    )
    assert posted["success"] is True
    rec = posted["event"]
    assert rec["kind"] == "agent_activity"
    assert rec["agent"] == "leads"
    assert rec["category"] == "outreach"
    assert rec["severity"] == "warn"
    assert rec["message"] == "Drafted 3 follow-ups."
    assert rec["metadata"] == {"count": 3}
    assert rec["ts"]

    listed = _call({"action": "list_activity", "agent_id": "leads"})
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["items"][0] == rec  # byte-compatible record shape

    # rows land in PG, not the jsonl
    with connect() as conn:
        rows = surface_state.list_activity(conn, agent="leads")
    assert len(rows) == 1
    assert rows[0]["event"] == "draft_created"
    assert rows[0]["metadata"]["category"] == "outreach"

    from tools.agent_bus_tool import _activity_log_path

    assert not _activity_log_path().exists()


def test_agent_bus_imports_legacy_activity_jsonl_once():
    from tools.agent_bus_tool import _activity_log_path

    path = _activity_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "kind": "agent_activity",
                "agent": "leads",
                "category": "action",
                "event": "old_event",
                "severity": "info",
                "message": "legacy row",
                "metadata": {"n": 1},
                "ts": "2026-01-01T00:00:00+00:00",
            }
        ),
        "not json {{{",
        json.dumps({"agent": "admin", "event": "older", "ts": "2025-12-31T00:00:00+00:00"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    listed = _call({"action": "list_activity"})
    assert listed["success"] is True
    assert [item["event"] for item in listed["items"]] == ["old_event", "older"]
    legacy = listed["items"][0]
    assert legacy["agent"] == "leads"
    assert legacy["message"] == "legacy row"
    assert legacy["metadata"] == {"n": 1}
    assert legacy["severity"] == "info"
    assert legacy["ts"] == "2026-01-01T00:00:00+00:00"

    marker = path.parent / (path.name + ".imported")
    assert marker.exists()
    assert path.exists()  # never deleted
    original = path.read_text(encoding="utf-8")

    # marker gates re-import: new writes don't duplicate the legacy rows
    _call({"action": "post_activity", "agent_id": "leads", "event": "new_event"})
    relisted = _call({"action": "list_activity"})
    assert relisted["count"] == 3
    assert [item["event"] for item in relisted["items"]][0] == "new_event"
    assert path.read_text(encoding="utf-8") == original  # jsonl untouched


def test_agent_bus_log_run_and_run_count():
    logged = _call(
        {
            "action": "log_run",
            "agent_id": "leads",
            "surface": "leads",
            "summary": "drafted 3 follow-ups",
            "record": {"ran_at": "2026-06-09T01:00:00+00:00", "found": "2 hot"},
        }
    )
    assert logged["success"] is True
    assert logged["run"]["surface"] == "leads"
    assert logged["run"]["kind"] == "work"
    assert logged["run"]["status"] == "ok"
    assert logged["run"]["summary"] == "drafted 3 follow-ups"
    assert logged["run"]["record"] == {"ran_at": "2026-06-09T01:00:00+00:00", "found": "2 hot"}
    assert logged["run_count"] == 1

    second = _call(
        {"action": "run_log", "surface": "leads", "agent_id": "leads",
         "kind": "experiment", "status": "error"}
    )
    assert second["success"] is True
    assert second["run"]["kind"] == "experiment"
    assert second["run_count"] == 2

    counted = _call({"action": "run_count", "surface": "leads", "agent_id": "leads"})
    assert counted["success"] is True
    assert counted["surface"] == "leads"
    assert counted["count"] == 2
    assert counted["count_by_kind"] == {"work": 1, "experiment": 1}

    # alias + surface defaulting to the calling agent
    other = _call({"action": "count_runs", "agent_id": "admin"})
    assert other["surface"] == "admin"
    assert other["count"] == 0
    assert other["count_by_kind"] == {"work": 0, "experiment": 0}

    # rows land in the DB run index
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        runs = surface_state.list_runs(conn, "leads")
    assert len(runs) == 2


def test_agent_bus_imports_legacy_history_runs_once():
    from elevate_constants import get_account_data_dir

    hist = get_account_data_dir() / "heartbeats" / "leads" / "history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "2026-01-01T00:00:00+00:00.json").write_text(
        json.dumps(
            {"ran_at": "2026-01-01T00:00:00+00:00", "did": "stuff",
             "summary": "old run", "found": "x"}
        ),
        encoding="utf-8",
    )
    # no ran_at -> falls back to the filename stem; no summary -> uses "did"
    (hist / "2026-01-02T000000.json").write_text(
        json.dumps({"did": "older stuff"}), encoding="utf-8"
    )
    (hist / "broken.json").write_text("{not json", encoding="utf-8")

    counted = _call({"action": "run_count", "surface": "leads", "agent_id": "leads"})
    assert counted["success"] is True
    assert counted["count"] == 3  # count parity with `ls history | wc -l`
    assert counted["count_by_kind"]["work"] == 3

    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        runs = {r["ran_at"]: r for r in surface_state.list_runs(conn, "leads")}
    assert runs["2026-01-01T00:00:00+00:00"]["summary"] == "old run"
    assert runs["2026-01-01T00:00:00+00:00"]["record"]["found"] == "x"
    assert runs["2026-01-02T000000"]["summary"] == "older stuff"  # did fallback + stem ran_at
    assert runs["broken"]["record"] == {}

    marker = hist / ".runs_imported"
    assert marker.exists()
    assert (hist / "broken.json").exists()  # files never deleted

    # marker gates re-import: a fresh log_run doesn't duplicate the legacy rows
    logged = _call({"action": "log_run", "surface": "leads", "agent_id": "leads",
                    "summary": "new run"})
    assert logged["run_count"] == 4
    assert len(list(hist.glob("*.json"))) == 3  # nothing written back to disk


def test_agent_bus_surface_config_get_and_update():
    fetched = _call({"action": "get_surface_config", "surface": "leads", "agent_id": "leads"})
    assert fetched["success"] is True
    assert fetched["surface"] == "leads"
    assert fetched["config"] == {}

    updated = _call(
        {
            "action": "update_surface_config",
            "surface": "leads",
            "agent_id": "leads",
            "patch": {"goal": "drain the queue", "model": "harness-default"},
        }
    )
    assert updated["success"] is True
    assert updated["config"]["goal"] == "drain the queue"

    merged = _call(
        {
            "action": "surface_config_update",
            "surface": "leads",
            "agent_id": "leads",
            "patch": {"model": "haiku"},
        }
    )
    assert merged["success"] is True
    assert merged["config"] == {"goal": "drain the queue", "model": "haiku"}

    refetched = _call({"action": "surface_config", "surface": "leads", "agent_id": "leads"})
    assert refetched["config"]["model"] == "haiku"

    missing = _call({"action": "update_surface_config", "surface": "leads", "agent_id": "leads"})
    assert "patch" in missing["error"]


def test_agent_bus_goals_get_and_update():
    defaults = _call({"action": "get_goals", "surface": "admin", "agent_id": "admin"})
    assert defaults["success"] is True
    assert defaults["goals"]["goals"] == []
    assert defaults["goals"]["bottleneck"] == ""

    updated = _call(
        {
            "action": "update_goals",
            "surface": "admin",
            "agent_id": "admin",
            "goals": {
                "bottleneck": "follow-ups",
                "daily_focus": "drain queue",
                "goals": [{"id": "g1", "title": "t", "progress": 40, "order": 0}],
            },
        }
    )
    assert updated["success"] is True
    assert updated["goals"]["bottleneck"] == "follow-ups"
    assert updated["goals"]["updated_at"]

    refetched = _call({"action": "surface_goals", "surface": "admin", "agent_id": "admin"})
    assert refetched["goals"]["goals"][0]["progress"] == 40

    missing = _call({"action": "update_goals", "surface": "admin", "agent_id": "admin"})
    assert "goals" in missing["error"]
