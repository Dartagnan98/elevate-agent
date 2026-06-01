"""Media payload policy for agent context, API calls, and persistence.

This module owns the lifecycle boundary for native media payloads:

* API-bound messages may carry image parts for the active model turn.
* Persisted transcripts keep text, local path hints, summaries, and metadata,
  but never raw inline image bytes.
* Retry recovery can downgrade tool-image messages when a provider rejects
  multipart tool content.

Keeping these rules in one module prevents the agent loop, compressor, session
store, and trajectory writer from each inventing subtly different media logic.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})
SESSION_IMAGE_PLACEHOLDER = "[Attached image omitted from persisted session log]"
COMPRESSION_IMAGE_PLACEHOLDER = "[Attached image - stripped after compression]"
TRAJECTORY_IMAGE_PLACEHOLDER = "[screenshot]"


@dataclass(frozen=True)
class MediaPayloadStats:
    """Lightweight accounting for inline media payloads."""

    image_parts: int = 0
    data_url_bytes: int = 0
    text_chars: int = 0

    @property
    def has_inline_image_bytes(self) -> bool:
        return self.data_url_bytes > 0

    def __add__(self, other: "MediaPayloadStats") -> "MediaPayloadStats":
        return MediaPayloadStats(
            image_parts=self.image_parts + other.image_parts,
            data_url_bytes=self.data_url_bytes + other.data_url_bytes,
            text_chars=self.text_chars + other.text_chars,
        )


def is_image_part(part: Any) -> bool:
    """Return True when *part* is a supported native image content block."""
    return isinstance(part, dict) and part.get("type") in IMAGE_PART_TYPES


def _iter_content_parts(content: Any) -> Iterable[Any]:
    if is_multimodal_tool_result(content):
        content = content.get("content")
    if isinstance(content, list):
        yield from content


def content_has_images(content: Any) -> bool:
    """Return True when content contains native image parts."""
    return any(is_image_part(part) for part in _iter_content_parts(content))


def is_multimodal_tool_result(value: Any) -> bool:
    """Return True for the native-vision tool-result envelope."""
    return (
        isinstance(value, dict)
        and value.get("_multimodal") is True
        and isinstance(value.get("content"), list)
    )


def multimodal_text_summary(value: Any) -> str:
    """Return a plain text view of a native multimodal result or any value."""
    if is_multimodal_tool_result(value):
        if value.get("text_summary"):
            return str(value["text_summary"])
        parts: list[str] = []
        for part in value.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                parts.append(str(part.get("text", "") or ""))
            elif isinstance(part, str):
                parts.append(part)
        if parts:
            return "\n".join(part for part in parts if part)
        return "[multimodal tool result]"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def append_text_to_multimodal(value: Dict[str, Any], text: str) -> None:
    """Append text to a multimodal envelope without touching image parts."""
    if not is_multimodal_tool_result(value):
        return
    parts = value.get("content") or []
    for part in parts:
        if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
            part["text"] = str(part.get("text", "") or "") + text
            break
    else:
        parts.insert(0, {"type": "text", "text": text})
        value["content"] = parts
    if isinstance(value.get("text_summary"), str):
        value["text_summary"] = value["text_summary"] + text


def _extract_image_url(part: dict) -> str:
    raw = part.get("image_url")
    if isinstance(raw, dict):
        return str(raw.get("url") or "")
    if isinstance(raw, str):
        return raw
    source = part.get("source")
    if isinstance(source, dict) and source.get("type") == "base64":
        media_type = str(source.get("media_type") or "image/jpeg")
        data = str(source.get("data") or "")
        return f"data:{media_type};base64,{data}" if data else ""
    return ""


def _data_url_payload_bytes(url: str) -> int:
    if not isinstance(url, str) or not url.startswith("data:"):
        return 0
    _, _, payload = url.partition(",")
    if not payload:
        return 0
    try:
        return len(base64.b64decode(payload, validate=False))
    except Exception:
        return len(payload)


def media_stats_for_content(content: Any) -> MediaPayloadStats:
    """Return image count, inline byte count, and text chars for content."""
    if isinstance(content, str):
        return MediaPayloadStats(text_chars=len(content))
    if is_multimodal_tool_result(content):
        return media_stats_for_content(content.get("content"))
    if not isinstance(content, list):
        return MediaPayloadStats(text_chars=len(str(content or "")))

    stats = MediaPayloadStats()
    for part in content:
        if isinstance(part, str):
            stats += MediaPayloadStats(text_chars=len(part))
            continue
        if not isinstance(part, dict):
            stats += MediaPayloadStats(text_chars=len(str(part)))
            continue
        if is_image_part(part):
            stats += MediaPayloadStats(
                image_parts=1,
                data_url_bytes=_data_url_payload_bytes(_extract_image_url(part)),
            )
            continue
        text = part.get("text")
        if isinstance(text, str):
            stats += MediaPayloadStats(text_chars=len(text))
    return stats


def media_stats_for_messages(messages: Iterable[dict]) -> MediaPayloadStats:
    stats = MediaPayloadStats()
    for msg in messages or []:
        if isinstance(msg, dict):
            stats += media_stats_for_content(msg.get("content"))
    return stats


def strip_image_parts_from_parts(
    parts: Any,
    *,
    placeholder: str = SESSION_IMAGE_PLACEHOLDER,
) -> Any:
    """Return a copy of a parts list with image parts replaced by text."""
    if not isinstance(parts, list):
        return None
    changed = False
    cleaned: List[Any] = []
    for part in parts:
        if is_image_part(part):
            changed = True
            cleaned.append({"type": "text", "text": placeholder})
        else:
            cleaned.append(part)
    return cleaned if changed else None


def strip_images_from_content(
    content: Any,
    *,
    placeholder: str = SESSION_IMAGE_PLACEHOLDER,
    multimodal_prefix: str = "[Attached image stripped]",
) -> Any:
    """Return content safe for historical context or persistence.

    The input is never mutated.
    """
    if is_multimodal_tool_result(content):
        if not content_has_images(content):
            return content
        summary = str(content.get("text_summary") or "native vision image")
        meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
        details = []
        source = meta.get("image_url") or meta.get("source") or ""
        size_bytes = meta.get("size_bytes")
        if source:
            details.append(f"source={source}")
        if isinstance(size_bytes, int) and size_bytes > 0:
            details.append(f"size={size_bytes} bytes")
        detail_text = f" ({', '.join(details)})" if details else ""
        return f"{multimodal_prefix} {summary[:300]}{detail_text}".strip()

    if not isinstance(content, list):
        return content
    stripped = strip_image_parts_from_parts(content, placeholder=placeholder)
    return stripped if stripped is not None else content


def content_for_persistence(content: Any) -> Any:
    """Return content safe for disk/DB persistence."""
    return strip_images_from_content(
        content,
        placeholder=SESSION_IMAGE_PLACEHOLDER,
        multimodal_prefix="[Attached image omitted from persisted session log]",
    )


def message_for_persistence(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of *msg* with raw media payloads removed."""
    safe = dict(msg)
    safe["content"] = content_for_persistence(safe.get("content"))
    safe.pop("_anthropic_content_blocks", None)
    return safe


def tool_result_content_for_active_model(result: Any, *, vision_supported: bool = True) -> Any:
    """Return the content shape to send on the immediate model call."""
    if not is_multimodal_tool_result(result):
        return result
    if not vision_supported:
        return multimodal_text_summary(result)
    return result.get("content") or multimodal_text_summary(result)


def strip_image_parts_from_tool_messages(api_messages: list) -> bool:
    """Mutate tool messages in-place, removing image parts from list content."""
    changed = False
    for msg in api_messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        new_parts: List[Any] = []
        removed = False
        for part in content:
            if is_image_part(part):
                removed = True
                continue
            new_parts.append(part)
        if not removed:
            continue
        changed = True
        msg["content"] = new_parts or "[image content removed after provider rejected tool images]"
    return changed


def message_for_trajectory(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a trajectory-safe message with image bytes replaced."""
    if not isinstance(msg, dict):
        return msg
    content = msg.get("content")
    if is_multimodal_tool_result(content):
        return {**msg, "content": multimodal_text_summary(content)}
    if isinstance(content, list):
        stripped = strip_image_parts_from_parts(
            content,
            placeholder=TRAJECTORY_IMAGE_PLACEHOLDER,
        )
        if stripped is not None:
            return {**msg, "content": stripped}
    return msg


__all__ = [
    "COMPRESSION_IMAGE_PLACEHOLDER",
    "IMAGE_PART_TYPES",
    "MediaPayloadStats",
    "SESSION_IMAGE_PLACEHOLDER",
    "TRAJECTORY_IMAGE_PLACEHOLDER",
    "append_text_to_multimodal",
    "content_for_persistence",
    "content_has_images",
    "is_image_part",
    "is_multimodal_tool_result",
    "media_stats_for_content",
    "media_stats_for_messages",
    "message_for_persistence",
    "message_for_trajectory",
    "multimodal_text_summary",
    "strip_image_parts_from_parts",
    "strip_image_parts_from_tool_messages",
    "strip_images_from_content",
    "tool_result_content_for_active_model",
]
