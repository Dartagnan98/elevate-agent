"""Browser Use cloud browser plugin — DISABLED in Elevate.

Elevate is local-first: the browser tool uses the open-source ``agent-browser``
engine running on the user's own machine (and, on desktops, their real
logged-in Chrome via the visible-browser auto-provision). It never needs the
paid Browser Use *cloud* service.

The cloud provider in ``provider.py`` is the hosted ``browser-use.com`` backend
(``BROWSER_USE_API_KEY``) inherited from the upstream Nous ``hermes-agent``
fork, where Nous resells Browser Use sessions through a managed subscription.
Elevate doesn't use that subscription, so the only thing this provider added
was a confusing second meaning of "Browser Use" and a key prompt users don't
need. We leave the provider class in place (so upstream merges stay clean) but
do NOT register it — the registry simply falls through to local mode.

To re-enable, restore the original ``register`` body that instantiated and
registered ``BrowserUseBrowserProvider``.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Intentionally a no-op. Browser Use cloud is disabled in Elevate.

    See the module docstring. Local mode (``agent-browser`` + the visible
    logged-in Chrome) is the only browser backend Elevate ships.
    """
    return None
