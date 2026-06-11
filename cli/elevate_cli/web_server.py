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
import importlib.util
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

import yaml

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
    OPTIONAL_ENV_VARS,
    get_config_path,
    get_env_path,
    get_elevate_home,
    get_env_value,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from elevate_cli.access import dashboard_access_status
from elevate_cli.data.deals import DealPhaseGateBlocked
from gateway.status import get_running_pid, read_runtime_status

try:
    from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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


app = FastAPI(title="Elevate", version=__version__)


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

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

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
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
    "/api/dashboard/plugins/rescan",
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


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


_AGENT_TELEGRAM_CHANNEL_RE = re.compile(r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_CHANNEL$")
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


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r — using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint (cross-container).

    Uses ``/health/detailed`` first (returns full state), falling back to
    the simpler ``/health`` endpoint.  Returns ``(is_alive, body_dict)``.

    Accepts any of these as ``GATEWAY_HEALTH_URL``:
    - ``http://gateway:8642``                (base URL — recommended)
    - ``http://gateway:8642/health``         (explicit health path)
    - ``http://gateway:8642/health/detailed`` (explicit detailed path)

    This is a **blocking** call — run via ``run_in_executor`` from async code.
    """
    if not _GATEWAY_HEALTH_URL:
        return False, None

    # Normalise to base URL so we always probe the right paths regardless of
    # whether the user included /health or /health/detailed in the env var.
    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


@app.get("/api/status")
async def get_status():
    cached = _cached_status_payload()
    if cached is not None:
        return cached

    current_ver, latest_ver = check_config_version()

    # --- Gateway liveness detection ---
    # Try local PID check first (same-host).  If that fails and a remote
    # GATEWAY_HEALTH_URL is configured, probe the gateway over HTTP so the
    # dashboard works when the gateway runs in a separate container.
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    remote_health_body: dict | None = None

    if not gateway_running and _GATEWAY_HEALTH_URL:
        loop = asyncio.get_event_loop()
        alive, remote_health_body = await loop.run_in_executor(
            None, _probe_gateway_health
        )
        if alive:
            gateway_running = True
            # PID from the remote container (display only — not locally valid)
            if remote_health_body:
                gateway_pid = remote_health_body.get("pid")

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    # Prefer the detailed health endpoint response (has full state) when the
    # local runtime status file is absent or stale (cross-container).
    runtime = read_runtime_status()
    if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
        runtime = remote_health_body

    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = gateway_state if gateway_state in ("stopped", "startup_failed") else "stopped"
            gateway_platforms = {}
        elif gateway_running and remote_health_body is not None:
            # The health probe confirmed the gateway is alive, but the local
            # runtime status file may be stale (cross-container).  Override
            # stopped/None state so the dashboard shows the correct badge.
            if gateway_state in (None, "stopped"):
                gateway_state = "running"

    # If there was no runtime info at all but the health probe confirmed alive,
    # ensure we still report the gateway as running (no shared volume scenario).
    if gateway_running and gateway_state is None and remote_health_body is not None:
        gateway_state = "running"

    active_sessions = 0
    try:
        from elevate_cli.data.chat_sessions import active_session_count

        active_sessions = active_session_count(_SESSION_ACTIVE_WINDOW_SEC)
    except Exception:
        try:
            from elevate_state import SessionDB
            db = _get_session_db()
            try:
                sessions = db.list_sessions_rich(limit=50)
                now = time.time()
                active_sessions = sum(
                    1 for s in sessions
                    if s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0)))
                    < _SESSION_ACTIVE_WINDOW_SEC
                )
            finally:
                db.close()
        except Exception:
            pass

    payload = {
        "version": __version__,
        "release_date": __release_date__,
        "project_root": str(WORKSPACE_ROOT),
        "elevate_home": str(get_elevate_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_health_url": _GATEWAY_HEALTH_URL,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
    }
    _store_status_payload(payload)
    return payload


@app.get("/api/access")
async def get_access_status():
    """Return local entitlement state used to unlock paid dashboard packs."""
    return dashboard_access_status()


# ---------------------------------------------------------------------------
# License / Activation endpoints
# ---------------------------------------------------------------------------

class LicenseActivateBody(BaseModel):
    email: str
    password: str
    backend_url: Optional[str] = None
    skip_skill_sync: bool = False
    # Collected at "Create account" (signup only); ignored by activate/login.
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class LoginCodeRequestBody(BaseModel):
    email: str
    backend_url: Optional[str] = None


class LoginCodeVerifyBody(BaseModel):
    email: str
    code: str
    backend_url: Optional[str] = None
    skip_skill_sync: bool = False


class LicenseLogoutBody(BaseModel):
    pass


@app.get("/api/license/status")
async def get_license_status():
    from elevate_cli import license as lic_mod

    lic = lic_mod.load()
    if not lic:
        return {
            "authenticated": False,
            "email": None,
            "tier": None,
            "license_id": None,
            "entitlements": [],
            "expires_at": None,
            "expired": True,
            "status_text": lic_mod.status_text(),
            "packs": dashboard_access_status().get("packs", {}),
        }
    return {
        "authenticated": True,
        "email": lic.email,
        "tier": lic.tier,
        "license_id": lic.license_id,
        "entitlements": list(lic.entitlements or []),
        "expires_at": lic.expires_at,
        "expired": lic.is_expired(margin=0),
        "status_text": lic_mod.status_text(lic),
        "packs": dashboard_access_status().get("packs", {}),
    }


@app.post("/api/license/activate")
async def activate_license(body: LicenseActivateBody, request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod

    if body.backend_url:
        lic_mod.BACKEND_URL = body.backend_url.rstrip("/")
        os.environ["ELEVATE_BACKEND_URL"] = lic_mod.BACKEND_URL
        try:
            from elevate_cli.config import save_env_value
            save_env_value("ELEVATE_BACKEND_URL", lic_mod.BACKEND_URL)
        except Exception:
            pass

    try:
        lic = lic_mod.login(body.email, body.password)
    except lic_mod.LicenseError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
    return {
        "authenticated": True,
        "email": lic.email,
        "tier": lic.tier,
        "license_id": lic.license_id,
        "entitlements": list(lic.entitlements or []),
        "expires_at": lic.expires_at,
        "packs": activation.get("packs", {}),
        "skill_count": activation.get("skill_count", 0),
        "skill_names": activation.get("skill_names", []),
        "skill_error": activation.get("skill_error"),
    }


@app.post("/api/license/signup")
async def signup_license(body: LicenseActivateBody, request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod

    if body.backend_url:
        lic_mod.BACKEND_URL = body.backend_url.rstrip("/")
        os.environ["ELEVATE_BACKEND_URL"] = lic_mod.BACKEND_URL
        try:
            from elevate_cli.config import save_env_value
            save_env_value("ELEVATE_BACKEND_URL", lic_mod.BACKEND_URL)
        except Exception:
            pass

    try:
        lic = lic_mod.create_account(
            body.email, body.password, first_name=body.first_name, last_name=body.last_name
        )
    except lic_mod.LicenseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
    return {
        "authenticated": True,
        "email": lic.email,
        "tier": lic.tier,
        "license_id": lic.license_id,
        "entitlements": list(lic.entitlements or []),
        "expires_at": lic.expires_at,
        "packs": activation.get("packs", {}),
        "skill_count": activation.get("skill_count", 0),
        "skill_names": activation.get("skill_names", []),
        "skill_error": activation.get("skill_error"),
    }


@app.post("/api/license/request-code")
async def request_license_code(body: LoginCodeRequestBody, request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod

    if body.backend_url:
        lic_mod.BACKEND_URL = body.backend_url.rstrip("/")
        os.environ["ELEVATE_BACKEND_URL"] = lic_mod.BACKEND_URL

    try:
        lic_mod.request_login_code(body.email)
    except lic_mod.LicenseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/api/license/activate-code")
async def activate_license_code(body: LoginCodeVerifyBody, request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod

    if body.backend_url:
        lic_mod.BACKEND_URL = body.backend_url.rstrip("/")
        os.environ["ELEVATE_BACKEND_URL"] = lic_mod.BACKEND_URL

    try:
        lic = lic_mod.login_with_code(body.email, body.code)
    except lic_mod.LicenseError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
    return {
        "authenticated": True,
        "email": lic.email,
        "tier": lic.tier,
        "license_id": lic.license_id,
        "entitlements": list(lic.entitlements or []),
        "expires_at": lic.expires_at,
        "packs": activation.get("packs", {}),
        "skill_count": activation.get("skill_count", 0),
        "skill_names": activation.get("skill_names", []),
        "skill_error": activation.get("skill_error"),
    }


@app.post("/api/license/sync-skills")
async def sync_license_skills(request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod
    from elevate_cli import cloud_skills

    lic = lic_mod.load()
    if not lic:
        raise HTTPException(status_code=401, detail="Not authenticated. Activate first.")

    try:
        if lic.is_expired():
            lic = lic_mod.refresh(lic)
    except lic_mod.LicenseError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    try:
        sync_result = cloud_skills.sync_all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill sync failed: {exc}")

    return {
        "skill_count": sync_result.get("skill_count", 0),
        "skill_names": sync_result.get("skill_names", []),
        "path": sync_result.get("path"),
        "removed": sync_result.get("removed", []),
        "errors": sync_result.get("errors", []),
        "packs": dashboard_access_status().get("packs", {}),
    }


@app.post("/api/license/logout")
async def logout_license(request: Request):
    _require_token(request)

    from elevate_cli import license as lic_mod

    cleared = lic_mod.clear()

    from elevate_cli.access import REAL_ESTATE_ENTITLEMENTS, update_entitlement
    for entitlement in REAL_ESTATE_ENTITLEMENTS:
        try:
            update_entitlement(entitlement, status="locked", owned_snapshot=False)
        except Exception:
            pass

    return {
        "authenticated": False,
        "cleared": cleared,
        "packs": dashboard_access_status().get("packs", {}),
    }


from elevate_cli.web_routes.agent_hub import create_agent_hub_router
from elevate_cli.web_routes.cron import create_cron_router
from elevate_cli.web_routes.source_connectors import create_source_connectors_router
from elevate_cli.web_routes.today import create_today_router

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


class SessionTitleUpdate(BaseModel):
    title: Optional[str] = None


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


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Kick off a ``elevate gateway restart`` in the background."""
    try:
        proc = _spawn_elevate_action(["gateway", "restart"], "gateway-restart")
    except Exception as exc:
        _log.exception("Failed to spawn gateway restart")
        raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-restart",
    }


@app.post("/api/gateway/start")
async def start_gateway_action():
    """Start a detached local gateway runner using the current interpreter."""
    try:
        proc = _spawn_elevate_action(["gateway", "run", "--replace"], "gateway-start")
    except Exception as exc:
        _log.exception("Failed to spawn gateway start")
        raise HTTPException(status_code=500, detail=f"Failed to start gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-start",
    }


@app.post("/api/telegram/pair/start")
async def start_telegram_pairing(request: Request):
    """Save the bot token, switch unauthorized DMs to pairing mode, restart gateway.

    Drives the web wizard's Telegram pairing ritual — same effect as running
    ``elevate gateway setup`` then ``elevate gateway start`` from the CLI. After
    this returns, the gateway will reload with the new token and the bot will
    reply with a pairing code on the first DM from an unknown user.
    """
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    bot_token = str(body.get("bot_token") or "").strip()
    if not bot_token:
        raise HTTPException(status_code=400, detail="bot_token is required")
    if not _looks_like_telegram_bot_token(bot_token):
        raise HTTPException(
            status_code=400,
            detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
        )

    _sync_executive_telegram_aliases("TELEGRAM_BOT_TOKEN", bot_token)
    save_env_value("TELEGRAM_BOT_TOKEN", bot_token)
    save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", "pair")

    try:
        proc = _spawn_elevate_action(["gateway", "restart"], "gateway-restart")
    except Exception as exc:
        _log.exception("Failed to spawn gateway restart during telegram pair start")
        raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")

    return {
        "ok": True,
        "action": "gateway-restart",
        "pid": proc.pid,
    }


@app.get("/api/telegram/pair/pending")
async def list_telegram_pairings():
    """Return pending pairing codes plus already-approved users.

    The wizard polls this after restarting the gateway. As soon as the user DMs
    /start to the bot, an unauthorized-DM handler mints a code, and this
    endpoint surfaces ``{code, user_id, user_name, age_minutes}`` so the wizard
    can offer a one-click approval.
    """
    try:
        from gateway.pairing import PairingStore
        store = PairingStore()
        pending = store.list_pending("telegram")
        approved = store.list_approved("telegram")
    except Exception as exc:
        _log.exception("Failed to list telegram pairings")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pending": pending, "approved": approved}


@app.post("/api/telegram/pair/approve")
async def approve_telegram_pairing(request: Request):
    """Approve a pairing code minted by the bot.

    Equivalent to ``elevate pairing approve telegram <code>`` plus the
    post-approval bookkeeping that ``_telegram_startup_preflight`` does in the
    CLI: merge the user's id into ``TELEGRAM_ALLOWED_USERS``, flip
    ``TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR`` back to ``ignore`` so strangers
    can't keep minting codes, and optionally pin the user as the home channel.
    """
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    code = str(body.get("code") or "").strip()
    set_home = bool(body.get("set_home"))
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    try:
        from gateway.pairing import PairingStore
        store = PairingStore()
        result = store.approve_code("telegram", code)
    except Exception as exc:
        _log.exception("Failed to approve telegram pairing")
        raise HTTPException(status_code=500, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Code not found or expired")

    user_id = str(result.get("user_id") or "").strip()
    user_name = str(result.get("user_name") or "").strip()

    if user_id:
        existing = str(get_env_value("TELEGRAM_ALLOWED_USERS") or "").strip()
        existing_ids = [v.strip() for v in existing.split(",") if v.strip()]
        if user_id not in existing_ids:
            existing_ids.append(user_id)
            save_env_value("TELEGRAM_ALLOWED_USERS", ",".join(existing_ids))
        save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", "ignore")
        if set_home:
            _sync_executive_telegram_aliases("TELEGRAM_HOME_CHANNEL", user_id)
            save_env_value("TELEGRAM_HOME_CHANNEL", user_id)

    return {
        "ok": True,
        "user_id": user_id,
        "user_name": user_name,
    }


# ────────────────────────────────────────────────────────────────────
# Channel configure endpoints. Each mirrors a CLI ``_setup_*`` flow
# from ``elevate_cli/setup.py`` so the web wizard writes to the same
# env vars the gateway reads at startup. Without these, the wizard's
# "configured" state is cosmetic — the gateway sees nothing.
# ────────────────────────────────────────────────────────────────────


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _token_preview(token: str) -> str:
    """Mask all but the last 4 chars of a secret for safe display."""
    s = str(token or "")
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * (len(s) - 4) + s[-4:]


@app.get("/api/channels/telegram/status")
async def telegram_status():
    """Return the currently-wired Telegram bot's identity + env config.

    Calls Telegram's ``getMe`` so the wizard can show the bot's display name
    and @username — answers "which bot is this token actually attached to?".
    Falls back to env-only data if the API call fails (offline, bad token).
    """
    token = get_env_value("TELEGRAM_BOT_TOKEN") or ""
    if not token:
        return {
            "configured": False,
            "tokenPreview": "",
            "allowedUsers": "",
            "homeChannel": "",
            "dmBehavior": "",
            "allowAllUsers": False,
        }

    bot_info: dict[str, Any] = {}
    try:
        import urllib.request as _ur
        import json as _json
        req = _ur.Request(
            f"https://api.telegram.org/bot{token}/getMe",
            headers={"User-Agent": "elevate-wizard"},
        )
        with _ur.urlopen(req, timeout=5) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
        if payload.get("ok") and isinstance(payload.get("result"), dict):
            r = payload["result"]
            bot_info = {
                "botId": r.get("id"),
                "botUsername": r.get("username") or "",
                "botName": (r.get("first_name") or "").strip(),
                "canJoinGroups": bool(r.get("can_join_groups")),
                "canReadAllGroupMessages": bool(r.get("can_read_all_group_messages")),
            }
    except Exception as exc:
        bot_info = {"error": str(exc)[:200]}

    return {
        "configured": True,
        "tokenPreview": _token_preview(token),
        "allowedUsers": get_env_value("TELEGRAM_ALLOWED_USERS") or "",
        "homeChannel": get_env_value("TELEGRAM_HOME_CHANNEL") or "",
        "dmBehavior": get_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
        "allowAllUsers": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
        **bot_info,
    }


@app.post("/api/channels/telegram/configure")
async def configure_telegram(request: Request):
    """Mirror ``setup._setup_telegram``. Saves TELEGRAM_BOT_TOKEN,
    TELEGRAM_ALLOWED_USERS, TELEGRAM_HOME_CHANNEL,
    TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR, GATEWAY_ALLOW_ALL_USERS.

    Token is optional when one is already in env — the wizard can update
    just the allowlist / home / DM behavior without re-pasting the secret.
    """
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    bot_token = _strip(body.get("bot_token"))
    allowed = _strip(body.get("allowed_users"))
    home = _strip(body.get("home_channel"))
    dm_behavior = _strip(body.get("dm_behavior")).lower()
    allow_all = bool(body.get("allow_all_users"))

    existing_token = get_env_value("TELEGRAM_BOT_TOKEN") or ""
    if bot_token:
        if not _looks_like_telegram_bot_token(bot_token):
            raise HTTPException(
                status_code=400,
                detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
            )
        _sync_executive_telegram_aliases("TELEGRAM_BOT_TOKEN", bot_token)
        save_env_value("TELEGRAM_BOT_TOKEN", bot_token)
    elif not existing_token:
        raise HTTPException(status_code=400, detail="bot_token is required")

    # "allowed_users":""  is an explicit clear, "allowed_users": None is leave-as-is.
    if allowed is not None and body.get("allowed_users") is not None:
        save_env_value("TELEGRAM_ALLOWED_USERS", allowed.replace(" ", ""))
    if body.get("home_channel") is not None:
        # Validate: a Telegram chat target is a numeric id (incl. -100… groups)
        # or an @username — never a pairing code. Storing a code here is what
        # crashed cron→Telegram delivery (int('8RWK85SD') ValueError loop).
        _hc = (home or "").strip()
        if _hc and not (_hc.lstrip("-").isdigit() or _hc.startswith("@")):
            raise HTTPException(
                status_code=400,
                detail=(
                    "home_channel must be a numeric chat id or an @username — "
                    f"got {home!r} (looks like a pairing code, not a chat id)."
                ),
            )
        save_env_value("TELEGRAM_HOME_CHANNEL", home)
    if dm_behavior:
        if dm_behavior not in {"pair", "ignore", "open"}:
            raise HTTPException(
                status_code=400,
                detail="dm_behavior must be one of: pair, ignore, open",
            )
        save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", dm_behavior)
    if allow_all:
        save_env_value("GATEWAY_ALLOW_ALL_USERS", "true")
    elif body.get("allow_all_users") is False:
        save_env_value("GATEWAY_ALLOW_ALL_USERS", "false")

    return {
        "ok": True,
        "tokenPreview": _token_preview(bot_token or existing_token),
        "allowedUsers": get_env_value("TELEGRAM_ALLOWED_USERS") or "",
        "homeChannel": get_env_value("TELEGRAM_HOME_CHANNEL") or "",
        "dmBehavior": get_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
        "allowAllUsers": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
    }


@app.post("/api/channels/discord/configure")
async def configure_discord(request: Request):
    """Mirror ``setup._setup_discord``. Saves DISCORD_BOT_TOKEN,
    DISCORD_ALLOWED_USERS, DISCORD_HOME_CHANNEL, DISCORD_CHANNEL_ID
    (the legacy key the agent-setup overlay checks)."""
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    bot_token = _strip(body.get("bot_token"))
    allowed = _strip(body.get("allowed_users"))
    home_channel = _strip(body.get("home_channel"))
    if not bot_token and not get_env_value("DISCORD_BOT_TOKEN"):
        raise HTTPException(status_code=400, detail="bot_token is required")

    if bot_token:
        save_env_value("DISCORD_BOT_TOKEN", bot_token)
    if allowed:
        cleaned = []
        for uid in allowed.replace(" ", "").split(","):
            uid = uid.strip()
            if uid.startswith("<@") and uid.endswith(">"):
                uid = uid.lstrip("<@!").rstrip(">")
            if uid.lower().startswith("user:"):
                uid = uid[5:]
            if uid:
                cleaned.append(uid)
        save_env_value("DISCORD_ALLOWED_USERS", ",".join(cleaned))
    if home_channel:
        save_env_value("DISCORD_HOME_CHANNEL", home_channel)
        # Legacy alias the agent-setup overlay reads
        save_env_value("DISCORD_CHANNEL_ID", home_channel)

    return {
        "ok": True,
        "tokenPreview": _token_preview(bot_token or get_env_value("DISCORD_BOT_TOKEN") or ""),
        "allowedUsers": get_env_value("DISCORD_ALLOWED_USERS") or "",
        "homeChannel": get_env_value("DISCORD_HOME_CHANNEL") or "",
    }


@app.post("/api/channels/slack/configure")
async def configure_slack(request: Request):
    """Mirror ``setup._setup_slack``. Saves SLACK_BOT_TOKEN (Socket Mode),
    SLACK_APP_TOKEN, SLACK_ALLOWED_USERS."""
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    bot_token = _strip(body.get("bot_token"))
    app_token = _strip(body.get("app_token"))
    allowed = _strip(body.get("allowed_users"))
    if not bot_token and not get_env_value("SLACK_BOT_TOKEN"):
        raise HTTPException(status_code=400, detail="bot_token (xoxb-…) is required")

    if bot_token:
        save_env_value("SLACK_BOT_TOKEN", bot_token)
    if app_token:
        save_env_value("SLACK_APP_TOKEN", app_token)
    if allowed:
        save_env_value("SLACK_ALLOWED_USERS", allowed.replace(" ", ""))

    return {
        "ok": True,
        "botTokenPreview": _token_preview(bot_token or get_env_value("SLACK_BOT_TOKEN") or ""),
        "appTokenPreview": _token_preview(app_token or get_env_value("SLACK_APP_TOKEN") or ""),
        "allowedUsers": get_env_value("SLACK_ALLOWED_USERS") or "",
    }


@app.post("/api/channels/imessage/bluebubbles/configure")
async def configure_bluebubbles(request: Request):
    """Mirror ``setup._setup_bluebubbles``. Saves BLUEBUBBLES_SERVER_URL,
    BLUEBUBBLES_PASSWORD, BLUEBUBBLES_ALLOWED_USERS, BLUEBUBBLES_HOME_CHANNEL."""
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_url = _strip(body.get("server_url")).rstrip("/")
    password = _strip(body.get("password"))
    allowed = _strip(body.get("allowed_users"))
    home = _strip(body.get("home_channel"))

    if server_url:
        save_env_value("BLUEBUBBLES_SERVER_URL", server_url)
    if password:
        save_env_value("BLUEBUBBLES_PASSWORD", password)
    if allowed:
        save_env_value("BLUEBUBBLES_ALLOWED_USERS", allowed.replace(" ", ""))
    if home:
        save_env_value("BLUEBUBBLES_HOME_CHANNEL", home)

    if not get_env_value("BLUEBUBBLES_SERVER_URL") or not get_env_value("BLUEBUBBLES_PASSWORD"):
        raise HTTPException(
            status_code=400,
            detail="BlueBubbles server URL + password are required",
        )

    return {
        "ok": True,
        "serverUrl": get_env_value("BLUEBUBBLES_SERVER_URL") or "",
        "passwordSet": bool(get_env_value("BLUEBUBBLES_PASSWORD")),
        "allowedUsers": get_env_value("BLUEBUBBLES_ALLOWED_USERS") or "",
        "homeChannel": get_env_value("BLUEBUBBLES_HOME_CHANNEL") or "",
    }


@app.post("/api/channels/whatsapp/configure")
async def configure_whatsapp(request: Request):
    """Save WhatsApp mode + allowlist (matches cmd_whatsapp steps 1-3).
    Pairing is a separate endpoint that streams the QR."""
    _require_token(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = _strip(body.get("mode"))  # "bot" or "self-chat"
    allowed = _strip(body.get("allowed_users"))
    if mode and mode not in {"bot", "self-chat"}:
        raise HTTPException(status_code=400, detail="mode must be 'bot' or 'self-chat'")
    if mode:
        save_env_value("WHATSAPP_MODE", mode)
        save_env_value("WHATSAPP_ENABLED", "true")
    if allowed:
        save_env_value("WHATSAPP_ALLOWED_USERS", allowed.replace(" ", ""))

    bridge_dir = _elevate_repo_root() / "scripts" / "whatsapp-bridge"
    has_node_modules = (bridge_dir / "node_modules").exists()
    bridge_present = (bridge_dir / "bridge.js").exists()
    session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
    paired = (session_dir / "creds.json").exists()

    return {
        "ok": True,
        "mode": get_env_value("WHATSAPP_MODE") or "",
        "enabled": (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true",
        "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
        "bridgePresent": bridge_present,
        "bridgeInstalled": has_node_modules,
        "paired": paired,
    }


def _elevate_repo_root() -> Path:
    """Locate the repo root that holds ``scripts/whatsapp-bridge``."""
    # web_server.py lives at <repo>/cli/elevate_cli/web_server.py
    return Path(__file__).resolve().parents[1]


@app.post("/api/channels/whatsapp/install")
async def install_whatsapp_bridge(request: Request):
    """Run ``npm install`` inside the WhatsApp bridge directory.
    Mirrors the auto-install step inside ``cmd_whatsapp``."""
    _require_token(request)
    bridge_dir = _elevate_repo_root() / "scripts" / "whatsapp-bridge"
    if not (bridge_dir / "bridge.js").exists():
        raise HTTPException(status_code=404, detail=f"bridge.js not found at {bridge_dir}")

    npm = shutil.which("npm")
    if not npm:
        raise HTTPException(
            status_code=400,
            detail="npm not on PATH — install Node.js first (https://nodejs.org/)",
        )

    try:
        # npm install can take minutes — run it off the event loop so the
        # single-worker dashboard stays responsive to every other request.
        proc = await asyncio.to_thread(
            subprocess.run,
            [npm, "install", "--no-fund", "--no-audit", "--progress=false"],
            cwd=str(bridge_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="npm install timed out after 10 minutes")

    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-30:]) or "(no output)"
        raise HTTPException(status_code=500, detail=f"npm install failed:\n{tail}")

    return {
        "ok": True,
        "installed": (bridge_dir / "node_modules").exists(),
    }


@app.get("/api/channels/whatsapp/status")
async def whatsapp_status():
    """Lightweight status: is bridge installed, has session been paired."""
    bridge_dir = _elevate_repo_root() / "scripts" / "whatsapp-bridge"
    session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
    return {
        "bridgePresent": (bridge_dir / "bridge.js").exists(),
        "bridgeInstalled": (bridge_dir / "node_modules").exists(),
        "mode": get_env_value("WHATSAPP_MODE") or "",
        "enabled": (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true",
        "paired": (session_dir / "creds.json").exists(),
        "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
    }


@app.get("/api/channels/whatsapp/pair/stream")
async def whatsapp_pair_stream(request: Request):
    """Server-Sent Events stream of WhatsApp pairing progress.

    Spawns ``node bridge.js --pair-only --qr-json`` and emits JSON
    events as the bridge produces them: ``qr`` (raw QR string for the
    browser to render), ``connected``, ``paired``, ``error``, ``exit``.
    """
    _require_token(request)
    bridge_dir = _elevate_repo_root() / "scripts" / "whatsapp-bridge"
    bridge_script = bridge_dir / "bridge.js"
    if not bridge_script.exists():
        raise HTTPException(status_code=404, detail="bridge.js not found")
    if not (bridge_dir / "node_modules").exists():
        raise HTTPException(
            status_code=400,
            detail="WhatsApp bridge dependencies not installed — call /api/channels/whatsapp/install first",
        )
    node = shutil.which("node")
    if not node:
        raise HTTPException(status_code=400, detail="node not on PATH")

    session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
    session_dir.mkdir(parents=True, exist_ok=True)
    # Re-pairing: clear stale session so Baileys emits a fresh QR.
    creds = session_dir / "creds.json"
    if creds.exists():
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
            session_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    async def event_stream():
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            node,
            str(bridge_script),
            "--pair-only",
            "--qr-json",
            "--session",
            str(session_dir),
            cwd=str(bridge_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def kill_if_disconnected():
            while True:
                if await request.is_disconnected():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return
                await asyncio.sleep(1.0)

        watcher = asyncio.create_task(kill_if_disconnected())
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                # Only forward our JSON lines; ignore Baileys chatter.
                if text.startswith("{") and text.endswith("}"):
                    try:
                        payload = json.loads(text)
                    except Exception:
                        yield f"data: {text}\n\n"
                        continue
                    # When the bridge sends a raw QR string, render it to
                    # a data URL server-side so the browser can drop it
                    # into an <img> tag without a JS QR library.
                    if payload.get("event") == "qr" and payload.get("qr"):
                        try:
                            import base64
                            import io
                            import qrcode  # type: ignore[import-not-found]
                            img = qrcode.make(payload["qr"], box_size=6, border=2)
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            payload["dataUrl"] = (
                                "data:image/png;base64,"
                                + base64.b64encode(buf.getvalue()).decode("ascii")
                            )
                        except Exception:
                            # Browser can still render the raw QR with its
                            # own library if it ever wants to.
                            pass
                    yield f"data: {json.dumps(payload)}\n\n"
            rc = await proc.wait()
            yield f"data: {json.dumps({'event': 'exit', 'code': rc})}\n\n"
        finally:
            watcher.cancel()
            if proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/elevate/update")
async def update_elevate():
    """Kick off ``elevate update`` in the background."""
    if _is_packaged_desktop_runtime():
        raise HTTPException(
            status_code=400,
            detail="Desktop app updates are managed by the built-in app updater.",
        )
    try:
        proc = _spawn_elevate_action(["update"], "elevate-update")
    except Exception as exc:
        _log.exception("Failed to spawn elevate update")
        raise HTTPException(status_code=500, detail=f"Failed to start update: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "elevate-update",
    }


def _git_value(
    repo_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 5,
) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def _parse_git_shortstat(raw: str) -> Dict[str, int]:
    stats = {"files": 0, "insertions": 0, "deletions": 0}
    for key, pattern in {
        "files": r"(\d+)\s+files?\s+changed",
        "insertions": r"(\d+)\s+insertions?\(\+\)",
        "deletions": r"(\d+)\s+deletions?\(-\)",
    }.items():
        match = re.search(pattern, raw)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _git_shortstat(repo_dir: Path) -> Dict[str, int]:
    raw = _git_value(repo_dir, "diff", "--shortstat", "HEAD") or ""
    return _parse_git_shortstat(raw)


def _git_run_for_tree(repo_dir: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _nul_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in raw.split("\0") if part]


def _git_worktree_changed_paths(repo_dir: Path) -> list[str]:
    """Return paths that need hashing to mirror `git add -A` in a temp index."""

    tracked = _git_value(
        repo_dir,
        "diff",
        "--name-only",
        "-z",
        "HEAD",
        "--",
        timeout=10,
    )
    untracked = _git_value(
        repo_dir,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        timeout=10,
    )
    return sorted(set(_nul_paths(tracked) + _nul_paths(untracked)))


def _git_worktree_fingerprint(repo_dir: Path, changed_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in changed_paths:
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        path = repo_dir / rel
        try:
            st = path.lstat()
            h.update(f"{st.st_mtime_ns}:{st.st_size}:{st.st_mode}".encode("ascii"))
        except FileNotFoundError:
            h.update(b"missing")
        except OSError as exc:
            h.update(f"error:{type(exc).__name__}".encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def _git_worktree_tree(repo_dir: Path, changed_paths: list[str] | None = None) -> str:
    """Return a git tree object for the current working tree.

    Uses a temporary index, so it does not touch the user's real index or
    staging area. The resulting tree lets the dashboard compare "this chat's
    baseline" to "right now" instead of showing the same global dirty diff in
    every chat.
    """
    if changed_paths is None:
        changed_paths = _git_worktree_changed_paths(repo_dir)
    with tempfile.TemporaryDirectory(prefix="elevate-git-index-") as tmp:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")

        read = _git_run_for_tree(repo_dir, env, "read-tree", "HEAD")
        if read.returncode != 0:
            read = _git_run_for_tree(repo_dir, env, "read-tree", "--empty")
        if read.returncode != 0:
            raise RuntimeError((read.stderr or read.stdout or "git read-tree failed").strip())

        if changed_paths:
            add = subprocess.run(
                ["git", "update-index", "--add", "--remove", "-z", "--stdin"],
                cwd=repo_dir,
                env=env,
                input="\0".join(changed_paths) + "\0",
                capture_output=True,
                text=True,
                timeout=20,
            )
            if add.returncode != 0:
                raise RuntimeError((add.stderr or add.stdout or "git update-index failed").strip())

        tree = _git_run_for_tree(repo_dir, env, "write-tree")
        if tree.returncode != 0:
            raise RuntimeError((tree.stderr or tree.stdout or "git write-tree failed").strip())
        value = (tree.stdout or "").strip()
        if not value:
            raise RuntimeError("git write-tree returned no tree")
        return value


def _git_tree_exists(repo_dir: Path, tree: str | None) -> bool:
    if not tree:
        return False
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{tree}^{{tree}}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0


def _git_tree_shortstat(repo_dir: Path, baseline_tree: str, current_tree: str) -> Dict[str, int]:
    raw = _git_value(
        repo_dir,
        "diff",
        "--shortstat",
        baseline_tree,
        current_tree,
        timeout=20,
    ) or ""
    return _parse_git_shortstat(raw)


def _session_git_baseline_path(session_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id).strip("._")[:140]
    if not safe_id:
        safe_id = "session"
    return get_elevate_home() / "session_git_baselines" / f"{safe_id}.json"


def _session_git_status_cache_path(session_id: str) -> Path:
    path = _session_git_baseline_path(session_id)
    return path.with_name(f"{path.stem}.status.json")


def _read_session_git_baseline(session_id: str, repo_dir: Path) -> Dict[str, Any] | None:
    try:
        path = _session_git_baseline_path(session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("repo_path") != str(repo_dir):
            return None
        tree = str(raw.get("tree") or "")
        if not _git_tree_exists(repo_dir, tree):
            return None
        return raw
    except Exception:
        return None


def _write_session_git_baseline(
    session_id: str,
    repo_dir: Path,
    *,
    branch: str | None,
    short_sha: str | None,
    tree: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "version": 1,
        "session_id": session_id,
        "repo_path": str(repo_dir),
        "repo_name": repo_dir.name,
        "branch": branch,
        "short_sha": short_sha,
        "tree": tree,
        "created_at": time.time(),
    }
    path = _session_git_baseline_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return payload


def _read_session_git_status_cache(
    session_id: str,
    repo_dir: Path,
    *,
    baseline_tree: str,
    fingerprint: str,
) -> Dict[str, Any] | None:
    try:
        path = _session_git_status_cache_path(session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("repo_path") != str(repo_dir):
            return None
        if raw.get("baseline_tree") != baseline_tree:
            return None
        if raw.get("fingerprint") != fingerprint:
            return None
        stats = raw.get("stats")
        if not isinstance(stats, dict):
            return None
        return raw
    except Exception:
        return None


def _write_session_git_status_cache(
    session_id: str,
    repo_dir: Path,
    *,
    baseline_tree: str,
    fingerprint: str,
    stats: Dict[str, int],
    changed_files: int,
) -> None:
    try:
        payload = {
            "version": 1,
            "session_id": session_id,
            "repo_path": str(repo_dir),
            "baseline_tree": baseline_tree,
            "fingerprint": fingerprint,
            "stats": stats,
            "changed_files": changed_files,
            "created_at": time.time(),
        }
        path = _session_git_status_cache_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _git_ahead_behind(repo_dir: Path) -> tuple[int, int]:
    raw = _git_value(repo_dir, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if not raw:
        return 0, 0
    parts = raw.split()
    if len(parts) < 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def _github_repo_url(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    url = remote_url.strip()
    if url.startswith("git@github.com:"):
        path = url.split(":", 1)[1]
    elif "github.com/" in url:
        path = urllib.parse.urlparse(url).path.lstrip("/")
    else:
        return None
    if path.endswith(".git"):
        path = path[:-4]
    if path.count("/") < 1:
        return None
    return f"https://github.com/{path}"


def _github_compare_url(repo_url: str | None, branch: str | None, upstream: str | None) -> str | None:
    if not repo_url or not branch or branch in {"HEAD", "main", "master"}:
        return None
    base = "main"
    if upstream:
        upstream_branch = upstream.split("/", 1)[1] if "/" in upstream else upstream
        if upstream_branch and upstream_branch != branch:
            base = upstream_branch
    return (
        f"{repo_url}/compare/"
        f"{urllib.parse.quote(base, safe='')}..."
        f"{urllib.parse.quote(branch, safe='')}?expand=1"
    )


def _resolve_workspace_repo_dir() -> Path | None:
    local_root = _git_value(WORKSPACE_ROOT, "rev-parse", "--show-toplevel")
    if local_root:
        return Path(local_root).resolve()
    return WORKSPACE_ROOT


def _workspace_display_dir(repo_dir: Path, working_directory: str | None = None) -> Path:
    fallback = repo_dir
    try:
        workspace_root = WORKSPACE_ROOT.resolve()
        workspace_root.relative_to(repo_dir.resolve())
        fallback = workspace_root
    except Exception:
        fallback = repo_dir

    if working_directory:
        try:
            candidate = Path(working_directory).expanduser()
            if not candidate.is_absolute():
                candidate = (repo_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.exists():
                try:
                    candidate.relative_to(repo_dir.resolve())
                except Exception:
                    return fallback
                return candidate
        except Exception:
            pass
    return fallback


def _repo_relative_display(repo_dir: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(repo_dir.resolve())
    except Exception:
        return path.name or str(path)
    if str(rel) == ".":
        return repo_dir.name
    return f"{repo_dir.name}/{rel.as_posix()}"


def _empty_workspace_git_payload(error: str | None = None) -> Dict[str, Any]:
    return {
        "ok": error is None,
        "error": error,
        "path": None,
        "repo_path": None,
        "working_directory": None,
        "display_name": None,
        "repo_name": None,
        "branch": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "changed_files": 0,
        "insertions": 0,
        "deletions": 0,
        "untracked": 0,
        "dirty": False,
        "repo_changed_files": 0,
        "repo_insertions": 0,
        "repo_deletions": 0,
        "repo_untracked": 0,
        "repo_dirty": False,
        "diff_scope": "repo",
        "baseline_created": False,
        "baseline_at": None,
        "short_sha": None,
        "origin_url": None,
        "repo_url": None,
        "pr_url": None,
        "checked_at": time.time(),
    }


def _workspace_git_status_payload(
    session_id: str | None = None,
    working_directory: str | None = None,
) -> Dict[str, Any]:
    repo_dir = _resolve_workspace_repo_dir()
    if repo_dir is None:
        return _empty_workspace_git_payload("not_git_install")

    display_dir = _workspace_display_dir(repo_dir, working_directory)
    branch = _git_value(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = _git_value(repo_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead, behind = _git_ahead_behind(repo_dir)
    porcelain = _git_value(repo_dir, "status", "--porcelain=v1") or ""
    status_lines = [line for line in porcelain.splitlines() if line.strip()]
    untracked = sum(1 for line in status_lines if line.startswith("??"))
    repo_stats = _git_shortstat(repo_dir)
    origin_url = _git_value(repo_dir, "remote", "get-url", "origin")
    repo_url = _github_repo_url(origin_url)
    short_sha = _git_value(repo_dir, "rev-parse", "--short", "HEAD")
    diff_scope = "repo"
    baseline_created = False
    baseline_at: float | None = None
    display_stats = repo_stats
    display_changed_files = len(status_lines)
    display_untracked = untracked

    if session_id:
        changed_paths = _git_worktree_changed_paths(repo_dir)
        fingerprint = _git_worktree_fingerprint(repo_dir, changed_paths)
        baseline = _read_session_git_baseline(session_id, repo_dir)
        cache = (
            _read_session_git_status_cache(
                session_id,
                repo_dir,
                baseline_tree=str(baseline["tree"]),
                fingerprint=fingerprint,
            )
            if baseline
            else None
        )
        if cache:
            baseline_at = float(baseline.get("created_at") or 0) or None
            cached_stats = cache.get("stats") or {}
            display_stats = {
                "files": int(cached_stats.get("files") or 0),
                "insertions": int(cached_stats.get("insertions") or 0),
                "deletions": int(cached_stats.get("deletions") or 0),
            }
            display_changed_files = int(cache.get("changed_files") or display_stats["files"])
        else:
            current_tree = _git_worktree_tree(repo_dir, changed_paths=changed_paths)
            if not baseline:
                baseline = _write_session_git_baseline(
                    session_id,
                    repo_dir,
                    branch=branch,
                    short_sha=short_sha,
                    tree=current_tree,
                )
                baseline_created = True
            baseline_at = float(baseline.get("created_at") or 0) or None
            display_stats = _git_tree_shortstat(repo_dir, str(baseline["tree"]), current_tree)
            display_changed_files = display_stats["files"]
            _write_session_git_status_cache(
                session_id,
                repo_dir,
                baseline_tree=str(baseline["tree"]),
                fingerprint=fingerprint,
                stats=display_stats,
                changed_files=display_changed_files,
            )
        display_untracked = 0
        diff_scope = "session"

    return {
        "ok": True,
        "error": None,
        "path": str(repo_dir),
        "repo_path": str(repo_dir),
        "working_directory": str(display_dir),
        "display_name": _repo_relative_display(repo_dir, display_dir),
        "repo_name": repo_dir.name,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "changed_files": display_changed_files,
        "insertions": display_stats["insertions"],
        "deletions": display_stats["deletions"],
        "untracked": display_untracked,
        "dirty": bool(display_changed_files),
        "repo_changed_files": len(status_lines),
        "repo_insertions": repo_stats["insertions"],
        "repo_deletions": repo_stats["deletions"],
        "repo_untracked": untracked,
        "repo_dirty": bool(status_lines),
        "diff_scope": diff_scope,
        "baseline_created": baseline_created,
        "baseline_at": baseline_at,
        "short_sha": short_sha,
        "origin_url": origin_url,
        "repo_url": repo_url,
        "pr_url": _github_compare_url(repo_url, branch, upstream),
        "checked_at": time.time(),
    }


_GIT_UNAVAILABLE_WARNED = False


def _is_git_unavailable_error(msg: str) -> bool:
    """True when the failure means git itself can't run (not a repo problem).

    Covers the common fresh-Mac case where Xcode command line tools aren't
    installed and the `/usr/bin/git` shim emits an install prompt to stderr.
    """
    low = (msg or "").lower()
    return (
        "no developer tools were found" in low
        or "xcode-select" in low
        or "git: command not found" in low
        or "git: not found" in low
        or "no such file or directory: 'git'" in low
    )


@app.get("/api/workspace/git/status")
async def get_workspace_git_status(
    session_id: str | None = None,
    working_directory: str | None = None,
):
    try:
        return await asyncio.to_thread(
            _workspace_git_status_payload,
            session_id=session_id,
            working_directory=working_directory,
        )
    except Exception as exc:
        msg = str(exc)
        # Fresh non-developer Macs ship a `git` stub that errors with
        # "No developer tools were found" until Xcode CLT is installed. End
        # users (e.g. realtors) never need git, so don't flood errors.log with
        # a full traceback on every poll — warn once, then degrade quietly.
        if _is_git_unavailable_error(msg):
            global _GIT_UNAVAILABLE_WARNED
            if not _GIT_UNAVAILABLE_WARNED:
                _GIT_UNAVAILABLE_WARNED = True
                _log.warning(
                    "workspace git status disabled: git is unavailable "
                    "(Xcode command line tools not installed?): %s",
                    msg.splitlines()[0] if msg else "git unavailable",
                )
            return _empty_workspace_git_payload(msg)
        _log.exception("GET /api/workspace/git/status failed")
        return _empty_workspace_git_payload(msg)


@app.post("/api/workspace/open")
async def open_workspace(payload: dict[str, Any] | None = Body(default=None)):
    repo_dir = _resolve_workspace_repo_dir()
    if repo_dir is None:
        raise HTTPException(status_code=404, detail="Workspace repo not found")
    requested = str((payload or {}).get("path") or "").strip()
    target = _workspace_display_dir(repo_dir, requested)
    _open_in_file_manager(target)
    return {"ok": True, "path": str(target)}


@app.get("/api/elevate/update/status")
async def get_elevate_update_status(refresh: bool = False):
    """Return whether this checkout is behind the release branch.

    The source of truth is the install's ``origin/main``. When the developer
    pushes commits to that branch, installed dashboards can show "updates
    available" before the user runs ``elevate update``.
    """
    try:
        if _is_packaged_desktop_runtime():
            return {
                "available": False,
                "behind": None,
                "ahead": 0,
                "branch": None,
                "checked_at": time.time(),
                "command": "desktop updater",
                "local": None,
                "origin_url": None,
                "repo_dir": str(PROJECT_ROOT),
                "upstream": None,
                "error": "desktop_app_managed_update",
            }

        from elevate_cli.banner import (
            _resolve_repo_dir,
            check_for_updates,
            get_git_banner_state,
        )
        from elevate_cli.config import recommended_update_command

        repo_dir = _resolve_repo_dir()
        if repo_dir is None:
            return {
                "available": False,
                "behind": None,
                "ahead": 0,
                "branch": None,
                "checked_at": time.time(),
                "command": recommended_update_command(),
                "local": None,
                "origin_url": None,
                "repo_dir": None,
                "upstream": None,
                "error": "not_git_install",
            }

        loop = asyncio.get_running_loop()
        behind = await loop.run_in_executor(
            None,
            lambda: check_for_updates(force=refresh, cache_seconds=5 * 60),
        )
        git_state = get_git_banner_state(repo_dir) or {}
        branch = _git_value(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
        origin_url = _git_value(repo_dir, "remote", "get-url", "origin")
        available = bool(behind and behind > 0)
        return {
            "available": available,
            "behind": behind,
            "ahead": int(git_state.get("ahead") or 0),
            "branch": branch,
            "checked_at": time.time(),
            "command": recommended_update_command(),
            "local": git_state.get("local"),
            "origin_url": origin_url,
            "repo_dir": str(repo_dir),
            "upstream": git_state.get("upstream"),
            "error": None,
        }
    except Exception as exc:
        _log.exception("GET /api/elevate/update/status failed")
        return {
            "available": False,
            "behind": None,
            "ahead": 0,
            "branch": None,
            "checked_at": time.time(),
            "command": "elevate update",
            "local": None,
            "origin_url": None,
            "repo_dir": None,
            "upstream": None,
            "error": str(exc),
        }


@app.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_path = _ACTION_LOG_DIR / log_file_name
    tail = _tail_lines(log_path, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        running = False
        exit_code: Optional[int] = None
        pid: Optional[int] = None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid

    return {
        "name": name,
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "lines": tail,
    }


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


_PREVIEWABLE_SUFFIXES = {
    ".csv",
    ".docx",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".txt",
    ".webp",
    ".xlsx",
    ".yaml",
    ".yml",
}
_MAX_PREVIEW_BYTES = 100 * 1024 * 1024


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _preview_roots() -> list[Path]:
    roots = [
        Path.home(),
        PROJECT_ROOT,
        get_elevate_home(),
        Path(tempfile.gettempdir()),
        # macOS: tempfile.gettempdir() returns /var/folders/.../T, not /tmp.
        # Agents routinely write artifacts to /tmp, so allow it explicitly.
        Path("/tmp"),
    ]
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(root.expanduser().resolve())
        except OSError:
            continue
    return resolved


def _resolve_preview_file(raw_path: str) -> Path:
    if not raw_path or not raw_path.strip():
        raise HTTPException(status_code=400, detail="Missing file path")

    candidate = Path(os.path.expandvars(raw_path.strip())).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate)

    try:
        path = candidate.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {exc}")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if path.suffix.lower() not in _PREVIEWABLE_SUFFIXES:
        raise HTTPException(status_code=415, detail="File type is not previewable")

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not inspect file: {exc}")
    if size > _MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=413, detail="File is too large to preview")

    if not any(_is_relative_to(path, root) for root in _preview_roots()):
        raise HTTPException(status_code=403, detail="File path is outside preview roots")

    return path


_FILES_TREE_EXCLUDED = {
    "node_modules", ".git", ".next", "__pycache__", ".venv", "venv",
    ".turbo", "dist", "build", ".cache", ".DS_Store", ".idea", ".vscode",
    "web_dist", ".pytest_cache", ".mypy_cache", "coverage",
}
_FILES_TREE_MAX_ENTRIES = 300


def _resolve_tree_root(raw_root: str) -> Path:
    raw = (raw_root or "").strip()
    if not raw:
        base = PROJECT_ROOT
    else:
        candidate = Path(os.path.expandvars(raw)).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        base = candidate
    try:
        base = base.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid root: {exc}")
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not any(_is_relative_to(base, root) for root in _preview_roots()):
        raise HTTPException(status_code=403, detail="Directory is outside allowed roots")
    return base


def _walk_files_tree(base: Path, max_depth: int, depth: int = 1) -> list:
    """One level (or more) of {name, type, path, children?} for the Files panel.

    Dirs only carry a `children` key when actually walked (depth < max_depth),
    so the client can lazy-load deeper levels with ?root=<dir>. Absolute paths
    are returned so click-to-preview reuses /api/files/preview directly.
    """
    try:
        children = list(base.iterdir())
    except (PermissionError, OSError):
        return []
    folders: list[Path] = []
    files: list[Path] = []
    for child in children:
        if child.name.startswith(".") or child.name in _FILES_TREE_EXCLUDED:
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        (folders if is_dir else files).append(child)
    folders.sort(key=lambda c: c.name.lower())
    files.sort(key=lambda c: c.name.lower())

    entries: list = []
    for child in folders[:_FILES_TREE_MAX_ENTRIES]:
        entry = {"name": child.name, "type": "dir", "path": str(child)}
        if depth < max_depth:
            entry["children"] = _walk_files_tree(child, max_depth, depth + 1)
        entries.append(entry)
    for child in files[:_FILES_TREE_MAX_ENTRIES]:
        entries.append({"name": child.name, "type": "file", "path": str(child)})
    return entries


@app.get("/api/files/tree")
async def get_files_tree(root: str = "", depth: int = 1):
    """Nested file tree for the chat Files panel, clamped to preview roots."""
    base = _resolve_tree_root(root)
    safe_depth = max(1, min(int(depth or 1), 4))
    return {
        "root": str(base),
        "name": base.name or str(base),
        "tree": _walk_files_tree(base, max_depth=safe_depth),
    }


@app.get("/api/files/preview")
async def preview_file(path: str):
    target = _resolve_preview_file(path)
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(
        target,
        filename=target.name,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "X-Elevate-File-Name": target.name,
            "X-Elevate-File-Size": str(target.stat().st_size),
        },
    )


_UPLOAD_MAX_PER_FILE = 500 * 1024 * 1024  # 500 MB per file (covers most phone videos)
_UPLOAD_DIRNAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_upload_filename(raw: str) -> str:
    name = (raw or "").strip().split("/")[-1].split("\\")[-1] or "file"
    clean = _UPLOAD_DIRNAME_SANITIZE.sub("_", name)
    if clean.startswith("."):
        clean = "_" + clean.lstrip(".")
    return clean[:120] or "file"


@app.post("/api/uploads/{session_id}")
async def upload_attachment(session_id: str, file: UploadFile = File(...)):
    """Accept a chat attachment from the web client and stash it under
    ~/.elevate/uploads/<sid>/ so the gateway can hand the absolute path to
    the agent via file.attach / attached_files."""
    from datetime import datetime

    sid_clean = _sanitize_upload_filename(session_id) or "anon"
    upload_dir = get_elevate_home() / "uploads" / sid_clean
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not create upload dir: {exc}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = _sanitize_upload_filename(file.filename or "file")
    dest = upload_dir / f"{ts}_{safe_name}"

    total = 0
    try:
        with dest.open("wb") as handle:
            while True:
                chunk = await file.read(1 << 20)  # 1 MB
                if not chunk:
                    break
                total += len(chunk)
                if total > _UPLOAD_MAX_PER_FILE:
                    handle.close()
                    try:
                        dest.unlink()
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {_UPLOAD_MAX_PER_FILE // (1024 * 1024)} MB cap",
                    )
                handle.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # disk full, permission, etc.
        try:
            dest.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")

    media_type = file.content_type or mimetypes.guess_type(str(dest))[0] or "application/octet-stream"
    return JSONResponse(
        {
            "path": str(dest),
            "name": safe_name,
            "size": total,
            "media_type": media_type,
        }
    )


# A session counts as "active" (spinner in the sidebar) only if a message
# landed within this many seconds. The spinner means genuinely working right
# now, not recently-touched — so this stays tight. 300s made idle chats spin.
_SESSION_ACTIVE_WINDOW_SEC = 25
_STATUS_CACHE_TTL_SEC = 1.5


def _live_running_session_keys() -> set[str]:
    """DB session keys the in-process gateway is ACTIVELY running a turn for.

    A long interactive turn persists nothing until it finishes, so its
    ``last_active`` freezes at the user-message time and the 25s active-window
    check above flips ``is_active`` to False mid-turn — which makes the sidebar
    drop its "working" dots while the agent is genuinely still working. The
    gateway tracks ``session["running"]`` in-process (dashboard --tui hosts both),
    so consult it as the source of truth for "running right now". Best-effort:
    returns empty if the gateway module isn't loaded (e.g. headless dashboard).
    """
    keys: set[str] = set()
    try:
        from tui_gateway import server as _gw

        for sess in list(getattr(_gw, "_sessions", {}).values()):
            if not isinstance(sess, dict) or not sess.get("running"):
                continue
            for k in (sess.get("session_key"), sess.get("session_id")):
                if k:
                    keys.add(str(k))
    except Exception:
        pass
    return keys
_status_cache_payload: dict[str, Any] | None = None
_status_cache_expires_at = 0.0
_status_cache_lock = threading.Lock()


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


def _cached_status_payload() -> dict[str, Any] | None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    now = time.monotonic()
    with _status_cache_lock:
        if _status_cache_payload is None or _status_cache_expires_at <= now:
            return None
        return dict(_status_cache_payload)


def _store_status_payload(payload: dict[str, Any]) -> None:
    global _status_cache_payload, _status_cache_expires_at
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _status_cache_lock:
        _status_cache_payload = dict(payload)
        _status_cache_expires_at = time.monotonic() + _STATUS_CACHE_TTL_SEC


@app.get("/api/sessions")
async def get_sessions(
    limit: int = 20,
    offset: int = 0,
    include_total: bool = True,
    include_details: bool = False,
):
    try:
        limit = max(1, min(int(limit or 20), 200))
        offset = max(0, int(offset or 0))
        if not include_details:
            try:
                from elevate_cli.data.chat_sessions import (
                    list_session_summaries,
                    session_count as pg_session_count,
                )

                sessions = list_session_summaries(limit=limit, offset=offset)
                total = pg_session_count() if include_total else offset + len(sessions)
                now = time.time()
                _running = _live_running_session_keys()
                for s in sessions:
                    s["is_active"] = (
                        s.get("ended_at") is None
                        and (now - s.get("last_active", s.get("started_at", 0)))
                        < _SESSION_ACTIVE_WINDOW_SEC
                    ) or (str(s.get("id") or "") in _running)
                return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
            except Exception:
                _log.debug("PG slim session list failed, falling back to SessionDB", exc_info=True)

        from elevate_state import SessionDB
        db = _get_session_db()
        try:
            sessions = db.list_sessions_rich(limit=limit, offset=offset)
            total = db.session_count() if include_total else offset + len(sessions)
            now = time.time()
            _running = _live_running_session_keys()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0)))
                    < _SESSION_ACTIVE_WINDOW_SEC
                ) or (str(s.get("id") or "") in _running)
            if not include_details:
                sessions = [_session_list_payload(s) for s in sessions]
            return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
        finally:
            db.close()
    except Exception as e:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from elevate_state import SessionDB
        db = _get_session_db()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re
            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            matches = db.search_messages(query=prefix_query, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Elevate supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_context_length"] = 0
    return config


@app.get("/api/config")
async def get_config():
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    return {k: v for k, v in config.items() if not k.startswith("_")}


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


@app.get("/api/model/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length
            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


@app.get("/api/models/available")
def get_models_available():
    """Return harness-available models for tier-mapping UI.

    Wraps :func:`elevate_cli.tier_resolver.list_available_models`. Only
    authenticated providers are listed because un-authed providers cannot be
    called by the runtime — listing them would let the user trap themselves.
    """
    try:
        from elevate_cli.tier_resolver import list_available_models
        return list_available_models()
    except Exception:
        _log.exception("GET /api/models/available failed")
        return {"models": [], "default": ""}


@app.get("/api/models/by-provider")
def get_models_by_provider(provider: str = ""):
    """Return the full model catalog for a specific provider.

    Powers the onboarding wizard's "Pick the brain" dropdown — given a
    provider id like ``anthropic`` / ``openai-codex`` / ``nous``, returns
    every model id we know the provider has, refreshed live from the
    provider's API when possible (codex, nous, anthropic, copilot, …) and
    falling back to the static curated list otherwise. The caller passes
    the *concrete* provider id, not the wizard's grouped label — e.g.
    pass ``openai-codex`` for "OpenAI · connected via Codex".
    """
    prov = str(provider or "").strip()
    if not prov:
        return {"provider": "", "models": []}
    try:
        from elevate_cli.models import provider_model_ids, normalize_provider
        normalized = normalize_provider(prov)
        models = provider_model_ids(normalized) or []
        return {"provider": normalized, "models": list(models)}
    except Exception:
        _log.exception("GET /api/models/by-provider failed for provider=%s", prov)
        return {"provider": prov, "models": []}


@app.post("/api/channels/slack/test")
def post_slack_test(payload: dict[str, Any] | None = Body(default=None)):
    """Send a one-shot test message to a Slack incoming webhook.

    Powers the wizard's "Send test" button so the operator can confirm their
    webhook URL is live before saving. Accepts ``{"webhook_url": "...",
    "channel": "...", "text": "..."}``. If ``webhook_url`` is omitted, falls
    back to ``$SLACK_WEBHOOK_URL`` in env. Returns ``{"ok": bool,
    "status": int, "detail": str}``.

    Used by the wizard. The actual runtime "agent posts to Slack" plumbing
    lives in the outbound sender — this endpoint exists so the wizard can
    validate creds without needing the full agent loop to fire.
    """
    import os
    import httpx

    body = payload or {}
    webhook = str(body.get("webhook_url") or "").strip()
    if not webhook:
        try:
            from elevate_cli.config import load_env as _load_env

            file_env = _load_env() or {}
        except Exception:
            file_env = {}
        webhook = (os.environ.get("SLACK_WEBHOOK_URL") or file_env.get("SLACK_WEBHOOK_URL") or "").strip()
    if not webhook:
        return {"ok": False, "status": 0, "detail": "No webhook URL provided and SLACK_WEBHOOK_URL is not set."}

    text = str(body.get("text") or "").strip() or "elevate · test message from onboarding wizard"
    channel = str(body.get("channel") or "").strip()
    msg: dict[str, Any] = {"text": text}
    if channel:
        msg["channel"] = channel if channel.startswith("#") or channel.startswith("@") else f"#{channel}"
    try:
        resp = httpx.post(webhook, json=msg, timeout=10)
    except httpx.HTTPError as exc:
        return {"ok": False, "status": 0, "detail": f"{type(exc).__name__}: {exc}"}
    body_text = (resp.text or "").strip()
    return {
        "ok": resp.is_success and body_text.lower() in ("ok", ""),
        "status": resp.status_code,
        "detail": body_text or "delivered",
    }


@app.get("/api/agents/peers")
def get_agent_peers():
    """Return the list of Cortex OS-style peer agents on this Mac.

    Powers the onboarding wizard's "Agents connected" rail so the operator
    can see which AI specialists already exist alongside this elevate agent
    (e.g. jimmy/gary/nina/ricky/qc from claudeclaw). Discovery is purely
    filesystem-based — no process probing here, the wizard just needs to
    surface what's wired up.

    Roots searched in order:
      1. $ELEVATE_PEERS_ROOT (single root)
      2. $ELEVATE_PEERS_ROOTS (colon-separated)
      3. $HOME/claudeclaw/orgs
    Each root is globbed as ``<root>/<org>/agents/<agent>/config.json``.
    """
    import json
    import os
    from pathlib import Path

    roots: list[Path] = []
    primary = os.environ.get("ELEVATE_PEERS_ROOT", "").strip()
    if primary:
        roots.append(Path(primary).expanduser())
    extra = os.environ.get("ELEVATE_PEERS_ROOTS", "").strip()
    if extra:
        for chunk in extra.split(":"):
            chunk = chunk.strip()
            if chunk:
                roots.append(Path(chunk).expanduser())
    if not roots:
        fallback = Path.home() / "claudeclaw" / "orgs"
        if fallback.exists():
            roots.append(fallback)

    peers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for config_path in sorted(root.glob("*/agents/*/config.json")):
                try:
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                org = config_path.parents[2].name
                agent = str(payload.get("agent_name") or config_path.parent.name)
                key = f"{org}/{agent}"
                if key in seen:
                    continue
                seen.add(key)
                # Look for the matching AGENTS.md / CLAUDE.md for a one-line
                # role hint without forcing an LLM call. First non-empty,
                # non-header line under 140 chars wins.
                role_hint = ""
                for fname in ("AGENTS.md", "CLAUDE.md", "IDENTITY.md"):
                    agent_doc = config_path.parent / fname
                    if not agent_doc.exists():
                        continue
                    try:
                        for line in agent_doc.read_text(encoding="utf-8").splitlines():
                            stripped = line.strip()
                            if not stripped or stripped.startswith("#"):
                                continue
                            if stripped.startswith("@"):
                                continue
                            if len(stripped) > 140:
                                stripped = stripped[:137] + "…"
                            role_hint = stripped
                            break
                        if role_hint:
                            break
                    except Exception:
                        continue
                # Peek inside the peer agent's directory for Telegram bot
                # config so the wizard can surface "gary already pairs with
                # @ctrl_gary_bot — want to reuse it?" rails. We scan
                # config.json (top level), config["channels"], a sibling
                # .env, and a memory MEMORY.md table — whichever surface
                # the peer happens to use. We never return the secret
                # itself, just a 4-char tail preview.
                telegram_chat_id = ""
                telegram_bot_handle = ""
                telegram_preview = ""
                telegram_source = ""

                def _capture_token(value: str, source: str) -> None:
                    nonlocal telegram_preview, telegram_source
                    value = (value or "").strip().strip("'\"")
                    if not value or telegram_preview:
                        return
                    telegram_preview = "•••" + value[-4:] if len(value) >= 4 else "•••"
                    telegram_source = source

                channels_blob = payload.get("channels")
                if isinstance(channels_blob, dict):
                    tg = channels_blob.get("telegram")
                    if isinstance(tg, dict):
                        chat = tg.get("chat_id") or tg.get("chatId")
                        if chat:
                            telegram_chat_id = str(chat)
                        handle = tg.get("bot_handle") or tg.get("botHandle") or tg.get("username")
                        if handle:
                            telegram_bot_handle = str(handle)
                        for k in ("bot_token", "botToken", "token"):
                            if tg.get(k):
                                _capture_token(str(tg[k]), f"{config_path.name}#channels.telegram.{k}")
                                break

                env_path = config_path.parent / ".env"
                if env_path.exists():
                    try:
                        for raw in env_path.read_text(encoding="utf-8").splitlines():
                            line = raw.strip()
                            if not line or line.startswith("#"):
                                continue
                            if "=" not in line:
                                continue
                            k, _, v = line.partition("=")
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k in ("TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN"):
                                _capture_token(v, ".env#" + k)
                            elif k in ("TELEGRAM_CHAT_ID", "TG_CHAT_ID") and not telegram_chat_id:
                                telegram_chat_id = v
                            elif k in ("TELEGRAM_BOT_USERNAME", "TG_BOT_USERNAME") and not telegram_bot_handle:
                                telegram_bot_handle = v
                    except Exception:
                        pass

                peers.append({
                    "org": org,
                    "name": agent,
                    "enabled": bool(payload.get("enabled", True)),
                    "workingDirectory": str(payload.get("working_directory") or ""),
                    "timezone": str(payload.get("timezone") or ""),
                    "communicationStyle": str(payload.get("communication_style") or ""),
                    "cronCount": len(payload.get("crons") or []),
                    "roleHint": role_hint,
                    "configPath": str(config_path),
                    "telegram": {
                        "configured": bool(telegram_preview or telegram_chat_id),
                        "botHandle": telegram_bot_handle,
                        "chatId": telegram_chat_id,
                        "tokenPreview": telegram_preview,
                        "source": telegram_source,
                    },
                })
        except Exception:
            _log.exception("GET /api/agents/peers failed walking root=%s", root)
            continue
    return {"peers": peers, "rootsSearched": [str(r) for r in roots]}


@app.get("/api/config/tiers")
def get_config_tiers():
    """Return the persisted tier->model mapping plus current resolved tiers.

    Resolved values reflect what ``resolve_tier`` would return *right now*
    given the persisted mapping + harness fallbacks, so the UI can show
    "configured" vs "auto-resolved" in one trip.
    """
    try:
        from elevate_cli.tier_resolver import (
            VALID_TIERS,
            load_tier_config,
            resolve_tier_with_provider,
        )
        mapping = load_tier_config()
        resolved = {}
        for tier_id in VALID_TIERS:
            model_id, provider = resolve_tier_with_provider(tier_id)
            resolved[tier_id] = {"model": model_id, "provider": provider}
        return {
            "tiers": list(VALID_TIERS),
            "mapping": mapping,
            "resolved": resolved,
        }
    except Exception:
        _log.exception("GET /api/config/tiers failed")
        return {"tiers": [], "mapping": {}, "resolved": {}}


class _TierMappingBody(BaseModel):
    mapping: Dict[str, Any]


@app.put("/api/config/tiers")
def put_config_tiers(body: _TierMappingBody):
    """Persist the tier->model mapping. Validates tier names + writes atomically."""
    try:
        from elevate_cli.tier_resolver import save_tier_config, load_tier_config
        save_tier_config(body.mapping or {})
        return {"ok": True, "mapping": load_tier_config()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/config/tiers failed")
        raise HTTPException(status_code=500, detail=str(exc))


def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model_context_length before processing model
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                disk_model["default"] = model_val
                # Write context_length into the model dict (0 = remove/auto)
                if ctx_override > 0:
                    disk_model["context_length"] = ctx_override
                else:
                    disk_model.pop("context_length", None)
                config["model"] = disk_model
            else:
                # Model was previously a bare string — upgrade to dict if
                # user is setting a context_length override
                if ctx_override > 0:
                    config["model"] = {
                        "default": model_val,
                        "context_length": ctx_override,
                    }
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        save_config(_denormalize_config_from_web(body.config))
        return {"ok": True}
    except Exception as e:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    for var_name, value in env_on_disk.items():
        if var_name in result:
            continue
        if not re.match(r"^ELEVATE_AGENT_[A-Z0-9_]+_TELEGRAM_(BOT_TOKEN|CHANNEL)$", var_name):
            continue
        is_token = var_name.endswith("_BOT_TOKEN")
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": "Telegram bot token" if is_token else "Telegram chat or topic routed to this agent",
            "url": "https://t.me/BotFather" if is_token else None,
            "category": "messaging",
            "is_password": is_token,
            "tools": [],
            "advanced": False,
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    try:
        key = str(body.key or "").strip()
        value = str(body.value or "").strip()
        if key == "TELEGRAM_HOME_CHANNEL" and _looks_like_telegram_bot_token(value):
            raise HTTPException(
                status_code=400,
                detail="That looks like a Telegram bot token. Paste it into the Bot token field, not the home chat field.",
            )
        channel_match = _AGENT_TELEGRAM_CHANNEL_RE.fullmatch(key)
        if channel_match and _looks_like_telegram_bot_token(value):
            raise HTTPException(
                status_code=400,
                detail="That looks like a Telegram bot token. Paste it into the Bot token field, not the chat/topic field.",
            )
        token_match = _AGENT_TELEGRAM_BOT_TOKEN_RE.fullmatch(key)
        if token_match:
            _reject_shared_agent_token(token_match.group(1), value)
        synced = _sync_executive_telegram_aliases(key, value)
        save_env_value(key, value)
        return {"ok": True, "key": key, "synced": synced}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var.

    Protected by:
    - Ephemeral session token (generated per server start, injected into SPA)
    - Rate limiting (max 5 reveals per 30s window)
    - Audit logging
    """
    # --- Token check ---
    _require_token(request)

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many reveal requests. Try again shortly.")
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic, device-code for Nous/Codex) still runs in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``elevate auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.
    """
    if not value:
        return ""
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Elevate resolves Anthropic creds in this order at runtime:
    1. ``~/.elevate/.anthropic_oauth.json`` — Elevate-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_elevate_oauth_credentials,
            read_claude_code_credentials,
            _ELEVATE_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_elevate_oauth_credentials = None  # type: ignore
        _ELEVATE_OAUTH_FILE = None  # type: ignore

    elevate_creds = None
    if read_elevate_oauth_credentials:
        try:
            elevate_creds = read_elevate_oauth_credentials()
        except Exception:
            elevate_creds = None
    if elevate_creds and elevate_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "elevate_pkce",
            "source_label": f"Elevate PKCE ({_ELEVATE_OAUTH_FILE})",
            "token_preview": _truncate_token(elevate_creds.get("accessToken")),
            "expires_at": elevate_creds.get("expiresAt"),
            "has_refresh_token": bool(elevate_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "ANTHROPIC_TOKEN environment variable",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Elevate even
    when they also have a separate Elevate-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials
        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "elevate auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (subscription)",
        # PKCE flow — refreshes the same Anthropic credential family that
        # Claude Code reads. Functionally identical to the Anthropic entry;
        # exposed separately so users coming from `claude setup-token` can
        # find a Login button without learning that "Anthropic" covers it.
        "flow": "pkce",
        "cli_command": "elevate auth add anthropic",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
    },
    {
        "id": "nous",
        "name": "Nous Portal",
        "flow": "device_code",
        "cli_command": "elevate auth add nous",
        "docs_url": "https://portal.nousresearch.com",
        "status_fn": None,  # dispatched via auth.get_nous_auth_status
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "elevate auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "elevate auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
    },
    {
        "id": "xai-oauth",
        "name": "xAI Grok (SuperGrok subscription)",
        # Loopback PKCE browser login (auth.x.ai). Surfaced as `external` so the
        # card shows the one-shot `elevate auth add xai-oauth` command + live
        # connection status, mirroring how Qwen is handled — no in-dashboard
        # OAuth server needed.
        "flow": "external",
        "cli_command": "elevate auth add xai-oauth",
        "docs_url": "https://elevate-agent.nousresearch.com/docs/guides/xai-grok-oauth",
        "status_fn": None,  # dispatched via auth.get_xai_oauth_auth_status
    },
    {
        "id": "google-gemini-cli",
        "name": "Google Gemini (OAuth — free tier)",
        "flow": "external",
        "cli_command": "elevate auth add google-gemini-cli",
        "docs_url": "https://github.com/google-gemini/gemini-cli",
        "status_fn": None,  # dispatched via auth.get_gemini_oauth_auth_status
    },
    {
        "id": "minimax-oauth",
        "name": "MiniMax (OAuth Coding Plan)",
        "flow": "external",
        "cli_command": "elevate auth add minimax-oauth",
        "docs_url": "https://www.minimax.io",
        "status_fn": None,  # dispatched via auth.get_minimax_oauth_auth_status
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from elevate_cli import auth as hauth
        if provider_id == "nous":
            raw = hauth.get_nous_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "nous_portal",
                "source_label": raw.get("portal_base_url") or "Nous Portal",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("access_expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "xai-oauth":
            raw = hauth.get_xai_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "xai_oauth",
                "source_label": raw.get("auth_mode") or "xAI Grok",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": bool(raw.get("api_key")),
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "google-gemini-cli":
            raw = hauth.get_gemini_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "google_oauth",
                "source_label": raw.get("email") or "Google Gemini",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": raw.get("expires_at_ms"),
                "has_refresh_token": bool(raw.get("logged_in")),
            }
        if provider_id == "minimax-oauth":
            raw = hauth.get_minimax_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "minimax_oauth",
                "source_label": f"MiniMax ({raw.get('region', 'global')})",
                "token_preview": None,
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("logged_in")),
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("elevate_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append({
            "id": p["id"],
            "name": p["name"],
            "flow": p["flow"],
            "cli_command": p["cli_command"],
            "docs_url": p["docs_url"],
            "status": status,
        })
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    _require_token(request)

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_id}. "
                   f"Available: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Elevate-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in ("anthropic", "claude-code"):
        try:
            from agent.anthropic_adapter import _ELEVATE_OAUTH_FILE
            if _ELEVATE_OAUTH_FILE.exists():
                _ELEVATE_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from elevate_cli.auth import clear_provider_auth
            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from elevate_cli.auth import clear_provider_auth
        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.elevate/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (Nous, OpenAI Codex):
#     1. POST /api/providers/oauth/{nous|openai-codex}/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so elevate web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )
    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(access_token: str, refresh_token: str, expires_at_ms: int) -> None:
    """Persist Anthropic PKCE creds to both Elevate file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``elevate auth add anthropic``.
    """
    from agent.anthropic_adapter import _ELEVATE_OAUTH_FILE
    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _ELEVATE_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ELEVATE_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid
        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [e for e in pool.entries() if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Anthropic OAuth not available (missing adapter)")
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {"ok": False, "status": sess["status"], "message": sess.get("error_message")}

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "code": code,
        "state": state_from_callback or sess["state"],
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "code_verifier": sess["verifier"],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "elevate-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        sess["status"] = "error"
        sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        sess["status"] = "error"
        sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        sess["status"] = "error"
        sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (Nous or OpenAI Codex).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    from elevate_cli import auth as hauth
    if provider_id == "nous":
        from elevate_cli.auth import _request_device_code, PROVIDER_REGISTRY
        import httpx
        pconfig = PROVIDER_REGISTRY["nous"]
        portal_base_url = (
            os.getenv("ELEVATE_PORTAL_BASE_URL")
            or os.getenv("NOUS_PORTAL_BASE_URL")
            or pconfig.portal_base_url
        ).rstrip("/")
        client_id = pconfig.client_id
        scope = pconfig.scope
        def _do_nous_device_request():
            with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
                return _request_device_code(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=client_id,
                    scope=scope,
                )
        device_data = await asyncio.get_event_loop().run_in_executor(None, _do_nous_device_request)
        sid, sess = _new_oauth_session("nous", "device_code")
        sess["device_code"] = str(device_data["device_code"])
        sess["interval"] = int(device_data["interval"])
        sess["expires_at"] = time.time() + int(device_data["expires_in"])
        sess["portal_base_url"] = portal_base_url
        sess["client_id"] = client_id
        threading.Thread(
            target=_nous_poller, args=(sid,), daemon=True, name=f"oauth-poll-{sid[:6]}"
        ).start()
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": str(device_data["user_code"]),
            "verification_url": str(device_data["verification_uri_complete"]),
            "expires_in": int(device_data["expires_in"]),
            "poll_interval": int(device_data["interval"]),
        }

    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker, args=(sid,), daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.time() + 10
        while time.time() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(status_code=500, detail=s.get("error_message") or "device-auth failed")
        if not s.get("user_code"):
            raise HTTPException(status_code=504, detail="device-auth timed out before returning a user code")
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(status_code=400, detail=f"Provider {provider_id} does not support device-code flow")


def _nous_poller(session_id: str) -> None:
    """Background poller that drives a Nous device-code flow to completion."""
    from elevate_cli.auth import _poll_for_token, refresh_nous_oauth_from_state
    from datetime import datetime, timezone
    import httpx
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    device_code = sess["device_code"]
    interval = sess["interval"]
    expires_in = max(60, int(sess["expires_at"] - time.time()))
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
            token_data = _poll_for_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                device_code=device_code,
                expires_in=expires_in,
                poll_interval=interval,
            )
        # Same post-processing as _nous_device_code_login (mint agent key)
        now = datetime.now(timezone.utc)
        token_ttl = int(token_data.get("expires_in") or 0)
        auth_state = {
            "portal_base_url": portal_base_url,
            "inference_base_url": token_data.get("inference_base_url"),
            "client_id": client_id,
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "obtained_at": now.isoformat(),
            "expires_at": (
                datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc).isoformat()
                if token_ttl else None
            ),
            "expires_in": token_ttl,
        }
        full_state = refresh_nous_oauth_from_state(
            auth_state, min_key_ttl_seconds=300, timeout_seconds=15.0,
            force_refresh=False, force_mint=True,
        )
        from elevate_cli.auth import persist_nous_credentials
        persist_nous_credentials(full_state)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: nous login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("nous device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    try:
        import httpx
        from elevate_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )
        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError("device-code response missing user_code or device_auth_id")
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.time() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.time() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in (403, 404):
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Device code expired before approval"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError("device-auth response missing authorization_code/code_verifier")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid
        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("ELEVATE_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    _require_token(request)
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} uses an external CLI; run `{catalog_entry['cli_command']}` manually",
        )
    try:
        if catalog_entry["flow"] == "pkce":
            # anthropic + claude-code share the same Anthropic PKCE plumbing.
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    _require_token(request)
    # claude-code shares the Anthropic PKCE plumbing — same credential family.
    if provider_id in {"anthropic", "claude-code"}:
        return await asyncio.get_event_loop().run_in_executor(
            None, _submit_anthropic_pkce, body.session_id, body.code,
        )
    raise HTTPException(status_code=400, detail=f"submit not supported for {provider_id}")


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch for session")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    _require_token(request)
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "session not found"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from elevate_state import SessionDB
    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        session = db.get_session(active_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        session.update(_session_identity_payload(identity))
        session["requested_session_id"] = sid
        return session
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    from elevate_state import SessionDB
    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        messages = db.get_messages(active_id)
        # Decorate each row with the stable wire id used for transcript
        # reconciliation. Pre-upgrade rows (NULL client_message_id) get the
        # deterministic weak fallback `legacy.{session}.{ordinal}` — ordinal =
        # raw row position in pk order, the SAME scheme
        # get_messages_as_conversation uses, so REST and gateway-resume mint
        # identical ids for the same legacy row.
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and not msg.get("client_message_id"):
                msg["client_message_id"] = f"legacy.{active_id}.{i}"
            if isinstance(msg, dict):
                msg["message_id"] = msg["client_message_id"]
        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "messages": messages,
        }
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/todos")
async def get_session_todos(session_id: str):
    """Current plan/todo list for a session (the chat Plan panel's source).

    The gateway runs a fresh AIAgent per turn, so the in-memory TodoStore is
    empty between turns -- the durable source is the most recent `todo` tool
    result in the message history. This mirrors AIAgent._hydrate_todo_store
    (run_agent.py): walk history newest-first for a tool message whose content
    parses to {"todos": [...]}. We serve it from here (untruncated) because the
    client tool stream caps tool results at 300 chars, which corrupts any real
    plan's JSON.
    """
    from elevate_state import SessionDB

    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        checkpoint = _read_session_checkpoint(
            db, active_id, identity.get("lineage_root_id"), sid
        )
        messages = db.get_messages(active_id)
    finally:
        db.close()

    todos: list = []
    updated_at = checkpoint.get("updated_at") if checkpoint else None
    if isinstance(checkpoint.get("todos"), list):
        todos = [t for t in checkpoint["todos"] if isinstance(t, dict)]
    from tools.todo_tool import parse_todo_injection

    for msg in reversed(messages):
        content = _content_as_text(msg.get("content"))
        if msg.get("role") == "tool" and '"todos"' in content:
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError, ValueError):
                data = None
            if isinstance(data, dict) and isinstance(data.get("todos"), list):
                todos = [t for t in data["todos"] if isinstance(t, dict)]
                updated_at = msg.get("created_at") or msg.get("timestamp")
                break
        injected = parse_todo_injection(content)
        if injected:
            todos = injected
            updated_at = msg.get("created_at") or msg.get("timestamp")
            break

    def _count(status: str) -> int:
        return sum(1 for t in todos if t.get("status") == status)

    return {
        "session_id": active_id,
        "requested_session_id": sid,
        **_session_identity_payload(identity),
        "todos": todos,
        "updated_at": updated_at,
        "summary": {
            "total": len(todos),
            "pending": _count("pending"),
            "in_progress": _count("in_progress"),
            "completed": _count("completed"),
            "cancelled": _count("cancelled"),
        },
    }


@app.get("/api/sessions/{session_id}/plan")
async def get_session_plan(session_id: str):
    """The full detailed plan for a session (chat Plan panel).

    The agent calls the `present_plan` tool with a rich Markdown plan; its
    result is stored untruncated in the message history. We walk newest-first
    for the most recent `present_plan` result and return its markdown so the
    panel can render it (the tool stream caps results, so we read it here).
    """
    from elevate_state import SessionDB

    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        checkpoint = _read_session_checkpoint(
            db, active_id, identity.get("lineage_root_id"), sid
        )
        messages = db.get_messages(active_id)
    finally:
        db.close()

    plan_md = str(checkpoint.get("plan") or "") if checkpoint else ""
    title = str(checkpoint.get("plan_title") or "") if checkpoint else ""
    updated_at = checkpoint.get("updated_at") if checkpoint else None
    from tools.present_plan_tool import PLAN_INJECTION_HEADER, extract_latest_plan_from_messages

    latest = extract_latest_plan_from_messages(messages)
    if latest:
        plan_md, parsed_title = latest
        title = parsed_title or ""
        for msg in reversed(messages):
            content = _content_as_text(msg.get("content"))
            if PLAN_INJECTION_HEADER in content or '"plan"' in content:
                updated_at = msg.get("created_at") or msg.get("timestamp")
                break

    return {
        "session_id": active_id,
        "requested_session_id": sid,
        **_session_identity_payload(identity),
        "plan": plan_md,
        "title": title,
        "updated_at": updated_at,
    }


_SESSION_FILE_ARG_KEYS = (
    "path", "file_path", "target_file", "filename", "file", "notebook_path",
)
_SESSION_FILE_RESULT_KEYS = _SESSION_FILE_ARG_KEYS + (
    "files", "paths", "files_read", "files_written", "output_path",
    "output_file", "artifact", "artifacts", "artifact_path",
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w/])(?:/Users|/tmp|/private/tmp|/var/folders|/Volumes)/[^\s`'\"<>),]+"
)


def _subagent_meta(db: Any, session_id: str) -> Dict[str, Any]:
    """For a subagent session, surface its parent (for a 'back to chat' button)
    and the agent it ran as (so the UI names it dynamically, no hardcode)."""
    out: Dict[str, Any] = {}
    try:
        row = db.get_session(session_id) or {}
        parent = row.get("parent_session_id") or row.get("parentSessionId")
        if parent:
            out["parent_session_id"] = parent
        mc = row.get("model_config") or row.get("modelConfig")
        if isinstance(mc, str):
            import json as _json
            try:
                mc = _json.loads(mc)
            except Exception:
                mc = {}
        agent_id = (mc or {}).get("agent_id") if isinstance(mc, dict) else None
        if agent_id:
            out["agent_id"] = agent_id
            try:
                from elevate_cli.agent_hub import get_agent_def
                d = get_agent_def(str(agent_id))
                if isinstance(d, dict) and d.get("name"):
                    out["agent_name"] = d.get("name")
            except Exception:
                pass
    except Exception:
        pass
    return out


def _session_identity_payload(identity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requested_session_id": identity.get("requested_session_id"),
        "lineage_root_id": identity.get("lineage_root_id"),
        "active_session_id": identity.get("active_session_id"),
        "session_kind": identity.get("session_kind"),
        "is_compression_tip": identity.get("is_compression_tip"),
        "parent_session_id": identity.get("parent_session_id"),
        "agent_id": identity.get("agent_id"),
        "agent_name": identity.get("agent_name"),
    }


def _is_cron_session_row(session: Dict[str, Any] | None, session_id: str = "") -> bool:
    sid = str((session or {}).get("id") or session_id or "")
    source = str((session or {}).get("source") or "")
    return source == "cron" or sid.startswith("cron_")


def _resolve_active_session_or_404(db: Any, session_id: str) -> tuple[str, str, Dict[str, Any]]:
    sid = db.resolve_session_id(session_id)
    if not sid:
        raise HTTPException(status_code=404, detail="Session not found")
    identity = db.resolve_canonical_session_identity(sid)
    requested_session = db.get_session(sid)
    if _is_cron_session_row(requested_session, sid):
        identity["active_session_id"] = sid
        identity["lineage_root_id"] = identity.get("lineage_root_id") or sid
        identity["session_kind"] = "cron"
        identity["is_compression_tip"] = True
        return sid, sid, identity
    active_id = str(identity.get("active_session_id") or sid)
    if not db.get_session(active_id):
        active_id = sid
        identity["active_session_id"] = sid
        identity["lineage_root_id"] = identity.get("lineage_root_id") or sid
        identity["session_kind"] = identity.get("session_kind") or "chat"
    # Subagent: attach its parent (for a back-to-chat button) + the agent it ran
    # as (so the badge names it dynamically).
    if identity.get("session_kind") == "subagent":
        identity.update(_subagent_meta(db, active_id))
    return sid, active_id, identity


def _read_session_checkpoint(db: Any, *session_ids: Any) -> dict:
    seen: set[str] = set()
    for raw_sid in session_ids:
        sid = str(raw_sid or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            raw = db.get_meta(f"session_checkpoint:{sid}")
        except Exception:
            continue
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _content_as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _append_path_values(value: Any, out: list[str], seen: set[str], *, recursive: bool = True) -> None:
    if len(out) >= 2000:
        return
    if isinstance(value, str):
        raw = value.strip()
        if raw and raw not in seen:
            seen.add(raw)
            out.append(raw)
        return
    if isinstance(value, list):
        for item in value:
            _append_path_values(item, out, seen, recursive=recursive)
        return
    if recursive and isinstance(value, dict):
        for item in value.values():
            _append_path_values(item, out, seen, recursive=recursive)


def _extract_session_file_candidates(messages: list[dict]) -> list[str]:
    raw_seen: set[str] = set()
    candidates: list[str] = []
    for msg in messages:
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else None
                args = (fn or {}).get("arguments", call.get("arguments"))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        args = None
                if isinstance(args, dict):
                    for key in _SESSION_FILE_ARG_KEYS:
                        _append_path_values(args.get(key), candidates, raw_seen, recursive=True)

        content_text = _content_as_text(msg.get("content"))
        if content_text:
            for match in _ABSOLUTE_PATH_RE.findall(content_text):
                _append_path_values(match.rstrip(".:;"), candidates, raw_seen, recursive=False)
            if msg.get("role") == "tool" and "{" in content_text:
                try:
                    data = json.loads(content_text)
                except (json.JSONDecodeError, TypeError, ValueError):
                    data = None
                if isinstance(data, dict):
                    for key in _SESSION_FILE_RESULT_KEYS:
                        _append_path_values(data.get(key), candidates, raw_seen, recursive=True)
    return candidates


def _resolve_existing_session_files(candidates: list[str], *, limit: int = 500) -> list[dict]:
    files: list[dict] = []
    out_seen: set[str] = set()
    for raw in candidates:
        try:
            cleaned = re.sub(r":\d+(?::\d+)?$", "", raw.strip())
            path = Path(os.path.expandvars(cleaned)).expanduser()
        except (OSError, ValueError):
            continue
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_file():
                continue
        except OSError:
            continue
        key = str(resolved)
        if key in out_seen:
            continue
        out_seen.add(key)
        files.append({"path": key, "name": resolved.name})
        if len(files) >= limit:
            break
    return files


def _artifact_kind(path: Path, mime_type: Optional[str]) -> str:
    suffix = path.suffix.lower()
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if mime_type and mime_type.startswith("video/"):
        return "video"
    if mime_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown", ".txt", ".json", ".csv", ".tsv", ".html", ".svg"}:
        return "document"
    if suffix in {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx"}:
        return "document"
    return "file"


@app.get("/api/sessions/{session_id}/files")
async def get_session_files(session_id: str):
    """Files the agent actually worked on in a session (the Files panel source).

    Elevate chats have no single workspace dir, so "the files it was working on"
    is reconstructed from the file paths the agent passed to file tools
    (read_file / edit / write_file / etc.). We keep only paths that resolve to an
    existing file — directories (e.g. search_files roots) and dead paths drop out.
    """
    from elevate_state import SessionDB

    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        checkpoint = _read_session_checkpoint(
            db, active_id, identity.get("lineage_root_id"), sid
        )
        messages = db.get_messages(active_id)
    finally:
        db.close()

    checkpoint_files = checkpoint.get("files") if isinstance(checkpoint, dict) else None
    candidates = [str(p) for p in checkpoint_files if isinstance(p, str)] if isinstance(checkpoint_files, list) else []
    if not candidates:
        candidates = _extract_session_file_candidates(messages)
    files = _resolve_existing_session_files(candidates)
    return {
        "session_id": active_id,
        "requested_session_id": sid,
        **_session_identity_payload(identity),
        "files": files,
    }


@app.get("/api/sessions/{session_id}/turn_usage")
async def get_session_turn_usage(session_id: str):
    """Per-turn usage (model, tokens, cost, latency) for a session's footer.

    turn_usage rows are keyed by a gateway message_id that won't match the
    frontend's message ids, so we return them ordered by timestamp and let the
    UI join by nearest-timestamp to each displayed assistant turn.
    """
    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        rows = db.turn_usage_for_session(active_id)
    finally:
        db.close()

    fields = (
        "message_id", "model", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
        "total_tokens", "estimated_cost_usd", "latency_ms", "timestamp",
    )
    return {
        "session_id": active_id,
        "requested_session_id": sid,
        "turn_usage": [{k: r.get(k) for k in fields} for r in rows],
    }


@app.get("/api/sessions/{session_id}/artifacts")
async def get_session_artifacts(session_id: str):
    """Artifacts/files surfaced from a session's durable transcript."""
    from elevate_state import SessionDB

    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        checkpoint = _read_session_checkpoint(
            db, active_id, identity.get("lineage_root_id"), sid
        )
        messages = db.get_messages(active_id)
    finally:
        db.close()

    checkpoint_files = checkpoint.get("files") if isinstance(checkpoint, dict) else None
    candidates = [str(p) for p in checkpoint_files if isinstance(p, str)] if isinstance(checkpoint_files, list) else []
    if not candidates:
        candidates = _extract_session_file_candidates(messages)

    artifacts: list[dict] = []
    for file_entry in _resolve_existing_session_files(
        candidates,
        limit=500,
    ):
        path = Path(file_entry["path"])
        mime_type, _encoding = mimetypes.guess_type(str(path))
        try:
            stat = path.stat()
            size = stat.st_size
            modified_at = stat.st_mtime
        except OSError:
            size = None
            modified_at = None
        artifacts.append({
            "id": hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16],
            "path": str(path),
            "name": path.name,
            "kind": _artifact_kind(path, mime_type),
            "mime_type": mime_type,
            "size": size,
            "modified_at": modified_at,
        })

    return {
        "session_id": active_id,
        "requested_session_id": sid,
        **_session_identity_payload(identity),
        "artifacts": artifacts,
    }


@app.get("/api/sessions/{session_id}/children")
async def get_session_children(session_id: str):
    """Physical child sessions/runs for a logical session lineage."""
    from elevate_state import SessionDB

    db = _get_session_db()
    try:
        sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
        children = db.list_child_sessions(active_id)
    finally:
        db.close()

    return {
        "session_id": active_id,
        "requested_session_id": sid,
        **_session_identity_payload(identity),
        "children": children,
    }


@app.put("/api/sessions/{session_id}/title")
async def update_session_title_endpoint(session_id: str, payload: SessionTitleUpdate):
    from elevate_state import SessionDB
    db = _get_session_db()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            updated = db.set_session_title(sid, payload.title or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not updated:
            raise HTTPException(status_code=404, detail="Session not found")
        session = db.get_session(sid)
        return {"ok": True, "title": session.get("title") if session else None}
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/reveal")
async def reveal_session_endpoint(session_id: str):
    from elevate_state import SessionDB
    db = _get_session_db()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid or not db.get_session(sid):
            raise HTTPException(status_code=404, detail="Session not found")
        target = _session_reveal_target(sid)
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(target)
        return {"ok": True, "path": str(target)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"File manager unavailable: {exc}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open session location: {exc}")
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from elevate_state import SessionDB
    db = _get_session_db()
    deleted = False
    try:
        resolver = getattr(db, "resolve_session_id", None)
        sid = resolver(session_id) if callable(resolver) else session_id
        if sid:
            deleted = bool(db.delete_session(sid))
        try:
            from elevate_cli.data.chat_sessions import delete_session as delete_chat_session

            deleted = bool(delete_chat_session(sid or session_id)) or deleted
        except Exception:
            _log.debug("PG chat session delete failed", exc_info=True)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from elevate_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_elevate_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from elevate_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                       f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path, min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class SourceConnectorAction(BaseModel):
    action: str
    sourceId: str


class IntegrationSettingsUpdate(BaseModel):
    provider: str = "custom"
    label: str = "CRM"
    apiKeyEnv: str = "CRM_API_KEY"
    apiKey: str = ""
    baseUrl: str = ""
    authType: str = "header"
    authHeader: str = "Authorization"
    authPrefix: str = "Bearer "
    authQueryParam: str = "api_key"
    dbColumns: dict = Field(default_factory=dict)
    endpoints: dict = Field(default_factory=dict)
    action: str = ""


app.include_router(create_cron_router(log=_log))

app.include_router(create_source_connectors_router(log=_log))

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
    (back-compat). Mirrors the cortextOS experiments scan but Elevate-native
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
    """Create a NEW custom surface from the template + overrides (cortextOS add-agent
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
    all writes. Elevate-native port of cortextOS scanExperiments().
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
    """CortextOS-compatible experiment list backed by native heartbeat experiments."""
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
    """CortextOS-style Meeting Room feed projected from Elevate handoffs."""
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
    """CortextOS-style per-pair conversation list projected from handoffs."""
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
    """Return one pair transcript in CortextOS channel-view shape."""
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
# Phase 6: thread scoring (lead scorer + dead label cron)
# ---------------------------------------------------------------------------

class _ThreadScoreBody(BaseModel):
    sourceId: str
    threadId: str
    score: int
    label: str
    reason: Optional[str] = None
    scoredBy: Optional[str] = None


class _ThreadDeadBody(BaseModel):
    sourceId: str
    threadId: str
    reason: Optional[str] = None
    scoredBy: Optional[str] = None


@app.get("/api/threads/meta")
async def list_thread_meta_endpoint(
    label: Optional[str] = None,
    minScore: Optional[int] = None,
    limit: int = 200,
):
    try:
        from elevate_cli import outreach_db

        return {
            "items": outreach_db.list_thread_meta(label=label, min_score=minScore, limit=limit),
            "stats": outreach_db.thread_meta_stats(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/threads/meta failed")
        raise HTTPException(status_code=500, detail=f"List thread meta failed: {exc}")


@app.get("/api/threads/meta/{source_id}/{thread_id}")
async def get_thread_meta_endpoint(source_id: str, thread_id: str):
    try:
        from elevate_cli import outreach_db

        meta = outreach_db.get_thread_meta(source_id, thread_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="not scored")
        return {"meta": meta}
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("GET /api/threads/meta/{source_id}/{thread_id} failed")
        raise HTTPException(status_code=500, detail=f"Get thread meta failed: {exc}")


@app.post("/api/threads/score")
async def score_thread_endpoint(body: _ThreadScoreBody):
    try:
        from elevate_cli import outreach_db

        meta = outreach_db.upsert_thread_score(
            body.sourceId,
            body.threadId,
            score=body.score,
            label=body.label,
            reason=body.reason,
            scored_by=body.scoredBy,
        )
        return {"meta": meta}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/threads/score failed")
        raise HTTPException(status_code=500, detail=f"Score thread failed: {exc}")


@app.post("/api/threads/dead")
async def mark_thread_dead_endpoint(body: _ThreadDeadBody):
    try:
        from elevate_cli import outreach_db

        meta = outreach_db.mark_thread_dead(
            body.sourceId,
            body.threadId,
            reason=body.reason,
            scored_by=body.scoredBy,
        )
        return {"meta": meta}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/threads/dead failed")
        raise HTTPException(status_code=500, detail=f"Mark dead failed: {exc}")


# ---------------------------------------------------------------------------
# Phase 7: per-lane channel picker
# ---------------------------------------------------------------------------

class _LaneChannelsBody(BaseModel):
    channels: list[str]


def _build_available_channels() -> dict[str, Any]:
    """Compute which channels the user can pick from for a lane, derived
    from (a) currently connected source connectors that aren't read-only and
    (b) Composio toolkits whose capability matrix says ``send.supported``
    AND have at least one connected account (no live account = nothing to
    send through, even if the matrix supports it).

    The shape is two arrays so the dashboard can render them in two groups:

    ```
    {
      "sourceChannels": [{id, label, channel, state}],
      "composioChannels": [{toolkit, slug, verification, label, accountCount}]
    }
    ```
    """
    from elevate_cli.source_connectors import build_source_connectors_response
    from elevate_cli import composio_client

    src_resp = build_source_connectors_response(include_prompts=False)
    source_channels: list[dict[str, Any]] = []
    for c in src_resp.get("connectors", []):
        sid = str(c.get("id") or "")
        if not sid:
            continue
        state = str(c.get("state") or "").lower()
        # Skip connectors that are read-only / not configured / blocked. The
        # picker should only show channels the user can actually send through.
        if state in {"blocked", "not_configured"}:
            continue
        source_channels.append({
            "id": f"source:{sid}",
            "sourceId": sid,
            "label": str(c.get("label") or sid),
            "channel": str(c.get("channel") or sid),
            "state": state or "ok",
        })

    matrix = composio_client.load_capability_matrix() or {}
    composio_channels: list[dict[str, Any]] = []
    for slug, entry in (matrix.get("toolkits") or {}).items():
        send = (entry or {}).get("send") or {}
        if not send.get("supported"):
            continue
        # Per Codex review #5: a "supported" toolkit with zero connected
        # accounts is not actually a channel the user can pick. Probe live
        # accounts; if Composio is unreachable, omit the toolkit rather than
        # advertise a channel we know the user can't use.
        try:
            accounts_resp = composio_client.list_all_connected_accounts(toolkit=slug)
            if not accounts_resp.get("ok"):
                continue
            accounts = (accounts_resp.get("data") or {}).get("items") or []
            if not accounts:
                continue
        except Exception:
            continue
        composio_channels.append({
            "id": f"composio:{slug}",
            "toolkit": slug,
            "slug": send.get("slug"),
            "label": str(slug).replace("_", " ").title(),
            "verification": send.get("verification") or "unknown",
            "accountCount": len(accounts),
        })

    return {
        "sourceChannels": source_channels,
        "composioChannels": composio_channels,
    }


def _reconcile_lane_config(config: dict[str, Any], available: dict[str, Any]) -> dict[str, Any]:
    """Strip stale enabled channels from a lane config snapshot.

    Saved configs survive across connector disconnects and Composio account
    revocations — without reconciliation the dashboard would render channels
    the user can't actually use. We don't mutate the DB row here; the GET
    response simply hides stale entries (and surfaces them under
    ``droppedChannels`` so the UI can flag the change).
    """
    if not isinstance(config, dict):
        return config
    valid_ids = (
        {c["id"] for c in available.get("sourceChannels", [])}
        | {c["id"] for c in available.get("composioChannels", [])}
    )
    saved = list(config.get("enabledChannels") or [])
    kept = [c for c in saved if c in valid_ids]
    dropped = [c for c in saved if c not in valid_ids]
    if not dropped:
        return config
    out = dict(config)
    out["enabledChannels"] = kept
    out["droppedChannels"] = dropped
    return out


@app.get("/api/lanes")
async def list_lanes_endpoint():
    """Return every lane's saved channel selection plus the universe of
    available channels the picker should expose. Saved channels that no
    longer exist in the availability set are stripped on the way out and
    reported under ``droppedChannels`` so the UI can flag the regression."""
    try:
        from elevate_cli import outreach_db

        avail = _build_available_channels()
        lanes = [_reconcile_lane_config(l, avail) for l in outreach_db.list_lane_configs()]
        return {
            "lanes": lanes,
            "available": avail,
        }
    except Exception as exc:
        _log.exception("GET /api/lanes failed")
        raise HTTPException(status_code=500, detail=f"List lanes failed: {exc}")


@app.get("/api/lanes/{lane}/channels")
async def get_lane_channels_endpoint(lane: str):
    try:
        from elevate_cli import outreach_db

        avail = _build_available_channels()
        return {
            "config": _reconcile_lane_config(outreach_db.get_lane_config(lane), avail),
            "available": avail,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/lanes/{lane}/channels failed")
        raise HTTPException(status_code=500, detail=f"Get lane channels failed: {exc}")


@app.get("/api/onboarding/status")
async def get_onboarding_status_endpoint(request: Request):
    """Cheap polling endpoint for the dashboard onboarding wizard.

    The dashboard sends ``If-None-Match: <etag>`` (Phase O wires the wizard
    to poll every ~10s). If the etag matches, return 304 — saves a render
    cycle on the lane cards. We respond with the bare etag in the ``ETag``
    response header on 200s so the next request can short-circuit.
    """
    from fastapi import Response
    from fastapi.responses import JSONResponse
    from elevate_cli.onboarding import compute_onboarding_status, parse_if_none_match

    try:
        status = compute_onboarding_status()
        inm = parse_if_none_match(request.headers.get("if-none-match"))
        etag = status["etag"]
        if inm and inm == etag:
            return Response(status_code=304, headers={"ETag": f'"{etag}"'})
        return JSONResponse(status, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        _log.exception("GET /api/onboarding/status failed")
        raise HTTPException(status_code=500, detail=f"Onboarding status failed: {exc}")


@app.post("/api/outreach/templates/seed-all")
async def seed_all_templates_endpoint():
    """Idempotent re-seed of the lane templates. Wizard calls this when the
    `templates_seeded` check is failing. Existing user-edited templates with
    the same ``(lane, name)`` are left alone."""
    try:
        from elevate_cli import outreach_db

        return outreach_db.seed_all_templates()
    except Exception as exc:
        _log.exception("POST /api/outreach/templates/seed-all failed")
        raise HTTPException(status_code=500, detail=f"Seed templates failed: {exc}")


@app.put("/api/lanes/{lane}/channels")
async def put_lane_channels_endpoint(lane: str, body: _LaneChannelsBody):
    """Replace the lane's enabled channels. The server validates each entry
    against the live availability set so callers can't persist a channel the
    user can't actually use."""
    try:
        from elevate_cli import outreach_db

        avail = _build_available_channels()
        valid_ids = {c["id"] for c in avail["sourceChannels"]} | {c["id"] for c in avail["composioChannels"]}

        cleaned: list[str] = []
        rejected: list[str] = []
        for raw in body.channels:
            cid = str(raw).strip()
            if not cid:
                continue
            if cid in valid_ids:
                cleaned.append(cid)
            else:
                rejected.append(cid)

        if rejected:
            raise HTTPException(
                status_code=400,
                detail=f"unknown or unsupported channels: {', '.join(rejected)}",
            )

        config = outreach_db.set_lane_channels(lane, cleaned)
        return {"config": config, "available": avail}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/lanes/{lane}/channels failed")
        raise HTTPException(status_code=500, detail=f"Set lane channels failed: {exc}")


from elevate_cli.source_connectors import (  # noqa: E402
    AGENT_SESSION_SOURCE_IDS as _AGENT_SESSION_SOURCE_IDS,
    WIRED_SOURCE_IDS as _WIRED_SOURCE_IDS,
)


@app.post("/api/source-connectors")
async def update_source_connector(body: SourceConnectorAction):
    if body.action not in {"scaffold", "refresh", "run-prompt"}:
        raise HTTPException(status_code=400, detail="Unsupported source connector action")
    try:
        from elevate_cli.source_connectors import (
            build_source_connectors_response,
            connector_view as _connector_view,
            get_source_root_info,
            initialize_apple_messages_source,
            scaffold_source,
            source_prompt_for,
        )

        refresh_summary: dict[str, Any] | None = None
        run_result: dict[str, Any] | None = None
        run_error: str | None = None
        composio_summary: dict[str, Any] | None = None

        def _run_canonical(source_id: str) -> dict[str, Any] | None:
            """Fire the source's wired pull. Returns the composio summary for
            social; None for apple-messages and crm (their state lives in the
            connector_view we read after). For unwired sources, scaffolds the
            agent setup task with the latest prompt embedded."""
            if source_id == "apple-messages":
                initialize_apple_messages_source()
                return None
            if source_id == "crm":
                scaffold_source("crm")
                return None
            if source_id == "social":
                from elevate_cli import composio_inbound
                return composio_inbound.pull_all_supported()
            scaffold_source(source_id)
            return None

        if body.action == "refresh":
            refresh_summary = _run_canonical(body.sourceId)
        elif body.action == "run-prompt":
            prompt_text = source_prompt_for(body.sourceId)
            wired = body.sourceId in _WIRED_SOURCE_IDS
            agent_session = body.sourceId in _AGENT_SESSION_SOURCE_IDS
            if not agent_session:
                try:
                    composio_summary = _run_canonical(body.sourceId)
                except Exception as exc:
                    _log.exception("run-prompt for %s failed", body.sourceId)
                    run_error = f"{type(exc).__name__}: {exc}"

            # Read post-run connector state so the UI can show real outcome.
            info = get_source_root_info()
            source_root = Path(info["sourceRoot"])
            view = _connector_view(source_root, body.sourceId) or {}

            counts = view.get("recordCounts") if isinstance(view, dict) else None
            counts = counts if isinstance(counts, dict) else {}
            contact_count = int(counts.get("contacts") or 0)
            conversation_count = int(counts.get("conversations") or 0)
            message_count = int(counts.get("messages") or 0)

            auth_status = view.get("authStatus") if isinstance(view, dict) else None
            last_error = view.get("lastError") if isinstance(view, dict) else None
            next_step = view.get("nextOperatorStep") if isinstance(view, dict) else None
            connected = bool(view.get("connected")) if isinstance(view, dict) else False

            outcome_kind: str
            outcome_message: str

            if run_error:
                outcome_kind = "error"
                outcome_message = f"Run failed: {run_error}"
            elif agent_session:
                outcome_kind = "dispatched"
                outcome_message = (
                    "Opening a visible agent session for this connector. "
                    "Watch the Chat tab for commands, browser steps when needed, verification, and output."
                )
            elif body.sourceId == "social" and isinstance(composio_summary, dict):
                total_new = composio_summary.get("total_new") or 0
                total_fetched = composio_summary.get("total_fetched") or 0
                outcome_kind = "ok"
                outcome_message = f"Composio pulled {total_new} new / {total_fetched} fetched into Postgres."
            elif body.sourceId == "crm" and auth_status == "missing_secret":
                outcome_kind = "needs_operator"
                outcome_message = (
                    next_step
                    or "CRM API key not configured — add it in the CRM Integration panel, then click Run prompt again."
                )
            elif body.sourceId == "crm":
                outcome_kind = "ok" if connected else ("error" if last_error else "ok")
                outcome_message = (
                    f"Pulled {contact_count} CRM contacts / {message_count} activities into Postgres."
                    if connected
                    else (last_error or "CRM sync ran — see Sources page for details.")
                )
            elif body.sourceId == "apple-messages":
                outcome_kind = "ok"
                outcome_message = (
                    f"Apple Messages: {contact_count} contacts, {conversation_count} chats, {message_count} messages indexed."
                )
            elif body.sourceId == "xposure-pcs":
                outcome_kind = "ok" if connected else ("error" if last_error else "needs_operator")
                outcome_message = (
                    f"MLS Buyer Searches: {contact_count} buyer contacts pulled into Postgres."
                    if connected
                    else (last_error or next_step or "Xposure PCS sync ran — see Sources page for details.")
                )
            elif wired:
                outcome_kind = "ok"
                outcome_message = "Pulled inline — Postgres updated."
            else:
                outcome_kind = "dispatched"
                source_dir = view.get("sourceDir") if isinstance(view, dict) else None
                outcome_message = (
                    f"Agent setup task scaffolded at {source_dir}/tasks.jsonl. "
                    "Open /tasks or dispatch to Jimmy to build the connector."
                )

            run_result = {
                "sourceId": body.sourceId,
                "wired": wired,
                "execution": (
                    "agent_session_seed"
                    if agent_session
                    else ("server_inline" if wired else "agent_task_dispatched")
                ),
                "prompt": prompt_text,
                "outcome": {
                    "kind": outcome_kind,
                    "message": outcome_message,
                    "recordCounts": {
                        "contacts": contact_count,
                        "conversations": conversation_count,
                        "messages": message_count,
                    },
                    "lastError": last_error,
                    "authStatus": auth_status,
                    "nextOperatorStep": next_step,
                    "sourceDir": view.get("sourceDir") if isinstance(view, dict) else None,
                },
                "next_action_for_operator": (
                    "The dashboard should navigate to /chat with this prompt seeded."
                    if agent_session
                    else None if wired else (
                        f"Open {view.get('sourceDir') if isinstance(view, dict) else 'data/sources/<source-id>'}/tasks.jsonl, "
                        "or dispatch to Jimmy via the dispatch-bridge."
                    )
                ),
            }
            if isinstance(composio_summary, dict):
                refresh_summary = composio_summary
        else:
            scaffold_source(body.sourceId)

        payload: dict[str, Any] = {
            "ok": True,
            **build_source_connectors_response(include_prompts=False),
        }
        if refresh_summary is not None:
            payload["refresh"] = refresh_summary
        if run_result is not None:
            payload["run"] = run_result
        return payload
    except Exception as exc:
        _log.exception("POST /api/source-connectors failed")
        raise HTTPException(status_code=500, detail=f"Source connector update failed: {exc}")


class OutreachTemplateCreate(BaseModel):
    lane: str
    name: str
    body: str
    channel: str = "any"


class OutreachTemplateUpdate(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[str] = None
    active: Optional[bool] = None


@app.get("/api/outreach/templates")
async def list_outreach_templates(lane: Optional[str] = None):
    try:
        from elevate_cli import outreach_db

        return {"templates": outreach_db.list_templates(lane=lane)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("GET /api/outreach/templates failed")
        raise HTTPException(status_code=500, detail=f"List templates failed: {exc}")


@app.post("/api/outreach/templates")
async def create_outreach_template(body: OutreachTemplateCreate):
    try:
        from elevate_cli import outreach_db

        return {"template": outreach_db.create_template(
            lane=body.lane, name=body.name, body=body.body, channel=body.channel
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/outreach/templates failed")
        raise HTTPException(status_code=500, detail=f"Create template failed: {exc}")


@app.put("/api/outreach/templates/{template_id}")
async def update_outreach_template(template_id: str, body: OutreachTemplateUpdate):
    try:
        from elevate_cli import outreach_db

        return {"template": outreach_db.update_template(
            template_id,
            name=body.name,
            body=body.body,
            channel=body.channel,
            active=body.active,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("PUT /api/outreach/templates failed")
        raise HTTPException(status_code=500, detail=f"Update template failed: {exc}")


@app.delete("/api/outreach/templates/{template_id}")
async def delete_outreach_template(template_id: str):
    try:
        from elevate_cli import outreach_db

        ok = outreach_db.delete_template(template_id)
        return {"ok": ok}
    except Exception as exc:
        _log.exception("DELETE /api/outreach/templates failed")
        raise HTTPException(status_code=500, detail=f"Delete template failed: {exc}")


@app.get("/api/outreach/templates/overview")
async def get_outreach_overview():
    try:
        from elevate_cli import outreach_db

        return outreach_db.overview()
    except Exception as exc:
        _log.exception("GET /api/outreach/templates/overview failed")
        raise HTTPException(status_code=500, detail=f"Overview failed: {exc}")


class OutreachSuggestBody(BaseModel):
    lane: str
    channel: str = "any"
    extraBrief: Optional[str] = None


@app.post("/api/outreach/templates/suggest")
async def suggest_outreach_template(body: OutreachSuggestBody):
    try:
        from elevate_cli import template_suggester

        saved = template_suggester.suggest_and_save(
            body.lane,
            channel=body.channel,
            extra_brief=body.extraBrief,
        )
        return {"template": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/outreach/templates/suggest failed")
        raise HTTPException(status_code=500, detail=f"Suggest failed: {exc}")


@app.post("/api/outreach/templates/{template_id}/approve")
async def approve_outreach_template(template_id: str):
    try:
        from elevate_cli import outreach_db

        return {"template": outreach_db.approve_template(template_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/outreach/templates/approve failed")
        raise HTTPException(status_code=500, detail=f"Approve failed: {exc}")


@app.post("/api/outreach/templates/{template_id}/reject")
async def reject_outreach_template(template_id: str):
    try:
        from elevate_cli import outreach_db

        ok = outreach_db.reject_template(template_id)
        return {"ok": ok}
    except Exception as exc:
        _log.exception("POST /api/outreach/templates/reject failed")
        raise HTTPException(status_code=500, detail=f"Reject failed: {exc}")


class ComposioKeyBody(BaseModel):
    apiKey: str


class ComposioConnectBody(BaseModel):
    toolkitSlug: str
    redirectUrl: Optional[str] = None
    userId: Optional[str] = None


class ComposioFacebookSelectionBody(BaseModel):
    pageIds: list[str]


class ComposioCustomAuthBody(BaseModel):
    toolkitSlug: str
    credentials: dict
    authScheme: Optional[str] = None
    redirectUrl: Optional[str] = None
    userId: Optional[str] = None


# Stale-while-revalidate cache for the Composio reads the settings panel
# fires on every mount (status + connections). Each call is a blocking
# round-trip to api.composio.dev, so the panel felt sluggish on every
# visit. With SWR the panel renders instantly from the last known value
# and a background thread refreshes anything past its TTL — only a truly
# cold cache (process just booted) pays the live fetch.
_COMPOSIO_SWR: dict[str, tuple[float, Any]] = {}
_COMPOSIO_SWR_LOCK = threading.Lock()
_COMPOSIO_SWR_REFRESHING: set[str] = set()
_COMPOSIO_STATUS_TTL_SEC = 60.0
_COMPOSIO_CONNECTIONS_TTL_SEC = 30.0


def _composio_refresh_async(key: str, fetch) -> None:
    """Refresh one SWR entry on a background thread, deduped per key."""
    with _COMPOSIO_SWR_LOCK:
        if key in _COMPOSIO_SWR_REFRESHING:
            return
        _COMPOSIO_SWR_REFRESHING.add(key)

    def _run() -> None:
        try:
            value = fetch()
            with _COMPOSIO_SWR_LOCK:
                _COMPOSIO_SWR[key] = (time.monotonic(), value)
        except Exception:
            _log.debug("Composio SWR refresh failed for %s", key, exc_info=True)
        finally:
            with _COMPOSIO_SWR_LOCK:
                _COMPOSIO_SWR_REFRESHING.discard(key)

    threading.Thread(
        target=_run, daemon=True, name=f"composio-swr-{key}"
    ).start()


def _composio_cached(key: str, ttl: float, fetch):
    """Return a Composio read instantly from cache, revalidating in the
    background when stale. A cold cache blocks on the live fetch once."""
    now = time.monotonic()
    with _COMPOSIO_SWR_LOCK:
        entry = _COMPOSIO_SWR.get(key)
    if entry is not None:
        ts, value = entry
        if (now - ts) >= ttl:
            _composio_refresh_async(key, fetch)
        return value
    value = fetch()
    with _COMPOSIO_SWR_LOCK:
        _COMPOSIO_SWR[key] = (time.monotonic(), value)
    return value


def _composio_cache_invalidate() -> None:
    """Drop every cached Composio read. Call after a mutation (key set or
    cleared, account connected or deleted) so the next read is live."""
    with _COMPOSIO_SWR_LOCK:
        _COMPOSIO_SWR.clear()


def _prewarm_composio_toolkits_in_background() -> None:
    """Fire-and-forget background fetch of the full toolkit catalog.

    Called whenever ``/api/composio/status`` reports valid creds. Populates
    ``_COMPOSIO_TOOLKITS_CACHE`` so that by the time the wizard's user opens
    the Composio panel (or types a search that misses the first page) the
    full list is already on disk.
    """
    import threading
    import time

    def _warm() -> None:
        try:
            from elevate_cli import composio_client

            # Warm the connections SWR cache too, so the settings panel's
            # mount fetch is a cache hit instead of a cold round-trip.
            with _COMPOSIO_SWR_LOCK:
                has_connections = "connections" in _COMPOSIO_SWR
            if not has_connections:
                _composio_refresh_async(
                    "connections", composio_client.list_connected_accounts
                )

            cache_key = "all::::100"
            entry = _COMPOSIO_TOOLKITS_CACHE.get(cache_key)
            now = time.monotonic()
            if entry and (now - entry[0]) < _COMPOSIO_TOOLKITS_TTL_SEC:
                return
            result = composio_client.list_all_toolkits(page_size=100)
            _COMPOSIO_TOOLKITS_CACHE[cache_key] = (now, result)
        except Exception:
            _log.debug("Composio pre-warm failed", exc_info=True)

    t = threading.Thread(target=_warm, daemon=True, name="composio-prewarm")
    t.start()


@app.get("/api/composio/status")
async def composio_status():
    try:
        from elevate_cli import composio_client

        result = await asyncio.to_thread(
            _composio_cached,
            "status",
            _COMPOSIO_STATUS_TTL_SEC,
            composio_client.get_status,
        )
        # Cheap optimization: as soon as we know the key is good, schedule a
        # background fetch of the catalog. The wizard polls /status on mount
        # and on window focus, so this kicks in exactly when the user is
        # most likely to open the toolkit panel next.
        if isinstance(result, dict) and result.get("valid"):
            _prewarm_composio_toolkits_in_background()
        return result
    except Exception as exc:
        _log.exception("GET /api/composio/status failed")
        raise HTTPException(status_code=500, detail=f"Composio status failed: {exc}")


@app.post("/api/composio/key")
async def composio_set_key(body: ComposioKeyBody):
    try:
        from elevate_cli import composio_client

        result = composio_client.set_api_key(body.apiKey)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Invalid key"))
        _composio_cache_invalidate()
        return composio_client.get_status()
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/composio/key failed")
        raise HTTPException(status_code=500, detail=f"Set Composio key failed: {exc}")


@app.delete("/api/composio/key")
async def composio_clear_key():
    try:
        from elevate_cli import composio_client

        composio_client.clear_api_key()
        _composio_cache_invalidate()
        return composio_client.get_status()
    except Exception as exc:
        _log.exception("DELETE /api/composio/key failed")
        raise HTTPException(status_code=500, detail=f"Clear Composio key failed: {exc}")


@app.get("/api/composio/connections")
async def composio_connections(fresh: bool = False):
    """List connected Composio accounts.

    Served from the SWR cache for an instant settings-panel mount. Pass
    ``?fresh=1`` (the panel does this on window focus and right after a
    connect/delete) to bypass the cache and repopulate it with live data.
    """
    try:
        from elevate_cli import composio_client

        if fresh:
            result = await asyncio.to_thread(composio_client.list_connected_accounts)
            with _COMPOSIO_SWR_LOCK:
                _COMPOSIO_SWR["connections"] = (time.monotonic(), result)
            return result
        return await asyncio.to_thread(
            _composio_cached,
            "connections",
            _COMPOSIO_CONNECTIONS_TTL_SEC,
            composio_client.list_connected_accounts,
        )
    except Exception as exc:
        _log.exception("GET /api/composio/connections failed")
        raise HTTPException(status_code=500, detail=f"List Composio connections failed: {exc}")


@app.get("/api/composio/connections/all")
async def composio_connections_all(
    toolkit: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 50,
):
    """Paginated list of all connected accounts. Phase 5a: replaces single-page calls."""
    try:
        from elevate_cli import composio_client
        return composio_client.list_all_connected_accounts(
            toolkit=toolkit, page_size=page_size, max_pages=max_pages,
        )
    except Exception as exc:
        _log.exception("GET /api/composio/connections/all failed")
        raise HTTPException(status_code=500, detail=f"List all Composio connections failed: {exc}")


@app.get("/api/composio/capabilities")
async def composio_capabilities(toolkit: Optional[str] = None):
    """Return the per-toolkit send/inbound matrix for the channel picker.

    Pass ``?toolkit=<slug>`` to look up a single toolkit, otherwise the
    full matrix comes back. Unknown toolkits return an explicit
    ``unverified`` stub so the UI can render a disabled chip with a reason.
    """
    try:
        from elevate_cli import composio_client
        if toolkit:
            return composio_client.capability(toolkit)
        return composio_client.load_capability_matrix()
    except Exception as exc:
        _log.exception("GET /api/composio/capabilities failed")
        raise HTTPException(status_code=500, detail=f"Composio capabilities failed: {exc}")


# Process-level cache for the full Composio toolkit catalog. The list rarely
# changes within a single dashboard session and the all-pages walk costs 3-6
# round-trips to api.composio.dev. Cuts wizard load time roughly in half.
_COMPOSIO_TOOLKITS_CACHE: dict[str, tuple[float, Any]] = {}
_COMPOSIO_TOOLKITS_TTL_SEC = 300.0


@app.get("/api/composio/toolkits")
async def composio_toolkits(
    category: Optional[str] = None,
    all: bool = True,
    limit: int = 100,
    cursor: Optional[str] = None,
    search: Optional[str] = None,
):
    """List Composio toolkits.

    Three modes:
      - ``search`` set → single-page server-side fuzzy search (always live).
      - ``cursor`` set or ``all=false`` → single page (no cache, fast).
      - default → full catalog walk, 5-min cached per (category, limit).

    The wizard now uses cursor-paginated mode on first load so the user
    sees results in ~200ms instead of waiting on the full 3-6 page walk.
    """
    import time

    try:
        from elevate_cli import composio_client

        # Search and explicit pagination both bypass the full-catalog cache.
        # Search results are cheap and need to stay fresh; cursor walking
        # already implies the caller knows what page they want.
        if search:
            return composio_client.list_toolkits(
                category=category, limit=limit, search=search
            )
        if cursor or not all:
            return composio_client.list_toolkits(
                category=category, limit=limit, cursor=cursor
            )

        cache_key = f"all::{category or ''}::{limit}"
        entry = _COMPOSIO_TOOLKITS_CACHE.get(cache_key)
        now = time.monotonic()
        if entry and (now - entry[0]) < _COMPOSIO_TOOLKITS_TTL_SEC:
            return entry[1]
        result = composio_client.list_all_toolkits(category=category, page_size=limit)
        _COMPOSIO_TOOLKITS_CACHE[cache_key] = (now, result)
        return result
    except Exception as exc:
        _log.exception("GET /api/composio/toolkits failed")
        raise HTTPException(status_code=500, detail=f"List Composio toolkits failed: {exc}")


@app.post("/api/composio/connect")
async def composio_connect(body: ComposioConnectBody):
    try:
        from elevate_cli import composio_client

        return composio_client.initiate_connection(
            body.toolkitSlug,
            redirect_url=body.redirectUrl,
            user_id=body.userId,
        )
    except Exception as exc:
        _log.exception("POST /api/composio/connect failed")
        raise HTTPException(status_code=500, detail=f"Composio connect failed: {exc}")


@app.get("/api/composio/toolkits/{slug}")
async def composio_toolkit_details(slug: str):
    """Return full toolkit metadata, including required custom-auth fields.

    The dashboard reads ``composio_managed_auth_schemes`` (empty → custom
    creds required) and ``auth_config_details[*].fields.auth_config_creation``
    to render a dynamic credentials form.
    """
    try:
        from elevate_cli import composio_client

        return composio_client.get_toolkit_details(slug)
    except Exception as exc:
        _log.exception("GET /api/composio/toolkits/{slug} failed")
        raise HTTPException(status_code=500, detail=f"Toolkit details failed: {exc}")


@app.post("/api/composio/auth-configs/custom")
async def composio_create_custom_auth(body: ComposioCustomAuthBody):
    """Create a ``use_custom_auth`` config and immediately initiate a connect.

    Single round-trip from the UI: user submits client_id + client_secret
    (and any optional fields like scopes), we create the auth_config with
    those creds, then kick off the OAuth handshake using the new id and
    return the redirect_url so the UI can open the consent screen.
    """
    try:
        from elevate_cli import composio_client

        created = composio_client.create_custom_auth_config(
            body.toolkitSlug,
            body.credentials or {},
            auth_scheme=body.authScheme,
        )
        if not created.get("ok"):
            return created
        data = created.get("data") or {}
        ac = data.get("auth_config") if isinstance(data, dict) else None
        ac_id = (ac or {}).get("id") if isinstance(ac, dict) else None
        if not ac_id:
            return {"ok": False, "error": "auth_config created but no id returned", "raw": created}
        link = composio_client.initiate_connection(
            body.toolkitSlug,
            redirect_url=body.redirectUrl,
            user_id=body.userId,
            auth_config_id=ac_id,
        )
        if isinstance(link, dict) and isinstance(link.get("data"), dict):
            link["data"].setdefault("auth_config_id", ac_id)
            link["data"].setdefault("auth_config_created", True)
        return link
    except Exception as exc:
        _log.exception("POST /api/composio/auth-configs/custom failed")
        raise HTTPException(status_code=500, detail=f"Custom auth config failed: {exc}")


@app.delete("/api/composio/connections/{account_id}")
async def composio_delete_connection(account_id: str):
    try:
        from elevate_cli import composio_client

        result = composio_client.delete_connected_account(account_id)
        _composio_cache_invalidate()
        return result
    except Exception as exc:
        _log.exception("DELETE /api/composio/connections failed")
        raise HTTPException(status_code=500, detail=f"Delete Composio connection failed: {exc}")


@app.get("/api/composio/facebook/pages")
async def composio_facebook_pages():
    """List FB pages from connected Facebook accounts plus current selection.

    Used by the page-picker on the source-connector card so the user can
    choose which pages surface on the /leads board. Selection persists
    independent of MCP — the Composio connection itself stays full-scope.
    """
    try:
        from elevate_cli import composio_inbound

        return composio_inbound.list_facebook_pages_for_picker()
    except Exception as exc:
        _log.exception("GET /api/composio/facebook/pages failed")
        raise HTTPException(status_code=500, detail=f"Composio FB pages failed: {exc}")


@app.put("/api/composio/facebook/pages")
async def composio_facebook_set_pages(body: ComposioFacebookSelectionBody):
    try:
        from elevate_cli import composio_inbound

        return composio_inbound.set_facebook_page_selection(body.pageIds or [])
    except Exception as exc:
        _log.exception("PUT /api/composio/facebook/pages failed")
        raise HTTPException(status_code=500, detail=f"Composio FB selection save failed: {exc}")


@app.post("/api/composio/inbound/pull")
async def composio_inbound_pull():
    """Manual trigger for the composio inbound puller.

    The 10-min cron tick runs ``pull_all_supported()`` automatically; this
    endpoint exposes the same call so the dashboard Refresh button can
    surface "actually fetched something new" instead of just re-reading the
    last tick's JSONL files. Returns the same summary shape as the cron tick.
    """
    try:
        from elevate_cli import composio_inbound

        return composio_inbound.pull_all_supported()
    except Exception as exc:
        _log.exception("POST /api/composio/inbound/pull failed")
        raise HTTPException(status_code=500, detail=f"Composio inbound pull failed: {exc}")


# ---------------------------------------------------------------------------
# Ayrshare publisher routes
# ---------------------------------------------------------------------------


class AyrshareKeyBody(BaseModel):
    apiKey: str


@app.get("/api/ayrshare/status")
async def ayrshare_status():
    try:
        from elevate_cli import ayrshare_client

        return ayrshare_client.get_status()
    except Exception as exc:
        _log.exception("GET /api/ayrshare/status failed")
        raise HTTPException(status_code=500, detail=f"Ayrshare status failed: {exc}")


@app.post("/api/ayrshare/key")
async def ayrshare_set_key(body: AyrshareKeyBody):
    try:
        from elevate_cli import ayrshare_client

        result = ayrshare_client.set_api_key(body.apiKey)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Invalid key"))
        return ayrshare_client.get_status()
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("POST /api/ayrshare/key failed")
        raise HTTPException(status_code=500, detail=f"Set Ayrshare key failed: {exc}")


@app.delete("/api/ayrshare/key")
async def ayrshare_clear_key():
    try:
        from elevate_cli import ayrshare_client

        ayrshare_client.clear_api_key()
        return ayrshare_client.get_status()
    except Exception as exc:
        _log.exception("DELETE /api/ayrshare/key failed")
        raise HTTPException(status_code=500, detail=f"Clear Ayrshare key failed: {exc}")


@app.get("/api/ayrshare/profiles")
async def ayrshare_profiles():
    """List connected social profiles (which platforms have OAuth tokens stored in Ayrshare)."""
    try:
        from elevate_cli import ayrshare_client

        return ayrshare_client.profiles()
    except Exception as exc:
        _log.exception("GET /api/ayrshare/profiles failed")
        raise HTTPException(status_code=500, detail=f"Ayrshare profiles failed: {exc}")


@app.get("/api/ayrshare/scheduled")
async def ayrshare_scheduled():
    """List currently scheduled (not yet posted) posts."""
    try:
        from elevate_cli import ayrshare_client

        return ayrshare_client.list_scheduled()
    except Exception as exc:
        _log.exception("GET /api/ayrshare/scheduled failed")
        raise HTTPException(status_code=500, detail=f"Ayrshare scheduled failed: {exc}")


@app.get("/api/ayrshare/history")
async def ayrshare_history(last_records: int = 100, last_days: Optional[int] = None):
    """List past posts with engagement metrics."""
    try:
        from elevate_cli import ayrshare_client

        return ayrshare_client.history(last_records=last_records, last_days=last_days)
    except Exception as exc:
        _log.exception("GET /api/ayrshare/history failed")
        raise HTTPException(status_code=500, detail=f"Ayrshare history failed: {exc}")


# ---------------------------------------------------------------------------
# Social content engine routes — backs the /social-media page
# ---------------------------------------------------------------------------


def _social_snapshot_path() -> Path:
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    workspace = (
        os.environ.get("ELEVATE_WORKSPACE_ID")
        or os.environ.get("ELEVATE_WORKSPACE")
        or "default"
    )
    return elevate_home / "state" / workspace / "social-snapshot.json"


def _social_metrics_path() -> Path:
    return _social_snapshot_path().parent / "social-metrics.jsonl"


def _social_tasks_path() -> Path:
    try:
        from elevate_cli.source_connectors import get_source_root_info
        info = get_source_root_info()
        root = Path(info.get("sourceRoot") or "")
        if root.parts:
            return root / "social" / "tasks.jsonl"
    except Exception:
        pass
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    return elevate_home / "tools" / "data" / "sources" / "social" / "tasks.jsonl"


def _read_social_tasks() -> list[dict]:
    path = _social_tasks_path()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_social_tasks(records: list[dict]) -> None:
    path = _social_tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class SocialIdeaActionBody(BaseModel):
    action: str  # approve | reject | edit
    notes: Optional[str] = None
    edit: Optional[dict] = None


@app.get("/api/social/snapshot")
async def social_snapshot():
    """Read the latest weekly snapshot built by aggregate.py."""
    path = _social_snapshot_path()
    if not path.exists():
        return {
            "exists": False,
            "snapshot_path": str(path),
            "message": "No snapshot yet. Run the social-content-engine skill or the aggregator script.",
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.exception("GET /api/social/snapshot failed")
        raise HTTPException(status_code=500, detail=f"Snapshot read failed: {exc}")


@app.get("/api/social/ideas")
async def social_ideas(status: Optional[str] = None):
    """List social post ideas (defaults to open/pending approval)."""
    try:
        all_tasks = _read_social_tasks()
        ideas = [t for t in all_tasks if str(t.get("task_type") or "").lower() == "social_post_idea"]
        if status:
            ideas = [t for t in ideas if str(t.get("status") or "").lower() == status.lower()]
        else:
            ideas = [t for t in ideas if str(t.get("status") or "").lower() in ("open", "pending_approval")]
        ideas.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        return {"items": ideas, "count": len(ideas)}
    except Exception as exc:
        _log.exception("GET /api/social/ideas failed")
        raise HTTPException(status_code=500, detail=f"Idea read failed: {exc}")


@app.post("/api/social/ideas/{record_id}/action")
async def social_idea_action(record_id: str, body: SocialIdeaActionBody):
    """Approve / reject / edit a social post idea. Updates tasks.jsonl in place."""
    action = (body.action or "").lower().strip()
    if action not in {"approve", "reject", "edit"}:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    try:
        records = _read_social_tasks()
    except Exception as exc:
        _log.exception("POST /api/social/ideas action read failed")
        raise HTTPException(status_code=500, detail=f"Read failed: {exc}")

    from datetime import datetime, timezone
    found = False
    for r in records:
        if str(r.get("source_record_id") or "") != record_id:
            continue
        if str(r.get("task_type") or "").lower() != "social_post_idea":
            continue
        found = True
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        r["last_action_at"] = ts
        if body.notes:
            r.setdefault("notes", []).append({"ts": ts, "text": body.notes})
        if action == "approve":
            r["status"] = "approved"
            r["approval_required"] = False
        elif action == "reject":
            r["status"] = "rejected"
            r["approval_required"] = False
        elif action == "edit" and body.edit:
            for k in ("hook", "concept", "outline", "best_post_time", "platform", "format", "target_audience"):
                if k in body.edit:
                    r[k] = body.edit[k]
        break

    if not found:
        raise HTTPException(status_code=404, detail=f"Idea {record_id} not found")

    try:
        _write_social_tasks(records)
    except Exception as exc:
        _log.exception("POST /api/social/ideas action write failed")
        raise HTTPException(status_code=500, detail=f"Write failed: {exc}")

    return {"ok": True, "record_id": record_id, "action": action}


@app.get("/api/social/recent-posts")
async def social_recent_posts(limit: int = 30):
    """Return the latest fetched metric row per (platform, post_id), newest first."""
    path = _social_metrics_path()
    if not path.exists():
        return {"items": [], "count": 0, "snapshot_path": str(path)}
    by_key: dict[tuple[str, str], dict] = {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                platform = row.get("platform")
                post_id = row.get("post_id")
                if not platform or not post_id:
                    continue
                if str(row.get("media_type") or "").upper() == "ACCOUNT":
                    continue
                key = (platform, post_id)
                existing = by_key.get(key)
                if not existing:
                    by_key[key] = row
                    continue
                # Merge: prefer the newest fetched_at for metrics/captions,
                # but preserve the `raw` payload from whichever row has it
                # (the fetcher only writes raw on first_seen).
                if (row.get("fetched_at") or "") > (existing.get("fetched_at") or ""):
                    preserved_raw = existing.get("raw") or row.get("raw")
                    by_key[key] = row
                    if preserved_raw and not by_key[key].get("raw"):
                        by_key[key]["raw"] = preserved_raw
                else:
                    if row.get("raw") and not existing.get("raw"):
                        existing["raw"] = row.get("raw")
    except Exception as exc:
        _log.exception("GET /api/social/recent-posts failed")
        raise HTTPException(status_code=500, detail=f"Read failed: {exc}")

    items = list(by_key.values())
    items.sort(key=lambda x: x.get("posted_at") or x.get("fetched_at") or "", reverse=True)
    items = items[: max(1, min(limit, 1000))]
    return {"items": items, "count": len(items)}


def _load_social_fetcher(module_name: str):
    """Import a fetcher script from the installed social-content-engine skill."""
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    skill_root = elevate_home / "skills" / "social-media" / "social-content-engine" / "scripts"
    script_path = skill_root / f"{module_name}.py"
    if not script_path.exists():
        # Fall back to the source tree (dev install)
        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "skills" / "social-content-engine" / "scripts" / f"{module_name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Fetcher script not found: {module_name}.py")
    spec = importlib.util.spec_from_file_location(f"_social_{module_name}", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load {module_name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@app.post("/api/social/refresh")
async def social_refresh(platform: Optional[str] = None, lookback_days: int = 730, max_posts: int = 200):
    """Pull fresh metrics from connected social platforms via Composio.

    `platform` may be one of `instagram`, `facebook`, `youtube`, or omitted to
    refresh all. Runs the fetchers in a thread to avoid blocking the event loop.
    """
    requested = (platform or "").strip().lower()
    targets = [requested] if requested else ["instagram", "facebook", "youtube"]
    valid = {"instagram", "facebook", "youtube"}
    targets = [t for t in targets if t in valid]
    if not targets:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")

    module_map = {
        "instagram": "instagram_insights",
        "facebook": "facebook_insights",
        "youtube": "youtube_analytics",
    }

    results: dict[str, Any] = {}

    def _run_one(p: str) -> dict:
        try:
            mod = _load_social_fetcher(module_map[p])
            return mod.fetch(lookback_days=lookback_days, max_posts=max_posts)
        except Exception as exc:
            _log.exception("social refresh %s failed", p)
            return {"platform": p, "status": "error", "error": str(exc)}

    for p in targets:
        results[p] = await asyncio.to_thread(_run_one, p)

    return {"ok": True, "results": results}


@app.get("/api/integrations")
async def get_integrations():
    try:
        from elevate_cli.source_connectors import get_integration_settings

        return get_integration_settings()
    except Exception as exc:
        _log.exception("GET /api/integrations failed")
        raise HTTPException(status_code=500, detail=f"Integration settings failed: {exc}")


@app.put("/api/integrations")
async def update_integrations(body: IntegrationSettingsUpdate):
    try:
        from elevate_cli.source_connectors import save_integration_settings

        return save_integration_settings(body.dict())
    except Exception as exc:
        _log.exception("PUT /api/integrations failed")
        raise HTTPException(status_code=500, detail=f"Integration settings save failed: {exc}")


@app.post("/api/integrations")
async def test_integrations(body: IntegrationSettingsUpdate):
    if body.action != "test":
        raise HTTPException(status_code=400, detail="Unsupported integration action")
    try:
        from elevate_cli.source_connectors import test_crm_connection

        return test_crm_connection(body.dict())
    except Exception as exc:
        _log.exception("POST /api/integrations failed")
        raise HTTPException(status_code=500, detail=f"Integration test failed: {exc}")


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


class SkillToggle(BaseModel):
    name: str
    enabled: bool


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from elevate_cli.skills_config import get_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)
    for s in skills:
        s["enabled"] = s["name"] not in disabled
    return skills


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from elevate_cli.skills_config import get_disabled_skills, save_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.get("/api/skills/{name}/steps")
async def get_skill_steps(name: str):
    """Return the `steps:` list declared in a skill's frontmatter, or [].

    Used by the cron form on `/leads` to preview which steps will run when
    a skill-bound cron job fires. Tier names only — concrete model resolves
    at run time via `tier_resolver` against the user's harness config.
    """
    import json
    from tools.skills_tool import skill_view
    from elevate_cli.skill_steps import parse_steps_from_text

    payload = json.loads(skill_view(name))
    if not payload.get("success"):
        return {"name": name, "steps": [], "error": payload.get("error", "skill not found")}

    content = str(payload.get("content") or "")
    steps = parse_steps_from_text(content, source=name)
    return {"name": name, "steps": steps}


def _resolve_skill_dir(name: str):
    """Locate the on-disk directory for *name*. Returns Path or None.

    Mirrors the search order used by tools.skills_tool.skill_view but only
    returns the directory — callers handle file reads / tree walks.
    """
    from pathlib import Path
    from tools.skills_tool import SKILLS_DIR, _EXCLUDED_SKILL_DIRS
    from agent.skill_utils import get_external_skills_dirs, iter_skill_index_files

    candidates = []
    if SKILLS_DIR.exists():
        candidates.append(SKILLS_DIR)
    candidates.extend(get_external_skills_dirs())

    for search_dir in candidates:
        direct = search_dir / name
        if direct.is_dir() and (direct / "SKILL.md").exists():
            return direct

    for search_dir in candidates:
        for skill_md in iter_skill_index_files(search_dir, "SKILL.md"):
            if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
                continue
            if skill_md.parent.name == name:
                return skill_md.parent
    return None


def _walk_skill_tree(skill_dir, max_depth: int = 4):
    """Return a nested list of {name, type, path, children?} for the skill dir.

    `path` is relative to the skill directory and is what callers pass to
    /api/skills/{name}/file. SKILL.md always sorts first; folders next;
    other files last (each group sorted alphabetically).
    """
    from tools.skills_tool import _EXCLUDED_SKILL_DIRS

    def walk(dir_path, rel_prefix: str, depth: int):
        if depth > max_depth:
            return []
        entries = []
        try:
            children = list(dir_path.iterdir())
        except (PermissionError, OSError):
            return []
        files = []
        folders = []
        for child in children:
            if child.name in _EXCLUDED_SKILL_DIRS or child.name.startswith("."):
                continue
            rel = f"{rel_prefix}{child.name}" if rel_prefix else child.name
            if child.is_dir():
                folders.append((child.name, rel, child))
            else:
                files.append((child.name, rel))

        skill_md_entry = None
        other_files = []
        for fname, rel in sorted(files, key=lambda x: x[0].lower()):
            entry = {"name": fname, "type": "file", "path": rel}
            if fname == "SKILL.md":
                skill_md_entry = entry
            else:
                other_files.append(entry)
        if skill_md_entry:
            entries.append(skill_md_entry)

        for fname, rel, child_dir in sorted(folders, key=lambda x: x[0].lower()):
            entries.append({
                "name": fname,
                "type": "dir",
                "path": rel,
                "children": walk(child_dir, f"{rel}/", depth + 1),
            })

        entries.extend(other_files)
        return entries

    return walk(skill_dir, "", 0)


@app.get("/api/skills/{name}/tree")
async def get_skill_tree(name: str):
    """Return the folder/file tree for a skill, used by the Skills page rail."""
    skill_dir = _resolve_skill_dir(name)
    if skill_dir is None:
        return {"name": name, "tree": [], "error": "skill not found"}
    return {
        "name": name,
        "root": skill_dir.name,
        "tree": _walk_skill_tree(skill_dir),
    }


@app.get("/api/skills/{name}/file")
async def get_skill_file(name: str, path: str = ""):
    """Return the contents of a file inside a skill directory.

    `path` is relative to the skill root (e.g. ``SKILL.md`` or
    ``references/api.md``). Empty path defaults to SKILL.md.
    Binary files return ``{"binary": true, "size": N}`` instead of content.
    """
    from tools.path_security import has_traversal_component, validate_within_dir

    skill_dir = _resolve_skill_dir(name)
    if skill_dir is None:
        return {"name": name, "path": path, "error": "skill not found"}

    rel = path.strip().lstrip("/") or "SKILL.md"
    if has_traversal_component(rel):
        return {"name": name, "path": rel, "error": "invalid path"}

    target = skill_dir / rel
    err = validate_within_dir(target, skill_dir)
    if err:
        return {"name": name, "path": rel, "error": err}
    if not target.exists() or not target.is_file():
        return {"name": name, "path": rel, "error": "file not found"}

    try:
        size = target.stat().st_size
    except OSError:
        size = 0

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {
            "name": name,
            "path": rel,
            "binary": True,
            "size": size,
        }

    return {
        "name": name,
        "path": rel,
        "size": size,
        "content": content,
    }


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from elevate_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name, "label": label, "description": desc,
            "enabled": is_enabled,
            "available": is_enabled,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        })
    return result


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
        save_config(parsed)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
def get_usage_analytics(days: int = 30):
    from elevate_state import SessionDB
    from agent.insights import InsightsEngine

    cutoff = time.time() - (days * 86400) if days > 0 else None
    where_sql = "WHERE started_at > ?" if cutoff is not None else ""
    params = (cutoff,) if cutoff is not None else ()
    try:
        from elevate_cli.data.connection import connect

        with connect() as conn:
            cur = conn.execute(f"""
                SELECT to_timestamp(started_at)::date::text as day,
                       COALESCE(SUM(input_tokens), 0) as input_tokens,
                       COALESCE(SUM(output_tokens), 0) as output_tokens,
                       COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                       COALESCE(SUM(reasoning_tokens), 0) as reasoning_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                       COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                       COUNT(*) as sessions,
                       COALESCE(SUM(api_call_count), 0) as api_calls
                FROM chat_sessions {where_sql}
                GROUP BY 1 ORDER BY 1
            """, params)
            daily = [dict(r) for r in cur.fetchall()]

            model_where = (
                f"{where_sql} AND model IS NOT NULL"
                if where_sql
                else "WHERE model IS NOT NULL"
            )
            cur2 = conn.execute(f"""
                SELECT model,
                       COALESCE(SUM(input_tokens), 0) as input_tokens,
                       COALESCE(SUM(output_tokens), 0) as output_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                       COUNT(*) as sessions,
                       COALESCE(SUM(api_call_count), 0) as api_calls
                FROM chat_sessions {model_where}
                GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
            """, params)
            by_model = [dict(r) for r in cur2.fetchall()]

            cur3 = conn.execute(f"""
                SELECT COALESCE(SUM(input_tokens), 0) as total_input,
                       COALESCE(SUM(output_tokens), 0) as total_output,
                       COALESCE(SUM(cache_read_tokens), 0) as total_cache_read,
                       COALESCE(SUM(reasoning_tokens), 0) as total_reasoning,
                       COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                       COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                       COUNT(*) as total_sessions,
                       COALESCE(SUM(api_call_count), 0) as total_api_calls
                FROM chat_sessions {where_sql}
            """, params)
            totals = dict(cur3.fetchone())

        try:
            db = _get_session_db()
            try:
                insights_report = InsightsEngine(db).generate(days=days if days > 0 else 3650)
                skills = insights_report.get("skills")
            finally:
                db.close()
        except Exception:
            skills = None
        if not isinstance(skills, dict):
            skills = {
                "summary": {
                    "total_skill_loads": 0,
                    "total_skill_edits": 0,
                    "total_skill_actions": 0,
                    "distinct_skills_used": 0,
                },
                "top_skills": [],
            }
        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
            "source": "postgres",
        }
    except Exception:
        _log.debug("analytics usage PG read failed, falling back to SQLite", exc_info=True)

    db = _get_session_db()
    try:
        cutoff = time.time() - (days * 86400) if days > 0 else 0
        cur = db._conn.execute("""
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """, (cutoff,))
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute("""
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute("""
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ?
        """, (cutoff,))
        totals = dict(cur3.fetchone())
        insights_report = InsightsEngine(db).generate(days=days)
        skills = insights_report.get("skills", {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        })

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
            "source": "sqlite",
        }
    finally:
        db.close()


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


# ---------------------------------------------------------------------------
# Dashboard theme endpoints
# ---------------------------------------------------------------------------

# Built-in dashboard themes — label + description only.  The actual color
# definitions live in the frontend (web/src/themes/presets.ts).
_BUILTIN_DASHBOARD_THEMES = [
    {"name": "dark",  "label": "Dark",  "description": "Deep blue-black workspace for focused agent work"},
    {"name": "light", "label": "Light", "description": "Bright workspace with crisp blue agent controls"},
]

_DASHBOARD_THEME_NAMES = {t["name"] for t in _BUILTIN_DASHBOARD_THEMES}
_DASHBOARD_THEME_ALIASES = {
    "cyberpunk": "dark",
    "default": "dark",
    "ember": "dark",
    "midnight": "dark",
    "mono": "dark",
    "rose": "dark",
}


def _normalise_dashboard_theme_name(name: Any) -> str:
    if isinstance(name, str):
        if name in _DASHBOARD_THEME_NAMES:
            return name
        if name in _DASHBOARD_THEME_ALIASES:
            return _DASHBOARD_THEME_ALIASES[name]
    return "dark"


def _parse_theme_layer(value: Any, default_hex: str, default_alpha: float = 1.0) -> Optional[Dict[str, Any]]:
    """Normalise a theme layer spec from YAML into `{hex, alpha}` form.

    Accepts shorthand (a bare hex string) or full dict form.  Returns
    ``None`` on garbage input so the caller can fall back to a built-in
    default rather than blowing up.
    """
    if value is None:
        return {"hex": default_hex, "alpha": default_alpha}
    if isinstance(value, str):
        return {"hex": value, "alpha": default_alpha}
    if isinstance(value, dict):
        hex_val = value.get("hex", default_hex)
        alpha_val = value.get("alpha", default_alpha)
        if not isinstance(hex_val, str):
            return None
        try:
            alpha_f = float(alpha_val)
        except (TypeError, ValueError):
            alpha_f = default_alpha
        return {"hex": hex_val, "alpha": max(0.0, min(1.0, alpha_f))}
    return None


_THEME_DEFAULT_TYPOGRAPHY: Dict[str, str] = {
    "fontSans": 'Aptos, "Avenir Next", "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
    "fontMono": 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
    "baseSize": "15px",
    "lineHeight": "1.55",
    "letterSpacing": "0",
}

_THEME_DEFAULT_LAYOUT: Dict[str, str] = {
    "radius": "0.5rem",
    "density": "comfortable",
}

_THEME_OVERRIDE_KEYS = {
    "card", "cardForeground", "popover", "popoverForeground",
    "primary", "primaryForeground", "secondary", "secondaryForeground",
    "muted", "mutedForeground", "accent", "accentForeground",
    "destructive", "destructiveForeground", "success", "warning",
    "border", "input", "ring",
}

# Well-known named asset slots themes can populate.  Any other keys under
# ``assets.custom`` are exposed as ``--theme-asset-custom-<key>`` CSS vars
# for plugin/shell use.
_THEME_NAMED_ASSET_KEYS = {"bg", "hero", "logo", "crest", "sidebar", "header"}

# Component-style buckets themes can override.  The value under each bucket
# is a mapping from camelCase property name to CSS string; each pair emits
# ``--component-<bucket>-<kebab-property>`` on :root.  The frontend's shell
# components (Card, App header, Backdrop, etc.) consume these vars so themes
# can restyle chrome (clip-path, border-image, segmented progress, etc.)
# without shipping their own CSS.
_THEME_COMPONENT_BUCKETS = {
    "card", "header", "footer", "sidebar", "tab",
    "progress", "badge", "backdrop", "page",
}

_THEME_LAYOUT_VARIANTS = {"standard", "cockpit", "tiled"}

# Cap on customCSS length so a malformed/oversized theme YAML can't blow up
# the response payload or the <style> tag.  32 KiB is plenty for every
# practical reskin (the Strike Freedom demo is ~2 KiB).
_THEME_CUSTOM_CSS_MAX = 32 * 1024


def _normalise_theme_definition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a user theme YAML into the wire format `ThemeProvider`
    expects.  Returns ``None`` if the theme is unusable.

    Accepts both the full schema (palette/typography/layout) and a loose
    form with bare hex strings, so hand-written YAMLs stay friendly.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    # Palette
    palette_src = data.get("palette", {}) if isinstance(data.get("palette"), dict) else {}
    # Allow top-level `colors.background` as a shorthand too.
    colors_src = data.get("colors", {}) if isinstance(data.get("colors"), dict) else {}

    def _layer(key: str, default_hex: str, default_alpha: float = 1.0) -> Dict[str, Any]:
        spec = palette_src.get(key, colors_src.get(key))
        parsed = _parse_theme_layer(spec, default_hex, default_alpha)
        return parsed if parsed is not None else {"hex": default_hex, "alpha": default_alpha}

    palette = {
        "background": _layer("background", "#07182f", 1.0),
        "midground": _layer("midground", "#e7f0ff", 1.0),
        "foreground": _layer("foreground", "#ffffff", 0.0),
        "warmGlow": palette_src.get("warmGlow") or data.get("warmGlow") or "rgba(76, 141, 255, 0.34)",
        "noiseOpacity": 1.0,
    }
    raw_noise = palette_src.get("noiseOpacity", data.get("noiseOpacity"))
    try:
        palette["noiseOpacity"] = float(raw_noise) if raw_noise is not None else 1.0
    except (TypeError, ValueError):
        palette["noiseOpacity"] = 1.0

    # Typography
    typo_src = data.get("typography", {}) if isinstance(data.get("typography"), dict) else {}
    typography = dict(_THEME_DEFAULT_TYPOGRAPHY)
    for key in ("fontSans", "fontMono", "fontDisplay", "fontUrl", "baseSize", "lineHeight", "letterSpacing"):
        val = typo_src.get(key)
        if isinstance(val, str) and val.strip():
            typography[key] = val

    # Layout
    layout_src = data.get("layout", {}) if isinstance(data.get("layout"), dict) else {}
    layout = dict(_THEME_DEFAULT_LAYOUT)
    radius = layout_src.get("radius")
    if isinstance(radius, str) and radius.strip():
        layout["radius"] = radius
    density = layout_src.get("density")
    if isinstance(density, str) and density in ("compact", "comfortable", "spacious"):
        layout["density"] = density

    # Color overrides — keep only valid keys with string values.
    overrides_src = data.get("colorOverrides", {})
    color_overrides: Dict[str, str] = {}
    if isinstance(overrides_src, dict):
        for key, val in overrides_src.items():
            if key in _THEME_OVERRIDE_KEYS and isinstance(val, str) and val.strip():
                color_overrides[key] = val

    # Assets — named slots + arbitrary user-defined keys.  Values must be
    # strings (URLs or CSS ``url(...)``/``linear-gradient(...)`` expressions).
    # We don't fetch remote assets here; the frontend just injects them as
    # CSS vars.  Empty values are dropped so a theme can explicitly clear a
    # slot by setting ``hero: ""``.
    assets_out: Dict[str, Any] = {}
    assets_src = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    for key in _THEME_NAMED_ASSET_KEYS:
        val = assets_src.get(key)
        if isinstance(val, str) and val.strip():
            assets_out[key] = val
    custom_assets_src = assets_src.get("custom")
    if isinstance(custom_assets_src, dict):
        custom_assets: Dict[str, str] = {}
        for key, val in custom_assets_src.items():
            if (
                isinstance(key, str)
                and key.replace("-", "").replace("_", "").isalnum()
                and isinstance(val, str)
                and val.strip()
            ):
                custom_assets[key] = val
        if custom_assets:
            assets_out["custom"] = custom_assets

    # Custom CSS — raw CSS text the frontend injects as a scoped <style>
    # tag on theme apply.  Clipped to _THEME_CUSTOM_CSS_MAX to keep the
    # payload bounded.  We intentionally do NOT parse/sanitise the CSS
    # here — the dashboard is localhost-only and themes are user-authored
    # YAML in ~/.elevate/, same trust level as the config file itself.
    custom_css_val = data.get("customCSS")
    custom_css: Optional[str] = None
    if isinstance(custom_css_val, str) and custom_css_val.strip():
        custom_css = custom_css_val[:_THEME_CUSTOM_CSS_MAX]

    # Component style overrides — per-bucket dicts of camelCase CSS
    # property -> CSS string.  The frontend converts these into CSS vars
    # that shell components (Card, App header, Backdrop) consume.
    component_styles_src = data.get("componentStyles", {})
    component_styles: Dict[str, Dict[str, str]] = {}
    if isinstance(component_styles_src, dict):
        for bucket, props in component_styles_src.items():
            if bucket not in _THEME_COMPONENT_BUCKETS or not isinstance(props, dict):
                continue
            clean: Dict[str, str] = {}
            for prop, value in props.items():
                if (
                    isinstance(prop, str)
                    and prop.replace("-", "").replace("_", "").isalnum()
                    and isinstance(value, (str, int, float))
                    and str(value).strip()
                ):
                    clean[prop] = str(value)
            if clean:
                component_styles[bucket] = clean

    layout_variant_src = data.get("layoutVariant")
    layout_variant = (
        layout_variant_src
        if isinstance(layout_variant_src, str) and layout_variant_src in _THEME_LAYOUT_VARIANTS
        else "standard"
    )

    result: Dict[str, Any] = {
        "name": name,
        "label": data.get("label") or name,
        "description": data.get("description", ""),
        "palette": palette,
        "typography": typography,
        "layout": layout,
        "layoutVariant": layout_variant,
    }
    if color_overrides:
        result["colorOverrides"] = color_overrides
    if assets_out:
        result["assets"] = assets_out
    if custom_css is not None:
        result["customCSS"] = custom_css
    if component_styles:
        result["componentStyles"] = component_styles
    return result


def _discover_user_themes() -> list:
    """Scan ~/.elevate/dashboard-themes/*.yaml for user-created themes.

    Returns a list of fully-normalised theme definitions ready to ship
    to the frontend, so the client can apply them without a secondary
    round-trip or a built-in stub.
    """
    themes_dir = get_elevate_home() / "dashboard-themes"
    if not themes_dir.is_dir():
        return []
    result = []
    for f in sorted(themes_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalised = _normalise_theme_definition(data)
        if normalised is not None:
            result.append(normalised)
    return result


@app.get("/api/dashboard/themes")
async def get_dashboard_themes():
    """Return available themes and the currently active one.

    Elevate intentionally exposes only the product light/dark pair here. Older
    theme config names are normalized to dark so stale local config cannot
    bring back removed textured skins.
    """
    config = load_config()
    active = _normalise_dashboard_theme_name(config.get("dashboard", {}).get("theme", "dark"))
    themes = []
    for t in _BUILTIN_DASHBOARD_THEMES:
        themes.append(t)
    return {"themes": themes, "active": active}


class ThemeSetBody(BaseModel):
    name: str


@app.put("/api/dashboard/theme")
async def set_dashboard_theme(body: ThemeSetBody):
    """Set the active dashboard theme (persists to config.yaml)."""
    config = load_config()
    if "dashboard" not in config:
        config["dashboard"] = {}
    config["dashboard"]["theme"] = _normalise_dashboard_theme_name(body.name)
    save_config(config)
    return {"ok": True, "theme": config["dashboard"]["theme"]}


# ---------------------------------------------------------------------------
# Dashboard plugin system
# ---------------------------------------------------------------------------

def _discover_dashboard_plugins() -> list:
    """Scan plugins/*/dashboard/manifest.json for dashboard extensions.

    Checks three plugin sources (same as elevate_cli.plugins):
    1. User plugins:    ~/.elevate/plugins/<name>/dashboard/manifest.json
    2. Bundled plugins: <repo>/plugins/<name>/dashboard/manifest.json  (memory/, etc.)
    3. Project plugins: ./.elevate/plugins/  (only if ELEVATE_ENABLE_PROJECT_PLUGINS)
    """
    plugins = []
    seen_names: set = set()

    search_dirs = [
        (get_elevate_home() / "plugins", "user"),
        (PROJECT_ROOT / "plugins" / "memory", "bundled"),
        (PROJECT_ROOT / "plugins", "bundled"),
    ]
    if os.environ.get("ELEVATE_ENABLE_PROJECT_PLUGINS"):
        search_dirs.append((Path.cwd() / ".elevate" / "plugins", "project"))

    for plugins_root, source in search_dirs:
        if not plugins_root.is_dir():
            continue
        for child in sorted(plugins_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "dashboard" / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                name = data.get("name", child.name)
                if name in seen_names:
                    continue
                seen_names.add(name)
                # Tab options: ``path`` + ``position`` for a new tab, optional
                # ``override`` to replace a built-in route, and ``hidden`` to
                # register the plugin component/slots without adding a tab
                # (useful for slot-only plugins like a header-crest injector).
                raw_tab = data.get("tab", {}) if isinstance(data.get("tab"), dict) else {}
                tab_info = {
                    "path": raw_tab.get("path", f"/{name}"),
                    "position": raw_tab.get("position", "end"),
                }
                override_path = raw_tab.get("override")
                if isinstance(override_path, str) and override_path.startswith("/"):
                    tab_info["override"] = override_path
                if bool(raw_tab.get("hidden")):
                    tab_info["hidden"] = True
                # Slots: list of named slot locations this plugin populates.
                # The frontend exposes ``registerSlot(pluginName, slotName, Component)``
                # on window; plugins with non-empty slots call it from their JS bundle.
                slots_src = data.get("slots")
                slots: List[str] = []
                if isinstance(slots_src, list):
                    slots = [s for s in slots_src if isinstance(s, str) and s]
                plugins.append({
                    "name": name,
                    "label": data.get("label", name),
                    "description": data.get("description", ""),
                    "icon": data.get("icon", "Puzzle"),
                    "version": data.get("version", "0.0.0"),
                    "tab": tab_info,
                    "slots": slots,
                    "entry": data.get("entry", "dist/index.js"),
                    "css": data.get("css"),
                    "has_api": bool(data.get("api")),
                    "source": source,
                    "_dir": str(child / "dashboard"),
                    "_api_file": data.get("api"),
                })
            except Exception as exc:
                _log.warning("Bad dashboard plugin manifest %s: %s", manifest_file, exc)
                continue
    return plugins


# Cache discovered plugins per-process (refresh on explicit re-scan).
_dashboard_plugins_cache: Optional[list] = None


def _get_dashboard_plugins(force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    if _dashboard_plugins_cache is None or force_rescan:
        _dashboard_plugins_cache = _discover_dashboard_plugins()
    return _dashboard_plugins_cache


@app.get("/api/dashboard/plugins")
async def get_dashboard_plugins():
    """Return discovered dashboard plugins."""
    plugins = _get_dashboard_plugins()
    # Strip internal fields before sending to frontend.
    return [
        {k: v for k, v in p.items() if not k.startswith("_")}
        for p in plugins
    ]


@app.get("/api/dashboard/plugins/rescan")
async def rescan_dashboard_plugins():
    """Force re-scan of dashboard plugins."""
    plugins = _get_dashboard_plugins(force_rescan=True)
    return {"ok": True, "count": len(plugins)}


@app.get("/dashboard-plugins/{plugin_name}/{file_path:path}")
async def serve_plugin_asset(plugin_name: str, file_path: str):
    """Serve static assets from a dashboard plugin directory.

    Only serves files from the plugin's ``dashboard/`` subdirectory.
    Path traversal is blocked by checking ``resolve().is_relative_to()``.
    """
    plugins = _get_dashboard_plugins()
    plugin = next((p for p in plugins if p["name"] == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    base = Path(plugin["_dir"])
    target = (base / file_path).resolve()

    if not target.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    suffix = target.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }
    media_type = content_types.get(suffix, "application/octet-stream")
    return FileResponse(target, media_type=media_type)


def _mount_plugin_api_routes():
    """Import and mount backend API routes from plugins that declare them.

    Each plugin's ``api`` field points to a Python file that must expose
    a ``router`` (FastAPI APIRouter).  Routes are mounted under
    ``/api/plugins/<name>/``.
    """
    for plugin in _get_dashboard_plugins():
        api_file_name = plugin.get("_api_file")
        if not api_file_name:
            continue
        api_path = Path(plugin["_dir"]) / api_file_name
        if not api_path.exists():
            _log.warning("Plugin %s declares api=%s but file not found", plugin["name"], api_file_name)
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"elevate_dashboard_plugin_{plugin['name']}", api_path,
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            router = getattr(mod, "router", None)
            if router is None:
                _log.warning("Plugin %s api file has no 'router' attribute", plugin["name"])
                continue
            app.include_router(router, prefix=f"/api/plugins/{plugin['name']}")
            _log.info("Mounted plugin API routes: /api/plugins/%s/", plugin["name"])
        except Exception as exc:
            _log.warning("Failed to load plugin %s API routes: %s", plugin["name"], exc)


# Mount plugin API routes before the SPA catch-all.
_mount_plugin_api_routes()

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
