"""Codex compression summaries must default to LOW reasoning effort.

The Phase-5 fix made the auxiliary model track the active model, so for a
ChatGPT/Codex user ``summary_model`` == main model (e.g. gpt-5.5). That model
does FULL reasoning by default, and a single summary of a near-full context
window then exceeds the auxiliary stream timeout — compaction silently fails,
context never shrinks, and the account's quota burns into usage-cap lockouts
(the exact symptom Phase 5 was meant to cure, re-surfaced as a timeout instead
of a 400). A compaction summary is structured extraction, not deep reasoning:
low effort returns the same result in <10s. ``call_llm`` injects this default
for the compression task on the openai-codex provider unless the caller/config
already set an explicit effort.
"""
import agent.auxiliary_client as ac

_apply = ac._apply_codex_compression_reasoning_default


def test_injects_low_effort_for_codex_compression_when_unset():
    out = _apply("compression", "openai-codex", {})
    assert out["reasoning"] == {"effort": "low"}


def test_does_not_mutate_caller_dict():
    original = {}
    out = _apply("compression", "openai-codex", original)
    assert original == {}  # augmented copy returned, caller dict untouched
    assert out is not original


def test_respects_explicit_effort():
    out = _apply("compression", "openai-codex", {"reasoning": {"effort": "high"}})
    assert out["reasoning"] == {"effort": "high"}


def test_preserves_other_extra_body_keys():
    out = _apply("compression", "openai-codex", {"foo": "bar"})
    assert out["foo"] == "bar"
    assert out["reasoning"] == {"effort": "low"}


def test_noop_for_non_codex_provider():
    body = {"x": 1}
    assert _apply("compression", "anthropic", body) is body


def test_noop_for_non_compression_task():
    body = {"x": 1}
    assert _apply("vision", "openai-codex", body) is body


def test_provider_match_is_case_and_whitespace_tolerant():
    out = _apply("compression", "  OpenAI-Codex  ", {})
    assert out["reasoning"] == {"effort": "low"}


def test_reasoning_present_but_no_effort_gets_default():
    # A reasoning dict without an effort key (e.g. {"summary": "auto"}) should
    # still receive the low-effort default, merged with the existing keys.
    out = _apply("compression", "openai-codex", {"reasoning": {"summary": "auto"}})
    assert out["reasoning"] == {"summary": "auto", "effort": "low"}
