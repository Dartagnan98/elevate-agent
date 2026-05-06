"""Filesystem layout for the central data store.

All paths resolve under ``ELEVATE_HOME`` (default ``~/.elevate``). The
``ELEVATE_HOME`` env var is the single override knob — tests and Docker
profiles set it to redirect the whole tree.

Layout::

    $ELEVATE_HOME/
        data/
            operational.db          # central SQLite store (Sprint 1+)
            operational.db-wal      # WAL sidecar
            operational.db-shm      # SHM sidecar
            payloads/               # spillover for events.payload_json > 16KB
            backups/                # pre-migration snapshots, retention 30 days
            parity/                 # shadow-read parity diff dumps (Sprint 2)
"""

from __future__ import annotations

from pathlib import Path

from elevate_constants import get_elevate_home


def data_root() -> Path:
    """Root of the central data store. Created on first call."""
    root = get_elevate_home() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def operational_db_path() -> Path:
    """Path to ``operational.db``. Parent dir is created if missing."""
    return data_root() / "operational.db"


def payloads_root() -> Path:
    """Spillover dir for ``events.payload_json`` rows over 16KB."""
    root = data_root() / "payloads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def backups_root() -> Path:
    """Pre-migration backup dir. ``migrate-data`` writes a snapshot here
    before mutating the store, retention is 30 days (Sprint 1E)."""
    root = data_root() / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def parity_root() -> Path:
    """Per-request parity diff dumps written during shadow-read (Sprint 2)."""
    root = data_root() / "parity"
    root.mkdir(parents=True, exist_ok=True)
    return root
