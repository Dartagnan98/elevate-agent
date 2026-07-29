"""Contact-card writes go through the data module — and still land.

The card's write endpoints used to run raw ``UPDATE contacts`` from the
route (see ``tests/elevate_cli/data/test_data_module_isolation.py``).
Postgres is the primary read path, so a route-level write skips the data
module's invariants and mirroring and a card edit can land inconsistently.

These tests pin both halves: the route file no longer hand-writes the
central table, and every endpoint still persists exactly what it did
before (same columns, same response shape).

Hermetic: ``conftest.py`` redirects ``ELEVATE_HOME`` to a tmp dir so each
test starts with an empty operational.db.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import connect, get_contact, upsert_contact
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


def _make_contact(**overrides):
    with connect() as conn:
        return upsert_contact(
            conn,
            display_name=overrides.get("display_name", "Card Lead"),
            primary_email=overrides.get("primary_email", "lead@example.com"),
            primary_phone=overrides.get("primary_phone", "+16045550100"),
            source_key=overrides.get("source_key", "lofty-default:card-1"),
        )


def _stored(contact_id: str) -> dict:
    with connect() as conn:
        return get_contact(conn, contact_id)


# ─── the guard itself, scoped to this router ──────────────────────────


def test_contact_card_router_has_no_raw_contacts_writes():
    """No ``INSERT/UPDATE/DELETE contacts`` literal in the route module.

    Scoped copy of the repo-wide isolation gate so this router's own
    regression is caught even while other modules are still being
    migrated off their direct writes.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "elevate_cli"
        / "web_routes"
        / "admin_contact_card.py"
    ).read_text(encoding="utf-8")
    rx = re.compile(
        r"\b(?:INSERT INTO|UPDATE|DELETE FROM|REPLACE INTO)\s+contacts\b",
        re.IGNORECASE,
    )
    offenders = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(source.splitlines(), start=1)
        if not line.strip().startswith("#") and rx.search(line)
    ]
    assert offenders == [], (
        "admin_contact_card.py must write contacts through elevate_cli.data "
        "helpers, not raw SQL:\n  " + "\n  ".join(offenders)
    )


# ─── POST /api/admin/contacts/{id}/tags ───────────────────────────────


def test_post_tags_persists_sorted_unique_tags(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/admin/contacts/{contact['id']}/tags",
        json={"tags": [" Buyer ", "sphere", "buyer", "  ", ""]},
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.json()["tagsJson"]) == ["Buyer", "buyer", "sphere"]
    assert json.loads(_stored(contact["id"])["tagsJson"]) == [
        "Buyer", "buyer", "sphere",
    ]


def test_post_tags_replaces_previous_set(client):
    contact = _make_contact()
    client.post(f"/api/admin/contacts/{contact['id']}/tags", json={"tags": ["a", "b"]})
    resp = client.post(
        f"/api/admin/contacts/{contact['id']}/tags", json={"tags": ["c"]}
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(_stored(contact["id"])["tagsJson"]) == ["c"]


def test_post_tags_unknown_contact_returns_404(client):
    resp = client.post("/api/admin/contacts/nope/tags", json={"tags": ["a"]})
    assert resp.status_code == 404


# ─── POST /api/admin/contacts/{id}/segments ───────────────────────────


def test_post_segments_persists_sorted_unique_segments(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/admin/contacts/{contact['id']}/segments",
        json={"segments": [" past-client ", "vip", "vip", " "]},
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.json()["segmentsJson"]) == ["past-client", "vip"]
    assert json.loads(_stored(contact["id"])["segmentsJson"]) == ["past-client", "vip"]


def test_post_segments_unknown_contact_returns_404(client):
    resp = client.post("/api/admin/contacts/nope/segments", json={"segments": ["a"]})
    assert resp.status_code == 404


# ─── POST /api/admin/contacts/{id}/consent ────────────────────────────


def test_post_consent_writes_cannot_flags(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/admin/contacts/{contact['id']}/consent",
        json={"call": False, "text": True, "email": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["cannotCall"], body["cannotText"], body["cannotEmail"]) == (
        True, False, True,
    )
    stored = _stored(contact["id"])
    assert (stored["cannotCall"], stored["cannotText"], stored["cannotEmail"]) == (
        True, False, True,
    )


def test_post_consent_all_allowed_clears_flags(client):
    contact = _make_contact()
    client.post(
        f"/api/admin/contacts/{contact['id']}/consent",
        json={"call": False, "text": False, "email": False},
    )
    resp = client.post(
        f"/api/admin/contacts/{contact['id']}/consent",
        json={"call": True, "text": True, "email": True},
    )
    assert resp.status_code == 200, resp.text
    stored = _stored(contact["id"])
    assert not stored["cannotCall"]
    assert not stored["cannotText"]
    assert not stored["cannotEmail"]


def test_post_consent_unknown_contact_returns_404(client):
    resp = client.post("/api/admin/contacts/nope/consent", json={"call": True})
    assert resp.status_code == 404


# ─── POST /api/admin/contacts/bulk ────────────────────────────────────


def test_bulk_tags_add_merges_with_existing(client):
    a = _make_contact(source_key="lofty-default:bulk-a")
    b = _make_contact(source_key="lofty-default:bulk-b")
    client.post(f"/api/admin/contacts/{a['id']}/tags", json={"tags": ["keep"]})

    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": [a["id"], b["id"]],
            "action": "tags",
            "mode": "add",
            "value": ["added"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 2, "failed": []}
    assert json.loads(_stored(a["id"])["tagsJson"]) == ["added", "keep"]
    assert json.loads(_stored(b["id"])["tagsJson"]) == ["added"]


def test_bulk_tags_replace_and_remove(client):
    contact = _make_contact()
    client.post(
        f"/api/admin/contacts/{contact['id']}/tags", json={"tags": ["x", "y"]}
    )

    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": [contact["id"]],
            "action": "tags",
            "mode": "replace",
            "value": ["only"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(_stored(contact["id"])["tagsJson"]) == ["only"]

    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": [contact["id"]],
            "action": "tags",
            "mode": "remove",
            "value": "only",
        },
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(_stored(contact["id"])["tagsJson"]) == []


def test_bulk_segments_add(client):
    contact = _make_contact()
    client.post(
        f"/api/admin/contacts/{contact['id']}/segments", json={"segments": ["seed"]}
    )
    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": [contact["id"]],
            "action": "segments",
            "mode": "add",
            "value": ["extra"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert json.loads(_stored(contact["id"])["segmentsJson"]) == ["extra", "seed"]


def test_bulk_reports_missing_contacts_without_aborting(client):
    contact = _make_contact()
    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": ["nope", contact["id"]],
            "action": "tags",
            "mode": "add",
            "value": ["t"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 1
    assert body["failed"] == [{"contactId": "nope", "error": "not found"}]
    assert json.loads(_stored(contact["id"])["tagsJson"]) == ["t"]


def test_bulk_pipeline_still_routes_through_set_pipeline_status(client):
    contact = _make_contact()
    resp = client.post(
        "/api/admin/contacts/bulk",
        json={
            "contactIds": [contact["id"]],
            "action": "pipeline",
            "value": "prospect",
        },
    )
    assert resp.status_code == 200, resp.text
    assert _stored(contact["id"])["pipelineStatus"] == "prospect"


# ─── PATCH /api/admin/contacts/{id} ───────────────────────────────────


def test_patch_writes_only_provided_fields(client):
    contact = _make_contact(display_name="Before", primary_email="before@example.com")
    resp = client.patch(
        f"/api/admin/contacts/{contact['id']}",
        json={"displayName": "After", "buyingTimeFrame": "3-6 months"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["displayName"] == "After"
    assert body["buyingTimeFrame"] == "3-6 months"
    # Untouched keys keep their old values.
    assert body["primaryEmail"] == "before@example.com"
    assert body["top25"] is False
    assert body["temperature"] is None

    stored = _stored(contact["id"])
    assert stored["displayName"] == "After"
    assert stored["buyingTimeFrame"] == "3-6 months"
    assert stored["primaryEmail"] == "before@example.com"
    assert stored["updatedAt"] >= contact["updatedAt"]


def test_patch_writes_every_editable_column(client):
    """Every _EDIT_COLUMNS entry that has a backing column round-trips.

    ``address``/``birthday`` are deliberately absent — no migration ever
    added those columns, so the card has never been able to store them
    (see ``test_patch_address_is_not_backed_by_a_column``).
    """
    contact = _make_contact()
    resp = client.patch(
        f"/api/admin/contacts/{contact['id']}",
        json={
            "displayName": "Full Edit",
            "primaryEmail": "full@example.com",
            "primaryPhone": "+16045550111",
            "buyingTimeFrame": "ASAP",
            "preQualStatus": "pre-approved",
        },
    )
    assert resp.status_code == 200, resp.text
    stored = _stored(contact["id"])
    assert stored["displayName"] == "Full Edit"
    assert stored["primaryEmail"] == "full@example.com"
    assert stored["primaryPhone"] == "+16045550111"
    assert stored["buyingTimeFrame"] == "ASAP"
    assert stored["preQualStatus"] == "pre-approved"


@pytest.mark.xfail(
    reason="pre-existing: contacts.address/contacts.birthday were never added "
    "by a migration, so the card's address + birthday edits 500. Unrelated to "
    "routing writes through the data module — delete this xfail when the "
    "column lands.",
    strict=False,
)
def test_patch_address_is_not_backed_by_a_column(client):
    contact = _make_contact()
    resp = client.patch(
        f"/api/admin/contacts/{contact['id']}", json={"address": "123 Main St"}
    )
    assert resp.status_code == 200, resp.text
    assert _stored(contact["id"])["address"] == "123 Main St"


def test_patch_explicit_null_clears_the_field(client):
    contact = _make_contact()
    client.patch(
        f"/api/admin/contacts/{contact['id']}", json={"preQualStatus": "pre-approved"}
    )
    resp = client.patch(
        f"/api/admin/contacts/{contact['id']}", json={"preQualStatus": None}
    )
    assert resp.status_code == 200, resp.text
    assert _stored(contact["id"])["preQualStatus"] is None


def test_patch_empty_body_is_a_noop_read(client):
    contact = _make_contact()
    resp = client.patch(f"/api/admin/contacts/{contact['id']}", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == contact["displayName"]
    assert _stored(contact["id"])["updatedAt"] == contact["updatedAt"]


def test_patch_unknown_contact_returns_404(client):
    resp = client.patch("/api/admin/contacts/nope", json={"displayName": "x"})
    assert resp.status_code == 404
