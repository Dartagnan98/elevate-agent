"""Best-effort cloud upload for sanitized session recorder events."""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any


_FALSE_VALUES = {"0", "false", "no", "off"}
_MAX_QUEUE = 1000
_BATCH_SIZE = 50
_FLUSH_INTERVAL_SECONDS = 1.0
_QUEUE: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=_MAX_QUEUE)
_STARTED = False
_LOCK = threading.Lock()


def uploader_enabled() -> bool:
    value = os.getenv("ELEVATE_SESSION_RECORDER_UPLOAD", "0").strip().lower()
    return value not in _FALSE_VALUES


def queue_session_event(event: dict[str, Any]) -> None:
    """Queue one already-sanitized recorder envelope for cloud upload."""
    if not uploader_enabled() or not isinstance(event, dict):
        return
    try:
        from elevate_cli import license as elevate_license

        if elevate_license.load() is None:
            return
    except Exception:
        return
    _ensure_worker()
    try:
        _QUEUE.put_nowait(event)
    except queue.Full:
        # Local JSONL remains the durable copy; cloud upload is best-effort.
        pass


def _ensure_worker() -> None:
    global _STARTED
    if _STARTED:
        return
    with _LOCK:
        if _STARTED:
            return
        threading.Thread(
            target=_worker,
            name="session-recorder-uploader",
            daemon=True,
        ).start()
        _STARTED = True


def _worker() -> None:
    while True:
        try:
            first = _QUEUE.get()
        except Exception:
            time.sleep(_FLUSH_INTERVAL_SECONDS)
            continue
        batch = [first]
        deadline = time.monotonic() + _FLUSH_INTERVAL_SECONDS
        while len(batch) < _BATCH_SIZE:
            timeout = max(0.0, deadline - time.monotonic())
            if timeout <= 0:
                break
            try:
                batch.append(_QUEUE.get(timeout=timeout))
            except queue.Empty:
                break
        _upload_batch(batch)


def _upload_batch(events: list[dict[str, Any]]) -> bool:
    if not events:
        return True
    try:
        import httpx
        from elevate_cli import license as elevate_license

        lic = elevate_license.ensure_valid()
        with httpx.Client(
            base_url=elevate_license.backend_url(),
            timeout=5.0,
            headers={"user-agent": "elevate-cli/0.11"},
        ) as client:
            resp = client.post(
                "/api/diagnostics/session-events",
                headers={"authorization": f"Bearer {lic.access_token}"},
                json={"events": events[:_BATCH_SIZE]},
            )
        return bool(resp.is_success)
    except Exception:
        return False
