"""End-to-end smoke test for the core realtor loop: Outreach -> Lead -> CMA.

WHAT THIS PROVES (and what it does NOT):
  This is a *pipeline liveness* test. It asserts each stage of the core loop
  RAN and produced its expected artifact against sandbox fixtures:

    1. Outreach  — a pending-approval send is approved, released, and the
                   sender delivers it (through the guaranteed-safe SANDBOX stub,
                   never a real transport). Final send_queue status == 'sent'.
    2. Lead      — the recipient exists as a contact + conversation, and the
                   successful send mirrors an 'outbound' event onto that lead
                   (the link that ties outreach back to a captured lead).
    3. CMA       — moving the listing deal into the CMA stage dispatches the
                   CMA skill (an admin_action_run for skill 'real-estate-admin/cma'),
                   and a CMA report artifact attaches to the deal.

  It does NOT prove the CMA is *correct* or *good*. Comp selection, pricing
  story, provenance, and photo analysis are a HUMAN read (see cli/skills/cma
  "Provenance contract"). A green smoke test means the wiring is intact, not
  that the deliverable is client-ready.

SAFETY:
  ``ELEVATE_OUTREACH_SANDBOX=1`` is forced for the whole module BEFORE
  ``elevate_cli.sender`` is imported, so every channel routes through
  ``sender._stub_dispatch`` — no Messages.app, no Composio, no agent send.
  The recipients below are obviously-fake fixtures (555-01xx numbers,
  @example.com). Nothing in this test can reach a real person.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

# HARD SAFETY GATE: set before importing sender so _wire_default_dispatchers
# (runs at import) never registers a real transport for this process.
os.environ["ELEVATE_OUTREACH_SANDBOX"] = "1"

from elevate_cli import data, outreach_db, sender  # noqa: E402
from elevate_cli.data.connection import _reset_schema_cache  # noqa: E402


# ---------------------------------------------------------------------------
# Test-realtor fixture: a fake realtor identity + a sandbox contact list.
# These are the ONLY people this loop is ever allowed to "message".
# ---------------------------------------------------------------------------
SANDBOX_REALTOR = {
    "realtorLegalName": "Sandbox Test Realtor",
    "brokerageName": "Fixture Brokerage Ltd.",
    "province": "BC",
    "approvalChannel": "telegram:sandbox",
}

# Deliberately unroutable: 555-01xx is the reserved fictional block; the email
# domain is RFC-2606 reserved. Even without the sandbox stub these can't land.
SANDBOX_CONTACTS = [
    {
        "display_name": "Ava Fixture",
        "primary_phone": "+15550100",
        "primary_email": "ava.fixture@example.com",
        "source_id": "crm",
        "channel": "sms",
        "thread_key": "sandbox-thread-ava",
        "draft_text": "Hi Ava, saw you were looking in Kitsilano. Want the short list?",
    },
]


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def sandbox_realtor():
    """Persist the fake realtor identity into the operational store so
    outreach copy resolves to THIS realtor, not a hardcoded name."""
    from elevate_cli.data.admin_setup import update_admin_setup

    with data.connect() as conn:
        update_admin_setup(conn, profile=SANDBOX_REALTOR, actor="smoke-test")
    return SANDBOX_REALTOR


def _seed_lead(contact_spec: dict) -> dict:
    """Stage 2 pre-req: a captured lead (contact + conversation) the outbound
    send can mirror onto. Returns {contactId, conversationId}."""
    with data.connect() as conn:
        contact = data.upsert_contact(
            conn,
            display_name=contact_spec["display_name"],
            primary_phone=contact_spec.get("primary_phone"),
            primary_email=contact_spec.get("primary_email"),
            source_key=contact_spec["source_id"],
        )
        conversation = data.get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id=contact_spec["source_id"],
            channel=contact_spec["channel"],
            thread_key=contact_spec["thread_key"],
        )
    return {"contactId": contact["id"], "conversationId": conversation["id"]}


def _enqueue_pending_approval(contact_spec: dict) -> str:
    """Simulate what an outreach cron writes: a send_queue row awaiting human
    approval (status='pending_approval'), never auto-sent. Returns task_id."""
    task_id = f"smoke-task-{uuid.uuid4().hex[:8]}"
    payload = {
        "draft_text": contact_spec["draft_text"],
        "recipient": {
            "person_name": contact_spec["display_name"],
            "phone": contact_spec.get("primary_phone"),
            "email": contact_spec.get("primary_email"),
        },
        "source_id": contact_spec["source_id"],
        "thread_id": contact_spec["thread_key"],
        "task_id": task_id,
        # mirrored outbound event reads payload["text"] or ["draft_text"]:
        "text": contact_spec["draft_text"],
    }
    now = outreach_db._now()
    with outreach_db.connect() as conn:
        with outreach_db.transaction(conn):
            conn.execute(
                """
                INSERT INTO send_queue
                    (id, idempotency_key, source_id, thread_id, task_id, channel,
                     payload_json, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_approval', 0, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    outreach_db.make_idempotency_key(
                        contact_spec["source_id"], contact_spec["thread_key"], task_id
                    ),
                    contact_spec["source_id"],
                    contact_spec["thread_key"],
                    task_id,
                    contact_spec["channel"],
                    json.dumps(payload),
                    now,
                    now,
                ),
            )
    return task_id


def test_sandbox_is_active():
    """Precondition: the safety kill switch is on for this process, so no
    channel can reach a real recipient."""
    assert sender.sandbox_enabled() is True
    # Every channel resolves to the stub, even ones with a real dispatcher name.
    for channel in ("sms", "email", "social_dm", "crm_note"):
        assert sender.get_dispatcher(channel) is sender._stub_dispatch


def test_outreach_cma_loop(sandbox_realtor, tmp_path):
    contact_spec = SANDBOX_CONTACTS[0]

    # ---- STAGE: LEAD CAPTURED --------------------------------------------
    lead = _seed_lead(contact_spec)
    assert lead["contactId"]
    assert lead["conversationId"]

    # ---- STAGE: OUTREACH RAN (approve -> release -> send) ----------------
    task_id = _enqueue_pending_approval(contact_spec)

    released = outreach_db.approve_pending_send(contact_spec["source_id"], task_id)
    assert released is not None, "approve should release the pending row to 'queued'"
    assert released["status"] == outreach_db.SEND_STATUS_QUEUED

    counts = sender.tick(batch=10)
    assert counts["sent"] == 1, f"expected exactly one sandbox send, got {counts}"

    sent = outreach_db.get_send_by_task(
        contact_spec["source_id"], contact_spec["thread_key"], task_id
    )
    assert sent is not None
    assert sent["status"] == outreach_db.SEND_STATUS_SENT
    # Proof it went through the SANDBOX stub, not a real transport.
    assert sent["providerMessageId"].startswith("stub-"), sent["providerMessageId"]

    # ---- STAGE: OUTREACH <-> LEAD LINK -----------------------------------
    # A successful send mirrors an 'outbound' event onto the captured lead's
    # conversation. This is the join that makes the send attributable.
    with data.connect() as conn:
        outbound = conn.execute(
            "SELECT COUNT(*) FROM events WHERE conversation_id=? AND kind='outbound'",
            (lead["conversationId"],),
        ).fetchone()[0]
    assert outbound == 1, "successful send should mirror one outbound event onto the lead"

    # ---- STAGE: CMA GENERATED --------------------------------------------
    from elevate_cli.data.dispatch import ensure_default_admin_actions
    from elevate_cli.data.dispatch import evaluate as evaluate_dispatch

    with data.connect() as conn:
        ensure_default_admin_actions(conn)
        deal = data.create_deal(
            conn,
            title=f"Seller: {contact_spec['display_name']}",
            side="listing",
            actor="smoke-test",
            province=SANDBOX_REALTOR["province"],
            current_stage=0,
            primary_contact_id=lead["contactId"],
            listing_address="123 Sandbox Ave, Kitsilano",
            dispatch_initial_stage=False,
        )

        # Entering the CMA/Evaluation stage (stage 1) must dispatch the CMA skill.
        runs = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            trigger="stage_entry",
            actor="smoke-test",
            to_stage=1,
            create_cron_jobs=False,
        )

    cma_runs = [r for r in runs if str(r.get("skill") or "").endswith("/cma")]
    assert cma_runs, f"CMA stage entry should dispatch the cma skill; got skills={[r.get('skill') for r in runs]}"

    # Simulate the CMA skill closing the run by attaching its report artifact
    # (the human-facing deliverable). We assert the artifact EXISTS, not that
    # its contents are correct — that is a human judgment.
    cma_pdf = tmp_path / "cma_report.pdf"
    cma_pdf.write_bytes(b"%PDF-1.4\n% sandbox fixture CMA - not a real valuation\n")
    with data.connect() as conn:
        attachment = data.add_deal_attachment(
            conn,
            deal["id"],
            kind="cma_report",
            file_path=str(cma_pdf),
            summary="Sandbox CMA fixture",
            actor="skill:cma",
        )
        attachments = data.list_deal_attachments(conn, deal["id"])

    assert attachment["kind"] == "cma_report"
    assert any(a["kind"] == "cma_report" for a in attachments)
    assert cma_pdf.exists() and cma_pdf.stat().st_size > 0

    # ---- FINAL: all four stage markers present ---------------------------
    assert sent["status"] == "sent"          # outreach ran
    assert outbound == 1                      # lead captured + linked
    assert cma_runs                           # cma dispatched
    assert attachment["id"]                   # cma artifact exists
