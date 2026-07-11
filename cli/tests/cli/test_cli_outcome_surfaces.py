import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cli as cli_module


FAILURE_SENTINELS = [
    {"partial": True},
    {"interrupted": True},
    {"error": "provider failed"},
    {"completed": False},
]


@pytest.mark.parametrize(
    "sentinel",
    FAILURE_SENTINELS,
)
def test_quiet_single_query_exits_nonzero_for_every_failure_sentinel(
    monkeypatch, sentinel
):
    result = {
        "final_response": "The run did not complete.",
        "completed": True,
        **sentinel,
    }
    agent = SimpleNamespace(
        quiet_mode=False,
        suppress_status_output=False,
        stream_delta_callback=None,
        tool_gen_callback=None,
        session_id="session-1",
        run_conversation=lambda **kwargs: result,
    )

    class DummyCLI:
        def __init__(self, **kwargs):
            self.session_id = "session-1"
            self.system_prompt = ""
            self.preloaded_skills = []
            self.tool_progress_mode = "all"
            self.conversation_history = []
            self._active_agent_route_signature = "route"
            self.agent = agent

        def _ensure_runtime_credentials(self):
            return True

        def _resolve_turn_agent_config(self, _query):
            return {"signature": "route", "model": "test", "runtime": {}}

        def _init_agent(self, **kwargs):
            return True

    monkeypatch.setattr(cli_module, "ElevateCLI", DummyCLI)

    with pytest.raises(SystemExit) as exc:
        cli_module.main(query="test", quiet=True, toolsets="file")

    assert exc.value.code == 1


@pytest.mark.parametrize("sentinel", FAILURE_SENTINELS)
def test_normal_single_query_exits_nonzero_for_every_failure_sentinel(
    monkeypatch, sentinel
):
    result = {
        "final_response": "The run did not complete.",
        "completed": True,
        **sentinel,
    }

    class DummyCLI:
        def __init__(self, **kwargs):
            self.console = MagicMock()
            self._last_agent_result = None

        def show_banner(self):
            pass

        def chat(self, _query, images=None):
            self._last_agent_result = result
            return result["final_response"]

        def _print_exit_summary(self):
            pass

    monkeypatch.setattr(cli_module, "ElevateCLI", DummyCLI)

    with pytest.raises(SystemExit) as exc:
        cli_module.main(query="test", quiet=False, toolsets="file")

    assert exc.value.code == 1


def test_terminal_background_prints_failed_marker_and_skips_success_bell(
    monkeypatch, capsys
):
    cli = cli_module.ElevateCLI.__new__(cli_module.ElevateCLI)
    cli._background_tasks = {}
    cli._background_task_counter = 0
    cli._app = None
    cli._agent_running = False
    cli._spinner_text = ""
    cli.max_turns = 5
    cli.enabled_toolsets = []
    cli._session_db = None
    cli.reasoning_config = None
    cli.service_tier = None
    cli._providers_only = None
    cli._providers_ignore = None
    cli._providers_order = None
    cli._provider_sort = None
    cli._provider_require_params = None
    cli._provider_data_collection = None
    cli._fallback_model = None
    cli.final_response_markdown = False
    cli.bell_on_complete = True
    cli._ensure_runtime_credentials = lambda: True
    cli._resolve_turn_agent_config = lambda _prompt: {
        "model": "test",
        "runtime": {},
        "request_overrides": None,
    }
    cli._invalidate = lambda **kwargs: None

    agent = MagicMock()
    agent.run_conversation.return_value = {
        "final_response": "The task failed after retries.",
        "failed": True,
        "completed": False,
    }
    monkeypatch.setattr(cli_module, "AIAgent", lambda **kwargs: agent)

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(cli_module.threading, "Thread", ImmediateThread)
    rendered = []
    monkeypatch.setattr(cli_module, "_cprint", rendered.append)
    monkeypatch.setattr(cli_module, "ChatConsole", lambda: MagicMock())

    cli._handle_background_command("/background finish the task")

    assert any("❌ Background task #1 failed" in line for line in rendered)
    assert not any("✅ Background task #1 complete" in line for line in rendered)
    assert "\a" not in capsys.readouterr().out


def test_terminal_btw_preserves_partial_under_incomplete_heading_and_skips_bell(
    monkeypatch, capsys
):
    cli = cli_module.ElevateCLI.__new__(cli_module.ElevateCLI)
    cli._app = None
    cli.conversation_history = []
    cli.reasoning_config = None
    cli.service_tier = None
    cli._providers_only = None
    cli._providers_ignore = None
    cli._providers_order = None
    cli._provider_sort = None
    cli._provider_require_params = None
    cli._provider_data_collection = None
    cli._fallback_model = None
    cli.final_response_markdown = False
    cli.bell_on_complete = True
    cli._ensure_runtime_credentials = lambda: True
    cli._resolve_turn_agent_config = lambda _question: {
        "model": "test",
        "runtime": {},
        "request_overrides": None,
    }
    cli._invalidate = lambda **kwargs: None

    agent = MagicMock()
    agent.run_conversation.return_value = {
        "final_response": "Partial lead summary",
        "partial": True,
        "completed": False,
        "error": "deadline exceeded",
    }
    monkeypatch.setattr(cli_module, "AIAgent", lambda **kwargs: agent)

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    panels = []
    monkeypatch.setattr(cli_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        cli_module, "_render_final_assistant_content", lambda content, mode: content
    )
    monkeypatch.setattr(
        cli_module,
        "Panel",
        lambda content, **kwargs: panels.append((content, kwargs)) or "panel",
    )
    monkeypatch.setattr(cli_module, "ChatConsole", lambda: MagicMock())
    monkeypatch.setattr(cli_module.time, "sleep", lambda _seconds: None)

    cli._handle_btw_command("/btw check the leads")

    assert panels
    content, panel_kwargs = panels[-1]
    assert "Partial lead summary" in str(content)
    assert "deadline exceeded" in str(content)
    assert "incomplete" in panel_kwargs["title"]
    assert "\a" not in capsys.readouterr().out


def test_foreground_chat_failure_skips_success_bell(monkeypatch, capsys):
    result = {
        "final_response": "Partial answer",
        "partial": True,
        "completed": False,
        "api_calls": 1,
        "messages": [],
    }
    cli = cli_module.ElevateCLI.__new__(cli_module.ElevateCLI)
    cli.session_id = "session-1"
    cli.conversation_history = []
    cli.agent = SimpleNamespace(
        session_id="session-1",
        max_iterations=150,
        run_conversation=lambda **kwargs: result,
    )
    cli._active_agent_route_signature = "route"
    cli._ensure_runtime_credentials = lambda: True
    cli._resolve_turn_agent_config = lambda _message: {
        "signature": "route",
        "model": "test",
        "runtime": {},
        "request_overrides": None,
    }
    cli._init_agent = lambda **kwargs: True
    cli._reset_stream_state = lambda: None
    cli._flush_stream = lambda: None
    cli._invalidate = lambda **kwargs: None
    cli._interrupt_queue = queue.Queue()
    cli._pending_input = queue.Queue()
    cli._clarify_state = None
    cli._clarify_freetext = None
    cli._voice_tts = False
    cli._voice_mode = False
    cli._voice_continuous = False
    cli._session_db = None
    cli.show_reasoning = False
    cli.final_response_markdown = False
    cli.bell_on_complete = True
    cli._stream_started = False
    cli._stream_box_opened = False

    panels = []
    monkeypatch.setattr(cli_module, "ChatConsole", lambda: MagicMock())
    monkeypatch.setattr(
        cli_module, "_render_final_assistant_content", lambda content, mode: content
    )
    monkeypatch.setattr(
        cli_module,
        "Panel",
        lambda content, **kwargs: panels.append((content, kwargs)) or "panel",
    )
    monkeypatch.setattr(cli_module.time, "sleep", lambda _seconds: None)

    assert cli.chat("test") == "Partial answer"
    assert cli._last_agent_result is result
    assert panels
    content, panel_kwargs = panels[-1]
    assert "Partial answer" in str(content)
    assert "incomplete" in panel_kwargs["title"]
    assert "▲ Elevate" not in panel_kwargs["title"]
    assert "\a" not in capsys.readouterr().out
