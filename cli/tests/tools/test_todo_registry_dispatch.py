"""Parity + adversarial tests for the ``todo`` agent-loop lane migration (A2b).

The four agent-loop ``todo`` branches (``run_agent._invoke_tool`` concurrent +
sequential, ``agent.tool_executor``, ``agent.agent_runtime_helpers``) used to
call ``todo_tool(store=self._todo_store)`` directly, bypassing the atomic
shadow-dispatch boundary and sourcing the per-session ``TodoStore`` through the
registered handler's ``kw.get("store")`` seam — a channel the shadow path's
JSON-only handler-kwargs snapshot can never carry.  They now route through
``tools.todo_tool.dispatch_todo_via_registry`` onto
``model_tools.dispatch_agent_owned_registry_tool``, binding the store through a
module-level :class:`DispatchCompanion` for exactly one dispatch.

These tests prove byte-identical caller behavior (the Stable bar) and lock the
fail-closed guarantees the migration must preserve: the store is reachable only
through the companion, only inside one dispatch, and never on a blocked/stale/
denied path or from smuggled arguments.  The adapter's own hygiene is covered
by ``test_agent_owned_registry_dispatch.py``; here the seam under attack is the
todo store specifically.
"""

import contextvars
import concurrent.futures
import json
import threading
from unittest.mock import patch

import pytest

from tools.approval import (
    Effect,
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry
from tools.todo_tool import (
    TodoStore,
    _TODO_STORE_COMPANION,
    dispatch_todo_via_registry,
    todo_tool,
)


_WRITE_ARGS = {"todos": [{"id": "1", "content": "ship it", "status": "pending"}]}
_READ_ARGS = {"merge": False}


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus a durable revision."""
    policy = ExecutionPolicy.for_mode("turn-todo-lane", "read_only")
    token = set_current_execution_policy(policy, policy_revision=9)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


# =========================================================================
# Parity (recipe step 6)
# =========================================================================


class TestTodoRegistryDispatchParity:
    def test_legacy_fallback_matches_direct_call_and_runs_impl_once(self):
        """No durable identity → legacy ``registry.dispatch`` payload, and the
        underlying ``todo_tool`` implementation runs exactly once with the
        model args plus the companion-bound store (no session/tool ids)."""
        routed_store = TodoStore()
        direct_store = TodoStore()

        calls = []
        real_todo_tool = todo_tool

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real_todo_tool(*args, **kwargs)

        with patch("tools.todo_tool.todo_tool", spy):
            routed = dispatch_todo_via_registry(dict(_WRITE_ARGS), store=routed_store)

        direct = real_todo_tool(
            todos=_WRITE_ARGS["todos"], merge=False, store=direct_store
        )

        assert routed == direct
        assert json.loads(routed)["summary"]["total"] == 1
        # Impl invoked exactly once, carrying the bound store — never kw store.
        assert len(calls) == 1
        assert calls[0]["store"] is routed_store
        assert routed_store.read() == direct_store.read()

    def test_routed_dispatch_traverses_atomic_boundary(self, monkeypatch):
        """Durable identity → the call traverses ``execute_shadow`` with the
        frozen session/invocation/turn identity, a 64-char args digest, the
        truthful ``write_local:session_plan`` effect, and a started handler
        that actually mutates the bound store."""
        store = TodoStore()
        policy = ExecutionPolicy.for_mode("turn-todo-routing", "read_only")
        token = set_current_execution_policy(policy, policy_revision=11)
        captured = {}
        real_execute_shadow = registry.execute_shadow

        def spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["name"] = name
            captured["context"] = outcome.prepared.context
            captured["args_digest"] = outcome.prepared.args_digest
            captured["effects"] = sorted(
                str(e) for e in outcome.prepared.resolved_effects
            )
            captured["started"] = outcome.started
            return outcome

        monkeypatch.setattr(registry, "execute_shadow", spy)
        try:
            result = json.loads(
                dispatch_todo_via_registry(
                    dict(_WRITE_ARGS),
                    store=store,
                    task_id="task-todo",
                    session_id="session-todo",
                    tool_call_id="call-todo-shadow",
                )
            )
        finally:
            reset_current_execution_policy(token)

        assert result["summary"]["total"] == 1
        assert captured["name"] == "todo"
        assert captured["started"] is True
        assert captured["effects"] == ["write_local:session_plan"]
        assert captured["context"].session_id == "session-todo"
        assert captured["context"].invocation_id == "call-todo-shadow"
        assert captured["context"].accepted_turn_id == "turn-todo-routing"
        assert captured["context"].policy_revision == 11
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64
        # The bound store — not any ambient one — was actually written.
        assert store.read() == [
            {"id": "1", "content": "ship it", "status": "pending"}
        ]

    def test_read_call_traverses_boundary_with_read_effect(self, monkeypatch):
        """A todo call without a ``todos`` payload resolves to the exact
        ``read:session_plan`` effect through the same boundary and leaves the
        bound store untouched."""
        store = TodoStore()
        store.write([{"id": "9", "content": "keep", "status": "in_progress"}])
        before = store.read()
        policy = ExecutionPolicy.for_mode("turn-todo-read", "read_only")
        token = set_current_execution_policy(policy, policy_revision=3)
        captured = {}
        real_execute_shadow = registry.execute_shadow

        def spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["effects"] = sorted(
                str(e) for e in outcome.prepared.resolved_effects
            )
            captured["started"] = outcome.started
            return outcome

        monkeypatch.setattr(registry, "execute_shadow", spy)
        try:
            result = json.loads(
                dispatch_todo_via_registry(
                    dict(_READ_ARGS),
                    store=store,
                    session_id="session-todo",
                    tool_call_id="call-todo-read",
                )
            )
        finally:
            reset_current_execution_policy(token)

        assert captured["effects"] == ["read:session_plan"]
        assert captured["started"] is True
        assert result["summary"]["total"] == 1
        assert store.read() == before  # read branch never mutates

    def test_legacy_dispatch_outside_binding_returns_not_available(self):
        """A registered-handler call reached WITHOUT the companion binding
        (legacy ``registry.dispatch`` without an agent, plugin dispatch,
        hallucinated calls) returns todo's byte-identical "not available"
        typed error and never touches a live plan store."""
        assert _TODO_STORE_COMPANION.get() is None
        result = registry.dispatch("todo", dict(_WRITE_ARGS))
        assert result == '{"error": "TodoStore not initialized"}'
        assert _TODO_STORE_COMPANION.get() is None


# =========================================================================
# Adversarial (recipe step 7)
# =========================================================================


class TestTodoRegistryDispatchAdversarial:
    def test_store_arg_cannot_override_companion_channel(
        self, accepted_turn_policy
    ):
        """Model-controlled arguments never masquerade as the plan store: a
        (JSON-valid) ``store`` key in args is ignored and only the
        companion-bound store is written."""
        real_store = TodoStore()
        args = dict(_WRITE_ARGS)
        args["store"] = "decoy-store"  # smuggle attempt via model args

        result = json.loads(
            dispatch_todo_via_registry(
                args,
                store=real_store,
                session_id="session-smuggle",
                tool_call_id="call-smuggle",
            )
        )

        assert result["summary"]["total"] == 1
        assert real_store.read() == [
            {"id": "1", "content": "ship it", "status": "pending"}
        ]
        assert _TODO_STORE_COMPANION.get() is None

    def test_nonserializable_store_in_args_fails_closed_before_seam(
        self, accepted_turn_policy
    ):
        """An actual store OBJECT smuggled through args can never reach the
        handler seam: canonicalization rejects the non-JSON value and the
        call fails closed (``invalid_arguments``) before any handler runs, so
        neither the smuggled store nor the real store is touched."""

        class _Tripwire(TodoStore):
            def write(self, *a, **k):  # pragma: no cover - must never run
                raise AssertionError("smuggled store was written")

        real_store = TodoStore()
        args = dict(_WRITE_ARGS)
        args["store"] = _Tripwire()  # non-JSON object smuggled via model args

        result = json.loads(
            dispatch_todo_via_registry(
                args,
                store=real_store,
                session_id="session-smuggle-obj",
                tool_call_id="call-smuggle-obj",
            )
        )

        assert result["shadow_status"] == "invalid_arguments"
        assert real_store.read() == []  # handler never ran
        assert _TODO_STORE_COMPANION.get() is None

    def test_binding_cleared_after_success(self, accepted_turn_policy):
        """The store binding is scoped to exactly one dispatch: a post-dispatch
        legacy dispatch gets "not available" and the companion reads None."""
        store = TodoStore()
        dispatch_todo_via_registry(
            dict(_WRITE_ARGS),
            store=store,
            session_id="session-clear",
            tool_call_id="call-clear",
        )
        assert _TODO_STORE_COMPANION.get() is None
        after = registry.dispatch("todo", dict(_READ_ARGS))
        assert after == '{"error": "TodoStore not initialized"}'

    def test_binding_cleared_when_impl_raises(self, accepted_turn_policy):
        """Even when the underlying ``todo_tool`` implementation raises, the
        companion is unbound on the way out and the store cannot leak to a
        later dispatch."""
        store = TodoStore()

        def boom(*_a, **_k):
            raise RuntimeError("todo impl exploded")

        with patch("tools.todo_tool.todo_tool", boom):
            result = json.loads(
                dispatch_todo_via_registry(
                    dict(_WRITE_ARGS),
                    store=store,
                    session_id="session-raise",
                    tool_call_id="call-raise",
                )
            )
        # Shadow path captures the handler exception into an error payload.
        assert "error" in result
        assert _TODO_STORE_COMPANION.get() is None
        after = registry.dispatch("todo", dict(_READ_ARGS))
        assert after == '{"error": "TodoStore not initialized"}'

    def test_stale_registration_fails_closed_before_impl(
        self, monkeypatch, accepted_turn_policy
    ):
        """A registration replaced between prepare and start runs no handler
        (the store is never written) and returns ``stale_registration``."""
        store = TodoStore()
        real_prepare = registry.prepare_shadow
        entry = registry.get_entry("todo")

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "todo":
                registry.register(
                    name="todo",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                    check_fn=entry.check_fn,
                    emoji=entry.emoji,
                    effect_resolver=entry.effect_resolver,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_todo_via_registry(
                dict(_WRITE_ARGS),
                store=store,
                session_id="session-stale",
                tool_call_id="call-stale",
            )
        )

        assert result["shadow_status"] == "stale_registration"
        assert store.read() == []  # handler never ran
        assert _TODO_STORE_COMPANION.get() is None

    def test_exact_beta_denied_write_fails_before_impl(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a todo WRITE against a read-only
        accepted turn is refused BEFORE the handler — the store is never
        written and the payload is ``effect_policy_block``.  This is the same
        fail-closed proof the gate-pinned run_agent Beta tests assert for the
        direct branch, now holding through the adapter."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        store = TodoStore()
        result = json.loads(
            dispatch_todo_via_registry(
                dict(_WRITE_ARGS),
                store=store,
                session_id="session-beta",
                tool_call_id="call-beta",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        assert store.read() == []  # handler never ran
        assert _TODO_STORE_COMPANION.get() is None

    def test_exact_beta_missing_identity_fails_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a call missing a durable identity is
        refused before any handler with ``effect_context_block``."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        store = TodoStore()
        result = json.loads(
            dispatch_todo_via_registry(dict(_WRITE_ARGS), store=store)
        )
        assert result["shadow_status"] == "effect_context_block"
        assert store.read() == []
        assert _TODO_STORE_COMPANION.get() is None

    def test_cross_thread_store_isolation_under_concurrent_dispatch(self):
        """Two overlapping dispatches (the agent loop's copy_context +
        Context.run worker pattern) each bind their OWN TodoStore; while both
        handlers are simultaneously inside the boundary each writes only to its
        own store, with no cross-contamination and both bindings cleared."""
        barrier = threading.Barrier(2, timeout=5)
        original_todo_tool = todo_tool

        def gated_todo_tool(*args, **kwargs):
            # Force both handlers to be inside the boundary at the same instant
            # with their bindings live before either writes.
            barrier.wait()
            return original_todo_tool(*args, **kwargs)

        stores = {"a": TodoStore(), "b": TodoStore()}

        def worker(tag):
            policy = ExecutionPolicy.for_mode(f"turn-todo-iso-{tag}", "read_only")
            token = set_current_execution_policy(policy, policy_revision=2)
            try:
                return dispatch_todo_via_registry(
                    {"todos": [{"id": tag, "content": tag, "status": "pending"}]},
                    store=stores[tag],
                    session_id=f"session-iso-{tag}",
                    tool_call_id=f"call-iso-{tag}",
                )
            finally:
                reset_current_execution_policy(token)

        with patch("tools.todo_tool.todo_tool", gated_todo_tool):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="todo-iso"
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    ctx = contextvars.copy_context()
                    futures.append(pool.submit(ctx.run, worker, tag))
                results = [f.result(timeout=10) for f in futures]

        assert all(json.loads(r)["summary"]["total"] == 1 for r in results)
        assert stores["a"].read() == [
            {"id": "a", "content": "a", "status": "pending"}
        ]
        assert stores["b"].read() == [
            {"id": "b", "content": "b", "status": "pending"}
        ]
        assert _TODO_STORE_COMPANION.get() is None


# =========================================================================
# Registration truthfulness (guards the migrated declaration)
# =========================================================================


class TestTodoRegistryDeclaration:
    def test_handler_swapped_to_companion_backed_registration(self):
        """The registered handler is the companion-backed handler, effects are
        still resolver-declared (no static widening), and the resolver is the
        untouched ``_todo_effect_resolver``."""
        import tools.todo_tool as todo_module

        entry = registry.get_entry("todo")
        assert entry is not None
        assert entry.handler is todo_module._registered_todo_handler
        assert entry.effects is None
        assert entry.effect_resolver is todo_module._todo_effect_resolver
        assert registry.resolve_effects("todo", _WRITE_ARGS) == frozenset(
            {Effect.parse("write_local:session_plan")}
        )
        assert registry.resolve_effects("todo", _READ_ARGS) == frozenset(
            {Effect.parse("read:session_plan")}
        )
