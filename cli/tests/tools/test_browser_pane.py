from __future__ import annotations

import json

from tools import browser_pane


def _install_endpoint(monkeypatch, tmp_path):
    (tmp_path / "browser-pane.json").write_text(
        json.dumps({"port": 12345, "token": "test-token"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_pane, "get_elevate_home", lambda: tmp_path)


def test_snapshot_uses_active_embedded_tab_and_agent_refs(monkeypatch, tmp_path):
    _install_endpoint(monkeypatch, tmp_path)
    calls = []

    def fake_rpc(method, params, _timeout):
        calls.append((method, params))
        if method == "list":
            return [
                {
                    "id": "tab_1",
                    "url": "https://example.com/",
                    "title": "Example",
                    "active": True,
                }
            ]
        assert method == "read_page"
        return {
            "url": "https://example.com/",
            "title": "Example",
            "text": "Example body",
            "elements": [{"ref": "e1", "tag": "a", "name": "More information"}],
        }

    monkeypatch.setattr(browser_pane, "_rpc", fake_rpc)
    result = browser_pane.run_command("snapshot", ["-c"], session_id="chat-a")

    assert result["success"] is True
    assert '[ref=e1]' in result["data"]["snapshot"]
    assert "e1" in result["data"]["refs"]
    assert calls[-1] == (
        "read_page",
        {"sessionKey": "chat-a", "tabId": "tab_1"},
    )


def test_type_targets_the_same_visible_tab(monkeypatch, tmp_path):
    _install_endpoint(monkeypatch, tmp_path)
    calls = []

    def fake_rpc(method, params, _timeout):
        calls.append((method, params))
        if method == "list":
            return [{"id": "tab_7", "active": True}]
        if method == "fill":
            return {"ok": True}
        raise AssertionError(method)

    monkeypatch.setattr(browser_pane, "_rpc", fake_rpc)
    result = browser_pane.run_command(
        "type",
        ["@ref_3", "hello"],
        session_id="chat-b",
    )

    assert result["success"] is True
    assert calls[-1] == (
        "fill",
        {
            "sessionKey": "chat-b",
            "tabId": "tab_7",
            "ref": "@ref_3",
            "value": "hello",
        },
    )


def test_new_tab_loads_url_and_returns_session_tabs(monkeypatch, tmp_path):
    _install_endpoint(monkeypatch, tmp_path)
    calls = []

    def fake_rpc(method, params, _timeout):
        calls.append((method, params))
        if method == "new_tab":
            return {"tabId": "tab_8"}
        if method == "navigate":
            return {"ok": True, "url": params["url"]}
        if method == "list":
            return [
                {
                    "id": "tab_8",
                    "active": True,
                    "url": "https://example.com/",
                    "title": "Example",
                }
            ]
        raise AssertionError(method)

    monkeypatch.setattr(browser_pane, "_rpc", fake_rpc)
    result = browser_pane.run_command(
        "new_tab",
        ["https://example.com/"],
        session_id="chat-tabs",
    )

    assert result["success"] is True
    assert result["data"]["tabId"] == "tab_8"
    assert calls == [
        (
            "new_tab",
            {"sessionKey": "chat-tabs", "url": "about:blank"},
        ),
        (
            "navigate",
            {
                "sessionKey": "chat-tabs",
                "tabId": "tab_8",
                "url": "https://example.com/",
            },
        ),
        ("list", {"sessionKey": "chat-tabs"}),
    ]


def test_select_and_close_tab_use_requested_session(monkeypatch, tmp_path):
    _install_endpoint(monkeypatch, tmp_path)
    calls = []

    def fake_rpc(method, params, _timeout):
        calls.append((method, params))
        if method in {"select_tab", "close_tab"}:
            return {"ok": True}
        if method == "list":
            return [
                {
                    "id": "tab_2",
                    "active": True,
                    "url": "https://two.example/",
                    "title": "Two",
                }
            ]
        raise AssertionError(method)

    monkeypatch.setattr(browser_pane, "_rpc", fake_rpc)
    selected = browser_pane.run_command(
        "select_tab",
        ["tab_2"],
        session_id="chat-tabs",
    )
    closed = browser_pane.run_command(
        "close_tab",
        ["tab_1"],
        session_id="chat-tabs",
    )

    assert selected["success"] is True
    assert selected["data"]["tabId"] == "tab_2"
    assert closed["success"] is True
    assert closed["data"]["closedTabId"] == "tab_1"
    assert (
        "select_tab",
        {"sessionKey": "chat-tabs", "tabId": "tab_2"},
    ) in calls
    assert (
        "close_tab",
        {"sessionKey": "chat-tabs", "tabId": "tab_1"},
    ) in calls


def test_forward_and_reload_target_active_visible_tab(monkeypatch, tmp_path):
    _install_endpoint(monkeypatch, tmp_path)
    calls = []

    def fake_rpc(method, params, _timeout):
        calls.append((method, params))
        if method == "list":
            return [{"id": "tab_4", "active": True}]
        if method in {"forward", "reload"}:
            return {"ok": True, "url": "https://example.com/next"}
        raise AssertionError(method)

    monkeypatch.setattr(browser_pane, "_rpc", fake_rpc)
    forwarded = browser_pane.run_command("forward", [], session_id="chat-history")
    reloaded = browser_pane.run_command("reload", [], session_id="chat-history")

    assert forwarded["success"] is True
    assert reloaded["success"] is True
    assert (
        "forward",
        {"sessionKey": "chat-history", "tabId": "tab_4"},
    ) in calls
    assert (
        "reload",
        {"sessionKey": "chat-history", "tabId": "tab_4"},
    ) in calls


def test_missing_desktop_endpoint_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_pane, "get_elevate_home", lambda: tmp_path)
    assert browser_pane.run_command("snapshot", ["-c"]) is None


def test_browser_tool_prefers_embedded_pane_before_cli_discovery(monkeypatch):
    from tools import browser_tool

    monkeypatch.setattr(
        browser_tool,
        "_run_embedded_browser_command",
        lambda command, args, timeout, session_id: {
            "success": True,
            "data": {"command": command, "args": args, "timeout": timeout},
        },
    )
    monkeypatch.setattr(
        browser_tool,
        "_find_agent_browser",
        lambda: (_ for _ in ()).throw(AssertionError("CLI discovery should not run")),
    )

    result = browser_tool._run_browser_command("task", "snapshot", ["-c"], timeout=9)

    assert result["success"] is True
    assert result["data"] == {"command": "snapshot", "args": ["-c"], "timeout": 9}


def test_embedded_snapshot_ignores_stale_external_supervisor(monkeypatch):
    from tools import browser_tool

    supervisor = type(
        "Supervisor",
        (),
        {
            "snapshot": lambda self: type(
                "Snapshot",
                (),
                {
                    "active": True,
                    "to_dict": lambda self: {
                        "pending_dialogs": [{"message": "wrong browser"}],
                        "frame_tree": {"top": {"url": "chrome://newtab"}},
                    },
                },
            )()
        },
    )()
    monkeypatch.setattr(browser_tool, "_embedded_browser_available", lambda: True)
    monkeypatch.setattr(
        browser_tool,
        "_run_browser_command",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {
                "snapshot": '- document "Visible page"',
                "refs": {},
            },
        },
    )
    monkeypatch.setattr(
        "tools.browser_supervisor.SUPERVISOR_REGISTRY.get",
        lambda _task_id: supervisor,
    )

    result = json.loads(browser_tool.browser_snapshot(task_id="visible-chat"))

    assert result["success"] is True
    assert result["snapshot"] == '- document "Visible page"'
    assert "pending_dialogs" not in result
    assert "frame_tree" not in result


def test_embedded_pane_satisfies_browser_requirements_without_cli(monkeypatch):
    from tools import browser_tool

    monkeypatch.setattr(browser_tool, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser_tool, "_embedded_browser_available", lambda: True)
    monkeypatch.setattr(
        browser_tool,
        "_find_agent_browser",
        lambda: (_ for _ in ()).throw(
            AssertionError("embedded pane must not require the fallback CLI")
        ),
    )

    assert browser_tool.check_browser_requirements() is True


def test_visible_browser_status_is_scoped_to_the_agent_session(monkeypatch):
    from tools import browser_tool
    from tools import visible_browser_tool

    monkeypatch.setattr(
        visible_browser_tool.browser_pane,
        "status",
        lambda task_id: {
            "open": True,
            "workspaceId": task_id,
            "activeTabId": "tab_9",
            "url": "https://example.com/",
            "tabs": [{"id": "tab_9", "active": True}],
        },
    )

    result = json.loads(visible_browser_tool.browser_status("chat-9"))

    assert result["success"] is True
    assert result["workspaceId"] == "chat-9"
    assert result["activeTabId"] == "tab_9"
    assert set(visible_browser_tool._SCHEMAS) == {
        "browser_status",
        "browser_open",
        "browser_read",
        "browser_forward",
        "browser_reload",
        "browser_new_tab",
        "browser_select_tab",
        "browser_close_tab",
        "browser_fill",
        "browser_drag",
        "browser_login",
        "browser_shot",
        "browser_recordings",
        "browser_play",
    }
    assert visible_browser_tool._SCHEMAS["browser_open"]["parameters"]["required"] == [
        "url"
    ]
    assert browser_tool._BROWSER_SCHEMA_MAP["browser_click"]["parameters"]["required"] == [
        "ref"
    ]


def test_browser_registry_handlers_prefer_chat_session_over_turn_task(monkeypatch):
    from tools import browser_tool
    from tools import visible_browser_tool
    from tools.registry import registry

    visible_sessions = []
    generic_sessions = []
    monkeypatch.setattr(
        visible_browser_tool,
        "browser_status",
        lambda session_id: visible_sessions.append(session_id) or "{}",
    )
    monkeypatch.setattr(
        browser_tool,
        "browser_navigate",
        lambda *, url, task_id: generic_sessions.append((url, task_id)) or "{}",
    )

    visible_handler = registry.get_entry("browser_status").handler
    generic_handler = registry.get_entry("browser_navigate").handler
    visible_handler(
        {},
        task_id="random-turn-task",
        session_id="durable-chat-session",
    )
    generic_handler(
        {"url": "https://example.com"},
        task_id="random-turn-task",
        session_id="durable-chat-session",
    )

    assert visible_sessions == ["durable-chat-session"]
    assert generic_sessions == [
        ("https://example.com", "durable-chat-session"),
    ]


def test_saved_browser_login_never_returns_the_password(monkeypatch):
    from tools import visible_browser_tool

    secret = "never-echo-this-password"
    monkeypatch.setenv("SKYSLOPE_LOGIN_URL", "https://app.skyslope.com/")
    monkeypatch.setenv("SKYSLOPE_USERNAME", "agent@example.com")
    monkeypatch.setenv("SKYSLOPE_PASSWORD", secret)
    monkeypatch.setattr(
        visible_browser_tool.browser_pane,
        "status",
        lambda _task_id: {"url": "https://app.skyslope.com/login"},
    )
    calls = []

    def fake_run(command, args, *, session_id):
        calls.append((command, args, session_id))
        if command == "snapshot":
            return {
                "success": True,
                "data": {
                    "refs": {
                        "ref_1": {
                            "tag": "input",
                            "type": "email",
                            "name": "Email",
                        },
                        "ref_2": {
                            "tag": "input",
                            "type": "password",
                            "name": "Password",
                        },
                    }
                },
            }
        return {"success": True, "data": {}}

    monkeypatch.setattr(
        visible_browser_tool.browser_pane,
        "run_command",
        fake_run,
    )

    raw = visible_browser_tool.browser_login("chat-login")
    result = json.loads(raw)

    assert result["success"] is True
    assert result["filled"] == ["email", "password"]
    assert secret not in raw
    assert (
        "fill",
        ["ref_2", secret],
        "chat-login",
    ) in calls


def test_saved_browser_login_does_not_require_a_duplicate_login_url(monkeypatch):
    from tools import visible_browser_tool

    secret = "never-echo-this-password"
    monkeypatch.delenv("SKYSLOPE_LOGIN_URL", raising=False)
    monkeypatch.delenv("COMPLIANCE_LOGIN_URL", raising=False)
    monkeypatch.delenv("SKYSLOPE_URL", raising=False)
    monkeypatch.setenv("SKYSLOPE_USERNAME", "agent@example.com")
    monkeypatch.setenv("SKYSLOPE_PASSWORD", secret)
    monkeypatch.setattr(
        visible_browser_tool.browser_pane,
        "status",
        lambda _task_id: {"url": "https://app.skyslope.com/login"},
    )

    def fake_run(command, _args, *, session_id):
        assert session_id == "chat-login"
        if command == "snapshot":
            return {
                "success": True,
                "data": {
                    "refs": {
                        "ref_1": {
                            "tag": "input",
                            "type": "email",
                            "name": "Email",
                        },
                        "ref_2": {
                            "tag": "input",
                            "type": "password",
                            "name": "Password",
                        },
                    }
                },
            }
        return {"success": True, "data": {}}

    monkeypatch.setattr(visible_browser_tool.browser_pane, "run_command", fake_run)

    raw = visible_browser_tool.browser_login("chat-login")
    result = json.loads(raw)

    assert result["success"] is True
    assert result["filled"] == ["email", "password"]
    assert secret not in raw


def test_saved_browser_login_waits_for_a_dynamic_login_form(monkeypatch):
    from tools import visible_browser_tool

    monkeypatch.setenv("SKYSLOPE_USERNAME", "agent@example.com")
    monkeypatch.setenv("SKYSLOPE_PASSWORD", "secret")
    monkeypatch.setattr(visible_browser_tool.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        visible_browser_tool.browser_pane,
        "status",
        lambda _task_id: {"url": "https://app.skyslope.com/login"},
    )
    snapshots = 0

    def fake_run(command, _args, *, session_id):
        nonlocal snapshots
        assert session_id == "dynamic-login"
        if command == "snapshot":
            snapshots += 1
            if snapshots == 1:
                return {"success": True, "data": {"refs": {}}}
            return {
                "success": True,
                "data": {
                    "refs": {
                        "ref_1": {
                            "tag": "input",
                            "type": "email",
                            "name": "Email",
                        },
                        "ref_2": {
                            "tag": "input",
                            "type": "submit",
                            "name": "Next",
                        },
                    }
                },
            }
        return {"success": True, "data": {}}

    monkeypatch.setattr(visible_browser_tool.browser_pane, "run_command", fake_run)

    result = json.loads(visible_browser_tool.browser_login("dynamic-login"))

    assert result["success"] is True
    assert result["filled"] == ["email"]
    assert result["action_ref"] == "ref_2"
    assert snapshots >= 3
