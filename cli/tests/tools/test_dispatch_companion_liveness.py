"""Generation-stamped companion bindings: dead tasks cannot validate.

A3 hardening of the two A2a review residuals: (1) the abandoned-async-task
stale binding — ``_run_async``'s running-loop branch abandons its worker
thread on timeout while the coroutine keeps running inside a
``copy_context()`` snapshot that still *contains* the binding token; and
(2) the timeout-bounded companion lifetime.  Bindings now carry a
per-companion generation retired on unbind, so any context snapshot that
outlives its dispatch observes ``None`` — a structural impossibility of
stale companion use rather than a timing accident.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading

import pytest

import model_tools
from tools.dispatch_companion import CompanionBindingError, DispatchCompanion


class TestGenerationLiveness:
    def test_live_binding_resolves_normally(self):
        comp = DispatchCompanion("liveness_basic")
        assert comp.get() is None
        with comp.bound("VALUE") as bound_value:
            assert bound_value == "VALUE"
            assert comp.get() == "VALUE"
        assert comp.get() is None

    def test_stale_context_snapshot_cannot_resolve_after_unbind(self):
        """A copied context captured inside the binding — exactly what an
        abandoned worker holds — reads None once the dispatch unwound."""
        comp = DispatchCompanion("liveness_snapshot")
        with comp.bound("VALUE"):
            snapshot = contextvars.copy_context()
            assert snapshot.run(comp.get) == "VALUE"
        # The snapshot still CONTAINS the token, but the generation is retired.
        assert snapshot.run(comp.get) is None

    def test_concurrent_thread_with_copied_context_sees_live_binding(self):
        """The legitimate copy_context + Context.run worker pattern keeps
        working while the dispatch is in flight."""
        comp = DispatchCompanion("liveness_worker")
        observed = {}
        with comp.bound("VALUE"):
            ctx = contextvars.copy_context()
            worker = threading.Thread(
                target=lambda: observed.setdefault("value", ctx.run(comp.get))
            )
            worker.start()
            worker.join(timeout=5)
        assert observed["value"] == "VALUE"

    def test_nested_rebinding_stays_lifo_and_generation_scoped(self):
        comp = DispatchCompanion("liveness_nested")
        with comp.bound("OUTER"):
            inner_snapshot = None
            with comp.bound("INNER"):
                assert comp.get() == "INNER"
                inner_snapshot = contextvars.copy_context()
            assert comp.get() == "OUTER"
            # The inner generation is retired even though the outer lives.
            assert inner_snapshot.run(comp.get) is None
        assert comp.get() is None

    def test_cross_context_unbind_raises_and_retires_the_generation(self):
        comp = DispatchCompanion("liveness_cross_context")
        cm = comp.bound("VALUE")
        entering_ctx = contextvars.copy_context()
        entering_ctx.run(cm.__enter__)
        # Exiting in a DIFFERENT context cannot reset the entering context's
        # token — it must fail loudly, and the binding must still be dead.
        with pytest.raises(CompanionBindingError):
            cm.__exit__(None, None, None)
        assert entering_ctx.run(comp.get) is None


class TestAbandonedAsyncWorker:
    def test_abandoned_run_async_worker_loses_companion_access(
        self, monkeypatch
    ):
        """A coroutine abandoned past ELEVATE_ASYNC_TOOL_TIMEOUT_S keeps
        running in its copied context, but once the dispatch unwinds its
        companion generation is retired: the zombie observes None and must
        take the typed 'not available' path instead of acting on stale
        process state."""
        comp = DispatchCompanion("liveness_abandoned")
        monkeypatch.setenv("ELEVATE_ASYNC_TOOL_TIMEOUT_S", "0.2")
        observed = {}
        unbound = threading.Event()
        finished = threading.Event()

        async def zombie():
            observed["before"] = comp.get()
            # Blocks only the abandoned worker's private event loop.
            unbound.wait(timeout=10)
            observed["after"] = comp.get()
            finished.set()
            return "late"

        async def driver():
            with comp.bound("LIVE"):
                with pytest.raises(concurrent.futures.TimeoutError):
                    model_tools._run_async(zombie())
            unbound.set()

        asyncio.run(driver())
        assert finished.wait(timeout=10)
        assert observed["before"] == "LIVE"
        assert observed["after"] is None

    def test_timeout_env_override_is_bounded_and_default_safe(self, monkeypatch):
        """An unparsable or non-positive override falls back to the historical
        300 s contract instead of disabling the deadline."""
        monkeypatch.setenv("ELEVATE_ASYNC_TOOL_TIMEOUT_S", "not-a-number")

        async def quick():
            return "ok"

        async def driver():
            return model_tools._run_async(quick())

        assert asyncio.run(driver()) == "ok"

        monkeypatch.setenv("ELEVATE_ASYNC_TOOL_TIMEOUT_S", "-5")

        async def quick2():
            return "ok2"

        async def driver2():
            return model_tools._run_async(quick2())

        assert asyncio.run(driver2()) == "ok2"
