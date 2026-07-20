"""Transport-surface tests for the hermes-tools MCP server.

Adversarial-review follow-up: the transport exposed ``kanban_list`` — whose
schema tells the model to "call kanban_recompute first" — without exposing
``kanban_recompute``, so a codex-runtime orchestrator was steered toward a
tool that did not exist on its transport. The referenced tool is now exposed
with the identical orchestrator gating the registry registration has.
"""

from __future__ import annotations

import asyncio
import json
import re

from agent.transports import hermes_tools_mcp_server as hermes_mcp
from tools import kanban_tools
from tools.registry import registry


class TestExposedKanbanSurface:
    def test_kanban_recompute_exposed_alongside_kanban_list(self):
        assert "kanban_list" in hermes_mcp.EXPOSED_TOOLS
        assert "kanban_recompute" in hermes_mcp.EXPOSED_TOOLS

    def test_exposed_kanban_schemas_reference_only_exposed_tools(self):
        """No exposed kanban tool's description may steer the model toward a
        kanban tool that is absent from this transport."""
        exposed = set(hermes_mcp.EXPOSED_TOOLS)
        kanban_exposed = sorted(n for n in exposed if n.startswith("kanban_"))
        assert kanban_exposed, "kanban surface unexpectedly empty"
        for name in kanban_exposed:
            schema = registry.get_schema(name)
            assert schema is not None, name
            referenced = set(
                re.findall(r"kanban_[a-z_]+", schema.get("description", ""))
            )
            missing = referenced - exposed
            assert not missing, (name, missing)

    def test_recompute_carries_same_orchestrator_gating_as_list(self):
        """Schema-level gating carries over: the transport builds its tool
        list from get_tool_definitions(), which filters on check_fn — and
        kanban_recompute registers the exact same orchestrator check_fn as
        kanban_list, so workers never see either schema."""
        list_entry = registry.get_entry("kanban_list")
        recompute_entry = registry.get_entry("kanban_recompute")
        assert list_entry is not None and recompute_entry is not None
        assert recompute_entry.check_fn is list_entry.check_fn
        assert (
            recompute_entry.check_fn
            is kanban_tools._check_kanban_orchestrator_mode
        )

    def test_recompute_refuses_worker_context_at_dispatch(self, monkeypatch):
        """Runtime gating carries over: even if a worker's transport served a
        stale schema, the handler's _require_orchestrator_tool guard refuses
        dispatch when ELEVATE_KANBAN_TASK marks a dispatcher-spawned worker."""
        monkeypatch.setenv("ELEVATE_KANBAN_TASK", "t_worker_ctx")
        result = json.loads(kanban_tools._handle_recompute({}))
        assert "orchestrator-only" in result["error"]

    def test_build_server_registers_recompute_from_hermes_schema(
        self, monkeypatch
    ):
        import model_tools

        fake_defs = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"{name} description",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in ("kanban_list", "kanban_recompute")
        ]
        monkeypatch.setattr(
            model_tools,
            "get_tool_definitions",
            lambda **_kwargs: fake_defs,
        )

        server = hermes_mcp._build_server()
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        assert {"kanban_list", "kanban_recompute"} <= names
