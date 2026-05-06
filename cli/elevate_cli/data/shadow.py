"""Shadow-read wrapper for the Sprint 2 cutover.

During Sprint 2 we move endpoints from JSONL-derived reads to
operational.db-derived reads. The cutover is gated on a window of
shadow-mode requests showing zero diffs between the two paths.

The wrapper here calls both the legacy and the new read function on
every request, records a :func:`elevate_cli.data.parity.record_parity_snapshot`,
and returns either the legacy or the db result depending on which is
the configured primary. The default primary stays "legacy" until the
3-day clean window has passed in production.

Knobs:

* ``ELEVATE_DATA_SHADOW_READ=1`` (default off): when off, only the
  configured primary runs — the wrapper is a passthrough with no parity
  recording. Off is the production default until Sprint 2 starts.
* ``ELEVATE_DATA_SHADOW_READ=fail-soft`` (default behavior when the flag
  is truthy): if the secondary path raises, log it, swallow it, return
  the primary result. The shadow path must not be able to break a live
  endpoint.
* ``ELEVATE_DATA_SHADOW_READ=fail-loud``: re-raise secondary exceptions.
  Useful in tests / staging.
* ``ELEVATE_DATA_PRIMARY=db``: flip the wrapper to return the db_fn
  result instead of the jsonl_fn result. This is the cutover knob —
  enabled only after a clean parity window. Defaults to ``jsonl``
  (legacy).
* ``ELEVATE_DATA_FALLBACK=jsonl``: emergency rollback. When the primary
  is ``db`` and this is set, fall back to legacy on any db_fn error
  without restarting the process. Off by default — set it before
  flipping the primary so you have a safety net.

Sprint 1D shipped the wrapper and the parity-report CLI with
``db_fn=None`` placeholders; Sprint 2 fills the db_fn slots and adds
the primary/fallback flags. The actual flip remains a deliberate
operator action gated on a clean parity window.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, TypeVar

from elevate_cli.data.connection import connect
from elevate_cli.data.parity import record_parity_snapshot


_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")

_SHADOW_ENV = "ELEVATE_DATA_SHADOW_READ"
_PRIMARY_ENV = "ELEVATE_DATA_PRIMARY"
_FALLBACK_ENV = "ELEVATE_DATA_FALLBACK"


def shadow_read_enabled() -> bool:
    """True iff the env flag is set to a truthy value (``1``/``true``/
    ``fail-soft``/``fail-loud``). Off by default so production stays
    on the legacy code path until Sprint 2 cutover."""
    val = os.environ.get(_SHADOW_ENV, "").strip().lower()
    return val not in ("", "0", "false", "off", "no")


def _fail_loud() -> bool:
    return os.environ.get(_SHADOW_ENV, "").strip().lower() == "fail-loud"


def data_primary_is_db() -> bool:
    """True when ``ELEVATE_DATA_PRIMARY=db`` — the wrapper should
    return the db_fn result instead of the legacy jsonl_fn result.

    Defaults to False so the cutover stays a deliberate operator action.
    """
    return os.environ.get(_PRIMARY_ENV, "").strip().lower() == "db"


def _fallback_to_jsonl() -> bool:
    """True when ``ELEVATE_DATA_FALLBACK=jsonl`` — emergency rollback
    knob. When primary=db and the db_fn errors, fall back to legacy
    rather than 500-ing the live endpoint. Off by default so silent
    fallbacks don't mask real bugs in staging."""
    return os.environ.get(_FALLBACK_ENV, "").strip().lower() == "jsonl"


def shadow_read(
    *,
    endpoint: str,
    request_args: Any,
    jsonl_fn: Callable[[], _T],
    db_fn: Callable[[], Any] | None,
) -> _T:
    """Run both the legacy and db read paths (depending on flags),
    record a parity snapshot when both succeed, and return whichever
    one is the configured primary.

    Behavior matrix:

    * shadow off, primary=jsonl  → return ``jsonl_fn()`` only. No db call.
    * shadow off, primary=db     → return ``db_fn()`` only. No jsonl call.
    * shadow on,  primary=jsonl  → run both, record parity, return jsonl.
    * shadow on,  primary=db     → run both, record parity, return db.

    ``db_fn=None`` collapses every case to "return jsonl_fn()" — kept
    valid so endpoints can be wired before their db read path lands.
    """
    primary_is_db = data_primary_is_db()
    shadow_on = shadow_read_enabled()

    # If db_fn isn't wired we can't run anything but legacy.
    if db_fn is None:
        return jsonl_fn()

    # Shadow off: only run the configured primary.
    if not shadow_on:
        if primary_is_db:
            try:
                return db_fn()  # type: ignore[return-value]
            except Exception:
                if _fallback_to_jsonl():
                    _LOG.exception(
                        "shadow_read: db_fn raised on endpoint=%r and "
                        "primary=db; ELEVATE_DATA_FALLBACK=jsonl is set, "
                        "falling back to legacy.",
                        endpoint,
                    )
                    return jsonl_fn()
                raise
        return jsonl_fn()

    # Shadow on: run both, record parity, return primary.
    legacy_result: Any = None
    legacy_err: BaseException | None = None
    try:
        legacy_result = jsonl_fn()
    except Exception as exc:
        legacy_err = exc
        if not primary_is_db:
            # legacy is what we'd return — let the caller see the real error.
            raise

    db_result: Any = None
    db_err: BaseException | None = None
    try:
        db_result = db_fn()
    except Exception as exc:
        db_err = exc
        _LOG.exception(
            "shadow_read: db_fn raised on endpoint=%r — primary=%s, "
            "ELEVATE_DATA_SHADOW_READ=%s.",
            endpoint,
            "db" if primary_is_db else "jsonl",
            os.environ.get(_SHADOW_ENV, ""),
        )
        if _fail_loud():
            raise
        if primary_is_db:
            if _fallback_to_jsonl() and legacy_err is None:
                return legacy_result
            raise

    # Record a parity snapshot only when both sides produced a value.
    if legacy_err is None and db_err is None:
        try:
            with connect() as conn:
                record_parity_snapshot(
                    conn,
                    endpoint=endpoint,
                    request_args=request_args,
                    jsonl_response=legacy_result,
                    db_response=db_result,
                )
        except Exception:
            _LOG.exception(
                "shadow_read: failed to persist parity snapshot for endpoint=%r",
                endpoint,
            )
            if _fail_loud():
                raise

    return db_result if primary_is_db else legacy_result
