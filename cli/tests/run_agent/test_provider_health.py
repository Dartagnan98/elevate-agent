"""Tests for the cross-session provider usage-cap circuit breaker."""
import os
import tempfile

import pytest

from agent import provider_health as ph


@pytest.fixture(autouse=True)
def _tmp_home(monkeypatch):
    """Isolate breaker state files to a temp ~/.elevate."""
    d = tempfile.mkdtemp()
    monkeypatch.setattr(ph, "_state_path", lambda provider: os.path.join(d, f"provider_{ph._sanitize(provider)}.json"))
    yield d


# --- the genuine-vs-transient gate (the safety-critical part) --------------

def test_genuine_cap_detected():
    # The exact message from Skyleigh's logs.
    assert ph.is_genuine_usage_cap("HTTP 429: The usage limit has been reached") is True
    assert ph.is_genuine_usage_cap("quota exceeded for this account") is True


def test_transient_429_does_not_trip():
    # Transient throttling carries "try again / retry / wait" language — must
    # NOT be treated as a cap, or we'd block a healthy provider cross-session.
    assert ph.is_genuine_usage_cap("Rate limited, please try again in 5 seconds") is False
    assert ph.is_genuine_usage_cap("rate limit exceeded, retry after 10s") is False
    assert ph.is_genuine_usage_cap("usage limit, please wait and try again") is False
    assert ph.is_genuine_usage_cap("too many requests") is False  # not a usage-cap phrase
    assert ph.is_genuine_usage_cap(None) is False
    assert ph.is_genuine_usage_cap("") is False


# --- record / remaining / clear -------------------------------------------

def test_record_then_remaining_then_clear():
    assert ph.provider_rate_limit_remaining("openai-codex") is None
    ph.record_provider_rate_limit("openai-codex", default_cooldown=300.0)
    rem = ph.provider_rate_limit_remaining("openai-codex")
    assert rem is not None and 290 < rem <= 300
    ph.clear_provider_rate_limit("openai-codex")
    assert ph.provider_rate_limit_remaining("openai-codex") is None


def test_retry_after_header_drives_cooldown():
    ph.record_provider_rate_limit("anthropic", headers={"retry-after": "120"})
    rem = ph.provider_rate_limit_remaining("anthropic")
    assert rem is not None and 110 < rem <= 120


def test_providers_do_not_collide():
    ph.record_provider_rate_limit("openai-codex", default_cooldown=300.0)
    assert ph.provider_rate_limit_remaining("openai-codex") is not None
    # A different provider is unaffected.
    assert ph.provider_rate_limit_remaining("anthropic") is None


def test_sanitize_handles_odd_provider_names():
    # Should not raise and should round-trip through record/remaining.
    ph.record_provider_rate_limit("weird/Provider name", default_cooldown=120.0)
    assert ph.provider_rate_limit_remaining("weird/Provider name") is not None
