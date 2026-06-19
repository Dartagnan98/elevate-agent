"""Dashboard route/nav drift guard."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "cli/web/src/App.tsx"
PATH_RE = re.compile(r'(?:path|to):\s*"(?P<path>/[^"?]*)"')
KEY_RE = re.compile(r'"(?P<path>/[^"]*)"\s*:')


def _read_app() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _balanced_block(source: str, start: int, opener: str, closer: str) -> str:
    depth = 0
    for idx in range(start, len(source)):
        char = source[idx]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return source[start : idx + 1]
    raise AssertionError(f"unterminated block starting at {start}")


def _const_block(source: str, name: str) -> str:
    marker = f"const {name}"
    start = source.index(marker)
    openers = [
        (source.index("{", start), "{", "}"),
        (source.index("[", start), "[", "]"),
    ]
    block_start, opener, closer = min(openers)
    return _balanced_block(source, block_start, opener, closer)


def _object_keys(source: str, name: str) -> set[str]:
    return set(KEY_RE.findall(_const_block(source, name)))


def _paths(source: str, block: str) -> set[str]:
    return {match.group("path") for match in PATH_RE.finditer(block)}


def _access_routes(source: str) -> set[str]:
    start = source.index("function buildAccessControlledBuiltinRoutes")
    return_start = source.index("return {", start) + len("return ")
    return set(KEY_RE.findall(_balanced_block(source, return_start, "{", "}")))


def test_dashboard_nav_routes_are_mounted_and_preloaded():
    app = _read_app()

    preloaded = _object_keys(app, "ROUTE_PRELOADERS")
    mounted = _object_keys(app, "BUILTIN_ROUTES_BASE") | _access_routes(app)
    nav_paths = (
        _paths(app, _const_block(app, "CHAT_NAV_ITEM"))
        | _paths(app, _const_block(app, "BUILTIN_NAV_REST"))
        | _paths(
            app,
            app[
                app.index("const agentPrimaryNavItems") : app.index(
                    "const realEstateNavItems"
                )
            ],
        )
    )

    redirect_aliases = {"/", "/listings", "/deals", "/marketing"}

    assert nav_paths <= mounted
    assert nav_paths <= preloaded
    assert preloaded <= mounted
    assert (mounted - redirect_aliases) <= preloaded


def test_dashboard_redirect_aliases_have_preload_targets():
    app = _read_app()

    assert 'if (base === "/marketing") return "/social-media";' in app
    assert 'if (base === "/listings" || base === "/deals") return "/admin";' in app
