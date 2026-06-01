"""Tests for the centralized media context policy."""

from __future__ import annotations

import json

from agent.media_context import (
    MediaAssetStore,
    content_for_persistence,
    content_has_images,
    externalize_inline_media_in_content,
    externalize_inline_media_in_messages,
    hydrate_media_refs_in_content,
    hydrate_media_refs_in_messages,
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


def test_externalize_inline_media_stores_asset_and_replaces_data_url(tmp_path):
    store = MediaAssetStore(tmp_path)

    result = externalize_inline_media_in_content(_parts(), store=store)

    assert result.changed is True
    assert result.assets == 1
    assert result.bytes_written == 4
    assert "data:image" not in json.dumps(result.content)
    assert result.content[1]["image_url"]["url"].startswith("media://")
    assert result.content[1]["_media_asset"]["path"]
    assert (tmp_path / result.content[1]["_media_asset"]["id"][:2]).exists()


def test_hydrate_media_refs_restores_provider_data_url(tmp_path):
    store = MediaAssetStore(tmp_path)
    externalized = externalize_inline_media_in_content(_parts(), store=store).content

    hydrated = hydrate_media_refs_in_content(externalized, store=store)

    assert hydrated[1]["image_url"]["url"] == DATA_URL


def test_externalize_and_hydrate_messages_preserves_live_state_separation(tmp_path):
    store = MediaAssetStore(tmp_path)
    messages = [{"role": "user", "content": _parts()}]

    externalized, result = externalize_inline_media_in_messages(messages, store=store)
    hydrated = hydrate_media_refs_in_messages(externalized, store=store)

    assert result.changed is True
    assert "data:image" not in json.dumps(externalized)
    assert "media://" in json.dumps(externalized)
    assert "data:image" in json.dumps(hydrated)
    assert "data:image" in json.dumps(messages)
