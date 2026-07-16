"""Exact-Beta provider containment for the scheduled LLM execution path."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import cron.scheduler as scheduler
import run_agent
from elevate_cli.auth import AuthError
from elevate_cli.beta_provider_policy import BetaProviderPolicyError


_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def _codex_runtime(home, token: str = "codex-current-token") -> dict:
    return {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": _CODEX_BASE_URL,
        "api_key": token,
        "source": "elevate-auth-store",
        "auth_store": str(home / "auth.json"),
        "requested_provider": "openai-codex",
    }


def _write_beta_auth(home) -> None:
    (home / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai-codex": {
                        "tokens": {
                            "access_token": "profile-access-token",
                            "refresh_token": "profile-refresh-token",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _prepare_beta_cron(monkeypatch, tmp_path) -> MagicMock:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    # The shipped Realtor Beta blocks scheduled execution at run_job(). These
    # tests exercise the defense-in-depth provider firewall below that public
    # entrypoint, so explicitly open only the policy seam in this unit module.
    monkeypatch.setattr(scheduler, "scheduled_execution_disabled_reason", lambda: None)
    monkeypatch.delenv("ELEVATE_MODEL", raising=False)
    monkeypatch.delenv("ELEVATE_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(scheduler, "_hermes_home", tmp_path)
    monkeypatch.setattr(scheduler, "_build_job_prompt", lambda job, **_kwargs: job["prompt"])
    monkeypatch.setattr(scheduler, "_resolve_delivery_target", lambda _job: None)
    monkeypatch.setattr(scheduler, "_resolve_cron_enabled_toolsets", lambda _job, _cfg: [])
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("tools.mcp_tool.discover_mcp_tools", lambda: [])
    monkeypatch.setattr("agent.auxiliary_client.cleanup_stale_async_clients", lambda: None)
    fake_db = MagicMock()
    monkeypatch.setattr("elevate_state.SessionDB", lambda: fake_db)
    _write_beta_auth(tmp_path)
    return fake_db


class _RecordingAgent:
    created: list[dict] = []
    events: list[str] = []
    result: object = {"final_response": "scheduled work complete"}

    def __init__(self, **kwargs):
        type(self).created.append(dict(kwargs))
        type(self).events.append("agent-created")

    def run_conversation(self, _prompt):
        value = type(self).result
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        return None


def _install_recording_agent(monkeypatch, result) -> None:
    _RecordingAgent.created = []
    _RecordingAgent.events = []
    _RecordingAgent.result = result
    monkeypatch.setattr(run_agent, "AIAgent", _RecordingAgent)


def _patch_tick_shell(monkeypatch, tmp_path, job: dict) -> tuple[MagicMock, MagicMock, MagicMock]:
    monkeypatch.setattr(scheduler, "get_due_jobs", lambda: [job])
    monkeypatch.setattr(scheduler, "advance_next_run", lambda _job_id: None)
    monkeypatch.setattr(scheduler, "_should_ensure_system_jobs", lambda: False)
    monkeypatch.setattr(scheduler, "_maybe_reap_idle_sessions", lambda: None)
    monkeypatch.setattr(scheduler, "_precreate_cron_session", lambda *_args: False)
    monkeypatch.setattr(scheduler, "_kill_orphaned_mcp_children", lambda: None, raising=False)
    save = MagicMock(return_value=str(tmp_path / "run.md"))
    mark = MagicMock()
    deliver = MagicMock(return_value=None)
    monkeypatch.setattr(scheduler, "save_job_output", save)
    monkeypatch.setattr(scheduler, "mark_job_run", mark)
    monkeypatch.setattr(scheduler, "_deliver_result", deliver)
    monkeypatch.setattr(scheduler, "_record_agent_handoff_delivery", lambda *_args, **_kwargs: None)
    return save, mark, deliver


def test_beta_cron_fresh_resolves_immediately_before_agent_and_strips_alternates(
    monkeypatch, tmp_path
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    (tmp_path / "config.yaml").write_text(
        """
model:
  provider: openai-codex
  default: gpt-5.5
provider_routing:
  only: [openrouter]
  order: [anthropic, openrouter]
""".lstrip(),
        encoding="utf-8",
    )
    _install_recording_agent(monkeypatch, {"final_response": "done"})

    events: list[str] = []
    calls: list[dict] = []

    def resolve(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            events.append("initial-resolve")
            return _codex_runtime(tmp_path, "stale-token")
        events.append("final-resolve")
        _RecordingAgent.events = events
        return _codex_runtime(tmp_path, "fresh-token")

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool_load = MagicMock(side_effect=AssertionError("credential pool must stay closed"))
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    success, output, final_response, error = scheduler.run_job(
        {
            "id": "beta-fresh",
            "name": "Beta fresh runtime",
            "prompt": "Do the scheduled task.",
            "model": "gpt-5.5",
        }
    )

    assert (success, final_response, error) == (True, "done", None)
    assert "done" in output
    assert calls == [
        {"requested": None, "target_model": "gpt-5.5"},
        {"requested": "openai-codex", "target_model": "gpt-5.5"},
    ]
    assert events[-2:] == ["final-resolve", "agent-created"]
    assert len(_RecordingAgent.created) == 1
    kwargs = _RecordingAgent.created[0]
    assert kwargs["provider"] == "openai-codex"
    assert kwargs["api_mode"] == "codex_responses"
    assert kwargs["base_url"] == _CODEX_BASE_URL
    assert kwargs["api_key"] == "fresh-token"
    assert kwargs["fallback_model"] is None
    assert kwargs["credential_pool"] is None
    assert kwargs["providers_allowed"] is None
    assert kwargs["providers_ignored"] is None
    assert kwargs["providers_order"] is None
    assert kwargs["provider_sort"] is None
    pool_load.assert_not_called()


@pytest.mark.parametrize(
    ("config_tail", "code"),
    [
        (
            "fallback_providers:\n  - provider: openrouter\n    model: openai/gpt-4o\n",
            "beta_fallback_not_allowed",
        ),
        (
            "custom_providers:\n  local-escape:\n    base_url: http://127.0.0.1:9000/v1\n",
            "beta_custom_provider_not_allowed",
        ),
    ],
)
def test_beta_cron_denies_persisted_fallback_and_custom_config_before_resolution(
    monkeypatch, tmp_path, config_tail, code
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n" + config_tail,
        encoding="utf-8",
    )
    _install_recording_agent(monkeypatch, {"final_response": "must not run"})
    resolve = MagicMock(return_value=_codex_runtime(tmp_path))
    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool_load = MagicMock()
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    success, output, final_response, error = scheduler.run_job(
        {"id": f"blocked-{code}", "name": "blocked", "prompt": "run"}
    )

    assert success is False
    assert final_response == ""
    assert f"Error [{code}]" in error
    assert f"Error [{code}]" in output
    resolve.assert_not_called()
    pool_load.assert_not_called()
    assert _RecordingAgent.created == []


@pytest.mark.parametrize(
    "hostile_patch",
    [
        {"provider": "openrouter", "api_key": "alternate-key"},
        {"base_url": "https://attacker.invalid/v1"},
        {"source": "credential-pool", "credential_pool": object()},
        {"command": "alternate-provider-client", "args": ["--escape"]},
        {"auth_store": "/tmp/not-current-profile/auth.json"},
    ],
)
def test_beta_cron_rejects_hostile_final_runtime_without_creating_any_agent(
    monkeypatch, tmp_path, hostile_patch
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    _install_recording_agent(monkeypatch, {"final_response": "must not run"})
    calls = 0

    def resolve(**_kwargs):
        nonlocal calls
        calls += 1
        runtime = _codex_runtime(tmp_path)
        if calls == 2:
            runtime.update(hostile_patch)
        return runtime

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool_load = MagicMock()
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    success, output, final_response, error = scheduler.run_job(
        {
            "id": "hostile-final-runtime",
            "name": "hostile final runtime",
            "prompt": "run",
            "model": "gpt-5.5",
        }
    )

    assert success is False
    assert final_response == ""
    assert "Error [beta_" in error
    assert "Error [beta_" in output
    assert calls == 2
    assert _RecordingAgent.created == []
    pool_load.assert_not_called()


def test_beta_cron_auth_failure_never_enters_fallback_or_pool(monkeypatch, tmp_path):
    _prepare_beta_cron(monkeypatch, tmp_path)
    _install_recording_agent(monkeypatch, {"final_response": "must not run"})
    resolve = MagicMock(side_effect=AuthError("Codex auth rejected", code="codex_auth_failed"))
    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool_load = MagicMock()
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    success, output, final_response, error = scheduler.run_job(
        {"id": "auth-failed", "name": "auth failed", "prompt": "run"}
    )

    assert success is False
    assert final_response == ""
    assert "Error [codex_auth_failed]" in error
    assert "Error [codex_auth_failed]" in output
    assert resolve.call_count == 1
    pool_load.assert_not_called()
    assert _RecordingAgent.created == []


def test_beta_cron_submits_hostile_job_provider_and_endpoint_to_policy_without_fallback(
    monkeypatch, tmp_path
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    _install_recording_agent(monkeypatch, {"final_response": "must not run"})
    seen: list[dict] = []

    def reject(**kwargs):
        seen.append(dict(kwargs))
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow the scheduled provider.",
            code="beta_provider_not_allowed",
        )

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", reject)
    pool_load = MagicMock()
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    success, output, final_response, error = scheduler.run_job(
        {
            "id": "hostile-job-provider",
            "name": "hostile job provider",
            "prompt": "run",
            "model": "gpt-5.5",
            "provider": "openrouter",
            "base_url": "https://attacker.invalid/v1",
        }
    )

    assert success is False
    assert final_response == ""
    assert "Error [beta_provider_not_allowed]" in error
    assert "Error [beta_provider_not_allowed]" in output
    assert seen == [
        {
            "requested": "openrouter",
            "explicit_base_url": "https://attacker.invalid/v1",
            "target_model": "gpt-5.5",
        }
    ]
    pool_load.assert_not_called()
    assert _RecordingAgent.created == []


def test_beta_cron_final_auth_loss_is_saved_delivered_and_marked_failed(
    monkeypatch, tmp_path
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    _install_recording_agent(monkeypatch, {"final_response": "must not run"})
    job = {
        "id": "auth-race",
        "name": "Auth race",
        "prompt": "Run after setup.",
        "model": "gpt-5.5",
        "deliver": "origin",
        "origin": {"platform": "telegram", "chat_id": "123"},
    }
    save, mark, deliver = _patch_tick_shell(monkeypatch, tmp_path, job)
    calls = 0

    def resolve(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _codex_runtime(tmp_path)
        raise BetaProviderPolicyError(
            "OpenAI Codex auth disappeared from this Beta profile.",
            code="beta_codex_auth_required",
        )

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)

    assert scheduler.tick(verbose=False) == 1
    assert calls == 2
    assert _RecordingAgent.created == []
    saved_output = save.call_args.args[1]
    assert "Error [beta_codex_auth_required]" in saved_output
    mark.assert_called_once()
    mark_args, mark_kwargs = mark.call_args
    assert mark_args[0] == "auth-race"
    assert mark_args[1] is False
    assert "Error [beta_codex_auth_required]" in mark_args[2]
    assert "Error [beta_codex_auth_required]" in mark_kwargs["summary"]
    deliver.assert_called_once()
    assert "failed" in deliver.call_args.args[1].lower()
    assert "beta_codex_auth_required" in deliver.call_args.args[1]


@pytest.mark.parametrize(
    ("agent_result", "expected_error"),
    [
        ({"failed": True, "error": "401 unauthorized"}, "401 unauthorized"),
        ({"failed": True, "error": "429 rate limited"}, "429 rate limited"),
        (TimeoutError("provider timeout"), "provider timeout"),
        ({"final_response": ""}, "Agent completed but produced empty response"),
    ],
)
def test_beta_cron_terminal_failures_never_switch_provider_or_persist_success(
    monkeypatch, tmp_path, agent_result, expected_error
):
    _prepare_beta_cron(monkeypatch, tmp_path)
    _install_recording_agent(monkeypatch, agent_result)
    job = {
        "id": "terminal-failure",
        "name": "Terminal failure",
        "prompt": "Run once.",
        "model": "gpt-5.5",
    }
    _save, mark, _deliver = _patch_tick_shell(monkeypatch, tmp_path, job)
    calls: list[dict] = []

    def resolve(**kwargs):
        calls.append(dict(kwargs))
        return _codex_runtime(tmp_path, f"token-{len(calls)}")

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool_load = MagicMock()
    monkeypatch.setattr("agent.credential_pool.load_pool", pool_load)

    assert scheduler.tick(verbose=False) == 1
    assert calls == [
        {"requested": None, "target_model": "gpt-5.5"},
        {"requested": "openai-codex", "target_model": "gpt-5.5"},
    ]
    assert len(_RecordingAgent.created) == 1
    kwargs = _RecordingAgent.created[0]
    assert kwargs["provider"] == "openai-codex"
    assert kwargs["fallback_model"] is None
    assert kwargs["credential_pool"] is None
    pool_load.assert_not_called()
    mark.assert_called_once()
    mark_args, _mark_kwargs = mark.call_args
    assert mark_args[1] is False
    assert expected_error in mark_args[2]
    assert not any(call.args[1] is True for call in mark.call_args_list)


def test_stable_cron_keeps_existing_fallback_pool_and_routing_behavior(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setattr(scheduler, "_hermes_home", tmp_path)
    monkeypatch.setattr(scheduler, "_build_job_prompt", lambda job, **_kwargs: job["prompt"])
    monkeypatch.setattr(scheduler, "_resolve_delivery_target", lambda _job: None)
    monkeypatch.setattr(scheduler, "_resolve_cron_enabled_toolsets", lambda _job, _cfg: [])
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("tools.mcp_tool.discover_mcp_tools", lambda: [])
    monkeypatch.setattr("agent.auxiliary_client.cleanup_stale_async_clients", lambda: None)
    monkeypatch.setattr("elevate_state.SessionDB", MagicMock)
    (tmp_path / "config.yaml").write_text(
        """
fallback_providers:
  - provider: openrouter
    model: openai/gpt-4o
    api_key: stable-fallback-key
provider_routing:
  only: [openrouter]
  order: [openrouter]
""".lstrip(),
        encoding="utf-8",
    )
    _install_recording_agent(monkeypatch, {"final_response": "stable done"})

    calls: list[dict] = []

    def resolve(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise AuthError("primary failed")
        return {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "stable-fallback-key",
        }

    monkeypatch.setattr("elevate_cli.runtime_provider.resolve_runtime_provider", resolve)
    pool = MagicMock()
    pool.has_credentials.return_value = True
    pool.entries.return_value = [object()]
    monkeypatch.setattr("agent.credential_pool.load_pool", MagicMock(return_value=pool))

    success, _output, final_response, error = scheduler.run_job(
        {"id": "stable-fallback", "name": "Stable fallback", "prompt": "run"}
    )

    assert (success, final_response, error) == (True, "stable done", None)
    assert calls == [
        {"requested": None},
        {
            "requested": "openrouter",
            "explicit_api_key": "stable-fallback-key",
        },
    ]
    kwargs = _RecordingAgent.created[0]
    assert kwargs["provider"] == "openrouter"
    assert kwargs["fallback_model"] == [
        {
            "provider": "openrouter",
            "model": "openai/gpt-4o",
            "api_key": "stable-fallback-key",
        }
    ]
    assert kwargs["credential_pool"] is pool
    assert kwargs["providers_allowed"] == ["openrouter"]
    assert kwargs["providers_order"] == ["openrouter"]
