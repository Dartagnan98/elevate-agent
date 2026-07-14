"""Strict read-only connection tests for model-facing operational reads."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest

from elevate_cli.data import connection as connection_module
from elevate_cli.data.deals import create_deal


@pytest.fixture(autouse=True)
def _fresh_connection_state():
    connection_module._reset_schema_cache()
    yield
    connection_module._reset_schema_cache()


def _unexpected_bootstrap(*_args, **_kwargs):
    raise AssertionError("read-only connection attempted write-side bootstrap")


def test_cold_read_only_connection_never_bootstraps(monkeypatch):
    monkeypatch.setattr(connection_module, "get_account_key", lambda: "acct_cold")
    monkeypatch.setattr(connection_module, "_get_pool", _unexpected_bootstrap)
    monkeypatch.setattr(
        connection_module,
        "_maybe_adopt_legacy",
        _unexpected_bootstrap,
    )
    monkeypatch.setattr(
        connection_module.pg_server,
        "ensure_database",
        _unexpected_bootstrap,
    )
    monkeypatch.setattr(connection_module, "_ensure_schema", _unexpected_bootstrap)

    with pytest.raises(
        connection_module.OperationalStoreNotReady,
        match="startup has not completed",
    ):
        with connection_module.connect_ready_read_only():
            pytest.fail("cold read-only connection unexpectedly yielded")


def test_read_only_connection_rejects_mismatched_pool_without_touching_it(
    monkeypatch,
):
    class UnusedPool:
        checked_out = False
        closed = False

        def connection(self):
            self.checked_out = True
            raise AssertionError("mismatched pool must not be checked out")

        def close(self):
            self.closed = True

    pool = UnusedPool()
    monkeypatch.setattr(connection_module, "get_account_key", lambda: "acct_active")
    monkeypatch.setattr(connection_module, "_schema_ready_for", "acct_active")
    monkeypatch.setattr(connection_module, "_pool_account", "acct_previous")
    monkeypatch.setattr(connection_module, "_pool", pool)

    with pytest.raises(
        connection_module.OperationalStoreNotReady,
        match="active account",
    ):
        with connection_module.connect_ready_read_only():
            pytest.fail("mismatched read-only connection unexpectedly yielded")

    assert pool.checked_out is False
    assert pool.closed is False
    assert connection_module._pool is pool


def test_account_switch_between_snapshots_fails_before_pool_checkout(monkeypatch):
    class UnusedPool:
        checked_out = False
        closed = False

        def connection(self):
            self.checked_out = True
            raise AssertionError("switched-account pool must not be checked out")

        def close(self):
            self.closed = True

    pool = UnusedPool()
    account_keys = iter(("acct_original", "acct_switched"))
    monkeypatch.setattr(
        connection_module,
        "get_account_key",
        lambda: next(account_keys),
    )
    monkeypatch.setattr(connection_module, "_schema_ready_for", "acct_original")
    monkeypatch.setattr(connection_module, "_pool_account", "acct_original")
    monkeypatch.setattr(connection_module, "_pool", pool)

    with pytest.raises(
        connection_module.OperationalStoreNotReady,
        match="active account",
    ):
        with connection_module.connect_ready_read_only():
            pytest.fail("switched-account connection unexpectedly yielded")

    assert pool.checked_out is False


def test_ready_connection_sets_read_only_and_forces_rollback(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def execute(self, statement):
            self.statements.append(statement)

    class FakeTransaction:
        entered = False
        exited = False

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, *_exc):
            self.exited = True
            return None

    class FakeRawConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.transaction_instance = FakeTransaction()
            self.force_rollback = None

        def cursor(self):
            return self.cursor_instance

        def transaction(self, *, force_rollback=False):
            self.force_rollback = force_rollback
            return self.transaction_instance

    class FakePool:
        def __init__(self, raw):
            self.raw = raw
            self.checkouts = 0
            self.closed = False

        @contextmanager
        def connection(self):
            self.checkouts += 1
            yield self.raw

        def close(self):
            self.closed = True

    raw = FakeRawConnection()
    pool = FakePool(raw)
    monkeypatch.setattr(connection_module, "get_account_key", lambda: "acct_ready")
    monkeypatch.setattr(connection_module, "_schema_ready_for", "acct_ready")
    monkeypatch.setattr(connection_module, "_pool_account", "acct_ready")
    monkeypatch.setattr(connection_module, "_pool", pool)

    with connection_module.connect_ready_read_only() as conn:
        assert conn._raw is raw
        assert raw.transaction_instance.entered is True
        assert raw.transaction_instance.exited is False

    assert pool.checkouts == 1
    assert raw.force_rollback is True
    assert raw.cursor_instance.statements == ["SET TRANSACTION READ ONLY"]
    assert raw.transaction_instance.exited is True


def test_account_switch_during_read_discards_snapshot(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def execute(self, _statement):
            return None

    class FakeTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    class FakeRawConnection:
        def cursor(self):
            return FakeCursor()

        def transaction(self, *, force_rollback=False):
            assert force_rollback is True
            return FakeTransaction()

    class FakePool:
        def __init__(self):
            self.raw = FakeRawConnection()

        @contextmanager
        def connection(self):
            yield self.raw

        def close(self):
            return None

    pool = FakePool()
    account_keys = iter(("acct_original", "acct_original", "acct_switched"))
    monkeypatch.setattr(
        connection_module,
        "get_account_key",
        lambda: next(account_keys),
    )
    monkeypatch.setattr(connection_module, "_schema_ready_for", "acct_original")
    monkeypatch.setattr(connection_module, "_pool_account", "acct_original")
    monkeypatch.setattr(connection_module, "_pool", pool)
    snapshot_computed = False
    snapshot_returned = False

    with pytest.raises(
        connection_module.OperationalStoreNotReady,
        match="changed during operational store read",
    ):
        with connection_module.connect_ready_read_only():
            snapshot_computed = True
        snapshot_returned = True

    assert snapshot_computed is True
    assert snapshot_returned is False


def test_ready_read_only_transaction_allows_select_and_rejects_update():
    with connection_module.connect() as conn:
        deal = create_deal(
            conn,
            title="Read-only proof",
            side="buyer",
            actor="test",
            dispatch_initial_stage=False,
        )

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with connection_module.connect_ready_read_only() as conn:
            read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
            assert read_only == "on"
            title = conn.execute(
                "SELECT title FROM deals WHERE id=?",
                (deal["id"],),
            ).fetchone()[0]
            assert title == "Read-only proof"
            conn.execute(
                "UPDATE deals SET title=? WHERE id=?",
                ("mutated", deal["id"]),
            )

    with connection_module.connect() as conn:
        title = conn.execute(
            "SELECT title FROM deals WHERE id=?",
            (deal["id"],),
        ).fetchone()[0]
    assert title == "Read-only proof"
