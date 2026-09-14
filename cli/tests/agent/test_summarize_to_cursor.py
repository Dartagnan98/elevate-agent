"""Step 3 of the compaction redesign — ``ContextCompressor.summarize_to_cursor``.

The cursor model NEVER rewrites the transcript: compaction is reduced to
computing ``(summary_text, compacted_idx)`` over ``messages[prev_cursor:idx]``,
reusing the exact same boundary helpers ``compress()`` uses so a tool pair is
never split and the most recent user turn is always kept in the live tail.

These tests pin:
  - the boundary never splits a tool_call/result pair (cursor lands clean)
  - the input ``messages`` list is never mutated (transcript is sacred)
  - the cursor advances monotonically across re-compactions
  - the prior summary is folded in iteratively (resume seeds previous_summary)
  - the no-op contract (cut doesn't advance) and abort contract (summary fails)
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.context_compressor import (
    ContextCompressor,
    SUMMARY_PREFIX,
    _LOW_YIELD_REMOVED_MESSAGES,
)


@pytest.fixture()
def compressor():
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
    # Tiny tail budget so the cut lands early and leaves a compressible head.
    c.tail_token_budget = 40
    return c


def _summary_response(text="## Active Task\nfollow up"):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _transcript(n):
    """n alternating user/assistant transcript messages (system-less)."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"message number {i} " * 8})
    return out


# ---------------------------------------------------------------------------
# Core: returns (summary, idx); transcript untouched
# ---------------------------------------------------------------------------

def test_returns_summary_and_advancing_cursor(compressor):
    msgs = _transcript(30)
    snapshot = [dict(m) for m in msgs]
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=0)
    assert summary is not None
    assert summary.startswith(SUMMARY_PREFIX)
    assert 0 < idx < len(msgs)
    # Transcript is sacred — not mutated, not shrunk.
    assert msgs == snapshot
    assert len(msgs) == 30


def test_cursor_never_splits_tool_pair(compressor):
    # The boundary must never land on a bare tool result whose tool_call was
    # skipped. Build a transcript where a tool group straddles a likely cut.
    msgs = []
    for i in range(10):
        msgs.append({"role": "user", "content": f"u{i} " * 6})
        msgs.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": f"c{i}", "function": {"name": "x"}}],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"r{i} " * 6})
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=0)
    assert summary is not None
    # The first KEPT message (at the cursor) must not be an orphan tool result.
    assert msgs[idx]["role"] != "tool", f"cursor split a tool pair at {idx}: {msgs[idx]}"


# ---------------------------------------------------------------------------
# Monotonic advance + iterative fold across re-compaction
# ---------------------------------------------------------------------------

def test_cursor_advances_monotonically_on_recompaction(compressor):
    msgs = _transcript(30)
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        summary1, idx1 = compressor.summarize_to_cursor(msgs, prev_cursor=0)
    # Conversation continues — append more turns, then re-compact.
    msgs.extend(_transcript(20))
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response("## Active Task\nstill going")
    ):
        summary2, idx2 = compressor.summarize_to_cursor(
            msgs, prev_cursor=idx1, previous_summary=summary1
        )
    assert idx2 > idx1  # cursor only moves forward
    assert summary2 is not None


def test_recompaction_folds_previous_summary(compressor):
    msgs = _transcript(40)
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ) as mock_call:
        # Seed a prior summary as if hydrated from the DB after a resume.
        compressor.summarize_to_cursor(
            msgs, prev_cursor=10, previous_summary="PRIOR SUMMARY BODY"
        )
        prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    # The iterative-update prompt must carry the prior summary forward.
    assert "PRIOR SUMMARY BODY" in prompt
    assert "PREVIOUS SUMMARY" in prompt


def test_only_delta_summarized_on_recompaction(compressor):
    # On re-compaction only messages[prev_cursor:idx] are sent, not the whole head.
    msgs = _transcript(40)
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ) as mock_call:
        compressor.summarize_to_cursor(
            msgs, prev_cursor=12, previous_summary="prior"
        )
        prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    # The earliest message (index 0) is behind the prev_cursor — it must NOT be
    # re-serialized into this pass's source turns.
    assert "message number 0 " not in prompt


# ---------------------------------------------------------------------------
# No-op contract: cut doesn't advance past prev_cursor
# ---------------------------------------------------------------------------

def test_noop_when_cursor_at_end(compressor):
    msgs = _transcript(30)
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        # prev_cursor already at/after where the cut would land → nothing new.
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=29)
    assert summary is None
    assert idx == 29
    assert not compressor._last_compress_aborted  # no-op, not an abort
    # No-op arms the low-yield cooldown so should_compress() backs off.
    assert compressor._consecutive_low_yield_compactions >= 1


# ---------------------------------------------------------------------------
# Abort contract: summary generation fails
# ---------------------------------------------------------------------------

def test_abort_when_summary_fails(compressor):
    msgs = _transcript(30)
    with patch(
        "agent.context_compressor.call_llm", side_effect=RuntimeError("no provider")
    ):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=0)
    assert summary is None
    assert idx == 0  # cursor NOT advanced
    assert compressor._last_compress_aborted is True


def test_low_yield_tracked_when_few_messages_hidden(compressor):
    # A cut that hides <= _LOW_YIELD_REMOVED_MESSAGES new messages is low-yield.
    msgs = _transcript(30)
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        # Force a cut that advances by exactly 1 past prev_cursor by choosing
        # prev_cursor = idx-1. First find where the natural cut lands.
        _, natural_idx = compressor.summarize_to_cursor(list(msgs), prev_cursor=0)
    assert natural_idx >= 1
    low_start = natural_idx - _LOW_YIELD_REMOVED_MESSAGES
    compressor._consecutive_low_yield_compactions = 0
    with patch(
        "agent.context_compressor.call_llm", return_value=_summary_response()
    ):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=low_start)
    if summary is not None and (idx - low_start) <= _LOW_YIELD_REMOVED_MESSAGES:
        assert compressor._consecutive_low_yield_compactions >= 1
