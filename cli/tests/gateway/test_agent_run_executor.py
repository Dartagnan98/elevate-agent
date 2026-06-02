"""G1 — agent runs get a dedicated, bounded thread pool.

Agent conversations (`agent.run_conversation`) can run for many minutes. If
they share asyncio's default executor with vision / MCP / status / dashboard
offloads, a few stuck turns drain the pool and everything else "times out."
The dedicated `elevate-agent-run` pool isolates that blast radius.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from gateway import run as gateway_run


@pytest.fixture(autouse=True)
def _reset_agent_executor():
    """Force a fresh, lazily-created executor per test, then restore."""
    old = gateway_run._AGENT_RUN_EXECUTOR
    gateway_run._AGENT_RUN_EXECUTOR = None
    yield
    created = gateway_run._AGENT_RUN_EXECUTOR
    if created is not None and created is not old:
        created.shutdown(wait=False, cancel_futures=True)
    gateway_run._AGENT_RUN_EXECUTOR = old


def test_executor_is_bounded_named_singleton(monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_RUN_WORKERS", "3")
    ex1 = gateway_run._get_agent_run_executor()
    ex2 = gateway_run._get_agent_run_executor()
    assert ex1 is ex2  # one pool for the whole process
    assert ex1._max_workers == 3
    assert ex1._thread_name_prefix == "elevate-agent-run"


def test_executor_default_worker_count(monkeypatch):
    monkeypatch.delenv("ELEVATE_AGENT_RUN_WORKERS", raising=False)
    assert gateway_run._get_agent_run_executor()._max_workers == 6


@pytest.mark.parametrize("val", ["0", "-4", "abc", ""])
def test_executor_bad_worker_count_floors_to_at_least_one(monkeypatch, val):
    monkeypatch.setenv("ELEVATE_AGENT_RUN_WORKERS", val)
    assert gateway_run._get_agent_run_executor()._max_workers >= 1


def test_dispatch_helper_runs_on_dedicated_pool():
    """The real agent-run dispatch helper must execute on the dedicated pool.

    The helper uses no instance state, so we can invoke it on a bare
    GatewayRunner and assert the worker thread name — proving isolation from
    asyncio's default executor end-to-end.
    """

    async def go():
        runner = object.__new__(gateway_run.GatewayRunner)
        return await gateway_run.GatewayRunner._run_in_executor_with_context(
            runner, lambda: threading.current_thread().name
        )

    name = asyncio.run(go())
    assert name.startswith("elevate-agent-run"), name
