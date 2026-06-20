"""Skills and toolsets routes."""

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from elevate_cli.config import load_config


class SkillToggle(BaseModel):
    name: str
    enabled: bool


def _resolve_skill_dir(name: str):
    """Locate the on-disk directory for a skill."""
    from pathlib import Path
    from tools.skills_tool import SKILLS_DIR, _EXCLUDED_SKILL_DIRS
    from agent.skill_utils import get_external_skills_dirs, iter_skill_index_files

    candidates = []
    if SKILLS_DIR.exists():
        candidates.append(SKILLS_DIR)
    candidates.extend(get_external_skills_dirs())

    for search_dir in candidates:
        direct = search_dir / name
        if direct.is_dir() and (direct / "SKILL.md").exists():
            return direct

    for search_dir in candidates:
        for skill_md in iter_skill_index_files(search_dir, "SKILL.md"):
            if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
                continue
            if skill_md.parent.name == name:
                return skill_md.parent
    return None


def _walk_skill_tree(skill_dir, max_depth: int = 4):
    """Return a nested list of file tree entries for a skill dir."""
    from tools.skills_tool import _EXCLUDED_SKILL_DIRS

    def walk(dir_path, rel_prefix: str, depth: int):
        if depth > max_depth:
            return []
        entries = []
        try:
            children = list(dir_path.iterdir())
        except (PermissionError, OSError):
            return []
        files = []
        folders = []
        for child in children:
            if child.name in _EXCLUDED_SKILL_DIRS or child.name.startswith("."):
                continue
            rel = f"{rel_prefix}{child.name}" if rel_prefix else child.name
            if child.is_dir():
                folders.append((child.name, rel, child))
            else:
                files.append((child.name, rel))

        skill_md_entry = None
        other_files = []
        for fname, rel in sorted(files, key=lambda x: x[0].lower()):
            entry = {"name": fname, "type": "file", "path": rel}
            if fname == "SKILL.md":
                skill_md_entry = entry
            else:
                other_files.append(entry)
        if skill_md_entry:
            entries.append(skill_md_entry)

        for fname, rel, child_dir in sorted(folders, key=lambda x: x[0].lower()):
            entries.append({
                "name": fname,
                "type": "dir",
                "path": rel,
                "children": walk(child_dir, f"{rel}/", depth + 1),
            })

        entries.extend(other_files)
        return entries

    return walk(skill_dir, "", 0)


def create_skills_router() -> APIRouter:
    """Build skills and toolsets routes."""
    router = APIRouter()

    @router.get("/api/skills")
    async def get_skills():
        from tools.skills_tool import _find_all_skills
        from elevate_cli.skills_config import get_disabled_skills

        config = load_config()
        disabled = get_disabled_skills(config)
        skills = _find_all_skills(skip_disabled=True)
        for s in skills:
            s["enabled"] = s["name"] not in disabled
        return skills

    @router.put("/api/skills/toggle")
    async def toggle_skill(body: SkillToggle):
        from elevate_cli.skills_config import get_disabled_skills, save_disabled_skills

        config = load_config()
        disabled = get_disabled_skills(config)
        if body.enabled:
            disabled.discard(body.name)
        else:
            disabled.add(body.name)
        save_disabled_skills(config, disabled)
        return {"ok": True, "name": body.name, "enabled": body.enabled}

    @router.get("/api/skills/{name}/steps")
    async def get_skill_steps(name: str):
        from tools.skills_tool import skill_view
        from elevate_cli.skill_steps import parse_steps_from_text

        payload = json.loads(skill_view(name))
        if not payload.get("success"):
            return {"name": name, "steps": [], "error": payload.get("error", "skill not found")}

        content = str(payload.get("content") or "")
        steps = parse_steps_from_text(content, source=name)
        return {"name": name, "steps": steps}

    @router.get("/api/skills/{name}/tree")
    async def get_skill_tree(name: str):
        skill_dir = _resolve_skill_dir(name)
        if skill_dir is None:
            return {"name": name, "tree": [], "error": "skill not found"}
        return {
            "name": name,
            "root": skill_dir.name,
            "tree": _walk_skill_tree(skill_dir),
        }

    @router.get("/api/skills/{name}/file")
    async def get_skill_file(name: str, path: str = ""):
        from tools.path_security import has_traversal_component, validate_within_dir

        skill_dir = _resolve_skill_dir(name)
        if skill_dir is None:
            return {"name": name, "path": path, "error": "skill not found"}

        rel = path.strip().lstrip("/") or "SKILL.md"
        if has_traversal_component(rel):
            return {"name": name, "path": rel, "error": "invalid path"}

        target = skill_dir / rel
        err = validate_within_dir(target, skill_dir)
        if err:
            return {"name": name, "path": rel, "error": err}
        if not target.exists() or not target.is_file():
            return {"name": name, "path": rel, "error": "file not found"}

        try:
            size = target.stat().st_size
        except OSError:
            size = 0

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "name": name,
                "path": rel,
                "binary": True,
                "size": size,
            }

        return {
            "name": name,
            "path": rel,
            "size": size,
            "content": content,
        }

    @router.get("/api/tools/toolsets")
    async def get_toolsets():
        from elevate_cli.tools_config import (
            _get_effective_configurable_toolsets,
            _get_platform_tools,
            _toolset_has_keys,
        )
        from toolsets import resolve_toolset

        config = load_config()
        enabled_toolsets = _get_platform_tools(
            config,
            "cli",
            include_default_mcp_servers=False,
        )
        result = []
        for name, label, desc in _get_effective_configurable_toolsets():
            try:
                tools = sorted(set(resolve_toolset(name)))
            except Exception:
                tools = []
            is_enabled = name in enabled_toolsets
            result.append({
                "name": name,
                "label": label,
                "description": desc,
                "enabled": is_enabled,
                "available": is_enabled,
                "configured": _toolset_has_keys(name, config),
                "tools": tools,
            })
        return result

    return router
