#!/usr/bin/env python3
"""Run the exact-installed Realtor Beta fault and rollback pre-publish gate.

The public entrypoint binds an already-installed ``Elevate Beta.app`` to its
immutable candidate receipt, then runs the bundled Python and bundled CLI in a
temporary HOME.  The installed app, the user's Beta profile, Stable, public
feeds, and remote hosts are never modified.

The rollback portion reads the pre-release public feed snapshots and performs
the mutation algorithm only inside a temporary local fixture.  It proves that
the Beta feed and Beta aliases can return to the receipt's rollback target
while Stable and an operational-data sentinel remain byte-for-byte unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_KIND = "elevate-realtor-beta-prepublish-gate"
TEST_PROFILE_NAME = "exact-installed-realtor-beta-prepublish-v1"
CHILD_RESULT_PREFIX = "ELEVATE_REALTOR_BETA_GATE_RESULT="
MAX_FEED_BYTES = 1024 * 1024
REQUIRED_CHECK_IDS = (
    "candidate_binding",
    "beta_profile_coexistence",
    "installed_runtime_import",
    "tool_request_receipt_parity",
    "bc_pack_baseline",
    "bc_pack_missing_fail_closed",
    "bc_pack_corrupt_fail_closed",
    "bc_pack_decoy_fail_closed",
    "bc_pack_stale_receipt_fail_closed",
    "forms_proof_missing_fail_closed",
    "forms_proof_fake_fail_closed",
    "artifact_missing_fail_closed",
    "artifact_wrong_kind_fail_closed",
    "worker_no_callback_retry_exhaustion",
    "session_restart_resume",
    "rollback_target_metadata",
    "rollback_local_rpo0",
    "stable_feed_untouched",
)
_SHA256_RE = __import__("re").compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN_EVIDENCE_KEYS = {
    "content",
    "messages",
    "password",
    "prompt",
    "raw",
    "reply",
    "secret",
    "text",
    "token",
    "transcript",
}


class GateFailure(RuntimeError):
    """A deterministic gate failure with a content-free code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_millis(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _evidence_integrity(evidence: Mapping[str, Any]) -> str:
    body = dict(evidence)
    body.pop("evidence_integrity_sha256", None)
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _assert_content_free(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_EVIDENCE_KEYS:
                raise GateFailure("unsafe_evidence_field")
            _assert_content_free(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_free(item)


def _write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    document = dict(evidence)
    document["evidence_integrity_sha256"] = _evidence_integrity(document)
    _assert_content_free(document)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    open_fd: int | None = fd
    try:
        os.fchmod(fd, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("short evidence write")
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
        open_fd = None
        os.link(temporary_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if open_fd is not None:
            os.close(open_fd)
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure(code) from exc
    if not isinstance(value, dict):
        raise GateFailure(code)
    return value


def _verify_candidate_binding(
    *, repo_root: Path, receipt_path: Path, installed_app: Path, architecture: str
) -> dict[str, str]:
    verifier = repo_root / "desktop/scripts/candidate-receipt.js"
    try:
        completed = subprocess.run(
            [
                "node",
                str(verifier),
                "verify-app",
                "--receipt",
                str(receipt_path.resolve()),
                "--app",
                str(installed_app.resolve()),
                "--arch",
                architecture,
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateFailure("candidate_binding_failed") from exc
    if completed.returncode != 0:
        raise GateFailure("candidate_binding_failed")
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise GateFailure("candidate_binding_invalid") from exc
    mapping = {
        "candidate_id": payload.get("candidate_id"),
        "source_receipt_id": payload.get("source_receipt_id"),
        "candidate_architecture": payload.get("candidate_architecture"),
        "candidate_receipt_sha256": payload.get("receipt_sha256"),
        "candidate_app_version": payload.get("app_version"),
        "candidate_app_bundle_manifest_sha256": payload.get(
            "app_bundle_manifest_sha256"
        ),
    }
    if any(not isinstance(item, str) or not item for item in mapping.values()):
        raise GateFailure("candidate_binding_incomplete")
    if mapping["candidate_architecture"] != architecture:
        raise GateFailure("candidate_architecture_mismatch")
    for key in (
        "candidate_id",
        "source_receipt_id",
        "candidate_receipt_sha256",
        "candidate_app_bundle_manifest_sha256",
    ):
        if not _SHA256_RE.fullmatch(mapping[key]):
            raise GateFailure("candidate_binding_invalid")
    return mapping  # type: ignore[return-value]


def _validate_beta_profile(
    *, receipt: Mapping[str, Any], installed_app: Path
) -> dict[str, Any]:
    release = receipt.get("release")
    if not isinstance(release, Mapping) or release.get("channel") != "beta":
        raise GateFailure("not_realtor_beta_candidate")
    profile = release.get("profile")
    if not isinstance(profile, Mapping):
        raise GateFailure("beta_profile_invalid")
    required = {
        "appBundleName": "Elevate Beta.app",
        "appId": "com.elevationrealestate.elevate.beta",
        "productName": "Elevate Beta",
        "protocolScheme": "elevate-beta",
        "elevateHomeName": ".elevate-beta",
        "gatewayLabel": "ai.elevate.gateway-beta",
        "channel": "beta",
    }
    if any(profile.get(key) != expected for key, expected in required.items()):
        raise GateFailure("beta_profile_invalid")
    try:
        preferred_port = int(profile.get("preferredPort") or 0)
    except (TypeError, ValueError) as exc:
        raise GateFailure("beta_profile_invalid") from exc
    stable_reserved = {
        "appBundleName": "Elevate.app",
        "appId": "com.elevationrealestate.elevate",
        "productName": "Elevate",
        "protocolScheme": "elevate",
        "elevateHomeName": ".elevate",
        "gatewayLabel": "ai.elevate.gateway",
        "preferredPort": 9119,
    }
    if preferred_port <= 0 or preferred_port == stable_reserved["preferredPort"]:
        raise GateFailure("beta_profile_collides_with_stable")
    for key, stable_value in stable_reserved.items():
        if key == "preferredPort":
            continue
        if profile.get(key) == stable_value:
            raise GateFailure("beta_profile_collides_with_stable")
    if installed_app.name != required["appBundleName"]:
        raise GateFailure("installed_beta_bundle_name_invalid")
    info_path = installed_app / "Contents/Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise GateFailure("installed_beta_plist_invalid") from exc
    if (
        info.get("CFBundleIdentifier") != required["appId"]
        or info.get("CFBundleName") != required["productName"]
        or info.get("CFBundleShortVersionString") != release.get("version")
    ):
        raise GateFailure("installed_beta_plist_invalid")
    schemes = {
        str(scheme)
        for item in info.get("CFBundleURLTypes") or []
        if isinstance(item, Mapping)
        for scheme in item.get("CFBundleURLSchemes") or []
    }
    if required["protocolScheme"] not in schemes or "elevate" in schemes:
        raise GateFailure("installed_beta_protocol_invalid")
    update_path = installed_app / "Contents/Resources/app-update.yml"
    try:
        update = yaml.safe_load(update_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GateFailure("installed_beta_updater_invalid") from exc
    if (
        not isinstance(update, Mapping)
        or update.get("channel") != "beta"
        or update.get("updaterCacheDirName") != "elevate-beta-desktop-updater"
    ):
        raise GateFailure("installed_beta_updater_invalid")
    return {
        "identities_distinct": True,
        "preferred_port": preferred_port,
        "production_feed_untouched": receipt.get("production_feed_untouched") is True,
    }


def _fetch_bounded(url: str, code: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "elevate-realtor-beta-rollback-gate/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = response.read(MAX_FEED_BYTES + 1)
    except Exception as exc:
        raise GateFailure(code) from exc
    if not value or len(value) > MAX_FEED_BYTES:
        raise GateFailure(code)
    return value


def _feed_bytes(path: Path | None, url: str, code: str) -> bytes:
    if path is None:
        return _fetch_bounded(url, code)
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise GateFailure(code) from exc
    if not value or len(value) > MAX_FEED_BYTES:
        raise GateFailure(code)
    return value


def _feed_metadata(value: bytes, code: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(value.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GateFailure(code) from exc
    if not isinstance(document, Mapping):
        raise GateFailure(code)
    files = document.get("files")
    if not isinstance(files, list):
        raise GateFailure(code)
    normalized: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, Mapping):
            raise GateFailure(code)
        url = str(item.get("url") or "")
        sha512 = str(item.get("sha512") or "")
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise GateFailure(code) from exc
        if not url or Path(url).name != url or not sha512 or size <= 0:
            raise GateFailure(code)
        normalized.append({"url": url, "sha512": sha512, "size": size})
    return {
        "version": str(document.get("version") or ""),
        "files": sorted(normalized, key=lambda item: item["url"]),
    }


def _rollback_dry_run(
    *,
    receipt: Mapping[str, Any],
    candidate_feed: bytes,
    rollback_beta_feed: bytes,
    stable_feed: bytes,
    work_root: Path,
) -> dict[str, Any]:
    release = receipt["release"]
    rollback = receipt.get("rollback_target")
    public = receipt.get("public_feeds_at_finalize")
    artifacts = receipt.get("artifacts")
    if not isinstance(rollback, Mapping) or not isinstance(public, Mapping):
        raise GateFailure("rollback_contract_missing")
    if not isinstance(artifacts, Mapping):
        raise GateFailure("rollback_contract_missing")
    beta_snapshot = public.get("beta")
    stable_snapshot = public.get("latest")
    if not isinstance(beta_snapshot, Mapping) or not isinstance(stable_snapshot, Mapping):
        raise GateFailure("rollback_contract_missing")
    target_version = str(rollback.get("version") or "")
    target_sha = str(rollback.get("sha256") or "")
    stable_sha = str(stable_snapshot.get("sha256") or "")
    feed_name = str(release.get("feed_name") or "")
    candidate_record = artifacts.get(feed_name)
    if (
        release.get("channel") != "beta"
        or feed_name != "beta-mac.yml"
        or not target_version
        or not _SHA256_RE.fullmatch(target_sha)
        or not _SHA256_RE.fullmatch(stable_sha)
        or not isinstance(candidate_record, Mapping)
    ):
        raise GateFailure("rollback_contract_invalid")
    if rollback != beta_snapshot:
        raise GateFailure("rollback_target_not_public_beta_snapshot")
    if _sha256_bytes(rollback_beta_feed) != target_sha:
        raise GateFailure("rollback_beta_snapshot_hash_mismatch")
    if _sha256_bytes(stable_feed) != stable_sha:
        raise GateFailure("stable_snapshot_hash_mismatch")
    candidate_sha = str(candidate_record.get("sha256") or "")
    if _sha256_bytes(candidate_feed) != candidate_sha:
        raise GateFailure("candidate_beta_feed_hash_mismatch")

    rollback_metadata = _feed_metadata(
        rollback_beta_feed, "rollback_beta_snapshot_invalid"
    )
    candidate_metadata = _feed_metadata(candidate_feed, "candidate_beta_feed_invalid")
    stable_metadata = _feed_metadata(stable_feed, "stable_snapshot_invalid")
    expected_files = sorted(
        [
            {
                "url": str(item.get("url") or ""),
                "sha512": str(item.get("sha512") or ""),
                "size": int(item.get("size") or 0),
            }
            for item in rollback.get("files") or []
            if isinstance(item, Mapping)
        ],
        key=lambda item: item["url"],
    )
    if (
        rollback_metadata["version"] != target_version
        or rollback_metadata["files"] != expected_files
        or candidate_metadata["version"] != str(release.get("version") or "")
        or not stable_metadata["version"]
    ):
        raise GateFailure("rollback_target_metadata_mismatch")

    aliases = list((release.get("profile") or {}).get("downloadAliasPrefixes") or [])
    download_aliases = list(release.get("download_aliases") or [])
    if (
        set(aliases) != {"Elevate-Beta", "Elevate-beta"}
        or len(download_aliases) != 4
        or any(not str(name).startswith(tuple(f"{prefix}-" for prefix in aliases)) for name in download_aliases)
    ):
        raise GateFailure("beta_alias_contract_invalid")
    rollback_dmgs = {
        arch: next(
            (
                item
                for item in expected_files
                if item["url"].endswith(f"-mac-{arch}.dmg")
            ),
            None,
        )
        for arch in ("x64", "arm64")
    }
    if any(item is None for item in rollback_dmgs.values()):
        raise GateFailure("rollback_dmg_contract_missing")

    remote = work_root / "local-remote-fixture"
    stage = remote / ".rollback-stage"
    remote.mkdir(parents=True, exist_ok=False)
    stage.mkdir(mode=0o700)
    stable_path = remote / "latest-mac.yml"
    beta_path = remote / "beta-mac.yml"
    data_path = remote / "operational-data.snapshot"
    stable_alias_paths = [
        remote / "Elevate-latest-mac-x64.dmg",
        remote / "Elevate-latest-mac-arm64.dmg",
    ]
    beta_alias_root = remote / "beta-aliases-by-logical-name"
    beta_alias_root.mkdir()

    def alias_fixture_path(root: Path, logical_name: Any) -> Path:
        # The production host is case-sensitive Linux, while the local drill
        # runs on default case-insensitive macOS. Encode the logical alias so
        # Elevate-Beta-* and Elevate-beta-* remain four independent fixtures.
        digest = hashlib.sha256(str(logical_name).encode("utf-8")).hexdigest()[:24]
        return root / f"alias-{digest}.dmg"

    stable_path.write_bytes(stable_feed)
    beta_path.write_bytes(candidate_feed)
    data_path.write_bytes(b"realtor-beta-operational-data-sentinel-v1\n")
    for index, path in enumerate(stable_alias_paths):
        path.write_bytes(f"stable-alias-{index}\n".encode("ascii"))

    rollback_sources: dict[str, Path] = {}
    for arch, metadata in rollback_dmgs.items():
        assert metadata is not None
        source = remote / str(metadata["url"])
        # Synthetic bytes exercise the exact copy/replace algorithm locally;
        # the real metadata remains bound to the public feed and receipt.
        source.write_bytes(
            f"rollback-fixture:{arch}:{metadata['size']}:{metadata['sha512']}\n".encode(
                "utf-8"
            )
        )
        rollback_sources[arch] = source

    stable_before = _sha256_file(stable_path)
    stable_alias_before = [_sha256_file(path) for path in stable_alias_paths]
    data_before = _sha256_file(data_path)
    (stage / "beta-mac.yml").write_bytes(rollback_beta_feed)
    for alias in download_aliases:
        arch = "arm64" if "-arm64." in str(alias) else "x64"
        shutil.copyfile(rollback_sources[arch], alias_fixture_path(stage, alias))
    if _sha256_file(stage / "beta-mac.yml") != target_sha:
        raise GateFailure("rollback_stage_feed_hash_mismatch")
    for alias in download_aliases:
        arch = "arm64" if "-arm64." in str(alias) else "x64"
        if _sha256_file(alias_fixture_path(stage, alias)) != _sha256_file(rollback_sources[arch]):
            raise GateFailure("rollback_stage_alias_hash_mismatch")

    for alias in download_aliases:
        os.replace(
            alias_fixture_path(stage, alias),
            alias_fixture_path(beta_alias_root, alias),
        )
    os.replace(stage / "beta-mac.yml", beta_path)
    stage.rmdir()

    stable_after = _sha256_file(stable_path)
    stable_alias_after = [_sha256_file(path) for path in stable_alias_paths]
    data_after = _sha256_file(data_path)
    if (
        _sha256_file(beta_path) != target_sha
        or stable_after != stable_before
        or stable_alias_after != stable_alias_before
        or data_after != data_before
    ):
        raise GateFailure("rollback_local_fixture_failed")
    for alias in download_aliases:
        arch = "arm64" if "-arm64." in str(alias) else "x64"
        if _sha256_file(alias_fixture_path(beta_alias_root, alias)) != _sha256_file(rollback_sources[arch]):
            raise GateFailure("rollback_local_alias_restore_failed")

    return {
        "mode": "local-fixture-dry-run",
        "target_version": target_version,
        "target_feed_sha256": target_sha,
        "candidate_feed_sha256": candidate_sha,
        "beta_after_sha256": _sha256_file(beta_path),
        "stable_before_sha256": stable_before,
        "stable_after_sha256": stable_after,
        "stable_expected_sha256": stable_sha,
        "stable_alias_count": len(stable_alias_paths),
        "beta_alias_count": len(download_aliases),
        "rollback_dmg_count": len(rollback_dmgs),
        "artifact_bytes_mode": "synthetic-local-fixture",
        "remote_mutation": False,
        "production_mutated": False,
        "profile_data_mutations": 0,
        "rpo_seconds": 0,
        "procedure_id": "realtor-beta-feed-and-alias-rollback-v1",
    }


_PACK_SCHEMA = """
CREATE TABLE province_reference_pages (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, slug TEXT NOT NULL, page_type TEXT NOT NULL,
 title TEXT NOT NULL, source_url TEXT, source_path TEXT NOT NULL, content_md TEXT NOT NULL,
 content_hash TEXT NOT NULL, imported_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(province, slug)
);
CREATE TABLE province_checklists (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
 source_url TEXT, source_path TEXT NOT NULL, content_md TEXT NOT NULL, content_hash TEXT NOT NULL,
 imported_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(province, slug)
);
CREATE TABLE province_forms (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
 category TEXT, description TEXT, page_count INTEGER, annotation_count INTEGER,
 image_urls_json TEXT, local_image_paths_json TEXT, source_path TEXT,
 imported_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(province, code)
);
CREATE TABLE conditional_docs (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, field_key TEXT NOT NULL, field_value TEXT NOT NULL,
 doc_code TEXT NOT NULL, doc_name TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL,
 side TEXT, stage INTEGER, UNIQUE(province, field_key, field_value, doc_code)
);
CREATE TABLE memory_documents (
 document_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
 source_uri TEXT UNIQUE NOT NULL, title TEXT, metadata_json TEXT
);
CREATE TABLE memory_chunks (
 chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
 chunk_index INTEGER NOT NULL, content TEXT NOT NULL
);
"""


class _FixtureMemoryStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def chunk_text(value: str) -> list[str]:
        return [value]

    def add_document_chunks(
        self, *, source_uri: str, chunks: list[str], title: str, source_type: str, metadata: Mapping[str, Any]
    ) -> dict[str, int]:
        self.conn.execute(
            "INSERT INTO memory_documents(source_type, source_uri, title, metadata_json) VALUES (?,?,?,?) "
            "ON CONFLICT(source_uri) DO UPDATE SET source_type=excluded.source_type, title=excluded.title, metadata_json=excluded.metadata_json",
            (source_type, source_uri, title, json.dumps(metadata, sort_keys=True)),
        )
        row = self.conn.execute(
            "SELECT document_id FROM memory_documents WHERE source_uri=?", (source_uri,)
        ).fetchone()
        document_id = int(row["document_id"])
        self.conn.execute("DELETE FROM memory_chunks WHERE document_id=?", (document_id,))
        for index, chunk in enumerate(chunks):
            self.conn.execute(
                "INSERT INTO memory_chunks(document_id, chunk_index, content) VALUES (?,?,?)",
                (document_id, index, chunk),
            )
        self.conn.commit()
        return {"document_id": document_id, "chunks": len(chunks)}

    def document_status(self, *, source_type: str | None = None, limit: int = 200) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT d.*, COUNT(c.chunk_id) AS chunks FROM memory_documents d "
            "LEFT JOIN memory_chunks c ON c.document_id=d.document_id "
            "WHERE (? IS NULL OR d.source_type=?) GROUP BY d.document_id ORDER BY d.document_id LIMIT ?",
            (source_type, source_type, limit),
        ).fetchall()
        return {
            "documents": [
                {**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")}
                for row in rows
            ]
        }

    def delete_document(self, *, source_uri: str) -> None:
        row = self.conn.execute(
            "SELECT document_id FROM memory_documents WHERE source_uri=?", (source_uri,)
        ).fetchone()
        if row:
            self.conn.execute(
                "DELETE FROM memory_chunks WHERE document_id=?", (row["document_id"],)
            )
            self.conn.execute(
                "DELETE FROM memory_documents WHERE document_id=?", (row["document_id"],)
            )
            self.conn.commit()

    def document_search(
        self, query: str, *, source_type: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        terms = query.lower().split()
        rows = self.conn.execute(
            "SELECT d.source_uri, d.source_type, c.content FROM memory_chunks c "
            "JOIN memory_documents d ON d.document_id=c.document_id "
            "WHERE (? IS NULL OR d.source_type=?) ORDER BY d.source_uri LIMIT ?",
            (source_type, source_type, limit),
        ).fetchall()
        return [
            dict(row)
            for row in rows
            if all(term in str(row["content"]).lower() for term in terms)
        ]


def _expect_pack_failure(loader: Any, root: Path, code: str) -> None:
    try:
        loader(root=root)
    except Exception:
        return
    raise GateFailure(code)


def _run_pack_faults(work_root: Path) -> dict[str, Any]:
    from elevate_cli.data.beta_province_pack import (
        PACK_FORM_COUNT,
        activate_exact_beta_bc_pack,
        default_exact_beta_bc_pack_root,
        exact_beta_bc_pack_readiness,
        exact_beta_bc_pack_receipt_path,
        load_exact_beta_bc_pack,
    )

    baseline = load_exact_beta_bc_pack()
    if len(baseline.forms) != PACK_FORM_COUNT or PACK_FORM_COUNT != 34:
        raise GateFailure("bc_pack_baseline_invalid")
    source = default_exact_beta_bc_pack_root()
    cases = work_root / "pack-faults"
    cases.mkdir()
    missing = cases / "missing"
    corrupt = cases / "corrupt"
    decoy = cases / "decoy"
    shutil.copytree(source, missing)
    shutil.copytree(source, corrupt)
    shutil.copytree(source, decoy)
    (missing / "guide.md").unlink()
    with (corrupt / "forms.json").open("ab") as handle:
        handle.write(b"\n")
    (decoy / "current-form.pdf").write_bytes(b"decoy")
    _expect_pack_failure(load_exact_beta_bc_pack, missing, "bc_pack_missing_accepted")
    _expect_pack_failure(load_exact_beta_bc_pack, corrupt, "bc_pack_corrupt_accepted")
    _expect_pack_failure(load_exact_beta_bc_pack, decoy, "bc_pack_decoy_accepted")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_PACK_SCHEMA)
    store = _FixtureMemoryStore(conn)
    activated = activate_exact_beta_bc_pack(conn, store=store)
    if activated.get("ready") is not True:
        raise GateFailure("bc_pack_activation_failed")
    receipt_path = exact_beta_bc_pack_receipt_path()
    stale_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    stale_receipt["packSha256"] = "0" * 64
    receipt_path.write_text(
        json.dumps(stale_receipt, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(receipt_path, 0o600)
    readiness = exact_beta_bc_pack_readiness(conn, store=store)
    if readiness.get("ready") is not False or "stale" not in str(
        readiness.get("reason") or ""
    ):
        raise GateFailure("bc_pack_stale_receipt_accepted")
    conn.close()
    return {"pack_sha256": baseline.sha256, "form_count": PACK_FORM_COUNT}


def _run_tool_parity() -> dict[str, int]:
    from run_agent import AIAgent

    call_ids = ("gate-call-1", "gate-call-2")
    rows = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {"name": "read_file", "arguments": "{}"},
                }
                for call_id in call_ids
            ],
        },
        {"role": "tool", "tool_call_id": call_ids[0], "content": "fixture"},
        {"role": "tool", "tool_call_id": "orphan-call", "content": "fixture"},
    ]
    sanitized = AIAgent._sanitize_api_messages(rows)
    receipts = [
        str(item.get("tool_call_id") or "")
        for item in sanitized
        if item.get("role") == "tool"
    ]
    if len(receipts) != len(set(receipts)) or set(receipts) != set(call_ids):
        raise GateFailure("tool_request_receipt_parity_failed")
    return {"request_count": len(call_ids), "receipt_count": len(receipts)}


def _run_forms_and_action_faults() -> dict[str, Any]:
    from elevate_cli.data.admin_setup import forms_provider_capability, get_admin_setup
    from elevate_cli.data import (
        create_action,
        evaluate_dispatch,
        queue_action_run,
    )
    from elevate_cli.data.connection import connect
    from elevate_cli.data.deals import (
        create_deal,
        get_deal,
        list_deal_attachments,
        record_run_result,
    )
    from elevate_cli.data import dispatch as dispatch_data

    record_action_run_worker_exit = dispatch_data.record_action_run_worker_exit

    original_wake = dispatch_data._request_agent_worker_wake
    dispatch_data._request_agent_worker_wake = lambda **_kwargs: None
    try:
        with connect() as conn:
            get_admin_setup(conn)
            missing = forms_provider_capability(conn)
            if missing.get("available") is not False:
                raise GateFailure("missing_forms_proof_accepted")
            forged = {
                "provider": "WEBForms",
                "verification": {
                    "checkedAt": "2099-01-01T00:00:00Z",
                    "verifiedBy": "operator_fixture",
                    "signals": ["claimed"],
                    "details": {
                        "receiptSchema": "forged",
                        "providerProof": True,
                        "providerIdentity": "webforms",
                    },
                },
            }
            conn.execute(
                "UPDATE admin_setup_items SET status='configured', provider=?, value_json=? WHERE key='forms_provider'",
                ("WEBForms", json.dumps(forged)),
            )
            fake = forms_provider_capability(conn)
            if fake.get("available") is not False:
                raise GateFailure("fake_forms_proof_accepted")

            deal = create_deal(
                conn,
                title="Gate artifact deal",
                side="listing",
                actor="gate",
                province="BC",
                current_stage=1,
                dispatch_initial_stage=False,
            )
            action = create_action(
                conn,
                name="Gate CMA artifact contract",
                trigger="manual",
                skill="cma",
                side="listing",
                skill_args={"requiredArtifactKinds": ["cma_report"]},
            )
            runs = evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="manual",
                actor="gate",
                create_cron_jobs=False,
            )
            run = next(item for item in runs if item["registryId"] == action["id"])
            try:
                record_run_result(
                    conn,
                    deal["id"],
                    run["id"],
                    status="succeeded",
                    idempotency_key="gate-missing-artifact",
                    artifacts=[],
                    actor="gate",
                )
            except ValueError:
                pass
            else:
                raise GateFailure("missing_required_artifact_accepted")
            try:
                record_run_result(
                    conn,
                    deal["id"],
                    run["id"],
                    status="succeeded",
                    idempotency_key="gate-wrong-artifact",
                    artifacts=[
                        {"kind": "supporting_document", "filePath": "/missing/gate.pdf"}
                    ],
                    actor="gate",
                )
            except ValueError:
                pass
            else:
                raise GateFailure("wrong_required_artifact_accepted")
            row = conn.execute(
                "SELECT status, result_json FROM admin_action_runs WHERE id=?", (run["id"],)
            ).fetchone()
            if (
                row["status"] in {"succeeded", "completed"}
                or row["result_json"] is not None
                or get_deal(conn, deal["id"])["currentStage"] != 1
                or list_deal_attachments(conn, deal["id"])
            ):
                raise GateFailure("artifact_failure_mutated_deal")

            worker_run = queue_action_run(
                conn,
                deal_id=deal["id"],
                skill="real-estate-admin/buyer-cps",
                name="Gate missing callback",
                create_cron_job=False,
                actor="gate",
            )
            conn.execute(
                "UPDATE admin_action_runs SET status='running', cron_job_id='gate-cron-1' WHERE id=?",
                (worker_run["id"],),
            )
            retried = record_action_run_worker_exit(
                conn,
                worker_run["id"],
                cron_job_id="gate-cron-1",
                success=True,
                actor="gate",
                max_retries=1,
            )
            if (
                retried["status"] != "queued"
                or retried["payload"]["recovery"]["event"]
                != "worker_exit_without_callback_requeued"
            ):
                raise GateFailure("worker_callback_retry_not_queued")
            conn.execute(
                "UPDATE admin_action_runs SET status='running', cron_job_id='gate-cron-2' WHERE id=?",
                (worker_run["id"],),
            )
            failed = record_action_run_worker_exit(
                conn,
                worker_run["id"],
                cron_job_id="gate-cron-2",
                success=False,
                error="gate worker fixture",
                actor="gate",
                max_retries=1,
            )
            if (
                failed["status"] != "failed"
                or failed["payload"]["recovery"]["event"]
                != "worker_exit_without_callback_failed"
                or failed["payload"]["recovery"]["attempts"] != 1
            ):
                raise GateFailure("worker_callback_retry_not_exhausted")
    finally:
        dispatch_data._request_agent_worker_wake = original_wake

    return {
        "forms_missing_available": False,
        "forms_fake_available": False,
        "artifact_rejections": 2,
        "worker_retry_count": 1,
        "worker_terminal_status": "failed",
    }


def _run_session_restart_resume(work_root: Path) -> dict[str, Any]:
    from gateway.config import GatewayConfig, Platform
    from gateway.session import SessionSource, SessionStore

    sessions = work_root / "gateway-sessions"
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="realtor-beta-gate",
        user_id="gate",
    )
    first_store = SessionStore(sessions_dir=sessions, config=GatewayConfig())
    first = first_store.get_or_create_session(source)
    first_store.append_to_transcript(
        first.session_id,
        {"role": "user", "content": "fixture", "client_message_id": "gate-user"},
    )
    if not first_store.mark_resume_pending(first.session_key, reason="restart_timeout"):
        raise GateFailure("session_resume_pending_not_marked")
    if first_store._db is not None:
        first_store._db.close()
    second_store = SessionStore(sessions_dir=sessions, config=GatewayConfig())
    resumed = second_store.get_or_create_session(source)
    transcript = second_store.load_transcript(resumed.session_id)
    if (
        resumed.session_id != first.session_id
        or resumed.resume_pending is not True
        or len(transcript) != 1
        or not second_store.clear_resume_pending(resumed.session_key)
    ):
        raise GateFailure("session_restart_resume_failed")
    if second_store._db is not None:
        second_store._db.close()
    return {
        "session_id_preserved": True,
        "message_count": len(transcript),
        "resume_pending_cleared": True,
    }


def _installed_module_proof(cli_root: Path) -> dict[str, Any]:
    import elevate_state
    import run_agent
    from elevate_cli.data import admin_setup, beta_province_pack, deals, dispatch
    from gateway import session

    modules = (
        elevate_state,
        run_agent,
        admin_setup,
        beta_province_pack,
        deals,
        dispatch,
        session,
    )
    resolved_root = cli_root.resolve()
    for module in modules:
        path = Path(str(module.__file__ or "")).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise GateFailure("source_module_leaked_into_installed_gate") from exc
    return {
        "module_count": len(modules),
        "python_major": sys.version_info.major,
        "python_minor": sys.version_info.minor,
    }


def _child_main(args: argparse.Namespace) -> int:
    cli_root = args.cli_root.resolve()
    expected = Path(os.environ.get("ELEVATE_GATE_INSTALLED_CLI_ROOT", "")).resolve()
    if expected != cli_root:
        raise GateFailure("installed_cli_root_mismatch")
    if os.environ.get("ELEVATE_RELEASE_CHANNEL") != "beta":
        raise GateFailure("child_not_exact_beta")
    result: dict[str, Any] = {
        "installed_runtime": _installed_module_proof(cli_root),
        "tool_parity": _run_tool_parity(),
        "pack": _run_pack_faults(args.work_root),
        "action_faults": _run_forms_and_action_faults(),
        "session_resume": _run_session_restart_resume(args.work_root),
    }
    try:
        from elevate_cli.data import connection

        connection._reset_schema_cache()
    except Exception:
        pass
    print(CHILD_RESULT_PREFIX + _canonical_json(result))
    return 0


def _run_installed_child(
    *, installed_app: Path, work_root: Path, timeout: float
) -> dict[str, Any]:
    resources = installed_app / "Contents/Resources"
    cli_root = resources / "cli"
    python = resources / "runtime/python/bin/python3"
    if not cli_root.is_dir() or not python.is_file():
        raise GateFailure("installed_runtime_missing")
    child_home = work_root / "isolated-home"
    elevate_home = child_home / ".elevate-beta"
    child_home.mkdir(mode=0o700)
    elevate_home.mkdir(mode=0o700)
    env = {
        **os.environ,
        "HOME": str(child_home),
        "ELEVATE_HOME": str(elevate_home),
        "ELEVATE_RELEASE_CHANNEL": "beta",
        "ELEVATE_GATE_INSTALLED_CLI_ROOT": str(cli_root.resolve()),
        "ELEVATE_PG_CLEANUP": "delete",
        "PYTHONPATH": str(cli_root.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(work_root / "python-pycache"),
    }
    try:
        completed = subprocess.run(
            [
                str(python),
                "-B",
                "-P",
                str(Path(__file__).resolve()),
                "--child",
                "--cli-root",
                str(cli_root),
                "--work-root",
                str(work_root / "child-work"),
            ],
            cwd=work_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateFailure("installed_fault_child_failed") from exc
    if completed.returncode != 0:
        raise GateFailure("installed_fault_child_failed")
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(CHILD_RESULT_PREFIX):
            try:
                value = json.loads(line.removeprefix(CHILD_RESULT_PREFIX))
            except json.JSONDecodeError as exc:
                raise GateFailure("installed_fault_child_invalid") from exc
            if not isinstance(value, dict):
                raise GateFailure("installed_fault_child_invalid")
            return value
    raise GateFailure("installed_fault_child_missing_result")


def _main_gate(args: argparse.Namespace) -> int:
    started_at = _utc_now()
    started_clock = time.monotonic()
    repo_root = args.repo_root.resolve()
    receipt_path = args.candidate_receipt.resolve()
    installed_app = args.installed_app.resolve()
    receipt = _read_json(receipt_path, "candidate_receipt_unreadable")
    binding = _verify_candidate_binding(
        repo_root=repo_root,
        receipt_path=receipt_path,
        installed_app=installed_app,
        architecture=args.candidate_architecture,
    )
    profile = _validate_beta_profile(receipt=receipt, installed_app=installed_app)
    if profile["production_feed_untouched"] is not True:
        raise GateFailure("candidate_did_not_preserve_stable_feed")
    # Embedded Postgres uses a Unix socket beneath ELEVATE_HOME and rejects
    # macOS's very long /var/folders tempfile paths. /tmp is private here
    # because TemporaryDirectory creates a mode-0700 directory.
    with tempfile.TemporaryDirectory(prefix="erb-gate-", dir="/tmp") as name:
        work_root = Path(name)
        child = _run_installed_child(
            installed_app=installed_app,
            work_root=work_root,
            timeout=args.timeout,
        )
        release = receipt.get("release") or {}
        public = receipt.get("public_feeds_at_finalize") or {}
        rollback = receipt.get("rollback_target") or {}
        rollback_beta_feed = _feed_bytes(
            args.rollback_beta_feed,
            str(rollback.get("url") or ""),
            "rollback_beta_snapshot_unreachable",
        )
        stable_feed = _feed_bytes(
            args.stable_feed,
            str((public.get("latest") or {}).get("url") or ""),
            "stable_snapshot_unreachable",
        )
        candidate_feed_path = args.candidate_feed or (
            receipt_path.parent / str(release.get("feed_name") or "beta-mac.yml")
        )
        try:
            candidate_feed = candidate_feed_path.read_bytes()
        except OSError as exc:
            raise GateFailure("candidate_beta_feed_unreadable") from exc
        rollback_result = _rollback_dry_run(
            receipt=receipt,
            candidate_feed=candidate_feed,
            rollback_beta_feed=rollback_beta_feed,
            stable_feed=stable_feed,
            work_root=work_root,
        )

    completed_at = _utc_now()
    evidence: dict[str, Any] = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "ok": True,
        "failures": [],
        "check_ids": list(REQUIRED_CHECK_IDS),
        **binding,
        "release_channel": "beta",
        "release_app_bundle_name": "Elevate Beta.app",
        "installed_app_name": installed_app.name,
        "started_at": _iso_millis(started_at),
        "completed_at": _iso_millis(completed_at),
        "duration_ms": round((time.monotonic() - started_clock) * 1000),
        "test_profile": {
            "name": TEST_PROFILE_NAME,
            "isolated_home": True,
            "installed_profile_mutation": False,
            "remote_mutation": False,
            "public_feed_mutation": False,
        },
        "profile": profile,
        "installed_runtime": child["installed_runtime"],
        "tool_parity": child["tool_parity"],
        "pack": child["pack"],
        "action_faults": child["action_faults"],
        "session_resume": child["session_resume"],
        "rollback": rollback_result,
    }
    _write_evidence(args.json_out, evidence)
    print(
        f"Realtor Beta pre-publish gate passed for {binding['candidate_id'][:12]} "
        f"({len(REQUIRED_CHECK_IDS)} checks; rollback {rollback_result['target_version']}; Stable untouched)."
    )
    return 0


def _positive_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return parsed


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-receipt", type=Path)
    parser.add_argument("--installed-app", type=Path)
    parser.add_argument("--candidate-architecture", choices=("x64", "arm64"))
    parser.add_argument("--candidate-feed", type=Path)
    parser.add_argument("--rollback-beta-feed", type=Path)
    parser.add_argument("--stable-feed", type=Path)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--timeout", type=_positive_timeout, default=600.0)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cli-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--work-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        if args.cli_root is None or args.work_root is None:
            parser.error("--child requires --cli-root and --work-root")
        args.work_root.mkdir(parents=True, exist_ok=False)
    else:
        required = {
            "--candidate-receipt": args.candidate_receipt,
            "--installed-app": args.installed_app,
            "--candidate-architecture": args.candidate_architecture,
            "--json-out": args.json_out,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error("missing required arguments: " + ", ".join(missing))
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return _child_main(args) if args.child else _main_gate(args)
    except GateFailure as exc:
        print(f"Realtor Beta pre-publish gate failed: {exc.code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
