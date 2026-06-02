"""Cross-session provider circuit breaker for genuine usage-cap exhaustion.

Generalizes ``nous_rate_guard`` to every provider. When a provider returns a
*genuine* usage-cap 429 ("the usage limit has been reached", "quota
exceeded" — with NO transient "try again / resets in" language), we record a
breaker file so ALL sessions (CLI, gateway, cron, auxiliary) skip that
provider until its cooldown elapses, instead of each one retrying into the
wall and deepening the hole.

CRITICAL: only trip on a *genuine* cap. A transient 429 ("rate limited, try
again in 5s", upstream overload) must NOT trip the breaker — that would block
a healthy provider cross-session for everyone. The caller is responsible for
the genuine-vs-transient decision (see ``is_genuine_usage_cap``); this module
just stores/reads the state.

State files live at ``~/.elevate/rate_limits/provider_<name>.json`` — separate
namespace from nous_rate_guard's ``nous.json`` so the two never collide.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Mapping, Optional

from utils import atomic_replace

logger = logging.getLogger(__name__)

_STATE_SUBDIR = "rate_limits"

# Imported from the classifier so the genuine-vs-transient test stays in sync
# with how errors are classified elsewhere.
try:
    from agent.error_classifier import (
        _USAGE_LIMIT_PATTERNS as _USAGE_LIMIT_PATTERNS,
        _USAGE_LIMIT_TRANSIENT_SIGNALS as _USAGE_LIMIT_TRANSIENT_SIGNALS,
    )
except Exception:  # pragma: no cover - defensive; keep a local copy in sync
    _USAGE_LIMIT_PATTERNS = ["usage limit", "quota", "limit exceeded", "key limit exceeded"]
    _USAGE_LIMIT_TRANSIENT_SIGNALS = [
        "try again", "retry", "resets at", "reset in", "wait",
        "requests remaining", "periodic", "window",
    ]


def _sanitize(provider: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", (provider or "unknown").strip().lower()) or "unknown"


def _state_path(provider: str) -> str:
    try:
        from elevate_constants import get_elevate_home
        base = get_elevate_home()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".elevate")
    return os.path.join(base, _STATE_SUBDIR, f"provider_{_sanitize(provider)}.json")


def is_genuine_usage_cap(error_msg: Optional[str]) -> bool:
    """True when an error message reads like a genuine account usage cap.

    A genuine cap mentions a usage-limit/quota AND lacks any transient
    "try again / resets in / wait" language. Transient throttling 429s
    (which carry that language) return False so the breaker never trips on
    a provider that's actually healthy.
    """
    if not error_msg:
        return False
    msg = error_msg.lower()
    has_cap = any(p in msg for p in _USAGE_LIMIT_PATTERNS)
    has_transient = any(s in msg for s in _USAGE_LIMIT_TRANSIENT_SIGNALS)
    return has_cap and not has_transient


def _parse_reset_seconds(headers: Optional[Mapping[str, str]]) -> Optional[float]:
    if not headers:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    for key in (
        "x-ratelimit-reset-requests-1h",
        "x-ratelimit-reset-requests",
        "retry-after",
    ):
        raw = lowered.get(key)
        if raw is not None:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
    return None


def record_provider_rate_limit(
    provider: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    error_context: Optional[dict[str, Any]] = None,
    default_cooldown: float = 300.0,
) -> None:
    """Record that ``provider`` is usage-capped. Parses reset time from headers
    or error context; falls back to ``default_cooldown``."""
    now = time.time()
    reset_at = None

    header_seconds = _parse_reset_seconds(headers)
    if header_seconds is not None:
        reset_at = now + header_seconds

    if reset_at is None and isinstance(error_context, dict):
        ctx_reset = error_context.get("reset_at")
        if isinstance(ctx_reset, (int, float)) and ctx_reset > now:
            reset_at = float(ctx_reset)

    if reset_at is None:
        reset_at = now + default_cooldown

    path = _state_path(provider)
    try:
        state_dir = os.path.dirname(path)
        os.makedirs(state_dir, exist_ok=True)
        state = {
            "provider": provider,
            "reset_at": reset_at,
            "recorded_at": now,
            "reset_seconds": reset_at - now,
        }
        fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            atomic_replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info(
            "Provider '%s' usage-cap breaker tripped: resets in %.0fs",
            provider, reset_at - now,
        )
    except Exception as exc:
        logger.debug("Failed to write provider breaker state for %s: %s", provider, exc)


def provider_rate_limit_remaining(provider: str) -> Optional[float]:
    """Seconds until ``provider``'s breaker resets, or None if not tripped."""
    path = _state_path(provider)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        remaining = state.get("reset_at", 0) - time.time()
        if remaining > 0:
            return remaining
        try:
            os.unlink(path)  # expired — clean up
        except OSError:
            pass
        return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_provider_rate_limit(provider: str) -> None:
    """Clear ``provider``'s breaker (e.g. after a successful request)."""
    try:
        os.unlink(_state_path(provider))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("Failed to clear provider breaker for %s: %s", provider, exc)


def format_remaining(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, remainder = divmod(s, 3600)
    m = remainder // 60
    return f"{h}h {m}m" if m else f"{h}h"
