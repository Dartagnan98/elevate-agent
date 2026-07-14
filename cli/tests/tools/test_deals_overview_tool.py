"""Effect and dispatch tests for the model-facing deals overview tool."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli import access
from elevate_cli.data import connection as connection_module
from elevate_cli.data import deals as deals_module
from tools.approval import (
    Effect,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.deals_overview_tool import _deals_overview_handler
from tools.registry import registry


def _unexpected_legacy_connect(*_args, **_kwargs):
    raise AssertionError("deals_overview fell back to general connect()")


def test_handler_uses_only_ready_read_only_connection(monkeypatch):
    marker = object()
    captured: dict[str, object] = {}

    @contextmanager
    def ready_read_only():
        yield marker

    def overview(conn, **kwargs):
        captured["conn"] = conn
        captured["kwargs"] = kwargs
        return {"totals": {"activeAfterFilter": 0}, "deals": []}

    monkeypatch.setattr(access, "is_entitlement_active", lambda *_args: True)
    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        ready_read_only,
    )
    monkeypatch.setattr(
        connection_module,
        "connect",
        _unexpected_legacy_connect,
    )
    monkeypatch.setattr(deals_module, "deals_overview", overview)

    result = json.loads(_deals_overview_handler({}))

    assert result == {
        "success": True,
        "overview": {"totals": {"activeAfterFilter": 0}, "deals": []},
    }
    assert captured == {
        "conn": marker,
        "kwargs": {
            "status": "active",
            "side": None,
            "exclude_mock": True,
            "near_close_days": 30,
            "near_subject_days": 21,
            "stale_days": 14,
        },
    }


def test_cold_handler_returns_structured_error_without_fallback(monkeypatch):
    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(access, "is_entitlement_active", lambda *_args: True)
    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        not_ready,
    )
    monkeypatch.setattr(
        connection_module,
        "connect",
        _unexpected_legacy_connect,
    )
    monkeypatch.setattr(
        deals_module,
        "deals_overview",
        lambda *_args, **_kwargs: pytest.fail("cold handler queried deals"),
    )

    result = json.loads(_deals_overview_handler({}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_mid_read_account_switch_discards_computed_snapshot(monkeypatch):
    marker = object()
    overview_calls: list[object] = []

    @contextmanager
    def account_switches_after_read():
        yield marker
        raise connection_module.OperationalStoreNotReady(
            "active account changed during operational store read"
        )

    def overview(conn, **_kwargs):
        overview_calls.append(conn)
        return {"deals": [{"id": "old-account-row"}]}

    monkeypatch.setattr(access, "is_entitlement_active", lambda *_args: True)
    monkeypatch.setattr(
        connection_module,
        "connect_ready_read_only",
        account_switches_after_read,
    )
    monkeypatch.setattr(
        connection_module,
        "connect",
        _unexpected_legacy_connect,
    )
    monkeypatch.setattr(deals_module, "deals_overview", overview)

    result = json.loads(_deals_overview_handler({}))

    assert overview_calls == [marker]
    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "overview" not in result
    assert "old-account-row" not in json.dumps(result)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"status": "all"},
        {"side": "buyer", "exclude_mock": False},
        {
            "status": "closed",
            "near_close_days": 90,
            "near_subject_days": 45,
            "stale_days": 30,
        },
    ],
)
def test_registration_declares_exact_read_deals_effect(args):
    expected = frozenset({Effect.parse("read:deals")})
    entry = registry.get_entry("deals_overview")

    assert entry is not None
    assert entry.effects == expected
    assert entry.effect_resolver is None
    assert registry.get_effect_metadata("deals_overview") == {
        "declared": True,
        "effects": expected,
        "has_resolver": False,
    }

    resolved = registry.resolve_effects("deals_overview", args)
    decision = authorize_effects(
        ExecutionPolicy.for_mode(
            "turn-deals-overview",
            ExecutionPolicyMode.READ_ONLY,
        ),
        resolved,
    )

    assert resolved == expected
    assert decision.allowed is True
    assert decision.requested_effects == expected
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"
