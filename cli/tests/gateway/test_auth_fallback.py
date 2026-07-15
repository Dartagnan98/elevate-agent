"""Test that AuthError triggers fallback provider resolution (#7230)."""

from unittest.mock import patch

import pytest


class TestResolveRuntimeAgentKwargsAuthFallback:
    """_resolve_runtime_agent_kwargs should try fallback on AuthError."""

    def test_auth_error_tries_fallback(self, tmp_path, monkeypatch):
        """When primary provider raises AuthError, fallback is attempted."""
        from elevate_cli.auth import AuthError

        # Create a config with fallback
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "model:\n  provider: openai-codex\n"
            "fallback_model:\n  provider: openrouter\n"
            "  model: meta-llama/llama-4-maverick\n"
        )

        monkeypatch.setattr("gateway.run._elevate_home", tmp_path)

        call_count = {"n": 0}
        calls = []

        def _mock_resolve(**kwargs):
            call_count["n"] += 1
            calls.append(dict(kwargs))
            requested = kwargs.get("requested", "")
            if requested and "codex" in str(requested).lower():
                raise AuthError("Codex token refresh failed with status 401")
            return {
                "api_key": "fallback-key",
                "base_url": "https://openrouter.ai/api/v1",
                "provider": "openrouter",
                "api_mode": "openai_chat",
                "command": None,
                "args": None,
                "credential_pool": None,
            }

        monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openai-codex")

        with patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            side_effect=_mock_resolve,
        ):
            from gateway.run import _resolve_runtime_agent_kwargs
            result = _resolve_runtime_agent_kwargs()

        assert result["provider"] == "openrouter"
        assert result["api_key"] == "fallback-key"
        assert result["model"] == "meta-llama/llama-4-maverick"
        assert calls[-1]["target_model"] == "meta-llama/llama-4-maverick"
        # Should have been called at least twice (primary + fallback)
        assert call_count["n"] >= 2

    def test_primary_resolution_uses_configured_gateway_model(self, monkeypatch):
        calls = []

        monkeypatch.setattr(
            "gateway.run._resolve_gateway_model",
            lambda config=None: "amazon.nova-pro-v1:0",
        )

        def _mock_resolve(**kwargs):
            calls.append(dict(kwargs))
            return {
                "api_key": "aws-sdk",
                "base_url": "https://bedrock-runtime.ca-central-1.amazonaws.com",
                "provider": "bedrock",
                "api_mode": "bedrock_converse",
                "model": kwargs.get("target_model"),
            }

        with patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            side_effect=_mock_resolve,
        ):
            from gateway.run import _resolve_runtime_agent_kwargs

            result = _resolve_runtime_agent_kwargs()

        assert calls == [
            {
                "requested": None,
                "target_model": "amazon.nova-pro-v1:0",
            }
        ]
        assert result["model"] == "amazon.nova-pro-v1:0"

    def test_auth_error_no_fallback_raises(self, tmp_path, monkeypatch):
        """When primary fails and no fallback configured, RuntimeError is raised."""
        from elevate_cli.auth import AuthError

        config_path = tmp_path / "config.yaml"
        config_path.write_text("model:\n  provider: openai-codex\n")

        monkeypatch.setattr("gateway.run._elevate_home", tmp_path)
        monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openai-codex")

        with patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            side_effect=AuthError("token expired"),
        ):
            from gateway.run import _resolve_runtime_agent_kwargs
            with pytest.raises(RuntimeError):
                _resolve_runtime_agent_kwargs()

    def test_beta_auth_error_never_tries_configured_fallback(
        self, tmp_path, monkeypatch
    ):
        from elevate_cli.auth import AuthError

        (tmp_path / "config.yaml").write_text(
            "model:\n  provider: openai-codex\n"
            "fallback_model:\n  provider: openrouter\n"
            "  model: meta-llama/llama-4-maverick\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gateway.run._elevate_home", tmp_path)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openai-codex")
        calls = []

        def _raise_auth(**kwargs):
            calls.append(kwargs)
            raise AuthError("Codex token expired")

        with patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            side_effect=_raise_auth,
        ):
            from gateway.run import _resolve_runtime_agent_kwargs

            with pytest.raises(RuntimeError, match="Codex token expired"):
                _resolve_runtime_agent_kwargs()

        assert len(calls) == 1

    def test_beta_policy_error_keeps_typed_code_visible(self, monkeypatch):
        from elevate_cli.beta_provider_policy import BetaProviderPolicyError

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        with patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            side_effect=BetaProviderPolicyError(
                "OpenAI Codex auth is required.",
                code="beta_codex_auth_required",
            ),
        ):
            from gateway.run import _resolve_runtime_agent_kwargs

            with pytest.raises(
                RuntimeError,
                match="beta_codex_auth_required: OpenAI Codex auth is required",
            ):
                _resolve_runtime_agent_kwargs()

    def test_beta_agent_fallback_chain_is_disabled(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(
            "fallback_providers:\n"
            "  - provider: anthropic\n"
            "    model: anthropic/claude-sonnet-4\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gateway.run._elevate_home", tmp_path)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

        from gateway.run import GatewayRunner

        assert GatewayRunner._load_fallback_model() is None
