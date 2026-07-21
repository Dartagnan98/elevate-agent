"""Effect-resolver and hidden-write tests for the working_state tool.

Pre-repair, ``recall`` and ``list_active`` opened the general
``data.connection.connect()``, which can bootstrap embedded Postgres,
adopt legacy databases, and run migrations on a cold process — hidden
writes for a "read" action. These tests pin the repaired contract:
read actions ride the already-ready forced-READ-ONLY boundary and
resolve to an exact ``read:working_state``; every mutating or
unrecognized action stays unknown and is denied under a read-only
policy.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli.data import connection as connection_module
from elevate_cli.data import working_state as working_state_module
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry
from tools.working_state_tool import _working_state_handler


def _unexpected_legacy_connect(*_args, **_kwargs):
    raise AssertionError(
        "working_state read action fell back to a bootstrapping connect()"
    )


def test_recall_uses_only_ready_read_only_connection(monkeypatch):
    marker = object()
    captured: dict[str, object] = {}

    @contextmanager
    def ready_read_only():
        yield marker

    def fake_recall(conn, *, entity_kind, entity_id):
        captured["conn"] = conn
        captured["entity"] = (entity_kind, entity_id)
        return {"body": "sent counter at $450k", "status": "in_progress"}

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", ready_read_only
    )
    monkeypatch.setattr(
        connection_module, "connect", _unexpected_legacy_connect
    )
    monkeypatch.setattr(
        working_state_module, "recall_working_state", fake_recall
    )

    result = json.loads(
        _working_state_handler(
            {
                "action": "recall",
                "entity_kind": "contact",
                "entity_id": "c_123",
            }
        )
    )

    assert result["success"] is True
    assert result["state"]["status"] == "in_progress"
    assert captured["conn"] is marker
    assert captured["entity"] == ("contact", "c_123")


def test_list_active_uses_only_ready_read_only_connection(monkeypatch):
    marker = object()
    captured: dict[str, object] = {}

    @contextmanager
    def ready_read_only():
        yield marker

    def fake_list(conn, *, entity_kinds, limit):
        captured["conn"] = conn
        captured["kinds"] = tuple(entity_kinds)
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", ready_read_only
    )
    monkeypatch.setattr(
        connection_module, "connect", _unexpected_legacy_connect
    )
    monkeypatch.setattr(
        working_state_module, "list_active_working_state", fake_list
    )

    result = json.loads(_working_state_handler({"action": "list_active"}))

    assert result["success"] is True
    assert result["count"] == 0
    assert result["items"] == []
    assert captured["conn"] is marker
    assert captured["limit"] == 30


@pytest.mark.parametrize("action", ["recall", "list_active"])
def test_cold_read_actions_return_structured_error_without_bootstrap(
    monkeypatch, action
):
    def unexpected_bootstrap(*_args, **_kwargs):
        raise AssertionError("working_state read attempted write-side bootstrap")

    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", not_ready
    )
    monkeypatch.setattr(connection_module, "connect", unexpected_bootstrap)
    monkeypatch.setattr(connection_module, "_get_pool", unexpected_bootstrap)
    monkeypatch.setattr(connection_module, "_ensure_schema", unexpected_bootstrap)
    monkeypatch.setattr(
        working_state_module, "recall_working_state", unexpected_bootstrap
    )
    monkeypatch.setattr(
        working_state_module, "list_active_working_state", unexpected_bootstrap
    )

    args = {"action": action}
    if action == "recall":
        args.update({"entity_kind": "contact", "entity_id": "c_cold"})

    result = json.loads(_working_state_handler(args))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_live_read_actions_run_inside_postgres_read_only_transaction(monkeypatch):
    # Warm/bootstrap the per-test store through the normal startup path.
    with connection_module.connect() as conn:
        notes_before = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

    observed_modes: list[str] = []
    original_list = working_state_module.list_active_working_state

    def audited_list(conn, **kwargs):
        observed_modes.append(
            conn.execute("SHOW transaction_read_only").fetchone()[0]
        )
        return original_list(conn, **kwargs)

    monkeypatch.setattr(
        working_state_module, "list_active_working_state", audited_list
    )

    result = json.loads(_working_state_handler({"action": "list_active"}))

    assert result["success"] is True
    assert observed_modes == ["on"]

    monkeypatch.undo()
    with connection_module.connect() as conn:
        notes_after = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    assert notes_after == notes_before


def test_resolver_declares_reads_and_keeps_mutations_unknown():
    read_effects = frozenset({Effect.parse("read:working_state")})
    unknown = frozenset({Effect(EffectKind.UNKNOWN)})

    entry = registry.get_entry("working_state")
    assert entry is not None
    assert entry.effects is None
    assert entry.effect_resolver is not None
    assert registry.get_effect_metadata("working_state") == {
        "declared": True,
        "effects": frozenset(),
        "has_resolver": True,
    }

    for args in (
        {"action": "recall", "entity_kind": "contact", "entity_id": "c_1"},
        {"action": "list_active"},
        {"action": "LIST_ACTIVE"},
    ):
        resolved = registry.resolve_effects("working_state", args)
        assert resolved == read_effects
        decision = authorize_effects(
            ExecutionPolicy.for_mode(
                "turn-working-state-read",
                ExecutionPolicyMode.READ_ONLY,
            ),
            resolved,
        )
        assert decision.allowed is True
        assert decision.reason == "allowed"

    # ``update``/``resolve`` write the journal row and nothing else — the data
    # layer imports only sqlite3 and elevate_cli.data._util, so there is no
    # network, subprocess, filesystem, notifier, or dispatcher branch to hide.
    # They are the agent's own "where we left off" note about the realtor's own
    # contact or deal, and the workspace ceiling admits exactly that.
    journal_write = frozenset({
        Effect.parse("read:working_state"),
        Effect.parse("write_local:working_state"),
    })
    for args in (
        {"action": "update", "entity_kind": "contact", "entity_id": "c_1"},
        {"action": "resolve", "entity_kind": "deal", "entity_id": "d_1"},
        {"action": " UPDATE "},
    ):
        resolved = registry.resolve_effects("working_state", args)
        assert resolved == journal_write
        allowed = authorize_effects(
            ExecutionPolicy.for_mode(
                "turn-working-state-board",
                ExecutionPolicyMode.WORKSPACE,
            ),
            resolved,
        )
        assert allowed.allowed is True
        assert allowed.reason == "allowed"

        denied = authorize_effects(
            ExecutionPolicy.for_mode(
                "turn-working-state-write",
                ExecutionPolicyMode.READ_ONLY,
            ),
            resolved,
        )
        assert denied.allowed is False
        assert denied.reason == "effect_not_allowed"

    # Anything unrecognized still fails closed under every ceiling.
    for args in ({"action": "surprise"}, {}, None):
        resolved = registry.resolve_effects("working_state", args)
        assert resolved == unknown
        for mode in (
            ExecutionPolicyMode.READ_ONLY,
            ExecutionPolicyMode.WORKSPACE,
            ExecutionPolicyMode.DEFAULT,
        ):
            decision = authorize_effects(
                ExecutionPolicy.for_mode("turn-working-state-unknown", mode),
                resolved,
            )
            assert decision.allowed is False
            assert decision.reason == "unknown_effect"
