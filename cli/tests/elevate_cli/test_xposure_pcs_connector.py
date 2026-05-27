"""Unit tests for the xposure-pcs connector wiring and identity mapping."""

from __future__ import annotations

from typing import Any

from elevate_cli import xposure_pcs_connector as pcs


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: Any = ()) -> FakeCursor:
        params_tuple = tuple(params) if params else ()
        self.calls.append((sql, params_tuple))
        if "FROM identities" in sql and params_tuple == ("xposure_pcs_id", "native-1"):
            # Simulates the important case: the walker resolved this PCS row
            # into an existing CRM contact, so source_key is NOT xposure-pcs:*.
            return FakeCursor([{"contact_id": "crm-contact-1"}])
        if "FROM identities" in sql:
            return FakeCursor([])
        if "FROM contacts" in sql:
            return FakeCursor([
                {"id": "legacy-xposure-contact-2", "source_key": "xposure-pcs:native-2"},
            ])
        return FakeCursor([])


def test_build_canonical_rows_emits_xposure_identity() -> None:
    contacts, events, extras = pcs._build_canonical_rows([
        {
            "id": "626963",
            "name": "Buyer One",
            "email": "BUYER@EXAMPLE.COM",
            "phone": "250-555-1212",
            "score": 88,
            "tier": "HOT",
            "searches": ["Kamloops 3 bed"],
            "scrapedAt": "2026-05-26T10:00:00+00:00",
        }
    ])

    assert contacts[0]["source_record_id"] == "626963"
    assert {"kind": "xposure_pcs_id", "value": "626963"} in contacts[0]["identities"]
    assert contacts[0]["email"] == "BUYER@EXAMPLE.COM"
    assert events[0]["contact_id"] == "626963"
    assert extras[0]["source_record_id"] == "626963"


def test_build_canonical_rows_derives_id_when_snapshot_lacks_id() -> None:
    contacts, events, extras = pcs._build_canonical_rows([
        {
            "name": "Buyer One",
            "email": "buyer@example.com",
            "searches": ["Kamloops 3 bed"],
            "dateEntered": "May 26/26",
        }
    ])

    native = contacts[0]["source_record_id"]
    assert native.startswith("derived:")
    assert events[0]["contact_id"] == native
    assert extras[0]["source_record_id"] == native


def test_contact_map_prefers_identity_then_legacy_source_key() -> None:
    conn = FakeConn()
    out = pcs._contact_map_by_native(
        conn,
        contacts=[
            {"source_record_id": "native-1"},
            {"source_record_id": "native-2"},
        ],
    )

    assert out == {
        "native-1": "crm-contact-1",
        "native-2": "legacy-xposure-contact-2",
    }


def test_source_prompt_is_executable_xposure_agent_prompt() -> None:
    from elevate_cli.source_connectors import source_prompt_for

    prompt = source_prompt_for("xposure-pcs")
    assert "You are an automation agent driving the AOIR Xposure MLS" in prompt
    assert "STEPS" in prompt
    assert "pcs-contacts-table" in prompt
    assert "DONE rows=<N>" in prompt
    assert "STATUS: No live pull code exists" not in prompt
    assert "SQLite" not in prompt
    assert "operational.db" not in prompt
    assert "Canonical contract" not in prompt


def test_xposure_pcs_is_scheduled() -> None:
    from elevate_cli.sync_scheduler import _JOBS

    assert any(source_id == "xposure-pcs" for _, source_id, _, _ in _JOBS)
