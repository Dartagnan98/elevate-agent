"""Effect-resolver and hidden-write tests for the admin_deal tool.

``admin_deal`` is a deal-board write surface: ``set_checklist``/``set_fields``/
``attach``/``complete_run``/``advance``/``move`` all mutate deal state. Only
``show`` is a genuine pure read (deal row + checklist + attachments + computed
gate, all SELECTs), and only after the repair that routes it over
``connect_ready_read_only()`` instead of the general bootstrapping ``connect()``.

These tests pin the repaired contract: ``show`` resolves to an exact
``read:deals`` and runs over the already-ready forced-READ-ONLY connection with
no bootstrap; every write action and any unrecognized action stays unknown and
denied under a read-only policy.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli import access as access_module
from elevate_cli.data import connection as connection_module
from tools.admin_deal_tool import _admin_deal_effect_resolver, _admin_deal_handler
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry

READ_DEALS = frozenset({Effect.parse("read:deals")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

READ_ACTIONS = ["show"]
NON_READ_ACTIONS = [
    "set_checklist", "set_fields", "attach", "complete_run", "advance", "move",
    "", "frobnicate",
]


def _read_only():
    return ExecutionPolicy.for_mode(
        "turn-admin-deal-read", ExecutionPolicyMode.READ_ONLY
    )


@pytest.fixture
def _entitled(monkeypatch):
    """Grant the real_estate_admin pack so the handler reaches the DB path."""
    monkeypatch.setattr(access_module, "is_entitlement_active", lambda *a, **k: True)
    yield


class RecordingReadOnlyConn:
    """Read-only stand-in that records SQL and refuses non-SELECT verbs."""

    def __init__(self, row=None):
        self.queries: list[str] = []
        self._row = row

    def execute(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        assert text.upper().startswith("SELECT"), (
            f"admin_deal show issued a non-SELECT statement: {text}"
        )
        return _OneRowCursor(self._row)


class _OneRowCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row is not None else []


def _unexpected_connect(*_args, **_kwargs):
    raise AssertionError("admin_deal show fell back to a bootstrapping connect()")


# ── declaration / resolver ───────────────────────────────────────────────


def test_admin_deal_registers_a_resolver():
    entry = registry.get_entry("admin_deal")
    assert entry is not None
    assert entry.effect_resolver is not None
    meta = registry.get_effect_metadata("admin_deal")
    assert meta["declared"] is True
    assert meta["has_resolver"] is True


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_show_resolves_read_deals_and_is_allowed(action):
    resolved = registry.resolve_effects("admin_deal", {"action": action, "deal_id": "d"})
    assert resolved == READ_DEALS
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize("action", NON_READ_ACTIONS)
def test_write_actions_stay_unknown_and_denied(action):
    resolved = registry.resolve_effects("admin_deal", {"action": action, "deal_id": "d"})
    assert resolved == UNKNOWN
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_missing_and_none_args_are_unknown():
    assert registry.resolve_effects("admin_deal", {}) == UNKNOWN
    assert registry.resolve_effects("admin_deal", None) == UNKNOWN
    assert _admin_deal_effect_resolver(None) == {EffectKind.UNKNOWN}


def test_resolver_mirrors_handler_action_normalization():
    for raw in ("show", "SHOW", "  Show "):
        assert _admin_deal_effect_resolver({"action": raw}) == {"read:deals"}
    for raw in ("Set_checklist", "  ADVANCE ", "move", "complete_run"):
        assert _admin_deal_effect_resolver({"action": raw}) == {EffectKind.UNKNOWN}


# ── read routing (read-only connection, no write fallback) ────────────────


def test_show_rides_only_the_ready_read_only_connection(monkeypatch, _entitled):
    conn = RecordingReadOnlyConn(row=None)

    @contextmanager
    def ready_read_only():
        yield conn

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", ready_read_only
    )

    # row=None -> deal not found (LookupError -> tool_error). What we pin here is
    # that show routes through the read-only SELECT path and never opens the
    # general bootstrapping connect().
    result = json.loads(_admin_deal_handler({"action": "show", "deal_id": "missing"}))

    assert "not found" in json.dumps(result).lower()
    assert conn.queries, "show never queried the read-only connection"
    assert all(q.upper().startswith("SELECT") for q in conn.queries)


def test_cold_store_returns_structured_error_without_fallback(monkeypatch, _entitled):
    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", not_ready
    )

    result = json.loads(_admin_deal_handler({"action": "show", "deal_id": "d"}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_show_on_cold_home_never_creates_elevate_home(monkeypatch, tmp_path):
    """Declaration-rot guard: the declared-read path must stay bootstrap-free.

    ``show``'s entitlement gate rides ``load_access_config`` ->
    ``read_raw_config``, which (unlike ``load_config`` ->
    ``ensure_elevate_home``) must NOT mkdir the profile tree or seed SOUL.md.
    If anyone later reroutes the gate through the bootstrapping config loader,
    the read:deals declaration silently becomes a lie — this test pins the
    bootstrap-free property at the tool boundary.
    """
    cold_home = tmp_path / "cold-elevate-home"
    assert not cold_home.exists()
    monkeypatch.setenv("ELEVATE_HOME", str(cold_home))

    # 1. Real entitlement check against the cold home: no config file means no
    #    entitlement, so the handler refuses before any DB path — and the home
    #    must still not exist afterward.
    result = json.loads(_admin_deal_handler({"action": "show", "deal_id": "d"}))
    assert result["success"] is False
    assert result["error"] == "requires_entitlement"
    assert not cold_home.exists(), (
        "admin_deal show bootstrapped ELEVATE_HOME during the entitlement check"
    )

    # 2. Even with the pack granted, a cold operational store yields the typed
    #    not-ready refusal and still must not bootstrap the home.
    monkeypatch.setattr(access_module, "is_entitlement_active", lambda *a, **k: True)

    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect_ready_read_only", not_ready)

    result = json.loads(_admin_deal_handler({"action": "show", "deal_id": "d"}))
    assert result["error"] == "operational_store_not_ready"
    assert not cold_home.exists(), (
        "admin_deal show bootstrapped ELEVATE_HOME on the not-ready path"
    )


# ── live embedded-PG: show reads without mutating ─────────────────────────


def test_live_show_reads_deal_without_mutating(_entitled):
    # No connect() freeze / monkeypatch.undo(): the shared function-scoped
    # monkeypatch carries the autouse ELEVATE_HOME/account fixtures. The
    # read-only routing proof lives in
    # ``test_show_rides_only_the_ready_read_only_connection``; here we prove the
    # live read returns the deal and mutates nothing.
    from elevate_cli.data import create_deal

    with connection_module.connect() as conn:
        created = create_deal(
            conn,
            title="Effect Test Deal",
            side="listing",
            actor="test:admin_deal_effects",
            province="BC",
            dispatch_initial_stage=False,
        )
    deal_id = created["id"]

    with connection_module.connect() as conn:
        deals_before = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        stage_before = conn.execute(
            "SELECT current_stage FROM deals WHERE id=?", (deal_id,)
        ).fetchone()[0]

    result = json.loads(_admin_deal_handler({"action": "show", "deal_id": deal_id}))

    assert result["success"] is True
    assert result["deal"]["id"] == deal_id
    assert result["deal"]["title"] == "Effect Test Deal"
    assert "gate" in result

    with connection_module.connect() as conn:
        deals_after = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        stage_after = conn.execute(
            "SELECT current_stage FROM deals WHERE id=?", (deal_id,)
        ).fetchone()[0]

    assert deals_after == deals_before
    assert stage_after == stage_before
