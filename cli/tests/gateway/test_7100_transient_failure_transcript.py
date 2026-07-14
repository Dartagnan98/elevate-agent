"""Tests for #7100 — transient failures (429/timeout) must not drop the
user message from the transcript.

The #1630 fix introduced a blanket skip of transcript writes on any
``failed`` agent result.  That was correct for context-overflow failures
(which would otherwise cause a session-growth loop), but it also caused
transient provider failures (rate limits, read timeouts, connection
resets) to silently drop the user's message — so the agent had no memory
of the last turn on the next attempt.

The gateway classifier must distinguish:

* ``compression_exhausted=True`` or an explicit context-overflow error
  → skip transcript
* everything else that fails → transient → persist the user message
"""

import pytest
import threading
from datetime import datetime

from elevate_state import SessionDB
from gateway.config import GatewayConfig
from gateway.run import GatewayRunner
from gateway.run import _should_suppress_transcript_growth
from gateway.session import SessionEntry, SessionStore


class TestContextOverflowStillSkipsTranscript:
    """#1630 behavior must be preserved for real context-overflow cases."""

    def test_compression_exhausted_is_context_overflow(self):
        agent_result = {
            "failed": True,
            "compression_exhausted": True,
            "error": "Request payload too large: max compression attempts reached.",
        }
        assert _should_suppress_transcript_growth(agent_result) is True

    def test_explicit_context_length_error_is_context_overflow(self):
        agent_result = {
            "failed": True,
            "error": "prompt is too long: 250000 tokens > 200000 maximum",
        }
        assert _should_suppress_transcript_growth(agent_result) is True

    def test_generic_400_on_large_session_is_not_explicit_overflow(self):
        agent_result = {
            "failed": True,
            "error": "error code: 400 - {'type': 'error', 'message': 'Error'}",
        }
        assert _should_suppress_transcript_growth(agent_result) is False


class TestTransientFailureKeepsUserMessage:
    """Transient provider failures must NOT skip the transcript — doing so
    drops the user message and the agent forgets the turn. (#7100)"""

    def test_rate_limit_429_is_not_context_overflow(self):
        agent_result = {
            "failed": True,
            "error": (
                "API call failed after 3 retries: 429 Too Many Requests "
                "— rate limit exceeded"
            ),
        }
        assert _should_suppress_transcript_growth(agent_result) is False

    def test_read_timeout_is_not_context_overflow(self):
        agent_result = {
            "failed": True,
            "error": "ReadTimeout: HTTPSConnectionPool(host='api.z.ai'): Read timed out.",
        }
        assert _should_suppress_transcript_growth(agent_result) is False

    def test_connection_reset_is_not_context_overflow(self):
        agent_result = {
            "failed": True,
            "error": "ConnectionError: [Errno 54] Connection reset by peer",
        }
        assert _should_suppress_transcript_growth(agent_result) is False

    def test_provider_500_is_not_context_overflow(self):
        agent_result = {
            "failed": True,
            "error": "API call failed after 3 retries: 500 Internal Server Error",
        }
        assert _should_suppress_transcript_growth(agent_result) is False

    def test_generic_400_on_short_session_is_not_context_overflow(self):
        """A 400 on a short session is a real client error, not context
        overflow — still not a reason to drop the user turn."""
        agent_result = {
            "failed": True,
            "error": "error code: 400 - invalid model",
        }
        assert _should_suppress_transcript_growth(agent_result) is False

    @pytest.mark.parametrize(
        "agent_result",
        [
            {
                "failed": True,
                "partial": True,
                "error": "unresolved tool failure: terminal exited with code 7",
            },
            {
                "failed": True,
                "error": "approval denied; requested action was not performed",
            },
        ],
    )
    def test_tool_and_action_failures_are_persisted(self, agent_result):
        assert _should_suppress_transcript_growth(agent_result) is False

    def test_pending_obligation_is_persisted(self):
        agent_result = {
            "completed": False,
            "failed": False,
            "partial": True,
            "pending": True,
            "pending_tool_obligations": [
                {"tool": "delegate_task", "task_id": "child-1", "status": "pending"}
            ],
        }

        assert _should_suppress_transcript_growth(agent_result) is False


class TestSuccessfulResultUnaffected:
    def test_successful_result_neither_failed_nor_overflow(self):
        agent_result = {
            "final_response": "Hello!",
            "messages": [{"role": "assistant", "content": "Hello!"}],
        }
        assert _should_suppress_transcript_growth(agent_result) is False


def test_db_unavailable_jsonl_roundtrip_preserves_failed_tool_action(tmp_path):
    """The fallback transcript must retain the evidence of a failed action."""
    store = object.__new__(SessionStore)
    store.sessions_dir = tmp_path
    store._db = None
    messages = [
        {"role": "user", "content": "Run the export"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"export-deals"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"exit_code":7,"error":"export failed"}',
        },
        {
            "role": "assistant",
            "content": "The export failed and was not completed.",
            "finish_reason": "error",
        },
    ]

    for message in messages:
        store.append_to_transcript("session-jsonl", message)

    assert store.load_transcript("session-jsonl") == messages


def test_context_overflow_reset_moves_next_cold_replay_to_fresh_session(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    old_session_id = "oversized-session"
    session_key = "agent:main:telegram:dm:123"
    db.create_session(session_id=old_session_id, source="telegram")
    db.append_message(old_session_id, "user", content="x" * 10_000)
    db.append_message(
        old_session_id,
        "assistant",
        content="maximum context length exceeded",
        finish_reason="error",
    )

    store = object.__new__(SessionStore)
    store.sessions_dir = tmp_path / "sessions"
    store.config = GatewayConfig()
    store._entries = {
        session_key: SessionEntry(
            session_key=session_key,
            session_id=old_session_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    }
    store._loaded = True
    store._lock = threading.Lock()
    store._has_active_processes_fn = None
    store._db = db

    runner = object.__new__(GatewayRunner)
    runner.session_store = store
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {session_key: {"model": "old-model"}}

    response = runner._reset_context_overflow_session(
        session_key=session_key,
        previous_session_id=old_session_id,
        response="The request exceeded the maximum context length.",
    )

    new_session_id = store._entries[session_key].session_id
    assert new_session_id != old_session_id
    assert len(db.get_messages_as_conversation(old_session_id)) == 2
    assert store.load_transcript(new_session_id) == []
    assert "next message will start in a fresh session" in response
    assert session_key not in runner._session_model_overrides
    db.close()
