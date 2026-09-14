"""Real-code tests for the session-hygiene ineffective-compression guard.

These import the ACTUAL helpers from gateway.run (not a replica), so the safety
gate is pinned: the guard must NEVER skip a session that genuinely needs
compaction (near the token limit, or a real token-trigger) -- otherwise the next
agent turn is handed an over-limit payload, the exact overflow hygiene prevents.
"""

from gateway.run import (
    _hygiene_effective_messages_for_pressure,
    _hygiene_should_skip,
    _hygiene_record,
    _HYGIENE_NOOP_RETRY_MARGIN,
)

WARN = 190_000            # stand-in for _warn_token_threshold (0.95 * context)
UNDER = 100_000           # comfortably under the warn line
MARGIN = _HYGIENE_NOOP_RETRY_MARGIN


def _skip(guard, sid, msg_count, reason="message_count", approx_tokens=UNDER):
    return _hygiene_should_skip(
        guard, sid,
        msg_count=msg_count, margin=MARGIN,
        reason=reason, approx_tokens=approx_tokens, warn_tokens=WARN,
    )


def test_no_entry_never_skips():
    assert _skip({}, "s", 100) is False


def test_same_count_message_count_noop_skips():
    g = {"s": 100}
    assert _skip(g, "s", 100) is True
    assert g["s"] == 100  # entry preserved, not cleared


def test_within_margin_and_boundary_skip():
    g = {"s": 100}
    assert _skip(g, "s", 124) is True   # inside margin
    assert _skip(g, "s", 125) is True   # exact boundary (+25)


def test_growth_past_margin_retries_and_clears():
    g = {"s": 100}
    assert _skip(g, "s", 126) is False  # +26 -> past margin -> retry
    assert "s" not in g                 # stale entry cleared


def test_near_limit_tokens_never_skip():
    # The high finding: a session within the message margin but whose tokens are
    # at/over the 95% warn line MUST still compact (never get suppressed).
    g = {"s": 100}
    assert _skip(g, "s", 100, approx_tokens=WARN) is False       # at the line
    assert _skip(g, "s", 100, approx_tokens=WARN + 1) is False   # over the line
    assert g["s"] == 100  # preserved (not a growth-clear), just not skipped


def test_token_triggered_compression_not_false_skipped():
    # A token-reason trigger means re-compaction can still help -> never skip.
    g = {"s": 100}
    assert _skip(g, "s", 100, reason="tokens") is False
    assert g["s"] == 100  # preserved


def test_critical_pressure_not_false_skipped():
    g = {"s": 100}
    assert _skip(g, "s", 100, reason="critical_pressure") is False
    assert g["s"] == 100  # preserved


def test_record_ineffective_then_effective_clears():
    g = {}
    _hygiene_record(g, "s", msg_count=100, ineffective=True)
    assert g == {"s": 100}
    _hygiene_record(g, "s", msg_count=100, ineffective=False)  # effective compaction
    assert "s" not in g


def test_record_rerecord_moves_to_end():
    g = {}
    _hygiene_record(g, "a", msg_count=1, ineffective=True)
    _hygiene_record(g, "b", msg_count=2, ineffective=True)
    _hygiene_record(g, "a", msg_count=3, ineffective=True)  # re-record a
    assert list(g.keys()) == ["b", "a"]  # a moved to the end (recency order)
    assert g["a"] == 3


def test_guard_is_bounded():
    g = {}
    for i in range(50):
        _hygiene_record(g, f"s{i}", msg_count=i, ineffective=True, max_entries=8)
    assert len(g) == 8
    assert "s49" in g and "s0" not in g  # newest kept, oldest evicted


def test_full_lifecycle():
    g = {}
    _hygiene_record(g, "s", msg_count=100, ineffective=True)   # ineffective -> recorded
    assert _skip(g, "s", 105) is True                          # same-ish, msg trigger -> skip
    assert _skip(g, "s", 130) is False                         # grew past margin -> retry
    assert "s" not in g                                        # cleared on the retry
    _hygiene_record(g, "s", msg_count=130, ineffective=False)  # then compresses effectively
    assert "s" not in g


def test_margin_constant_is_25():
    assert _HYGIENE_NOOP_RETRY_MARGIN == 25


def test_effective_messages_without_cursor_returns_original_history():
    history = [{"role": "user", "content": "one"}]
    assert _hygiene_effective_messages_for_pressure(history) is history


def test_effective_messages_uses_summary_and_tail_after_cursor():
    history = [
        {"role": "user", "content": "old 1"},
        {"role": "assistant", "content": "old 2"},
        {"role": "user", "content": "tail"},
    ]

    effective = _hygiene_effective_messages_for_pressure(
        history,
        compaction_cursor=2,
        compaction_summary="already summarized",
    )

    assert len(effective) == 2
    assert effective[0]["role"] == "user"
    assert "already summarized" in effective[0]["content"]
    assert effective[1]["content"] == "tail"


def test_effective_messages_clamps_cursor_to_keep_tail():
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "last"},
    ]

    effective = _hygiene_effective_messages_for_pressure(
        history,
        compaction_cursor=20,
        compaction_summary="summary",
    )

    assert [m["content"] for m in effective[1:]] == ["last"]
