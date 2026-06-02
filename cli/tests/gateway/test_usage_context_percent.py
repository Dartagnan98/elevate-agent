"""Context ring (`context_percent`) must reflect CURRENT context occupancy,
never the cumulative session total.

Regression test for the bug where a long turn made the desktop context ring
falsely drain to "0% left / out of context": `_get_usage` computed
`ctx_used = last_prompt_tokens or usage["total"]`, and `usage["total"]` is the
SUM of tokens across every API call this session, which climbs into the
millions and clamps the percentage to 100% while the real context is a small
fraction of the window.
"""

from __future__ import annotations

from types import SimpleNamespace

from tui_gateway.server import _get_usage


def _agent(*, last_prompt_tokens, context_length, session_total_tokens):
    comp = SimpleNamespace(
        last_prompt_tokens=last_prompt_tokens,
        context_length=context_length,
        compression_count=0,
    )
    return SimpleNamespace(
        model="gpt-5.5",
        context_compressor=comp,
        session_input_tokens=0,
        session_output_tokens=0,
        session_cache_read_tokens=0,
        session_cache_write_tokens=0,
        session_prompt_tokens=0,
        session_completion_tokens=0,
        session_total_tokens=session_total_tokens,
        session_api_calls=61,
        provider="openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
    )


def test_percent_reflects_current_context_not_cumulative():
    # Real context 58k of 272k = ~21%, even though the cumulative session
    # total is 1.8M. The old code reported ~100% ("out of context").
    u = _get_usage(
        _agent(last_prompt_tokens=58000, context_length=272000, session_total_tokens=1_800_000)
    )
    assert u["context_used"] == 58000
    assert u["context_max"] == 272000
    assert u["context_percent"] == 21


def test_percent_omitted_when_no_current_measurement():
    # No current prompt size yet -> omit the percentage (UI shows "--"),
    # never inflate it from the cumulative total.
    u = _get_usage(
        _agent(last_prompt_tokens=0, context_length=272000, session_total_tokens=1_800_000)
    )
    assert "context_percent" not in u
    assert "context_used" not in u


def test_percent_clamped_to_100():
    u = _get_usage(
        _agent(last_prompt_tokens=300000, context_length=272000, session_total_tokens=0)
    )
    assert u["context_percent"] == 100
