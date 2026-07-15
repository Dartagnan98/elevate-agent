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
    permanent_before = set(approval._permanent_approved)
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
    with approval._lock:
        approval._permanent_approved.clear()
        approval._permanent_approved.update(permanent_before)


def _deny(*_args, **_kwargs) -> str:
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


def test_exact_beta_normalizes_smart_to_manual_without_llm_approval(monkeypatch):
    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: {"mode": "smart"},
    )
    monkeypatch.setattr(
        approval,
        "_smart_approve",
        lambda *_args: pytest.fail("exact Beta must not ask an LLM to approve"),
    )

    assert approval._get_approval_mode() == "manual"
    assert _combined_result()["approved"] is False


def test_exact_beta_noninteractive_dangerous_commands_fail_closed(monkeypatch):
    monkeypatch.delenv("ELEVATE_INTERACTIVE")

    direct = approval.check_dangerous_command(_DANGEROUS_COMMAND, "local")
    combined = approval.check_all_command_guards(_DANGEROUS_COMMAND, "local")

    for result in (direct, combined):
        assert result["approved"] is False
        assert result["status"] == "human_approval_required"
        assert "Realtor Beta" in result["message"]
        assert "interactive" in result["message"]
        assert "approve that specific command" in result["message"]


def test_exact_beta_noninteractive_safe_command_still_runs(monkeypatch):
    monkeypatch.delenv("ELEVATE_INTERACTIVE")

    assert approval.check_dangerous_command("pwd", "local")["approved"] is True
    assert approval.check_all_command_guards("pwd", "local")["approved"] is True


def test_exact_beta_noninteractive_tirith_warning_fails_closed(monkeypatch):
    monkeypatch.delenv("ELEVATE_INTERACTIVE")
    monkeypatch.setattr(
        tools.tirith_security,
        "check_command_security",
        lambda _command: {
            "action": "warn",
            "findings": [
                {
                    "rule_id": "shortened_url",
                    "severity": "medium",
                    "title": "Shortened URL",
                    "description": "The destination is hidden",
                }
            ],
            "summary": "shortened URL",
        },
    )

    result = approval.check_all_command_guards(
        "curl https://bit.ly/example",
        "local",
    )

    assert result["approved"] is False
    assert result["pattern_key"] == "tirith:shortened_url"
    assert result["status"] == "human_approval_required"
    assert "Shortened URL" in result["message"]


def test_exact_beta_ignores_stale_session_and_permanent_allowlists(monkeypatch):
    _, pattern_key, _ = approval.detect_dangerous_command(_DANGEROUS_COMMAND)
    assert pattern_key

    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL")
    approval.approve_session(_SESSION_KEY, pattern_key)
    approval.approve_permanent(pattern_key)
    assert approval.is_approved(_SESSION_KEY, pattern_key) is True

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    assert approval.is_approved(_SESSION_KEY, pattern_key) is False
    assert approval.check_dangerous_command(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=_deny,
    )["approved"] is False
    assert _combined_result()["approved"] is False


@pytest.mark.parametrize("guard", ["direct", "combined"])
@pytest.mark.parametrize("choice", ["once", "session", "always"])
def test_exact_beta_cli_callback_cannot_bypass_durable_approval_bridge(
    monkeypatch,
    choice,
    guard,
):
    save = []
    monkeypatch.setattr(
        approval,
        "save_permanent_allowlist",
        lambda patterns: save.append(set(patterns)),
    )

    check = (
        approval.check_dangerous_command
        if guard == "direct"
        else approval.check_all_command_guards
    )
    first = check(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=lambda *_args, **_kwargs: choice,
    )
    second = check(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=_deny,
    )
    _, pattern_key, _ = approval.detect_dangerous_command(_DANGEROUS_COMMAND)

    assert first["approved"] is False
    assert first["status"] == "approval_bridge_unavailable"
    assert second["approved"] is False
    assert approval.is_approved(_SESSION_KEY, pattern_key) is False
    assert save == []


@pytest.mark.parametrize(
    "check",
    [approval.check_dangerous_command, approval.check_all_command_guards],
)
def test_exact_beta_invalid_callback_choice_fails_closed(check):
    result = check(
        _DANGEROUS_COMMAND,
        "local",
        approval_callback=lambda *_args, **_kwargs: "approve",
    )

    assert result["approved"] is False


@pytest.mark.parametrize("choice", ["once", "session", "always"])
def test_exact_beta_gateway_resolver_reduces_affirmative_scope_to_once(
    monkeypatch,
    choice,
    tmp_path,
):
    from elevate_state import SessionDB
    from gateway.session_context import clear_session_vars, set_session_vars

    db = SessionDB(tmp_path / "state.db")
    approval._initialize_approval_store(db)
    policy = approval.ExecutionPolicy.for_mode("turn-beta-resolver", "default")
    effect_context = approval.ApprovalEffectContext(
        session_id="session-beta-resolver",
        invocation_id="call-beta-resolver",
        tool_name="terminal",
        canonical_args_digest=approval._approval_sha256(
            {"command": _DANGEROUS_COMMAND}
        ),
        accepted_policy=policy,
        policy_revision=0,
        declared_effects={"destructive"},
    )
    session_tokens = set_session_vars(
        platform="gateway",
        chat_id=_SESSION_KEY,
        user_id="u1",
        session_key=_SESSION_KEY,
        correlation_id="corr_" + "d" * 32,
    )
    policy_token = approval.set_current_execution_policy(
        policy,
        policy_revision=0,
    )
    try:
        entry = approval._ApprovalEntry(
            {"command": _DANGEROUS_COMMAND},
            grant_store=db,
            effect_context=effect_context,
        )
        assert approval._prepare_durable_approval_grant(
            entry,
            _SESSION_KEY,
            _DANGEROUS_COMMAND,
            timeout_seconds=300,
        )
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)
    monkeypatch.setattr(
        approval,
        "_record_approval_receipt",
        lambda *_args, **_kwargs: None,
    )
    with approval._lock:
        approval._gateway_queues[_SESSION_KEY] = [entry]

    resolved = approval.resolve_gateway_approval(
        _SESSION_KEY,
        choice,
        request_id=entry.request_id,
        resolver_identity="u1",
        resolver_context={
            "actor_id": "u1",
            "platform": "gateway",
            "chat_id": _SESSION_KEY,
        },
    )

    assert resolved == 1
    assert entry.result == "once"


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


def test_case_mismatched_beta_preserves_session_allowlist_compatibility(monkeypatch):
    _, pattern_key, _ = approval.detect_dangerous_command(_DANGEROUS_COMMAND)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    approval.approve_session(_SESSION_KEY, pattern_key)

    assert approval.is_approved(_SESSION_KEY, pattern_key) is True
    assert _combined_result()["approved"] is True


def test_case_mismatched_beta_preserves_smart_approval(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: {"mode": "smart"},
    )
    calls = []
    monkeypatch.setattr(
        approval,
        "_smart_approve",
        lambda *args: calls.append(args) or "approve",
    )

    result = approval.check_all_command_guards(_DANGEROUS_COMMAND, "local")

    assert result["approved"] is True
    assert result["smart_approved"] is True
    assert len(calls) == 1
