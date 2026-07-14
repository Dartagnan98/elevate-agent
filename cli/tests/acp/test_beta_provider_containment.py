"""Realtor Beta containment for the inbound ACP adapter.

All provider calls are faked.  These tests use only per-test Elevate homes and
never import host credentials or make provider/network requests.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("acp", reason="requires optional ACP extra: acp")

import acp
from acp.schema import TextContentBlock

from acp_adapter.auth import detect_provider
from acp_adapter.server import ElevateACPAgent
from acp_adapter.session import SessionManager
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    BETA_DEFAULT_MODEL,
    BetaProviderPolicyError,
)
from elevate_constants import get_elevate_home


class _FakeAIAgent:
    instances: list["_FakeAIAgent"] = []
    run_calls = 0
    compression_behavior: object = None
    behavior: object = {
        "final_response": "Codex completed the request.",
        "messages": [
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "Codex completed the request."},
        ],
    }

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.model = kwargs.get("model")
        self.provider = kwargs.get("provider")
        self.base_url = kwargs.get("base_url")
        self.api_mode = kwargs.get("api_mode")
        self.api_key = kwargs.get("api_key")
        self.enabled_toolsets = list(kwargs.get("enabled_toolsets") or [])
        self._print_fn = None
        self._session_db = None
        self.compression_enabled = True
        self.interrupted = False
        type(self).instances.append(self)

    def run_conversation(self, **_kwargs):
        type(self).run_calls += 1
        behavior = type(self).behavior
        if isinstance(behavior, BaseException):
            raise behavior
        return copy.deepcopy(behavior)

    def interrupt(self, *_args):
        self.interrupted = True

    def _compress_context(self, history, *_args, **_kwargs):
        behavior = type(self).compression_behavior
        if isinstance(behavior, BaseException):
            raise behavior
        if behavior is not None:
            return copy.deepcopy(behavior)
        return ([{"role": "assistant", "content": "compressed"}], {})


@pytest.fixture()
def beta_acp(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    home = get_elevate_home()
    (home / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    BETA_ALLOWED_PROVIDER: {
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

    config = {
        "model": {
            "provider": BETA_ALLOWED_PROVIDER,
            "default": BETA_DEFAULT_MODEL,
            "base_url": BETA_CODEX_BASE_URL,
            "api_mode": "codex_responses",
        }
    }

    def load_config():
        return copy.deepcopy(config)

    from elevate_cli import config as config_module
    from elevate_cli import runtime_provider
    import run_agent

    monkeypatch.setattr(config_module, "load_config", load_config)
    monkeypatch.setattr(runtime_provider, "load_config", load_config)

    credential_reads: list[str] = []

    def fake_codex_credentials(**_kwargs):
        token = f"fresh-current-profile-token-{len(credential_reads) + 1}"
        credential_reads.append(token)
        return {
            "provider": BETA_ALLOWED_PROVIDER,
            "base_url": BETA_CODEX_BASE_URL,
            "api_key": token,
            "source": "elevate-auth-store",
            "auth_mode": "chatgpt",
            "last_refresh": None,
        }

    monkeypatch.setattr(
        runtime_provider,
        "resolve_codex_runtime_credentials",
        fake_codex_credentials,
    )
    monkeypatch.setattr(run_agent, "AIAgent", _FakeAIAgent)

    _FakeAIAgent.instances = []
    _FakeAIAgent.run_calls = 0
    _FakeAIAgent.compression_behavior = None
    _FakeAIAgent.behavior = {
        "final_response": "Codex completed the request.",
        "messages": [
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "Codex completed the request."},
        ],
    }
    return SimpleNamespace(
        home=home,
        config=config,
        credential_reads=credential_reads,
        runtime_provider=runtime_provider,
    )


def _connection() -> MagicMock:
    conn = MagicMock(spec=acp.Client)
    conn.session_update = AsyncMock()
    conn.request_permission = AsyncMock(return_value=None)
    return conn


def _last_update_text(conn: MagicMock) -> str:
    call = conn.session_update.await_args_list[-1]
    update = call.kwargs.get("update") or call.args[1]
    return str(update)


def test_beta_auth_detection_is_a_pure_current_profile_read(beta_acp, monkeypatch):
    monkeypatch.setattr(
        beta_acp.runtime_provider,
        "resolve_runtime_provider",
        lambda **_kwargs: pytest.fail("generic provider resolution must not run"),
    )

    assert detect_provider() == BETA_ALLOWED_PROVIDER
    beta_acp.home.joinpath("auth.json").unlink()
    assert detect_provider() is None


@pytest.mark.asyncio
async def test_beta_model_catalog_is_closed_and_codex_only(beta_acp, monkeypatch):
    monkeypatch.setattr(
        "elevate_cli.models.curated_models_for_provider",
        lambda *_args, **_kwargs: pytest.fail("generic model discovery must not run"),
    )
    server = ElevateACPAgent(session_manager=SessionManager())

    response = await server.new_session(cwd="/tmp/project")

    assert response.models is not None
    assert response.models.current_model_id == (
        f"{BETA_ALLOWED_PROVIDER}:{BETA_DEFAULT_MODEL}"
    )
    assert [item.model_id for item in response.models.available_models] == [
        f"{BETA_ALLOWED_PROVIDER}:{model}" for model in BETA_ALLOWED_MODELS
    ]
    assert {instance.provider for instance in _FakeAIAgent.instances} == {
        BETA_ALLOWED_PROVIDER
    }


@pytest.mark.asyncio
async def test_beta_prompt_rebuilds_from_fresh_current_profile_runtime(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    first_agent = state.agent

    prompt_response = await server.prompt(
        prompt=[TextContentBlock(type="text", text="continue")],
        session_id=state.session_id,
    )

    assert prompt_response.stop_reason == "end_turn"
    assert state.agent is not first_agent
    assert state.agent.api_key == "fresh-current-profile-token-2"
    assert beta_acp.credential_reads == [
        "fresh-current-profile-token-1",
        "fresh-current-profile-token-2",
    ]
    assert state.agent.provider == BETA_ALLOWED_PROVIDER
    assert state.agent.base_url == BETA_CODEX_BASE_URL
    assert state.agent.api_mode == "codex_responses"
    assert state.agent._fallback_chain == []
    assert state.agent._credential_pool is None
    assert state.agent._api_max_retries == 1
    assert state.agent._try_refresh_codex_client_credentials(force=True) is False
    assert state.history[-1]["content"] == "Codex completed the request."


@pytest.mark.parametrize(
    ("path", "value", "expected_code"),
    [
        (("model", "provider"), "anthropic", "beta_provider_not_allowed"),
        (("model", "default"), "claude-sonnet", "beta_model_not_allowed"),
        (
            ("model", "base_url"),
            "https://hostile.invalid/v1",
            "beta_custom_endpoint_not_allowed",
        ),
        (("model", "api_mode"), "chat_completions", "beta_api_mode_not_allowed"),
        (("fallback_model",), {"provider": "anthropic"}, "beta_fallback_not_allowed"),
        (("custom_providers",), [{"name": "hostile"}], "beta_custom_provider_not_allowed"),
    ],
)
def test_beta_rejects_hostile_config_before_credentials_or_agent(
    beta_acp,
    path,
    value,
    expected_code,
):
    target = beta_acp.config
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        SessionManager().create_session(cwd="/tmp/project")

    assert exc_info.value.code == expected_code
    assert beta_acp.credential_reads == []
    assert _FakeAIAgent.instances == []


@pytest.mark.parametrize(
    ("env_name", "env_value", "expected_code"),
    [
        (
            "ELEVATE_INFERENCE_PROVIDER",
            "anthropic",
            "beta_provider_not_allowed",
        ),
        (
            "ELEVATE_CODEX_BASE_URL",
            "https://hostile.invalid/v1",
            "beta_codex_endpoint_not_allowed",
        ),
        ("ELEVATE_MODEL", "claude-sonnet", "beta_model_not_allowed"),
    ],
)
def test_beta_rejects_hostile_environment_before_agent(
    beta_acp,
    monkeypatch,
    env_name,
    env_value,
    expected_code,
):
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        SessionManager().create_session(cwd="/tmp/project")

    assert exc_info.value.code == expected_code
    assert beta_acp.credential_reads == []
    assert _FakeAIAgent.instances == []


@pytest.mark.parametrize(
    ("kwargs", "expected_code"),
    [
        (
            {"base_url": "https://cached-hostile.invalid/v1"},
            "beta_acp_cached_endpoint_not_allowed",
        ),
        (
            {"api_mode": "chat_completions"},
            "beta_acp_cached_api_mode_not_allowed",
        ),
        (
            {"requested_provider": "anthropic"},
            "beta_provider_not_allowed",
        ),
        (
            {"model": "claude-sonnet"},
            "beta_model_not_allowed",
        ),
    ],
)
def test_beta_rejects_hostile_cached_session_authority(
    beta_acp,
    kwargs,
    expected_code,
):
    with pytest.raises(BetaProviderPolicyError) as exc_info:
        SessionManager()._make_agent(
            session_id="cached-session",
            cwd="/tmp/project",
            **kwargs,
        )

    assert exc_info.value.code == expected_code
    assert _FakeAIAgent.instances == []


def test_beta_rejects_noncanonical_resolver_output_before_agent(
    beta_acp,
    monkeypatch,
):
    monkeypatch.setattr(
        beta_acp.runtime_provider,
        "resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "anthropic",
            "api_mode": "anthropic_messages",
            "base_url": "https://api.anthropic.com",
            "api_key": "hostile-token",
            "source": "environment",
            "auth_store": "/tmp/other-profile/auth.json",
        },
    )

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        SessionManager().create_session(cwd="/tmp/project")

    assert exc_info.value.code == "beta_acp_runtime_provider_mismatch"
    assert _FakeAIAgent.instances == []


@pytest.mark.asyncio
async def test_beta_blocked_slash_model_switch_is_visible_and_atomic(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    original_agent = state.agent
    original_model = state.model
    conn = _connection()
    server._conn = conn

    result = await server.prompt(
        prompt=[
            TextContentBlock(
                type="text",
                text="/model anthropic:claude-sonnet",
            )
        ],
        session_id=state.session_id,
    )

    assert result.stop_reason == "refusal"
    assert "beta_provider_not_allowed" in _last_update_text(conn)
    assert state.agent is original_agent
    assert state.model == original_model
    assert len(_FakeAIAgent.instances) == 1


@pytest.mark.asyncio
async def test_beta_allowed_protocol_model_switch_is_atomic(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    original_agent = state.agent
    selected = BETA_ALLOWED_MODELS[1]

    result = await server.set_session_model(
        model_id=f"{BETA_ALLOWED_PROVIDER}:{selected}",
        session_id=state.session_id,
    )

    assert result is not None
    assert state.agent is not original_agent
    assert state.agent.provider == BETA_ALLOWED_PROVIDER
    assert state.agent.model == selected
    assert state.model == selected
    assert beta_acp.credential_reads[-1] == "fresh-current-profile-token-2"


@pytest.mark.asyncio
async def test_beta_blocked_protocol_model_switch_is_typed_and_atomic(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    original_agent = state.agent
    original_model = state.model

    with pytest.raises(RuntimeError, match="beta_provider_not_allowed"):
        await server.set_session_model(
            model_id="anthropic:claude-sonnet",
            session_id=state.session_id,
        )

    assert state.agent is original_agent
    assert state.model == original_model
    assert len(_FakeAIAgent.instances) == 1


@pytest.mark.asyncio
async def test_beta_auth_loss_before_prompt_preserves_session_and_is_visible(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    state.history = [{"role": "user", "content": "existing history"}]
    manager.save_session(state.session_id)
    original_agent = state.agent
    original_history = copy.deepcopy(state.history)
    beta_acp.home.joinpath("auth.json").unlink()
    conn = _connection()
    server._conn = conn

    result = await server.prompt(
        prompt=[TextContentBlock(type="text", text="continue")],
        session_id=state.session_id,
    )

    assert result.stop_reason == "refusal"
    assert "beta_codex_auth_required" in _last_update_text(conn)
    assert state.agent is original_agent
    assert state.history == original_history
    assert _FakeAIAgent.run_calls == 0
    assert len(_FakeAIAgent.instances) == 1


@pytest.mark.asyncio
async def test_beta_hostile_env_change_before_prompt_preserves_session(
    beta_acp,
    monkeypatch,
):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    state.history = [{"role": "user", "content": "existing history"}]
    manager.save_session(state.session_id)
    original_agent = state.agent
    original_history = copy.deepcopy(state.history)
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "anthropic")
    conn = _connection()
    server._conn = conn

    result = await server.prompt(
        prompt=[TextContentBlock(type="text", text="continue")],
        session_id=state.session_id,
    )

    assert result.stop_reason == "refusal"
    assert "beta_provider_not_allowed" in _last_update_text(conn)
    assert state.agent is original_agent
    assert state.history == original_history
    assert len(_FakeAIAgent.instances) == 1
    assert _FakeAIAgent.run_calls == 0


@pytest.mark.asyncio
async def test_beta_compaction_failure_is_typed_and_preserves_session(beta_acp):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    state.history = [{"role": "user", "content": "existing history"}]
    manager.save_session(state.session_id)
    original_agent = state.agent
    original_history = copy.deepcopy(state.history)
    _FakeAIAgent.compression_behavior = TimeoutError("compression timed out")
    conn = _connection()
    server._conn = conn

    result = await server.prompt(
        prompt=[TextContentBlock(type="text", text="/compact")],
        session_id=state.session_id,
    )

    assert result.stop_reason == "refusal"
    assert "beta_acp_codex_timeout" in _last_update_text(conn)
    assert state.agent is original_agent
    assert state.history == original_history
    assert len(_FakeAIAgent.instances) == 2
    assert {instance.provider for instance in _FakeAIAgent.instances} == {
        BETA_ALLOWED_PROVIDER
    }


@pytest.mark.parametrize(
    ("behavior", "expected_code"),
    [
        (
            {
                "final_response": "upstream rejected credentials",
                "messages": [{"role": "assistant", "content": "mutated"}],
                "failed": True,
                "completed": False,
                "error": "HTTP 401 unauthorized",
            },
            "beta_acp_codex_auth_failed",
        ),
        (
            {
                "final_response": "upstream rate limit",
                "messages": [{"role": "assistant", "content": "mutated"}],
                "failed": True,
                "completed": False,
                "error": "HTTP 429 rate limited",
            },
            "beta_acp_codex_rate_limited",
        ),
        (TimeoutError("provider timed out"), "beta_acp_codex_timeout"),
        (
            {
                "final_response": "",
                "messages": [{"role": "assistant", "content": "mutated"}],
                "completed": True,
            },
            "beta_acp_empty_response",
        ),
    ],
)
@pytest.mark.asyncio
async def test_beta_provider_failures_preserve_state_and_never_switch(
    beta_acp,
    behavior,
    expected_code,
):
    manager = SessionManager()
    server = ElevateACPAgent(session_manager=manager)
    response = await server.new_session(cwd="/tmp/project")
    state = manager.get_session(response.session_id)
    state.history = [{"role": "user", "content": "existing history"}]
    manager.save_session(state.session_id)
    original_agent = state.agent
    original_model = state.model
    original_history = copy.deepcopy(state.history)
    _FakeAIAgent.behavior = behavior
    conn = _connection()
    server._conn = conn

    result = await server.prompt(
        prompt=[TextContentBlock(type="text", text="continue")],
        session_id=state.session_id,
    )

    assert result.stop_reason == "refusal"
    assert expected_code in _last_update_text(conn)
    assert state.agent is original_agent
    assert state.model == original_model
    assert state.history == original_history
    persisted = manager._get_db().get_messages_as_conversation(state.session_id)
    assert [
        {"role": message["role"], "content": message["content"]}
        for message in persisted
    ] == original_history
    assert {instance.provider for instance in _FakeAIAgent.instances} == {
        BETA_ALLOWED_PROVIDER
    }
    assert all(instance._fallback_chain == [] for instance in _FakeAIAgent.instances)
