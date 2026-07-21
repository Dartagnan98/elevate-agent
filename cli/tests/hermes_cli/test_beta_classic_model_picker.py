"""Exact Realtor Beta containment for the classic terminal model picker."""

from __future__ import annotations

from unittest.mock import patch

from cli import ElevateCLI


def test_exact_beta_picker_canonicalizes_stale_session_before_config_discovery(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    cli = object.__new__(ElevateCLI)
    cli.model = "claude-opus-4-6"
    cli.provider = "anthropic"
    captured = {}
    cli._open_model_picker = (
        lambda providers, current_model, current_provider, **kwargs: captured.update(
            providers=providers,
            current_model=current_model,
            current_provider=current_provider,
            kwargs=kwargs,
        )
    )
    codex_rows = [
        {
            "slug": "openai-codex",
            "name": "OpenAI Codex",
            "models": ["gpt-5.6-sol"],
            "is_current": True,
        }
    ]

    with (
        patch(
            "elevate_cli.model_switch.list_authenticated_providers",
            return_value=codex_rows,
        ) as listing,
        patch(
            "elevate_cli.config.load_config",
            side_effect=AssertionError("generic config discovery reached exact Beta"),
        ),
    ):
        cli._handle_model_switch("/model")

    assert captured == {
        "providers": codex_rows,
        "current_model": "gpt-5.6-sol",
        "current_provider": "OpenAI Codex",
        "kwargs": {"user_provs": None, "custom_provs": None},
    }
    listing.assert_called_once_with(
        current_provider="openai-codex",
        user_providers=None,
        custom_providers=None,
        max_models=50,
    )


def test_nonexact_picker_preserves_generic_config_discovery(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    cli = object.__new__(ElevateCLI)
    cli.model = "claude-opus-4-6"
    cli.provider = "anthropic"
    captured = {}
    cli._open_model_picker = (
        lambda providers, current_model, current_provider, **kwargs: captured.update(
            providers=providers,
            current_model=current_model,
            current_provider=current_provider,
            kwargs=kwargs,
        )
    )

    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"providers": {"anthropic": {}}},
        ) as load_config,
        patch(
            "elevate_cli.config.get_compatible_custom_providers",
            return_value=[{"name": "local"}],
        ),
        patch(
            "elevate_cli.model_switch.list_authenticated_providers",
            return_value=[{"slug": "anthropic"}],
        ),
    ):
        cli._handle_model_switch("/model")

    load_config.assert_called_once_with()
    assert captured["current_model"] == "claude-opus-4-6"
    assert captured["kwargs"] == {
        "user_provs": {"anthropic": {}},
        "custom_provs": [{"name": "local"}],
    }
