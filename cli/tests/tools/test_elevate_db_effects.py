"""Effect-resolver and hidden-write tests for the elevate_db tool.

``elevate_db`` is a three-action tool over the operational Postgres store:

* ``query``    — SELECT / WITH only (keyword-guarded), pack-entitlement filtered
* ``describe`` — ``information_schema`` + ``COUNT(*)`` reads
* ``call``     — invoke a curated ``elevate_cli.data.*`` write function inside a
  write ``transaction()``

``query`` and ``describe`` are genuine reads only after the repair that routes
them over ``connect_ready_read_only()`` (forced PG ``SET TRANSACTION READ
ONLY``) instead of the bootstrapping ``connect()``. These tests pin the
repaired contract: both read actions resolve to an exact ``read:database`` and
ride the already-ready forced-READ-ONLY connection with no bootstrap and no
fallback; ``call`` and any unrecognized action stay ``unknown`` and fail closed.
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
from tools.elevate_db_tool import (
    _action_describe,
    _action_query,
    _elevate_db_effect_resolver,
    _elevate_db_handler,
)
from tools.registry import registry

READ_DB = frozenset({Effect.parse("read:database")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

READ_ACTIONS = ["query", "describe"]
NON_READ_ACTIONS = ["call", "", "frobnicate"]


def _read_only():
    return ExecutionPolicy.for_mode("turn-elevate-db-read", ExecutionPolicyMode.READ_ONLY)


def _default():
    return ExecutionPolicy.for_mode("turn-elevate-db-default", ExecutionPolicyMode.DEFAULT)


def _unexpected_connect(*_args, **_kwargs):
    raise AssertionError("elevate_db read fell back to a bootstrapping connect()")


class _Cursor:
    def __init__(self, *, fetchall=None, fetchone=None, description=None):
        self._fetchall = fetchall if fetchall is not None else []
        self._fetchone = fetchone
        self.description = description

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return self._fetchone


class RecordingReadOnlyConn:
    """Read-only stand-in that records SQL, refuses non-SELECT, and returns
    canned rows keyed on which read statement is running."""

    def __init__(self):
        self.queries: list[str] = []

    def execute(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        assert text.upper().startswith("SELECT"), (
            f"elevate_db read issued a non-SELECT statement: {text}"
        )
        up = text.upper()
        if up.startswith("SELECT COLUMN_NAME"):
            return _Cursor(
                fetchall=[
                    {
                        "column_name": "id",
                        "data_type": "text",
                        "is_nullable": "NO",
                        "column_default": None,
                    }
                ]
            )
        if up.startswith("SELECT KCU"):
            return _Cursor(fetchall=[])
        if "COUNT(*)" in up:
            return _Cursor(fetchone=(0,))
        # ``query`` action: no rows, no description.
        return _Cursor(fetchall=[], description=None)


# ── declaration / resolver ────────────────────────────────────────────────


def test_elevate_db_registers_a_resolver():
    entry = registry.get_entry("elevate_db")
    assert entry is not None
    assert entry.effect_resolver is _elevate_db_effect_resolver
    meta = registry.get_effect_metadata("elevate_db")
    assert meta["declared"] is True
    assert meta["has_resolver"] is True


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_read_actions_resolve_to_read_database_and_are_allowed(action):
    resolved = registry.resolve_effects("elevate_db", {"action": action})
    assert resolved == READ_DB
    # A pure local DB read is allowed under both READ_ONLY and DEFAULT (no
    # credential effect, unlike discord/composio).
    for policy in (_read_only(), _default()):
        decision = authorize_effects(policy, resolved)
        assert decision.allowed is True
        assert decision.denied_effects == frozenset()
        assert decision.reason == "allowed"


@pytest.mark.parametrize("action", NON_READ_ACTIONS)
def test_non_read_actions_stay_unknown_and_denied(action):
    resolved = registry.resolve_effects("elevate_db", {"action": action})
    assert resolved == UNKNOWN
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_missing_and_none_args_are_unknown():
    assert registry.resolve_effects("elevate_db", {}) == UNKNOWN
    assert registry.resolve_effects("elevate_db", None) == UNKNOWN
    assert _elevate_db_effect_resolver(None) == {EffectKind.UNKNOWN}


def test_resolver_mirrors_handler_action_normalization():
    for raw in ("query", "QUERY", "  Query "):
        assert _elevate_db_effect_resolver({"action": raw}) == {"read:database"}
    for raw in ("describe", " Describe ", "DESCRIBE"):
        assert _elevate_db_effect_resolver({"action": raw}) == {"read:database"}
    for raw in ("call", " CALL ", "bogus"):
        assert _elevate_db_effect_resolver({"action": raw}) == {EffectKind.UNKNOWN}


# ── read routing (read-only connection, no write fallback) ────────────────


def test_query_rides_only_the_ready_read_only_connection(monkeypatch):
    conn = RecordingReadOnlyConn()

    @contextmanager
    def ready_read_only():
        yield conn

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect_ready_read_only", ready_read_only)

    # ``contacts`` is a core table (always allowed) so we reach the DB path.
    result = json.loads(_action_query({"sql": "SELECT id FROM contacts"}))

    assert result["success"] is True
    assert result["rows"] == []
    assert conn.queries, "query never touched the read-only connection"
    assert all(q.upper().startswith("SELECT") for q in conn.queries)


def test_describe_rides_only_the_ready_read_only_connection(monkeypatch):
    conn = RecordingReadOnlyConn()

    @contextmanager
    def ready_read_only():
        yield conn

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect_ready_read_only", ready_read_only)

    result = json.loads(_action_describe({"table": "contacts"}))

    assert result["success"] is True
    assert result["table"] == "contacts"
    assert result["row_count"] == 0
    assert conn.queries, "describe never touched the read-only connection"
    assert all(q.upper().startswith("SELECT") for q in conn.queries)


@pytest.mark.parametrize(
    ("action", "args"),
    [("query", {"sql": "SELECT id FROM contacts"}), ("describe", {"table": "contacts"})],
)
def test_cold_store_returns_structured_error_without_fallback(monkeypatch, action, args):
    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect_ready_read_only", not_ready)

    handler = {"query": _action_query, "describe": _action_describe}[action]
    result = json.loads(handler(args))

    assert result["success"] is False
    assert result["error"] == "operational_store_not_ready"
    assert "starting" in result["message"].lower()


def test_reads_on_cold_home_never_create_elevate_home(monkeypatch, tmp_path):
    """Declaration-rot guard: the declared read paths must stay bootstrap-free.

    Both actions' entitlement gate rides ``is_entitlement_active`` ->
    ``load_access_config`` -> ``read_raw_config`` (no ``ensure_elevate_home``),
    and the read itself rides ``connect_ready_read_only`` (which raises rather
    than bootstrapping a cold store). If anyone reroutes either through the
    bootstrapping config/connection path, the read:database declaration becomes
    a lie — this pins the property at the tool boundary.
    """
    cold_home = tmp_path / "cold-elevate-home"
    assert not cold_home.exists()
    monkeypatch.setenv("ELEVATE_HOME", str(cold_home))

    # 1. Real entitlement check against the cold home: an admin-pack table is
    #    unowned, so query refuses before any DB path and the home stays absent.
    result = json.loads(_action_query({"sql": "SELECT id FROM deals"}))
    assert result["success"] is False
    assert result["error"] == "requires_entitlement"
    assert not cold_home.exists(), "query bootstrapped ELEVATE_HOME in the entitlement gate"

    # 2. Even with packs granted, a cold operational store yields the typed
    #    not-ready refusal for both actions and still must not bootstrap.
    monkeypatch.setattr(access_module, "is_entitlement_active", lambda *a, **k: True)

    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect_ready_read_only", not_ready)

    for args in ({"sql": "SELECT id FROM contacts"}, {"table": "contacts"}):
        handler = _action_query if "sql" in args else _action_describe
        result = json.loads(handler(args))
        assert result["error"] == "operational_store_not_ready"
    assert not cold_home.exists(), "read bootstrapped ELEVATE_HOME on the not-ready path"


# ── live embedded-PG: reads return rows and mutate nothing ────────────────


def test_live_query_reads_contact_without_mutating():
    from elevate_cli.data import upsert_contact

    contact_id = "edb-eff-live-1"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="ElevateDB Effect Lead",
            type="buyer",
            stage="warm",
        )
    with connection_module.connect() as conn:
        contacts_before = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    result = json.loads(
        _elevate_db_handler(
            {
                "action": "query",
                "sql": f"SELECT id, display_name FROM contacts WHERE id = '{contact_id}'",
            }
        )
    )

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["rows"][0]["id"] == contact_id
    assert result["rows"][0]["display_name"] == "ElevateDB Effect Lead"

    with connection_module.connect() as conn:
        contacts_after = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    assert contacts_after == contacts_before


def test_live_describe_reads_schema_without_mutating():
    with connection_module.connect() as conn:
        contacts_before = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    result = json.loads(_elevate_db_handler({"action": "describe", "table": "contacts"}))

    assert result["success"] is True
    assert result["table"] == "contacts"
    assert result["pack"] == "elevate_core"
    column_names = {c["column_name"] for c in result["columns"]}
    assert "id" in column_names

    with connection_module.connect() as conn:
        contacts_after = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    assert contacts_after == contacts_before


def test_live_write_action_stays_unknown_and_reads_only_are_declared():
    # The tool advertises three actions but only the two reads are declared;
    # ``call`` remains undeclared/unknown so a restricted cohort can never reach
    # a write function through elevate_db.
    assert registry.resolve_effects("elevate_db", {"action": "call", "function": "upsert_contact"}) == UNKNOWN
