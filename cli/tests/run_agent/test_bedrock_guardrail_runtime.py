"""Main-runtime Bedrock guardrail enforcement regressions."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from elevate_cli import runtime_provider as _runtime_provider  # noqa: F401
from run_agent import AIAgent


def _guardrail_config(*, partial: bool = False) -> dict:
    guardrail = {
        "guardrail_identifier": "gr-main",
        "stream_processing_mode": "async",
        "trace": "enabled",
    }
    if not partial:
        guardrail["guardrail_version"] = "4"
    return {"bedrock": {"guardrail": guardrail}}


def _build_bedrock_agent(
    *,
    api_mode: str,
    model: str,
    config: dict,
    client=None,
    provider: str = "bedrock",
):
    patches = [
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("elevate_cli.config.load_config", return_value=config),
    ]
    if client is not None:
        patches.append(
            patch(
                "agent.anthropic_adapter.build_anthropic_bedrock_client",
                return_value=client,
            )
        )
    entered = []
    try:
        for context in patches:
            entered.append(context)
            context.start()
        return AIAgent(
            provider=provider,
            api_mode=api_mode,
            base_url="https://bedrock-runtime.eu-west-1.amazonaws.com",
            api_key="aws-sdk",
            model=model,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    finally:
        for context in reversed(entered):
            context.stop()


def _converse_kwargs(agent: AIAgent) -> dict:
    kwargs = {
        "__bedrock_region__": "eu-west-1",
        "__bedrock_converse__": True,
        "modelId": agent.model,
        "messages": [{"role": "user", "content": [{"text": "hello"}]}],
        "inferenceConfig": {"maxTokens": 32},
    }
    if agent._bedrock_guardrail_config:
        kwargs["guardrailConfig"] = dict(agent._bedrock_guardrail_config)
    return kwargs


def test_main_converse_strips_stream_only_guardrail_field() -> None:
    agent = _build_bedrock_agent(
        api_mode="bedrock_converse",
        model="amazon.nova-lite-v1:0",
        config=_guardrail_config(),
    )
    runtime_client = MagicMock()
    runtime_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "ok"}],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
    }

    with patch(
        "agent.bedrock_adapter._get_bedrock_runtime_client",
        return_value=runtime_client,
    ):
        agent._interruptible_api_call(_converse_kwargs(agent))

    guardrail = runtime_client.converse.call_args.kwargs["guardrailConfig"]
    assert guardrail == {
        "guardrailIdentifier": "gr-main",
        "guardrailVersion": "4",
        "trace": "enabled",
    }


def test_main_converse_stream_retains_stream_processing_mode() -> None:
    agent = _build_bedrock_agent(
        api_mode="bedrock_converse",
        model="amazon.nova-lite-v1:0",
        config=_guardrail_config(),
    )
    runtime_client = MagicMock()
    runtime_client.converse_stream.return_value = {
        "stream": [
            {"contentBlockDelta": {"delta": {"text": "ok"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
    }

    with patch(
        "agent.bedrock_adapter._get_bedrock_runtime_client",
        return_value=runtime_client,
    ):
        agent._interruptible_streaming_api_call(_converse_kwargs(agent))

    guardrail = runtime_client.converse_stream.call_args.kwargs[
        "guardrailConfig"
    ]
    assert guardrail["streamProcessingMode"] == "async"
    assert guardrail["guardrailIdentifier"] == "gr-main"
    assert guardrail["guardrailVersion"] == "4"


def test_main_bedrock_claude_sync_and_stream_apply_guardrail_headers() -> None:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[])
    stream = MagicMock()
    stream.__enter__ = MagicMock(return_value=stream)
    stream.__exit__ = MagicMock(return_value=False)
    stream.__iter__ = MagicMock(return_value=iter([]))
    stream.get_final_message.return_value = SimpleNamespace(
        content=[],
        stop_reason="end_turn",
    )
    client.messages.stream.return_value = stream
    agent = _build_bedrock_agent(
        api_mode="anthropic_messages",
        model="anthropic.claude-sonnet-4-6-v1:0",
        config=_guardrail_config(),
        client=client,
    )
    agent._try_refresh_anthropic_client_credentials = lambda: None

    agent._anthropic_messages_create(
        {
            "model": agent.model,
            "messages": [],
            "max_tokens": 8,
            "extra_headers": {"keep": "yes"},
        }
    )
    agent._interruptible_streaming_api_call(
        {
            "model": agent.model,
            "messages": [],
            "max_tokens": 8,
        }
    )

    for request in (
        client.messages.create.call_args.kwargs,
        client.messages.stream.call_args.kwargs,
    ):
        headers = request["extra_headers"]
        assert headers["X-Amzn-Bedrock-GuardrailIdentifier"] == "gr-main"
        assert headers["X-Amzn-Bedrock-GuardrailVersion"] == "4"
        assert headers["X-Amzn-Bedrock-Trace"] == "ENABLED"
    assert client.messages.create.call_args.kwargs["extra_headers"]["keep"] == "yes"


def test_main_bedrock_partial_guardrail_fails_closed() -> None:
    with pytest.raises(ValueError, match="both an identifier and version"):
        _build_bedrock_agent(
            api_mode="bedrock_converse",
            model="amazon.nova-lite-v1:0",
            config=_guardrail_config(partial=True),
        )


@pytest.mark.parametrize(
    "guardrail",
    [
        {
            "guardrail_identifier": "gr-a",
            "guardrailIdentifier": "gr-b",
            "guardrail_version": "1",
        },
        {
            "guardrail_identifier": "gr-a",
            "guardrail_version": "1",
            "guardrailVersion": "2",
        },
        {
            "guardrail_identifier": "gr-a",
            "guardrail_version": "1",
            "unknown_policy": True,
        },
        {
            "guardrail_identifier": "gr-a",
            "guardrail_version": "1",
            "trace": "verbose",
        },
        {
            "guardrail_identifier": "gr-a",
            "guardrail_version": "1",
            "stream_processing_mode": "eventual",
        },
    ],
)
def test_main_bedrock_malformed_guardrail_policy_fails_closed(
    guardrail,
) -> None:
    with pytest.raises(ValueError):
        _build_bedrock_agent(
            api_mode="bedrock_converse",
            model="amazon.nova-lite-v1:0",
            config={"bedrock": {"guardrail": guardrail}},
        )


def test_main_bedrock_matching_aliases_share_one_guardrail_policy() -> None:
    agent = _build_bedrock_agent(
        api_mode="bedrock_converse",
        model="amazon.nova-lite-v1:0",
        config={
            "bedrock": {
                "guardrail": {
                    "guardrail_identifier": "gr-same",
                    "guardrailIdentifier": "gr-same",
                    "guardrail_version": "8",
                    "guardrailVersion": "8",
                    "stream_processing_mode": "sync",
                    "streamProcessingMode": "sync",
                    "trace": "enabled_full",
                }
            }
        },
    )

    assert agent._bedrock_guardrail_config == {
        "guardrailIdentifier": "gr-same",
        "guardrailVersion": "8",
        "streamProcessingMode": "sync",
        "trace": "enabled_full",
    }


@pytest.mark.parametrize("malformed_guardrail", [[], "", 0, False])
def test_main_bedrock_falsey_non_mapping_guardrail_fails_closed(
    malformed_guardrail,
) -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        _build_bedrock_agent(
            api_mode="bedrock_converse",
            model="amazon.nova-lite-v1:0",
            config={"bedrock": {"guardrail": malformed_guardrail}},
        )


@pytest.mark.parametrize("malformed_bedrock", [[], "", 0, False])
def test_main_bedrock_falsey_non_mapping_provider_config_fails_closed(
    malformed_bedrock,
) -> None:
    with pytest.raises(ValueError, match="Bedrock configuration must be a mapping"):
        _build_bedrock_agent(
            api_mode="bedrock_converse",
            model="amazon.nova-lite-v1:0",
            config={"bedrock": malformed_bedrock},
        )


def test_non_bedrock_main_runtime_does_not_emit_bedrock_disable_sentinel() -> None:
    agent = object.__new__(AIAgent)
    agent.model = "gpt-5.5"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.api_key = "oauth-token"
    agent.api_mode = "codex_responses"
    agent._bedrock_region = "stale-region"
    agent._bedrock_guardrail_config = None

    runtime = agent._current_main_runtime()

    assert "region" not in runtime
    assert "guardrail_config" not in runtime


def test_providerless_bedrock_endpoint_still_loads_guardrails() -> None:
    agent = _build_bedrock_agent(
        api_mode="bedrock_converse",
        model="amazon.nova-lite-v1:0",
        config=_guardrail_config(),
        provider="",
    )

    assert agent.provider == "bedrock"
    assert agent._bedrock_region == "eu-west-1"
    assert agent._bedrock_guardrail_config == {
        "guardrailIdentifier": "gr-main",
        "guardrailVersion": "4",
        "streamProcessingMode": "async",
        "trace": "enabled",
    }


@pytest.mark.parametrize("use_extracted_helper", [False, True])
def test_main_bedrock_midstream_stale_error_evicts_exact_client_and_withholds_output(
    use_extracted_helper: bool,
) -> None:
    from botocore.exceptions import ReadTimeoutError

    from agent import chat_completion_helpers

    agent = _build_bedrock_agent(
        api_mode="bedrock_converse",
        model="amazon.nova-lite-v1:0",
        config={},
    )
    runtime_client = MagicMock()

    def _broken_events():
        yield {"contentBlockDelta": {"delta": {"text": "partial"}}}
        raise ReadTimeoutError(
            endpoint_url="https://bedrock-runtime.eu-west-1.amazonaws.com"
        )

    runtime_client.converse_stream.return_value = {
        "stream": _broken_events(),
    }
    agent.stream_delta_callback = MagicMock()
    agent._last_activity_ts = 1

    call = (
        chat_completion_helpers.interruptible_streaming_api_call
        if use_extracted_helper
        else agent._interruptible_streaming_api_call
    )
    args = (agent, _converse_kwargs(agent)) if use_extracted_helper else (
        _converse_kwargs(agent),
    )
    with (
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
        pytest.raises(ReadTimeoutError),
    ):
        call(*args)

    invalidate.assert_called_once_with(
        "eu-west-1",
        timeout=None,
        endpoint_url=None,
        expected_client=runtime_client,
    )
    agent.stream_delta_callback.assert_not_called()
    assert agent._last_activity_ts > 1
    assert agent._last_activity_desc == "receiving Bedrock stream"
