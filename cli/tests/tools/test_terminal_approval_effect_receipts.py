"""Terminal integration tests for exact-Beta durable effect receipts."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from elevate_state import SessionDB
from gateway.session_context import clear_session_vars, set_session_vars
from model_tools import handle_function_call
from tools import approval
from tools import process_registry as process_registry_module
import tools.terminal_tool as terminal_module
import tools.tirith_security


_COMMAND = "rm -rf /tmp/elevate-receipt-test"


def _config(tmp_path):
    return {
        "env_type": "local",
        "timeout": 30,
        "cwd": str(tmp_path),
        "host_cwd": None,
        "modal_mode": "auto",
        "docker_image": "",
        "singularity_image": "",
        "modal_image": "",
        "daytona_image": "",
    }


def _install_exact_beta_path(
    monkeypatch,
    tmp_path,
    *,
    execute,
    claim,
    complete,
    start_cleanup=lambda: None,
):
    env = SimpleNamespace(execute=execute, env={})
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(terminal_module, "_get_env_config", lambda: _config(tmp_path))
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", start_cleanup)
    monkeypatch.setattr(
        terminal_module,
        "_check_all_guards",
        lambda *_args, **_kwargs: {
            "approved": True,
            "user_approved": True,
            "description": "dangerous test command",
            "_approval_effect_entry": object(),
        },
    )
    monkeypatch.setattr(approval, "claim_approved_effect", claim)
    monkeypatch.setattr(approval, "complete_approved_effect_claim", complete)
    monkeypatch.setitem(terminal_module._active_environments, "default", env)
    monkeypatch.setitem(terminal_module._last_activity, "default", 0.0)
    return env


def _invoke(*, background: bool = False) -> dict:
    tool_args = {
        "command": _COMMAND,
        **({"background": True} if background else {}),
    }
    policy = approval.ExecutionPolicy.for_mode("turn-mocked-effect", "default")
    effect_context = approval.ApprovalEffectContext(
        session_id="session-mocked-effect",
        invocation_id="call-mocked-effect",
        tool_name="terminal",
        canonical_args_digest=approval._approval_sha256(tool_args),
        accepted_policy=policy,
        policy_revision=0,
        declared_effects={"destructive"},
    )
    return json.loads(
        terminal_module.terminal_tool(
            command=_COMMAND,
            background=background,
            _approval_effect_context=effect_context,
            _approval_tool_args=tool_args,
        )
    )


def test_exact_beta_missing_context_never_reaches_environment(monkeypatch, tmp_path):
    calls = []

    def execute(*_args, **_kwargs):
        calls.append("executed")
        return {"output": "unexpected", "returncode": 0}

    env = SimpleNamespace(execute=execute, env={})
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(terminal_module, "_get_env_config", lambda: _config(tmp_path))
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", lambda: None)
    monkeypatch.setitem(terminal_module._active_environments, "default", env)

    result = json.loads(terminal_module.terminal_tool(command="ls"))

    assert result["status"] == "effect_context_block"
    assert calls == []


def test_terminal_effect_resolver_has_a_narrow_explicit_read_lane():
    assert {
        str(effect)
        for effect in terminal_module._terminal_effect_resolver({"command": "ls -la"})
    } == {"read"}
    for command in (
        "python3 -c 'print(1)'",
        "echo changed > file.txt",
        "curl https://example.com",
        "git push origin main",
        "ls | wc -l",
        "rg --pre 'touch marker' pattern",
        "tree -o listing.txt",
    ):
        assert {
            str(effect)
            for effect in terminal_module._terminal_effect_resolver(
                {"command": command}
            )
        } == {"destructive"}
    assert {
        str(effect)
        for effect in terminal_module._terminal_effect_resolver(
            {"command": "ls", "background": True}
        )
    } == {"read", "spawn"}


def test_claim_persistence_failure_prevents_invocation(monkeypatch, tmp_path):
    calls = []

    def execute(*_args, **_kwargs):
        calls.append("executed")
        return {"output": "must not run", "returncode": 0}

    def fail_claim(*_args, **_kwargs):
        raise OSError("state store unavailable")

    completions = []
    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=execute,
        claim=fail_claim,
        complete=lambda *_args, **kwargs: completions.append(kwargs) or True,
    )

    result = _invoke()

    assert result["status"] == "blocked"
    assert calls == []
    assert completions == []


def test_final_receipt_failure_suppresses_success_output(monkeypatch, tmp_path):
    calls = []
    completions = []

    def execute(*_args, **_kwargs):
        calls.append("executed")
        return {"output": "looks successful", "returncode": 0}

    def complete(_claim, **kwargs):
        completions.append(kwargs)
        return False

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=execute,
        claim=lambda *_args, **_kwargs: object(),
        complete=complete,
    )

    result = _invoke()

    assert calls == ["executed"]
    assert result["status"] == "effect_outcome_unknown"
    assert result["output"] == ""
    assert "looks successful" not in json.dumps(result)
    assert [item["status"] for item in completions] == [
        "succeeded",
        "unknown",
    ]


def test_nonzero_exit_code_persists_truthful_failed_receipt(
    monkeypatch,
    tmp_path,
):
    completions = []

    def complete(_claim, **kwargs):
        completions.append(kwargs)
        return True

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=lambda *_args, **_kwargs: {"output": "no matches", "returncode": 2},
        claim=lambda *_args, **_kwargs: object(),
        complete=complete,
    )

    result = _invoke()

    assert result["exit_code"] == 2
    assert completions == [
        {
            "status": "failed",
            "result_identity": {"background": False, "returncode": 2},
            "failure_code": "command_exit_nonzero",
        }
    ]


def test_sessiondb_backed_terminal_claims_executes_and_receipts_once(
    monkeypatch,
    tmp_path,
):
    """Exercise registry -> guard -> grant -> claim -> env -> receipt as one path."""
    session_key = "beta-effect-integration"
    actor = "beta-user"
    correlation_id = "corr_" + "9" * 32
    command = "ls"
    invocation_id = "call-real-effect"
    db = SessionDB(tmp_path / "state.db")
    executions = []
    env = SimpleNamespace(env={})

    def execute(received_command, **_kwargs):
        executions.append(received_command)
        return {"output": "listing", "returncode": 0}

    env.execute = execute
    policy = approval.ExecutionPolicy.for_mode("turn-real-effect", "read_only")
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="chat-real-effect",
        thread_id="thread-real-effect",
        user_id=actor,
        session_key=session_key,
        message_id="message-real-effect",
        correlation_id=correlation_id,
    )
    policy_token = approval.set_current_execution_policy(
        policy,
        policy_revision=7,
    )

    def approve_exact_request(data):
        assert (
            approval.resolve_gateway_approval(
                session_key,
                "once",
                request_id=data["request_id"],
                resolver_identity=actor,
                resolver_context={
                    "actor_id": actor,
                    "platform": "telegram",
                    "chat_id": "chat-real-effect",
                    "thread_id": "thread-real-effect",
                    "origin_message_id": "message-real-effect",
                },
            )
            == 1
        )

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_INTERACTIVE", "1")
    monkeypatch.setattr(terminal_module, "_get_env_config", lambda: _config(tmp_path))
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        tools.tirith_security,
        "check_command_security",
        lambda _command: {
            "action": "warn",
            "findings": [
                {
                    "rule_id": "integration-review",
                    "severity": "medium",
                    "title": "Test review",
                    "description": "Exercise the approval path",
                }
            ],
            "summary": "test review",
        },
    )
    monkeypatch.setitem(terminal_module._active_environments, "default", env)
    monkeypatch.setitem(terminal_module._last_activity, "default", 0.0)
    approval.register_gateway_notify(
        session_key,
        approve_exact_request,
        approval_store=db,
    )

    def invoke():
        with patch("elevate_cli.plugins.invoke_hook", return_value=[]):
            return json.loads(
                handle_function_call(
                    "terminal",
                    {"command": command},
                    session_id="session-real-effect",
                    tool_call_id=invocation_id,
                    skip_pre_tool_call_hook=True,
                )
            )

    try:
        first = invoke()
        assert first["exit_code"] == 0
        assert first["output"] == "listing"
        assert executions == [command]
        receipts = db._conn.execute("SELECT * FROM approval_effect_receipts").fetchall()
        assert len(receipts) == 1
        assert receipts[0]["status"] == "succeeded"
        assert receipts[0]["session_id"] == "session-real-effect"
        assert receipts[0]["invocation_id"] == invocation_id
        assert receipts[0]["result_digest"] is not None
        assert receipts[0]["failure_code"] is None
        first_claim_id = receipts[0]["claim_id"]

        # The same invocation may create another reviewed request, but the
        # durable invocation uniqueness constraint prevents a second claim or
        # a second command execution.
        duplicate = invoke()
        assert duplicate["status"] == "blocked"
        assert executions == [command]
        assert (
            db._conn.execute(
                "SELECT COUNT(*) FROM approval_effect_receipts"
            ).fetchone()[0]
            == 1
        )
        assert db.get_approval_effect_receipt(first_claim_id)["status"] == ("succeeded")

        # Simulate a process restart with a new logical boot. A completed
        # receipt remains the invocation authority; it is not reopened by
        # startup cleanup or a newly approved request.
        old_boot = approval._APPROVAL_BOOT_ID
        db._conn.execute(
            "UPDATE state_meta SET value = ? WHERE key = 'approval_grants.active_boot'",
            (
                json.dumps(
                    {
                        "boot_id": old_boot,
                        "owners": [
                            {
                                "process_id": 1_000_000_000,
                                "process_start_id": "crashed-process",
                                "process_create_time": 1.0,
                            }
                        ],
                        "activated_at": time.time(),
                    }
                ),
            ),
        )
        db._conn.commit()
        monkeypatch.setattr(approval, "_APPROVAL_BOOT_ID", "8" * 32)
        approval._initialized_approval_stores.discard(approval._approval_store_key(db))
        approval.register_gateway_notify(
            session_key,
            approve_exact_request,
            approval_store=db,
        )

        after_restart = invoke()
        assert after_restart["status"] == "blocked"
        assert executions == [command]
        assert (
            db._conn.execute(
                "SELECT COUNT(*) FROM approval_effect_receipts"
            ).fetchone()[0]
            == 1
        )
        assert db.get_approval_effect_receipt(first_claim_id)["status"] == ("succeeded")
    finally:
        approval.unregister_gateway_notify(session_key)
        approval.clear_session(session_key)
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)


def test_sessiondb_backed_terminal_nonzero_exit_receipts_failed(
    monkeypatch,
    tmp_path,
):
    session_key = "beta-effect-failure"
    actor = "beta-user-failure"
    correlation_id = "corr_" + "7" * 32
    db = SessionDB(tmp_path / "state.db")
    env = SimpleNamespace(
        env={},
        execute=lambda *_args, **_kwargs: {"output": "failed", "returncode": 2},
    )
    policy = approval.ExecutionPolicy.for_mode("turn-real-failure", "read_only")
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="chat-real-failure",
        user_id=actor,
        session_key=session_key,
        message_id="message-real-failure",
        correlation_id=correlation_id,
    )
    policy_token = approval.set_current_execution_policy(policy, policy_revision=8)

    def approve(data):
        assert (
            approval.resolve_gateway_approval(
                session_key,
                "once",
                request_id=data["request_id"],
                resolver_identity=actor,
                resolver_context={
                    "actor_id": actor,
                    "platform": "telegram",
                    "chat_id": "chat-real-failure",
                },
            )
            == 1
        )

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_INTERACTIVE", "1")
    monkeypatch.setattr(terminal_module, "_get_env_config", lambda: _config(tmp_path))
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        tools.tirith_security,
        "check_command_security",
        lambda _command: {
            "action": "warn",
            "findings": [{"rule_id": "integration-failure"}],
            "summary": "test review",
        },
    )
    monkeypatch.setitem(terminal_module._active_environments, "default", env)
    monkeypatch.setitem(terminal_module._last_activity, "default", 0.0)
    approval.register_gateway_notify(session_key, approve, approval_store=db)
    try:
        with patch("elevate_cli.plugins.invoke_hook", return_value=[]):
            result = json.loads(
                handle_function_call(
                    "terminal",
                    {"command": "ls"},
                    session_id="session-real-failure",
                    tool_call_id="call-real-failure",
                    skip_pre_tool_call_hook=True,
                )
            )
        receipt = db._conn.execute("SELECT * FROM approval_effect_receipts").fetchone()
        assert result["exit_code"] == 2
        assert receipt["status"] == "failed"
        assert receipt["failure_code"] == "command_exit_nonzero"
        assert receipt["result_digest"] is not None
    finally:
        approval.unregister_gateway_notify(session_key)
        approval.clear_session(session_key)
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)


def test_execution_exception_is_unknown_and_never_retried(monkeypatch, tmp_path):
    attempts = []
    completions = []

    def execute(*_args, **_kwargs):
        attempts.append("attempt")
        raise TimeoutError("outcome unavailable")

    def complete(_claim, **kwargs):
        completions.append(kwargs)
        return True

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=execute,
        claim=lambda *_args, **_kwargs: object(),
        complete=complete,
    )

    result = _invoke()

    assert attempts == ["attempt"]
    assert result["status"] == "effect_outcome_unknown"
    assert completions == [
        {
            "status": "unknown",
            "result_identity": None,
            "failure_code": "foreground_execution_outcome_unknown",
        }
    ]


def test_preinvoke_handler_exception_is_durable_failure(monkeypatch, tmp_path):
    calls = []
    completions = []

    def execute(*_args, **_kwargs):
        calls.append("executed")
        return {"output": "unexpected", "returncode": 0}

    def complete(_claim, **kwargs):
        completions.append(kwargs)
        return True

    def fail_cleanup():
        raise RuntimeError("cleanup startup failed")

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=execute,
        claim=lambda *_args, **_kwargs: object(),
        complete=complete,
        start_cleanup=fail_cleanup,
    )

    result = _invoke()

    assert calls == []
    assert result["status"] == "error"
    assert completions == [
        {
            "status": "failed",
            "result_identity": None,
            "failure_code": "terminal_preinvoke_exception",
        }
    ]


def test_background_spawn_requires_success_receipt_before_success_output(
    monkeypatch,
    tmp_path,
):
    spawns = []
    completions = []

    def spawn(**kwargs):
        spawns.append(kwargs)
        return SimpleNamespace(id="proc-effect", pid=1234, notify_on_complete=False)

    def complete(_claim, **kwargs):
        completions.append(kwargs)
        return True

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=lambda *_args, **_kwargs: None,
        claim=lambda *_args, **_kwargs: object(),
        complete=complete,
    )
    monkeypatch.setattr(
        process_registry_module.process_registry,
        "spawn_local",
        spawn,
    )

    result = _invoke(background=True)

    assert len(spawns) == 1
    assert result["session_id"] == "proc-effect"
    assert result["exit_code"] == 0
    assert completions == [
        {
            "status": "succeeded",
            "result_identity": {
                "background": True,
                "effect": "process_started",
            },
            "failure_code": None,
        }
    ]


def test_background_spawn_receipt_failure_suppresses_started_result(
    monkeypatch,
    tmp_path,
):
    spawns = []

    def spawn(**kwargs):
        spawns.append(kwargs)
        return SimpleNamespace(id="proc-ambiguous", pid=1235, notify_on_complete=False)

    _install_exact_beta_path(
        monkeypatch,
        tmp_path,
        execute=lambda *_args, **_kwargs: None,
        claim=lambda *_args, **_kwargs: object(),
        complete=lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        process_registry_module.process_registry,
        "spawn_local",
        spawn,
    )

    result = _invoke(background=True)

    assert len(spawns) == 1
    assert result["status"] == "effect_outcome_unknown"
    assert "proc-ambiguous" not in json.dumps(result)
