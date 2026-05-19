"""Regression test for issue #5 — pre-first-byte heartbeat.

The dispatch→first-stream-byte window at the ``_interruptible_api_call``
chokepoint emitted nothing: the UI sat on "initializing" and the watchdog
was blind for the entire round-trip until the first delta arrived. The
only backstop was the #2 per-turn wall-clock deadline (a hard ceiling,
not a heartbeat).

Issue #5 adds a single cheap ``_emit_status`` heartbeat immediately
before the blocking API call begins, so the UI/watchdog gets a sign of
life during dispatch — before the API result is consumed.

This test pins the ordering invariant: the heartbeat MUST be emitted
*before* control enters the blocking ``_interruptible_*`` call (and
therefore before any response is consumed). It does not assert on the
exact wording — only that a status fires first, exactly once per attempt.
"""

from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_agent():
    """Minimal AIAgent, same harness style as the sibling config tests."""
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        agent.client = MagicMock()
        return agent


class _StopBeforeResponse(RuntimeError):
    """Sentinel raised from inside the stubbed blocking call so the agent
    loop short-circuits deterministically the moment we've proven the
    heartbeat already fired — no valid response shape required."""


def _run_one_turn_capturing_order(agent):
    """Drive a single turn. Record every ``_emit_status`` call, and snapshot
    that record at the instant control enters the blocking API call.

    Returns ``(status_calls, status_at_dispatch)`` where
    ``status_at_dispatch`` is the list of statuses already emitted *before*
    the blocking call body ran.
    """
    status_calls: list[str] = []
    status_at_dispatch: dict[str, list[str]] = {}

    real_emit = agent._emit_status

    def _spy_emit(message: str) -> None:
        status_calls.append(message)
        # Don't actually fan out to CLI/gateway sinks in the test.
        return None

    def _blocking_stub(*args, **kwargs):
        # By the time the chokepoint reaches the blocking call, the
        # pre-first-byte heartbeat must already be in the history.
        # Snapshot only the *first* attempt: the retry loop legitimately
        # re-emits one heartbeat per subsequent attempt, but "once per
        # attempt" is asserted against a single, clean attempt.
        status_at_dispatch.setdefault("snapshot", list(status_calls))
        raise _StopBeforeResponse("stop after heartbeat proven")

    with (
        patch.object(agent, "_emit_status", side_effect=_spy_emit),
        patch.object(agent, "_interruptible_api_call", side_effect=_blocking_stub),
        patch.object(
            agent, "_interruptible_streaming_api_call", side_effect=_blocking_stub
        ),
    ):
        try:
            agent.run_conversation("ping", task_id="hb-test")
        except _StopBeforeResponse:
            # Expected: we deliberately abort the turn the instant the
            # blocking call is reached, having already captured ordering.
            pass

    assert real_emit is not None  # keep the reference; silences lint
    return status_calls, status_at_dispatch.get("snapshot")


def test_heartbeat_emitted_before_api_result_consumed():
    """A status heartbeat fires before the blocking API call returns —
    i.e. before any response could be consumed."""
    agent = _make_agent()
    status_calls, snapshot = _run_one_turn_capturing_order(agent)

    # The blocking call was reached (stub ran and captured a snapshot).
    assert snapshot is not None, (
        "blocking _interruptible_* call was never reached — the test did "
        "not exercise the chokepoint"
    )
    # At least one status was already emitted *before* the blocking call.
    assert len(snapshot) >= 1, (
        f"no heartbeat emitted before the blocking API call; "
        f"statuses at dispatch={snapshot!r} all={status_calls!r}"
    )
    # The last status before dispatch is the pre-first-byte heartbeat.
    assert "request" in snapshot[-1].lower(), (
        f"expected the pre-first-byte send heartbeat just before dispatch, "
        f"got {snapshot[-1]!r} (full pre-dispatch history={snapshot!r})"
    )


def test_heartbeat_fires_once_per_attempt_not_in_a_loop():
    """The heartbeat is a single emit per API-call attempt, not a polled
    loop. With exactly one attempt reached, the send heartbeat appears
    exactly once."""
    agent = _make_agent()
    _status_calls, snapshot = _run_one_turn_capturing_order(agent)

    assert snapshot is not None
    send_heartbeats = [s for s in snapshot if "sending request" in s.lower()]
    assert len(send_heartbeats) == 1, (
        f"pre-first-byte heartbeat must fire exactly once per attempt, "
        f"saw {len(send_heartbeats)}: {snapshot!r}"
    )
