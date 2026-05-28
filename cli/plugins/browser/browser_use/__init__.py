"""Browser Use browser plugin — managed Nous gateway only.

Elevate is local-first: the browser tool uses the open-source ``agent-browser``
engine on the user's own machine (and, on desktops, their real logged-in Chrome
via the visible-browser auto-provision). The direct, self-billed Browser Use
*cloud* (``BROWSER_USE_API_KEY``) was removed to avoid confusing it with the
local open-source engine of the same name.

What remains is the **managed Nous gateway** path: Nous subscribers can still
have Browser Use sessions billed to their subscription. The provider only
activates when that managed gateway is configured — see
``provider.py::_get_config_or_none`` (the direct-API-key branch is gone).
"""

from __future__ import annotations

from plugins.browser.browser_use.provider import BrowserUseBrowserProvider


def register(ctx) -> None:
    """Register the Browser Use provider (managed Nous gateway path only)."""
    ctx.register_browser_provider(BrowserUseBrowserProvider())
