"""Visible debug-browser support.

Elevate's browser tool defaults to a hidden, headless Chromium the user
cannot see or log into. This module sets up a real, VISIBLE Chrome window
with remote debugging enabled, cloned from the user's own Chrome profile so
the agent is logged into everything the user is. The browser tool then
connects to it over CDP (``browser.cdp_url`` in config) instead of spawning
the headless one.

Components, all owned by this module:
  - A launchd LaunchAgent (``ai.elevate.debugchrome``) that keeps the visible
    Chrome running, started on login.
  - A clone of the user's active Chrome profile at
    ``<elevate_home>/chrome-debug`` (Chrome 136+ blocks remote debugging on a
    live profile, and a profile cannot be open in two Chrome instances).
  - ``browser.cdp_url`` set in config so the browser tool uses CDP.

macOS only — Chrome's profile layout and launchd are macOS-specific.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from elevate_cli.config import get_elevate_home, load_config, save_config

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"
LAUNCH_AGENT_LABEL = "ai.elevate.debugchrome"

# Caches regenerate themselves — never worth cloning.
_PROFILE_EXCLUDES = [
    "Cache/",
    "Code Cache/",
    "GPUCache/",
    "DawnGraphiteCache/",
    "DawnWebGPUCache/",
    "GraphiteDawnCache/",
    "Service Worker/CacheStorage/",
    "Service Worker/ScriptCache/",
    "Component Crx Cache/",
    "optimization_guide_model_store/",
]


def is_supported() -> bool:
    """The visible debug browser is macOS-only."""
    return sys.platform == "darwin"


def chrome_binary() -> Path | None:
    """Path to the Chrome executable, or None if Chrome is not installed."""
    candidate = Path(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    if candidate.exists():
        return candidate
    found = shutil.which("google-chrome") or shutil.which("Google Chrome")
    return Path(found) if found else None


def chrome_support_dir() -> Path:
    """Chrome's Application Support directory (where profiles live)."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Google"
        / "Chrome"
    )


def debug_profile_dir() -> Path:
    """The dedicated user-data-dir for the visible debug Chrome."""
    return get_elevate_home() / "chrome-debug"


def detect_active_profile() -> str:
    """Return the directory name of the user's most-recently-used Chrome profile.

    Chrome records this in ``Local State`` under ``profile.last_used``. Falls
    back to ``Default`` when that file is missing or unreadable.
    """
    local_state = chrome_support_dir() / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        last_used = data.get("profile", {}).get("last_used")
        if last_used and (chrome_support_dir() / last_used).is_dir():
            return last_used
    except Exception:
        pass
    return "Default"


def profile_label(profile_dir_name: str) -> str:
    """Human-readable name + account for a profile directory, best-effort."""
    local_state = chrome_support_dir() / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {}).get(
            profile_dir_name, {}
        )
        name = info.get("name") or profile_dir_name
        account = info.get("user_name")
        return f"{name} ({account})" if account else name
    except Exception:
        return profile_dir_name


def cdp_is_up() -> bool:
    """True when a Chrome with remote debugging is reachable on the CDP port."""
    try:
        with urllib.request.urlopen(
            f"{CDP_URL}/json/version", timeout=2
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def clone_profile(profile_dir_name: str | None = None) -> Path:
    """Clone the user's active Chrome profile into the debug Chrome profile.

    rsync ``<support>/<profile>`` -> ``<elevate_home>/chrome-debug/Default``,
    excluding caches. macOS keeps the cookie-encryption key in the login
    Keychain ("Chrome Safe Storage"), shared across profiles for the same
    Chrome.app — so the cloned cookies decrypt fine in the debug Chrome.
    """
    profile_dir_name = profile_dir_name or detect_active_profile()
    src = chrome_support_dir() / profile_dir_name
    if not src.is_dir():
        raise FileNotFoundError(f"Chrome profile not found: {src}")

    dst = debug_profile_dir() / "Default"
    dst.mkdir(parents=True, exist_ok=True)

    # Stop the debug Chrome so its profile dir is not being written mid-copy.
    stop_chrome()
    time.sleep(1.5)

    cmd = ["rsync", "-a", "--delete"]
    for exc in _PROFILE_EXCLUDES:
        cmd += ["--exclude", exc]
    cmd += [f"{src}/", f"{dst}/"]
    subprocess.run(cmd, check=True, timeout=300)

    # Singleton lock files belong to the source instance — never carry over.
    for lock in debug_profile_dir().glob("Singleton*"):
        try:
            lock.unlink()
        except OSError:
            pass
    return dst


def stop_chrome() -> None:
    """Kill any Chrome started by this module (matched by the debug port)."""
    subprocess.run(
        ["pkill", "-f", f"remote-debugging-port={CDP_PORT}"],
        check=False,
        capture_output=True,
    )


def launch_chrome(wait: bool = True) -> bool:
    """Launch the visible debug Chrome. Idempotent — no-op if CDP is already up.

    Returns True when CDP is reachable afterwards.
    """
    if cdp_is_up():
        return True
    binary = chrome_binary()
    if binary is None:
        return False
    debug_profile_dir().mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(binary),
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={debug_profile_dir()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--restore-last-session",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not wait:
        return True
    for _ in range(20):
        if cdp_is_up():
            return True
        time.sleep(0.5)
    return cdp_is_up()


def launch_agent_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{LAUNCH_AGENT_LABEL}.plist"
    )


def _python_path() -> str:
    """Absolute interpreter path for the LaunchAgent (mirrors gateway.py)."""
    try:
        from elevate_cli.gateway import get_python_path

        return get_python_path()
    except Exception:
        return sys.executable


def generate_plist() -> bytes:
    log_dir = get_elevate_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            _python_path(),
            "-m",
            "elevate_cli.main",
            "browser",
            "launch",
        ],
        # RunAtLoad only — no KeepAlive, so quitting the window stays quit
        # until next login. The agent must not fight the user.
        "RunAtLoad": True,
        "StandardOutPath": str(log_dir / "debugchrome.log"),
        "StandardErrorPath": str(log_dir / "debugchrome.error.log"),
    }
    return plistlib.dumps(payload)


def install_launch_agent() -> None:
    """Write and bootstrap the debug-Chrome LaunchAgent."""
    path = launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(generate_plist())
    uid = os.getuid()
    domain = f"gui/{uid}"
    # bootout first so a stale definition is replaced cleanly.
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{LAUNCH_AGENT_LABEL}"],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        check=False,
        capture_output=True,
    )


def uninstall_launch_agent() -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"],
        check=False,
        capture_output=True,
    )
    path = launch_agent_path()
    if path.exists():
        path.unlink()


def set_cdp_config(enabled: bool) -> None:
    """Point the browser tool at the debug Chrome (or unset it)."""
    config = load_config()
    browser_cfg = config.setdefault("browser", {})
    if not isinstance(browser_cfg, dict):
        browser_cfg = {}
        config["browser"] = browser_cfg
    browser_cfg["cdp_url"] = CDP_URL if enabled else ""
    save_config(config)


def setup() -> tuple[bool, str]:
    """Full setup: clone profile, install LaunchAgent, launch, wire config.

    Returns (ok, message).
    """
    if not is_supported():
        return False, "Visible debug browser is only supported on macOS."
    if chrome_binary() is None:
        return False, (
            "Google Chrome not found. Install Chrome, then re-run "
            "'elevate browser setup'."
        )

    profile = detect_active_profile()
    try:
        clone_profile(profile)
    except Exception as exc:  # noqa: BLE001
        return False, f"Profile clone failed: {exc}"

    install_launch_agent()
    set_cdp_config(True)

    if not launch_chrome(wait=True):
        return False, (
            "Debug Chrome did not come up on the CDP port. Check "
            f"{get_elevate_home()}/logs/debugchrome.error.log"
        )
    return True, (
        f"Visible debug browser ready. Cloned profile "
        f"'{profile_label(profile)}', logged in as the user. The agent now "
        f"drives a Chrome window you can watch."
    )


def status() -> dict:
    """Snapshot of the debug-browser setup, for `elevate browser status`."""
    config = load_config()
    cdp_cfg = (config.get("browser") or {}).get("cdp_url") or ""
    return {
        "supported": is_supported(),
        "chrome_installed": chrome_binary() is not None,
        "cdp_up": cdp_is_up(),
        "cdp_url_config": cdp_cfg,
        "launch_agent_installed": launch_agent_path().exists(),
        "debug_profile_exists": (debug_profile_dir() / "Default").is_dir(),
        "active_profile": detect_active_profile() if is_supported() else None,
    }
