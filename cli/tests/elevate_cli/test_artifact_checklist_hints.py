"""Phase B / L1 — artifact -> checklist auto-tick (downgraded scope).

We only extend ``_ARTIFACT_CHECKLIST_HINTS`` (no broad tool-name hook). These
lock the new aliases and prove the existing run-completion auto-tick path still
ticks the mapped cell with no explicit checklist write.
"""
from elevate_cli.data import connect, create_deal
from elevate_cli.data.deals import _ARTIFACT_CHECKLIST_HINTS, get_deal, record_run_result
from elevate_cli.data.dispatch import queue_action_run


def _make_deal():
    with connect() as conn:
        return create_deal(
            conn, title="Artifact Deal", side="listing", current_stage=0, actor="human:test"
        )


def test_new_aliases_map_to_existing_sibling_cells():
    # Each new alias points at the SAME cell as an existing sibling (zero
    # wrong-cell risk: worst case is a no-op if the kind is never emitted).
    assert _ARTIFACT_CHECKLIST_HINTS["cma_pdf"] == "draft-cma-followup"
    assert _ARTIFACT_CHECKLIST_HINTS["title_report"] == "workflow_title_ordered"
    assert _ARTIFACT_CHECKLIST_HINTS["listing_agreement"] == "workflow_stage_2_complete"


def test_completed_run_with_mapped_artifact_ticks_cell():
    deal = _make_deal()
    with connect() as conn:
        run = queue_action_run(conn, deal_id=deal["id"], skill="cma-pdf", actor="system")
        # No explicit checklist_updates — the tick must come purely from the
        # artifact-kind hint (cma_pdf -> draft-cma-followup, not a protected
        # stage-complete cell, so a skill actor is allowed to set it).
        record_run_result(
            conn,
            deal["id"],
            run["id"],
            status="succeeded",
            artifacts=[{"kind": "cma_pdf", "file_path": "/tmp/cma.pdf", "summary": "CMA"}],
            actor="skill:cma-pdf",
        )
        toggles = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert toggles.get("draft-cma-followup") is True
