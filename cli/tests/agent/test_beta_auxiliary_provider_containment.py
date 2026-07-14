"""Exact-Beta containment for auxiliary, compaction, and vision LLM calls."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import agent.auxiliary_client as auxiliary
from elevate_cli.beta_provider_policy import (
    BETA_CODEX_BASE_URL,
    BetaProviderPolicyError,
)


def _runtime(home, token: str = "current-profile-token") -> dict:
    return {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": BETA_CODEX_BASE_URL,
        "api_key": token,
        "source": "elevate-auth-store",
        "auth_store": str(home / "auth.json"),
        "requested_provider": "openai-codex",
    }


def _response(content: str | None = "done"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )


@pytest.fixture
def beta_home(monkeypatch, tmp_path):
    home = tmp_path / "beta-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    (home / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai-codex": {
                        "tokens": {
                            "access_token": "profile-token",
                            "refresh_token": "profile-refresh",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    for name in (
        "ELEVATE_MODEL",
        "ELEVATE_INFERENCE_PROVIDER",
        "ELEVATE_CODEX_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with auxiliary._client_cache_lock:
        auxiliary._client_cache.clear()
    yield home
    with auxiliary._client_cache_lock:
        auxiliary._client_cache.clear()


class _FakeOpenAI:
    created: list["_FakeOpenAI"] = []

    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.base_url = kwargs["base_url"]
        self.default_headers = kwargs.get("default_headers")
        type(self).created.append(self)

    def close(self):
        return None


def test_beta_direct_router_uses_real_current_profile_runtime_without_pool(
    monkeypatch, beta_home
):
    import elevate_cli.runtime_provider as runtime_provider

    monkeypatch.setattr(auxiliary, "OpenAI", _FakeOpenAI)
    _FakeOpenAI.created = []
    monkeypatch.setattr(
        runtime_provider,
        "load_pool",
        MagicMock(side_effect=AssertionError("Beta must not load a pool")),
    )
    monkeypatch.setattr(
        auxiliary,
        "_read_codex_access_token",
        MagicMock(
            side_effect=AssertionError(
                "Beta auxiliary code must not read auth outside runtime authority"
            )
        ),
    )

    client, model = auxiliary.resolve_provider_client("auto")

    assert client is not None
    assert model == "gpt-5.5"
    assert len(_FakeOpenAI.created) == 1
    assert _FakeOpenAI.created[0].api_key == "profile-token"
    assert _FakeOpenAI.created[0].base_url == BETA_CODEX_BASE_URL


def test_beta_cached_client_bypasses_cache_pool_and_hostile_main_runtime(
    monkeypatch, beta_home
):
    calls: list[dict] = []

    def resolve(**kwargs):
        calls.append(dict(kwargs))
        return _runtime(beta_home, f"fresh-token-{len(calls)}")

    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    monkeypatch.setattr(auxiliary, "OpenAI", _FakeOpenAI)
    _FakeOpenAI.created = []
    monkeypatch.setattr(
        auxiliary,
        "load_pool",
        MagicMock(side_effect=AssertionError("Beta must not load a pool")),
    )
    monkeypatch.setattr(
        auxiliary,
        "_resolve_auto",
        MagicMock(side_effect=AssertionError("Beta must not auto-discover")),
    )
    poisoned = object()
    with auxiliary._client_cache_lock:
        auxiliary._client_cache[("poisoned",)] = (
            poisoned,
            "anthropic/claude",
            None,
        )

    first, first_model = auxiliary._get_cached_client(
        "auto",
        main_runtime={
            "provider": "openrouter",
            "api_key": "hostile-main-key",
            "base_url": "https://attacker.invalid/v1",
        },
    )
    second, second_model = auxiliary._get_cached_client("openai-codex")

    assert first is not second
    assert first is not poisoned and second is not poisoned
    assert (first_model, second_model) == ("gpt-5.5", "gpt-5.5")
    assert calls == [
        {"requested": "openai-codex", "target_model": "gpt-5.5"},
        {"requested": "openai-codex", "target_model": "gpt-5.5"},
    ]
    assert [client.api_key for client in _FakeOpenAI.created] == [
        "fresh-token-1",
        "fresh-token-2",
    ]
    assert all(
        client.base_url == BETA_CODEX_BASE_URL
        for client in _FakeOpenAI.created
    )


@pytest.mark.parametrize(
    ("task_lines", "code"),
    [
        ("    provider: openrouter\n", "beta_provider_not_allowed"),
        ("    model: anthropic/claude\n", "beta_model_not_allowed"),
        (
            "    base_url: https://attacker.invalid/v1\n",
            "beta_auxiliary_endpoint_not_allowed",
        ),
        ("    api_key: alternate-key\n", "beta_auxiliary_api_key_not_allowed"),
        (
            "    api_mode: chat_completions\n",
            "beta_auxiliary_api_mode_not_allowed",
        ),
        (
            "    fallback_chain:\n      - provider: openrouter\n",
            "beta_auxiliary_fallback_not_allowed",
        ),
    ],
)
def test_beta_validates_hostile_task_config_even_with_safe_explicit_override(
    monkeypatch, beta_home, task_lines, code
):
    (beta_home / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-codex\n"
        "  default: gpt-5.5\n"
        "auxiliary:\n"
        "  compression:\n"
        + task_lines,
        encoding="utf-8",
    )
    resolve = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        auxiliary.call_llm(
            task="compression",
            provider="openai-codex",
            model="gpt-5.5",
            messages=[{"role": "user", "content": "summarize"}],
        )

    assert exc.value.code == code
    resolve.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"provider": "anthropic"}, "beta_provider_not_allowed"),
        ({"model": "gpt-4o"}, "beta_model_not_allowed"),
        (
            {"explicit_base_url": BETA_CODEX_BASE_URL},
            "beta_auxiliary_endpoint_not_allowed",
        ),
        (
            {"explicit_api_key": "alternate-key"},
            "beta_auxiliary_api_key_not_allowed",
        ),
        (
            {"api_mode": "chat_completions"},
            "beta_auxiliary_api_mode_not_allowed",
        ),
    ],
)
def test_beta_direct_router_rejects_every_explicit_escape_before_resolution(
    monkeypatch, beta_home, kwargs, code
):
    resolve = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    arguments = {"provider": "openai-codex", "model": "gpt-5.5"}
    arguments.update(kwargs)

    with pytest.raises(BetaProviderPolicyError) as exc:
        auxiliary.resolve_provider_client(**arguments)

    assert exc.value.code == code
    resolve.assert_not_called()


@pytest.mark.parametrize(
    "hostile_patch",
    [
        {"provider": "openrouter"},
        {"api_mode": "chat_completions"},
        {"base_url": "https://attacker.invalid/v1"},
        {"source": "credential-pool"},
        {"auth_store": "/tmp/stable/auth.json"},
        {"credential_pool": object()},
        {"command": "alternate-provider-client"},
    ],
)
def test_beta_rejects_hostile_fresh_runtime_before_client_construction(
    monkeypatch, beta_home, hostile_patch
):
    runtime = _runtime(beta_home)
    runtime.update(hostile_patch)
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: runtime,
    )
    openai = MagicMock()
    monkeypatch.setattr(auxiliary, "OpenAI", openai)

    with pytest.raises(BetaProviderPolicyError) as exc:
        auxiliary.resolve_provider_client("openai-codex", "gpt-5.5")

    assert exc.value.code == "beta_auxiliary_runtime_not_local"
    openai.assert_not_called()


@pytest.mark.parametrize(
    "outcome",
    [
        RuntimeError("401 unauthorized"),
        RuntimeError("429 rate limit"),
        TimeoutError("request timed out"),
        _response(None),
    ],
)
def test_beta_sync_failures_are_visible_and_never_retry_or_fallback(
    monkeypatch, beta_home, outcome
):
    create = MagicMock()
    if isinstance(outcome, BaseException):
        create.side_effect = outcome
    else:
        create.return_value = outcome
    client = SimpleNamespace(
        base_url=BETA_CODEX_BASE_URL,
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        ),
    )
    build = MagicMock(return_value=(client, "gpt-5.5"))
    monkeypatch.setattr(auxiliary, "_build_beta_auxiliary_client", build)
    fallback = MagicMock(
        side_effect=AssertionError("Beta must not attempt fallback")
    )
    monkeypatch.setattr(auxiliary, "_try_payment_fallback", fallback)
    monkeypatch.setattr(auxiliary, "_try_configured_fallback_chain", fallback)
    monkeypatch.setattr(auxiliary, "_try_main_agent_model_fallback", fallback)

    expected = (
        auxiliary.AuxiliaryResponseRejectedError
        if not isinstance(outcome, BaseException)
        else type(outcome)
    )
    with pytest.raises(expected):
        auxiliary.call_llm(
            task="compression",
            messages=[{"role": "user", "content": "summarize"}],
        )

    create.assert_called_once()
    fallback.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [RuntimeError("429 rate limit"), _response(None)],
)
async def test_beta_async_failures_are_visible_and_never_fallback(
    monkeypatch, beta_home, outcome
):
    calls = 0

    async def create(**_kwargs):
        nonlocal calls
        calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    client = SimpleNamespace(
        base_url=BETA_CODEX_BASE_URL,
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        ),
    )
    monkeypatch.setattr(
        auxiliary,
        "_build_beta_auxiliary_client",
        MagicMock(return_value=(client, "gpt-5.5")),
    )
    fallback = MagicMock(
        side_effect=AssertionError("Beta must not attempt fallback")
    )
    monkeypatch.setattr(auxiliary, "_try_payment_fallback", fallback)
    monkeypatch.setattr(auxiliary, "_try_configured_fallback_chain", fallback)
    monkeypatch.setattr(auxiliary, "_try_main_agent_model_fallback", fallback)

    expected = (
        auxiliary.AuxiliaryResponseRejectedError
        if not isinstance(outcome, BaseException)
        else type(outcome)
    )
    with pytest.raises(expected):
        await auxiliary.async_call_llm(
            task="vision",
            messages=[{"role": "user", "content": "inspect image"}],
        )

    assert calls == 1
    fallback.assert_not_called()


def test_beta_vision_routes_directly_to_codex_and_availability_is_local_only(
    monkeypatch, beta_home
):
    resolve = MagicMock(return_value=_runtime(beta_home))
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    monkeypatch.setattr(auxiliary, "OpenAI", _FakeOpenAI)
    _FakeOpenAI.created = []
    forbidden = MagicMock(
        side_effect=AssertionError("Beta must not enumerate vision providers")
    )
    monkeypatch.setattr(auxiliary, "_try_openrouter", forbidden)
    monkeypatch.setattr(auxiliary, "_try_nous", forbidden)
    monkeypatch.setattr(auxiliary, "_read_main_provider", forbidden)

    provider, client, model = auxiliary.resolve_vision_provider_client()

    assert provider == "openai-codex"
    assert client is not None
    assert model == "gpt-5.5"
    assert resolve.call_args.kwargs == {
        "requested": "openai-codex",
        "target_model": "gpt-5.5",
    }
    forbidden.assert_not_called()

    resolve.reset_mock()
    _FakeOpenAI.created = []
    assert auxiliary.get_available_vision_backends() == ["openai-codex"]
    resolve.assert_not_called()
    assert _FakeOpenAI.created == []
    forbidden.assert_not_called()


def test_non_exact_beta_channel_keeps_stable_auto_router(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    stable_client = object()
    auto = MagicMock(return_value=(stable_client, "stable-model"))
    monkeypatch.setattr(auxiliary, "_resolve_auto", auto)
    beta_build = MagicMock(
        side_effect=AssertionError("non-exact channel must remain Stable")
    )
    monkeypatch.setattr(auxiliary, "_build_beta_auxiliary_client", beta_build)

    client, model = auxiliary.resolve_provider_client("auto")

    assert (client, model) == (stable_client, "stable-model")
    auto.assert_called_once()
    beta_build.assert_not_called()
