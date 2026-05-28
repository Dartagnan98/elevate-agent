"""Tests for transparent visible-browser auto-provisioning in browser_tool.

The feature: on a fresh download, the first local-mode browser action clones
the user's real Chrome profile into a visible debug window (logged in as them)
and drives it over CDP — no manual ``elevate browser setup`` step.

These tests verify the GATING only (we never launch a real browser): the
``debug_browser.ensure_debug_browser`` call is mocked. We assert it fires in
pure local mode and is correctly suppressed for every backend/host where a
cloned desktop Chrome would be wrong.
"""

import importlib

import pytest

bt = importlib.import_module("tools.browser_tool")


@pytest.fixture(autouse=True)
def _reset_cooldown():
    bt._autoprovision_cooldown_until = 0.0
    yield
    bt._autoprovision_cooldown_until = 0.0


def _patch_common(monkeypatch, *, cloud=None, camofox=False, termux=False):
    monkeypatch.setattr(bt, "_get_cloud_provider", lambda: cloud)
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: camofox)
    monkeypatch.setattr(bt, "_is_termux_environment", lambda: termux)
    # No external env override by default.
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)


def _fake_db(monkeypatch, *, supported=True, disabled=False, url="http://localhost:9222"):
    import types

    db = types.SimpleNamespace(
        CDP_URL="http://localhost:9222",
        is_supported=lambda: supported,
        auto_provision_disabled=lambda: disabled,
        ensure_debug_browser=lambda: url,
    )
    monkeypatch.setitem(__import__("sys").modules, "elevate_cli.debug_browser", db)
    return db


def _fake_config(monkeypatch, cdp_url=""):
    """Stub elevate_cli.config.read_raw_config so the helper sees a known cdp_url."""
    import types

    cfg_mod = types.SimpleNamespace(read_raw_config=lambda: {"browser": {"cdp_url": cdp_url}})
    monkeypatch.setitem(__import__("sys").modules, "elevate_cli.config", cfg_mod)


def test_provisions_in_pure_local_mode(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    monkeypatch.setattr(bt.sys, "platform", "darwin")
    assert bt._ensure_managed_debug_browser() == "http://localhost:9222"


def test_skips_when_cloud_provider_configured(monkeypatch):
    _patch_common(monkeypatch, cloud=object())
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    assert bt._ensure_managed_debug_browser() == ""


def test_skips_in_camofox_mode(monkeypatch):
    _patch_common(monkeypatch, camofox=True)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    assert bt._ensure_managed_debug_browser() == ""


def test_skips_when_external_env_override_set(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    monkeypatch.setenv("BROWSER_CDP_URL", "http://10.0.0.5:9222")
    assert bt._ensure_managed_debug_browser() == ""


def test_skips_on_termux(monkeypatch):
    _patch_common(monkeypatch, termux=True)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    assert bt._ensure_managed_debug_browser() == ""


def test_skips_on_headless_linux_without_display(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    monkeypatch.setattr(bt.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert bt._ensure_managed_debug_browser() == ""


def test_provisions_on_linux_with_display(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    _fake_config(monkeypatch, "")
    monkeypatch.setattr(bt.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    assert bt._ensure_managed_debug_browser() == "http://localhost:9222"


def test_skips_when_user_disabled(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch, disabled=True)
    _fake_config(monkeypatch, "")
    monkeypatch.setattr(bt.sys, "platform", "darwin")
    assert bt._ensure_managed_debug_browser() == ""


def test_leaves_external_config_cdp_endpoint_alone(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    # User pointed browser.cdp_url at their own remote Chrome — not ours.
    _fake_config(monkeypatch, "http://10.0.0.5:9222")
    monkeypatch.setattr(bt.sys, "platform", "darwin")
    assert bt._ensure_managed_debug_browser() == ""


def test_self_heals_when_config_has_managed_url(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch)
    # Config already records our managed URL (provisioned a prior session).
    _fake_config(monkeypatch, "http://localhost:9222")
    monkeypatch.setattr(bt.sys, "platform", "darwin")
    assert bt._ensure_managed_debug_browser() == "http://localhost:9222"


def test_cooldown_after_failed_launch(monkeypatch):
    _patch_common(monkeypatch)
    _fake_db(monkeypatch, url=None)  # ensure_debug_browser returns None == launch failed
    _fake_config(monkeypatch, "")
    monkeypatch.setattr(bt.sys, "platform", "darwin")
    assert bt._ensure_managed_debug_browser() == ""
    # Cooldown armed so we don't re-block on the launch wait next call.
    assert bt._autoprovision_cooldown_until > 0.0
