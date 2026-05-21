"""Sync province admin guides into searchable holographic memory.

The province guide corpus (reference pages, checklists) lives in
``operational.db``.  ``province_agent_memory`` injects compact excerpts into
the admin skill prompt, but the full text was never searchable on demand.

This module ingests that corpus into the holographic memory store so the
agent can ``document_search`` / recall it like any other source document.
It is idempotent — ``add_document_chunks`` upserts on ``source_uri`` — so a
repeat run refreshes content in place rather than duplicating it.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from elevate_cli.data.province_guides import (
    list_province_checklists,
    list_province_reference_pages,
)

_log = logging.getLogger(__name__)

# Shared source_type so the agent (and document_search filters) can scope
# recall to province guide material specifically.
SOURCE_TYPE = "province_guide"


def _open_store() -> Any:
    """Open the holographic memory store at its configured/default path."""
    from plugins.memory.holographic.store import MemoryStore

    return MemoryStore()


def sync_province_guide_to_memory(
    conn: sqlite3.Connection,
    province: str,
    *,
    store: Any | None = None,
) -> dict[str, Any]:
    """Ingest a province's admin guide into the holographic memory store.

    Reference pages and checklists become searchable source documents under
    ``source_type='province_guide'``.  Idempotent on ``source_uri``.

    Best-effort: callers should treat any raised exception as non-fatal and
    never let a memory-store failure break admin setup.
    """
    province = (province or "").strip().upper()
    if not province:
        return {"province": province, "documents": 0, "chunks": 0, "skipped": "no province"}

    pages = list_province_reference_pages(conn, province=province)
    checklists = list_province_checklists(conn, province=province)
    records: list[tuple[str, dict[str, Any]]] = [
        ("reference", row) for row in pages
    ] + [("checklist", row) for row in checklists]
    if not records:
        return {"province": province, "documents": 0, "chunks": 0, "skipped": "no guide rows"}

    own_store = store is None
    store = store or _open_store()
    documents = 0
    chunks = 0
    try:
        for kind, row in records:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            slug = str(row.get("slug") or "").strip()
            title = str(row.get("title") or slug or kind).strip()
            source_uri = f"elevate://province-guide/{province}/{kind}/{slug}"
            result = store.add_document_chunks(
                source_uri=source_uri,
                chunks=store.chunk_text(content),
                title=title,
                source_type=SOURCE_TYPE,
                metadata={
                    "province": province,
                    "kind": kind,
                    "slug": slug,
                    "sourcePath": row.get("sourcePath"),
                },
            )
            documents += 1
            chunks += int(result.get("chunks") or 0)
    finally:
        if own_store:
            close = getattr(store, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - close is best-effort
                    pass

    _log.info(
        "province guide %s synced to memory: %d documents, %d chunks",
        province,
        documents,
        chunks,
    )
    return {
        "province": province,
        "documents": documents,
        "chunks": chunks,
        "sourceType": SOURCE_TYPE,
    }
