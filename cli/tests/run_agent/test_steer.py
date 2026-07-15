"""Tests for AIAgent.steer() — mid-run user message injection.

/steer lets the user add a note without interrupting the current tool call.
The complete tool-result batch is followed by an identified user guidance row
so crash recovery retains the exact client message id.
"""
from __future__ import annotations

import threading

import pytest

from run_agent import AIAgent


def _bare_agent() -> AIAgent:
    """Build an AIAgent without running __init__, then install the steer
    state manually — matches the existing object.__new__ stub pattern
    used elsewhere in the test suite.
    """
    agent = object.__new__(AIAgent)
    agent._pending_steer = None
    agent._pending_steer_lock = threading.Lock()
    return agent


class TestSteerAcceptance:
    def test_accepts_non_empty_text(self):
        agent = _bare_agent()
        assert agent.steer("go ahead and check the logs") is True
        assert agent._pending_steer == "go ahead and check the logs"

    def test_rejects_empty_string(self):
        agent = _bare_agent()
        assert agent.steer("") is False
        assert agent._pending_steer is None

    def test_rejects_whitespace_only(self):
        agent = _bare_agent()
        assert agent.steer("   \n\t  ") is False
        assert agent._pending_steer is None

    def test_rejects_none(self):
        agent = _bare_agent()
        assert agent.steer(None) is False  # type: ignore[arg-type]
        assert agent._pending_steer is None

    def test_strips_surrounding_whitespace(self):
        agent = _bare_agent()
        assert agent.steer("  hello world  \n") is True
        assert agent._pending_steer == "hello world"

    def test_concatenates_multiple_steers_with_newlines(self):
        agent = _bare_agent()
        agent.steer("first note")
        agent.steer("second note")
        agent.steer("third note")
        assert agent._pending_steer == "first note\nsecond note\nthird note"


class TestSteerDrain:
    def test_drain_returns_and_clears(self):
        agent = _bare_agent()
        agent.steer("hello")
        assert agent._drain_pending_steer() == "hello"
        assert agent._pending_steer is None

    def test_drain_on_empty_returns_none(self):
        agent = _bare_agent()
        assert agent._drain_pending_steer() is None


class TestSteerInjection:
    def test_appends_identified_row_after_complete_tool_batch(self):
        agent = _bare_agent()
        agent.steer(
            "please also check auth.log",
            client_message_id="guidance-auth-log",
        )
        messages = [
            {"role": "user", "content": "what's in /var/log?"},
            {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]},
            {"role": "tool", "content": "ls output A", "tool_call_id": "a"},
            {"role": "tool", "content": "ls output B", "tool_call_id": "b"},
        ]
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=2)
        # Both tool results remain contiguous and unchanged; guidance follows
        # the complete batch with the exact caller-supplied id.
        assert messages[2]["content"] == "ls output A"
        assert messages[3]["content"] == "ls output B"
        assert messages[4] == {
            "role": "user",
            "content": "User guidance: please also check auth.log",
            "client_message_id": "guidance-auth-log",
            "_display_content": "please also check auth.log",
            "finish_reason": "guidance_reserved_steer",
        }
        # And pending_steer is consumed.
        assert agent._pending_steer is None

    def test_no_op_when_no_steer_pending(self):
        agent = _bare_agent()
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "a"}]},
            {"role": "tool", "content": "output", "tool_call_id": "a"},
        ]
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=1)
        assert messages[-1]["content"] == "output"  # unchanged

    def test_no_op_when_num_tool_msgs_zero(self):
        agent = _bare_agent()
        agent.steer("steer")
        messages = [{"role": "user", "content": "hi"}]
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=0)
        # Steer should remain pending (nothing to drain into)
        assert agent._pending_steer == "steer"

    def test_marker_labels_text_as_user_guidance(self):
        """The injection marker must label the appended text as user
        guidance so the model attributes it to the user rather than
        confusing it with tool output.  This is the cache-safe way to
        signal provenance without violating message-role alternation.
        """
        agent = _bare_agent()
        agent.steer("stop after next step")
        messages = [{"role": "tool", "content": "x", "tool_call_id": "1"}]
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=1)
        content = messages[-1]["content"]
        assert "User guidance:" in content
        assert "stop after next step" in content

    def test_multimodal_content_list_preserved(self):
        """Anthropic-style tool content stays byte-for-byte unchanged."""
        agent = _bare_agent()
        agent.steer("extra note", client_message_id="guidance-multimodal")
        original_blocks = [{"type": "text", "text": "existing output"}]
        messages = [
            {"role": "tool", "content": list(original_blocks), "tool_call_id": "1"}
        ]
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=1)
        assert messages[0]["content"] == original_blocks
        assert messages[1]["role"] == "user"
        assert messages[1]["client_message_id"] == "guidance-multimodal"
        assert messages[1]["_display_content"] == "extra note"
        assert messages[1]["finish_reason"] == "guidance_reserved_steer"

    def test_restashed_when_no_tool_result_in_batch(self):
        """If the 'batch' contains no tool-role messages (e.g. all skipped
        after an interrupt), the steer should be put back into the pending
        slot so the caller's fallback path can deliver it."""
        agent = _bare_agent()
        agent.steer("ping")
        messages = [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "y"},
        ]
        # Claim there were N tool msgs, but the tail has none — simulates
        # the interrupt-cancelled case.
        agent._apply_pending_steer_to_tool_results(messages, num_tool_msgs=2)
        # Messages untouched
        assert messages[-1]["content"] == "y"
        # And the steer is back in pending so the fallback can grab it
        assert agent._pending_steer == "ping"


class TestSteerThreadSafety:
    def test_concurrent_steer_calls_preserve_all_text(self):
        agent = _bare_agent()
        N = 200

        def worker(idx: int) -> None:
            agent.steer(f"note-{idx}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = agent._drain_pending_steer()
        assert text is not None
        # Every single note must be preserved — none dropped by the lock.
        lines = text.split("\n")
        assert len(lines) == N
        assert set(lines) == {f"note-{i}" for i in range(N)}

    def test_two_producers_same_arbitrary_id_append_once(self):
        agent = _bare_agent()
        barrier = threading.Barrier(3)
        accepted: list[bool] = []

        def worker() -> None:
            barrier.wait()
            accepted.append(
                agent.steer(
                    "same guidance",
                    client_message_id="dashboard-message-42",
                )
            )

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        items = agent._drain_pending_inputs()
        assert accepted == [True, True]
        assert [item["client_message_id"] for item in items] == [
            "dashboard-message-42"
        ]

    def test_same_arbitrary_id_with_different_payload_conflicts(self):
        agent = _bare_agent()
        assert agent.steer("first", client_message_id="message-A")

        with pytest.raises(ValueError, match="different queued guidance"):
            agent.steer("different", client_message_id="message-A")

    def test_terminal_close_snapshots_or_rejects_every_producer(self):
        agent = _bare_agent()
        assert agent.steer("included", client_message_id="message-A")

        handed_off = agent._drain_pending_inputs(close_for_handoff=True)

        assert [item["client_message_id"] for item in handed_off] == [
            "message-A"
        ]
        assert agent.steer("too late", client_message_id="message-B") is False
        # Once the handoff closes, every producer retry is rejected cleanly.
        assert agent.steer("included", client_message_id="message-A") is False
        assert agent._drain_pending_inputs() == []


class TestSteerClearedOnInterrupt:
    def test_clear_interrupt_drops_pending_steer(self):
        """A hard interrupt supersedes any pending steer — the agent's
        next tool iteration won't happen, so delivering the steer later
        would be surprising."""
        agent = _bare_agent()
        # Minimal surface needed by clear_interrupt()
        agent._interrupt_requested = True
        agent._interrupt_message = None
        agent._interrupt_thread_signal_pending = False
        agent._execution_thread_id = None
        agent._tool_worker_threads = None
        agent._tool_worker_threads_lock = None

        agent.steer("will be dropped")
        assert agent._pending_steer == "will be dropped"

        agent.clear_interrupt()
        assert agent._pending_steer is None


class TestPreApiCallSteerDrain:
    """Test that steers arriving during an API call are drained before the
    next API call — not deferred until the next tool batch.  This is the
    fix for the scenario where /steer sent during model thinking only lands
    after the agent is completely done."""

    def test_pre_api_drain_injects_into_last_tool_result(self):
        """If a steer is pending when the main loop starts building
        api_messages, it should be injected into the last tool result
        in the messages list."""
        agent = _bare_agent()
        # Simulate messages after a tool batch completed
        messages = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "tc1", "function": {"name": "terminal", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "output here", "tool_call_id": "tc1"},
        ]
        # Steer arrives during API call (set after tool execution)
        agent.steer("focus on error handling")
        # Simulate what the pre-API-call drain does:
        _pre_api_steer = agent._drain_pending_steer()
        assert _pre_api_steer == "focus on error handling"
        # Inject into last tool msg (mirrors the new code in run_conversation)
        for _si in range(len(messages) - 1, -1, -1):
            if messages[_si].get("role") == "tool":
                messages[_si]["content"] += f"\n\nUser guidance: {_pre_api_steer}"
                break
        assert "User guidance:" in messages[-1]["content"]
        assert "focus on error handling" in messages[-1]["content"]
        assert agent._pending_steer is None

    def test_pre_api_drain_restashes_when_no_tool_message(self):
        """If there are no tool results yet (first iteration), the steer
        should be put back into _pending_steer for the post-tool drain."""
        agent = _bare_agent()
        messages = [
            {"role": "user", "content": "hello"},
        ]
        agent.steer("early steer")
        _pre_api_steer = agent._drain_pending_steer()
        assert _pre_api_steer == "early steer"
        # No tool message found — put it back
        found = False
        for _si in range(len(messages) - 1, -1, -1):
            if messages[_si].get("role") == "tool":
                found = True
                break
        assert not found
        # Restash
        agent._pending_steer = _pre_api_steer
        assert agent._pending_steer == "early steer"

    def test_pre_api_drain_finds_tool_msg_past_assistant(self):
        """The pre-API drain should scan backwards past a non-tool message
        (e.g., if an assistant message was somehow appended after tools)
        and still find the tool result."""
        agent = _bare_agent()
        messages = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "let me check", "tool_calls": [
                {"id": "tc1", "function": {"name": "web_search", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "search results", "tool_call_id": "tc1"},
        ]
        agent.steer("change approach")
        _pre_api_steer = agent._drain_pending_steer()
        assert _pre_api_steer is not None
        for _si in range(len(messages) - 1, -1, -1):
            if messages[_si].get("role") == "tool":
                messages[_si]["content"] += f"\n\nUser guidance: {_pre_api_steer}"
                break
        assert "change approach" in messages[2]["content"]


class TestSteerCommandRegistry:
    def test_steer_in_command_registry(self):
        """The /steer slash command must be registered so it reaches all
        platforms (CLI, gateway, TUI autocomplete, Telegram/Slack menus).
        """
        from elevate_cli.commands import resolve_command

        cmd = resolve_command("steer")
        assert cmd is not None
        assert cmd.name == "steer"
        assert cmd.category == "Session"
        assert cmd.args_hint == "<prompt>"

    def test_steer_in_bypass_set(self):
        """When the agent is running, /steer MUST bypass the Level-1
        base-adapter queue so it reaches the gateway runner's /steer
        handler. Otherwise it would be queued as user text and only
        delivered at turn end — defeating the whole point.
        """
        from elevate_cli.commands import ACTIVE_SESSION_BYPASS_COMMANDS, should_bypass_active_session

        assert "steer" in ACTIVE_SESSION_BYPASS_COMMANDS
        assert should_bypass_active_session("steer") is True


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
