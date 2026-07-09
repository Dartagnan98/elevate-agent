"""C6 — no bundled skill may carry the premium/entitlement sidecar.

A ``.elevate-cloud-skill.json`` marks server-entitlement-gated Premium content
(e.g. the real_estate_admin pack). Such a skill must NEVER ship in the base
bundle: if it did, its "paid" gating would collapse to the locally-forgeable
license.json, so a user could edit that file to unlock it. This guard is the CI
belt for the 1.2.62 premium-leak fix so the leak cannot recur.
"""
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def test_no_bundled_skill_carries_premium_entitlement_sidecar():
    leaks = sorted(
        str(p.relative_to(SKILLS_DIR))
        for p in SKILLS_DIR.rglob(".elevate-cloud-skill.json")
    )
    assert leaks == [], (
        "bundled skills carry the premium/entitlement sidecar "
        "(.elevate-cloud-skill.json) — server-gated Premium content must not ship "
        "in the base bundle (its gating would collapse to the forgeable "
        "license.json): " + ", ".join(leaks)
    )
