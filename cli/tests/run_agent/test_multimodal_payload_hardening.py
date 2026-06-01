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

    assert safe["content"].startswith("[Attached image omitted from persisted session log]")
    assert "Image attached natively: /tmp/cma/screenshot.png" in safe["content"]
    assert "size=48 bytes" in safe["content"]
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


def test_session_db_flush_uses_persistence_safe_media_content():
    captured = {}

    class FakeSessionDb:
        def ensure_session(self, *args, **kwargs):
            captured["ensured"] = True

        def append_message(self, **kwargs):
            captured["content"] = kwargs["content"]
            captured["role"] = kwargs["role"]

    agent = object.__new__(AIAgent)
    agent._session_db = FakeSessionDb()
    agent.session_id = "session_1"
    agent.platform = "cli"
    agent.model = "gpt-5"
    agent._last_flushed_db_idx = 0
    agent._persist_user_message_idx = None
    agent._persist_user_message_override = None

    agent._flush_messages_to_session_db(
        [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "tool_name": "vision_analyze",
                "content": _native_tool_result(),
            }
        ]
    )

    assert captured["ensured"] is True
    assert captured["role"] == "tool"
    assert captured["content"].startswith("[Attached image omitted from persisted session log]")
    assert "/tmp/cma/screenshot.png" in captured["content"]
    assert "data:image" not in captured["content"]


def test_agent_externalizes_live_media_and_hydrates_api_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    agent = object.__new__(AIAgent)
    agent.session_id = "session_1"

    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "tool_name": "vision_analyze",
            "content": _native_tool_result(),
        }
    ]

    externalized = agent._externalize_inline_media_messages(messages)
    api_messages = agent._hydrate_media_refs_for_api([msg.copy() for msg in externalized])

    assert "data:image" not in json.dumps(externalized)
    assert "media://" in json.dumps(externalized)
    assert "data:image" in json.dumps(api_messages)
    assert "data:image" in json.dumps(messages)


def test_pending_steer_appends_to_multimodal_envelope_without_corrupting_it():
    agent = object.__new__(AIAgent)
    agent._pending_steer = "focus on the navbar"
    agent._pending_steer_lock = None
    content = _native_tool_result()
    messages = [{"role": "tool", "content": content, "tool_call_id": "call_1"}]

    agent._apply_pending_steer_to_tool_results(messages, 1)

    assert messages[0]["content"]["_multimodal"] is True
    assert isinstance(messages[0]["content"]["content"], list)
    assert "User guidance: focus on the navbar" in messages[0]["content"]["content"][0]["text"]
    assert "User guidance: focus on the navbar" in messages[0]["content"]["text_summary"]


def test_soft_interrupt_appends_to_multimodal_envelope_without_corrupting_it():
    agent = object.__new__(AIAgent)
    agent._pending_soft_interrupts = [{"content": "also check mobile"}]
    agent._pending_soft_interrupts_lock = None
    content = _native_tool_result()
    messages = [{"role": "tool", "content": content, "tool_call_id": "call_1"}]

    delivered = agent._apply_pending_soft_interrupts_to_tool_results(messages, 1)

    assert delivered is True
    assert messages[0]["content"]["_multimodal"] is True
    assert isinstance(messages[0]["content"]["content"], list)
    assert "also check mobile" in messages[0]["content"]["content"][0]["text"]
    assert "also check mobile" in messages[0]["content"]["text_summary"]
