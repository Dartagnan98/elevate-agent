"""Reliability release (section B4): a REVOKED/EXPIRED Composio account is
accumulated and surfaced on the 'social' connector's status.json, which the
read-side connector_state/connector_view render with zero UI edits.
"""

from __future__ import annotations

import json
from pathlib import Path

from elevate_cli import composio_inbound
from elevate_cli.config import load_config
from elevate_cli.source_connectors import get_source_root_info
from elevate_cli.source_connector_modules.connector_views import connector_view


def _social_dir() -> Path:
    info = get_source_root_info(load_config() or {})
    return Path(info["sourceRoot"]) / "social"


def _read_status() -> dict:
    return json.loads((_social_dir() / "status.json").read_text(encoding="utf-8"))


def test_write_social_status_blocked_on_dead_account():
    dead = [{"account_id": "acct-1", "status": "REVOKED", "toolkit": "gmail"}]
    composio_inbound._write_social_status(dead, live_accounts=False)

    status = _read_status()
    assert status["connected"] is False
    assert status["blocked"] is True
    assert "Gmail" in status["last_error"]
    assert "reconnect" in status["last_error"].lower()
    assert "Config → Composio" in status["next_operator_step"]
    assert status["last_checked_at"]


def test_dead_status_flows_through_connector_view_as_blocked():
    dead = [{"account_id": "acct-1", "status": "EXPIRED", "toolkit": "gmail"}]
    composio_inbound._write_social_status(dead, live_accounts=False)

    info = get_source_root_info(load_config() or {})
    view = connector_view(Path(info["sourceRoot"]), "social", include_prompt=False)
    assert view is not None
    assert view["state"] == "blocked"
    assert view["blocked"] is True
    assert view["connected"] is False
    assert "Gmail" in (view["lastError"] or "")
    assert (view["nextOperatorStep"] or "")


def test_healthy_write_clears_block_when_live_accounts_present():
    # First mark blocked, then a healthy tick with a live account clears it.
    composio_inbound._write_social_status(
        [{"account_id": "a", "status": "REVOKED", "toolkit": "gmail"}], live_accounts=False
    )
    composio_inbound._write_social_status([], live_accounts=True)

    status = _read_status()
    assert status["connected"] is True
    assert status["blocked"] is False
    assert status["last_error"] is None


def test_no_accounts_leaves_status_untouched():
    social_dir = _social_dir()
    status_path = social_dir / "status.json"
    if status_path.exists():
        status_path.unlink()
    # Nothing connected and nothing dead -> must not fabricate a status file.
    composio_inbound._write_social_status([], live_accounts=False)
    assert not status_path.exists()


def test_pull_all_supported_writes_social_status_on_dead(monkeypatch):
    monkeypatch.setattr(
        composio_inbound.composio_client,
        "load_capability_matrix",
        lambda: {"toolkits": {"gmail": {}}},
    )

    def _fake_pull(slug, **_kw):
        return {
            "ok": True,
            "skipped": False,
            "toolkit": slug,
            "accounts": 1,
            "dead": [{"account_id": "acct-1", "status": "REVOKED", "toolkit": slug}],
            "fetched": 0,
            "new": 0,
        }

    monkeypatch.setattr(composio_inbound, "pull_toolkit", _fake_pull)

    summary = composio_inbound.pull_all_supported()
    assert summary["total_dead"] == 1

    status = _read_status()
    assert status["blocked"] is True
    assert status["connected"] is False
    assert "Gmail" in status["last_error"]
