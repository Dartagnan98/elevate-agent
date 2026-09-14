"""Anti-thrash patch tests (compaction-rs fixture 2026-06-15).

Regression coverage for the three anti-thrash fixes landed on top of the
relief batch:

  B. Low-yield cooldown in should_compress() — after a compaction that removed
     <= _LOW_YIELD_REMOVED_MESSAGES messages, suppress the every-~65s
     iteration-boundary refire until context grows past the level where
     compaction last failed to help. Overflow safety always wins.
  A. No-op window + negative-savings now register as low-yield so the cooldown
     actually engages (the parked stash's counter bump, strengthened).
  C. Emergency large-tool-result policy — huge tool-results in the protected
     tail get truncated (keeping the most-recent intact) when the tail is
     genuinely bloated, so they can't sit untouched and force re-compaction.

The fixture that motivated these: 22 compactions in ~23 min, 12 consecutive
iteration-boundary compactions each removing exactly 1 message while the tail
grew 76->100, all reporting "healthy" 12-32% savings.
"""

import pytest
from unittest.mock import patch

from agent.context_compressor import (
    ContextCompressor,
    _LOW_YIELD_COOLDOWN_TOKEN_GROWTH,
    _EMERGENCY_TAIL_TOOL_RESULT_CHARS,
    _EMERGENCY_TAIL_KEEP_RECENT,
)


@pytest.fixture()
def compressor():
    with patch("agent.context_compressor.get_model_context_length", return_value=272000):
        c = ContextCompressor(
            model="test/model",
            threshold_percent=0.0001,  # floors at MINIMUM_CONTEXT_LENGTH
            protect_first_n=2,
            protect_last_n=2,
            quiet_mode=True,
        )
    # Pin the prod-like band explicitly so the cooldown math is unambiguous:
    # threshold 64000, context 272000 -> critical = 0.9 * 272000 = 244800.
    c.context_length = 272000
    c.threshold_tokens = 64000
    return c


class TestLowYieldCooldown:
    """Fix B — should_compress() suppresses thrash after low-yield compactions."""

    def test_no_cooldown_when_not_low_yield(self, compressor):
        compressor._consecutive_low_yield_compactions = 0
        compressor._last_low_yield_tokens = 0
        assert compressor.should_compress(70_000) is True

    def test_cooldown_blocks_midband_after_low_yield(self, compressor):
        # Last low-yield compaction ran at 70k. Now at 72k: above threshold,
        # well below critical, and has NOT grown by the required +16k.
        compressor._consecutive_low_yield_compactions = 1
        compressor._last_low_yield_tokens = 70_000
        assert compressor.should_compress(72_000) is False

    def test_cooldown_allows_after_sufficient_growth(self, compressor):
        compressor._consecutive_low_yield_compactions = 1
        compressor._last_low_yield_tokens = 70_000
        grown = 70_000 + _LOW_YIELD_COOLDOWN_TOKEN_GROWTH
        assert compressor.should_compress(grown) is True

    def test_cooldown_never_blocks_near_critical(self, compressor):
        # Overflow safety: a near-ceiling session must always be allowed to
        # compact even mid-cooldown (relief 1.6 invariant).
        compressor._consecutive_low_yield_compactions = 3
        compressor._last_low_yield_tokens = 240_000
        # 245k >= critical (244800) but has NOT grown by +16k since 240k.
        assert compressor.should_compress(245_000) is True

    def test_cooldown_inert_below_threshold(self, compressor):
        compressor._consecutive_low_yield_compactions = 2
        compressor._last_low_yield_tokens = 64_000
        # Below threshold always returns False regardless of cooldown state.
        assert compressor.should_compress(50_000) is False

    def test_existing_ineffective_guard_still_fires(self, compressor):
        # The pre-existing savings<10% guard is independent and still works.
        compressor._ineffective_compression_count = 2
        compressor._consecutive_low_yield_compactions = 0
        assert compressor.should_compress(90_000) is False

    def test_blocked_should_compress_leaves_no_stale_pending(self, compressor):
        # Regression (review #1/#3): a should_compress() that returns False must
        # NOT leave a stale _pending_compress_tokens for a later direct
        # compress() (context-limit recovery) to reuse as an inflated baseline.
        compressor._pending_compress_tokens = 0
        assert compressor.should_compress(50_000) is False  # below threshold
        assert compressor._pending_compress_tokens == 0
        compressor._consecutive_low_yield_compactions = 1
        compressor._last_low_yield_tokens = 70_000
        assert compressor.should_compress(72_000) is False  # cooldown
        assert compressor._pending_compress_tokens == 0
        # Only the allow path captures the baseline.
        assert compressor.should_compress(90_000) is True
        assert compressor._pending_compress_tokens == 90_000

    def test_cooldown_band_exists_on_small_floored_context(self):
        # Regression (review #2): on a smaller-context model where threshold is
        # near critical, the cooldown band must still be non-empty (not dead
        # code) and must not wedge.
        with patch("agent.context_compressor.get_model_context_length", return_value=100_000):
            c = ContextCompressor(model="m", threshold_percent=0.85,
                                  protect_first_n=2, protect_last_n=2, quiet_mode=True)
        c.context_length = 100_000
        c.threshold_tokens = 85_000
        c._consecutive_low_yield_compactions = 1
        c._last_low_yield_tokens = 85_000
        # Mid-band (below the ~97K critical, < +16K growth) -> blocked.
        assert c.should_compress(88_000) is False
        # Near-critical override still releases before the ceiling -> allowed.
        assert c.should_compress(99_000) is True

    def test_floor_context_fails_open_never_wedges(self):
        # At the 64K minimum (threshold == context), the cooldown simply fails
        # open — never blocks — so it can never wedge a session.
        with patch("agent.context_compressor.get_model_context_length", return_value=64_000):
            c = ContextCompressor(model="m", threshold_percent=0.85,
                                  protect_first_n=2, protect_last_n=2, quiet_mode=True)
        c.context_length = 64_000
        c.threshold_tokens = 64_000
        c._consecutive_low_yield_compactions = 5
        c._last_low_yield_tokens = 64_000
        assert c.should_compress(64_000) is True  # fails open, no wedge


class TestNoopWindowLowYield:
    """Fix A — the no-op compress window registers as low-yield + ineffective."""

    def _msgs(self, n=12):
        out = [{"role": "system", "content": "sys"}]
        for i in range(n):
            out.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"message body {i}",
            })
        return out

    def test_noop_window_increments_low_yield_and_ineffective(self, compressor):
        msgs = self._msgs(12)
        before_ineff = compressor._ineffective_compression_count
        before_low = compressor._consecutive_low_yield_compactions
        # Force the degenerate "no compressible middle" geometry: tail cut at 0
        # makes compress_start (>= head size) >= compress_end.
        with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=0):
            result = compressor.compress(msgs, current_tokens=120_000)
        assert result == msgs  # unchanged
        assert compressor._ineffective_compression_count == before_ineff + 1
        assert compressor._consecutive_low_yield_compactions == before_low + 1
        assert compressor._last_low_yield_tokens == 120_000

    def test_forced_compress_does_not_arm_cooldown(self, compressor):
        # Regression (review #4): a manual /compress (force=True) is
        # user-initiated and must not feed the auto low-yield cooldown, even
        # when it nets a no-op window (the common pinned-window case).
        msgs = self._msgs(12)
        with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=0):
            compressor.compress(msgs, current_tokens=100_000, force=True)
        assert compressor._consecutive_low_yield_compactions == 0
        # And the next AUTO compaction is therefore not suppressed.
        assert compressor.should_compress(90_000) is True

    def test_noop_window_then_cooldown_blocks(self, compressor):
        msgs = self._msgs(12)
        with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=0):
            compressor.compress(msgs, current_tokens=100_000)
        # Immediately after the no-op, an iteration-boundary recheck at a
        # similar token level must be suppressed.
        assert compressor.should_compress(101_000) is False

    def test_cooldown_baseline_uses_measured_not_display_tokens(self, compressor):
        # Regression for the units bug: should_compress() is called with
        # request-rough tokens (incl. tool schemas, ~+20K above messages-only
        # display_tokens). The cooldown baseline must be the MEASURED level so
        # the +growth check compares like-with-like. Here the trigger measured
        # 90K but compress() only sees display_tokens=60K; the baseline must be
        # 90K (else the constant schema offset would defeat the cooldown).
        msgs = self._msgs(12)
        compressor.should_compress(90_000)  # measured trigger level
        with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=0):
            compressor.compress(msgs, current_tokens=60_000)  # display (messages-only)
        assert compressor._last_low_yield_tokens == 90_000
        # A recheck at 95K (only +5K over the measured 90K baseline) is blocked;
        # if the baseline had been the 60K display value, +growth would pass.
        assert compressor.should_compress(95_000) is False
        # +growth past 90K+16K is allowed.
        assert compressor.should_compress(90_000 + 16_000) is True


class TestEmergencyTailPrune:
    """Fix C — oversized tool-results in a bloated protected tail get truncated."""

    BIG = "X" * (_EMERGENCY_TAIL_TOOL_RESULT_CHARS + 4000)  # > oversize threshold

    def _conversation(self, n_big_tail):
        """Head + a small middle + n_big_tail huge tool-results at the end."""
        msgs = [{"role": "system", "content": "sys"}]
        # small middle
        for i in range(3):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        # tail: alternating assistant tool_call + huge tool result
        for j in range(n_big_tail):
            cid = f"call_{j}"
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": cid, "function": {"name": "read_file",
                                                          "arguments": f'{{"path":"f{j}.py"}}'}}],
            })
            msgs.append({"role": "tool", "tool_call_id": cid, "content": self.BIG})
        return msgs

    def test_truncates_old_oversized_keeps_recent(self, compressor):
        msgs = self._conversation(n_big_tail=4)
        # Small tail budget so the 4 huge results count as bloated tail.
        budget = 2000  # tokens
        result, pruned = compressor._prune_old_tool_results(
            msgs, protect_tail_count=2, protect_tail_tokens=budget,
        )
        big_results = [m for m in result if m.get("role") == "tool"]
        intact = [m for m in big_results if m["content"] == self.BIG]
        truncated = [m for m in big_results if m["content"] != self.BIG]
        # Exactly _EMERGENCY_TAIL_KEEP_RECENT most-recent oversized stay intact.
        assert len(intact) == _EMERGENCY_TAIL_KEEP_RECENT
        assert len(truncated) == 4 - _EMERGENCY_TAIL_KEEP_RECENT
        assert pruned >= 4 - _EMERGENCY_TAIL_KEEP_RECENT
        # The most-recent tool result (last in the list) must be the intact one.
        assert big_results[-1]["content"] == self.BIG

    def test_no_truncation_when_tail_not_bloated(self, compressor):
        # One big tail result, generous budget -> tail not bloated -> untouched.
        msgs = self._conversation(n_big_tail=1)
        budget = 100_000  # tokens — far exceeds the single tail result
        result, pruned = compressor._prune_old_tool_results(
            msgs, protect_tail_count=2, protect_tail_tokens=budget,
        )
        big_results = [m for m in result if m.get("role") == "tool"]
        assert all(m["content"] == self.BIG for m in big_results)

    def test_small_tail_results_never_touched(self, compressor):
        # With a budget that protects the whole tail, small (below-threshold)
        # tool-results are touched by NEITHER the normal prune (they're in the
        # protected tail) NOR the emergency pass (not oversized).
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(3):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        # Unique per result so the dedup pass (Pass 1) doesn't fire — we want
        # to prove the EMERGENCY pass leaves small results alone, in isolation.
        smalls = [f"unique result {j} " + ("y" * 480) for j in range(6)]
        for j in range(6):
            cid = f"c{j}"
            msgs.append({"role": "assistant", "content": None,
                         "tool_calls": [{"id": cid, "function": {"name": "read_file", "arguments": "{}"}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "content": smalls[j]})
        result, pruned = compressor._prune_old_tool_results(
            msgs, protect_tail_count=2, protect_tail_tokens=100_000,
        )
        tail_tools = [m for m in result if m.get("role") == "tool"]
        # No oversized content existed and the whole tail is protected.
        assert [m["content"] for m in tail_tools] == smalls
