"""Tests for the centralized media context policy."""

from __future__ import annotations

import json

from agent.media_context import (
    content_for_persistence,
    content_has_images,
    media_stats_for_messages,
    message_for_trajectory,
    strip_image_parts_from_tool_messages,
    tool_result_content_for_active_model,
)


DATA_URL = "data:image/png;base64,QUJDRA=="


def _parts():
    return [
        {"type": "text", "text": "Screenshot at /tmp/screen.png"},
        {"type": "image_url", "image_url": {"url": DATA_URL}},
    ]


def _envelope():
    return {
        "_multimodal": True,
        "content": _parts(),
        "text_summary": "Screenshot attached: /tmp/screen.png",
        "meta": {"image_url": "/tmp/screen.png", "size_bytes": 4},
    }


def test_content_for_persistence_replaces_raw_image_bytes():
    safe = content_for_persistence(_parts())

    assert safe[0]["text"] == "Screenshot at /tmp/screen.png"
    assert safe[1]["type"] == "text"
    assert "data:image" not in json.dumps(safe)


def test_multimodal_envelope_persists_as_summary_with_metadata():
    safe = content_for_persistence(_envelope())

    assert isinstance(safe, str)
    assert "Screenshot attached" in safe
    assert "/tmp/screen.png" in safe
    assert "data:image" not in safe


def test_tool_result_content_policy_preserves_active_vision_turn_only():
    envelope = _envelope()

    assert tool_result_content_for_active_model(envelope, vision_supported=True) == envelope["content"]
    assert (
        tool_result_content_for_active_model(envelope, vision_supported=False)
        == "Screenshot attached: /tmp/screen.png"
    )


def test_tool_message_downgrade_removes_only_image_parts():
    messages = [{"role": "tool", "content": _parts()}]

    changed = strip_image_parts_from_tool_messages(messages)

    assert changed is True
    assert messages == [{"role": "tool", "content": [{"type": "text", "text": "Screenshot at /tmp/screen.png"}]}]


def test_media_stats_count_inline_bytes_without_treating_them_as_text():
    stats = media_stats_for_messages([{"role": "user", "content": _parts()}])

    assert stats.image_parts == 1
    assert stats.data_url_bytes == 4
    assert stats.text_chars == len("Screenshot at /tmp/screen.png")
    assert stats.has_inline_image_bytes is True


def test_trajectory_message_replaces_image_with_placeholder():
    msg = {"role": "user", "content": _parts()}

    safe = message_for_trajectory(msg)

    assert content_has_images(msg["content"]) is True
    assert content_has_images(safe["content"]) is False
    assert safe["content"][1] == {"type": "text", "text": "[screenshot]"}
