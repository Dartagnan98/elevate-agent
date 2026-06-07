#!/usr/bin/env python3
"""Import CortextOS skills into Elevate's bundled skill tree.

The import keeps Elevate as the runtime source of truth. CortextOS skill
instructions are copied as compatibility guides and get an Elevate-native
preamble so daemon, IPC, PM2, PTY, and file-inbox instructions are translated
to the existing Elevate surfaces.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path("/tmp/cortextos-github")
DEFAULT_DEST = REPO_ROOT / "cli" / "skills" / "cortextos"
MANIFEST_NAME = "IMPORT_MANIFEST.json"
README_NAME = "DESCRIPTION.md"
MANAGED_BY = "import_cortextos_skills.py"
COLLISION_RENAMES = {
    "theta-wave": "cortextos-theta-wave",
}
COMPAT_NOTE = (
    "> Elevate compatibility: This skill was imported from CortextOS. Use "
    "Elevate-native Agent Hub, Heartbeats, Cron, Comms, Tasks, Approvals, "
    "Activity, memory providers, and agent_handoffs instead of CortextOS "
    "daemon, IPC, PM2, PTY injection, or file inbox commands. When a "
    "CortextOS command is named below, translate it to the matching Elevate "
    "UI/API/store or create a waiting-human item.\n\n"
)


def source_roots(source: Path) -> list[Path]:
    """Return roots in precedence order for duplicate CortextOS skill names."""
    roots: list[Path] = [
        source / "community" / "skills",
        source / "skills",
    ]
    roots.extend(sorted((source / "community" / "agents").glob("*/.claude/skills")))
    roots.extend(sorted((source / "templates").glob("*/.claude/skills")))
    roots.extend(sorted((source / "templates").glob("*/plugins/*/skills")))
    return [root for root in roots if root.exists()]


def read_frontmatter_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    in_frontmatter = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return skill_md.parent.name


def existing_skill_names(root: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    if not root.exists():
        return names
    for skill_md in root.rglob("SKILL.md"):
        if any(part in {".git", "__pycache__", "node_modules"} for part in skill_md.parts):
            continue
        name = read_frontmatter_name(skill_md)
        names.setdefault(name, str(skill_md.relative_to(root)))
    return names


def iter_cortext_skill_dirs(source: Path) -> Iterable[Path]:
    for root in source_roots(source):
        yield from sorted(root.glob("*/SKILL.md"))


def collect_cortext_skills(source: Path) -> tuple[dict[str, Path], dict[str, list[str]]]:
    first_seen: dict[str, Path] = {}
    duplicate_sources: dict[str, list[str]] = {}
    for skill_md in iter_cortext_skill_dirs(source):
        name = read_frontmatter_name(skill_md)
        if name not in first_seen:
            first_seen[name] = skill_md.parent
            continue
        duplicate_sources.setdefault(name, []).append(str(skill_md.relative_to(source)))
    return first_seen, duplicate_sources


def split_frontmatter(text: str) -> tuple[list[str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return [], text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines[: idx + 1], "".join(lines[idx + 1 :])
    return [], text


def rewrite_skill_md(text: str, runtime_name: str, original_name: str, source_rel: str) -> str:
    frontmatter, body = split_frontmatter(text)
    rename_note = ""
    if runtime_name != original_name:
        rename_note = (
            f"> Imported as `{runtime_name}` to avoid colliding with Elevate's "
            f"native `{original_name}` skill. Calls to `{original_name}` keep "
            "using the native Elevate skill.\n\n"
        )

    if frontmatter:
        has_name = False
        has_category = False
        rewritten: list[str] = []
        for line in frontmatter:
            stripped = line.strip()
            if stripped.startswith("name:"):
                rewritten.append(f"name: {runtime_name}\n")
                has_name = True
            elif stripped.startswith("category:"):
                rewritten.append("category: cortextos\n")
                has_category = True
            elif stripped == "---" and line is frontmatter[-1]:
                if not has_name:
                    rewritten.append(f"name: {runtime_name}\n")
                if not has_category:
                    rewritten.append("category: cortextos\n")
                rewritten.append(line)
            else:
                rewritten.append(line)
        return "".join(rewritten) + "\n" + COMPAT_NOTE + rename_note + body.lstrip()

    return (
        "---\n"
        f"name: {runtime_name}\n"
        "category: cortextos\n"
        f"description: Imported CortextOS skill from {source_rel}.\n"
        "---\n\n"
        + COMPAT_NOTE
        + rename_note
        + body.lstrip()
    )


def assert_dest_managed(dest: Path) -> None:
    if not dest.exists():
        return
    manifest = dest / MANIFEST_NAME
    if not manifest.exists():
        raise SystemExit(f"{dest} exists without {MANIFEST_NAME}; refusing to overwrite it.")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{manifest} is not valid JSON; refusing to overwrite it.") from exc
    if data.get("managed_by") != MANAGED_BY:
        raise SystemExit(f"{dest} is not managed by {MANAGED_BY}; refusing to overwrite it.")


def git_head(source: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_oauth_rotation_wrapper(dest: Path) -> dict[str, str]:
    skill_dir = dest / "oauth-rotation"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: oauth-rotation
category: cortextos
description: "Rotate, refresh, or repair OAuth/provider credentials using Elevate settings and connector state without exposing secrets."
triggers: ["oauth", "token rotation", "refresh token", "expired token", "connector auth", "reauthorize", "api key rotation", "credential rotation"]
---

# OAuth Rotation

> Elevate compatibility: CortextOS references `oauth-rotation`, but the current upstream checkout does not ship a matching skill folder. This Elevate compatibility skill maps that intent to the native Settings, Env, OAuth providers, connector config, Approvals, Activity, and Comms surfaces.

Use this skill when an agent needs to rotate or repair OAuth credentials, API keys, refresh tokens, app passwords, webhook secrets, or provider-specific connector authorization.

## Rules

1. Never print, summarize, or return raw secrets.
2. Never write credentials into prompts, tasks, handoffs, Activity, Comms, or memory.
3. Prefer the Elevate Settings/OAuth provider flow or connector reauth flow over manual environment edits.
4. If credential rotation affects external delivery, billing, deployment, legal, or user-facing communication, create an approval or waiting-human item first.
5. After rotation, record only non-secret metadata: provider, account label, agent id, result, timestamp, and follow-up needed.

## Elevate Mapping

- CortextOS daemon credential reload -> Elevate app config reload or connector reauth.
- CortextOS `.env` token edits -> Elevate Env/Settings provider config.
- CortextOS bus activity log -> Elevate Activity event.
- CortextOS human approval -> Elevate Approvals or `waiting_human` handoff.
- CortextOS Telegram token repair -> Agent Hub channel config with fallback to orchestrator/executive-assistant bot when no per-agent token exists.

## Output

Return a short status with:

- Provider or connector name.
- Whether the credential is healthy, expired, missing, or waiting on human action.
- Non-secret next step.
- Approval or handoff id when one was created.
""",
        encoding="utf-8",
    )
    return {
        "name": "oauth-rotation",
        "runtime_name": "oauth-rotation",
        "source": "<compatibility-wrapper>",
        "destination": "oauth-rotation",
    }


def write_description(dest: Path) -> None:
    (dest / README_NAME).write_text(
        """# CortextOS Agent Ops

Imported CortextOS skills adapted for Elevate's native Agent Hub, Heartbeats,
Cron, Comms, Tasks, Approvals, Activity, memory, and handoff systems.

These skills are compatibility guides. They must not start CortextOS daemon,
IPC, PM2, PTY injection, or file-inbox workflows inside Elevate.
""",
        encoding="utf-8",
    )


def import_skills(source: Path, dest: Path) -> dict:
    if not source.exists():
        raise SystemExit(f"CortextOS source does not exist: {source}")

    first_seen, duplicate_sources = collect_cortext_skills(source)
    existing = {
        name: rel
        for name, rel in existing_skill_names(REPO_ROOT / "cli" / "skills").items()
        if not rel.startswith("cortextos/")
    }

    assert_dest_managed(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    write_description(dest)

    imported: list[dict[str, str | bool]] = []
    collisions: list[dict[str, str]] = []

    for original_name, source_dir in sorted(first_seen.items(), key=lambda item: item[0].lower()):
        runtime_name = COLLISION_RENAMES.get(original_name, original_name)
        if original_name in existing and original_name not in COLLISION_RENAMES:
            raise SystemExit(
                f"Unexpected collision for {original_name}: {existing[original_name]}. "
                "Add it to COLLISION_RENAMES before importing."
            )

        source_rel = str(source_dir.relative_to(source))
        if runtime_name != original_name:
            collisions.append({
                "name": original_name,
                "runtime_name": runtime_name,
                "existing": existing.get(original_name, ""),
                "source": source_rel,
            })

        skill_dest = dest / runtime_name
        shutil.copytree(source_dir, skill_dest)
        skill_md = skill_dest / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        skill_md.write_text(
            rewrite_skill_md(text, runtime_name, original_name, source_rel),
            encoding="utf-8",
        )
        imported.append({
            "name": original_name,
            "runtime_name": runtime_name,
            "source": source_rel,
            "destination": runtime_name,
            "exact_name": runtime_name == original_name,
        })

    oauth_wrapper = write_oauth_rotation_wrapper(dest)

    manifest = {
        "managed_by": MANAGED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_git_head": git_head(source),
        "imported_count": len(imported) + 1,
        "imported": imported + [oauth_wrapper],
        "collisions": collisions,
        "duplicate_sources": duplicate_sources,
        "compatibility_wrappers": [oauth_wrapper],
    }
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()

    manifest = import_skills(args.source.resolve(), args.dest.resolve())
    print(
        f"Imported {manifest['imported_count']} CortextOS skills into "
        f"{args.dest.resolve()}"
    )
    if manifest["collisions"]:
        for item in manifest["collisions"]:
            print(
                f"Renamed {item['name']} -> {item['runtime_name']} "
                f"because Elevate already has {item['existing']}"
            )


if __name__ == "__main__":
    main()
