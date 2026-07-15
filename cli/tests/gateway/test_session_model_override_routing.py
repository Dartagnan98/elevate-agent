"""Regression tests for session-scoped model/provider overrides in gateway agents.

These cover the bug where `/model ...` stored a session override, but fresh
agent constructions still resolved model/provider from global config/runtime.
That let helper agents (and cache-miss main agents) route GPT-5.4 to the wrong
provider, e.g. Nous instead of OpenAI Codex.
"""

import asyncio
import sys
import threading
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource


class _CapturingAgent:
    """Fake agent that records init kwargs for assertions."""

    last_init = None

    def __init__(self, *args, **kwargs):
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(self, user_message: str, conversation_history=None, task_id=None, persist_user_message=None):
        return {
            "final_response": "ok",
            "messages": [],
            "api_calls": 1,
        }


def _make_runner():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner.session_store = None
    runner.config = None
    runner._voice_mode = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._show_reasoning = False
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._service_tier = None
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_tasks = set()
    runner._session_db = None
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._pending_approvals = {}
    runner._pending_platform_delegates = {}
    runner._pending_platform_delegates_lock = threading.Lock()
    runner._pending_cron_context = {}
    runner._pending_cron_context_lock = threading.Lock()
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.hooks.loaded_hooks = []
    return runner


def _codex_override():
    return {
        "model": "gpt-5.4",
        "provider": "openai-codex",
        "api_key": "***",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_mode": "codex_responses",
    }


def _explode_runtime_resolution():
    raise AssertionError(
        "global runtime resolution should not run when a complete session override exists"
    )


@pytest.mark.parametrize(
    "override",
    [
        {
            "model": "gpt-5.4",
            "provider": "anthropic",
            "api_key": "hostile-key",
            "base_url": "https://api.anthropic.com",
            "api_mode": "anthropic_messages",
        },
        {
            "model": "anthropic/claude-sonnet-4",
            "provider": "openai-codex",
            "api_key": "hostile-key",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        },
    ],
)
def test_beta_rejects_hostile_session_override_before_runtime_resolution(
    monkeypatch, override
):
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config: "gpt-5.5")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        _explode_runtime_resolution,
    )
    runner = _make_runner()
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = override

    with pytest.raises(BetaProviderPolicyError):
        runner._resolve_session_agent_runtime(session_key=session_key)


def test_beta_session_override_uses_fresh_local_codex_runtime(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config: "gpt-5.5")
    fresh_runtime = {
        "provider": "openai-codex",
        "api_key": "fresh-local-token",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_mode": "codex_responses",
        "credential_pool": None,
    }
    resolver = MagicMock(return_value=fresh_runtime)
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", resolver)
    runner = _make_runner()
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()

    model, runtime = runner._resolve_session_agent_runtime(session_key=session_key)

    assert model == "gpt-5.4"
    assert runtime == fresh_runtime
    assert runtime["api_key"] != "***"
    resolver.assert_called_once_with()


def test_bedrock_session_override_refreshes_timeout_receipt_and_signature(
    monkeypatch,
):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_gateway_model",
        lambda config=None: "global-model",
    )
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        _explode_runtime_resolution,
    )

    from elevate_cli import runtime_provider

    endpoint = "https://bedrock-runtime-fips.us-west-2.amazonaws.com"
    selected_model = "anthropic.claude-3-7-sonnet-20250219-v1:0"
    current_bounds = {"request": 17.0, "stale": 31.0}
    resolution_calls = []

    def _resolve_override(**kwargs):
        resolution_calls.append(dict(kwargs))
        return {
            "provider": "bedrock",
            "model": selected_model,
            "api_mode": "anthropic_messages",
            "base_url": endpoint,
            "api_key": "aws-sdk",
            "bedrock_timeout_provider": "west-bedrock",
            "request_timeout_seconds": current_bounds["request"],
            "stale_timeout_seconds": current_bounds["stale"],
        }

    monkeypatch.setattr(
        runtime_provider,
        "resolve_runtime_provider",
        _resolve_override,
    )
    runner = _make_runner()
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = {
        "model": selected_model,
        "provider": "custom:west-bedrock",
        "api_key": "aws-sdk",
        "base_url": endpoint,
        "api_mode": "anthropic_messages",
    }

    model, first_runtime = runner._resolve_session_agent_runtime(
        session_key=session_key
    )
    first_signature = runner._resolve_turn_agent_config(
        "first", model, first_runtime
    )["signature"]

    current_bounds.update(request=9.0, stale=14.0)
    model, second_runtime = runner._resolve_session_agent_runtime(
        session_key=session_key
    )
    second_signature = runner._resolve_turn_agent_config(
        "second", model, second_runtime
    )["signature"]

    assert first_runtime["request_timeout_seconds"] == 17.0
    assert first_runtime["stale_timeout_seconds"] == 31.0
    assert second_runtime["request_timeout_seconds"] == 9.0
    assert second_runtime["stale_timeout_seconds"] == 14.0
    assert first_signature != second_signature
    assert runner._session_model_overrides[session_key][
        "bedrock_timeout_provider"
    ] == "west-bedrock"
    assert resolution_calls == [
        {
            "requested": "custom:west-bedrock",
            "explicit_base_url": endpoint,
            "target_model": selected_model,
        },
        {
            "requested": "custom:west-bedrock",
            "explicit_base_url": endpoint,
            "target_model": selected_model,
        },
    ]


def test_session_override_clears_timeout_receipt_when_identity_changes():
    runner = _make_runner()
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = {
        "model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "provider": "bedrock",
        "base_url": "https://bedrock-runtime-fips.us-west-2.amazonaws.com",
        "api_mode": "anthropic_messages",
    }
    runtime = {
        "provider": "bedrock",
        "base_url": "https://bedrock-runtime.ca-central-1.amazonaws.com",
        "api_mode": "bedrock_converse",
        "bedrock_timeout_provider": "canada-bedrock",
        "request_timeout_seconds": 17.0,
        "stale_timeout_seconds": 31.0,
    }

    model, resolved = runner._apply_session_model_override(
        session_key,
        "amazon.nova-pro-v1:0",
        runtime,
    )

    assert model == "anthropic.claude-3-7-sonnet-20250219-v1:0"
    assert resolved["bedrock_timeout_provider"] is None
    assert resolved["request_timeout_seconds"] is None
    assert resolved["stale_timeout_seconds"] is None


def test_run_agent_prefers_session_override_over_global_runtime(monkeypatch):
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()

    result = asyncio.run(
        runner._run_agent(
            message="ping",
            context_prompt="",
            history=[],
            source=source,
            session_id="session-1",
            session_key=session_key,
        )
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init is not None
    assert _CapturingAgent.last_init["model"] == "gpt-5.4"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"
    assert _CapturingAgent.last_init["api_mode"] == "codex_responses"
    assert _CapturingAgent.last_init["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert _CapturingAgent.last_init["api_key"] == "***"


def test_run_agent_runtime_auth_failure_is_explicit_and_not_success(monkeypatch):
    """Credential/runtime resolution failures must survive every truth predicate."""
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)

    runner = _make_runner()
    runner._resolve_session_agent_runtime = MagicMock(
        side_effect=RuntimeError("bad credentials")
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = asyncio.run(
        runner._run_agent(
            message="ping",
            context_prompt="",
            history=[],
            source=source,
            session_id="session-1",
            session_key="agent:main:local:dm",
        )
    )

    assert result["completed"] is False
    assert result["failed"] is True
    assert result["interrupted"] is False
    assert result["needs_input"] is False
    assert result["partial"] is False
    assert result["pending"] is False
    assert result["pending_tool_obligations"] == []
    assert "bad credentials" in result["error"]
    assert gateway_run.agent_result_succeeded(result) is False
    assert gateway_run._should_suppress_transcript_growth(result) is False


@pytest.mark.asyncio
async def test_background_task_prefers_session_override_over_global_runtime(monkeypatch):
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()

    adapter = AsyncMock()
    adapter.send = AsyncMock()
    adapter.extract_media = MagicMock(return_value=([], "ok"))
    adapter.extract_images = MagicMock(return_value=([], "ok"))
    runner.adapters[Platform.TELEGRAM] = adapter

    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="12345",
        chat_id="67890",
        user_name="testuser",
    )
    session_key = runner._session_key_for_source(source)
    runner._session_model_overrides[session_key] = _codex_override()

    await runner._run_background_task("say hello", source, "bg_test")

    assert _CapturingAgent.last_init is not None
    assert _CapturingAgent.last_init["model"] == "gpt-5.4"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"
    assert _CapturingAgent.last_init["api_mode"] == "codex_responses"
    assert _CapturingAgent.last_init["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert _CapturingAgent.last_init["api_key"] == "***"
