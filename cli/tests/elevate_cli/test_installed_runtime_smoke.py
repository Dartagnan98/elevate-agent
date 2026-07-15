from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "cli/scripts/installed_runtime_smoke.py"


def _load_smoke_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("installed_runtime_smoke", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_installed_app_seal_records_codesign_and_spctl_failures(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    app = tmp_path / "Elevate.app"
    app.mkdir()
    calls: list[str] = []

    def fake_run(command, **_kwargs):
        calls.append(command[0])
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"{app}: a sealed resource is missing or invalid\n",
        )

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    result = smoke.SmokeResult()
    smoke.run_installed_app_seal(installed_app=app, timeout=5.0, result=result)

    assert calls == ["codesign", "spctl"]
    assert result.ok is False
    assert [item["name"] for item in result.installed_app_seal] == ["codesign", "spctl"]
    assert all(item["ok"] is False for item in result.installed_app_seal)
    assert result.failures == [
        f"codesign installed app seal check failed: {app}: a sealed resource is missing or invalid",
        f"spctl installed app seal check failed: {app}: a sealed resource is missing or invalid",
    ]


def test_installed_app_seal_passes_when_codesign_and_spctl_pass(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    app = tmp_path / "Elevate.app"
    app.mkdir()

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=f"{command[0]} ok\n", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    result = smoke.SmokeResult()
    smoke.run_installed_app_seal(installed_app=app, timeout=5.0, result=result)

    assert result.ok is True
    assert [item["ok"] for item in result.installed_app_seal] == [True, True]
    assert "installed app seal valid (codesign + spctl)" in result.checks


def test_bundled_runtime_dependency_smoke_uses_isolated_python(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    runtime_python = tmp_path / "runtime/python/bin/python3.12"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")
    installed_cli = tmp_path / "cli"
    installed_cli.mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    result = smoke.SmokeResult()
    smoke.run_bundled_runtime_dependency_smoke(
        runtime_python=runtime_python,
        installed_cli=installed_cli,
        timeout=5.0,
        result=result,
    )

    assert [call[0][1:5] for call in calls] == [
        ["-I", "-B", "-m", "pip"],
        ["-I", "-B", "-c", smoke.RUNTIME_AGENT_PROBE],
    ]
    assert calls[1][0][-2:] == [str(installed_cli), ""]
    assert calls[0][1]["env"]["ELEVATE_HOME"].endswith("/.elevate")
    assert "PYTHONPATH" not in calls[0][1]["env"]
    assert result.ok is True
    assert result.installed_runtime_dependencies is not None
    assert [item["name"] for item in result.installed_runtime_dependencies["checks"]] == [
        "pip_check",
        "backend_agent_init",
    ]
    assert "bundled Python dependency closure and backend/agent initialization pass" in result.checks


def test_bundled_runtime_dependency_smoke_uses_beta_provider_contract(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    runtime_python = tmp_path / "runtime/python/bin/python3.12"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")
    installed_cli = tmp_path / "cli"
    installed_cli.mkdir()
    observed = {}

    def fake_run(command, **kwargs):
        if "-c" in command:
            observed["command"] = command
            observed["env"] = kwargs["env"]
            observed["auth"] = json.loads(
                (Path(kwargs["env"]["ELEVATE_HOME"]) / "auth.json").read_text(
                    encoding="utf-8"
                )
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    result = smoke.SmokeResult()
    smoke.run_bundled_runtime_dependency_smoke(
        runtime_python=runtime_python,
        installed_cli=installed_cli,
        timeout=5.0,
        result=result,
        release_channel="beta",
        elevate_home_name=".elevate-beta",
    )

    assert observed["command"][-2:] == [str(installed_cli), "beta"]
    assert observed["env"]["ELEVATE_RELEASE_CHANNEL"] == "beta"
    assert observed["env"]["ELEVATE_HOME"].endswith("/.elevate-beta")
    assert "openai-codex" in observed["auth"]["providers"]
    assert result.ok is True


def test_bundled_runtime_dependency_smoke_rejects_home_path_escape(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    runtime_python = tmp_path / "runtime/python/bin/python3.12"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")
    installed_cli = tmp_path / "cli"
    installed_cli.mkdir()
    outside = tmp_path / "outside"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unsafe profile must fail before subprocesses"),
    )

    for unsafe_name in (str(outside), "../outside", "nested/home", ".", ""):
        result = smoke.SmokeResult()
        smoke.run_bundled_runtime_dependency_smoke(
            runtime_python=runtime_python,
            installed_cli=installed_cli,
            timeout=5.0,
            result=result,
            release_channel="beta",
            elevate_home_name=unsafe_name,
        )
        assert result.ok is False
        assert result.failures == [
            "release profile elevate home name must be one relative directory"
        ]

    assert not (outside / "auth.json").exists()


def test_bundled_runtime_dependency_smoke_reports_missing_transitive_dependency(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    runtime_python = tmp_path / "runtime/python/bin/python3.12"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")
    installed_cli = tmp_path / "cli"
    installed_cli.mkdir()
    responses = iter(
        [
            subprocess.CompletedProcess(
                [],
                1,
                stdout="requests requires urllib3, which is not installed.\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                [],
                1,
                stdout="",
                stderr="ModuleNotFoundError: No module named 'urllib3'\n",
            ),
        ]
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    result = smoke.SmokeResult()
    smoke.run_bundled_runtime_dependency_smoke(
        runtime_python=runtime_python,
        installed_cli=installed_cli,
        timeout=5.0,
        result=result,
    )

    assert result.ok is False
    assert result.failures == [
        "bundled Python pip_check failed: requests requires urllib3, which is not installed.",
        "bundled Python backend_agent_init failed: ModuleNotFoundError: No module named 'urllib3'",
    ]


def test_installed_runtime_smoke_can_skip_seal_for_dev_only_probe():
    smoke = _load_smoke_script()

    assert smoke.parse_args(["--skip-seal"]).skip_seal is True


def test_candidate_binding_is_recorded_in_smoke_evidence(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    repo = tmp_path / "repo"
    verifier = repo / "desktop/scripts/candidate-receipt.js"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("", encoding="utf-8")
    receipt = tmp_path / "candidate-receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    app = tmp_path / "Elevate Beta.app"
    app.mkdir()
    payload = {
        "candidate_id": "candidate-123",
        "source_receipt_id": "source-123",
        "candidate_architecture": "arm64",
        "receipt_sha256": "a" * 64,
        "app_version": "1.2.67",
        "app_bundle_manifest_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload) + "\n", stderr=""
        ),
    )

    result = smoke.SmokeResult()
    smoke.verify_candidate_binding(
        repo_root=repo,
        receipt_path=receipt,
        installed_app=app,
        architecture="arm64",
        result=result,
    )

    assert result.ok is True
    assert result.candidate_id == "candidate-123"
    assert result.source_receipt_id == "source-123"
    assert result.candidate_architecture == "arm64"
    assert result.candidate_receipt_sha256 == "a" * 64
    assert result.candidate_app_version == "1.2.67"
    assert result.candidate_app_bundle_manifest_sha256 == "b" * 64


def test_candidate_binding_hash_mismatch_blocks_smoke(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    repo = tmp_path / "repo"
    verifier = repo / "desktop/scripts/candidate-receipt.js"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 1, stdout="", stderr="[candidate] arm64 bundle_manifest mismatch\n"
        ),
    )

    result = smoke.SmokeResult()
    smoke.verify_candidate_binding(
        repo_root=repo,
        receipt_path=tmp_path / "candidate-receipt.json",
        installed_app=tmp_path / "Elevate Beta.app",
        architecture="arm64",
        result=result,
    )

    assert result.ok is False
    assert result.failures == [
        "candidate receipt verification failed: [candidate] arm64 bundle_manifest mismatch"
    ]


def test_smoke_evidence_integrity_matches_candidate_verifier_canonical_json():
    smoke = _load_smoke_script()
    evidence = {
        "evidence_schema_version": 1,
        "checks": ["Unicode proof ✓"],
        "nested": {"beta": True, "count": 2},
        "evidence_integrity_sha256": None,
    }
    expected = smoke.compute_evidence_integrity(evidence)
    script = (
        "const fs=require('node:fs');"
        "const {evidenceIntegrity}=require('./desktop/scripts/candidate-receipt');"
        "console.log(evidenceIntegrity(JSON.parse(fs.readFileSync(0,'utf8'))));"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        input=json.dumps(evidence, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == expected


def test_installed_runtime_smoke_allows_slow_gatekeeper_assessment():
    smoke = _load_smoke_script()

    assert smoke.parse_args([]).seal_timeout == 600.0
    assert smoke.parse_args(["--seal-timeout", "45"]).seal_timeout == 45.0


def test_installed_runtime_smoke_discovers_selected_dashboard_port(tmp_path):
    smoke = _load_smoke_script()
    log = tmp_path / "main.log"
    log.write_text(
        "[2026-06-19 00:00:00.000] [info] [startup] 42ms backend:port-selected 9120\n",
        encoding="utf-8",
    )

    assert smoke.parse_args([]).port is None
    assert smoke.read_selected_dashboard_port(log) == 9120
    assert smoke.read_selected_dashboard_port(tmp_path / "missing.log") == 9119


def test_installed_runtime_smoke_reads_license_from_elevate_home(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    elevate_home = tmp_path / "state"
    elevate_home.mkdir()
    monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

    assert smoke.license_state_path() == elevate_home / "license.json"


def test_recent_log_scan_ignores_old_untimestamped_continuations(tmp_path):
    smoke = _load_smoke_script()
    log = tmp_path / "main.log"
    since = datetime(2026, 6, 19, 12, 0, 0)
    log.write_text(
        "\n".join(
            [
                "[2026-06-19 11:59:00.000] [error] old failure",
                "BLANK-TRACE from stale renderer boot",
                "[2026-06-19 12:00:01.000] [info] fresh healthy line",
            ]
        ),
        encoding="utf-8",
    )

    assert smoke.read_recent_log_hits(log, since) == []

    log.write_text(
        "[2026-06-19 12:00:01.000] [error] fresh failure\n"
        "Uncaught fresh renderer error\n",
        encoding="utf-8",
    )

    assert smoke.read_recent_log_hits(log, since) == ["Uncaught fresh renderer error"]


def test_main_records_selected_dashboard_port(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    log = tmp_path / "main.log"
    out = tmp_path / "smoke.json"
    app = tmp_path / "Elevate.app"
    app.mkdir()
    log.write_text(
        "[2026-06-19 00:00:00.000] [info] [startup] 42ms backend:port-selected 9121\n",
        encoding="utf-8",
    )
    dependency_probe = {}

    monkeypatch.setattr(smoke, "read_recent_log_hits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        smoke,
        "run_bundled_runtime_dependency_smoke",
        lambda **kwargs: dependency_probe.update(kwargs),
    )

    rc = smoke.main(
        [
            "--installed-app",
            str(app),
            "--main-log",
            str(log),
            "--skip-seal",
            "--skip-parity",
            "--skip-sidecar",
            "--json-out",
            str(out),
        ]
    )

    assert rc == 0
    assert '"dashboard_port": 9121' in out.read_text(encoding="utf-8")
    assert dependency_probe["runtime_python"] == (
        app / "Contents/Resources/runtime/python/bin/python3.12"
    )
    assert dependency_probe["installed_cli"] == app / "Contents/Resources/cli"
    assert dependency_probe["release_channel"] == ""
    assert dependency_probe["elevate_home_name"] == ".elevate"


def test_main_passes_beta_candidate_profile_to_dependency_probe(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    app = tmp_path / "Elevate Beta.app"
    app.mkdir()
    receipt = tmp_path / "candidate-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "release": {
                    "channel": "beta",
                    "profile": {
                        "elevateHomeName": ".elevate-beta",
                        "preferredPort": 9139,
                        "productName": "Elevate Beta",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "smoke.json"
    dependency_probe = {}

    monkeypatch.setattr(smoke, "verify_candidate_binding", lambda **_kwargs: None)
    monkeypatch.setattr(smoke, "read_recent_log_hits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(smoke, "run_installed_whatsapp_bridge", lambda **_kwargs: None)
    monkeypatch.setattr(
        smoke,
        "run_bundled_runtime_dependency_smoke",
        lambda **kwargs: dependency_probe.update(kwargs),
    )

    rc = smoke.main(
        [
            "--installed-app",
            str(app),
            "--candidate-receipt",
            str(receipt),
            "--candidate-architecture",
            "arm64",
            "--skip-seal",
            "--skip-parity",
            "--skip-sidecar",
            "--json-out",
            str(out),
        ]
    )

    assert rc == 0
    assert dependency_probe["release_channel"] == "beta"
    assert dependency_probe["elevate_home_name"] == ".elevate-beta"


def test_installed_dashboard_assets_extract_index_and_chat(tmp_path):
    smoke = _load_smoke_script()
    web_dist = tmp_path / "web_dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text(
        '<script type="module" src="/assets/index-live.js"></script>',
        encoding="utf-8",
    )
    (assets / "index-live.js").write_text('import("./ChatPage-live.js");', encoding="utf-8")

    assert smoke.installed_dashboard_assets(web_dist) == ("index-live.js", "ChatPage-live.js")


def test_served_asset_mismatch_fails(tmp_path):
    smoke = _load_smoke_script()
    web_dist = tmp_path / "web_dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text(
        '<script type="module" src="/assets/index-installed.js"></script>',
        encoding="utf-8",
    )
    (assets / "index-installed.js").write_text(
        'import("./ChatPage-installed.js");',
        encoding="utf-8",
    )

    result = smoke.SmokeResult(
        installed_index_asset="index-stale.js",
        installed_chat_asset="ChatPage-stale.js",
    )
    smoke.check_served_assets_match_installed(web_dist, result)

    assert result.ok is False
    assert result.failures == [
        "served dashboard index asset differs from installed web_dist: "
        "'index-stale.js' != 'index-installed.js'",
        "served dashboard ChatPage asset differs from installed web_dist: "
        "'ChatPage-stale.js' != 'ChatPage-installed.js'",
    ]


def test_protected_http_auth_probe(monkeypatch):
    smoke = _load_smoke_script()
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_fetch_status(url, _timeout, headers=None):
        calls.append((url, headers))
        return 200 if headers else 401

    monkeypatch.setattr(smoke, "fetch_status", fake_fetch_status)

    result = smoke.SmokeResult()
    smoke.check_protected_http_auth(port=9120, token="tok", timeout=5.0, result=result)

    assert result.ok is True
    assert calls == [
        ("http://127.0.0.1:9120/api/sessions?limit=1", None),
        ("http://127.0.0.1:9120/api/sessions?limit=1", {"X-Elevate-Session-Token": "tok"}),
    ]


def test_read_installed_app_version_uses_bundle_info_plist(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    app = tmp_path / "Elevate.app"
    plist = app / "Contents/Info.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist />\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        assert command[-1] == str(plist)
        return subprocess.CompletedProcess(command, 0, stdout="1.2.58\n", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.read_installed_app_version(app) == "1.2.58"


def test_expected_app_version_mismatch_fails_main(monkeypatch, tmp_path):
    smoke = _load_smoke_script()
    app = tmp_path / "Elevate.app"
    out = tmp_path / "smoke.json"
    app.mkdir()

    monkeypatch.setattr(smoke, "read_installed_app_version", lambda _app: "1.2.57")
    monkeypatch.setattr(smoke, "read_recent_log_hits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(smoke, "run_bundled_runtime_dependency_smoke", lambda **_kwargs: None)

    rc = smoke.main(
        [
            "--installed-app",
            str(app),
            "--expected-app-version",
            "1.2.58",
            "--skip-seal",
            "--skip-parity",
            "--skip-sidecar",
            "--json-out",
            str(out),
        ]
    )

    assert rc == 1
    assert "installed app version mismatch" in out.read_text(encoding="utf-8")


def test_installed_whatsapp_bridge_passes_when_packaged(tmp_path):
    smoke = _load_smoke_script()
    installed_cli = tmp_path / "Elevate.app/Contents/Resources/cli"
    bridge_dir = installed_cli / "scripts/whatsapp-bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "bridge.js").write_text("console.log('ok')\n", encoding="utf-8")
    (bridge_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    (bridge_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")

    result = smoke.SmokeResult()
    smoke.run_installed_whatsapp_bridge(installed_cli=installed_cli, result=result)

    assert result.ok is True
    assert result.installed_whatsapp_bridge == {
        "bridge_js": True,
        "package_json": True,
        "package_lock": True,
    }
    assert "installed WhatsApp bridge present for lazy install" in result.checks


def test_installed_whatsapp_bridge_fails_when_missing(tmp_path):
    smoke = _load_smoke_script()
    installed_cli = tmp_path / "Elevate.app/Contents/Resources/cli"
    installed_cli.mkdir(parents=True)

    result = smoke.SmokeResult()
    smoke.run_installed_whatsapp_bridge(installed_cli=installed_cli, result=result)

    assert result.ok is False
    assert result.failures == [
        "installed WhatsApp bridge incomplete: bridge_js, package_json, package_lock"
    ]
