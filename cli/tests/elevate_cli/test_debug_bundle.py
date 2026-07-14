from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from elevate_cli import debug_bundle


def test_parse_since_and_safe_id_validation():
    assert debug_bundle._parse_since("30m") == 1800
    assert debug_bundle._parse_since("all") is None
    with pytest.raises(ValueError, match="--last"):
        debug_bundle._parse_since("0m")
    with pytest.raises(ValueError, match="correlation ID"):
        debug_bundle._safe_id("client address", label="correlation ID")


def test_bundle_contains_only_structured_correlated_events(monkeypatch, tmp_path):
    home = tmp_path / "profile"
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_APP_VERSION", "1.2.68")
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_SOURCE_RECEIPT_ID", "b" * 64)
    monkeypatch.setattr(
        debug_bundle,
        "_route_health",
        lambda _port: {"dashboard_port": 9140, "routes": {"/api/status": {"http_status": 200}}},
    )
    captured = {}

    def fake_collect_session_events(**kwargs):
        captured.update(kwargs)
        return {
            "events": [
                {
                    "schema_version": 1,
                    "event_id": "event-1",
                    "event": "tool.error",
                    "component": "John Smith",
                    "correlation_id": "turn-1",
                    "session_id": "session-1",
                    "payload": {
                        "error_class": "John Smith",
                        "error_message": "John Smith at 123 Client Street client@example.com",
                        "reason": "raw prompt password=hunter2",
                        "tool_name": "document_search",
                        "status": "error",
                    },
                    "redaction": {"John Smith": 3, "strings_redacted": 4},
                }
            ],
            "report": {
                "events_seen": 1,
                "events_written": 1,
                "John Smith": 7,
                "strings_redacted": 4,
            },
        }

    import elevate_cli.diagnostics.session_recorder as recorder

    monkeypatch.setattr(recorder, "collect_session_events", fake_collect_session_events)
    payload = debug_bundle.build_support_payload(
        correlation_id="turn-1",
        since_seconds=1800,
    )
    bundle, sidecar, digest = debug_bundle.write_support_bundle(
        payload,
        output=tmp_path / "bundle.zip",
    )

    assert captured["correlation_id"] == "turn-1"
    assert captured["include_lineage"] is True
    assert oct(bundle.stat().st_mode & 0o777) == "0o600"
    assert oct(sidecar.stat().st_mode & 0o777) == "0o600"
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == digest
    assert digest in sidecar.read_text(encoding="ascii")
    with zipfile.ZipFile(bundle) as archive:
        assert archive.namelist() == ["manifest.json"]
        raw = archive.read("manifest.json")
    manifest = json.loads(raw)
    assert manifest["correlation_id"] == "turn-1"
    assert manifest["candidate"]["source_receipt_id"] == "b" * 64
    assert manifest["events"][0]["payload"]["tool_name"] == "document_search"
    assert "component" not in manifest["events"][0]
    assert "error_class" not in manifest["events"][0]["payload"]
    assert "error_message" not in manifest["events"][0]["payload"]
    assert "reason" not in manifest["events"][0]["payload"]
    assert "John Smith" not in manifest["events"][0]["redaction"]
    assert "John Smith" not in manifest["redaction_report"]
    assert manifest["payload_sha256"]
    serialized = bundle.read_bytes()
    for forbidden in (
        b"raw prompt",
        b"123 Client Street",
        b"client@example.com",
        b"password=hunter2",
    ):
        assert forbidden not in serialized


def test_candidate_receipt_adds_final_candidate_identity(tmp_path):
    receipt = tmp_path / "candidate.json"
    receipt.write_text(
        json.dumps(
            {
                "candidate_id": "c" * 64,
                "source_receipt_id": "d" * 64,
                "release": {
                    "version": "1.2.68",
                    "channel": "beta",
                    "profile": {"appBundleName": "Elevate Beta.app"},
                },
            }
        ),
        encoding="utf-8",
    )
    identity = debug_bundle._candidate_identity(receipt)
    assert identity["candidate_id"] == "c" * 64
    assert identity["source_receipt_id"] == "d" * 64
    assert identity["candidate_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert identity["candidate_binding"] == "supplied_receipt_runtime_metadata_missing"


def test_candidate_receipt_rejects_runtime_identity_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVATE_APP_VERSION", "9.9.9")
    receipt = tmp_path / "candidate.json"
    receipt.write_text(
        json.dumps(
            {
                "candidate_id": "c" * 64,
                "source_receipt_id": "d" * 64,
                "release": {
                    "version": "1.2.68",
                    "channel": "beta",
                    "profile": {"appBundleName": "Elevate Beta.app"},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="app_version"):
        debug_bundle._candidate_identity(receipt)


def test_run_debug_bundle_never_uploads(monkeypatch, tmp_path):
    payload = {"correlation_id": "turn-2", "events": [], "payload_sha256": "e" * 64}
    monkeypatch.setattr(debug_bundle, "build_support_payload", lambda **_kwargs: payload)
    output = tmp_path / "safe.zip"
    result = debug_bundle.run_debug_bundle(
        SimpleNamespace(
            correlation="turn-2",
            last="30m",
            candidate_receipt=None,
            output=str(output),
        )
    )
    assert result[0] == output.resolve()
    assert output.exists()
