"""Step 7 of the compaction redesign — the anti-thrash cooldown composes with
the cursor model.

The low-yield cooldown (commit a109de3f6) lives in should_compress() and reads
_consecutive_low_yield_compactions / _last_low_yield_tokens. The cursor-model
compaction (summarize_to_cursor, step 3) ARMS those counters the same way
compress() did, and the 0.95 critical line (step 6) overrides the cooldown when
overflow is imminent. No new production code — these tests just prove the three
pieces interlock.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.context_compressor import (
    ContextCompressor,
    _LOW_YIELD_COOLDOWN_TOKEN_GROWTH,
    _LOW_YIELD_REMOVED_MESSAGES,
)
from agent.conversation_compression import should_critical_compress_now


@pytest.fixture()
def compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=272000
    ):
        c = ContextCompressor(
            model="test/model",
            protect_first_n=0,
            protect_last_n=4,
            quiet_mode=True,
        )
    c.context_length = 272000
    c.threshold_tokens = 64000
    c.tail_token_budget = 40
    return c


def _summary_response(text="## Active Task\ngo"):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _transcript(n):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " * 8}
        for i in range(n)
    ]


def test_cursor_noop_arms_cooldown_and_should_compress_backs_off(compressor):
    # A no-op cursor compaction (cursor already at the end) arms the low-yield
    # cooldown exactly like compress()'s no-compressible-window branch did.
    msgs = _transcript(30)
    with patch("agent.context_compressor.call_llm", return_value=_summary_response()):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=29)
    assert summary is None  # nothing new to compact
    assert compressor._consecutive_low_yield_compactions >= 1

    # Mid-band (above threshold, below critical, not grown by +16k): should_compress
    # now BACKS OFF because the cooldown is armed.
    compressor._last_low_yield_tokens = 70_000
    assert compressor.should_compress(72_000) is False

    # Once context grows past the cooldown band, compaction is allowed again.
    grew = 70_000 + _LOW_YIELD_COOLDOWN_TOKEN_GROWTH + 1
    assert compressor.should_compress(grew) is True


def test_healthy_cursor_compaction_clears_cooldown(compressor):
    # A compaction that hides many messages is NOT low-yield -> counters reset,
    # so the next trigger is not suppressed.
    msgs = _transcript(60)
    compressor._consecutive_low_yield_compactions = 3  # pretend prior thrash
    with patch("agent.context_compressor.call_llm", return_value=_summary_response()):
        summary, idx = compressor.summarize_to_cursor(msgs, prev_cursor=0)
    assert summary is not None
    assert (idx - 0) > _LOW_YIELD_REMOVED_MESSAGES  # hid many messages
    assert compressor._consecutive_low_yield_compactions == 0
    assert compressor.should_compress(70_000) is True


def test_critical_overrides_cooldown(compressor):
    # Even with the cooldown armed and should_compress() backing off, the 0.95
    # critical line is the caller's override (it forces compaction regardless).
    compressor._consecutive_low_yield_compactions = 2
    compressor._last_low_yield_tokens = 70_000
    window = compressor.context_length
    # Mid-band: cooldown suppresses the normal trigger.
    assert compressor.should_compress(72_000) is False
    # But at >=95% the critical line fires — the caller compacts with force=True.
    assert should_critical_compress_now(int(window * 0.95), window) is True
    assert should_critical_compress_now(72_000, window) is False  # mid-band: not critical
