"""
Elevate — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m elevate_cli.main web          # Start on http://127.0.0.1:9119
    python -m elevate_cli.main web --port 8080
"""

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
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
    check_config_version,
    get_elevate_home,
    load_config,
    save_config,
)
from gateway.status import get_running_pid, read_runtime_status
from elevate_cli.web_auth import (
    _LOOPBACK_HOST_VALUES,
    has_valid_run_token as _has_valid_run_token_impl,
    has_valid_session_token as _has_valid_session_token_impl,
    is_accepted_host as _is_accepted_host_impl,
    license_signed_in as _license_signed_in_impl,
    load_session_token as _load_session_token_impl,
    request_id_for_log as _request_id_for_log_impl,
    require_session_token as _require_session_token_impl,
    safe_log_token as _safe_log_token_impl,
    session_id_for_log as _session_id_for_log_impl,
)
from elevate_cli.web_cloud_skills import (
    _CLOUD_SKILL_SYNC_INTERVAL_S,
    _cloud_skill_heartbeat as _cloud_skill_heartbeat_impl,
    _cloud_skill_sync_once as _cloud_skill_sync_once_impl,
    kickoff_cloud_skill_sync,
    stop_cloud_skill_heartbeat,
)
from elevate_cli.web_action_helpers import (
    open_in_file_manager as _open_in_file_manager_impl,
    session_reveal_target as _session_reveal_target_impl,
    spawn_elevate_action as _spawn_elevate_action_impl,
    tail_lines as _tail_lines_impl,
)
from elevate_cli.web_config_schema import (
    CONFIG_SCHEMA,
    _CATEGORY_MERGE,
    _CATEGORY_ORDER,
    _SCHEMA_OVERRIDES,
    _build_schema_from_config,
    _infer_type,
)
from elevate_cli.web_session_activity import (
    _SESSION_LIST_FIELDS,
    gateway_session_run_states as _gateway_session_run_states_impl,
    live_subagent_child_session_ids as _live_subagent_child_session_ids_impl,
    mark_session_activity as _mark_session_activity_impl,
    platform_chat_sources as _platform_chat_sources_impl,
    session_list_payload as _session_list_payload_impl,
)
from elevate_cli.web_session_store import (
    _FS_SCAN_CACHE,
    _FS_SCAN_CACHE_LOCK,
    _SESSION_DB_SINGLETON,
    _SESSION_DB_SINGLETON_LOCK,
    _SharedSessionDB,
    _account_key_safe,
    _fs_cache_get,
    _fs_cache_invalidate,
    _fs_cache_put,
    _get_session_db,
)
from elevate_cli.web_telegram_aliases import (
    _AGENT_TELEGRAM_BOT_TOKEN_RE,
    _EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY,
    _EXECUTIVE_TELEGRAM_CHANNEL_KEY,
    _TELEGRAM_BOT_TOKEN_RE,
    _agent_segment_is_executive,
    _executive_telegram_token,
    _looks_like_telegram_bot_token,
    _non_executive_duplicate_agent_token,
    _reject_shared_agent_token,
    _sync_executive_telegram_aliases,
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
    return _load_session_token_impl()


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


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r - using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint."""
    if not _GATEWAY_HEALTH_URL:
        return False, None

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
    return _license_signed_in_impl(license_path=_LICENSE_PATH)

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
    return _has_valid_session_token_impl(
        request,
        session_header_name=_SESSION_HEADER_NAME,
        session_token=_SESSION_TOKEN,
    )


def _has_valid_run_token(request: Request) -> bool:
    return _has_valid_run_token_impl(
        request,
        run_result_path_re=_RUN_RESULT_PATH_RE,
        run_token_header_name=_RUN_TOKEN_HEADER_NAME,
    )


def _require_token(request: Request) -> None:
    _require_session_token_impl(
        request,
        has_valid_session_token_func=_has_valid_session_token,
    )


# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    return _is_accepted_host_impl(host_header, bound_host)


def _safe_log_token(value: object, *, max_len: int = 96) -> str:
    return _safe_log_token_impl(value, max_len=max_len, log_token_re=_LOG_TOKEN_RE)


def _request_id_for_log(request: Request) -> str:
    return _request_id_for_log_impl(
        request,
        request_id_header_name=_REQUEST_ID_HEADER_NAME,
        safe_log_token_func=_safe_log_token,
    )


def _session_id_for_log(request: Request) -> str:
    return _session_id_for_log_impl(
        request,
        session_id_header_names=_SESSION_ID_HEADER_NAMES,
        request_session_path_re=_REQUEST_SESSION_PATH_RE,
        safe_log_token_func=_safe_log_token,
    )


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
from elevate_cli.web_routes.channels import _elevate_repo_root, create_channels_router
from elevate_cli.web_routes.chat_websockets import (
    create_chat_websocket_router,
    default_resolve_chat_argv,
)
from elevate_cli.web_routes.composio import (
    _COMPOSIO_SWR,
    _COMPOSIO_SWR_LOCK,
    _COMPOSIO_TOOLKITS_CACHE,
    _prewarm_composio_toolkits_in_background,
    create_composio_router,
)
from elevate_cli.web_routes.config import (
    _denormalize_config_from_web,
    _normalize_config_for_web,
    create_config_router,
)
from elevate_cli.web_routes.cron import create_cron_router
from elevate_cli.web_routes import dashboard as _dashboard_routes
from elevate_cli.web_routes.dashboard import create_dashboard_router, mount_dashboard_plugin_api_routes
from elevate_cli.web_routes.env import create_env_router
from elevate_cli.web_routes.files import _UPLOAD_MAX_PER_FILE, create_files_router
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
from elevate_cli.web_routes.social import _load_social_fetcher, create_social_router
from elevate_cli.web_routes.source_connectors import create_source_connectors_router
from elevate_cli.web_routes.status import create_status_router
from elevate_cli.web_routes.surface_tasks import create_surface_tasks_router
from elevate_cli.web_routes.threads import create_threads_router
from elevate_cli.web_routes.today import create_today_router
from elevate_cli.web_routes.workspace import create_workspace_router, git_value as _git_value
from elevate_cli.web_spa import mount_spa as _mount_spa
from elevate_cli.pty_bridge import PtyBridge, PtyUnavailableError

_normalise_theme_definition = _dashboard_routes._normalise_theme_definition
_discover_user_themes = _dashboard_routes._discover_user_themes
_dashboard_plugins_cache = None


def _get_dashboard_plugins(force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    _dashboard_routes._dashboard_plugins_cache = _dashboard_plugins_cache
    plugins = _dashboard_routes._get_dashboard_plugins(
        PROJECT_ROOT,
        _log,
        force_rescan=force_rescan,
    )
    _dashboard_plugins_cache = _dashboard_routes._dashboard_plugins_cache
    return plugins

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
    return _spawn_elevate_action_impl(
        subcommand,
        name,
        action_log_files=_ACTION_LOG_FILES,
        action_log_dir=_ACTION_LOG_DIR,
        action_procs=_ACTION_PROCS,
        project_root=PROJECT_ROOT,
    )


def _tail_lines(path: Path, n: int) -> List[str]:
    return _tail_lines_impl(path, n)


def _session_reveal_target(session_id: str) -> Path:
    return _session_reveal_target_impl(session_id, elevate_home=get_elevate_home())


def _open_in_file_manager(path: Path) -> None:
    _open_in_file_manager_impl(path)


# A session counts as "active" (spinner in the sidebar) only if a message
# landed within this many seconds. The spinner means genuinely working right
# now, not recently-touched — so this stays tight. 300s made idle chats spin.
_SESSION_ACTIVE_WINDOW_SEC = 25


def _gateway_session_run_states() -> tuple[set[str], set[str]]:
    return _gateway_session_run_states_impl()


def _live_running_session_keys() -> set[str]:
    """DB session keys the in-process gateway is ACTIVELY running a turn for."""
    return _gateway_session_run_states()[0]


def _live_subagent_child_session_ids() -> set[str]:
    return _live_subagent_child_session_ids_impl()


def _mark_session_activity(sessions: list[dict[str, Any]], now: float) -> None:
    _mark_session_activity_impl(
        sessions,
        now,
        session_active_window_sec=_SESSION_ACTIVE_WINDOW_SEC,
        gateway_session_run_states_func=_gateway_session_run_states,
    )


def _session_list_payload(session: dict[str, Any]) -> dict[str, Any]:
    return _session_list_payload_impl(session)


def _platform_chat_sources() -> list[str]:
    return _platform_chat_sources_impl()


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
        check_config_version_func=lambda: check_config_version(),
        get_running_pid_func=lambda: get_running_pid(),
        read_runtime_status_func=lambda: read_runtime_status(),
        gateway_health_url_func=lambda: _GATEWAY_HEALTH_URL,
        probe_gateway_health_func=lambda: _probe_gateway_health(),
        log=_log,
    )
)

app.include_router(create_license_router(require_token=_require_token))

app.include_router(
    create_files_router(
        project_root=PROJECT_ROOT,
        get_elevate_home_func=lambda: get_elevate_home(),
        upload_max_per_file_func=lambda: _UPLOAD_MAX_PER_FILE,
        log=_log,
    )
)

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
        load_config_func=lambda: load_config(),
        save_config_func=lambda config: save_config(config),
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
        elevate_repo_root_func=lambda: _elevate_repo_root(),
    )
)

app.include_router(create_source_connectors_router(log=_log))

app.include_router(create_integrations_router(log=_log))

app.include_router(
    create_composio_router(
        prewarm_composio_toolkits_func=lambda log: _prewarm_composio_toolkits_in_background(log),
        log=_log,
    )
)

app.include_router(create_dashboard_router(project_root=PROJECT_ROOT, log=_log))

app.include_router(create_lanes_router(log=_log))

app.include_router(create_outreach_templates_router(log=_log))

app.include_router(create_skills_router())

app.include_router(
    create_social_router(
        load_social_fetcher_func=lambda module_name: _load_social_fetcher(module_name),
        log=_log,
    )
)

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


def _cloud_skill_sync_once(reason: str) -> None:
    _cloud_skill_sync_once_impl(reason, log=_log)


async def _cloud_skill_heartbeat() -> None:
    await _cloud_skill_heartbeat_impl(
        interval_s=_CLOUD_SKILL_SYNC_INTERVAL_S,
        sync_once=_cloud_skill_sync_once,
    )


@app.on_event("startup")
async def _kickoff_cloud_skill_sync() -> None:
    await kickoff_cloud_skill_sync(
        app,
        sync_once=_cloud_skill_sync_once,
        heartbeat=_cloud_skill_heartbeat,
    )


@app.on_event("shutdown")
async def _stop_cloud_skill_heartbeat() -> None:
    await stop_cloud_skill_heartbeat(app)


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
