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


def test_default_turn_deadline_is_disabled(monkeypatch):
    """Elevate intentionally defaults to disabled (0.0) — heavy agentic
    workflows can't tolerate a wall-clock cap that can't distinguish a
    productive long turn from a dead one. Per-request hangs are caught by
    the non-stream stale detector; api_max_retries bounds retry storms.
    See run_agent.py lines 1690-1700."""
    monkeypatch.delenv("ELEVATE_API_TURN_DEADLINE", raising=False)
    assert _make_agent()._api_turn_deadline_s == 0.0


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
    assert _make_agent(api_turn_deadline="not-a-number")._api_turn_deadline_s == 0.0
