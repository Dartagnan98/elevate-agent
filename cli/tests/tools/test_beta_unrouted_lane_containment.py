"""Package A5 — the four ERB-406 unrouted lanes under exact Realtor Beta.

The registry/effect-broker boundary governs every migrated dispatch lane
(A2a/A2b/A3/A4).  Four lanes named by the ERB-406 gate map never routed
through it; A5 requires each to be routed, proven unreachable, or failed
closed under exact Beta.  This suite pins the source dispositions:

1. **Nested code-execution RPC** — ``execute_code`` is undeclared →
   ``unknown`` → typed refusal BEFORE its handler, so the sandbox RPC
   server can never start under exact Beta; and the exact nested dispatch
   shape (``handle_function_call(name, args, task_id=...)`` with no
   durable identity) independently fails closed as defense in depth.
2. **Cron scripts** — disabled at source (``cron/execution_policy``),
   pinned exhaustively by ``tests/cron/test_beta_execution_disabled.py``
   (gate-pinned suite).  Here: the ``cronjob`` management tools are
   undeclared → refused at the atomic boundary.
3. **MCP / provider-owned** — MCP discovery and registration fail closed
   before any config read, loop start, spawn, or connection; a registered
   ``mcp-*`` tool is refused before its handler; the hermes-tools MCP
   callback shape fails closed; the external codex app-server runtime is
   refused at its entry point before any subprocess session, and its
   AIAgent binding is severed at source.
4. **Sender queue** — covered by
   ``tests/elevate_cli/test_beta_sender_containment.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import tools.mcp_tool as mcp_tool
from model_tools import dispatch_agent_owned_registry_tool, handle_function_call
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry


TURN = "turn-a5-lanes"


@pytest.fixture
def bound_read_only_policy():
    policy = ExecutionPolicy.for_mode(TURN, "read_only")
    token = set_current_execution_policy(policy, policy_revision=2)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class _ScratchTool:
    def __init__(self, name, handler, *, toolset="_test-a5-lanes", effects=None):
        self.name = name
        registry.register(
            name=name,
            toolset=toolset,
            schema={
                "name": name,
                "description": "a5 lane scratch tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=handler,
            effects=effects,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        registry.deregister(self.name)
        return False


# =========================================================================
# Lane 1 — nested code-execution RPC
# =========================================================================


class TestNestedCodeExecutionLane:
    def test_execute_code_is_undeclared_and_refused_before_sandbox(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        assert registry.get_effect_metadata("execute_code")["declared"] is False

        import tools.code_execution_tool as code_execution_tool

        def _forbidden(*args, **kwargs):
            raise AssertionError("execute_code sandbox must not start in Beta")

        monkeypatch.setattr(code_execution_tool, "execute_code", _forbidden)

        payload = json.loads(
            dispatch_agent_owned_registry_tool(
                "execute_code",
                {"code": "print('x')"},
                session_id="session-a5-lanes",
                tool_call_id="call-a5-exec",
            )
        )
        assert payload["shadow_status"] == "effect_policy_block"
        assert "No handler was run" in payload["error"]

    def test_nested_rpc_dispatch_shape_fails_closed_without_identity(
        self, monkeypatch, bound_read_only_policy
    ):
        """``_rpc_server_loop`` / ``_rpc_poll_loop`` dispatch nested calls as
        ``handle_function_call(tool, args, task_id=task_id)`` — no session,
        no tool_call_id.  Even for a declared pure-read tool, exact Beta
        refuses that shape before any handler (defense in depth if the
        sandbox were ever revived)."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_nested_read",
            lambda args, **kw: calls.append(1) or '{"ok": true}',
            effects={"read"},
        ):
            result = handle_function_call(
                "_a5_nested_read", {}, task_id="sandbox-task"
            )

        payload = json.loads(result)
        assert payload["shadow_status"] == "effect_context_block"
        assert calls == []


# =========================================================================
# Lane 2 — cron management tools at the atomic boundary
# =========================================================================


class TestCronToolLane:
    @pytest.mark.parametrize(
        "action", ["create", "list", "run", "remove", "pause", "resume"]
    )
    def test_cronjob_management_tool_refused_before_handler(
        self, monkeypatch, bound_read_only_policy, action
    ):
        """Scheduled execution is disabled at source under Beta (pinned by
        the gate-pinned ``test_beta_execution_disabled`` suite); the single
        registered ``cronjob`` management tool is additionally undeclared,
        so every action shape is refused pre-handler at the atomic
        boundary — a Beta turn cannot even schedule future work."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        assert registry.get_entry("cronjob") is not None
        assert registry.get_effect_metadata("cronjob")["declared"] is False
        payload = json.loads(
            dispatch_agent_owned_registry_tool(
                "cronjob",
                {"action": action},
                session_id="session-a5-lanes",
                tool_call_id=f"call-a5-cron-{action}",
            )
        )
        assert payload["shadow_status"] == "effect_policy_block"
        assert "No handler was run" in payload["error"]


# =========================================================================
# Lane 3a — MCP discovery/registration fail closed pre-connection
# =========================================================================


class TestMcpDiscoveryLane:
    def test_discover_fails_closed_before_config_read_under_exact_beta(
        self, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

        def _forbidden_config():
            raise AssertionError("Beta must not read mcp_servers config")

        def _forbidden_loop(*args, **kwargs):
            raise AssertionError("Beta must not start the MCP loop thread")

        monkeypatch.setattr(mcp_tool, "_load_mcp_config", _forbidden_config)
        monkeypatch.setattr(mcp_tool, "_ensure_mcp_loop", _forbidden_loop)
        monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", _forbidden_loop)

        assert mcp_tool.discover_mcp_tools() == []

    def test_register_fails_closed_before_any_connection_under_exact_beta(
        self, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

        def _forbidden_loop(*args, **kwargs):
            raise AssertionError("Beta must not start or use the MCP loop")

        monkeypatch.setattr(mcp_tool, "_ensure_mcp_loop", _forbidden_loop)
        monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", _forbidden_loop)
        before = dict(mcp_tool._servers)

        result = mcp_tool.register_mcp_servers(
            {"attacker": {"command": "/bin/echo", "args": ["hi"]}}
        )

        assert result == []
        assert mcp_tool._servers == before

    def test_stable_discovery_path_is_unchanged(self, monkeypatch):
        """Outside exact Beta the gate must be inert: discovery still reads
        config (when the SDK is present) and degrades exactly as before."""
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        if not mcp_tool._MCP_AVAILABLE:
            pytest.skip("mcp SDK unavailable; stable path returns [] earlier")
        config_reads = []
        monkeypatch.setattr(
            mcp_tool, "_load_mcp_config", lambda: config_reads.append(1) or {}
        )

        assert mcp_tool.discover_mcp_tools() == []
        assert config_reads == [1]

    def test_noncanonical_channel_keeps_stable_mcp_behavior(self, monkeypatch):
        """Exact-lowercase channel contract: ``BeTa`` is NOT Beta and must
        not inherit Beta clamps (committed channel-contract design)."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "BeTa")
        if not mcp_tool._MCP_AVAILABLE:
            pytest.skip("mcp SDK unavailable; stable path returns [] earlier")
        config_reads = []
        monkeypatch.setattr(
            mcp_tool, "_load_mcp_config", lambda: config_reads.append(1) or {}
        )
        assert mcp_tool.discover_mcp_tools() == []
        assert config_reads == [1]

    def test_operator_probe_fails_closed_before_loop_or_connection(
        self, monkeypatch
    ):
        """The operator-CLI temporary probe (``mcp add``/``test``/``login``
        funnel through ``_probe_single_server``) bypasses both registration
        chokepoints, so it carries the same exact-Beta gate: typed refusal
        BEFORE any loop thread, spawn, or connection (A5 review P2 fix)."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        from elevate_cli import mcp_config

        def _forbidden(*args, **kwargs):
            raise AssertionError("Beta probe must not start or use the MCP loop")

        monkeypatch.setattr(mcp_tool, "_ensure_mcp_loop", _forbidden)
        monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", _forbidden)
        monkeypatch.setattr(mcp_tool, "_connect_server", _forbidden)

        with pytest.raises(RuntimeError, match="beta_mcp_servers_disabled"):
            mcp_config._probe_single_server(
                "attacker", {"command": "/bin/echo", "args": ["hi"]}
            )

    def test_stable_operator_probe_still_reaches_the_loop(self, monkeypatch):
        """Outside exact Beta the probe gate is inert: the helper still
        starts its loop machinery (proven by the sentinel firing)."""
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        from elevate_cli import mcp_config

        class _Sentinel(RuntimeError):
            pass

        def _loop_sentinel(*args, **kwargs):
            raise _Sentinel("SENTINEL-LOOP")

        monkeypatch.setattr(mcp_tool, "_ensure_mcp_loop", _loop_sentinel)

        with pytest.raises(_Sentinel, match="SENTINEL-LOOP"):
            mcp_config._probe_single_server(
                "probe", {"command": "/bin/echo", "args": ["hi"]}
            )


# =========================================================================
# Lane 3b — a registered mcp-* tool is refused before its handler
# =========================================================================


class TestMcpDispatchLane:
    def test_registered_mcp_tool_refused_before_handler(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_mcp_probe",
            lambda args, **kw: calls.append(1) or '{"remote": "mutated"}',
            toolset="mcp-_a5test",
        ):
            payload = json.loads(
                dispatch_agent_owned_registry_tool(
                    "_a5_mcp_probe",
                    {},
                    session_id="session-a5-lanes",
                    tool_call_id="call-a5-mcp",
                )
            )

        assert payload["shadow_status"] == "effect_policy_block"
        assert calls == []

    def test_hermes_mcp_callback_shape_fails_closed(
        self, monkeypatch, bound_read_only_policy
    ):
        """The hermes-tools MCP server callback dispatches
        ``handle_function_call(tool_name, kwargs)`` with no session, turn,
        call, or policy identity.  Exact Beta refuses that shape before any
        handler — the stateless callback cannot execute effects even if the
        (Beta-blocked) codex app-server runtime were revived."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_callback_probe",
            lambda args, **kw: calls.append(1) or '{"ok": true}',
            effects={"read"},
        ):
            # Exact shape from hermes_tools_mcp_server._make_handler._dispatch.
            result = handle_function_call("_a5_callback_probe", {})

        payload = json.loads(result)
        assert payload["shadow_status"] == "effect_context_block"
        assert calls == []


# =========================================================================
# Lane 3c — external codex app-server runtime
# =========================================================================


class TestCodexAppServerLane:
    def _agent(self):
        return SimpleNamespace(api_mode="codex_app_server", session_cwd=None)

    def test_refused_at_entry_before_any_subprocess_session(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        import agent.transports.codex_app_server_session as session_module
        from agent.codex_runtime import run_codex_app_server_turn

        def _forbidden(*args, **kwargs):
            raise AssertionError("Beta must never spawn a codex app-server")

        monkeypatch.setattr(session_module, "CodexAppServerSession", _forbidden)

        agent_obj = self._agent()
        messages = [{"role": "user", "content": "hi"}]
        result = run_codex_app_server_turn(
            agent_obj,
            user_message="hi",
            original_user_message="hi",
            messages=messages,
            effective_task_id="task-a5",
        )

        assert result["error"] == "beta_codex_app_server_not_allowed"
        assert result["completed"] is False
        assert "beta_codex_app_server_not_allowed" in result["final_response"]
        assert result["messages"] is messages
        assert getattr(agent_obj, "_codex_session", None) is None

    def test_stable_entry_still_reaches_session_construction(self, monkeypatch):
        """Outside exact Beta the gate is inert: the lane still constructs
        its session (proven by the sentinel firing)."""
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        import agent.transports.codex_app_server_session as session_module
        from agent.codex_runtime import run_codex_app_server_turn

        class _Sentinel(RuntimeError):
            pass

        def _spawn(*args, **kwargs):
            raise _Sentinel("SENTINEL-SPAWN")

        monkeypatch.setattr(session_module, "CodexAppServerSession", _spawn)

        with pytest.raises(_Sentinel, match="SENTINEL-SPAWN"):
            run_codex_app_server_turn(
                self._agent(),
                user_message="hi",
                original_user_message="hi",
                messages=[],
                effective_task_id="task-a5",
            )

    def test_aiagent_app_server_binding_is_severed_at_source(self):
        """``conversation_loop`` still names ``_run_codex_app_server_turn``,
        but AIAgent deliberately no longer binds it: the lane is dead code
        in production.  If someone rebinds it, this pin fails and the
        entry-point gate above becomes the enforced boundary."""
        import run_agent

        assert getattr(run_agent.AIAgent, "_run_codex_app_server_turn", None) is None
