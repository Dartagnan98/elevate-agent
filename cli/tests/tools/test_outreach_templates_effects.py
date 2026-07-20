"""Effect-resolver and hidden-write tests for the outreach_templates tool.

``outreach_templates`` is mostly a template-management (write/learn) surface.
Only its ``list``/``grouped``/``stats`` actions are genuine pure reads, and
only after the repair that routes them over ``connect_ready_read_only()``: the
pre-repair handler called ``outreach_db.list_templates()`` /
``list_templates_grouped()`` / ``stats()``, each of which opened
``outreach_db.connect()`` and ran ``_maybe_seed_templates()`` — a cold-connect
template seed + seed-metadata write.

These tests pin the repaired contract: the three reads resolve to an exact
``read:outreach`` and run over ONE already-ready forced-READ-ONLY connection
with zero seeding; every mutating action (create/update/delete/pick/
record_use/record_outcome) and any unrecognized action stays unknown and denied
under a read-only policy.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from elevate_cli import outreach_db
from elevate_cli.data import connection as connection_module
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.outreach_templates_tool import (
    _outreach_templates_effect_resolver,
    outreach_templates,
)
from tools.registry import registry

READ_OUTREACH = frozenset({Effect.parse("read:outreach")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

READ_ACTIONS = ["list", "list_templates", "templates", "grouped", "list_grouped", "stats"]
NON_READ_ACTIONS = [
    "create", "update", "delete",
    "pick", "record_use", "use", "record", "record_outcome", "outcome",
    "", "frobnicate",
]


def _read_only():
    return ExecutionPolicy.for_mode(
        "turn-outreach-templates-read", ExecutionPolicyMode.READ_ONLY
    )


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else {"n": 0}

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
            f"outreach_templates issued a non-SELECT statement: {text}"
        )
        for prefix, rows in self._rows_by_prefix.items():
            if text.startswith(prefix):
                return FakeCursor(rows)
        return FakeCursor([])


def _unexpected_seed(*_args, **_kwargs):
    raise AssertionError("outreach_templates read triggered template seeding")


def _unexpected_connect(*_args, **_kwargs):
    raise AssertionError("outreach_templates read fell back to a bootstrapping connect()")


@pytest.fixture
def _no_hidden_write_paths(monkeypatch):
    monkeypatch.setattr(outreach_db, "connect", _unexpected_connect)
    monkeypatch.setattr(connection_module, "connect", _unexpected_connect)
    monkeypatch.setattr(outreach_db, "_maybe_seed_templates", _unexpected_seed)
    monkeypatch.setattr(outreach_db, "_insert_template", _unexpected_seed)
    monkeypatch.setattr(outreach_db, "_write_meta", _unexpected_seed)
    yield


# ── declaration / resolver ───────────────────────────────────────────────


def test_outreach_templates_registers_a_resolver():
    entry = registry.get_entry("outreach_templates")
    assert entry is not None
    assert entry.effect_resolver is not None
    meta = registry.get_effect_metadata("outreach_templates")
    assert meta["declared"] is True
    assert meta["has_resolver"] is True


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_read_actions_resolve_read_outreach_and_are_allowed(action):
    resolved = registry.resolve_effects("outreach_templates", {"action": action})
    assert resolved == READ_OUTREACH
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize("action", NON_READ_ACTIONS)
def test_write_actions_stay_unknown_and_denied(action):
    resolved = registry.resolve_effects("outreach_templates", {"action": action})
    assert resolved == UNKNOWN
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_missing_and_none_args_are_unknown():
    assert registry.resolve_effects("outreach_templates", {}) == UNKNOWN
    assert registry.resolve_effects("outreach_templates", None) == UNKNOWN
    assert _outreach_templates_effect_resolver(None) == {EffectKind.UNKNOWN}


def test_resolver_mirrors_handler_action_normalization():
    # Handler normalizes with (action or "").strip().lower(); resolver must
    # classify the same normalized value.
    for raw in ("list", "LIST", "  Grouped ", "STATS", "Templates"):
        assert _outreach_templates_effect_resolver({"action": raw}) == {"read:outreach"}
    for raw in ("Create", "  DELETE ", "pick", "record_use"):
        assert _outreach_templates_effect_resolver({"action": raw}) == {EffectKind.UNKNOWN}


# ── read routing (no seeding, SELECT-only) ────────────────────────────────


@pytest.mark.parametrize(
    "action,key",
    [("list", "templates"), ("grouped", "lanes"), ("stats", "stats")],
)
def test_reads_ride_only_the_ready_read_only_connection(
    monkeypatch, _no_hidden_write_paths, action, key
):
    conn = RecordingReadOnlyConn()

    @contextmanager
    def ready_read_only():
        yield conn

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", ready_read_only
    )

    result = json.loads(outreach_templates(action=action))

    assert result["ok"] is True
    assert key in result
    assert conn.queries, "read never queried the read-only connection"
    assert all(q.upper().startswith("SELECT") for q in conn.queries)


def test_cold_store_returns_structured_error_without_fallback(
    monkeypatch, _no_hidden_write_paths
):
    @contextmanager
    def not_ready():
        raise connection_module.OperationalStoreNotReady("cold")
        yield  # pragma: no cover

    monkeypatch.setattr(
        connection_module, "connect_ready_read_only", not_ready
    )

    result = json.loads(outreach_templates(action="list"))

    assert "ok" not in result
    assert "starting" in result["error"].lower()


# ── live embedded-PG: read path never seeds or mutates ────────────────────


def test_live_reads_never_seed_or_mutate_templates(monkeypatch):
    # Warm/bootstrap the per-test store through the normal startup path so the
    # seed metadata already exists, then prove the three reads change no rows.
    # We deliberately do NOT freeze connect()/undo() around the handler: the
    # function-scoped monkeypatch is shared with the autouse ELEVATE_HOME/account
    # fixtures, so undo() would revert the sandbox. The "reads never seed / never
    # open the bootstrapping connect()" proof lives in
    # ``test_reads_ride_only_the_ready_read_only_connection`` (which freezes seed
    # + connect via the _no_hidden_write_paths fixture over a fake read-only
    # connection). Here we exercise the real store.
    with connection_module.connect() as conn:
        templates_before = conn.execute(
            "SELECT COUNT(*) FROM templates"
        ).fetchone()[0]
        attempts_before = conn.execute(
            "SELECT COUNT(*) FROM draft_attempts"
        ).fetchone()[0]

    # Seeding is already done by warmup; make a fresh seed a hard failure so a
    # re-seed during the reads is caught even though connect() stays live.
    monkeypatch.setattr(outreach_db, "_maybe_seed_templates", _unexpected_seed)
    monkeypatch.setattr(outreach_db, "_insert_template", _unexpected_seed)
    monkeypatch.setattr(outreach_db, "_write_meta", _unexpected_seed)

    list_result = json.loads(outreach_templates(action="list"))
    grouped_result = json.loads(outreach_templates(action="grouped"))
    stats_result = json.loads(outreach_templates(action="stats"))

    assert list_result["ok"] is True
    assert isinstance(list_result["templates"], list)
    assert grouped_result["ok"] is True
    assert isinstance(grouped_result["lanes"], dict)
    assert stats_result["ok"] is True
    assert stats_result["stats"]["templates"] == templates_before

    with connection_module.connect() as conn:
        templates_after = conn.execute(
            "SELECT COUNT(*) FROM templates"
        ).fetchone()[0]
        attempts_after = conn.execute(
            "SELECT COUNT(*) FROM draft_attempts"
        ).fetchone()[0]

    assert templates_after == templates_before
    assert attempts_after == attempts_before
