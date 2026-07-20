"""The extracted memory branches build provider metadata truthfully.

The ``tool_executor`` / ``agent_runtime_helpers`` extractions referenced a
nonexistent ``agent._build_memory_write_metadata`` method; the real builder
is the module-level ``agent.background_review.build_memory_write_metadata
(agent, …)``.  Because the provider bridge swallows factory exceptions, the
broken reference silently dropped ALL provenance metadata instead of
failing loudly — these tests pin the corrected wiring.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_no_extraction_references_a_nonexistent_agent_method():
    import agent.agent_runtime_helpers as agent_runtime_helpers
    import agent.tool_executor as tool_executor

    for module in (tool_executor, agent_runtime_helpers):
        source = inspect.getsource(module)
        assert "agent._build_memory_write_metadata(" not in source, (
            f"{module.__name__} calls a nonexistent AIAgent method"
        )

    from agent.background_review import build_memory_write_metadata

    signature = inspect.signature(build_memory_write_metadata)
    assert next(iter(signature.parameters)) == "agent"
    assert {"task_id", "tool_call_id"} <= set(signature.parameters)


def test_extracted_memory_branch_delivers_real_provenance_metadata():
    """Driving the extracted ``invoke_tool`` memory branch end-to-end, the
    provider bridge receives the module-level builder's metadata instead of
    silently swallowing an AttributeError."""
    from agent.agent_runtime_helpers import invoke_tool

    manager = MagicMock()
    store = MagicMock()
    store.add.return_value = {"success": True, "message": "Entry added"}
    agent = SimpleNamespace(
        session_id="session-metadata",
        _parent_session_id="",
        platform="cli",
        _memory_store=store,
        _memory_manager=manager,
        _todo_store=None,
    )

    invoke_tool(
        agent,
        "memory",
        {"action": "add", "target": "memory", "content": "remember me"},
        "task-metadata",
        tool_call_id="call-metadata",
    )

    manager.on_memory_write.assert_called_once()
    metadata = manager.on_memory_write.call_args.kwargs["metadata"]
    assert metadata["session_id"] == "session-metadata"
    assert metadata["tool_name"] == "memory"
    assert metadata["task_id"] == "task-metadata"
    assert metadata["tool_call_id"] == "call-metadata"
    assert metadata["write_origin"] == "assistant_tool"
    assert metadata["execution_context"] == "foreground"
