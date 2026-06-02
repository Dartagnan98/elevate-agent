#!/usr/bin/env python3
"""Materialize iCloud "dataless" placeholder files before reading.

On macOS, files in iCloud-managed folders (``~/Documents`` / ``~/Desktop``
when "Desktop & Documents Folders" sync is on) are offloaded to *dataless*
placeholders: ``stat()`` reports the logical size, but the bytes live in the
cloud. Reading one forces a synchronous fault-in through ``fileproviderd``;
when that can't complete in the caller's context the kernel returns
``EDEADLK`` ("Resource deadlock avoided", errno 11) instead of blocking.

This module detects the dataless flag, triggers materialization
(``brctl download``) with a bounded wait, and retries reads once on EDEADLK.
It is a no-op on non-macOS platforms and for files whose data is already
resident, so it is safe to call unconditionally before any local read.
"""
from __future__ import annotations

import errno
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# macOS BSD st_flags bit: file data is not resident (iCloud / File Provider
# placeholder). Defined in <sys/stat.h> as SF_DATALESS.
SF_DATALESS = 0x40000000

_IS_MACOS = sys.platform == "darwin"


class FileNotReadyError(OSError):
    """Raised when an iCloud placeholder could not be materialized in time."""


def is_dataless(path) -> bool:
    """Return True if ``path`` is an offloaded iCloud placeholder (macOS only)."""
    if not _IS_MACOS:
        return False
    try:
        flags = os.stat(path).st_flags
    except (OSError, AttributeError):
        return False
    return bool(flags & SF_DATALESS)


def materialize_if_dataless(path, timeout: float = 10.0, poll: float = 0.25) -> bool:
    """Trigger and await the iCloud download of a dataless file.

    Returns True once the file is resident (or was never dataless / not macOS).
    Raises :class:`FileNotReadyError` if it stays offloaded past ``timeout``.
    """
    if not is_dataless(path):
        return True

    p = str(path)
    logger.info("Materializing iCloud dataless file: %s", p)

    # Best-effort nudge. brctl may be absent or slow; the polling stat below
    # is the real wait. Never fail just because brctl misbehaves.
    try:
        subprocess.run(
            ["brctl", "download", p],
            capture_output=True,
            timeout=max(1.0, timeout),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("brctl download nudge failed (continuing): %s", exc)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_dataless(path):
            return True
        time.sleep(poll)

    if is_dataless(path):
        raise FileNotReadyError(
            errno.EDEADLK,
            f"iCloud file is still offloaded after {timeout:.0f}s "
            f"(could not download from iCloud): {p}",
        )
    return True


def read_bytes_resilient(path, timeout: float = 10.0) -> bytes:
    """Read file bytes, materializing iCloud placeholders and retrying once on EDEADLK."""
    materialize_if_dataless(path, timeout=timeout)
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        if exc.errno == errno.EDEADLK:
            # Materialization raced the read; nudge again and retry once.
            materialize_if_dataless(path, timeout=timeout)
            time.sleep(0.5)
            return Path(path).read_bytes()
        raise
