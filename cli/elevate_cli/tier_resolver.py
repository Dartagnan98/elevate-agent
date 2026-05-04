"""Tier -> concrete model resolver.

Skills declare *tiers* (`utility`, `draft`, `orchestrator`, `send`) instead of
hardcoding model IDs. The user maps each tier to a model from their harness
once via the Settings UI; the mapping persists to ``~/.elevate/tier_config.json``.

Resolution order (first hit wins):
1. Explicit per-tier mapping in ``tier_config.json``.
2. Heuristic against the harness model catalog
   (cheapest known fast model for ``utility``/``send``,
    most-capable for ``orchestrator``, mid for ``draft``).
3. The current ``model.default`` from ``~/.elevate/config.yaml``.

The resolver never reads provider API keys, never calls a provider directly,
and never hardcodes a model name. New providers and new model families surface
automatically through the harness's standard model discovery (see
``elevate_cli.models.provider_model_ids`` + ``list_available_providers``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

VALID_TIERS = ("orchestrator", "draft", "utility", "send")
TIER_CONFIG_FILENAME = "tier_config.json"

# Lower-case substring hints used to bucket models when the user has not yet
# mapped a tier explicitly. These are intentionally tiny and family-agnostic
# (they look at *categories* like opus/haiku/mini/flash/turbo, not specific
# version strings) so new releases land in the right bucket without code edits.
_CHEAP_HINTS = (
    "haiku", "mini", "flash", "nano", "small", "lite", "tiny",
    "8b", "9b", "12b", "instruct-7", "phi-3",
)
_TOP_HINTS = (
    "opus", "sonnet-4", "sonnet-5", "gpt-5", "gpt-4.1", "gpt-4o",
    "o1", "o3", "o4", "gemini-2.5-pro", "ultra", "pro-1.5", "70b", "405b",
)
_MID_HINTS = (
    "sonnet", "gpt-4", "gemini-1.5", "deepseek", "qwen2", "command-r",
)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _tier_config_path() -> Path:
    from elevate_constants import get_elevate_home
    return get_elevate_home() / TIER_CONFIG_FILENAME


def load_tier_config() -> Dict[str, Any]:
    """Read the persisted tier->model mapping. Returns ``{}`` if missing."""
    path = _tier_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log.warning("tier_resolver: failed to read %s: %s", path, exc)
        return {}


def save_tier_config(mapping: Dict[str, Any]) -> Path:
    """Atomically write the tier->model mapping. Validates tier names."""
    sanitized: Dict[str, Any] = {}
    for tier_id, value in mapping.items():
        if tier_id not in VALID_TIERS:
            raise ValueError(f"unknown tier: {tier_id!r}")
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            model_id = value.get("model") or value.get("default") or ""
            provider = value.get("provider", "")
        else:
            model_id = str(value)
            provider = ""
        if not model_id:
            continue
        sanitized[tier_id] = {"model": model_id}
        if provider:
            sanitized[tier_id]["provider"] = provider

    path = _tier_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(sanitized, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _harness_default_model() -> tuple[str, str]:
    """Return (model_id, provider) from ``~/.elevate/config.yaml``."""
    try:
        from elevate_cli.config import load_config
    except Exception:
        return "", ""
    cfg = load_config() or {}
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        return (
            str(model_cfg.get("default") or model_cfg.get("model") or "").strip(),
            str(model_cfg.get("provider") or "").strip(),
        )
    if isinstance(model_cfg, str):
        return model_cfg.strip(), ""
    return "", ""


def _model_bucket(model_id: str) -> str:
    """Best-effort heuristic bucket for an unknown model name.

    Returns one of ``"cheap" | "top" | "mid" | "unknown"``. Used only when
    no explicit mapping exists.
    """
    name = model_id.lower()
    for hint in _TOP_HINTS:
        if hint in name:
            return "top"
    for hint in _CHEAP_HINTS:
        if hint in name:
            return "cheap"
    for hint in _MID_HINTS:
        if hint in name:
            return "mid"
    return "unknown"


def _bucket_for_tier(tier_id: str) -> str:
    if tier_id == "orchestrator":
        return "top"
    if tier_id == "draft":
        return "mid"
    # utility + send both want cheapest
    return "cheap"


def _enumerate_available_models() -> List[Dict[str, Any]]:
    """Best-effort enumeration of harness-available models.

    Each entry: ``{id, provider, source, tier_hint, authenticated}``.
    Failures are swallowed so resolution still returns the harness default.
    """
    out: List[Dict[str, Any]] = []
    try:
        from elevate_cli.models import (
            list_available_providers,
            provider_model_ids,
        )
    except Exception as exc:
        _log.debug("tier_resolver: model discovery import failed: %s", exc)
        return out

    try:
        providers = list_available_providers() or []
    except Exception as exc:
        _log.debug("tier_resolver: list_available_providers failed: %s", exc)
        providers = []

    for prov in providers:
        pid = prov.get("id", "")
        if not pid or pid == "custom":
            continue
        if not prov.get("authenticated"):
            # Skip providers without creds — listing them confuses tier
            # mapping because the user can't actually call them.
            continue
        try:
            ids = provider_model_ids(pid) or []
        except Exception as exc:
            _log.debug("tier_resolver: provider_model_ids(%s) failed: %s", pid, exc)
            ids = []
        for model_id in ids:
            out.append({
                "id": model_id,
                "provider": pid,
                "source": "harness",
                "tier_hint": _model_bucket(model_id),
                "authenticated": True,
            })

    # Always include the configured default so mapping never traps the user
    # without a fallback option.
    default_id, default_provider = _harness_default_model()
    if default_id and not any(m["id"] == default_id for m in out):
        out.append({
            "id": default_id,
            "provider": default_provider,
            "source": "configured",
            "tier_hint": _model_bucket(default_id),
            "authenticated": True,
        })
    return out


def list_available_models() -> Dict[str, Any]:
    """Return ``{models: [...], default: <id>}`` for ``/api/models/available``."""
    models = _enumerate_available_models()
    default_id, _ = _harness_default_model()
    # De-dup by id while preserving first-seen order.
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for entry in models:
        mid = entry["id"]
        if mid in seen:
            continue
        seen.add(mid)
        deduped.append(entry)
    return {"models": deduped, "default": default_id}


def resolve_tier(tier_id: str) -> str:
    """Return the model id for a tier. Empty string if nothing resolves.

    Caller is expected to fall through to its own default if this returns "".
    """
    if tier_id not in VALID_TIERS:
        raise ValueError(f"unknown tier: {tier_id!r}")

    mapping = load_tier_config()
    explicit = mapping.get(tier_id)
    if isinstance(explicit, dict) and explicit.get("model"):
        return str(explicit["model"]).strip()
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    target_bucket = _bucket_for_tier(tier_id)
    candidates = _enumerate_available_models()
    if candidates:
        # First pass: exact bucket match.
        for entry in candidates:
            if entry.get("tier_hint") == target_bucket:
                return entry["id"]
        # Second pass: nearest neighbour (top->mid, cheap->mid, mid->any).
        neighbour_order = {
            "top": ["mid", "cheap", "unknown"],
            "mid": ["top", "cheap", "unknown"],
            "cheap": ["mid", "top", "unknown"],
        }.get(target_bucket, ["unknown"])
        for next_bucket in neighbour_order:
            for entry in candidates:
                if entry.get("tier_hint") == next_bucket:
                    return entry["id"]
        # Last resort: first available.
        return candidates[0]["id"]

    # Final fallback: the harness default.
    default_id, _ = _harness_default_model()
    return default_id


def resolve_tier_with_provider(tier_id: str) -> tuple[str, str]:
    """Like ``resolve_tier`` but also returns the provider id.

    Returns ``("", "")`` if nothing resolves.
    """
    mapping = load_tier_config()
    explicit = mapping.get(tier_id)
    if isinstance(explicit, dict) and explicit.get("model"):
        return str(explicit["model"]).strip(), str(explicit.get("provider") or "").strip()
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), ""

    target_bucket = _bucket_for_tier(tier_id)
    candidates = _enumerate_available_models()
    if candidates:
        for entry in candidates:
            if entry.get("tier_hint") == target_bucket:
                return entry["id"], entry.get("provider") or ""
        neighbour_order = {
            "top": ["mid", "cheap", "unknown"],
            "mid": ["top", "cheap", "unknown"],
            "cheap": ["mid", "top", "unknown"],
        }.get(target_bucket, ["unknown"])
        for next_bucket in neighbour_order:
            for entry in candidates:
                if entry.get("tier_hint") == next_bucket:
                    return entry["id"], entry.get("provider") or ""
        first = candidates[0]
        return first["id"], first.get("provider") or ""

    return _harness_default_model()


def fallback_banner(tier_id: str, resolved_model: str) -> Optional[str]:
    """Return a UI-facing banner string when resolution had to compromise."""
    mapping = load_tier_config()
    if mapping.get(tier_id):
        return None
    if not resolved_model:
        return f"{tier_id} tier is not configured — set it in Settings → Model tiers"
    bucket = _model_bucket(resolved_model)
    target = _bucket_for_tier(tier_id)
    if bucket == target or bucket == "unknown":
        return None
    return (
        f"{tier_id} tier falling back to {resolved_model} — "
        f"configure a higher-capability model in your harness for better quality"
        if target == "top"
        else None
    )
