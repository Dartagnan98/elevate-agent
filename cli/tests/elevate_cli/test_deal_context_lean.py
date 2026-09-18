"""The dashboard task board must not pull the province corpus per deal.

``list_deal_tasks`` runs for every active deal on every Today/Admin poll, so
it asks ``get_deal_context`` for a lean context. Skill-facing callers (the
``admin_deal`` tool, skill-run dispatch, the deal detail route) keep the full
context, province guides included.
"""

from __future__ import annotations

import pytest

from elevate_cli.data import (
    connect,
    create_deal,
    get_deal_context,
    list_deal_tasks,
    province_guides,
)
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _seed_province_page(conn, province: str = "BC") -> None:
    conn.execute(
        """
        INSERT INTO province_reference_pages(
            id, province, slug, page_type, title, source_url, source_path,
            content_md, content_hash, imported_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "page-1", province, "transaction-guide", "guide", "Transaction guide",
            None, "guides/bc.md", "# Guide\n\nlong body", "hash", "2026-01-01", "2026-01-01",
        ),
    )


def test_full_context_still_includes_province_guides():
    with connect() as conn:
        _seed_province_page(conn)
        deal = create_deal(
            conn, title="Full ctx", side="listing", province="BC",
            actor="human:test", dispatch_initial_stage=False,
        )
        ctx = get_deal_context(conn, deal["id"])

    assert ctx["provinceGuide"]["coverage"]["referencePages"] == 1
    assert ctx["agentGuideMemory"]
    assert "stages" in ctx["stageDocuments"]
    assert isinstance(ctx["events"], list) and ctx["events"]
    assert isinstance(ctx["coContacts"], list)


def test_lean_context_skips_guides_and_events_but_keeps_gate():
    with connect() as conn:
        _seed_province_page(conn)
        deal = create_deal(
            conn, title="Lean ctx", side="listing", province="BC",
            actor="human:test", dispatch_initial_stage=False,
        )
        full = get_deal_context(conn, deal["id"])
        lean = get_deal_context(
            conn, deal["id"], include_guides=False, include_events=False
        )

    assert lean["provinceGuide"] == {}
    assert lean["agentGuideMemory"] == {}
    assert lean["stageDocuments"] == {}
    assert lean["events"] == []
    assert lean["coContacts"] == []
    # The phase gate (what the task board renders) is identical either way.
    assert lean["dealFlow"] == full["dealFlow"]
    assert lean["conditionalDocs"] == full["conditionalDocs"]
    assert set(lean) == set(full)


def test_list_deal_tasks_never_reads_province_corpus(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("province corpus read from the task board")

    monkeypatch.setattr(province_guides, "province_guide_summary", _boom)
    monkeypatch.setattr(province_guides, "province_agent_memory", _boom)
    monkeypatch.setattr(province_guides, "province_stage_documents", _boom)

    with connect() as conn:
        _seed_province_page(conn)
        deal = create_deal(
            conn, title="Board deal", side="listing", province="BC",
            actor="human:test", dispatch_initial_stage=False,
        )
        tasks = list_deal_tasks(conn, status="open", limit=200)
        # The full path is unchanged: it still goes through the province readers.
        with pytest.raises(AssertionError, match="province corpus"):
            get_deal_context(conn, deal["id"])

    assert tasks, "gate work should still surface on the task board"
    assert all(task["dealId"] == deal["id"] for task in tasks)
