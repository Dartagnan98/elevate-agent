"""Contact-scoped (client-level) compliance documents.

Sibling of ``deal_attachments`` (deal-scoped). Some documents belong to the
*client relationship*, not to any one property, and are reusable across a
client's deals within their validity window:

    dorts      Disclosure of Representation in Trading Services  (durable)
    pnc        Privacy Notice & Consent                          (durable)
    fintrac_id FINTRAC / FINTRACKER individual identification    (validity window)
    lotr       LOTR transparency screenshot                      (validity window)
    baec       Buyer Agency Agreement                            (expiry + scope)

Everything else (CPS, PDS, MLS sheet, deal sheet, remuneration disclosure,
title, deposit records, subject removal) is deal-level and NEVER lives here.

This module gives client docs an identity beyond ``deal_id`` so a collapsed or
closed deal no longer strands them. See
``knowledge/deals/client-doc-reuse-architecture.md``.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from elevate_cli.data._util import new_id, now_iso

# ---------------------------------------------------------------------------
# Taxonomy: which client-class doc_type (if any) a free-form attachment kind or
# document label maps to. The kind vocabulary in deal_attachments is free text
# assigned by whatever skill filed the doc, so match tolerantly on aliases.
# Anything that does not match is deal-level (returns None) -- fail closed.
# ---------------------------------------------------------------------------

# doc_type -> alias regex. Ordered; first match wins.
_CLIENT_DOC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dorts", re.compile(r"dorts|disclosure[_\s-]*of[_\s-]*representation|representation[_\s-]*in[_\s-]*trading", re.I)),
    ("pnc", re.compile(r"\bpnc\b|privacy[_\s-]*notice|privacy[_\s-]*(and|&)[_\s-]*consent", re.I)),
    ("fintrac_id", re.compile(r"fintrac(ker)?|individual[_\s-]*identification|individual[_\s-]*id\b", re.I)),
    ("lotr", re.compile(r"\blotr\b", re.I)),
    ("baec", re.compile(r"buyer[_\s-]*agency|\bbaec\b|exclusive[_\s-]*buyer", re.I)),
]

# Client docs whose validity is durable (no expiry) vs. carry a validity window.
_DURABLE_DOC_TYPES = frozenset({"dorts", "pnc"})
_WINDOWED_DOC_TYPES = frozenset({"fintrac_id", "lotr", "baec"})

CLIENT_DOC_TYPES = frozenset(_DURABLE_DOC_TYPES | _WINDOWED_DOC_TYPES)


def client_doc_type_for(*values: str | None) -> str | None:
    """Return the canonical client doc_type for any of the given labels
    (attachment kind, file name, doc-type string), or None if deal-level.

    Fail closed: only an explicit alias match returns a client doc_type.
    """
    for value in values:
        if not value:
            continue
        text = str(value)
        for doc_type, pattern in _CLIENT_DOC_PATTERNS:
            if pattern.search(text):
                return doc_type
    return None


def is_durable(doc_type: str) -> bool:
    return doc_type in _DURABLE_DOC_TYPES


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------

_COLUMNS = (
    "id", "contact_id", "doc_type", "file_path", "drive_file_id", "sha256",
    "signed_status", "signed_at", "valid_from", "valid_until", "scope_json",
    "fintrac_method", "fintrac_verified_at", "source_deal_id",
    "source_attachment_id", "status", "superseded_by", "verified_by",
    "summary", "created_at", "updated_at",
)


def _row_to_contact_document(row: Any) -> dict[str, Any]:
    d = {k: row[k] for k in _COLUMNS}
    return {
        "id": d["id"],
        "contactId": d["contact_id"],
        "docType": d["doc_type"],
        "filePath": d["file_path"],
        "driveFileId": d["drive_file_id"],
        "sha256": d["sha256"],
        "signedStatus": d["signed_status"],
        "signedAt": d["signed_at"],
        "validFrom": d["valid_from"],
        "validUntil": d["valid_until"],
        "scopeJson": d["scope_json"],
        "fintracMethod": d["fintrac_method"],
        "fintracVerifiedAt": d["fintrac_verified_at"],
        "sourceDealId": d["source_deal_id"],
        "sourceAttachmentId": d["source_attachment_id"],
        "status": d["status"],
        "supersededBy": d["superseded_by"],
        "verifiedBy": d["verified_by"],
        "summary": d["summary"],
        "createdAt": d["created_at"],
        "updatedAt": d["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_contact_documents(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM contact_documents WHERE contact_id=?"
    params: list[Any] = [contact_id]
    if not include_superseded:
        sql += " AND status != 'superseded'"
    sql += " ORDER BY doc_type, created_at DESC"
    return [_row_to_contact_document(r) for r in conn.execute(sql, params).fetchall()]


def list_contact_documents_for_contacts(
    conn: sqlite3.Connection,
    contact_ids: list[str],
    *,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cid in contact_ids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.extend(list_contact_documents(conn, cid, include_superseded=include_superseded))
    return out


def get_current_contact_document(
    conn: sqlite3.Connection, contact_id: str, doc_type: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM contact_documents WHERE contact_id=? AND doc_type=? AND status='valid'",
        (contact_id, doc_type),
    ).fetchone()
    return _row_to_contact_document(row) if row is not None else None


def upsert_contact_document(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    doc_type: str,
    file_path: str,
    signed_status: str = "unknown",
    sha256: str | None = None,
    drive_file_id: str | None = None,
    signed_at: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    scope_json: str | None = None,
    fintrac_method: str | None = None,
    fintrac_verified_at: str | None = None,
    source_deal_id: str | None = None,
    source_attachment_id: str | None = None,
    verified_by: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Insert a client document, superseding any existing current one of the
    same type for the same contact. Never deletes -- the old row becomes
    ``status='superseded'`` with ``superseded_by`` pointing at the new row.

    Idempotent on ``sha256``: re-filing the identical bytes for the same
    contact+type returns the existing current row unchanged.
    """
    if not contact_id or not contact_id.strip():
        raise ValueError("contact_id is required")
    if doc_type not in CLIENT_DOC_TYPES:
        raise ValueError(f"{doc_type!r} is not a client-level doc_type")
    if not file_path or not file_path.strip():
        raise ValueError("file_path is required")

    current = get_current_contact_document(conn, contact_id, doc_type)
    if current is not None and sha256 and current.get("sha256") == sha256:
        return current  # identical doc already current -- no-op

    now = now_iso()
    new_row_id = new_id()

    if current is not None:
        conn.execute(
            "UPDATE contact_documents SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
            (new_row_id, now, current["id"]),
        )

    conn.execute(
        """
        INSERT INTO contact_documents(
            id, contact_id, doc_type, file_path, drive_file_id, sha256,
            signed_status, signed_at, valid_from, valid_until, scope_json,
            fintrac_method, fintrac_verified_at, source_deal_id,
            source_attachment_id, status, superseded_by, verified_by,
            summary, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_row_id, contact_id, doc_type, file_path.strip(), drive_file_id, sha256,
            signed_status, signed_at, valid_from, valid_until, scope_json,
            fintrac_method, fintrac_verified_at, source_deal_id,
            source_attachment_id, "valid", None, verified_by,
            summary, now, now,
        ),
    )
    row = conn.execute("SELECT * FROM contact_documents WHERE id=?", (new_row_id,)).fetchone()
    return _row_to_contact_document(row)
