"""Regression tests for native vision payload handling in run_agent."""

from __future__ import annotations

import json

from run_agent import AIAgent


DATA_URL = "data:image/png;base64," + ("A" * 64)


def _native_tool_result() -> dict:
    return {
        "_multimodal": True,
        "content": [
            {
                "type": "text",
                "text": "Image attached at: /tmp/cma/screenshot.png",
            },
            {
                "type": "image_url",
                "image_url": {"url": DATA_URL},
            },
        ],
        "text_summary": "Image attached natively: /tmp/cma/screenshot.png",
        "meta": {"image_url": "/tmp/cma/screenshot.png", "size_bytes": 48},
    }


def test_session_log_replaces_native_tool_result_with_text_summary():
    original = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": _native_tool_result(),
    }

    safe = AIAgent._message_for_session_log(original)

    assert safe["content"] == "Image attached natively: /tmp/cma/screenshot.png"
    assert "data:image" not in json.dumps(safe)
    assert "data:image" in json.dumps(original)


def test_session_log_strips_user_image_parts_but_keeps_text_path_hints():
    original = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Use this CMA image: /tmp/cma/hero.png"},
            {"type": "image_url", "image_url": {"url": DATA_URL}},
        ],
        "_anthropic_content_blocks": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "B" * 64,
                },
            }
        ],
    }

    safe = AIAgent._message_for_session_log(original)

    assert safe["content"][0]["text"] == "Use this CMA image: /tmp/cma/hero.png"
    assert safe["content"][1] == {
        "type": "text",
        "text": "[Attached image omitted from persisted session log]",
    }
    assert "_anthropic_content_blocks" not in safe
    assert "data:image" not in json.dumps(safe)
    assert "_anthropic_content_blocks" in original


def test_native_tool_result_stays_multimodal_for_active_vision_model():
    agent = object.__new__(AIAgent)
    agent._vision_supported = True
    result = _native_tool_result()

    content = agent._tool_result_content_for_active_model("vision_analyze", result)

    assert isinstance(content, list)
    assert content[1]["image_url"]["url"].startswith("data:image")


def test_native_tool_result_downgrades_when_provider_rejects_vision():
    agent = object.__new__(AIAgent)
    agent._vision_supported = False

    content = agent._tool_result_content_for_active_model("vision_analyze", _native_tool_result())

    assert content == "Image attached natively: /tmp/cma/screenshot.png"


def test_strip_image_parts_from_tool_messages_downgrades_list_content():
    api_messages = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": [
                {"type": "text", "text": "Image attached at: /tmp/cma/screenshot.png"},
                {"type": "image_url", "image_url": {"url": DATA_URL}},
            ],
        }
    ]

    changed = AIAgent._try_strip_image_parts_from_tool_messages(api_messages)

    assert changed is True
    assert api_messages[0]["content"] == [
        {"type": "text", "text": "Image attached at: /tmp/cma/screenshot.png"}
    ]
    assert "data:image" not in json.dumps(api_messages)
