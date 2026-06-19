from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


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


def test_installed_runtime_smoke_can_skip_seal_for_dev_only_probe():
    smoke = _load_smoke_script()

    assert smoke.parse_args(["--skip-seal"]).skip_seal is True


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
    (bridge_dir / "node_modules").mkdir(parents=True)
    (bridge_dir / "bridge.js").write_text("console.log('ok')\n", encoding="utf-8")
    (bridge_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    (bridge_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")

    result = smoke.SmokeResult()
    smoke.run_installed_whatsapp_bridge(installed_cli=installed_cli, result=result)

    assert result.ok is True
    assert result.installed_whatsapp_bridge == {
        "bridge_js": True,
        "package_json": True,
        "node_modules": True,
        "package_lock": True,
    }
    assert "installed WhatsApp bridge present with dependencies" in result.checks


def test_installed_whatsapp_bridge_fails_when_missing(tmp_path):
    smoke = _load_smoke_script()
    installed_cli = tmp_path / "Elevate.app/Contents/Resources/cli"
    installed_cli.mkdir(parents=True)

    result = smoke.SmokeResult()
    smoke.run_installed_whatsapp_bridge(installed_cli=installed_cli, result=result)

    assert result.ok is False
    assert result.failures == [
        "installed WhatsApp bridge incomplete: bridge_js, node_modules, package_json, package_lock"
    ]
