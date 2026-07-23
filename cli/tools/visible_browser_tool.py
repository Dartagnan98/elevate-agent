"""Pre-Beta visible-browser actions backed by the embedded desktop pane.

These names are intentionally user-facing and session-scoped. They preserve
the browser contract real-estate skills were authored against while the
generic ``browser_*`` tools remain available to other Elevate surfaces.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from elevate_constants import get_elevate_home
from elevate_cli.portal_credentials import PORTAL_ENV_ALIASES, resolve_portal_env
from tools import browser_pane
from tools.browser_tool import (
    _run_browser_command,
    browser_navigate,
    browser_snapshot,
    check_browser_requirements,
)
from tools.registry import registry


_READ_EFFECTS = {"read:browser"}
_SHOT_EFFECTS = {"read:browser", "write_local:browser"}
_AUTONOMOUS_EFFECTS = {
    "read:browser",
    "write_local:browser",
    "write_external:browser",
    "message_external:browser",
    "destructive:browser",
    "credential_access:browser",
    "financial:browser",
    "spawn:browser",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _task_id(value: str | None) -> str:
    return str(value or "default")


def browser_status(task_id: str | None = None) -> str:
    state = browser_pane.status(_task_id(task_id))
    if state is None:
        return _json(
            {
                "success": False,
                "open": False,
                "error": "The visible Elevate browser is not available.",
            }
        )
    return _json({"success": True, **state})


def browser_open(url: str, task_id: str | None = None) -> str:
    return browser_navigate(url=url, task_id=_task_id(task_id))


def browser_read(task_id: str | None = None) -> str:
    return browser_snapshot(full=True, task_id=_task_id(task_id))


def browser_fill(ref: str, value: str, task_id: str | None = None) -> str:
    task = _task_id(task_id)
    normalized = ref if ref.startswith("@") else f"@{ref}"
    result = _run_browser_command(task, "fill", [normalized, value])
    if not result.get("success"):
        return _json(
            {
                "success": False,
                "error": result.get("error", f"Failed to fill {normalized}"),
            }
        )
    return _json({"success": True, "filled": normalized})


def browser_drag(
    from_ref: str,
    to_ref: str,
    task_id: str | None = None,
) -> str:
    task = _task_id(task_id)
    source = from_ref if from_ref.startswith("@") else f"@{from_ref}"
    target = to_ref if to_ref.startswith("@") else f"@{to_ref}"
    result = _run_browser_command(task, "drag", [source, target])
    if not result.get("success"):
        return _json(
            {
                "success": False,
                "error": result.get("error", f"Failed to drag {source} to {target}"),
            }
        )
    return _json({"success": True, "from_ref": source, "to_ref": target})


def _portal_for_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if "skyslope" in host or "compliance" in host:
        return "compliance"
    if any(name in host for name in ("showingtime", "brokerbay", "showing")):
        return "showing"
    if any(name in host for name in ("matrix", "paragon", "xposure", "mls")):
        return "mls"

    configured = [
        portal
        for portal in PORTAL_ENV_ALIASES
        if resolve_portal_env(os.environ, portal).get("configured")
    ]
    return configured[0] if len(configured) == 1 else None


def _pick_login_ref(
    refs: dict[str, Any],
    *,
    password: bool,
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for ref, raw in refs.items():
        if not isinstance(raw, dict) or raw.get("disabled"):
            continue
        field_type = str(raw.get("type") or "").lower()
        name = str(raw.get("name") or "").lower()
        tag = str(raw.get("tag") or "").lower()
        if tag != "input":
            continue
        if password:
            score = 100 if field_type == "password" else 0
        else:
            score = 100 if field_type == "email" else 0
            if any(token in name for token in ("email", "username", "user name", "login")):
                score += 40
            if field_type in {"", "text"}:
                score += 10
        if score:
            candidates.append((score, ref))
    return max(candidates, default=(0, ""))[1] or None


def browser_login(task_id: str | None = None) -> str:
    """Fill the visible login step without returning stored credentials."""
    task = _task_id(task_id)
    state = browser_pane.status(task)
    if not state:
        return _json({"success": False, "error": "The visible browser is not available."})

    portal = _portal_for_url(str(state.get("url") or ""))
    if not portal:
        return _json(
            {
                "success": False,
                "error": (
                    "Could not choose a saved portal credential for this page. "
                    "Open the configured MLS, compliance, or showing portal first."
                ),
            }
        )
    credential = resolve_portal_env(os.environ, portal)
    if not credential.get("configured"):
        return _json(
            {
                "success": False,
                "error": f"No complete saved {portal} portal credential is configured.",
            }
        )

    snap = browser_pane.run_command("snapshot", [], session_id=task)
    refs = ((snap or {}).get("data") or {}).get("refs") or {}
    if not isinstance(refs, dict):
        refs = {}
    email_ref = _pick_login_ref(refs, password=False)
    password_ref = _pick_login_ref(refs, password=True)
    filled: list[str] = []

    if email_ref:
        result = browser_pane.run_command(
            "fill",
            [email_ref, str(credential.get("loginEmail") or "")],
            session_id=task,
        )
        if result and result.get("success"):
            filled.append("email")
    if password_ref:
        result = browser_pane.run_command(
            "fill",
            [password_ref, str(credential.get("loginPassword") or "")],
            session_id=task,
        )
        if result and result.get("success"):
            filled.append("password")

    if not filled:
        return _json(
            {
                "success": False,
                "error": "No visible email, username, or password field was found.",
            }
        )
    return _json(
        {
            "success": True,
            "portal": portal,
            "filled": filled,
            "submitted": False,
            "next": "Review the visible page and click Continue or Sign in.",
        }
    )


def browser_shot(task_id: str | None = None) -> str:
    result = _run_browser_command(_task_id(task_id), "screenshot", [])
    if not result.get("success"):
        return _json(
            {
                "success": False,
                "error": result.get("error", "Failed to capture the visible browser."),
            }
        )
    return _json(
        {
            "success": True,
            "path": (result.get("data") or {}).get("path"),
        }
    )


def _recording_dir() -> Path:
    return get_elevate_home() / "browser_skills"


def browser_recordings() -> str:
    root = _recording_dir()
    recordings = []
    if root.exists():
        for path in sorted(root.glob("*.json")):
            recordings.append(
                {
                    "slug": path.stem,
                    "updated_at": path.stat().st_mtime,
                }
            )
    return _json({"success": True, "recordings": recordings})


def browser_play(slug: str, task_id: str | None = None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(slug or "")):
        return _json({"success": False, "error": "Invalid browser recording slug."})
    path = _recording_dir() / f"{slug}.json"
    if not path.is_file():
        return _json({"success": False, "error": f"No browser recording named '{slug}'."})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return _json({"success": False, "error": f"Could not read recording: {error}"})
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(steps, list) or len(steps) > 200:
        return _json({"success": False, "error": "The browser recording is invalid."})

    task = _task_id(task_id)
    completed = 0
    for step in steps:
        if not isinstance(step, dict):
            return _json({"success": False, "error": f"Invalid step {completed + 1}."})
        action = str(step.get("action") or "")
        if action == "open":
            result = _run_browser_command(task, "open", [str(step.get("url") or "")])
        elif action in {"click", "press"}:
            key = "ref" if action == "click" else "key"
            result = _run_browser_command(task, action, [str(step.get(key) or "")])
        elif action in {"fill", "type"}:
            result = _run_browser_command(
                task,
                action,
                [str(step.get("ref") or ""), str(step.get("value") or "")],
            )
        elif action == "drag":
            result = _run_browser_command(
                task,
                "drag",
                [str(step.get("from_ref") or ""), str(step.get("to_ref") or "")],
            )
        elif action == "scroll":
            result = _run_browser_command(
                task,
                "scroll",
                [str(step.get("direction") or "down"), str(step.get("amount") or 500)],
            )
        else:
            return _json({"success": False, "error": f"Unsupported step action: {action}"})
        if not result.get("success"):
            return _json(
                {
                    "success": False,
                    "completed_steps": completed,
                    "error": result.get("error", f"Step {completed + 1} failed."),
                }
            )
        completed += 1
    return _json({"success": True, "slug": slug, "completed_steps": completed})


def _schema(name: str, description: str, properties=None, required=None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


_SCHEMAS = {
    "browser_status": _schema(
        "browser_status",
        "Check whether the visible in-app browser is open for this session, list its tabs, and report the active page.",
    ),
    "browser_open": _schema(
        "browser_open",
        "Open a URL in the visible in-app browser. Uses the realtor's persistent cookies and logins.",
        {"url": {"type": "string", "description": "The URL to open."}},
        ["url"],
    ),
    "browser_read": _schema(
        "browser_read",
        "Read the current visible page as text plus ref-addressed interactive elements.",
    ),
    "browser_fill": _schema(
        "browser_fill",
        "Type a value into a visible browser field by its ref from browser_read.",
        {"ref": {"type": "string"}, "value": {"type": "string"}},
        ["ref", "value"],
    ),
    "browser_drag": _schema(
        "browser_drag",
        "Drag one visible-browser element onto another. Both refs come from browser_read.",
        {"from_ref": {"type": "string"}, "to_ref": {"type": "string"}},
        ["from_ref", "to_ref"],
    ),
    "browser_login": _schema(
        "browser_login",
        "Fill the current portal login step with the realtor's saved credential. The password is never returned. Call again after an email-first Continue step.",
    ),
    "browser_shot": _schema(
        "browser_shot",
        "Take a screenshot of the current visible browser page.",
    ),
    "browser_recordings": _schema(
        "browser_recordings",
        "List saved visible-browser skills that can be replayed.",
    ),
    "browser_play": _schema(
        "browser_play",
        "Replay a saved visible-browser skill by slug.",
        {"slug": {"type": "string"}},
        ["slug"],
    ),
}


registry.register(
    name="browser_status",
    toolset="browser",
    schema=_SCHEMAS["browser_status"],
    handler=lambda _args, **kw: browser_status(kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="🌐",
    effects=_READ_EFFECTS,
)
registry.register(
    name="browser_open",
    toolset="browser",
    schema=_SCHEMAS["browser_open"],
    handler=lambda args, **kw: browser_open(args.get("url", ""), kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="🌐",
    effects=_AUTONOMOUS_EFFECTS,
)
registry.register(
    name="browser_read",
    toolset="browser",
    schema=_SCHEMAS["browser_read"],
    handler=lambda _args, **kw: browser_read(kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="📖",
    effects=_READ_EFFECTS,
)
registry.register(
    name="browser_fill",
    toolset="browser",
    schema=_SCHEMAS["browser_fill"],
    handler=lambda args, **kw: browser_fill(
        args.get("ref", ""),
        args.get("value", ""),
        kw.get("task_id"),
    ),
    check_fn=check_browser_requirements,
    emoji="⌨️",
    effects=_AUTONOMOUS_EFFECTS,
)
registry.register(
    name="browser_drag",
    toolset="browser",
    schema=_SCHEMAS["browser_drag"],
    handler=lambda args, **kw: browser_drag(
        args.get("from_ref", ""),
        args.get("to_ref", ""),
        kw.get("task_id"),
    ),
    check_fn=check_browser_requirements,
    emoji="↔️",
    effects=_AUTONOMOUS_EFFECTS,
)
registry.register(
    name="browser_login",
    toolset="browser",
    schema=_SCHEMAS["browser_login"],
    handler=lambda _args, **kw: browser_login(kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="🔐",
    effects=_AUTONOMOUS_EFFECTS,
)
registry.register(
    name="browser_shot",
    toolset="browser",
    schema=_SCHEMAS["browser_shot"],
    handler=lambda _args, **kw: browser_shot(kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="📸",
    effects=_SHOT_EFFECTS,
)
registry.register(
    name="browser_recordings",
    toolset="browser",
    schema=_SCHEMAS["browser_recordings"],
    handler=lambda _args, **_kw: browser_recordings(),
    check_fn=check_browser_requirements,
    emoji="🎬",
    effects=_READ_EFFECTS,
)
registry.register(
    name="browser_play",
    toolset="browser",
    schema=_SCHEMAS["browser_play"],
    handler=lambda args, **kw: browser_play(args.get("slug", ""), kw.get("task_id")),
    check_fn=check_browser_requirements,
    emoji="▶️",
    effects=_AUTONOMOUS_EFFECTS,
)
