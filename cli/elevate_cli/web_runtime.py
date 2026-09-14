from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def init_workspace_root(*, project_root: Path) -> Path:
    """Resolve and initialize the user workspace root."""
    raw = os.environ.get("ELEVATE_WORKSPACE", "").strip()
    if not raw:
        return project_root
    try:
        root = Path(raw).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").exists():
            subprocess.run(
                ["git", "init"],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        return root
    except Exception:
        return project_root


def is_packaged_desktop_runtime(*, project_root: Path) -> bool:
    """True when this API is running from the immutable Electron app bundle."""
    if os.environ.get("ELEVATE_DESKTOP_APP") == "1":
        return True
    parts = project_root.parts
    return (
        any(part.endswith(".app") for part in parts)
        and "Contents" in parts
        and "Resources" in parts
    )


def probe_gateway_health(
    *,
    gateway_health_url: str | None,
    gateway_health_timeout: float,
) -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint."""
    if not gateway_health_url:
        return False, None

    base = gateway_health_url.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=gateway_health_timeout) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


def ensure_project_root_on_path(project_root: Path) -> None:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
