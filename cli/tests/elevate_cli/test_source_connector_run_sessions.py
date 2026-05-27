"""Regression tests for Settings connector run-mode wiring."""

from __future__ import annotations

from unittest import mock


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
