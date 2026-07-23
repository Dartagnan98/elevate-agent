import plistlib
from pathlib import Path

from elevate_cli import debug_browser as db


def test_visible_browser_identity_isolates_beta_from_stable():
    assert db._managed_browser_identity(
        home=Path("/tmp/.elevate"), release_channel="latest"
    ) == (9222, "ai.elevate.debugchrome")
    assert db._managed_browser_identity(
        home=Path("/tmp/.elevate-beta"), release_channel="beta"
    ) == (9232, "ai.elevate.debugchrome-beta")
    # The Beta home remains authoritative even when a launcher omitted the
    # explicit channel environment variable.
    assert db._managed_browser_identity(
        home=Path("/tmp/.elevate-beta"), release_channel=""
    ) == (9232, "ai.elevate.debugchrome-beta")
    assert db._managed_browser_identity(
        home=Path("/tmp/.elevate"), release_channel="Beta "
    ) == (9222, "ai.elevate.debugchrome")


def test_beta_launch_agent_persists_beta_home_and_channel(tmp_path, monkeypatch):
    beta_home = tmp_path / ".elevate-beta"
    monkeypatch.setattr(db, "get_elevate_home", lambda: beta_home)
    monkeypatch.setattr(db, "_python_path", lambda: "/tmp/elevate-python")
    monkeypatch.setattr(db, "LAUNCH_AGENT_LABEL", db.BETA_LAUNCH_AGENT_LABEL)

    payload = plistlib.loads(db.generate_plist())

    assert payload["Label"] == "ai.elevate.debugchrome-beta"
    assert payload["WorkingDirectory"] == str(
        Path(db.__file__).resolve().parent.parent
    )
    assert payload["EnvironmentVariables"]["ELEVATE_HOME"] == str(beta_home)
    assert payload["EnvironmentVariables"]["ELEVATE_RELEASE_CHANNEL"] == "beta"
    assert payload["EnvironmentVariables"]["PYTHONNOUSERSITE"] == "1"
    assert payload["EnvironmentVariables"]["PYTHONPATH"] == payload["WorkingDirectory"]
    assert payload["EnvironmentVariables"]["PYTHONPYCACHEPREFIX"] == str(
        beta_home / "cache" / "python-pycache"
    )


def test_reachable_managed_browser_repairs_persistent_setup(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "is_supported", lambda: True)
    monkeypatch.setattr(db, "chrome_binary", lambda: Path("/tmp/Chrome"))
    monkeypatch.setattr(db, "auto_provision_disabled", lambda: False)
    monkeypatch.setattr(db, "cdp_is_up", lambda: True)
    monkeypatch.setattr(db, "install_launch_agent", lambda: calls.append("launch-agent"))
    monkeypatch.setattr(db, "set_cdp_config", lambda enabled: calls.append(("config", enabled)))

    assert db.ensure_debug_browser() == db.CDP_URL
    assert calls == ["launch-agent", ("config", True)]
