"""Tests for anti-false-flag browser stealth: persistent per-site profile
resolver, fingerprint-hardening init script, and human-like pacing.

These are logic tests — no real browser is launched. Config is driven through
``browser_stealth``'s cached snapshot (``_cfg_cache``), which we set directly
so every test is deterministic and independent of the on-disk config.yaml.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import tools.browser_stealth as bs


@pytest.fixture(autouse=True)
def _reset_stealth_config(monkeypatch):
    """Each test starts from defaults (all features on) with a clean cache."""
    bs.reset_cache()
    # Force an empty config snapshot -> all defaults (features on).
    bs._cfg_cache = {}
    bs._cfg_cache_loaded = True
    yield
    bs.reset_cache()


def _set_cfg(**browser_keys):
    """Replace the cached browser-config snapshot for this test."""
    bs._cfg_cache = {"browser": dict(browser_keys)}
    bs._cfg_cache_loaded = True


# ---------------------------------------------------------------------------
# Registrable domain
# ---------------------------------------------------------------------------

class TestRegistrableDomain:

    @pytest.mark.parametrize("url,expected", [
        ("https://app.skyslope.com/dashboard", "skyslope.com"),
        ("https://office.lofty.com:443/leads", "lofty.com"),
        ("http://xposure.ca/listing/123", "xposure.ca"),
        ("https://user:pass@portal.ghl.io/x", "ghl.io"),
        ("https://foo.co.uk/bar", "foo.co.uk"),
        ("https://sub.foo.co.uk/bar", "foo.co.uk"),
        ("example.com", "example.com"),
    ])
    def test_extracts_registrable_domain(self, url, expected):
        assert bs.registrable_domain(url) == expected

    @pytest.mark.parametrize("url", [
        "", "about:blank", "data:text/html,hi", "http://localhost:8080/x",
        "https://127.0.0.1/x", "file:///tmp/page.html",
    ])
    def test_non_host_urls_return_none(self, url):
        assert bs.registrable_domain(url) is None


# ---------------------------------------------------------------------------
# Profile resolver + concurrency safety
# ---------------------------------------------------------------------------

class TestProfileResolver:

    def test_same_domain_maps_to_same_dir(self, tmp_path):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        a = bs.resolve_profile_dir("https://app.skyslope.com/a")
        b = bs.resolve_profile_dir("https://login.skyslope.com/b")
        assert a is not None and a == b
        assert a.is_dir()
        assert a.parent == tmp_path

    def test_different_domains_map_to_different_dirs(self, tmp_path):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        a = bs.resolve_profile_dir("https://skyslope.com/")
        b = bs.resolve_profile_dir("https://lofty.com/")
        assert a != b

    def test_disabled_returns_none(self, tmp_path):
        _set_cfg(persistent_profiles=False, profile_dir=str(tmp_path))
        assert bs.resolve_profile_dir("https://skyslope.com/") is None

    def test_non_host_url_returns_none(self, tmp_path):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        assert bs.resolve_profile_dir("about:blank") is None

    def test_profile_dir_override_respected(self, tmp_path):
        custom = tmp_path / "custom-profiles"
        _set_cfg(persistent_profiles=True, profile_dir=str(custom))
        d = bs.resolve_profile_dir("https://skyslope.com/")
        assert d is not None and d.parent == custom

    # -- concurrency: copy-on-write decision is enforced via the lock --------

    def test_lock_claim_and_release(self, tmp_path):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        d = bs.resolve_profile_dir("https://skyslope.com/")
        assert bs.profile_is_locked(d) is False
        assert bs.mark_profile_locked(d) is True
        # Same process re-reads as not "another live process".
        assert bs.profile_is_locked(d) is False
        bs.release_profile_lock(d)
        assert not (d / ".elevate-profile.lock").exists()

    def test_live_other_pid_blocks_claim(self, tmp_path, monkeypatch):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        d = bs.resolve_profile_dir("https://skyslope.com/")
        # Simulate another live process holding the dir.
        (d / ".elevate-profile.lock").write_text("999999999", encoding="utf-8")
        monkeypatch.setattr(bs.os, "kill", lambda pid, sig: None)  # PID "alive"
        assert bs.profile_is_locked(d) is True
        # A second claimant must be refused -> caller does copy-on-write.
        assert bs.mark_profile_locked(d) is False

    def test_stale_pid_lock_is_ignored(self, tmp_path, monkeypatch):
        _set_cfg(persistent_profiles=True, profile_dir=str(tmp_path))
        d = bs.resolve_profile_dir("https://skyslope.com/")
        (d / ".elevate-profile.lock").write_text("999999999", encoding="utf-8")

        def _dead(pid, sig):
            raise OSError("no such process")

        monkeypatch.setattr(bs.os, "kill", _dead)
        assert bs.profile_is_locked(d) is False
        assert bs.mark_profile_locked(d) is True


# ---------------------------------------------------------------------------
# Fingerprint hardening
# ---------------------------------------------------------------------------

class TestFingerprintInitScript:

    def test_default_on_builds_script(self):
        _set_cfg()  # defaults -> on
        script = bs.build_init_script()
        assert script

    def test_sets_expected_properties(self):
        _set_cfg(fingerprint_hardening=True)
        script = bs.build_init_script()
        # The canonical automation tell, neutralized.
        assert "webdriver" in script
        assert "undefined" in script
        # Plausible navigator shape.
        assert "languages" in script
        assert "hardwareConcurrency" in script
        assert "deviceMemory" in script
        # chrome runtime object present.
        assert "window.chrome" in script
        # permissions query shim.
        assert "permissions" in script and "query" in script
        # WebGL vendor/renderer spoof (UNMASKED_* param ids).
        assert "37445" in script and "37446" in script
        # Idempotency guard + a real GPU string.
        assert "__elevateStealth" in script

    def test_disabled_returns_empty(self):
        _set_cfg(fingerprint_hardening=False)
        assert bs.build_init_script() == ""
        assert bs.stealth_chrome_flags() == []

    def test_chrome_flags_strip_automation_tells(self):
        _set_cfg(fingerprint_hardening=True)
        flags = bs.stealth_chrome_flags()
        joined = " ".join(flags)
        assert "AutomationControlled" in joined
        assert "enable-automation" in joined

    def test_no_leftover_placeholders(self):
        _set_cfg(fingerprint_hardening=True)
        script = bs.build_init_script()
        for ph in ("__NAV_PLATFORM__", "__GPU_VENDOR__", "__GPU_RENDERER__"):
            assert ph not in script

    def test_platform_specific_gpu(self, monkeypatch):
        _set_cfg(fingerprint_hardening=True)
        monkeypatch.setattr(bs, "_platform_key", lambda: "win32")
        script = bs.build_init_script()
        assert "Win32" in script


# ---------------------------------------------------------------------------
# Human-like pacing
# ---------------------------------------------------------------------------

class TestPacing:

    def test_paces_state_affecting_only(self):
        _set_cfg(human_pacing=True)
        assert bs.should_pace("click") is True
        assert bs.should_pace("type") is True
        assert bs.should_pace("navigate") is True
        assert bs.should_pace("press") is True
        assert bs.should_pace("scroll") is True
        # Pure reads are NOT paced -> trivial reads keep full throughput.
        assert bs.should_pace("snapshot") is False
        assert bs.should_pace("eval") is False

    def test_disabled_paces_nothing(self):
        _set_cfg(human_pacing=False)
        assert bs.should_pace("click") is False
        assert bs.should_pace("navigate") is False

    def test_pace_action_sleeps_for_state_affecting(self):
        _set_cfg(human_pacing=True, pacing_min_ms=100, pacing_max_ms=100)
        sleeps = []
        delay = bs.pace_action("click", sleep=sleeps.append)
        assert delay == pytest.approx(0.1, abs=1e-6)
        assert sleeps == [pytest.approx(0.1, abs=1e-6)]

    def test_pace_action_noop_for_reads(self):
        _set_cfg(human_pacing=True)
        sleeps = []
        delay = bs.pace_action("snapshot", sleep=sleeps.append)
        assert delay == 0.0
        assert sleeps == []

    def test_pace_action_noop_when_disabled(self):
        _set_cfg(human_pacing=False, pacing_min_ms=100, pacing_max_ms=100)
        sleeps = []
        delay = bs.pace_action("click", sleep=sleeps.append)
        assert delay == 0.0
        assert sleeps == []

    def test_pacing_delay_within_bounds(self):
        _set_cfg(human_pacing=True, pacing_min_ms=120, pacing_max_ms=650)
        for _ in range(50):
            d = bs.pacing_delay_seconds()
            assert 0.120 <= d <= 0.650

    def test_pacing_bounds_overridable(self):
        _set_cfg(human_pacing=True, pacing_min_ms=5, pacing_max_ms=10)
        for _ in range(20):
            d = bs.pacing_delay_seconds()
            assert 0.005 <= d <= 0.010

    def test_type_jitter_invoked_per_character(self):
        _set_cfg(human_pacing=True)
        emitted = []
        sleeps = []
        n = bs.type_with_jitter("abc", emitted.append, sleep=sleeps.append)
        assert n == 3
        # one emit per character (human keystrokes), not one atomic fill
        assert emitted == ["a", "b", "c"]
        # a jitter delay applied per character
        assert len(sleeps) == 3

    def test_type_jitter_falls_back_when_disabled(self):
        _set_cfg(human_pacing=False)
        emitted = []
        sleeps = []
        n = bs.type_with_jitter("abc", emitted.append, sleep=sleeps.append)
        assert n == 3
        # atomic emit, no jitter
        assert emitted == ["abc"]
        assert sleeps == []

    def test_keystroke_delays_shape(self):
        _set_cfg(human_pacing=True, type_jitter_min_ms=8, type_jitter_max_ms=45)
        delays = bs.type_keystroke_delays("hello")
        assert len(delays) == 5
        for d in delays:
            assert 0.008 <= d <= 0.045

    def test_preclick_scroll_probability(self):
        _set_cfg(human_pacing=True, preclick_scroll_prob=0.0)
        assert bs.should_scroll_before_click() is False
        _set_cfg(human_pacing=True, preclick_scroll_prob=1.0)
        assert bs.should_scroll_before_click() is True
        _set_cfg(human_pacing=False, preclick_scroll_prob=1.0)
        assert bs.should_scroll_before_click() is False


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------

class TestConfigKnobs:

    def test_all_default_on(self):
        _set_cfg()
        assert bs.persistent_profiles_enabled() is True
        assert bs.fingerprint_hardening_enabled() is True
        assert bs.human_pacing_enabled() is True

    def test_each_knob_overridable(self):
        _set_cfg(
            persistent_profiles=False,
            fingerprint_hardening=False,
            human_pacing=False,
        )
        assert bs.persistent_profiles_enabled() is False
        assert bs.fingerprint_hardening_enabled() is False
        assert bs.human_pacing_enabled() is False

    def test_string_truthy_accepted(self):
        _set_cfg(human_pacing="false")
        assert bs.human_pacing_enabled() is False
        _set_cfg(human_pacing="on")
        assert bs.human_pacing_enabled() is True
