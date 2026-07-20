"""Effect and hidden-write tests for the model-facing leads overview tool.

The pre-repair handler opened ``outreach_db.connect()`` (which seeds
templates and writes seed metadata on a cold store) and the general
``data.connection.connect()`` (which can bootstrap/migrate/adopt). These
tests pin the repaired contract: one already-ready forced-READ-ONLY
connection, zero seeding, zero bootstrap, and an exact ``read:leads``
declaration.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli import outreach_db
from elevate_cli.data import connection as connection_module
from tools.approval import (
    Effect,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.leads_overview_tool import _leads_overview_handler
from tools.registry import registry


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class RecordingReadOnlyConn:
    """Read-only stand-in that records SQL and refuses non-SELECT verbs."""

    def __init__(self, rows_by_prefix=None):
        self.queries: list[str] = []
        self._rows_by_prefix = rows_by_prefix or {}

    def execute(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        assert text.upper().startswith("SELECT"), (
            f"leads_overview issued a non-SELECT statement: {text}"
        )
        for prefix, rows in self._rows_by_prefix.items():
            if text.startswith(prefix):
                return FakeCursor(rows)
        return FakeCursor([])


def _unexpected_legacy_connect(*_args, **_kwargs):
    raise AssertionError("leads_overview fell back to a bootstrapping connect()")


def _unexpected_seed(*_args, **_kwargs):
    raise AssertionError("leads_overview triggered outreach template seeding")


@pytest.fixture
def _no_hidden_write_paths(monkeypatch):
    monkeypatch.setattr(
        connection_module, "connect", _unexpected_legacy_connect
    )
    monkeypatch.setattr(outreach_db, "connect", _unexpected_legacy_connect)
    monkeypatch.setattr(
        outreach_db, "_maybe_seed_templates", _unexpected_seed
    )
    monkeypatch.setattr(outreach_db, "_insert_template", _unexpected_seed)
    monkeypatch.setattr(outreach_db, "_write_meta", _unexpected_seed)
    yield


def test_handler_uses_only_ready_read_only_connection(
    monkeypatch, _no_hidden_write_paths
):
    conn = RecordingReadOnlyConn()

    @contextmanager
    def ready_read_only():
        yield conn

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", ready_read_only
    )

    result = json.loads(_leads_overview_handler({}))

    assert result["success"] is True
    overview = result["overview"]
    assert overview["pendingApproval"] == 0
    assert overview["byStatus"] == {}
    assert overview["pendingByChannel"] == {}
    assert overview["pendingBySource"] == {}
    assert overview["recentSends"] == []
    assert overview["recentlyWorked"] == []
    # Every section rode the single injected read-only connection.
    assert conn.queries, "handler never queried the read-only connection"
    assert all(q.upper().startswith("SELECT") for q in conn.queries)


def test_cold_handler_returns_structured_error_without_fallback(
    monkeypatch, _no_hidden_write_paths
):
    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", not_ready
    )
    monkeypatch.setattr(
        outreach_db,
        "send_queue_stats",
        lambda *_a, **_k: pytest.fail("cold handler queried the send queue"),
    )

    result = json.loads(_leads_overview_handler({}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_mid_read_account_switch_discards_computed_snapshot(
    monkeypatch, _no_hidden_write_paths
):
    conn = RecordingReadOnlyConn(
        rows_by_prefix={
            "SELECT status, COUNT(*)": [{"status": "sent", "n": 7}],
        }
    )

    @contextmanager
    def account_switches_after_read():
        yield conn
        raise connection_module.OperationalStoreNotReady(
            "active account changed during operational store read"
        )

    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        account_switches_after_read,
    )

    result = json.loads(_leads_overview_handler({}))

    assert conn.queries, "snapshot was never computed before the switch"
    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "overview" not in result
    assert "sent" not in json.dumps(result)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"recent_limit": 10},
        {"recent_limit": 25, "worked_since_hours": 48},
    ],
)
def test_registration_declares_exact_read_leads_effect(args):
    expected = frozenset({Effect.parse("read:leads")})
    entry = registry.get_entry("leads_overview")

    assert entry is not None
    assert entry.effects == expected
    assert entry.effect_resolver is None
    assert registry.get_effect_metadata("leads_overview") == {
        "declared": True,
        "effects": expected,
        "has_resolver": False,
    }

    resolved = registry.resolve_effects("leads_overview", args)
    decision = authorize_effects(
        ExecutionPolicy.for_mode(
            "turn-leads-overview",
            ExecutionPolicyMode.READ_ONLY,
        ),
        resolved,
    )

    assert resolved == expected
    assert decision.allowed is True
    assert decision.requested_effects == expected
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


def test_live_overview_reads_ready_store_without_seeding_templates(monkeypatch):
    # Warm/bootstrap the per-test store through the normal startup path,
    # then freeze the template state the pre-repair handler used to mutate.
    with connection_module.connect() as conn:
        templates_before = conn.execute(
            "SELECT COUNT(*) FROM templates"
        ).fetchone()[0]
        sends_before = conn.execute(
            "SELECT COUNT(*) FROM send_queue"
        ).fetchone()[0]

    # After warmup, any fallback to a bootstrapping/seeding connection is
    # a contract violation.
    monkeypatch.setattr(
        connection_module, "connect", _unexpected_legacy_connect
    )
    monkeypatch.setattr(outreach_db, "connect", _unexpected_legacy_connect)
    monkeypatch.setattr(
        outreach_db, "_maybe_seed_templates", _unexpected_seed
    )

    result = json.loads(_leads_overview_handler({}))

    assert result["success"] is True
    overview = result["overview"]
    assert overview["pendingApproval"] == 0
    assert overview["recentSends"] == []

    monkeypatch.undo()
    with connection_module.connect() as conn:
        templates_after = conn.execute(
            "SELECT COUNT(*) FROM templates"
        ).fetchone()[0]
        sends_after = conn.execute(
            "SELECT COUNT(*) FROM send_queue"
        ).fetchone()[0]

    assert templates_after == templates_before
    assert sends_after == sends_before
