"""Tests for the native Google AI Studio Gemini adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class DummyResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


def test_build_native_request_preserves_thought_signature_on_tool_replay():
    from agent.gemini_native_adapter import build_gemini_request

    request = build_gemini_request(
        messages=[
            {"role": "system", "content": "Be helpful."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Paris"}',
                        },
                        "extra_content": {"google": {"thought_signature": "sig-123"}},
                    }
                ],
            },
        ],
        tools=[],
        tool_choice=None,
    )

    parts = request["contents"][0]["parts"]
    assert parts[0]["functionCall"]["name"] == "get_weather"
    assert parts[0]["thoughtSignature"] == "sig-123"


def test_build_native_request_uses_original_function_name_for_tool_result():
    from agent.gemini_native_adapter import build_gemini_request

    request = build_gemini_request(
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Paris"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"forecast": "sunny"}',
            },
        ],
        tools=[],
        tool_choice=None,
    )

    tool_response = request["contents"][1]["parts"][0]["functionResponse"]
    assert tool_response["name"] == "get_weather"


def test_build_native_request_strips_json_schema_only_fields_from_tool_parameters():
    from agent.gemini_native_adapter import build_gemini_request

    request = build_gemini_request(
        messages=[{"role": "user", "content": "Hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_weather",
                    "description": "Weather lookup",
                    "parameters": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "city": {
                                "type": "string",
                                "$schema": "ignored",
                                "description": "City name",
                            }
                        },
                        "required": ["city"],
                    },
                },
            }
        ],
        tool_choice=None,
    )

    params = request["tools"][0]["functionDeclarations"][0]["parameters"]
    assert "$schema" not in params
    assert "additionalProperties" not in params
    assert params["type"] == "object"
    assert params["properties"]["city"] == {
        "type": "string",
        "description": "City name",
    }


def test_translate_native_response_surfaces_reasoning_and_tool_calls():
    from agent.gemini_native_adapter import translate_gemini_response

    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "text": "thinking..."},
                        {"functionCall": {"name": "search", "args": {"q": "elevate"}}},
                    ]
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }

    response = translate_gemini_response(payload, model="gemini-2.5-flash")
    choice = response.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.reasoning == "thinking..."
    assert choice.message.tool_calls[0].function.name == "search"
    assert json.loads(choice.message.tool_calls[0].function.arguments) == {
        "q": "elevate"
    }


@pytest.mark.parametrize(
    "function_call",
    [
        pytest.param({"name": "bad", "args": None}, id="args-none"),
        pytest.param({"name": "bad", "args": False}, id="args-bool"),
        pytest.param({"name": "bad", "args": 7}, id="args-number"),
        pytest.param({"name": "bad", "args": "{}"}, id="args-string"),
        pytest.param({"name": "bad", "args": []}, id="args-list"),
        pytest.param(
            {"name": "bad", "args": {"nested": {"not-json"}}},
            id="args-unserializable",
        ),
        pytest.param({"args": {}}, id="name-missing"),
        pytest.param({"name": "", "args": {}}, id="name-empty"),
        pytest.param({"name": "   ", "args": {}}, id="name-whitespace"),
        pytest.param({"name": None, "args": {}}, id="name-none"),
        pytest.param({"name": 7, "args": {}}, id="name-number"),
        pytest.param(None, id="call-none"),
        pytest.param([], id="call-list"),
        pytest.param("search", id="call-string"),
    ],
)
def test_native_malformed_function_call_poisons_mixed_batch(function_call):
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "must not escape"},
                            {"text": "must not display"},
                            {
                                "functionCall": {
                                    "name": "valid_sibling",
                                    "args": {"listing_id": "123"},
                                }
                            },
                            {"functionCall": function_call},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
        },
        model="gemini-2.5-flash",
    )

    choice = response.choices[0]
    assert choice.finish_reason == "error"
    assert choice.message.content is None
    assert choice.message.reasoning is None
    assert choice.message.reasoning_content is None
    assert choice.message.tool_calls is None
    assert response._elevate_gemini_diagnostic["finish_reason"] == "INVALID"


@pytest.mark.parametrize(
    "function_call",
    [
        pytest.param({"name": "no_args"}, id="args-absent"),
        pytest.param({"name": "no_args", "args": {}}, id="args-empty-object"),
    ],
)
def test_native_absent_or_empty_object_args_remain_valid(function_call):
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "candidates": [
                {
                    "content": {"parts": [{"functionCall": function_call}]},
                    "finishReason": "STOP",
                }
            ],
        },
        model="gemini-2.5-flash",
    )

    choice = response.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.tool_calls[0].function.name == "no_args"
    assert choice.message.tool_calls[0].function.arguments == "{}"


def test_native_diagnostic_is_content_free_and_allowlisted():
    from agent.gemini_native_adapter import translate_gemini_response

    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "text": "SECRET_REASONING_TEXT"},
                        {"text": "SECRET_RESPONSE_TEXT"},
                        {
                            "functionCall": {
                                "name": "SECRET_FUNCTION_NAME",
                                "args": {"token": "SECRET_FUNCTION_ARGUMENT"},
                            },
                            "thoughtSignature": "SECRET_THOUGHT_SIGNATURE",
                        },
                    ]
                },
                "finishReason": "STOP",
                "finishMessage": "SECRET_FINISH_MESSAGE",
            }
        ],
        "promptFeedback": {
            "blockReason": "SAFETY",
            "blockReasonMessage": "SECRET_BLOCK_MESSAGE",
        },
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 7,
            "thoughtsTokenCount": 3,
            "totalTokenCount": 21,
        },
    }

    response = translate_gemini_response(payload, model="gemini-2.5-flash")
    diagnostic = response._elevate_gemini_diagnostic

    assert diagnostic == {
        "finish_reason": "STOP",
        "prompt_block_reason": "SAFETY",
        "candidate_count": 1,
        "part_counts": {
            "text": 1,
            "thought_text": 1,
            "function_call": 1,
            "thought_signature": 1,
            "other": 0,
        },
        "usable_part_count": 3,
        "prompt_tokens": 11,
        "candidate_tokens": 7,
        "thought_tokens": 3,
        "cached_tokens": 0,
        "total_tokens": 21,
    }
    serialized = json.dumps(diagnostic, sort_keys=True)
    for secret in (
        "SECRET_RESPONSE_TEXT",
        "SECRET_REASONING_TEXT",
        "SECRET_FUNCTION_NAME",
        "SECRET_FUNCTION_ARGUMENT",
        "SECRET_THOUGHT_SIGNATURE",
        "SECRET_FINISH_MESSAGE",
        "SECRET_BLOCK_MESSAGE",
    ):
        assert secret not in serialized

    message = response.choices[0].message
    assert message.content is None
    assert message.reasoning is None
    assert message.reasoning_content is None
    assert message.tool_calls is None


def test_native_no_candidate_diagnostic_keeps_prompt_block_reason():
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "promptFeedback": {
                "blockReason": "PROHIBITED_CONTENT",
                "blockReasonMessage": "SECRET_BLOCK_DETAILS",
            },
            "usageMetadata": {"promptTokenCount": 9, "totalTokenCount": 9},
        },
        model="gemini-2.5-flash",
    )

    diagnostic = response._elevate_gemini_diagnostic
    assert diagnostic["finish_reason"] == "UNSPECIFIED"
    assert diagnostic["prompt_block_reason"] == "PROHIBITED_CONTENT"
    assert diagnostic["candidate_count"] == 0
    assert diagnostic["usable_part_count"] == 0
    assert diagnostic["prompt_tokens"] == 9
    assert response.usage.prompt_tokens == 9
    assert response.usage.total_tokens == 9
    assert "SECRET_BLOCK_DETAILS" not in json.dumps(diagnostic)


@pytest.mark.parametrize(
    "finish_reason",
    [
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    ],
)
def test_native_candidate_content_filter_reasons_are_terminal(finish_reason):
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "FILTERED_REASONING"},
                            {"text": "FILTERED_PARTIAL_TEXT"},
                            {
                                "functionCall": {
                                    "name": "deals_overview",
                                    "args": {"status": "active"},
                                }
                            },
                        ]
                    },
                    "finishReason": finish_reason,
                }
            ]
        },
        model="gemini-2.5-flash",
    )

    assert response.choices[0].finish_reason == "content_filter"
    assert response.choices[0].message.content is None
    assert response.choices[0].message.reasoning is None
    assert response.choices[0].message.reasoning_content is None
    assert response.choices[0].message.tool_calls is None
    assert response._elevate_gemini_diagnostic["finish_reason"] == finish_reason


def test_native_client_uses_x_goog_api_key_and_native_models_endpoint(monkeypatch):
    from agent.gemini_native_adapter import GeminiNativeClient

    recorded = {}

    class DummyHTTP:
        def post(self, url, json=None, headers=None, timeout=None):
            recorded["url"] = url
            recorded["json"] = json
            recorded["headers"] = headers
            return DummyResponse(
                payload={
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "hello"}]},
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 2,
                    },
                }
            )

        def close(self):
            return None

    monkeypatch.setattr(
        "agent.gemini_native_adapter.httpx.Client", lambda *a, **k: DummyHTTP()
    )

    client = GeminiNativeClient(
        api_key="AIza-test", base_url="https://generativelanguage.googleapis.com/v1beta"
    )
    response = client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "Hello"}],
    )

    assert (
        recorded["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert recorded["headers"]["x-goog-api-key"] == "AIza-test"
    assert "Authorization" not in recorded["headers"]
    assert response.choices[0].message.content == "hello"


def test_native_http_error_keeps_status_and_retry_after():
    from agent.gemini_native_adapter import gemini_http_error

    response = DummyResponse(
        status_code=429,
        headers={"Retry-After": "17"},
        payload={
            "error": {
                "code": 429,
                "message": "quota exhausted",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "RESOURCE_EXHAUSTED",
                        "metadata": {"service": "generativelanguage.googleapis.com"},
                    }
                ],
            }
        },
    )

    err = gemini_http_error(response)
    assert getattr(err, "status_code", None) == 429
    assert getattr(err, "retry_after", None) == 17.0
    assert "quota exhausted" in str(err)


def test_native_client_accepts_injected_http_client():
    from agent.gemini_native_adapter import GeminiNativeClient

    injected = SimpleNamespace(close=lambda: None)
    client = GeminiNativeClient(api_key="AIza-test", http_client=injected)
    assert client._http is injected


def test_native_client_rejects_empty_api_key_with_actionable_message():
    """Empty/whitespace api_key must raise at construction, not produce a cryptic
    Google GFE 'Error 400 (Bad Request)!!1' HTML page on the first request."""
    from agent.gemini_native_adapter import GeminiNativeClient

    for bad in ("", "   ", None):
        with pytest.raises(RuntimeError) as excinfo:
            GeminiNativeClient(api_key=bad)  # type: ignore[arg-type]
        msg = str(excinfo.value)
        assert "GOOGLE_API_KEY" in msg and "GEMINI_API_KEY" in msg
        assert "aistudio.google.com" in msg


@pytest.mark.asyncio
async def test_async_native_client_streams_without_requiring_async_iterator_from_sync_client():
    from agent.gemini_native_adapter import AsyncGeminiNativeClient

    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason=None)
        ]
    )
    sync_stream = iter([chunk])

    def _advance(iterator):
        try:
            return False, next(iterator)
        except StopIteration:
            return True, None

    sync_client = SimpleNamespace(
        api_key="AIza-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: sync_stream)
        ),
        _advance_stream_iterator=_advance,
        close=lambda: None,
    )

    async_client = AsyncGeminiNativeClient(sync_client)
    stream = await async_client.chat.completions.create(stream=True)
    collected = []
    async for item in stream:
        collected.append(item)
    assert collected == [chunk]


def test_stream_event_translation_emits_tool_call_delta_with_stable_index():
    from agent.gemini_native_adapter import translate_stream_event

    tool_call_indices = {}
    event = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "search", "args": {"q": "abc"}}}
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    first = translate_stream_event(
        event, model="gemini-2.5-flash", tool_call_indices=tool_call_indices
    )
    second = translate_stream_event(
        event, model="gemini-2.5-flash", tool_call_indices=tool_call_indices
    )

    assert first[0].choices[0].delta.tool_calls[0].index == 0
    assert second[0].choices[0].delta.tool_calls[0].index == 0
    assert (
        first[0].choices[0].delta.tool_calls[0].id
        == second[0].choices[0].delta.tool_calls[0].id
    )
    assert first[0].choices[0].delta.tool_calls[0].function.arguments == '{"q": "abc"}'
    assert second[0].choices[0].delta.tool_calls[0].function.arguments == ""
    assert first[-1].choices[0].finish_reason == "tool_calls"


@pytest.mark.parametrize(
    "function_call",
    [
        pytest.param({"name": "bad", "args": None}, id="args-none"),
        pytest.param({"name": "bad", "args": []}, id="args-list"),
        pytest.param({"name": "bad", "args": "{}"}, id="args-string"),
        pytest.param({"args": {}}, id="name-missing"),
        pytest.param({"name": " ", "args": {}}, id="name-whitespace"),
        pytest.param(None, id="call-none"),
    ],
)
def test_native_stream_malformed_call_atomically_suppresses_mixed_batch(
    function_call,
):
    from agent.gemini_native_adapter import translate_stream_event

    state = {}
    chunks = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "must not display"},
                            {
                                "functionCall": {
                                    "name": "valid_sibling",
                                    "args": {"listing_id": "123"},
                                }
                            },
                            {"functionCall": function_call},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
        },
        model="gemini-2.5-flash",
        tool_call_indices=state,
    )

    assert len(chunks) == 1
    terminal = chunks[0]
    assert terminal.choices[0].finish_reason == "error"
    assert terminal.choices[0].delta.content is None
    assert terminal.choices[0].delta.reasoning is None
    assert terminal.choices[0].delta.tool_calls is None
    assert terminal._elevate_gemini_diagnostic["finish_reason"] == "INVALID"
    assert (
        translate_stream_event(
            {"candidates": [{"finishReason": "STOP"}]},
            model="gemini-2.5-flash",
            tool_call_indices=state,
        )
        == []
    )


@pytest.mark.parametrize(
    "function_call",
    [
        pytest.param({"name": "no_args"}, id="args-absent"),
        pytest.param({"name": "no_args", "args": {}}, id="args-empty-object"),
    ],
)
def test_native_stream_absent_or_empty_object_args_remain_valid(function_call):
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {"parts": [{"functionCall": function_call}]},
                    "finishReason": "STOP",
                }
            ],
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    tool_delta = chunks[0].choices[0].delta.tool_calls[0]
    assert tool_delta.function.name == "no_args"
    assert tool_delta.function.arguments == "{}"
    assert chunks[-1].choices[0].finish_reason == "tool_calls"


def test_native_stream_later_malformed_event_poison_is_persistent():
    from agent.gemini_native_adapter import translate_stream_event

    state = {}
    first = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {"name": "valid_first", "args": {}},
                            }
                        ]
                    }
                }
            ]
        },
        model="gemini-2.5-flash",
        tool_call_indices=state,
    )
    poisoned = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {"name": "bad_later", "args": None},
                            }
                        ]
                    }
                }
            ]
        },
        model="gemini-2.5-flash",
        tool_call_indices=state,
    )
    final = translate_stream_event(
        {"candidates": [{"finishReason": "STOP"}]},
        model="gemini-2.5-flash",
        tool_call_indices=state,
    )

    assert first[0].choices[0].delta.tool_calls is not None
    assert len(poisoned) == 1
    assert poisoned[0].choices[0].finish_reason == "error"
    assert final == []


def test_stream_empty_stop_carries_content_free_diagnostic():
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"thoughtSignature": "SECRET_THOUGHT_SIGNATURE"}]
                    },
                    "finishReason": "STOP",
                    "finishMessage": "SECRET_FINISH_MESSAGE",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 31,
                "candidatesTokenCount": 0,
                "thoughtsTokenCount": 0,
                "totalTokenCount": 31,
            },
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    finish_chunk = chunks[-1]
    diagnostic = finish_chunk._elevate_gemini_diagnostic
    assert finish_chunk.choices[0].finish_reason == "stop"
    assert diagnostic["finish_reason"] == "STOP"
    assert diagnostic["usable_part_count"] == 0
    assert diagnostic["part_counts"]["thought_signature"] == 1
    serialized = json.dumps(diagnostic)
    assert "SECRET_THOUGHT_SIGNATURE" not in serialized
    assert "SECRET_FINISH_MESSAGE" not in serialized


def test_stream_content_filter_discards_tool_call_parts():
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "FILTERED_REASONING"},
                            {"text": "FILTERED_PARTIAL_TEXT"},
                            {
                                "functionCall": {
                                    "name": "deals_overview",
                                    "args": {"status": "active"},
                                }
                            },
                        ]
                    },
                    "finishReason": "SAFETY",
                }
            ]
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert len(chunks) == 1
    assert chunks[0].choices[0].finish_reason == "content_filter"
    assert chunks[0].choices[0].delta.content is None
    assert chunks[0].choices[0].delta.reasoning_content is None
    assert chunks[0].choices[0].delta.tool_calls is None


def test_native_abnormal_finish_discards_all_candidate_content():
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "REJECTED_REASONING"},
                            {"text": "REJECTED_PARTIAL_TEXT"},
                            {
                                "functionCall": {
                                    "name": "deals_overview",
                                    "args": {"status": "active"},
                                }
                            },
                        ]
                    },
                    "finishReason": "OTHER",
                }
            ]
        },
        model="gemini-2.5-flash",
    )

    choice = response.choices[0]
    assert choice.finish_reason == "error"
    assert choice.message.content is None
    assert choice.message.reasoning is None
    assert choice.message.reasoning_content is None
    assert choice.message.tool_calls is None


def test_stream_no_candidate_preserves_prompt_block_diagnostic():
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "promptFeedback": {
                "blockReason": "PROHIBITED_CONTENT",
                "blockReasonMessage": "SECRET_BLOCK_DETAILS",
            },
            "usageMetadata": {
                "promptTokenCount": 13,
                "candidatesTokenCount": 0,
                "thoughtsTokenCount": 0,
                "totalTokenCount": 13,
            },
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert len(chunks) == 1
    diagnostic_chunk = chunks[0]
    assert diagnostic_chunk.choices == []
    assert diagnostic_chunk.usage.prompt_tokens == 13
    diagnostic = diagnostic_chunk._elevate_gemini_diagnostic
    assert diagnostic["finish_reason"] == "UNSPECIFIED"
    assert diagnostic["prompt_block_reason"] == "PROHIBITED_CONTENT"
    assert diagnostic["candidate_count"] == 0
    assert diagnostic["usable_part_count"] == 0
    assert "SECRET_BLOCK_DETAILS" not in json.dumps(diagnostic)


def test_stream_usage_only_event_does_not_emit_empty_diagnostic():
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "usageMetadata": {
                "promptTokenCount": 31,
                "candidatesTokenCount": 0,
                "thoughtsTokenCount": 0,
                "totalTokenCount": 31,
            }
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert len(chunks) == 1
    assert chunks[0].choices == []
    assert chunks[0].usage.prompt_tokens == 31
    assert not hasattr(chunks[0], "_elevate_gemini_diagnostic")


def test_stream_explicit_unspecified_prompt_feedback_is_not_a_block():
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        {
            "promptFeedback": {
                "blockReason": "BLOCK_REASON_UNSPECIFIED",
            },
            "usageMetadata": {"promptTokenCount": 7},
        },
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert len(chunks) == 1
    assert chunks[0].usage.prompt_tokens == 7
    assert not hasattr(chunks[0], "_elevate_gemini_diagnostic")


def test_stream_event_translation_keeps_identical_calls_in_distinct_parts():
    from agent.gemini_native_adapter import translate_stream_event

    event = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "search", "args": {"q": "abc"}}},
                        {"functionCall": {"name": "search", "args": {"q": "abc"}}},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    chunks = translate_stream_event(
        event, model="gemini-2.5-flash", tool_call_indices={}
    )
    tool_chunks = [chunk for chunk in chunks if chunk.choices[0].delta.tool_calls]
    assert tool_chunks[0].choices[0].delta.tool_calls[0].index == 0
    assert tool_chunks[1].choices[0].delta.tool_calls[0].index == 1
    assert (
        tool_chunks[0].choices[0].delta.tool_calls[0].id
        != tool_chunks[1].choices[0].delta.tool_calls[0].id
    )


def test_empty_native_response_preserves_cached_token_usage():
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "usageMetadata": {
                "promptTokenCount": 31,
                "cachedContentTokenCount": 19,
                "totalTokenCount": 31,
            }
        },
        model="gemini-2.5-flash",
    )

    assert response._elevate_gemini_diagnostic["cached_tokens"] == 19
    assert response.usage.prompt_tokens_details.cached_tokens == 19


def test_whitespace_only_native_text_is_not_counted_as_usable():
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "   \n\t"}]},
                    "finishReason": "STOP",
                }
            ]
        },
        model="gemini-2.5-flash",
    )

    assert response._elevate_gemini_diagnostic["usable_part_count"] == 0


def test_malformed_sse_debug_log_never_contains_payload(caplog):
    from agent.gemini_native_adapter import _iter_sse_events

    secret = "PRIVATE_DEAL_TEXT_AND_API_KEY"

    class StreamResponse:
        @staticmethod
        def iter_text():
            return iter([f'data: {{"secret":"{secret}"\n'])

    with caplog.at_level("DEBUG", logger="agent.gemini_native_adapter"):
        assert list(_iter_sse_events(StreamResponse())) == []

    assert "Non-JSON Gemini SSE line" in caplog.text
    assert "JSONDecodeError" in caplog.text
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("payload", "diagnostic_field"),
    [
        (
            {
                "promptFeedback": {"blockReason": "future-safety-v2"},
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "MALFORMED_BLOCK_TEXT"},
                                {
                                    "functionCall": {
                                        "name": "write_file",
                                        "args": {"path": "unsafe"},
                                    }
                                },
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
            },
            "prompt_block_reason",
        ),
        (
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "MALFORMED_FINISH_TEXT"},
                                {
                                    "functionCall": {
                                        "name": "write_file",
                                        "args": {"path": "unsafe"},
                                    }
                                },
                            ]
                        },
                        "finishReason": "future-safety-v2",
                    }
                ]
            },
            "finish_reason",
        ),
    ],
)
def test_malformed_nonempty_gemini_enums_fail_closed(payload, diagnostic_field):
    from agent.gemini_native_adapter import translate_gemini_response

    response = translate_gemini_response(payload, model="gemini-2.5-flash")

    assert response._elevate_gemini_diagnostic[diagnostic_field] == "INVALID"
    assert response.choices[0].message.content is None
    assert response.choices[0].message.reasoning is None
    assert response.choices[0].message.tool_calls is None


@pytest.mark.parametrize(
    "event",
    [
        {
            "promptFeedback": {"blockReason": "future-safety-v2"},
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "STREAM_BLOCK_TEXT"},
                            {
                                "functionCall": {
                                    "name": "write_file",
                                    "args": {"path": "unsafe"},
                                }
                            },
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
        },
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "STREAM_FINISH_TEXT"},
                            {
                                "functionCall": {
                                    "name": "write_file",
                                    "args": {"path": "unsafe"},
                                }
                            },
                        ]
                    },
                    "finishReason": "future-safety-v2",
                }
            ]
        },
    ],
)
def test_stream_malformed_nonempty_gemini_enums_emit_no_candidate_output(event):
    from agent.gemini_native_adapter import translate_stream_event

    chunks = translate_stream_event(
        event,
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert chunks
    assert all(
        not chunk.choices
        or (
            chunk.choices[0].delta.content is None
            and chunk.choices[0].delta.reasoning_content is None
            and chunk.choices[0].delta.tool_calls is None
        )
        for chunk in chunks
    )
    diagnostic = chunks[-1]._elevate_gemini_diagnostic
    assert "INVALID" in {
        diagnostic["prompt_block_reason"],
        diagnostic["finish_reason"],
    }


@pytest.mark.parametrize("prompt_feedback", [None, [], "SAFETY", 7, False])
def test_present_malformed_prompt_feedback_container_fails_closed(
    prompt_feedback,
):
    from agent.gemini_native_adapter import (
        translate_gemini_response,
        translate_stream_event,
    )

    payload = {
        "promptFeedback": prompt_feedback,
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "MALFORMED_CONTAINER_TEXT"},
                        {
                            "functionCall": {
                                "name": "write_file",
                                "args": {"path": "unsafe"},
                            }
                        },
                    ]
                },
                "finishReason": "STOP",
            }
        ],
    }

    response = translate_gemini_response(payload, model="gemini-2.5-flash")
    chunks = translate_stream_event(
        payload,
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert response._elevate_gemini_diagnostic["prompt_block_reason"] == "INVALID"
    assert response.choices[0].message.content is None
    assert response.choices[0].message.tool_calls is None
    assert chunks[-1]._elevate_gemini_diagnostic["prompt_block_reason"] == "INVALID"
    assert all(
        not chunk.choices
        or (
            chunk.choices[0].delta.content is None
            and chunk.choices[0].delta.tool_calls is None
        )
        for chunk in chunks
    )


@pytest.mark.parametrize(
    "invalid_value",
    [None, False, "", 7, [], "future-safety-v2_UNSPECIFIED"],
)
@pytest.mark.parametrize("field", ["blockReason", "finishReason"])
def test_present_malformed_enum_shape_fails_closed(field, invalid_value):
    from agent.gemini_native_adapter import (
        translate_gemini_response,
        translate_stream_event,
    )

    candidate = {
        "content": {
            "parts": [
                {"text": "MALFORMED_ENUM_TEXT"},
                {
                    "functionCall": {
                        "name": "write_file",
                        "args": {"path": "unsafe"},
                    }
                },
            ]
        },
        "finishReason": "STOP",
    }
    payload = {"candidates": [candidate]}
    diagnostic_field = "finish_reason"
    if field == "blockReason":
        payload["promptFeedback"] = {"blockReason": invalid_value}
        diagnostic_field = "prompt_block_reason"
    else:
        candidate["finishReason"] = invalid_value

    response = translate_gemini_response(payload, model="gemini-2.5-flash")
    chunks = translate_stream_event(
        payload,
        model="gemini-2.5-flash",
        tool_call_indices={},
    )

    assert response._elevate_gemini_diagnostic[diagnostic_field] == "INVALID"
    assert response.choices[0].message.content is None
    assert response.choices[0].message.tool_calls is None
    assert chunks
    assert chunks[-1]._elevate_gemini_diagnostic[diagnostic_field] == "INVALID"
    assert all(
        not chunk.choices
        or (
            chunk.choices[0].delta.content is None
            and chunk.choices[0].delta.tool_calls is None
        )
        for chunk in chunks
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("finishReason", "FINISH_REASON_UNSPECIFIED"),
        ("blockReason", "BLOCK_REASON_UNSPECIFIED"),
        ("finishReason", "UNSPECIFIED"),
        ("blockReason", "UNSPECIFIED"),
    ],
)
def test_exact_unspecified_enums_remain_no_signal(field, value):
    from agent.gemini_native_adapter import translate_gemini_response

    candidate = {
        "content": {"parts": [{"text": "accepted"}]},
        "finishReason": "STOP",
    }
    payload = {"candidates": [candidate]}
    diagnostic_field = "finish_reason"
    if field == "blockReason":
        payload["promptFeedback"] = {"blockReason": value}
        diagnostic_field = "prompt_block_reason"
    else:
        candidate["finishReason"] = value

    response = translate_gemini_response(payload, model="gemini-2.5-flash")

    assert response._elevate_gemini_diagnostic[diagnostic_field] == "UNSPECIFIED"
