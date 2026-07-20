"""Exact Beta admits agent runtimes only through the in-app repair registry."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    clear_beta_runtime_repair_state,
)


def test_exact_beta_standalone_tui_gateway_requires_dashboard_sidecar(
    monkeypatch,
):
    from tui_gateway import entry

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.delenv("ELEVATE_TUI_SIDECAR_URL", raising=False)

    with pytest.raises(RuntimeError, match="launched from the Elevate app"):
        entry._install_sidecar_publisher()


def test_stable_standalone_tui_gateway_remains_supported(monkeypatch):
    from tui_gateway import entry

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    monkeypatch.delenv("ELEVATE_TUI_SIDECAR_URL", raising=False)

    assert entry._install_sidecar_publisher() is None


def test_exact_beta_accepted_sidecar_without_registry_ack_cannot_start(
    monkeypatch,
):
    from tui_gateway import entry, event_publisher, server

    class AcceptedButUnregisteredSocket:
        def __init__(self) -> None:
            self.sent = []
            self.closed = False

        def send(self, payload):
            self.sent.append(payload)

        def recv(self, timeout=None):
            raise TimeoutError("dashboard never acknowledged registration")

        def close(self):
            self.closed = True

    sockets = []

    def connect(*_args, **_kwargs):
        socket = AcceptedButUnregisteredSocket()
        sockets.append(socket)
        return socket

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv(
        "ELEVATE_TUI_SIDECAR_URL",
        "ws://127.0.0.1:9120/api/pub?token=test&channel=chat&instance="
        + "1" * 32,
    )
    monkeypatch.setattr(event_publisher, "ws_connect", connect)
    before_transport = server._stdio_transport
    server.install_exact_beta_sidecar_registration_check(None)

    with pytest.raises(RuntimeError, match="could not register"):
        entry._install_sidecar_publisher()

    assert sockets and sockets[0].sent
    assert server._stdio_transport is before_transport
    assert server._exact_beta_sidecar_registration_check is None


def test_exact_beta_cli_chat_and_direct_tui_stop_before_launch(monkeypatch):
    from elevate_cli import main

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        main,
        "_make_tui_argv",
        lambda *_args, **_kwargs: pytest.fail("standalone TUI launched"),
    )

    with pytest.raises(SystemExit) as tui_exit:
        main._launch_tui()
    with pytest.raises(SystemExit) as chat_exit:
        main.cmd_chat(SimpleNamespace())

    assert tui_exit.value.code == 1
    assert chat_exit.value.code == 1


def test_exact_beta_classic_model_picker_cannot_mutate_shared_config(
    monkeypatch,
    capsys,
):
    from elevate_cli import main
    from elevate_cli import config as config_module
    from elevate_cli import beta_provider_policy

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    for name in ("load_config", "read_raw_config", "save_config"):
        monkeypatch.setattr(
            config_module,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"classic picker used config {_name}"
            ),
        )
    monkeypatch.setattr(
        beta_provider_policy,
        "read_beta_codex_auth_status",
        lambda *_args, **_kwargs: pytest.fail("classic picker read Beta auth"),
    )

    assert main._select_beta_codex_model() is None
    assert "beta_app_onboarding_required" in capsys.readouterr().out


def test_exact_beta_cli_auth_mutations_require_in_app_onboarding(
    tmp_path,
    monkeypatch,
):
    from elevate_cli import auth as auth_module
    from elevate_cli import auth_commands, main

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    auth_path = tmp_path / "auth.json"
    before = json.dumps(
        {
            "active_provider": BETA_ALLOWED_PROVIDER,
            "providers": {
                BETA_ALLOWED_PROVIDER: {
                    "tokens": {
                        "access_token": "must-remain",
                        "refresh_token": "must-remain-refresh",
                    }
                }
            },
        }
    ).encode()
    auth_path.write_bytes(before)
    monkeypatch.setattr(
        auth_module,
        "clear_provider_auth",
        lambda *_args, **_kwargs: pytest.fail("CLI deleted Beta auth"),
    )
    monkeypatch.setattr(
        auth_module,
        "_save_codex_tokens",
        lambda *_args, **_kwargs: pytest.fail("CLI persisted Beta auth"),
    )
    monkeypatch.setattr(
        auth_module,
        "_codex_device_code_login",
        lambda *_args, **_kwargs: pytest.fail("CLI launched Beta OAuth"),
    )
    monkeypatch.setattr(
        auth_module,
        "get_active_provider",
        lambda: pytest.fail("CLI inspected auth before app-only guard"),
    )
    monkeypatch.setattr(
        auth_commands,
        "load_pool",
        lambda *_args, **_kwargs: pytest.fail("CLI mutated the credential pool"),
    )
    logout_args = SimpleNamespace(provider=BETA_ALLOWED_PROVIDER)
    remove_args = SimpleNamespace(
        auth_action="remove",
        provider=BETA_ALLOWED_PROVIDER,
        target="1",
    )
    auth_logout_args = SimpleNamespace(
        auth_action="logout",
        provider=BETA_ALLOWED_PROVIDER,
    )
    add_args = SimpleNamespace(
        auth_action="add",
        provider=BETA_ALLOWED_PROVIDER,
        auth_type="oauth",
        api_key=None,
        label=None,
    )

    entrypoints = (
        (main.cmd_login, logout_args),
        (main.cmd_logout, logout_args),
        (auth_commands.auth_add_command, add_args),
        (main.cmd_auth, add_args),
        (auth_commands.auth_logout_command, logout_args),
        (main.cmd_auth, auth_logout_args),
        (auth_commands.auth_remove_command, remove_args),
        (main.cmd_auth, remove_args),
        (main.cmd_auth, SimpleNamespace(auth_action="")),
    )
    for entrypoint, args in entrypoints:
        with pytest.raises(SystemExit) as caught:
            entrypoint(args)
        assert "beta_app_onboarding_required" in str(caught.value)

    assert auth_path.read_bytes() == before


def test_exact_beta_runtime_resolution_rejects_codex_app_server_escape(
    monkeypatch,
):
    from elevate_cli import runtime_provider
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    with pytest.raises(BetaProviderPolicyError) as caught:
        runtime_provider._maybe_apply_codex_app_server_runtime(
            provider=BETA_ALLOWED_PROVIDER,
            api_mode="codex_responses",
            model_cfg={"openai_runtime": "codex_app_server"},
        )

    assert caught.value.code == "beta_codex_app_server_not_allowed"


def test_exact_beta_codex_runtime_command_has_zero_spawn_or_mutation(
    monkeypatch,
):
    from elevate_cli import codex_runtime_switch

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = {
        "model": {
            "provider": BETA_ALLOWED_PROVIDER,
            "default": "gpt-5.5",
            "openai_runtime": "codex_app_server",
        }
    }
    before = json.loads(json.dumps(config))
    monkeypatch.setattr(
        codex_runtime_switch,
        "check_codex_binary_ok",
        lambda: pytest.fail("Beta /codex-runtime spawned an external binary"),
    )

    result = codex_runtime_switch.apply(
        config,
        "codex_app_server",
        persist_callback=lambda _config: pytest.fail(
            "Beta /codex-runtime persisted configuration"
        ),
    )

    assert result.success is False
    assert result.new_value is None
    assert "/codex-runtime is not available" in result.message
    assert config == before


def test_exact_beta_low_level_codex_runtime_setter_has_zero_mutation(
    monkeypatch,
):
    from elevate_cli import codex_runtime_switch
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = {"model": {"provider": BETA_ALLOWED_PROVIDER}}
    before = json.loads(json.dumps(config))

    with pytest.raises(BetaProviderPolicyError) as caught:
        codex_runtime_switch.set_runtime(config, "codex_app_server")

    assert caught.value.code == "beta_codex_app_server_not_allowed"
    assert config == before


def test_exact_beta_messaging_gateway_stops_before_runtime_side_effects(
    monkeypatch,
):
    from gateway import run
    from agent import turn_attribution

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        turn_attribution,
        "mark_persistent_process",
        lambda: pytest.fail("messaging runtime started"),
    )

    # Intentional disablement is a successful no-op so service supervisors do
    # not turn it into a permanent restart loop.
    assert asyncio.run(run.start_gateway()) is True


def test_exact_beta_foreground_gateway_command_exits_zero(monkeypatch):
    from elevate_cli import gateway

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    # ``run_gateway`` raises SystemExit only when start_gateway reports a real
    # failure. Exact Beta is deliberately disabled, so returning normally is
    # the process-level exit-0 contract.
    assert gateway.run_gateway() is None


def test_exact_beta_low_level_provider_mutation_requires_live_dashboard(
    tmp_path,
    monkeypatch,
):
    from elevate_cli import auth
    from elevate_cli.web_routes import chat_websockets

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    monkeypatch.setattr(
        chat_websockets,
        "_dashboard_repair_control_plane_ready",
        False,
    )
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "active_provider": BETA_ALLOWED_PROVIDER,
                "providers": {
                    BETA_ALLOWED_PROVIDER: {
                        "tokens": {
                            "access_token": "local-test-token",
                            "refresh_token": "local-test-refresh",
                        },
                        "auth_mode": "chatgpt",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    before = b"model:\n  provider: gemini\n  default: gemini-2.5-flash\n"
    config_path.write_bytes(before)
    clear_beta_runtime_repair_state()

    with pytest.raises(RuntimeError, match="running Elevate app"):
        auth._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )

    assert config_path.read_bytes() == before
    clear_beta_runtime_repair_state()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("model", "gpt-5.4"),
        ("model.provider", BETA_ALLOWED_PROVIDER),
        ("ANTHROPIC_API_KEY", "must-not-write"),
        ("terminal.backend", "docker"),
    ],
)
def test_exact_beta_legacy_config_set_has_zero_file_or_env_mutation(
    tmp_path,
    monkeypatch,
    key,
    value,
    capsys,
):
    from elevate_cli import config as config_module

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_before = b"model:\n  provider: openai-codex\n  default: gpt-5.5\n"
    env_before = b"EXISTING_KEY=preserve-me\n"
    config_path.write_bytes(config_before)
    env_path.write_bytes(env_before)

    with pytest.raises(SystemExit) as caught:
        config_module.set_config_value(key, value)

    assert caught.value.code == 1
    assert config_path.read_bytes() == config_before
    assert env_path.read_bytes() == env_before
    assert "beta_app_onboarding_required" in capsys.readouterr().err


def test_exact_beta_raw_config_edit_stops_before_editor_or_file_mutation(
    tmp_path,
    monkeypatch,
):
    from elevate_cli import config as config_module

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    monkeypatch.setenv("EDITOR", "synthetic-editor")
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_before = b"model:\n  provider: openai-codex\n  default: gpt-5.5\n"
    env_before = b"EXISTING_KEY=preserve-me\n"
    config_path.write_bytes(config_before)
    env_path.write_bytes(env_before)
    monkeypatch.setattr(
        config_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("raw config editor launched"),
    )

    with pytest.raises(SystemExit) as caught:
        config_module.edit_config()

    assert caught.value.code == 1
    assert config_path.read_bytes() == config_before
    assert env_path.read_bytes() == env_before


def test_exact_beta_legacy_config_migrate_stops_before_inspection_or_write(
    monkeypatch,
):
    from elevate_cli import config as config_module

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        config_module,
        "get_missing_env_vars",
        lambda *_args, **_kwargs: pytest.fail("legacy migration inspected config"),
    )

    with pytest.raises(SystemExit) as caught:
        config_module.config_command(SimpleNamespace(config_command="migrate"))

    assert caught.value.code == 1


def test_exact_beta_xai_apply_migration_cannot_bypass_app_model_writer(
    tmp_path,
    monkeypatch,
):
    from elevate_cli import migrate

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    before = b"model:\n  provider: xai\n  default: grok-3-mini-beta\n"
    config_path.write_bytes(before)

    with pytest.raises(SystemExit) as caught:
        migrate.cmd_migrate_xai(SimpleNamespace(apply=True, no_backup=False))

    assert caught.value.code == 1
    assert config_path.read_bytes() == before
    assert list(tmp_path.glob("config.yaml.bak-pre-migrate-xai-*")) == []
