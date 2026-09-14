"""Regression tests for Settings connector run-mode wiring."""

from __future__ import annotations

import json
from unittest import mock


def _write_json(path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_all_wired_settings_connectors_open_agent_sessions() -> None:
    from elevate_cli.source_connectors import (
        AGENT_SESSION_SOURCE_IDS,
        SERVER_INLINE_SOURCE_IDS,
        WIRED_SOURCE_IDS,
    )

    assert AGENT_SESSION_SOURCE_IDS == WIRED_SOURCE_IDS
    assert SERVER_INLINE_SOURCE_IDS == frozenset()


def test_wired_prompts_are_executable_session_prompts() -> None:
    from elevate_cli import xposure_pcs_views as views
    from elevate_cli.source_connectors import WIRED_SOURCE_IDS, source_prompt_for

    with mock.patch.object(views, "_candidate_emails_for_prompt", return_value=["buyer@example.com"]):
        prompts = {source_id: source_prompt_for(source_id) for source_id in WIRED_SOURCE_IDS}

    for source_id, prompt in prompts.items():
        assert "STATUS: No live pull code exists" not in prompt, source_id
        assert ("TASK" in prompt or "You are an automation agent" in prompt), source_id
        assert "Postgres" in prompt, source_id

    assert "elevate_cli.main sync apple-messages" in prompts["apple-messages"]
    assert "elevate_cli.main sync crm" in prompts["crm"]
    assert "elevate_cli.main sync social" in prompts["social"]
    assert "source_id LIKE 'composio-%%'" in prompts["social"]
    assert "source_id LIKE 'composio-%'" not in prompts["social"]
    assert "elevate_cli.main sync buyer-brief" in prompts["buyer-brief"]
    assert "enrichment_brief" in prompts["buyer-brief"]
    assert "events WHERE source_id = 'xposure-pcs'" in prompts["xposure-pcs"]
    assert "identities WHERE kind = 'xposure_pcs_id'" in prompts["xposure-pcs"]
    assert "finish this buyer-search import before" in prompts["xposure-pcs"]
    assert "do not run concurrently" in prompts["buyer-brief"]
    assert "xposure_pcs_views_cdp_writer" in prompts["xposure-pcs-views"]
    assert "contacts_with_xposure_contact_id" in prompts["xposure-pcs-views"]
    assert "Do not\n   run it in parallel with xposure-pcs" in prompts["xposure-pcs-views"]
    assert "VISIBLE SESSION CONTINUATION" in prompts["xposure-pcs"]


def test_connector_response_includes_recovery_classification(tmp_path) -> None:
    from elevate_cli.source_connectors import build_source_connectors_response

    tools_root = tmp_path / "tools"
    source_root = tools_root / "data" / "sources"
    social_dir = source_root / "social"
    _write_json(
        social_dir / "source.json",
        {
            "provider": "Composio Social Accounts",
            "owner_agent": "Social Media",
            "enabled_ui_surfaces": ["Social Media", "Leads"],
        },
    )
    _write_json(
        social_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": "HTTP 422 from Composio Gmail connected_accounts",
            "last_checked_at": "2026-06-19T00:00:00+00:00",
        },
    )

    response = build_source_connectors_response(
        {"sources": {"tools_root": str(tools_root)}},
        include_prompts=False,
    )
    by_id = {connector["id"]: connector for connector in response["connectors"]}

    sms = by_id["sms-provider"]
    assert sms["state"] == "not_configured"
    assert sms["recoveryKind"] == "missing_config"
    assert sms["recoverySeverity"] == "info"
    assert sms["recoveryOwner"] == "Outreach"
    assert "Initialize this source" in sms["recoveryAction"]

    social = by_id["social"]
    assert social["state"] == "error"
    assert social["recoveryKind"] == "upstream_error"
    assert social["recoverySeverity"] == "warning"
    assert social["recoveryOwner"] == "Social Media"
    assert "Composio panel" in social["recoveryAction"]
    assert social["recoveryError"] == "HTTP 422 from Composio Gmail connected_accounts"
