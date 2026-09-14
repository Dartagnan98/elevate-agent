"""Step 6 of the compaction redesign — the 0.95 critical line + emergency
tool-result truncation.

  - should_critical_compress_now(measured, window): fires at/above 0.95*window so
    the caller can FORCE a synchronous compaction past the anti-thrash backoff,
    just before a context-overflow error would force error-recovery compaction.
  - ContextCompressor.emergency_truncate_tool_results(messages): last-resort that
    shortens oversized tool-result CONTENT in place (never removes rows) so a turn
    that still overflows after a forced compaction can fit.
"""

from unittest.mock import patch

import pytest

from agent.conversation_compression import (
    CRITICAL_THRESHOLD,
    should_critical_compress_now,
)
from agent.context_compressor import (
    ContextCompressor,
    _EMERGENCY_TAIL_TOOL_RESULT_CHARS,
    _EMERGENCY_TAIL_KEEP_RECENT,
)


# ---------------------------------------------------------------------------
# Critical threshold
# ---------------------------------------------------------------------------

def test_critical_threshold_value():
    assert CRITICAL_THRESHOLD == 0.95


def test_critical_fires_at_or_above_95_percent():
    window = 200_000
    assert should_critical_compress_now(int(window * 0.95), window) is True
    assert should_critical_compress_now(int(window * 0.97), window) is True
    assert should_critical_compress_now(window, window) is True


def test_critical_quiet_below_95_percent():
    window = 200_000
    assert should_critical_compress_now(int(window * 0.94), window) is False
    assert should_critical_compress_now(int(window * 0.90), window) is False


def test_critical_guards_bad_inputs():
    assert should_critical_compress_now(0, 200_000) is False
    assert should_critical_compress_now(190_000, 0) is False
    assert should_critical_compress_now(-1, 200_000) is False


# ---------------------------------------------------------------------------
# Emergency tool-result truncation
# ---------------------------------------------------------------------------

@pytest.fixture()
def compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=200000
    ):
        return ContextCompressor(model="test/model", quiet_mode=True)


def _huge(n_chars):
    return "X" * n_chars


def test_emergency_truncates_oversized_tool_results(compressor):
    big = _EMERGENCY_TAIL_TOOL_RESULT_CHARS + 5000
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": _huge(big)},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c2", "content": _huge(big)},
        {"role": "assistant", "content": "done"},
    ]
    n_rows_before = len(messages)
    out, n = compressor.emergency_truncate_tool_results(messages)

    # At least one oversized result was shortened (keep-recent leaves the newest).
    assert n >= 1
    # Row count is preserved — content edited, no rows removed.
    assert len(out) == n_rows_before
    assert len(messages) == n_rows_before
    # The truncated tool result is now short.
    assert len(messages[2]["content"]) < big


def test_emergency_keeps_most_recent_intact(compressor):
    big = _EMERGENCY_TAIL_TOOL_RESULT_CHARS + 5000
    messages = [
        {"role": "tool", "tool_call_id": "c1", "content": _huge(big)},
        {"role": "tool", "tool_call_id": "c2", "content": _huge(big)},
    ]
    compressor.emergency_truncate_tool_results(messages)
    if _EMERGENCY_TAIL_KEEP_RECENT:
        # The most recent oversized result is preserved.
        assert len(messages[-1]["content"]) == big


def test_emergency_noop_when_nothing_oversized(compressor):
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "c1", "content": "small result"},
    ]
    snapshot = [dict(m) for m in messages]
    out, n = compressor.emergency_truncate_tool_results(messages)
    assert n == 0
    assert messages == snapshot
