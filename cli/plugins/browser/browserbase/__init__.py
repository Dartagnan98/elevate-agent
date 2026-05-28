"""Browserbase cloud browser plugin — DISABLED in Elevate.

Elevate is local-first: the browser tool uses the open-source ``agent-browser``
engine on the user's own machine (and, on desktops, their real logged-in Chrome
via the visible-browser auto-provision). Browserbase is a paid remote cloud
browser inherited from the upstream Nous ``hermes-agent`` fork; it was never
used here and only added another cloud option to the picker.

We leave ``provider.py`` in place (so upstream merges stay clean) but do NOT
register it — the registry simply falls through to local mode. To re-enable,
restore the ``register`` body that instantiated ``BrowserbaseBrowserProvider``.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Intentionally a no-op. Browserbase is disabled in Elevate (local-first)."""
    return None
