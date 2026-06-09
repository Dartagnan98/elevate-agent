"""PG-backed Agent Hub persistence (``hub_agents``, migration 0026).

Agent definitions moved from the per-machine config.yaml
(``agent_hub.agents`` + ``removed_default_agents``) into the per-account
database. These tests cover the surface_state row helpers, the public
create/update/delete/reconcile contracts, default tombstones, and the
one-shot config.yaml import (frozen-archive semantics).
"""

from __future__ import annotations

import pytest
import yaml

from elevate_cli.data import connect, surface_state
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_hub_agent_rows_roundtrip_flags_and_tombstones():
    with connect() as conn:
        surface_state.upsert_hub_agent(conn, "helper", {"id": "helper", "name": "Helper"})
        surface_state.upsert_hub_agent(conn, "admin", {"id": "admin", "name": "Admin"}, builtin=True)

        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
        assert rows["helper"]["builtin"] is False
        assert rows["admin"]["builtin"] is True

        # Flags are preserved when not passed (upsert_registry pattern).
        surface_state.upsert_hub_agent(conn, "admin", {"id": "admin", "name": "Admin v2"})
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
        assert rows["admin"]["builtin"] is True
        assert rows["admin"]["config"]["name"] == "Admin v2"

        # tombstone keeps the row (removed=1); plain remove deletes it.
        assert surface_state.remove_hub_agent(conn, "admin", tombstone=True) is True
        assert surface_state.remove_hub_agent(conn, "helper") is True
        assert surface_state.remove_hub_agent(conn, "helper") is False
        assert surface_state.list_hub_agents(conn) == []
        every = surface_state.list_hub_agents(conn, include_removed=True)
        assert [(row["agent_id"], row["removed"]) for row in every] == [("admin", True)]

        # Tombstoning an absent id still records the park (idempotent no-op).
        assert surface_state.remove_hub_agent(conn, "marketing", tombstone=True) is True
        every = {row["agent_id"] for row in surface_state.list_hub_agents(conn, include_removed=True)}
        assert "marketing" in every


def test_create_update_delete_roundtrip_writes_hub_agents_rows():
    from elevate_cli.agent_hub import (
        create_agent_config,
        delete_agent_config,
        update_agent_config,
    )

    created = create_agent_config({"name": "Custom Helper", "skills": ["custom-skill"]})
    assert created["id"] == "custom-helper"
    assert "custom-skill" in created["skills"]

    with pytest.raises(ValueError):
        create_agent_config({"name": "Custom Helper"})  # duplicate id
    with pytest.raises(ValueError):
        create_agent_config({"id": "admin", "name": "Admin"})  # built-in id

    updated = update_agent_config("custom-helper", {"description": "does things", "enabled": False})
    assert updated["description"] == "does things"
    assert updated["enabled"] is False

    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
    row = rows["custom-helper"]
    assert row["builtin"] is False
    assert row["config"]["description"] == "does things"
    assert row["config"]["enabled"] is False
    assert "custom-skill" in row["config"]["skills"]

    result = delete_agent_config("custom-helper")
    assert result == {"ok": True, "id": "custom-helper", "removable": False}
    with connect() as conn:
        every = {row["agent_id"] for row in surface_state.list_hub_agents(conn, include_removed=True)}
    assert "custom-helper" not in every  # custom agents are deleted outright
    with pytest.raises(LookupError):
        delete_agent_config("custom-helper")


def test_deleted_default_tombstone_survives_reconcile_and_unparks_on_reinstall():
    from elevate_cli.agent_hub import (
        _load_agent_defs,
        delete_agent_config,
        reconcile_agent_hub_defaults,
        update_agent_config,
    )

    # Install the removable default, then delete it.
    installed = update_agent_config("admin", {"enabled": True})
    assert installed["id"] == "admin"
    assert "admin" in {agent["id"] for agent in _load_agent_defs({})}

    result = delete_agent_config("admin")
    assert result == {"ok": True, "id": "admin", "removable": True}
    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn, include_removed=True)}
    assert rows["admin"]["removed"] is True

    # Reconcile must not resurrect a tombstoned default.
    reconcile_agent_hub_defaults()
    ids = {agent["id"] for agent in _load_agent_defs({})}
    assert "admin" not in ids
    assert "executive-assistant" in ids

    # The permanent EA cannot be deleted.
    with pytest.raises(ValueError):
        delete_agent_config("executive-assistant")

    # Re-installing the default un-parks it.
    update_agent_config("admin", {"enabled": True})
    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn, include_removed=True)}
    assert rows["admin"]["removed"] is False
    assert "admin" in {agent["id"] for agent in _load_agent_defs({})}


def test_config_yaml_one_shot_import_freezes_yaml_and_runs_once():
    from elevate_cli.agent_hub import _load_agent_defs, delete_agent_config
    from elevate_cli.config import get_config_path

    legacy = {
        "agent_hub": {
            "default_agent": "executive-assistant",
            "removed_default_agents": ["marketing"],
            "agents": [
                {"id": "executive-assistant", "name": "My EA", "role": "main"},
                {"id": "my-custom", "name": "My Custom", "skills": ["x-skill"]},
            ],
        }
    }
    config_path = get_config_path()
    config_path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    yaml_before = config_path.read_text(encoding="utf-8")

    # First PG read triggers the import.
    roster = {agent["id"]: agent for agent in _load_agent_defs({})}
    assert roster["executive-assistant"]["name"] == "My EA"
    assert "x-skill" in roster["my-custom"]["skills"]
    assert "marketing" not in roster

    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn, include_removed=True)}
    assert rows["executive-assistant"]["builtin"] is True
    assert rows["my-custom"]["builtin"] is False
    assert rows["marketing"]["removed"] is True  # removed-ids list became tombstones
    assert rows["_imported"]["removed"] is True  # one-shot marker

    # config.yaml is a frozen archive — untouched by the import.
    assert config_path.read_text(encoding="utf-8") == yaml_before

    # The marker guards re-import: empty the roster down and the yaml agents
    # must NOT come back on the next read.
    delete_agent_config("my-custom")
    ids = {agent["id"] for agent in _load_agent_defs({})}
    assert "my-custom" not in ids
    with connect() as conn:
        every = {row["agent_id"] for row in surface_state.list_hub_agents(conn, include_removed=True)}
    assert "my-custom" not in every
