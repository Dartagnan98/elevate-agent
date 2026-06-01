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
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List


IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})
MEDIA_REF_SCHEME = "media://"
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


@dataclass(frozen=True)
class MediaAsset:
    """Stored media asset metadata."""

    id: str
    media_type: str
    path: str
    size_bytes: int

    @property
    def ref(self) -> str:
        return f"{MEDIA_REF_SCHEME}{self.id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ref": self.ref,
            "media_type": self.media_type,
            "path": self.path,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class MediaExternalizationResult:
    """Result of replacing inline image bytes with managed media refs."""

    content: Any
    changed: bool = False
    assets: int = 0
    bytes_written: int = 0


class MediaAssetStore:
    """Small content-addressed store for inline media bytes."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_media_asset_root()

    def _asset_path(self, asset_id: str, media_type: str) -> Path:
        return self.root / asset_id[:2] / f"{asset_id}{_extension_for_media_type(media_type)}"

    def store_bytes(self, data: bytes, media_type: str) -> MediaAsset:
        if not isinstance(data, bytes):
            data = bytes(data or b"")
        normalized_media_type = media_type if media_type.startswith("image/") else "image/jpeg"
        asset_id = hashlib.sha256(data).hexdigest()
        path = self._asset_path(asset_id, normalized_media_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return MediaAsset(
            id=asset_id,
            media_type=normalized_media_type,
            path=str(path),
            size_bytes=len(data),
        )

    def store_data_url(self, data_url: str) -> MediaAsset | None:
        parsed = parse_data_url(data_url)
        if parsed is None:
            return None
        media_type, data = parsed
        return self.store_bytes(data, media_type)

    def load_data_url(self, asset: dict | MediaAsset | str) -> str | None:
        if isinstance(asset, MediaAsset):
            asset_id = asset.id
            media_type = asset.media_type
            path = Path(asset.path)
        elif isinstance(asset, dict):
            asset_id = str(asset.get("id") or asset.get("ref") or "").removeprefix(MEDIA_REF_SCHEME)
            media_type = str(asset.get("media_type") or "image/jpeg")
            path = Path(str(asset.get("path") or ""))
        else:
            asset_id = str(asset or "").removeprefix(MEDIA_REF_SCHEME)
            media_type = "image/jpeg"
            path = Path("")

        if not path or str(path) == ".":
            path = self._find_asset_path(asset_id)
        if not asset_id or not path.exists():
            return None

        data = path.read_bytes()
        payload = base64.b64encode(data).decode("ascii")
        return f"data:{media_type};base64,{payload}"

    def load_base64_source(self, asset: dict | MediaAsset | str) -> dict | None:
        data_url = self.load_data_url(asset)
        if not data_url:
            return None
        header, _, payload = data_url.partition(",")
        media_type = header[len("data:"):].split(";", 1)[0] if header.startswith("data:") else "image/jpeg"
        return {"type": "base64", "media_type": media_type, "data": payload}

    def _find_asset_path(self, asset_id: str) -> Path:
        if not asset_id:
            return Path("")
        shard = self.root / asset_id[:2]
        matches = list(shard.glob(f"{asset_id}.*")) if shard.exists() else []
        return matches[0] if matches else Path("")


def default_media_asset_root() -> Path:
    """Return the profile-scoped media asset root."""
    try:
        from elevate_constants import get_elevate_home

        return get_elevate_home() / "cache" / "media-assets"
    except Exception:
        return Path(os.environ.get("ELEVATE_HOME", "") or str(Path.home() / ".elevate")) / "cache" / "media-assets"


def _extension_for_media_type(media_type: str) -> str:
    return {
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }.get(media_type.lower(), ".bin")


def parse_data_url(data_url: str) -> tuple[str, bytes] | None:
    """Parse ``data:image/...;base64,...`` into media type and bytes."""
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    header, _, payload = data_url.partition(",")
    if not payload:
        return None
    media_type = header[len("data:"):].split(";", 1)[0].strip() or "image/jpeg"
    if not media_type.startswith("image/"):
        return None
    try:
        return media_type, base64.b64decode(payload, validate=False)
    except Exception:
        return None


def _asset_ref_from_part(part: dict) -> dict | None:
    asset = part.get("_media_asset")
    if isinstance(asset, dict):
        return asset
    raw = _extract_image_url(part)
    if isinstance(raw, str) and raw.startswith(MEDIA_REF_SCHEME):
        return {"id": raw.removeprefix(MEDIA_REF_SCHEME), "ref": raw, "media_type": "image/jpeg"}
    source = part.get("source")
    if isinstance(source, dict) and source.get("type") == "media_ref":
        media_id = str(source.get("media_id") or "")
        return {
            "id": media_id,
            "ref": f"{MEDIA_REF_SCHEME}{media_id}",
            "media_type": str(source.get("media_type") or "image/jpeg"),
        }
    return None


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
    parsed = parse_data_url(url)
    return len(parsed[1]) if parsed else 0


def _externalize_image_part(part: dict, store: MediaAssetStore) -> tuple[dict, MediaAsset | None]:
    ptype = part.get("type")

    if ptype in {"image_url", "input_image"}:
        image_url = _extract_image_url(part)
        asset = store.store_data_url(image_url)
        if asset is None:
            return part, None
        new_part = dict(part)
        new_part["_media_asset"] = asset.to_dict()
        raw_image_url = part.get("image_url")
        if isinstance(raw_image_url, dict):
            new_part["image_url"] = {**raw_image_url, "url": asset.ref}
        else:
            new_part["image_url"] = asset.ref
        return new_part, asset

    if ptype == "image":
        source = part.get("source")
        if not isinstance(source, dict) or source.get("type") != "base64":
            return part, None
        media_type = str(source.get("media_type") or "image/jpeg")
        data_raw = str(source.get("data") or "")
        try:
            data = base64.b64decode(data_raw, validate=False)
        except Exception:
            return part, None
        asset = store.store_bytes(data, media_type)
        new_part = dict(part)
        new_part["_media_asset"] = asset.to_dict()
        new_part["source"] = {
            "type": "media_ref",
            "media_id": asset.id,
            "media_type": asset.media_type,
        }
        return new_part, asset

    return part, None


def externalize_inline_media_in_content(
    content: Any,
    *,
    store: MediaAssetStore | None = None,
) -> MediaExternalizationResult:
    """Replace inline image bytes with managed media refs.

    The returned content is safe to keep in live conversation state. It may
    still contain image parts, but those parts point at ``media://`` assets
    instead of embedding base64 bytes.
    """
    store = store or MediaAssetStore()
    if is_multimodal_tool_result(content):
        inner = externalize_inline_media_in_content(content.get("content"), store=store)
        if not inner.changed:
            return MediaExternalizationResult(content=content)
        new_content = dict(content)
        new_content["content"] = inner.content
        meta = dict(new_content.get("meta") or {})
        meta["media_externalized"] = True
        new_content["meta"] = meta
        return MediaExternalizationResult(
            content=new_content,
            changed=True,
            assets=inner.assets,
            bytes_written=inner.bytes_written,
        )

    if not isinstance(content, list):
        return MediaExternalizationResult(content=content)

    changed = False
    assets = 0
    bytes_written = 0
    out: List[Any] = []
    for part in content:
        if is_image_part(part):
            new_part, asset = _externalize_image_part(part, store)
            out.append(new_part)
            if asset is not None:
                changed = True
                assets += 1
                bytes_written += asset.size_bytes
            continue
        out.append(part)
    return MediaExternalizationResult(
        content=out if changed else content,
        changed=changed,
        assets=assets,
        bytes_written=bytes_written,
    )


def externalize_inline_media_in_messages(
    messages: Iterable[dict],
    *,
    store: MediaAssetStore | None = None,
) -> tuple[list, MediaExternalizationResult]:
    """Externalize inline media across messages, returning a possibly new list."""
    store = store or MediaAssetStore()
    changed = False
    assets = 0
    bytes_written = 0
    out: list = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        result = externalize_inline_media_in_content(msg.get("content"), store=store)
        if result.changed:
            new_msg = dict(msg)
            new_msg["content"] = result.content
            out.append(new_msg)
            changed = True
            assets += result.assets
            bytes_written += result.bytes_written
        else:
            out.append(msg)
    return out if changed else list(messages or []), MediaExternalizationResult(
        content=None,
        changed=changed,
        assets=assets,
        bytes_written=bytes_written,
    )


def _hydrate_image_part(part: dict, store: MediaAssetStore) -> dict:
    asset_ref = _asset_ref_from_part(part)
    if not asset_ref:
        return part

    ptype = part.get("type")
    if ptype in {"image_url", "input_image"}:
        data_url = store.load_data_url(asset_ref)
        if not data_url:
            return {
                "type": "text",
                "text": "[Attached image unavailable: media asset could not be loaded]",
            }
        new_part = dict(part)
        new_part.pop("_media_asset", None)
        raw_image_url = part.get("image_url")
        if isinstance(raw_image_url, dict):
            new_part["image_url"] = {**raw_image_url, "url": data_url}
        else:
            new_part["image_url"] = data_url
        return new_part

    if ptype == "image":
        source = store.load_base64_source(asset_ref)
        if not source:
            return {
                "type": "text",
                "text": "[Attached image unavailable: media asset could not be loaded]",
            }
        new_part = dict(part)
        new_part.pop("_media_asset", None)
        new_part["source"] = source
        return new_part
    return part


def hydrate_media_refs_in_content(
    content: Any,
    *,
    store: MediaAssetStore | None = None,
) -> Any:
    """Hydrate ``media://`` refs in a content value for an outgoing API call."""
    store = store or MediaAssetStore()
    if is_multimodal_tool_result(content):
        new_content = dict(content)
        new_content["content"] = hydrate_media_refs_in_content(content.get("content"), store=store)
        return new_content
    if not isinstance(content, list):
        return content
    changed = False
    out: List[Any] = []
    for part in content:
        if is_image_part(part):
            hydrated = _hydrate_image_part(part, store)
            out.append(hydrated)
            changed = changed or hydrated is not part
        else:
            out.append(part)
    return out if changed else content


def hydrate_media_refs_in_messages(
    messages: Iterable[dict],
    *,
    store: MediaAssetStore | None = None,
) -> list:
    """Hydrate media refs in message copies for provider transport only."""
    store = store or MediaAssetStore()
    hydrated: list = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            hydrated.append(msg)
            continue
        content = hydrate_media_refs_in_content(msg.get("content"), store=store)
        if content is msg.get("content"):
            hydrated.append(msg)
        else:
            new_msg = dict(msg)
            new_msg["content"] = content
            hydrated.append(new_msg)
    return hydrated


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
    "MEDIA_REF_SCHEME",
    "MediaAsset",
    "MediaAssetStore",
    "MediaExternalizationResult",
    "MediaPayloadStats",
    "SESSION_IMAGE_PLACEHOLDER",
    "TRAJECTORY_IMAGE_PLACEHOLDER",
    "append_text_to_multimodal",
    "content_for_persistence",
    "content_has_images",
    "default_media_asset_root",
    "externalize_inline_media_in_content",
    "externalize_inline_media_in_messages",
    "hydrate_media_refs_in_content",
    "hydrate_media_refs_in_messages",
    "is_image_part",
    "is_multimodal_tool_result",
    "media_stats_for_content",
    "media_stats_for_messages",
    "message_for_persistence",
    "message_for_trajectory",
    "multimodal_text_summary",
    "parse_data_url",
    "strip_image_parts_from_parts",
    "strip_image_parts_from_tool_messages",
    "strip_images_from_content",
    "tool_result_content_for_active_model",
]
