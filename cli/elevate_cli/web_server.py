"""
Elevate — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m elevate_cli.main web          # Start on http://127.0.0.1:9119
    python -m elevate_cli.main web --port 8080
"""

import asyncio
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _init_workspace_root() -> Path:
    """The user folder the agent works out of and that the workspace panel
    opens / shows status for.

    Defaults to PROJECT_ROOT (a dev checkout, which is itself a git repo). The
    desktop app sets ELEVATE_WORKSPACE to a dedicated folder (e.g. ~/Elevation)
    so the packaged agent never treats its own read-only bundled code as the
    workspace. We git-init the folder so the workspace panel / Review / Create
    PR work instead of throwing a raw git error on a plain directory.
    """
    raw = os.environ.get("ELEVATE_WORKSPACE", "").strip()
    if not raw:
        return PROJECT_ROOT
    try:
        root = Path(raw).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").exists():
            subprocess.run(
                ["git", "init"],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        return root
    except Exception:
        return PROJECT_ROOT


WORKSPACE_ROOT = _init_workspace_root()


def _is_packaged_desktop_runtime() -> bool:
    """True when this API is running from the immutable Electron app bundle."""
    if os.environ.get("ELEVATE_DESKTOP_APP") == "1":
        return True
    parts = PROJECT_ROOT.parts
    return (
        any(part.endswith(".app") for part in parts)
        and "Contents" in parts
        and "Resources" in parts
    )

from elevate_cli import __version__, __release_date__
from elevate_cli.config import (
    DEFAULT_CONFIG,
    get_elevate_home,
    get_env_value,
    load_config,
    load_env,
    save_config,
    save_env_value,
)
try:
    from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError:
    raise SystemExit(
        "Web UI requires fastapi and uvicorn.\n"
        f"Install with: {sys.executable} -m pip install 'fastapi' 'uvicorn[standard]'"
    )

WEB_DIST = Path(os.environ["ELEVATE_WEB_DIST"]) if "ELEVATE_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

# ── Shared SessionDB ──────────────────────────────────────────────────
# SessionDB was previously constructed per request at ~15 call sites; each
# construction opens a fresh SQLite connection and runs _init_schema(). The
# class is safe to share across the uvicorn threadpool (check_same_thread=False
# + an internal lock serializing every op — see elevate_state.SessionDB.__init__),
# so we cache one instance process-wide. If the first open fails we leave the
# singleton unset so the next call retries (matches the old per-request retry).
_SESSION_DB_SINGLETON = None
_SESSION_DB_SINGLETON_LOCK = threading.Lock()


class _SharedSessionDB:
    """Per-request handle over the process-wide SessionDB.

    The ~15 call sites construct a SessionDB then ``db.close()`` it in a
    ``finally`` block. Against a shared instance that close would tear down the
    connection for every other request, so this proxy makes ``close()`` a no-op
    and forwards everything else to the real shared instance (which has its own
    lock + check_same_thread=False, so concurrent use is safe).
    """

    __slots__ = ("_db",)

    def __init__(self, db):
        object.__setattr__(self, "_db", db)

    def close(self):  # shared instance lives for the process — do not close
        return None

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_db"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_db"), name, value)


def _get_session_db():
    """Return a handle over the process-wide shared SessionDB.

    Built once and reused. The state.db path (elevate_state.DEFAULT_DB_PATH) is
    fixed at import in production, so the singleton is stable there; but if it
    ever changes (tests patch it per-case, and a future runtime relocation would
    too) we rebuild against the new path rather than serve a stale handle.
    """
    global _SESSION_DB_SINGLETON
    from elevate_state import SessionDB
    import elevate_state as _es
    target_path = _es.DEFAULT_DB_PATH
    db = _SESSION_DB_SINGLETON
    if db is None or getattr(db, "db_path", None) != target_path:
        with _SESSION_DB_SINGLETON_LOCK:
            db = _SESSION_DB_SINGLETON
            if db is None or getattr(db, "db_path", None) != target_path:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                _SESSION_DB_SINGLETON = SessionDB()
            db = _SESSION_DB_SINGLETON
    return _SharedSessionDB(db)


# ── Account-scoped TTL cache for filesystem-scan endpoints ────────────
# Some read endpoints (activity feed, heartbeat surfaces) walk the account
# data dir and parse dozens of JSON files on every request. Cache the computed
# result per account for a short TTL so rapid polling collapses to one scan.
# Keyed on the account key so one account never serves another's data. The TTL
# is short (seconds) and acts as a backstop: even a mutation we forget to
# invalidate self-heals within the TTL.
import time as _time  # noqa: E402

_FS_SCAN_CACHE: dict = {}
_FS_SCAN_CACHE_LOCK = threading.Lock()


def _account_key_safe() -> str:
    try:
        from elevate_constants import get_account_key

        return get_account_key()
    except Exception:
        return "_default"


def _fs_cache_get(name: str):
    """Return cached value for (current account, name) if still fresh, else None."""
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        ent = _FS_SCAN_CACHE.get(key)
        if ent is not None and ent[0] > _time.monotonic():
            return ent[1]
    return None


def _fs_cache_put(name: str, value, ttl_seconds: float) -> None:
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        _FS_SCAN_CACHE[key] = (_time.monotonic() + ttl_seconds, value)


def _fs_cache_invalidate(name: str) -> None:
    """Drop the current account's cached entry for ``name`` (call after a mutation)."""
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        _FS_SCAN_CACHE.pop(key, None)


app = FastAPI(
    title="Elevate",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
)


class ImmutableStaticFiles(StaticFiles):
    """StaticFiles variant for hashed Vite assets."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Persisted at ~/.elevate/dashboard-session-token (0600) so it stays STABLE
# across dashboard restarts. The desktop dashboard restarts once at startup
# (to enable embedded chat); a fresh-per-process token would leave the already-
# loaded Electron renderer holding a stale token -> every API call 401s ->
# false "Unauthorized" screen. A stable token keeps the renderer's injected
# token valid across restarts (and even if the SPA HTML is cached). Local-only
# (127.0.0.1) API, same trust level as license.json next to it. Override with
# ELEVATE_DASHBOARD_SESSION_TOKEN.
# ---------------------------------------------------------------------------
def _load_session_token() -> str:
    env = os.environ.get("ELEVATE_DASHBOARD_SESSION_TOKEN")
    if env:
        return env.strip()
    try:
        path = os.path.join(os.path.expanduser("~"), ".elevate", "dashboard-session-token")
        if os.path.exists(path):
            existing = open(path, encoding="utf-8").read().strip()
            if existing:
                return existing
        token = secrets.token_urlsafe(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.chmod(path, 0o600)
        return token
    except Exception:
        return secrets.token_urlsafe(32)


_SESSION_TOKEN = _load_session_token()
_SESSION_HEADER_NAME = "X-Elevate-Session-Token"
_RUN_TOKEN_HEADER_NAME = "X-Elevate-Run-Token"
_RUN_RESULT_PATH_RE = re.compile(r"^/api/deals/([^/]+)/runs/([^/]+)/result$")
_REQUEST_ID_HEADER_NAME = "X-Request-Id"
_SESSION_ID_HEADER_NAMES = ("X-Elevate-Session-Id", "X-Session-Id")
_REQUEST_SESSION_PATH_RE = re.compile(r"^/api/(?:sessions|uploads)/([^/]+)")
_LOG_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.:-]+")

# In-browser Chat tab (/chat, /api/pty, …).  Off unless ``elevate dashboard --tui``
# or ELEVATE_DASHBOARD_TUI=1.  Set from :func:`start_server`.
_DASHBOARD_EMBEDDED_CHAT_ENABLED = False


# ---------------------------------------------------------------------------
# Elevation Real Estate HQ sign-in gate.
#
# The chat refuses to start until ``~/.elevate/license.json`` exists with a
# non-expired access token. This is the same file ``elevate_cli/license.py``
# writes after ``elevate activate`` or the desktop app's IPC login. We do the
# check inline (no import of license.py) so we avoid a circular import.
# ---------------------------------------------------------------------------

_LICENSE_PATH = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate") / "license.json"
_SIGN_IN_URL = (
    os.environ.get("ELEVATE_BACKEND_URL", "https://api.elevationrealestatehq.com").rstrip("/")
    + "/login"
)


def _license_signed_in() -> bool:
    """Return True iff a license.json with an unexpired access token exists."""
    try:
        with _LICENSE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False

    token = data.get("access_token")
    expires_at = data.get("expires_at")
    if not token or not isinstance(expires_at, (int, float)):
        return False
    # 30s of slack so we don't flap right at the boundary; the desktop and CLI
    # both refresh well before this triggers in practice.
    return float(expires_at) > (time.time() + 30)

# CORS: restrict to localhost origins only.  The web UI is intended to run
# locally; binding to 0.0.0.0 with allow_origins=["*"] would let any website
# read/modify config and secrets.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress large JSON/text responses for clients that send Accept-Encoding: gzip.
# Starlette's GZipMiddleware excludes text/event-stream by default
# (DEFAULT_EXCLUDED_CONTENT_TYPES), so SSE token-streaming keeps flushing
# uncompressed. minimum_size skips tiny payloads; a modest compresslevel keeps
# CPU low (the dashboard is usually loopback, so this mainly trims large lists).
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# ---------------------------------------------------------------------------
# Endpoints that do NOT require the session token.  Everything else under
# /api/ is gated by the auth middleware below.  Keep this list minimal —
# only truly non-sensitive, read-only endpoints belong here.
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
    "/api/redoc",
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
    # /api/dashboard/plugins/rescan mutates the plugin cache and stays authenticated.
})


def _has_valid_session_token(request: Request) -> bool:
    """True if the request carries a valid dashboard session token.

    The dedicated session header avoids collisions with reverse proxies that
    already use ``Authorization`` (for example Caddy ``basic_auth``). We still
    accept the legacy Bearer path for backward compatibility with older
    dashboard bundles.
    """
    session_header = request.headers.get(_SESSION_HEADER_NAME, "")
    if session_header and hmac.compare_digest(
        session_header.encode(),
        _SESSION_TOKEN.encode(),
    ):
        return True

    # Cookie path: set when serving the SPA, so the browser auto-sends it with
    # every same-origin /api request regardless of JS-token-injection timing.
    cookie_tok = request.cookies.get("elevate_session", "")
    if cookie_tok and hmac.compare_digest(
        cookie_tok.encode(),
        _SESSION_TOKEN.encode(),
    ):
        return True

    auth = request.headers.get("authorization", "")
    expected = f"Bearer {_SESSION_TOKEN}"
    return hmac.compare_digest(auth.encode(), expected.encode())


def _has_valid_run_token(request: Request) -> bool:
    match = _RUN_RESULT_PATH_RE.match(request.url.path)
    if not match:
        return False
    deal_id, run_id = match.groups()
    token = request.headers.get(_RUN_TOKEN_HEADER_NAME, "").strip()
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return False
    try:
        from elevate_cli.data import connect, verify_action_run_token

        with connect() as conn:
            return verify_action_run_token(
                conn,
                deal_id=deal_id,
                run_id=run_id,
                token=token,
            )
    except Exception:
        return False


def _require_token(request: Request) -> None:
    """Validate the ephemeral session token.  Raises 401 on mismatch."""
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to.

    Accepts:
    - Exact bound host (with or without port suffix)
    - Loopback aliases when bound to loopback
    - Any host when bound to 0.0.0.0 (explicit opt-in to non-loopback,
      no protection possible at this layer)
    """
    if not host_header:
        return False
    # Strip port suffix. IPv6 addresses use bracket notation:
    #   [::1]         — no port
    #   [::1]:9119    — with port
    # Plain hosts/v4:
    #   localhost:9119
    #   127.0.0.1:9119
    h = host_header.strip()
    if h.startswith("["):
        # IPv6 bracketed — port (if any) follows "]:"
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]  # strip brackets
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    # 0.0.0.0 bind means operator explicitly opted into all-interfaces
    # (requires --insecure per web_server.start_server). No Host-layer
    # defence can protect that mode; rely on operator network controls.
    if bound_host in ("0.0.0.0", "::"):
        return True

    # Loopback bind: accept the loopback names
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES

    # Explicit non-loopback bind: require exact host match
    return host_only == bound_lc


def _safe_log_token(value: object, *, max_len: int = 96) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return _LOG_TOKEN_RE.sub("_", text)[:max_len] or "-"


def _request_id_for_log(request: Request) -> str:
    incoming = _safe_log_token(request.headers.get(_REQUEST_ID_HEADER_NAME), max_len=96)
    return incoming if incoming != "-" else secrets.token_hex(8)


def _session_id_for_log(request: Request) -> str:
    for header in _SESSION_ID_HEADER_NAMES:
        candidate = _safe_log_token(request.headers.get(header), max_len=140)
        if candidate != "-":
            return candidate
    match = _REQUEST_SESSION_PATH_RE.match(request.url.path)
    if match:
        return _safe_log_token(urllib.parse.unquote(match.group(1)), max_len=140)
    return "-"


@app.middleware("http")
async def host_header_middleware(request: Request, call_next):
    """Reject requests whose Host header doesn't match the bound interface.

    Defends against DNS rebinding: a victim browser on a localhost
    dashboard is tricked into fetching from an attacker hostname that
    TTL-flips to 127.0.0.1. CORS and same-origin checks don't help —
    the browser now treats the attacker origin as same-origin with the
    dashboard. Host-header validation at the app layer catches it.

    See GHSA-ppp5-vxwm-4cf7.
    """
    # Store the bound host on app.state so this middleware can read it —
    # set by start_server() at listen time.
    bound_host = getattr(app.state, "bound_host", None)
    if bound_host:
        host_header = request.headers.get("host", "")
        if not _is_accepted_host(host_header, bound_host):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "Invalid Host header. Dashboard requests must use "
                        "the hostname the server was bound to."
                    ),
                },
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require the session token on all /api/ routes except the public list."""
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        if not (_has_valid_session_token(request) or _has_valid_run_token(request)):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
    return await call_next(request)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = _request_id_for_log(request)
    session_id = _session_id_for_log(request)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _log.exception(
            "request failed request_id=%s session_id=%s method=%s path=%s elapsed_ms=%.1f",
            request_id,
            session_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers[_REQUEST_ID_HEADER_NAME] = request_id
    _log.info(
        "request complete request_id=%s session_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
        request_id,
        session_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Default model (e.g. anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "singularity"],
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        "options": ["local", "openai", "mistral"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "dashboard.theme": {
        "type": "select",
        "description": "Web dashboard visual theme",
        "options": ["default", "midnight", "ember", "mono", "cyberpunk", "rose"],
    },
    "sources.tools_root": {
        "type": "string",
        "description": "Customer tools root containing data/sources/<source-id>",
        "category": "sources",
    },
    "integrations.tools_root": {
        "type": "string",
        "description": "Legacy alias for customer tools root; sources.tools_root takes precedence",
        "category": "integrations",
    },
    "integrations.crm.provider": {
        "type": "select",
        "description": "CRM provider preset",
        "options": ["custom", "lofty", "follow_up_boss", "kvcore", "chime", "wise_agent", "real_geeks"],
        "category": "integrations",
    },
    "integrations.crm.auth_type": {
        "type": "select",
        "description": "CRM API authentication placement",
        "options": ["header", "query"],
        "category": "integrations",
    },
    "agent_hub.default_agent": {
        "type": "string",
        "description": "Default Agent Hub persona for new local chat sessions",
        "category": "agent_hub",
    },
    "agent_hub.agents": {
        # NOTE: agent definitions are authoritative in the per-account DB
        # (hub_agents, migration 0026). config.yaml's copy is a frozen
        # one-shot-import archive — edits here are inert on read. Manage
        # agents via /api/agent-hub/agents. Kept in the schema for back-compat.
        "type": "json",
        "description": "Agent Hub personas/orchestration metadata (read-only archive; manage via Agent Hub)",
        "category": "agent_hub",
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["queue", "interrupt", "block"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["", "builtin", "holographic", "honcho", "openviking", "mem0", "hindsight", "retaindb", "byterover"],
    },
    "plugins.elevate-memory-store.db_path": {
        "type": "string",
        "description": "Holographic memory SQLite database path",
        "category": "memory",
    },
    "plugins.elevate-memory-store.auto_extract": {
        "type": "boolean",
        "description": "Auto-extract durable facts at session end",
        "category": "memory",
    },
    "plugins.elevate-memory-store.turn_journal_enabled": {
        "type": "boolean",
        "description": "Record completed turns locally for daily/session memory organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_on_session_end": {
        "type": "boolean",
        "description": "Organize pending journal turns when a session ends",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_every_n_turns": {
        "type": "number",
        "description": "Also organize pending journal turns every N completed turns (0 disables)",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_enabled": {
        "type": "boolean",
        "description": "Run local daily journal organization even when sessions stay open",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_hour": {
        "type": "number",
        "description": "Local hour for daily journal organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_minute": {
        "type": "number",
        "description": "Local minute for daily journal organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_max_batches": {
        "type": "number",
        "description": "Maximum memory organization batches in one daily pass",
        "category": "memory",
    },
    "plugins.elevate-memory-store.turn_journal_max_chars": {
        "type": "number",
        "description": "Maximum characters saved per side of a turn",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_batch_limit": {
        "type": "number",
        "description": "Maximum pending turns to organize in one pass",
        "category": "memory",
    },
    "plugins.elevate-memory-store.layered_prefetch_enabled": {
        "type": "boolean",
        "description": "Inject recent, durable, and graph memory lanes instead of one flat memory list",
        "category": "memory",
    },
    "plugins.elevate-memory-store.recent_recall_enabled": {
        "type": "boolean",
        "description": "Include recent same-session journal recall",
        "category": "memory",
    },
    "plugins.elevate-memory-store.graph_recall_enabled": {
        "type": "boolean",
        "description": "Include wiki-style entity graph recall",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_enabled": {
        "type": "boolean",
        "description": "Enable semantic embeddings for durable memory search",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_provider": {
        "type": "select",
        "description": "Embedding backend",
        "options": ["openai", "ollama", "openai_compatible", "local_minilm"],
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_model": {
        "type": "string",
        "description": "Embedding model name",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_dimensions": {
        "type": "string",
        "description": "Optional embedding dimensions override",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_base_url": {
        "type": "string",
        "description": "Optional OpenAI-compatible embedding base URL",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_api_key_env": {
        "type": "string",
        "description": "Environment variable containing the embedding API key",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_cache_dir": {
        "type": "string",
        "description": "Optional local model cache directory for local_minilm",
        "category": "memory",
    },
    "access.profile": {
        "type": "select",
        "description": "Access profile for local entitlement gates",
        "options": ["standalone", "exp", "team_pack"],
        "category": "access",
    },
    "access.affiliation.status": {
        "type": "select",
        "description": "Affiliation status used by team/EXP skill access gates",
        "options": ["active", "inactive", "left", "paused"],
        "category": "access",
    },
    "platforms.telegram.reply_to_mode": {
        "type": "select",
        "description": "Telegram reply threading mode",
        "options": ["off", "first", "all"],
        "category": "platforms",
    },
    "platforms.telegram.extra.unauthorized_dm_behavior": {
        "type": "select",
        "description": "Telegram behavior for unpaired direct messages",
        "options": ["pair", "ignore"],
        "category": "platforms",
    },
    "platforms.api_server.reply_to_mode": {
        "type": "select",
        "description": "API server reply threading mode",
        "options": ["off", "first", "all"],
        "category": "platforms",
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "approvals.permission_mode": {
        "type": "select",
        "description": "Tool permission mode (Claude-style). Overrides 'mode' when set: "
        "default = ask first, acceptEdits = auto-accept file edits, "
        "plan = read-only, bypassPermissions = never ask",
        "options": ["default", "acceptEdits", "plan", "bypassPermissions"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
    "prompt_caching": "agent",
    "goals": "agent",
    "sources": "integrations",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "agent_hub", "sources", "integrations", "platforms", "terminal", "display",
    "delegation", "memory", "access", "plugins", "compression", "security",
    "browser", "voice", "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            if full_key.startswith("plugins.elevate-memory-store."):
                entry["category"] = "memory"
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema


_AGENT_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_BOT_TOKEN$")
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN"
_EXECUTIVE_TELEGRAM_CHANNEL_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL"


def _looks_like_telegram_bot_token(value: Any) -> bool:
    text = str(value or "").strip()
    if text.lower().startswith("telegram:"):
        text = text.split(":", 1)[1]
    return bool(_TELEGRAM_BOT_TOKEN_RE.fullmatch(text))


def _agent_segment_is_executive(segment: str) -> bool:
    return segment.strip().upper() == "EXECUTIVE_ASSISTANT"


def _executive_telegram_token() -> str:
    return str(
        get_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY)
        or get_env_value("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()


def _non_executive_duplicate_agent_token(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    for key, existing in load_env().items():
        match = _AGENT_TELEGRAM_BOT_TOKEN_RE.fullmatch(key)
        if not match or _agent_segment_is_executive(match.group(1)):
            continue
        if str(existing or "").strip() == candidate:
            return key
    return ""


def _reject_shared_agent_token(segment: str, value: str) -> None:
    executive_token = _executive_telegram_token()
    if executive_token and value.strip() == executive_token and not _agent_segment_is_executive(segment):
        raise HTTPException(
            status_code=400,
            detail=(
                "This token already belongs to the Executive Telegram bot. "
                "Create a separate bot token for this agent in BotFather."
            ),
        )


def _sync_executive_telegram_aliases(key: str, value: str) -> list[str]:
    """Keep legacy gateway Telegram keys and the Executive agent lane aligned."""
    old_shared_token = str(get_env_value("TELEGRAM_BOT_TOKEN") or "").strip()
    old_shared_channel = str(get_env_value("TELEGRAM_HOME_CHANNEL") or "").strip()
    old_executive_token = str(get_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY) or "").strip()
    old_executive_channel = str(get_env_value(_EXECUTIVE_TELEGRAM_CHANNEL_KEY) or "").strip()
    synced: list[str] = []

    if key == "TELEGRAM_BOT_TOKEN":
        if _non_executive_duplicate_agent_token(value):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This token is already assigned to another agent. "
                    "Each non-Executive Telegram agent needs its own BotFather token."
                ),
            )
        if value and (not old_executive_token or old_executive_token == old_shared_token):
            save_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY, value)
            synced.append(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY)
    elif key == _EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY:
        if _non_executive_duplicate_agent_token(value):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This token is already assigned to another agent. "
                    "Each non-Executive Telegram agent needs its own BotFather token."
                ),
            )
        if value and (not old_shared_token or old_shared_token == old_executive_token):
            save_env_value("TELEGRAM_BOT_TOKEN", value)
            synced.append("TELEGRAM_BOT_TOKEN")
    elif key == "TELEGRAM_HOME_CHANNEL":
        if value and (not old_executive_channel or old_executive_channel == old_shared_channel):
            save_env_value(_EXECUTIVE_TELEGRAM_CHANNEL_KEY, value)
            synced.append(_EXECUTIVE_TELEGRAM_CHANNEL_KEY)
    elif key == _EXECUTIVE_TELEGRAM_CHANNEL_KEY:
        if value and (not old_shared_channel or old_shared_channel == old_executive_channel):
            save_env_value("TELEGRAM_HOME_CHANNEL", value)
            synced.append("TELEGRAM_HOME_CHANNEL")

    return synced


from elevate_cli.web_routes.agent_hub import create_agent_hub_router
from elevate_cli.web_routes.actions import create_actions_router
from elevate_cli.web_routes.activity_comms import create_activity_comms_router
from elevate_cli.web_routes.analytics import create_analytics_router
from elevate_cli.web_routes.admin_actions import create_admin_actions_router
from elevate_cli.web_routes.admin_contacts import create_admin_contacts_router
from elevate_cli.web_routes.admin_deals import create_admin_deals_router
from elevate_cli.web_routes.admin_onboarding import create_admin_onboarding_router
from elevate_cli.web_routes.admin_pack import create_admin_pack_router
from elevate_cli.web_routes.admin_setup import (
    admin_jurisdiction_config as _admin_jurisdiction_config,
    create_admin_setup_router,
    require_admin_setup_ready_for_launch as _require_admin_setup_ready_for_launch,
)
from elevate_cli.web_routes.admin_templates import create_admin_templates_router
from elevate_cli.web_routes.ayrshare import create_ayrshare_router
from elevate_cli.web_routes.channels import create_channels_router
from elevate_cli.web_routes.composio import create_composio_router
from elevate_cli.web_routes.config import create_config_router
from elevate_cli.web_routes.cron import create_cron_router
from elevate_cli.web_routes.dashboard import create_dashboard_router, mount_dashboard_plugin_api_routes
from elevate_cli.web_routes.env import create_env_router
from elevate_cli.web_routes.files import create_files_router
from elevate_cli.web_routes.integrations import create_integrations_router
from elevate_cli.web_routes.lanes import create_lanes_router
from elevate_cli.web_routes.license import create_license_router
from elevate_cli.web_routes.logs import create_logs_router
from elevate_cli.web_routes.oauth import create_oauth_router
from elevate_cli.web_routes.outreach_templates import create_outreach_templates_router
from elevate_cli.web_routes.session_details import create_session_detail_router
from elevate_cli.web_routes.sessions import create_sessions_router
from elevate_cli.web_routes.skills import create_skills_router
from elevate_cli.web_routes.social import create_social_router
from elevate_cli.web_routes.source_connectors import create_source_connectors_router
from elevate_cli.web_routes.status import create_status_router
from elevate_cli.web_routes.surface_tasks import create_surface_tasks_router
from elevate_cli.web_routes.threads import create_threads_router
from elevate_cli.web_routes.today import create_today_router
from elevate_cli.web_routes.workspace import create_workspace_router, git_value as _git_value

# ---------------------------------------------------------------------------
# Gateway + update actions (invoked from the Status page).
#
# Both commands are spawned as detached subprocesses so the HTTP request
# returns immediately.  stdin is closed (``DEVNULL``) so any stray ``input()``
# calls fail fast with EOF rather than hanging forever.  stdout/stderr are
# streamed to a per-action log file under ``~/.elevate/logs/<action>.log`` so
# the dashboard can tail them back to the user.
# ---------------------------------------------------------------------------

_ACTION_LOG_DIR: Path = get_elevate_home() / "logs"

# Short ``name`` (from the URL) → absolute log file path.
_ACTION_LOG_FILES: Dict[str, str] = {
    "gateway-start": "gateway-start.log",
    "gateway-restart": "gateway-restart.log",
    "elevate-update": "elevate-update.log",
}

# ``name`` → most recently spawned Popen handle.  Used so ``status`` can
# report liveness and exit code without shelling out to ``ps``.
_ACTION_PROCS: Dict[str, subprocess.Popen] = {}


def _spawn_elevate_action(subcommand: List[str], name: str) -> subprocess.Popen:
    """Spawn ``elevate <subcommand>`` detached and record the Popen handle.

    Uses the running interpreter's ``elevate_cli.main`` module so the action
    inherits the same venv/PYTHONPATH the web server is using.
    """
    log_file_name = _ACTION_LOG_FILES[name]
    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _ACTION_LOG_DIR / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "elevate_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "ELEVATE_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _ACTION_PROCS[name] = proc
    return proc


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``.  Reads the whole file — fine
    for our small per-action logs.  Binary-decoded with ``errors='replace'``
    so log corruption doesn't 500 the endpoint."""
    if not path.exists():
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


def _session_reveal_target(session_id: str) -> Path:
    sessions_dir = get_elevate_home() / "sessions"
    transcript = sessions_dir / f"{session_id}.jsonl"
    if transcript.exists():
        return transcript
    return sessions_dir


def _open_in_file_manager(path: Path) -> None:
    path = path.expanduser().resolve()
    if sys.platform == "darwin":
        cmd = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
    elif sys.platform == "win32":
        selector = f"/select,{path}" if path.is_file() else str(path)
        cmd = ["explorer", selector]
    else:
        cmd = ["xdg-open", str(path if path.is_dir() else path.parent)]

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# A session counts as "active" (spinner in the sidebar) only if a message
# landed within this many seconds. The spinner means genuinely working right
# now, not recently-touched — so this stays tight. 300s made idle chats spin.
_SESSION_ACTIVE_WINDOW_SEC = 25


def _gateway_session_run_states() -> tuple[set[str], set[str]]:
    """(running_keys, known_keys) for sessions the in-process gateway hosts.

    A long interactive turn persists nothing until it finishes, so its
    ``last_active`` freezes at the user-message time and the 25s active-window
    check above flips ``is_active`` to False mid-turn — which makes the sidebar
    drop its "working" dots while the agent is genuinely still working. The
    gateway tracks ``session["running"]`` in-process (dashboard --tui hosts both),
    so consult it as the source of truth for "running right now". Best-effort:
    returns empty sets if the gateway module isn't loaded (headless dashboard).

    ``known_keys`` covers every hosted session regardless of run state. A
    session that is KNOWN but not RUNNING is authoritatively idle — e.g. the
    user hit Stop and the turn ended ``interrupted_by_user``. The recency
    window must not keep showing it as working for another 25 seconds.
    """
    running: set[str] = set()
    known: set[str] = set()
    try:
        from tui_gateway import server as _gw

        for sess in list(getattr(_gw, "_sessions", {}).values()):
            if not isinstance(sess, dict):
                continue
            keys = [
                str(k)
                for k in (sess.get("session_key"), sess.get("session_id"))
                if k
            ]
            known.update(keys)
            if sess.get("running"):
                running.update(keys)
    except Exception:
        pass
    return running, known


def _live_running_session_keys() -> set[str]:
    """DB session keys the in-process gateway is ACTIVELY running a turn for."""
    return _gateway_session_run_states()[0]


def _live_subagent_child_session_ids() -> set[str]:
    """Child session ids currently present in the live delegation registry."""
    ids: set[str] = set()
    try:
        from tools.delegate_tool import list_active_subagents

        for record in list_active_subagents():
            if not isinstance(record, dict):
                continue
            child_session_id = str(record.get("child_session_id") or "").strip()
            if child_session_id:
                ids.add(child_session_id)
    except Exception:
        pass
    return ids


def _mark_session_activity(sessions: list[dict[str, Any]], now: float) -> None:
    """Stamp ``is_active`` on session list rows.

    Priority: gateway-running (True) > gateway-known-but-idle (False — a
    stopped/interrupted session is NOT active no matter how fresh its last
    message is) > recency window (covers turns run outside this process,
    e.g. cron jobs, where the gateway has no entry to consult).
    """
    running, known = _gateway_session_run_states()
    for s in sessions:
        sid = str(s.get("id") or "")
        if sid in running:
            s["is_active"] = True
        elif sid in known:
            s["is_active"] = False
        else:
            s["is_active"] = (
                s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0)))
                < _SESSION_ACTIVE_WINDOW_SEC
            )


_SESSION_LIST_FIELDS = (
    "id",
    "source",
    "user_id",
    "model",
    "parent_session_id",
    "started_at",
    "ended_at",
    "end_reason",
    "message_count",
    "tool_call_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "title",
    "api_call_count",
    "preview",
    "last_active",
    "_lineage_root_id",
    "is_active",
)


def _session_list_payload(session: dict[str, Any]) -> dict[str, Any]:
    """Return only fields needed by dashboard session lists."""
    return {key: session.get(key) for key in _SESSION_LIST_FIELDS if key in session}


def _platform_chat_sources() -> list[str]:
    """Gateway chat-platform sources hidden from the app's session sidebar.

    Telegram/Discord/etc. conversations live on the messenger — surfacing
    their gateway sessions in the desktop app duplicates them as fake
    "chats" the user never started there. ``local`` is the gateway's own
    terminal mode and stays visible.
    """
    try:
        from gateway.config import Platform

        return [p.value for p in Platform if p.value != "local"]
    except Exception:
        return [
            "telegram", "discord", "whatsapp", "slack", "signal",
            "mattermost", "matrix", "homeassistant", "email", "sms",
            "dingtalk", "api_server", "webhook", "feishu", "wecom",
            "wecom_callback", "weixin", "bluebubbles", "qqbot", "yuanbao",
            "msgraph_webhook",
        ]


app.include_router(
    create_sessions_router(
        get_session_db=_get_session_db,
        platform_chat_sources=_platform_chat_sources,
        mark_session_activity=_mark_session_activity,
        session_list_payload=_session_list_payload,
        log=_log,
    )
)

app.include_router(create_oauth_router(require_token=_require_token))

app.include_router(
    create_session_detail_router(
        get_session_db=_get_session_db,
        session_reveal_target=_session_reveal_target,
        open_in_file_manager=_open_in_file_manager,
        live_subagent_child_session_ids=_live_subagent_child_session_ids,
        log=_log,
    )
)

app.include_router(create_cron_router(log=_log))

app.include_router(
    create_status_router(
        workspace_root=WORKSPACE_ROOT,
        get_session_db=_get_session_db,
        session_active_window_sec=_SESSION_ACTIVE_WINDOW_SEC,
        log=_log,
    )
)

app.include_router(create_license_router(require_token=_require_token))

app.include_router(create_files_router(project_root=PROJECT_ROOT, log=_log))

app.include_router(create_logs_router())

app.include_router(
    create_workspace_router(
        workspace_root=WORKSPACE_ROOT,
        open_in_file_manager=_open_in_file_manager,
        log=_log,
    )
)

app.include_router(
    create_actions_router(
        project_root=PROJECT_ROOT,
        action_log_dir=_ACTION_LOG_DIR,
        action_log_files=_ACTION_LOG_FILES,
        action_procs=_ACTION_PROCS,
        spawn_elevate_action=_spawn_elevate_action,
        tail_lines=_tail_lines,
        is_packaged_desktop_runtime=_is_packaged_desktop_runtime,
        git_value=_git_value,
        log=_log,
    )
)

app.include_router(
    create_activity_comms_router(
        fs_cache_get=_fs_cache_get,
        fs_cache_put=_fs_cache_put,
        log=_log,
    )
)

app.include_router(
    create_admin_actions_router(
        require_admin_setup_ready_for_launch=lambda: _require_admin_setup_ready_for_launch(),
        web_actor="human:web",
        log=_log,
    )
)

app.include_router(
    create_admin_deals_router(
        require_admin_setup_ready_for_launch=lambda: _require_admin_setup_ready_for_launch(),
        admin_jurisdiction_config=lambda: _admin_jurisdiction_config(),
        web_actor="human:web",
        log=_log,
    )
)

app.include_router(create_admin_templates_router(web_actor="human:web", log=_log))

app.include_router(
    create_config_router(
        default_config=DEFAULT_CONFIG,
        config_schema=CONFIG_SCHEMA,
        category_order=_CATEGORY_ORDER,
        log=_log,
    )
)

app.include_router(
    create_env_router(
        require_token=_require_token,
        looks_like_telegram_bot_token=_looks_like_telegram_bot_token,
        reject_shared_agent_token=_reject_shared_agent_token,
        sync_executive_telegram_aliases=_sync_executive_telegram_aliases,
        log=_log,
    )
)

app.include_router(create_analytics_router(get_session_db=_get_session_db, log=_log))

app.include_router(create_ayrshare_router(log=_log))

app.include_router(
    create_channels_router(
        log=_log,
        require_token=_require_token,
        spawn_elevate_action=_spawn_elevate_action,
        looks_like_telegram_bot_token=_looks_like_telegram_bot_token,
        sync_executive_telegram_aliases=_sync_executive_telegram_aliases,
    )
)

app.include_router(create_source_connectors_router(log=_log))

app.include_router(create_integrations_router(log=_log))

app.include_router(create_composio_router(log=_log))

app.include_router(create_dashboard_router(project_root=PROJECT_ROOT, log=_log))

app.include_router(create_lanes_router(log=_log))

app.include_router(create_outreach_templates_router(log=_log))

app.include_router(create_skills_router())

app.include_router(create_social_router(log=_log))

app.include_router(create_surface_tasks_router(log=_log))

app.include_router(create_threads_router(log=_log))

app.include_router(create_today_router(log=_log))

_WEB_ACTOR = "human:web"


app.include_router(
    create_agent_hub_router(
        require_admin_setup_ready_for_launch=_require_admin_setup_ready_for_launch,
        log=_log,
    )
)

app.include_router(create_admin_contacts_router(web_actor=_WEB_ACTOR, log=_log))
app.include_router(create_admin_setup_router(web_actor=_WEB_ACTOR, log=_log))
app.include_router(create_admin_onboarding_router(log=_log))
app.include_router(create_admin_pack_router(web_actor=_WEB_ACTOR, log=_log))


@app.get("/api/heartbeats/surfaces")
def get_heartbeat_surfaces():
    """Per-surface heartbeat state, cached per account for a few seconds. The
    scan walks every surface dir + reads its config/history/learnings, so rapid
    polling is collapsed to one scan. Surface mutations invalidate the cache
    (see _fs_cache_invalidate('surfaces')); the short TTL is a backstop for any
    mutation path that doesn't."""
    cached = _fs_cache_get("surfaces")
    if cached is not None:
        return cached
    result = _compute_heartbeat_surfaces()
    _fs_cache_put("surfaces", result, 3.0)
    return result


def _compute_heartbeat_surfaces():
    """Per-surface heartbeat state for the CURRENT account.

    Surface STATE (config, heartbeat record, experiments) lives in the account
    database (migration 0024); markdown artifacts (learnings.md, history/ run
    records) stay in ``<account_data_dir>/heartbeats/<surface>/``. Surfaces
    enumerate from the DB, unioned with any workspace dirs that exist
    (back-compat). Mirrors the experiments scan but Elevate-native
    and per-account-scoped. Missing rows/files degrade to empty so a surface
    that has never fired still renders.
    """
    try:
        from elevate_constants import get_account_data_dir
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        heartbeats_dir = get_account_data_dir() / "heartbeats"
        surfaces: List[Dict[str, Any]] = []

        # Authoritative enabled state lives on the cron job, not the config — a
        # paused/resumed toggle updates the job first. Map surface -> job.enabled
        # so a card reflects whether the heartbeat will actually fire, even if a
        # stale config copy disagrees.
        job_by_surface: Dict[str, Dict[str, Any]] = {}
        job_enabled_by_surface: Dict[str, bool] = {}
        # A surface's heartbeat is split into several FOCUSED crons (origin.focus) —
        # collect them per surface like automations so each card lists them; the
        # surface counts as enabled if ANY focused heartbeat is enabled.
        heartbeats_by_surface: Dict[str, List[Dict[str, Any]]] = {}
        # Surface automations are the per-surface "kit" cron jobs that pair with
        # each heartbeat (origin.type=="surface-automation"). Group them by
        # surface here from the SAME job scan so each card can list its own.
        automations_by_surface: Dict[str, List[Dict[str, Any]]] = {}
        try:
            from cron.jobs import list_jobs as _list_jobs

            for _job in _list_jobs(include_disabled=True):
                _origin = _job.get("origin") or {}
                _otype = _origin.get("type")
                _surf = _origin.get("surface")
                if not (isinstance(_surf, str) and _surf):
                    continue
                if _otype == "surface-heartbeat":
                    _is_owner = bool(_origin.get("experiment_owner"))
                    # Representative job for the surface = the experiment owner when
                    # present (it carries the surface-level cadence/settings).
                    if _surf not in job_by_surface or _is_owner:
                        job_by_surface[_surf] = _job
                    _hb_enabled = bool(_job.get("enabled", True))
                    job_enabled_by_surface[_surf] = (
                        job_enabled_by_surface.get(_surf, False) or _hb_enabled
                    )
                    _hb_sched_obj = _job.get("schedule") or {}
                    _hb_sched = (
                        str(_job.get("schedule_display") or "").strip()
                        or str(_hb_sched_obj.get("display") or "").strip()
                        or str(_hb_sched_obj.get("expr") or "").strip()
                    )
                    heartbeats_by_surface.setdefault(_surf, []).append(
                        {
                            "id": _job.get("id"),
                            "name": _job.get("name") or _job.get("id") or "heartbeat",
                            "focus": str(_origin.get("focus") or ""),
                            "schedule": _hb_sched,
                            "enabled": _hb_enabled,
                            "experiment_owner": _is_owner,
                            "last_run_at": _job.get("last_run_at"),
                        }
                    )
                elif _otype == "surface-automation":
                    _sched_obj = _job.get("schedule") or {}
                    _sched = (
                        str(_job.get("schedule_display") or "").strip()
                        or str(_sched_obj.get("display") or "").strip()
                        or str(_sched_obj.get("expr") or "").strip()
                    )
                    automations_by_surface.setdefault(_surf, []).append(
                        {
                            "id": _job.get("id"),
                            "name": _job.get("name") or _job.get("id") or "automation",
                            "schedule": _sched,
                            "enabled": bool(_job.get("enabled", True)),
                            "last_run_at": _job.get("last_run_at"),
                        }
                    )
        except Exception:
            # No cron access -> fall back to the config's own enabled below.
            job_enabled_by_surface = {}
            automations_by_surface = {}

        # Stable order: sort each surface's automations by name (case-insensitive).
        for _list in automations_by_surface.values():
            _list.sort(key=lambda a: str(a.get("name") or "").lower())
        # Stable order: experiment owner first, then by name.
        for _list in heartbeats_by_surface.values():
            _list.sort(
                key=lambda h: (not h.get("experiment_owner"), str(h.get("name") or "").lower())
            )

        def _read_json(path: Path) -> Optional[Any]:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None

        with connect() as conn:
            # Surfaces enumerate from the account DB (state + registry rows),
            # unioned with any workspace dirs that exist (back-compat / markdown).
            surface_names = set(surface_state.list_state_surfaces(conn))
            if heartbeats_dir.is_dir():
                surface_names.update(
                    p.name for p in heartbeats_dir.iterdir() if p.is_dir()
                )

            for surface_name in sorted(surface_names):
                surface_dir = heartbeats_dir / surface_name

                # Config (account DB; missing row degrades to None like the old
                # missing config.json read).
                config: Optional[Dict[str, Any]] = (
                    surface_state.get_config(conn, surface_name) or None
                )
                # Overlay the AUTHORITATIVE enabled from the cron job so the card
                # never shows a stale config value (the toggle writes the job
                # first). Falls back to the config's own enabled when no job exists.
                if surface_name in job_enabled_by_surface:
                    if not isinstance(config, dict):
                        config = {}
                    config["enabled"] = job_enabled_by_surface[surface_name]
                job = job_by_surface.get(surface_name)
                if job:
                    if not isinstance(config, dict):
                        config = {}
                    if job.get("agent"):
                        config["agent"] = job.get("agent")
                    if job.get("deliver"):
                        config["deliver"] = job.get("deliver")
                    if job.get("model"):
                        config["model"] = job.get("model")
                    if not config.get("cadence"):
                        schedule = job.get("schedule") or {}
                        config["cadence"] = (
                            job.get("schedule_display")
                            or (schedule.get("display") if isinstance(schedule, dict) else None)
                            or (schedule.get("expr") if isinstance(schedule, dict) else None)
                        )
                if isinstance(config, dict) and not str(config.get("agent") or "").strip():
                    try:
                        from cron.jobs import resolve_surface_agent

                        inferred_agent = resolve_surface_agent(surface_name, {"config": config})
                        if inferred_agent:
                            config["agent"] = inferred_agent
                    except Exception:
                        pass

                # Work-run history: prefer the DB run index (surface_runs,
                # migration 0027) — newest row wins. Surfaces that never
                # logged/imported runs to the DB fall back to the legacy
                # history/*.json file scan (markdown transcripts and old
                # json run records stay on disk).
                db_runs = surface_state.list_runs(conn, surface_name, limit=1)
                if db_runs:
                    newest_run = db_runs[0]
                    run_count = surface_state.count_runs(conn, surface_name)
                    last_run = newest_run.get("record") or {
                        "ran_at": newest_run.get("ran_at"),
                        "summary": newest_run.get("summary"),
                        "status": newest_run.get("status"),
                    }
                else:
                    history_files: List[Path] = []
                    hist_dir = surface_dir / "history"
                    if hist_dir.is_dir():
                        history_files = sorted(
                            (p for p in hist_dir.glob("*.json") if p.is_file()),
                            key=lambda p: p.name,
                            reverse=True,
                        )
                    run_count = len(history_files)
                    last_run = _read_json(history_files[0]) if history_files else None
                if last_run is None:
                    # Fall back to the agent_bus heartbeat record (account DB).
                    last_run = surface_state.get_heartbeat(conn, surface_name)

                # Learnings (raw markdown, stays on disk)
                learnings = ""
                learnings_path = surface_dir / "learnings.md"
                if learnings_path.is_file():
                    try:
                        learnings = learnings_path.read_text(encoding="utf-8")
                    except Exception:
                        learnings = ""

                # Experiments (account DB): most recent active record + the
                # completed keep/discard history.
                active_exp = surface_state.get_experiment(conn, surface_name)
                exp_history: List[Any] = surface_state.list_experiments(
                    conn, surface_name, status="completed"
                )

                # Newest first by timestamp when present (updated_at order is
                # the fallback, matching the old filename sort).
                def _exp_ts(e: Any) -> str:
                    return str(e.get("ts") or "") if isinstance(e, dict) else ""

                exp_history.sort(key=_exp_ts, reverse=True)

                kept = sum(
                    1
                    for e in exp_history
                    if isinstance(e, dict) and e.get("decision") == "keep"
                )
                discarded = sum(
                    1
                    for e in exp_history
                    if isinstance(e, dict) and e.get("decision") == "discard"
                )
                decided = kept + discarded
                keep_rate = round((kept / decided) * 100) if decided else 0

                # Job health: stall backoff + last status, so a backed-off
                # heartbeat is visible on its card instead of silently sleeping
                # for up to 6h (the stall cap) with no explanation.
                job_health: Optional[Dict[str, Any]] = None
                if job:
                    job_health = {
                        "lastStatus": job.get("last_status"),
                        "lastRunAt": job.get("last_run_at"),
                        "nextRunAt": job.get("next_run_at"),
                        "stallCount": job.get("stall_count") or 0,
                        "backoffUntil": job.get("backoff_until"),
                        "backoffMinutes": job.get("backoff_minutes"),
                        "lastError": job.get("last_error"),
                    }

                surfaces.append(
                    {
                        "surface": surface_name,
                        "config": config,
                        "runCount": run_count,
                        "lastRun": last_run,
                        "jobHealth": job_health,
                        "learnings": learnings,
                        "heartbeats": heartbeats_by_surface.get(surface_name, []),
                        "automations": automations_by_surface.get(surface_name, []),
                        "experiments": {
                            "active": active_exp,
                            "history": exp_history,
                            "stats": {
                                "total": len(exp_history),
                                "kept": kept,
                                "discarded": discarded,
                                "keepRate": keep_rate,
                            },
                        },
                    }
                )

        return {"surfaces": surfaces}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/surfaces failed")
        raise HTTPException(status_code=500, detail=f"Heartbeat surfaces failed: {exc}")


class _HeartbeatSurfaceCreateBody(BaseModel):
    surface: str
    title: Optional[str] = None
    name: Optional[str] = None
    schedule: Optional[str] = None
    goal: Optional[str] = None
    experiment: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


@app.post("/api/heartbeats/surfaces")
def create_heartbeat_surface(body: _HeartbeatSurfaceCreateBody):
    """Create a NEW custom surface from the template + overrides (add-agent
    equivalent). Registers it in the account surface registry, scaffolds its workspace,
    and seeds an opt-in (off) cron job. The realtor turns it on from the Heartbeat page.
    """
    try:
        from cron.jobs import create_surface

        spec = {
            k: v
            for k, v in {
                "title": body.title,
                "name": body.name,
                "schedule": body.schedule,
                "goal": body.goal,
                "experiment": body.experiment,
                "config": body.config,
            }.items()
            if v is not None
        }
        result = create_surface(body.surface, spec, created_by="user")
        # Mirror the registry write into the account DB (migration 0024) so
        # PG-backed reads see the new surface immediately, whichever storage
        # cron.jobs.register_surface targets.
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                surface_state.upsert_registry(
                    conn,
                    result["surface"],
                    dict(result.get("spec") or {}),
                    created_by="user",
                )
        except Exception:
            _log.warning("surface registry DB mirror failed", exc_info=True)
        _fs_cache_invalidate("surfaces")
        return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/heartbeats/surfaces failed")
        raise HTTPException(status_code=500, detail=f"Create surface failed: {exc}")


@app.delete("/api/heartbeats/surfaces/{surface}")
def delete_heartbeat_surface(surface: str, force: bool = False):
    """Delete a custom heartbeat surface, its generated jobs, and its workspace.

    Built-in surfaces are protected unless ``force=true`` is passed. This is
    primarily the inverse of the add-agent/import flow: the surface registry,
    surface heartbeat cron, surface-automation crons, and
    ``accounts/<key>/heartbeats/<surface>/`` are removed together.
    """
    try:
        from cron.jobs import delete_surface
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        key = (surface or "").strip().lower()
        try:
            result: Optional[Dict[str, Any]] = delete_surface(surface, force=bool(force))
        except LookupError:
            result = None  # may still exist only in the account DB — checked below

        # Purge the account-DB state (migration 0024): registry row, state row,
        # experiments, and goals history all go with the surface.
        with connect() as conn:
            spec = surface_state.list_registry(conn).get(key)
            if result is None:
                known = key in surface_state.list_state_surfaces(conn)
                if spec is None and not known:
                    raise LookupError(f"surface '{key}' not found")
                if spec and spec.get("builtin") and not force:
                    raise ValueError("built-in heartbeat surfaces cannot be deleted")
            removed_registry = surface_state.remove_registry(conn, key)
            conn.execute("DELETE FROM surface_state WHERE surface = ?", (key,))
            conn.execute("DELETE FROM surface_experiments WHERE surface = ?", (key,))
            conn.execute("DELETE FROM surface_goals_history WHERE surface = ?", (key,))

        if result is None:
            result = {
                "ok": True,
                "surface": key,
                "removed": {"registry": removed_registry, "files": False, "jobs": []},
            }
        elif removed_registry and isinstance(result.get("removed"), dict):
            result["removed"]["registry"] = True
        _fs_cache_invalidate("surfaces")
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("DELETE /api/heartbeats/surfaces/%s failed", surface)
        raise HTTPException(status_code=500, detail=f"Delete surface failed: {exc}")


def _experiment_stats(experiments: List[Dict[str, Any]]) -> Dict[str, int]:
    """Per-surface experiment stats, computed at read time (never persisted)."""
    running = sum(1 for e in experiments if e.get("status") == "running")
    proposed = sum(1 for e in experiments if e.get("status") == "proposed")
    completed = sum(1 for e in experiments if e.get("status") == "completed")
    kept = sum(1 for e in experiments if e.get("decision") == "keep")
    discarded = sum(1 for e in experiments if e.get("decision") == "discard")
    decided = kept + discarded
    return {
        "total": len(experiments),
        "running": running,
        "proposed": proposed,
        "completed": completed,
        "kept": kept,
        "discarded": discarded,
        "keepRate": round((kept / decided) * 100) if decided else 0,
    }


def _experiment_summary(surfaces: List[Dict[str, Any]]) -> Dict[str, int]:
    """Fleet-wide rollup across all surfaces."""
    kept = sum(s["stats"]["kept"] for s in surfaces)
    discarded = sum(s["stats"]["discarded"] for s in surfaces)
    decided = kept + discarded
    return {
        "surfaces": len(surfaces),
        "cycles": sum(len(s["cycles"]) for s in surfaces),
        "total": sum(s["stats"]["total"] for s in surfaces),
        "running": sum(s["stats"]["running"] for s in surfaces),
        "completed": sum(s["stats"]["completed"] for s in surfaces),
        "kept": kept,
        "discarded": discarded,
        "keepRate": round((kept / decided) * 100) if decided else 0,
    }


@app.get("/api/heartbeats/experiments")
def get_heartbeat_experiments():
    """Dedicated experiments view for the CURRENT account — the data behind the
    Experiments page. For every surface, reads the cycle definition (the config's
    ``experiment`` block / ``cycles[]``), the active (proposed+running) experiments,
    and the completed ones — all from the account DB (migration 0024) — normalizes
    each to one shape, folds in learnings.md (still on disk), and computes
    per-surface + fleet stats. Read-only; the surface-heartbeat EXPERIMENT loop owns
    all writes. Elevate-native port of scanExperiments().
    """
    try:
        from elevate_constants import get_account_data_dir
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        heartbeats_dir = get_account_data_dir() / "heartbeats"
        out_surfaces: List[Dict[str, Any]] = []

        with connect() as conn:
            # Surfaces enumerate from the account DB (state + registry rows),
            # unioned with any workspace dirs that exist (markdown back-compat).
            surface_names = set(surface_state.list_state_surfaces(conn))
            if heartbeats_dir.is_dir():
                surface_names.update(
                    p.name for p in heartbeats_dir.iterdir() if p.is_dir()
                )
            if not surface_names:
                return {"surfaces": out_surfaces, "summary": _experiment_summary([])}

            for surface_name in sorted(surface_names):
                surface_dir = heartbeats_dir / surface_name
                config = surface_state.get_config(conn, surface_name)
                try:
                    from cron.jobs import resolve_surface_agent

                    agent_name = resolve_surface_agent(
                        surface_name,
                        {"config": config if isinstance(config, dict) else {}},
                    )
                except Exception:
                    agent_name = (
                        str(config.get("agent") or "").strip()
                        if isinstance(config, dict)
                        else ""
                    )
                agent_name = agent_name or surface_name
                exp_cfg = config.get("experiment") if isinstance(config, dict) else None
                exp_cfg = exp_cfg if isinstance(exp_cfg, dict) else {}

                # Cycles are agent-creatable DATA: the real config.cycles[] array,
                # falling back (read-only) to the migrated legacy ``experiment`` block.
                try:
                    from cron.cycles import list_cycles as _list_cycles
                    cycles: List[Dict[str, Any]] = _list_cycles(surface_name)
                except Exception:
                    cycles = []
                cycles = [
                    {**c, "agent": c.get("agent") or agent_name}
                    for c in cycles
                    if isinstance(c, dict)
                ]

                # Metric/direction/window context for normalizing experiments below.
                cycle_by_metric = {
                    str(c.get("metric") or ""): c
                    for c in cycles
                    if isinstance(c, dict) and c.get("metric")
                }
                _ctx = cycles[0] if cycles else exp_cfg
                c_metric = _ctx.get("metric")
                c_direction = _ctx.get("direction")
                c_window = _ctx.get("window")

                def _normalize_experiment(r: Dict[str, Any], *, active: bool = False) -> Dict[str, Any]:
                    metric = r.get("metric") or c_metric
                    cycle_ctx = cycle_by_metric.get(str(metric or "")) or _ctx
                    status = str(r.get("status") or ("running" if active else "completed")).lower()
                    result_value = (
                        r.get("result_value")
                        if r.get("result_value") is not None
                        else r.get("result")
                    )
                    baseline_value = (
                        r.get("baseline_value")
                        if r.get("baseline_value") is not None
                        else r.get("baseline")
                    )
                    return {
                        "id": r.get("id") or r.get("ts"),
                        "surface": surface_name,
                        "agent": agent_name,
                        "status": status,
                        "decision": r.get("decision"),
                        "hypothesis": r.get("hypothesis"),
                        "changes_description": r.get("surface_change") or r.get("changes_description"),
                        "baseline": baseline_value,
                        "result": None if active and status == "running" else result_value,
                        "learning": r.get("learning"),
                        "metric": metric,
                        "direction": r.get("direction") or cycle_ctx.get("direction") or c_direction,
                        "window": r.get("window") or cycle_ctx.get("window") or c_window,
                        "created_at": r.get("created_at") or r.get("createdAt") or r.get("started_at") or r.get("ts"),
                        "started_at": r.get("started_at"),
                        "completed_at": r.get("completed_at") or r.get("ts"),
                    }

                experiments: List[Dict[str, Any]] = []
                seen_exp_ids: set[str] = set()

                # Active (proposed + running) experiments from the account DB.
                for r in surface_state.list_experiments(conn, surface_name, status="active"):
                    if not isinstance(r, dict):
                        continue
                    rid = str(r.get("id") or "")
                    if rid and rid in seen_exp_ids:
                        continue
                    experiments.append(_normalize_experiment(r, active=True))
                    if rid:
                        seen_exp_ids.add(rid)

                # Completed (keep/discard) experiments from the account DB.
                hist_records: List[Dict[str, Any]] = [
                    r
                    for r in surface_state.list_experiments(
                        conn, surface_name, status="completed"
                    )
                    if isinstance(r, dict)
                ]
                hist_records.sort(
                    key=lambda e: str(
                        e.get("completed_at")
                        or e.get("started_at")
                        or e.get("created_at")
                        or e.get("createdAt")
                        or e.get("ts")
                        or ""
                    ),
                    reverse=True,
                )
                for r in hist_records:
                    rid = str(r.get("id") or r.get("ts") or "")
                    if rid and rid in seen_exp_ids:
                        continue
                    experiments.append(_normalize_experiment(r))
                    if rid:
                        seen_exp_ids.add(rid)

                experiments.sort(
                    key=lambda e: str(e.get("completed_at") or e.get("started_at") or e.get("created_at") or ""),
                    reverse=True,
                )

                learnings = ""
                lp = surface_dir / "learnings.md"
                if lp.is_file():
                    try:
                        learnings = lp.read_text(encoding="utf-8")
                    except Exception:
                        learnings = ""

                out_surfaces.append({
                    "surface": surface_name,
                    "agent": agent_name,
                    "cycles": cycles,
                    "experiments": experiments,
                    "learnings": learnings,
                    "stats": _experiment_stats(experiments),
                })

        return {"surfaces": out_surfaces, "summary": _experiment_summary(out_surfaces)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/experiments failed")
        raise HTTPException(status_code=500, detail=f"Heartbeat experiments failed: {exc}")


@app.get("/api/experiments")
def list_experiments_alias(surface: Optional[str] = None):
    """native experiment list backed by native heartbeat experiments."""
    try:
        if surface:
            from tools.agent_bus_tool import _list_experiments

            return {"experiments": _list_experiments(surface)}
        return get_heartbeat_experiments()
    except Exception as exc:
        _log.exception("GET /api/experiments failed")
        raise HTTPException(status_code=500, detail=f"List experiments failed: {exc}")


@app.post("/api/experiments")
def create_experiment_alias(body: Dict[str, Any]):
    """Create a native heartbeat experiment through the Cortext-style HTTP path."""
    try:
        from tools.agent_bus_tool import _create_experiment

        return {"ok": True, "experiment": _create_experiment(dict(body or {}))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/experiments failed")
        raise HTTPException(status_code=500, detail=f"Create experiment failed: {exc}")


@app.post("/api/experiments/{experiment_id}/run")
def run_experiment_alias(experiment_id: str, body: Optional[Dict[str, Any]] = None):
    """Start a native heartbeat experiment through the Cortext-style HTTP path."""
    try:
        from tools.agent_bus_tool import _run_experiment

        payload = dict(body or {})
        payload.setdefault("experiment_id", experiment_id)
        return {"ok": True, "experiment": _run_experiment(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/experiments/%s/run failed", experiment_id)
        raise HTTPException(status_code=500, detail=f"Run experiment failed: {exc}")


@app.post("/api/experiments/{experiment_id}/evaluate")
def evaluate_experiment_alias(experiment_id: str, body: Dict[str, Any]):
    """Evaluate a native heartbeat experiment through the Cortext-style HTTP path."""
    try:
        from tools.agent_bus_tool import _evaluate_experiment

        payload = dict(body or {})
        payload.setdefault("experiment_id", experiment_id)
        return {"ok": True, "experiment": _evaluate_experiment(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/experiments/%s/evaluate failed", experiment_id)
        raise HTTPException(status_code=500, detail=f"Evaluate experiment failed: {exc}")


def _validate_heartbeat_surface(surface: str) -> str:
    """Return the trimmed surface name if it's a known surface for the current
    account — present in the account DB (state/registry rows, migration 0024)
    OR with a heartbeat workspace dir (back-compat) — else raise 400/404.
    Cycle endpoints are scoped to real surfaces only.
    """
    from elevate_constants import get_account_data_dir

    surface_key = (surface or "").strip()
    if not surface_key:
        raise HTTPException(status_code=400, detail="surface is required")
    surface_dir = get_account_data_dir() / "heartbeats" / surface_key
    if surface_dir.is_dir():
        return surface_key
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            if surface_key in surface_state.list_state_surfaces(conn):
                return surface_key
    except Exception:
        _log.warning("surface validation DB lookup failed", exc_info=True)
    raise HTTPException(status_code=404, detail=f"No heartbeat surface '{surface_key}'")


def _validate_heartbeat_agent(agent_id: str) -> str:
    """Resolve + validate an agent id for the per-agent heartbeat endpoints."""
    from cron.jobs import _slug_agent, _HEARTBEAT_CRON_EXCLUDED_AGENTS

    aid = _slug_agent(agent_id)
    if not aid:
        raise HTTPException(status_code=400, detail="invalid agent id")
    if aid in _HEARTBEAT_CRON_EXCLUDED_AGENTS:
        raise HTTPException(status_code=404, detail=f"agent '{aid}' has no heartbeat")
    return aid


def _agent_heartbeat_job(aid: str) -> Optional[Dict[str, Any]]:
    """The agent-bound 'heartbeat' cron job, if seeded."""
    from cron.jobs import load_jobs, _slug_agent

    for j in load_jobs():
        if (j.get("name") or "").strip().lower() == "heartbeat" and _slug_agent(
            str(j.get("agent") or "")
        ) == aid:
            return j
    return None


class _AgentHeartbeatMdBody(BaseModel):
    content: str


@app.get("/api/agents/{agent_id}/heartbeat-md")
def get_agent_heartbeat_md(agent_id: str):
    """Read an agent's HEARTBEAT.md (the 10-step beat it runs each cycle) plus its
    heartbeat cron state. Seeds the file from the role-aware template if missing."""
    try:
        aid = _validate_heartbeat_agent(agent_id)
        from cron.jobs import ensure_agent_heartbeat_md, agent_heartbeat_md_path

        ensure_agent_heartbeat_md(aid)
        path = agent_heartbeat_md_path(aid)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        job = _agent_heartbeat_job(aid)
        enabled = bool(job and job.get("enabled", True) and job.get("state") != "paused")
        return {
            "agent": aid,
            "path": str(path),
            "content": content,
            "job_id": (job or {}).get("id"),
            "enabled": enabled,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/agents/%s/heartbeat-md failed", agent_id)
        raise HTTPException(status_code=500, detail=f"read heartbeat-md failed: {exc}")


@app.put("/api/agents/{agent_id}/heartbeat-md")
def put_agent_heartbeat_md(agent_id: str, body: _AgentHeartbeatMdBody):
    """Overwrite an agent's HEARTBEAT.md (manual edit from the Agent Hub)."""
    try:
        aid = _validate_heartbeat_agent(agent_id)
        from cron.jobs import agent_heartbeat_md_path

        path = agent_heartbeat_md_path(aid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content or "", encoding="utf-8")
        return {"ok": True, "agent": aid, "path": str(path)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PUT /api/agents/%s/heartbeat-md failed", agent_id)
        raise HTTPException(status_code=500, detail=f"write heartbeat-md failed: {exc}")


@app.get("/api/heartbeats/surfaces/{surface}/cycles")
def list_heartbeat_cycles(surface: str):
    """List a surface's experiment cycles (the real ``cycles[]`` array, falling
    back to the migrated legacy ``experiment`` block). Read-only."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.cycles import list_cycles
        return {"cycles": list_cycles(surface_key)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/surfaces/%s/cycles failed", surface)
        raise HTTPException(status_code=500, detail=f"List cycles failed: {exc}")


class _HeartbeatCycleCreateBody(BaseModel):
    name: str
    metric: str
    metric_type: str
    direction: str
    window: str
    every_n_runs: Optional[int] = None
    measurement: Optional[str] = None
    approval_required: Optional[bool] = None
    surface: Optional[str] = None
    created_by: Optional[str] = None


@app.post("/api/heartbeats/surfaces/{surface}/cycles")
def create_heartbeat_cycle(surface: str, body: _HeartbeatCycleCreateBody):
    """Create a new agent-creatable experiment cycle on a surface."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.cycles import manage_cycle

        opts = {k: v for k, v in body.model_dump().items() if v is not None}
        result = manage_cycle(surface_key, "create", **opts)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "create failed")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/heartbeats/surfaces/%s/cycles failed", surface)
        raise HTTPException(status_code=500, detail=f"Create cycle failed: {exc}")


class _HeartbeatCyclePatchBody(BaseModel):
    metric_type: Optional[str] = None
    direction: Optional[str] = None
    window: Optional[str] = None
    loop_interval: Optional[str] = None
    every_n_runs: Optional[int] = None
    surface: Optional[str] = None
    measurement: Optional[str] = None
    enabled: Optional[bool] = None


@app.patch("/api/heartbeats/surfaces/{surface}/cycles/{name}")
def modify_heartbeat_cycle(surface: str, name: str, body: _HeartbeatCyclePatchBody):
    """Patch supplied fields of a surface cycle (matched by name, case-insensitive)."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.cycles import manage_cycle

        opts = {k: v for k, v in body.model_dump().items() if v is not None}
        result = manage_cycle(surface_key, "modify", name=name, **opts)
        if not result.get("ok"):
            err = result.get("error") or "modify failed"
            status = 404 if "not found" in err.lower() else 400
            raise HTTPException(status_code=status, detail=err)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PATCH /api/heartbeats/surfaces/%s/cycles/%s failed", surface, name)
        raise HTTPException(status_code=500, detail=f"Modify cycle failed: {exc}")


@app.delete("/api/heartbeats/surfaces/{surface}/cycles/{name}")
def remove_heartbeat_cycle(surface: str, name: str):
    """Remove a surface cycle by name (case-insensitive)."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.cycles import manage_cycle

        result = manage_cycle(surface_key, "remove", name=name)
        if not result.get("ok"):
            err = result.get("error") or "remove failed"
            status = 404 if "not found" in err.lower() else 400
            raise HTTPException(status_code=status, detail=err)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("DELETE /api/heartbeats/surfaces/%s/cycles/%s failed", surface, name)
        raise HTTPException(status_code=500, detail=f"Remove cycle failed: {exc}")


# ─── Surface delivery routing (each agent routes to its own channel/bot) ───────
def _surface_heartbeat_jobs(surface_key: str) -> List[Dict[str, Any]]:
    """ALL account-scoped focused heartbeat crons for a surface (enabled or not)."""
    from cron.jobs import list_jobs

    return [
        job
        for job in list_jobs(include_disabled=True)
        if (job.get("origin") or {}).get("type") == "surface-heartbeat"
        and (job.get("origin") or {}).get("surface") == surface_key
    ]


def _surface_heartbeat_job(surface_key: str) -> Optional[Dict[str, Any]]:
    """The representative heartbeat cron for a surface — the experiment owner when
    present (it carries the surface-level cadence/settings), else any."""
    jobs = _surface_heartbeat_jobs(surface_key)
    if not jobs:
        return None
    for job in jobs:
        if (job.get("origin") or {}).get("experiment_owner"):
            return job
    return jobs[-1]


def _delivery_routes() -> List[Dict[str, str]]:
    """Available delivery routes for the picker: in-app (local) + every channel the
    account has connected (the channel directory — Telegram/Discord/Slack/…). Each
    agent/surface can route to its own channel, faithful to CTRL Flow's per-agent
    bot/channel routing."""
    routes: List[Dict[str, str]] = [
        {"value": "local", "label": "In-app (default)", "platform": "local"}
    ]
    try:
        from gateway.channel_directory import load_directory

        directory = load_directory()
        for platform, channels in (directory.get("platforms") or {}).items():
            channels = [c for c in (channels or []) if c.get("id")]
            if not channels:
                continue  # platform not actually connected — skip the noise
            routes.append(
                {"value": platform, "label": f"{platform.title()} (home)", "platform": platform}
            )
            for ch in channels:
                cid = ch["id"]
                name = ch.get("name") or cid
                routes.append(
                    {"value": f"{platform}:{cid}", "label": f"{name} ({platform})", "platform": platform}
                )
    except Exception:
        _log.warning("delivery routes: channel directory unavailable", exc_info=True)
    return routes


@app.get("/api/heartbeats/surfaces/{surface}/route")
def get_heartbeat_surface_route(surface: str):
    """Current delivery route for a surface + the routes available to pick from."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        job = _surface_heartbeat_job(surface_key)
        deliver = (job or {}).get("deliver") or "local"
        return {"surface": surface_key, "deliver": deliver, "routes": _delivery_routes()}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/surfaces/%s/route failed", surface)
        raise HTTPException(status_code=500, detail=f"Get route failed: {exc}")


class _HeartbeatRouteBody(BaseModel):
    deliver: str


@app.post("/api/heartbeats/surfaces/{surface}/route")
def set_heartbeat_surface_route(surface: str, body: _HeartbeatRouteBody):
    """Route a surface's heartbeat output to a channel/bot (or 'local' = in-app).
    Updates the authoritative cron job's ``deliver`` + mirrors to the surface
    config in the account DB."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.jobs import update_job

        deliver = (body.deliver or "local").strip() or "local"
        valid = {r["value"] for r in _delivery_routes()}
        platform0 = deliver.split(":")[0]
        if deliver not in valid and platform0 != "local":
            # Accept explicit ``platform:chat`` forms whose platform is known even
            # if the directory cache is stale.
            from cron.scheduler import _is_known_delivery_platform

            if not _is_known_delivery_platform(platform0):
                raise HTTPException(status_code=400, detail=f"unknown delivery route: {deliver}")
        # Route ALL of the surface's focused heartbeats to the same channel.
        surface_jobs = _surface_heartbeat_jobs(surface_key)
        if not surface_jobs:
            raise HTTPException(
                status_code=404, detail=f"No heartbeat job for surface '{surface_key}'"
            )
        updated = None
        for job in surface_jobs:
            updated = update_job(job["id"], {"deliver": deliver}) or updated
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                surface_state.patch_config(conn, surface_key, {"deliver": deliver})
        except Exception:
            _log.warning("route config mirror failed for %s", surface_key, exc_info=True)
        return {"surface": surface_key, "deliver": (updated or {}).get("deliver", deliver)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/heartbeats/surfaces/%s/route failed", surface)
        raise HTTPException(status_code=500, detail=f"Set route failed: {exc}")



class _HeartbeatSurfaceEnabledBody(BaseModel):
    enabled: bool


@app.post("/api/heartbeats/surfaces/{surface}/enabled")
def set_heartbeat_surface_enabled(surface: str, body: _HeartbeatSurfaceEnabledBody):
    """Turn a surface heartbeat ON or OFF (opt-in) for the CURRENT account.

    Surface heartbeats are seeded OFF (they run agent passes on the realtor's
    box). The realtor opts in here. This flips the AUTHORITATIVE cron job via the
    canonical resume/pause paths — ``resume_job`` recomputes a fresh future
    ``next_run_at`` so an enabled heartbeat actually schedules and never gets
    stuck — then mirrors ``enabled`` into the surface config (account DB).
    """
    try:
        from cron.jobs import list_jobs, pause_job, resume_job

        want = bool(body.enabled)
        surface_key = (surface or "").strip()
        if not surface_key:
            raise HTTPException(status_code=400, detail="surface is required")

        # A surface's heartbeat is split into several FOCUSED crons — flip ALL of
        # them so the card toggle controls the whole surface (account-scoped).
        surface_jobs = [
            j
            for j in list_jobs(include_disabled=True)
            if (j.get("origin") or {}).get("type") == "surface-heartbeat"
            and (j.get("origin") or {}).get("surface") == surface_key
        ]
        if not surface_jobs:
            raise HTTPException(
                status_code=404,
                detail=f"No heartbeat job for surface '{surface_key}'",
            )

        # Flip each via the canonical cron paths (resume recomputes next_run_at).
        updated = None
        for job in surface_jobs:
            if want:
                updated = resume_job(job["id"]) or updated
            else:
                updated = (
                    pause_job(job["id"], reason="surface heartbeat disabled by realtor")
                    or updated
                )
        if not updated:
            raise HTTPException(status_code=404, detail="Job not found")

        # Keep the surface config (account DB) in sync so it never drifts from the job.
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                surface_state.patch_config(conn, surface_key, {"enabled": want})
        except Exception:
            # Job state is authoritative; a config write hiccup is non-fatal.
            _log.warning("heartbeat %s: config enabled sync failed", surface_key, exc_info=True)

        _fs_cache_invalidate("surfaces")  # reflect the toggle immediately
        return {"surface": surface_key, "enabled": bool(updated.get("enabled", want))}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/heartbeats/surfaces/%s/enabled failed", surface)
        raise HTTPException(status_code=500, detail=f"Heartbeat toggle failed: {exc}")


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Allowlist of per-surface heartbeat settings the dashboard may edit. The
# backend still stores these under ``surface`` workspaces, but the UI presents
# them as ordinary heartbeats.
_SURFACE_CONFIG_EDITABLE = {
    "goal",
    "cadence",
    "agent",
    "model",
    "timezone",
    "day_mode_start",
    "day_mode_end",
    "communication_style",
    "approval_rules",
    "max_session_seconds",
    "heartbeat_report_mode",
}


def _normalize_heartbeat_report_mode(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw in {"notify", "notifying", "always", "always-notify", "every-run", "report"}:
        return "notify"
    if raw in {"quiet", "silent", "changes", "change-only", "important", "important-only"}:
        return "quiet"
    raise HTTPException(
        status_code=400,
        detail="heartbeat_report_mode must be quiet or notify",
    )


@app.get("/api/heartbeats/surfaces/{surface}/config")
def get_heartbeat_surface_config(surface: str):
    """Return a surface's config (account DB) plus its current day/night mode. Read-only."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.jobs import day_night_mode
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            cfg: Dict[str, Any] = surface_state.get_config(conn, surface_key)
        if not str(cfg.get("agent") or "").strip():
            try:
                from cron.jobs import resolve_surface_agent

                inferred_agent = resolve_surface_agent(surface_key, {"config": cfg})
                if inferred_agent:
                    cfg["agent"] = inferred_agent
            except Exception:
                pass
        return {"surface": surface_key, "config": cfg, "mode": day_night_mode(cfg)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/surfaces/%s/config failed", surface)
        raise HTTPException(status_code=500, detail=f"Get surface config failed: {exc}")


class _HeartbeatConfigPatchBody(BaseModel):
    goal: Optional[str] = None
    cadence: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    timezone: Optional[str] = None
    day_mode_start: Optional[str] = None
    day_mode_end: Optional[str] = None
    communication_style: Optional[str] = None
    approval_rules: Optional[Dict[str, Any]] = None
    max_session_seconds: Optional[int] = None
    heartbeat_report_mode: Optional[str] = None
    report_mode: Optional[str] = None
    notification_mode: Optional[str] = None


@app.patch("/api/heartbeats/surfaces/{surface}/config")
def patch_heartbeat_surface_config(surface: str, body: _HeartbeatConfigPatchBody):
    """Allowlist-merge editable settings into a surface's config (account DB).

    Mirrors job-owned fields (cadence, agent, model) onto the surface heartbeat
    cron job so the settings are functional, not just prompt-visible.
    """
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from cron.jobs import day_night_mode

        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        mode_value = None
        for alias in ("heartbeat_report_mode", "report_mode", "notification_mode"):
            if alias in patch:
                mode_value = patch.pop(alias)
                break
        if mode_value is not None:
            patch["heartbeat_report_mode"] = _normalize_heartbeat_report_mode(mode_value)
        if "goal" in patch and not str(patch["goal"]).strip():
            raise HTTPException(status_code=400, detail="goal is required")
        if "cadence" in patch:
            cadence = str(patch["cadence"]).strip()
            if not cadence:
                raise HTTPException(status_code=400, detail="cadence is required")
            try:
                from cron.jobs import parse_schedule

                parse_schedule(cadence)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"invalid cadence: {exc}")
            patch["cadence"] = cadence
        # Validate time windows.
        for k in ("day_mode_start", "day_mode_end"):
            if k in patch and not _HHMM_RE.match(str(patch[k])):
                raise HTTPException(status_code=400, detail=f"{k} must be HH:MM (00:00–23:59)")
        # Validate approval_rules shape: {always_ask:[...], never_ask:[...]}.
        if "approval_rules" in patch:
            ar = patch["approval_rules"]
            if not isinstance(ar, dict):
                raise HTTPException(status_code=400, detail="approval_rules must be an object")
            for bucket in ("always_ask", "never_ask"):
                if bucket in ar and not isinstance(ar[bucket], list):
                    raise HTTPException(
                        status_code=400, detail=f"approval_rules.{bucket} must be a list"
                    )
        # Only allowlisted keys survive (belt-and-suspenders over the typed body).
        patch = {k: v for k, v in patch.items() if k in _SURFACE_CONFIG_EDITABLE}

        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            # Shallow merge: preserves goal/cadence/experiment/cycles/playbook
            # and every other non-allowlisted key already in the config.
            cfg: Dict[str, Any] = surface_state.patch_config(conn, surface_key, patch)
        job_updates: Dict[str, Any] = {}
        if "model" in patch:
            job_updates["model"] = patch.get("model") or None
        if "agent" in patch:
            job_updates["agent"] = patch.get("agent") or None
        if "cadence" in patch:
            job_updates["schedule"] = patch["cadence"]
        if "heartbeat_report_mode" in patch:
            job = _surface_heartbeat_job(surface_key)
            metadata = job.get("metadata") if isinstance((job or {}).get("metadata"), dict) else {}
            job_updates["metadata"] = {
                **metadata,
                "heartbeat_report_mode": patch["heartbeat_report_mode"],
            }
        if job_updates:
            from cron.jobs import update_job

            job = _surface_heartbeat_job(surface_key)
            if job:
                update_job(job["id"], job_updates)
        _fs_cache_invalidate("surfaces")  # reflect edited settings immediately
        return {"surface": surface_key, "config": cfg, "mode": day_night_mode(cfg)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PATCH /api/heartbeats/surfaces/%s/config failed", surface)
        raise HTTPException(status_code=500, detail=f"Update surface config failed: {exc}")


def _read_surface_goals(surface_key: str) -> Dict[str, Any]:
    """Read + normalize a surface's goals (account DB). Tolerant: coerces legacy
    string goal entries into the rich {id,title,progress,order} shape."""
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        data: Dict[str, Any] = surface_state.get_goals(conn, surface_key)
    raw_goals = data.get("goals") if isinstance(data.get("goals"), list) else []
    goals: List[Dict[str, Any]] = []
    for i, g in enumerate(raw_goals):
        if isinstance(g, str):
            goals.append({"id": f"g{i}", "title": g, "progress": 0, "order": i})
        elif isinstance(g, dict) and g.get("title"):
            goals.append({
                "id": str(g.get("id") or f"g{i}"),
                "title": str(g["title"])[:200],
                "progress": max(0, min(100, int(g.get("progress") or 0))),
                "order": int(g.get("order") if g.get("order") is not None else i),
            })
    goals.sort(key=lambda x: x["order"])
    return {
        "bottleneck": str(data.get("bottleneck") or ""),
        "daily_focus": str(data.get("daily_focus") or ""),
        "daily_focus_set_at": data.get("daily_focus_set_at"),
        "goals": goals,
        "updated_at": data.get("updated_at"),
    }


@app.get("/api/heartbeats/surfaces/{surface}/goals")
def get_heartbeat_surface_goals(surface: str):
    """Return a surface's goals (north-star focus + bottleneck + rich goal list)."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        return {"surface": surface_key, **_read_surface_goals(surface_key)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/heartbeats/surfaces/%s/goals failed", surface)
        raise HTTPException(status_code=500, detail=f"Get goals failed: {exc}")


class _HeartbeatGoalItem(BaseModel):
    id: Optional[str] = None
    title: str
    progress: Optional[int] = None
    order: Optional[int] = None


class _HeartbeatGoalsPatchBody(BaseModel):
    bottleneck: Optional[str] = None
    daily_focus: Optional[str] = None
    goals: Optional[List[_HeartbeatGoalItem]] = None


@app.patch("/api/heartbeats/surfaces/{surface}/goals")
def patch_heartbeat_surface_goals(surface: str, body: _HeartbeatGoalsPatchBody):
    """Replace goals[] / set bottleneck / set daily_focus. Validates title length,
    clamps progress 0-100, mints ids + order, stamps updated_at. Appends a history row."""
    try:
        surface_key = _validate_heartbeat_surface(surface)
        from datetime import datetime, timezone

        current = _read_surface_goals(surface_key)
        now_iso = datetime.now(timezone.utc).isoformat()
        if body.bottleneck is not None:
            current["bottleneck"] = body.bottleneck.strip()
        if body.daily_focus is not None:
            new_focus = body.daily_focus.strip()
            if new_focus != current.get("daily_focus"):
                current["daily_focus_set_at"] = now_iso
            current["daily_focus"] = new_focus
        if body.goals is not None:
            cleaned: List[Dict[str, Any]] = []
            for i, g in enumerate(body.goals):
                title = (g.title or "").strip()
                if not title:
                    continue
                if len(title) > 200:
                    raise HTTPException(status_code=400, detail="goal title max 200 chars")
                cleaned.append({
                    "id": str(g.id or f"g{int(time.time())}_{secrets.token_hex(2)}"),
                    "title": title,
                    "progress": max(0, min(100, int(g.progress or 0))),
                    "order": int(g.order if g.order is not None else i),
                })
            cleaned.sort(key=lambda x: x["order"])
            for i, g in enumerate(cleaned):
                g["order"] = i
            current["goals"] = cleaned
        current["updated_at"] = now_iso

        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            # set_goals appends the history row itself (the old goals_history.jsonl).
            surface_state.set_goals(conn, surface_key, current)
        return {"surface": surface_key, **current}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PATCH /api/heartbeats/surfaces/%s/goals failed", surface)
        raise HTTPException(status_code=500, detail=f"Update goals failed: {exc}")



class _HeartbeatAutomationEnabledBody(BaseModel):
    enabled: bool


@app.post("/api/heartbeats/automations/{job_id}/enabled")
def set_heartbeat_automation_enabled(job_id: str, body: _HeartbeatAutomationEnabledBody):
    """Turn a single surface AUTOMATION on or off for the CURRENT account.

    Surface automations are the per-surface "kit" cron jobs that pair with each
    surface heartbeat (``origin.type == "surface-automation"``). They ship OFF
    (opt-in) and the realtor flips one here. This reuses the EXACT same cron
    enable/disable path as ``set_heartbeat_surface_enabled`` — ``resume_job``
    (recomputes a fresh ``next_run_at`` so it actually schedules) / ``pause_job``.

    Safety: refuses to toggle any job that is NOT a ``surface-automation`` job, so
    this endpoint can never be used to flip arbitrary cron jobs.
    """
    try:
        from cron.jobs import get_job, pause_job, resume_job

        want = bool(body.enabled)
        job_ref = (job_id or "").strip()
        if not job_ref:
            raise HTTPException(status_code=400, detail="job_id is required")

        # Look up by ID and verify it's a surface-automation job before touching it.
        job = get_job(job_ref)
        if not job:
            raise HTTPException(status_code=404, detail=f"No job '{job_ref}'")
        origin = job.get("origin") or {}
        if origin.get("type") != "surface-automation":
            raise HTTPException(
                status_code=400,
                detail="Job is not a surface automation",
            )

        # Flip via the canonical cron paths (resume recomputes next_run_at) — the
        # same path the surface-heartbeat toggle uses.
        if want:
            updated = resume_job(job["id"])
        else:
            updated = pause_job(job["id"], reason="surface automation disabled by realtor")
        if not updated:
            raise HTTPException(status_code=404, detail="Job not found")

        return {"id": job["id"], "enabled": bool(updated.get("enabled", want))}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/heartbeats/automations/%s/enabled failed", job_id)
        raise HTTPException(status_code=500, detail=f"Automation toggle failed: {exc}")



# ---------------------------------------------------------------------------
# /api/pty — PTY-over-WebSocket bridge for the dashboard "Chat" tab.
#
# The endpoint spawns the same ``elevate --tui`` binary the CLI uses, behind
# a POSIX pseudo-terminal, and forwards bytes + resize escapes across a
# WebSocket.  The browser renders the ANSI through xterm.js (see
# web/src/pages/ChatPage.tsx).
#
# Auth: ``?token=<session_token>`` query param (browsers can't set
# Authorization on the WS upgrade).  Same ephemeral ``_SESSION_TOKEN`` as
# REST.  Localhost-only — we defensively reject non-loopback clients even
# though uvicorn binds to 127.0.0.1.
# ---------------------------------------------------------------------------

import re
import asyncio

from elevate_cli.pty_bridge import PtyBridge, PtyUnavailableError

_RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")
_PTY_READ_CHUNK_TIMEOUT = 0.2
_VALID_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Starlette's TestClient reports the peer as "testclient"; treat it as
# loopback so tests don't need to rewrite request scope.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

# Per-channel subscriber registry used by /api/pub (PTY-side gateway → dashboard)
# and /api/events (dashboard → browser sidebar).  Keyed by an opaque channel id
# the chat tab generates on mount; entries auto-evict when the last subscriber
# drops AND the publisher has disconnected.
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()


def _resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Resolve the argv + cwd + env for the chat PTY.

    Default: whatever ``elevate --tui`` would run.  Tests monkeypatch this
    function to inject a tiny fake command (``cat``, ``sh -c 'printf …'``)
    so nothing has to build Node or the TUI bundle.

    Session resume is propagated via the ``ELEVATE_TUI_RESUME`` env var —
    matching what ``elevate_cli.main._launch_tui`` does for the CLI path.
    Appending ``--resume <id>`` to argv doesn't work because ``ui-tui`` does
    not parse its argv.

    `sidecar_url` (when set) is forwarded as ``ELEVATE_TUI_SIDECAR_URL`` so
    the spawned ``tui_gateway.entry`` can mirror dispatcher emits to the
    dashboard's ``/api/pub`` endpoint (see :func:`pub_ws`).
    """
    from elevate_cli.main import PROJECT_ROOT, _make_tui_argv

    argv, cwd = _make_tui_argv(PROJECT_ROOT / "ui-tui", tui_dev=False)
    env = os.environ.copy()
    env["ELEVATE_PYTHON_SRC_ROOT"] = os.environ.get(
        "ELEVATE_PYTHON_SRC_ROOT", str(PROJECT_ROOT)
    )
    env.setdefault("ELEVATE_PYTHON", sys.executable)
    env.setdefault("ELEVATE_CWD", os.getcwd())

    if resume:
        env["ELEVATE_TUI_RESUME"] = resume

    if sidecar_url:
        env["ELEVATE_TUI_SIDECAR_URL"] = sidecar_url

    return list(argv), str(cwd) if cwd else None, env


def _build_sidecar_url(channel: str) -> Optional[str]:
    """ws:// URL the PTY child should publish events to, or None when unbound."""
    host = getattr(app.state, "bound_host", None)
    port = getattr(app.state, "bound_port", None)

    if not host or not port:
        return None

    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    qs = urllib.parse.urlencode({"token": _SESSION_TOKEN, "channel": channel})

    return f"ws://{netloc}/api/pub?{qs}"


async def _broadcast_event(channel: str, payload: str) -> None:
    """Fan out one publisher frame to every subscriber on `channel`."""
    async with _event_lock:
        subs = list(_event_channels.get(channel, ()))

    for sub in subs:
        try:
            await sub.send_text(payload)
        except Exception:
            # Subscriber went away mid-send; the /api/events finally clause
            # will remove it from the registry on its next iteration.
            pass


def _channel_or_close_code(ws: WebSocket) -> Optional[str]:
    """Return the channel id from the query string or None if invalid."""
    channel = ws.query_params.get("channel", "")

    return channel if _VALID_CHANNEL_RE.match(channel) else None


@app.websocket("/api/pty")
async def pty_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    # --- auth + loopback check (before accept so we can close cleanly) ---
    token = ws.query_params.get("token", "")
    expected = _SESSION_TOKEN
    if not hmac.compare_digest(token.encode(), expected.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    await ws.accept()

    # --- license gate ---------------------------------------------------
    # The chat refuses to start until the user has signed in. We render a
    # short, themed banner in the terminal pane and close cleanly so the
    # user sees the message in their chat panel and clicks the link to
    # sign in. Re-opening the chat after signing in works without an
    # app restart because this check happens per-connection.
    if client_host != "testclient" and not _license_signed_in():
        banner = (
            "\r\n"
            "\x1b[38;5;215m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m\r\n"
            "\x1b[1m  Sign in to start chatting\x1b[0m\r\n"
            "\r\n"
            "  Open the Sign In window from the Elevate menu\r\n"
            "  (or press \x1b[1m\xe2\x8c\x98L\x1b[0m) and use your Elevation Real\r\n"
            "  Estate HQ account. Reopen this chat when done.\r\n"
            "\x1b[38;5;215m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m\r\n"
            "\r\n"
        )
        await ws.send_text(banner)
        await ws.close(code=1000)
        return

    # --- spawn PTY ------------------------------------------------------
    resume = ws.query_params.get("resume") or None
    channel = _channel_or_close_code(ws)
    sidecar_url = _build_sidecar_url(channel) if channel else None

    try:
        argv, cwd, env = _resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)
    except SystemExit as exc:
        # _make_tui_argv calls sys.exit(1) when node/npm is missing.
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return


    try:
        bridge = PtyBridge.spawn(argv, cwd=cwd, env=env)
    except PtyUnavailableError as exc:
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return
    except (FileNotFoundError, OSError) as exc:
        await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return

    loop = asyncio.get_running_loop()

    # --- reader task: PTY master → WebSocket ----------------------------
    async def pump_pty_to_ws() -> None:
        while True:
            chunk = await loop.run_in_executor(
                None, bridge.read, _PTY_READ_CHUNK_TIMEOUT
            )
            if chunk is None:  # EOF
                return
            if not chunk:  # no data this tick; yield control and retry
                await asyncio.sleep(0)
                continue
            try:
                await ws.send_bytes(chunk)
            except Exception:
                return

    reader_task = asyncio.create_task(pump_pty_to_ws())

    # --- writer loop: WebSocket → PTY master ----------------------------
    try:
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw is None:
                text = msg.get("text")
                raw = text.encode("utf-8") if isinstance(text, str) else b""
            if not raw:
                continue

            # Resize escape is consumed locally, never written to the PTY.
            match = _RESIZE_RE.match(raw)
            if match and match.end() == len(raw):
                cols = int(match.group(1))
                rows = int(match.group(2))
                bridge.resize(cols=cols, rows=rows)
                continue

            bridge.write(raw)
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        bridge.close()


# ---------------------------------------------------------------------------
# /api/ws — JSON-RPC WebSocket sidecar for the dashboard "Chat" tab.
#
# Drives the same `tui_gateway.dispatch` surface Ink uses over stdio, so the
# dashboard can render structured metadata (model badge, tool-call sidebar,
# slash launcher, session info) alongside the xterm.js terminal that PTY
# already paints. Both transports bind to the same session id when one is
# active, so a tool.start emitted by the agent fans out to both sinks.
# ---------------------------------------------------------------------------


@app.websocket("/api/ws")
async def gateway_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    from tui_gateway.ws import handle_ws

    try:
        await handle_ws(ws)
    except RuntimeError as exc:
        _log.debug("Chat sidecar websocket closed before handshake completed: %s", exc)


# ---------------------------------------------------------------------------
# /api/pub + /api/events — chat-tab event broadcast.
#
# The PTY-side ``tui_gateway.entry`` opens /api/pub at startup (driven by
# ELEVATE_TUI_SIDECAR_URL set in /api/pty's PTY env) and writes every
# dispatcher emit through it.  The dashboard fans those frames out to any
# subscriber that opened /api/events on the same channel id.  This is what
# gives the React sidebar its tool-call feed without breaking the PTY
# child's stdio handshake with Ink.
# ---------------------------------------------------------------------------


@app.websocket("/api/pub")
async def pub_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    try:
        while True:
            await _broadcast_event(channel, await ws.receive_text())
    except WebSocketDisconnect:
        pass


@app.websocket("/api/events")
async def events_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    async with _event_lock:
        _event_channels.setdefault(channel, set()).add(ws)

    try:
        while True:
            # Subscribers don't speak — the receive() just blocks until
            # disconnect so the connection stays open as long as the
            # browser holds it.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _event_lock:
            subs = _event_channels.get(channel)

            if subs is not None:
                subs.discard(ws)

                if not subs:
                    _event_channels.pop(channel, None)


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.
    """
    if not WEB_DIST.exists():
        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )
        return

    _index_path = WEB_DIST / "index.html"

    def _serve_index():
        """Return index.html with the session token injected."""
        html = _index_path.read_text()
        chat_js = "true" if _DASHBOARD_EMBEDDED_CHAT_ENABLED else "false"
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
            f'<script>window.__ELEVATE_SESSION_TOKEN__="{_SESSION_TOKEN}";'
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
            _SESSION_TOKEN,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return resp

    application.mount("/assets", ImmutableStaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
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


mount_dashboard_plugin_api_routes(app, project_root=PROJECT_ROOT, log=_log)

mount_spa(app)


# ---------------------------------------------------------------------------
# Cloud-skill sync — startup + hourly heartbeat.
#
# Skills live server-side, gated by tier + entitlements. The CLI keeps a local
# mirror at ~/.elevate/cloud-skills/. We sync:
#   - on every gateway boot (so server-side version bumps land after restart)
#   - every hour while running (so entitlement flips on HQ propagate without
#     forcing the user to re-activate or restart the app)
# Both paths swallow errors so a flaky network never blocks the gateway.
# ---------------------------------------------------------------------------

_CLOUD_SKILL_SYNC_INTERVAL_S = int(os.environ.get("ELEVATE_CLOUD_SKILL_SYNC_INTERVAL_S", "3600"))


def _cloud_skill_sync_once(reason: str) -> None:
    try:
        from elevate_cli import license as lic_mod
        from elevate_cli import cloud_skills
    except Exception as exc:
        _log.debug("cloud-skill sync (%s): import failed: %s", reason, exc)
        return

    lic = lic_mod.load()
    if not lic:
        _log.debug("cloud-skill sync (%s): no license, skipping", reason)
        return

    try:
        if lic.is_expired():
            lic = lic_mod.refresh(lic)
    except Exception as exc:
        _log.info("cloud-skill sync (%s): license refresh failed: %s", reason, exc)
        return

    try:
        result = cloud_skills.sync_all()
    except Exception as exc:
        _log.info("cloud-skill sync (%s): sync failed: %s", reason, exc)
        return

    _log.info(
        "cloud-skill sync (%s): %d skills, %d removed, %d errors",
        reason,
        result.get("skill_count", 0),
        len(result.get("removed", []) or []),
        len(result.get("errors", []) or []),
    )


async def _cloud_skill_heartbeat() -> None:
    while True:
        try:
            await asyncio.sleep(_CLOUD_SKILL_SYNC_INTERVAL_S)
        except asyncio.CancelledError:
            return
        await asyncio.get_running_loop().run_in_executor(None, _cloud_skill_sync_once, "heartbeat")


@app.on_event("startup")
async def _kickoff_cloud_skill_sync() -> None:
    loop = asyncio.get_running_loop()
    # Run the first sync off the event loop so a slow network doesn't delay
    # the gateway accepting connections.
    loop.run_in_executor(None, _cloud_skill_sync_once, "startup")
    app.state.cloud_skill_heartbeat_task = loop.create_task(_cloud_skill_heartbeat())


@app.on_event("shutdown")
async def _stop_cloud_skill_heartbeat() -> None:
    task = getattr(app.state, "cloud_skill_heartbeat_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def start_server(
    host: str = "127.0.0.1",
    port: int = 9119,
    open_browser: bool = True,
    allow_public: bool = False,
    *,
    embedded_chat: bool = False,
):
    """Start the web UI server."""
    import uvicorn

    global _DASHBOARD_EMBEDDED_CHAT_ENABLED
    _DASHBOARD_EMBEDDED_CHAT_ENABLED = embedded_chat

    _LOCALHOST = ("127.0.0.1", "localhost", "::1")
    if host not in _LOCALHOST and not allow_public:
        raise SystemExit(
            f"Refusing to bind to {host} — the dashboard exposes API keys "
            f"and config without robust authentication.\n"
            f"Use --insecure to override (NOT recommended on untrusted networks)."
        )
    if host not in _LOCALHOST:
        _log.warning(
            "Binding to %s with --insecure — the dashboard has no robust "
            "authentication. Only use on trusted networks.", host,
        )

    # Record the bound host so host_header_middleware can validate incoming
    # Host headers against it. Defends against DNS rebinding (GHSA-ppp5-vxwm-4cf7).
    # bound_port is also stashed so /api/pty can build the back-WS URL the
    # PTY child uses to publish events to the dashboard sidebar.
    app.state.bound_host = host
    app.state.bound_port = port

    if open_browser:
        import webbrowser

        def _open():
            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Elevate Web UI → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
