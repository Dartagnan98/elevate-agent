"""Route registration for dashboard admin, config, and integration APIs."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from elevate_cli.web_routes.admin_actions import create_admin_actions_router
from elevate_cli.web_routes.admin_deals import create_admin_deals_router
from elevate_cli.web_routes.admin_templates import create_admin_templates_router
from elevate_cli.web_routes.analytics import create_analytics_router
from elevate_cli.web_routes.ayrshare import create_ayrshare_router
from elevate_cli.web_routes.channels import create_channels_router
from elevate_cli.web_routes.composio import create_composio_router
from elevate_cli.web_routes.config import create_config_router
from elevate_cli.web_routes.dashboard import create_dashboard_router
from elevate_cli.web_routes.env import create_env_router
from elevate_cli.web_routes.integrations import create_integrations_router
from elevate_cli.web_routes.lanes import create_lanes_router
from elevate_cli.web_routes.outreach_templates import create_outreach_templates_router
from elevate_cli.web_routes.skills import create_skills_router
from elevate_cli.web_routes.social import create_social_router
from elevate_cli.web_routes.source_connectors import create_source_connectors_router
from elevate_cli.web_routes.surface_tasks import create_surface_tasks_router
from elevate_cli.web_routes.threads import create_threads_router
from elevate_cli.web_routes.today import create_today_router


def register_business_routes(
    app: FastAPI,
    *,
    log: logging.Logger,
    web_actor: str,
    require_admin_setup_ready_for_launch: Callable[[], None],
    admin_jurisdiction_config: Callable[[], Any],
    default_config: dict[str, Any],
    config_schema: dict[str, Any],
    category_order: list[str],
    load_config_func: Callable[[], dict[str, Any]],
    save_config_func: Callable[[dict[str, Any]], Any],
    require_token: Callable[[Request], None],
    looks_like_telegram_bot_token: Callable[[str], bool],
    reject_shared_agent_token: Callable[[str, str], None],
    sync_executive_telegram_aliases: Callable[..., Any],
    get_session_db: Callable[[], Any],
    spawn_elevate_action: Callable[..., Any],
    elevate_repo_root_func: Callable[[], Path],
    prewarm_composio_toolkits_func: Callable[[logging.Logger], None],
    project_root: Path,
    load_social_fetcher_func: Callable[[str], Any],
) -> None:
    app.include_router(
        create_admin_actions_router(
            require_admin_setup_ready_for_launch=require_admin_setup_ready_for_launch,
            web_actor=web_actor,
            log=log,
        )
    )

    app.include_router(
        create_admin_deals_router(
            require_admin_setup_ready_for_launch=require_admin_setup_ready_for_launch,
            admin_jurisdiction_config=admin_jurisdiction_config,
            web_actor=web_actor,
            log=log,
        )
    )

    app.include_router(create_admin_templates_router(web_actor=web_actor, log=log))

    app.include_router(
        create_config_router(
            default_config=default_config,
            config_schema=config_schema,
            category_order=category_order,
            load_config_func=load_config_func,
            save_config_func=save_config_func,
            log=log,
        )
    )

    app.include_router(
        create_env_router(
            require_token=require_token,
            looks_like_telegram_bot_token=looks_like_telegram_bot_token,
            reject_shared_agent_token=reject_shared_agent_token,
            sync_executive_telegram_aliases=sync_executive_telegram_aliases,
            log=log,
        )
    )

    app.include_router(create_analytics_router(get_session_db=get_session_db, log=log))
    app.include_router(create_ayrshare_router(log=log))
    app.include_router(
        create_channels_router(
            log=log,
            require_token=require_token,
            spawn_elevate_action=spawn_elevate_action,
            looks_like_telegram_bot_token=looks_like_telegram_bot_token,
            sync_executive_telegram_aliases=sync_executive_telegram_aliases,
            elevate_repo_root_func=elevate_repo_root_func,
        )
    )
    app.include_router(create_source_connectors_router(log=log))
    app.include_router(create_integrations_router(log=log))
    app.include_router(
        create_composio_router(
            prewarm_composio_toolkits_func=prewarm_composio_toolkits_func,
            log=log,
        )
    )
    app.include_router(create_dashboard_router(project_root=project_root, log=log))
    app.include_router(create_lanes_router(log=log))
    app.include_router(create_outreach_templates_router(log=log))
    app.include_router(create_skills_router())
    app.include_router(
        create_social_router(
            load_social_fetcher_func=load_social_fetcher_func,
            log=log,
        )
    )
    app.include_router(create_surface_tasks_router(log=log))
    app.include_router(create_threads_router(log=log))
    app.include_router(create_today_router(log=log))
