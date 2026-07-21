"""Effect-resolver and hidden-write tests for the lead_status tool.

``lead_status`` is a lead-labeling (write) surface: ``set``/``heat``/
``follow_up``/``classify`` all mutate the contact row (and ``set`` can push to
an external CRM). Only ``show`` is a genuine pure read, and only after the
repair that routes it over ``connect_ready_read_only()`` instead of the general
bootstrapping ``connect()``.

These tests pin the contract in both directions:

* ``show`` resolves to an exact ``read:leads`` and runs over the already-ready
  forced-READ-ONLY connection with no bootstrap.
* ``heat``/``follow_up``/``classify`` are purely local label writes and are
  ALLOWED under the workspace ceiling.
* ``set`` is allowed only while the operator's CRM mirror is off. With the
  mirror on it declares ``write_external:crm`` and the whole call is REFUSED
  under the workspace ceiling — a status change that leaves the machine is a
  write to someone else's system, which can trip that system's own client
  automations.
* any unrecognized action stays unknown and denied under every ceiling.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli import access as access_module
from elevate_cli.data import connection as connection_module
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.lead_status_tool import (
    _crm_mirror_reachable_for_set as _real_crm_mirror_probe,
)
from tools.lead_status_tool import _lead_status_effect_resolver, _lead_status_handler
from tools.registry import registry

READ_LEADS = frozenset({Effect.parse("read:leads")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})
LOCAL_LABEL_WRITE = frozenset({
    Effect.parse("read:leads"), Effect.parse("write_local:leads"),
})
MIRRORED_WRITE = LOCAL_LABEL_WRITE | {Effect.parse("write_external:crm")}

READ_ACTIONS = ["show"]
LOCAL_WRITE_ACTIONS = ["heat", "follow_up", "classify"]
UNKNOWN_ACTIONS = ["", "frobnicate"]


@pytest.fixture(autouse=True)
def _crm_mirror_off(monkeypatch):
    """Default the operator's CRM mirror OFF — the shipped default.

    Tests that care about the mirror override this explicitly.
    """
    monkeypatch.setattr(
        "tools.lead_status_tool._crm_mirror_reachable_for_set", lambda: False
    )


def _read_only():
    return ExecutionPolicy.for_mode(
        "turn-lead-status-read", ExecutionPolicyMode.READ_ONLY
    )


def _workspace():
    return ExecutionPolicy.for_mode(
        "turn-lead-status-workspace", ExecutionPolicyMode.WORKSPACE
    )


@pytest.fixture
def _entitled(monkeypatch):
    """Grant the real_estate_sales pack so the handler reaches the DB path."""
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
            f"lead_status show issued a non-SELECT statement: {text}"
        )
        row = self._row
        return _OneRowCursor(row)


class _OneRowCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row is not None else []


def _unexpected_connect(*_args, **_kwargs):
    raise AssertionError("lead_status show fell back to a bootstrapping connect()")


# ── declaration / resolver ───────────────────────────────────────────────


def test_lead_status_registers_a_resolver():
    entry = registry.get_entry("lead_status")
    assert entry is not None
    assert entry.effect_resolver is not None
    meta = registry.get_effect_metadata("lead_status")
    assert meta["declared"] is True
    assert meta["has_resolver"] is True


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_show_resolves_read_leads_and_is_allowed(action):
    resolved = registry.resolve_effects("lead_status", {"action": action, "contact_id": "c"})
    assert resolved == READ_LEADS
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize("action", LOCAL_WRITE_ACTIONS)
def test_label_writes_declare_a_scoped_local_lead_write(action):
    resolved = registry.resolve_effects("lead_status", {"action": action, "contact_id": "c"})
    assert resolved == LOCAL_LABEL_WRITE
    decision = authorize_effects(_workspace(), resolved)
    assert decision.allowed is True
    assert decision.reason == "allowed"


@pytest.mark.parametrize("action", LOCAL_WRITE_ACTIONS)
def test_label_writes_are_still_denied_under_read_only(action):
    resolved = registry.resolve_effects("lead_status", {"action": action, "contact_id": "c"})
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "effect_not_allowed"


def test_set_is_local_and_allowed_while_the_crm_mirror_is_off():
    resolved = registry.resolve_effects("lead_status", {"action": "set", "contact_id": "c"})
    assert resolved == LOCAL_LABEL_WRITE
    assert authorize_effects(_workspace(), resolved).allowed is True


def test_set_declares_the_external_write_and_is_refused_when_the_mirror_is_on(
    monkeypatch,
):
    """The structural test: local write + outward reach must NOT slip through.

    Nothing about the tool's NAME changes here — only the fact that this box
    would physically push to Lofty/FUB/Sierra. The workspace ceiling refuses
    the whole call because one declared effect is outside it.
    """
    monkeypatch.setattr(
        "tools.lead_status_tool._crm_mirror_reachable_for_set", lambda: True
    )
    resolved = registry.resolve_effects("lead_status", {"action": "set", "contact_id": "c"})
    assert resolved == MIRRORED_WRITE
    decision = authorize_effects(_workspace(), resolved)
    assert decision.allowed is False
    assert decision.reason == "effect_not_allowed"
    assert decision.denied_effects == frozenset({Effect.parse("write_external:crm")})


@pytest.mark.parametrize("status", ["closed_seller", "closed_buyer"])
def test_closing_a_lead_declares_the_deal_board_write_it_causes(status):
    """``set`` to a closing status is not just a relabel.

    ``set_pipeline_status`` routes both closing values through
    ``close_to_admin`` -> ``promote_profile_to_admin_deal`` -> ``create_deal``.
    Both effects sit inside the workspace ceiling so nothing is denied, but a
    receipt naming only ``write_local:leads`` for a call that created a deal
    would be a false record — and the receipt is the evidence.
    """
    resolved = registry.resolve_effects(
        "lead_status", {"action": "set", "contact_id": "c", "status": status}
    )
    assert resolved == LOCAL_LABEL_WRITE | {Effect.parse("write_local:deals")}
    assert authorize_effects(_workspace(), resolved).allowed is True


@pytest.mark.parametrize("status", ["new_lead", "follow_up", "ghosting", "dead"])
def test_non_closing_statuses_do_not_claim_the_deal_board(status):
    resolved = registry.resolve_effects(
        "lead_status", {"action": "set", "contact_id": "c", "status": status}
    )
    assert resolved == LOCAL_LABEL_WRITE


def test_a_cold_store_does_not_read_as_mirror_on(monkeypatch):
    """A not-ready store must not masquerade as an external-write refusal.

    Declaring ``write_external:crm`` here would refuse the call with a
    policy-shaped error and hide the handler's real, actionable
    ``operational_store_not_ready`` message. The handler's own onboarding read
    already degrades to config-only in exactly this case, so the resolver
    mirrors that rather than inventing a different answer.
    """
    from contextlib import contextmanager

    @contextmanager
    def _not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", _not_ready
    )
    monkeypatch.setattr(
        "tools.lead_status_crm._load_config_safely", lambda: {}
    )
    assert _real_crm_mirror_probe() is False

    monkeypatch.setattr(
        "tools.lead_status_crm._load_config_safely",
        lambda: {"crm": {"push_status": True}},
    )
    assert _real_crm_mirror_probe() is True


def test_resolver_fails_closed_toward_declaring_the_external_write(monkeypatch):
    """An undeterminable mirror state declares the external write, not silence.

    Bound to the REAL probe captured at import, so the autouse mirror-off
    fixture cannot mask the fail-closed branch.
    """

    def _boom(*_a, **_k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(
        "elevate_cli.data.connection.connect_ready_read_only", _boom
    )
    assert _real_crm_mirror_probe() is True


@pytest.mark.parametrize("action", UNKNOWN_ACTIONS)
def test_unrecognized_actions_stay_unknown_and_denied_everywhere(action):
    resolved = registry.resolve_effects("lead_status", {"action": action, "contact_id": "c"})
    assert resolved == UNKNOWN
    for mode in (
        ExecutionPolicyMode.READ_ONLY,
        ExecutionPolicyMode.PLAN,
        ExecutionPolicyMode.DRAFT_ONLY,
        ExecutionPolicyMode.WORKSPACE,
        ExecutionPolicyMode.DEFAULT,
    ):
        decision = authorize_effects(
            ExecutionPolicy.for_mode("turn-unknown", mode), resolved
        )
        assert decision.allowed is False
        assert decision.reason == "unknown_effect"


def test_missing_and_none_args_are_unknown():
    assert registry.resolve_effects("lead_status", {}) == UNKNOWN
    assert registry.resolve_effects("lead_status", None) == UNKNOWN
    assert _lead_status_effect_resolver(None) == {EffectKind.UNKNOWN}


def test_resolver_mirrors_handler_action_normalization():
    for raw in ("show", "SHOW", "  Show "):
        assert _lead_status_effect_resolver({"action": raw}) == {"read:leads"}
    for raw in ("Set", "  HEAT ", "classify", "FOLLOW_UP "):
        assert _lead_status_effect_resolver({"action": raw}) == {
            "read:leads", "write_local:leads",
        }
    for raw in ("", "frobnicate", "  "):
        assert _lead_status_effect_resolver({"action": raw}) == {EffectKind.UNKNOWN}


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

    # row=None -> "not found", but the SELECT-only routing is what we pin here:
    # show must never open the general bootstrapping connect().
    result = json.loads(_lead_status_handler({"action": "show", "contact_id": "missing"}))

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

    result = json.loads(_lead_status_handler({"action": "show", "contact_id": "c"}))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "startup" in result["message"].lower()


def test_show_on_cold_home_never_creates_elevate_home(monkeypatch, tmp_path):
    """Declaration-rot guard: the declared-read path must stay bootstrap-free.

    ``show``'s entitlement gate rides ``load_access_config`` ->
    ``read_raw_config``, which (unlike ``load_config`` ->
    ``ensure_elevate_home``) must NOT mkdir the profile tree or seed SOUL.md.
    If anyone later reroutes the gate through the bootstrapping config loader,
    the read:leads declaration silently becomes a lie — this test pins the
    bootstrap-free property at the tool boundary.
    """
    cold_home = tmp_path / "cold-elevate-home"
    assert not cold_home.exists()
    monkeypatch.setenv("ELEVATE_HOME", str(cold_home))

    # 1. Real entitlement check against the cold home: no config file means no
    #    entitlement, so the handler refuses before any DB path — and the home
    #    must still not exist afterward.
    result = json.loads(_lead_status_handler({"action": "show", "contact_id": "c"}))
    assert result["success"] is False
    assert result["error"] == "requires_entitlement"
    assert not cold_home.exists(), (
        "lead_status show bootstrapped ELEVATE_HOME during the entitlement check"
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

    result = json.loads(_lead_status_handler({"action": "show", "contact_id": "c"}))
    assert result["error"] == "operational_store_not_ready"
    assert not cold_home.exists(), (
        "lead_status show bootstrapped ELEVATE_HOME on the not-ready path"
    )


# ── live embedded-PG: show reads without mutating ─────────────────────────


def test_live_show_reads_contact_without_mutating(_entitled):
    # No connect() freeze / monkeypatch.undo() here: the shared function-scoped
    # monkeypatch also carries the autouse ELEVATE_HOME/account fixtures, so an
    # undo() would revert the sandbox out from under the store. The read-only
    # routing proof (show never opens the bootstrapping connect()) lives in
    # ``test_show_rides_only_the_ready_read_only_connection``; here we prove the
    # live read returns the row and mutates nothing.
    from elevate_cli.data import upsert_contact

    contact_id = "lead-eff-live-1"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="Effect Test Lead",
            type="buyer",
            stage="warm",
        )
    with connection_module.connect() as conn:
        contacts_before = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        status_before = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()[0]

    result = json.loads(_lead_status_handler({"action": "show", "contact_id": contact_id}))

    assert result["success"] is True
    assert result["lead"]["id"] == contact_id
    assert result["lead"]["name"] == "Effect Test Lead"

    with connection_module.connect() as conn:
        contacts_after = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        status_after = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()[0]

    assert contacts_after == contacts_before
    assert status_after == status_before
