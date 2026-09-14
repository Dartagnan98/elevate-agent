"""Contact-card edits and deletion persist through the operational data API."""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli.data import connect, get_contact, upsert_contact
from elevate_cli.data.contacts import update_contact_fields
from elevate_cli.web_routes.admin_contact_card import create_admin_contact_card_router
from elevate_cli.web_routes.admin_contacts import create_admin_contacts_router


@pytest.fixture
def client(monkeypatch):
    account = f"acct_t{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr("elevate_cli.data.connection.get_account_key", lambda: account)
    app = FastAPI()
    app.include_router(create_admin_contact_card_router(web_actor="human:test"))
    app.include_router(create_admin_contacts_router(web_actor="human:test"))
    with TestClient(app) as client:
        yield client


def contact(name):
    with connect() as conn:
        return upsert_contact(conn, display_name=name)["id"]


def test_card_edits_and_bulk_updates_preserve_other_contacts(client):
    edited, untouched = contact("Edited"), contact("Untouched")
    base = f"/api/admin/contacts/{edited}"
    for suffix, payload in [
        ("/tags", {"tags": ["buyer", "buyer", " priority "]}),
        ("/segments", {"segments": ["north"]}),
        ("/consent", {"call": False, "text": True, "email": False}),
    ]:
        response = client.post(base + suffix, json=payload)
        assert response.status_code == 200, response.text
    response = client.patch(base, json={"displayName": "Updated", "primaryEmail": "new@example.test"})
    assert response.status_code == 200, response.text
    response = client.post("/api/admin/contacts/bulk", json={
        "contactIds": [edited], "action": "tags", "mode": "remove", "value": ["buyer"],
    })
    assert response.status_code == 200, response.text
    with connect() as conn:
        row = get_contact(conn, edited)
        assert row["displayName"] == "Updated"
        assert row["primaryEmail"] == "new@example.test"
        assert json.loads(row["tagsJson"]) == ["priority"]
        assert json.loads(row["segmentsJson"]) == ["north"]
        assert row["cannotCall"] and row["cannotEmail"] and not row["cannotText"]
        assert get_contact(conn, untouched)["displayName"] == "Untouched"


def test_contact_edit_rejects_non_editable_columns(client):
    cid = contact("Safe")
    with connect() as conn:
        with pytest.raises(ValueError, match="Unsupported contact fields"):
            update_contact_fields(conn, cid, {"id": "replacement"})
        assert get_contact(conn, cid)["displayName"] == "Safe"


def test_delete_removes_dependent_notes_and_preserves_other_contacts(client):
    deleted, retained = contact("Delete"), contact("Retain")
    for cid in (deleted, retained):
        response = client.post(f"/api/admin/contacts/{cid}/notes", json={"body": "Keep with this contact"})
        assert response.status_code == 200, response.text
    response = client.delete(f"/api/admin/contacts/{deleted}")
    assert response.status_code == 200, response.text
    assert response.json()["deleted"]["contacts"] == 1
    with connect() as conn:
        assert get_contact(conn, deleted) is None
        assert get_contact(conn, retained) is not None
        assert conn.execute("SELECT COUNT(*) FROM notes WHERE contact_id=?", (deleted,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM notes WHERE contact_id=?", (retained,)).fetchone()[0] == 1
