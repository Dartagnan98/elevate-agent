"""Physical attachment truth at the agent-handoff dependency boundary."""

from __future__ import annotations

import pytest

from elevate_cli.data import add_deal_attachment, connect, create_deal
from elevate_cli.data.agent_handoffs import _dependency_blocks
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_deleted_attachment_blocks_handoff_dependency(tmp_path):
    import fitz

    artifact = tmp_path / "handoff-cma.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Verified CMA for handoff")
    document.save(artifact)
    document.close()

    with connect() as conn:
        deal = create_deal(
            conn,
            title="Physical handoff dependency",
            side="listing",
            province="BC",
            current_stage=1,
            dispatch_initial_stage=False,
            actor="human:test",
        )
        add_deal_attachment(
            conn,
            deal["id"],
            kind="cma_report",
            file_path=str(artifact),
            actor="human:test",
        )
        handoff = {
            "dealId": deal["id"],
            "payload": {
                "requires": [
                    {
                        "type": "attachment",
                        "kind": "cma_report",
                        "label": "Current CMA",
                    }
                ]
            },
        }
        assert _dependency_blocks(conn, handoff) == []

        artifact.unlink()
        assert _dependency_blocks(conn, handoff) == [
            {
                "type": "attachment",
                "kind": "cma_report",
                "label": "Current CMA",
            }
        ]
