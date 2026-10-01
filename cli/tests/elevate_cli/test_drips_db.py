"""Drip campaign store + engine tests (embedded Postgres via the hermetic env)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from elevate_cli import data, drip_templates, drips_db
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _contact(conn, name="Tara Bourassa", email="tara@example.com", type="buyer"):
    return data.upsert_contact(
        conn,
        display_name=name,
        primary_email=email,
        primary_phone="+12505550199",
        type=type,
        source_key=f"test:{email}",
    )


def _campaign(conn, slug):
    row = conn.execute("SELECT id FROM drip_campaigns WHERE slug=?", (slug,)).fetchone()
    assert row, slug
    return row["id"]


# ─── Seeding ───────────────────────────────────────────────────────────


def test_seed_installs_elevation_library_once():
    with drips_db.connect() as conn:
        segments = drips_db.list_segments(conn)
        campaigns = drips_db.list_campaigns(conn)
        videos = drips_db.list_videos(conn)
        assert [s["key"] for s in segments] == [s["key"] for s in drip_templates.SEGMENTS]
        assert {c["templateSlug"] for c in campaigns} == {c["slug"] for c in drip_templates.CAMPAIGNS}
        assert len(videos) == len(drip_templates.VIDEOS)
        assert all(c["enabled"] for c in campaigns)
        warm = drips_db.get_campaign(conn, _campaign(conn, "warm-nurture"))
        assert [s["day"] for s in warm["steps"]] == [1, 4, 9, 14, 21, 30, 40, 50, 60, 70, 85, 92]
        # second connect must not duplicate anything
        assert drips_db.maybe_seed(conn) is False
        assert len(drips_db.list_campaigns(conn)) == len(campaigns)


def test_template_days_never_clash_with_courses():
    """Buyer Course (3,5,7,11,13,16,18,22,24) and Seller Course (6,8,12,17,19,23,26)
    must miss every text/email day in the nurture campaigns they layer on."""
    buyer = {s["day"] for s in drip_templates.campaign_by_slug("buyer-course")["steps"] if s["channel"] == "email"}
    seller = {s["day"] for s in drip_templates.campaign_by_slug("seller-course")["steps"] if s["channel"] == "email"}
    assert not (buyer & seller)
    for slug in ("warm-nurture", "lukewarm-nurture", "long-term-nurture", "bad-number-drip"):
        sends = {s["day"] for s in drip_templates.campaign_by_slug(slug)["steps"] if s["channel"] in ("text", "email")}
        assert not (sends & buyer), slug
        assert not (sends & seller), slug


# ─── Segments ──────────────────────────────────────────────────────────


def test_segments_can_be_renamed_added_and_reordered():
    with drips_db.connect() as conn:
        renamed = drips_db.update_segment(conn, "lukewarm", label="Cool", windowLabel="3 to 6 months")
        assert renamed["label"] == "Cool"
        custom = drips_db.create_segment(conn, label="Investors", color="#123456")
        assert custom["key"] == "investors" and custom["builtin"] is False
        keys = [s["key"] for s in drips_db.list_segments(conn)]
        keys.remove("investors")
        keys.insert(0, "investors")
        reordered = drips_db.reorder_segments(conn, keys)
        assert reordered[0]["key"] == "investors"
        with pytest.raises(ValueError):
            drips_db.delete_segment(conn, "warm")  # Warm Nurture starts from it
        assert drips_db.delete_segment(conn, "investors") is True


# ─── Enrollment + layering ─────────────────────────────────────────────


def test_new_lead_runs_first_14_days_and_defers_the_course():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        start = date(2026, 10, 1)
        state = drips_db.set_contact_segment(
            conn, contact["id"], "new", actor="human:test", buying=True, start_date=start,
        )
        names = [s["campaignName"] for s in state["started"]]
        assert names == ["The First 14 Days"]  # Buyer Course waits for day 15
        enrollment = drips_db.get_enrollment(conn, state["started"][0]["enrollmentId"])
        touches = enrollment["touches"]
        assert len(touches) == 14
        assert touches[0]["dueDate"] == "2026-10-01" and touches[0]["channel"] == "call"
        assert touches[-1]["dueDate"] == "2026-10-15" and touches[-1]["channel"] == "tag"


def test_segment_move_ends_old_campaign_and_layers_courses_on_free_days():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        start = date(2026, 10, 1)
        drips_db.set_contact_segment(conn, contact["id"], "new", actor="human:test", start_date=start)
        moved = drips_db.set_contact_segment(
            conn, contact["id"], "warm", actor="human:test", buying=True, selling=True, start_date=start,
        )
        assert len(moved["stopped"]) == 1
        started = sorted(s["campaignName"] for s in moved["started"])
        assert started == ["Buyer Course", "Seller Course", "Warm Nurture"]
        live = drips_db.list_enrollments(conn, contact_id=contact["id"], live_only=True)
        assert sorted(e["campaignName"] for e in live) == ["Buyer Course", "Seller Course", "Warm Nurture"]
        # no two sends on the same day across the three runs
        rows = conn.execute(
            """
            SELECT t.due_date, COUNT(*) AS n FROM drip_touches t
            JOIN drip_enrollments e ON e.id=t.enrollment_id
            JOIN drip_steps s ON s.id=t.step_id
            WHERE e.contact_id=? AND t.status='scheduled' AND s.channel IN ('text','email')
            GROUP BY t.due_date HAVING COUNT(*) > 1
            """,
            (contact["id"],),
        ).fetchall()
        assert rows == []
        # the First 14 Days touches were cancelled by the move
        cancelled = conn.execute(
            "SELECT COUNT(*) AS n FROM drip_touches t JOIN drip_enrollments e ON e.id=t.enrollment_id WHERE e.contact_id=? AND t.status='cancelled'",
            (contact["id"],),
        ).fetchone()
        assert int(cancelled["n"]) == 14


def test_course_runs_once_per_person():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        buyer_course = _campaign(conn, "buyer-course")
        first = drips_db.enroll_contact(conn, buyer_course, contact["id"], actor="human:test", start_date=date(2026, 1, 1))
        assert first["created"] is True
        again = drips_db.enroll_contact(conn, buyer_course, contact["id"], actor="human:test", start_date=date(2026, 1, 1))
        assert again["created"] is False and again["id"] == first["id"]
        # run the engine past day 25 so the "done" tag fires
        summary = drips_db.run_engine(conn, today=date(2026, 2, 1))
        assert summary["completed"] >= 1
        assert drips_db.get_enrollment(conn, first["id"])["status"] == "completed"
        with pytest.raises(ValueError, match="runs once"):
            drips_db.enroll_contact(conn, buyer_course, contact["id"], actor="human:test", start_date=date(2026, 3, 1))


def test_campaign_switched_off_blocks_enrollment_and_hides_from_board():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        warm = _campaign(conn, "warm-nurture")
        drips_db.set_campaign_enabled(conn, warm, False)
        state = drips_db.set_contact_segment(conn, contact["id"], "warm", actor="human:test", start_date=date(2026, 10, 1))
        assert state["started"] == []  # nothing auto-started while Warm Nurture is off
        with pytest.raises(ValueError, match="switched off"):
            drips_db.enroll_contact(conn, warm, contact["id"], actor="human:test")
        drips_db.set_campaign_enabled(conn, warm, True)
        enrollment = drips_db.enroll_contact(conn, warm, contact["id"], actor="human:test", start_date=date(2026, 10, 1))
        assert enrollment["created"] is True
        board = drips_db.due_board(conn, today=date(2026, 10, 1), horizon_days=0)
        assert [i["campaignName"] for i in board["today"]] == ["Warm Nurture"]
        drips_db.set_campaign_enabled(conn, warm, False)
        board = drips_db.due_board(conn, today=date(2026, 10, 1), horizon_days=0)
        assert board["today"] == []


# ─── Board + engine ────────────────────────────────────────────────────


def test_board_renders_copy_and_flags_missing_pieces():
    with drips_db.connect() as conn:
        contact = _contact(conn, name="Priya Devi", email="priya@example.com")
        drips_db.set_contact_segment(conn, contact["id"], "lukewarm", actor="human:test", start_date=date(2026, 10, 1))
        board = drips_db.due_board(conn, today=date(2026, 10, 1), horizon_days=0)
        item = board["today"][0]
        assert item["channel"] == "email"
        assert item["body"].startswith("Hi Priya :)")
        assert "[First Name]" not in item["body"]
        assert item["contact"]["segment"] == "lukewarm"
        # day 45 carries the Market Insight video, not recorded yet
        later = drips_db.due_board(conn, today=date(2026, 11, 14), horizon_days=0)
        video_item = [i for i in later["today"] if i["video"]][0]
        assert video_item["video"]["slug"] == "market-insight"
        assert video_item["videoMissing"] is True
        drips_db.update_video(conn, "market-insight", link="https://youtu.be/abc123")
        later = drips_db.due_board(conn, today=date(2026, 11, 14), horizon_days=0)
        video_item = [i for i in later["today"] if i["video"]][0]
        assert video_item["videoMissing"] is False
        assert "https://youtu.be/abc123" in video_item["body"]


def test_engine_auto_routes_on_day_15_and_starts_the_next_campaign():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        start = date(2026, 10, 1)
        drips_db.set_contact_segment(conn, contact["id"], "new", actor="human:test", buying=True, start_date=start)
        summary = drips_db.run_engine(conn, today=start + timedelta(days=14))
        assert summary["routed"] and summary["routed"][0]["to"] == "lukewarm"
        state = drips_db.contact_drip_state(conn, contact["id"])
        assert state["segment"] == "lukewarm"
        live = sorted(e["campaignName"] for e in state["enrollments"] if e["status"] == "active")
        assert live == ["Buyer Course", "Lukewarm Nurture"]
        assert "Drips: moved to Lukewarm" in (data.get_contact(conn, contact["id"])["ownerNotes"] or "")


def test_engine_respects_manual_moves_and_auto_tag_setting():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        start = date(2026, 10, 1)
        drips_db.set_contact_segment(conn, contact["id"], "warm", actor="human:test", start_date=start)
        drips_db.update_settings(conn, {"autoTagMoves": False})
        summary = drips_db.run_engine(conn, today=start + timedelta(days=100))
        assert summary["routed"] == []
        assert drips_db.contact_drip_state(conn, contact["id"])["segment"] == "warm"
        drips_db.update_settings(conn, {"autoTagMoves": True})
        summary = drips_db.run_engine(conn, today=start + timedelta(days=100))
        assert [r["to"] for r in summary["routed"]] == ["lukewarm"]


def test_engine_turns_due_calls_into_tasks_once():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        start = date(2026, 10, 1)
        drips_db.set_contact_segment(conn, contact["id"], "new", actor="human:test", start_date=start)
        first = drips_db.run_engine(conn, today=start)
        assert first["tasksCreated"] == 1
        second = drips_db.run_engine(conn, today=start)
        assert second["tasksCreated"] == 0
        board = drips_db.due_board(conn, today=start, horizon_days=0)
        call = [i for i in board["today"] if i["channel"] == "call"][0]
        assert call["taskId"]


def test_touch_done_and_skip_complete_the_run():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        custom = drips_db.create_campaign(
            conn, name="Open house follow-up", kind="custom",
            steps=[
                {"day": 1, "channel": "text", "title": "Thanks for coming", "body": "Hi [First Name], thanks for coming by!"},
                {"day": 3, "channel": "email", "title": "Sold prices", "subject": "What it sold for", "body": "Hi [First Name] :)"},
            ],
        )
        enrollment = drips_db.enroll_contact(conn, custom["id"], contact["id"], actor="human:test", start_date=date(2026, 10, 1))
        touches = enrollment["touches"]
        drips_db.complete_touch(conn, touches[0]["id"], status="done")
        drips_db.complete_touch(conn, touches[1]["id"], status="skipped", note="already spoke")
        assert drips_db.get_enrollment(conn, enrollment["id"])["status"] == "completed"


def test_step_edits_reschedule_live_runs():
    with drips_db.connect() as conn:
        contact = _contact(conn)
        custom = drips_db.create_campaign(
            conn, name="Just listed", kind="custom",
            steps=[{"day": 1, "channel": "text", "title": "Heads up", "body": "x"}],
        )
        enrollment = drips_db.enroll_contact(conn, custom["id"], contact["id"], actor="human:test", start_date=date.today())
        step = custom["steps"][0]
        drips_db.update_step(conn, step["id"], day=5)
        added = drips_db.add_step(conn, custom["id"], day=9, channel="email", title="Photos", body="y")
        refreshed = drips_db.get_enrollment(conn, enrollment["id"])
        due = sorted(t["dueDate"] for t in refreshed["touches"] if t["status"] == "scheduled")
        assert due == [(date.today() + timedelta(days=4)).isoformat(), (date.today() + timedelta(days=8)).isoformat()]
        drips_db.delete_step(conn, added["id"])
        refreshed = drips_db.get_enrollment(conn, enrollment["id"])
        assert len(refreshed["touches"]) == 1


def test_templates_install_copy_and_reset():
    with drips_db.connect() as conn:
        templates = drips_db.list_templates(conn)
        assert all(t["installed"] for t in templates)
        warm_id = _campaign(conn, "warm-nurture")
        drips_db.update_campaign(conn, warm_id, name="My warm drip")
        drips_db.delete_step(conn, drips_db.get_campaign(conn, warm_id)["steps"][0]["id"])
        copy = drips_db.install_template(conn, "warm-nurture", as_copy=True)
        assert copy["enabled"] is False and copy["triggerSegment"] is None
        assert copy["stepCount"] == 12
        reset = drips_db.reset_campaign_to_template(conn, warm_id)
        assert reset["name"] == "Warm Nurture" and reset["stepCount"] == 12
        with pytest.raises(ValueError):
            drips_db.reset_campaign_to_template(conn, copy["id"])


def test_settings_round_trip_and_auto_enroll_only_new_leads():
    with drips_db.connect() as conn:
        old = _contact(conn, name="Old Lead", email="old@example.com")
        settings = drips_db.update_settings(conn, {"autoEnrollNewLeads": True, "sendWindowEnd": "20:30"})
        assert settings["autoEnrollNewLeads"] is True and settings["autoEnrollSince"]
        with pytest.raises(ValueError):
            drips_db.update_settings(conn, {"sendWindowStart": "late"})
        # created before the switch was flipped: untouched
        summary = drips_db.run_engine(conn, today=date.today())
        assert drips_db.contact_drip_state(conn, old["id"])["segment"] is None
        conn.execute("UPDATE contacts SET created_at=? WHERE id=?", ("2999-01-01T00:00:00+00:00", old["id"]))
        realtor = _contact(conn, name="Some Realtor", email="agent@example.com", type="other")
        summary = drips_db.run_engine(conn, today=date.today())
        assert summary["autoEnrolled"] == 1
        assert drips_db.contact_drip_state(conn, old["id"])["segment"] == "new"
        assert drips_db.contact_drip_state(conn, realtor["id"])["segment"] is None


def test_render_text_reports_leftover_placeholders():
    out = drips_db.render_text(
        "Hi [First Name] :) It is [Your Name] from [Brokerage]. [Insert video: Welcome] Which [Area]?",
        first_name="Tara", agent_name="Skyleigh", brokerage="Elevation", video_link=None,
    )
    assert out["text"].startswith("Hi Tara :) It is Skyleigh from Elevation.")
    assert out["placeholders"] == ["[Area]"]
    assert out["videoMissing"] is True
