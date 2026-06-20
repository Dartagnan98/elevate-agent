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
from elevate_cli.web_routes.chat_websockets import (
    create_chat_websocket_router,
    default_resolve_chat_argv,
)
from elevate_cli.web_routes.composio import create_composio_router
from elevate_cli.web_routes.config import create_config_router
from elevate_cli.web_routes.cron import create_cron_router
from elevate_cli.web_routes.dashboard import create_dashboard_router, mount_dashboard_plugin_api_routes
from elevate_cli.web_routes.env import create_env_router
from elevate_cli.web_routes.files import create_files_router
from elevate_cli.web_routes.heartbeats import create_heartbeats_router
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
from elevate_cli.web_spa import mount_spa as _mount_spa
from elevate_cli.pty_bridge import PtyBridge, PtyUnavailableError

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


def _resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    return default_resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)


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
app.include_router(
    create_heartbeats_router(
        fs_cache_get=_fs_cache_get,
        fs_cache_put=_fs_cache_put,
        fs_cache_invalidate=_fs_cache_invalidate,
        log=_log,
    )
)

app.include_router(
    create_chat_websocket_router(
        embedded_chat_enabled=lambda: _DASHBOARD_EMBEDDED_CHAT_ENABLED,
        session_token=lambda: _SESSION_TOKEN,
        bound_host=lambda: getattr(app.state, "bound_host", None),
        bound_port=lambda: getattr(app.state, "bound_port", None),
        license_signed_in=_license_signed_in,
        resolve_chat_argv=lambda resume=None, sidecar_url=None: _resolve_chat_argv(
            resume=resume,
            sidecar_url=sidecar_url,
        ),
        pty_bridge_class=lambda: PtyBridge,
        pty_unavailable_error_class=lambda: PtyUnavailableError,
        log=_log,
    )
)



def mount_spa(application: FastAPI):
    _mount_spa(
        application,
        web_dist=WEB_DIST,
        static_files_class=ImmutableStaticFiles,
        session_token=_SESSION_TOKEN,
        embedded_chat_enabled=lambda: _DASHBOARD_EMBEDDED_CHAT_ENABLED,
    )


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
