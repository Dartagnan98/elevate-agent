from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_faster_whisper_is_not_a_base_dependency():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]

    assert not any(dep.startswith("faster-whisper") for dep in deps)

    voice_extra = data["project"]["optional-dependencies"]["voice"]
    assert any(dep.startswith("faster-whisper") for dep in voice_extra)


def test_web_extra_contains_dashboard_upload_dependencies():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    web_extra = data["project"]["optional-dependencies"]["web"]

    assert any(dep.startswith("fastapi") for dep in web_extra)
    assert any(dep.startswith("uvicorn") for dep in web_extra)
    assert any(dep.startswith("python-multipart") for dep in web_extra)


def test_download_installers_repair_dashboard_runtime_dependencies():
    install_sh = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    setup_sh = (REPO_ROOT / "setup-elevate.sh").read_text(encoding="utf-8")

    for script in (install_sh, setup_sh):
        assert "ensure_dashboard_runtime_dependencies" in script
        assert "verify_dashboard_runtime_imports" in script
        assert '".[web]"' in script
        assert "elevate_cli.web_server" in script

    assert "Ensure-DashboardRuntimeDependencies" in install_ps1
    assert "Test-DashboardRuntimeImports" in install_ps1
    assert 'pip install -e ".[web]"' in install_ps1
    assert "elevate_cli.web_server" in install_ps1


def test_manifest_includes_bundled_skills():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "graft skills" in manifest
    assert "graft optional-skills" in manifest
