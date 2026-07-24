"""G3 — operational PG pool sizing + checkout timeout.

The old pool was `max_size=10` with no checkout timeout, so a few concurrent
dashboard scans plus an active turn could exhaust it and block indefinitely.
Sizing now comes from `_pool_sizing()` (env-overridable, floored), and the
pool gets an explicit checkout timeout so exhaustion is a fast, retryable
error rather than a hang.
"""

from __future__ import annotations

import time

import pytest

from elevate_cli.data import connection


def test_defaults(monkeypatch):
    monkeypatch.delenv("ELEVATE_PG_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("ELEVATE_PG_POOL_TIMEOUT_S", raising=False)
    max_size, timeout = connection._pool_sizing()
    assert max_size == 20
    # A3: short checkout timeout so DB-down is a fast 503, not a 10s hang.
    assert timeout == 3.0


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
    assert timeout == 3.0


# ─── A3: reconnect timeout (self-heal window) ──────────────────────────────


def test_reconnect_timeout_default(monkeypatch):
    monkeypatch.delenv("ELEVATE_PG_POOL_RECONNECT_TIMEOUT_S", raising=False)
    assert connection._reconnect_timeout_s() == 10.0


def test_reconnect_timeout_env_override(monkeypatch):
    monkeypatch.setenv("ELEVATE_PG_POOL_RECONNECT_TIMEOUT_S", "4.5")
    assert connection._reconnect_timeout_s() == 4.5


def test_reconnect_timeout_floored_and_bad_values(monkeypatch):
    monkeypatch.setenv("ELEVATE_PG_POOL_RECONNECT_TIMEOUT_S", "0")
    assert connection._reconnect_timeout_s() == 1.0
    monkeypatch.setenv("ELEVATE_PG_POOL_RECONNECT_TIMEOUT_S", "nonsense")
    assert connection._reconnect_timeout_s() == 10.0


# ─── A3: pool built for fast-fail + self-heal ──────────────────────────────


def test_pool_built_with_fast_fail_knobs():
    connection._reset_schema_cache()
    try:
        with connection.connect() as conn:
            conn.execute("SELECT 1")
        pool = connection._pool
        assert pool is not None
        # Bounded wait queue + short checkout timeout ⇒ DB-down is a fast error,
        # not a thread-pool-saturating hang.
        assert pool.max_waiting == 20
        assert pool.timeout == 3.0
    finally:
        connection._reset_schema_cache()


def test_reconnect_failed_restarts_pg_and_drops_pool(monkeypatch):
    """The reconnect_failed hook restarts embedded PG (A2) and drops the dead
    pool so the next checkout rebuilds against the recovered server (A3)."""
    restarts = []
    monkeypatch.setattr(
        connection.pg_server, "restart_server", lambda: restarts.append(1)
    )

    class _FakePool:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = _FakePool()
    monkeypatch.setattr(connection, "_pool", fake)
    monkeypatch.setattr(connection, "_pool_account", "acct_dead")

    connection._rebuild_pool_after_failure(fake)

    assert restarts == [1]
    assert connection._pool is None
    assert connection._pool_account is None
    # The dead pool is closed on a detached daemon thread; give it a beat.
    for _ in range(50):
        if fake.closed:
            break
        time.sleep(0.02)
    assert fake.closed is True


def test_reconnect_failed_ignores_a_pool_that_was_already_replaced(monkeypatch):
    """If the module pool was already rebuilt (not the failed one), the hook
    must not null out the live pool."""
    monkeypatch.setattr(connection.pg_server, "restart_server", lambda: None)

    class _FakePool:
        def close(self):
            pass

    live = _FakePool()
    stale = _FakePool()
    monkeypatch.setattr(connection, "_pool", live)
    monkeypatch.setattr(connection, "_pool_account", "acct_live")

    connection._rebuild_pool_after_failure(stale)

    assert connection._pool is live
    assert connection._pool_account == "acct_live"


# ─── B1: database_reachable liveness probe ─────────────────────────────────


def test_database_reachable_true_against_live_pg():
    connection._reset_schema_cache()
    try:
        with connection.connect() as conn:
            conn.execute("SELECT 1")
        ok, latency_ms, err = connection.database_reachable()
        assert ok is True
        assert err is None
        assert isinstance(latency_ms, float)
        assert latency_ms >= 0.0
    finally:
        connection._reset_schema_cache()


def test_database_reachable_false_when_postmaster_unreachable(monkeypatch):
    # Point the probe at a socket dir with no listener: a direct connect fails
    # fast (no pool, no migrations) and the helper reports it without raising.
    monkeypatch.setattr(
        connection.pg_server,
        "get_uri",
        lambda database="postgres": (
            "postgresql://postgres:@/elevate_op_default"
            "?host=/tmp/elevate-nonexistent-socket-dir-xyz"
        ),
    )
    ok, latency_ms, err = connection.database_reachable()
    assert ok is False
    assert latency_ms is None
    assert err  # a non-empty error string, not a raise


def test_database_reachable_never_raises(monkeypatch):
    # Even if URI resolution itself explodes, the probe returns False.
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(connection.pg_server, "get_uri", _boom)
    ok, latency_ms, err = connection.database_reachable()
    assert ok is False
    assert latency_ms is None
    assert "boom" in err
