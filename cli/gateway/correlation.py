"""Opaque, privacy-safe lineage for externally accepted gateway work.

Correlation identifiers are deliberately generated independently from platform
message IDs, chat IDs, session labels, idempotency keys, prompts, and customer
data.  External callers may continue a trace only by supplying an identifier in
the canonical opaque format; every other value is replaced with a new root.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator, Optional


CORRELATION_HEADER = "X-Elevate-Correlation-Id"
EXECUTION_CORRELATION_HEADER = "X-Elevate-Execution-Correlation-Id"

_CORRELATION_RE = re.compile(r"^corr_[0-9a-f]{32}$")
_ATTEMPT_RE = re.compile(r"^attempt_[0-9a-f]{32}$")
# These formats are minted by Elevate itself. Deliberately exclude gateway
# session keys (which embed platform/chat/user labels), caller-provided API
# session strings, and content-derived ``api-<hash>`` conversation IDs.
_INTERNAL_SESSION_RE = re.compile(
    r"^(?:"
    r"[0-9]{8}_[0-9]{6}_[0-9a-f]{6,8}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|run_[0-9a-f]{32}"
    r")$"
)
_INTERNAL_TASK_RE = re.compile(r"^dt_[0-9a-f]{8}$")
_ALLOWED_RELATIONS = frozenset(
    {
        "delivery_attempt",
        "retry_of",
        "delegate_result",
        "duplicate_of",
    }
)

_CURRENT_CORRELATION_ID: ContextVar[str] = ContextVar(
    "ELEVATE_GATEWAY_CORRELATION_ID", default=""
)
_CURRENT_CORRELATION_SESSION_ID: ContextVar[str] = ContextVar(
    "ELEVATE_GATEWAY_CORRELATION_SESSION_ID", default=""
)


def is_opaque_correlation_id(value: Any) -> bool:
    """Return True only for canonical externally reusable root IDs."""
    return isinstance(value, str) and bool(_CORRELATION_RE.fullmatch(value))


def is_lineage_id(value: Any) -> bool:
    """Return True for a canonical root or one-shot delivery attempt ID."""
    return isinstance(value, str) and bool(
        _CORRELATION_RE.fullmatch(value) or _ATTEMPT_RE.fullmatch(value)
    )


def is_opaque_internal_session_id(value: Any) -> bool:
    """Return True only for session IDs minted by Elevate, never routing keys."""
    return isinstance(value, str) and bool(_INTERNAL_SESSION_RE.fullmatch(value))


def is_opaque_internal_task_id(value: Any) -> bool:
    """Return True only for opaque async-delegation dispatch IDs."""
    return isinstance(value, str) and bool(_INTERNAL_TASK_RE.fullmatch(value))


def mint_correlation_id() -> str:
    return f"corr_{uuid.uuid4().hex}"


def mint_attempt_id() -> str:
    return f"attempt_{uuid.uuid4().hex}"


def accept_external_correlation_id(value: Any = None) -> str:
    """Validate an opaque caller root or mint a replacement.

    Never hashes or embeds the rejected value: even a digest can become a
    stable customer-data join key, which is unnecessary for execution lineage.
    """
    return value if is_opaque_correlation_id(value) else mint_correlation_id()


def current_correlation_id() -> str:
    return _CURRENT_CORRELATION_ID.get()


def current_correlation_session_id() -> str:
    return _CURRENT_CORRELATION_SESSION_ID.get()


def bind_correlation(
    correlation_id: str, session_id: Optional[str] = None
) -> tuple[Token, Token]:
    """Bind already-validated lineage to the current async/thread context."""
    root = correlation_id if is_opaque_correlation_id(correlation_id) else mint_correlation_id()
    return (
        _CURRENT_CORRELATION_ID.set(root),
        _CURRENT_CORRELATION_SESSION_ID.set(
            str(session_id) if is_opaque_internal_session_id(session_id) else ""
        ),
    )


def reset_correlation(tokens: tuple[Token, Token]) -> None:
    try:
        _CURRENT_CORRELATION_ID.reset(tokens[0])
    finally:
        _CURRENT_CORRELATION_SESSION_ID.reset(tokens[1])


@contextmanager
def correlation_scope(
    correlation_id: str, session_id: Optional[str] = None
) -> Iterator[str]:
    tokens = bind_correlation(correlation_id, session_id)
    try:
        yield current_correlation_id()
    finally:
        reset_correlation(tokens)


def record_correlation_event(
    event_type: str,
    *,
    correlation_id: str,
    session_id: Optional[str] = None,
    parent_correlation_id: Optional[str] = None,
    relation: Optional[str] = None,
    status: Optional[str] = None,
    source: str = "gateway",
    component: str = "gateway.external",
    severity: str = "info",
    success: Optional[bool] = None,
    failed: Optional[bool] = None,
    attempt_count: Optional[int] = None,
    retry_count: Optional[int] = None,
    task_id: Optional[str] = None,
) -> bool:
    """Write a content-free lineage breadcrumb, best effort.

    Both IDs and relations are revalidated here so an unsafe boundary caller
    cannot smuggle a semantic label into the diagnostics recorder.
    """
    if not is_lineage_id(correlation_id):
        return False

    payload: dict[str, Any] = {}
    if parent_correlation_id and is_lineage_id(parent_correlation_id):
        payload["parent_correlation_id"] = parent_correlation_id
    if relation in _ALLOWED_RELATIONS:
        payload["relation"] = relation
    if status:
        payload["status"] = str(status)
    if success is not None:
        payload["success"] = bool(success)
    if failed is not None:
        payload["failed"] = bool(failed)
    if isinstance(attempt_count, int) and not isinstance(attempt_count, bool):
        payload["attempt_count"] = attempt_count
    if isinstance(retry_count, int) and not isinstance(retry_count, bool):
        payload["retry_count"] = retry_count

    try:
        from elevate_cli.diagnostics.session_recorder import record_session_event

        recorder_kwargs: dict[str, Any] = {
            "payload": payload,
            "severity": severity,
            "source": source,
            "component": component,
            "correlation_id": correlation_id,
        }
        if is_opaque_internal_session_id(session_id):
            recorder_kwargs["session_id"] = str(session_id)
        if is_opaque_internal_task_id(task_id):
            recorder_kwargs["task_id"] = str(task_id)
        return bool(record_session_event(event_type, **recorder_kwargs))
    except Exception:
        return False
