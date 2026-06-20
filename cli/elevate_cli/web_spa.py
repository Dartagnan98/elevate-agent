"""SPA/static mounting for the dashboard web server."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


def mount_spa(
    application,
    *,
    web_dist: Path,
    static_files_class,
    session_token: str,
    embedded_chat_enabled: Callable[[], bool],
) -> None:
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.
    """
    if not web_dist.exists():
        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )
        return

    _index_path = web_dist / "index.html"

    def _serve_index():
        """Return index.html with the session token injected."""
        html = _index_path.read_text()
        chat_js = "true" if embedded_chat_enabled() else "false"
        # transcriptStore (Phase 4) per-box burn-in switch. OFF unless this box
        # sets ELEVATE_TRANSCRIPT_STORE=1 — so it's scoped to a tester's machine
        # and stays inert for every customer until the default is flipped.
        transcript_store_js = (
            "true"
            if os.environ.get("ELEVATE_TRANSCRIPT_STORE", "").strip().lower()
            in ("1", "true", "yes", "on")
            else "false"
        )
        # Force a neutral grey text selection app-wide, injected into <head> so
        # it's always present regardless of which CSS chunk a route loads (some
        # chunks ship their own accent-tinted ::selection; without this the
        # macOS default blue shows through on routes that don't load the global
        # override).
        token_script = (
            f'<script>window.__ELEVATE_SESSION_TOKEN__="{session_token}";'
            f"window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__={chat_js};"
            f"window.__ELEVATE_TRANSCRIPT_STORE__={transcript_store_js};</script>"
            "<style>::selection{background:#5d5d5d !important;color:#fff !important}"
            "::-moz-selection{background:#5d5d5d !important;color:#fff !important}</style>"
        )
        # Inject at the TOP of <head> so the token global is set before the
        # deferred app bundle runs (it sits above this in the built HTML).
        if "<head>" in html:
            html = html.replace("<head>", f"<head>{token_script}", 1)
        else:
            html = html.replace("</head>", f"{token_script}</head>", 1)
        resp = HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
        # Also set the token as a cookie so EVERY same-origin request carries it
        # automatically — even the very first one, before any JS runs. This is
        # what fixes the race where initial /api calls went out token-less and
        # 401'd, latching the UI on a false "signed out" screen.
        resp.set_cookie(
            "elevate_session",
            session_token,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return resp

    application.mount("/assets", static_files_class(directory=web_dist / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "API route not found"}, status_code=404)

        file_path = web_dist / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(web_dist.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            headers = {}
            if full_path.startswith(("fonts/", "ds-assets/")) or re.search(
                r"\.[a-fA-F0-9]{8,}\.",
                file_path.name,
            ):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(file_path, headers=headers)
        return _serve_index()
