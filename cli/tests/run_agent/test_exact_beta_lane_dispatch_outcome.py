"""Exact-Beta agent-lane ``ToolDispatchOutcome`` truthfulness (P0 seam regression).

The exact-Beta sequential loop (``AIAgent._execute_tool_calls_sequential_impl``)
and concurrent path (``_execute_tool_calls_concurrent_impl`` / ``_run_tool``)
unwrap ``ToolDispatchOutcome`` from ``_invoke_tool(..., return_outcome=True)``.
The A2b agent-owned lane branches of ``_invoke_tool`` (todo, session_search,
memory, memory-provider, clarify, delegate_task) historically returned RAW
strings, ignoring ``return_outcome``.  Composition bug (P0): when a lane tool
PASSED the Beta gate and physically executed (todo's declared
``read:session_plan`` / ``write_local:session_plan`` effects pass the PLAN /
DRAFT_ONLY ceilings, broker-claim, and receipt), the loop's else-arm set
``_execution_blocked=True`` and never assigned ``function_result``:

* first tool in a batch  -> ``UnboundLocalError`` at the result-summary line;
* later tool in a batch  -> the PREVIOUS iteration's stale result was appended
  as this tool's tool message (cross-wired receipted writes);
* concurrent path (P2)   -> an executed, receipted lane tool was recorded as
  ``dispatch_started=False`` (inverted shadow evidence, suppressed start
  observers and batch outcomes).

These tests drive the REAL loops under exact Realtor Beta with the REAL
``todo`` lane and lock the truthful contract: executed lane tool -> its own
result delivered + ``started=True`` + broker receipt; refused lane tool ->
typed payload + ``started=False``; raw-string byte parity for every
``return_outcome``-less caller.  Extracted-copy parity
(``agent.tool_executor`` / ``agent.agent_runtime_helpers``) is locked in the
same file so the three kept-in-sync copies cannot drift apart again.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import run_agent
from run_agent import AIAgent
from elevate_state import SessionDB
from model_tools import ToolDispatchOutcome
import tools.approval as approval_module
import tools.effect_broker as effect_broker
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry
from tools.todo_tool import TodoStore


_ECHO_TOOL = "_test_beta_lane_echo"
_ECHO_TOOLSET = "_test-beta-lane-outcome"
_ECHO_PAYLOAD = json.dumps({"echo": "first-tool-distinct-payload"})
_TODO_ARGS = {"todos": [{"id": "1", "content": "ship the fix", "status": "pending"}]}
_TODO_ARGS_B = {"todos": [{"id": "2", "content": "verify the fix", "status": "pending"}]}


def _tool_call(name: str, arguments: dict, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _assistant_message(*tool_calls: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content="", tool_calls=list(tool_calls))


def _make_agent() -> AIAgent:
    """Real ``AIAgent`` surface (no __init__) with inert I/O collaborators."""
    agent = AIAgent.__new__(AIAgent)
    agent.session_id = "session-beta-lane-outcome"
    agent._interrupt_requested = False
    agent.quiet_mode = True
    agent.verbose_logging = False
    agent.log_prefix = ""
    agent.log_prefix_chars = 200
    agent.tool_delay = 0
    agent.valid_tool_names = {"todo", "session_search", _ECHO_TOOL}
    agent.context_compressor = SimpleNamespace(context_length=128_000)
    agent._current_tool = None
    agent._turns_since_memory = 0
    agent._iters_since_skill = 0
    agent._tool_worker_threads = set()
    agent._tool_worker_threads_lock = threading.Lock()
    agent._last_tool_batch_outcomes = []

    agent._todo_store = TodoStore()
    agent._session_db = None
    agent._memory_store = None
    agent._memory_manager = None
    agent._context_engine_tool_names = set()
    agent.clarify_callback = None
    agent._agent_memory_write_allowed = True
    agent._agent_memory_recall_allowed = True

    agent._checkpoint_mgr = SimpleNamespace(
        enabled=False,
        get_working_dir_for_path=lambda _p: None,
        ensure_checkpoint=lambda *_a, **_k: True,
    )
    agent._subdirectory_hints = SimpleNamespace(
        check_tool_call=lambda *_a, **_k: ""
    )
    agent._touch_activity = lambda *_a, **_k: None
    agent._apply_pending_steer_to_tool_results = lambda *_a, **_k: None

    # agent.tool_executor extracted-copy surface.
    from agent.tool_guardrails import ToolCallGuardrailController

    agent._tool_guardrails = ToolCallGuardrailController()
    agent._guardrail_block_result = lambda decision: json.dumps(
        {"error": str(decision)}
    )
    agent._append_guardrail_observation = (
        lambda _name, _args, result, **_kw: result
    )
    agent._record_file_mutation_result = lambda *_a, **_k: None
    agent._tool_result_content_for_active_model = lambda _name, result: result
    agent._get_session_db_for_recall = lambda: None
    agent._delegate_spinner = None
    agent._should_emit_quiet_tool_messages = lambda: False
    agent._should_start_quiet_spinner = lambda: False
    agent._print_fn = lambda *_a, **_k: None
    agent._vprint = lambda *_a, **_k: None

    # Direct pass-through so callback evidence is observable without a fence.
    agent._invoke_generation_callback = (
        lambda _kind, callback, *args, **kwargs: callback(*args, **kwargs)
    )
    agent.started_events: list[tuple] = []
    agent.tool_progress_callback = None
    agent.tool_start_callback = lambda *args, **kwargs: agent.started_events.append(args)
    agent.tool_complete_callback = None
    return agent


@pytest.fixture(autouse=True)
def _isolated_durable_effect_store(tmp_path, monkeypatch):
    """Route the durable effect broker + approval default store into an
    isolated per-test SQLite store under ``tmp_path`` — fail-safe hermeticity.

    These tests physically claim durable effects (the executed ``todo`` lane
    under exact Beta) with FIXED identities: ``session_id`` is always
    ``session-beta-lane-outcome`` and the invocation ids are hardcoded
    (``call-todo-1`` … ``call-helpers-1``).  Absent an override, the broker
    resolves its store lazily through
    ``tools.approval._get_default_approval_store()`` → ``SessionDB()`` →
    ``elevate_state.DEFAULT_DB_PATH``.  ``DEFAULT_DB_PATH`` is frozen at the
    first ``elevate_state`` import from ``get_elevate_home()``, and the default
    store is memoized once per process (the ``_reset_module_state`` conftest
    fixture does NOT reset it).  Under the source gate's sanitized environment
    ``ELEVATE_HOME`` is unset, so in the full 46-file suite that default
    resolves to the operator's REAL ``~/.elevate/state.db`` — this suite then
    both leaks its fixed-identity receipts into the real home AND collides on
    every rerun via ``UNIQUE(session_id, invocation_id)``
    (``effect_claim_conflict``): green-on-clean, red-on-rerun.

    Pinning ``effect_broker._store_override`` (the physical claim/receipt
    chokepoint at ``registry._start_prepared_shadow``) and the approval default
    store to a ``tmp_path`` ``SessionDB`` makes every durable write resolve
    INSIDE ``tmp_path`` regardless of ``ELEVATE_HOME`` — even when it is
    entirely unset — so the suite can never touch the real home and reruns get
    a fresh, unique store.  ``autouse`` with a dependency on ``tmp_path``/
    ``monkeypatch`` only (never on the policy fixture) installs the override
    during fixture setup, which completes before any test body — hence before
    any broker call can reach ``_resolve_store()``.  Resetting the per-store
    init memos keeps the isolated store's one-time boot activation clean.
    """
    store = SessionDB(tmp_path / "state.db")
    # Durable effect broker: overrides store resolution outright, so
    # ``_get_default_approval_store()``/``DEFAULT_DB_PATH`` are never consulted.
    monkeypatch.setattr(effect_broker, "_store_override", store)
    monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
    # Approval default store: belt-and-suspenders so no other code path can
    # lazily open the frozen ``DEFAULT_DB_PATH`` (the real home) even if it
    # bypasses the broker override.
    monkeypatch.setattr(approval_module, "_default_approval_store", store)
    monkeypatch.setattr(approval_module, "_default_approval_store_attempted", True)
    monkeypatch.setattr(approval_module, "_initialized_approval_stores", set())
    return store


@pytest.fixture
def exact_beta_plan_policy(monkeypatch, tmp_path):
    """Exact Realtor Beta + PLAN ceilings (read + write_local:session_plan)."""
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    policy = ExecutionPolicy.for_mode("turn-beta-lane-outcome", "plan")
    token = set_current_execution_policy(policy, policy_revision=7)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


@pytest.fixture
def echo_tool():
    """A plain (non-lane) registry read tool with a distinctive payload."""
    registry.register(
        _ECHO_TOOL,
        _ECHO_TOOLSET,
        {"name": _ECHO_TOOL, "description": "echo", "parameters": {"type": "object", "properties": {}}},
        lambda _args, **_kw: _ECHO_PAYLOAD,
        effects={"read"},
    )
    try:
        yield
    finally:
        registry.deregister(_ECHO_TOOL)


@pytest.fixture
def shadow_outcomes(monkeypatch):
    """Capture every immutable registry outcome the exact-Beta path produced."""
    captured = []
    real = registry.execute_prepared_shadow

    def spy(prepared_call):
        outcome = real(prepared_call)
        captured.append(outcome)
        return outcome

    monkeypatch.setattr(registry, "execute_prepared_shadow", spy)
    return captured


def _inert_result_io():
    return patch.multiple(
        run_agent,
        maybe_persist_tool_result=lambda content, **_kw: content,
        get_active_env=lambda *_a, **_k: None,
        enforce_turn_budget=lambda *_a, **_k: None,
    )


def _run_sequential(agent, message, messages):
    with _inert_result_io():
        agent._execute_tool_calls_sequential(
            message, messages, "task-beta-lane"
        )


def _run_concurrent(agent, message, messages):
    with _inert_result_io():
        agent._execute_tool_calls_concurrent(
            message, messages, "task-beta-lane"
        )


# =========================================================================
# The REAL sequential loop under exact Beta with a declared lane tool
# =========================================================================


class TestSequentialLoopLaneOutcome:
    def test_first_lane_tool_in_batch_executes_and_delivers_own_result(
        self, exact_beta_plan_policy, shadow_outcomes
    ):
        """P0 regression: pre-fix this exact scenario raised
        ``UnboundLocalError`` (``function_result`` never assigned when the lane
        branch returned a raw string) before any tool message was appended."""
        agent = _make_agent()
        messages: list[dict] = []
        message = _assistant_message(_tool_call("todo", _TODO_ARGS, "call-todo-1"))

        _run_sequential(agent, message, messages)

        assert len(messages) == 1
        tool_msg = messages[0]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call-todo-1"
        payload = json.loads(tool_msg["content"])
        assert payload["summary"]["total"] == 1
        # The bound per-agent store was physically written.
        assert [t["content"] for t in agent._todo_store.read()] == ["ship the fix"]

        # Immutable registry outcome: physically started, receipt recorded.
        todo_outcomes = [
            o for o in shadow_outcomes if o.prepared.context.invocation_id == "call-todo-1"
        ]
        assert len(todo_outcomes) == 1
        assert todo_outcomes[0].started is True
        assert getattr(todo_outcomes[0], "effect_receipt", None) is not None

        # Start-gated evidence fired exactly once for the executed lane tool.
        assert len(agent.started_events) == 1
        assert agent.started_events[0][0] == "call-todo-1"
        # Batch outcome recorded as a real (started) result, not a non-start.
        assert len(agent._last_tool_batch_outcomes) == 1
        name, _args, is_error, suffix, result_text, _baselines = (
            agent._last_tool_batch_outcomes[0]
        )
        assert name == "todo"
        assert is_error is False
        assert "[not started]" not in (suffix or "")
        assert json.loads(result_text)["summary"]["total"] == 1

    def test_two_tool_batch_second_result_is_its_own(
        self, exact_beta_plan_policy, echo_tool, shadow_outcomes
    ):
        """P0 regression (stale cross-wire): pre-fix the todo tool's message
        silently carried the PREVIOUS tool's result bytes."""
        agent = _make_agent()
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call(_ECHO_TOOL, {}, "call-echo-1"),
            _tool_call("todo", _TODO_ARGS, "call-todo-2"),
        )

        _run_sequential(agent, message, messages)

        assert [m["tool_call_id"] for m in messages] == ["call-echo-1", "call-todo-2"]
        assert messages[0]["content"] == _ECHO_PAYLOAD
        todo_payload = json.loads(messages[1]["content"])
        # The second tool's recorded result is ITS OWN, never the stale echo.
        assert messages[1]["content"] != _ECHO_PAYLOAD
        assert todo_payload["summary"]["total"] == 1
        assert [t["content"] for t in agent._todo_store.read()] == ["ship the fix"]
        # Both tools started physically and truthfully.
        started_by_call = {
            o.prepared.context.invocation_id: o.started for o in shadow_outcomes
        }
        assert started_by_call.get("call-echo-1") is True
        assert started_by_call.get("call-todo-2") is True

    def test_blocked_lane_tool_typed_payload_not_started(
        self, exact_beta_plan_policy, shadow_outcomes
    ):
        """A lane tool refused by the Beta gate (session_search: UNKNOWN
        effects) yields exactly one typed payload, no handler, no start
        evidence — and no crash before/after it in the batch."""
        agent = _make_agent()
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("session_search", {"query": "x"}, "call-search-1"),
            _tool_call("todo", _TODO_ARGS, "call-todo-3"),
        )

        _run_sequential(agent, message, messages)

        assert [m["tool_call_id"] for m in messages] == [
            "call-search-1",
            "call-todo-3",
        ]
        blocked = json.loads(messages[0]["content"])
        assert blocked["shadow_status"] == "effect_policy_block"
        assert "No handler was run" in blocked["error"]
        # No shadow outcome and no start callback for the refused call.
        assert all(
            o.prepared.context.invocation_id != "call-search-1"
            for o in shadow_outcomes
        )
        assert [e[0] for e in agent.started_events] == ["call-todo-3"]
        # The refused call is retained only as a logical non-start failure.
        non_start = [
            row for row in agent._last_tool_batch_outcomes if row[0] == "session_search"
        ]
        assert len(non_start) == 1
        assert non_start[0][2] is True
        # The following todo still executed with its own result.
        assert json.loads(messages[1]["content"])["summary"]["total"] == 1


# =========================================================================
# The REAL concurrent path under exact Beta (P2: inverted start evidence)
# =========================================================================


class TestConcurrentPathLaneOutcome:
    def test_concurrent_lane_tool_records_truthful_started_evidence(
        self, exact_beta_plan_policy, shadow_outcomes
    ):
        """P2 regression: pre-fix an executed, receipted lane tool came back
        ``dispatch_started=False`` — no start callback, no batch outcome."""
        agent = _make_agent()
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("todo", _TODO_ARGS, "call-todo-conc-1"),
            _tool_call("todo", _TODO_ARGS_B, "call-todo-conc-2"),
        )

        _run_concurrent(agent, message, messages)

        by_call = {m["tool_call_id"]: m for m in messages}
        assert set(by_call) == {"call-todo-conc-1", "call-todo-conc-2"}
        for call_id in ("call-todo-conc-1", "call-todo-conc-2"):
            assert json.loads(by_call[call_id]["content"])["summary"]["total"] >= 1

        started_by_call = {
            o.prepared.context.invocation_id: o for o in shadow_outcomes
        }
        for call_id in ("call-todo-conc-1", "call-todo-conc-2"):
            assert started_by_call[call_id].started is True
            assert getattr(started_by_call[call_id], "effect_receipt", None) is not None

        # Truthful evidence surfaced to the loop: start callbacks fired and
        # batch outcomes recorded as physically started results.
        assert sorted(e[0] for e in agent.started_events) == [
            "call-todo-conc-1",
            "call-todo-conc-2",
        ]
        recorded = {row[0]: row for row in agent._last_tool_batch_outcomes}
        assert set(recorded) == {"todo"} or len(agent._last_tool_batch_outcomes) == 2
        assert len(agent._last_tool_batch_outcomes) == 2
        for row in agent._last_tool_batch_outcomes:
            assert row[2] is False
            assert "[not started]" not in (row[3] or "")


# =========================================================================
# The lane seam itself: truthful outcomes + raw byte parity
# =========================================================================


class TestInvokeToolLaneOutcomeContract:
    def test_lane_refusals_report_started_false(self):
        """In-branch refusals (no session DB / memory policy) are typed
        ``started=False`` outcomes, and byte-identical raw strings without
        ``return_outcome`` (Stable parity)."""
        agent = _make_agent()
        agent._session_db = None
        raw = agent._invoke_tool(
            "session_search", {"query": "x"}, "task-lane", "call-raw-1"
        )
        outcome = agent._invoke_tool(
            "session_search",
            {"query": "x"},
            "task-lane",
            "call-raw-1",
            return_outcome=True,
        )
        assert isinstance(raw, str)
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.started is False
        assert outcome.block_reason == "session_db_unavailable"
        assert outcome.result == raw

        agent._agent_memory_recall_allowed = False
        raw_mem = agent._invoke_tool(
            "memory", {"action": "recall"}, "task-lane", "call-raw-2"
        )
        outcome_mem = agent._invoke_tool(
            "memory",
            {"action": "recall"},
            "task-lane",
            "call-raw-2",
            return_outcome=True,
        )
        assert isinstance(outcome_mem, ToolDispatchOutcome)
        assert outcome_mem.started is False
        assert outcome_mem.block_reason == "memory_policy_block"
        assert outcome_mem.result == raw_mem

    def test_executed_lane_dispatch_wraps_started_true_with_parity(self):
        """The todo lane returns its executed result as ``started=True`` and
        the exact same bytes as the raw-string call (Stable parity)."""
        agent = _make_agent()
        outcome = agent._invoke_tool(
            "todo", dict(_TODO_ARGS), "task-lane", "call-parity-1",
            return_outcome=True,
        )
        raw_agent = _make_agent()
        raw = raw_agent._invoke_tool(
            "todo", dict(_TODO_ARGS), "task-lane", "call-parity-1"
        )
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.started is True
        assert outcome.block_reason == ""
        assert isinstance(raw, str)
        assert outcome.result == raw

    def test_beta_preflight_refusal_at_lane_seam(self, exact_beta_plan_policy):
        """Under exact Beta a policy-refused lane tool is a typed
        ``started=False`` outcome before any lane branch can run."""
        agent = _make_agent()
        sentinel_db = object()
        agent._session_db = sentinel_db
        outcome = agent._invoke_tool(
            "session_search",
            {"query": "x"},
            "task-lane",
            "call-beta-refuse-1",
            return_outcome=True,
        )
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.started is False
        assert outcome.block_reason == "beta_preflight_block"
        assert json.loads(outcome.result)["shadow_status"] == "effect_policy_block"


# =========================================================================
# Extracted-copy parity: agent.tool_executor + agent.agent_runtime_helpers
# =========================================================================


class TestExtractedCopyParity:
    def test_tool_executor_sequential_lane_tool_executes_under_beta(
        self, exact_beta_plan_policy, shadow_outcomes
    ):
        """P3 regression: the extracted executor passes
        ``pre_tool_block_checked=True`` — pre-fix that raised ``TypeError``
        against ``AIAgent._invoke_tool`` and every Beta tool errored."""
        from agent.tool_executor import execute_tool_calls_sequential
        import agent.tool_executor as tool_executor_module

        agent = _make_agent()
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("todo", _TODO_ARGS, "call-executor-1")
        )
        with patch.object(
            tool_executor_module,
            "maybe_persist_tool_result",
            lambda content, **_kw: content,
        ):
            execute_tool_calls_sequential(
                agent, message, messages, "task-beta-lane"
            )

        assert len(messages) == 1
        content = messages[0]["content"]
        assert "unexpected keyword argument" not in content
        assert "Error executing tool" not in content
        assert json.loads(content)["summary"]["total"] == 1
        assert [t["content"] for t in agent._todo_store.read()] == ["ship the fix"]
        outcome = next(
            o for o in shadow_outcomes
            if o.prepared.context.invocation_id == "call-executor-1"
        )
        assert outcome.started is True

    def test_runtime_helpers_lane_outcomes_truthful(self, exact_beta_plan_policy):
        """The helpers copy no longer hardcodes ``started=True``: executed
        lane dispatches carry the adapter's truthful outcome; refusals are
        ``started=False``."""
        from agent.agent_runtime_helpers import invoke_tool

        agent = _make_agent()
        agent._get_session_db_for_recall = lambda: None
        executed = invoke_tool(
            agent, "todo", dict(_TODO_ARGS), "task-beta-lane",
            tool_call_id="call-helpers-1", return_outcome=True,
        )
        assert isinstance(executed, ToolDispatchOutcome)
        assert executed.started is True
        assert json.loads(executed.result)["summary"]["total"] == 1

        refused = invoke_tool(
            agent, "session_search", {"query": "x"}, "task-beta-lane",
            tool_call_id="call-helpers-2", return_outcome=True,
        )
        assert isinstance(refused, ToolDispatchOutcome)
        assert refused.started is False
        assert json.loads(refused.result)["shadow_status"] == "effect_policy_block"

    def test_runtime_helpers_session_db_refusal_not_started(self):
        """The no-session-DB refusal is evidence of a NON-start (was
        inverted to ``started=True`` in the helpers copy)."""
        from agent.agent_runtime_helpers import invoke_tool

        agent = _make_agent()
        agent._get_session_db_for_recall = lambda: None
        refused = invoke_tool(
            agent, "session_search", {"query": "x"}, "task-lane",
            tool_call_id="call-helpers-3", return_outcome=True,
        )
        assert isinstance(refused, ToolDispatchOutcome)
        assert refused.started is False
        assert refused.block_reason == "session_db_unavailable"
        payload = json.loads(refused.result)
        assert payload["success"] is False

    def test_runtime_helpers_raw_parity_without_return_outcome(self):
        """Raw-string behavior of the helpers copy is byte-identical when
        ``return_outcome`` is absent (Stable parity for the whole family)."""
        from agent.agent_runtime_helpers import invoke_tool

        raw_agent = _make_agent()
        raw = invoke_tool(
            raw_agent, "todo", dict(_TODO_ARGS), "task-lane",
            tool_call_id="call-helpers-4",
        )
        outcome_agent = _make_agent()
        outcome = invoke_tool(
            outcome_agent, "todo", dict(_TODO_ARGS), "task-lane",
            tool_call_id="call-helpers-4", return_outcome=True,
        )
        assert isinstance(raw, str)
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.result == raw


# =========================================================================
# Fail-closed else-arms of the exact-Beta unwrap (legacy override stubs)
# =========================================================================


class TestFailClosedRawArms:
    def test_raw_legacy_override_delivers_own_bytes_per_call_blocked(
        self, exact_beta_plan_policy
    ):
        """A legacy ``_invoke_tool`` override returning RAW strings under
        exact Beta fails closed: each call's own bytes are delivered (never
        unbound, never a stale prior result) with zero start evidence."""
        agent = _make_agent()
        raw_results = iter(['{"legacy": "raw-1"}', '{"legacy": "raw-2"}'])
        agent._invoke_tool = lambda *_a, **_k: next(raw_results)
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("todo", _TODO_ARGS, "call-raw-arm-1"),
            _tool_call("todo", _TODO_ARGS_B, "call-raw-arm-2"),
        )

        _run_sequential(agent, message, messages)

        assert [m["tool_call_id"] for m in messages] == [
            "call-raw-arm-1",
            "call-raw-arm-2",
        ]
        assert messages[0]["content"] == '{"legacy": "raw-1"}'
        assert messages[1]["content"] == '{"legacy": "raw-2"}'
        # Raw results are not physical-start proof: no start evidence at all.
        assert agent.started_events == []
        assert agent._todo_store.read() == []

    def test_none_legacy_override_yields_typed_fail_closed_payload(
        self, exact_beta_plan_policy
    ):
        """A legacy override returning ``None`` under exact Beta yields the
        typed no-outcome payload instead of crashing the loop."""
        agent = _make_agent()
        agent._invoke_tool = lambda *_a, **_k: None
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("todo", _TODO_ARGS, "call-none-arm-1")
        )

        _run_sequential(agent, message, messages)

        assert len(messages) == 1
        payload = json.loads(messages[0]["content"])
        assert "no exact-Beta dispatch outcome" in payload["error"]
        assert agent.started_events == []

    def test_tool_executor_raw_override_fails_closed_with_own_bytes(
        self, exact_beta_plan_policy
    ):
        """The extracted executor's mirror arm has the same fail-closed
        always-assign contract."""
        from agent.tool_executor import execute_tool_calls_sequential
        import agent.tool_executor as tool_executor_module

        agent = _make_agent()
        raw_results = iter(['{"legacy": "raw-A"}', '{"legacy": "raw-B"}'])
        agent._invoke_tool = lambda *_a, **_k: next(raw_results)
        messages: list[dict] = []
        message = _assistant_message(
            _tool_call("todo", _TODO_ARGS, "call-exec-raw-1"),
            _tool_call("todo", _TODO_ARGS_B, "call-exec-raw-2"),
        )
        with patch.object(
            tool_executor_module,
            "maybe_persist_tool_result",
            lambda content, **_kw: content,
        ):
            execute_tool_calls_sequential(
                agent, message, messages, "task-beta-lane"
            )

        assert [m["tool_call_id"] for m in messages] == [
            "call-exec-raw-1",
            "call-exec-raw-2",
        ]
        assert messages[0]["content"] == '{"legacy": "raw-A"}'
        assert messages[1]["content"] == '{"legacy": "raw-B"}'
        assert agent.started_events == []


# =========================================================================
# Wrapper / adapter byte parity for return_outcome-less callers
# =========================================================================


class TestAdapterOutcomeParity:
    def test_dispatch_agent_owned_registry_tool_outcome_parity(self):
        """The shared adapter returns the exact same result bytes raw and
        wrapped, with truthful started evidence."""
        from tools.todo_tool import dispatch_todo_via_registry

        raw = dispatch_todo_via_registry(
            dict(_TODO_ARGS),
            store=TodoStore(),
            task_id="task-adapter",
            session_id="session-adapter",
            tool_call_id="call-adapter-1",
        )
        outcome = dispatch_todo_via_registry(
            dict(_TODO_ARGS),
            store=TodoStore(),
            task_id="task-adapter",
            session_id="session-adapter",
            tool_call_id="call-adapter-1",
            return_outcome=True,
        )
        assert isinstance(raw, str)
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.started is True
        assert outcome.result == raw

    def test_memory_provider_wrapper_refusals_truthful(self):
        from agent.memory_manager import dispatch_memory_tool_via_registry

        refused = dispatch_memory_tool_via_registry(
            None, "fact_store", {"content": "x"}, return_outcome=True
        )
        assert isinstance(refused, ToolDispatchOutcome)
        assert refused.started is False
        assert refused.block_reason == "no_memory_provider"
        raw = dispatch_memory_tool_via_registry(None, "fact_store", {"content": "x"})
        assert raw == refused.result

    def test_memory_provider_direct_fallback_fails_closed_under_beta(
        self, exact_beta_plan_policy
    ):
        """An unroutable provider tool cannot execute ungoverned under exact
        Beta when physical-start proof is demanded."""
        from agent.memory_manager import dispatch_memory_tool_via_registry

        class _Manager:
            def __init__(self):
                self.calls = []

            def ensure_registry_routed_tools_registered(self):
                return None

            def has_tool(self, _name):
                return True

            def handle_tool_call(self, name, args, **kwargs):
                self.calls.append((name, args, kwargs))
                return json.dumps({"success": True})

        manager = _Manager()
        outcome = dispatch_memory_tool_via_registry(
            manager,
            "_test_unroutable_provider_tool",
            {"content": "x"},
            session_id="session-adapter",
            tool_call_id="call-adapter-2",
            return_outcome=True,
        )
        assert isinstance(outcome, ToolDispatchOutcome)
        assert outcome.started is False
        assert outcome.block_reason == "registry_routing_unavailable"
        # The provider was NEVER invoked: no ungoverned side effects.
        assert manager.calls == []
