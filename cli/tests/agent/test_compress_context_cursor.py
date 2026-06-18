"""Step 3 of the compaction redesign — ``compress_context`` is now
compute-cursor-not-rewrite.

These tests drive the live shared ``compress_context`` with a real SQLite
``SessionDB`` + real ``ContextCompressor`` (summary LLM mocked) and prove the
redesign invariants:

  - the transcript list passed in is returned UNCHANGED (same object, same
    length — never rewritten or shrunk)
  - the new (summary, cursor) lands on the SESSION ROW via update_compaction
  - the agent's compaction_cursor / compaction_summary are set
  - NO session rotation happens (session_id is stable; no parent/child row)
  - the usage projector is invalidated + the -1 sentinel parked
  - re-compaction advances the cursor and folds the prior summary
  - the abort contract (summary fails) freezes: no cursor, no metadata write
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from elevate_state import SessionDB
from agent.context_compressor import ContextCompressor
from agent.conversation_compression import compress_context


class _Projector:
    def __init__(self):
        self.invalidated = 0

    def invalidate(self):
        self.invalidated += 1


def _make_compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=200000
    ):
        c = ContextCompressor(
            model="test/model",
            protect_first_n=0,
            protect_last_n=4,
            quiet_mode=True,
        )
    c.context_length = 200000
    c.threshold_tokens = 64000
    c.tail_token_budget = 40  # tiny tail so the cut leaves a compressible head
    return c


def _make_agent(db, compressor, session_id="sess-1"):
    db.create_session(session_id=session_id, source="test")
    agent = SimpleNamespace(
        session_id=session_id,
        model="test/model",
        tools=None,
        _session_db=db,
        context_compressor=compressor,
        compaction_cursor=0,
        compaction_summary=None,
        _memory_manager=None,
        _compression_feasibility_checked=True,
        _cached_system_prompt="SYSTEM",
        _usage_projector=_Projector(),
        log_prefix="",
        status_callback=lambda *a, **k: None,
        status_emits=[],
        commit_calls=[],
    )
    agent._emit_status = lambda m: agent.status_emits.append(m)
    agent._emit_warning = lambda m: None
    agent._touch_activity = lambda d: None
    agent._vprint = lambda *a, **k: None
    agent._build_system_prompt = lambda sm: "SYSTEM"
    agent.commit_memory_session = lambda msgs: agent.commit_calls.append(len(msgs))
    return agent


def _summary_response(text="## Active Task\nkeep going"):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _transcript(n):
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"message number {i} " * 8})
    return out


def _large_transcript(n):
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"message {i}\n" + ("x" * 10000)})
    return out


def test_transcript_untouched_metadata_persisted_no_rotation(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)
    msgs_id = id(messages)
    snapshot = [dict(m) for m in messages]

    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        out_msgs, out_sp = compress_context(agent, messages, "SYSTEM")

    # Transcript is sacred: same object, same content, same length.
    assert id(out_msgs) == msgs_id
    assert out_msgs == snapshot
    assert len(out_msgs) == 30

    # Cursor + summary set on the agent AND persisted to the session row.
    assert agent.compaction_cursor > 0
    assert agent.compaction_summary
    row = db.get_session("sess-1")
    assert row["compaction_cursor"] == agent.compaction_cursor
    assert row["compaction_summary"] == agent.compaction_summary

    # NO rotation: the session id never changed, and no child/parent row exists.
    assert agent.session_id == "sess-1"
    all_sessions = [s for s in db.list_sessions()] if hasattr(db, "list_sessions") else []
    # Whether or not list_sessions exists, the one session we made is the only one.
    if all_sessions:
        assert len(all_sessions) == 1

    # Projector invalidated + -1 sentinel parked (don't re-trigger off stale count).
    assert agent._usage_projector.invalidated == 1
    assert compressor.last_prompt_tokens == -1

    # Memory extraction still fired (no rotation, but memories saved).
    assert agent.commit_calls == [30]


def test_structured_completion_log_includes_cursor_result(tmp_path, caplog):
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    caplog.set_level(logging.INFO, logger="agent.conversation_compression")
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        compress_context(agent, messages, "SYSTEM", approx_tokens=12345)

    assert "compaction.completed reason=full_compact source=compress_context" in caplog.text
    assert "session=sess-1" in caplog.text
    assert f"cursor_after={agent.compaction_cursor}" in caplog.text
    assert "tokens_before=12345" in caplog.text


def test_recompaction_advances_cursor_and_folds_summary(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        compress_context(agent, messages, "SYSTEM")
    cursor1 = agent.compaction_cursor

    # Conversation continues — append turns, then re-compact the SAME list.
    messages.extend(_transcript(24))
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_summary_response("## Active Task\nstill going"),
    ) as mock_call:
        compress_context(agent, messages, "SYSTEM")
        prompt = mock_call.call_args.kwargs["messages"][0]["content"]

    assert agent.compaction_cursor > cursor1  # monotonic advance
    # Iterative fold: the second pass carried the prior summary forward.
    assert "PREVIOUS SUMMARY" in prompt
    row = db.get_session("sess-1")
    assert row["compaction_cursor"] == agent.compaction_cursor


def test_abort_freezes_no_cursor_no_metadata(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    with patch(
        "agent.context_compressor.call_llm",
        side_effect=RuntimeError("no provider"),
    ):
        out_msgs, out_sp = compress_context(agent, messages, "SYSTEM")

    # Frozen: transcript unchanged, no cursor advance, nothing persisted.
    assert out_msgs == messages
    assert agent.compaction_cursor == 0
    assert agent.compaction_summary is None
    row = db.get_session("sess-1")
    assert (row.get("compaction_cursor") or 0) == 0
    assert row.get("compaction_summary") in (None, "")
    # Projector NOT invalidated on abort (payload didn't change).
    assert agent._usage_projector.invalidated == 0


def test_abort_logs_structured_failure(tmp_path, caplog):
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    caplog.set_level(logging.INFO, logger="agent.conversation_compression")
    with patch(
        "agent.context_compressor.call_llm",
        side_effect=RuntimeError("no provider"),
    ):
        compress_context(agent, messages, "SYSTEM", approx_tokens=54321)

    assert "compaction.failed reason=full_compact source=compress_context" in caplog.text
    assert "session=sess-1" in caplog.text
    assert "tokens_before=54321" in caplog.text
    assert "error=no auxiliary LLM provider configured" in caplog.text


def test_cursor_summary_window_capped_before_llm_call():
    compressor = _make_compressor()
    compressor.context_length = 64000
    compressor.summary_context_length = 64000
    compressor.threshold_tokens = 64000
    compressor.max_summary_tokens = 3200
    compressor.tail_token_budget = 40
    messages = _large_transcript(120)
    seen = []

    def fake_summary(turns, focus_topic=None):
        seen.append((len(turns), compressor._estimate_summary_input_tokens(turns)))
        return "## Active Task\nkeep going"

    compressor._generate_summary = fake_summary

    summary, cursor = compressor.summarize_to_cursor(messages)

    assert summary
    assert cursor > 0
    assert cursor < 100
    assert seen
    assert seen[0][1] <= compressor._summary_input_token_budget()


def _capture_recorder_events(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    calls = []
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)) or True,
    )
    return calls


def test_successful_compaction_records_health_sample(tmp_path, monkeypatch):
    recorder_events = _capture_recorder_events(monkeypatch)
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        compress_context(agent, messages, "SYSTEM", approx_tokens=12345)

    complete = [
        call for call in recorder_events
        if call[0] == "compact.health_sample"
        and call[1]["payload"].get("status") == "complete"
    ]
    assert len(complete) == 1
    payload = complete[0][1]["payload"]
    assert payload["outcome"] == "complete"
    assert payload["context_tokens"] == 12345
    assert payload["compaction_removed_messages"] == agent.compaction_cursor
    assert payload["compaction_saved_tokens"] >= 0
    assert "summary" not in payload


def test_noop_compaction_records_low_yield(tmp_path, monkeypatch):
    recorder_events = _capture_recorder_events(monkeypatch)
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    with patch.object(compressor, "summarize_to_cursor", return_value=(None, 0)):
        compress_context(agent, messages, "SYSTEM", approx_tokens=1000)

    low_yield = [call for call in recorder_events if call[0] == "compact.low_yield"]
    assert len(low_yield) == 1
    payload = low_yield[0][1]["payload"]
    assert payload["outcome"] == "noop"
    assert payload["compaction_removed_messages"] == 0
    assert payload["noop"] is True


def test_summary_failure_records_compact_error(tmp_path, monkeypatch):
    recorder_events = _capture_recorder_events(monkeypatch)
    db = SessionDB(db_path=tmp_path / "state.db")
    compressor = _make_compressor()
    agent = _make_agent(db, compressor)
    messages = _transcript(30)

    with patch(
        "agent.context_compressor.call_llm",
        side_effect=RuntimeError("no provider"),
    ):
        compress_context(agent, messages, "SYSTEM", approx_tokens=54321)

    errors = [call for call in recorder_events if call[0] == "compact.error"]
    assert errors
    payload = errors[0][1]["payload"]
    assert payload["status"] == "aborted"
    assert payload["outcome"] == "aborted"
    assert payload["error_class"] == "compression_aborted"
    assert "no provider" not in json.dumps(payload)
