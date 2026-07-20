"""Tests for model_tools.py — function call dispatch, agent-loop interception, legacy toolsets."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import call, patch

import pytest

from model_tools import (
    handle_function_call,
    get_all_tool_names,
    get_tool_definitions,
    get_toolset_for_tool,
    _AGENT_LOOP_TOOLS,
    _LEGACY_TOOLSET_MAP,
    TOOL_TO_TOOLSET_MAP,
)
from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import ToolCallContext, registry


_EXACT_BETA_MUTATING_REGISTRY_CALLS = (
    ("write_file", {"path": "/tmp/never-written", "content": "blocked"}),
    ("patch", {"mode": "replace", "path": "/tmp/never-patched", "old_string": "a", "new_string": "b"}),
    ("execute_code", {"code": "result = 1"}),
    ("process", {"action": "kill", "process_id": "never"}),
    ("send_message", {"action": "send", "target": "telegram", "message": "blocked"}),
    ("lead_status", {"action": "set", "contact_id": "never", "status": "dead"}),
    ("admin_profile", {"action": "promote", "contact_id": "never"}),
    ("agent_bus", {"action": "create_task", "title": "blocked"}),
    ("agent_handoff", {"action": "create", "goal": "blocked"}),
    ("skill_manage", {"action": "delete", "name": "never"}),
    ("browser_click", {"element": "never"}),
    ("browser_type", {"element": "never", "text": "blocked"}),
)


# =========================================================================
# handle_function_call
# =========================================================================

class TestHandleFunctionCall:
    def test_agent_loop_tool_returns_error(self):
        for tool_name in _AGENT_LOOP_TOOLS:
            result = json.loads(handle_function_call(tool_name, {}))
            assert "error" in result
            assert "agent loop" in result["error"].lower()

    def test_unknown_tool_returns_error(self):
        result = json.loads(handle_function_call("totally_fake_tool_xyz", {}))
        assert "error" in result
        assert "totally_fake_tool_xyz" in result["error"]

    def test_exception_returns_json_error(self):
        # Even if something goes wrong, should return valid JSON
        result = handle_function_call("web_search", None)  # None args may cause issues
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" in parsed
        assert len(parsed["error"]) > 0
        assert "error" in parsed["error"].lower() or "failed" in parsed["error"].lower()

    def test_tool_hooks_receive_session_and_tool_call_ids(self):
        with (
            patch("model_tools.registry.dispatch", return_value='{"ok":true}'),
            patch("elevate_cli.plugins.invoke_hook") as mock_invoke_hook,
        ):
            result = handle_function_call(
                "web_search",
                {"q": "test"},
                task_id="task-1",
                tool_call_id="call-1",
                session_id="session-1",
            )

        assert result == '{"ok":true}'
        assert mock_invoke_hook.call_args_list == [
            call(
                "pre_tool_call",
                tool_name="web_search",
                args={"q": "test"},
                task_id="task-1",
                session_id="session-1",
                tool_call_id="call-1",
            ),
            call(
                "post_tool_call",
                tool_name="web_search",
                args={"q": "test"},
                result='{"ok":true}',
                task_id="task-1",
                session_id="session-1",
                tool_call_id="call-1",
            ),
            call(
                "transform_tool_result",
                tool_name="web_search",
                args={"q": "test"},
                result='{"ok":true}',
                task_id="task-1",
                session_id="session-1",
                tool_call_id="call-1",
            ),
        ]

    def test_missing_durable_identity_uses_content_free_legacy_fallback(
        self,
        caplog,
    ):
        with (
            caplog.at_level(logging.DEBUG, logger="model_tools"),
            patch("model_tools.registry.dispatch", return_value='{"legacy":true}') as dispatch,
            patch("model_tools.registry.execute_shadow") as execute_shadow,
            patch("elevate_cli.plugins.invoke_hook", return_value=[]),
        ):
            result = handle_function_call(
                "web_search",
                {"q": "private-client-address"},
                task_id="private-task-id",
                session_id="private-session-id",
                tool_call_id="private-call-id",
                user_task="private-user-request",
                skip_pre_tool_call_hook=True,
            )

        assert result == '{"legacy":true}'
        dispatch.assert_called_once_with(
            "web_search",
            {"q": "private-client-address"},
            task_id="private-task-id",
            user_task="private-user-request",
        )
        execute_shadow.assert_not_called()
        assert "registry shadow fallback" in caplog.text
        assert "policy,policy_revision" in caplog.text
        for private_value in (
            "private-client-address",
            "private-task-id",
            "private-session-id",
            "private-call-id",
            "private-user-request",
        ):
            assert private_value not in caplog.text

    def test_exact_beta_terminal_missing_identity_fails_closed(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        with (
            patch(
                "tools.approval.get_current_execution_policy",
                return_value=None,
            ),
            patch(
                "tools.approval.get_current_execution_policy_revision",
                return_value=-1,
            ),
            patch("model_tools.registry.dispatch") as dispatch,
            patch("elevate_cli.plugins.invoke_hook", return_value=[]),
        ):
            result = handle_function_call(
                "terminal",
                {"command": "echo blocked"},
                session_id="session-beta",
                tool_call_id="call-beta",
                skip_pre_tool_call_hook=True,
            )

        # Terminal is hard-denied before durable identity evaluation in the
        # Realtor Beta; no command shape may reach the terminal classifier.
        assert json.loads(result)["shadow_status"] == "effect_policy_block"
        dispatch.assert_not_called()

    @pytest.mark.parametrize(
        ("tool_name", "tool_args"),
        _EXACT_BETA_MUTATING_REGISTRY_CALLS,
        ids=[name for name, _args in _EXACT_BETA_MUTATING_REGISTRY_CALLS],
    )
    def test_exact_beta_named_mutator_missing_identity_never_uses_legacy_dispatch(
        self,
        monkeypatch,
        tool_name,
        tool_args,
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        with (
            patch("tools.approval.get_current_execution_policy", return_value=None),
            patch("tools.approval.get_current_execution_policy_revision", return_value=None),
            patch("model_tools.registry.dispatch") as dispatch,
            patch("elevate_cli.plugins.get_pre_tool_call_block_message") as pre_hook,
            patch("elevate_cli.plugins.invoke_hook", return_value=[]) as hooks,
            patch("tools.file_tools.notify_other_tool_call") as tracker,
        ):
            result = handle_function_call(
                tool_name,
                tool_args,
                session_id="session-beta",
                tool_call_id="call-beta",
            )

        assert json.loads(result)["shadow_status"] == "effect_context_block"
        dispatch.assert_not_called()
        pre_hook.assert_not_called()
        hooks.assert_not_called()
        tracker.assert_not_called()

    def test_stable_terminal_missing_identity_retains_legacy_fallback(
        self,
        monkeypatch,
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        with (
            patch(
                "tools.approval.get_current_execution_policy",
                return_value=None,
            ),
            patch(
                "tools.approval.get_current_execution_policy_revision",
                return_value=-1,
            ),
            patch(
                "model_tools.registry.dispatch",
                return_value='{"legacy":true}',
            ) as dispatch,
            patch("elevate_cli.plugins.invoke_hook", return_value=[]),
        ):
            result = handle_function_call(
                "terminal",
                {"command": "echo stable"},
                session_id="session-stable",
                tool_call_id="call-stable",
                skip_pre_tool_call_hook=True,
            )

        assert result == '{"legacy":true}'
        dispatch.assert_called_once()

    def test_unknown_tool_with_durable_identity_preserves_legacy_output(self):
        policy = ExecutionPolicy.for_mode("accepted-unknown", "read_only")
        token = set_current_execution_policy(policy, policy_revision=1)
        try:
            with (
                patch("model_tools.registry.execute_shadow") as execute_shadow,
                patch("elevate_cli.plugins.invoke_hook", return_value=[]),
            ):
                result = handle_function_call(
                    "totally_fake_durable_tool",
                    {},
                    task_id="task-unknown",
                    session_id="session-unknown",
                    tool_call_id="call-unknown",
                    skip_pre_tool_call_hook=True,
                )
        finally:
            reset_current_execution_policy(token)

        assert result == '{"error": "Unknown tool: totally_fake_durable_tool"}'
        execute_shadow.assert_not_called()

    @pytest.mark.parametrize(
        ("function_args", "task_id", "expected_status"),
        [
            ({"opaque": object()}, "task-input", "invalid_arguments"),
            ({}, object(), "invalid_handler_context"),
        ],
        ids=["non-json-arguments", "non-json-handler-context"],
    )
    def test_durable_shadow_rejects_non_json_invocation_before_handler(
        self,
        function_args,
        task_id,
        expected_status,
    ):
        tool_name = "_test_shadow_strict_model_input"
        calls = []
        registry.register(
            tool_name,
            "test-shadow",
            {
                "name": tool_name,
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            },
            lambda args, **kwargs: calls.append((args, kwargs)) or "unexpected",
            effects={"read"},
        )
        policy = ExecutionPolicy.for_mode("accepted-strict", "read_only")
        token = set_current_execution_policy(policy, policy_revision=3)
        try:
            with patch("elevate_cli.plugins.invoke_hook", return_value=[]):
                result = handle_function_call(
                    tool_name,
                    function_args,
                    task_id=task_id,
                    session_id="session-strict",
                    tool_call_id="call-strict",
                    skip_pre_tool_call_hook=True,
                )
        finally:
            reset_current_execution_policy(token)
            registry.deregister(tool_name)

        assert calls == []
        assert json.loads(result)["shadow_status"] == expected_status

    def test_complete_durable_identity_routes_shadow_with_hook_output_parity(self):
        policy = ExecutionPolicy.for_mode(
            "accepted-turn-1",
            ExecutionPolicyMode.READ_ONLY,
        )
        authorization = SimpleNamespace(allowed=True, reason="allowed")
        outcome = SimpleNamespace(
            prepared=SimpleNamespace(authorization=authorization),
            result='{"original":true}',
            started=True,
        )
        hook_calls = []

        def invoke_hook(hook_name, **kwargs):
            hook_calls.append((hook_name, kwargs))
            if hook_name == "transform_tool_result":
                return ['{"transformed":true}']
            return []

        token = set_current_execution_policy(policy, policy_revision=7)
        try:
            with (
                patch("model_tools.registry.execute_shadow", return_value=outcome) as shadow,
                patch(
                    "model_tools.registry.dispatch",
                    side_effect=AssertionError("legacy dispatch must not run"),
                ),
                patch("elevate_cli.plugins.invoke_hook", side_effect=invoke_hook),
            ):
                result = handle_function_call(
                    "web_search",
                    {"q": "listing"},
                    task_id="task-1",
                    session_id="session-1",
                    tool_call_id="call-1",
                    user_task="research the listing",
                    skip_pre_tool_call_hook=True,
                )
        finally:
            reset_current_execution_policy(token)

        assert result == '{"transformed":true}'
        shadow.assert_called_once_with(
            "web_search",
            {"q": "listing"},
            context=ToolCallContext(
                session_id="session-1",
                invocation_id="call-1",
                accepted_turn_id="accepted-turn-1",
                policy_revision=7,
            ),
            execution_policy=policy,
            handler_kwargs={
                "task_id": "task-1",
                "user_task": "research the listing",
            },
        )
        assert [name for name, _kwargs in hook_calls] == [
            "pre_tool_call",
            "post_tool_call",
            "transform_tool_result",
        ]
        assert hook_calls[1][1]["result"] == '{"original":true}'
        assert hook_calls[2][1]["result"] == '{"original":true}'

    def test_execute_code_shadow_binds_enabled_tools_not_user_task(self):
        policy = ExecutionPolicy.for_mode("accepted-code", "read_only")
        outcome = SimpleNamespace(
            prepared=SimpleNamespace(
                authorization=SimpleNamespace(allowed=True, reason="allowed")
            ),
            result={"_multimodal": True},
            started=True,
        )
        token = set_current_execution_policy(policy, policy_revision=2)
        try:
            with (
                patch("model_tools.registry.execute_shadow", return_value=outcome) as shadow,
                patch("elevate_cli.plugins.invoke_hook", return_value=[]),
            ):
                result = handle_function_call(
                    "execute_code",
                    {"code": "result = 1"},
                    task_id="task-code",
                    session_id="session-code",
                    tool_call_id="call-code",
                    user_task="must not reach handler context",
                    enabled_tools=["read_file", "skills_list"],
                    skip_pre_tool_call_hook=True,
                )
        finally:
            reset_current_execution_policy(token)

        assert result is outcome.result
        assert shadow.call_args.kwargs["handler_kwargs"] == {
            "task_id": "task-code",
            "enabled_tools": ["read_file", "skills_list"],
        }

    def test_denied_shadow_authorization_is_observed_but_still_executes(
        self,
        caplog,
    ):
        tool_name = "_test_shadow_denied_model_tool"
        calls = []

        def handler(args, **kwargs):
            calls.append((args, kwargs))
            return {"raw": "result"}

        registry.register(
            tool_name,
            "test-shadow",
            {
                "name": tool_name,
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            },
            handler,
            effects={"write_external:crm"},
        )
        policy = ExecutionPolicy.for_mode("accepted-denied", "read_only")
        token = set_current_execution_policy(policy, policy_revision=11)
        try:
            with (
                caplog.at_level(logging.INFO, logger="model_tools"),
                patch("elevate_cli.plugins.invoke_hook", return_value=[]),
            ):
                result = handle_function_call(
                    tool_name,
                    {"record": "123"},
                    task_id="task-denied",
                    session_id="session-denied",
                    tool_call_id="call-denied",
                    skip_pre_tool_call_hook=True,
                )
        finally:
            reset_current_execution_policy(token)
            registry.deregister(tool_name)

        assert result == {"raw": "result"}
        assert calls == [
            (
                {"record": "123"},
                {"task_id": "task-denied", "user_task": None},
            )
        ]
        assert "allowed=false" in caplog.text
        assert "effect_not_allowed" in caplog.text
        assert "enforcement=false" in caplog.text

    @pytest.mark.parametrize(
        ("tool_name", "tool_args"),
        _EXACT_BETA_MUTATING_REGISTRY_CALLS,
        ids=[name for name, _args in _EXACT_BETA_MUTATING_REGISTRY_CALLS],
    )
    def test_exact_beta_named_mutator_with_durable_identity_never_starts_handler(
        self,
        monkeypatch,
        tool_name,
        tool_args,
    ):
        entry = registry.get_entry(tool_name)
        assert entry is not None, f"installed registry tool missing: {tool_name}"
        calls = []
        monkeypatch.setattr(
            entry,
            "handler",
            lambda args, **kwargs: calls.append((args, kwargs)) or "unexpected",
        )
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = ExecutionPolicy.for_mode("accepted-beta-mutator", "read_only")
        token = set_current_execution_policy(policy, policy_revision=19)
        try:
            with (
                patch("elevate_cli.plugins.get_pre_tool_call_block_message") as pre_hook,
                patch("elevate_cli.plugins.invoke_hook", return_value=[]) as hooks,
                patch("tools.file_tools.notify_other_tool_call") as tracker,
            ):
                result = handle_function_call(
                    tool_name,
                    tool_args,
                    task_id="task-beta",
                    session_id="session-beta",
                    tool_call_id="call-beta",
                )
        finally:
            reset_current_execution_policy(token)

        assert json.loads(result)["shadow_status"] == "effect_policy_block"
        assert calls == []
        pre_hook.assert_not_called()
        hooks.assert_not_called()
        tracker.assert_not_called()

    def test_exact_beta_unknown_tool_runs_no_hooks_tracker_or_handler(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = ExecutionPolicy.for_mode("accepted-beta-unknown", "read_only")
        token = set_current_execution_policy(policy, policy_revision=20)
        try:
            with (
                patch("model_tools.registry.dispatch") as dispatch,
                patch("elevate_cli.plugins.get_pre_tool_call_block_message") as pre_hook,
                patch("elevate_cli.plugins.invoke_hook", return_value=[]) as hooks,
                patch("tools.file_tools.notify_other_tool_call") as tracker,
            ):
                result = handle_function_call(
                    "unknown_beta_mutator",
                    {"action": "mutate"},
                    task_id="task-beta",
                    session_id="session-beta",
                    tool_call_id="call-beta-unknown",
                )
        finally:
            reset_current_execution_policy(token)

        assert json.loads(result)["shadow_status"] == "effect_policy_block"
        dispatch.assert_not_called()
        pre_hook.assert_not_called()
        hooks.assert_not_called()
        tracker.assert_not_called()

    def test_exact_beta_stale_registration_after_preflight_runs_no_observers(
        self,
        monkeypatch,
    ):
        tool_name = "_test_beta_stale_after_preflight"
        original_calls = []
        replacement_calls = []
        registry.register(
            tool_name,
            "test-shadow",
            {
                "name": tool_name,
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            },
            lambda args, **kwargs: original_calls.append((args, kwargs)) or "old",
            effects={"read"},
        )
        real_prepare = registry.prepare_shadow

        def prepare_then_replace(*args, **kwargs):
            prepared = real_prepare(*args, **kwargs)
            registry.register(
                tool_name,
                "test-shadow",
                {
                    "name": tool_name,
                    "description": "replacement",
                    "parameters": {"type": "object", "properties": {}},
                },
                lambda call_args, **call_kwargs: replacement_calls.append(
                    (call_args, call_kwargs)
                ) or "new",
                effects={"read"},
            )
            return prepared

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = ExecutionPolicy.for_mode("accepted-beta-stale", "read_only")
        token = set_current_execution_policy(policy, policy_revision=21)
        try:
            with (
                patch.object(registry, "prepare_shadow", side_effect=prepare_then_replace),
                patch("elevate_cli.plugins.get_pre_tool_call_block_message") as pre_hook,
                patch("elevate_cli.plugins.invoke_hook", return_value=[]) as hooks,
                patch("tools.file_tools.notify_other_tool_call") as tracker,
            ):
                result = handle_function_call(
                    tool_name,
                    {},
                    task_id="task-beta",
                    session_id="session-beta",
                    tool_call_id="call-beta-stale",
                )
        finally:
            reset_current_execution_policy(token)
            registry.deregister(tool_name)

        assert json.loads(result)["shadow_status"] == "stale_registration"
        assert original_calls == []
        assert replacement_calls == []
        pre_hook.assert_not_called()
        hooks.assert_not_called()
        tracker.assert_not_called()


# =========================================================================
# Agent loop tools
# =========================================================================

class TestAgentLoopTools:
    def test_expected_tools_in_set(self):
        assert "todo" in _AGENT_LOOP_TOOLS
        assert "memory" in _AGENT_LOOP_TOOLS
        assert "session_search" in _AGENT_LOOP_TOOLS
        assert "delegate_task" in _AGENT_LOOP_TOOLS

    def test_no_regular_tools_in_set(self):
        assert "web_search" not in _AGENT_LOOP_TOOLS
        assert "terminal" not in _AGENT_LOOP_TOOLS


class TestToolDefinitionContainment:
    def test_disabled_toolsets_subtract_from_explicit_enabled_toolsets(
        self,
        monkeypatch,
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)

        definitions = get_tool_definitions(
            enabled_toolsets=["file", "messaging"],
            disabled_toolsets=["messaging"],
            quiet_mode=True,
        )
        names = {tool["function"]["name"] for tool in definitions}

        assert "read_file" in names
        assert "send_message" not in names

    def test_exact_beta_advertises_only_effect_declared_registry_tools(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

        definitions = get_tool_definitions(
            enabled_toolsets=[
                "deals_overview",
                "file",
                "lead_status",
                "messaging",
                "skills",
                "terminal",
            ],
            quiet_mode=True,
        )
        names = {tool["function"]["name"] for tool in definitions}

        assert {"deals_overview", "skills_list"} <= names

        # lead_status is now effect-declared: its ``show`` action resolves to an
        # exact read:leads over connect_ready_read_only, so Beta advertises it.
        # The schema being visible does NOT grant writes — every mutating action
        # still resolves to ``unknown`` and is denied under a read-only policy,
        # so the declaration expands what the model can *read*, never what it can
        # mutate under a restricted cohort.
        from tools.approval import authorize_effects

        assert "lead_status" in names
        read_only = ExecutionPolicy.for_mode(
            "turn-beta-advertise-check", ExecutionPolicyMode.READ_ONLY
        )
        for write_action in ("set", "heat", "follow_up", "classify"):
            resolved = registry.resolve_effects(
                "lead_status", {"action": write_action, "contact_id": "c"}
            )
            assert authorize_effects(read_only, resolved).allowed is False

        # Still-undeclared tools must never leak into the Beta surface.
        # (send_message is declared but its messaging check_fn fails in the
        # unconfigured test profile, so it stays out here too.)
        assert not {
            "write_file",
            "patch",
            "send_message",
            "skill_manage",
            "skill_view",
        }.intersection(names)
        assert all(registry.get_effect_metadata(name)["declared"] for name in names)

    def test_tool_definition_cache_is_release_channel_scoped(
        self,
        monkeypatch,
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        stable_names = {
            tool["function"]["name"]
            for tool in get_tool_definitions(
                enabled_toolsets=["file"],
                quiet_mode=True,
            )
        }
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        beta_names = {
            tool["function"]["name"]
            for tool in get_tool_definitions(
                enabled_toolsets=["file"],
                quiet_mode=True,
            )
        }

        assert "write_file" in stable_names
        # The file toolset now exposes two effect-declared reads — read_file and
        # search_files both declare an exact read:files — so a read-only Beta
        # advertises exactly those, while the still-UNKNOWN mutating file tools
        # (write_file/patch) never leak into the restricted surface. The channels
        # therefore still resolve to different sets (release-channel scoping).
        assert beta_names == {"read_file", "search_files"}
        assert not {"write_file", "patch"}.intersection(beta_names)
        assert beta_names != stable_names
        assert all(
            registry.get_effect_metadata(name)["declared"] for name in beta_names
        )


# =========================================================================
# Pre-tool-call blocking via plugin hooks
# =========================================================================

class TestPreToolCallBlocking:
    """Verify that pre_tool_call hooks can block tool execution."""

    def test_blocked_tool_returns_error_and_skips_dispatch(self, monkeypatch):
        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [{"action": "block", "message": "Blocked by policy"}]
            return []

        dispatch_called = False
        _orig_dispatch = None

        def fake_dispatch(*args, **kwargs):
            nonlocal dispatch_called
            dispatch_called = True
            raise AssertionError("dispatch should not run when blocked")

        monkeypatch.setattr("elevate_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("model_tools.registry.dispatch", fake_dispatch)

        result = json.loads(handle_function_call("read_file", {"path": "test.txt"}, task_id="t1"))
        assert result == {"error": "Blocked by policy"}
        assert not dispatch_called

    def test_blocked_tool_skips_read_loop_notification(self, monkeypatch):
        notifications = []

        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [{"action": "block", "message": "Blocked"}]
            return []

        monkeypatch.setattr("elevate_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("model_tools.registry.dispatch",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not run")))
        monkeypatch.setattr("tools.file_tools.notify_other_tool_call",
                            lambda task_id: notifications.append(task_id))

        result = json.loads(handle_function_call("web_search", {"q": "test"}, task_id="t1"))
        assert result == {"error": "Blocked"}
        assert notifications == []

    def test_invalid_hook_returns_do_not_block(self, monkeypatch):
        """Malformed hook returns should be ignored — tool executes normally."""
        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [
                    "block",
                    {"action": "block"},           # missing message
                    {"action": "deny", "message": "nope"},
                ]
            return []

        monkeypatch.setattr("elevate_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("model_tools.registry.dispatch",
                            lambda *a, **kw: json.dumps({"ok": True}))

        result = json.loads(handle_function_call("read_file", {"path": "test.txt"}, task_id="t1"))
        assert result == {"ok": True}

    def test_skip_flag_prevents_double_block_check(self, monkeypatch):
        """When skip_pre_tool_call_hook=True, blocking is not checked (caller did it)."""
        hook_calls = []

        def fake_invoke_hook(hook_name, **kwargs):
            hook_calls.append(hook_name)
            return []

        monkeypatch.setattr("elevate_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("model_tools.registry.dispatch",
                            lambda *a, **kw: json.dumps({"ok": True}))

        handle_function_call("web_search", {"q": "test"}, task_id="t1",
                             skip_pre_tool_call_hook=True)

        # Hook still fires for observer notification, but get_pre_tool_call_block_message
        # is not called — invoke_hook fires directly in the skip=True branch.
        assert "pre_tool_call" in hook_calls
        assert "post_tool_call" in hook_calls


# =========================================================================
# Legacy toolset map
# =========================================================================

class TestLegacyToolsetMap:
    def test_expected_legacy_names(self):
        expected = [
            "web_tools", "terminal_tools", "vision_tools", "moa_tools",
            "image_tools", "skills_tools", "browser_tools", "cronjob_tools",
            "rl_tools", "file_tools", "tts_tools",
        ]
        for name in expected:
            assert name in _LEGACY_TOOLSET_MAP, f"Missing legacy toolset: {name}"

    def test_values_are_lists_of_strings(self):
        for name, tools in _LEGACY_TOOLSET_MAP.items():
            assert isinstance(tools, list), f"{name} is not a list"
            for tool in tools:
                assert isinstance(tool, str), f"{name} contains non-string: {tool}"


# =========================================================================
# Backward-compat wrappers
# =========================================================================

class TestBackwardCompat:
    def test_get_all_tool_names_returns_list(self):
        names = get_all_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        # Should contain well-known tools
        assert "web_search" in names
        assert "terminal" in names

    def test_get_toolset_for_tool(self):
        result = get_toolset_for_tool("web_search")
        assert result is not None
        assert isinstance(result, str)

    def test_get_toolset_for_unknown_tool(self):
        result = get_toolset_for_tool("totally_nonexistent_tool")
        assert result is None

    def test_tool_to_toolset_map(self):
        assert isinstance(TOOL_TO_TOOLSET_MAP, dict)
        assert len(TOOL_TO_TOOLSET_MAP) > 0


# =========================================================================
# Agent-owned registry routing adapter (ERB-406)
# =========================================================================

class TestDispatchAgentOwnedRegistryTool:
    """The adapter agent special-case branches use to reach the registry
    shadow boundary must preserve legacy result payloads for callers."""

    def test_unknown_tool_keeps_exact_legacy_payload(self):
        import json as _json

        from model_tools import dispatch_agent_owned_registry_tool

        result = _json.loads(
            dispatch_agent_owned_registry_tool(
                "totally_nonexistent_tool",
                {"anything": 1},
                task_id="task-x",
                session_id="session-x",
                tool_call_id="call-x",
            )
        )
        assert result == {"error": "Unknown tool: totally_nonexistent_tool"}

    def test_registered_tool_result_matches_legacy_dispatch(self):
        from model_tools import dispatch_agent_owned_registry_tool
        from tools.registry import registry

        name = "_test_agent_owned_adapter_tool"
        calls = []
        registry.register(
            name=name,
            toolset="_test-agent-owned-adapter",
            schema={
                "name": name,
                "description": "adapter parity tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args, **kwargs: calls.append((args, kwargs))
            or '{"ok": true}',
        )
        try:
            result = dispatch_agent_owned_registry_tool(
                name,
                {"value": 3},
                task_id="task-adapter",
                session_id="session-adapter",
                tool_call_id="call-adapter",
            )
        finally:
            registry.deregister(name)

        assert result == '{"ok": true}'
        assert len(calls) == 1
        assert calls[0][0] == {"value": 3}
