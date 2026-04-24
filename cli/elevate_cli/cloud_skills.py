"""
Cloud skill access — fetch skill bodies from the Elevate backend.

Skills live server-side, gated by subscription tier. This module:
  - lists skills available to the user (manifest only, no body)
  - fetches a skill body on demand (GET /api/skills/run)
  - mounts all available skills into a session-ephemeral tmp dir so the
    existing Hermes skill loader picks them up

The tmp dir is wiped when the process exits.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from elevate_cli import license as elevate_license

_MOUNT_DIR: Optional[Path] = None


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=elevate_license.BACKEND_URL,
        timeout=15.0,
        headers={"user-agent": "elevate-cli/0.11"},
    )


def _auth_header(lic: elevate_license.License) -> dict:
    return {"authorization": f"Bearer {lic.access_token}"}


def list_skills() -> list[dict]:
    lic = elevate_license.ensure_valid()
    with _client() as client:
        resp = client.get("/api/skills/list", headers=_auth_header(lic))
    if not resp.is_success:
        raise elevate_license.LicenseError(f"list failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("skills", [])


def fetch_skill(name: str, args: Optional[dict] = None) -> dict:
    """Fetch a single skill's manifest + body."""
    lic = elevate_license.ensure_valid()
    with _client() as client:
        resp = client.post(
            "/api/skills/run",
            headers=_auth_header(lic),
            json={"skill_name": name, "args": args or {}},
        )
    if resp.status_code == 404:
        raise elevate_license.LicenseError(f"skill '{name}' not found")
    if resp.status_code == 403:
        raise elevate_license.LicenseError(f"skill '{name}' requires a higher subscription tier")
    if not resp.is_success:
        raise elevate_license.LicenseError(f"fetch failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _write_skill(root: Path, name: str, body: str, manifest: dict) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md with YAML frontmatter from the manifest
    front = ["---", f"name: {name}"]
    desc = manifest.get("description")
    if desc:
        front.append(f"description: {desc}")
    tags = manifest.get("tags")
    if tags:
        front.append(f"tags: [{', '.join(tags)}]")
    front.append("---")
    content = "\n".join(front) + "\n\n" + body
    (skill_dir / "SKILL.md").write_text(content)


def mount_all() -> Optional[Path]:
    """Fetch all subscription skills and write to a tmp dir. Return the path."""
    global _MOUNT_DIR
    if _MOUNT_DIR is not None:
        return _MOUNT_DIR

    try:
        skills = list_skills()
    except elevate_license.LicenseError as e:
        print(f"cloud skills unavailable: {e}", file=sys.stderr)
        return None

    if not skills:
        return None

    tmp = Path(tempfile.mkdtemp(prefix="elevate-skills-"))
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))

    for stub in skills:
        try:
            full = fetch_skill(stub["name"])
        except elevate_license.LicenseError:
            continue
        _write_skill(tmp, full["name"], full.get("body", ""), full.get("manifest", {}))

    _MOUNT_DIR = tmp
    # Point Hermes's skill loader at the mount dir (additive).
    existing = os.environ.get("ELEVATE_EXTRA_SKILLS_PATH", "")
    os.environ["ELEVATE_EXTRA_SKILLS_PATH"] = (
        f"{existing}:{tmp}" if existing else str(tmp)
    )
    return tmp


# --- CLI subcommands ---

def cmd_cloud_list(args) -> int:
    try:
        skills = list_skills()
    except elevate_license.LicenseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not skills:
        print("(no skills available at your tier)")
        return 0
    for s in skills:
        desc = (s.get("manifest") or {}).get("description", "")
        print(f"  {s['name']:<28} [{s['tier_required']}]  {desc}")
    return 0


def cmd_cloud_fetch(args) -> int:
    try:
        skill = fetch_skill(args.name)
    except elevate_license.LicenseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(skill, indent=2))
    else:
        print(skill.get("body", ""))
    return 0
