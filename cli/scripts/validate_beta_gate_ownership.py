#!/usr/bin/env python3
"""Fail-closed ownership validation for Elevate Beta control gates.

An assigned gate needs one named person, one canonical role, an ISO due date,
and a concrete evidence plan. A gate may only claim PASS when its evidence
artifact is a retained, non-empty repo-relative file with the declared SHA-256.

The schema permits an UNASSIGNED fixture so missing human decisions can be
represented truthfully. This validator still returns non-zero for that state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = REPO_ROOT / "cli" / "docs" / "beta-gate-ownership.schema.json"

CANONICAL_ROLES = frozenset(
    {
        "program_owner",
        "release_engineering",
        "harness_runtime",
        "provider_adapters",
        "safety_policy",
        "realtor_product",
        "onboarding",
        "province_pack",
        "document_factory",
        "web_desktop",
        "quality_engineering",
        "support_operations",
    }
)
GATE_CLASSES = frozenset({"P0", "P1", "INVITATION_UNKNOWN"})
GATE_STATUSES = frozenset(
    {"UNASSIGNED", "UNKNOWN", "OPEN", "IN_PROGRESS", "BLOCKED", "FAIL", "PASS"}
)
REQUIRED_GATE_FIELDS = frozenset(
    {
        "gate_id",
        "gate_class",
        "status",
        "accountable_person",
        "accountable_role",
        "due_date",
        "evidence_plan",
        "evidence_artifact",
    }
)
PLACEHOLDER_VALUES = frozenset(
    {"", "unassigned", "unknown", "tbd", "todo", "none", "n/a", "owner", "name"}
)
GATE_ID_PATTERN = re.compile(r"^ERB-[0-9]{3}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MULTI_PERSON_PATTERN = re.compile(r"(?:[;|]|\s(?:&|and|\+)\s)", re.IGNORECASE)


class DuplicateKeyError(ValueError):
    """Raised when JSON contains a duplicate object key."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def validate_contract_schema(schema: Any) -> list[str]:
    """Ensure the checked-in contract has not drifted from validator constants."""

    errors: list[str] = []
    try:
        gate_schema = schema["properties"]["gates"]["items"]
        schema_required = frozenset(gate_schema["required"])
        schema_roles = frozenset(
            role
            for role in gate_schema["properties"]["accountable_role"]["enum"]
            if role is not None
        )
        schema_classes = frozenset(gate_schema["properties"]["gate_class"]["enum"])
        schema_statuses = frozenset(gate_schema["properties"]["status"]["enum"])
    except (KeyError, TypeError) as exc:
        return [f"schema contract is incomplete: {exc}"]

    if schema_required != REQUIRED_GATE_FIELDS:
        errors.append("schema required gate fields do not match the validator")
    if schema_roles != CANONICAL_ROLES:
        errors.append("schema canonical roles do not match the validator")
    if schema_classes != GATE_CLASSES:
        errors.append("schema gate classes do not match the validator")
    if schema_statuses != GATE_STATUSES:
        errors.append("schema gate statuses do not match the validator")
    return errors


def _meaningful_text(value: Any, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, str)
        and len(value.strip()) >= minimum
        and value.strip().casefold() not in PLACEHOLDER_VALUES
    )


def _named_person(value: Any) -> bool:
    if not _meaningful_text(value, minimum=2):
        return False
    assert isinstance(value, str)
    stripped = value.strip()
    if MULTI_PERSON_PATTERN.search(stripped):
        return False
    if any(char.isdigit() for char in stripped):
        return False
    if not any(char.isalpha() for char in stripped):
        return False
    return stripped.casefold().replace(" ", "_") not in CANONICAL_ROLES


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_artifact(artifact: Any, *, repo_root: Path, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(artifact, dict):
        return [f"{label}.evidence_artifact must be an object"]
    if set(artifact) != {"path", "sha256"}:
        errors.append(f"{label}.evidence_artifact must contain only path and sha256")

    relative_path = artifact.get("path")
    declared_hash = artifact.get("sha256")
    if not _meaningful_text(relative_path):
        errors.append(f"{label}.evidence_artifact.path must be a repo-relative file")
        return errors
    assert isinstance(relative_path, str)
    if Path(relative_path).is_absolute():
        errors.append(f"{label}.evidence_artifact.path must not be absolute")
        return errors
    if not isinstance(declared_hash, str) or not SHA256_PATTERN.fullmatch(declared_hash):
        errors.append(f"{label}.evidence_artifact.sha256 must be 64 lowercase hex characters")
        return errors

    root = repo_root.resolve()
    unresolved = root / relative_path
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"{label}.evidence_artifact.path escapes the repository root")
        return errors
    if unresolved.is_symlink():
        errors.append(f"{label}.evidence_artifact.path must not be a symlink")
        return errors
    if not resolved.is_file():
        errors.append(f"{label}.evidence_artifact.path is not a retained file")
        return errors
    if resolved.stat().st_size == 0:
        errors.append(f"{label}.evidence_artifact.path is empty")
        return errors
    actual_hash = _sha256(resolved)
    if actual_hash != declared_hash:
        errors.append(f"{label}.evidence_artifact.sha256 does not match retained bytes")
    return errors


def validate_inventory(inventory: Any, *, repo_root: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(inventory, dict):
        return ["inventory must be a JSON object"]
    if set(inventory) != {"schema_version", "gates"}:
        errors.append("inventory must contain only schema_version and gates")
    if inventory.get("schema_version") != 1:
        errors.append("schema_version must equal 1")

    gates = inventory.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates must be a non-empty array")
        return errors

    seen_gate_ids: set[str] = set()
    for index, gate in enumerate(gates):
        label = f"gates[{index}]"
        if not isinstance(gate, dict):
            errors.append(f"{label} must be an object")
            continue
        gate_id = gate.get("gate_id")
        if isinstance(gate_id, str):
            label = f"{label} ({gate_id})"
        missing = REQUIRED_GATE_FIELDS - set(gate)
        extra = set(gate) - REQUIRED_GATE_FIELDS
        if missing:
            errors.append(f"{label} missing fields: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{label} has unknown fields: {', '.join(sorted(extra))}")

        if not isinstance(gate_id, str) or not GATE_ID_PATTERN.fullmatch(gate_id):
            errors.append(f"{label}.gate_id must match ERB-000")
        elif gate_id in seen_gate_ids:
            errors.append(f"{label}.gate_id is duplicated")
        else:
            seen_gate_ids.add(gate_id)

        gate_class = gate.get("gate_class")
        if gate_class not in GATE_CLASSES:
            errors.append(f"{label}.gate_class is not canonical")
        status = gate.get("status")
        if status not in GATE_STATUSES:
            errors.append(f"{label}.status is not canonical")

        if status == "UNASSIGNED":
            errors.append(f"{label} is UNASSIGNED")
        if not _named_person(gate.get("accountable_person")):
            errors.append(f"{label}.accountable_person must name exactly one person")
        if gate.get("accountable_role") not in CANONICAL_ROLES:
            errors.append(f"{label}.accountable_role is not canonical")
        if not _iso_date(gate.get("due_date")):
            errors.append(f"{label}.due_date must be an ISO date (YYYY-MM-DD)")
        if not _meaningful_text(gate.get("evidence_plan"), minimum=12):
            errors.append(f"{label}.evidence_plan must describe the retained proof")

        artifact = gate.get("evidence_artifact")
        if status == "PASS" and artifact is None:
            errors.append(f"{label} cannot PASS without a retained evidence artifact")
        elif artifact is not None:
            errors.extend(_validate_artifact(artifact, repo_root=repo_root, label=label))
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="Beta gate ownership JSON inventory")
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"contract schema (default: {DEFAULT_SCHEMA})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help=f"root containing retained evidence (default: {REPO_ROOT})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        schema = load_json(args.schema)
        inventory = load_json(args.inventory)
    except (OSError, json.JSONDecodeError, DuplicateKeyError) as exc:
        print(f"beta gate ownership: INVALID INPUT: {exc}", file=sys.stderr)
        return 2

    errors = validate_contract_schema(schema)
    errors.extend(validate_inventory(inventory, repo_root=args.repo_root))
    if errors:
        print("beta gate ownership: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"beta gate ownership: VALID ({len(inventory['gates'])} gates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
