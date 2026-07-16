"""Adversarial exact-Realtor-Beta containment tests for modular tool dispatch.

These tests deliberately exercise the extracted sequential and concurrent
executors.  A synthetic denial must create one model-visible tool result while
remaining physically inert: no handler or observer may confuse authorization
with a tool having actually started.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.agent_runtime_helpers import invoke_tool
from agent.subdirectory_hints import SubdirectoryHintTracker
from agent.tool_executor import (
    execute_tool_calls_concurrent,
    execute_tool_calls_sequential,
)
from agent.tool_guardrails import ToolCallGuardrailController
from model_tools import get_tool_definitions
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry


_DENIED_TOOL = "_test_exact_beta_denied_containment"
_STALE_TOOL = "_test_exact_beta_stale_containment"
_UNKNOWN_TOOL = "_test_exact_beta_unknown_containment"
_TOOLSET = "_test-exact-beta-containment"
_SCHEMA = {
    "description": "Exact Beta containment test tool",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    },
}
_AGENTS_MARKER = "NEVER-INJECT-EXACT-BETA-DENIAL"


def _tool_call(name: str, arguments: dict, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, sort_keys=True),
        ),
    )


def _assistant_message(*tool_calls: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content="", tool_calls=list(tool_calls))


class _ByteSentinel:
    """Disk-backed tripwire used by every forbidden observer and handler."""

    _BASELINE = b'{"state":"byte-identical-before-tool-dispatch"}\n'

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[str] = []
        self.path.write_bytes(self._BASELINE)

    @property
    def before(self) -> bytes:
        return self._BASELINE

    def hit(self, source: str) -> None:
        self.calls.append(source)
        self.path.write_bytes(f"mutated-by:{source}\n".encode())


def _tripwire(sentinel: _ByteSentinel, source: str, result=None):
    def _called(*_args, **_kwargs):
        sentinel.hit(source)
        return result

    return MagicMock(side_effect=_called)


class _ContainmentAgent:
    """Small production-shaped agent surface required by tool_executor.py."""

    def __init__(self, tmp_path: Path, sentinel: _ByteSentinel) -> None:
        self.session_id = "session-exact-beta-containment"
        self._interrupt_requested = False
        self.log_prefix = ""
        self.log_prefix_chars = 200
        self.quiet_mode = True
        self.verbose_logging = False
        self.tool_delay = 0
        self.valid_tool_names = {_DENIED_TOOL, _STALE_TOOL, "terminal"}
        self.context_compressor = SimpleNamespace(context_length=128_000)

        # These values are intentionally non-default so an executor that merely
        # clears state for a denied call is caught as a mutation.
        self._current_tool = "pre-existing-current-tool"
        self._turns_since_memory = 17
        self._iters_since_skill = 19
        self._tool_worker_threads: set[int] = set()
        self._tool_worker_threads_lock = threading.Lock()

        self._tool_guardrails = ToolCallGuardrailController()
        self._guardrail_block_result = _tripwire(
            sentinel, "guardrail_block_result", '{"unexpected":true}'
        )
        self._append_guardrail_observation = MagicMock(
            side_effect=lambda _name, _args, result, **_kwargs: (
                sentinel.hit("guardrail_after_call") or result
            )
        )
        self._record_file_mutation_result = _tripwire(
            sentinel, "file_mutation_verifier"
        )
        self._touch_activity = _tripwire(sentinel, "activity")

        self.tool_progress_callback = _tripwire(sentinel, "progress_callback")
        self.tool_start_callback = _tripwire(sentinel, "start_callback")
        self.tool_complete_callback = _tripwire(sentinel, "complete_callback")

        checkpoint = SimpleNamespace(enabled=True)
        checkpoint.get_working_dir_for_path = _tripwire(
            sentinel, "checkpoint_path", str(tmp_path)
        )
        checkpoint.ensure_checkpoint = _tripwire(
            sentinel, "checkpoint_create", True
        )
        self._checkpoint_mgr = checkpoint

        self._subdirectory_hints = SubdirectoryHintTracker(
            working_dir=str(tmp_path)
        )
        self._subdirectory_hints.check_tool_call = MagicMock(
            wraps=self._subdirectory_hints.check_tool_call
        )
        self._initial_hint_dirs = frozenset(self._subdirectory_hints._loaded_dirs)

        self._tool_result_content_for_active_model = MagicMock(
            side_effect=lambda _name, result: result
        )
        # Steering is model-input bookkeeping, not a physical tool observer.
        self._apply_pending_steer_to_tool_results = MagicMock()
        self._should_emit_quiet_tool_messages = lambda: False
        self._should_start_quiet_spinner = lambda: False
        self._print_fn = lambda *_args, **_kwargs: None
        self._safe_print = lambda *_args, **_kwargs: None
        self._vprint = lambda *_args, **_kwargs: None
        self._wrap_verbose = lambda _prefix, value: value

        self._memory_manager = None
        self._context_engine_tool_names: set[str] = set()
        self._todo_store = None
        self._memory_store = None
        self.clarify_callback = None
        self._dispatch_delegate_task = _tripwire(
            sentinel, "delegate_handler", '{"unexpected":true}'
        )
        self._get_session_db_for_recall = _tripwire(
            sentinel, "session_recall", None
        )
        self._build_memory_write_metadata = _tripwire(
            sentinel, "memory_metadata", {}
        )

        # Blocked tests replace this with a tripwire. Stale-registration tests
        # bind the real modular helper so all inner revalidation runs.
        self._invoke_tool = _tripwire(
            sentinel, "concurrent_invoke", '{"unexpected":true}'
        )

    def bind_real_invoke(self) -> None:
        self._invoke_tool = lambda *args, **kwargs: invoke_tool(
            self, *args, **kwargs
        )


@contextmanager
def _forbidden_runtime_observers(sentinel: _ByteSentinel):
    """Install tripwires around process-wide handlers and observer seams."""

    def persist_tripwire(*_args, **kwargs):
        sentinel.hit("result_persistence")
        return kwargs.get("content", _args[0] if _args else "")

    with (
        patch(
            "agent.tool_executor.maybe_persist_tool_result",
            MagicMock(side_effect=persist_tripwire),
        ) as persistence,
        patch(
            "elevate_cli.plugins.get_pre_tool_call_block_message",
            _tripwire(sentinel, "plugin_pre_hook", None),
        ) as pre_hook,
        patch(
            "elevate_cli.plugins.invoke_hook",
            _tripwire(sentinel, "plugin_hook", []),
        ) as plugin_hook,
        patch(
            "tools.file_tools.notify_other_tool_call",
            _tripwire(sentinel, "read_loop_tracker", None),
        ) as read_loop_tracker,
    ):
        yield SimpleNamespace(
            persistence=persistence,
            pre_hook=pre_hook,
            plugin_hook=plugin_hook,
            read_loop_tracker=read_loop_tracker,
        )


def _run_executor(
    mode: str,
    agent: _ContainmentAgent,
    assistant_message: SimpleNamespace,
    messages: list[dict],
) -> None:
    executor = {
        "sequential": execute_tool_calls_sequential,
        "concurrent": execute_tool_calls_concurrent,
    }[mode]
    executor(agent, assistant_message, messages, "task-exact-beta-containment")


def _assert_inert_boundary(
    agent: _ContainmentAgent,
    sentinel: _ByteSentinel,
    observers: SimpleNamespace,
) -> None:
    assert sentinel.path.read_bytes() == sentinel.before
    assert sentinel.calls == []
    assert agent._current_tool == "pre-existing-current-tool"
    assert agent._turns_since_memory == 17
    assert agent._iters_since_skill == 19
    assert agent._tool_worker_threads == set()

    agent._checkpoint_mgr.get_working_dir_for_path.assert_not_called()
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._subdirectory_hints.check_tool_call.assert_not_called()
    assert frozenset(agent._subdirectory_hints._loaded_dirs) == agent._initial_hint_dirs
    agent._record_file_mutation_result.assert_not_called()
    agent._append_guardrail_observation.assert_not_called()
    agent._touch_activity.assert_not_called()
    agent.tool_progress_callback.assert_not_called()
    agent.tool_start_callback.assert_not_called()
    agent.tool_complete_callback.assert_not_called()
    observers.persistence.assert_not_called()
    observers.pre_hook.assert_not_called()
    observers.plugin_hook.assert_not_called()
    observers.read_loop_tracker.assert_not_called()


def _assert_one_denial_per_call(
    messages: list[dict],
    calls: list[SimpleNamespace],
    *,
    expected_status: str,
) -> None:
    assert len(messages) == len(calls)
    assert [message["tool_call_id"] for message in messages] == [
        call.id for call in calls
    ]
    for message, call in zip(messages, calls):
        assert message["role"] == "tool"
        assert message["name"] == call.function.name
        assert _AGENTS_MARKER not in message["content"]
        payload = json.loads(message["content"])
        assert payload["shadow_status"] == expected_status
        assert isinstance(payload.get("error"), str) and payload["error"]


@pytest.fixture
def exact_beta_read_policy(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    policy = ExecutionPolicy.for_mode(
        "accepted-turn-exact-beta-containment", "read_only"
    )
    token = set_current_execution_policy(policy, policy_revision=41)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


@pytest.fixture
def containment_tools():
    """Register one denied tool and clean up every synthetic registration."""

    registry.register(
        _DENIED_TOOL,
        _TOOLSET,
        {"name": _DENIED_TOOL, **_SCHEMA},
        lambda _args, **_kwargs: '{"unexpected":true}',
        effects={"write_local:test"},
    )
    try:
        yield
    finally:
        registry.deregister(_DENIED_TOOL)
        registry.deregister(_STALE_TOOL)
        registry.deregister(_UNKNOWN_TOOL)


@pytest.mark.parametrize("mode", ["sequential", "concurrent"])
def test_denied_and_unknown_batch_has_only_model_denials(
    mode,
    tmp_path,
    exact_beta_read_policy,
    containment_tools,
):
    child = tmp_path / "listing-files"
    child.mkdir()
    (child / "AGENTS.md").write_text(_AGENTS_MARKER, encoding="utf-8")
    target = child / "offer.pdf"
    calls = [
        _tool_call(_DENIED_TOOL, {"path": str(target)}, "call-denied"),
        _tool_call(_UNKNOWN_TOOL, {"path": str(target)}, "call-unknown"),
    ]
    sentinel = _ByteSentinel(tmp_path / "dispatch-sentinel.bin")
    agent = _ContainmentAgent(tmp_path, sentinel)
    messages: list[dict] = []

    with _forbidden_runtime_observers(sentinel) as observers:
        _run_executor(mode, agent, _assistant_message(*calls), messages)

    _assert_one_denial_per_call(
        messages,
        calls,
        expected_status="effect_policy_block",
    )
    _assert_inert_boundary(agent, sentinel, observers)
    agent._invoke_tool.assert_not_called()


@pytest.mark.parametrize("mode", ["sequential", "concurrent"])
def test_stale_registration_nonstart_has_no_physical_tool_effects(
    mode,
    tmp_path,
    monkeypatch,
    exact_beta_read_policy,
    containment_tools,
):
    child = tmp_path / "transaction"
    child.mkdir()
    (child / "AGENTS.md").write_text(_AGENTS_MARKER, encoding="utf-8")
    target = child / "contract.pdf"
    sentinel = _ByteSentinel(tmp_path / "stale-sentinel.bin")
    handler = _tripwire(sentinel, "stale_handler", '{"unexpected":true}')
    registry.register(
        _STALE_TOOL,
        _TOOLSET,
        {"name": _STALE_TOOL, **_SCHEMA},
        handler,
        effects={"read"},
    )

    real_prepare = registry.prepare_shadow
    preparation_count = 0

    def replace_after_every_preparation(*args, **kwargs):
        nonlocal preparation_count
        prepared = real_prepare(*args, **kwargs)
        if args and args[0] == _STALE_TOOL:
            preparation_count += 1
            registry.register(
                _STALE_TOOL,
                _TOOLSET,
                {"name": _STALE_TOOL, **_SCHEMA},
                handler,
                effects={"read"},
            )
        return prepared

    monkeypatch.setattr(
        registry,
        "prepare_shadow",
        replace_after_every_preparation,
    )
    call = _tool_call(_STALE_TOOL, {"path": str(target)}, "call-stale")
    agent = _ContainmentAgent(tmp_path, sentinel)
    agent.bind_real_invoke()
    messages: list[dict] = []

    with _forbidden_runtime_observers(sentinel) as observers:
        _run_executor(mode, agent, _assistant_message(call), messages)

    _assert_one_denial_per_call(
        messages,
        [call],
        expected_status="stale_registration",
    )
    assert preparation_count >= 2
    handler.assert_not_called()
    _assert_inert_boundary(agent, sentinel, observers)


_TERMINAL_FABRICATIONS = [
    pytest.param({"command": "./ls -la"}, id="relative-basename"),
    pytest.param({"command": "/tmp/attacker/ls -la"}, id="absolute-attacker-path"),
    pytest.param(
        {"command": "PATH=/tmp/attacker:$PATH ls -la"},
        id="path-shadow",
    ),
    pytest.param(
        {"command": "ln -sf /bin/sh /tmp/ls && /tmp/ls -c 'touch /tmp/pwned'"},
        id="symlink-executable",
    ),
    pytest.param(
        {"command": "diff --output=/tmp/leak before after"},
        id="write-capable-flag",
    ),
    pytest.param(
        {"command": "find . -fprintf /tmp/files '%p\\n'"},
        id="alternate-write-flag",
    ),
    pytest.param(
        {"command": "ls -la", "background": True},
        id="background",
    ),
    pytest.param(
        {"command": "ls -la", "pty": True},
        id="pty",
    ),
    pytest.param(
        {
            "command": "ls -la",
            "background": True,
            "notify_on_complete": True,
        },
        id="notify-on-complete",
    ),
]


def test_exact_beta_never_advertises_terminal(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    definitions = get_tool_definitions(
        enabled_toolsets=["terminal_tools"],
        quiet_mode=True,
    )

    assert "terminal" not in {
        definition["function"]["name"] for definition in definitions
    }


def test_stable_terminal_surface_remains_legacy(monkeypatch):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    definitions = get_tool_definitions(
        enabled_toolsets=["terminal_tools"],
        quiet_mode=True,
    )

    assert "terminal" in {
        definition["function"]["name"] for definition in definitions
    }


@pytest.mark.parametrize("mode", ["sequential", "concurrent"])
@pytest.mark.parametrize("terminal_args", _TERMINAL_FABRICATIONS)
def test_fabricated_terminal_call_is_inert_in_exact_beta(
    mode,
    terminal_args,
    tmp_path,
    exact_beta_read_policy,
):
    child = tmp_path / "terminal-workdir"
    child.mkdir()
    (child / "AGENTS.md").write_text(_AGENTS_MARKER, encoding="utf-8")
    arguments = {**terminal_args, "workdir": str(child)}
    call = _tool_call("terminal", arguments, "call-terminal")
    sentinel = _ByteSentinel(tmp_path / "terminal-sentinel.bin")
    agent = _ContainmentAgent(tmp_path, sentinel)
    messages: list[dict] = []

    with (
        _forbidden_runtime_observers(sentinel) as observers,
        patch(
            "tools.terminal_tool.terminal_tool",
            _tripwire(sentinel, "terminal_handler", '{"unexpected":true}'),
        ) as terminal_handler,
    ):
        _run_executor(mode, agent, _assistant_message(call), messages)

    _assert_one_denial_per_call(
        messages,
        [call],
        expected_status="effect_policy_block",
    )
    assert "shell surface is not available" in json.loads(
        messages[0]["content"]
    )["error"]
    terminal_handler.assert_not_called()
    _assert_inert_boundary(agent, sentinel, observers)
    agent._invoke_tool.assert_not_called()
