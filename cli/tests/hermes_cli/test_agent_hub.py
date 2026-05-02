import json

import yaml


def test_agent_hub_snapshot_reflects_local_state_without_raw_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    memory_db = tmp_path / "memory_store.db"

    from plugins.memory.holographic.store import MemoryStore

    store = MemoryStore(db_path=memory_db)
    try:
        store.add_fact("Skyleigh Elevate uses Telegram for agent access.", category="agent")
        store.record_turn(
            "session-1",
            "Remember that Skyli works with eXp.",
            "Saved that to memory.",
            session_day="2026-04-30",
            created_at="2026-04-30T12:00:00",
        )
    finally:
        store.close()

    raw_token = "test-telegram-token-placeholder"
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "openai", "default": "gpt-4.1-mini"},
                "memory": {"provider": "holographic"},
                "plugins": {
                    "elevate-memory-store": {
                        "db_path": str(memory_db),
                        "embedding_enabled": "true",
                        "embedding_provider": "openai",
                        "embedding_model": "text-embedding-3-small",
                    }
                },
                "platforms": {
                    "telegram": {
                        "enabled": True,
                        "token": raw_token,
                    }
                },
                "agent_hub": {
                    "agents": [
                        {
                            "id": "executive-assistant",
                            "name": "Executive Assistant",
                            "role": "main",
                            "platforms": ["telegram"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: None)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: None)

    snapshot = agent_hub.build_agent_hub_snapshot()
    encoded = json.dumps(snapshot)

    assert snapshot["agents"][0]["name"] == "Executive Assistant"
    telegram = next(item for item in snapshot["platforms"] if item["name"] == "telegram")
    assert telegram["token_configured"] is True
    assert snapshot["memory"]["facts"] == 1
    assert snapshot["memory"]["journal"]["pending"] == 1
    assert snapshot["memory"]["graph"]["nodes"]
    assert raw_token not in encoded


def test_agent_hub_defaults_include_starter_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"model": "gpt-4.1-mini"}),
        encoding="utf-8",
    )

    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: None)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: None)

    snapshot = agent_hub.build_agent_hub_snapshot()
    names = {agent["name"] for agent in snapshot["agents"]}

    assert {
        "Executive Assistant",
        "Admin",
        "Outreach",
        "Ads",
        "Social Media",
    }.issubset(names)
