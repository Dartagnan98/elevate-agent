"""HTTP surface for the Drips section (``/api/drips/*``)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.web_routes.drips import create_drips_router


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(create_drips_router(web_actor="human:test"))
    with TestClient(app) as c:
        yield c


def _make_contact(name="Tara Bourassa", email="tara@example.com"):
    from elevate_cli import data

    with data.connect() as conn:
        return data.upsert_contact(
            conn, display_name=name, primary_email=email, primary_phone="+12505550199",
            type="buyer", source_key=f"test:{email}",
        )


def test_overview_seeds_and_lists_everything(client):
    res = client.get("/api/drips/overview")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["segments"]) == 7
    assert any(c["slug"] == "first-14-days" for c in body["campaigns"])
    assert body["settings"]["sendWindowEnd"] == "20:30"
    assert body["counts"]["videosTotal"] == 22


def test_campaign_crud_and_toggle(client):
    created = client.post(
        "/api/drips/campaigns",
        json={
            "name": "Open house follow-up",
            "kind": "custom",
            "steps": [
                {"day": 1, "channel": "text", "title": "Thanks", "body": "Hi [First Name]!"},
                {"day": 2, "channel": "tag", "title": "Route", "routeTo": "warm"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    campaign = created.json()["campaign"]
    assert campaign["stepCount"] == 2 and campaign["enabled"] is True

    off = client.post(f"/api/drips/campaigns/{campaign['id']}/enabled", json={"enabled": False})
    assert off.json()["campaign"]["enabled"] is False

    renamed = client.put(f"/api/drips/campaigns/{campaign['id']}", json={"name": "Open house", "triggerSegment": "warm"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["campaign"]["triggerSegment"] == "warm"

    bad = client.put(f"/api/drips/campaigns/{campaign['id']}", json={"triggerSegment": "nope"})
    assert bad.status_code == 400

    step = client.post(
        f"/api/drips/campaigns/{campaign['id']}/steps",
        json={"day": 4, "channel": "email", "title": "Sold prices", "subject": "What sold", "body": "Hi"},
    )
    assert step.status_code == 200, step.text
    moved = client.put(f"/api/drips/steps/{step.json()['step']['id']}", json={"day": 6})
    assert moved.json()["step"]["day"] == 6
    assert client.delete(f"/api/drips/steps/{step.json()['step']['id']}").json() == {"ok": True}

    dup = client.post(f"/api/drips/campaigns/{campaign['id']}/duplicate", json={"name": "Open house v2"})
    assert dup.status_code == 200 and dup.json()["campaign"]["enabled"] is False
    assert client.delete(f"/api/drips/campaigns/{dup.json()['campaign']['id']}").json() == {"ok": True}
    assert client.get("/api/drips/campaigns/missing").status_code == 404


def test_segment_move_enrolls_and_board_lists_touches(client):
    contact = _make_contact()
    res = client.post(
        f"/api/drips/contacts/{contact['id']}/segment",
        json={"segment": "warm", "buying": True, "startDate": "2026-10-01", "note": "said spring"},
    )
    assert res.status_code == 200, res.text
    state = res.json()["contact"]
    assert state["segment"] == "warm"
    assert sorted(s["campaignName"] for s in state["started"]) == ["Buyer Course", "Warm Nurture"]

    board = client.get("/api/drips/board", params={"date": "2026-10-01", "horizon": 7}).json()
    assert board["counts"]["today"] == 1
    item = board["today"][0]
    assert item["campaignName"] == "Warm Nurture" and item["contact"]["name"] == "Tara Bourassa"
    assert item["body"].startswith("Hi Tara :)")

    done = client.post(f"/api/drips/touches/{item['id']}/done", json={"note": "sent by text"})
    assert done.status_code == 200 and done.json()["touch"]["status"] == "done"

    found = client.get("/api/drips/contacts", params={"q": "tara"}).json()["contacts"]
    assert found and found[0]["segment"] == "warm" and found[0]["buying"] is True

    enrollment_id = state["started"][0]["enrollmentId"]
    assert client.post(f"/api/drips/enrollments/{enrollment_id}/pause").json()["enrollment"]["status"] == "paused"
    assert client.post(f"/api/drips/enrollments/{enrollment_id}/resume").json()["enrollment"]["status"] == "active"
    stopped = client.post(f"/api/drips/enrollments/{enrollment_id}/stop", json={"reason": "bought elsewhere"})
    assert stopped.json()["enrollment"]["status"] == "stopped"

    cleared = client.post(f"/api/drips/contacts/{contact['id']}/segment", json={"segment": None})
    assert cleared.json()["contact"]["segment"] is None
    assert client.get("/api/drips/contacts/nobody").status_code == 404


def test_segments_videos_templates_and_settings(client):
    seg = client.post("/api/drips/segments", json={"label": "Investors", "color": "#336699"})
    assert seg.status_code == 200 and seg.json()["segment"]["key"] == "investors"
    renamed = client.put("/api/drips/segments/lukewarm", json={"label": "Cool"})
    assert renamed.json()["segment"]["label"] == "Cool"
    blocked = client.delete("/api/drips/segments/warm")
    assert blocked.status_code == 400
    assert client.delete("/api/drips/segments/investors").json() == {"ok": True}

    video = client.put("/api/drips/videos/market-insight", json={"link": "https://youtu.be/abc"})
    assert video.status_code == 200 and video.json()["video"]["recordedAt"]
    bad_link = client.put("/api/drips/videos/market-insight", json={"link": "youtu.be/abc"})
    assert bad_link.status_code == 400
    custom_video = client.post("/api/drips/videos", json={"name": "Neighbourhood tour", "script": "Hi!"})
    assert custom_video.json()["video"]["slug"] == "neighbourhood-tour"

    templates = client.get("/api/drips/templates").json()["templates"]
    assert {t["slug"] for t in templates} >= {"first-14-days", "buyer-course", "raving-fan-club"}
    copy = client.post("/api/drips/templates/bad-number-drip/install", json={"asCopy": True}).json()["campaign"]
    assert copy["name"].endswith("(Elevation copy)") and copy["enabled"] is False

    settings = client.put("/api/drips/settings", json={"callsAsTasks": False, "sendWindowStart": "9:00"}).json()["settings"]
    assert settings["callsAsTasks"] is False and settings["sendWindowStart"] == "09:00"
    assert client.put("/api/drips/settings", json={"sendWindowEnd": "nope"}).status_code == 400

    run = client.post("/api/drips/run", json={"date": "2026-10-01"})
    assert run.status_code == 200 and "routed" in run.json()["run"]
