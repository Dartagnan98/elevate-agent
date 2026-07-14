from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


CLI_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = CLI_ROOT / "scripts" / "validate_beta_gate_ownership.py"
SCHEMA_PATH = CLI_ROOT / "docs" / "beta-gate-ownership.schema.json"
UNASSIGNED_FIXTURE = Path(__file__).parent / "fixtures" / "beta-gate-ownership.unassigned.json"

SPEC = importlib.util.spec_from_file_location("validate_beta_gate_ownership", SCRIPT_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _artifact(repo_root: Path, content: bytes = b"retained beta evidence\n") -> dict[str, str]:
    path = repo_root / "evidence" / "gate.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return {
        "path": "evidence/gate.txt",
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _gate(*, status: str = "IN_PROGRESS", artifact: object = None) -> dict[str, object]:
    # Synthetic values are generated only inside unit tests; this is not a live
    # ownership assignment or due date.
    return {
        "gate_id": "ERB-107",
        "gate_class": "P0",
        "status": status,
        "accountable_person": "Fixture Person",
        "accountable_role": "program_owner",
        "due_date": "9999-12-31",
        "evidence_plan": "Retain the signed gate review and its exact digest.",
        "evidence_artifact": artifact,
    }


def _inventory(gate: dict[str, object]) -> dict[str, object]:
    return {"schema_version": 1, "gates": [gate]}


def test_checked_in_schema_matches_validator_contract():
    schema = validator.load_json(SCHEMA_PATH)
    assert validator.validate_contract_schema(schema) == []


def test_unassigned_fixture_is_truthful_and_fails_closed(tmp_path):
    inventory = validator.load_json(UNASSIGNED_FIXTURE)
    errors = validator.validate_inventory(inventory, repo_root=tmp_path)

    assert inventory["gates"][0]["accountable_person"] == "UNASSIGNED"
    assert any("is UNASSIGNED" in error for error in errors)
    assert any("must name exactly one person" in error for error in errors)
    assert any("due_date" in error for error in errors)


def test_assigned_non_pass_gate_requires_plan_but_not_finished_artifact(tmp_path):
    assert validator.validate_inventory(_inventory(_gate()), repo_root=tmp_path) == []


def test_pass_without_retained_evidence_is_blocked(tmp_path):
    errors = validator.validate_inventory(_inventory(_gate(status="PASS")), repo_root=tmp_path)
    assert errors == [
        "gates[0] (ERB-107) cannot PASS without a retained evidence artifact"
    ]


def test_pass_with_matching_retained_evidence_is_valid(tmp_path):
    gate = _gate(status="PASS", artifact=_artifact(tmp_path))
    assert validator.validate_inventory(_inventory(gate), repo_root=tmp_path) == []


def test_pass_with_tampered_evidence_is_blocked(tmp_path):
    artifact = _artifact(tmp_path)
    (tmp_path / artifact["path"]).write_text("tampered\n", encoding="utf-8")
    errors = validator.validate_inventory(
        _inventory(_gate(status="PASS", artifact=artifact)), repo_root=tmp_path
    )
    assert any("does not match retained bytes" in error for error in errors)


def test_noncanonical_role_and_multiple_people_are_rejected(tmp_path):
    gate = _gate()
    gate["accountable_person"] = "Fixture Person & Second Fixture Person"
    gate["accountable_role"] = "Engineering Team"
    errors = validator.validate_inventory(_inventory(gate), repo_root=tmp_path)
    assert any("exactly one person" in error for error in errors)
    assert any("accountable_role is not canonical" in error for error in errors)


def test_duplicate_gate_ids_are_rejected(tmp_path):
    inventory = {"schema_version": 1, "gates": [_gate(), _gate()]}
    errors = validator.validate_inventory(inventory, repo_root=tmp_path)
    assert any("gate_id is duplicated" in error for error in errors)


def test_evidence_must_be_repo_relative(tmp_path):
    external = tmp_path.parent / "external-beta-evidence.txt"
    external.write_text("evidence\n", encoding="utf-8")
    artifact = {
        "path": str(external),
        "sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
    }
    errors = validator.validate_inventory(
        _inventory(_gate(status="PASS", artifact=artifact)), repo_root=tmp_path
    )
    assert any("must not be absolute" in error for error in errors)


def test_cli_returns_nonzero_for_unassigned_fixture(capsys, tmp_path):
    result = validator.main(
        [str(UNASSIGNED_FIXTURE), "--schema", str(SCHEMA_PATH), "--repo-root", str(tmp_path)]
    )
    assert result == 1
    assert "beta gate ownership: FAIL" in capsys.readouterr().err


def test_cli_accepts_complete_assigned_gate(tmp_path, capsys):
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(_inventory(_gate(status="PASS", artifact=_artifact(tmp_path)))),
        encoding="utf-8",
    )
    result = validator.main(
        [str(inventory_path), "--schema", str(SCHEMA_PATH), "--repo-root", str(tmp_path)]
    )
    assert result == 0
    assert "beta gate ownership: VALID (1 gates)" in capsys.readouterr().out
