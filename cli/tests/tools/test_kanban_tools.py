"""Connection-lifecycle and effect tests for the Kanban tool surface."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from elevate_cli import kanban_db as kb
from elevate_cli.data import connection as connection_module
from tools import kanban_tools
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry


@pytest.fixture(autouse=True)
def _fresh_connection_state(monkeypatch):
    connection_module._reset_schema_cache()
    monkeypatch.delenv("ELEVATE_KANBAN_TASK", raising=False)
    monkeypatch.delenv("ELEVATE_KANBAN_RUN_ID", raising=False)
    monkeypatch.delenv("ELEVATE_KANBAN_CLAIM_LOCK", raising=False)
    yield
    connection_module._reset_schema_cache()


class ConnectionSentinel:
    """A connection that exposes accidental legacy manual-close calls."""

    def close(self):
        raise AssertionError("handler manually closed a context-managed connection")


class TrackingContext:
    def __init__(self, conn):
        self.conn = conn
        self.entered = 0
        self.exited = 0

    def __enter__(self):
        self.entered += 1
        return self.conn

    def __exit__(self, *_exc):
        self.exited += 1
        return None


def _patch_normal_kanban_calls(monkeypatch, conn):
    calls: list[str] = []
    results = {
        "recompute_ready": 2,
        "list_tasks": [],
        "complete_task": True,
        "latest_run": None,
        "block_task": True,
        "heartbeat_claim": None,
        "heartbeat_worker": True,
        "add_comment": 17,
        "create_task": "t_new",
        "get_task": SimpleNamespace(status="running"),
        "unblock_task": True,
        "link_tasks": None,
    }

    for name, result in results.items():
        def fake(call_conn, *_args, _name=name, _result=result, **_kwargs):
            assert call_conn is conn
            assert not isinstance(call_conn, TrackingContext)
            calls.append(_name)
            return _result

        monkeypatch.setattr(kb, name, fake)

    return calls


@pytest.mark.parametrize(
    ("name", "handler", "args", "expected_calls"),
    [
        (
            "kanban_recompute",
            kanban_tools._handle_recompute,
            {"board": "legacy-board"},
            ["recompute_ready"],
        ),
        (
            "kanban_complete",
            kanban_tools._handle_complete,
            {
                "board": "legacy-board",
                "task_id": "t_work",
                "summary": "done",
            },
            ["complete_task", "latest_run"],
        ),
        (
            "kanban_block",
            kanban_tools._handle_block,
            {
                "board": "legacy-board",
                "task_id": "t_work",
                "reason": "needs input",
            },
            ["block_task", "latest_run"],
        ),
        (
            "kanban_heartbeat",
            kanban_tools._handle_heartbeat,
            {"board": "legacy-board", "task_id": "t_work", "note": "alive"},
            ["heartbeat_claim", "heartbeat_worker"],
        ),
        (
            "kanban_comment",
            kanban_tools._handle_comment,
            {"board": "legacy-board", "task_id": "t_work", "body": "note"},
            ["add_comment"],
        ),
        (
            "kanban_create",
            kanban_tools._handle_create,
            {
                "board": "legacy-board",
                "title": "child",
                "assignee": "worker",
            },
            ["create_task", "get_task"],
        ),
        (
            "kanban_unblock",
            kanban_tools._handle_unblock,
            {"board": "legacy-board", "task_id": "t_work"},
            ["unblock_task"],
        ),
        (
            "kanban_link",
            kanban_tools._handle_link,
            {
                "board": "legacy-board",
                "parent_id": "t_parent",
                "child_id": "t_child",
            },
            ["link_tasks"],
        ),
    ],
)
def test_normal_handlers_enter_and_exit_connection_context(
    monkeypatch,
    name,
    handler,
    args,
    expected_calls,
):
    conn = ConnectionSentinel()
    contexts: list[TrackingContext] = []
    boards: list[str | None] = []

    def fake_connect(*, board=None):
        boards.append(board)
        context = TrackingContext(conn)
        contexts.append(context)
        return context

    monkeypatch.setattr(kb, "connect", fake_connect)
    calls = _patch_normal_kanban_calls(monkeypatch, conn)

    result = json.loads(handler(args))

    assert "error" not in result, (name, result)
    assert boards == ["legacy-board"]
    assert len(contexts) == 1
    assert contexts[0].entered == 1
    assert contexts[0].exited == 1
    assert calls == expected_calls
    if name == "kanban_recompute":
        assert result["promoted"] == 2


def _show_task():
    return SimpleNamespace(
        id="t_show",
        title="Inspect task",
        body="Read the current state",
        assignee="worker",
        status="running",
        tenant=None,
        priority=3,
        workspace_kind="scratch",
        workspace_path=None,
        created_by="tester",
        created_at=1,
        started_at=2,
        completed_at=None,
        result=None,
        current_run_id=4,
        model_override=None,
    )


def test_show_enters_read_only_context_and_never_calls_normal_connect(monkeypatch):
    conn = ConnectionSentinel()
    read_context = TrackingContext(conn)
    calls: list[str] = []

    def assert_conn(name, result):
        def fake(call_conn, *_args, **_kwargs):
            assert call_conn is conn
            assert not isinstance(call_conn, TrackingContext)
            calls.append(name)
            return result

        return fake

    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        lambda: read_context,
    )
    monkeypatch.setattr(
        connection_module,
        "connect",
        lambda: pytest.fail("kanban_show used general data connect"),
    )
    monkeypatch.setattr(
        kb,
        "connect",
        lambda **_kwargs: pytest.fail("kanban_show used normal kanban connect"),
    )
    monkeypatch.setattr(kb, "get_task", assert_conn("get_task", _show_task()))
    monkeypatch.setattr(kb, "list_comments", assert_conn("list_comments", []))
    monkeypatch.setattr(kb, "list_events", assert_conn("list_events", []))
    monkeypatch.setattr(kb, "list_runs", assert_conn("list_runs", []))
    monkeypatch.setattr(kb, "parent_ids", assert_conn("parent_ids", []))
    monkeypatch.setattr(kb, "child_ids", assert_conn("child_ids", []))
    monkeypatch.setattr(
        kb,
        "build_worker_context",
        assert_conn("build_worker_context", "# worker context"),
    )

    result = json.loads(
        kanban_tools._handle_show({"task_id": "t_show", "board": "ignored"})
    )

    assert result["task"]["id"] == "t_show"
    assert result["worker_context"] == "# worker context"
    assert read_context.entered == 1
    assert read_context.exited == 1
    assert calls == [
        "get_task",
        "list_comments",
        "list_events",
        "list_runs",
        "parent_ids",
        "child_ids",
        "build_worker_context",
    ]


def test_cold_show_returns_structured_error_without_bootstrap(monkeypatch):
    def unexpected_bootstrap(*_args, **_kwargs):
        raise AssertionError("kanban_show attempted write-side bootstrap")

    monkeypatch.setattr(connection_module, "_get_pool", unexpected_bootstrap)
    monkeypatch.setattr(
        connection_module,
        "_maybe_adopt_legacy",
        unexpected_bootstrap,
    )
    monkeypatch.setattr(
        connection_module.pg_server,
        "ensure_database",
        unexpected_bootstrap,
    )
    monkeypatch.setattr(connection_module, "_ensure_schema", unexpected_bootstrap)
    monkeypatch.setattr(kb, "connect", unexpected_bootstrap)
    monkeypatch.setattr(kb, "get_task", unexpected_bootstrap)

    result = json.loads(kanban_tools._handle_show({"task_id": "t_cold"}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_show_runs_inside_postgres_read_only_transaction(monkeypatch):
    with kb.connect() as conn:
        task_id = kb.create_task(
            conn,
            title="Read-only Kanban proof",
            created_by="test",
        )

    observed_modes: list[str] = []
    original_get_task = kb.get_task

    def audited_get_task(conn, requested_task_id):
        observed_modes.append(
            conn.execute("SHOW transaction_read_only").fetchone()[0]
        )
        return original_get_task(conn, requested_task_id)

    monkeypatch.setattr(kb, "get_task", audited_get_task)

    result = json.loads(kanban_tools._handle_show({"task_id": task_id}))

    assert "error" not in result
    assert result["task"]["id"] == task_id
    assert observed_modes
    assert set(observed_modes) == {"on"}


def _summary_task():
    return SimpleNamespace(
        id="t_list",
        title="List me",
        assignee="worker",
        status="todo",
        priority=0,
        tenant=None,
        workspace_kind="scratch",
        workspace_path=None,
        created_by="tester",
        created_at=1,
        started_at=None,
        completed_at=None,
        current_run_id=None,
        model_override=None,
    )


def test_list_enters_read_only_context_and_never_recomputes(monkeypatch):
    conn = ConnectionSentinel()
    read_context = TrackingContext(conn)
    calls: list[str] = []

    def assert_conn(name, result):
        def fake(call_conn, *_args, **_kwargs):
            assert call_conn is conn
            assert not isinstance(call_conn, TrackingContext)
            calls.append(name)
            return result

        return fake

    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        lambda: read_context,
    )
    monkeypatch.setattr(
        connection_module,
        "connect",
        lambda: pytest.fail("kanban_list used general data connect"),
    )
    monkeypatch.setattr(
        kb,
        "connect",
        lambda **_kwargs: pytest.fail("kanban_list used normal kanban connect"),
    )
    monkeypatch.setattr(
        kb,
        "recompute_ready",
        lambda *_a, **_k: pytest.fail("kanban_list recomputed readiness"),
    )
    monkeypatch.setattr(kb, "list_tasks", assert_conn("list_tasks", [_summary_task()]))
    monkeypatch.setattr(kb, "parent_ids", assert_conn("parent_ids", []))
    monkeypatch.setattr(kb, "child_ids", assert_conn("child_ids", []))

    result = json.loads(
        kanban_tools._handle_list({"board": "ignored", "limit": 5})
    )

    assert "error" not in result
    assert [t["id"] for t in result["tasks"]] == ["t_list"]
    assert result["count"] == 1
    assert result["truncated"] is False
    assert "promoted" not in result
    assert read_context.entered == 1
    assert read_context.exited == 1
    assert calls == ["list_tasks", "parent_ids", "child_ids"]


def test_cold_list_returns_structured_error_without_bootstrap(monkeypatch):
    def unexpected_bootstrap(*_args, **_kwargs):
        raise AssertionError("kanban_list attempted write-side bootstrap")

    monkeypatch.setattr(connection_module, "_get_pool", unexpected_bootstrap)
    monkeypatch.setattr(
        connection_module,
        "_maybe_adopt_legacy",
        unexpected_bootstrap,
    )
    monkeypatch.setattr(
        connection_module.pg_server,
        "ensure_database",
        unexpected_bootstrap,
    )
    monkeypatch.setattr(connection_module, "_ensure_schema", unexpected_bootstrap)
    monkeypatch.setattr(kb, "connect", unexpected_bootstrap)
    monkeypatch.setattr(kb, "recompute_ready", unexpected_bootstrap)
    monkeypatch.setattr(kb, "list_tasks", unexpected_bootstrap)

    result = json.loads(kanban_tools._handle_list({}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_list_runs_inside_postgres_read_only_transaction(monkeypatch):
    with kb.connect() as conn:
        task_id = kb.create_task(
            conn,
            title="Read-only Kanban list proof",
            created_by="test",
        )

    observed_modes: list[str] = []
    original_list_tasks = kb.list_tasks

    def audited_list_tasks(conn, **kwargs):
        observed_modes.append(
            conn.execute("SHOW transaction_read_only").fetchone()[0]
        )
        return original_list_tasks(conn, **kwargs)

    monkeypatch.setattr(kb, "list_tasks", audited_list_tasks)

    result = json.loads(kanban_tools._handle_list({}))

    assert "error" not in result
    assert task_id in {t["id"] for t in result["tasks"]}
    assert observed_modes
    assert set(observed_modes) == {"on"}


def test_list_never_promotes_and_recompute_is_the_explicit_mutation():
    with kb.connect() as conn:
        parent_id = kb.create_task(
            conn,
            title="Parent dependency",
            created_by="test",
        )
        child_id = kb.create_task(
            conn,
            title="Dependent child",
            created_by="test",
            parents=(parent_id,),
        )
        # Clear the dependency outside every recomputing code path,
        # simulating "parent finished since the last dispatcher tick".
        conn.execute(
            "UPDATE tasks SET status = 'done' WHERE id = ?", (parent_id,)
        )

    listing = json.loads(kanban_tools._handle_list({"limit": 200}))
    assert "error" not in listing
    assert "promoted" not in listing
    by_id = {t["id"]: t for t in listing["tasks"]}
    assert by_id[child_id]["status"] == "todo"

    # Board truth unchanged after the read: still todo, no promoted event.
    with kb.connect() as conn:
        row = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (child_id,)
        ).fetchone()
        assert row["status"] == "todo"
        events = kb.list_events(conn, child_id)
        assert all(e.kind != "promoted" for e in events)

    # Freshness is preserved through the explicit mutation path.
    recompute = json.loads(kanban_tools._handle_recompute({}))
    assert recompute["ok"] is True
    assert recompute["promoted"] == 1

    with kb.connect() as conn:
        row = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (child_id,)
        ).fetchone()
        assert row["status"] == "ready"
        events = kb.list_events(conn, child_id)
        assert any(e.kind == "promoted" for e in events)


def test_show_and_list_are_read_only_and_every_other_registration_remains_unknown():
    expected = frozenset({Effect.parse("read:kanban")})

    for name, sample_args in (
        ("kanban_show", {"task_id": "t_show"}),
        ("kanban_list", {"limit": 5}),
    ):
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.effects == expected
        assert entry.effect_resolver is None
        assert registry.resolve_effects(name, sample_args) == expected

        decision = authorize_effects(
            ExecutionPolicy.for_mode(
                f"turn-{name.replace('_', '-')}",
                ExecutionPolicyMode.READ_ONLY,
            ),
            expected,
        )
        assert decision.allowed is True
        assert decision.reason == "allowed"

    unknown = frozenset({Effect(EffectKind.UNKNOWN)})
    for name in (
        "kanban_recompute",
        "kanban_complete",
        "kanban_block",
        "kanban_heartbeat",
        "kanban_comment",
        "kanban_create",
        "kanban_unblock",
        "kanban_link",
    ):
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.effects is None
        assert entry.effect_resolver is None
        assert registry.resolve_effects(name, {}) == unknown

    denial = authorize_effects(
        ExecutionPolicy.for_mode(
            "turn-kanban-recompute",
            ExecutionPolicyMode.READ_ONLY,
        ),
        registry.resolve_effects("kanban_recompute", {}),
    )
    assert denial.allowed is False
    assert denial.reason == "unknown_effect"


def test_board_schema_admits_legacy_value_without_claiming_routing():
    description = kanban_tools.KANBAN_SHOW_SCHEMA["parameters"]["properties"][
        "board"
    ]["description"]

    assert "Legacy board slug" in description
    assert "does not select or isolate a different board" in description
    assert "ELEVATE_KANBAN_BOARD" not in description
