"""Bedrock primary lifecycle must preserve transport identity and policy."""

import copy
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from elevate_cli import runtime_provider as _runtime_provider  # noqa: F401
from run_agent import (
    AIAgent,
    SteerCutInterrupt,
    _ProviderAttempt,
    _bedrock_region_from_base_url,
)


CLAUDE_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
NOVA_MODEL = "amazon.nova-lite-v1:0"
FIPS_ENDPOINT = "https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com"


class _DocumentedContextEngine:
    """Plugin double implementing exactly the public ContextEngine signature."""

    def __init__(self) -> None:
        self.model = NOVA_MODEL
        self.base_url = "https://bedrock-runtime.eu-west-1.amazonaws.com"
        self.api_key = "aws-sdk"
        self.provider = "bedrock"
        self.context_length = 32_000
        self.threshold_tokens = 27_200
        self.calls = []

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
    ) -> None:
        self.calls.append(
            {
                "model": model,
                "context_length": context_length,
                "base_url": base_url,
                "api_key": api_key,
                "provider": provider,
            }
        )
        self.model = model
        self.context_length = context_length
        self.base_url = base_url
        self.api_key = api_key
        self.provider = provider
        self.threshold_tokens = int(context_length * 0.85)


def _config(*, region: str = "eu-west-1", guardrail: bool = True) -> dict:
    bedrock = {"region": region}
    if guardrail:
        bedrock["guardrail"] = {
            "guardrail_identifier": "gr-lifecycle",
            "guardrail_version": "7",
            "stream_processing_mode": "async",
            "trace": "enabled",
        }
    return {"bedrock": bedrock}


def _build_agent(
    model: str,
    *,
    api_mode: str | None,
    provider: str = "bedrock",
    base_url: str = "https://bedrock-runtime.eu-west-1.amazonaws.com",
    config: dict | None = None,
    anthropic_client=None,
) -> AIAgent:
    contexts = [
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch(
            "elevate_cli.config.load_config",
            return_value=config if config is not None else _config(),
        ),
    ]
    if "anthropic" in model:
        contexts.append(
            patch(
                "agent.anthropic_adapter.build_anthropic_bedrock_client",
                return_value=anthropic_client or MagicMock(),
            )
        )
    entered = []
    try:
        for context in contexts:
            entered.append(context)
            context.start()
        return AIAgent(
            provider=provider,
            api_mode=api_mode,
            base_url=base_url,
            api_key="aws-sdk",
            model=model,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    finally:
        for context in reversed(entered):
            context.stop()


def _plant_fallback(agent: AIAgent) -> MagicMock:
    fallback_client = MagicMock(name="fallback_client")
    agent.model = "gpt-fallback"
    agent.provider = "custom"
    agent.base_url = "https://fallback.example/v1"
    agent.api_mode = "chat_completions"
    agent.api_key = "fallback-key"
    agent.client = fallback_client
    agent._client_kwargs = {
        "api_key": "fallback-key",
        "base_url": "https://fallback.example/v1",
    }
    agent._anthropic_client = None
    agent._anthropic_api_key = ""
    agent._anthropic_base_url = ""
    agent._is_anthropic_oauth = False
    agent._bedrock_region = "ap-south-1"
    agent._bedrock_guardrail_config = None
    agent._fallback_activated = True
    agent._rate_limited_until = 0
    return fallback_client


@pytest.mark.parametrize(
    ("model", "api_mode", "expected_kind"),
    [
        (CLAUDE_MODEL, "anthropic_messages", "anthropic_bedrock"),
        (NOVA_MODEL, "bedrock_converse", "converse"),
    ],
)
def test_bedrock_snapshot_records_kind_region_and_guardrail_copy(
    model: str,
    api_mode: str,
    expected_kind: str,
) -> None:
    agent = _build_agent(model, api_mode=api_mode)
    snapshot = agent._primary_runtime

    assert snapshot["bedrock_client_kind"] == expected_kind
    assert snapshot["bedrock_region"] == "eu-west-1"
    assert snapshot["bedrock_guardrail_config"] == {
        "guardrailIdentifier": "gr-lifecycle",
        "guardrailVersion": "7",
        "streamProcessingMode": "async",
        "trace": "enabled",
    }
    assert snapshot["bedrock_guardrail_config"] is not agent._bedrock_guardrail_config
    agent._bedrock_guardrail_config["guardrailIdentifier"] = "mutated"
    assert snapshot["bedrock_guardrail_config"]["guardrailIdentifier"] == "gr-lifecycle"


def test_restore_bedrock_claude_uses_anthropic_bedrock_not_generic() -> None:
    initial_client = MagicMock(name="initial_bedrock")
    agent = _build_agent(
        CLAUDE_MODEL,
        api_mode="anthropic_messages",
        anthropic_client=initial_client,
    )
    fallback_client = _plant_fallback(agent)
    restored_client = MagicMock(name="restored_bedrock")

    with (
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=restored_client,
        ) as build_bedrock,
        patch("agent.anthropic_adapter.build_anthropic_client") as build_generic,
    ):
        assert agent._restore_primary_runtime() is True

    build_bedrock.assert_called_once_with("eu-west-1")
    build_generic.assert_not_called()
    assert agent._anthropic_client is restored_client
    assert agent.client is None
    assert agent.api_mode == "anthropic_messages"
    assert agent._fallback_activated is False
    fallback_client.close.assert_called_once()


def test_restore_bedrock_converse_never_builds_openai_client() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse")
    _plant_fallback(agent)

    with patch.object(
        agent,
        "_create_openai_client",
        side_effect=AssertionError("OpenAI client must not be built"),
    ) as build_openai:
        assert agent._restore_primary_runtime() is True

    build_openai.assert_not_called()
    assert agent.provider == "bedrock"
    assert agent.api_mode == "bedrock_converse"
    assert agent.client is None
    assert agent._anthropic_client is None


def test_failed_restore_keeps_complete_fallback_runtime() -> None:
    agent = _build_agent(CLAUDE_MODEL, api_mode="anthropic_messages")
    fallback_client = _plant_fallback(agent)
    before = {
        key: getattr(agent, key)
        for key in (
            "model",
            "provider",
            "base_url",
            "api_mode",
            "api_key",
            "client",
            "_anthropic_client",
            "_bedrock_region",
            "_bedrock_guardrail_config",
            "_fallback_activated",
            "_fallback_index",
        )
    }

    with patch(
        "agent.anthropic_adapter.build_anthropic_bedrock_client",
        side_effect=RuntimeError("AWS unavailable"),
    ):
        assert agent._restore_primary_runtime() is False

    for key, value in before.items():
        assert getattr(agent, key) is value if key in {
            "client",
            "_anthropic_client",
            "_bedrock_guardrail_config",
        } else getattr(agent, key) == value
    fallback_client.close.assert_not_called()


@pytest.mark.parametrize(
    ("fallback_model", "expected_kind", "expected_api_mode"),
    [
        (CLAUDE_MODEL, "anthropic_bedrock", "anthropic_messages"),
        (NOVA_MODEL, "converse", "bedrock_converse"),
    ],
)
def test_fallback_to_bedrock_installs_model_aware_region_and_guardrail(
    fallback_model: str,
    expected_kind: str,
    expected_api_mode: str,
) -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse", config={})
    agent._fallback_chain = [
        {"provider": "bedrock", "model": fallback_model}
    ]
    agent._fallback_index = 0
    staged_client = MagicMock(name="fallback_bedrock")
    receipt = {
        "provider": "bedrock",
        "api_mode": expected_api_mode,
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "api_key": "aws-sdk",
        "region": "eu-west-1",
    }

    with (
        patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            return_value=receipt,
        ),
        patch("elevate_cli.config.load_config", return_value=_config()),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=staged_client,
        ) as build_bedrock,
    ):
        assert agent._try_activate_fallback() is True

    assert agent.api_mode == expected_api_mode
    assert agent._bedrock_region == "eu-west-1"
    assert agent._bedrock_guardrail_config["guardrailIdentifier"] == "gr-lifecycle"
    assert agent._fallback_activated is True
    assert agent._primary_runtime["model"] == NOVA_MODEL
    if expected_kind == "anthropic_bedrock":
        build_bedrock.assert_called_once_with("eu-west-1")
        assert agent._anthropic_client is staged_client
    else:
        build_bedrock.assert_not_called()
        assert agent._anthropic_client is None


def test_switch_model_bedrock_updates_exact_client_and_primary_snapshot() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse", config={})
    claude_client = MagicMock(name="switched_claude")

    with (
        patch("elevate_cli.config.load_config", return_value=_config()),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=claude_client,
        ),
    ):
        agent.switch_model(
            CLAUDE_MODEL,
            "bedrock",
            base_url="https://bedrock-runtime.eu-west-1.amazonaws.com",
        )

    assert agent.api_mode == "anthropic_messages"
    assert agent._anthropic_client is claude_client
    assert agent._primary_runtime["bedrock_client_kind"] == "anthropic_bedrock"
    assert agent._primary_runtime["bedrock_region"] == "eu-west-1"

    with patch("elevate_cli.config.load_config", return_value=_config()):
        agent.switch_model(
            NOVA_MODEL,
            "bedrock",
            base_url="https://bedrock-runtime.eu-west-1.amazonaws.com",
        )

    assert agent.api_mode == "bedrock_converse"
    assert agent.client is None
    assert agent._anthropic_client is None
    assert agent._primary_runtime["bedrock_client_kind"] == "converse"
    claude_client.close.assert_called_once()


def test_switch_named_custom_bedrock_keeps_timeout_policy_and_fips() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse", config={})
    config = {
        "bedrock": {"region": "us-east-1"},
        "providers": {
            "gov-bedrock": {
                "base_url": FIPS_ENDPOINT,
                "request_timeout_seconds": 0.25,
                "stale_timeout_seconds": 0.5,
            }
        },
    }
    claude_client = MagicMock(name="named_switch")

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("elevate_cli.runtime_provider.load_config", return_value=config),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=claude_client,
        ) as build_bedrock,
    ):
        agent.switch_model(CLAUDE_MODEL, "custom:gov-bedrock")

    build_bedrock.assert_called_once_with(
        "us-gov-west-1",
        base_url=FIPS_ENDPOINT,
        timeout=0.25,
    )
    assert agent.provider == "bedrock"
    assert agent.base_url == FIPS_ENDPOINT
    assert agent._bedrock_timeout_provider == "gov-bedrock"
    assert agent._primary_runtime["bedrock_request_timeout"] == 0.25
    assert agent._primary_runtime["bedrock_stale_timeout"] == 0.5


def test_bedrock_lifecycle_supports_documented_context_engine_signature() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse", config={})
    context_engine = _DocumentedContextEngine()
    agent.context_compressor = context_engine
    agent._primary_runtime = agent._build_primary_runtime_snapshot()
    agent._fallback_chain = [{"provider": "bedrock", "model": CLAUDE_MODEL}]
    agent._fallback_index = 0
    receipt = {
        "provider": "bedrock",
        "api_mode": "anthropic_messages",
        "base_url": "https://bedrock-runtime.eu-west-1.amazonaws.com",
        "api_key": "aws-sdk",
        "region": "eu-west-1",
    }
    fallback_client = MagicMock(name="plugin_fallback_bedrock")

    with (
        patch(
            "elevate_cli.runtime_provider.resolve_runtime_provider",
            return_value=receipt,
        ),
        patch("elevate_cli.config.load_config", return_value=_config()),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=fallback_client,
        ),
    ):
        assert agent._try_activate_fallback() is True

    assert context_engine.calls[-1]["model"] == CLAUDE_MODEL
    assert agent._restore_primary_runtime() is True
    assert context_engine.calls[-1]["model"] == NOVA_MODEL

    switched_client = MagicMock(name="plugin_switched_bedrock")
    with (
        patch("elevate_cli.config.load_config", return_value=_config()),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=switched_client,
        ),
    ):
        agent.switch_model(CLAUDE_MODEL, "bedrock")

    assert context_engine.calls[-1]["model"] == CLAUDE_MODEL
    assert agent._primary_runtime["bedrock_client_kind"] == "anthropic_bedrock"


def test_primary_transport_recovery_uses_bedrock_specific_builder() -> None:
    old_client = MagicMock(name="old_bedrock")
    agent = _build_agent(
        CLAUDE_MODEL,
        api_mode="anthropic_messages",
        anthropic_client=old_client,
    )
    rebuilt_client = MagicMock(name="rebuilt_bedrock")

    class ReadTimeout(Exception):
        pass

    with (
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=rebuilt_client,
        ) as build_bedrock,
        patch("agent.anthropic_adapter.build_anthropic_client") as build_generic,
        patch("run_agent.time.sleep"),
    ):
        assert agent._try_recover_primary_transport(
            ReadTimeout("stale"),
            retry_count=0,
            max_retries=0,
        ) is True

    build_bedrock.assert_called_once_with("eu-west-1")
    build_generic.assert_not_called()
    assert agent._anthropic_client is rebuilt_client
    old_client.close.assert_called_once()


def test_restored_guardrail_reaches_converse_sync_and_stream() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse")
    _plant_fallback(agent)
    assert agent._restore_primary_runtime() is True
    runtime_client = MagicMock()
    runtime_client.converse.return_value = {
        "output": {
            "message": {"role": "assistant", "content": [{"text": "ok"}]}
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }
    runtime_client.converse_stream.return_value = {
        "stream": [
            {"contentBlockDelta": {"delta": {"text": "ok"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
    }

    def _kwargs() -> dict:
        return {
            "__bedrock_region__": "eu-west-1",
            "__bedrock_converse__": True,
            "modelId": NOVA_MODEL,
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "inferenceConfig": {"maxTokens": 8},
            "guardrailConfig": copy.deepcopy(agent._bedrock_guardrail_config),
        }

    with patch(
        "agent.bedrock_adapter._get_bedrock_runtime_client",
        return_value=runtime_client,
    ):
        agent._interruptible_api_call(_kwargs())
        agent._interruptible_streaming_api_call(_kwargs())

    sync_guardrail = runtime_client.converse.call_args.kwargs["guardrailConfig"]
    stream_guardrail = runtime_client.converse_stream.call_args.kwargs[
        "guardrailConfig"
    ]
    assert "streamProcessingMode" not in sync_guardrail
    assert stream_guardrail["streamProcessingMode"] == "async"
    assert sync_guardrail["guardrailIdentifier"] == "gr-lifecycle"
    assert stream_guardrail["guardrailIdentifier"] == "gr-lifecycle"


def test_direct_bedrock_constructor_autoclassifies_claude() -> None:
    client = MagicMock()
    agent = _build_agent(
        CLAUDE_MODEL,
        api_mode=None,
        base_url="",
        anthropic_client=client,
    )

    assert agent.api_mode == "anthropic_messages"
    assert agent._anthropic_client is client
    assert agent._primary_runtime["bedrock_client_kind"] == "anthropic_bedrock"
    assert agent.base_url == "https://bedrock-runtime.eu-west-1.amazonaws.com"


def test_custom_label_on_trusted_bedrock_url_canonicalizes_full_runtime() -> None:
    client = MagicMock()
    agent = _build_agent(
        CLAUDE_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        anthropic_client=client,
    )

    assert agent.provider == "bedrock"
    assert agent.api_mode == "anthropic_messages"
    assert agent._bedrock_region == "eu-west-1"
    assert agent._bedrock_guardrail_config["guardrailIdentifier"] == "gr-lifecycle"
    assert agent._anthropic_client is client


def test_bedrock_region_parser_accepts_fips_endpoint_and_rejects_lookalike() -> None:
    assert _bedrock_region_from_base_url(
        "https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com"
    ) == "us-gov-west-1"
    assert _bedrock_region_from_base_url(
        "https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com.evil.test"
    ) == ""


def test_fips_startup_reaches_actual_claude_client_and_snapshot() -> None:
    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "gov-bedrock": {
            "base_url": FIPS_ENDPOINT,
            "request_timeout_seconds": 0.25,
            "stale_timeout_seconds": 0.5,
        }
    }
    client = MagicMock(name="fips_startup")

    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=client,
        ) as build_bedrock,
    ):
        agent = AIAgent(
            provider="custom",
            api_mode="bedrock_converse",
            base_url=FIPS_ENDPOINT,
            api_key="ignored-custom-key",
            model=CLAUDE_MODEL,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    build_bedrock.assert_called_once_with(
        "us-gov-west-1",
        base_url=FIPS_ENDPOINT,
        timeout=0.25,
    )
    assert agent.provider == "bedrock"
    assert agent.api_mode == "anthropic_messages"
    assert agent._bedrock_endpoint_url == FIPS_ENDPOINT
    assert agent._primary_runtime["bedrock_endpoint_url"] == FIPS_ENDPOINT
    assert agent._primary_runtime["bedrock_timeout_provider"] == "gov-bedrock"
    assert agent._primary_runtime["bedrock_request_timeout"] == 0.25
    assert agent._primary_runtime["bedrock_stale_timeout"] == 0.5


def test_fips_converse_sync_and_stream_dispatch_actual_policy() -> None:
    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "gov-bedrock": {
            "base_url": FIPS_ENDPOINT,
            "request_timeout_seconds": 0.25,
            "stale_timeout_seconds": 0.5,
        }
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    runtime_client = MagicMock()
    runtime_client.converse.return_value = {
        "output": {
            "message": {"role": "assistant", "content": [{"text": "ok"}]}
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }
    runtime_client.converse_stream.return_value = {
        "stream": [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"text": "ok"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
    }

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_client,
    ):
        sync_kwargs = agent._build_api_kwargs(
            [{"role": "user", "content": "sync"}]
        )
        stream_kwargs = agent._build_api_kwargs(
            [{"role": "user", "content": "stream"}]
        )
        agent._interruptible_api_call(sync_kwargs)
        agent._interruptible_streaming_api_call(stream_kwargs)

    expected_call = {
        "timeout": 0.25,
        "endpoint_url": FIPS_ENDPOINT,
        "exclusive": True,
    }
    assert get_client.call_count == 2
    for client_call in get_client.call_args_list:
        assert client_call.args == ("us-gov-west-1",)
        assert client_call.kwargs == expected_call
    assert "__bedrock_endpoint_url__" not in runtime_client.converse.call_args.kwargs
    assert "__bedrock_timeout__" not in runtime_client.converse.call_args.kwargs
    assert (
        "__bedrock_endpoint_url__"
        not in runtime_client.converse_stream.call_args.kwargs
    )
    assert "__bedrock_timeout__" not in runtime_client.converse_stream.call_args.kwargs
    assert agent._effective_provider_stale_timeout() == 0.5


def test_extracted_fips_converse_dispatch_matches_active_runtime() -> None:
    from agent import chat_completion_helpers

    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "gov-bedrock": {
            "base_url": FIPS_ENDPOINT,
            "request_timeout_seconds": 0.25,
            "stale_timeout_seconds": 0.5,
        }
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    runtime_client = MagicMock()
    runtime_client.converse.return_value = {
        "output": {
            "message": {"role": "assistant", "content": [{"text": "ok"}]}
        },
        "stopReason": "end_turn",
    }
    runtime_client.converse_stream.return_value = {
        "stream": [{"messageStop": {"stopReason": "end_turn"}}]
    }

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ) as get_client,
    ):
        chat_completion_helpers.interruptible_api_call(
            agent,
            agent._build_api_kwargs([{"role": "user", "content": "sync"}]),
        )
        chat_completion_helpers.interruptible_streaming_api_call(
            agent,
            agent._build_api_kwargs([{"role": "user", "content": "stream"}]),
        )

    assert get_client.call_count == 2
    for dispatched in get_client.call_args_list:
        assert dispatched.args == ("us-gov-west-1",)
        assert dispatched.kwargs == {
            "timeout": 0.25,
            "endpoint_url": FIPS_ENDPOINT,
            "exclusive": True,
        }
    assert "__bedrock_endpoint_url__" not in runtime_client.converse.call_args.kwargs
    assert "__bedrock_timeout__" not in runtime_client.converse.call_args.kwargs
    assert (
        "__bedrock_endpoint_url__"
        not in runtime_client.converse_stream.call_args.kwargs
    )
    assert "__bedrock_timeout__" not in runtime_client.converse_stream.call_args.kwargs


def test_silent_bedrock_stream_timeout_closes_event_stream_and_worker() -> None:
    class BlockingEventStream:
        def __init__(self) -> None:
            self.closed = threading.Event()
            self.worker_finished = threading.Event()
            self.close_calls = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.closed.wait(timeout=2.0)
            self.worker_finished.set()
            raise StopIteration

        def close(self) -> None:
            self.close_calls += 1
            self.closed.set()

    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "bedrock": {"request_timeout_seconds": 0.05}
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    event_stream = BlockingEventStream()
    runtime_client = MagicMock()
    runtime_client.converse_stream.return_value = {"stream": event_stream}

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
        pytest.raises(TimeoutError, match="no provider events"),
    ):
        agent._interruptible_streaming_api_call(
            agent._build_api_kwargs([{"role": "user", "content": "hang"}])
        )

    assert event_stream.worker_finished.wait(timeout=1.0)
    assert event_stream.close_calls == 1
    runtime_client.close.assert_called_once()
    invalidate.assert_called_once_with(
        "us-gov-west-1",
        timeout=0.05,
        endpoint_url=FIPS_ENDPOINT,
        expected_client=runtime_client,
    )


def test_late_bedrock_stream_is_closed_after_caller_cancels() -> None:
    class LateEventStream:
        def __init__(self) -> None:
            self.closed = threading.Event()
            self.close_calls = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.closed.wait(timeout=3.0)
            raise StopIteration

        def close(self) -> None:
            self.close_calls += 1
            self.closed.set()

    class LateRuntimeClient:
        def __init__(self, event_stream: LateEventStream) -> None:
            self.event_stream = event_stream
            self.call_entered = threading.Event()
            self.allow_response = threading.Event()
            self.closed = threading.Event()
            self.close_calls = 0

        def converse_stream(self, **_kwargs):
            self.call_entered.set()
            self.allow_response.wait(timeout=3.0)
            return {"stream": self.event_stream}

        def close(self) -> None:
            self.close_calls += 1
            self.closed.set()

    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=_config(region="us-gov-west-1"),
    )
    event_stream = LateEventStream()
    runtime_client = LateRuntimeClient(event_stream)
    spawned_workers = []
    real_spawn = agent._spawn_model_worker

    def _capture_worker(*args, **kwargs):
        worker = real_spawn(*args, **kwargs)
        spawned_workers.append(worker)
        return worker

    agent._spawn_model_worker = _capture_worker
    agent._consume_steer_cut_request = lambda: runtime_client.call_entered.is_set()

    with (
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
    ):
        try:
            with pytest.raises(SteerCutInterrupt):
                agent._interruptible_streaming_api_call(
                    agent._build_api_kwargs(
                        [{"role": "user", "content": "cancel late stream"}]
                    )
                )
            assert runtime_client.closed.is_set()
        finally:
            runtime_client.allow_response.set()

        closed_by_agent = event_stream.closed.wait(timeout=1.0)
        if not closed_by_agent:
            event_stream.close()
        assert len(spawned_workers) == 1
        spawned_workers[0].join(timeout=1.0)

    assert closed_by_agent, "a stream returned after cancellation must be closed"
    assert event_stream.close_calls == 1
    assert not spawned_workers[0].is_alive()
    assert runtime_client.close_calls == 1
    invalidate.assert_called_once_with(
        "us-gov-west-1",
        timeout=None,
        endpoint_url=FIPS_ENDPOINT,
        expected_client=runtime_client,
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_cancel_at_bedrock_dispatch_fence_never_calls_sdk(
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
) -> None:
    class RecordingRuntimeClient:
        def __init__(self) -> None:
            self.closed = threading.Event()
            self.converse_called = threading.Event()
            self.converse_stream_called = threading.Event()
            self.close_calls = 0

        def converse(self, **_kwargs):
            self.converse_called.set()
            return {
                "output": {"message": {"role": "assistant", "content": []}},
                "stopReason": "end_turn",
            }

        def converse_stream(self, **_kwargs):
            self.converse_stream_called.set()
            return {"stream": []}

        def close(self) -> None:
            self.close_calls += 1
            self.closed.set()

    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "bedrock": {
            "request_timeout_seconds": 5,
            "stale_timeout_seconds": 5,
        }
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    runtime_client = RecordingRuntimeClient()
    fence_entered = threading.Event()
    release_fence = threading.Event()
    spawned_workers = []
    real_dispatch = _ProviderAttempt.dispatch_if_active
    real_spawn = agent._spawn_model_worker

    def _blocked_dispatch(attempt: _ProviderAttempt, callback, *args, **kwargs):
        fence_entered.set()
        release_fence.wait(timeout=3.0)
        return real_dispatch(attempt, callback, *args, **kwargs)

    def _capture_worker(*args, **kwargs):
        worker = real_spawn(*args, **kwargs)
        spawned_workers.append(worker)
        return worker

    monkeypatch.setattr(
        _ProviderAttempt,
        "dispatch_if_active",
        _blocked_dispatch,
    )
    agent._spawn_model_worker = _capture_worker
    agent._consume_steer_cut_request = lambda: fence_entered.is_set()
    call = (
        agent._interruptible_streaming_api_call
        if streaming
        else agent._interruptible_api_call
    )

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
    ):
        try:
            with pytest.raises(SteerCutInterrupt):
                call(
                    agent._build_api_kwargs(
                        [{"role": "user", "content": "cancel at fence"}]
                    )
                )
            assert fence_entered.is_set()
            assert runtime_client.closed.is_set()
        finally:
            release_fence.set()

        assert len(spawned_workers) == 1
        spawned_workers[0].join(timeout=1.0)

    assert not spawned_workers[0].is_alive()
    assert runtime_client.close_calls == 1
    assert not runtime_client.converse_called.is_set()
    assert not runtime_client.converse_stream_called.is_set()
    invalidate.assert_called_once_with(
        "us-gov-west-1",
        timeout=5.0,
        endpoint_url=FIPS_ENDPOINT,
        expected_client=runtime_client,
    )


def test_noncontent_bedrock_events_keep_stream_alive_without_consumers() -> None:
    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "bedrock": {"request_timeout_seconds": 0.1}
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    runtime_client = MagicMock()

    def _progress_events():
        for _ in range(9):
            time.sleep(0.04)
            yield {"messageStart": {"role": "assistant"}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    runtime_client.converse_stream.return_value = {
        "stream": _progress_events(),
    }
    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
    ):
        response = agent._interruptible_streaming_api_call(
            agent._build_api_kwargs(
                [{"role": "user", "content": "long noncontent stream"}]
            )
        )

    assert response.choices[0].finish_reason == "stop"
    runtime_client.close.assert_called_once()


def test_nonstream_bedrock_steer_cut_closes_client_and_quiesces_worker() -> None:
    class BlockingRuntimeClient:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.closed = threading.Event()
            self.worker_finished = threading.Event()
            self.close_calls = 0

        def converse(self, **_kwargs):
            self.started.set()
            self.closed.wait(timeout=2.0)
            self.worker_finished.set()
            return {
                "output": {"message": {"role": "assistant", "content": []}},
                "stopReason": "end_turn",
            }

        def close(self) -> None:
            self.close_calls += 1
            self.closed.set()

    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=_config(region="us-gov-west-1"),
    )
    runtime_client = BlockingRuntimeClient()
    agent._consume_steer_cut_request = (
        lambda: runtime_client.started.is_set()
    )

    with (
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            return_value=runtime_client,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
        pytest.raises(SteerCutInterrupt, match="Steer cut"),
    ):
        agent._interruptible_api_call(
            agent._build_api_kwargs(
                [{"role": "user", "content": "redirect this request"}]
            )
        )

    assert runtime_client.worker_finished.wait(timeout=1.0)
    assert runtime_client.close_calls == 1
    invalidate.assert_called_once_with(
        "us-gov-west-1",
        timeout=None,
        endpoint_url=FIPS_ENDPOINT,
        expected_client=runtime_client,
    )


@pytest.mark.parametrize("cancel_kind", ["timeout", "steer"])
@pytest.mark.parametrize("streaming", [False, True])
def test_cancel_while_bedrock_client_builder_is_blocked_never_dispatches(
    cancel_kind: str,
    streaming: bool,
) -> None:
    class LateRuntimeClient:
        def __init__(self) -> None:
            self.closed = threading.Event()
            self.converse_called = threading.Event()
            self.converse_stream_called = threading.Event()

        def converse(self, **_kwargs):
            self.converse_called.set()
            return {
                "output": {"message": {"role": "assistant", "content": []}},
                "stopReason": "end_turn",
            }

        def converse_stream(self, **_kwargs):
            self.converse_stream_called.set()
            return {"stream": []}

        def close(self) -> None:
            self.closed.set()

    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "bedrock": {
            "request_timeout_seconds": 0.05 if cancel_kind == "timeout" else 5,
            "stale_timeout_seconds": 0.05 if cancel_kind == "timeout" else 5,
        }
    }
    agent = _build_agent(
        NOVA_MODEL,
        api_mode="bedrock_converse",
        provider="custom",
        base_url=FIPS_ENDPOINT,
        config=config,
    )
    client = LateRuntimeClient()
    builder_started = threading.Event()
    release_builder = threading.Event()

    def _blocked_builder(*_args, **_kwargs):
        builder_started.set()
        release_builder.wait(timeout=3.0)
        return client

    agent._consume_steer_cut_request = lambda: (
        cancel_kind == "steer" and builder_started.is_set()
    )
    call_method = (
        agent._interruptible_streaming_api_call
        if streaming
        else agent._interruptible_api_call
    )
    expected_error = SteerCutInterrupt if cancel_kind == "steer" else TimeoutError

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch(
            "agent.bedrock_adapter._get_bedrock_runtime_client",
            side_effect=_blocked_builder,
        ),
        patch("agent.bedrock_adapter.invalidate_runtime_client") as invalidate,
    ):
        try:
            with pytest.raises(expected_error):
                call_method(
                    agent._build_api_kwargs(
                        [{"role": "user", "content": "cancel before dispatch"}]
                    )
                )
            assert builder_started.is_set()
            assert not client.converse_called.is_set()
            assert not client.converse_stream_called.is_set()
        finally:
            release_builder.set()

        assert client.closed.wait(timeout=1.0)
        assert not client.converse_called.is_set()
        assert not client.converse_stream_called.is_set()
        invalidate.assert_called_once_with(
            "us-gov-west-1",
            timeout=(0.05 if cancel_kind == "timeout" else 5.0),
            endpoint_url=FIPS_ENDPOINT,
            expected_client=client,
        )


def test_fips_restore_and_recovery_keep_actual_claude_endpoint() -> None:
    initial_client = MagicMock(name="initial_fips")
    config = _config(region="us-gov-west-1")
    config["providers"] = {
        "gov-bedrock": {
            "base_url": FIPS_ENDPOINT,
            "request_timeout_seconds": 0.25,
            "stale_timeout_seconds": 0.5,
        }
    }
    agent = _build_agent(
        CLAUDE_MODEL,
        api_mode="anthropic_messages",
        base_url=FIPS_ENDPOINT,
        config=config,
        anthropic_client=initial_client,
    )
    _plant_fallback(agent)
    restored_client = MagicMock(name="restored_fips")
    rebuilt_client = MagicMock(name="rebuilt_fips")

    with patch(
        "agent.anthropic_adapter.build_anthropic_bedrock_client",
        side_effect=[restored_client, rebuilt_client],
    ) as build_bedrock:
        assert agent._restore_primary_runtime() is True
        agent._rebuild_anthropic_client()

    assert build_bedrock.call_args_list == [
        call("us-gov-west-1", base_url=FIPS_ENDPOINT, timeout=0.25),
        call("us-gov-west-1", base_url=FIPS_ENDPOINT, timeout=0.25),
    ]
    assert agent._anthropic_client is rebuilt_client
    assert agent._bedrock_timeout_provider == "gov-bedrock"
    assert agent._bedrock_stale_timeout == 0.5


@pytest.mark.parametrize(
    ("model", "expected_mode", "expect_claude_builder"),
    [
        (CLAUDE_MODEL, "anthropic_messages", True),
        (NOVA_MODEL, "bedrock_converse", False),
    ],
)
def test_named_custom_fips_fallback_promotes_native_bedrock(
    model: str,
    expected_mode: str,
    expect_claude_builder: bool,
) -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse")
    agent._fallback_chain = [
        {"provider": "custom:gov-bedrock", "model": model}
    ]
    agent._fallback_index = 0
    config = {
        "model": {"provider": "bedrock", "default": NOVA_MODEL},
        "bedrock": {"region": "us-gov-west-1"},
        "providers": {
            "gov-bedrock": {
                "name": "Gov Bedrock",
                "base_url": FIPS_ENDPOINT,
                "default_model": model,
                "request_timeout_seconds": 0.25,
                "stale_timeout_seconds": 0.5,
            }
        },
    }
    staged_client = MagicMock(name="named_fips")

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("elevate_cli.runtime_provider.load_config", return_value=config),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=staged_client,
        ) as build_bedrock,
    ):
        assert agent._try_activate_fallback() is True

    assert agent.provider == "bedrock"
    assert agent.api_mode == expected_mode
    assert agent.base_url == FIPS_ENDPOINT
    assert agent._bedrock_endpoint_url == FIPS_ENDPOINT
    assert agent._bedrock_timeout_provider == "gov-bedrock"
    assert agent._bedrock_request_timeout == 0.25
    assert agent._bedrock_stale_timeout == 0.5
    if expect_claude_builder:
        build_bedrock.assert_called_once_with(
            "us-gov-west-1",
            base_url=FIPS_ENDPOINT,
            timeout=0.25,
        )
        assert agent._anthropic_client is staged_client
    else:
        build_bedrock.assert_not_called()
        assert agent._anthropic_client is None


@pytest.mark.parametrize(
    "provider_alias",
    ["aws", "aws-bedrock", "amazon-bedrock", "amazon"],
)
@pytest.mark.parametrize(
    ("model", "expected_mode"),
    [
        (CLAUDE_MODEL, "anthropic_messages"),
        (NOVA_MODEL, "bedrock_converse"),
    ],
)
def test_bedrock_alias_fallback_uses_native_runtime_from_environment(
    monkeypatch,
    provider_alias: str,
    model: str,
    expected_mode: str,
) -> None:
    monkeypatch.setenv("BEDROCK_BASE_URL", FIPS_ENDPOINT)
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse")
    agent._fallback_chain = [{"provider": provider_alias, "model": model}]
    agent._fallback_index = 0
    config = {
        "model": {"provider": "bedrock", "default": NOVA_MODEL},
        "bedrock": {"region": "us-east-1"},
        "providers": {
            "bedrock": {
                "request_timeout_seconds": 0.25,
                "stale_timeout_seconds": 0.5,
            }
        },
    }
    staged_client = MagicMock(name=f"{provider_alias}_fallback")

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("elevate_cli.runtime_provider.load_config", return_value=config),
        patch(
            "agent.anthropic_adapter.build_anthropic_bedrock_client",
            return_value=staged_client,
        ) as build_bedrock,
    ):
        assert agent._try_activate_fallback() is True

    assert agent.provider == "bedrock"
    assert agent.api_mode == expected_mode
    assert agent.base_url == FIPS_ENDPOINT
    assert agent._bedrock_request_timeout == 0.25
    assert agent._bedrock_stale_timeout == 0.5
    if model == CLAUDE_MODEL:
        build_bedrock.assert_called_once_with(
            "us-gov-west-1",
            base_url=FIPS_ENDPOINT,
            timeout=0.25,
        )
    else:
        build_bedrock.assert_not_called()


def test_named_custom_provider_shadows_bedrock_alias_in_active_fallback() -> None:
    agent = _build_agent(NOVA_MODEL, api_mode="bedrock_converse")
    agent._fallback_chain = [{"provider": "aws", "model": "custom-model"}]
    agent._fallback_index = 0
    config = {
        "providers": {
            "aws": {
                "base_url": "https://custom.example/v1",
                "api_key": "custom-key",
                "default_model": "custom-model",
            }
        }
    }
    custom_client = MagicMock(name="custom_aws")
    custom_client.base_url = "https://custom.example/v1"
    custom_client.api_key = "custom-key"

    with (
        patch("elevate_cli.config.load_config", return_value=config),
        patch("elevate_cli.runtime_provider.load_config", return_value=config),
        patch("agent.auxiliary_client.OpenAI", return_value=custom_client),
        patch.object(agent, "_activate_bedrock_fallback") as native_fallback,
        patch("agent.model_metadata.get_model_context_length", return_value=32_000),
    ):
        assert agent._try_activate_fallback() is True

    native_fallback.assert_not_called()
    assert agent.provider == "aws"
    assert agent.base_url == "https://custom.example/v1"
    assert agent.client is custom_client


def test_extracted_switch_promotes_custom_fips_to_native_bedrock() -> None:
    from agent.agent_runtime_helpers import switch_model

    agent = MagicMock()
    with patch(
        "run_agent._resolve_beta_agent_switch",
        return_value=None,
    ):
        switch_model(
            agent,
            CLAUDE_MODEL,
            "custom",
            base_url=FIPS_ENDPOINT,
        )

    agent._switch_model_to_bedrock.assert_called_once_with(
        CLAUDE_MODEL,
        base_url=FIPS_ENDPOINT,
        policy_provider="custom",
    )
