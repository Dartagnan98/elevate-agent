from __future__ import annotations

from gateway import guardrails


def _config(
    *,
    max_messages: int = 2,
    window_seconds: int = 10,
    rate_enabled: bool = True,
    usage_enabled: bool = False,
    daily_token_cap: int = 1_000,
) -> dict:
    return {
        "guardrails": {
            "enabled": True,
            "rate_limit": {
                "enabled": rate_enabled,
                "max_messages": max_messages,
                "window_seconds": window_seconds,
            },
            "usage": {
                "enabled": usage_enabled,
                "daily_token_cap": daily_token_cap,
                "window_seconds": 86_400,
            },
        }
    }


def _check(config: dict, *, now: float = 100.0):
    return guardrails.check_gateway_guardrails(
        config=config,
        identity_key="telegram:user-1",
        source="telegram",
        session_key="session-1",
        now=now,
    )


def test_rate_limit_blocks_after_window_capacity(monkeypatch):
    for name in (
        "ELEVATE_RATE_LIMIT_MESSAGES",
        "ELEVATE_RATE_LIMIT_WINDOW_SECONDS",
        "ELEVATE_DAILY_TOKEN_CAP",
        "ELEVATE_TOKEN_CAP_WINDOW_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    guardrails.reset_guardrails_for_tests()
    config = _config(max_messages=2, window_seconds=10)

    assert _check(config, now=100.0).allowed is True
    assert _check(config, now=101.0).allowed is True

    decision = _check(config, now=102.0)
    assert decision.allowed is False
    assert decision.reason == "rate_limited"
    assert decision.retry_after_seconds is not None
    assert decision.retry_after_seconds > 0
    assert "Rate limit hit" in decision.message


def test_rate_limit_can_be_disabled(monkeypatch):
    monkeypatch.delenv("ELEVATE_RATE_LIMIT_MESSAGES", raising=False)
    guardrails.reset_guardrails_for_tests()
    config = _config(max_messages=1, window_seconds=10, rate_enabled=False)

    assert _check(config, now=100.0).allowed is True
    assert _check(config, now=101.0).allowed is True
    assert _check(config, now=102.0).allowed is True


def test_token_cap_blocks_when_usage_sum_reaches_cap(monkeypatch):
    guardrails.reset_guardrails_for_tests()
    monkeypatch.delenv("ELEVATE_DAILY_TOKEN_CAP", raising=False)

    def fake_sum_recent_tokens(*, since, source=None, session_key=None):
        assert source == "telegram"
        assert session_key == "session-1"
        assert since < 100.0
        return 2_000

    monkeypatch.setattr("gateway.usage_ledger.sum_recent_tokens", fake_sum_recent_tokens)
    decision = _check(_config(usage_enabled=True, daily_token_cap=1_000), now=100.0)

    assert decision.allowed is False
    assert decision.reason == "token_cap_exceeded"
    assert decision.used_tokens == 2_000
    assert decision.token_cap == 1_000
    assert "Daily token cap reached" in decision.message


def test_token_cap_fail_open_when_ledger_unavailable(monkeypatch):
    guardrails.reset_guardrails_for_tests()

    def raise_sum_recent_tokens(*, since, source=None, session_key=None):
        raise RuntimeError("ledger offline")

    monkeypatch.setattr("gateway.usage_ledger.sum_recent_tokens", raise_sum_recent_tokens)
    decision = _check(_config(usage_enabled=True, daily_token_cap=1), now=100.0)

    assert decision.allowed is True
