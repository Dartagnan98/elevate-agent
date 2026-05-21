#!/usr/bin/env python3
"""Computer-use tool — drive native macOS apps (mouse, keyboard, screen).

Elevate's browser tool covers web apps. This tool covers everything else:
Finder, native MLS apps, System Settings, any desktop app. It captures the
screen and posts real mouse/keyboard events.

Backends, all macOS-native or one Homebrew install:
  - ``screencapture`` (built in) — screenshots.
  - ``cliclick`` (``brew install cliclick``) — mouse + keyboard events.
  - ``osascript`` (built in) — frontmost-app UI element snapshot.

Permissions: the process that runs the gateway needs macOS **Accessibility**
(for clicks/keys) and **Screen Recording** (for screenshots). macOS prompts
for these the first time; grant them in System Settings > Privacy & Security.

The agent should screenshot, then call ``vision_analyze`` on the returned
path to see the screen, then click/type by coordinate. There is no DOM here —
coordinates come from looking at the screenshot.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.registry import registry, tool_error

_CLICK_ACTIONS = {
    "left_click": "c",
    "right_click": "rc",
    "double_click": "dc",
    "move": "m",
}
_VALID_ACTIONS = set(_CLICK_ACTIONS) | {
    "screenshot",
    "ui_snapshot",
    "type",
    "key",
    "scroll",
}

# cliclick key names accepted for the `key` action (single keys / chord parts
# that are not plain characters). Modifiers are handled separately.
_SPECIAL_KEYS = {
    "return", "enter", "esc", "escape", "tab", "space", "delete",
    "fwd-delete", "home", "end", "page-up", "page-down",
    "arrow-up", "arrow-down", "arrow-left", "arrow-right",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12",
}
_MODIFIERS = {"cmd", "command", "ctrl", "control", "alt", "option", "shift", "fn"}
_MOD_MAP = {"command": "cmd", "control": "ctrl", "option": "alt"}

# macOS key chords that lock the screen, sleep the Mac, or log the user out.
# Modifier sets use cliclick-normalized names (cmd/ctrl/alt/shift/fn) and are
# matched unordered, so chord direction does not matter. If the computer tool
# fires one of these mid-task it strands both the agent and the user behind
# the login window — so _do_key refuses them outright.
#   cmd+ctrl+q          → Lock Screen
#   cmd+shift+q         → Log Out (with dialog)
#   cmd+shift+alt+q     → Log Out immediately
_LOCKOUT_COMBOS = {
    (frozenset({"cmd", "ctrl"}), "q"),
    (frozenset({"cmd", "shift"}), "q"),
    (frozenset({"cmd", "shift", "alt"}), "q"),
    (frozenset({"cmd", "shift", "ctrl"}), "q"),
    (frozenset({"cmd", "shift", "ctrl", "alt"}), "q"),
}


# Homebrew installs cliclick here, but launchd-spawned processes (the Elevate
# gateway) often run with a minimal PATH that excludes these dirs — so
# shutil.which alone is unreliable. Probe the known locations too.
_CLICLICK_FALLBACKS = (
    "/opt/homebrew/bin/cliclick",  # Apple Silicon Homebrew
    "/usr/local/bin/cliclick",     # Intel Homebrew
)


def _find_cliclick() -> str | None:
    """Locate the cliclick binary regardless of the process PATH."""
    found = shutil.which("cliclick")
    if found:
        return found
    for candidate in _CLICLICK_FALLBACKS:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def check_computer_requirements() -> bool:
    """Available on macOS once cliclick is installed."""
    return sys.platform == "darwin" and _find_cliclick() is not None


# When a computer-use action fails for lack of a macOS permission, route the
# user straight to the exact Privacy & Security pane that fixes it instead of
# leaving them to hunt for it (or to dismiss a recurring consent dialog that
# never sticks). Each pane is opened at most once per process so System
# Settings is never spammed.
_PRIVACY_PANES = {
    "full_disk": ("Privacy_AllFiles", "Full Disk Access"),
    "accessibility": ("Privacy_Accessibility", "Accessibility"),
    "screen": ("Privacy_ScreenCapture", "Screen Recording"),
    "automation": ("Privacy_Automation", "Automation"),
}
_PRIVACY_PANES_OPENED: set[str] = set()


def _route_to_permission(pane: str) -> str:
    """Open the relevant Privacy & Security pane once and return guidance."""
    anchor, label = _PRIVACY_PANES.get(pane, ("", pane))
    if anchor and pane not in _PRIVACY_PANES_OPENED:
        _PRIVACY_PANES_OPENED.add(pane)
        try:
            subprocess.run(
                [
                    "open",
                    "x-apple.systempreferences:com.apple.preference."
                    f"security?{anchor}",
                ],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    return (
        f" This action needs the macOS '{label}' permission. Opened System "
        f"Settings > Privacy & Security > {label} — switch 'Elevate' ON there "
        f"(add it with the + button if it is not listed; the app is at "
        f"~/Applications/Elevate.app), then retry."
    )


def _cliclick(*commands: str, timeout: float = 15.0) -> tuple[bool, str]:
    binary = _find_cliclick()
    if not binary:
        return False, (
            "cliclick not installed. Run 'brew install cliclick', then grant "
            "the gateway Accessibility permission in System Settings."
        )
    try:
        proc = subprocess.run(
            [binary, *commands],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "cliclick timed out"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        base = err or "cliclick failed"
        return False, base + _route_to_permission("accessibility")
    return True, (proc.stdout or "").strip()


# JavaScript-for-Automation reads NSScreen directly from the osascript
# process — no app-automation permission needed (unlike querying Finder).
_LOGICAL_SIZE_SCRIPT = (
    'ObjC.import("AppKit"); var f = $.NSScreen.mainScreen.frame; '
    'Math.round(f.size.width) + "x" + Math.round(f.size.height)'
)


def _logical_size() -> tuple[int, int] | None:
    """Main display size in logical points — the coordinate space cliclick
    uses. screencapture produces Retina (2x) pixels, so screenshots must be
    downscaled to this size or coordinates read off them will be 2x wrong."""
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _LOGICAL_SIZE_SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        w, _, h = proc.stdout.strip().partition("x")
        if w.isdigit() and h.isdigit() and int(w) > 0 and int(h) > 0:
            return int(w), int(h)
    except Exception:
        pass
    return None


def _take_screenshot() -> tuple[bool, str]:
    out_path = Path(tempfile.gettempdir()) / f"elevate-screen-{int(time.time())}.png"
    try:
        proc = subprocess.run(
            ["screencapture", "-x", str(out_path)],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return False, "screencapture timed out"
    if proc.returncode != 0 or not out_path.exists():
        return False, "screencapture failed." + _route_to_permission("screen")
    # Downscale Retina pixels to logical points so coordinates the agent
    # reads off the screenshot match what cliclick will click.
    logical = _logical_size()
    if logical:
        try:
            subprocess.run(
                ["sips", "--resampleWidth", str(logical[0]), str(out_path)],
                capture_output=True, text=True, timeout=20,
            )
        except Exception:
            pass
    return True, str(out_path)


# NOTE: do not name a variable `result` — it is AppleScript's implicit
# last-command variable, silently overwritten by every command (so
# `result & "text"` ends up coercing the last command's object, e.g. a
# window, into a string and throws -1700). Use `outText` instead.
_UI_SNAPSHOT_SCRIPT = r'''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set outText to "frontmost app: " & appName & linefeed
    set wantRoles to {"AXButton", "AXMenuButton", "AXPopUpButton", ¬
        "AXTextField", "AXTextArea", "AXCheckBox", "AXRadioButton", ¬
        "AXLink", "AXTab", "AXSlider", "AXComboBox"}
    try
        if (count of windows of frontApp) is 0 then
            return outText & "(no windows)"
        end if
        set w to window 1 of frontApp
        set winName to (name of w) as text
        set outText to outText & "window: " & winName & linefeed
        set els to entire contents of w
        set shown to 0
        repeat with el in els
            if shown > 120 then exit repeat
            try
                set elRole to role of el
                if elRole is in wantRoles then
                    set elName to ""
                    try
                        set rawName to name of el
                        if rawName is not missing value then ¬
                            set elName to rawName as text
                    end try
                    if elName is "" then
                        try
                            set rawDesc to description of el
                            if rawDesc is not missing value then ¬
                                set elName to rawDesc as text
                        end try
                    end if
                    if elName is "" then set elName to "(unlabeled)"
                    set elPos to position of el
                    set elSize to size of el
                    set cx to ((item 1 of elPos) + ((item 1 of elSize) / 2)) as integer
                    set cy to ((item 2 of elPos) + ((item 2 of elSize) / 2)) as integer
                    set outText to outText & elRole & " | " & elName & ¬
                        " | click=" & cx & "," & cy & linefeed
                    set shown to shown + 1
                end if
            end try
        end repeat
    on error errMsg number errNum
        -- errMsg can hold an uncoercible object reference (Electron apps),
        -- so coercing it can itself throw — fall back to the numeric code.
        try
            set outText to outText & "(no window detail: " & (errMsg as text) & ")"
        on error
            set outText to outText & "(no window detail: AX error " & errNum & ")"
        end try
    end try
    return outText
end tell
'''


# ui_snapshot spawns `osascript` to talk to System Events. macOS gates
# that behind the AppleEvents/Automation TCC permission. If the gateway
# process can't get (or hold) that grant, every call re-triggers the
# "would like to access data from other apps" dialog — an unstoppable
# prompt loop for the user. So once ui_snapshot fails, we latch it OFF
# for the rest of the process: further calls return the fallback message
# WITHOUT spawning osascript, so no dialog can fire again. A gateway
# restart clears the latch (one prompt worst case, never a loop).
_UI_SNAPSHOT_DISABLED = False

_UI_SNAPSHOT_FALLBACK = (
    "ui_snapshot is unavailable in this process (macOS did not grant the "
    "gateway AppleEvents/Automation access). Do NOT retry ui_snapshot — it "
    "is disabled for this session. Use action 'screenshot' + vision_analyze "
    "instead; that always works and gives you click coordinates."
)


def _ui_snapshot() -> tuple[bool, str]:
    global _UI_SNAPSHOT_DISABLED
    if _UI_SNAPSHOT_DISABLED:
        return False, _UI_SNAPSHOT_FALLBACK
    try:
        proc = subprocess.run(
            ["osascript", "-e", _UI_SNAPSHOT_SCRIPT],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        # A hung osascript is almost always a TCC dialog blocking the call.
        # Latch off so the next call can't spawn another blocking dialog.
        _UI_SNAPSHOT_DISABLED = True
        return False, _UI_SNAPSHOT_FALLBACK + _route_to_permission("accessibility")
    err = (proc.stderr or "").strip()
    out = (proc.stdout or "").strip()
    # entire-contents failures (Electron apps, missing Accessibility grant)
    # surface inside stdout as "(no window detail: ...)" — treat as soft fail.
    failed = proc.returncode != 0 or "(no window detail" in out
    if failed:
        detail = err or out
        # Latch ui_snapshot off for the session so it can never re-prompt.
        _UI_SNAPSHOT_DISABLED = True
        # osascript drives System Events, gated by the Accessibility TCC
        # permission ("not allowed assistive access") — NOT Full Disk Access.
        return False, (
            f"ui_snapshot could not read the UI tree ({detail}). It is now "
            f"disabled for this session — do NOT retry it. Use action "
            f"'screenshot' + vision_analyze instead; that always works."
            + _route_to_permission("accessibility")
        )
    return True, out


def _do_key(spec: str) -> tuple[bool, str]:
    """Press a key or chord. spec like 'return', 'cmd+c', 'ctrl+shift+tab'."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        return False, "key action requires a non-empty 'text' (e.g. 'cmd+c')"
    mods = [_MOD_MAP.get(p, p) for p in parts if p in _MODIFIERS]
    keys = [p for p in parts if p not in _MODIFIERS]
    if len(keys) != 1:
        return False, f"key spec must have exactly one non-modifier key: {spec!r}"
    key = keys[0]

    # Guard against chords that lock, sleep, or log out the Mac — these strand
    # the agent (and the user) behind the login window mid-task. Compared as an
    # unordered modifier set so "cmd+ctrl+q" and "ctrl+cmd+q" both match.
    _modset = frozenset(mods)
    if (_modset, key) in _LOCKOUT_COMBOS:
        return False, (
            f"Refused key chord {spec!r}: it locks / sleeps / logs out the "
            f"Mac, which would strand this session behind the login window. "
            f"Lock-screen and logout shortcuts are blocked for the computer "
            f"tool. If you meant to quit an app, use 'cmd+q' alone."
        )

    cmds: list[str] = []
    if mods:
        cmds.append("kd:" + ",".join(mods))
    if key in _SPECIAL_KEYS:
        kp = "enter" if key == "enter" else key
        kp = "escape" if kp == "esc" else kp
        # cliclick uses: return, esc, tab, space, delete, arrow-*, page-*, f1..
        kp = {"escape": "esc"}.get(kp, kp)
        cmds.append(f"kp:{kp}")
    elif len(key) == 1:
        cmds.append(f"t:{key}")
    else:
        if mods:
            return False, f"unknown key name: {key!r}"
        return False, f"unknown key {key!r} — use a single char or {sorted(_SPECIAL_KEYS)}"
    if mods:
        cmds.append("ku:" + ",".join(mods))
    return _cliclick(*cmds)


def _keep_awake() -> None:
    """Keep the display awake while the computer tool is in use.

    An idle Mac dims, sleeps the display, runs the screensaver, then hits the
    idle lock — any of which strands the agent mid-task. `caffeinate -u`
    declares user activity, which wakes the display now and resets the idle
    timer; `-t 90` lets the assertion lapse 90s after the agent goes quiet so
    the Mac is not pinned awake forever. Fire-and-forget, called once per
    computer action, so a continuous agent run never lets the screen idle.
    """
    try:
        subprocess.Popen(
            ["caffeinate", "-u", "-t", "90"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def computer_tool(args: dict) -> str:
    if sys.platform != "darwin":
        return tool_error("The computer tool is macOS-only.")
    _keep_awake()
    action = (args.get("action") or "").strip()
    if action not in _VALID_ACTIONS:
        return tool_error(
            f"Unknown action {action!r}. Valid: {sorted(_VALID_ACTIONS)}"
        )

    if action == "screenshot":
        ok, result = _take_screenshot()
        if not ok:
            return tool_error(result)
        logical = _logical_size()
        return json.dumps({
            "action": "screenshot",
            "path": result,
            "screen_resolution": (
                f"{logical[0]}x{logical[1]}" if logical else "unknown"
            ),
            "next": (
                "Call vision_analyze on this path to see the screen. "
                "Coordinates on this screenshot map 1:1 to click coordinates."
            ),
        }, ensure_ascii=False)

    if action == "ui_snapshot":
        ok, result = _ui_snapshot()
        if not ok:
            return tool_error(result)
        return json.dumps({"action": "ui_snapshot", "elements": result},
                           ensure_ascii=False)

    if action in _CLICK_ACTIONS:
        x, y = args.get("x"), args.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return tool_error(f"action '{action}' requires numeric 'x' and 'y'.")
        ok, result = _cliclick(f"{_CLICK_ACTIONS[action]}:{int(x)},{int(y)}")
        if not ok:
            return tool_error(result)
        return json.dumps({"action": action, "x": int(x), "y": int(y),
                           "status": "done"}, ensure_ascii=False)

    if action == "type":
        text = args.get("text")
        if not text:
            return tool_error("action 'type' requires 'text'.")
        ok, result = _cliclick(f"t:{text}", timeout=30.0)
        if not ok:
            return tool_error(result)
        return json.dumps({"action": "type", "chars": len(str(text)),
                           "status": "done"}, ensure_ascii=False)

    if action == "key":
        spec = args.get("text")
        if not spec:
            return tool_error("action 'key' requires 'text' (e.g. 'cmd+c').")
        ok, result = _do_key(str(spec))
        if not ok:
            return tool_error(result)
        return json.dumps({"action": "key", "keys": spec, "status": "done"},
                           ensure_ascii=False)

    if action == "scroll":
        direction = (args.get("direction") or "down").strip().lower()
        if direction not in ("up", "down"):
            return tool_error("scroll 'direction' must be 'up' or 'down'.")
        amount = args.get("amount", 3)
        try:
            amount = max(1, min(int(amount), 20))
        except (TypeError, ValueError):
            amount = 3
        key = "page-down" if direction == "down" else "page-up"
        ok, result = _cliclick(*([f"kp:{key}"] * amount))
        if not ok:
            return tool_error(result)
        return json.dumps({"action": "scroll", "direction": direction,
                           "amount": amount, "status": "done"},
                          ensure_ascii=False)

    return tool_error(f"Unhandled action {action!r}")


COMPUTER_SCHEMA = {
    "name": "computer",
    "description": (
        "Control the macOS desktop — drive native apps (Finder, System "
        "Settings, native MLS/desktop software, anything not in a browser). "
        "Posts real mouse and keyboard events.\n\n"
        "Workflow: take a 'screenshot', call vision_analyze on the returned "
        "path to see the screen and read coordinates, then 'left_click' / "
        "'type' / 'key' to act. Coordinates are screen pixels from the "
        "top-left. 'ui_snapshot' lists the frontmost app's UI elements with "
        "their centre coordinates when the accessibility API exposes them.\n\n"
        "For web apps use the browser_* tools instead — they are more "
        "reliable than pixel-clicking. Requires macOS Accessibility and "
        "Screen Recording permissions for the Elevate gateway process."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_VALID_ACTIONS),
                "description": (
                    "screenshot: capture the screen | ui_snapshot: list "
                    "frontmost app UI elements | left_click/right_click/"
                    "double_click/move: pointer at x,y | type: type text | "
                    "key: press a key or chord like 'cmd+c' | scroll: page "
                    "up/down"
                ),
            },
            "x": {"type": "number", "description": "X pixel for click/move."},
            "y": {"type": "number", "description": "Y pixel for click/move."},
            "text": {
                "type": "string",
                "description": (
                    "For 'type': the literal text. For 'key': a key name "
                    "('return', 'esc', 'arrow-down') or chord ('cmd+c')."
                ),
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "For 'scroll': scroll direction.",
            },
            "amount": {
                "type": "integer",
                "description": "For 'scroll': number of pages (1-20, default 3).",
            },
        },
        "required": ["action"],
    },
}


registry.register(
    name="computer",
    toolset="computer",
    schema=COMPUTER_SCHEMA,
    handler=lambda args, **kw: computer_tool(args),
    check_fn=check_computer_requirements,
    emoji="🖥️",
)
