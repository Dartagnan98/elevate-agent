"""
Cloud skill access — fetch skill bodies from the Elevate backend.

Skills live server-side, gated by subscription tier. This module:
  - lists skills available to the user (manifest only, no body)
  - fetches a skill body on demand (GET /api/skills/run)
  - syncs all available skills into ELEVATE_HOME/cloud-skills so the
    existing Elevate skill loader picks them up across restarts

The cloud-skills directory is profile-local and entitlement-controlled by the
backend. Sync removes previously synced cloud skills that are no longer
available at the current tier.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import httpx

from elevate_cli import license as elevate_license
from elevate_constants import get_elevate_home

_MOUNT_DIR: Optional[Path] = None
_MOUNTED_SKILLS: list[str] = []
_MARKER = ".elevate-cloud-skill.json"


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=elevate_license.backend_url(),
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


def cloud_skills_dir() -> Path:
    override = os.environ.get("ELEVATE_CLOUD_SKILLS_DIR", "").strip()
    return Path(override).expanduser() if override else get_elevate_home() / "cloud-skills"


def _skill_dir_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name.strip())
    safe = safe.strip(".-")
    return safe or "cloud-skill"


def _add_extra_skills_path(path: Path) -> None:
    """Expose the persistent cloud skill dir to this process, if needed."""
    resolved = str(path.resolve())
    existing = os.environ.get("ELEVATE_EXTRA_SKILLS_PATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if resolved not in parts:
        parts.append(resolved)
        os.environ["ELEVATE_EXTRA_SKILLS_PATH"] = os.pathsep.join(parts)


def _write_skill(root: Path, name: str, body: str, manifest: dict) -> None:
    skill_dir = root / _skill_dir_name(name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md with YAML frontmatter from the manifest
    front = ["---", f"name: {json.dumps(name)}"]
    desc = manifest.get("description")
    if desc:
        front.append(f"description: {json.dumps(str(desc))}")
    category = (
        manifest.get("category")
        or manifest.get("skill_category")
        or manifest.get("section_key")
    )
    if category:
        front.append(f"category: {json.dumps(str(category))}")
    tags = manifest.get("tags")
    if tags:
        front.append(f"tags: {json.dumps(list(tags))}")
    entitlement = (
        manifest.get("entitlement")
        or manifest.get("requires_entitlement")
        or manifest.get("required_entitlement")
    )
    if entitlement:
        front.extend(["access:", f"  entitlement: {json.dumps(str(entitlement))}"])
    front.append("---")
    content = "\n".join(front) + "\n\n" + body
    skill_tmp = skill_dir / "SKILL.md.tmp"
    skill_tmp.write_text(content, encoding="utf-8")
    skill_tmp.replace(skill_dir / "SKILL.md")

    marker_tmp = skill_dir / f"{_MARKER}.tmp"
    marker_tmp.write_text(
        json.dumps(
            {
                "name": name,
                "source": "elevation-real-estate-hq",
                "manifest": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    marker_tmp.replace(skill_dir / _MARKER)


def _read_marker_name(path: Path) -> Optional[str]:
    try:
        marker = json.loads((path / _MARKER).read_text(encoding="utf-8"))
    except Exception:
        return None
    name = marker.get("name")
    return str(name) if name else None


def _remove_stale_synced_skills(root: Path, available_names: set[str]) -> list[str]:
    removed: list[str] = []
    if not root.exists():
        return removed
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = _read_marker_name(child)
        if not name or name in available_names:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(name)
    return removed


def _existing_synced_names(root: Path) -> list[str]:
    names: list[str] = []
    if not root.exists():
        return names
    for child in root.iterdir():
        if not child.is_dir() or not (child / "SKILL.md").exists():
            continue
        names.append(_read_marker_name(child) or child.name)
    return sorted(names)


def mounted_skill_names() -> list[str]:
    """Return the names mounted into the current process."""
    return list(_MOUNTED_SKILLS)


def sync_all(target_dir: Optional[Path] = None) -> dict:
    """Fetch all subscription skills and persist them to disk."""
    global _MOUNT_DIR, _MOUNTED_SKILLS
    root = target_dir or cloud_skills_dir()
    _MOUNTED_SKILLS = []
    try:
        skills = list_skills()
    except elevate_license.LicenseError as e:
        print(f"cloud skills unavailable: {e}", file=sys.stderr)
        return {
            "path": None,
            "skill_count": 0,
            "skill_names": [],
            "removed": [],
            "errors": [str(e)],
        }

    if not skills:
        return {
            "path": str(root),
            "skill_count": 0,
            "skill_names": [],
            "removed": _remove_stale_synced_skills(root, set()),
            "errors": [],
        }

    root.mkdir(parents=True, exist_ok=True)
    available_names = {str(stub.get("name", "")).strip() for stub in skills if stub.get("name")}
    removed = _remove_stale_synced_skills(root, available_names)

    mounted: list[str] = []
    errors: list[str] = []
    for stub in skills:
        try:
            full = fetch_skill(stub["name"])
        except elevate_license.LicenseError as exc:
            errors.append(f"{stub.get('name')}: {exc}")
            continue
        name = full["name"]
        _write_skill(root, name, full.get("body", ""), full.get("manifest", {}))
        mounted.append(name)

    _MOUNT_DIR = root if mounted else None
    _MOUNTED_SKILLS = mounted
    if mounted:
        _add_extra_skills_path(root)
    return {
        "path": str(root),
        "skill_count": len(mounted),
        "skill_names": mounted,
        "removed": removed,
        "errors": errors,
    }


def mount_all() -> Optional[Path]:
    """Sync subscription skills and expose the persistent dir to this process."""
    global _MOUNT_DIR, _MOUNTED_SKILLS
    if _MOUNT_DIR is not None:
        _add_extra_skills_path(_MOUNT_DIR)
        return _MOUNT_DIR
    root = cloud_skills_dir()
    existing = _existing_synced_names(root)
    if existing:
        _MOUNT_DIR = root
        _MOUNTED_SKILLS = existing
        _add_extra_skills_path(root)
        return root
    result = sync_all()
    path = result.get("path")
    if not path or not result.get("skill_count"):
        return None
    _MOUNT_DIR = Path(path)
    return _MOUNT_DIR


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


def cmd_cloud_sync(args) -> int:
    try:
        result = sync_all()
    except elevate_license.LicenseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return 0

    path = result.get("path")
    count = result.get("skill_count", 0)
    print(f"paid skills synced: {count}")
    if path:
        print(f"path: {path}")
    names = result.get("skill_names") or []
    for name in names:
        print(f"  {name}")
    removed = result.get("removed") or []
    if removed:
        print("removed stale skills:")
        for name in removed:
            print(f"  {name}")
    errors = result.get("errors") or []
    if errors:
        print("warnings:", file=sys.stderr)
        for item in errors:
            print(f"  {item}", file=sys.stderr)
        return 1 if count == 0 else 0
    return 0
