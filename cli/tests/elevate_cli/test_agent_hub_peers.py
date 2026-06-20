import logging
import json

from elevate_cli.web_routes.agent_hub_peers import build_agent_peers


def test_build_agent_peers_reads_env_roots_and_masks_telegram_token(tmp_path, monkeypatch):
    agent_dir = tmp_path / "acme" / "agents" / "ops"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.json").write_text(
        json.dumps(
            {
                "agent_name": "Operations",
                "enabled": True,
                "working_directory": "/tmp/ops",
                "timezone": "America/Vancouver",
                "communication_style": "brief",
                "crons": [{"name": "heartbeat"}],
                "channels": {"telegram": {"chat_id": "chat-1", "bot_token": "1234567890abcdef"}},
            }
        ),
        encoding="utf-8",
    )
    (agent_dir / "IDENTITY.md").write_text("# Ops\nKeeps work moving.\n", encoding="utf-8")
    monkeypatch.setenv("ELEVATE_PEERS_ROOT", str(tmp_path))
    monkeypatch.delenv("ELEVATE_PEERS_ROOTS", raising=False)

    result = build_agent_peers(logging.getLogger(__name__))

    assert result["rootsSearched"] == [str(tmp_path)]
    assert len(result["peers"]) == 1
    peer = result["peers"][0]
    assert peer["org"] == "acme"
    assert peer["name"] == "Operations"
    assert peer["roleHint"] == "Keeps work moving."
    assert peer["telegram"]["configured"] is True
    assert peer["telegram"]["chatId"] == "chat-1"
    assert peer["telegram"]["tokenPreview"] == "\u2022\u2022\u2022cdef"
    assert "1234567890abcdef" not in json.dumps(result)
