from __future__ import annotations

import json


def test_cortext_pack_preserves_runtime_lifecycle_and_cron_seeds(tmp_path):
    source = tmp_path / "community" / "agents" / "orchestrator"
    source.mkdir(parents=True)
    template = tmp_path / "templates" / "orchestrator"
    template.mkdir(parents=True)
    (template / "config.json").write_text(
        json.dumps(
            {
                "runtime": "claude-code",
                "model": "claude-sonnet",
                "ctx_warning_threshold": 65,
                "ctx_handoff_threshold": 75,
            }
        ),
        encoding="utf-8",
    )
    (source / "config.json").write_text(
        json.dumps(
            {
                "startup_delay": 5,
                "max_session_seconds": 255600,
                "max_crashes_per_day": 10,
                "working_directory": "/tmp/orchestrator",
                "timezone": "America/New_York",
                "day_mode_start": "08:00",
                "day_mode_end": "18:00",
                "communication_style": "casual",
                "approval_rules": {
                    "always_ask": ["external-comms"],
                    "never_ask": ["read_status"],
                },
                "crons": [
                    {
                        "name": "heartbeat",
                        "type": "recurring",
                        "interval": "4h",
                        "prompt": "Read HEARTBEAT.md and update state.",
                    },
                    {
                        "name": "check-approvals",
                        "type": "recurring",
                        "interval": "2h",
                        "prompt": "Check pending approvals.",
                    },
                ],
                "ecosystem": {
                    "local_version_control": {"enabled": True},
                    "upstream_sync": {"enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (source / "IDENTITY.md").write_text("Primary coordinator.\n", encoding="utf-8")
    (source / "SOUL.md").write_text("# Day Mode\nCoordinate approvals.\n", encoding="utf-8")
    (source / "HEARTBEAT.md").write_text("- Keep approvals moving\n", encoding="utf-8")

    from elevate_cli.web_routes.agent_hub import _build_cortext_pack

    pack = _build_cortext_pack(
        tmp_path,
        {
            "id": "orchestrator",
            "name": "Orchestrator",
            "role": "orchestrator",
            "source": "community/agents/orchestrator",
            "description": "Coordinates agents.",
            "owns": ["approvals"],
            "handoff_targets": ["analyst"],
            "escalation_target": "executive-assistant",
            "memory_scopes": ["orchestration"],
        },
    )
    payload = pack["payload"]

    assert payload["runtime"]["runtime_type"] == "claude-code"
    assert payload["runtime"]["model"] == "claude-sonnet"
    assert payload["runtime"]["workdir"] == "/tmp/orchestrator"
    assert payload["runtime"]["timezone"] == "America/New_York"
    assert payload["runtime"]["context_warning_threshold"] == 65
    assert payload["runtime"]["context_handoff_threshold"] == 75
    assert payload["lifecycle"]["startup_delay"] == 5
    assert payload["lifecycle"]["max_session_seconds"] == 255600
    assert payload["lifecycle"]["max_crashes_per_day"] == 10
    assert payload["ecosystem"]["local_version_control"] is True
    assert payload["ecosystem"]["upstream_sync"] is True

    heartbeat = payload["heartbeatSurfaceSeed"]
    assert heartbeat["schedule"] == "0 */4 * * *"
    assert heartbeat["goal"] == "Read HEARTBEAT.md and update state."
    assert heartbeat["config"]["max_session_seconds"] == 255600
    assert heartbeat["config"]["approval_rules"]["always_ask"] == ["external-comms"]

    assert len(payload["cronSeeds"]) == 1
    cron = payload["cronSeeds"][0]
    assert cron["name"] == "Orchestrator - check-approvals"
    assert cron["schedule"] == "every 2h"
    assert cron["agent"] == "orchestrator"
    assert cron["enabled"] is False
    assert cron["origin"]["type"] == "cortext-cron"
