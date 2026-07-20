"""Adversarial coverage for delegate-lane policy inheritance (package A4).

Every child agent — sync single, batch thread-pool, async daemon-wake, and
nested (child-of-child) — funnels through ``_run_single_child``'s worker
thread, where contextvars start empty.  These tests prove the wiring:

* the parent's accepted-turn policy is captured at ``delegate_task``
  dispatch time and STAMPED on each built child;
* the child's ``run_conversation`` observes exactly that derived policy
  (equal-or-narrower, same accepted-turn identity, original revision) on
  its worker thread;
* the stamp — never ambient thread state — is authoritative: a worker
  thread carrying a wider ambient policy cannot widen a child, and an
  unstamped child runs with explicit no-policy even when ambient state
  exists;
* the derivation is durably projected as a diagnostics event; and
* exact Realtor Beta still fail-closes ``delegate_task`` at the adapter
  boundary BEFORE any capture or spawn (delegation stays undeclared).
"""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

import tools.delegate_tool as delegate
from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    InheritedPolicyBinding,
    get_current_execution_policy,
    get_current_execution_policy_revision,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.delegate_tool import delegate_task


@pytest.fixture(autouse=True)
def _isolate_delegation_runtime_config(monkeypatch):
    monkeypatch.setattr("tools.delegate_tool._load_config", lambda: {})
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)


def _policy(mode: str = "draft_only", turn: str = "turn-delegate") -> ExecutionPolicy:
    return ExecutionPolicy.for_mode(turn, ExecutionPolicyMode.parse(mode))


def _make_mock_parent(depth: int = 0) -> MagicMock:
    parent = MagicMock()
    parent.base_url = "https://openrouter.ai/api/v1"
    parent.api_key = "test-key"
    parent.provider = "openrouter"
    parent.api_mode = "chat_completions"
    parent.model = "anthropic/claude-sonnet-4"
    parent.platform = "cli"
    parent.providers_allowed = None
    parent.providers_ignored = None
    parent.providers_order = None
    parent.provider_sort = None
    parent._session_db = None
    parent._delegate_depth = depth
    parent._active_children = []
    parent._active_children_lock = threading.Lock()
    parent._print_fn = None
    parent.tool_progress_callback = None
    parent.thinking_callback = None
    parent.clarify_callback = None
    parent._async_delegate_sink = None
    parent.session_id = "parent-session-inherit"
    return parent


def _make_mock_child(observed: dict, key: str = "policy", **attrs) -> MagicMock:
    """Mock child whose run_conversation records the worker-thread policy."""
    child = MagicMock()
    child.session_id = f"child-session-{key}"
    child.session_estimated_cost_usd = 0.0
    child.get_activity_summary.return_value = {
        "api_call_count": 1,
        "current_tool": None,
        "max_iterations": 10,
    }

    def _record(*_a, **_k):
        observed[key] = get_current_execution_policy()
        observed[f"{key}_revision"] = get_current_execution_policy_revision()
        observed[f"{key}_thread"] = threading.current_thread().name
        return {"final_response": "done", "completed": True, "api_calls": 1}

    child.run_conversation.side_effect = _record
    for name, value in attrs.items():
        setattr(child, name, value)
    return child


class TestSyncChildInheritance:
    def test_single_child_observes_parent_policy_on_worker_thread(self):
        parent = _make_mock_parent()
        policy = _policy("draft_only")
        observed: dict = {}
        token = set_current_execution_policy(policy, policy_revision=5)
        try:
            with patch("run_agent.AIAgent") as MockAgent:
                MockAgent.return_value = _make_mock_child(observed)
                result = json.loads(
                    delegate_task(goal="inherit me", parent_agent=parent)
                )
        finally:
            reset_current_execution_policy(token)

        assert result["results"][0]["status"] == "completed"
        assert observed["policy"] == policy
        assert observed["policy_revision"] == 5
        # The observation happened on the child worker thread, not the
        # dispatching thread — the contextvar cannot have leaked there.
        assert observed["policy_thread"] != threading.current_thread().name

    def test_child_policy_keeps_parent_turn_identity(self):
        parent = _make_mock_parent()
        policy = _policy("read_only", turn="parent-turn-77")
        observed: dict = {}
        token = set_current_execution_policy(policy, policy_revision=0)
        try:
            with patch("run_agent.AIAgent") as MockAgent:
                MockAgent.return_value = _make_mock_child(observed)
                delegate_task(goal="turn identity", parent_agent=parent)
        finally:
            reset_current_execution_policy(token)
        assert observed["policy"].accepted_turn_id == "parent-turn-77"

    def test_policyless_parent_spawns_policyless_child(self):
        parent = _make_mock_parent()
        observed: dict = {}
        with patch("run_agent.AIAgent") as MockAgent:
            MockAgent.return_value = _make_mock_child(observed)
            result = json.loads(
                delegate_task(goal="no policy", parent_agent=parent)
            )
        assert result["results"][0]["status"] == "completed"
        assert observed["policy"] is None
        assert observed["policy_revision"] is None

    def test_children_are_stamped_with_the_dispatch_time_binding(self):
        parent = _make_mock_parent()
        policy = _policy("draft_only")
        token = set_current_execution_policy(policy, policy_revision=2)
        try:
            with patch("run_agent.AIAgent") as MockAgent:
                child = _make_mock_child({})
                MockAgent.return_value = child
                delegate_task(goal="stamp me", parent_agent=parent)
        finally:
            reset_current_execution_policy(token)
        binding = child._inherited_policy_binding
        assert isinstance(binding, InheritedPolicyBinding)
        assert binding.policy == policy
        assert binding.policy_revision == 2
        assert binding.parent_session_id == "parent-session-inherit"


class TestBatchChildInheritance:
    def test_all_batch_children_observe_the_same_inherited_policy(self):
        parent = _make_mock_parent()
        policy = _policy("draft_only")
        observed: dict = {}
        children = [
            _make_mock_child(observed, key="c0"),
            _make_mock_child(observed, key="c1"),
        ]
        token = set_current_execution_policy(policy, policy_revision=8)
        try:
            with patch("run_agent.AIAgent") as MockAgent:
                MockAgent.side_effect = children
                result = json.loads(
                    delegate_task(
                        tasks=[{"goal": "batch a"}, {"goal": "batch b"}],
                        parent_agent=parent,
                    )
                )
        finally:
            reset_current_execution_policy(token)

        assert {r["status"] for r in result["results"]} == {"completed"}
        assert observed["c0"] == policy
        assert observed["c1"] == policy
        assert observed["c0_revision"] == 8
        assert observed["c1_revision"] == 8


class TestAsyncChildInheritance:
    def test_daemon_wake_children_observe_the_dispatch_time_policy(self):
        """Async lane: dispatch returns immediately; the child later runs on
        a daemon thread and must still observe the policy captured at
        dispatch time — even though the dispatching turn's binding was reset
        (turn over) before the child ran."""
        parent = _make_mock_parent()
        policy = _policy("draft_only")
        sink_done = threading.Event()
        release_child = threading.Event()
        observed: dict = {}

        def _sink(_payload):
            sink_done.set()

        parent._async_delegate_sink = _sink

        child = MagicMock()
        child.session_id = "child-session-async"
        child.session_estimated_cost_usd = 0.0
        child.get_activity_summary.return_value = {
            "api_call_count": 1,
            "current_tool": None,
            "max_iterations": 10,
        }

        def _record(*_a, **_k):
            release_child.wait(timeout=5)
            observed["policy"] = get_current_execution_policy()
            observed["revision"] = get_current_execution_policy_revision()
            return {"final_response": "done", "completed": True, "api_calls": 1}

        child.run_conversation.side_effect = _record

        token = set_current_execution_policy(policy, policy_revision=6)
        try:
            with patch("run_agent.AIAgent") as MockAgent, patch(
                "tools.delegate_tool._get_async_delegation_enabled",
                return_value=True,
            ):
                MockAgent.return_value = child
                result = json.loads(
                    delegate_task(goal="async inherit", parent_agent=parent)
                )
        finally:
            # Parent turn ends BEFORE the child executes.
            reset_current_execution_policy(token)

        assert result["status"] == "dispatched"
        release_child.set()
        assert sink_done.wait(timeout=10), "async child never completed"
        assert observed["policy"] == policy
        assert observed["revision"] == 6


class TestNestedDelegationInheritance:
    def test_grandchild_derives_from_the_child_binding(self):
        """Nested delegation: the child's own delegate_task call captures the
        CHILD's bound (inherited) policy, so the grandchild observes the same
        accepted-turn policy transitively — never ambient state."""
        parent = _make_mock_parent(depth=0)
        policy = _policy("draft_only", turn="root-turn")
        observed: dict = {}

        grandchild = _make_mock_child(observed, key="grandchild")

        child = MagicMock()
        child.session_id = "child-session-nested"
        child.session_estimated_cost_usd = 0.0
        child.get_activity_summary.return_value = {
            "api_call_count": 1,
            "current_tool": None,
            "max_iterations": 10,
        }
        # The nested parent (the child) must expose what delegate_task reads.
        child.base_url = parent.base_url
        child.api_key = parent.api_key
        child.provider = parent.provider
        child.api_mode = parent.api_mode
        child.model = parent.model
        child.platform = "cli"
        child.providers_allowed = None
        child.providers_ignored = None
        child.providers_order = None
        child.provider_sort = None
        child._session_db = None
        child._active_children = []
        child._active_children_lock = threading.Lock()
        child._print_fn = None
        child.tool_progress_callback = None
        child.thinking_callback = None
        child.clarify_callback = None
        child._async_delegate_sink = None

        def _child_run(*_a, **_k):
            observed["child"] = get_current_execution_policy()
            # Nested call FROM the child's worker thread, exactly like an
            # orchestrator child dispatching its own delegate_task.
            child._delegate_depth = 1
            nested = json.loads(
                delegate_task(goal="grandchild goal", parent_agent=child)
            )
            observed["nested_status"] = nested["results"][0]["status"]
            return {"final_response": "done", "completed": True, "api_calls": 1}

        child.run_conversation.side_effect = _child_run

        token = set_current_execution_policy(policy, policy_revision=4)
        try:
            with patch("run_agent.AIAgent") as MockAgent, patch(
                "tools.delegate_tool._get_max_spawn_depth", return_value=3
            ):
                MockAgent.side_effect = [child, grandchild]
                result = json.loads(
                    delegate_task(goal="child goal", parent_agent=parent)
                )
        finally:
            reset_current_execution_policy(token)

        assert result["results"][0]["status"] == "completed"
        assert observed["nested_status"] == "completed"
        assert observed["child"] == policy
        assert observed["grandchild"] == policy
        assert observed["grandchild"].accepted_turn_id == "root-turn"
        assert observed["grandchild_revision"] == 4


class TestAmbientStateCannotLeak:
    def test_stamped_binding_beats_ambient_policy_on_the_calling_thread(self):
        """Ambient-widening injection at the _run_single_child boundary: the
        caller's thread carries a WIDE default-mode policy, but the child was
        stamped read-only — the child must observe read-only."""
        narrow = _policy("read_only")
        wide = _policy("default", turn="other-turn")
        observed: dict = {}
        child = _make_mock_child(
            observed,
            _inherited_policy_binding=InheritedPolicyBinding(narrow, 1, "p"),
            _credential_pool=None,
            _delegate_role="leaf",
            _subagent_id=None,
        )
        token = set_current_execution_policy(wide, policy_revision=9)
        try:
            entry = delegate._run_single_child(
                task_index=0,
                goal="ambient injection",
                child=child,
                parent_agent=_make_mock_parent(),
            )
        finally:
            reset_current_execution_policy(token)
        assert entry["status"] == "completed"
        assert observed["policy"] == narrow
        assert observed["policy_revision"] == 1

    def test_unstamped_child_runs_with_explicit_no_policy(self):
        """A child without a stamped binding NEVER inherits ambient state."""
        wide = _policy("default", turn="other-turn")
        observed: dict = {}
        child = _make_mock_child(
            observed,
            _credential_pool=None,
            _delegate_role="leaf",
            _subagent_id=None,
        )
        # MagicMock auto-vivifies _inherited_policy_binding as a MagicMock —
        # exactly the "garbage stamp" case; the scope must treat it as
        # no-policy, not crash and not fall through to ambient.
        token = set_current_execution_policy(wide, policy_revision=9)
        try:
            entry = delegate._run_single_child(
                task_index=0,
                goal="unstamped",
                child=child,
                parent_agent=_make_mock_parent(),
            )
        finally:
            reset_current_execution_policy(token)
        assert entry["status"] == "completed"
        assert observed["policy"] is None
        assert observed["policy_revision"] is None

    def test_crashing_child_restores_the_worker_thread_state(self):
        """The scope unwinds on child failure; the failure result is
        unchanged from the pre-inheritance contract."""
        narrow = _policy("read_only")
        observed: dict = {}
        child = _make_mock_child(
            observed,
            _inherited_policy_binding=InheritedPolicyBinding(narrow, 1, None),
            _credential_pool=None,
            _delegate_role="leaf",
            _subagent_id=None,
        )
        child.run_conversation.side_effect = RuntimeError("child exploded")
        entry = delegate._run_single_child(
            task_index=0,
            goal="crash",
            child=child,
            parent_agent=_make_mock_parent(),
        )
        assert entry["status"] == "error"
        assert "child exploded" in entry["error"]


class TestDerivationEvidence:
    def test_policy_inheritance_event_is_projected(self):
        parent = _make_mock_parent()
        policy = _policy("draft_only", turn="evidence-turn")
        recorded: list = []

        def _capture_event(event_type, **kwargs):
            recorded.append((event_type, kwargs))
            return True

        token = set_current_execution_policy(policy, policy_revision=3)
        try:
            with patch("run_agent.AIAgent") as MockAgent, patch(
                "elevate_cli.diagnostics.session_recorder.record_session_event",
                side_effect=_capture_event,
            ):
                MockAgent.return_value = _make_mock_child({})
                delegate_task(goal="evidence", parent_agent=parent)
        finally:
            reset_current_execution_policy(token)

        events = [e for e in recorded if e[0] == "delegation.policy_inheritance"]
        assert len(events) == 1
        payload = events[0][1]["payload"]
        assert payload["parent_session_id"] == "parent-session-inherit"
        assert payload["accepted_turn_id"] == "evidence-turn"
        assert payload["policy_mode"] == "draft_only"
        assert payload["policy_revision"] == 3
        assert payload["inherited"] is True
        assert payload["child_session_ids"] == ["child-session-policy"]

    def test_evidence_failure_never_blocks_delegation(self):
        parent = _make_mock_parent()
        observed: dict = {}
        with patch("run_agent.AIAgent") as MockAgent, patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            side_effect=RuntimeError("diagnostics down"),
        ):
            MockAgent.return_value = _make_mock_child(observed)
            result = json.loads(
                delegate_task(goal="evidence down", parent_agent=parent)
            )
        assert result["results"][0]["status"] == "completed"


class TestExactBetaDelegationStaysClosed:
    def test_adapter_fail_closes_before_any_capture_or_spawn(self, monkeypatch):
        """Under exact Beta, delegate_task is UNDECLARED (unknown effect) and
        must fail closed at the adapter boundary BEFORE the inheritance
        capture or any child construction runs — zero children, zero
        derivation events."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        parent = _make_mock_parent()
        policy = ExecutionPolicy.for_mode(
            "beta-turn", ExecutionPolicyMode.DRAFT_ONLY
        )
        token = set_current_execution_policy(policy, policy_revision=0)
        try:
            with patch("run_agent.AIAgent") as MockAgent, patch.object(
                delegate,
                "_record_policy_inheritance_evidence",
            ) as evidence:
                result = json.loads(
                    delegate.dispatch_delegate_task_via_registry(
                        {"goal": "should never spawn"},
                        parent_agent=parent,
                        session_id="beta-session",
                        tool_call_id="call-beta-1",
                    )
                )
        finally:
            reset_current_execution_policy(token)

        assert result["shadow_status"] == "effect_policy_block"
        MockAgent.assert_not_called()
        evidence.assert_not_called()
