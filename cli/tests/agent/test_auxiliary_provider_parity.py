"""Hostile provider-parity tests for auxiliary inference adapters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_codex_auxiliary_reuses_canonical_tool_pair_projection():
    from agent.auxiliary_client import _CodexCompletionsAdapter

    final = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text="done")],
            )
        ],
        usage=None,
    )

    class _CompletedStream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield SimpleNamespace(type="response.completed", response=final)

        def get_final_response(self):
            return final

    captured = {}

    def _stream(**kwargs):
        captured.update(kwargs)
        return _CompletedStream()

    client = SimpleNamespace(
        responses=SimpleNamespace(stream=_stream),
    )
    messages = [
        {"role": "system", "content": "Keep the deal record accurate."},
        {"role": "user", "content": "Look up the deal."},
        {
            "role": "assistant",
            "content": "Checking now.",
            "codex_reasoning_items": [
                {
                    "type": "reasoning",
                    "id": "rs_secret",
                    "encrypted_content": "encrypted-reasoning",
                    "summary": [],
                }
            ],
            "codex_message_items": [
                {
                    "type": "message",
                    "id": "msg_exact",
                    "role": "assistant",
                    "status": "completed",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "Checking now."}],
                }
            ],
            "tool_calls": [
                {
                    "id": "call_deal_1|fc_deal_1",
                    "type": "function",
                    "function": {
                        "name": "get_deal",
                        "arguments": '{"deal_id":"deal-7"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_deal_1|fc_deal_1",
            "content": '{"status":"active"}',
        },
    ]

    response = _CodexCompletionsAdapter(client, "gpt-5.5").create(messages=messages)

    assert response.choices[0].message.content == "done"
    assert captured["instructions"] == "Keep the deal record accurate."
    assert captured["input"] == [
        {"role": "user", "content": "Look up the deal."},
        {
            "type": "reasoning",
            "encrypted_content": "encrypted-reasoning",
            "summary": [],
        },
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Checking now."}],
            "id": "msg_exact",
            "phase": "final_answer",
        },
        {
            "type": "function_call",
            "call_id": "call_deal_1",
            "name": "get_deal",
            "arguments": '{"deal_id":"deal-7"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_deal_1",
            "output": '{"status":"active"}',
        },
    ]
    assert not any(item.get("role") == "tool" for item in captured["input"])


def test_non_claude_bedrock_auxiliary_calls_converse_not_messages():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    runtime_client = MagicMock()
    runtime_client.converse.return_value = {
        "modelId": "amazon.nova-lite-v1:0",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "native converse reply"}],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 4, "outputTokens": 3},
    }
    anthropic_client = MagicMock()

    with (
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.bedrock_adapter.resolve_bedrock_region", return_value="us-west-2"),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=anthropic_client,
        ) as build_anthropic,
    ):
        client, model = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Summarize the deal."}],
            max_tokens=321,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert response.choices[0].message.content == "native converse reply"
    runtime_client.converse.assert_called_once()
    assert runtime_client.converse.call_args.kwargs["modelId"] == "amazon.nova-lite-v1:0"
    assert runtime_client.converse.call_args.kwargs["inferenceConfig"]["maxTokens"] == 321
    build_anthropic.assert_not_called()
    anthropic_client.messages.create.assert_not_called()
    assert not hasattr(client, "close")
    runtime_client.close.assert_not_called()


def test_non_claude_bedrock_does_not_import_anthropic_helper():
    """Converse-only models remain usable without the optional Anthropic SDK."""
    import builtins

    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    runtime_client = MagicMock()
    real_import = builtins.__import__

    def _reject_anthropic_helper(name, globals=None, locals=None, fromlist=(), level=0):
        if (
            name == "agent.anthropic_adapter"
            and "build_anthropic_bedrock_client" in fromlist
        ):
            raise AssertionError("non-Claude Bedrock imported the Anthropic helper")
        return real_import(name, globals, locals, fromlist, level)

    with (
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.bedrock_adapter.resolve_bedrock_region", return_value="us-east-1"),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("builtins.__import__", side_effect=_reject_anthropic_helper),
    ):
        client, model = resolve_provider_client(
            "bedrock",
            "meta.llama3-3-70b-instruct-v1:0",
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert model == "meta.llama3-3-70b-instruct-v1:0"


def test_anthropic_auxiliary_threads_endpoint_identity_into_projection():
    from agent.auxiliary_client import AnthropicAuxiliaryClient

    endpoint = "https://third-party.example/anthropic"
    real_client = MagicMock()
    raw_response = SimpleNamespace(usage=None)
    real_client.messages.create.return_value = raw_response
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="ok",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )

    with (
        patch(
            "agent.anthropic_adapter.build_anthropic_kwargs",
            return_value={"model": "claude-sonnet-4-6", "messages": [], "max_tokens": 32},
        ) as build_kwargs,
        patch("agent.transports.get_transport", return_value=transport),
    ):
        client = AnthropicAuxiliaryClient(
            real_client,
            "claude-sonnet-4-6",
            api_key="test-key",
            base_url=endpoint,
        )
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
        )

    assert response.choices[0].message.content == "ok"
    assert build_kwargs.call_args.kwargs["base_url"] == endpoint
    real_client.messages.create.assert_called_once()


def test_default_bedrock_claude_task_timeout_reaches_sdk_request():
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    real_client = MagicMock()
    real_client.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="bounded",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )

    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter.resolve_bedrock_region",
            return_value="us-west-2",
        ),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_client,
        patch("agent.transports.get_transport", return_value=transport),
    ):
        client, model = resolve_provider_client("bedrock", None)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Summarize the deal."}],
            timeout=6.25,
        )

    assert isinstance(client, AnthropicAuxiliaryClient)
    assert response.choices[0].message.content == "bounded"
    build_client.assert_called_once_with("us-west-2")
    request = real_client.messages.create.call_args.kwargs
    assert request["timeout"] == 6.25


@pytest.mark.parametrize(
    "provider_alias",
    ["aws", "aws-bedrock", "amazon-bedrock", "amazon"],
)
def test_bedrock_aliases_route_to_native_auxiliary(provider_alias):
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    model = "anthropic.claude-sonnet-4-6-v1:0"
    real_client = MagicMock()
    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "us-west-2"}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_client,
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
    ):
        client, resolved_model = resolve_provider_client(provider_alias, model)

    assert isinstance(client, AnthropicAuxiliaryClient)
    assert resolved_model == model
    build_client.assert_called_once_with("us-west-2")
    openai_wire.assert_not_called()


def test_named_custom_provider_can_shadow_bedrock_alias():
    from agent.auxiliary_client import resolve_provider_client

    config = {
        "providers": {
            "aws": {
                "base_url": "https://custom.example/v1",
                "api_key": "custom-key",
                "default_model": "custom-model",
            }
        }
    }
    custom_client = MagicMock()
    custom_client.base_url = "https://custom.example/v1"
    with (
        patch("elevate_cli.runtime_provider.load_config", return_value=config),
        patch("elevate_cli.config.load_config", return_value=config),
        patch("agent.auxiliary_client.OpenAI", return_value=custom_client) as openai_wire,
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client"
        ) as build_bedrock,
    ):
        client, model = resolve_provider_client("aws", None)

    assert client is custom_client
    assert model == "custom-model"
    openai_wire.assert_called_once()
    build_bedrock.assert_not_called()


@pytest.mark.parametrize(
    ("region", "expected_model"),
    [
        (
            "us-east-1",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ),
        (
            "eu-west-1",
            "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        ),
        (
            "ap-southeast-2",
            "apac.anthropic.claude-haiku-4-5-20251001-v1:0",
        ),
    ],
)
def test_missing_bedrock_model_uses_region_safe_profile_in_request(
    region,
    expected_model,
):
    from agent.auxiliary_client import resolve_provider_client

    real_client = MagicMock()
    real_client.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="profile request",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )
    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": region}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ),
        patch("agent.transports.get_transport", return_value=transport),
    ):
        client, model = resolve_provider_client("bedrock", None)
        client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=4,
        )

    assert model == expected_model
    assert real_client.messages.create.call_args.kwargs["model"] == expected_model


def test_missing_bedrock_model_prefers_live_bedrock_runtime_model():
    from agent.auxiliary_client import resolve_provider_client

    runtime_model = "eu.anthropic.claude-sonnet-4-6"
    runtime = {
        "provider": "bedrock",
        "model": runtime_model,
        "region": "eu-west-1",
        "api_mode": "anthropic_messages",
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "guardrail_config": None,
    }
    real_client = MagicMock()
    real_client.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="main model request",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ),
        patch("agent.transports.get_transport", return_value=transport),
    ):
        client, model = resolve_provider_client(
            "bedrock",
            None,
            main_runtime=runtime,
        )
        client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=4,
        )

    assert model == runtime_model
    assert real_client.messages.create.call_args.kwargs["model"] == runtime_model


def test_missing_bedrock_model_prefers_live_nova_runtime_model():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    runtime_model = "eu.amazon.nova-lite-v1:0"
    runtime = {
        "provider": "bedrock",
        "model": runtime_model,
        "region": "eu-west-1",
        "api_mode": "bedrock_converse",
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "guardrail_config": None,
    }
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("nova runtime")
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
    ):
        client, model = resolve_provider_client(
            "bedrock",
            None,
            main_runtime=runtime,
        )
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=4,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert model == runtime_model
    assert response.choices[0].message.content == "nova runtime"
    assert runtime_client.converse.call_args.kwargs["modelId"] == runtime_model


def test_missing_bedrock_model_fails_closed_for_unknown_profile_geography():
    from agent.auxiliary_client import resolve_provider_client

    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "me-south-1"}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client"
        ) as build_client,
    ):
        client, model = resolve_provider_client("bedrock", None)

    assert client is None
    assert model is None
    build_client.assert_not_called()


def test_bedrock_claude_guardrail_is_enforced_via_invoke_headers():
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    config = {
        "bedrock": {
            "region": "eu-west-1",
            "guardrail": {
                "guardrail_identifier": "gr-claude",
                "guardrail_version": "4",
                "stream_processing_mode": "async",
                "trace": "enabled_full",
            },
        }
    }
    real_client = MagicMock()
    real_client.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="guarded",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ),
        patch("agent.transports.get_transport", return_value=transport),
    ):
        client, model = resolve_provider_client("bedrock", None)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Check this offer."}],
            timeout=5,
        )

    assert isinstance(client, AnthropicAuxiliaryClient)
    request = real_client.messages.create.call_args.kwargs
    assert request["extra_headers"] == {
        "X-Amzn-Bedrock-GuardrailIdentifier": "gr-claude",
        "X-Amzn-Bedrock-GuardrailVersion": "4",
        "X-Amzn-Bedrock-Trace": "ENABLED_FULL",
    }
    assert "streamProcessingMode" not in request["extra_headers"]


def test_partial_bedrock_guardrail_configuration_fails_closed():
    from agent.auxiliary_client import resolve_provider_client

    config = {
        "bedrock": {
            "guardrail": {
                "guardrail_identifier": "gr-incomplete",
                "guardrail_version": "",
                "stream_processing_mode": "async",
                "trace": "disabled",
            }
        }
    }
    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        pytest.raises(ValueError, match="both an identifier and version"),
    ):
        resolve_provider_client("bedrock", None)


def test_explicit_custom_fips_claude_uses_native_bedrock_builder_endpoint():
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    endpoint = "https://bedrock-runtime-fips.us-west-2.amazonaws.com/"
    canonical = endpoint.rstrip("/")
    real_client = MagicMock()
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_client,
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
    ):
        client, model = resolve_provider_client(
            "custom",
            "us.anthropic.claude-sonnet-4-6-v1:0",
            explicit_base_url=endpoint,
            explicit_api_key="must-not-be-used",
        )

    assert isinstance(client, AnthropicAuxiliaryClient)
    assert model == "us.anthropic.claude-sonnet-4-6-v1:0"
    assert client.base_url == canonical
    build_client.assert_called_once_with("us-west-2", base_url=canonical)
    openai_wire.assert_not_called()


def test_explicit_custom_fips_nova_reaches_actual_converse_endpoint_policy():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.eu-west-1.amazonaws.com"
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("fips native")
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_runtime_client,
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
    ):
        client, model = resolve_provider_client(
            "custom",
            "eu.amazon.nova-lite-v1:0",
            explicit_base_url=endpoint,
        )
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "Summarize this deal."}],
            timeout=7,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == endpoint
    assert response.choices[0].message.content == "fips native"
    get_runtime_client.assert_called_once_with(
        "eu-west-1",
        timeout=7,
        endpoint_url=endpoint,
    )
    assert runtime_client.converse.call_args.kwargs["modelId"] == model
    openai_wire.assert_not_called()


def test_live_main_runtime_fips_claude_preserves_endpoint_and_url_region():
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    endpoint = "https://bedrock-runtime-fips.eu-central-1.amazonaws.com"
    runtime = {
        "provider": "bedrock",
        "model": "eu.anthropic.claude-sonnet-4-6-v1:0",
        "api_mode": "anthropic_messages",
        "base_url": endpoint,
        "region": "us-east-1",  # stale metadata must not beat the endpoint
        "guardrail_config": None,
    }
    real_client = MagicMock()
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_client,
    ):
        client, model = resolve_provider_client(
            "bedrock",
            None,
            main_runtime=runtime,
        )

    assert isinstance(client, AnthropicAuxiliaryClient)
    assert model == runtime["model"]
    assert client.base_url == endpoint
    build_client.assert_called_once_with(
        "eu-central-1",
        base_url=endpoint,
    )


def test_live_main_runtime_fips_converse_preserves_endpoint_on_request():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.ap-southeast-2.amazonaws.com"
    runtime = {
        "provider": "bedrock",
        "model": "apac.amazon.nova-lite-v1:0",
        "api_mode": "bedrock_converse",
        "base_url": endpoint,
        "region": "ap-southeast-2",
        "guardrail_config": {
            "guardrail_identifier": "gr-live-snake",
            "guardrail_version": "3",
            "trace": "enabled",
        },
    }
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("live fips")
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_runtime_client,
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            None,
            main_runtime=runtime,
        )
        client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=6,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == endpoint
    get_runtime_client.assert_called_once_with(
        "ap-southeast-2",
        timeout=6,
        endpoint_url=endpoint,
    )
    assert runtime_client.converse.call_args.kwargs["guardrailConfig"] == {
        "guardrailIdentifier": "gr-live-snake",
        "guardrailVersion": "3",
        "trace": "enabled",
    }


def test_custom_provider_uses_normalized_live_bedrock_runtime_without_explicit_url():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.us-east-2.amazonaws.com"
    runtime = {
        "provider": "custom",
        "model": "amazon.nova-lite-v1:0",
        "api_mode": "bedrock_converse",
        "base_url": endpoint,
        "region": "us-east-2",
        "guardrail_config": None,
    }
    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
    ):
        client, model = resolve_provider_client(
            "custom",
            None,
            main_runtime=runtime,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == endpoint
    assert model == runtime["model"]
    openai_wire.assert_not_called()


@pytest.mark.parametrize("async_mode", [False, True])
def test_direct_bedrock_claude_honors_fips_environment_endpoint(async_mode):
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.ca-central-1.amazonaws.com"
    real_client = MagicMock()
    with (
        patch.dict("os.environ", {"BEDROCK_BASE_URL": endpoint}),
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "us-east-1"}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_client,
    ):
        client, model = resolve_provider_client(
            "bedrock",
            "anthropic.claude-sonnet-4-6-v1:0",
            async_mode=async_mode,
        )

    expected_type = (
        AsyncAnthropicAuxiliaryClient if async_mode else AnthropicAuxiliaryClient
    )
    assert isinstance(client, expected_type)
    assert model == "anthropic.claude-sonnet-4-6-v1:0"
    assert client.base_url == endpoint
    build_client.assert_called_once_with(
        "ca-central-1",
        base_url=endpoint,
    )


def test_direct_bedrock_converse_honors_fips_environment_endpoint():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com"
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("environment fips")
    with (
        patch.dict("os.environ", {"BEDROCK_BASE_URL": endpoint}),
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_runtime_client,
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
        )
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=5,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == endpoint
    assert response.choices[0].message.content == "environment fips"
    get_runtime_client.assert_called_once_with(
        "us-gov-west-1",
        timeout=5,
        endpoint_url=endpoint,
    )


@pytest.mark.asyncio
async def test_direct_async_bedrock_converse_honors_fips_environment_endpoint():
    from agent.auxiliary_client import (
        AsyncBedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime-fips.ap-northeast-1.amazonaws.com"
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("async environment fips")

    async def _run_in_place(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch.dict("os.environ", {"BEDROCK_BASE_URL": endpoint}),
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_runtime_client,
        patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=_run_in_place),
        ) as to_thread,
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            async_mode=True,
        )
        response = await client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=6,
        )

    assert isinstance(client, AsyncBedrockConverseAuxiliaryClient)
    assert client.base_url == endpoint
    assert response.choices[0].message.content == "async environment fips"
    get_runtime_client.assert_called_once_with(
        "ap-northeast-1",
        timeout=6,
        endpoint_url=endpoint,
    )
    assert to_thread.await_count == 1


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    "invalid_endpoint",
    [
        "http://bedrock-runtime-fips.us-east-1.amazonaws.com",
        "https://bedrock-runtime-fips.us-east-1.amazonaws.com.evil.example",
        "https://bedrock-runtime-fips.us-east-1.amazonaws.com@evil.example",
        "https://bedrock-runtime-fips.us-east-1.amazonaws.com:443",
        "https://bedrock-runtime-fips.us-east-1.amazonaws.com/v1",
        "https://bedrock-runtime-fips.us-east-1.amazonaws.com?redirect=evil",
    ],
)
def test_direct_bedrock_rejects_malformed_environment_endpoint(
    invalid_endpoint,
    async_mode,
):
    from agent.auxiliary_client import resolve_provider_client

    with (
        patch.dict("os.environ", {"BEDROCK_BASE_URL": invalid_endpoint}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client"
        ) as build_client,
        pytest.raises(ValueError, match="BEDROCK_BASE_URL"),
    ):
        resolve_provider_client(
            "bedrock",
            "anthropic.claude-sonnet-4-6-v1:0",
            async_mode=async_mode,
        )

    build_client.assert_not_called()


def test_direct_bedrock_rejects_malformed_environment_before_auth_check():
    from agent.auxiliary_client import resolve_provider_client

    with (
        patch.dict(
            "os.environ",
            {
                "BEDROCK_BASE_URL": (
                    "https://bedrock-runtime-fips.us-east-1.amazonaws.com.evil.example"
                )
            },
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=False),
        pytest.raises(ValueError, match="BEDROCK_BASE_URL"),
    ):
        resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
        )


def test_direct_bedrock_cache_identity_tracks_environment_endpoint():
    from agent.auxiliary_client import _client_cache_key

    fips_endpoint = "https://bedrock-runtime-fips.us-west-1.amazonaws.com"
    standard_endpoint = "https://bedrock-runtime.us-west-1.amazonaws.com"
    with patch("elevate_cli.config.load_config", return_value={"bedrock": {}}):
        with patch.dict("os.environ", {"BEDROCK_BASE_URL": fips_endpoint}):
            fips_key = _client_cache_key(
                "bedrock",
                model="amazon.nova-lite-v1:0",
                async_mode=False,
            )
        with patch.dict("os.environ", {"BEDROCK_BASE_URL": standard_endpoint}):
            standard_key = _client_cache_key(
                "bedrock",
                model="amazon.nova-lite-v1:0",
                async_mode=False,
            )

    assert fips_key != standard_key
    assert fips_endpoint in repr(fips_key)
    assert standard_endpoint in repr(standard_key)


@pytest.mark.parametrize(
    ("model", "expected_type"),
    [
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude"),
        ("amazon.nova-lite-v1:0", "converse"),
    ],
)
def test_named_custom_bedrock_alias_routes_native_by_model(model, expected_type):
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    endpoint = "https://bedrock-runtime.us-east-1.amazonaws.com"
    real_client = MagicMock()
    custom_entry = {
        "name": "deal-aws",
        "base_url": endpoint,
        "model": model,
        "api_mode": "chat_completions",
    }
    with (
        patch(
            "elevate_cli.runtime_provider._get_named_custom_provider",
            return_value=custom_entry,
        ),
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=real_client,
        ) as build_claude,
        patch("agent.auxiliary_client.OpenAI") as openai_wire,
    ):
        client, resolved_model = resolve_provider_client("deal-aws", None)

    assert resolved_model == model
    if expected_type == "claude":
        assert isinstance(client, AnthropicAuxiliaryClient)
        build_claude.assert_called_once_with("us-east-1")
    else:
        assert isinstance(client, BedrockConverseAuxiliaryClient)
        build_claude.assert_not_called()
    assert client.base_url == endpoint
    openai_wire.assert_not_called()


@pytest.mark.parametrize(
    "lookalike",
    [
        "http://bedrock-runtime.us-east-1.amazonaws.com",
        "https://bedrock-runtime.us-east-1.amazonaws.com.evil.example",
        "https://bedrock-runtime.us-east-1.amazonaws.com@evil.example",
        "https://bedrock-runtime.us-east-1.amazonaws.com:443",
        "https://bedrock-runtime.us-east-1.amazonaws.com/v1",
        "https://bedrock-runtime.us-east-1.amazonaws.com?redirect=evil",
    ],
)
def test_custom_bedrock_lookalikes_never_inherit_aws_sdk_routing(lookalike):
    from agent.auxiliary_client import resolve_provider_client

    openai_client = MagicMock()
    with (
        patch("agent.auxiliary_client.OpenAI", return_value=openai_client) as openai_wire,
        patch("agent.bedrock_adapter.has_aws_credentials") as aws_credentials,
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client"
        ) as build_bedrock,
    ):
        client, _ = resolve_provider_client(
            "custom",
            "amazon.nova-lite-v1:0",
            explicit_base_url=lookalike,
            explicit_api_key="custom-key",
        )

    assert client is openai_client
    openai_wire.assert_called_once()
    aws_credentials.assert_not_called()
    build_bedrock.assert_not_called()


def test_camel_case_bedrock_guardrail_config_matches_snake_case_policy():
    from agent.auxiliary_client import resolve_provider_client

    config = {
        "bedrock": {
            "region": "eu-west-2",
            "guardrail": {
                "guardrailIdentifier": "gr-camel",
                "guardrailVersion": "12",
                "streamProcessingMode": "ASYNC",
                "trace": "ENABLED_FULL",
            },
        }
    }
    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
        )

    assert client.chat.completions._guardrail_config == {
        "guardrailIdentifier": "gr-camel",
        "guardrailVersion": "12",
        "streamProcessingMode": "async",
        "trace": "enabled_full",
    }


@pytest.mark.parametrize(
    "guardrail",
    [
        {"guardrailIdentifier": "gr-partial"},
        {
            "guardrail_identifier": "gr-conflict-a",
            "guardrailIdentifier": "gr-conflict-b",
            "guardrail_version": "1",
        },
        {
            "guardrail_identifier": "gr-unknown",
            "guardrail_version": "1",
            "allow_unguarded_fallback": True,
        },
    ],
)
def test_malformed_or_unknown_guardrail_policy_fails_closed(guardrail):
    from agent.auxiliary_client import resolve_provider_client

    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"guardrail": guardrail}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        pytest.raises(ValueError),
    ):
        resolve_provider_client("bedrock", "amazon.nova-lite-v1:0")


_ANTHROPIC_TOOL = {
    "type": "function",
    "function": {
        "name": "get_deal",
        "description": "Load a deal record.",
        "parameters": {"type": "object", "properties": {}},
    },
}


@pytest.mark.parametrize("provider_kind", ["native", "bedrock-claude"])
@pytest.mark.parametrize(
    ("tool_choice", "expected_tool_choice"),
    [
        (None, {"type": "auto", "disable_parallel_tool_use": True}),
        ("auto", {"type": "auto", "disable_parallel_tool_use": True}),
        ("required", {"type": "any", "disable_parallel_tool_use": True}),
        (
            {"type": "function", "function": {"name": "get_deal"}},
            {
                "type": "tool",
                "name": "get_deal",
                "disable_parallel_tool_use": True,
            },
        ),
        ("none", None),
    ],
)
def test_anthropic_native_and_bedrock_tool_contract_capture(
    provider_kind,
    tool_choice,
    expected_tool_choice,
):
    from agent.auxiliary_client import AnthropicAuxiliaryClient, resolve_provider_client

    real_client = MagicMock()
    real_client.messages.create.return_value = SimpleNamespace(usage=None)
    transport = MagicMock()
    transport.normalize_response.return_value = SimpleNamespace(
        content="tool contract captured",
        tool_calls=None,
        reasoning=None,
        finish_reason="stop",
    )

    if provider_kind == "native":
        client = AnthropicAuxiliaryClient(
            real_client,
            "claude-sonnet-4-6",
            api_key="test-key",
            base_url="https://api.anthropic.com",
        )
        model = "claude-sonnet-4-6"
        with patch("agent.transports.get_transport", return_value=transport):
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Check the deal."}],
                tools=[_ANTHROPIC_TOOL],
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                timeout=5,
            )
    else:
        with (
            patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
            patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
            patch(
                "agent.bedrock_adapter.resolve_bedrock_region",
                return_value="us-east-1",
            ),
            patch(
                "agent.anthropic_adapter.build_anthropic_bedrock_client",
                return_value=real_client,
            ),
            patch("agent.transports.get_transport", return_value=transport),
        ):
            client, model = resolve_provider_client("bedrock", None)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Check the deal."}],
                tools=[_ANTHROPIC_TOOL],
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                timeout=5,
            )

    assert isinstance(client, AnthropicAuxiliaryClient)
    request = real_client.messages.create.call_args.kwargs
    if expected_tool_choice is None:
        assert "tools" not in request
        assert "tool_choice" not in request
    else:
        assert request["tools"][0]["name"] == "get_deal"
        assert request["tool_choice"] == expected_tool_choice


@pytest.mark.parametrize(
    "tool_choice",
    [
        {"type": "parallel_if_possible"},
        {"type": "function", "function": {}},
        {"type": "function", "function": {"name": "missing_tool"}},
    ],
)
def test_anthropic_invalid_tool_choice_dict_fails_before_request(tool_choice):
    from agent.auxiliary_client import AnthropicAuxiliaryClient

    real_client = MagicMock()
    client = AnthropicAuxiliaryClient(
        real_client,
        "claude-sonnet-4-6",
        api_key="test-key",
        base_url="https://api.anthropic.com",
    )

    with pytest.raises(ValueError, match="Anthropic auxiliary|unknown tool"):
        client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            tools=[_ANTHROPIC_TOOL],
            tool_choice=tool_choice,
        )
    real_client.messages.create.assert_not_called()


def test_anthropic_parallel_tool_calls_must_be_boolean():
    from agent.auxiliary_client import AnthropicAuxiliaryClient

    real_client = MagicMock()
    client = AnthropicAuxiliaryClient(
        real_client,
        "claude-sonnet-4-6",
        api_key="test-key",
        base_url="https://api.anthropic.com",
    )

    with pytest.raises(ValueError, match="parallel_tool_calls must be a boolean"):
        client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            tools=[_ANTHROPIC_TOOL],
            parallel_tool_calls="false",
        )
    real_client.messages.create.assert_not_called()


def _capture_codex_request(**create_kwargs):
    from agent.auxiliary_client import _CodexCompletionsAdapter

    final = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text="ok")],
            )
        ],
        usage=None,
    )

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield SimpleNamespace(type="response.completed", response=final)

        def get_final_response(self):
            return final

    captured = {}

    def _stream(**kwargs):
        captured.update(kwargs)
        return _Stream()

    client = SimpleNamespace(responses=SimpleNamespace(stream=_stream))
    _CodexCompletionsAdapter(client, "gpt-5.5").create(
        messages=[{"role": "user", "content": "use the tool"}],
        **create_kwargs,
    )
    return captured


@pytest.mark.parametrize(
    ("tool_choice", "expected"),
    [
        ("required", "required"),
        ("none", "none"),
        (
            {"type": "function", "function": {"name": "get_deal"}},
            {"type": "function", "name": "get_deal"},
        ),
    ],
)
def test_codex_auxiliary_preserves_tool_contract(tool_choice, expected):
    captured = _capture_codex_request(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_deal",
                    "description": "Read one deal",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": True,
                },
            }
        ],
        tool_choice=tool_choice,
        parallel_tool_calls=False,
        extra_body={"reasoning": {"effort": "xhigh"}},
    )

    assert captured["tools"] == [
        {
            "type": "function",
            "name": "get_deal",
            "description": "Read one deal",
            "strict": True,
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert captured["tool_choice"] == expected
    assert captured["parallel_tool_calls"] is False
    assert captured["reasoning"]["effort"] == "high"


def test_codex_required_tool_choice_without_tools_fails_before_network():
    from agent.auxiliary_client import _CodexCompletionsAdapter

    client = MagicMock()
    with pytest.raises(ValueError, match="needs at least one valid tool"):
        _CodexCompletionsAdapter(client, "gpt-5.5").create(
            messages=[{"role": "user", "content": "hi"}],
            tool_choice="required",
        )
    client.responses.stream.assert_not_called()


def test_build_call_kwargs_promotes_tool_controls_out_of_extra_body():
    from agent.auxiliary_client import _build_call_kwargs

    with patch("agent.auxiliary_client.auxiliary_is_nous", False):
        kwargs = _build_call_kwargs(
            "bedrock",
            "amazon.nova-lite-v1:0",
            [{"role": "user", "content": "hi"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_deal",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            extra_body={
                "tool_choice": "required",
                "parallel_tool_calls": False,
                "provider_extension": "keep-me",
            },
        )

    assert kwargs["tool_choice"] == "required"
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["extra_body"] == {"provider_extension": "keep-me"}


def test_bedrock_runtime_client_cache_is_timeout_aware_and_retry_bounded():
    from agent.bedrock_adapter import (
        _get_bedrock_runtime_client,
        reset_client_cache,
    )

    boto3 = MagicMock()
    first = MagicMock(name="first")
    second = MagicMock(name="second")
    boto3.client.side_effect = [first, second]
    reset_client_cache()
    try:
        with patch("agent.bedrock_adapter._require_boto3", return_value=boto3):
            assert _get_bedrock_runtime_client("eu-west-1", timeout=7.5) is first
            assert _get_bedrock_runtime_client("eu-west-1", timeout=7.5) is first
            assert _get_bedrock_runtime_client("eu-west-1", timeout=11) is second
    finally:
        reset_client_cache()

    assert boto3.client.call_count == 2
    first_config = boto3.client.call_args_list[0].kwargs["config"]
    second_config = boto3.client.call_args_list[1].kwargs["config"]
    assert first_config.connect_timeout == 7.5
    assert first_config.read_timeout == 7.5
    assert first_config.retries["total_max_attempts"] == 1
    assert second_config.connect_timeout == 11.0
    assert second_config.read_timeout == 11.0
    assert second_config.retries["total_max_attempts"] == 1


def test_bedrock_timeout_invalidation_evicts_only_exact_policy():
    from agent.bedrock_adapter import (
        _bedrock_runtime_client_cache,
        invalidate_runtime_client,
        reset_client_cache,
    )

    reset_client_cache()
    try:
        _bedrock_runtime_client_cache[("eu-west-1", 7.0)] = "dead"
        _bedrock_runtime_client_cache[("eu-west-1", 11.0)] = "other-timeout"
        _bedrock_runtime_client_cache["eu-west-1"] = "main-runtime"
        _bedrock_runtime_client_cache[("us-east-1", 7.0)] = "other-region"

        assert invalidate_runtime_client("eu-west-1", timeout=7) is True
        assert ("eu-west-1", 7.0) not in _bedrock_runtime_client_cache
        assert _bedrock_runtime_client_cache[("eu-west-1", 11.0)] == "other-timeout"
        assert _bedrock_runtime_client_cache["eu-west-1"] == "main-runtime"
        assert _bedrock_runtime_client_cache[("us-east-1", 7.0)] == "other-region"
    finally:
        reset_client_cache()


def test_bedrock_identity_aware_invalidation_preserves_fresh_replacement():
    from agent.bedrock_adapter import (
        _bedrock_runtime_client_cache,
        invalidate_runtime_client,
        reset_client_cache,
    )

    stale_client = object()
    fresh_client = object()
    cache_key = ("eu-west-1", 7.0)
    reset_client_cache()
    try:
        # A newer request has already installed its replacement by the time
        # the old request reports a late stale-connection failure.
        _bedrock_runtime_client_cache[cache_key] = fresh_client

        assert invalidate_runtime_client(
            "eu-west-1",
            timeout=7,
            expected_client=stale_client,
        ) is False
        assert _bedrock_runtime_client_cache[cache_key] is fresh_client
        assert invalidate_runtime_client(
            "eu-west-1",
            timeout=7,
            expected_client=fresh_client,
        ) is True
        assert cache_key not in _bedrock_runtime_client_cache
    finally:
        reset_client_cache()


def test_call_converse_stream_evicts_exact_client_on_midstream_stale_error():
    from botocore.exceptions import ReadTimeoutError

    from agent.bedrock_adapter import (
        _bedrock_runtime_client_cache,
        call_converse_stream,
        reset_client_cache,
    )

    def _broken_events():
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": "partial"}}}
        raise ReadTimeoutError(
            endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
        )

    poisoned = MagicMock()
    poisoned.converse_stream.return_value = {"stream": _broken_events()}
    reset_client_cache()
    try:
        _bedrock_runtime_client_cache["us-east-1"] = poisoned
        with pytest.raises(ReadTimeoutError):
            call_converse_stream(
                region="us-east-1",
                model="amazon.nova-lite-v1:0",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert "us-east-1" not in _bedrock_runtime_client_cache
    finally:
        reset_client_cache()

    poisoned.converse_stream.assert_called_once()
    poisoned.close.assert_not_called()


def test_late_midstream_failure_cannot_evict_fresh_stream_client():
    from botocore.exceptions import ReadTimeoutError

    from agent.bedrock_adapter import (
        _bedrock_runtime_client_cache,
        call_converse_stream,
        reset_client_cache,
    )

    poisoned = MagicMock()
    fresh = MagicMock()

    def _replace_then_fail():
        yield {"messageStart": {"role": "assistant"}}
        _bedrock_runtime_client_cache["eu-west-1"] = fresh
        raise ReadTimeoutError(
            endpoint_url="https://bedrock-runtime.eu-west-1.amazonaws.com"
        )

    poisoned.converse_stream.return_value = {"stream": _replace_then_fail()}
    reset_client_cache()
    try:
        _bedrock_runtime_client_cache["eu-west-1"] = poisoned
        with pytest.raises(ReadTimeoutError):
            call_converse_stream(
                region="eu-west-1",
                model="amazon.nova-lite-v1:0",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert _bedrock_runtime_client_cache["eu-west-1"] is fresh
    finally:
        reset_client_cache()

    poisoned.converse_stream.assert_called_once()
    fresh.converse_stream.assert_not_called()
    poisoned.close.assert_not_called()


def _bedrock_success(text="ok"):
    return {
        "modelId": "amazon.nova-lite-v1:0",
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }


def _chat_success(text="ok"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )


def test_evict_async_wrapper_removes_shared_leaf_but_preserves_replacement():
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        _client_cache,
        _evict_cached_client_instance,
    )

    poisoned_leaf = MagicMock()
    poisoned_sync = AnthropicAuxiliaryClient(
        poisoned_leaf,
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        api_key="aws-sdk",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        is_bedrock=True,
    )
    poisoned_async = AsyncAnthropicAuxiliaryClient(poisoned_sync)
    fresh_leaf = MagicMock()
    fresh = AnthropicAuxiliaryClient(
        fresh_leaf,
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        api_key="aws-sdk",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        is_bedrock=True,
    )

    old_cache = dict(_client_cache)
    try:
        _client_cache.clear()
        _client_cache["poisoned-sync"] = (poisoned_sync, "model", None)
        _client_cache["poisoned-async"] = (poisoned_async, "model", None)
        _client_cache["fresh-replacement"] = (fresh, "model", None)

        assert _evict_cached_client_instance(poisoned_async) is True
        assert "poisoned-sync" not in _client_cache
        assert "poisoned-async" not in _client_cache
        assert _client_cache["fresh-replacement"][0] is fresh
    finally:
        _client_cache.clear()
        _client_cache.update(old_cache)


def test_sync_successful_configured_fallback_evicts_bedrock_claude_and_rebuilds():
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        _get_cached_client,
        call_llm,
    )

    bedrock_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    poisoned_leaf = MagicMock()
    poisoned_leaf.messages.create.side_effect = ConnectionError("dead Bedrock socket")
    poisoned = AnthropicAuxiliaryClient(
        poisoned_leaf,
        bedrock_model,
        api_key="aws-sdk",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        is_bedrock=True,
    )
    fallback = MagicMock()
    fallback.base_url = "https://openrouter.ai/api/v1"
    fallback.chat.completions.create.return_value = _chat_success("fallback")
    fresh = MagicMock(name="fresh-bedrock-claude")
    cache = {("primary",): (poisoned, bedrock_model, None)}

    def _resolve(
        provider,
        model=None,
        async_mode=False,
        raw_codex=False,
        explicit_base_url=None,
        explicit_api_key=None,
        api_mode=None,
        main_runtime=None,
        is_vision=False,
    ):
        del raw_codex, api_mode, main_runtime, is_vision
        if provider == "openrouter":
            assert model is None
            assert explicit_base_url is None
            assert explicit_api_key is None
            assert async_mode is False
            return fallback, "openrouter/default-model"
        assert provider == "bedrock"
        assert model == bedrock_model
        return fresh, bedrock_model

    with (
        patch("agent.auxiliary_client._client_cache", cache),
        patch("agent.auxiliary_client._client_cache_key", return_value=("primary",)),
        patch("agent.auxiliary_client._beta_auxiliary_policy_active", return_value=False),
        patch(
            "agent.auxiliary_client._resolve_task_provider_model",
            return_value=("bedrock", bedrock_model, None, None, None),
        ),
        patch(
            "agent.auxiliary_client._get_auxiliary_task_config",
            return_value={"fallback_chain": [{"provider": "openrouter"}]},
        ),
        patch(
            "agent.auxiliary_client._try_main_agent_model_fallback",
            return_value=(None, None, ""),
        ),
        patch("agent.auxiliary_client.resolve_provider_client", side_effect=_resolve),
    ):
        response = call_llm(
            task="compression",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert cache == {}
        rebuilt, rebuilt_model = _get_cached_client("bedrock", bedrock_model)

    assert response.choices[0].message.content == "fallback"
    assert fallback.chat.completions.create.call_args.kwargs["model"] == (
        "openrouter/default-model"
    )
    assert rebuilt is fresh
    assert rebuilt_model == bedrock_model
    assert poisoned_leaf.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_async_successful_configured_fallback_evicts_before_return_and_rebuilds():
    import asyncio

    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        _get_cached_client,
        async_call_llm,
    )

    bedrock_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    poisoned_leaf = MagicMock()
    poisoned_sync = AnthropicAuxiliaryClient(
        poisoned_leaf,
        bedrock_model,
        api_key="aws-sdk",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        is_bedrock=True,
    )
    poisoned = AsyncAnthropicAuxiliaryClient(poisoned_sync)
    poisoned.chat.completions.create = AsyncMock(
        side_effect=ConnectionError("dead async Bedrock socket")
    )
    fallback_sync = MagicMock()
    fallback_sync.base_url = "https://openrouter.ai/api/v1"
    fallback_async = MagicMock()
    fallback_async.chat.completions.create = AsyncMock(
        return_value=_chat_success("async fallback")
    )
    fresh = MagicMock(name="fresh-async-bedrock-claude")
    loop = asyncio.get_running_loop()
    cache = {("primary",): (poisoned, bedrock_model, loop)}

    def _resolve(
        provider,
        model=None,
        async_mode=False,
        raw_codex=False,
        explicit_base_url=None,
        explicit_api_key=None,
        api_mode=None,
        main_runtime=None,
        is_vision=False,
    ):
        del raw_codex, api_mode, main_runtime, is_vision
        if provider == "openrouter":
            assert model is None
            assert explicit_base_url is None
            assert explicit_api_key is None
            assert async_mode is False
            return fallback_sync, "openrouter/default-model"
        assert provider == "bedrock"
        assert model == bedrock_model
        assert async_mode is True
        return fresh, bedrock_model

    with (
        patch("agent.auxiliary_client._client_cache", cache),
        patch("agent.auxiliary_client._client_cache_key", return_value=("primary",)),
        patch("agent.auxiliary_client._beta_auxiliary_policy_active", return_value=False),
        patch(
            "agent.auxiliary_client._resolve_task_provider_model",
            return_value=("bedrock", bedrock_model, None, None, None),
        ),
        patch(
            "agent.auxiliary_client._get_auxiliary_task_config",
            return_value={"fallback_chain": [{"provider": "openrouter"}]},
        ),
        patch(
            "agent.auxiliary_client._try_main_agent_model_fallback",
            return_value=(None, None, ""),
        ),
        patch("agent.auxiliary_client.resolve_provider_client", side_effect=_resolve),
        patch(
            "agent.auxiliary_client._to_async_client",
            return_value=(fallback_async, "openrouter/default-model"),
        ),
    ):
        response = await async_call_llm(
            task="session_search",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert cache == {}
        rebuilt, rebuilt_model = _get_cached_client(
            "bedrock",
            bedrock_model,
            async_mode=True,
        )

    assert response.choices[0].message.content == "async fallback"
    assert fallback_async.chat.completions.create.call_args.kwargs["model"] == (
        "openrouter/default-model"
    )
    assert rebuilt is fresh
    assert rebuilt_model == bedrock_model
    assert poisoned.chat.completions.create.await_count == 1


def test_main_agent_fallback_prefers_switched_live_runtime_over_stale_config():
    from agent.auxiliary_client import _try_main_agent_model_fallback

    live_model = "eu.anthropic.claude-sonnet-4-6"
    live_guardrail = {
        "guardrailIdentifier": "gr-live-fallback",
        "guardrailVersion": "5",
        "trace": "enabled",
    }
    runtime = {
        "provider": "bedrock",
        "model": live_model,
        "api_mode": "anthropic_messages",
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "api_key": "aws-sdk",
        "region": "eu-west-1",
        "guardrail_config": live_guardrail,
    }
    live_client = MagicMock()

    with (
        patch("agent.auxiliary_client._read_main_provider", return_value="anthropic"),
        patch(
            "agent.auxiliary_client._read_main_model",
            return_value="claude-haiku-4-5",
        ),
        patch("agent.auxiliary_client._is_provider_unhealthy", return_value=False),
        patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(live_client, live_model),
        ) as resolve,
    ):
        client, model, label = _try_main_agent_model_fallback(
            "openrouter",
            task="compression",
            reason="connection error",
            main_runtime=runtime,
        )

    assert client is live_client
    assert model == live_model
    assert label == "main-agent(bedrock)"
    resolve.assert_called_once_with(
        provider="bedrock",
        model=live_model,
        main_runtime=runtime,
    )


def test_bedrock_converse_re_resolves_after_exact_policy_stale_error():
    from botocore.exceptions import ReadTimeoutError

    from agent.auxiliary_client import BedrockConverseAuxiliaryClient

    poisoned = MagicMock()
    poisoned.converse.side_effect = ReadTimeoutError(
        endpoint_url="https://bedrock-runtime.eu-west-1.amazonaws.com"
    )
    fresh = MagicMock()
    fresh.converse.return_value = _bedrock_success("fresh")
    wrapper = BedrockConverseAuxiliaryClient(
        "amazon.nova-lite-v1:0",
        "eu-west-1",
    )

    with (
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            side_effect=[poisoned, fresh],
        ) as get_client,
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
    ):
        with pytest.raises(ReadTimeoutError):
            wrapper.chat.completions.create(
                messages=[{"role": "user", "content": "first"}],
                timeout=9,
            )
        assert get_client.call_count == 1
        poisoned.converse.assert_called_once()
        poisoned.close.assert_not_called()
        invalidate.assert_called_once_with(
            "eu-west-1",
            timeout=9,
            expected_client=poisoned,
        )

        response = wrapper.chat.completions.create(
            messages=[{"role": "user", "content": "second"}],
            timeout=9,
        )

    assert response.choices[0].message.content == "fresh"
    assert get_client.call_count == 2
    fresh.converse.assert_called_once()


@pytest.mark.asyncio
async def test_async_bedrock_converse_awaits_to_thread():
    from agent.auxiliary_client import (
        AsyncBedrockConverseAuxiliaryClient,
        BedrockConverseAuxiliaryClient,
    )

    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success("async")
    wrapper = AsyncBedrockConverseAuxiliaryClient(
        BedrockConverseAuxiliaryClient(
            "amazon.nova-lite-v1:0",
            "us-west-2",
        )
    )

    async def _run_in_place(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("asyncio.to_thread", new=AsyncMock(side_effect=_run_in_place)) as to_thread,
    ):
        response = await wrapper.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=4,
        )

    assert response.choices[0].message.content == "async"
    assert to_thread.await_count == 1


def test_bedrock_region_guardrail_runtime_policy_reaches_cache_and_request():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        _client_cache_key,
        resolve_provider_client,
    )

    runtime = {
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "region": "eu-west-1",
        "guardrail_config": {
            "guardrailIdentifier": "gr-runtime",
            "guardrailVersion": "7",
            "trace": "enabled",
        },
    }
    other_runtime = {
        **runtime,
        "region": "eu-central-1",
    }
    runtime_client = MagicMock()
    runtime_client.converse.return_value = _bedrock_success()

    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
    ):
        key = _client_cache_key(
            "bedrock",
            model="amazon.nova-lite-v1:0",
            async_mode=False,
            main_runtime=runtime,
        )
        other_key = _client_cache_key(
            "bedrock",
            model="amazon.nova-lite-v1:0",
            async_mode=False,
            main_runtime=other_runtime,
        )
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            main_runtime=runtime,
        )
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": "hi"}],
            timeout=8,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == "https://bedrock-runtime.eu-west-1.amazonaws.com"
    assert key != other_key
    assert response.choices[0].message.content == "ok"
    assert runtime_client.converse.call_args.kwargs["guardrailConfig"] == {
        "guardrailIdentifier": "gr-runtime",
        "guardrailVersion": "7",
        "trace": "enabled",
    }


def test_bedrock_live_runtime_base_url_region_beats_stale_config_region():
    from agent.auxiliary_client import (
        BedrockConverseAuxiliaryClient,
        resolve_provider_client,
    )

    runtime = {
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "api_key": "aws-sdk",
        "api_mode": "bedrock_converse",
    }
    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "us-east-1"}},
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.bedrock_adapter.resolve_bedrock_region") as env_fallback,
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            main_runtime=runtime,
        )

    assert isinstance(client, BedrockConverseAuxiliaryClient)
    assert client.base_url == "https://bedrock-runtime.eu-west-1.amazonaws.com"
    env_fallback.assert_not_called()


@pytest.mark.parametrize("explicit_guardrail", [None, {}])
def test_live_disabled_guardrail_does_not_fall_back_to_later_config(
    explicit_guardrail,
):
    from agent.auxiliary_client import resolve_provider_client

    runtime = {
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "region": "eu-west-1",
        "guardrail_config": explicit_guardrail,
    }
    later_config = {
        "bedrock": {
            "region": "us-east-1",
            "guardrail": {
                "guardrail_identifier": "gr-configured-later",
                "guardrail_version": "9",
                "stream_processing_mode": "async",
                "trace": "enabled",
            },
        }
    }
    with (
        patch("elevate_cli.config.load_config", return_value=later_config),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            main_runtime=runtime,
        )

    assert client.chat.completions._guardrail_config is None


def test_actual_agent_runtime_freezes_live_bedrock_guardrail_over_stale_config():
    from agent.auxiliary_client import _resolve_bedrock_auxiliary_policy
    from run_agent import AIAgent

    live_guardrail = {
        "guardrailIdentifier": "gr-live",
        "guardrailVersion": "9",
        "trace": "enabled",
    }
    agent = object.__new__(AIAgent)
    agent.model = "amazon.nova-lite-v1:0"
    agent.provider = "bedrock"
    agent.base_url = "https://bedrock-runtime.eu-west-1.amazonaws.com"
    agent.api_key = "aws-sdk"
    agent.api_mode = "bedrock_converse"
    agent._bedrock_region = "eu-west-1"
    agent._bedrock_guardrail_config = live_guardrail

    stale_config = {
        "bedrock": {
            "region": "us-east-1",
            "guardrail": {
                "guardrail_identifier": "gr-stale-config",
                "guardrail_version": "1",
            },
        }
    }
    with patch("elevate_cli.config.load_config", return_value=stale_config):
        runtime = agent._current_main_runtime()
        region, guardrail = _resolve_bedrock_auxiliary_policy(runtime)

    assert region == "eu-west-1"
    assert guardrail == live_guardrail
    assert runtime["guardrail_config"] is not live_guardrail


def test_actual_non_bedrock_runtime_does_not_disable_auxiliary_bedrock_guardrail():
    from agent.auxiliary_client import _resolve_bedrock_auxiliary_policy
    from run_agent import AIAgent

    agent = object.__new__(AIAgent)
    agent.model = "gpt-5.5"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.api_key = "oauth-token"
    agent.api_mode = "codex_responses"

    auxiliary_bedrock_config = {
        "bedrock": {
            "region": "eu-west-1",
            "guardrail": {
                "guardrail_identifier": "gr-auxiliary",
                "guardrail_version": "6",
                "stream_processing_mode": "async",
                "trace": "enabled",
            },
        }
    }
    with patch(
        "elevate_cli.config.load_config",
        return_value=auxiliary_bedrock_config,
    ):
        runtime = agent._current_main_runtime()
        region, guardrail = _resolve_bedrock_auxiliary_policy(runtime)

    assert region == "eu-west-1"
    assert guardrail == {
        "guardrailIdentifier": "gr-auxiliary",
        "guardrailVersion": "6",
        "streamProcessingMode": "async",
        "trace": "enabled",
    }


def test_malformed_config_guardrail_fails_closed_for_explicit_aux_bedrock():
    from agent.auxiliary_client import resolve_provider_client
    from run_agent import AIAgent

    agent = object.__new__(AIAgent)
    agent.model = "gpt-5.5"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.api_key = "oauth-token"
    agent.api_mode = "codex_responses"
    runtime = agent._current_main_runtime()

    with (
        patch(
            "elevate_cli.config.load_config",
            return_value={
                "bedrock": {
                    "region": "eu-west-1",
                    "guardrail": "malformed-policy",
                }
            },
        ),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client"
        ) as runtime_client,
        pytest.raises(ValueError, match="guardrail configuration must be a mapping"),
    ):
        resolve_provider_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            main_runtime=runtime,
        )

    runtime_client.assert_not_called()


def test_malformed_live_bedrock_guardrail_fails_closed():
    from agent.auxiliary_client import _resolve_bedrock_auxiliary_policy
    from run_agent import AIAgent

    agent = object.__new__(AIAgent)
    agent.model = "amazon.nova-lite-v1:0"
    agent.provider = "bedrock"
    agent.base_url = "https://bedrock-runtime.eu-west-1.amazonaws.com"
    agent.api_key = "aws-sdk"
    agent.api_mode = "bedrock_converse"
    agent._bedrock_region = "eu-west-1"
    agent._bedrock_guardrail_config = "malformed-live-policy"
    runtime = agent._current_main_runtime()

    with (
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        pytest.raises(ValueError, match="guardrail configuration must be a mapping"),
    ):
        _resolve_bedrock_auxiliary_policy(runtime)


def test_bedrock_config_region_and_guardrail_are_resolved_exactly():
    from agent.auxiliary_client import resolve_provider_client

    config = {
        "bedrock": {
            "region": "eu-west-2",
            "guardrail": {
                "guardrail_identifier": "gr-config",
                "guardrail_version": "3",
                "stream_processing_mode": "async",
            },
        }
    }
    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
    ):
        client, _ = resolve_provider_client(
            "bedrock",
            "meta.llama3-3-70b-instruct-v1:0",
        )

    adapter = client.chat.completions
    assert client.base_url == "https://bedrock-runtime.eu-west-2.amazonaws.com"
    assert adapter._guardrail_config == {
        "guardrailIdentifier": "gr-config",
        "guardrailVersion": "3",
        "streamProcessingMode": "async",
    }


def test_non_streaming_converse_guardrail_passes_botocore_validation():
    import boto3
    from botocore.stub import Stubber

    from agent.auxiliary_client import BedrockConverseAuxiliaryClient

    runtime_client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    expected = {
        "modelId": "amazon.nova-lite-v1:0",
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        "inferenceConfig": {"maxTokens": 2000},
        "guardrailConfig": {
            "guardrailIdentifier": "gr-converse",
            "guardrailVersion": "2",
            "trace": "enabled",
        },
    }
    raw_response = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "locally validated"}],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
        "metrics": {"latencyMs": 1},
    }
    wrapper = BedrockConverseAuxiliaryClient(
        "amazon.nova-lite-v1:0",
        "us-east-1",
        guardrail_config={
            "guardrailIdentifier": "gr-converse",
            "guardrailVersion": "2",
            "streamProcessingMode": "async",
            "trace": "enabled",
        },
    )

    try:
        with Stubber(runtime_client) as stubber:
            stubber.add_response("converse", raw_response, expected)
            with patch(
                "agent.bedrock_adapter._get_bedrock_runtime_client",
                return_value=runtime_client,
            ):
                response = wrapper.chat.completions.create(
                    messages=[{"role": "user", "content": "hi"}],
                    timeout=4,
                )
    finally:
        runtime_client.close()

    assert response.choices[0].message.content == "locally validated"


def test_auxiliary_cache_key_uses_normalized_model():
    from agent.auxiliary_client import _client_cache_key

    with patch(
        "agent.auxiliary_client._normalize_resolved_model",
        side_effect=lambda model, _provider: str(model or "").lower(),
    ):
        upper = _client_cache_key(
            "copilot",
            model="GPT-5.5",
            async_mode=False,
        )
        lower = _client_cache_key(
            "copilot",
            model="gpt-5.5",
            async_mode=False,
        )

    assert upper == lower
    assert upper[1] == "gpt-5.5"


def test_auto_bedrock_cache_identity_tracks_config_region():
    from agent.auxiliary_client import _client_cache_key

    with (
        patch("agent.auxiliary_client._read_main_provider", return_value="bedrock"),
        patch(
            "agent.auxiliary_client._read_main_model",
            return_value="amazon.nova-lite-v1:0",
        ),
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "eu-west-1"}},
        ),
    ):
        west = _client_cache_key("auto", async_mode=False)
    with (
        patch("agent.auxiliary_client._read_main_provider", return_value="bedrock"),
        patch(
            "agent.auxiliary_client._read_main_model",
            return_value="amazon.nova-lite-v1:0",
        ),
        patch(
            "elevate_cli.config.load_config",
            return_value={"bedrock": {"region": "eu-central-1"}},
        ),
    ):
        central = _client_cache_key("auto", async_mode=False)

    assert west != central


def test_bedrock_claude_and_nova_wrappers_never_cross_sync_cache():
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        BedrockConverseAuxiliaryClient,
        _get_cached_client,
    )

    with (
        patch("agent.auxiliary_client._client_cache", {}),
        patch("agent.auxiliary_client._beta_auxiliary_policy_active", return_value=False),
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.bedrock_adapter.resolve_bedrock_region", return_value="us-east-1"),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=MagicMock(),
        ),
    ):
        claude, _ = _get_cached_client(
            "bedrock", "anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        nova, _ = _get_cached_client("bedrock", "amazon.nova-lite-v1:0")
        claude_again, _ = _get_cached_client(
            "bedrock", "anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    assert isinstance(claude, AnthropicAuxiliaryClient)
    assert isinstance(nova, BedrockConverseAuxiliaryClient)
    assert claude is claude_again
    assert claude is not nova


@pytest.mark.asyncio
async def test_bedrock_claude_and_nova_wrappers_never_cross_async_cache():
    from agent.auxiliary_client import (
        AsyncAnthropicAuxiliaryClient,
        AsyncBedrockConverseAuxiliaryClient,
        _get_cached_client,
    )

    with (
        patch("agent.auxiliary_client._client_cache", {}),
        patch("agent.auxiliary_client._beta_auxiliary_policy_active", return_value=False),
        patch("elevate_cli.config.load_config", return_value={"bedrock": {}}),
        patch("agent.bedrock_adapter.has_aws_credentials", return_value=True),
        patch("agent.bedrock_adapter.resolve_bedrock_region", return_value="us-east-1"),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=MagicMock(),
        ),
    ):
        claude, _ = _get_cached_client(
            "bedrock",
            "anthropic.claude-haiku-4-5-20251001-v1:0",
            async_mode=True,
        )
        nova, _ = _get_cached_client(
            "bedrock",
            "amazon.nova-lite-v1:0",
            async_mode=True,
        )

    assert isinstance(claude, AsyncAnthropicAuxiliaryClient)
    assert isinstance(nova, AsyncBedrockConverseAuxiliaryClient)
    assert claude is not nova


@pytest.mark.asyncio
async def test_async_anthropic_loop_replacement_closes_owned_transport():
    import asyncio

    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        _get_cached_client,
    )

    model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    old_leaf = MagicMock(name="old-anthropic-leaf")
    old_wrapper = AsyncAnthropicAuxiliaryClient(
        AnthropicAuxiliaryClient(
            old_leaf,
            model,
            api_key="aws-sdk",
            base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
            is_bedrock=True,
        )
    )
    new_leaf = MagicMock(name="new-anthropic-leaf")
    new_wrapper = AsyncAnthropicAuxiliaryClient(
        AnthropicAuxiliaryClient(
            new_leaf,
            model,
            api_key="aws-sdk",
            base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
            is_bedrock=True,
        )
    )
    cache_key = ("async-bedrock",)
    stale_loop = MagicMock(name="stale-loop")
    stale_loop.is_closed.return_value = False
    cache = {cache_key: (old_wrapper, model, stale_loop)}

    with (
        patch("agent.auxiliary_client._client_cache", cache),
        patch(
            "agent.auxiliary_client._client_cache_key",
            return_value=cache_key,
        ),
        patch(
            "agent.auxiliary_client._beta_auxiliary_policy_active",
            return_value=False,
        ),
        patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(new_wrapper, model),
        ),
    ):
        resolved, resolved_model = _get_cached_client(
            "bedrock",
            model,
            async_mode=True,
        )

    assert asyncio.get_running_loop() is not stale_loop
    assert resolved is new_wrapper
    assert resolved_model == model
    old_leaf.close.assert_called_once_with()
    new_leaf.close.assert_not_called()
    assert cache[cache_key][0] is new_wrapper


def test_async_anthropic_shutdown_closes_owned_transport_once() -> None:
    from agent.auxiliary_client import (
        AnthropicAuxiliaryClient,
        AsyncAnthropicAuxiliaryClient,
        shutdown_cached_clients,
    )

    model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    leaf = MagicMock(name="anthropic-leaf")
    wrapper = AsyncAnthropicAuxiliaryClient(
        AnthropicAuxiliaryClient(
            leaf,
            model,
            api_key="aws-sdk",
            base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
            is_bedrock=True,
        )
    )
    cache = {("async-bedrock",): (wrapper, model, MagicMock())}

    with patch("agent.auxiliary_client._client_cache", cache):
        shutdown_cached_clients()
        wrapper.close()

    leaf.close.assert_called_once_with()
    assert cache == {}


@pytest.mark.parametrize("async_mode", [False, True])
def test_copilot_chat_and_responses_wrappers_never_cross_cache(async_mode):
    from agent.auxiliary_client import (
        AsyncCodexAuxiliaryClient,
        CodexAuxiliaryClient,
        _get_cached_client,
    )

    def _resolve(_provider, model, requested_async=False, **_kwargs):
        if model == "gpt-5.5":
            real = MagicMock()
            real.api_key = "token"
            real.base_url = "https://api.githubcopilot.com"
            sync = CodexAuxiliaryClient(real, model)
            if requested_async:
                return AsyncCodexAuxiliaryClient(sync), model
            return sync, model
        return SimpleNamespace(kind="chat", model=model), model

    with (
        patch("agent.auxiliary_client._client_cache", {}),
        patch("agent.auxiliary_client._beta_auxiliary_policy_active", return_value=False),
        patch("agent.auxiliary_client.resolve_provider_client", side_effect=_resolve),
    ):
        chat, _ = _get_cached_client(
            "copilot", "gpt-4o", async_mode=async_mode
        )
        responses, _ = _get_cached_client(
            "copilot", "gpt-5.5", async_mode=async_mode
        )
        chat_again, _ = _get_cached_client(
            "copilot", "gpt-4o", async_mode=async_mode
        )

    assert getattr(chat, "kind", None) == "chat"
    assert chat is chat_again
    if async_mode:
        assert isinstance(responses, AsyncCodexAuxiliaryClient)
    else:
        assert isinstance(responses, CodexAuxiliaryClient)
    assert chat is not responses


@pytest.mark.parametrize(
    "model_id",
    [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6-v1:0",
        "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-sonnet-4-6-v1:0",
    ],
)
def test_claude_classifier_accepts_recognizable_arns(model_id):
    from agent.bedrock_adapter import is_anthropic_bedrock_model

    assert is_anthropic_bedrock_model(model_id) is True


def test_claude_classifier_routes_opaque_application_profile_to_converse():
    from agent.bedrock_adapter import is_anthropic_bedrock_model

    assert is_anthropic_bedrock_model(
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/abc123"
    ) is False


@pytest.mark.parametrize(
    "model_id",
    [
        "apac.anthropic.claude-sonnet-4-6-v1:0",
        (
            "arn:aws:bedrock:ap-southeast-2:123456789012:inference-profile/"
            "apac.anthropic.claude-sonnet-4-6-v1:0"
        ),
    ],
)
def test_claude_classifier_accepts_apac_system_profiles(model_id):
    from agent.bedrock_adapter import is_anthropic_bedrock_model

    assert is_anthropic_bedrock_model(model_id) is True


def test_bedrock_tool_choice_translation_and_parallel_fail_closed():
    from agent.bedrock_adapter import build_converse_kwargs

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_deal",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    messages = [{"role": "user", "content": "hi"}]

    required = build_converse_kwargs(
        "amazon.nova-lite-v1:0",
        messages,
        tools,
        tool_choice="required",
    )
    selected = build_converse_kwargs(
        "amazon.nova-lite-v1:0",
        messages,
        tools,
        tool_choice={"type": "function", "function": {"name": "get_deal"}},
    )
    none = build_converse_kwargs(
        "amazon.nova-lite-v1:0",
        messages,
        tools,
        tool_choice="none",
        parallel_tool_calls=False,
    )

    assert required["toolConfig"]["toolChoice"] == {"any": {}}
    assert selected["toolConfig"]["toolChoice"] == {
        "tool": {"name": "get_deal"}
    }
    assert "toolConfig" not in none
    with pytest.raises(ValueError, match="cannot guarantee"):
        build_converse_kwargs(
            "amazon.nova-lite-v1:0",
            messages,
            tools,
            parallel_tool_calls=False,
        )
