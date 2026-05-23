"""Tests for the session race guard that prevents concurrent agent runs.

The sentinel-based guard ensures that when _handle_message passes the
"is an agent already running?" check and proceeds to the slow async
setup path (vision enrichment, STT, hooks, session hygiene), a second
message for the same session is correctly recognized as "already running"
and routed through the interrupt/queue path instead of spawning a
duplicate agent.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType, merge_pending_message_event
from gateway.run import GatewayRunner, _AGENT_PENDING_SENTINEL
from gateway.session import SessionSource, build_session_key


class _FakeAdapter:
    """Minimal adapter stub for testing."""

    def __init__(self):
        self._pending_messages = {}
        self._active_sessions = {}
        self.interrupted_sessions = []

    async def send(self, chat_id, text, **kwargs):
        pass

    async def interrupt_session_activity(self, session_key, chat_id):
        self.interrupted_sessions.append((session_key, chat_id))
        event = self._active_sessions.get(session_key)
        if event is not None:
            event.set()


def _make_runner():
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    runner.adapters = {Platform.TELEGRAM: _FakeAdapter()}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._session_run_generation = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._voice_mode = {}
    runner._background_tasks = set()
    runner._draining = False
    runner._restart_requested = False
    runner._restart_task_started = False
    runner._restart_detached = False
    runner._restart_via_service = False
    runner._restart_drain_timeout = 0.0
    runner._stop_task = None
    runner._exit_code = None
    runner._update_runtime_status = MagicMock()
    runner._is_user_authorized = lambda _source: True
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.session_store = MagicMock()
    runner.delivery_router = MagicMock()
    return runner


def _make_event(text="hello", chat_id="12345"):
    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id=chat_id, chat_type="dm",
        user_id="u1",
    )
    return MessageEvent(text=text, message_type=MessageType.TEXT, source=source)


# ------------------------------------------------------------------
# Test 1: Sentinel is placed before _handle_message_with_agent runs
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sentinel_placed_before_agent_setup():
    """After passing the 'not running' guard, the sentinel must be
    written into _running_agents *before* any await, so that a
    concurrent message sees the session as occupied."""
    runner = _make_runner()
    event = _make_event()
    session_key = build_session_key(event.source)

    # Patch _handle_message_with_agent to capture state at entry
    sentinel_was_set = False

    async def mock_inner(self_inner, ev, src, qk, generation):
        nonlocal sentinel_was_set
        sentinel_was_set = runner._running_agents.get(qk) is _AGENT_PENDING_SENTINEL
        return "ok"

    with patch.object(GatewayRunner, "_handle_message_with_agent", mock_inner):
        await runner._handle_message(event)

    assert sentinel_was_set, (
        "Sentinel must be in _running_agents when _handle_message_with_agent starts"
    )


# ------------------------------------------------------------------
# Test 2: Sentinel is cleaned up after _handle_message_with_agent
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sentinel_cleaned_up_after_handler_returns():
    """If _handle_message_with_agent returns normally, the sentinel
    must be removed so the session is not permanently locked."""
    runner = _make_runner()
    event = _make_event()
    session_key = build_session_key(event.source)

    async def mock_inner(self_inner, ev, src, qk, generation):
        return "ok"

    with patch.object(GatewayRunner, "_handle_message_with_agent", mock_inner):
        await runner._handle_message(event)

    assert session_key not in runner._running_agents, (
        "Sentinel must be removed after handler completes"
    )


# ------------------------------------------------------------------
# Test 3: Sentinel cleaned up on exception
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sentinel_cleaned_up_on_exception():
    """If _handle_message_with_agent raises, the sentinel must still
    be cleaned up so the session is not permanently locked."""
    runner = _make_runner()
    event = _make_event()
    session_key = build_session_key(event.source)

    async def mock_inner(self_inner, ev, src, qk, generation):
        raise RuntimeError("boom")

    with patch.object(GatewayRunner, "_handle_message_with_agent", mock_inner):
        with pytest.raises(RuntimeError, match="boom"):
            await runner._handle_message(event)

    assert session_key not in runner._running_agents, (
        "Sentinel must be removed even if handler raises"
    )


# ------------------------------------------------------------------
# Test 4: Second message during sentinel sees "already running"
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_second_message_during_sentinel_queued_not_duplicate():
    """While the sentinel is set (agent setup in progress), a second
    message for the same session must hit the 'already running' branch
    and be queued — not start a second agent."""
    runner = _make_runner()
    event1 = _make_event(text="first message")
    event2 = _make_event(text="second message")
    session_key = build_session_key(event1.source)

    barrier = asyncio.Event()

    async def slow_inner(self_inner, ev, src, qk, generation):
        # Simulate slow setup — wait until test tells us to proceed
        await barrier.wait()
        return "ok"

    with patch.object(GatewayRunner, "_handle_message_with_agent", slow_inner):
        # Start first message (will block at barrier)
        task1 = asyncio.create_task(runner._handle_message(event1))
        # Yield so task1 enters slow_inner and sentinel is set
        await asyncio.sleep(0)

        # Verify sentinel is set
        assert runner._running_agents.get(session_key) is _AGENT_PENDING_SENTINEL

        # Second message should see "already running" and be queued
        result2 = await runner._handle_message(event2)
        assert result2 is None, "Second message should return None (queued)"

        # The second message should have been queued in adapter pending
        adapter = runner.adapters[Platform.TELEGRAM]
        assert session_key in adapter._pending_messages, (
            "Second message should be queued as pending"
        )
        assert adapter._pending_messages[session_key] is event2

        # Let first message complete
        barrier.set()
        await task1


def test_merge_pending_message_event_merges_text_and_photo_followups():
    pending = {}
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="12345",
        chat_type="dm",
        user_id="u1",
    )
    session_key = build_session_key(source)

    text_event = MessageEvent(
        text="first follow-up",
        message_type=MessageType.TEXT,
        source=source,
    )
    photo_event = MessageEvent(
        text="see screenshot",
        message_type=MessageType.PHOTO,
        source=source,
        media_urls=["/tmp/test.png"],
        media_types=["image/png"],
    )

    merge_pending_message_event(pending, session_key, text_event, merge_text=True)
    merge_pending_message_event(pending, session_key, photo_event, merge_text=True)

    merged = pending[session_key]
    assert merged.message_type == MessageType.PHOTO
    assert merged.text == "first follow-up\n\nsee screenshot"
    assert merged.media_urls == ["/tmp/test.png"]
    assert merged.media_types == ["image/png"]


@pytest.mark.asyncio
async def test_recent_telegram_text_followup_is_queued_without_interrupt():
    runner = _make_runner()
    event = _make_event(text="follow-up")
    session_key = build_session_key(event.source)

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    import time as _time
    runner._running_agents_ts[session_key] = _time.time()

    result = await runner._handle_message(event)

    assert result is None
    fake_agent.interrupt.assert_not_called()
    adapter = runner.adapters[Platform.TELEGRAM]
    assert adapter._pending_messages[session_key].text == "follow-up"


@pytest.mark.asyncio
async def test_recent_telegram_followups_append_in_pending_queue():
    runner = _make_runner()
    first = _make_event(text="part one")
    second = _make_event(text="part two")
    session_key = build_session_key(first.source)

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    import time as _time
    runner._running_agents_ts[session_key] = _time.time()

    await runner._handle_message(first)
    await runner._handle_message(second)

    fake_agent.interrupt.assert_not_called()
    adapter = runner.adapters[Platform.TELEGRAM]
    assert adapter._pending_messages[session_key].text == "part one\npart two"


# ------------------------------------------------------------------
# Test 5: Sentinel not placed for command messages
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_messages_do_not_leave_sentinel():
    """Slash commands (/help, /status, etc.) return early from
    _handle_message.  They must NOT leave a sentinel behind."""
    runner = _make_runner()
    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm",
        user_id="u1",
    )
    event = MessageEvent(
        text="/help", message_type=MessageType.TEXT, source=source
    )
    session_key = build_session_key(source)

    # Mock the help handler to avoid needing full runner setup
    runner._handle_help_command = AsyncMock(return_value="Help text")
    # Need hooks for command emission
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()

    await runner._handle_message(event)

    assert session_key not in runner._running_agents, (
        "Command handlers must not leave sentinel in _running_agents"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command_text", "handler_attr", "handler_result"),
    [
        ("/help", "_handle_help_command", "Help text"),
        ("/commands", "_handle_commands_command", "Commands text"),
        ("/update", "_handle_update_command", "Update text"),
        ("/profile", "_handle_profile_command", "Profile text"),
    ],
)
async def test_active_session_bypass_commands_dispatch_without_interrupt(
    command_text,
    handler_attr,
    handler_result,
):
    """Gateway-handled bypass commands must return directly while an agent runs."""
    runner = _make_runner()
    event = _make_event(text=command_text)
    session_key = build_session_key(event.source)

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    setattr(runner, handler_attr, AsyncMock(return_value=handler_result))

    result = await runner._handle_message(event)

    assert result == handler_result
    fake_agent.interrupt.assert_not_called()
    assert session_key not in runner.adapters[Platform.TELEGRAM]._pending_messages


@pytest.mark.asyncio
async def test_status_question_during_running_agent_does_not_interrupt_or_queue():
    """Natural status questions should answer from gateway state mid-run."""
    runner = _make_runner()
    event = _make_event(text="what exactly are you doing")
    session_key = build_session_key(event.source)

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {
        "api_call_count": 22,
        "max_iterations": 60,
        "current_tool": "terminal",
        "last_activity_desc": "terminal",
        "seconds_since_activity": 1,
    }
    runner._running_agents[session_key] = fake_agent

    result = await runner._handle_message(event)

    assert result is not None
    assert "still running" in result
    assert "not interrupting" in result
    fake_agent.interrupt.assert_not_called()
    assert session_key not in runner.adapters[Platform.TELEGRAM]._pending_messages


def test_telegram_default_uses_configured_tool_profile():
    runner = _make_runner()
    cfg = {"platform_toolsets": {"telegram": ["elevate-telegram"]}}

    toolsets = runner._resolve_gateway_enabled_toolsets(
        cfg,
        "telegram",
        "what should I do next",
    )

    assert {"terminal", "file", "delegation", "code_execution"}.issubset(set(toolsets))
    assert {"memory", "messaging", "session_search", "todo"}.issubset(set(toolsets))


def test_telegram_auto_mode_cma_message_escalates_to_skill_runner_profile():
    runner = _make_runner()
    cfg = {
        "agent": {"gateway_tool_profile": "auto"},
        "platform_toolsets": {"telegram": ["elevate-telegram"]},
    }

    toolsets = runner._resolve_gateway_enabled_toolsets(
        cfg,
        "telegram",
        "run the cma skill for 1872 red tail crescent",
    )

    assert {"skills", "terminal", "file", "todo"}.issubset(set(toolsets))
    assert "browser" not in toolsets
    assert "web" not in toolsets
    assert "cronjob" not in toolsets
    assert "image_gen" not in toolsets


def test_explicit_platform_tool_config_is_respected():
    runner = _make_runner()
    # known_builtin_toolsets records the builtin set known at the last
    # `elevate tools` save. Supplying it (all configurable keys) disables the
    # self-heal auto-enable so the explicit ["web", "terminal"] allowlist is
    # honored exactly — the state a real saved config is in.
    from elevate_cli.tools_config import CONFIGURABLE_TOOLSETS
    _all_builtin = [name for name, _, _ in CONFIGURABLE_TOOLSETS]
    cfg = {
        "platform_toolsets": {"telegram": ["web", "terminal"]},
        "known_builtin_toolsets": {"telegram": _all_builtin},
    }

    toolsets = runner._resolve_gateway_enabled_toolsets(
        cfg,
        "telegram",
        "what should I do next",
    )

    # Explicit allowlist is honored for configurable keys; non-configurable
    # platform-default toolsets (e.g. admin_profile on telegram) get recovered
    # by _get_platform_tools so they stay available even after an explicit save.
    assert {"terminal", "web"}.issubset(set(toolsets))
    # No other CONFIGURABLE toolsets sneak in via self-heal.
    from elevate_cli.tools_config import CONFIGURABLE_TOOLSETS
    configurable_keys = {n for n, _, _ in CONFIGURABLE_TOOLSETS}
    assert set(toolsets) & configurable_keys == {"terminal", "web"}


def test_repeated_skill_view_history_is_compacted():
    content = "CMA instructions\n" + ("x" * 5000)
    payload = {
        "success": True,
        "name": "cma",
        "content": content,
        "path": "cma/SKILL.md",
        "skill_dir": "/tmp/skills/cma",
    }
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "skill_view", "arguments": "{\"name\":\"cma\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": __import__("json").dumps(payload)},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_2",
                    "function": {"name": "skill_view", "arguments": "{\"name\":\"cma\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": __import__("json").dumps(payload)},
    ]

    compacted = GatewayRunner._compact_repeated_skill_view_history(history)

    assert len(compacted[1]["content"]) > 5000
    assert len(compacted[3]["content"]) < 1000
    assert "cached_duplicate" in compacted[3]["content"]


# ------------------------------------------------------------------
# Test 6: /stop during sentinel force-cleans and unlocks session
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_during_sentinel_force_cleans_session():
    """If /stop arrives while the sentinel is set (agent still starting),
    it should force-clean the sentinel and unlock the session."""
    runner = _make_runner()
    event1 = _make_event(text="hello")
    session_key = build_session_key(event1.source)

    barrier = asyncio.Event()

    async def slow_inner(self_inner, ev, src, qk, generation):
        await barrier.wait()
        return "ok"

    with patch.object(GatewayRunner, "_handle_message_with_agent", slow_inner):
        task1 = asyncio.create_task(runner._handle_message(event1))
        await asyncio.sleep(0)

        # Sentinel should be set
        assert runner._running_agents.get(session_key) is _AGENT_PENDING_SENTINEL

        # Send /stop — should force-clean the sentinel
        stop_event = _make_event(text="/stop")
        result = await runner._handle_message(stop_event)
        assert result is not None, "/stop during sentinel should return a message"
        assert "stopped" in result.lower()
        assert session_key not in runner._running_agents, (
            "/stop must remove sentinel so the session is unlocked"
        )

        # Should NOT be queued as pending
        adapter = runner.adapters[Platform.TELEGRAM]
        assert session_key not in adapter._pending_messages

        barrier.set()
        await task1


# ------------------------------------------------------------------
# Test 6b: /stop hard-kills a running agent and unlocks session
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_hard_kills_running_agent():
    """When /stop arrives while a real agent is running, it must:
    1. Call interrupt() on the agent
    2. Force-clean _running_agents to unlock the session
    3. Return a confirmation message
    This fixes the bug where a hung agent kept the session locked
    forever — showing 'writing...' but never producing output."""
    runner = _make_runner()
    session_key = build_session_key(
        SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    )

    # Simulate a running (possibly hung) agent
    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    runner.adapters[Platform.TELEGRAM]._active_sessions[session_key] = asyncio.Event()

    # Send /stop
    stop_event = _make_event(text="/stop")
    result = await runner._handle_message(stop_event)

    # Agent must have been interrupted
    fake_agent.interrupt.assert_called_once_with("Stop requested")

    # Session must be unlocked
    assert session_key not in runner._running_agents, (
        "/stop must remove the agent from _running_agents so the session is unlocked"
    )
    assert runner.adapters[Platform.TELEGRAM].interrupted_sessions == [
        (session_key, "12345")
    ]
    assert runner.adapters[Platform.TELEGRAM]._active_sessions[session_key].is_set()

    # Must return a confirmation
    assert result is not None
    assert "stopped" in result.lower()


@pytest.mark.asyncio
async def test_stop_evicts_cached_agent_resources():
    """Hard stop should evict cached agent/tool resources for that session."""
    from collections import OrderedDict
    import threading

    runner = _make_runner()
    session_key = build_session_key(
        SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    )

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    runner._agent_cache = OrderedDict({session_key: (fake_agent, "sig")})
    runner._agent_cache_lock = threading.Lock()
    runner._cleanup_agent_resources = MagicMock()

    stop_event = _make_event(text="/stop")
    result = await runner._handle_message(stop_event)

    assert result is not None
    assert "stopped" in result.lower()
    runner._cleanup_agent_resources.assert_called_once_with(fake_agent)
    assert session_key not in runner._agent_cache


# ------------------------------------------------------------------
# Test 6c: /stop clears pending messages to prevent stale replays
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_clears_pending_messages():
    """When /stop hard-kills a running agent, any pending messages
    queued during the run must be discarded."""
    runner = _make_runner()
    session_key = build_session_key(
        SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    )

    fake_agent = MagicMock()
    fake_agent.get_activity_summary.return_value = {"seconds_since_activity": 0}
    runner._running_agents[session_key] = fake_agent
    runner._pending_messages[session_key] = "some queued text"

    # Queue a pending message in the adapter too
    adapter = runner.adapters[Platform.TELEGRAM]
    adapter._pending_messages[session_key] = _make_event(text="queued")
    adapter.get_pending_message = MagicMock(return_value=_make_event(text="queued"))
    adapter.has_pending_interrupt = MagicMock(return_value=False)

    stop_event = _make_event(text="/stop")
    await runner._handle_message(stop_event)

    # Pending messages must be cleared
    assert session_key not in runner._pending_messages
    adapter.get_pending_message.assert_called_once_with(session_key)


# ------------------------------------------------------------------
# Test 7: Shutdown skips sentinel entries
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shutdown_skips_sentinel():
    """During gateway shutdown, sentinel entries in _running_agents
    should be skipped without raising AttributeError."""
    runner = _make_runner()
    session_key = "telegram:dm:99999"

    # Simulate a sentinel in _running_agents
    runner._running_agents[session_key] = _AGENT_PENDING_SENTINEL

    # Also add a real agent mock to verify it still gets interrupted
    real_agent = MagicMock()
    runner._running_agents["telegram:dm:88888"] = real_agent

    runner.adapters = {}  # No adapters to disconnect
    runner._running = True
    runner._shutdown_event = asyncio.Event()
    runner._exit_reason = None
    runner._shutdown_all_gateway_honcho = lambda: None

    with patch("gateway.status.remove_pid_file"), \
         patch("gateway.status.write_runtime_status"):
        await runner.stop()

    # Real agent should have been interrupted
    real_agent.interrupt.assert_called_once()
    # Should not have raised on the sentinel
