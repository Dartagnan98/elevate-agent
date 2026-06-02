"""G3 — operational PG pool sizing + checkout timeout.

The old pool was `max_size=10` with no checkout timeout, so a few concurrent
dashboard scans plus an active turn could exhaust it and block indefinitely.
Sizing now comes from `_pool_sizing()` (env-overridable, floored), and the
pool gets an explicit checkout timeout so exhaustion is a fast, retryable
error rather than a hang.
"""

from __future__ import annotations

import pytest

from elevate_cli.data import connection


def test_defaults(monkeypatch):
    monkeypatch.delenv("ELEVATE_PG_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("ELEVATE_PG_POOL_TIMEOUT_S", raising=False)
    max_size, timeout = connection._pool_sizing()
    assert max_size == 20
    assert timeout == 10.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("ELEVATE_PG_POOL_MAX_SIZE", "32")
    monkeypatch.setenv("ELEVATE_PG_POOL_TIMEOUT_S", "5.5")
    max_size, timeout = connection._pool_sizing()
    assert max_size == 32
    assert timeout == 5.5


def test_max_size_floored(monkeypatch):
    # Never drop below headroom for the agent-run pool + dashboard workers.
    monkeypatch.setenv("ELEVATE_PG_POOL_MAX_SIZE", "1")
    assert connection._pool_sizing()[0] == 4


@pytest.mark.parametrize("bad", ["abc", "", "1.2.3"])
def test_bad_values_fall_back_to_defaults(monkeypatch, bad):
    monkeypatch.setenv("ELEVATE_PG_POOL_MAX_SIZE", bad)
    monkeypatch.setenv("ELEVATE_PG_POOL_TIMEOUT_S", bad)
    max_size, timeout = connection._pool_sizing()
    assert max_size == 20
    assert timeout == 10.0
