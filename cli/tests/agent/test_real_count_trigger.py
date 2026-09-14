"""Tests for the real-count compression trigger (agent/conversation_compression.py).

Covers the 2026-06 trigger rework:
  - real-count mode triggers at 0.90 of the window, estimate mode keeps 0.85
  - a fixed output reserve (max output tokens + summarizer overhead + pad)
    caps the trigger at window - reserve and can force an EARLIER trigger
  - delta estimation: projected usage = last real prompt_tokens + rough
    estimate of messages appended since that call (never the whole list)
  - invalidation: list replacement / removals / post-compaction reset the
    measurement to estimate mode until the next API call reports usage
  - prune_only keeps its band but runs off the same measurement
  - anti-thrash (#14695) guards keep applying
"""

from unittest.mock import patch

import pytest

from agent.context_compressor import ContextCompressor
from agent.conversation_compression import (
    DEFAULT_MAX_OUTPUT_TOKENS_GUESS,
    ESTIMATE_MODE_THRESHOLD,
    OUTPUT_RESERVE_SAFETY_PAD_TOKENS,
    REAL_COUNT_MODE_THRESHOLD,
    SUMMARIZER_OUTPUT_OVERHEAD_TOKENS,
    RealUsageProjector,
    compute_output_reserve_tokens,
    effective_compression_trigger_tokens,
    resolve_compression_pressure,
    should_compress_now,
    should_prune_only_now,
)
from agent.model_metadata import estimate_messages_tokens_rough

WINDOW = 200_000
# Default reserve: no session max_tokens configured
DEFAULT_RESERVE = (
    max(SUMMARIZER_OUTPUT_OVERHEAD_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS_GUESS)
    + OUTPUT_RESERVE_SAFETY_PAD_TOKENS
)


@pytest.fixture()
def compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=WINDOW
    ):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.85,
            protect_first_n=2,
            protect_last_n=2,
            quiet_mode=True,
        )


def _msgs(n=3, chars=400):
    return [{"role": "user", "content": "x" * chars} for _ in range(n)]


# ──────────────────────────────────────────────────────────────────────
# Output reserve
# ──────────────────────────────────────────────────────────────────────


class TestOutputReserve:
    def test_default_when_no_max_tokens(self):
        assert compute_output_reserve_tokens(None) == DEFAULT_RESERVE
        assert compute_output_reserve_tokens(0) == DEFAULT_RESERVE

    def test_large_configured_max_tokens_dominates(self):
        # 64K output > summarizer overhead → reserve follows max_tokens
        assert (
            compute_output_reserve_tokens(64_000)
            == 64_000 + OUTPUT_RESERVE_SAFETY_PAD_TOKENS
        )

    def test_small_configured_max_tokens_floor_is_summarizer(self):
        # The compaction request itself must fit even when outputs are tiny
        assert (
            compute_output_reserve_tokens(1_024)
            == SUMMARIZER_OUTPUT_OVERHEAD_TOKENS + OUTPUT_RESERVE_SAFETY_PAD_TOKENS
        )

    def test_garbage_value_falls_back(self):
        assert compute_output_reserve_tokens("not-a-number") == DEFAULT_RESERVE


# ──────────────────────────────────────────────────────────────────────
# Trigger line
# ──────────────────────────────────────────────────────────────────────


class TestEffectiveTrigger:
    def test_estimate_mode_keeps_085(self, compressor):
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=False,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        # min(0.85*200K=170K, 200K-18K=182K) = 170K
        assert trigger == int(WINDOW * ESTIMATE_MODE_THRESHOLD)

    def test_real_mode_rises_to_090(self, compressor):
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=True,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        # min(0.90*200K=180K, 182K) = 180K
        assert trigger == int(WINDOW * REAL_COUNT_MODE_THRESHOLD)

    def test_pinned_threshold_wins_in_real_mode(self, compressor):
        # If the caller marks a threshold as user-pinned, real-count mode must
        # not bump it to 0.90. run_agent decides whether the default 0.85 is
        # actually user-pinned.
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=True,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=True,
        )
        assert trigger == compressor.threshold_tokens == int(WINDOW * 0.85)

    def test_auto_lowered_threshold_not_bumped(self, compressor):
        # Aux-feasibility auto-lower rewrites threshold_percent/_tokens;
        # the real-mode bump only applies to the untouched 0.85 default.
        compressor.threshold_tokens = 100_000
        compressor.threshold_percent = 0.5
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=True,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert trigger == 100_000

    def test_output_reserve_forces_earlier_trigger(self, compressor):
        # window - reserve < threshold*window → reserve line wins
        reserve = compute_output_reserve_tokens(64_000)  # 66K
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=False,
            output_reserve_tokens=reserve,
            threshold_pinned=False,
        )
        assert trigger == WINDOW - reserve  # 134K < 170K
        assert trigger < compressor.threshold_tokens

    def test_reserve_line_floored_at_half_window(self, compressor):
        # A pathological reserve can never drag the trigger below 50% of
        # the window (compact-every-turn protection).
        trigger = effective_compression_trigger_tokens(
            compressor,
            real_mode=False,
            output_reserve_tokens=150_000,
            threshold_pinned=False,
        )
        assert trigger == WINDOW // 2


# ──────────────────────────────────────────────────────────────────────
# RealUsageProjector
# ──────────────────────────────────────────────────────────────────────


class TestRealUsageProjector:
    def test_no_record_means_no_projection(self):
        p = RealUsageProjector()
        assert p.project(_msgs()) is None
        assert p.has_real_count is False

    def test_projects_exact_real_count_for_unchanged_list(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        assert p.project(msgs) == 50_000

    def test_delta_estimation_for_appended_messages(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        appended = [
            {"role": "assistant", "content": "y" * 2_000},
            {"role": "tool", "content": "z" * 8_000},
        ]
        msgs.extend(appended)
        expected_delta = estimate_messages_tokens_rough(appended)
        assert expected_delta > 0
        assert p.project(msgs) == 50_000 + expected_delta

    def test_list_replacement_invalidates(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        new_list = [m.copy() for m in msgs]  # prune_only / compress shape
        assert p.project(new_list) is None

    def test_removal_invalidates(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        msgs.pop()  # thinking-prefill pop
        assert p.project(msgs) is None

    def test_in_place_surgery_before_snapshot_invalidates(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        msgs[-1] = dict(msgs[-1])  # replace last counted message object
        assert p.project(msgs) is None

    def test_zero_usage_keeps_previous_snapshot(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        p.record(msgs, 0)  # provider returned no usage — keep old snapshot
        assert p.project(msgs) == 50_000

    def test_invalidate_then_rerecord(self):
        p = RealUsageProjector()
        msgs = _msgs(4)
        p.record(msgs, 50_000)
        p.invalidate()
        assert p.project(msgs) is None
        p.record(msgs, 30_000)
        assert p.project(msgs) == 30_000


# ──────────────────────────────────────────────────────────────────────
# resolve_compression_pressure + should_compress_now (mode behavior)
# ──────────────────────────────────────────────────────────────────────


class TestModeThresholds:
    def test_real_count_mode_triggers_at_090_not_085(self, compressor):
        """At 87.5% of the window: estimate mode compacts, real mode doesn't."""
        msgs = _msgs(4)
        projector = RealUsageProjector()
        projector.record(msgs, 175_000)  # between 170K (0.85) and 180K (0.90)

        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            msgs,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is True
        assert measured == 175_000
        assert trigger == 180_000
        assert should_compress_now(compressor, measured, trigger) is False

        # Real-count mode does fire once past 0.90
        projector.record(msgs, 181_000)
        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            msgs,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode and measured == 181_000
        assert should_compress_now(compressor, measured, trigger) is True

    def test_estimate_fallback_stays_085(self, compressor):
        """Same 175K measurement without a valid real count → fires at 0.85."""
        msgs = _msgs(4)
        compressor.last_prompt_tokens = 175_000  # stale real count, no projection
        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            None,  # no projector (resumed session / fresh agent)
            msgs,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is False
        assert measured == 175_000
        assert trigger == 170_000
        assert should_compress_now(compressor, measured, trigger) is True

    def test_output_reserve_forces_earlier_compaction(self, compressor):
        """window - reserve < threshold*window → trigger moves below 0.85
        and should_compress_now still fires (despite should_compress's own
        internal threshold compare sitting higher)."""
        reserve = compute_output_reserve_tokens(64_000)  # 66K → line at 134K
        msgs = _msgs(4)
        projector = RealUsageProjector()
        projector.record(msgs, 140_000)  # only 70% of the window

        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            msgs,
            output_reserve_tokens=reserve,
            threshold_pinned=False,
        )
        assert real_mode is True
        assert trigger == WINDOW - reserve == 134_000
        assert should_compress_now(compressor, measured, trigger) is True

    def test_delta_estimation_after_real_count(self, compressor):
        msgs = _msgs(4)
        projector = RealUsageProjector()
        projector.record(msgs, 100_000)
        appended = [{"role": "tool", "content": "t" * 40_000}]
        msgs.extend(appended)

        measured, _trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            msgs,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is True
        assert measured == 100_000 + estimate_messages_tokens_rough(appended)

    def test_post_compaction_resets_to_estimate_mode(self, compressor):
        """After compaction: projector invalidated + -1 sentinel → measured 0
        (no re-trigger, #14695); the next API-reported usage restores real
        mode."""
        msgs = _msgs(4)
        projector = RealUsageProjector()
        projector.record(msgs, 190_000)

        # Compaction runs (mirrors run_agent._compress_context bookkeeping)
        projector.invalidate()
        compressor.last_prompt_tokens = -1
        compressor.awaiting_real_usage_after_compression = True
        compacted = [m.copy() for m in msgs[:2]]

        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            compacted,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is False
        assert measured == 0
        assert should_compress_now(compressor, measured, trigger) is False
        assert should_prune_only_now(compressor, measured, trigger) is False

        # Next API call reports usage for the compacted conversation
        compressor.update_from_response(
            {"prompt_tokens": 40_000, "completion_tokens": 100, "total_tokens": 40_100}
        )
        projector.record(compacted, 40_000)
        measured, trigger, real_mode = resolve_compression_pressure(
            compressor,
            projector,
            compacted,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is True
        assert measured == 40_000
        assert trigger == 180_000  # back on the real-count line

    def test_full_estimate_when_usage_never_reported(self, compressor):
        """#2153 fallback: no real count anywhere → estimate the whole list."""
        msgs = _msgs(4, chars=4_000)
        compressor.last_prompt_tokens = 0
        measured, _trigger, real_mode = resolve_compression_pressure(
            compressor,
            RealUsageProjector(),
            msgs,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
        )
        assert real_mode is False
        assert measured == estimate_messages_tokens_rough(msgs)

    def test_estimate_fallback_can_use_effective_cursor_payload(self, compressor):
        """Resumed cursor sessions estimate summary+tail, not full transcript."""
        full_transcript = _msgs(8, chars=4_000)
        effective_payload = _msgs(2, chars=400)
        compressor.last_prompt_tokens = 0

        measured, _trigger, real_mode = resolve_compression_pressure(
            compressor,
            RealUsageProjector(),
            full_transcript,
            output_reserve_tokens=DEFAULT_RESERVE,
            threshold_pinned=False,
            fallback_messages=effective_payload,
        )

        assert real_mode is False
        assert measured == estimate_messages_tokens_rough(effective_payload)
        assert measured < estimate_messages_tokens_rough(full_transcript)

    def test_anti_thrash_backoff_still_applies(self, compressor):
        """#14695: two ineffective compressions in a row veto the trigger."""
        compressor._ineffective_compression_count = 2
        assert should_compress_now(compressor, 195_000, 180_000) is False


# ──────────────────────────────────────────────────────────────────────
# prune_only stage keeps its band, on the same measurement
# ──────────────────────────────────────────────────────────────────────


class TestPruneOnlyStage:
    def test_band_below_threshold_delegates(self, compressor):
        # 72% of 200K = 144K soft bar; 150K is in the classic band
        trigger = 170_000
        assert should_prune_only_now(compressor, 143_000, trigger) is False
        assert should_prune_only_now(compressor, 150_000, trigger) is True

    def test_gap_between_threshold_and_raised_trigger_is_prune_band(self, compressor):
        # Real-count mode: trigger 180K, threshold_tokens 170K.
        # 175K should prune, not compress.
        compressor._last_prune_attempt_tokens = 0
        assert should_prune_only_now(compressor, 175_000, 180_000) is True
        assert should_compress_now(compressor, 175_000, 180_000) is False

    def test_gap_band_rate_limited(self, compressor):
        # After an attempt at 175K, needs +5% of window (10K) to retry
        compressor._last_prune_attempt_tokens = 175_000
        assert should_prune_only_now(compressor, 176_000, 180_000) is False
        # (185K would already be past the 180K trigger → compress instead)
        assert should_prune_only_now(compressor, 185_000, 180_000) is False

    def test_at_or_past_trigger_is_compress_territory(self, compressor):
        assert should_prune_only_now(compressor, 180_000, 180_000) is False

    def test_zero_measurement_never_prunes(self, compressor):
        assert should_prune_only_now(compressor, 0, 180_000) is False
