"""Integration tests for stealth wiring inside ``browser_tool``: the
fingerprint init-script is injected on navigation, pacing is applied to
state-affecting public tools, the per-site profile is pinned, and — critically
— none of it defeats the loop guard (action budget / stuck counter).

The browser transport (``_run_browser_command``) is mocked throughout; no real
browser is launched.
"""

import json
from unittest.mock import patch

import pytest

import tools.browser_tool as bt
import tools.browser_stealth as bs


@pytest.fixture(autouse=True)
def _stealth_env(monkeypatch):
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    # Skip the SSRF / policy machinery so navigate runs the open command.
    monkeypatch.setattr(bt, "_is_local_backend", lambda: True)
    monkeypatch.setattr(bt, "check_website_access", lambda url: None)
    monkeypatch.setattr(bt, "_maybe_start_recording", lambda key: None)
    # Deterministic loop-guard config.
    bt._cached_stuck_threshold = 3
    bt._stuck_threshold_resolved = True
    bt._cached_max_actions_per_session = 120
    bt._max_actions_per_session_resolved = True
    with bt._loop_guard_lock:
        bt._loop_guard_state.clear()
    # Stealth config: all features on, but zero pacing delay so tests are fast.
    bs.reset_cache()
    bs._cfg_cache = {"browser": {"pacing_min_ms": 0, "pacing_max_ms": 0,
                                 "preclick_scroll_prob": 0.0}}
    bs._cfg_cache_loaded = True
    yield
    with bt._loop_guard_lock:
        bt._loop_guard_state.clear()
    bt._cached_stuck_threshold = None
    bt._stuck_threshold_resolved = False
    bt._cached_max_actions_per_session = None
    bt._max_actions_per_session_resolved = False
    bs.reset_cache()


def _open_result(url="https://app.skyslope.com/x", title="Dashboard"):
    return {"success": True, "data": {"url": url, "title": title,
                                      "snapshot": 'heading "Dashboard"'}}


# ---------------------------------------------------------------------------
# Init-script injection on navigation
# ---------------------------------------------------------------------------

def test_init_script_injected_after_navigation(monkeypatch, tmp_path):
    bs._cfg_cache = {"browser": {"pacing_min_ms": 0, "pacing_max_ms": 0,
                                 "profile_dir": str(tmp_path)}}
    calls = []

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        calls.append((command, list(args or [])))
        if command == "open":
            return _open_result()
        if command == "snapshot":
            return {"success": True, "data": {"snapshot": 'heading "Dashboard"'}}
        return {"success": True, "data": {}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        bt.browser_navigate("https://app.skyslope.com/x", task_id="t1")

    commands = [c for c, _ in calls]
    assert "open" in commands
    # An eval carrying the fingerprint-hardening script must follow the open.
    eval_calls = [a for c, a in calls if c == "eval"]
    assert eval_calls, "stealth init-script eval was not issued"
    assert any("webdriver" in a[0] for a in eval_calls)


def test_no_init_script_when_disabled(monkeypatch):
    bs._cfg_cache = {"browser": {"fingerprint_hardening": False,
                                 "pacing_min_ms": 0, "pacing_max_ms": 0}}
    calls = []

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        calls.append(command)
        if command == "open":
            return _open_result()
        return {"success": True, "data": {"snapshot": "x"}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        bt.browser_navigate("https://app.skyslope.com/x", task_id="t2")

    assert "eval" not in calls  # hardening off -> empty script -> no eval


# ---------------------------------------------------------------------------
# Pacing on state-affecting public tools
# ---------------------------------------------------------------------------

def test_click_paces(monkeypatch):
    paced = []
    monkeypatch.setattr(bs, "pace_action",
                        lambda action, **k: paced.append(action) or 0.0)
    with patch.object(bt, "_run_browser_command",
                      return_value={"success": True, "data": {}}):
        bt.browser_click("@e1", task_id="t1")
    assert "click" in paced


def test_snapshot_does_not_pace(monkeypatch):
    paced = []
    monkeypatch.setattr(bs, "pace_action",
                        lambda action, **k: paced.append(action) or 0.0)
    with patch.object(bt, "_run_browser_command",
                      return_value={"success": True,
                                    "data": {"snapshot": "x", "refs": {}}}):
        bt.browser_snapshot(task_id="t1")
    # browser_snapshot must never call _pace -> trivial reads keep throughput.
    assert paced == []


def test_type_uses_keystrokes_when_pacing_on(monkeypatch):
    calls = []

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        calls.append((command, list(args or [])))
        return {"success": True, "data": {}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        bt.browser_type("@e3", "hello", task_id="t1")

    cmds = [c for c, _ in calls]
    # human path = clear (fill "") then type via keystrokes
    assert "type" in cmds
    assert ("fill", ["@e3", ""]) in calls


def test_type_falls_back_to_fill_when_pacing_off(monkeypatch):
    bs._cfg_cache = {"browser": {"human_pacing": False}}
    calls = []

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        calls.append((command, list(args or [])))
        return {"success": True, "data": {}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        bt.browser_type("@e3", "hello", task_id="t1")

    cmds = [c for c, _ in calls]
    assert "type" not in cmds
    assert ("fill", ["@e3", "hello"]) in calls


# ---------------------------------------------------------------------------
# Per-site profile pinning (local path)
# ---------------------------------------------------------------------------

def test_profile_pinned_on_first_nav(monkeypatch, tmp_path):
    bs._cfg_cache = {"browser": {"pacing_min_ms": 0, "pacing_max_ms": 0,
                                 "profile_dir": str(tmp_path)}}
    # Force the pure local (headless) path — no managed/CDP browser, which is
    # where per-site profile pinning applies.
    monkeypatch.setattr(bt, "_ensure_managed_debug_browser", lambda: "")
    monkeypatch.setattr(bt, "_get_cdp_override", lambda: "")
    monkeypatch.setattr(bt, "_get_cloud_provider", lambda: None)

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        if command == "open":
            return _open_result()
        return {"success": True, "data": {"snapshot": "x"}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        bt.browser_navigate("https://app.skyslope.com/x", task_id="tp")

    # The session for this nav should now carry a per-domain profile dir.
    si = bt._get_session_info(bt._navigation_session_key("tp", "https://app.skyslope.com/x"))
    pdir = si.get("_site_profile_dir")
    assert pdir is not None
    assert "skyslope_com" in pdir


# ---------------------------------------------------------------------------
# Composition with the loop guard
# ---------------------------------------------------------------------------

def test_pacing_does_not_consume_action_budget(monkeypatch):
    """Pacing sleeps + internal (unguarded) commands must NOT count against the
    per-session action budget — only the guarded public tool call does."""
    bt._cached_max_actions_per_session = 5
    bt._max_actions_per_session_resolved = True

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        return {"success": True, "data": {}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        # 5 clicks: each click issues an internal (possible) scroll + the
        # guarded click. Only the 5 guarded calls count. The 6th would refuse.
        for _ in range(5):
            r = json.loads(bt.browser_click("@e1", task_id="tb"))
            assert r.get("success") is True
        # 6th guarded call -> budget exhausted refusal.
        r6 = json.loads(bt.browser_click("@e1", task_id="tb"))
        assert r6.get("success") is False
        assert "budget" in r6.get("error", "").lower()


def test_pacing_does_not_reset_stuck_counter(monkeypatch):
    """Unchanged snapshots across paced navigations must still trip the stuck
    warning — pacing must not mask stuckness."""
    same = {"success": True, "data": {"url": "https://x.test/a",
                                      "title": "A",
                                      "snapshot": 'heading "Stuck page"'}}

    def fake_cmd(task_id, command, args=None, timeout=None, _engine_override=None):
        if command == "open":
            return same
        if command == "snapshot":
            return {"success": True, "data": {"snapshot": 'heading "Stuck page"'}}
        return {"success": True, "data": {}}

    with patch.object(bt, "_run_browser_command", side_effect=fake_cmd):
        last = None
        for _ in range(4):
            last = json.loads(bt.browser_navigate("https://x.test/a", task_id="ts"))
    # After repeated identical pages, the loop guard's stuck warning fires
    # despite pacing being active.
    assert "stuck_warning" in last


def test_loop_guard_decorator_still_wraps(monkeypatch):
    """The @_loop_guarded decorator must remain in place on the public tools
    after the stealth changes (budget pre-check + postprocess still applied)."""
    for fn_name in ("browser_navigate", "browser_click", "browser_type",
                    "browser_snapshot", "browser_scroll", "browser_press",
                    "browser_back"):
        fn = getattr(bt, fn_name)
        # functools.wraps preserves __name__/__wrapped__ on the guarded fn.
        assert hasattr(fn, "__wrapped__"), f"{fn_name} lost its loop-guard wrapper"
