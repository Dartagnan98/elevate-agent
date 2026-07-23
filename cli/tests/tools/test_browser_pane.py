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
    assert calls[-1] == (
        "fill",
        ["ref_2", secret],
        "chat-login",
    )
