"""Tests for the Nous-Elevate-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"elevate"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``elevate-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "elevate" tag namespace.

``is_nous_elevate_non_agentic`` should only match the actual Nous Research
Elevate-3 / Elevate-4 chat family.
"""

from __future__ import annotations

import pytest

from elevate_cli.model_switch import (
    _ELEVATE_MODEL_WARNING,
    _check_elevate_model_warning,
    is_nous_elevate_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Elevate-3-Llama-3.1-70B",
        "NousResearch/Elevate-3-Llama-3.1-405B",
        "elevate-3",
        "Elevate-3",
        "elevate-4",
        "elevate-4-405b",
        "elevate_4_70b",
        "openrouter/elevate3:70b",
        "openrouter/nousresearch/elevate-4-405b",
        "NousResearch/Elevate3",
        "elevate-3.1",
    ],
)
def test_matches_real_nous_elevate_chat_models(model_name: str) -> None:
    assert is_nous_elevate_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Elevate 3/4"
    )
    assert _check_elevate_model_warning(model_name) == _ELEVATE_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "elevate-brain:qwen3-14b-ctx16k",
        "elevate-brain:qwen3-14b-ctx32k",
        "elevate-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Elevate models we don't warn about
        "elevate-llm-2",
        "elevate2-pro",
        "nous-elevate-2-mistral",
        # Edge cases
        "",
        "elevate",  # bare "elevate" isn't the 3/4 family
        "elevate-brain",
        "brain-elevate-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_elevate_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Elevate 3/4"
    )
    assert _check_elevate_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_elevate_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_elevate_model_warning("") == ""
