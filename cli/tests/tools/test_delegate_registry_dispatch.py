"""Parity + adversarial tests for the ``delegate_task`` dispatch-seam migration (A2b lane 4).

The four agent-loop ``delegate_task`` branches (``run_agent._invoke_tool``
concurrent + sequential, ``agent.tool_executor``, ``agent.agent_runtime_helpers``)
used to funnel through ``AIAgent._dispatch_delegate_task``, which called
``delegate_task(..., parent_agent=self)`` directly — bypassing the atomic
shadow-dispatch boundary and sourcing the live parent agent through the
registered handler's ``kw.get("parent_agent")`` seam (a channel the shadow
path's JSON-only handler-kwargs snapshot can never carry).  They now route
through ``tools.delegate_tool.dispatch_delegate_task_via_registry`` onto
``model_tools.dispatch_agent_owned_registry_tool``, binding the parent agent
through a module-level :class:`DispatchCompanion` for exactly one dispatch.

Scope note (recipe): this is the DISPATCH SEAM ONLY.  Child-agent policy
inheritance, thread-pool context copying, and async daemon wake are package A4
and are not exercised here — every test patches the ``delegate_task`` entry so
no real child agent is ever spawned; the seam under attack is the parent-agent
binding and the frozen registry identity, not the delegation machinery.

These tests prove byte-identical caller behavior (the Stable bar) and lock the
fail-closed guarantees the migration must preserve.  The adapter's own hygiene
is covered by ``test_agent_owned_registry_dispatch.py``.

The filename carries a ``registry`` substring so the effect/policy/shadow/registry
sweep picks it up.
"""

import contextvars
import concurrent.futures
import json
import threading
from unittest.mock import patch

import pytest

from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry
import tools.delegate_tool as delegate_module
from tools.delegate_tool import (
    _DELEGATE_PARENT_COMPANION,
    dispatch_delegate_task_via_registry,
)


# A parent-agent stand-in.  The seam only forwards this object by reference and
# never touches it, so a plain sentinel is sufficient and keeps the test off the
# real spawn path.
class _ParentSentinel:
    def __init__(self, tag="parent"):
        self.tag = tag


# One arg per accepted ``delegate_task`` field, each a distinct value so a
# dropped/renamed field is caught.  Mirrors exactly the fields the pre-migration
# ``_dispatch_delegate_task`` forwarded.
_FULL_ARGS = {
    "goal": "do the thing",
    "context": "some context",
    "toolsets": ["web"],
    "agent": "outreach",
    "agent_id": "agent-123",
    "expected_return": "a summary",
    "handoff_reason": "specialist work",
    "priority": "high",
    "artifacts": ["file.txt"],
    "parent_run_id": "run-9",
    "tasks": None,
    "max_iterations": 7,
    "acp_command": None,
    "acp_args": None,
    "role": "leaf",
    "cancel_task_id": None,
}

_FORWARDED_FIELDS = (
    "goal",
    "context",
    "toolsets",
    "agent",
    "agent_id",
    "expected_return",
    "handoff_reason",
    "priority",
    "artifacts",
    "parent_run_id",
    "tasks",
    "max_iterations",
    "acp_command",
    "acp_args",
    "role",
    "cancel_task_id",
)


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus a durable revision."""
    policy = ExecutionPolicy.for_mode("turn-delegate-lane", "read_only")
    token = set_current_execution_policy(policy, policy_revision=9)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


def _delegate_spy(record):
    """Return a ``delegate_task`` replacement that records its call and never spawns."""

    def spy(**kwargs):
        record.append(kwargs)
        return json.dumps({"success": True, "result": "spy"})

    return spy


# =========================================================================
# Parity (recipe step 6)
# =========================================================================


class TestDelegateRegistryDispatchParity:
    def test_legacy_fallback_forwards_all_fields_and_parent_from_companion(self):
        """No durable identity → the legacy ``registry.dispatch`` payload, and
        the ``delegate_task`` entry runs exactly once with EVERY model-facing
        field forwarded byte-identically to the pre-migration direct call, plus
        the parent agent from the companion (never from dispatch kwargs)."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        parent = _ParentSentinel()
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            routed = dispatch_delegate_task_via_registry(
                dict(_FULL_ARGS), parent_agent=parent
            )

        assert json.loads(routed) == {"success": True, "result": "spy"}
        assert len(calls) == 1
        forwarded = calls[0]
        for field in _FORWARDED_FIELDS:
            assert forwarded[field] == _FULL_ARGS[field], field
        # Parent rides the companion, not the (task_id/user_task-only) kwargs.
        assert forwarded["parent_agent"] is parent
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_routed_dispatch_traverses_atomic_boundary_with_unknown_effects(
        self, monkeypatch
    ):
        """Durable identity → the call traverses ``execute_shadow`` with the
        frozen session/invocation/turn identity, a 64-char args digest, and a
        started handler — even though the delegation effect surface is UNKNOWN
        (declaration != allowance; it still runs on the observational Stable
        path)."""
        parent = _ParentSentinel()
        policy = ExecutionPolicy.for_mode("turn-delegate-routing", "read_only")
        token = set_current_execution_policy(policy, policy_revision=11)
        captured = {}
        calls = []
        real_execute_shadow = registry.execute_shadow

        def shadow_spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["name"] = name
            captured["context"] = outcome.prepared.context
            captured["args_digest"] = outcome.prepared.args_digest
            captured["effects"] = sorted(
                str(e) for e in outcome.prepared.resolved_effects
            )
            captured["started"] = outcome.started
            return outcome

        monkeypatch.setattr(registry, "execute_shadow", shadow_spy)
        try:
            with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
                result = json.loads(
                    dispatch_delegate_task_via_registry(
                        dict(_FULL_ARGS),
                        parent_agent=parent,
                        task_id="task-delegate",
                        session_id="session-delegate",
                        tool_call_id="call-delegate-shadow",
                    )
                )
        finally:
            reset_current_execution_policy(token)

        assert result == {"success": True, "result": "spy"}
        assert captured["name"] == "delegate_task"
        assert captured["started"] is True
        assert captured["effects"] == ["unknown"]
        assert captured["context"].session_id == "session-delegate"
        assert captured["context"].invocation_id == "call-delegate-shadow"
        assert captured["context"].accepted_turn_id == "turn-delegate-routing"
        assert captured["context"].policy_revision == 11
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64
        # The companion-bound parent — not any ambient one — reached the entry.
        assert len(calls) == 1
        assert calls[0]["parent_agent"] is parent

    def test_legacy_dispatch_outside_binding_returns_not_available(self):
        """A registered-handler call reached WITHOUT the companion binding and
        without a legacy ``parent_agent`` kwarg (hallucinated call, agent-less
        dispatch) returns ``delegate_task``'s byte-identical "requires a parent
        agent context" typed error and never spawns."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        result = json.loads(registry.dispatch("delegate_task", dict(_FULL_ARGS)))
        assert result["error"] == "delegate_task requires a parent agent context."
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_kw_parent_agent_channel_is_retired(self):
        """The temporary ``kw.get("parent_agent")`` fallback is GONE (A2b lane 7).

        Lane 7 migrated ``PluginContext.dispatch_tool`` onto the adapter, binding
        the parent through the companion, so the delegate handler no longer reads
        ``parent_agent`` from dispatch kwargs.  A legacy
        ``registry.dispatch("delegate_task", args, parent_agent=X)`` — the ONLY
        caller that ever used that seam — now fails closed with ``delegate_task``'s
        typed "requires a parent agent context" error and NEVER spawns, proving
        the companion is the one and only parent channel.

        The REAL ``delegate_task`` runs (unpatched): with the kw seam retired the
        handler resolves ``parent_agent=None`` and delegation's own guard fires
        BEFORE any spawn machinery, so a smuggled kw parent is provably inert."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        parent = _ParentSentinel("plugin")
        result = json.loads(
            registry.dispatch(
                "delegate_task", dict(_FULL_ARGS), parent_agent=parent
            )
        )
        assert result["error"] == "delegate_task requires a parent agent context."
        assert _DELEGATE_PARENT_COMPANION.get() is None


# =========================================================================
# Adversarial (recipe step 7)
# =========================================================================


class TestDelegateRegistryDispatchAdversarial:
    def test_parent_agent_arg_cannot_override_companion_channel(
        self, accepted_turn_policy
    ):
        """Model-controlled arguments never masquerade as the parent agent: a
        (JSON-valid) ``parent_agent`` key in args is ignored and only the
        companion-bound parent reaches the entry."""
        real_parent = _ParentSentinel("real")
        args = dict(_FULL_ARGS)
        args["parent_agent"] = "decoy-parent"  # smuggle attempt via model args
        calls = []

        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            json.loads(
                dispatch_delegate_task_via_registry(
                    args,
                    parent_agent=real_parent,
                    session_id="session-smuggle",
                    tool_call_id="call-smuggle",
                )
            )

        assert len(calls) == 1
        assert calls[0]["parent_agent"] is real_parent
        assert calls[0]["parent_agent"] != "decoy-parent"
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_nonserializable_parent_in_args_fails_closed_before_seam(
        self, accepted_turn_policy
    ):
        """An actual agent OBJECT smuggled through args can never reach the
        handler seam: canonicalization rejects the non-JSON value and the call
        fails closed (``invalid_arguments``) before any handler runs, so the
        ``delegate_task`` entry is never invoked."""
        real_parent = _ParentSentinel("real")
        args = dict(_FULL_ARGS)
        args["parent_agent"] = _ParentSentinel("smuggled")  # non-JSON object
        calls = []

        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(
                dispatch_delegate_task_via_registry(
                    args,
                    parent_agent=real_parent,
                    session_id="session-smuggle-obj",
                    tool_call_id="call-smuggle-obj",
                )
            )

        assert result["shadow_status"] == "invalid_arguments"
        assert calls == []  # entry never invoked
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_binding_cleared_after_success(self, accepted_turn_policy):
        """The parent binding is scoped to exactly one dispatch: a post-dispatch
        legacy dispatch gets "requires a parent agent context" and the companion
        reads None."""
        parent = _ParentSentinel()
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            dispatch_delegate_task_via_registry(
                dict(_FULL_ARGS),
                parent_agent=parent,
                session_id="session-clear",
                tool_call_id="call-clear",
            )
        assert _DELEGATE_PARENT_COMPANION.get() is None
        after = json.loads(registry.dispatch("delegate_task", dict(_FULL_ARGS)))
        assert after["error"] == "delegate_task requires a parent agent context."

    def test_binding_cleared_when_impl_raises(self, accepted_turn_policy):
        """Even when the ``delegate_task`` entry raises, the companion is unbound
        on the way out and the parent cannot leak to a later dispatch."""
        parent = _ParentSentinel()

        def boom(**_kwargs):
            raise RuntimeError("delegate impl exploded")

        with patch("tools.delegate_tool.delegate_task", boom):
            result = json.loads(
                dispatch_delegate_task_via_registry(
                    dict(_FULL_ARGS),
                    parent_agent=parent,
                    session_id="session-raise",
                    tool_call_id="call-raise",
                )
            )
        # Shadow path captures the handler exception into an error payload.
        assert "error" in result
        assert _DELEGATE_PARENT_COMPANION.get() is None
        after = json.loads(registry.dispatch("delegate_task", dict(_FULL_ARGS)))
        assert after["error"] == "delegate_task requires a parent agent context."

    def test_stale_registration_fails_closed_before_impl(
        self, monkeypatch, accepted_turn_policy
    ):
        """A registration replaced between prepare and start runs no handler (the
        entry is never invoked) and returns ``stale_registration``."""
        parent = _ParentSentinel()
        real_prepare = registry.prepare_shadow
        entry = registry.get_entry("delegate_task")
        calls = []

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "delegate_task":
                registry.register(
                    name="delegate_task",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                    check_fn=entry.check_fn,
                    emoji=entry.emoji,
                    dynamic_schema_overrides=entry.dynamic_schema_overrides,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(
                dispatch_delegate_task_via_registry(
                    dict(_FULL_ARGS),
                    parent_agent=parent,
                    session_id="session-stale",
                    tool_call_id="call-stale",
                )
            )

        assert result["shadow_status"] == "stale_registration"
        assert calls == []  # entry never invoked
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_exact_beta_unknown_effects_fail_before_impl(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement ``delegate_task``'s UNKNOWN effect
        surface is refused BEFORE the entry runs — no child is spawned and the
        payload is ``effect_policy_block``.  This is the same fail-closed proof
        the gate-pinned run_agent Beta test asserts for the direct branch, now
        holding through the adapter."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(
                dispatch_delegate_task_via_registry(
                    dict(_FULL_ARGS),
                    parent_agent=_ParentSentinel(),
                    session_id="session-beta",
                    tool_call_id="call-beta",
                )
            )
        assert result["shadow_status"] == "effect_policy_block"
        assert calls == []  # entry never invoked
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_exact_beta_missing_identity_fails_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a call missing a durable identity is
        refused before any handler with ``effect_context_block``."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(
                dispatch_delegate_task_via_registry(
                    dict(_FULL_ARGS), parent_agent=_ParentSentinel()
                )
            )
        assert result["shadow_status"] == "effect_context_block"
        assert calls == []
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_cross_thread_parent_isolation_under_concurrent_dispatch(self):
        """Two overlapping dispatches (the agent loop's copy_context +
        Context.run worker pattern) each bind their OWN parent agent; while both
        handlers are simultaneously inside the boundary each resolves only its
        own companion value, with no cross-contamination and both bindings
        cleared."""
        barrier = threading.Barrier(2, timeout=5)
        parents = {"a": _ParentSentinel("a"), "b": _ParentSentinel("b")}
        seen = {}
        seen_lock = threading.Lock()

        def gated_delegate(**kwargs):
            # Force both handlers to be inside the boundary at the same instant
            # with their bindings live before either records what it resolved.
            barrier.wait()
            parent = kwargs["parent_agent"]
            with seen_lock:
                seen[parent.tag] = parent
            return json.dumps({"success": True, "result": parent.tag})

        def worker(tag):
            policy = ExecutionPolicy.for_mode(
                f"turn-delegate-iso-{tag}", "read_only"
            )
            token = set_current_execution_policy(policy, policy_revision=2)
            try:
                return dispatch_delegate_task_via_registry(
                    {"goal": tag},
                    parent_agent=parents[tag],
                    session_id=f"session-iso-{tag}",
                    tool_call_id=f"call-iso-{tag}",
                )
            finally:
                reset_current_execution_policy(token)

        with patch("tools.delegate_tool.delegate_task", gated_delegate):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="delegate-iso"
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    ctx = contextvars.copy_context()
                    futures.append(pool.submit(ctx.run, worker, tag))
                results = [json.loads(f.result(timeout=10)) for f in futures]

        assert {r["result"] for r in results} == {"a", "b"}
        assert seen["a"] is parents["a"]
        assert seen["b"] is parents["b"]
        assert _DELEGATE_PARENT_COMPANION.get() is None


# =========================================================================
# Registration truthfulness (guards the migrated declaration)
# =========================================================================


class TestDelegateRegistryDeclaration:
    def test_delegate_task_is_companion_backed_and_declared_unknown(self):
        """The registered handler is the companion-backed handler, the tool
        stays on the ``delegation`` toolset (schema visibility unchanged — it is
        NOT hidden), and it carries NO effect declaration → UNKNOWN, so a
        restricted policy fails it closed rather than assuming a read."""
        entry = registry.get_entry("delegate_task")
        assert entry is not None
        assert entry.handler is delegate_module._registered_delegate_task_handler
        assert entry.toolset == "delegation"
        assert entry.effects is None
        assert entry.effect_resolver is None
        assert sorted(
            str(e) for e in registry.resolve_effects("delegate_task", _FULL_ARGS)
        ) == ["unknown"]
