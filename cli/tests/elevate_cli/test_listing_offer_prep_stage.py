"""Guards for the listing tail after Offer Prep was inserted at stage 6.

The listing board's columns (cli/web/.../admin/admin-data.ts) are a separate
hand-written list from the backend stage pack, and a Lofty "Stage N" label is
no longer the same number as the internal stage index. Both are easy to drift
and neither fails loudly on its own, so pin them here.
"""

from __future__ import annotations

import re
from pathlib import Path

from elevate_cli.admin_deal_flow import BC_PACKAGE_KEY, _package_for_key
from elevate_cli.data.workflow_import import _parse_stage


LISTING_STAGES = [
    "Pre-CMA",
    "CMA / Evaluation",
    "Listing Intake",
    "SkySlope & Matrix Prep",
    "Marketing Go",
    "Listing Live / Marketing",
    "Offer Prep",
    "Accepted",
    "Condition Removal",
    "Subjects Off",
]

_WEB_ADMIN_DATA = (
    Path(__file__).resolve().parents[2]
    / "web/src/pages/real-estate-hub/admin/admin-data.ts"
)
_PIPELINE_RE = re.compile(
    r"export const ADMIN_PIPELINE: PipelinePhase\[\] = \[(.*?)\n\];", re.DOTALL
)
_COLUMN_RE = re.compile(r'stage:\s*"S(\d+)",\s*name:\s*"([^"]+)"')


def test_backend_listing_stages_are_in_board_order():
    stages = _package_for_key(BC_PACKAGE_KEY)["listing"]["stages"]
    assert [s["title"] for s in stages] == LISTING_STAGES


def test_board_columns_match_backend_listing_stages():
    body = _PIPELINE_RE.search(_WEB_ADMIN_DATA.read_text(encoding="utf-8"))
    assert body, "ADMIN_PIPELINE not found in admin-data.ts"
    columns = _COLUMN_RE.findall(body.group(1))
    assert [name for _, name in columns] == LISTING_STAGES
    # Column S<n> must be the nth backend stage, or a card lands in the wrong one.
    assert [int(n) for n, _ in columns] == list(range(len(LISTING_STAGES)))


def test_lofty_stage_labels_map_past_the_offer_boundary():
    # Below the boundary Lofty's number is still the internal index.
    assert _parse_stage("Stage 5 - Listing Live") == 5
    # From Lofty's accepted-offer stage on, internal is one higher.
    assert _parse_stage("Stage 6 - Accepted Offer") == 7
    assert _parse_stage("Stage 7 - Subject Removal Complete") == 8
    # Lofty runs past our last stage; those clamp to Subjects Off rather than
    # blowing the deals.current_stage CHECK (0-9).
    assert _parse_stage("Stage 8 - Closing") == 9
    assert _parse_stage("Stage 9 - Closed") == 9
    assert _parse_stage(None) == 0
