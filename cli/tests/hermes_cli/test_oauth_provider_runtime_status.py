"""OAuth status must describe credentials the selected runtime can consume."""

import time

from elevate_cli.web_routes import oauth


def _expired_claude_credentials():
    return {
        "accessToken": "expired-access-token",
        "refreshToken": "rejected-refresh-token",
        "expiresAt": int(time.time() * 1000) - 60_000,
    }


def test_anthropic_status_blocks_expired_keychain_with_refresh_metadata(
    monkeypatch,
):
    creds = _expired_claude_credentials()
    creds["source"] = "macos_keychain"
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_elevate_oauth_credentials", lambda: None
    )
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_claude_code_credentials", lambda: creds
    )
    monkeypatch.setattr(
        "agent.anthropic_adapter._resolve_claude_code_token_from_credentials",
        lambda _creds: (_ for _ in ()).throw(
            AssertionError("macOS Keychain credentials must be renewed by Claude Code")
        ),
    )

    status = oauth._anthropic_oauth_status()
    cli_status = oauth._claude_code_only_status()

    assert status["logged_in"] is False
    assert status["source"] == "claude_code"
    assert status["has_refresh_token"] is True
    assert "claude /login" in status["error"]
    assert cli_status["logged_in"] is False
    assert "claude /login" in cli_status["error"]


def test_anthropic_status_accepts_non_expired_claude_credentials(
    monkeypatch,
):
    fresh = {
        "source": "claude_code_credentials_file",
        "accessToken": "fresh-access-token",
        "refreshToken": "refresh-token",
        "expiresAt": int(time.time() * 1000) + 3_600_000,
    }
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_elevate_oauth_credentials", lambda: None
    )
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_claude_code_credentials", lambda: fresh
    )

    status = oauth._anthropic_oauth_status()

    assert status["logged_in"] is True
    assert status["source"] == "claude_code"
    assert status["token_preview"].endswith("-token")
    assert status["expires_at"] == fresh["expiresAt"]


def test_anthropic_status_preserves_no_expiry_as_no_expiry(monkeypatch):
    creds = {
        "source": "claude_code_credentials_file",
        "accessToken": "managed-access-token",
        "refreshToken": "",
        "expiresAt": 0,
    }
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_elevate_oauth_credentials", lambda: None
    )
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_claude_code_credentials", lambda: creds
    )

    status = oauth._anthropic_oauth_status()

    assert status["logged_in"] is True
    assert status["expires_at"] is None


def test_anthropic_status_blocks_expired_elevate_pkce(
    monkeypatch,
):
    creds = _expired_claude_credentials()
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_elevate_oauth_credentials", lambda: creds
    )
    monkeypatch.setattr(
        "agent.anthropic_adapter.read_claude_code_credentials", lambda: None
    )
    status = oauth._anthropic_oauth_status()

    assert status["logged_in"] is False
    assert status["source"] == "elevate_pkce"
    assert "Sign in again" in status["error"]


def test_oauth_wizard_selections_materialize_to_runtime_provider_ids():
    from elevate_cli.web_routes.admin_setup import (
        _WIZARD_PROVIDER_TO_CONFIG,
        _wizard_runtime_provider,
    )

    assert _WIZARD_PROVIDER_TO_CONFIG["openai"] == "openai-codex"
    assert _WIZARD_PROVIDER_TO_CONFIG["qwen"] == "qwen-oauth"
    assert _WIZARD_PROVIDER_TO_CONFIG["xai"] == "xai-oauth"
    assert _WIZARD_PROVIDER_TO_CONFIG["gemini"] == "google-gemini-cli"
    assert _WIZARD_PROVIDER_TO_CONFIG["minimax"] == "minimax-oauth"
    assert _wizard_runtime_provider("xai", {"runtimeProvider": "xai"}) == "xai"
    assert _wizard_runtime_provider("qwen", {"runtimeProvider": "qwen"}) == "alibaba"
    assert (
        _wizard_runtime_provider(
            "azure_openai", {"runtimeProvider": "azure_openai"}
        )
        == "azure-foundry"
    )
    assert (
        _wizard_runtime_provider("xai", {"runtimeProvider": "xai-oauth"})
        == "xai-oauth"
    )
    assert _wizard_runtime_provider("xai", {}) == "xai-oauth"
