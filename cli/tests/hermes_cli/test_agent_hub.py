import json

import pytest
import yaml

from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    """Agent defs are PG-backed (hub_agents) — bind the pool to this test's
    ELEVATE_HOME instead of a previous test's torn-down embedded server."""
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_agent_hub_snapshot_reflects_local_state_without_raw_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    memory_db = tmp_path / "memory_store.db"

    from plugins.memory.holographic.store import MemoryStore

    store = MemoryStore(db_path=memory_db)
    try:
        store.add_fact("Elevate Demo uses Telegram for agent access.", category="agent")
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
    # Only the Executive Assistant is auto-seeded on a fresh install; every
    # other native agent is an installable default.
    names = {agent["name"] for agent in snapshot["agents"]}
    assert names == {"Executive Assistant"}

    installable = {item["name"] for item in snapshot.get("installableDefaults", [])}
    assert {
        "Admin",
        "Outreach",
        "Ads",
        "Marketing",
        "Social Media",
    }.issubset(installable)
