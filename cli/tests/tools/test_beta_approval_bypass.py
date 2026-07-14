"""Exact Realtor Beta cannot inherit legacy approval bypass state."""

import os
from unittest.mock import patch

import pytest

import tools.approval as approval
import tools.tirith_security


_SESSION_KEY = "beta-approval-bypass"
_DANGEROUS_COMMAND = "rm -rf /tmp/elevate-beta-test"


@pytest.fixture(autouse=True)
def _isolated_approval_state(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_INTERACTIVE", "1")
    monkeypatch.setenv("ELEVATE_SESSION_KEY", _SESSION_KEY)
    monkeypatch.delenv("ELEVATE_GATEWAY_SESSION", raising=False)
    monkeypatch.delenv("ELEVATE_EXEC_ASK", raising=False)
    monkeypatch.delenv("ELEVATE_CRON_SESSION", raising=False)
    monkeypatch.delenv("ELEVATE_YOLO_MODE", raising=False)
    approval.clear_session(_SESSION_KEY)
    monkeypatch.setattr(
        tools.tirith_security,
        "check_command_security",
        lambda _command: {"action": "allow", "findings": [], "summary": ""},
    )
    yield
    approval.clear_session(_SESSION_KEY)


def _deny(*_args) -> str:
    return "deny"


def _combined_result() -> dict:
    return approval.check_all_command_guards(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=_deny,
    )


def test_exact_beta_ignores_process_yolo(monkeypatch):
    monkeypatch.setenv("ELEVATE_YOLO_MODE", "1")

    direct = approval.check_dangerous_command(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=_deny,
    )
    combined = _combined_result()

    assert direct["approved"] is False
    assert combined["approved"] is False


def test_exact_beta_ignores_stale_session_yolo(monkeypatch):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL")
    approval.enable_session_yolo(_SESSION_KEY)
    assert approval.is_session_yolo_enabled(_SESSION_KEY) is True

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    assert approval.is_session_yolo_enabled(_SESSION_KEY) is False
    assert _combined_result()["approved"] is False


def test_exact_beta_ignores_approvals_mode_off(monkeypatch):
    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: {"mode": "off"},
    )

    assert approval._get_approval_mode() == "manual"
    assert _combined_result()["approved"] is False


def test_exact_beta_ignores_bypass_permissions():
    approval.set_session_permission_mode(_SESSION_KEY, "bypassPermissions")

    assert approval.get_session_permission_mode(_SESSION_KEY) == "bypassPermissions"
    assert _combined_result()["approved"] is False


def test_exact_beta_cron_approve_config_still_denies(monkeypatch):
    monkeypatch.setenv("ELEVATE_CRON_SESSION", "1")
    monkeypatch.delenv("ELEVATE_INTERACTIVE")
    with patch(
        "elevate_cli.config.load_config",
        return_value={"approvals": {"cron_mode": "approve"}},
    ):
        assert approval._get_cron_approval_mode() == "deny"
        direct = approval.check_dangerous_command(_DANGEROUS_COMMAND, "local")
        combined = approval.check_all_command_guards(_DANGEROUS_COMMAND, "local")

    assert direct["approved"] is False
    assert combined["approved"] is False
    assert "Realtor Beta" in direct["message"]
    assert "Realtor Beta" in combined["message"]


def test_exact_beta_classic_yolo_command_is_rejected_without_env_mutation(
    monkeypatch,
):
    import cli as cli_module

    monkeypatch.delenv("ELEVATE_YOLO_MODE", raising=False)
    output: list[str] = []
    monkeypatch.setattr(cli_module, "_cprint", output.append)
    cli = cli_module.ElevateCLI.__new__(cli_module.ElevateCLI)

    cli._toggle_yolo()

    assert "ELEVATE_YOLO_MODE" not in os.environ
    assert output and "unavailable" in output[-1].lower()


@pytest.mark.parametrize("bypass", ["process_yolo", "mode_off", "permission"])
def test_stable_preserves_interactive_bypass_compatibility(monkeypatch, bypass):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL")
    if bypass == "process_yolo":
        monkeypatch.setenv("ELEVATE_YOLO_MODE", "1")
    elif bypass == "mode_off":
        monkeypatch.setattr(
            approval,
            "_get_approval_config",
            lambda: {"mode": "off"},
        )
    else:
        approval.set_session_permission_mode(_SESSION_KEY, "bypassPermissions")

    assert _combined_result()["approved"] is True


def test_stable_preserves_cron_approve_compatibility(monkeypatch):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL")
    monkeypatch.setenv("ELEVATE_CRON_SESSION", "1")
    monkeypatch.delenv("ELEVATE_INTERACTIVE")
    with patch(
        "elevate_cli.config.load_config",
        return_value={"approvals": {"cron_mode": "approve"}},
    ):
        assert approval._get_cron_approval_mode() == "approve"
        result = approval.check_all_command_guards(_DANGEROUS_COMMAND, "local")

    assert result["approved"] is True
