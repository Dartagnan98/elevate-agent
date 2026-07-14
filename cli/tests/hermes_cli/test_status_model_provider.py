"""Tests for elevate_cli.status model/provider display."""

from types import SimpleNamespace

from elevate_cli.nous_subscription import NousFeatureState, NousSubscriptionFeatures


def _patch_common_status_deps(monkeypatch, status_mod, tmp_path, *, openai_base_url=""):
    import elevate_cli.auth as auth_mod

    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env", raising=False)
    monkeypatch.setattr(status_mod, "get_elevate_home", lambda: tmp_path, raising=False)

    def _get_env_value(name: str):
        if name == "OPENAI_BASE_URL":
            return openai_base_url
        return ""

    monkeypatch.setattr(status_mod, "get_env_value", _get_env_value, raising=False)
    monkeypatch.setattr(auth_mod, "get_nous_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(auth_mod, "get_codex_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(
        status_mod.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="inactive\n", returncode=3),
    )


def test_show_status_displays_configured_dict_model_and_provider_label(monkeypatch, capsys, tmp_path):
    from elevate_cli import status as status_mod

    _patch_common_status_deps(monkeypatch, status_mod, tmp_path)
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: {"model": {"default": "anthropic/claude-sonnet-4", "provider": "anthropic"}},
        raising=False,
    )
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "anthropic", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "anthropic", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "Anthropic", raising=False)

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    out = capsys.readouterr().out
    assert "Model:        anthropic/claude-sonnet-4" in out
    assert "Provider:     Anthropic" in out


def test_show_status_displays_legacy_string_model_and_custom_endpoint(monkeypatch, capsys, tmp_path):
    from elevate_cli import status as status_mod

    _patch_common_status_deps(monkeypatch, status_mod, tmp_path, openai_base_url="http://localhost:8080/v1")
    monkeypatch.setattr(status_mod, "load_config", lambda: {"model": "qwen3:latest"}, raising=False)
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "auto", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "openrouter", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "Custom endpoint" if provider == "custom" else provider, raising=False)

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    out = capsys.readouterr().out
    assert "Model:        qwen3:latest" in out
    assert "Provider:     Custom endpoint" in out


def test_show_status_reports_managed_nous_features(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("elevate_cli.status.managed_nous_tools_enabled", lambda: True)
    from elevate_cli import status as status_mod

    _patch_common_status_deps(monkeypatch, status_mod, tmp_path)
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: {"model": {"default": "claude-opus-4-6", "provider": "nous"}},
        raising=False,
    )
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "nous", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "nous", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "Nous Portal", raising=False)
    monkeypatch.setattr(
        status_mod,
        "get_nous_subscription_features",
        lambda config: NousSubscriptionFeatures(
            subscribed=True,
            nous_auth_present=True,
            provider_is_nous=True,
            features={
                "web": NousFeatureState("web", "Web tools", True, True, True, True, False, True, "firecrawl"),
                "image_gen": NousFeatureState("image_gen", "Image generation", True, True, True, True, False, True, "Nous Subscription"),
                "tts": NousFeatureState("tts", "OpenAI TTS", True, True, True, True, False, True, "OpenAI TTS"),
                "browser": NousFeatureState("browser", "Browser automation", True, True, True, True, False, True, "Browser Use"),
                "modal": NousFeatureState("modal", "Modal execution", False, True, False, False, False, True, "local"),
            },
        ),
        raising=False,
    )

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    out = capsys.readouterr().out
    assert "Nous Tool Gateway" in out
    assert "Browser automation" in out
    assert "active via Nous subscription" in out


def test_show_status_hides_nous_subscription_section_when_feature_flag_is_off(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("elevate_cli.status.managed_nous_tools_enabled", lambda: False)
    from elevate_cli import status as status_mod

    _patch_common_status_deps(monkeypatch, status_mod, tmp_path)
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: {"model": {"default": "claude-opus-4-6", "provider": "nous"}},
        raising=False,
    )
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "nous", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "nous", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "Nous Portal", raising=False)

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    out = capsys.readouterr().out
    assert "Nous Tool Gateway" not in out


def test_exact_beta_status_is_codex_only_and_never_reads_alternate_inference_auth(
    monkeypatch, capsys, tmp_path
):
    from elevate_cli import status as status_mod
    import elevate_cli.auth as auth_mod
    import httpx

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-probed")
    _patch_common_status_deps(monkeypatch, status_mod, tmp_path)
    monkeypatch.setattr(
        status_mod,
        "load_config",
        lambda: {"model": {"provider": "anthropic", "default": "claude-hostile"}},
    )
    monkeypatch.setattr(
        status_mod,
        "provider_label",
        lambda provider: "OpenAI Codex" if provider == "openai-codex" else provider,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("alternate inference discovery is forbidden")

    monkeypatch.setattr(status_mod, "resolve_requested_provider", forbidden)
    monkeypatch.setattr(status_mod, "resolve_provider", forbidden)
    for name in (
        "get_nous_auth_status",
        "get_codex_auth_status",
        "get_anthropic_key",
        "get_qwen_auth_status",
        "get_minimax_oauth_auth_status",
        "get_xai_oauth_auth_status",
    ):
        monkeypatch.setattr(auth_mod, name, forbidden)

    allowed_tool_envs = {
        "FIRECRAWL_API_KEY",
        "TAVILY_API_KEY",
        "FAL_KEY",
        "ELEVENLABS_API_KEY",
        "GITHUB_TOKEN",
    }
    env_reads = []

    def read_tool_env(name):
        assert name in allowed_tool_envs
        env_reads.append(name)
        return "tool-secret-value" if name == "TAVILY_API_KEY" else ""

    monkeypatch.setattr(status_mod, "get_env_value", read_tool_env)
    monkeypatch.setattr(status_mod, "managed_nous_tools_enabled", lambda: False)
    monkeypatch.setattr(httpx, "get", forbidden)

    status_mod.show_status(SimpleNamespace(all=True, deep=True))

    out = capsys.readouterr().out
    assert "Provider:     OpenAI Codex" in out
    assert "claude-hostile (blocked by Realtor Beta policy)" in out
    assert "OpenAI Codex only" in out
    assert "Tavily" in out
    assert "tool-secret-value" not in out
    for hidden in (
        "OpenRouter",
        "Anthropic",
        "Nous Portal",
        "Google / Gemini",
        "Qwen OAuth",
        "MiniMax OAuth",
        "xAI OAuth",
        "Z.AI / GLM",
        "Kimi / Moonshot",
    ):
        assert hidden not in out
    assert set(env_reads) == allowed_tool_envs
