"""Source connector scaffold writers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_state import _blueprint
from elevate_cli.source_connector_modules.connector_views import connector_view
from elevate_cli.source_connector_modules.integration_settings import _as_dict
from elevate_cli.source_connector_modules.source_catalog import JSONL_FILES, OWNER_BY_SOURCE, UI_BY_SOURCE
from elevate_cli.source_connector_modules.source_io import _replace_jsonl, _source_dir, _write_json


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def scaffold_composio_social_source(config: dict[str, Any] | None = None) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    blueprint = _blueprint("social")
    if not blueprint:
        raise RuntimeError("Composio social connector blueprint is missing")

    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "social")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = source_connectors._now()
    surfaces = UI_BY_SOURCE["social"]
    owner = OWNER_BY_SOURCE["social"]
    prompt = source_connectors.source_prompt_for("social")
    prompt_path = artifacts_dir / "composio-social-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    composio_server = source_connectors._configured_composio_server(config)
    has_server = composio_server is not None
    next_step = (
        "Add Instagram, Facebook, LinkedIn, YouTube, TikTok, or other social apps inside Composio, "
        "then run the social sync/import agent prompt so Elevate can write local metrics, messages, lead events, and tasks."
        if has_server
        else (
            "Connect Composio MCP in Settings/config first, add the social apps inside Composio, "
            "then refresh this setup and run the social sync/import agent prompt."
        )
    )

    _write_json(
        source_dir / "source.json",
        {
            "source_id": "social",
            "provider": "Composio Social Accounts",
            "account_label": "Composio Social Hub",
            "connection_type": "composio_mcp" if has_server else "composio_mcp_setup",
            "auth_status": "composio_mcp_configured" if has_server else "needs_composio_account",
            "sync_mode": "composio_social_setup",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_social_accounts" if has_server else "needs_composio_mcp",
            "last_sync_at": now,
            "setup_notes": (
                "Composio is the social account hub. Elevate reads through the local MCP/tool connection "
                "and writes normalized local source records; outbound replies remain approval-gated."
            ),
            "agent_setup_prompt_path": str(prompt_path),
            "composio_server": composio_server,
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": next_step,
            "last_checked_at": now,
        },
    )

    for file_name in JSONL_FILES:
        _replace_jsonl(source_dir / file_name, [])

    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": "social",
                "source_record_id": f"social-composio-setup:{now}",
                "display_name": "Composio Social Accounts",
                "timestamp": now,
                "title": "Connect social accounts in Composio",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": next_step,
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.9,
                "tags": ["connector-setup", "composio", "social-media"],
                "target_ui_surfaces": ["Settings", "Social Media", "Leads", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": "social",
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Connect the operator's Composio account in Elevate Settings/config.",
                "Add approved social apps inside Composio.",
                "Confirm read scopes for metrics, posts, comments, and DMs.",
                "Run the social sync/import agent prompt to write local records.",
                "Keep outbound replies and posts approval-gated.",
            ],
        },
    )
    view = connector_view(source_root, "social")
    if view is None:
        raise RuntimeError("Composio social scaffold was written but could not be read")
    return view


def scaffold_source(source_id: str, config: dict[str, Any] | None = None) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    blueprint = _blueprint(source_id)
    if not blueprint:
        raise ValueError(f"Unknown source connector: {source_id}")

    if source_id == "apple-messages":
        return source_connectors.initialize_apple_messages_source(config)
    if source_id == "social":
        return scaffold_composio_social_source(config)
    if source_id == "crm":
        integrations = _as_dict(config.get("integrations"))
        crm = source_connectors._merge_crm(integrations.get("crm"))
        provider = str(crm.get("provider") or "").lower()
        env_values = source_connectors._combined_env(config)
        if provider == "lofty" or (not provider and env_values.get("LOFTY_API_KEY")):
            return source_connectors.sync_lofty_crm_source(config)
        if provider in {"followupboss", "sierra", "boldtrail", "brivity", "custom"}:
            return source_connectors.sync_generic_crm_source(config)
        return source_connectors.sync_lofty_crm_source(config)
    if source_id == "xposure-pcs":
        # Real scraper + canonical writethrough lives in its own module;
        # the scraper is replaceable, so keep it isolated.
        from elevate_cli.xposure_pcs_connector import sync_xposure_pcs_source

        # skip_scraper honored via env so cron + manual /api/source-
        # connectors/{id}/run can choose to reuse the latest snapshot
        # without burning a Lofty session.
        skip = bool(os.getenv("ELEVATE_XPOSURE_SKIP_SCRAPER"))
        return sync_xposure_pcs_source(config, skip_scraper=skip)
    if source_id == "buyer-brief":
        from elevate_cli.xposure_pcs_enrichment import run_enrichment

        return run_enrichment(config)
    if source_id == "xposure-pcs-views":
        # Per-listing engagement scrape (one-way mirror Client View).
        # Reuses the same Lofty/Xposure session as xposure-pcs but runs
        # on its own 48h cadence so we can re-fetch view counts without
        # re-running the criteria scrape every time.
        from elevate_cli.xposure_pcs_views import run_views_sync

        skip = bool(os.getenv("ELEVATE_XPOSURE_VIEWS_SKIP_SCRAPER"))
        views_cfg = _as_dict(config.get("xposure_pcs_views")) or config
        return run_views_sync(views_cfg, skip_scraper=skip)

    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, source_id)
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = source_connectors._now()
    surfaces = UI_BY_SOURCE.get(source_id, ["Settings"])
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    prompt = source_connectors.source_prompt_for(source_id)
    prompt_path = artifacts_dir / "agent-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    _write_json(
        source_dir / "source.json",
        {
            "source_id": source_id,
            "provider": blueprint["source"],
            "account_label": f"{blueprint['source']} setup",
            "connection_type": "agent_setup_task",
            "auth_status": "needs_agent_or_operator",
            "sync_mode": "agent_build_required",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_agent_setup",
            "last_sync_at": now,
            "setup_notes": (
                "No live account is connected yet. Elevate created a local setup prompt and task "
                "for the agent/operator to build the real webhook, poller, import command, or local bridge."
            ),
            "agent_setup_prompt_path": str(prompt_path),
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": (
                f"Run the agent setup prompt at {prompt_path} to build the {blueprint['source']} "
                "connector. No records are imported until that connector exists."
            ),
            "last_checked_at": now,
        },
    )

    _replace_jsonl(source_dir / "contacts.jsonl", [])
    _replace_jsonl(source_dir / "conversations.jsonl", [])
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", [])
    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": source_id,
                "source_record_id": f"{source_id}-agent-setup:{now}",
                "display_name": blueprint["source"],
                "timestamp": now,
                "title": f"Build {blueprint['source']} connector",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": (
                    "Use the generated setup prompt to create the real read-only connector, "
                    "then write normalized source records for the Hub."
                ),
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.86,
                "tags": ["connector-setup", "agent-build-required"],
                "target_ui_surfaces": ["Settings", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": source_id,
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Confirm provider/account and allowed data scope.",
                "Choose webhook, poller, import command, or local bridge.",
                "Create read-only credentials or export path.",
                "Normalize contacts, conversations, messages, lead events, and tasks.",
                "Mark status.json as connected, import_only, blocked, or needs_operator with exact next step.",
            ],
        },
    )
    view = connector_view(source_root, source_id)
    if view is None:
        raise RuntimeError("Connector scaffold was written but could not be read")
    return view
