import json
import os
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

from tui_gateway import server


class _ChunkyStdout:
    def __init__(self):
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        for ch in text:
            self.parts.append(ch)
            time.sleep(0.0001)
        return len(text)

    def flush(self) -> None:
        return None


class _BrokenStdout:
    def write(self, text: str) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        return None


def test_write_json_serializes_concurrent_writes(monkeypatch):
    out = _ChunkyStdout()
    monkeypatch.setattr(server, "_real_stdout", out)

    threads = [
        threading.Thread(target=server.write_json, args=({"seq": i, "text": "x" * 24},))
        for i in range(8)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    lines = "".join(out.parts).splitlines()

    assert len(lines) == 8
    assert {json.loads(line)["seq"] for line in lines} == set(range(8))


def test_write_json_returns_false_on_broken_pipe(monkeypatch):
    monkeypatch.setattr(server, "_real_stdout", _BrokenStdout())

    assert server.write_json({"ok": True}) is False


def test_status_callback_emits_kind_and_text():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("context_pressure", "85% to compaction")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "context_pressure", "text": "85% to compaction"},
    )


def test_status_callback_accepts_single_message_argument():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("thinking...")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "status", "text": "thinking..."},
    )


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        **extra,
    }


def test_config_set_yolo_toggles_session_scope():
    from tools.approval import clear_session, is_session_yolo_enabled

    server._sessions["sid"] = _session()
    try:
        resp_on = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_on["result"]["value"] == "1"
        assert is_session_yolo_enabled("session-key") is True

        resp_off = server.handle_request(
            {
                "id": "2",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_off["result"]["value"] == "0"
        assert is_session_yolo_enabled("session-key") is False
    finally:
        clear_session("session-key")
        server._sessions.clear()


def test_config_get_statusbar_survives_non_dict_display(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"display": "broken"})

    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "statusbar"}}
    )

    assert resp["result"]["value"] == "top"


def test_config_set_statusbar_survives_non_dict_display(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"display": "broken"}))
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "statusbar", "value": "bottom"},
        }
    )

    assert resp["result"]["value"] == "bottom"
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["tui_statusbar"] == "bottom"


def test_config_set_section_writes_per_section_override(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": "hidden"},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": "hidden"}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"activity": "hidden"}


def test_config_set_section_clears_override_on_empty_value(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"display": {"sections": {"activity": "hidden", "tools": "expanded"}}}
        )
    )
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": ""},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": ""}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"tools": "expanded"}


def test_config_set_section_rejects_unknown_section_or_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    bad_section = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.bogus", "value": "hidden"},
        }
    )
    assert bad_section["error"]["code"] == 4002

    bad_mode = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"key": "details_mode.tools", "value": "maximised"},
        }
    )
    assert bad_mode["error"]["code"] == 4002


def test_enable_gateway_prompts_sets_gateway_env(monkeypatch):
    monkeypatch.delenv("ELEVATE_EXEC_ASK", raising=False)
    monkeypatch.delenv("ELEVATE_GATEWAY_SESSION", raising=False)
    monkeypatch.delenv("ELEVATE_INTERACTIVE", raising=False)

    server._enable_gateway_prompts()

    assert server.os.environ["ELEVATE_GATEWAY_SESSION"] == "1"
    assert server.os.environ["ELEVATE_EXEC_ASK"] == "1"
    assert server.os.environ["ELEVATE_INTERACTIVE"] == "1"


def test_setup_status_reports_provider_config(monkeypatch):
    monkeypatch.setattr("elevate_cli.main._has_any_provider_configured", lambda: False)

    resp = server.handle_request({"id": "1", "method": "setup.status", "params": {}})

    assert resp["result"]["provider_configured"] is False


def test_config_set_reasoning_updates_live_session_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)
    agent = types.SimpleNamespace(reasoning_config=None)
    server._sessions["sid"] = _session(agent=agent)

    resp_effort = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "low"},
        }
    )
    assert resp_effort["result"]["value"] == "low"
    assert agent.reasoning_config == {"enabled": True, "effort": "low"}

    resp_show = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "show"},
        }
    )
    assert resp_show["result"]["value"] == "show"
    assert server._sessions["sid"]["show_reasoning"] is True


def test_config_set_verbose_updates_session_mode_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)
    agent = types.SimpleNamespace(verbose_logging=False)
    server._sessions["sid"] = _session(agent=agent)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "verbose", "value": "cycle"},
        }
    )

    assert resp["result"]["value"] == "verbose"
    assert server._sessions["sid"]["tool_progress_mode"] == "verbose"
    assert agent.verbose_logging is True


def test_config_set_model_uses_live_switch_path(monkeypatch):
    server._sessions["sid"] = _session()
    seen = {}

    def _fake_apply(sid, session, raw):
        seen["args"] = (sid, session["session_key"], raw)
        return {"value": "new/model", "warning": "catalog unreachable"}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "model", "value": "new/model"},
        }
    )

    assert resp["result"]["value"] == "new/model"
    assert resp["result"]["warning"] == "catalog unreachable"
    assert seen["args"] == ("sid", "session-key", "new/model")


def test_config_set_model_global_persists(monkeypatch):
    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-old"

        def switch_model(self, **kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="anthropic/claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-new",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )
    seen = {}
    saved = {}

    def _switch_model(**kwargs):
        seen.update(kwargs)
        return result

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr("elevate_cli.model_switch.switch_model", _switch_model)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr("elevate_cli.config.save_config", lambda cfg: saved.update(cfg))

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {
                "session_id": "sid",
                "key": "model",
                "value": "anthropic/claude-sonnet-4.6 --global",
            },
        }
    )

    assert resp["result"]["value"] == "anthropic/claude-sonnet-4.6"
    assert seen["is_global"] is True
    assert saved["model"]["default"] == "anthropic/claude-sonnet-4.6"
    assert saved["model"]["provider"] == "anthropic"
    assert saved["model"]["base_url"] == "https://api.anthropic.com"


def test_config_set_model_syncs_inference_provider_env(monkeypatch):
    """After an explicit provider switch, ELEVATE_INFERENCE_PROVIDER must
    reflect the user's choice so ambient re-resolution (credential pool
    refresh, aux clients) picks up the new provider instead of the original
    one persisted in config or shell env.

    Regression: a TUI user switched openrouter → anthropic and the TUI kept
    trying openrouter because the env-var-backed resolvers still saw the old
    provider.
    """

    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-or"

        def switch_model(self, **_kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-ant",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setattr(
        "elevate_cli.model_switch.switch_model", lambda **_kwargs: result
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {
                "session_id": "sid",
                "key": "model",
                "value": "claude-sonnet-4.6 --provider anthropic",
            },
        }
    )

    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "anthropic"


def test_config_set_personality_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "personality", "value": "bogus"},
        }
    )

    assert "error" in resp
    assert "Unknown personality" in resp["error"]["message"]


def test_config_set_personality_resets_history_and_returns_info(monkeypatch):
    session = _session(
        agent=types.SimpleNamespace(),
        history=[{"role": "user", "text": "hi"}],
        history_version=4,
    )
    new_agent = types.SimpleNamespace(model="x")
    emits = []

    server._sessions["sid"] = session
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    monkeypatch.setattr(
        server, "_make_agent", lambda sid, key, session_id=None: new_agent
    )
    monkeypatch.setattr(
        server, "_session_info", lambda agent: {"model": getattr(agent, "model", "?")}
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
    monkeypatch.setattr(server, "_write_config_key", lambda path, value: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "personality", "value": "helpful"},
        }
    )

    assert resp["result"]["history_reset"] is True
    assert resp["result"]["info"] == {"model": "x"}
    assert session["history"] == []
    assert session["history_version"] == 5
    assert ("session.info", "sid", {"model": "x"}) in emits


def test_direct_compress_persists_and_emits_pill(monkeypatch):
    """Manual /compress must (1) emit the 'Compacting context' pill before the
    blocking summary and 'Session compacted' after, and (2) PERSIST the
    compressed history — _compress_context rotates to a fresh empty session, so
    without an explicit flush the compress is lost on resume (the "compressed
    twice" bug)."""
    original = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    compressed = [
        {"role": "user", "content": "summary"},
        {"role": "user", "content": "m7"},
    ]
    persisted = []

    agent = types.SimpleNamespace(
        compression_enabled=True,
        _cached_system_prompt="sys",
        session_id="rotated-session",  # differs from session_key → rotation path
        _compress_context=lambda *a, **k: (compressed, "sys"),
        _persist_session=lambda msgs, hist: persisted.append(list(msgs)),
    )
    session = _session(agent=agent, session_key="old-session")
    session["history"] = list(original)
    server._sessions["dsid"] = session

    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda _s: None)
    emitted = []
    try:
        with patch(
            "tui_gateway.server._emit",
            side_effect=lambda ev, s, p=None: emitted.append((ev, p)),
        ):
            out = server._run_direct_compress_slash("dsid", session, "")
    finally:
        server._sessions.pop("dsid", None)

    # Compressed history was persisted into the rotated session.
    assert persisted == [compressed]
    # In-memory history + session_key both moved to the compressed/rotated state.
    assert session["history"] == compressed
    assert session["session_key"] == "rotated-session"
    # Pill on before, off after.
    status_texts = [p.get("text") for (ev, p) in emitted if ev == "status"]
    assert "Compacting context" in status_texts
    assert "Session compacted" in status_texts
    assert status_texts.index("Compacting context") < status_texts.index(
        "Session compacted"
    )
    # Result card still reports the numbers.
    assert "Compressed" in out or "messages" in out


def test_session_compress_uses_compress_helper(monkeypatch):
    agent = types.SimpleNamespace()
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server,
        "_compress_session_history",
        lambda session, focus_topic=None: (2, {"total": 42}),
    )
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})

    with patch("tui_gateway.server._emit") as emit:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )

    assert resp["result"]["removed"] == 2
    assert resp["result"]["usage"]["total"] == 42
    emit.assert_called_once_with("session.info", "sid", {"model": "x"})


def test_prompt_submit_sets_approval_session_key(monkeypatch):
    from tools.approval import get_current_session_key

    captured = {}

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            captured["session_key"] = get_current_session_key(default="")
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "ping"},
        }
    )

    assert resp["result"]["status"] == "streaming"
    assert captured["session_key"] == "session-key"


def test_prompt_submit_expands_context_refs(monkeypatch):
    captured = {}

    class _Agent:
        model = "test/model"
        base_url = ""
        api_key = ""

        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            captured["prompt"] = prompt
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    fake_ctx = types.ModuleType("agent.context_references")
    fake_ctx.preprocess_context_references = (
        lambda message, **kwargs: types.SimpleNamespace(
            blocked=False,
            message="expanded prompt",
            warnings=[],
            references=[],
            injected_tokens=0,
        )
    )
    fake_meta = types.ModuleType("agent.model_metadata")
    fake_meta.get_model_context_length = lambda *args, **kwargs: 100000

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setitem(sys.modules, "agent.context_references", fake_ctx)
    monkeypatch.setitem(sys.modules, "agent.model_metadata", fake_meta)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "@diff"},
        }
    )

    assert captured["prompt"] == "expanded prompt"


def test_prompt_submit_forwards_persist_user_message(monkeypatch):
    captured = {}

    class _Agent:
        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
            persist_user_message=None,
            **kwargs,
        ):
            captured["prompt"] = prompt
            captured["persist_user_message"] = persist_user_message
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {
                "session_id": "sid",
                "text": "[hub context]\n\nUser request: open it",
                "persist_user_message": "open it",
            },
        }
    )

    assert captured == {
        "prompt": "[hub context]\n\nUser request: open it",
        "persist_user_message": "open it",
    }


def test_prompt_submit_releases_running_before_auto_title(monkeypatch):
    captured = {}

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    fake_title = types.ModuleType("agent.title_generator")

    def _maybe_auto_title(*args, **kwargs):
        captured["running_during_title"] = server._sessions["sid"]["running"]

    fake_title.maybe_auto_title = _maybe_auto_title

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setitem(sys.modules, "agent.title_generator", fake_title)

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "ping"},
            }
        )

        assert resp["result"]["status"] == "streaming"
        assert captured["running_during_title"] is False
        assert server._sessions["sid"]["running"] is False
    finally:
        server._sessions.pop("sid", None)


def test_image_attach_appends_local_image(monkeypatch):
    fake_cli = types.ModuleType("cli")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (raw, "")
    fake_cli._resolve_attachment_path = lambda raw: Path("/tmp/cat.png")

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["name"] == "cat.png"
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_image_attach_accepts_unquoted_screenshot_path_with_spaces(monkeypatch):
    screenshot = Path("/tmp/Screenshot 2026-04-21 at 1.04.43 PM.png")
    fake_cli = types.ModuleType("cli")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": screenshot,
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (
        "/tmp/Screenshot",
        "2026-04-21 at 1.04.43 PM.png",
    )
    fake_cli._resolve_attachment_path = lambda raw: None

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": str(screenshot)},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["path"] == str(screenshot)
    assert resp["result"]["remainder"] == ""
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_commands_catalog_surfaces_quick_commands(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {
            "quick_commands": {
                "build": {"type": "exec", "command": "npm run build"},
                "git": {"type": "alias", "target": "/shell git"},
                "notes": {
                    "type": "exec",
                    "command": "cat NOTES.md",
                    "description": "Open design notes",
                },
            }
        },
    )

    resp = server.handle_request(
        {"id": "1", "method": "commands.catalog", "params": {}}
    )

    pairs = dict(resp["result"]["pairs"])
    assert "npm run build" in pairs["/build"]
    assert pairs["/git"].startswith("alias →")
    assert pairs["/notes"] == "Open design notes"

    user_cat = next(
        c for c in resp["result"]["categories"] if c["name"] == "User commands"
    )
    user_pairs = dict(user_cat["pairs"])
    assert set(user_pairs) == {"/build", "/git", "/notes"}

    assert resp["result"]["canon"]["/build"] == "/build"
    assert resp["result"]["canon"]["/notes"] == "/notes"


def test_command_dispatch_exec_nonzero_surfaces_error(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"quick_commands": {"boom": {"type": "exec", "command": "boom"}}},
    )
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout="", stderr="failed"
        ),
    )

    resp = server.handle_request(
        {"id": "1", "method": "command.dispatch", "params": {"name": "boom"}}
    )

    assert "error" in resp
    assert "failed" in resp["error"]["message"]


def test_plugins_list_surfaces_loader_error(monkeypatch):
    with patch("elevate_cli.plugins.get_plugin_manager", side_effect=Exception("boom")):
        resp = server.handle_request(
            {"id": "1", "method": "plugins.list", "params": {}}
        )

    assert "error" in resp
    assert "boom" in resp["error"]["message"]


def test_complete_slash_surfaces_completer_error(monkeypatch):
    with patch(
        "elevate_cli.commands.SlashCommandCompleter",
        side_effect=Exception("no completer"),
    ):
        resp = server.handle_request(
            {"id": "1", "method": "complete.slash", "params": {"text": "/mo"}}
        )

    assert "error" in resp
    assert "no completer" in resp["error"]["message"]


def test_input_detect_drop_attaches_image(monkeypatch):
    fake_cli = types.ModuleType("cli")
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "input.detect_drop",
            "params": {"session_id": "sid", "text": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["matched"] is True
    assert resp["result"]["is_image"] is True
    assert resp["result"]["text"] == "[User attached image: cat.png]"


def test_rollback_restore_resolves_number_and_file_path():
    calls = {}

    class _Mgr:
        enabled = True

        def list_checkpoints(self, cwd):
            return [{"hash": "aaa111"}, {"hash": "bbb222"}]

        def restore(self, cwd, target, file_path=None):
            calls["args"] = (cwd, target, file_path)
            return {"success": True, "message": "done"}

    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(_checkpoint_mgr=_Mgr()), history=[]
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "rollback.restore",
            "params": {"session_id": "sid", "hash": "2", "file_path": "src/app.tsx"},
        }
    )

    assert resp["result"]["success"] is True
    assert calls["args"][1] == "bbb222"
    assert calls["args"][2] == "src/app.tsx"


# ── session.steer ────────────────────────────────────────────────────


def test_session_steer_calls_agent_steer_when_agent_supports_it():
    """The TUI RPC method must call agent.steer(text) and return a
    queued status without touching interrupt state.
    """
    calls = {}

    class _Agent:
        def steer(self, text):
            calls["steer_text"] = text
            return True

        def interrupt(self, *args, **kwargs):
            calls["interrupt_called"] = True

    server._sessions["sid"] = _session(agent=_Agent())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "also check auth.log"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "result" in resp, resp
    assert resp["result"]["status"] == "queued"
    assert resp["result"]["text"] == "also check auth.log"
    assert calls["steer_text"] == "also check auth.log"
    assert "interrupt_called" not in calls  # must NOT interrupt


def test_session_steer_rejects_empty_text():
    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(steer=lambda t: True)
    )
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "   "},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4002


def test_session_steer_errors_when_agent_has_no_steer_method():
    server._sessions["sid"] = _session(agent=types.SimpleNamespace())  # no steer()
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4010


def test_session_info_includes_mcp_servers(monkeypatch):
    fake_status = [
        {"name": "github", "transport": "http", "tools": 12, "connected": True},
        {"name": "filesystem", "transport": "stdio", "tools": 4, "connected": True},
        {"name": "broken", "transport": "stdio", "tools": 0, "connected": False},
    ]
    fake_mod = types.ModuleType("tools.mcp_tool")
    fake_mod.get_mcp_status = lambda: fake_status
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", fake_mod)

    info = server._session_info(types.SimpleNamespace(tools=[], model=""))

    assert info["mcp_servers"] == fake_status


# ---------------------------------------------------------------------------
# History-mutating commands must reject while session.running is True.
# Without these guards, prompt.submit's post-run history write either
# clobbers the mutation (version matches) or silently drops the agent's
# output (version mismatch) — both produce UI<->backend state desync.
# ---------------------------------------------------------------------------


def test_session_undo_rejects_while_running():
    """Fix for TUI silent-drop #1: /undo must not mutate history
    while the agent is mid-turn — would either clobber the undo or
    cause prompt.submit to silently drop the agent's response."""
    server._sessions["sid"] = _session(
        running=True,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("error"), "session.undo should reject while running"
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        # History must be unchanged
        assert len(server._sessions["sid"]["history"]) == 2
    finally:
        server._sessions.pop("sid", None)


def test_session_undo_allowed_when_idle():
    """Regression guard: when not running, /undo still works."""
    server._sessions["sid"] = _session(
        running=False,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"
        assert resp["result"]["removed"] == 2
        assert server._sessions["sid"]["history"] == []
    finally:
        server._sessions.pop("sid", None)


def test_session_compress_rejects_while_running(monkeypatch):
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_rollback_restore_rejects_full_history_while_running(monkeypatch):
    """Full-history rollback must reject; file-scoped rollback still allowed."""
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "rollback.restore",
                "params": {"session_id": "sid", "hash": "abc"},
            }
        )
        assert resp.get("error"), "full-history rollback should reject while running"
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_mismatch_surfaces_warning(monkeypatch):
    """Fix for TUI silent-drop #2: the defensive backstop at prompt.submit
    must attach a 'warning' to message.complete when history was
    mutated externally during the turn (instead of silently dropping
    the agent's output)."""
    # Agent bumps history_version itself mid-run to simulate an external
    # mutation slipping past the guards.
    session_ref = {"s": None}

    class _RacyAgent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            # Simulate: something external bumped history_version
            # while we were running.
            with session_ref["s"]["history_lock"]:
                session_ref["s"]["history_version"] += 1
            return {
                "final_response": "agent reply",
                "messages": [{"role": "assistant", "content": "agent reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_RacyAgent())
    session_ref["s"] = server._sessions["sid"]
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # History should NOT contain the agent's output (version mismatch)
        assert server._sessions["sid"]["history"] == []

        # message.complete must carry a 'warning' so the UI / operator
        # knows the output was not persisted.
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" in payload, (
            "message.complete must include a 'warning' field on "
            "history_version mismatch — otherwise the UI silently "
            "shows output that was never persisted"
        )
        assert (
            "not saved" in payload["warning"].lower()
            or "changed" in payload["warning"].lower()
        )
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_match_persists_normally(monkeypatch):
    """Regression guard: the backstop does not affect the happy path."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            return {
                "final_response": "reply",
                "messages": [{"role": "assistant", "content": "reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result")

        # History was written
        assert server._sessions["sid"]["history"] == [
            {"role": "assistant", "content": "reply"}
        ]
        assert server._sessions["sid"]["history_version"] == 1

        # No warning should be attached
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" not in payload
    finally:
        server._sessions.pop("sid", None)


# ---------------------------------------------------------------------------
# session.interrupt must only cancel pending prompts owned by the calling
# session — it must not blast-resolve clarify/sudo/secret prompts on
# unrelated sessions sharing the same tui_gateway process.  Without
# session scoping the other sessions' prompts silently resolve to empty
# strings, unblocking their agent threads as if the user cancelled.
# ---------------------------------------------------------------------------


def test_interrupt_only_clears_own_session_pending():
    """session.interrupt on session A must NOT release pending prompts
    that belong to session B."""
    import types

    session_a = _session()
    session_a["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    session_b = _session()
    session_b["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid_a"] = session_a
    server._sessions["sid_b"] = session_b

    try:
        # Simulate pending prompts on both sessions (what _block creates
        # while a clarify/sudo/secret request is outstanding).
        ev_a = threading.Event()
        ev_b = threading.Event()
        server._pending["rid-a"] = ("sid_a", ev_a)
        server._pending["rid-b"] = ("sid_b", ev_b)
        server._answers.clear()

        # Interrupt session A.
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.interrupt",
                "params": {"session_id": "sid_a"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # Session A's pending must be released to empty.
        assert ev_a.is_set(), "sid_a pending Event should be set after interrupt"
        assert server._answers.get("rid-a") == ""

        # Session B's pending MUST remain untouched — no cross-session blast.
        assert not ev_b.is_set(), (
            "CRITICAL: session.interrupt on sid_a released a pending prompt "
            "belonging to sid_b — other sessions' clarify/sudo/secret "
            "prompts are being silently cancelled"
        )
        assert "rid-b" not in server._answers
    finally:
        server._sessions.pop("sid_a", None)
        server._sessions.pop("sid_b", None)
        server._pending.pop("rid-a", None)
        server._pending.pop("rid-b", None)
        server._answers.pop("rid-a", None)
        server._answers.pop("rid-b", None)


def test_interrupt_clears_multiple_own_pending():
    """When a single session has multiple pending prompts (uncommon but
    possible via nested tool calls), interrupt must release all of them."""
    import types

    sess = _session()
    sess["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid"] = sess

    try:
        ev1, ev2 = threading.Event(), threading.Event()
        server._pending["r1"] = ("sid", ev1)
        server._pending["r2"] = ("sid", ev2)

        resp = server.handle_request(
            {"id": "1", "method": "session.interrupt", "params": {"session_id": "sid"}}
        )
        assert resp.get("result")
        assert ev1.is_set() and ev2.is_set()
        assert server._answers.get("r1") == "" and server._answers.get("r2") == ""
    finally:
        server._sessions.pop("sid", None)
        for key in ("r1", "r2"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_session_stop_forces_idle_and_kills_processes(monkeypatch):
    calls = {"interrupt": 0}

    class _Agent:
        def interrupt(self):
            calls["interrupt"] += 1

    fake_registry = types.ModuleType("tools.process_registry")
    fake_registry.process_registry = types.SimpleNamespace(kill_all=lambda: 2)
    monkeypatch.setitem(sys.modules, "tools.process_registry", fake_registry)

    server._sessions["sid"] = _session(
        agent=_Agent(),
        events=[
            {"type": "message.start", "session_id": "sid", "ts": 1710000000.0},
            {
                "type": "tool.start",
                "session_id": "sid",
                "ts": 1710000001.0,
                "payload": {"tool_id": "tool-1", "name": "shell"},
            },
        ],
        events_lock=threading.Lock(),
        running=True,
        running_tools={"tool-1": {"tool_id": "tool-1", "name": "shell"}},
    )

    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.stop", "params": {"session_id": "sid"}}
        )

        assert resp["result"] == {
            "status": "stopped",
            "interrupted": True,
            "killed": 2,
        }
        assert calls["interrupt"] == 1
        assert server._sessions["sid"]["running"] is False
        assert server._sessions["sid"]["running_tools"] == {}
        assert server._sessions["sid"]["events"] == []
    finally:
        server._sessions.pop("sid", None)


def test_clear_pending_without_sid_clears_all():
    """_clear_pending(None) is the shutdown path — must still release
    every pending prompt regardless of owning session."""
    ev1, ev2, ev3 = threading.Event(), threading.Event(), threading.Event()
    server._pending["a"] = ("sid_x", ev1)
    server._pending["b"] = ("sid_y", ev2)
    server._pending["c"] = ("sid_z", ev3)
    try:
        server._clear_pending(None)
        assert ev1.is_set() and ev2.is_set() and ev3.is_set()
    finally:
        for key in ("a", "b", "c"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_respond_unpacks_sid_tuple_correctly():
    """After the (sid, Event) tuple change, _respond must still work."""
    ev = threading.Event()
    server._pending["rid-x"] = ("sid_x", ev)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "clarify.respond",
                "params": {"request_id": "rid-x", "answer": "the answer"},
            }
        )
        assert resp.get("result")
        assert ev.is_set()
        assert server._answers.get("rid-x") == "the answer"
    finally:
        server._pending.pop("rid-x", None)
        server._answers.pop("rid-x", None)


# ---------------------------------------------------------------------------
# /model switch and other agent-mutating commands must reject while the
# session is running.  agent.switch_model() mutates self.model, self.provider,
# self.base_url, self.client etc. in place — the worker thread running
# agent.run_conversation is reading those on every iteration.  Same class of
# bug as the session.undo / session.compress mid-run silent-drop; same fix
# pattern: reject with 4009 while running.
# ---------------------------------------------------------------------------


def test_config_set_model_rejects_while_running(monkeypatch):
    """/model via config.set must reject during an in-flight turn."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": raw, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "anthropic/claude-sonnet-4.6",
                },
            }
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        assert not seen["called"], (
            "_apply_model_switch was called mid-turn — would race with "
            "the worker thread reading agent.model / agent.client"
        )
    finally:
        server._sessions.pop("sid", None)


def test_config_set_model_allowed_when_idle(monkeypatch):
    """Regression guard: idle sessions can still switch models."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": "newmodel", "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=False)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "model", "value": "newmodel"},
            }
        )
        assert resp.get("result")
        assert resp["result"]["value"] == "newmodel"
        assert seen["called"]
    finally:
        server._sessions.pop("sid", None)


def test_mirror_slash_side_effects_rejects_mutating_commands_while_running(monkeypatch):
    """Slash worker passthrough (e.g. /model, /personality, /prompt,
    /compress) must reject during an in-flight turn.  Same race as
    config.set — mutates live agent state while run_conversation is
    reading it."""
    import types

    applied = {"model": False, "compress": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    def _fake_compress(session, focus):
        applied["compress"] = True
        return (0, {})

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)
    monkeypatch.setattr(server, "_compress_session_history", _fake_compress)

    session = _session(running=True)
    session["agent"] = types.SimpleNamespace(model="x")

    for cmd, expected_name in [
        ("/model new/model", "model"),
        ("/personality default", "personality"),
        ("/prompt", "prompt"),
        ("/compress", "compress"),
    ]:
        warning = server._mirror_slash_side_effects("sid", session, cmd)
        assert (
            "session busy" in warning
        ), f"{cmd} should have returned busy warning, got: {warning!r}"
        assert f"/{expected_name}" in warning

    # None of the mutating side-effect helpers should have fired.
    assert not applied["model"], "model switch fired despite running session"
    assert not applied["compress"], "compress fired despite running session"


def test_mirror_slash_side_effects_allowed_when_idle(monkeypatch):
    """Regression guard: idle session still runs the side effects."""
    import types

    applied = {"model": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)

    session = _session(running=False)
    session["agent"] = types.SimpleNamespace(model="x")

    warning = server._mirror_slash_side_effects("sid", session, "/model foo")
    # Should NOT contain "session busy" — the switch went through.
    assert "session busy" not in warning
    assert applied["model"]


# ---------------------------------------------------------------------------
# session.create / session.close race: fast /new churn must not orphan the
# slash_worker subprocess or the global approval-notify registration.
# ---------------------------------------------------------------------------


def test_session_create_close_race_does_not_orphan_worker(monkeypatch):
    """Regression guard: if session.close runs while session.create's
    _build thread is still constructing the agent, the build thread
    must detect the orphan and clean up the notify registration it's
    about to install.  The slash worker is created lazily by slash.exec
    (419c82ec5) so _build must NOT allocate one — eagerly or on the
    orphan path."""
    import threading

    closed_workers: list[str] = []
    unregistered_keys: list[str] = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key
            self._closed = False

        def close(self):
            self._closed = True
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    # Make _build block until we release it — simulates slow agent init
    release_build = threading.Event()

    def _slow_make_agent(sid, key):
        release_build.wait(timeout=3.0)
        return _FakeAgent()

    # Stub everything _build touches
    monkeypatch.setattr(server, "_make_agent", _slow_make_agent)
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(create_session=lambda *a, **kw: None),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    # Shim register/unregister to observe leaks
    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    # Start: session.create spawns _build thread, returns synchronously
    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    assert resp.get("result"), f"got error: {resp.get('error')}"
    sid = resp["result"]["session_id"]
    build_done = server._sessions[sid]["agent_ready"]

    # Build thread is blocked in _slow_make_agent.  Close the session
    # NOW — this pops _sessions[sid] before _build can install the
    # worker/notify.
    close_resp = server.handle_request(
        {
            "id": "2",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert close_resp.get("result", {}).get("closed") is True

    # At this point session.close saw slash_worker=None (lazy — never
    # installed) so it didn't close anything.  Release the build thread
    # and let it finish — it should detect the orphan and unregister
    # the notify it just installed.
    release_build.set()

    # The build thread's finally sets agent_ready AFTER the orphan
    # cleanup, so once this returns the cleanup has run (or not).
    assert build_done.wait(timeout=3.0), "build thread never finished"

    # Lazy slash worker: _build never allocates one, so there is no
    # worker subprocess to orphan (or to close).
    assert (
        closed_workers == []
    ), f"build thread closed a worker it should never have created: {closed_workers}"
    # Notify may be unregistered by both session.close (unconditional)
    # and the orphan-cleanup path; the key guarantee is that the build
    # thread does at least one unregister call (any prior close
    # already popped the callback; the duplicate is a no-op).
    assert len(unregistered_keys) >= 1, (
        f"orphan notify registration was not unregistered — "
        f"unregistered_keys={unregistered_keys}"
    )


def test_session_create_no_race_keeps_worker_alive(monkeypatch):
    """Regression guard: when session.close does NOT race, the build
    thread must install the notify normally and leave it alone (no
    over-eager cleanup).  The slash worker is lazy (419c82ec5): None
    after build, created by the first slash.exec, and left installed."""
    closed_workers: list[str] = []
    unregistered_keys: list[str] = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def run(self, cmd):
            return "ok"

        def close(self):
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    monkeypatch.setattr(server, "_make_agent", lambda sid, key: _FakeAgent())
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(create_session=lambda *a, **kw: None),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    sid = resp["result"]["session_id"]

    # Wait for the build to finish (ready event inside session dict).
    session = server._sessions[sid]
    session["agent_ready"].wait(timeout=2.0)

    # Build finished without a close race — nothing should have been
    # cleaned up by the orphan check.
    assert (
        closed_workers == []
    ), f"build thread closed a worker despite no race: {closed_workers}"
    assert (
        unregistered_keys == []
    ), f"build thread unregistered its own notify despite no race: {unregistered_keys}"

    # Lazy worker: nothing installed at build time.
    assert session.get("slash_worker") is None

    # First slash.exec creates the worker and leaves it installed.
    fake_sc = types.ModuleType("agent.skill_commands")
    fake_sc.get_skill_commands = lambda: {}
    monkeypatch.setitem(sys.modules, "agent.skill_commands", fake_sc)

    exec_resp = server.handle_request(
        {
            "id": "2",
            "method": "slash.exec",
            "params": {"session_id": sid, "command": "/noop-test"},
        }
    )
    assert exec_resp.get("result", {}).get("output") == "ok", (
        f"slash.exec failed: {exec_resp.get('error')}"
    )
    assert session.get("slash_worker") is not None
    assert (
        closed_workers == []
    ), f"slash.exec closed its own worker despite no race: {closed_workers}"

    # Cleanup
    server._sessions.pop(sid, None)


def test_slash_exec_close_race_does_not_orphan_lazy_worker(monkeypatch):
    """Regression guard for the lazy slash-worker path: if session.close
    runs while slash.exec is constructing the worker, close sees
    slash_worker=None and closes nothing — slash.exec must detect the
    orphaned session dict and close the worker it just installed,
    otherwise the subprocess leaks until process exit (the atexit sweep
    only walks live _sessions)."""
    closed_workers: list[str] = []
    sid = "race-sid"

    class _RacingWorker:
        def __init__(self, key, model):
            self.key = key
            # Deterministically simulate session.close winning the race
            # mid-construction: it pops the session dict and, finding
            # slash_worker=None, closes nothing.
            server._sessions.pop(sid, None)

        def run(self, cmd):
            return "ok"

        def close(self):
            closed_workers.append(self.key)

    monkeypatch.setattr(server, "_SlashWorker", _RacingWorker)
    fake_sc = types.ModuleType("agent.skill_commands")
    fake_sc.get_skill_commands = lambda: {}
    monkeypatch.setitem(sys.modules, "agent.skill_commands", fake_sc)

    session = _session()
    server._sessions[sid] = session
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "slash.exec",
                "params": {"session_id": sid, "command": "/noop-test"},
            }
        )
        # The command itself still completes (worker ran before the
        # orphan check) — the guarantee is about cleanup, not output.
        assert resp.get("result", {}).get("output") == "ok", (
            f"slash.exec failed: {resp.get('error')}"
        )
        assert closed_workers == ["session-key"], (
            f"orphaned lazy worker was not closed — closed_workers={closed_workers}"
        )
        assert session.get("slash_worker") is None
    finally:
        server._sessions.pop(sid, None)


def test_get_db_degrades_cleanly_when_sessiondb_init_fails(monkeypatch):
    fake_mod = types.ModuleType("elevate_state")

    class _BrokenSessionDB:
        def __init__(self):
            raise RuntimeError("locking protocol")

    fake_mod.SessionDB = _BrokenSessionDB
    monkeypatch.setitem(sys.modules, "elevate_state", fake_mod)
    monkeypatch.setattr(server, "_db", None)
    monkeypatch.setattr(server, "_db_error", None)

    assert server._get_db() is None
    assert server._db_error == "locking protocol"


def test_session_create_continues_when_state_db_is_unavailable(monkeypatch):
    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def close(self):
            return None

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    emits = []

    monkeypatch.setattr(server, "_make_agent", lambda sid, key: _FakeAgent())
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emits.append(a))

    import tools.approval as _approval
    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    resp = server.handle_request(
        {"id": "1", "method": "session.create", "params": {"cols": 80}}
    )
    sid = resp["result"]["session_id"]
    session = server._sessions[sid]
    session["agent_ready"].wait(timeout=2.0)

    assert session["agent_error"] is None
    assert session["agent"] is not None
    assert not any(args and args[0] == "error" for args in emits)

    server._sessions.pop(sid, None)


def test_session_list_returns_clean_error_when_state_db_is_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_db_error", "locking protocol")

    resp = server.handle_request({"id": "1", "method": "session.list", "params": {}})

    assert "error" in resp
    assert "state.db unavailable: locking protocol" in resp["error"]["message"]


# --------------------------------------------------------------------------
# model.options — curated-list parity with `elevate model` and classic /model
# --------------------------------------------------------------------------


def test_model_options_does_not_overwrite_curated_models(monkeypatch):
    """The TUI model.options handler must surface the same curated model
    list as `elevate model` and the classic CLI /model picker.

    Regression: earlier versions of this handler unconditionally replaced
    each provider's curated ``models`` field with ``provider_model_ids()``
    (live /models catalog).  That pulled in hundreds of non-agentic models
    for providers like Nous whose /models endpoint returns image/video
    generators, rerankers, embeddings, and TTS models alongside chat models.
    """
    curated_providers = [
        {
            "slug": "nous",
            "name": "Nous",
            "models": ["moonshotai/kimi-k2.5", "anthropic/claude-opus-4.7"],
            "total_models": 30,
            "source": "built-in",
            "is_current": False,
            "is_user_defined": False,
        },
    ]

    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )

    with patch(
        "elevate_cli.model_switch.list_authenticated_providers",
        return_value=curated_providers,
    ) as listing:
        # If provider_model_ids gets called at all, the handler is still
        # overwriting curated with live — that's the regression we're
        # guarding against.
        with patch("elevate_cli.models.provider_model_ids") as live_fetch:
            resp = server._methods["model.options"](99, {"session_id": ""})

    assert "result" in resp, resp
    providers = resp["result"]["providers"]
    nous = next((p for p in providers if p.get("slug") == "nous"), None)
    assert nous is not None
    assert nous["models"] == [
        "moonshotai/kimi-k2.5",
        "anthropic/claude-opus-4.7",
    ]
    assert nous["total_models"] == 30
    # Handler must not consult the live catalog — curated is the truth.
    live_fetch.assert_not_called()
    # list_authenticated_providers is the single source.
    assert listing.call_count == 1


def test_model_options_propagates_list_exception(monkeypatch):
    """If list_authenticated_providers itself raises, surface as an RPC
    error rather than swallowing to a blank picker."""
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )
    with patch(
        "elevate_cli.model_switch.list_authenticated_providers",
        side_effect=RuntimeError("catalog blew up"),
    ):
        resp = server._methods["model.options"](77, {"session_id": ""})
    assert "error" in resp
    assert resp["error"]["code"] == 5033
    assert "catalog blew up" in resp["error"]["message"]


def test_async_delegate_sink_rewakes_main_agent():
    """The async-delegation completion sink must, on a child result payload:
    flip the subagent dot, emit a lightweight delegate.complete ping (NO dumped
    text), and re-wake the main agent via prompt.submit so it evaluates the
    result and replies. The result must NOT be threaded as a fake user message;
    it rides into the wake turn as context (full text to the API) and is stored
    as a ⟦subagent-result⟧ card marker (persist_user_message)."""
    # Stamp idle well in the past so the sustained-quiet-window gate is already
    # satisfied and the watcher fires on its first pass (no real 2.5s wait).
    session = _session(idle_since=time.monotonic() - 100.0)
    sid = "async-sid"
    emitted = []
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    with patch("tui_gateway.server._emit", side_effect=lambda ev, s, p=None: emitted.append((ev, s, p))), \
         patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}):
        sink = server._make_async_delegate_sink(sid, session)
        sink({
            "task_id": "dt_abc123",
            "results": [
                {
                    "task_index": 0,
                    "subagent_id": "sa-0-deadbeef",
                    "status": "completed",
                    "summary": "Pulled 6 comps; CMA drafted.",
                    "goal": "Run the Lewis Creek CMA",
                    "child_session_id": "child-1",
                }
            ],
            "total_duration_seconds": 12.3,
        })
        # The idle wake watcher runs on its own daemon thread — wait for it.
        for _ in range(100):
            if submitted:
                break
            time.sleep(0.03)

    kinds = [e[0] for e in emitted]
    assert "subagent.complete" in kinds
    assert "delegate.complete" in kinds
    # delegate.complete is now a lightweight ping — no dumped result text.
    dc = next(p for (ev, _s, p) in emitted if ev == "delegate.complete")
    assert dc["task_id"] == "dt_abc123"
    assert "text" not in dc
    # The raw result is NOT threaded as a fake user message.
    assert session["history"] == []
    assert session["history_version"] == 0
    # The idle watcher consumed the parked result and re-woke via prompt.submit.
    assert len(submitted) == 1
    _rid, params = submitted[0]
    assert params["session_id"] == sid
    assert "CMA drafted" in params["text"]  # API sees the full result + eval ask
    # Stored as a status-marked card, never a plain user bubble.
    assert params["persist_user_message"].startswith("⟦subagent-result:completed⟧")
    assert "Run the Lewis Creek CMA" in params["persist_user_message"]
    assert "CMA drafted" in params["persist_user_message"]
    # Consumed: nothing left parked for a later turn to double-report.
    assert session.get("pending_delegate_results") == []


def test_parked_result_yields_to_busy_session():
    """If the session is BUSY when the delegation finishes (the user hit send
    at the same moment), the sink must NOT fire a competing wake turn — the
    result parks on the session for the user's turn to consume."""
    session = _session(running=True)
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    with patch("tui_gateway.server._emit"), \
         patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[0, 0, 100]):
        sink = server._make_async_delegate_sink("busy-sid", session)
        sink({
            "task_id": "dt_busy1",
            "results": [{
                "task_index": 0,
                "status": "completed",
                "summary": "Found 7 leads.",
                "goal": "Find leads",
            }],
        })

    # No competing wake turn while busy; result parked for the user's turn.
    assert submitted == []
    parked = session.get("pending_delegate_results")
    assert parked and "Found 7 leads" in parked[0]["summary"]


def test_wake_defers_until_sustained_quiet_window():
    """Idle but not yet QUIET: a session that just went idle (idle_since
    moments ago) must NOT be woken — the watcher waits out the quiet window so
    it never pounces in the gap between a user's back-to-back turns."""
    # idle_since = now → quiet window NOT yet elapsed.
    session = _session(
        running=False,
        idle_since=1000.0,
        pending_delegate_results=[{"status": "completed", "goal": "g", "summary": "s"}],
    )
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    # monotonic stays inside the quiet window then the deadline trips, so the
    # watcher loops a couple of times waiting and then gives up WITHOUT firing.
    with patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[1000.0, 1000.5, 1001.0, 2000.0]):
        server._wake_main_agent_with_result("quiet-sid", session)

    assert submitted == []
    # Result still parked → it will ride the user's next turn.
    assert session.get("pending_delegate_results")


def test_wake_reparks_when_submit_loses_latch_race():
    """If a user turn claims the latch between our drain and submit (submit
    returns a 'session busy' error), the drained result must be RE-PARKED, not
    dropped."""
    session = _session(
        running=False,
        idle_since=0.0,  # quiet window long satisfied
        pending_delegate_results=[
            {"status": "completed", "goal": "Find leads", "summary": "Found 7 leads."}
        ],
    )
    submitted = []

    def busy_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": 4009, "message": "session busy"}}

    # monotonic: deadline calc (0→deadline 90), while-enter (1), quiet-window
    # elapsed check (10 → 10s idle ≥ 2.5 quiet), then while-exit (99999).
    # First pass: quiet satisfied → drain + submit → busy error → repark, then
    # the deadline trips so the loop ends.
    with patch.dict("tui_gateway.server._methods", {"prompt.submit": busy_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[0.0, 1.0, 10.0, 99999.0]):
        server._wake_main_agent_with_result("race-sid", session)

    # Submit was attempted and lost; the result is back in the parked queue.
    assert len(submitted) == 1
    parked = session.get("pending_delegate_results")
    assert parked and "Found 7 leads" in parked[0]["summary"]


def test_async_delegate_sink_never_raises():
    """A malformed payload must not bubble out of the sink (it runs on a
    daemon thread; an exception there is silent and would drop the ping)."""
    session = _session()
    with patch("tui_gateway.server._emit"), patch("tui_gateway.server._get_db", return_value=None):
        sink = server._make_async_delegate_sink("sid", session)
        sink(None)            # no payload
        sink({"results": "not a list"})  # wrong shape
    # No assertion needed beyond "did not raise".
