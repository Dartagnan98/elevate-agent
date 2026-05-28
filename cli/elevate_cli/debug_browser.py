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

Cross-platform (macOS, Windows, Linux). Chrome's profile layout and the
keep-running mechanism differ per OS:
  - Profile location: ``chrome_support_dir()`` resolves the per-OS path.
  - Keep-alive across logins: launchd on macOS only. Windows/Linux rely on
    on-demand launch via ``ensure_debug_browser()`` — the window comes up the
    first time the agent needs it each session, which is enough for the
    "download and it just works" path.

Cookie carryover: the cloned profile keeps its encrypted Cookies DB plus
``Local State`` (which holds the encryption key, OS-keystore-wrapped). Because
the debug Chrome runs as the SAME OS user on the SAME machine, the keystore
(Keychain on macOS, DPAPI on Windows, libsecret/kwallet or plaintext on Linux)
decrypts the cloned cookies — so the agent is logged in everywhere the user is.
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


def _is_mac() -> bool:
    return sys.platform == "darwin"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_supported() -> bool:
    """The visible debug browser works wherever we can find Chrome.

    macOS / Windows / Linux. The gate is "is Chrome installed", not OS —
    profile cloning + CDP launch are portable; only the optional keep-alive
    LaunchAgent is macOS-specific (and on-demand launch covers the rest).
    """
    if not (_is_mac() or _is_windows() or _is_linux()):
        return False
    return chrome_binary() is not None


# Per-OS candidate locations for a Chromium-family binary. Chrome preferred,
# then Chromium/Brave/Edge as fallbacks (all Chromium, all speak CDP).
def _windows_chrome_candidates() -> list[Path]:
    out: list[Path] = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        out += [
            Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(base) / "Chromium" / "Application" / "chrome.exe",
            Path(base) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
    return out


def chrome_binary() -> Path | None:
    """Path to the Chrome executable, or None if Chrome is not installed."""
    if _is_mac():
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            if Path(app).exists():
                return Path(app)
    elif _is_windows():
        for cand in _windows_chrome_candidates():
            if cand.exists():
                return cand
    elif _is_linux():
        for cand in (
            "/opt/google/chrome/chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/brave-browser",
            "/usr/bin/microsoft-edge",
        ):
            if Path(cand).exists():
                return Path(cand)
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "brave-browser",
        "microsoft-edge",
    ):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def chrome_support_dir() -> Path:
    """Chrome's user-data directory (where profiles + Local State live)."""
    if _is_mac():
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        return Path(base) / "Google" / "Chrome" / "User Data"
    # Linux
    return Path.home() / ".config" / "google-chrome"


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


def _copy_profile_tree(src: Path, dst: Path) -> None:
    """Portable recursive copy of a Chrome profile, skipping cache dirs.

    Replaces the macOS-only ``rsync`` shell-out so the clone works on Windows
    and Linux too. ``_PROFILE_EXCLUDES`` are matched as path prefixes relative
    to ``src`` (same dirs rsync was excluding). Per-file errors are tolerated —
    a locked cache file must not abort the whole clone.
    """
    excludes = tuple(e.rstrip("/").replace("/", os.sep) for e in _PROFILE_EXCLUDES)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        rel = "" if rel == "." else rel
        # Prune excluded subtrees in-place so os.walk doesn't descend them.
        dirs[:] = [
            d
            for d in dirs
            if not any(
                (os.path.join(rel, d) if rel else d).startswith(ex) for ex in excludes
            )
        ]
        target_root = dst / rel if rel else dst
        target_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                shutil.copy2(os.path.join(root, f), target_root / f)
            except (OSError, shutil.Error):
                # Locked/transient file (Cookies-journal, lock, etc.) — skip.
                pass


def clone_profile(profile_dir_name: str | None = None) -> Path:
    """Clone the user's active Chrome profile into the debug Chrome profile.

    Copies ``<support>/<profile>`` -> ``<elevate_home>/chrome-debug/Default``
    and ``<support>/Local State`` -> ``<elevate_home>/chrome-debug/Local State``
    (the latter holds the OS-keystore-wrapped cookie key), excluding caches.
    Because the debug Chrome runs as the same OS user on the same machine, the
    keystore decrypts the cloned cookies — so logins carry over on macOS
    (Keychain), Windows (DPAPI) and Linux (libsecret/kwallet/plaintext).
    """
    profile_dir_name = profile_dir_name or detect_active_profile()
    src = chrome_support_dir() / profile_dir_name
    if not src.is_dir():
        raise FileNotFoundError(f"Chrome profile not found: {src}")

    dst = debug_profile_dir() / "Default"

    # Stop the debug Chrome so its profile dir is not being written mid-copy.
    stop_chrome()
    time.sleep(1.5)

    # Fresh clone each time — drop the old copy so deletes propagate.
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    _copy_profile_tree(src, dst)

    # Local State carries the encrypted cookie key + profile metadata. Without
    # it the cloned Cookies DB cannot be decrypted.
    local_state = chrome_support_dir() / "Local State"
    if local_state.is_file():
        try:
            shutil.copy2(local_state, debug_profile_dir() / "Local State")
        except (OSError, shutil.Error):
            pass

    # Singleton lock files belong to the source instance — never carry over.
    for lock in debug_profile_dir().glob("Singleton*"):
        try:
            lock.unlink()
        except OSError:
            pass
    return dst


def stop_chrome() -> None:
    """Kill any Chrome started by this module (matched by the debug port)."""
    if _is_windows():
        # No pkill on Windows. WMIC matches the debug-port flag in the command
        # line so we only kill the debug instance, not the user's real Chrome.
        subprocess.run(
            [
                "wmic",
                "process",
                "where",
                f"CommandLine like '%remote-debugging-port={CDP_PORT}%'",
                "delete",
            ],
            check=False,
            capture_output=True,
        )
        return
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
            # The profile is cloned from the user's real Chrome, so it carries
            # their extensions — including ad/content blockers and the Claude
            # for Chrome extension. Those run webRequest/declarativeNetRequest
            # rules that block the agent's navigations with
            # ERR_BLOCKED_BY_CLIENT. The agent only needs the cloned COOKIES
            # (logins), never the extensions, so disable them outright.
            "--disable-extensions",
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
    """Write and bootstrap the debug-Chrome LaunchAgent (macOS only).

    On Windows/Linux this is a no-op: there's no launchd, and the on-demand
    launch in ``ensure_debug_browser()`` brings the window up the first time
    the agent needs it each session, which is enough for the download-and-go
    path. (A future pass can add a Task Scheduler / systemd-user unit.)
    """
    if not _is_mac():
        return
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
    if not _is_mac():
        return
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


def set_auto_provision(enabled: bool) -> None:
    """Allow or block transparent auto-provisioning by the browser tool.

    ``elevate browser disable`` sets this False so the browser tool stops
    re-cloning Chrome on the next action. ``setup`` / ``sync`` clear it.
    """
    config = load_config()
    browser_cfg = config.setdefault("browser", {})
    if not isinstance(browser_cfg, dict):
        browser_cfg = {}
        config["browser"] = browser_cfg
    browser_cfg["debug_auto"] = bool(enabled)
    save_config(config)


def auto_provision_disabled() -> bool:
    """True only when the user explicitly ran ``elevate browser disable``."""
    try:
        config = load_config()
        browser_cfg = config.get("browser") or {}
        if isinstance(browser_cfg, dict):
            return browser_cfg.get("debug_auto") is False
    except Exception:
        pass
    return False


def ensure_debug_browser() -> str | None:
    """Auto-provision the visible debug browser, returning its CDP URL.

    Called transparently by the browser tool when no explicit CDP override
    is configured. The point: the first browser action just works against a
    visible, logged-in Chrome — no manual ``elevate browser setup`` step, no
    stalling while the agent figures out it has no profile.

    - No Chrome / unsupported OS / user disabled it -> None (caller falls back
      to the headless browser).
    - CDP already up -> CDP_URL.
    - Debug profile already cloned -> launch the window, return CDP_URL.
    - No debug profile -> clone the user's Chrome profile, install the
      keep-alive (macOS), wire config, launch, return CDP_URL.

    Any failure -> None, so the browser tool degrades to headless instead of
    breaking. The one-time profile clone on first use is unavoidable but only
    happens once; on macOS the LaunchAgent keeps the window up afterwards, and
    on Windows/Linux this same path re-launches it on demand next session.
    """
    try:
        if not is_supported() or chrome_binary() is None:
            return None
        if auto_provision_disabled():
            return None
        if cdp_is_up():
            return CDP_URL
        if (debug_profile_dir() / "Default").is_dir():
            return CDP_URL if launch_chrome(wait=True) else None
        # First run: no debug profile yet. Clone, wire up, launch.
        clone_profile()
        install_launch_agent()
        set_cdp_config(True)
        return CDP_URL if launch_chrome(wait=True) else None
    except Exception:
        return None


def setup() -> tuple[bool, str]:
    """Full setup: clone profile, install LaunchAgent, launch, wire config.

    Returns (ok, message).
    """
    if chrome_binary() is None:
        return False, (
            "Chrome not found. Install Google Chrome (or a Chromium-family "
            "browser), then re-run 'elevate browser setup'."
        )

    profile = detect_active_profile()
    try:
        clone_profile(profile)
    except Exception as exc:  # noqa: BLE001
        return False, f"Profile clone failed: {exc}"

    install_launch_agent()
    set_cdp_config(True)
    set_auto_provision(True)

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
