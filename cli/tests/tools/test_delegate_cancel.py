"""Kill switch for dispatched background delegations.

Covers the three layers added together:
- registry-level cancel/interrupt resolvers (by task id, by child session id)
- result suppression for cancelled async tasks
- the delegate_task(cancel_task_id=...) tool surface (no spawn, no parent
  required)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tools import delegate_tool as dt


@pytest.fixture(autouse=True)
def _clean_registry():
    with dt._active_subagents_lock:
        dt._active_subagents.clear()
    with dt._cancelled_async_tasks_lock:
        dt._cancelled_async_tasks.clear()
    yield
    with dt._active_subagents_lock:
        dt._active_subagents.clear()
    with dt._cancelled_async_tasks_lock:
        dt._cancelled_async_tasks.clear()


def _register(subagent_id: str, *, task_id=None, session_id=None):
    agent = MagicMock()
    agent.session_id = session_id
    dt._register_subagent(
        {
            "subagent_id": subagent_id,
            "async_task_id": task_id,
            "agent": agent,
            "goal": "test goal",
            "status": "running",
        }
    )
    return agent


def test_cancel_marks_and_interrupts_matching_children():
    a1 = _register("sa_1", task_id="dt_abc12345")
    a2 = _register("sa_2", task_id="dt_abc12345")
    other = _register("sa_3", task_id="dt_other000")

    result = dt.cancel_dispatched_delegation("dt_abc12345")

    assert result["cancelled"] is True
    assert result["interrupted"] == 2
    a1.interrupt.assert_called_once()
    a2.interrupt.assert_called_once()
    other.interrupt.assert_not_called()
    assert dt.is_async_task_cancelled("dt_abc12345")
    assert not dt.is_async_task_cancelled("dt_other000")


def test_cancel_after_completion_still_suppresses():
    # No running children — too late to interrupt, but the mark must stand
    # so a parked result is never delivered.
    result = dt.cancel_dispatched_delegation("dt_gone0000")
    assert result["cancelled"] is True
    assert result["interrupted"] == 0
    assert dt.is_async_task_cancelled("dt_gone0000")


def test_cancel_requires_task_id():
    result = dt.cancel_dispatched_delegation("")
    assert result["cancelled"] is False


def test_interrupt_by_session_resolves_live_agent():
    agent = _register("sa_9", session_id="sess-child-42")
    assert dt.interrupt_subagent_by_session("sess-child-42") is True
    agent.interrupt.assert_called_once()
    assert dt.interrupt_subagent_by_session("sess-nope") is False
    assert dt.interrupt_subagent_by_session("") is False


def test_delegate_task_cancel_surface_no_parent_needed():
    agent = _register("sa_5", task_id="dt_feed1234")
    raw = dt.delegate_task(cancel_task_id="dt_feed1234", parent_agent=None)
    payload = json.loads(raw)
    assert payload["cancelled"] is True
    assert payload["interrupted"] == 1
    assert "will NOT be delivered" in payload["note"]
    agent.interrupt.assert_called_once()
    # No spawn machinery ran: registry untouched beyond our fixture.
    with dt._active_subagents_lock:
        assert set(dt._active_subagents) == {"sa_5"}


def test_schema_exposes_cancel_param():
    assert "cancel_task_id" in dt.DELEGATE_TASK_SCHEMA["parameters"]["properties"]
    # The dynamic override (what the model actually sees) must keep it too.
    overrides = dt._build_dynamic_schema_overrides()
    assert "cancel_task_id" in overrides["parameters"]["properties"]
