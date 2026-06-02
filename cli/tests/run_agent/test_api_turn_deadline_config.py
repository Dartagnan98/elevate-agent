"""Tests for the agent.api_turn_deadline config surface.

The non-stream stale detector only guards a *single* request; every retry
resets it, so a run of hung calls can burn far past any single timeout
(observed in production: 2063s on a 6-msg / 17k-token turn before giving
up). ``agent.api_turn_deadline`` is the absolute cumulative wall-clock
ceiling for one API-call sequence; the loop-top guard in
``run_conversation`` enforces it regardless of how many retries reset the
per-call detector.
"""
from unittest.mock import patch

from run_agent import AIAgent


def _make_agent(api_turn_deadline=None):
    cfg = {"agent": {}}
    if api_turn_deadline is not None:
        cfg["agent"]["api_turn_deadline"] = api_turn_deadline

    with patch("run_agent.OpenAI"), \
         patch("elevate_cli.config.load_config", return_value=cfg):
        return AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )


def test_default_turn_deadline_is_600(monkeypatch):
    """Defaults to 600s as a backstop for ONE API-call sequence (a single
    response + its retries — not the whole agentic loop). A response sequence
    past 10min is pathological. Explicit 0 still disables it (see
    test_zero_or_negative_disables). See run_agent.py ~1700-1721."""
    monkeypatch.delenv("ELEVATE_API_TURN_DEADLINE", raising=False)
    assert _make_agent()._api_turn_deadline_s == 600.0


def test_config_override(monkeypatch):
    monkeypatch.delenv("ELEVATE_API_TURN_DEADLINE", raising=False)
    assert _make_agent(api_turn_deadline=600)._api_turn_deadline_s == 600.0
    assert _make_agent(api_turn_deadline="450")._api_turn_deadline_s == 450.0


def test_zero_or_negative_disables(monkeypatch):
    """<=0 means disabled — stored as 0.0 so the loop guard is a no-op."""
    monkeypatch.delenv("ELEVATE_API_TURN_DEADLINE", raising=False)
    assert _make_agent(api_turn_deadline=0)._api_turn_deadline_s == 0.0
    assert _make_agent(api_turn_deadline=-5)._api_turn_deadline_s == 0.0


def test_env_override_when_no_config(monkeypatch):
    monkeypatch.setenv("ELEVATE_API_TURN_DEADLINE", "300")
    assert _make_agent()._api_turn_deadline_s == 300.0


def test_config_beats_env(monkeypatch):
    """Config is consulted before the env var."""
    monkeypatch.setenv("ELEVATE_API_TURN_DEADLINE", "300")
    assert _make_agent(api_turn_deadline=900)._api_turn_deadline_s == 900.0


def test_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("ELEVATE_API_TURN_DEADLINE", raising=False)
    assert _make_agent(api_turn_deadline="not-a-number")._api_turn_deadline_s == 600.0
