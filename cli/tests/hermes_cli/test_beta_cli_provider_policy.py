"""Codex-only Realtor Beta policy on classic CLI model and auth surfaces."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    BetaProviderPolicyError,
    read_beta_codex_auth_status,
)


@pytest.fixture
def beta_home(tmp_path, monkeypatch):
    home = tmp_path / "beta-profile"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "hostile-ambient-value")
    monkeypatch.setenv("ELEVATE_CODEX_BASE_URL", "https://hostile.invalid/v1")
    return home


def _write_auth(home, *, suppressed=False):
    home.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "providers": {
            BETA_ALLOWED_PROVIDER: {
                "tokens": {
                    "access_token": "local-access-token",
                    "refresh_token": "local-refresh-token",
                },
                "auth_mode": "chatgpt",
            }
        },
    }
    if suppressed:
        payload["suppressed_sources"] = {
            BETA_ALLOWED_PROVIDER: ["device_code", "manual:device_code"]
        }
    (home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


def _unexpected(*_args, **_kwargs):
    raise AssertionError("Beta CLI entered an alternate-provider path")


def _tree_snapshot(root):
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): (
            "directory" if path.is_dir() else "file",
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


@pytest.mark.parametrize("provider", ["gemini", "anthropic", "custom:hostile"])
def test_beta_auth_add_rejects_non_codex_before_any_mutation(
    beta_home,
    monkeypatch,
    provider,
):
    from elevate_cli import auth_commands

    monkeypatch.setattr(auth_commands, "load_pool", _unexpected)
    monkeypatch.setattr(auth_commands.auth_mod, "_codex_device_code_login", _unexpected)

    with pytest.raises(SystemExit, match="beta_provider_not_allowed"):
        auth_commands.auth_add_command(
            SimpleNamespace(
                provider=provider,
                auth_type="oauth",
                api_key=None,
                label=None,
            )
        )

    assert not beta_home.exists()


def test_beta_auth_add_rejects_api_key_before_prompt_or_pool(beta_home, monkeypatch):
    from elevate_cli import auth_commands

    monkeypatch.setattr(auth_commands, "load_pool", _unexpected)
    monkeypatch.setattr(auth_commands, "getpass", _unexpected)
    monkeypatch.setattr(auth_commands.auth_mod, "_codex_device_code_login", _unexpected)

    with pytest.raises(SystemExit, match="beta_primary_api_key_not_allowed"):
        auth_commands.auth_add_command(
            SimpleNamespace(
                provider=BETA_ALLOWED_PROVIDER,
                auth_type="api-key",
                api_key="not-real",
                label=None,
            )
        )

    assert not beta_home.exists()


def test_beta_auth_add_invalid_login_result_is_nonmutating(beta_home, monkeypatch):
    from elevate_cli import auth_commands

    monkeypatch.setattr(
        auth_commands.auth_mod,
        "_codex_device_code_login",
        lambda: {"tokens": {"access_token": "access-only"}},
    )
    monkeypatch.setattr(auth_commands, "load_pool", _unexpected)

    with pytest.raises(SystemExit, match="beta_codex_auth_invalid"):
        auth_commands.auth_add_command(
            SimpleNamespace(
                provider=BETA_ALLOWED_PROVIDER,
                auth_type="oauth",
                api_key=None,
                label=None,
            )
        )

    assert not beta_home.exists()


def test_beta_auth_add_saves_current_profile_state_not_pool(
    beta_home,
    monkeypatch,
):
    from elevate_cli import auth_commands

    _write_auth(beta_home, suppressed=True)
    monkeypatch.setattr(auth_commands, "load_pool", _unexpected)
    monkeypatch.setattr(
        auth_commands.auth_mod,
        "_codex_device_code_login",
        lambda: {
            "tokens": {
                "access_token": "new-local-access",
                "refresh_token": "new-local-refresh",
            },
            "base_url": "https://hostile.invalid/from-login",
            "last_refresh": "2026-07-14T00:00:00Z",
        },
    )

    auth_commands.auth_add_command(
        SimpleNamespace(
            provider=BETA_ALLOWED_PROVIDER,
            auth_type="oauth",
            api_key=None,
            label=None,
        )
    )

    payload = json.loads((beta_home / "auth.json").read_text(encoding="utf-8"))
    state = payload["providers"][BETA_ALLOWED_PROVIDER]
    assert state["tokens"] == {
        "access_token": "new-local-access",
        "refresh_token": "new-local-refresh",
    }
    assert state["auth_mode"] == "chatgpt"
    assert "credential_pool" not in payload
    assert BETA_ALLOWED_PROVIDER not in payload.get("suppressed_sources", {})
    assert read_beta_codex_auth_status(beta_home)["logged_in"] is True


def test_beta_auth_list_and_status_do_not_enumerate_inference_pools(
    beta_home,
    monkeypatch,
    capsys,
):
    from elevate_cli import auth_commands

    _write_auth(beta_home)
    monkeypatch.setattr(auth_commands, "load_pool", _unexpected)
    monkeypatch.setattr(auth_commands.auth_mod, "get_auth_status", _unexpected)

    auth_commands.auth_list_command(SimpleNamespace(provider=None))
    auth_commands.auth_status_command(
        SimpleNamespace(provider=BETA_ALLOWED_PROVIDER)
    )

    output = capsys.readouterr().out
    assert "current Beta profile" in output
    assert "openai-codex: connected" in output
    assert "openai-codex: logged in" in output


def test_beta_service_auth_status_remains_available(beta_home, monkeypatch, capsys):
    from elevate_cli import auth_commands

    seen = []
    monkeypatch.setattr(
        auth_commands.auth_mod,
        "get_auth_status",
        lambda provider: seen.append(provider) or {"logged_in": True},
    )

    auth_commands.auth_status_command(SimpleNamespace(provider="spotify"))

    assert seen == ["spotify"]
    assert "spotify: logged in" in capsys.readouterr().out


def test_beta_model_missing_auth_uses_no_provider_discovery_or_filesystem(
    beta_home,
    monkeypatch,
    capsys,
):
    from elevate_cli import main as main_module
    import elevate_cli.auth as auth_module

    monkeypatch.setattr(auth_module, "resolve_provider", _unexpected)
    monkeypatch.setattr(main_module, "_prompt_beta_codex_model", _unexpected)
    before = _tree_snapshot(beta_home)

    main_module.select_provider_and_model()

    assert "beta_codex_auth_required" in capsys.readouterr().out
    assert _tree_snapshot(beta_home) == before


def test_beta_model_picker_exposes_only_allowlist_and_repairs_legacy_provider(
    beta_home,
    monkeypatch,
):
    from elevate_cli import main as main_module
    import elevate_cli.auth as auth_module

    _write_auth(beta_home)
    config_path = beta_home / "config.yaml"
    config_path.write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    seen = {}

    def choose(models, current):
        seen["models"] = models
        seen["current"] = current
        return BETA_ALLOWED_MODELS[2]

    monkeypatch.setattr(auth_module, "resolve_provider", _unexpected)
    monkeypatch.setattr(main_module, "_prompt_beta_codex_model", choose)

    main_module.select_provider_and_model()

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert seen == {
        "models": BETA_ALLOWED_MODELS,
        "current": BETA_ALLOWED_MODELS[0],
    }
    assert written["model"] == {
        "provider": BETA_ALLOWED_PROVIDER,
        "default": BETA_ALLOWED_MODELS[2],
        "base_url": BETA_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }


def test_beta_model_rejects_unlisted_picker_result_without_mutation(
    beta_home,
    monkeypatch,
    capsys,
):
    from elevate_cli import main as main_module

    _write_auth(beta_home)
    config_path = beta_home / "config.yaml"
    before = b"model:\n  provider: openai-codex\n  default: gpt-5.5\n"
    config_path.write_bytes(before)
    monkeypatch.setattr(
        main_module,
        "_prompt_beta_codex_model",
        lambda *_args: "hostile-model",
    )

    main_module.select_provider_and_model()

    assert "beta_model_not_allowed" in capsys.readouterr().out
    assert config_path.read_bytes() == before


def test_beta_model_revalidates_auth_before_write(beta_home, monkeypatch, capsys):
    from elevate_cli import main as main_module

    _write_auth(beta_home)
    config_path = beta_home / "config.yaml"
    before = b"model:\n  provider: openai-codex\n  default: gpt-5.5\n"
    config_path.write_bytes(before)

    def expire_auth(*_args):
        (beta_home / "auth.json").write_text(
            json.dumps({"version": 1, "providers": {}}),
            encoding="utf-8",
        )
        return BETA_ALLOWED_MODELS[1]

    monkeypatch.setattr(main_module, "_prompt_beta_codex_model", expire_auth)

    main_module.select_provider_and_model()

    assert "beta_codex_auth_required" in capsys.readouterr().out
    assert config_path.read_bytes() == before


def test_beta_model_rejects_hostile_fallback_without_rewriting_bytes(
    beta_home,
    monkeypatch,
    capsys,
):
    from elevate_cli import main as main_module

    _write_auth(beta_home)
    config_path = beta_home / "config.yaml"
    config_path.write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n"
        "fallback_model:\n  provider: openrouter\n  model: hostile\n",
        encoding="utf-8",
    )
    before = config_path.read_bytes()
    monkeypatch.setattr(
        main_module,
        "_prompt_beta_codex_model",
        lambda *_args: BETA_ALLOWED_MODELS[1],
    )

    main_module.select_provider_and_model()

    assert "beta_fallback_not_allowed" in capsys.readouterr().out
    assert config_path.read_bytes() == before


def test_beta_low_level_provider_update_rejects_alternate_without_mutation(beta_home):
    from elevate_cli.auth import _update_config_for_provider

    _write_auth(beta_home)
    config_path = beta_home / "config.yaml"
    config_path.write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    config_before = config_path.read_bytes()
    auth_before = (beta_home / "auth.json").read_bytes()

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        _update_config_for_provider("anthropic", "https://api.anthropic.com")

    assert exc_info.value.code == "beta_provider_not_allowed"
    assert config_path.read_bytes() == config_before
    assert (beta_home / "auth.json").read_bytes() == auth_before


def test_beta_low_level_codex_update_uses_canonical_runtime_without_auth_mutation(
    beta_home,
):
    from elevate_cli.auth import _update_config_for_provider

    _write_auth(beta_home)
    auth_before = (beta_home / "auth.json").read_bytes()

    _update_config_for_provider(
        BETA_ALLOWED_PROVIDER,
        BETA_CODEX_BASE_URL,
        default_model=BETA_ALLOWED_MODELS[3],
    )

    written = yaml.safe_load((beta_home / "config.yaml").read_text(encoding="utf-8"))
    assert written["model"] == {
        "provider": BETA_ALLOWED_PROVIDER,
        "default": BETA_ALLOWED_MODELS[3],
        "base_url": BETA_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }
    assert (beta_home / "auth.json").read_bytes() == auth_before
