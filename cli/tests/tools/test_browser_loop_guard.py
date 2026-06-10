"""Tests for the browser loop guard: page-state fingerprint stuck detection,
blocker classification, per-session action budgets, and stuck telemetry.

These are logic tests — the browser transport (``_run_browser_command``) is
mocked throughout; no real browser is launched.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import tools.browser_tool as bt

# Captured before the conftest autouse fixture replaces it with a no-op —
# the writer tests below exercise the real implementation.
_REAL_WRITE_STUCK_TELEMETRY = bt._write_stuck_telemetry

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SNAP_A = 'heading "Welcome"\nbutton "Buy now" [ref=e1]\nlink "Docs" [ref=e2]'
SNAP_B = 'heading "Checkout"\nbutton "Pay" [ref=e5]'

LOGIN_SNAP = (
    'heading "Welcome back"\n'
    'textbox "Email" [ref=e1]\n'
    'textbox "Password" [ref=e2]\n'
    'button "Sign in" [ref=e3]'
)
CAPTCHA_SNAP = 'heading "Just a moment..."\niframe "reCAPTCHA challenge" [ref=e1]'
TWOFA_SNAP = 'text "Enter the verification code we sent to your phone"\ntextbox "Code" [ref=e1]'
CONSENT_SNAP = (
    'dialog "We value your privacy"\n'
    'text "This site uses cookies to improve your experience"\n'
    'button "Accept all" [ref=e9]\n'
    'button "Manage preferences" [ref=e10]'
)
PAYWALL_SNAP = 'heading "Subscribe to continue reading"\nbutton "See plans" [ref=e1]'
ANTIBOT_SNAP = 'heading "Access denied"\ntext "Request blocked due to unusual traffic"'


def _snap_result(text):
    return {"success": True, "data": {"snapshot": text, "refs": {"e1": {}}}}


def _set_threshold(value):
    bt._cached_stuck_threshold = value
    bt._stuck_threshold_resolved = True


def _set_budget(value):
    bt._cached_max_actions_per_session = value
    bt._max_actions_per_session_resolved = True


@pytest.fixture(autouse=True)
def _clean_loop_guard(monkeypatch):
    """Fresh guard state + deterministic config for every test."""
    with bt._loop_guard_lock:
        bt._loop_guard_state.clear()
    _set_threshold(3)
    _set_budget(120)
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    yield
    with bt._loop_guard_lock:
        bt._loop_guard_state.clear()
    bt._cached_stuck_threshold = None
    bt._stuck_threshold_resolved = False
    bt._cached_max_actions_per_session = None
    bt._max_actions_per_session_resolved = False


def _snapshot(task_id="t1"):
    return json.loads(bt.browser_snapshot(task_id=task_id))


def _click(task_id="t1"):
    return json.loads(bt.browser_click("@e1", task_id=task_id))


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

class TestPageFingerprint:

    def test_whitespace_normalized(self):
        assert bt._page_fingerprint("a   b\n\t c") == bt._page_fingerprint("a b c")

    def test_timestamps_ignored(self):
        a = bt._page_fingerprint('text "Last updated 12:01:33 pm"')
        b = bt._page_fingerprint('text "Last updated 1:02 am"')
        assert a == b

    def test_different_content_differs(self):
        assert bt._page_fingerprint(SNAP_A) != bt._page_fingerprint(SNAP_B)


# ---------------------------------------------------------------------------
# Stuck detection
# ---------------------------------------------------------------------------

class TestStuckDetection:

    def test_unchanged_three_actions_appends_warning(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)):
            first = _snapshot()           # baseline observation
            assert "stuck_warning" not in first
            assert "stuck_warning" not in _snapshot()  # unchanged x1
            assert "stuck_warning" not in _snapshot()  # unchanged x2
            stuck = _snapshot()           # unchanged x3 -> warning
        warning = stuck.get("stuck_warning", "")
        assert "page state unchanged after 3 actions" in warning
        assert "you appear stuck" in warning
        assert "needs_operator" in warning

    def test_fingerprint_change_resets_counter(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)):
            for _ in range(3):
                _snapshot()
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_B)):
            changed = _snapshot()
        assert "stuck_warning" not in changed
        st = bt._loop_guard_entry("t1")
        assert st["unchanged_actions"] == 0
        # Two more unchanged actions stay under the threshold again
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_B)):
            assert "stuck_warning" not in _snapshot()
            assert "stuck_warning" not in _snapshot()

    def test_clicks_count_toward_stuck_streak(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)):
            _snapshot()  # baseline
        with patch.object(bt, "_run_browser_command", return_value={"success": True}):
            assert "stuck_warning" not in _click()
            assert "stuck_warning" not in _click()
            stuck = _click()  # 3rd action with no observed change
        assert "page state unchanged after 3 actions" in stuck.get("stuck_warning", "")

    def test_navigate_to_new_url_resets_counter(self, monkeypatch):
        st = bt._loop_guard_entry("t1")
        st["last_url"] = "https://a.example.com/"
        st["last_fp"] = bt._page_fingerprint(SNAP_A)
        st["unchanged_actions"] = 5

        def fake_run(task_id, command, args=None, **kwargs):
            if command == "open":
                return {"success": True, "data": {"url": "https://b.example.com/", "title": "B"}}
            return _snap_result(SNAP_B)

        monkeypatch.setattr(bt, "_run_browser_command", fake_run)
        monkeypatch.setattr(bt, "_is_local_backend", lambda: True)
        monkeypatch.setattr(bt, "check_website_access", lambda url: None)
        monkeypatch.setattr(bt, "_get_session_info", lambda key: {"_first_nav": False})

        result = json.loads(bt.browser_navigate("https://b.example.com/", task_id="t1"))
        assert result["success"] is True
        assert "stuck_warning" not in result
        assert bt._loop_guard_entry("t1")["unchanged_actions"] == 0

    def test_stuck_state_is_per_task(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)):
            for _ in range(4):
                _snapshot(task_id="task_a")
            other = _snapshot(task_id="task_b")
        assert "stuck_warning" not in other

    def test_cleanup_browser_resets_guard_state(self):
        st = bt._loop_guard_entry("t9")
        st["unchanged_actions"] = 7
        with patch.object(bt, "_run_browser_command", return_value={"success": True}):
            bt.cleanup_browser("t9")
        with bt._loop_guard_lock:
            assert "t9" not in bt._loop_guard_state


# ---------------------------------------------------------------------------
# Blocker classification
# ---------------------------------------------------------------------------

class TestBlockerClassifier:

    @pytest.mark.parametrize("snippet,expected", [
        (LOGIN_SNAP, "login_wall"),
        (CAPTCHA_SNAP, "captcha"),
        ('div "cf-turnstile" [ref=e1]', "captcha"),
        ('text "Verify you are human"', "captcha"),
        (TWOFA_SNAP, "2fa"),
        ('text "Enter the security code sent to your email"', "2fa"),
        (CONSENT_SNAP, "consent_overlay"),
        (PAYWALL_SNAP, "paywall"),
        (ANTIBOT_SNAP, "antibot_interstitial"),
        (SNAP_A, None),
        ("", None),
        (None, None),
    ])
    def test_classification_table(self, snippet, expected):
        assert bt._classify_page_blocker(snippet) == expected

    def test_captcha_outranks_login(self):
        combined = LOGIN_SNAP + "\n" + CAPTCHA_SNAP
        assert bt._classify_page_blocker(combined) == "captcha"

    def test_consent_dismiss_ref_hint(self):
        assert bt._find_consent_dismiss_ref(CONSENT_SNAP) == "@e9"
        assert bt._find_consent_dismiss_ref(SNAP_A) is None

    def test_snapshot_prefixed_with_notice(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(CONSENT_SNAP)):
            result = _snapshot()
        assert result["page_blocker"] == "consent_overlay"
        assert result["snapshot"].startswith("page-blocker: consent_overlay")
        assert "Likely dismiss: click @e9." in result["snapshot"]
        # Original snapshot content preserved after the notice
        assert 'button "Accept all" [ref=e9]' in result["snapshot"]

    def test_login_wall_notice(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(LOGIN_SNAP)):
            result = _snapshot()
        assert result["page_blocker"] == "login_wall"
        assert result["snapshot"].startswith("page-blocker: login_wall")
        assert "needs_operator" in result["snapshot"].splitlines()[0]

    def test_stuck_plus_blocker_says_needs_operator(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(LOGIN_SNAP)):
            for _ in range(3):
                _snapshot()
            stuck = _snapshot()
        warning = stuck.get("stuck_warning", "")
        assert "Detected page-blocker: login_wall" in warning
        assert "do not keep retrying" in warning

    def test_stuck_plus_consent_says_dismiss(self):
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(CONSENT_SNAP)):
            for _ in range(3):
                _snapshot()
            stuck = _snapshot()
        warning = stuck.get("stuck_warning", "")
        assert "consent_overlay" in warning
        assert "Click the dismiss button" in warning
        # consent suffix advises dismissing, not escalating
        assert "do not keep retrying" not in warning


# ---------------------------------------------------------------------------
# Action budget
# ---------------------------------------------------------------------------

class TestActionBudget:

    def test_budget_counter_visible_past_half(self):
        _set_budget(6)
        with patch.object(bt, "_run_browser_command", return_value={"success": True}) as run:
            r1 = _click()
            r2 = _click()
            r3 = _click()
        assert "action_budget" not in r1
        assert "action_budget" not in r2
        assert r3["action_budget"] == "action 3/6"
        assert run.call_count == 3

    def test_cap_refuses_further_commands(self):
        _set_budget(4)
        with patch.object(bt, "_run_browser_command", return_value={"success": True}) as run:
            for _ in range(4):
                result = _click()
                assert result["success"] is True
            refused = _click()
        assert run.call_count == 4  # 5th command never reached the browser
        assert refused["success"] is False
        assert "Browser action budget exhausted (5/4 actions this session)" in refused["error"]
        assert "Wrap up now" in refused["error"]
        assert "needs_operator" in refused["error"]
        assert "browser.max_actions_per_session" in refused["error"]
        assert refused["action_budget"] == "action 5/4"

    def test_budget_is_per_task(self):
        _set_budget(2)
        with patch.object(bt, "_run_browser_command", return_value={"success": True}):
            _click(task_id="a")
            _click(task_id="a")
            refused = _click(task_id="a")
            other = _click(task_id="b")
        assert refused["success"] is False
        assert other["success"] is True

    def test_zero_cap_disables_budget(self):
        _set_budget(0)
        with patch.object(bt, "_run_browser_command", return_value={"success": True}):
            for _ in range(10):
                result = _click()
        assert result["success"] is True
        assert "action_budget" not in result

    def test_cleanup_all_resets_budget_caches(self):
        _set_budget(7)
        bt.cleanup_all_browsers()
        assert bt._max_actions_per_session_resolved is False
        assert bt._stuck_threshold_resolved is False
        with bt._loop_guard_lock:
            assert bt._loop_guard_state == {}


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestStuckTelemetry:

    def test_stuck_emits_activity_once_per_episode(self, monkeypatch):
        writer = MagicMock()
        monkeypatch.setattr(bt, "_write_stuck_telemetry", writer)
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)):
            for _ in range(6):  # crosses threshold at the 4th call, stays stuck
                _snapshot()
        assert _wait_for(lambda: writer.call_count >= 1)
        time.sleep(0.05)
        assert writer.call_count == 1  # deduped within the episode
        agent, message, metadata = writer.call_args[0]
        assert agent == "browser"
        assert "page state unchanged after 3 actions" in message
        assert metadata["task_id"] == "t1"
        assert metadata["fingerprint_repeats"] == 3
        assert metadata["blocker"] is None
        assert metadata["action_count"] >= 4

    def test_blocker_emits_activity_once(self, monkeypatch):
        writer = MagicMock()
        monkeypatch.setattr(bt, "_write_stuck_telemetry", writer)
        _set_threshold(50)  # keep stuck detection quiet
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(CAPTCHA_SNAP)):
            _snapshot()
            _snapshot()
        assert _wait_for(lambda: writer.call_count >= 1)
        time.sleep(0.05)
        assert writer.call_count == 1
        agent, message, metadata = writer.call_args[0]
        assert message == "browser page-blocker detected: captcha"
        assert metadata["blocker"] == "captcha"

    def test_writer_appends_activity_row(self):
        conn = MagicMock()
        connect_cm = MagicMock()
        connect_cm.return_value.__enter__.return_value = conn
        connect_cm.return_value.__exit__.return_value = False
        append = MagicMock()
        with patch("elevate_cli.data.connect", connect_cm), \
                patch("elevate_cli.data.surface_state.append_activity", append):
            _REAL_WRITE_STUCK_TELEMETRY("leads", "stuck msg", {"url": "https://x.test"})
        append.assert_called_once()
        args, kwargs = append.call_args
        assert args[0] is conn
        assert args[1] == "leads"
        assert args[2] == "browser_stuck"
        assert kwargs["message"] == "stuck msg"
        assert kwargs["metadata"] == {"url": "https://x.test"}

    def test_writer_failure_is_swallowed(self):
        with patch("elevate_cli.data.connect", side_effect=RuntimeError("db down")):
            _REAL_WRITE_STUCK_TELEMETRY("browser", "msg", {})  # must not raise

    def test_telemetry_failure_never_breaks_command(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("telemetry exploded")

        monkeypatch.setattr(bt, "_emit_browser_stuck_telemetry", boom)
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(LOGIN_SNAP)):
            result = _snapshot()
        # postprocess failed -> falls back to the unannotated raw result
        assert result["success"] is True
        assert "snapshot" in result


# ---------------------------------------------------------------------------
# Guard resilience
# ---------------------------------------------------------------------------

class TestGuardResilience:

    def test_non_json_result_passthrough(self):
        assert bt._loop_guard_postprocess("t", "snapshot", "not json") == "not json"

    def test_warning_never_hard_kills_session(self):
        """Past the stuck threshold commands still execute (warnings only)."""
        with patch.object(bt, "_run_browser_command", return_value=_snap_result(SNAP_A)) as run:
            for _ in range(8):
                result = _snapshot()
        assert run.call_count == 8
        assert result["success"] is True
        assert "stuck_warning" in result
