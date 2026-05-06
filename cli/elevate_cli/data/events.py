"""Append-only event log writes.

Every business action — inbound message, outbound send, classify, park,
template approval — writes one ``events`` row. The rest of the data
module funnels through :func:`_insert_event`.

Public surface:

* :func:`record_inbound`
* :func:`record_outbound`
* :func:`record_draft`
* :func:`record_send`
* :func:`record_classification`
* :func:`record_lifecycle` (parked / unparked / lifecycle_change / note / merge / merge_conflict)
* :func:`record_pcs_activity`
* :func:`record_template_event` (template_candidate / approved / rejected)
* :func:`record_attribution_ambiguous`
* :func:`record_ingest_marker` (ingest_run_started / completed)
* :func:`record_reply_attributed`
"""

from __future__ import annotations

import sqlite3
from typing import Any

from elevate_cli.data._util import (
    compute_event_hash,
    encode_payload,
    new_id,
    now_iso,
)
from elevate_cli.data import contacts as _contacts


# ─── Internal core ─────────────────────────────────────────────────────


def _insert_event(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str | None,
    kind: str,
    channel: str | None,
    source_id: str,
    actor: str,
    template_id: str | None = None,
    payload: Any = None,
    ingest_run_id: str | None = None,
    event_hash: str | None = None,
    ts: str | None = None,
    thread_key: str | None = None,
    body_for_hash: str | None = None,
) -> dict[str, Any]:
    """Insert one events row, returning a dict.

    If ``event_hash`` is None the function computes it from
    (source_id, thread_key, ts, body_for_hash) per
    docs/source-keys.md. For UI/cron events without a natural
    ``thread_key``, the caller passes a synthetic body string that's
    unique to the action (e.g. ``f"classify:{contact_id}:{type}"``).
    """
    ts_ = ts or now_iso()
    eid = new_id()
    pj, pref = encode_payload(payload)
    eh = event_hash or compute_event_hash(
        source_id=source_id,
        thread_key=thread_key or eid,  # fallback ensures uniqueness for synthetic events
        ts=ts_,
        body=body_for_hash if body_for_hash is not None else (pj or eid),
    )
    conn.execute(
        """
        INSERT INTO events(
            id, contact_id, conversation_id, kind, channel, source_id,
            actor, template_id, payload_json, payload_ref, ingest_run_id,
            event_hash, ts
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            eid, contact_id, conversation_id, kind, channel, source_id,
            actor, template_id, pj, pref, ingest_run_id, eh, ts_,
        ),
    )
    _contacts.touch_last_activity(conn, contact_id, ts_)
    return {
        "id": eid,
        "contactId": contact_id,
        "conversationId": conversation_id,
        "kind": kind,
        "channel": channel,
        "sourceId": source_id,
        "actor": actor,
        "templateId": template_id,
        "ingestRunId": ingest_run_id,
        "eventHash": eh,
        "ts": ts_,
    }


# ─── Public recorders ──────────────────────────────────────────────────


def record_inbound(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    channel: str,
    body: str,
    source_id: str,
    thread_key: str | None,
    ts: str | None = None,
    actor: str = "system",
    ingest_run_id: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="inbound",
        channel=channel,
        source_id=source_id,
        actor=actor,
        payload={"body": body},
        ingest_run_id=ingest_run_id,
        ts=ts,
        thread_key=thread_key,
        body_for_hash=body,
    )


def record_outbound(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    channel: str,
    body: str,
    source_id: str,
    thread_key: str | None,
    template_id: str | None = None,
    draft_attempt_id: str | None = None,
    ts: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="outbound",
        channel=channel,
        source_id=source_id,
        actor=actor,
        template_id=template_id,
        payload={"body": body, "draftAttemptId": draft_attempt_id},
        ts=ts,
        thread_key=thread_key,
        body_for_hash=body,
    )


def record_draft(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    body: str,
    template_id: str,
    actor: str,
    source_id: str = "agent",
    ts: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="draft",
        channel=None,
        source_id=source_id,
        actor=actor,
        template_id=template_id,
        payload={"body": body},
        ts=ts,
    )


def record_send(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    channel: str,
    template_id: str | None,
    provider_message_id: str | None,
    source_id: str,
    ts: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="send",
        channel=channel,
        source_id=source_id,
        actor=actor,
        template_id=template_id,
        payload={"providerMessageId": provider_message_id},
        ts=ts,
    )


def record_classification(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    type: str,
    actor: str,
    ts: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=None,
        kind="classified",
        channel=None,
        source_id="ui:classify",
        actor=actor,
        payload={"type": type},
        ts=ts,
        body_for_hash=f"classify:{contact_id}:{type}",
    )


def record_lifecycle(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    kind: str,
    actor: str,
    ts: str | None = None,
    payload: Any = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Catch-all for lifecycle-shaped events: parked, unparked,
    lifecycle_change, note, merge, merge_conflict."""
    valid = {
        "parked", "unparked", "lifecycle_change", "note",
        "merge", "merge_conflict",
    }
    if kind not in valid:
        raise ValueError(f"unsupported lifecycle kind {kind!r}")
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind=kind,
        channel=None,
        source_id="ui:lifecycle",
        actor=actor,
        payload=payload,
        ts=ts,
    )


def record_pcs_activity(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    mls_payload: Any,
    ts: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=None,
        kind="pcs_activity",
        channel=None,
        source_id="mls-private-search",
        actor="system",
        payload=mls_payload,
        ts=ts,
    )


def record_template_event(
    conn: sqlite3.Connection,
    *,
    kind: str,                   # template_candidate | template_approved | template_rejected
    contact_id: str,             # nullable in spirit but FK requires a real contact;
                                 # caller passes a "system contact" id when no real one exists
    template_id: str,
    actor: str,
    payload: Any = None,
    ts: str | None = None,
) -> dict[str, Any]:
    if kind not in {
        "template_candidate", "template_approved", "template_rejected",
    }:
        raise ValueError(f"invalid template event kind {kind!r}")
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=None,
        kind=kind,
        channel=None,
        source_id="ui:templates",
        actor=actor,
        template_id=template_id,
        payload=payload,
        ts=ts,
    )


def record_attribution_ambiguous(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    candidate_template_ids: list[str],
    reason: str,
    ts: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="attribution_ambiguous",
        channel=None,
        source_id="agent:attribution",
        actor="system",
        payload={
            "candidateTemplateIds": candidate_template_ids,
            "reason": reason,
        },
        ts=ts,
    )


def record_reply_attributed(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    conversation_id: str,
    template_id: str,
    draft_attempt_id: str,
    ts: str | None = None,
) -> dict[str, Any]:
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=conversation_id,
        kind="reply_attributed",
        channel=None,
        source_id="agent:attribution",
        actor="system",
        template_id=template_id,
        payload={"draftAttemptId": draft_attempt_id},
        ts=ts,
    )


def record_ingest_marker(
    conn: sqlite3.Connection,
    *,
    kind: str,                   # ingest_run_started | ingest_run_completed
    ingest_run_id: str,
    source_id: str,
    contact_id: str,             # see comment in record_template_event
    payload: Any = None,
    ts: str | None = None,
) -> dict[str, Any]:
    if kind not in {"ingest_run_started", "ingest_run_completed"}:
        raise ValueError(f"invalid ingest marker kind {kind!r}")
    return _insert_event(
        conn,
        contact_id=contact_id,
        conversation_id=None,
        kind=kind,
        channel=None,
        source_id=source_id,
        actor="system",
        payload=payload,
        ingest_run_id=ingest_run_id,
        ts=ts,
        body_for_hash=f"{kind}:{ingest_run_id}",
    )
