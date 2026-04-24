"""Shared helpers for direct xAI HTTP integrations."""

from __future__ import annotations


def elevate_xai_user_agent() -> str:
    """Return a stable Elevate-specific User-Agent for xAI HTTP calls."""
    try:
        from elevate_cli import __version__
    except Exception:
        __version__ = "unknown"
    return f"Elevate/{__version__}"
