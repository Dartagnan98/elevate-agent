"""Config-only Bedrock FIPS identity across auxiliary routing modes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


FIPS_ENDPOINT = "https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com"
CLAUDE_MODEL = "anthropic.claude-sonnet-4-6-v1:0"
NOVA_MODEL = "amazon.nova-lite-v1:0"


def _config(model: str) -> dict:
    return {
        "model": {
            "provider": "bedrock",
            "default": model,
            "base_url": FIPS_ENDPOINT,
        },
        # Deliberately stale: the trusted endpoint owns the runtime region.
        "bedrock": {"region": "us-east-1"},
    }


def _converse_success(model: str) -> dict:
    return {
        "modelId": model,
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "config fips reply"}],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["direct", "auto"])
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    ("family", "model"),
    [("claude", CLAUDE_MODEL), ("nova", NOVA_MODEL)],
)
async def test_config_only_fips_reaches_native_auxiliary_wire(
    monkeypatch,
    route,
    async_mode,
    family,
    model,
):
    """Exercise Claude/Nova x sync/async x direct/auto without a network."""
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        AsyncBedrockConverseAuxiliaryClient,
        BedrockConverseAuxiliaryClient,
        _get_cached_client,
        resolve_provider_client,
    )

    monkeypatch.delenv("BEDROCK_BASE_URL", raising=False)
    real_anthropic = MagicMock()
    real_anthropic.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="config fips reply",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _converse_success(model)

    async def _run_in_place(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    cache = {}
    with (
        patch("agent.auxiliary_client._client_cache", cache),
        patch("agent.auxiliary_client._RUNTIME_MAIN_PROVIDER", None),
        patch("agent.auxiliary_client._RUNTIME_MAIN_MODEL", None),
        patch(
            "agent.auxiliary_client._beta_auxiliary_policy_active",
            return_value=False,
        ),
        patch("elevate_cli.config.load_config", return_value=_config(model)),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_anthropic,
        ) as build_anthropic,
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_runtime_client,
        patch("agent.transports.get_transport", return_value=transport),
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
        patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=_run_in_place),
        ) as to_thread,
    ):
        if route == "direct":
            client, resolved_model = resolve_provider_client(
                "bedrock",
                model,
                async_mode=async_mode,
            )
        else:
            client, resolved_model = _get_cached_client(
                "auto",
                async_mode=async_mode,
            )

        create = client.chat.completions.create
        call = create(
            model=resolved_model,
            messages=[{"role": "user", "content": "Summarize this deal."}],
            timeout=9,
        )
        response = await call if async_mode else call

    expected_type = {
        ("claude", False): AnthropicAuxiliaryClient,
        ("claude", True): AsyncAnthropicAuxiliaryClient,
        ("nova", False): BedrockConverseAuxiliaryClient,
        ("nova", True): AsyncBedrockConverseAuxiliaryClient,
    }[(family, async_mode)]
    assert isinstance(client, expected_type)
    assert resolved_model == model
    assert client.base_url == FIPS_ENDPOINT
    assert response.choices[0].message.content == "config fips reply"
    openai_wire.assert_not_called()
    assert to_thread.await_count == (1 if async_mode else 0)

    if route == "auto":
        assert len(cache) == 1
        assert FIPS_ENDPOINT in repr(next(iter(cache)))
    else:
        assert cache == {}

    if family == "claude":
        build_anthropic.assert_called_once_with(
            "us-gov-west-1",
            base_url=FIPS_ENDPOINT,
        )
        real_anthropic.messages.create.assert_called_once()
        get_runtime_client.assert_not_called()
    else:
        build_anthropic.assert_not_called()
        get_runtime_client.assert_called_once_with(
            "us-gov-west-1",
            timeout=9,
            endpoint_url=FIPS_ENDPOINT,
        )
        runtime_client.converse.assert_called_once()
