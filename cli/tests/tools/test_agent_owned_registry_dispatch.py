"""Adversarial tests for the A2a agent-owned registry dispatch adapter.

``model_tools.dispatch_agent_owned_registry_tool`` is THE common seam every
agent-loop direct tool branch migrates onto (ERB-406 step 4).  These tests
attack the adapter itself: companion-binding hygiene on every exit path
(success, handler exceptions, ``CancelledError``, ``KeyboardInterrupt``),
cross-thread and cross-task isolation, sync->async bridging through
``_run_async``'s disposable-thread path, re-entrancy via stacked tokens,
smuggled process state, shadow-vs-legacy fallback parity, and
stale-registration / missing-identity fail-closed behavior.
"""

import asyncio
import concurrent.futures
import contextvars
import json
import threading

import pytest

from model_tools import dispatch_agent_owned_registry_tool
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.dispatch_companion import CompanionBindingError, DispatchCompanion
from tools.registry import registry


_TEST_COMPANION = DispatchCompanion("test_adapter_companion")


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus durable revision."""
    policy = ExecutionPolicy.for_mode("turn-adapter-adversarial", "read_only")
    token = set_current_execution_policy(policy, policy_revision=7)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class _ScratchTool:
    """Register one scratch tool for the duration of a test."""

    def __init__(self, name, handler, *, is_async=False):
        self.name = name
        registry.register(
            name=name,
            toolset="_test-adapter-adversarial",
            schema={
                "name": name,
                "description": "adapter adversarial scratch tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=handler,
            is_async=is_async,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        registry.deregister(self.name)
        return False


def _dispatch(name, args=None, *, companions=(), with_identity=True, suffix=""):
    kwargs = {"task_id": "task-adv", "companions": companions}
    if with_identity:
        kwargs["session_id"] = "session-adv" + suffix
        kwargs["tool_call_id"] = "call-adv" + suffix
    return dispatch_agent_owned_registry_tool(name, args or {}, **kwargs)


# =========================================================================
# Companion hygiene: cleared on every exit path
# =========================================================================


class TestCompanionExitPaths:
    def test_binding_visible_to_handler_and_cleared_on_success(
        self, accepted_turn_policy
    ):
        seen = []

        def handler(args, **kwargs):
            seen.append(_TEST_COMPANION.get())
            return '{"ok": true}'

        marker = object()
        with _ScratchTool("_adv_success_tool", handler):
            result = _dispatch(
                "_adv_success_tool",
                companions=(_TEST_COMPANION.bound(marker),),
            )
        assert result == '{"ok": true}'
        assert seen == [marker]
        assert _TEST_COMPANION.get() is None

    def test_binding_cleared_when_handler_raises(self, accepted_turn_policy):
        def handler(args, **kwargs):
            raise RuntimeError("handler exploded")

        with _ScratchTool("_adv_raise_tool", handler):
            result = json.loads(
                _dispatch(
                    "_adv_raise_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
            )
        assert "error" in result
        assert _TEST_COMPANION.get() is None

    def test_cancellation_propagates_and_unbinds(self, accepted_turn_policy):
        """CancelledError is BaseException: never a tool payload, always
        propagated, with the companion already unbound."""

        def handler(args, **kwargs):
            raise asyncio.CancelledError()

        with _ScratchTool("_adv_cancel_tool", handler):
            with pytest.raises(asyncio.CancelledError):
                _dispatch(
                    "_adv_cancel_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
        assert _TEST_COMPANION.get() is None

    def test_keyboard_interrupt_propagates_and_unbinds(
        self, accepted_turn_policy
    ):
        def handler(args, **kwargs):
            raise KeyboardInterrupt()

        with _ScratchTool("_adv_kbint_tool", handler):
            with pytest.raises(KeyboardInterrupt):
                _dispatch(
                    "_adv_kbint_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
        assert _TEST_COMPANION.get() is None

    def test_cancellation_on_legacy_fallback_path_unbinds(self):
        """No durable identity → legacy dispatch; hygiene must hold there too."""

        def handler(args, **kwargs):
            raise asyncio.CancelledError()

        with _ScratchTool("_adv_cancel_legacy_tool", handler):
            with pytest.raises(asyncio.CancelledError):
                _dispatch(
                    "_adv_cancel_legacy_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                    with_identity=False,
                )
        assert _TEST_COMPANION.get() is None

    def test_failed_companion_enter_unwinds_prior_bindings(
        self, accepted_turn_policy
    ):
        """A failing second companion must unwind the first before raising."""

        class _ExplodingContext:
            def __enter__(self):
                raise RuntimeError("companion enter failed")

            def __exit__(self, *exc_info):
                return False

        ran = []

        def handler(args, **kwargs):
            ran.append(True)
            return '{"ok": true}'

        with _ScratchTool("_adv_enter_fail_tool", handler):
            with pytest.raises(RuntimeError, match="companion enter failed"):
                _dispatch(
                    "_adv_enter_fail_tool",
                    companions=(
                        _TEST_COMPANION.bound("first"),
                        _ExplodingContext(),
                    ),
                )
        assert ran == []
        assert _TEST_COMPANION.get() is None


# =========================================================================
# Concurrency isolation: threads and asyncio tasks
# =========================================================================


class TestConcurrencyIsolation:
    def test_cross_thread_isolation_under_concurrent_dispatch(self):
        """Two overlapping dispatches on worker threads (the agent loop's
        copy_context + Context.run pattern) each see exactly their own
        companion binding while both are simultaneously inside the handler."""
        barrier = threading.Barrier(2, timeout=5)
        observed = {}
        observed_lock = threading.Lock()

        def handler(args, **kwargs):
            value = _TEST_COMPANION.get()
            barrier.wait()  # both bindings alive at the same instant
            with observed_lock:
                observed[threading.current_thread().name] = value
            return '{"ok": true}'

        def worker(tag):
            policy = ExecutionPolicy.for_mode(f"turn-iso-{tag}", "read_only")
            token = set_current_execution_policy(policy, policy_revision=3)
            try:
                return _dispatch(
                    "_adv_thread_iso_tool",
                    companions=(_TEST_COMPANION.bound(f"value-{tag}"),),
                    suffix=f"-{tag}",
                )
            finally:
                reset_current_execution_policy(token)

        with _ScratchTool("_adv_thread_iso_tool", handler):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="adv-iso",
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    ctx = contextvars.copy_context()
                    futures.append(pool.submit(ctx.run, worker, tag))
                results = [f.result(timeout=10) for f in futures]

        assert results == ['{"ok": true}', '{"ok": true}']
        assert sorted(observed.values()) == ["value-a", "value-b"]
        assert _TEST_COMPANION.get() is None

    def test_cross_task_asyncio_isolation(self):
        """Bindings made inside one asyncio task are invisible to sibling
        tasks and to the parent once the task completes."""
        observed = {}

        async def bind_and_probe(tag, hold, release):
            with _TEST_COMPANION.bound(f"task-{tag}"):
                release.set()
                await asyncio.wait_for(hold.wait(), timeout=5)
                observed[tag] = _TEST_COMPANION.get()

        async def main():
            gate_a = asyncio.Event()
            gate_b = asyncio.Event()
            task_a = asyncio.ensure_future(bind_and_probe("a", gate_b, gate_a))
            await asyncio.wait_for(gate_a.wait(), timeout=5)
            # Task a's binding is live right now; the parent must not see it.
            observed["parent_during"] = _TEST_COMPANION.get()
            task_b = asyncio.ensure_future(bind_and_probe("b", gate_a, gate_b))
            gate_b.set()
            await asyncio.gather(task_a, task_b)
            observed["parent_after"] = _TEST_COMPANION.get()

        asyncio.run(main())
        assert observed["a"] == "task-a"
        assert observed["b"] == "task-b"
        assert observed["parent_during"] is None
        assert observed["parent_after"] is None

    def test_async_handler_sees_binding_from_sync_context(
        self, accepted_turn_policy
    ):
        """Persistent-loop bridge path: async captured handler observes the
        companion bound around the dispatch."""
        seen = []

        async def handler(args, **kwargs):
            seen.append(_TEST_COMPANION.get())
            return '{"ok": "async"}'

        with _ScratchTool("_adv_async_sync_tool", handler, is_async=True):
            result = _dispatch(
                "_adv_async_sync_tool",
                companions=(_TEST_COMPANION.bound("async-visible"),),
            )
        assert result == '{"ok": "async"}'
        assert seen == ["async-visible"]
        assert _TEST_COMPANION.get() is None

    def test_async_handler_sees_binding_on_worker_thread_persistent_loop(self):
        """Per-thread persistent-loop bridge path (_get_worker_loop): an async
        captured handler dispatched from a non-main worker thread (no running
        loop) observes the companion binding, and the binding is cleared in
        the worker's context after the dispatch returns."""
        seen = []
        after = {}

        async def handler(args, **kwargs):
            seen.append(_TEST_COMPANION.get())
            return '{"ok": "async-worker"}'

        def worker():
            policy = ExecutionPolicy.for_mode("turn-worker-loop", "read_only")
            token = set_current_execution_policy(policy, policy_revision=5)
            try:
                result = _dispatch(
                    "_adv_async_worker_tool",
                    companions=(_TEST_COMPANION.bound("worker-visible"),),
                )
            finally:
                reset_current_execution_policy(token)
            after["binding"] = _TEST_COMPANION.get()
            return result

        with _ScratchTool("_adv_async_worker_tool", handler, is_async=True):
            results = {}
            thread = threading.Thread(
                target=lambda: results.setdefault("result", worker()),
                name="adv-worker-loop",
            )
            thread.start()
            thread.join(timeout=10)
            assert not thread.is_alive()

        assert results["result"] == '{"ok": "async-worker"}'
        assert seen == ["worker-visible"]
        assert after["binding"] is None
        assert _TEST_COMPANION.get() is None

    def test_async_handler_sees_binding_from_running_loop(self):
        """Disposable-thread bridge path (threaded gateway): _run_async must
        propagate the caller's contextvars into the fresh asyncio.run thread,
        or the companion silently vanishes for async handlers."""
        seen = []

        async def handler(args, **kwargs):
            seen.append(_TEST_COMPANION.get())
            return '{"ok": "async-loop"}'

        async def call_from_running_loop():
            policy = ExecutionPolicy.for_mode("turn-async-loop", "read_only")
            token = set_current_execution_policy(policy, policy_revision=4)
            try:
                return _dispatch(
                    "_adv_async_loop_tool",
                    companions=(_TEST_COMPANION.bound("loop-visible"),),
                )
            finally:
                reset_current_execution_policy(token)

        with _ScratchTool("_adv_async_loop_tool", handler, is_async=True):
            result = asyncio.run(call_from_running_loop())

        assert result == '{"ok": "async-loop"}'
        assert seen == ["loop-visible"]
        assert _TEST_COMPANION.get() is None


# =========================================================================
# Re-entrancy: stacked tokens are the defined behavior
# =========================================================================


class TestReentrancy:
    def test_nested_dispatch_stacks_and_restores_bindings(
        self, accepted_turn_policy
    ):
        """A handler performing a nested adapter dispatch may rebind the same
        companion; the inner dispatch sees the inner value and the outer
        binding is restored when the inner dispatch exits (LIFO)."""
        sequence = []

        def inner_handler(args, **kwargs):
            sequence.append(("inner", _TEST_COMPANION.get()))
            return '{"ok": "inner"}'

        def outer_handler(args, **kwargs):
            sequence.append(("outer-before", _TEST_COMPANION.get()))
            inner_result = dispatch_agent_owned_registry_tool(
                "_adv_reentrant_inner",
                {},
                task_id="task-adv",
                session_id="session-adv-inner",
                tool_call_id="call-adv-inner",
                companions=(_TEST_COMPANION.bound("inner-value"),),
            )
            sequence.append(("outer-after", _TEST_COMPANION.get()))
            return inner_result

        with _ScratchTool("_adv_reentrant_inner", inner_handler), _ScratchTool(
            "_adv_reentrant_outer", outer_handler
        ):
            result = _dispatch(
                "_adv_reentrant_outer",
                companions=(_TEST_COMPANION.bound("outer-value"),),
            )

        assert result == '{"ok": "inner"}'
        assert sequence == [
            ("outer-before", "outer-value"),
            ("inner", "inner-value"),
            ("outer-after", "outer-value"),
        ]
        assert _TEST_COMPANION.get() is None

    def test_cross_context_unbind_fails_typed(self):
        """Exiting a binding in a different context than the one that entered
        it raises CompanionBindingError instead of silently leaking."""
        binding = _TEST_COMPANION.bound("smuggled")
        ctx = contextvars.copy_context()
        ctx.run(binding.__enter__)
        with pytest.raises(CompanionBindingError):
            binding.__exit__(None, None, None)


# =========================================================================
# Smuggled state
# =========================================================================


class TestSmuggledState:
    def test_callable_handler_kwarg_fails_closed_on_shadow_path(
        self, accepted_turn_policy
    ):
        """Process state forced through task_id can never reach a shadow
        handler: canonicalization rejects it before start."""
        ran = []

        def handler(args, **kwargs):
            ran.append(kwargs)
            return '{"ok": true}'

        with _ScratchTool("_adv_smuggle_tool", handler):
            result = json.loads(
                dispatch_agent_owned_registry_tool(
                    "_adv_smuggle_tool",
                    {},
                    task_id=lambda: "smuggled-callable",  # type: ignore[arg-type]
                    session_id="session-adv",
                    tool_call_id="call-adv",
                )
            )
        assert ran == []
        assert result["shadow_status"] == "invalid_handler_context"

    def test_lazy_companion_read_after_dispatch_observes_nothing(
        self, accepted_turn_policy
    ):
        """A handler that leaks a lazy closure over the companion cannot read
        the binding after the dispatch has exited."""
        leaked = {}

        def handler(args, **kwargs):
            leaked["probe"] = _TEST_COMPANION.get  # lazy, hygiene violation
            return '{"ok": true}'

        with _ScratchTool("_adv_lazy_leak_tool", handler):
            _dispatch(
                "_adv_lazy_leak_tool",
                companions=(_TEST_COMPANION.bound("dispatch-scoped"),),
            )
        assert leaked["probe"]() is None

    def test_args_cannot_override_companion_channel(self, accepted_turn_policy):
        """Model-controlled arguments never masquerade as process state."""
        seen = []

        def handler(args, **kwargs):
            seen.append((args, _TEST_COMPANION.get()))
            return '{"ok": true}'

        with _ScratchTool("_adv_args_override_tool", handler):
            _dispatch(
                "_adv_args_override_tool",
                {"active_clarify_callback": "fake", "manager": "fake"},
                companions=(_TEST_COMPANION.bound("real"),),
            )
        assert seen == [
            ({"active_clarify_callback": "fake", "manager": "fake"}, "real")
        ]


# =========================================================================
# Parity and fail-closed behavior
# =========================================================================


class TestParityAndFailClosed:
    def test_shadow_and_legacy_fallback_results_are_identical(
        self, accepted_turn_policy
    ):
        """The same registered tool returns byte-identical payloads and sees
        identical args/kwargs through the shadow path (durable identity) and
        the legacy fallback path (no identity)."""
        calls = []

        def handler(args, **kwargs):
            calls.append((args, kwargs))
            return json.dumps({"echo": args})

        with _ScratchTool("_adv_parity_tool", handler):
            shadow_result = _dispatch(
                "_adv_parity_tool", {"value": 3}, with_identity=True
            )
            legacy_result = _dispatch(
                "_adv_parity_tool", {"value": 3}, with_identity=False
            )

        assert shadow_result == legacy_result == '{"echo": {"value": 3}}'
        assert len(calls) == 2
        assert calls[0] == calls[1]
        assert calls[0][0] == {"value": 3}
        assert calls[0][1] == {"task_id": "task-adv", "user_task": None}

    def test_stale_registration_fails_closed_and_unbinds(
        self, monkeypatch, accepted_turn_policy
    ):
        """A registration replaced between prepare and start never runs any
        handler, and companion hygiene holds on the blocked path."""
        ran = []

        def handler(args, **kwargs):
            ran.append(True)
            return '{"ok": true}'

        real_prepare = registry.prepare_shadow

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "_adv_stale_tool":
                entry = registry.get_entry(name)
                registry.register(
                    name=name,
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                )
            return prepared

        with _ScratchTool("_adv_stale_tool", handler):
            monkeypatch.setattr(
                registry, "prepare_shadow", replace_after_preparation
            )
            result = json.loads(
                _dispatch(
                    "_adv_stale_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
            )

        assert ran == []
        assert result["shadow_status"] == "stale_registration"
        assert _TEST_COMPANION.get() is None

    def test_exact_beta_missing_identity_fails_closed_and_unbinds(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a call without a durable identity is
        blocked before any handler or observer, with hygiene intact."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        ran = []

        def handler(args, **kwargs):
            ran.append(True)
            return '{"ok": true}'

        with _ScratchTool("_adv_beta_identity_tool", handler):
            result = json.loads(
                dispatch_agent_owned_registry_tool(
                    "_adv_beta_identity_tool",
                    {},
                    task_id="task-adv",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
            )

        assert ran == []
        assert result["shadow_status"] == "effect_context_block"
        assert _TEST_COMPANION.get() is None

    def test_exact_beta_undeclared_effects_fail_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """A tool registered without effect declarations is refused before
        start under exact-Beta enforcement even with a durable identity."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        ran = []

        def handler(args, **kwargs):
            ran.append(True)
            return '{"ok": true}'

        with _ScratchTool("_adv_beta_undeclared_tool", handler):
            result = json.loads(
                _dispatch(
                    "_adv_beta_undeclared_tool",
                    companions=(_TEST_COMPANION.bound("bound"),),
                )
            )

        assert ran == []
        assert result["shadow_status"] == "effect_policy_block"
        assert _TEST_COMPANION.get() is None
