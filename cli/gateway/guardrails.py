"""Gateway-level spend and abuse guardrails.

These checks run before an agent turn starts, so accidental loops or public
message bursts fail cheaply and leave a useful audit trail.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque


DEFAULT_RATE_LIMIT_MESSAGES = 20
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_DAILY_TOKEN_CAP = 2_000_000
DEFAULT_DAILY_WINDOW_SECONDS = 24 * 60 * 60


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _as_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    return _as_int(raw, default, minimum=minimum) if raw not in (None, "") else default


def _guardrail_root(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    raw = cfg.get("guardrails") or cfg.get("gateway_guardrails") or {}
    return raw if isinstance(raw, dict) else {}


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str = ""
    message: str = ""
    retry_after_seconds: int | None = None
    used_tokens: int = 0
    token_cap: int = 0


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        *,
        max_messages: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int | None]:
        if max_messages <= 0 or window_seconds <= 0:
            return True, None
        ts = time.time() if now is None else now
        cutoff = ts - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= max_messages:
                retry_after = max(1, int(round(window_seconds - (ts - bucket[0]))))
                return False, retry_after
            bucket.append(ts)
        return True, None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_RATE_LIMITER = _SlidingWindowLimiter()


def reset_guardrails_for_tests() -> None:
    _RATE_LIMITER.reset()


def _rate_limit_config(config: dict[str, Any] | None) -> tuple[bool, int, int]:
    root = _guardrail_root(config)
    enabled_default = _as_bool(root.get("enabled"), True)
    raw = root.get("rate_limit") or {}
    rate_cfg = raw if isinstance(raw, dict) else {}
    enabled = _as_bool(rate_cfg.get("enabled"), enabled_default)
    max_messages = _env_int(
        "ELEVATE_RATE_LIMIT_MESSAGES",
        _as_int(
            rate_cfg.get("max_messages"),
            DEFAULT_RATE_LIMIT_MESSAGES,
            minimum=0,
        ),
        minimum=0,
    )
    window_seconds = _env_int(
        "ELEVATE_RATE_LIMIT_WINDOW_SECONDS",
        _as_int(
            rate_cfg.get("window_seconds"),
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
            minimum=1,
        ),
        minimum=1,
    )
    return enabled, max_messages, window_seconds


def _usage_config(config: dict[str, Any] | None) -> tuple[bool, int, int]:
    root = _guardrail_root(config)
    enabled_default = _as_bool(root.get("enabled"), True)
    raw = root.get("usage") or root.get("token_cap") or {}
    usage_cfg = raw if isinstance(raw, dict) else {}
    enabled = _as_bool(usage_cfg.get("enabled"), enabled_default)
    cap = _env_int(
        "ELEVATE_DAILY_TOKEN_CAP",
        _as_int(
            usage_cfg.get("daily_token_cap"),
            DEFAULT_DAILY_TOKEN_CAP,
            minimum=0,
        ),
        minimum=0,
    )
    window_seconds = _env_int(
        "ELEVATE_TOKEN_CAP_WINDOW_SECONDS",
        _as_int(
            usage_cfg.get("window_seconds"),
            DEFAULT_DAILY_WINDOW_SECONDS,
            minimum=1,
        ),
        minimum=1,
    )
    return enabled, cap, window_seconds


def check_gateway_guardrails(
    *,
    config: dict[str, Any] | None,
    identity_key: str,
    source: str,
    session_key: str,
    now: float | None = None,
) -> GuardrailDecision:
    """Return whether a new agent turn may start."""
    key = identity_key or session_key or source or "unknown"
    rate_enabled, max_messages, window_seconds = _rate_limit_config(config)
    if rate_enabled and max_messages > 0:
        allowed, retry_after = _RATE_LIMITER.check(
            key,
            max_messages=max_messages,
            window_seconds=window_seconds,
            now=now,
        )
        if not allowed:
            return GuardrailDecision(
                allowed=False,
                reason="rate_limited",
                retry_after_seconds=retry_after,
                message=(
                    f"Rate limit hit: this chat has already sent {max_messages} "
                    f"message{'s' if max_messages != 1 else ''} in {window_seconds}s. "
                    f"Try again in {retry_after}s. This protects AI spend and keeps Elevate responsive."
                ),
            )

    usage_enabled, token_cap, token_window = _usage_config(config)
    if usage_enabled and token_cap > 0:
        try:
            from gateway.usage_ledger import sum_recent_tokens

            used_tokens = sum_recent_tokens(
                since=(time.time() if now is None else now) - token_window,
                source=source,
                session_key=session_key,
            )
        except Exception:
            used_tokens = 0
        if used_tokens >= token_cap:
            hours = max(1, round(token_window / 3600))
            return GuardrailDecision(
                allowed=False,
                reason="token_cap_exceeded",
                message=(
                    f"Daily token cap reached for this chat: {used_tokens:,}/{token_cap:,} "
                    f"tokens in the last {hours}h. Start a new chat, raise "
                    "`guardrails.usage.daily_token_cap` in config.yaml, or wait for usage to roll off."
                ),
                used_tokens=used_tokens,
                token_cap=token_cap,
            )

    return GuardrailDecision(allowed=True)


def record_guardrail_block(
    *,
    decision: GuardrailDecision,
    session_id: str | None = None,
    session_key: str | None = None,
    message_id: str | None = None,
    source: str | None = None,
    model: str | None = None,
) -> None:
    """Persist a metadata-only audit row for a blocked turn."""
    if decision.allowed:
        return
    try:
        from gateway.usage_ledger import record_gateway_turn

        record_gateway_turn(
            agent_result={
                "session_id": session_id,
                "status": "blocked",
                "failed": True,
                "error_type": decision.reason,
                "model": model or "",
                "total_tokens": 0,
                "api_calls": 0,
            },
            session_id=session_id,
            session_key=session_key,
            message_id=message_id,
            source=source,
            latency_ms=0,
        )
    except Exception:
        pass
