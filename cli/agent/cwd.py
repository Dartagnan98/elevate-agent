"""Cwd helpers resilient to a deleted process working directory."""

from __future__ import annotations

import os


def safe_getcwd() -> str:
    """Return a usable cwd even when the process cwd was deleted.

    Long-lived desktop/gateway processes can outlive the folder they were
    launched from. In that state ``os.getcwd()`` raises ``FileNotFoundError``.
    Fall back to TERMINAL_CWD, then the user's home, then ``/``.
    """
    try:
        return os.getcwd()
    except (FileNotFoundError, OSError):
        for candidate in (os.getenv("TERMINAL_CWD"), os.path.expanduser("~")):
            if not candidate:
                continue
            try:
                if os.path.isdir(candidate):
                    return candidate
            except OSError:
                continue
        return "/"


def safe_abspath(path: str) -> str:
    """Like ``abspath`` without calling raw ``getcwd`` for relative paths."""
    expanded = os.path.expanduser(str(path))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    return os.path.normpath(os.path.join(safe_getcwd(), expanded))


def safe_realpath(path: str) -> str:
    """Like ``realpath`` but safe when cwd is missing and path is relative."""
    return os.path.realpath(safe_abspath(path))
