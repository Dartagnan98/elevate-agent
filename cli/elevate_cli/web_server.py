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
from elevate_cli.data.deals import DealPhaseGateBlocked

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
from elevate_cli.web_routes.analytics import create_analytics_router
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

app.include_router(create_threads_router(log=_log))

app.include_router(create_today_router(log=_log))

# ---------------------------------------------------------------------------
# Sprint 3: lifecycle UX (classify, park, active leads, admin contacts,
# identity conflicts, lead signal graduate). Single-user product so every
# UI mutation is attributed to ``human:web``. Agents that mutate via
# scheduled jobs use their own actor strings ("agent:autopilot", etc).
# ---------------------------------------------------------------------------

_WEB_ACTOR = "human:web"

_ADMIN_CONTACTS_TAB_FILTERS = {
    "all": {},
    "buyers": {"type": "buyer"},
    "listings": {"type": "listing"},
    "parked": {"stage": "parked"},
    "dormant": {"stage": "dormant"},
    "dead": {"stage": "dead"},
}


class _ContactClassifyBody(BaseModel):
    type: str  # 'buyer' | 'listing' | 'other'


class _ContactParkBody(BaseModel):
    reason: str


class _ConflictResolveBody(BaseModel):
    resolution: str  # 'merged_into:<contact_id>' | 'kept_separate' | 'discarded'


class _SignalGraduateBody(BaseModel):
    contactId: str


class _TemplateRejectBody(BaseModel):
    reason: str


class _TemplateEditBody(BaseModel):
    body: str


class _DealCreateBody(BaseModel):
    title: str
    side: str
    # Optional package selectors. If omitted, the configured deal-flow defaults are used.
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    primaryContactId: Optional[str] = None
    loftyContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    dispatchInitialStage: bool = True
    suppressInitialDispatch: bool = False


class _ProfilePromotionBody(BaseModel):
    profileId: str
    side: str
    displayName: Optional[str] = None
    primaryContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    workflow: Optional[str] = None
    # Optional package selectors. If omitted, the configured deal-flow defaults are used.
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    profileContext: Dict[str, Any] = Field(default_factory=dict)
    verifiers: List[Dict[str, Any]] = Field(default_factory=list)
    fields: Dict[str, Any] = Field(default_factory=dict)
    dispatchInitialStage: bool = True


class _AdminJurisdictionBody(BaseModel):
    country: Optional[str] = None
    province: Optional[str] = None
    market: Optional[str] = None
    packageKey: Optional[str] = None
    package_key: Optional[str] = None


class _AdminSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _AdminSetupUpdateBody(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    items: List[_AdminSetupItemBody] = []


class _PackOnboardingItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _PackOnboardingUpdateBody(BaseModel):
    items: List[_PackOnboardingItemBody] = []


class _LeadsSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _LeadsSetupUpdateBody(BaseModel):
    items: List[_LeadsSetupItemBody] = []


class _AgentSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _AgentSetupUpdateBody(BaseModel):
    items: List[_AgentSetupItemBody] = []


class _OnboardingChatMessage(BaseModel):
    role: str
    content: str


class _OnboardingChatBody(BaseModel):
    messages: List[_OnboardingChatMessage] = []


class _OnboardingBrowserUseBody(BaseModel):
    portalKey: str  # mls | compliance | showing
    taskHint: Optional[str] = None


class _DealMoveBody(BaseModel):
    toStage: int
    force: bool = False


class _DealToggleBody(BaseModel):
    field: str
    value: Any


class _DealContactBody(BaseModel):
    role: str
    contactId: str
    notes: Optional[str] = None


class _DealAttachmentBody(BaseModel):
    kind: str
    filePath: str
    summary: Optional[str] = None
    sourceRunId: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _DealFieldsBody(BaseModel):
    fields: Dict[str, Any]


class _RunResultArtifact(BaseModel):
    kind: str
    file_path: Optional[str] = None
    filePath: Optional[str] = None
    summary: Optional[str] = None
    source_snapshot_id: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _RunResultBody(BaseModel):
    status: str
    idempotency_key: Optional[str] = None
    idempotencyKey: Optional[str] = None
    artifacts: List[_RunResultArtifact] = []
    next_tasks: List[Dict[str, Any]] = []
    nextTasks: List[Dict[str, Any]] = []
    checklist_updates: List[Dict[str, Any]] = []
    checklistUpdates: List[Dict[str, Any]] = []
    human_prompt: Optional[Dict[str, Any]] = None
    humanPrompt: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class _DealAdvanceBody(BaseModel):
    force: bool = False


class _AdminTaskRunBody(BaseModel):
    dealId: str
    skill: str
    title: Optional[str] = None
    sourceTaskId: Optional[str] = None
    runNow: bool = True


class _ProvinceGuideImportBody(BaseModel):
    root: Optional[str] = None
    province: Optional[str] = None
    pruneOtherProvinces: bool = False


class _ActionRunApproveBody(BaseModel):
    approved: bool = True
    runNow: bool = True


class _AdminActionCreateBody(BaseModel):
    name: str
    trigger: str
    skill: str
    side: Optional[str] = None
    fromStage: Optional[int] = None
    toStage: Optional[int] = None
    fieldKey: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    skillArgs: Optional[Dict[str, Any]] = None
    provinceFilter: Optional[List[str]] = None
    enabled: bool = True
    priority: int = 0
    approvalRequired: bool = False


class _AdminActionUpdateBody(BaseModel):
    name: Optional[str] = None
    trigger: Optional[str] = None
    skill: Optional[str] = None
    side: Optional[str] = None
    fromStage: Optional[int] = None
    toStage: Optional[int] = None
    fieldKey: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    skillArgs: Optional[Dict[str, Any]] = None
    provinceFilter: Optional[List[str]] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    approvalRequired: Optional[bool] = None


_ADMIN_TEMPLATES_TABS = {"live", "proposed", "retired"}


def _clean_admin_jurisdiction_value(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text


def _admin_jurisdiction_config() -> Dict[str, str]:
    """Return Admin Hub deal-flow defaults.

    Product onboarding is the canonical source after a profile exists; config is
    only the fallback/override layer for package keys and fresh installs.
    """
    from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

    real_estate = (load_config().get("real_estate") or {})
    setup_profile: Dict[str, Any] = {}
    try:
        from elevate_cli.data import connect, get_admin_setup

        with connect() as conn:
            setup_profile = (get_admin_setup(conn).get("profile") or {})
    except Exception:
        setup_profile = {}

    country = _clean_admin_jurisdiction_value(
        setup_profile.get("country") or real_estate.get("country"),
        "CA",
    ).upper()
    province = _clean_admin_jurisdiction_value(
        setup_profile.get("province") or real_estate.get("province"),
        "",
    ).upper()
    market = _clean_admin_jurisdiction_value(
        setup_profile.get("market") or real_estate.get("market"),
        "",
    )
    package_key = package_key_from_jurisdiction(
        country=country,
        province=province,
        package_key=real_estate.get("package_key") or real_estate.get("packageKey"),
    )
    return {
        "country": country,
        "province": province,
        "market": market,
        "packageKey": package_key,
    }


def _require_admin_setup_ready_for_launch() -> None:
    """Block Admin launch/mutation endpoints until the setup gate is complete."""
    from elevate_cli.data import connect, get_admin_setup

    with connect() as conn:
        setup = get_admin_setup(conn)
    if setup.get("complete"):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": "Admin setup must be completed before starting admin work.",
            "setup": setup,
        },
    )


def _admin_setup_runtime_env_values() -> Dict[str, str]:
    env_values: Dict[str, str] = {
        str(key): str(value)
        for key, value in load_env().items()
        if value is not None
    }
    for key, value in os.environ.items():
        if value:
            env_values[key] = value
    return env_values


def _mirror_admin_setup_portal_env(items: List["_AdminSetupItemBody"]) -> None:
    """Persist onboarding portal login fields into the runtime .env file.

    The Admin wizard owns the browser playbook, but SkySlope/MLS scripts read
    env vars. Mirroring non-empty values here keeps onboarding and runtime from
    drifting without ever clearing an existing credential when the user leaves a
    password box blank.
    """
    try:
        from elevate_cli.portal_credentials import (
            portal_env_updates_from_playbooks,
            portal_playbooks_for_storage,
        )
    except Exception:
        _log.exception("admin setup portal env mirror: helper import failed")
        return

    for item in items:
        if item.key != "browser_workflows" or not isinstance(item.value, dict):
            continue
        playbooks = item.value.get("playbooks")
        updates = portal_env_updates_from_playbooks(playbooks if isinstance(playbooks, dict) else {})
        for key, value in updates.items():
            save_env_value(key, value)
        item.value["playbooks"] = portal_playbooks_for_storage(
            playbooks if isinstance(playbooks, dict) else {}
        )
        if updates:
            _log.info(
                "admin setup portal env mirror: saved %s",
                ", ".join(sorted(updates)),
            )


app.include_router(
    create_agent_hub_router(
        require_admin_setup_ready_for_launch=_require_admin_setup_ready_for_launch,
        log=_log,
    )
)


@app.post("/api/contacts/{contact_id}/classify")
def post_contact_classify(contact_id: str, body: _ContactClassifyBody):
    try:
        from elevate_cli.data import classify_contact, connect, get_contact

        with connect() as conn:
            if get_contact(conn, contact_id) is None:
                raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
            return classify_contact(conn, contact_id, body.type, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/contacts/%s/classify failed", contact_id)
        raise HTTPException(status_code=500, detail=f"Classify failed: {exc}")


@app.post("/api/contacts/{contact_id}/park")
def post_contact_park(contact_id: str, body: _ContactParkBody):
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=400, detail="reason is required")
    try:
        from elevate_cli.data import connect, get_contact, park_contact

        with connect() as conn:
            if get_contact(conn, contact_id) is None:
                raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
            return park_contact(conn, contact_id, body.reason.strip(), actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/contacts/%s/park failed", contact_id)
        raise HTTPException(status_code=500, detail=f"Park failed: {exc}")


@app.post("/api/contacts/{contact_id}/unpark")
def post_contact_unpark(contact_id: str):
    try:
        from elevate_cli.data import connect, get_contact, unpark_contact

        with connect() as conn:
            if get_contact(conn, contact_id) is None:
                raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
            return unpark_contact(conn, contact_id, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/contacts/%s/unpark failed", contact_id)
        raise HTTPException(status_code=500, detail=f"Unpark failed: {exc}")


@app.get("/api/contacts/active")
def get_contacts_active(limit: int = 100):
    """Active leads section — stage in ('first_touched', 'active'),
    sorted by ``last_activity_at`` desc."""
    try:
        from elevate_cli.data import connect, find_contacts

        safe_limit = max(1, min(500, int(limit)))
        with connect() as conn:
            rows = find_contacts(
                conn,
                stage_in=("first_touched", "active"),
                limit=safe_limit,
            )
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        _log.exception("GET /api/contacts/active failed")
        raise HTTPException(status_code=500, detail=f"Active contacts failed: {exc}")


@app.get("/api/admin/contacts")
def get_admin_contacts(
    type: Optional[str] = None,
    stage: Optional[str] = None,
    tab: Optional[str] = None,
    lastActivityAfter: Optional[str] = None,
    hasOpenConflict: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Admin contacts list — supports tab presets (All/Buyers/Listings/
    Parked/Dormant/Dead) plus arbitrary type/stage filters that override
    the tab.
    """
    try:
        from elevate_cli.data import connect, find_contacts

        kwargs: Dict[str, Any] = {}
        if tab:
            tab_filter = _ADMIN_CONTACTS_TAB_FILTERS.get(tab.lower())
            if tab_filter is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown tab {tab!r} (expected one of {sorted(_ADMIN_CONTACTS_TAB_FILTERS)})",
                )
            kwargs.update(tab_filter)
        if type is not None:
            kwargs["type"] = type
        if stage is not None:
            kwargs["stage"] = stage
        if hasOpenConflict is not None:
            kwargs["has_open_conflict"] = hasOpenConflict
        if lastActivityAfter is not None:
            kwargs["last_activity_after"] = lastActivityAfter
        kwargs["limit"] = max(1, min(500, int(limit)))
        kwargs["offset"] = max(0, int(offset))

        with connect() as conn:
            rows = find_contacts(conn, **kwargs)
        return {"items": rows, "count": len(rows), "tab": tab, "limit": kwargs["limit"], "offset": kwargs["offset"]}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/contacts failed")
        raise HTTPException(status_code=500, detail=f"Admin contacts failed: {exc}")


@app.get("/api/admin/conflicts")
def get_admin_conflicts():
    try:
        from elevate_cli.data import connect, list_open_conflicts

        with connect() as conn:
            rows = list_open_conflicts(conn)
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        _log.exception("GET /api/admin/conflicts failed")
        raise HTTPException(status_code=500, detail=f"Admin conflicts failed: {exc}")


@app.post("/api/admin/conflicts/{conflict_id}/resolve")
def post_admin_conflict_resolve(conflict_id: str, body: _ConflictResolveBody):
    try:
        from elevate_cli.data import connect, resolve_identity_conflict

        with connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM identity_conflicts WHERE id=?", (conflict_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"conflict {conflict_id!r} not found")
            return resolve_identity_conflict(
                conn, conflict_id, resolution=body.resolution, actor=_WEB_ACTOR
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/conflicts/%s/resolve failed", conflict_id)
        raise HTTPException(status_code=500, detail=f"Resolve conflict failed: {exc}")


@app.get("/api/admin/signals")
def get_admin_signals(sourceId: Optional[str] = None, limit: int = 200):
    try:
        from elevate_cli.data import connect, list_open_signals

        safe_limit = max(1, min(500, int(limit)))
        with connect() as conn:
            rows = list_open_signals(conn, source_id=sourceId, limit=safe_limit)
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        _log.exception("GET /api/admin/signals failed")
        raise HTTPException(status_code=500, detail=f"Admin signals failed: {exc}")


@app.post("/api/admin/signals/{signal_id}/graduate")
def post_admin_signal_graduate(signal_id: str, body: _SignalGraduateBody):
    if not body.contactId or not body.contactId.strip():
        raise HTTPException(status_code=400, detail="contactId is required")
    try:
        from elevate_cli.data import (
            connect,
            get_contact,
            get_lead_signal,
            graduate_lead_signal,
        )

        with connect() as conn:
            if get_lead_signal(conn, signal_id) is None:
                raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
            if get_contact(conn, body.contactId) is None:
                raise HTTPException(status_code=404, detail=f"contact {body.contactId!r} not found")
            return graduate_lead_signal(
                conn, signal_id, contact_id=body.contactId, actor=_WEB_ACTOR
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/signals/%s/graduate failed", signal_id)
        raise HTTPException(status_code=500, detail=f"Graduate signal failed: {exc}")


# ---------------------------------------------------------------------------
# /admin/deals - Admin Hub deal cards
# ---------------------------------------------------------------------------


@app.get("/api/admin/jurisdiction")
async def get_admin_jurisdiction():
    """Return the configured admin deal-flow package. No UI switching."""
    return _admin_jurisdiction_config()


@app.put("/api/admin/jurisdiction")
def put_admin_jurisdiction(body: _AdminJurisdictionBody):
    """Persist the workspace default province/package for Admin Hub deals."""
    try:
        from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

        config = load_config()
        real_estate = dict(config.get("real_estate") or {})
        country = _clean_admin_jurisdiction_value(
            body.country if body.country is not None else real_estate.get("country"),
            "CA",
        ).upper()
        province = _clean_admin_jurisdiction_value(
            body.province if body.province is not None else real_estate.get("province"),
            "",
        ).upper()
        market = _clean_admin_jurisdiction_value(
            body.market if body.market is not None else real_estate.get("market"),
            "",
        )
        explicit_package = body.packageKey or body.package_key
        package_key = package_key_from_jurisdiction(
            country=country,
            province=province,
            package_key=explicit_package,
        )
        real_estate.update(
            {
                "country": country,
                "province": province,
                "market": market,
                "package_key": package_key,
            }
        )
        config["real_estate"] = real_estate
        save_config(config)
        try:
            from elevate_cli.data import connect, update_admin_setup

            with connect() as conn:
                update_admin_setup(
                    conn,
                    profile={"country": country, "province": province, "market": market},
                    actor="admin:jurisdiction",
                )
        except Exception:
            _log.exception("failed to sync Admin setup jurisdiction profile")
            raise
        return _admin_jurisdiction_config()
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/admin/jurisdiction failed")
        raise HTTPException(status_code=500, detail=f"Update jurisdiction failed: {exc}")


@app.get("/api/admin/setup")
def get_admin_setup_endpoint():
    """Return the Admin first-run readiness profile."""
    try:
        from elevate_cli.data import connect, get_admin_setup

        with connect() as conn:
            return get_admin_setup(conn)
    except Exception as exc:
        _log.exception("GET /api/admin/setup failed")
        raise HTTPException(status_code=500, detail=f"Admin setup failed: {exc}")


@app.put("/api/admin/setup")
def put_admin_setup_endpoint(body: _AdminSetupUpdateBody):
    """Update Admin setup profile/items while the launch gate is open."""
    try:
        from elevate_cli.data import connect, update_admin_setup

        _mirror_admin_setup_portal_env(body.items)
        with connect() as conn:
            setup = update_admin_setup(
                conn,
                profile=body.profile,
                items=[item.dict() for item in body.items],
                actor=_WEB_ACTOR,
            )
        if body.profile and any(key in body.profile for key in ("country", "province", "market", "packageKey", "package_key")):
            from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

            config = load_config()
            real_estate = dict(config.get("real_estate") or {})
            country = _clean_admin_jurisdiction_value(body.profile.get("country"), real_estate.get("country") or "CA").upper()
            province = _clean_admin_jurisdiction_value(body.profile.get("province"), real_estate.get("province") or "").upper()
            market = _clean_admin_jurisdiction_value(body.profile.get("market"), real_estate.get("market") or "")
            package_key = package_key_from_jurisdiction(
                country=country,
                province=province,
                package_key=body.profile.get("packageKey") or body.profile.get("package_key") or real_estate.get("package_key"),
            )
            real_estate.update({"country": country, "province": province, "market": market, "package_key": package_key})
            config["real_estate"] = real_estate
            save_config(config)
        return setup
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/admin/setup failed")
        raise HTTPException(status_code=500, detail=f"Update admin setup failed: {exc}")


@app.post("/api/admin/setup/complete")
def post_admin_setup_complete_endpoint():
    """Mark Admin setup complete after all required readiness items are filled."""
    try:
        from elevate_cli.data import complete_admin_setup, connect

        with connect() as conn:
            return complete_admin_setup(conn, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/setup/complete failed")
        raise HTTPException(status_code=500, detail=f"Complete admin setup failed: {exc}")


@app.post("/api/admin/setup/verify")
def post_admin_setup_verify_endpoint():
    """Check setup items against local runtime connectors and imported guides."""
    warnings: List[str] = []
    try:
        from elevate_cli.data import (
            connect,
            get_admin_setup,
            import_exp_agent_centre,
            province_guide_summary,
            sync_admin_setup_runtime,
        )

        config = load_config()
        source_connectors: Dict[str, Any] | None = None
        composio_accounts: Dict[str, Any] | None = None
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            source_connectors = build_source_connectors_response(config, include_prompts=False)
        except Exception as exc:
            warnings.append(f"Source connector check skipped: {exc}")
        try:
            from elevate_cli import composio_client

            composio_accounts = composio_client.list_all_connected_accounts(
                page_size=100,
                max_pages=2,
            )
            if not composio_accounts.get("ok"):
                warnings.append(
                    f"Composio account check skipped: {composio_accounts.get('error') or 'not connected'}"
                )
        except Exception as exc:
            warnings.append(f"Composio account check skipped: {exc}")

        with connect() as conn:
            setup = get_admin_setup(conn)
            province = str(setup.get("profile", {}).get("province") or "").strip().upper()
            province_guide: Dict[str, Any] | None = None
            try:
                import_exp_agent_centre(conn)
                if province:
                    province_guide = province_guide_summary(conn, province)
            except Exception as exc:
                warnings.append(f"Province guide import skipped: {exc}")
            verified = sync_admin_setup_runtime(
                conn,
                env_values=_admin_setup_runtime_env_values(),
                source_connectors=source_connectors,
                composio_accounts=composio_accounts,
                province_guide=province_guide,
                actor=_WEB_ACTOR,
            )
        if warnings:
            verified["verificationWarnings"] = warnings
        return verified
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/admin/setup/verify failed")
        raise HTTPException(status_code=500, detail=f"Verify admin setup failed: {exc}")


@app.get("/api/leads/setup")
def get_leads_setup_endpoint():
    """Return the Leads onboarding readiness snapshot."""
    try:
        from elevate_cli.data import connect, get_leads_setup

        with connect() as conn:
            return get_leads_setup(conn)
    except Exception as exc:
        _log.exception("GET /api/leads/setup failed")
        raise HTTPException(status_code=500, detail=f"Leads setup failed: {exc}")


@app.put("/api/leads/setup")
def put_leads_setup_endpoint(body: _LeadsSetupUpdateBody):
    """Update Leads setup items while the gate is open."""
    try:
        from elevate_cli.data import connect, update_leads_setup

        with connect() as conn:
            return update_leads_setup(
                conn,
                items=[item.dict() for item in body.items],
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/leads/setup failed")
        raise HTTPException(status_code=500, detail=f"Update leads setup failed: {exc}")


@app.post("/api/leads/setup/complete")
def post_leads_setup_complete_endpoint():
    """Mark Leads onboarding complete once CRM + at least one lead source + auto-reply are ready."""
    try:
        from elevate_cli.data import complete_leads_setup, connect

        with connect() as conn:
            return complete_leads_setup(conn)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/leads/setup/complete failed")
        raise HTTPException(status_code=500, detail=f"Complete leads setup failed: {exc}")


@app.post("/api/leads/setup/reset")
def post_leads_setup_reset_endpoint():
    """Re-open the Leads onboarding gate without wiping item state."""
    try:
        from elevate_cli.data import connect, reset_leads_setup

        with connect() as conn:
            return reset_leads_setup(conn)
    except Exception as exc:
        _log.exception("POST /api/leads/setup/reset failed")
        raise HTTPException(status_code=500, detail=f"Reset leads setup failed: {exc}")


@app.get("/api/agent/setup")
def get_agent_setup_endpoint():
    """Return the top-level Agent onboarding readiness snapshot."""
    try:
        from elevate_cli.data import connect, get_agent_setup

        with connect() as conn:
            return get_agent_setup(conn)
    except Exception as exc:
        _log.exception("GET /api/agent/setup failed")
        raise HTTPException(status_code=500, detail=f"Agent setup failed: {exc}")


@app.put("/api/agent/setup")
def put_agent_setup_endpoint(body: _AgentSetupUpdateBody):
    """Update Agent setup items while the gate is open."""
    try:
        from elevate_cli.data import connect, update_agent_setup

        with connect() as conn:
            return update_agent_setup(
                conn,
                items=[item.dict() for item in body.items],
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/agent/setup failed")
        raise HTTPException(status_code=500, detail=f"Update agent setup failed: {exc}")


# Onboarding wizard provider-dropdown values -> canonical config provider slug.
_WIZARD_PROVIDER_TO_CONFIG = {
    "openai": "openai-codex",
    "qwen": "qwen-oauth",
    "azure_openai": "azure-foundry",
}
# Onboarding memory-store labels -> config memory.provider values. "sqlite_local"
# is a wizard label only; the runtime's local memory provider is "holographic".
_WIZARD_MEMORY_TO_CONFIG = {
    "sqlite_local": "holographic",
    "supabase": "supabase",
}


def _materialize_agent_setup_to_config(conn) -> Dict[str, Any]:
    """Write the onboarding tracker's model/embedding/memory selections into
    config.yaml so finishing the wizard actually configures the agent — not
    just the readiness checklist.

    Reads the RAW agent_setup_items rows (the user's actual picks), NOT the
    env-overlaid snapshot, so an ambient API key can't mask the selection.
    Best-effort per item; never raises — a materialization failure must not
    undo the gate-complete the caller just performed.
    """
    applied: Dict[str, Any] = {}
    try:
        from elevate_cli.config import load_config, save_config
    except Exception as exc:  # pragma: no cover
        return {"error": f"config module unavailable: {exc}"}

    items: Dict[str, Dict[str, Any]] = {}
    try:
        rows = conn.execute(
            "SELECT key, status, provider, value_json FROM agent_setup_items"
        ).fetchall()
        for r in rows:
            d = dict(r)
            try:
                d["value"] = json.loads(d.get("value_json") or "{}") or {}
            except Exception:
                d["value"] = {}
            items[d.get("key")] = d
    except Exception as exc:
        return {"error": f"could not read setup items: {exc}"}

    cfg = load_config()
    changed = False

    # Primary model + provider -> config["model"] {provider, default}. Same
    # shape the working composer model-switch persists (_persist_model_switch);
    # base_url/credentials are resolved at runtime from the provider + auth pool.
    mp = items.get("model_primary") or {}
    prov = str(mp.get("provider") or "").strip()
    model = str((mp.get("value") or {}).get("model") or "").strip()
    if prov and model:
        canon = _WIZARD_PROVIDER_TO_CONFIG.get(prov, prov)
        mc = cfg.get("model")
        if not isinstance(mc, dict):
            mc = {}
            cfg["model"] = mc
        mc["provider"] = canon
        mc["default"] = model
        changed = True
        applied["model"] = {"provider": canon, "model": model}

    # Embedding -> plugins["elevate-memory-store"].embedding_{provider,model}.
    me = items.get("model_embedding") or {}
    eprov = str(me.get("provider") or "").strip()
    emodel = str((me.get("value") or {}).get("model") or "").strip()
    if eprov:
        plugins = cfg.get("plugins")
        if not isinstance(plugins, dict):
            plugins = {}
            cfg["plugins"] = plugins
        store = plugins.get("elevate-memory-store")
        if not isinstance(store, dict):
            store = {}
            plugins["elevate-memory-store"] = store
        store["embedding_provider"] = eprov
        if emodel:
            store["embedding_model"] = emodel
        changed = True
        applied["embedding"] = {"provider": eprov, "model": emodel}

    # Memory store -> config["memory"].provider.
    mm = items.get("memory_store") or {}
    mprov = str(mm.get("provider") or "").strip()
    if mprov:
        canon_mem = _WIZARD_MEMORY_TO_CONFIG.get(mprov, mprov)
        mem = cfg.get("memory")
        if not isinstance(mem, dict):
            mem = {}
            cfg["memory"] = mem
        mem["provider"] = canon_mem
        changed = True
        applied["memory"] = {"provider": canon_mem}

    if changed:
        save_config(cfg)
    return applied


@app.post("/api/agent/setup/complete")
def post_agent_setup_complete_endpoint():
    """Mark Agent onboarding complete once primary LLM + embedding + memory store are ready.

    On success, materialize the wizard's model/embedding/memory selections into
    config.yaml so finishing onboarding actually configures the agent (the
    selections otherwise live only in the readiness-tracker DB).
    """
    try:
        from elevate_cli.data import complete_agent_setup, connect

        with connect() as conn:
            snapshot = complete_agent_setup(conn)
            try:
                snapshot["materialized"] = _materialize_agent_setup_to_config(conn)
            except Exception as exc:  # never let materialization undo completion
                _log.exception("agent setup materialization failed")
                snapshot["materialize_error"] = str(exc)
            return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/agent/setup/complete failed")
        raise HTTPException(status_code=500, detail=f"Complete agent setup failed: {exc}")


@app.post("/api/agent/setup/reset")
def post_agent_setup_reset_endpoint():
    """Re-open the Agent onboarding gate without wiping item state."""
    try:
        from elevate_cli.data import connect, reset_agent_setup

        with connect() as conn:
            return reset_agent_setup(conn)
    except Exception as exc:
        _log.exception("POST /api/agent/setup/reset failed")
        raise HTTPException(status_code=500, detail=f"Reset agent setup failed: {exc}")


_ONBOARDING_CHAT_SYSTEM = (
    "You are Elevate's onboarding coach for a Canadian real estate agent. "
    "Tone: direct operator, no fluff, no 'do you have', no 'would you like to'. "
    "Get-it-done energy. Treat the snapshot below as ground truth — the wizard "
    "is done, the agent is up to date. "
    "RULES: "
    "(1) Always lead with current state: name the province and what's already "
    "connected (with provider names). Don't ask questions about anything the "
    "snapshot shows as connected/configured. "
    "IMPORTANT: 'Still missing' has two sub-buckets — items that the user "
    "set up but Elevate hasn't yet captured a runtime verification ping for "
    "(status=connected/configured AND key in missingRequiredKeys, listed under "
    "'Pending verification'), and items the user hasn't picked a provider for "
    "(status=missing, listed under 'Not picked yet'). NEVER tell the user a "
    "Pending-verification item is 'missing' or that they need to reconnect "
    "it — say 'health-check pending, will clear on next sync' instead. Only "
    "items in 'Not picked yet' need user action. "
    "(2) After the state line, name the next concrete 'Not picked yet' gap "
    "and tell the user how to close it — not 'do you have a calendar', but "
    "'Next: Calendar — click Connect on the Calendar card in the connectors "
    "panel'. If everything is either connected or pending verification, say "
    "so; do not invent action items. "
    "(3) Never say you're 'making' or 'creating' something that already exists. "
    "(4) Never offer to import 'any spreadsheets of contacts, deals, listings, "
    "or past clients' unless the user brings them up first. The CRM already "
    "covers that surface area. "
    "(5) Keep replies to 1-3 short sentences. No bullet lists, no markdown, no "
    "'great question' / 'happy to help'. "
    "(6) OAuth connectors (Google Drive, Gmail, Calendar): say 'click Connect "
    "on the X card'. Portal logins (MLS, compliance, showing): say 'enter URL "
    "+ email + password on the X card, then hit Connect & analyze'. When the "
    "snapshot lists a saved portal login URL or provider home page for the "
    "missing item, paste that URL verbatim in the reply so the user can click "
    "through directly. Plain https URLs render as clickable links in the chat "
    "bubble — do not wrap them in markdown. "
    "(7) If the user asks 'where are we at' or similar status questions, "
    "restate: province, completion %, connected items with providers, missing "
    "items with the next action to close the first one. "
    "(8) If everything required is in, say so in one sentence and ask if "
    "anything else needs tightening up. Do not invent tasks."
)


_PROVIDER_HOMEPAGE = {
    "google calendar": "https://calendar.google.com",
    "google drive": "https://drive.google.com",
    "gmail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "microsoft 365": "https://outlook.office.com",
    "lofty": "https://app.lofty.com",
    "follow up boss": "https://app.followupboss.com",
    "kvcore": "https://www.kvcore.com",
    "boldtrail": "https://www.boldtrail.com",
    "matrix": "https://matrix.realtor.ca",
    "paragon": "https://paragonconnect.com",
    "stellar mls": "https://www.stellarmls.com",
    "broker bay": "https://brokerbay.com",
    "showingtime": "https://www.showingtime.com",
    "showami": "https://www.showami.com",
    "webforms": "https://wf.crea.ca",
    "transactiondesk": "https://www.transactiondesk.com",
    "dotloop": "https://www.dotloop.com",
    "skyslope": "https://www.skyslope.com",
    "docusign": "https://www.docusign.com",
    "authentisign": "https://www.authentisign.com",
}


def _provider_home_url(provider: str) -> str:
    if not provider:
        return ""
    return _PROVIDER_HOMEPAGE.get(provider.strip().lower(), "")


def _onboarding_chat_context(setup: Dict[str, Any]) -> str:
    """Compact snapshot context appended to the system prompt."""
    profile = setup.get("profile") or {}
    items = setup.get("items") or []
    missing = setup.get("missingRequiredKeys") or []
    by_key = {it["key"]: it for it in items if isinstance(it, dict) and it.get("key")}
    lines = [
        "--- CURRENT SETUP SNAPSHOT ---",
        f"Realtor: {profile.get('realtorLegalName') or '(unset)'} @ {profile.get('brokerageName') or '(unset)'}",
        f"Province: {profile.get('province') or '(unset)'} · Market: {profile.get('market') or '(unset)'}",
        f"Completion: {setup.get('completionPct') or 0}% ({setup.get('completedRequiredCount') or 0}/{setup.get('requiredCount') or 0})",
    ]
    if missing:
        pending_verify: List[str] = []
        not_picked: List[str] = []
        for k in missing:
            it = by_key.get(k) or {}
            label = it.get("label") or k
            status = (it.get("status") or "").strip()
            if status in ("connected", "configured"):
                pending_verify.append(label)
            else:
                not_picked.append(label)
        if pending_verify:
            lines.append(f"Pending verification (provider set, health-check not yet captured): {', '.join(pending_verify)}")
        if not_picked:
            lines.append(f"Not picked yet (user action required): {', '.join(not_picked)}")
        if not pending_verify and not not_picked:
            lines.append("All required items present.")
    else:
        lines.append("All required items present.")
    for key in ("drive", "crm", "mls", "compliance", "showing"):
        item = by_key.get(key)
        if item:
            provider = item.get("provider") or "(none)"
            lines.append(f"{key}: {provider} [{item.get('status') or 'missing'}]")

    browser_item = by_key.get("browser_workflows") or {}
    browser_value = browser_item.get("value") if isinstance(browser_item.get("value"), dict) else {}
    playbooks = browser_value.get("playbooks") if isinstance(browser_value.get("playbooks"), dict) else {}
    portal_urls: List[str] = []
    for portal_key, label in (("mls", "MLS"), ("compliance", "Compliance"), ("showing", "Showing")):
        pb = playbooks.get(portal_key) if isinstance(playbooks.get(portal_key), dict) else {}
        url = (pb.get("loginUrl") or "").strip()
        if url:
            portal_urls.append(f"{label} login URL: {url}")
    if portal_urls:
        lines.append("--- SAVED PORTAL LOGINS ---")
        lines.extend(portal_urls)

    home_lines: List[str] = []
    for key in ("calendar", "email", "drive", "crm", "mls", "compliance", "showing"):
        item = by_key.get(key) or {}
        if item.get("status") in ("connected", "configured"):
            continue
        provider = (item.get("provider") or "").strip()
        home = _provider_home_url(provider)
        if home:
            home_lines.append(f"{key} ({provider}): {home}")
    if home_lines:
        lines.append("--- PROVIDER HOMEPAGES FOR PENDING ITEMS ---")
        lines.extend(home_lines)

    return "\n".join(lines)


_CONNECTOR_NEXT_ACTION = {
    "calendar": "click Connect on the Calendar card.",
    "email": "click Connect on the Email card.",
    "drive": "click Connect on the Drive card.",
    "crm": "click Connect on the CRM card or paste your spreadsheet path.",
    "mls": "enter URL + email + password on the MLS card, then hit Connect & analyze.",
    "compliance_platform": "enter URL + email + password on the Compliance card, then hit Connect & analyze.",
    "showing_platform": "enter URL + email + password on the Showing card, then hit Connect & analyze.",
    "photo_processing": "pick a provider on the Photo processing card.",
    "fintrac_workflow": "pick a FINTRAC workflow on the card.",
    "forms_provider": "pick your forms provider on the card.",
    "signing_provider": "pick your signing provider on the card.",
    "approval_channel": "pick your approval channel (Telegram / email).",
}


def _onboarding_fallback_reply(messages: List[Dict[str, str]], setup: Dict[str, Any]) -> str:
    """Deterministic guidance when no LLM is configured.

    Mirrors the system prompt: state-first, direct next-action ask.
    """
    profile = setup.get("profile") or {}
    items = setup.get("items") or []
    by_key: Dict[str, Dict[str, Any]] = {it["key"]: it for it in items if isinstance(it, dict) and it.get("key")}
    missing = list(setup.get("missingRequiredKeys") or [])
    province = (profile.get("province") or "").strip().upper()
    pct = setup.get("completionPct") or 0
    last = (messages[-1].get("content") if messages else "") or ""
    last_lower = last.lower()

    browser_item = by_key.get("browser_workflows") or {}
    browser_value = browser_item.get("value") if isinstance(browser_item.get("value"), dict) else {}
    playbooks = browser_value.get("playbooks") if isinstance(browser_value.get("playbooks"), dict) else {}

    def _portal_url(portal_key: str) -> str:
        pb = playbooks.get(portal_key) if isinstance(playbooks.get(portal_key), dict) else {}
        return (pb.get("loginUrl") or "").strip()

    def _next_action_with_url(missing_key: str) -> str:
        base = _CONNECTOR_NEXT_ACTION.get(missing_key, "")
        if missing_key == "mls":
            url = _portal_url("mls")
            if url:
                return f"{base} ({url})"
        if missing_key == "compliance_platform":
            url = _portal_url("compliance")
            if url:
                return f"{base} ({url})"
        if missing_key == "showing_platform":
            url = _portal_url("showing")
            if url:
                return f"{base} ({url})"
        item = by_key.get(missing_key) or {}
        provider = (item.get("provider") or "").strip()
        home = _provider_home_url(provider)
        if home and base:
            return f"{base} Sign-in: {home}"
        return base

    connected_bits: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("status") not in ("connected", "configured"):
            continue
        label = (it.get("label") or it.get("key") or "").strip()
        provider = (it.get("provider") or "").strip()
        if not label:
            continue
        connected_bits.append(f"{label} ({provider})" if provider else label)

    pending_verify_labels: List[str] = []
    not_picked_labels: List[str] = []
    not_picked_keys: List[str] = []
    for k in missing:
        it = by_key.get(k) or {}
        label = it.get("label") or k
        status = (it.get("status") or "").strip()
        if status in ("connected", "configured"):
            pending_verify_labels.append(label)
        else:
            not_picked_labels.append(label)
            not_picked_keys.append(k)

    next_action = _next_action_with_url(not_picked_keys[0]) if not_picked_keys else None

    status_re_ask = any(
        token in last_lower
        for token in ("where are we", "status", "where we at", "what's left", "where do we", "what do we need")
    )

    if status_re_ask or not messages:
        head = f"{province + ', ' if province else ''}{pct}% wired up."
        connected_line = f" Connected: {', '.join(connected_bits)}." if connected_bits else ""
        pending_line = (
            f" Health-check pending (will clear on next sync): {', '.join(pending_verify_labels)}."
            if pending_verify_labels else ""
        )
        if not_picked_labels:
            tail = (
                f" Not picked yet: {', '.join(not_picked_labels)}. Next: {not_picked_labels[0]} — {next_action}"
                if next_action else f" Not picked yet: {', '.join(not_picked_labels)}."
            )
        elif pending_verify_labels:
            tail = " No user action needed — pending items will clear automatically."
        else:
            tail = " Everything required is in. Anything else to tighten?"
        return head + connected_line + pending_line + tail

    if "spreadsheet" in last_lower or "sheet" in last_lower:
        crm = (profile.get("crmProvider") or "").strip()
        if crm:
            return f"{crm} is already wired in as your CRM — leads, contacts, deals all flow through it. Drop a sheet only if there's data not in {crm} yet."
        return "Paste the Google Sheet URL into your drive folder; the next sync will pick it up."

    if not_picked_labels and next_action:
        return f"{not_picked_labels[0]} is the next gap — {next_action}"
    if not_picked_labels:
        return f"Still need to pick: {', '.join(not_picked_labels)}. Knock them out in the connectors panel."
    if pending_verify_labels:
        return (
            f"Pending health-check on {', '.join(pending_verify_labels)} — these are wired up, "
            f"verification ping just hasn't landed. Will clear on next sync."
        )
    return "Everything required is in. Anything else to tighten before we go live?"


@app.post("/api/admin/onboarding/chat")
def post_admin_onboarding_chat(body: _OnboardingChatBody):
    """LLM-backed onboarding coach. Falls back to deterministic guidance when no auxiliary client is configured."""
    try:
        from elevate_cli.data import connect, get_admin_setup
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Onboarding chat unavailable: {exc}")

    try:
        with connect() as conn:
            setup = get_admin_setup(conn)
    except Exception as exc:
        _log.exception("onboarding chat: failed to read admin_setup snapshot")
        setup = {}

    messages = [m.dict() for m in body.messages if m.content.strip()]
    context = _onboarding_chat_context(setup)
    system_prompt = _ONBOARDING_CHAT_SYSTEM + "\n\n" + context

    try:
        from agent.auxiliary_client import get_text_auxiliary_client

        client, model = get_text_auxiliary_client("onboarding_chat")
    except Exception as exc:
        _log.info("onboarding chat: auxiliary client unavailable (%s) — falling back", exc)
        return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": None}

    if client is None or not model:
        return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": None}

    payload_messages = [{"role": "system", "content": system_prompt}, *messages]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=payload_messages,
            temperature=0.4,
            max_tokens=400,
            timeout=20,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        _log.info("onboarding chat: LLM call failed (%s) — falling back", exc)
        return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": model, "warning": str(exc)}

    if not text:
        text = _onboarding_fallback_reply(messages, setup)
    return {"ok": True, "reply": text, "model": model}


def _browser_use_api_key() -> Optional[str]:
    """Pull a direct browser-use API key from env or YAML config."""
    for env_key in ("BROWSER_USE_API_KEY", "BROWSERUSE_API_KEY"):
        value = os.environ.get(env_key)
        if value:
            return value.strip()
    try:
        cfg = load_config() or {}
    except Exception:
        return None
    browser_cfg = (cfg.get("browser") or {}) if isinstance(cfg, dict) else {}
    candidate = browser_cfg.get("api_key") if isinstance(browser_cfg, dict) else None
    return str(candidate).strip() if candidate else None


@app.post("/api/admin/onboarding/browser-use/launch")
def post_admin_onboarding_browser_use_launch(body: _OnboardingBrowserUseBody):
    """Fire a browser-use cloud task against a portal saved in admin_setup."""
    portal_key = (body.portalKey or "").strip().lower()
    if portal_key not in {"mls", "compliance", "showing"}:
        raise HTTPException(status_code=400, detail="portalKey must be one of mls | compliance | showing")

    try:
        from elevate_cli.data import connect, get_admin_setup

        with connect() as conn:
            setup = get_admin_setup(conn)
    except Exception as exc:
        _log.exception("browser-use launch: snapshot read failed")
        raise HTTPException(status_code=500, detail=f"Read setup failed: {exc}")

    items = setup.get("items") or []
    browser_item = next(
        (it for it in items if isinstance(it, dict) and it.get("key") == "browser_workflows"),
        None,
    )
    playbooks = (((browser_item or {}).get("value") or {}).get("playbooks") or {}) if browser_item else {}
    playbook = playbooks.get(portal_key) or {}
    login_url = (playbook.get("loginUrl") or "").strip()
    credential_ref = (playbook.get("credentialRef") or "").strip()
    provider = (playbook.get("provider") or "").strip()
    notes = (playbook.get("notes") or "").strip()
    if not login_url:
        return {"ok": False, "error": f"No login URL saved for {portal_key} portal yet. Add it in the connectors card first."}

    api_key = _browser_use_api_key()
    if not api_key:
        return {
            "ok": False,
            "error": "BROWSER_USE_API_KEY not configured. Add it under Tools → Browser Use.",
            "portal": {"loginUrl": login_url, "provider": provider, "credentialRef": credential_ref},
        }

    province = (setup.get("profile") or {}).get("province") or ""
    task = body.taskHint or (
        f"Sign in to {provider or portal_key} at {login_url} using credentials referenced "
        f"by '{credential_ref or '(unspecified — ask the agent)'}'. "
        f"This is a {province or 'Canadian'} real-estate agent's {portal_key} portal. "
        "Once logged in, scan the dashboard and summarize: current active listings, pending "
        "transactions, any compliance alerts, and the structure of the main navigation. "
        "Report back as plain text — do not modify any data."
    )
    if notes:
        task += f"\n\nAgent notes about this portal:\n{notes}"

    request_body = json.dumps({"task": task, "save_browser_data": True}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.browser-use.com/api/v1/run-task",
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        _log.warning("browser-use launch: HTTP %s — %s", exc.code, err_body[:400])
        return {"ok": False, "error": f"browser-use returned {exc.code}: {err_body[:200] or exc.reason}"}
    except Exception as exc:
        _log.exception("browser-use launch: request failed")
        return {"ok": False, "error": f"browser-use call failed: {exc}"}

    task_id = data.get("id") or data.get("task_id") or data.get("uuid")
    return {
        "ok": True,
        "taskId": task_id,
        "runUrl": data.get("live_url") or (f"https://cloud.browser-use.com/tasks/{task_id}" if task_id else None),
        "raw": data,
    }


@app.get("/api/pack-onboarding")
def get_pack_onboarding_endpoint():
    """Return pack-specific onboarding contracts for unlocked real estate packs."""
    try:
        from elevate_cli.data import connect, get_pack_onboarding

        with connect() as conn:
            return get_pack_onboarding(conn)
    except Exception as exc:
        _log.exception("GET /api/pack-onboarding failed")
        raise HTTPException(status_code=500, detail=f"Pack onboarding failed: {exc}")


@app.put("/api/pack-onboarding/{pack_id}")
def put_pack_onboarding_endpoint(pack_id: str, body: _PackOnboardingUpdateBody):
    """Save onboarding answers for one paid pack."""
    try:
        from elevate_cli.data import connect, update_pack_onboarding

        with connect() as conn:
            return update_pack_onboarding(
                conn,
                pack_id,
                items=[item.dict() for item in body.items],
                actor=_WEB_ACTOR,
            )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/pack-onboarding/%s failed", pack_id)
        raise HTTPException(status_code=500, detail=f"Update pack onboarding failed: {exc}")


@app.post("/api/pack-onboarding/{pack_id}/complete")
def post_pack_onboarding_complete_endpoint(pack_id: str):
    """Mark one pack onboarding complete once required fields are ready."""
    try:
        from elevate_cli.data import complete_pack_onboarding, connect

        with connect() as conn:
            return complete_pack_onboarding(conn, pack_id, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/pack-onboarding/%s/complete failed", pack_id)
        raise HTTPException(status_code=500, detail=f"Complete pack onboarding failed: {exc}")


@app.get("/api/admin/province-guides")
def get_admin_province_guides(province: Optional[str] = None):
    """Return SQLite-backed province guide coverage/reference material."""
    try:
        from elevate_cli.data import connect, province_coverage, province_guide_summary
        from elevate_cli.data.province_guides import normalize_province_code

        with connect() as conn:
            requested_province = normalize_province_code(province) if province and province.strip() else None
            if requested_province:
                return province_guide_summary(conn, requested_province)
            return {"items": province_coverage(conn)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/province-guides failed")
        raise HTTPException(status_code=500, detail=f"Province guides failed: {exc}")


@app.post("/api/admin/province-guides/import")
def post_admin_province_guides_import(body: Optional[_ProvinceGuideImportBody] = None):
    """Import local eXp Agent Centre scrape output into SQLite."""
    try:
        from elevate_cli.data import connect, import_exp_agent_centre
        from elevate_cli.data.province_guides import normalize_province_code

        root = body.root.strip() if body and body.root and body.root.strip() else None
        requested_province = normalize_province_code(body.province) if body and body.province else None
        prune = body.pruneOtherProvinces if body is not None else False
        with connect() as conn:
            return import_exp_agent_centre(
                conn,
                root=root,
                province=requested_province,
                prune_other_provinces=prune,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/province-guides/import failed")
        raise HTTPException(status_code=500, detail=f"Province guide import failed: {exc}")


@app.get("/api/admin/deals")
def get_admin_deals(
    side: Optional[str] = None,
    current_stage: Optional[int] = None,
    status: Optional[str] = "active",
    province: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Return Admin Hub deals for the configured jurisdiction."""
    try:
        from elevate_cli.data import connect, list_deals
        from elevate_cli.data.deals import deal_card_gate

        with connect() as conn:
            rows = list_deals(
                conn,
                side=side or None,
                current_stage=current_stage,
                status=status or None,
                province=province.strip().upper() if province and province.strip() else None,
                limit=limit,
                offset=offset,
            )
            # Enrich each card with its live scorecard (checklist progress +
            # gate state) so the board shows it without opening the modal.
            for row in rows:
                try:
                    scorecard = deal_card_gate(conn, row)
                    row["scorecard"] = scorecard
                    # Feed the existing DealCard `progress` render path with live data.
                    if scorecard.get("progress"):
                        row["progress"] = scorecard["progress"]
                except Exception:
                    _log.debug("deal_card_gate failed for deal %s", row.get("id"), exc_info=True)
            return {"items": rows, "count": len(rows), "jurisdiction": _admin_jurisdiction_config()}
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/deals failed")
        raise HTTPException(status_code=500, detail=f"Admin deals failed: {exc}")


@app.get("/api/admin/upcoming-events")
def get_admin_upcoming_events(days: int = 21):
    """Return merged Admin calendar feed: Google Calendar + deal milestone dates."""
    try:
        from elevate_cli.data import connect
        from elevate_cli.data.admin_calendar import list_upcoming_admin_events

        safe_days = max(1, min(int(days or 21), 90))
        with connect() as conn:
            return list_upcoming_admin_events(conn, days=safe_days)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/upcoming-events failed")
        raise HTTPException(status_code=500, detail=f"Admin upcoming events failed: {exc}")


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


def _activity_text(value: Any) -> Optional[str]:
    """Convert activity payload fragments into compact display text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_activity_text(item) for item in value]
        text = "; ".join(part for part in parts if part)
        return text or None
    if isinstance(value, dict):
        for key in (
            "summary",
            "attention_summary",
            "message",
            "title",
            "event",
            "category",
            "status",
        ):
            text = _activity_text(value.get(key))
            if text:
                return text
        try:
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return None
    return str(value)


def _build_activity_items() -> List[Dict[str, Any]]:
    """Scan the account data dir for the fleet activity feed (the expensive part
    of GET /api/activity). Returns the unfiltered, unsorted item list so the
    endpoint can cache it and apply agent-filter/sort/limit per request."""
    from elevate_constants import get_account_data_dir

    items: List[Dict[str, Any]] = []
    base = get_account_data_dir() / "heartbeats"
    try:
        # Heartbeat run records: prefer the DB run index (surface_runs,
        # migration 0027) — one query overall, capped per surface. Surfaces
        # with no DB rows fall back to the legacy history/*.json file scan
        # below (same item shape either way).
        runs_by_surface: Dict[str, List[Dict[str, Any]]] = {}
        try:
            from elevate_cli.data import connect as _runs_connect
            from elevate_cli.data import surface_state as _runs_state

            with _runs_connect() as _conn:
                for run in _runs_state.list_runs(_conn, limit=400):
                    bucket = runs_by_surface.setdefault(
                        str(run.get("surface") or "") or "system", []
                    )
                    if len(bucket) < 30:
                        bucket.append(run)
        except Exception:
            _log.warning("activity: surface_runs unavailable", exc_info=True)
            runs_by_surface = {}
        for surface, runs in runs_by_surface.items():
            for run in runs:
                rec = run.get("record") if isinstance(run.get("record"), dict) else {}
                items.append({
                    "kind": "heartbeat",
                    "agent": surface,
                    "ts": _activity_text(rec.get("ran_at") or run.get("ran_at")) or "",
                    "title": _activity_text(
                        run.get("summary") or rec.get("summary") or rec.get("did")
                    ) or "ran",
                    "detail": _activity_text(rec.get("found") or rec.get("checked")),
                    "status": _activity_text(run.get("status")) or "ok",
                })
        if base.is_dir():
            for sdir in base.iterdir():
                if not sdir.is_dir():
                    continue
                surface = sdir.name
                if runs_by_surface.get(surface):
                    continue  # DB rows already cover this surface
                hist = sdir / "history"
                if not hist.is_dir():
                    continue
                for f in sorted(hist.glob("*.json"), reverse=True)[:30]:
                    try:
                        rec = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    items.append({
                        "kind": "heartbeat",
                        "agent": surface,
                        "ts": _activity_text(rec.get("ran_at") or f.stem) or f.stem,
                        "title": _activity_text(rec.get("summary") or rec.get("did")) or "ran",
                        "detail": _activity_text(rec.get("found") or rec.get("checked")),
                        "status": "ok",
                    })
        try:
            from cron.jobs import list_jobs

            for j in list_jobs(include_disabled=True):
                lr = j.get("last_run_at")
                if not lr:
                    continue
                o = j.get("origin") or {}
                items.append({
                    "kind": "cron",
                    "agent": _activity_text(o.get("surface") or j.get("agent")) or "system",
                    "ts": _activity_text(lr) or "",
                    "title": _activity_text(j.get("name")) or "job",
                    "detail": _activity_text(j.get("last_summary")),
                    "status": _activity_text(j.get("last_status")) or "ok",
                })
        except Exception:
            _log.warning("activity: cron last-runs unavailable", exc_info=True)
        try:
            from elevate_cli.data.paths import data_root

            # Agent activity is DB-backed (surface_activity, migration 0025);
            # the legacy agent_activity.jsonl is frozen after the one-shot
            # import in tools/agent_bus_tool.py. kind/category/severity ride
            # inside the metadata payload — same unwrap as _activity_record.
            try:
                from elevate_cli.data import connect as _data_connect
                from elevate_cli.data import surface_state as _surface_state

                with _data_connect() as _conn:
                    activity_rows = _surface_state.list_activity(_conn, limit=120)
            except Exception:
                _log.warning("activity: surface_activity unavailable", exc_info=True)
                activity_rows = []
            for rec in activity_rows:
                meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
                items.append({
                    "kind": _activity_text(meta.get("kind")) or "agent_activity",
                    "agent": _activity_text(rec.get("agent")) or "system",
                    "ts": _activity_text(rec.get("at")),
                    "title": _activity_text(rec.get("event") or meta.get("category"))
                    or "Agent activity",
                    "detail": _activity_text(rec.get("message") or meta.get("metadata")),
                    "status": _activity_text(meta.get("severity")) or "info",
                })

            pressure_log = data_root() / "agent_context_pressure.jsonl"
            if pressure_log.exists():
                lines = pressure_log.read_text(encoding="utf-8").splitlines()[-80:]
                for line in lines:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    items.append({
                        "kind": _activity_text(rec.get("kind")) or "context",
                        "agent": _activity_text(rec.get("agent")) or "system",
                        "ts": _activity_text(rec.get("ts")),
                        "title": _activity_text(rec.get("title")) or "Context pressure",
                        "detail": _activity_text(rec.get("detail")),
                        "status": _activity_text(rec.get("status")) or "warning",
                    })
        except Exception:
            _log.warning("activity: context pressure log unavailable", exc_info=True)

    except Exception:
        _log.exception("activity scan failed; returning partial results")
    return items


@app.get("/api/activity")
def get_activity(limit: int = 100, agent: Optional[str] = None):
    """Fleet activity feed — what every agent did, newest first. Aggregates surface
    heartbeat run history + cron job last-runs (file-based, no DB). The FS scan is
    cached per account for a few seconds so rapid polling doesn't rescan each call;
    agent-filter/sort/limit are applied per request on a copy."""
    try:
        items = _fs_cache_get("activity")
        if items is None:
            items = _build_activity_items()
            _fs_cache_put("activity", items, 3.0)
        result = list(items)
        if agent:
            result = [i for i in result if i.get("agent") == agent]
        result.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        return {"items": result[: max(1, min(limit, 300))]}
    except Exception as exc:
        _log.exception("GET /api/activity failed")
        raise HTTPException(status_code=500, detail=f"Activity failed: {exc}")


@app.get("/api/comms/delivery-channels")
def get_comms_delivery_channels():
    """The connected delivery channels (Telegram/Discord/Slack/… chats) for the Comms
    tab's channel panel. Read-only view of the channel directory."""
    try:
        from gateway.channel_directory import load_directory

        directory = load_directory()
        out: List[Dict[str, Any]] = []
        for platform, channels in (directory.get("platforms") or {}).items():
            for ch in channels or []:
                if not ch.get("id"):
                    continue
                out.append({
                    "platform": platform,
                    "id": ch["id"],
                    "name": ch.get("name") or ch["id"],
                    "type": ch.get("type"),
                })
        return {"channels": out, "updated_at": directory.get("updated_at")}
    except Exception as exc:
        _log.exception("GET /api/comms/delivery-channels failed")
        raise HTTPException(status_code=500, detail=f"Comms delivery channels failed: {exc}")


@app.get("/api/comms/feed")
def get_comms_feed(
    limit: int = 200,
    search: Optional[str] = None,
    agent: Optional[str] = None,
):
    """native Meeting Room feed projected from Elevate handoffs."""
    try:
        from elevate_cli.data import connect, list_agent_comms_messages

        with connect() as conn:
            return list_agent_comms_messages(
                conn,
                agent_id=agent,
                search=search,
                limit=limit,
            )
    except Exception as exc:
        _log.exception("GET /api/comms/feed failed")
        raise HTTPException(status_code=500, detail=f"Comms feed failed: {exc}")


@app.get("/api/comms/channels")
def get_comms_channels(
    include_archived: bool = False,
    limit: int = 200,
):
    """native per-pair conversation list projected from handoffs."""
    try:
        from elevate_cli.data import connect, list_agent_comms_channels

        with connect() as conn:
            return list_agent_comms_channels(
                conn,
                include_archived=include_archived,
                limit=limit,
            )
    except Exception as exc:
        _log.exception("GET /api/comms/channels failed")
        raise HTTPException(status_code=500, detail=f"Comms channels failed: {exc}")


@app.get("/api/comms/channel/{pair}")
def get_comms_channel(pair: str, limit: int = 200):
    """Return one pair transcript in channel-view shape."""
    try:
        from elevate_cli.data import connect, get_agent_comms_channel

        with connect() as conn:
            return get_agent_comms_channel(conn, pair, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/comms/channel/%s failed", pair)
        raise HTTPException(status_code=500, detail=f"Comms channel failed: {exc}")


class _CommsMessageCreateBody(BaseModel):
    fromAgentId: Optional[str] = None
    from_agent_id: Optional[str] = None
    toAgentId: Optional[str] = None
    to_agent_id: Optional[str] = None
    agent: Optional[str] = None
    text: str
    priority: Optional[str] = None
    replyTo: Optional[str] = None
    reply_to: Optional[str] = None
    runNow: Optional[bool] = None
    run_now: Optional[bool] = None


@app.post("/api/messages/send")
@app.post("/api/comms/messages")
def create_comms_message(body: _CommsMessageCreateBody):
    """Send a user/agent message by creating the native handoff it represents."""
    try:
        from elevate_cli.data import connect, create_agent_comms_message

        from_id = body.fromAgentId or body.from_agent_id or "human-web"
        to_id = body.toAgentId or body.to_agent_id or body.agent
        if not to_id:
            raise HTTPException(status_code=400, detail="toAgentId or agent is required")
        with connect() as conn:
            return create_agent_comms_message(
                conn,
                from_agent_id=from_id,
                to_agent_id=to_id,
                text=body.text,
                priority=body.priority or "normal",
                reply_to=body.replyTo or body.reply_to,
                run_now=bool(body.runNow or body.run_now),
                actor="human:web" if str(from_id).strip().lower() in {"human", "human-web"} else from_id,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/comms/messages failed")
        raise HTTPException(status_code=500, detail=f"Comms message failed: {exc}")


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


# ─── Surface Tasks (dispatch work to a surface; kanban) ───────────────────────
class _SurfaceTaskCreateBody(BaseModel):
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    assigned_to: Optional[str] = None
    project: Optional[str] = None
    needs_approval: Optional[bool] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None
    createdBy: Optional[str] = None
    org: Optional[str] = None
    kpi_key: Optional[str] = None
    kpiKey: Optional[str] = None
    due_date: Optional[str] = None
    dueDate: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    blockedBy: Optional[List[str]] = None
    blocks: Optional[List[str]] = None
    actor: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    policyCategory: Optional[str] = None
    policy_category: Optional[str] = None


class _SurfaceTaskPatchBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    assigned_to: Optional[str] = None
    project: Optional[str] = None
    needs_approval: Optional[bool] = None
    notes: Optional[str] = None
    outputs: Optional[List[Any]] = None
    created_by: Optional[str] = None
    createdBy: Optional[str] = None
    org: Optional[str] = None
    kpi_key: Optional[str] = None
    kpiKey: Optional[str] = None
    due_date: Optional[str] = None
    dueDate: Optional[str] = None
    result: Optional[str] = None
    archived: Optional[bool] = None
    blocked_by: Optional[List[str]] = None
    blockedBy: Optional[List[str]] = None
    blocks: Optional[List[str]] = None
    actor: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    policyAction: Optional[str] = None
    policy_action: Optional[str] = None
    policyCategory: Optional[str] = None
    policy_category: Optional[str] = None


class _SurfaceTaskClaimBody(BaseModel):
    agent: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    actor: Optional[str] = None


class _SurfaceTaskArchiveBody(BaseModel):
    dry_run: Optional[bool] = None
    dryRun: Optional[bool] = None
    older_than_days: Optional[int] = None
    olderThanDays: Optional[int] = None


@app.get("/api/tasks")
@app.get("/api/surface-tasks")
def list_surface_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None,
    include_archived: bool = False,
    limit: Optional[int] = None,
):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            reaped: list = []
            if status == "pending":
                # Self-healing on the exact query heartbeats drain with:
                # crash-orphaned in_progress tasks (untouched >1h) return to
                # the pending queue instead of being invisible forever.
                try:
                    reaped = st.reap_stale_in_progress(conn)
                    if reaped:
                        _log.warning(
                            "surface-tasks: reaped %d stale in_progress task(s) back to pending",
                            len(reaped),
                        )
                except Exception:
                    _log.exception("surface-tasks reaper failed (non-fatal)")
            payload = {
                "tasks": st.list_tasks(
                    conn,
                    status=status,
                    assignee=assignee,
                    priority=priority,
                    project=project,
                    include_archived=include_archived,
                    limit=limit,
                )
            }
            if reaped:
                payload["reaped"] = [t.get("id") for t in reaped]
            return payload
    except Exception as exc:
        _log.exception("GET /api/surface-tasks failed")
        raise HTTPException(status_code=500, detail=f"List tasks failed: {exc}")


@app.post("/api/tasks")
@app.post("/api/surface-tasks")
def create_surface_task(body: _SurfaceTaskCreateBody):
    """Dispatch = enqueue: insert a task assigned to a surface (or 'human'). The
    surface's next heartbeat WORK run drains pending tasks (drafts-only)."""
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            task = st.create_task(
                conn,
                title=body.title,
                description=body.description,
                type=body.type or "agent",
                status=body.status or "pending",
                priority=body.priority or "normal",
                assignee=body.assignee or body.assigned_to,
                project=body.project,
                needs_approval=bool(body.needs_approval),
                notes=body.notes,
                created_by=body.created_by or body.createdBy,
                org=body.org,
                kpi_key=body.kpi_key or body.kpiKey,
                due_date=body.due_date or body.dueDate,
                blocked_by=body.blocked_by if body.blocked_by is not None else body.blockedBy,
                blocks=body.blocks,
                actor=body.actor or "human:web",
                actor_agent_id=body.agentId or body.agent_id,
                policy_category=body.policyCategory or body.policy_category or "task",
            )
        return {"ok": True, "task": task}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/surface-tasks failed")
        raise HTTPException(status_code=500, detail=f"Create task failed: {exc}")


@app.get("/api/tasks/stale")
@app.get("/api/surface-tasks/stale")
def check_surface_task_stale():
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            return st.check_stale_tasks(conn)
    except Exception as exc:
        _log.exception("GET /api/surface-tasks/stale failed")
        raise HTTPException(status_code=500, detail=f"Check stale tasks failed: {exc}")


@app.get("/api/tasks/human")
@app.get("/api/surface-tasks/human")
def check_surface_human_tasks():
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            items = st.check_human_tasks(conn)
            return {"tasks": items, "count": len(items)}
    except Exception as exc:
        _log.exception("GET /api/surface-tasks/human failed")
        raise HTTPException(status_code=500, detail=f"Check human tasks failed: {exc}")


@app.post("/api/tasks/archive")
@app.post("/api/surface-tasks/archive")
def archive_surface_tasks(body: _SurfaceTaskArchiveBody):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            return st.archive_tasks(
                conn,
                dry_run=bool(body.dry_run or body.dryRun),
                older_than_days=body.older_than_days or body.olderThanDays or 7,
                actor="human:web",
            )
    except Exception as exc:
        _log.exception("POST /api/surface-tasks/archive failed")
        raise HTTPException(status_code=500, detail=f"Archive tasks failed: {exc}")


@app.post("/api/tasks/compact")
@app.post("/api/surface-tasks/compact")
def compact_surface_tasks(body: _SurfaceTaskArchiveBody):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            return st.compact_tasks(
                conn,
                dry_run=bool(body.dry_run or body.dryRun),
                older_than_days=body.older_than_days or body.olderThanDays or 30,
                actor="human:web",
            )
    except Exception as exc:
        _log.exception("POST /api/surface-tasks/compact failed")
        raise HTTPException(status_code=500, detail=f"Compact tasks failed: {exc}")


@app.get("/api/tasks/{task_id}")
@app.get("/api/surface-tasks/{task_id}")
def get_surface_task(task_id: str):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            task = st.get_task(conn, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return {"task": task}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/surface-tasks/%s failed", task_id)
        raise HTTPException(status_code=500, detail=f"Get task failed: {exc}")


@app.get("/api/tasks/{task_id}/audit")
@app.get("/api/surface-tasks/{task_id}/audit")
def get_surface_task_audit(task_id: str, limit: int = 200):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            return {"events": st.read_task_audit(conn, task_id, limit=limit)}
    except Exception as exc:
        _log.exception("GET /api/surface-tasks/%s/audit failed", task_id)
        raise HTTPException(status_code=500, detail=f"Read task audit failed: {exc}")


@app.post("/api/tasks/{task_id}/claim")
@app.post("/api/surface-tasks/{task_id}/claim")
def claim_surface_task(task_id: str, body: _SurfaceTaskClaimBody):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        agent = body.agent or body.agentId or body.agent_id
        if not agent:
            raise HTTPException(status_code=400, detail="agent is required")
        with connect() as conn:
            task = st.claim_task(
                conn,
                task_id,
                agent=agent,
                actor=body.actor or f"agent:{agent}",
            )
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return {"ok": True, "task": task}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/surface-tasks/%s/claim failed", task_id)
        raise HTTPException(status_code=500, detail=f"Claim task failed: {exc}")


@app.patch("/api/tasks/{task_id}")
@app.patch("/api/surface-tasks/{task_id}")
def patch_surface_task(task_id: str, body: _SurfaceTaskPatchBody):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        actor = str(patch.pop("actor", "human:web") or "human:web")
        actor_agent_id = patch.pop("agentId", None) or patch.pop("agent_id", None)
        policy_action = patch.pop("policyAction", None) or patch.pop("policy_action", None)
        policy_category = patch.pop("policyCategory", None) or patch.pop("policy_category", None)
        with connect() as conn:
            task = st.update_task(
                conn,
                task_id,
                patch,
                actor=actor,
                actor_agent_id=actor_agent_id,
                policy_action=policy_action,
                policy_category=policy_category,
            )
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return {"ok": True, "task": task}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PATCH /api/surface-tasks/%s failed", task_id)
        raise HTTPException(status_code=500, detail=f"Update task failed: {exc}")


@app.delete("/api/tasks/{task_id}")
@app.delete("/api/surface-tasks/{task_id}")
def delete_surface_task(
    task_id: str,
    actor: Optional[str] = None,
    agentId: Optional[str] = None,
    agent_id: Optional[str] = None,
):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            result = st.request_delete_task(
                conn,
                task_id,
                actor=actor or "human:web",
                actor_agent_id=agentId or agent_id,
            )
        if result.get("approvalRequired"):
            return result
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail="task not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("DELETE /api/surface-tasks/%s failed", task_id)
        raise HTTPException(status_code=500, detail=f"Delete task failed: {exc}")


# ─── Surface Approvals (decisions kanban — dashboard-only) ─────────────────────
class _SurfaceApprovalResolveBody(BaseModel):
    decision: str  # 'approve' | 'reject'
    note: Optional[str] = None


@app.get("/api/approvals")
@app.get("/api/surface-approvals")
def list_surface_approvals(
    status: Optional[str] = None,
    surface: Optional[str] = None,
    category: Optional[str] = None,
):
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            return {
                "approvals": st.list_approvals(
                    conn, status=status, surface=surface, category=category
                )
            }
    except Exception as exc:
        _log.exception("GET /api/surface-approvals failed")
        raise HTTPException(status_code=500, detail=f"List approvals failed: {exc}")


@app.patch("/api/approvals/{approval_id}")
@app.patch("/api/surface-approvals/{approval_id}")
def resolve_surface_approval(approval_id: str, body: _SurfaceApprovalResolveBody):
    """Resolve an approval (approve/reject). Dashboard-only — no Telegram path."""
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_tasks as st

        with connect() as conn:
            approval = st.resolve_approval(
                conn, approval_id, decision=body.decision, note=body.note
            )
        if not approval:
            raise HTTPException(status_code=404, detail="approval not found")
        return {"ok": True, "approval": approval}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("PATCH /api/surface-approvals/%s failed", approval_id)
        raise HTTPException(status_code=500, detail=f"Resolve approval failed: {exc}")


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


@app.post("/api/admin/deals")
def post_admin_deal(body: _DealCreateBody):
    """Create one Admin Hub deal card."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, create_deal, get_admin_setup

        jurisdiction = _admin_jurisdiction_config()
        with connect() as conn:
            setup_profile = (get_admin_setup(conn).get("profile") or {})
            province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
            market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
            return create_deal(
                conn,
                title=body.title,
                side=body.side,
                actor=_WEB_ACTOR,
                province=(province or "").strip().upper(),
                board=(body.board or "").strip() or None,
                market=(market or "").strip() or None,
                current_stage=body.currentStage,
                primary_contact_id=body.primaryContactId,
                lofty_contact_id=body.loftyContactId,
                listing_address=body.listingAddress,
                fields=body.fields,
                dispatch_initial_stage=body.dispatchInitialStage and not body.suppressInitialDispatch,
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/deals failed")
        raise HTTPException(status_code=500, detail=f"Create deal failed: {exc}")


@app.post("/api/admin/profile-promotions")
def post_admin_profile_promotion(body: _ProfilePromotionBody):
    """Create or update an Admin Hub deal from a verified lead profile."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, get_admin_setup, promote_profile_to_admin_deal

        jurisdiction = _admin_jurisdiction_config()
        with connect() as conn:
            setup_profile = (get_admin_setup(conn).get("profile") or {})
            province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
            market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
            return promote_profile_to_admin_deal(
                conn,
                profile_id=body.profileId,
                side=body.side,
                actor=_WEB_ACTOR,
                province=(province or "").strip().upper(),
                board=(body.board or "").strip() or None,
                market=(market or "").strip() or None,
                current_stage=body.currentStage,
                display_name=body.displayName,
                primary_contact_id=body.primaryContactId,
                listing_address=body.listingAddress,
                workflow=body.workflow,
                profile_context=body.profileContext,
                verifiers=body.verifiers,
                fields=body.fields,
                dispatch_initial_stage=body.dispatchInitialStage,
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/profile-promotions failed")
        raise HTTPException(status_code=500, detail=f"Promote profile failed: {exc}")


@app.post("/api/admin/deals/{deal_id}/move")
def post_admin_deal_move(deal_id: str, body: _DealMoveBody):
    """Move one Admin Hub deal card to another stage."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, move_deal_stage

        with connect() as conn:
            return move_deal_stage(
                conn,
                deal_id,
                to_stage=body.toStage,
                actor=_WEB_ACTOR,
                force=body.force,
            )
    except HTTPException:
        raise
    except DealPhaseGateBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "gate": exc.gate,
            },
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/deals/%s/move failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Move deal failed: {exc}")


@app.get("/api/admin/deals/deadlines")
def get_admin_deal_deadlines(near_subject_days: int = 21, near_close_days: int = 30):
    """Deals with an upcoming subject-removal or completion deadline.

    Powers the admin "Coming up" strip so the realtor sees what needs prepping
    (subject removal / amendment / closing) before it lands. Reuses the existing
    deals_overview soon-lists; no new data, just surfaced.
    """
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, deals_overview

        with connect() as conn:
            ov = deals_overview(
                conn,
                near_subject_days=near_subject_days,
                near_close_days=near_close_days,
            )
        return {
            "subjectsSoon": ov.get("subjectsSoon", []),
            "closingsSoon": ov.get("closingsSoon", []),
            "staleStages": ov.get("staleStages", []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/admin/deals/deadlines failed")
        raise HTTPException(status_code=500, detail=f"Deadlines failed: {exc}")


@app.post("/api/admin/deals/{deal_id}/toggle")
def post_admin_deal_toggle(deal_id: str, body: _DealToggleBody):
    """Update one checklist, toggle, or enum field on an Admin Hub deal."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, set_deal_toggle

        with connect() as conn:
            return set_deal_toggle(
                conn,
                deal_id,
                field=body.field,
                value=body.value,
                actor=_WEB_ACTOR,
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/deals/%s/toggle failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Toggle deal failed: {exc}")


# ---------------------------------------------------------------------------
# /api/deals — source-of-truth deal context + skill callback spine
# ---------------------------------------------------------------------------


@app.get("/api/deals/{deal_id}/context")
def get_deal_source_context(deal_id: str):
    """Return the single source-of-truth blob every admin skill starts from."""
    try:
        from elevate_cli.data import connect, get_deal_context

        with connect() as conn:
            return get_deal_context(conn, deal_id)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/deals/%s/context failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Deal context failed: {exc}")


@app.post("/api/deals/{deal_id}/fields")
def post_deal_fields(deal_id: str, body: _DealFieldsBody):
    """Patch durable date/money/property fields on the deal source of truth."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, set_deal_fields

        with connect() as conn:
            return set_deal_fields(conn, deal_id, actor=_WEB_ACTOR, fields=body.fields)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/deals/%s/fields failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Deal field update failed: {exc}")


@app.post("/api/deals/{deal_id}/advance")
def post_deal_advance(deal_id: str, body: _DealAdvanceBody):
    """Advance a deal to the next package phase when its gate is clear."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, get_deal_context, move_deal_stage

        with connect() as conn:
            context = get_deal_context(conn, deal_id)
            gate = ((context.get("dealFlow") or {}).get("gate") or {})
            next_stage = gate.get("nextStage")
            if next_stage is None:
                raise HTTPException(status_code=400, detail="deal is already at the final stage")
            if not body.force and not gate.get("canAdvance"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "deal phase gate is blocked",
                        "gate": gate,
                    },
                )
            move_deal_stage(
                conn,
                deal_id,
                to_stage=int(next_stage),
                actor=_WEB_ACTOR,
                force=body.force,
                gate_checked=not body.force,
            )
            return get_deal_context(conn, deal_id)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/deals/%s/advance failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Deal advance failed: {exc}")


@app.post("/api/deals/{deal_id}/contacts")
def post_deal_contact(deal_id: str, body: _DealContactBody):
    """Attach a co-contact role (lawyer/lender/inspector/etc.) to a deal."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import add_deal_contact, connect

        with connect() as conn:
            return add_deal_contact(
                conn,
                deal_id,
                role=body.role,
                contact_id=body.contactId,
                notes=body.notes,
                actor=_WEB_ACTOR,
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/deals/%s/contacts failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Deal contact link failed: {exc}")


@app.post("/api/deals/{deal_id}/attachments")
def post_deal_attachment(deal_id: str, body: _DealAttachmentBody):
    """Attach an artifact/file to the deal source of truth."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import add_deal_attachment, connect

        with connect() as conn:
            return add_deal_attachment(
                conn,
                deal_id,
                kind=body.kind,
                file_path=body.filePath,
                summary=body.summary,
                source_run_id=body.sourceRunId,
                source_snapshot_id=body.sourceSnapshotId,
                actor=_WEB_ACTOR,
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/deals/%s/attachments failed", deal_id)
        raise HTTPException(status_code=500, detail=f"Deal attachment failed: {exc}")


@app.post("/api/deals/{deal_id}/runs/{run_id}/result")
def post_deal_run_result(deal_id: str, run_id: str, body: _RunResultBody):
    """Standard callback for admin skills to close action_runs and attach outputs."""
    try:
        from elevate_cli.data import connect, record_run_result

        artifacts = [item.model_dump(exclude_none=True) for item in body.artifacts]
        next_tasks = body.next_tasks or body.nextTasks
        checklist_updates = body.checklist_updates or body.checklistUpdates
        human_prompt = body.human_prompt or body.humanPrompt
        idempotency_key = body.idempotency_key or body.idempotencyKey
        with connect() as conn:
            return record_run_result(
                conn,
                deal_id,
                run_id,
                status=body.status,
                idempotency_key=idempotency_key,
                artifacts=artifacts,
                next_tasks=next_tasks,
                checklist_updates=checklist_updates,
                human_prompt=human_prompt,
                error=body.error,
                actor="skill:web-callback",
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/deals/%s/runs/%s/result failed", deal_id, run_id)
        raise HTTPException(status_code=500, detail=f"Deal run result failed: {exc}")


# ---------------------------------------------------------------------------
# /admin/actions — stage-action registry + run log
# ---------------------------------------------------------------------------


@app.get("/api/admin/actions")
def get_admin_actions(
    trigger: Optional[str] = None,
    side: Optional[str] = None,
    enabled: Optional[bool] = None,
    skill: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """List stage-action registry rows."""
    try:
        from elevate_cli.data import connect, list_actions

        with connect() as conn:
            rows = list_actions(
                conn,
                trigger=trigger or None,
                side=side or None,
                enabled=enabled,
                skill=skill or None,
                limit=limit,
                offset=offset,
            )
            return {"items": rows, "count": len(rows)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/actions failed")
        raise HTTPException(status_code=500, detail=f"Admin actions failed: {exc}")


@app.post("/api/admin/actions")
def post_admin_action(body: _AdminActionCreateBody):
    """Create a new registry row."""
    try:
        from elevate_cli.data import connect, create_action

        with connect() as conn:
            return create_action(
                conn,
                name=body.name,
                trigger=body.trigger,
                skill=body.skill,
                side=body.side,
                from_stage=body.fromStage,
                to_stage=body.toStage,
                field_key=body.fieldKey,
                condition=body.condition,
                skill_args=body.skillArgs,
                province_filter=body.provinceFilter,
                enabled=body.enabled,
                priority=body.priority,
                approval_required=body.approvalRequired,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/actions failed")
        raise HTTPException(status_code=500, detail=f"Create action failed: {exc}")


@app.post("/api/admin/actions/defaults")
def post_admin_actions_defaults():
    """Idempotently seed the default listing phase action registry."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, ensure_default_admin_actions

        with connect() as conn:
            return ensure_default_admin_actions(conn)
    except Exception as exc:
        _log.exception("POST /api/admin/actions/defaults failed")
        raise HTTPException(status_code=500, detail=f"Seed default admin actions failed: {exc}")


@app.patch("/api/admin/actions/{action_id}")
def patch_admin_action(action_id: str, body: _AdminActionUpdateBody):
    """Update an existing registry row, bumping its version."""
    try:
        from elevate_cli.data import connect, update_action

        with connect() as conn:
            return update_action(
                conn,
                action_id,
                name=body.name,
                trigger=body.trigger,
                skill=body.skill,
                side=body.side,
                from_stage=body.fromStage,
                to_stage=body.toStage,
                field_key=body.fieldKey,
                condition=body.condition,
                skill_args=body.skillArgs,
                province_filter=body.provinceFilter,
                enabled=body.enabled,
                priority=body.priority,
                approval_required=body.approvalRequired,
            )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PATCH /api/admin/actions/%s failed", action_id)
        raise HTTPException(status_code=500, detail=f"Update action failed: {exc}")


@app.delete("/api/admin/actions/{action_id}")
def delete_admin_action(action_id: str):
    """Delete a registry row. Cascades to its queued runs."""
    try:
        from elevate_cli.data import connect, delete_action

        with connect() as conn:
            delete_action(conn, action_id)
        return {"ok": True, "id": action_id}
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        _log.exception("DELETE /api/admin/actions/%s failed", action_id)
        raise HTTPException(status_code=500, detail=f"Delete action failed: {exc}")


@app.get("/api/admin/action-runs")
def get_admin_action_runs(
    deal_id: Optional[str] = None,
    registry_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List recent dispatcher run rows."""
    try:
        from elevate_cli.data import connect, list_action_runs

        with connect() as conn:
            rows = list_action_runs(
                conn,
                deal_id=deal_id or None,
                registry_id=registry_id or None,
                status=status or None,
                limit=limit,
                offset=offset,
            )
            return {"items": rows, "count": len(rows)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/action-runs failed")
        raise HTTPException(status_code=500, detail=f"Admin runs failed: {exc}")


@app.post("/api/admin/action-runs/drain")
def post_admin_action_runs_drain(limit: int = 50):
    """Drain queued Admin action runs into cron."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, drain_queued_action_runs

        with connect() as conn:
            rows = drain_queued_action_runs(
                conn,
                limit=max(1, min(200, int(limit))),
                actor=_WEB_ACTOR,
            )
        return {"items": rows, "count": len(rows)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/action-runs/drain failed")
        raise HTTPException(status_code=500, detail=f"Drain action runs failed: {exc}")


@app.post("/api/admin/action-runs/{run_id}/approve")
def post_admin_action_run_approve(run_id: str, body: _ActionRunApproveBody):
    """Approve or cancel a human-gated Admin action run."""
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import approve_action_run, connect

        with connect() as conn:
            return approve_action_run(
                conn,
                run_id,
                approved=body.approved,
                actor=_WEB_ACTOR,
                create_cron_job=body.runNow,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/action-runs/%s/approve failed", run_id)
        raise HTTPException(status_code=500, detail=f"Approve action run failed: {exc}")


@app.get("/api/admin/tasks")
def get_admin_tasks(
    status: Optional[str] = "open",
    limit: int = 100,
    offset: int = 0,
):
    """Project active deal phase gates and AI actions into the task board."""
    try:
        from elevate_cli.data import connect, list_deal_tasks

        with connect() as conn:
            rows = list_deal_tasks(
                conn,
                status=status or "open",
                limit=limit,
                offset=offset,
            )
            return {"items": rows, "count": len(rows)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/admin/tasks failed")
        raise HTTPException(status_code=500, detail=f"Admin tasks failed: {exc}")


@app.post("/api/admin/tasks/run")
def post_admin_task_run(body: _AdminTaskRunBody):
    """Queue an AI-capable task from the task board against its deal file."""
    if not body.dealId or not body.dealId.strip():
        raise HTTPException(status_code=400, detail="dealId is required")
    if not body.skill or not body.skill.strip():
        raise HTTPException(status_code=400, detail="skill is required")
    try:
        _require_admin_setup_ready_for_launch()
        from elevate_cli.data import connect, queue_action_run

        with connect() as conn:
            return queue_action_run(
                conn,
                deal_id=body.dealId,
                skill=body.skill,
                name=body.title or f"Task board: {body.skill}",
                payload={
                    "trigger": "task_board",
                    "sourceTaskId": body.sourceTaskId,
                    "taskTitle": body.title,
                },
                create_cron_job=body.runNow,
                actor=_WEB_ACTOR,
            )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/tasks/run failed")
        raise HTTPException(status_code=500, detail=f"Run admin task failed: {exc}")


# ---------------------------------------------------------------------------
# /admin/templates — template library (Live / Proposed / Retired tabs)
# ---------------------------------------------------------------------------


@app.get("/api/admin/templates")
def get_admin_templates(
    tab: str = "live",
    lane: Optional[str] = None,
    channel: Optional[str] = None,
):
    """Return the template library for one of three tabs.

    * ``tab=live`` (default) — leaderboard view, split into authoritative
      (uses ≥ 50 OR age > 30d) and trial buckets. Versions roll up by
      lineage so an edit doesn't reset the apparent stats.
    * ``tab=proposed`` — agent-proposed templates awaiting human approval.
    * ``tab=retired`` — historical, read-only.
    """
    tab_norm = tab.lower()
    if tab_norm not in _ADMIN_TEMPLATES_TABS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown tab {tab!r} (expected one of {sorted(_ADMIN_TEMPLATES_TABS)})",
        )
    try:
        from elevate_cli.data import (
            connect,
            list_proposed_templates,
            list_templates,
            template_leaderboard,
        )

        with connect() as conn:
            if tab_norm == "live":
                board = template_leaderboard(conn, lane=lane, channel=channel)
                return {
                    "tab": "live",
                    "authoritative": board["authoritative"],
                    "trial": board["trial"],
                    "count": len(board["authoritative"]) + len(board["trial"]),
                }
            if tab_norm == "proposed":
                rows = list_proposed_templates(conn)
                return {"tab": "proposed", "items": rows, "count": len(rows)}
            # retired
            rows = list_templates(conn, status="retired", lane=lane)
            return {"tab": "retired", "items": rows, "count": len(rows)}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/admin/templates failed")
        raise HTTPException(status_code=500, detail=f"Admin templates failed: {exc}")


@app.post("/api/admin/templates/{template_id}/approve")
def post_admin_template_approve(template_id: str):
    """Flip a proposed template to status='live'. Records audit fields."""
    try:
        from elevate_cli.data import approve_template, connect, get_template

        with connect() as conn:
            if get_template(conn, template_id) is None:
                raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
            return approve_template(conn, template_id, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/templates/%s/approve failed", template_id)
        raise HTTPException(status_code=500, detail=f"Approve template failed: {exc}")


@app.post("/api/admin/templates/{template_id}/reject")
def post_admin_template_reject(template_id: str, body: _TemplateRejectBody):
    """Mark a proposed template ``status='retired'`` with a reason note."""
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=400, detail="reason is required")
    try:
        from elevate_cli.data import connect, get_template, reject_template

        with connect() as conn:
            if get_template(conn, template_id) is None:
                raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
            return reject_template(
                conn, template_id, body.reason.strip(), actor=_WEB_ACTOR
            )
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/admin/templates/%s/reject failed", template_id)
        raise HTTPException(status_code=500, detail=f"Reject template failed: {exc}")


@app.post("/api/admin/templates/{template_id}/edit")
def post_admin_template_edit(template_id: str, body: _TemplateEditBody):
    """Bump version: parent → ``superseded``, new live row with ``version+1``."""
    if not body.body or not body.body.strip():
        raise HTTPException(status_code=400, detail="body is required")
    try:
        from elevate_cli.data import connect, edit_template, get_template

        with connect() as conn:
            if get_template(conn, template_id) is None:
                raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
            return edit_template(
                conn, template_id, new_body=body.body, actor=_WEB_ACTOR
            )
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/admin/templates/%s/edit failed", template_id)
        raise HTTPException(status_code=500, detail=f"Edit template failed: {exc}")


@app.post("/api/admin/templates/{template_id}/retire")
def post_admin_template_retire(template_id: str):
    """Soft-deprecate a live template. Counters stay queryable."""
    try:
        from elevate_cli.data import connect, get_template, retire_template

        with connect() as conn:
            if get_template(conn, template_id) is None:
                raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
            return retire_template(conn, template_id, actor=_WEB_ACTOR)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/admin/templates/%s/retire failed", template_id)
        raise HTTPException(status_code=500, detail=f"Retire template failed: {exc}")



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
