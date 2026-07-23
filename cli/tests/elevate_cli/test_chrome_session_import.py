from __future__ import annotations

from elevate_cli import chrome_session_import


def test_export_cookie_payload_keeps_only_import_fields():
    cookies = chrome_session_import._export_cookie_payload(
        [
            {
                "name": "session",
                "value": "secret",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "priority": "High",
            },
            {
                "name": "partitioned",
                "value": "secret",
                "domain": ".example.com",
                "partitionKey": {"topLevelSite": "https://example.com"},
            },
            {"name": "", "value": "ignored", "domain": "example.com"},
            "invalid",
        ]
    )

    assert cookies == [
        {
            "name": "session",
            "value": "secret",
            "domain": ".example.com",
            "path": "/",
            "secure": True,
        }
    ]


def test_export_chrome_cookies_refreshes_clone_and_restores_stopped_state(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(chrome_session_import.debug_browser, "is_supported", lambda: True)
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "chrome_binary",
        lambda: tmp_path / "Chrome",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "detect_active_profile",
        lambda: "Profile 3",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "profile_label",
        lambda _profile: "Work",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "debug_profile_dir",
        lambda: tmp_path / "chrome-debug",
    )
    monkeypatch.setattr(chrome_session_import.debug_browser, "cdp_is_up", lambda: False)
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "clone_profile",
        lambda profile: calls.append(("clone", profile)),
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "launch_chrome",
        lambda *, wait: calls.append(("launch", wait)) or True,
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "stop_chrome",
        lambda: calls.append(("stop",)),
    )
    monkeypatch.setattr(
        chrome_session_import,
        "_cdp_call",
        lambda _url, method: {
            "cookies": [
                {
                    "name": "session",
                    "value": "secret",
                    "domain": "example.com",
                }
            ]
        }
        if method == "Storage.getCookies"
        else {},
    )

    result = chrome_session_import.export_chrome_cookies(refresh=True)

    assert result["sourceProfile"] == "Work"
    assert result["exported"] == 1
    assert result["cookies"][0]["value"] == "secret"
    assert calls == [("clone", "Profile 3"), ("launch", True), ("stop",)]


def test_export_does_not_stop_a_debug_chrome_that_was_already_running(
    monkeypatch, tmp_path
):
    clone = tmp_path / "chrome-debug" / "Default"
    clone.mkdir(parents=True)
    monkeypatch.setattr(chrome_session_import.debug_browser, "is_supported", lambda: True)
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "chrome_binary",
        lambda: tmp_path / "Chrome",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "detect_active_profile",
        lambda: "Default",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "profile_label",
        lambda _profile: "Default",
    )
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "debug_profile_dir",
        lambda: clone.parent,
    )
    monkeypatch.setattr(chrome_session_import.debug_browser, "cdp_is_up", lambda: True)
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "launch_chrome",
        lambda *, wait: True,
    )
    stopped = []
    monkeypatch.setattr(
        chrome_session_import.debug_browser,
        "stop_chrome",
        lambda: stopped.append(True),
    )
    monkeypatch.setattr(
        chrome_session_import,
        "_cdp_call",
        lambda _url, _method: {"cookies": []},
    )

    result = chrome_session_import.export_chrome_cookies(refresh=False)

    assert result["exported"] == 0
    assert stopped == []
