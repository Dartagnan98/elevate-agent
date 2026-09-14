"""Route registration for dashboard session, status, files, and actions APIs."""

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from elevate_cli.web_routes.actions import create_actions_router
from elevate_cli.web_routes.activity_comms import create_activity_comms_router
from elevate_cli.web_routes.cron import create_cron_router
from elevate_cli.web_routes.files import create_files_router
from elevate_cli.web_routes.license import create_license_router
from elevate_cli.web_routes.logs import create_logs_router
from elevate_cli.web_routes.oauth import create_oauth_router
from elevate_cli.web_routes.session_details import create_session_detail_router
from elevate_cli.web_routes.sessions import create_sessions_router
from elevate_cli.web_routes.status import create_status_router
from elevate_cli.web_routes.workspace import create_workspace_router


def register_session_system_routes(
    app: FastAPI,
    *,
    log: logging.Logger,
    get_session_db: Callable[[], Any],
    platform_chat_sources: Callable[[], list[str]],
    mark_session_activity: Callable[[list[dict[str, Any]], float], None],
    session_list_payload: Callable[[dict[str, Any]], dict[str, Any]],
    require_token: Callable[[Request], None],
    session_reveal_target: Callable[[str], Path],
    open_in_file_manager: Callable[[Path], None],
    live_subagent_child_session_ids: Callable[[], set[str]],
    workspace_root: Path,
    session_active_window_sec: int,
    check_config_version_func: Callable[[], Any],
    get_running_pid_func: Callable[[], Any],
    read_runtime_status_func: Callable[[], Any],
    gateway_health_url_func: Callable[[], Any],
    probe_gateway_health_func: Callable[[], Any],
    project_root: Path,
    get_elevate_home_func: Callable[[], Path],
    upload_max_per_file_func: Callable[[], int],
    action_log_dir: Path,
    action_log_files: dict[str, str],
    action_procs: dict[str, subprocess.Popen],
    spawn_elevate_action: Callable[[list[str], str], subprocess.Popen],
    tail_lines: Callable[[Path, int], list[str]],
    is_packaged_desktop_runtime: Callable[[], bool],
    git_value: Callable[..., Any],
    fs_cache_get: Callable[..., Any],
    fs_cache_put: Callable[..., Any],
) -> None:
    app.include_router(
        create_sessions_router(
            get_session_db=get_session_db,
            platform_chat_sources=platform_chat_sources,
            mark_session_activity=mark_session_activity,
            session_list_payload=session_list_payload,
            log=log,
        )
    )

    app.include_router(create_oauth_router(require_token=require_token))

    app.include_router(
        create_session_detail_router(
            get_session_db=get_session_db,
            session_reveal_target=session_reveal_target,
            open_in_file_manager=open_in_file_manager,
            live_subagent_child_session_ids=live_subagent_child_session_ids,
            log=log,
        )
    )

    app.include_router(create_cron_router(log=log))

    app.include_router(
        create_status_router(
            workspace_root=workspace_root,
            get_session_db=get_session_db,
            session_active_window_sec=session_active_window_sec,
            check_config_version_func=check_config_version_func,
            get_running_pid_func=get_running_pid_func,
            read_runtime_status_func=read_runtime_status_func,
            gateway_health_url_func=gateway_health_url_func,
            probe_gateway_health_func=probe_gateway_health_func,
            log=log,
        )
    )

    app.include_router(create_license_router(require_token=require_token))

    app.include_router(
        create_files_router(
            project_root=project_root,
            get_elevate_home_func=get_elevate_home_func,
            upload_max_per_file_func=upload_max_per_file_func,
            log=log,
        )
    )

    app.include_router(create_logs_router())

    app.include_router(
        create_workspace_router(
            workspace_root=workspace_root,
            open_in_file_manager=open_in_file_manager,
            log=log,
        )
    )

    app.include_router(
        create_actions_router(
            project_root=project_root,
            action_log_dir=action_log_dir,
            action_log_files=action_log_files,
            action_procs=action_procs,
            spawn_elevate_action=spawn_elevate_action,
            tail_lines=tail_lines,
            is_packaged_desktop_runtime=is_packaged_desktop_runtime,
            git_value=git_value,
            log=log,
        )
    )

    app.include_router(
        create_activity_comms_router(
            fs_cache_get=fs_cache_get,
            fs_cache_put=fs_cache_put,
            log=log,
        )
    )
