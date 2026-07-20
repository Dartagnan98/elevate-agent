from __future__ import annotations

import plistlib

from elevate_cli import gateway, sender, template_suggester, web_auth, xposure_pcs_views


def test_dashboard_session_token_uses_elevate_home(tmp_path, monkeypatch):
    beta_home = tmp_path / ".elevate-beta"
    monkeypatch.delenv("ELEVATE_DASHBOARD_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(web_auth, "get_elevate_home", lambda: beta_home)

    token = web_auth.load_session_token()
    token_path = beta_home / "dashboard-session-token"

    assert token_path.read_text(encoding="utf-8") == token
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert web_auth.load_session_token() == token


def test_sms_outbox_uses_elevate_home(tmp_path, monkeypatch):
    beta_home = tmp_path / ".elevate-beta"
    monkeypatch.setattr(sender, "get_elevate_home", lambda: beta_home)

    assert sender._sms_outbox_dir() == str(beta_home / "sms-outbox")
    assert sender._ids_capability_bin_path() == str(beta_home / "bin" / "ids-capability")


def test_realtor_runtime_files_use_elevate_home(tmp_path, monkeypatch):
    beta_home = tmp_path / ".elevate-beta"
    beta_home.mkdir()
    (beta_home / "SOUL.md").write_text("Beta realtor voice", encoding="utf-8")
    monkeypatch.setattr(template_suggester, "get_elevate_home", lambda: beta_home)
    monkeypatch.setattr(xposure_pcs_views, "get_elevate_home", lambda: beta_home)

    assert template_suggester._voice_anchor() == "Beta realtor voice"
    assert xposure_pcs_views._snapshot_path() == (
        beta_home / "snapshots" / "pcs-listing-views.jsonl"
    )


def test_beta_gateway_has_a_distinct_persisted_service_identity(tmp_path, monkeypatch):
    beta_home = tmp_path / ".elevate-beta"
    monkeypatch.setenv("ELEVATE_HOME", str(beta_home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(gateway, "get_elevate_home", lambda: beta_home)

    assert gateway.get_launchd_label() == "ai.elevate.gateway-beta"
    assert gateway.get_service_name() == "elevate-gateway-beta"
    plist = gateway.generate_launchd_plist()
    payload = plistlib.loads(plist.encode("utf-8"))
    assert payload["Label"] == "ai.elevate.gateway-beta"
    assert payload["EnvironmentVariables"]["ELEVATE_RELEASE_CHANNEL"] == "beta"
    assert payload["EnvironmentVariables"]["ELEVATE_HOME"] == str(beta_home)


def test_sloppy_release_channel_never_claims_the_beta_service_identity(
    tmp_path, monkeypatch
):
    """The service-identity suffix is exact-match on ``beta`` — the same
    contract every safety reader of ELEVATE_RELEASE_CHANNEL uses. A sloppy
    value that no safety gate treats as Beta must neither claim the Beta
    label nor persist a normalized beta channel into the plist (which would
    install a beta-channel gateway under a non-Beta service name)."""
    home = tmp_path / ".elevate-custom"
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setattr(gateway, "get_elevate_home", lambda: home)

    for sloppy in ("Beta", " beta ", "BETA", "beta\n"):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", sloppy)
        label = gateway.get_launchd_label()
        assert label != "ai.elevate.gateway-beta", sloppy
        assert not label.endswith("-beta"), sloppy
        assert gateway.get_service_name() != "elevate-gateway-beta", sloppy
        payload = plistlib.loads(
            gateway.generate_launchd_plist().encode("utf-8")
        )
        assert payload["Label"] == label, sloppy
        assert (
            "ELEVATE_RELEASE_CHANNEL" not in payload["EnvironmentVariables"]
        ), sloppy
