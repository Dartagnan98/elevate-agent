"""Dashboard status route."""

import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter

from elevate_cli import __release_date__, __version__
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BETA_ALLOWED_MODELS_VERSION,
    BETA_ALLOWED_PROVIDER,
    BETA_PROVIDER_POLICY_VERSION,
    BetaProviderPolicyError,
    beta_provider_policy_active,
    read_beta_codex_auth_status,
    validate_beta_config_for_persistence,
)
from elevate_cli.config import (
    check_config_version,
    get_config_path,
    get_elevate_home,
    get_env_path,
    read_raw_config,
)
from gateway.status import get_running_pid, read_runtime_status


GetSessionDb = Callable[[], Any]

_STATUS_CACHE_TTL_SEC = 1.5
_status_cache_payload: dict[str, Any] | None = None
_status_cache_expires_at = 0.0
_status_cache_lock = threading.Lock()
_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    logging.getLogger(__name__).warning(
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


def _configured_primary(config: Any) -> tuple[str, str]:
    """Return only public-safe string fields from the raw primary config."""
    if not isinstance(config, dict):
        return "", ""
    model = config.get("model")
    if not isinstance(model, dict):
        return "", ""
    provider_value = model.get("provider")
    model_value = model.get("default") or model.get("model")
    provider = provider_value.strip() if isinstance(provider_value, str) else ""
    model_id = model_value.strip() if isinstance(model_value, str) else ""
    return provider, model_id


def _beta_runtime_receipt(
    *,
    elevate_home: Path,
    config: Any,
    auth_status: Any,
) -> dict[str, Any]:
    """Build the public-safe, pure-read receipt used for Beta adoption.

    Config validation is run with a synthetic ready auth flag so config-policy
    failures remain distinct from the current profile's local auth reason.  No
    secret values, auth paths, tokens, custom endpoints, or provider metadata
    are copied into the receipt.
    """
    normalized_home = elevate_home.expanduser().resolve(strict=False)
    raw_config = config if isinstance(config, dict) else {}
    local_auth = auth_status if isinstance(auth_status, dict) else {}
    configured_provider, configured_model = _configured_primary(raw_config)

    entitlement_schema = 1
    entitlement_key_id = "ent-2026-07-a"
    entitlement_verifier_ready = False
    try:
        from elevate_cli.entitlement_assertion import (
            ENTITLEMENT_ASSERTION_KID,
            ENTITLEMENT_ASSERTION_SCHEMA,
            verifier_ready,
        )

        entitlement_schema = ENTITLEMENT_ASSERTION_SCHEMA
        entitlement_key_id = ENTITLEMENT_ASSERTION_KID
        entitlement_verifier_ready = verifier_ready()
    except Exception:
        entitlement_verifier_ready = False

    blocked_reason: str | None = None
    try:
        validate_beta_config_for_persistence(
            raw_config,
            {"logged_in": True},
            environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
        )
    except BetaProviderPolicyError as exc:
        blocked_reason = exc.code

    if blocked_reason is None and not configured_provider:
        blocked_reason = "missing_beta_provider"
    if blocked_reason is None and not configured_model:
        blocked_reason = "missing_beta_model"
    if blocked_reason is None and not entitlement_verifier_ready:
        blocked_reason = "beta_entitlement_verifier_unavailable"

    auth_ready = bool(local_auth.get("logged_in"))
    auth_reason = local_auth.get("reason")
    if not isinstance(auth_reason, str):
        auth_reason = None
    if blocked_reason is None and not auth_ready:
        blocked_reason = auth_reason or "beta_codex_auth_required"

    runtime_ready = (
        blocked_reason is None
        and auth_ready
        and configured_provider == BETA_ALLOWED_PROVIDER
        and configured_model in BETA_ALLOWED_MODELS
        and entitlement_verifier_ready
    )
    return {
        "releaseChannel": "beta",
        "elevateHome": str(normalized_home),
        "providerPolicyVersion": BETA_PROVIDER_POLICY_VERSION,
        "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
        "entitlementAssertionSchema": entitlement_schema,
        "entitlementAssertionKeyId": entitlement_key_id,
        "entitlementVerifierReady": entitlement_verifier_ready,
        "allowedProvider": BETA_ALLOWED_PROVIDER,
        "configuredProvider": configured_provider,
        "configuredModel": configured_model,
        "authReady": auth_ready,
        "authReason": auth_reason,
        "runtimeReady": runtime_ready,
        "blockedReason": blocked_reason,
    }


def create_status_router(
    *,
    workspace_root: Path,
    get_session_db: GetSessionDb,
    session_active_window_sec: int,
    check_config_version_func=check_config_version,
    get_running_pid_func=get_running_pid,
    read_runtime_status_func=read_runtime_status,
    gateway_health_url_func=lambda: _GATEWAY_HEALTH_URL,
    probe_gateway_health_func=_probe_gateway_health,
    read_raw_config_func=read_raw_config,
    get_elevate_home_func=get_elevate_home,
    read_beta_codex_auth_status_func=read_beta_codex_auth_status,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build the dashboard status route."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/status")
    async def get_status():
        cached = _cached_status_payload()
        if cached is not None:
            return cached

        current_ver, latest_ver = check_config_version_func()

        gateway_pid = get_running_pid_func()
        gateway_running = gateway_pid is not None
        remote_health_body: dict | None = None
        gateway_health_url = gateway_health_url_func()

        if not gateway_running and gateway_health_url:
            loop = asyncio.get_event_loop()
            alive, remote_health_body = await loop.run_in_executor(
                None, probe_gateway_health_func
            )
            if alive:
                gateway_running = True
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

        runtime = read_runtime_status_func()
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
                if gateway_state in (None, "stopped"):
                    gateway_state = "running"

        if gateway_running and gateway_state is None and remote_health_body is not None:
            gateway_state = "running"

        active_sessions = 0
        try:
            from elevate_cli.data.chat_sessions import active_session_count

            active_sessions = active_session_count(session_active_window_sec)
        except Exception:
            try:
                db = get_session_db()
                try:
                    sessions = db.list_sessions_rich(limit=50)
                    now = time.time()
                    active_sessions = sum(
                        1 for s in sessions
                        if s.get("ended_at") is None
                        and (now - s.get("last_active", s.get("started_at", 0)))
                        < session_active_window_sec
                    )
                finally:
                    db.close()
            except Exception:
                _log.debug("status active session count failed", exc_info=True)

        payload = {
            "version": __version__,
            "release_date": __release_date__,
            "project_root": str(workspace_root),
            "elevate_home": str(get_elevate_home()),
            "config_path": str(get_config_path()),
            "env_path": str(get_env_path()),
            "config_version": current_ver,
            "latest_config_version": latest_ver,
            "gateway_running": gateway_running,
            "gateway_pid": gateway_pid,
            "gateway_health_url": gateway_health_url,
            "gateway_state": gateway_state,
            "gateway_platforms": gateway_platforms,
            "gateway_exit_reason": gateway_exit_reason,
            "gateway_updated_at": gateway_updated_at,
            "active_sessions": active_sessions,
        }
        if beta_provider_policy_active():
            elevate_home = get_elevate_home_func()
            raw_config = read_raw_config_func()
            auth_status = read_beta_codex_auth_status_func(elevate_home)
            payload["beta_runtime"] = _beta_runtime_receipt(
                elevate_home=Path(elevate_home),
                config=raw_config,
                auth_status=auth_status,
            )
        _store_status_payload(payload)
        return payload

    return router
