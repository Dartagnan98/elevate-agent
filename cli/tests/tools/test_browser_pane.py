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
    result = browser_pane.run_command("snapshot", ["-c"])

    assert result["success"] is True
    assert '[ref=e1]' in result["data"]["snapshot"]
    assert "e1" in result["data"]["refs"]
    assert calls[-1] == ("read_page", {"tabId": "tab_1"})


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
    result = browser_pane.run_command("type", ["@e3", "hello"])

    assert result["success"] is True
    assert calls[-1] == (
        "fill",
        {"tabId": "tab_7", "ref": "@e3", "value": "hello"},
    )


def test_missing_desktop_endpoint_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_pane, "get_elevate_home", lambda: tmp_path)
    assert browser_pane.run_command("snapshot", ["-c"]) is None


def test_browser_tool_prefers_embedded_pane_before_cli_discovery(monkeypatch):
    from tools import browser_tool

    monkeypatch.setattr(
        browser_tool,
        "_run_embedded_browser_command",
        lambda command, args, timeout: {
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
