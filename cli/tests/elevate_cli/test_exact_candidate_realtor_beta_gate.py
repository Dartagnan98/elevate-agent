from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "cli/scripts/exact_candidate_realtor_beta_gate.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "exact_candidate_realtor_beta_gate", SCRIPT_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _feed(version: str, prefix: str) -> bytes:
    files = []
    for arch in ("x64", "arm64"):
        for extension in ("zip", "dmg"):
            files.append(
                {
                    "url": f"{prefix}-{version}-mac-{arch}.{extension}",
                    "size": 1000 + len(files),
                    "sha512": f"sha512-{version}-{arch}-{extension}",
                }
            )
    return yaml.safe_dump(
        {
            "version": version,
            "files": files,
            "path": files[0]["url"],
            "sha512": files[0]["sha512"],
        },
        sort_keys=False,
    ).encode()


def _snapshot(channel: str, version: str, value: bytes) -> dict:
    metadata = yaml.safe_load(value)
    return {
        "channel": channel,
        "version": version,
        "status": 200,
        "url": f"https://updates.invalid/{channel}-mac.yml",
        "sha256": hashlib.sha256(value).hexdigest(),
        "files": metadata["files"],
    }


def _receipt() -> tuple[dict, bytes, bytes, bytes]:
    recovery_feed = _feed("1.2.98", "Elevate-Beta-Recovery")
    stable_feed = _feed("1.2.63", "Elevate")
    candidate_feed = _feed("1.2.97", "Elevate-Beta")
    stable = _snapshot("latest", "1.2.63", stable_feed)
    recovery_metadata = yaml.safe_load(recovery_feed)
    beta_profile = {
        "productName": "Elevate Beta",
        "appBundleName": "Elevate Beta.app",
        "appId": "com.elevationrealestate.elevate.beta",
        "packageName": "elevate-beta-desktop",
        "protocolScheme": "elevate-beta",
        "elevateHomeName": ".elevate-beta",
        "gatewayLabel": "ai.elevate.gateway-beta",
        "downloadAliasPrefixes": ["Elevate-Beta", "Elevate-beta"],
    }
    receipt = {
        "source_receipt_id": "a" * 64,
        "release": {
            "version": "1.2.97",
            "channel": "beta",
            "feed_name": "beta-mac.yml",
            "download_aliases": [
                "Elevate-Beta-mac-x64.dmg",
                "Elevate-beta-mac-x64.dmg",
                "Elevate-Beta-mac-arm64.dmg",
                "Elevate-beta-mac-arm64.dmg",
            ],
            "profile": beta_profile,
        },
        "recovery": {
            "schema_version": 1,
            "kind": "elevate-beta-recovery-package",
            "candidate_version": "1.2.97",
            "version": "1.2.98",
            "channel": "beta",
            "public_feed_name": "beta-mac.yml",
            "profile": beta_profile,
            "local_feed": {
                "path": "desktop/dist/recovery/beta-mac.yml",
                "size": len(recovery_feed),
                "sha256": hashlib.sha256(recovery_feed).hexdigest(),
            },
            "artifacts": {
                item["url"]: {
                    "size": item["size"],
                    "sha512": item["sha512"],
                    "sha256": hashlib.sha256(item["url"].encode()).hexdigest(),
                }
                for item in recovery_metadata["files"]
            },
            "static_provenance": {
                "runtime_policy": {
                    "backend": False,
                    "cli": False,
                    "gateway": False,
                    "runtime": False,
                    "tools": False,
                    "profile_preserved": True,
                }
            },
            "apps": {
                arch: {
                    "architecture": arch,
                    "trust": {
                        "signed": True,
                        "notarized": True,
                        "stapled": True,
                        "verification_method": "codesign-gatekeeper-stapled-ticket",
                    },
                }
                for arch in ("x64", "arm64")
            },
        },
        "public_feeds_at_finalize": {"latest": stable},
        "artifacts": {
            "beta-mac.yml": {
                "sha256": hashlib.sha256(candidate_feed).hexdigest()
            }
        },
    }
    return receipt, candidate_feed, recovery_feed, stable_feed


def test_local_recovery_drill_rolls_beta_forward_and_leaves_stable_and_data_untouched(
    tmp_path: Path,
):
    gate = _load_gate()
    receipt, candidate_feed, recovery_feed, stable_feed = _receipt()

    result = gate._recovery_roll_forward_dry_run(
        receipt=receipt,
        candidate_feed=candidate_feed,
        recovery_feed=recovery_feed,
        stable_feed=stable_feed,
        work_root=tmp_path,
    )

    assert result["candidate_version"] == "1.2.97"
    assert result["recovery_version"] == "1.2.98"
    assert result["beta_after_sha256"] == receipt["recovery"]["local_feed"]["sha256"]
    assert result["stable_before_sha256"] == result["stable_after_sha256"]
    assert result["stable_after_sha256"] == receipt["public_feeds_at_finalize"]["latest"]["sha256"]
    assert result["recovery_alias_count"] == 4
    assert result["recovery_artifact_count"] == 4
    assert result["runtime_actor_count"] == 0
    assert result["production_mutated"] is False
    assert result["profile_data_mutations"] == 0
    assert result["rpo_seconds"] == 0
    assert result["signed_app_count"] == 2
    assert result["notarized_app_count"] == 2
    assert result["stapled_app_count"] == 2

    # The trust counts are derived from the receipt's per-app trust records, not
    # hardcoded: dropping one app's attestation must lower every count so the
    # evidence can never over-claim.
    untrusted, untrusted_candidate, untrusted_recovery, untrusted_stable = _receipt()
    untrusted["recovery"]["apps"]["x64"]["trust"].update(
        {"signed": False, "notarized": False, "stapled": False}
    )
    downgraded = gate._recovery_roll_forward_dry_run(
        receipt=untrusted,
        candidate_feed=untrusted_candidate,
        recovery_feed=untrusted_recovery,
        stable_feed=untrusted_stable,
        work_root=tmp_path / "second",
    )
    assert downgraded["signed_app_count"] == 1
    assert downgraded["notarized_app_count"] == 1
    assert downgraded["stapled_app_count"] == 1


def test_later_beta_marks_version_pinned_recovery_contract_not_applicable():
    gate = _load_gate()
    receipt, _candidate_feed, _recovery_feed, _stable_feed = _receipt()
    receipt["release"]["version"] = "1.2.97"
    del receipt["recovery"]

    result = gate._recovery_not_applicable_result(receipt)
    check_ids = gate._required_check_ids(recovery_applicable=False)

    assert result == {
        "mode": "not-applicable",
        "candidate_version": "1.2.97",
        "source_receipt_id": "a" * 64,
        "reason": "candidate-has-no-recovery-contract",
        "remote_mutation": False,
        "production_mutated": False,
        "profile_data_mutations": 0,
    }
    assert gate.RECOVERY_NOT_APPLICABLE_CHECK_ID in check_ids
    assert not set(gate.RECOVERY_CHECK_IDS).intersection(check_ids)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("recovery", "recovery_feed_hash_mismatch"),
        ("stable", "stable_snapshot_hash_mismatch"),
        ("candidate", "candidate_beta_feed_hash_mismatch"),
    ],
)
def test_local_recovery_drill_fails_closed_on_any_feed_drift(
    tmp_path: Path, mutation: str, code: str
):
    gate = _load_gate()
    receipt, candidate_feed, recovery_feed, stable_feed = _receipt()
    values = {
        "candidate": candidate_feed,
        "recovery": recovery_feed,
        "stable": stable_feed,
    }
    values[mutation] += b"drift"

    with pytest.raises(gate.GateFailure, match=code):
        gate._recovery_roll_forward_dry_run(
            receipt=receipt,
            candidate_feed=values["candidate"],
            recovery_feed=values["recovery"],
            stable_feed=values["stable"],
            work_root=tmp_path,
        )


def test_local_recovery_drill_rejects_a_downgrade(tmp_path: Path):
    gate = _load_gate()
    receipt, candidate_feed, _recovery_feed, stable_feed = _receipt()
    downgrade_feed = _feed("1.2.72", "Elevate-Beta-Recovery")
    metadata = yaml.safe_load(downgrade_feed)
    receipt["recovery"]["version"] = "1.2.72"
    receipt["recovery"]["local_feed"]["size"] = len(downgrade_feed)
    receipt["recovery"]["local_feed"]["sha256"] = hashlib.sha256(downgrade_feed).hexdigest()
    receipt["recovery"]["artifacts"] = {
        item["url"]: {
            "size": item["size"],
            "sha512": item["sha512"],
            "sha256": hashlib.sha256(item["url"].encode()).hexdigest(),
        }
        for item in metadata["files"]
    }
    with pytest.raises(gate.GateFailure, match="recovery_not_roll_forward"):
        gate._recovery_roll_forward_dry_run(
            receipt=receipt,
            candidate_feed=candidate_feed,
            recovery_feed=downgrade_feed,
            stable_feed=stable_feed,
            work_root=tmp_path,
        )


def test_recovery_feed_receipt_path_rejects_escape_and_symlink(tmp_path: Path):
    gate = _load_gate()
    real = tmp_path / "desktop" / "dist" / "recovery" / "beta-mac.yml"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"recovery-feed")
    assert gate._repo_receipt_file(
        tmp_path, "desktop/dist/recovery/beta-mac.yml", "unsafe"
    ) == real
    with pytest.raises(gate.GateFailure, match="unsafe"):
        gate._repo_receipt_file(tmp_path, "../escape", "unsafe")
    with pytest.raises(gate.GateFailure, match="unsafe"):
        gate._repo_receipt_file(tmp_path, str(real.resolve()), "unsafe")
    link = tmp_path / "recovery-link.yml"
    link.symlink_to(real)
    with pytest.raises(gate.GateFailure, match="unsafe"):
        gate._repo_receipt_file(tmp_path, link.name, "unsafe")


def test_evidence_is_owner_only_immutable_and_content_free(tmp_path: Path):
    gate = _load_gate()
    path = tmp_path / "gate.json"
    gate._write_evidence(path, {"ok": True, "check_ids": list(gate.REQUIRED_CHECK_IDS)})

    document = json.loads(path.read_text())
    assert document["evidence_integrity_sha256"] == gate._evidence_integrity(document)
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        gate._write_evidence(path, {"ok": True})
    with pytest.raises(gate.GateFailure, match="unsafe_evidence_field"):
        gate._write_evidence(tmp_path / "unsafe.json", {"prompt": "must not persist"})


def test_installed_fault_child_contract_against_current_cli(tmp_path: Path):
    # This exercises the same isolated child contract used with an installed
    # app. The release run replaces this source CLI root with the
    # candidate-verified Contents/Resources/cli tree.
    short_root = Path("/tmp") / f"erb-test-{os.getpid()}-{tmp_path.name[-6:]}"
    short_root.mkdir(mode=0o700)
    home = short_root / "home"
    home.mkdir(mode=0o700)
    work = short_root / "work"
    env = {
        **os.environ,
        "HOME": str(home),
        "ELEVATE_HOME": str(home / ".elevate-beta"),
        "ELEVATE_RELEASE_CHANNEL": "beta",
        "ELEVATE_GATE_INSTALLED_CLI_ROOT": str((REPO_ROOT / "cli").resolve()),
        "ELEVATE_PG_CLEANUP": "delete",
        "PYTHONPATH": str((REPO_ROOT / "cli").resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(short_root / "pycache"),
    }
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-P",
                str(SCRIPT_PATH),
                "--child",
                "--cli-root",
                str(REPO_ROOT / "cli"),
                "--work-root",
                str(work),
            ],
            cwd=short_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    finally:
        import shutil

        shutil.rmtree(short_root, ignore_errors=True)

    assert completed.returncode == 0, completed.stderr
    line = next(
        item
        for item in completed.stdout.splitlines()
        if item.startswith("ELEVATE_REALTOR_BETA_GATE_RESULT=")
    )
    result = json.loads(line.split("=", 1)[1])
    assert result["tool_parity"] == {"request_count": 2, "receipt_count": 2}
    assert result["pack"]["form_count"] == 34
    assert result["action_faults"]["artifact_rejections"] == 2
    assert result["action_faults"]["worker_terminal_status"] == "failed"
    assert result["session_resume"]["session_id_preserved"] is True
