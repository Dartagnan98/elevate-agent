"""Resolve ELEVATE_HOME for standalone skill scripts.

Skill scripts may run outside the Hermes process (e.g. system Python,
nix env, CI) where ``elevate_constants`` is not importable.  This module
provides the same ``get_elevate_home()`` and ``display_elevate_home()``
contracts as ``elevate_constants`` without requiring it on ``sys.path``.

When ``elevate_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``elevate_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ELEVATE_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from elevate_constants import display_elevate_home as display_elevate_home
    from elevate_constants import get_elevate_home as get_elevate_home
except (ModuleNotFoundError, ImportError):

    def get_elevate_home() -> Path:
        """Return the Hermes home directory (default: ~/.elevate).

        Mirrors ``elevate_constants.get_elevate_home()``."""
        val = os.environ.get("ELEVATE_HOME", "").strip()
        return Path(val) if val else Path.home() / ".hermes"

    def display_elevate_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``elevate_constants.display_elevate_home()``."""
        home = get_elevate_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
