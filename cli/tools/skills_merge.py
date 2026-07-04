#!/usr/bin/env python3
"""
Skills Merge -- agent-driven resolution of queued skill update conflicts.

skills_sync.py handles everything mechanical: unedited skills update in
place, and user-modified skills get a per-file three-way merge against the
recorded base snapshot. What lands here is only what a file copy can never
decide — files where BOTH the user and the bundled skill changed (or
user-modified skills from installs that predate base snapshots, where the
true base is unknowable). For those, the box's own agent reads every
version and produces a merged file that keeps the user's customizations
while integrating the upstream improvement.

Queue layout (written by skills_sync._queue_agent_merge):
    ~/.elevate/skills/.pending-merges/<key>.json   — merge job metadata
    ~/.elevate/skills/.pending-merges/<key>.new/   — the new bundled version

Entry point: run_pending_merges() — used by `elevate skills merge-updates`.
Safety: the user's copy is snapshotted to <dest>.bak-premerge before any
write; a skill is only finalized when EVERY merged file verifies; failures
leave the queue entry in place and touch nothing.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from tools.skills_sync import (
    pending_merges_root,
    _base_dir_for,
    _read_file_map,
    _read_manifest,
    _read_skill_name,
    _write_base_snapshot,
    _write_manifest,
)

logger = logging.getLogger(__name__)

# One agent call per file; generous because skill bodies can be long but a
# hung provider must not wedge the whole drain.
AGENT_TIMEOUT_SECONDS = 300

_MERGE_RULES = """\
You are merging an update to the Elevate skill "{skill}" — file: {rel}

Rules — follow every one:
1. PRESERVE every customization from MY CURRENT VERSION: added sections,
   reworded instructions, extra examples, local paths, names, credentials
   references — anything the user added or changed stays.
2. INTEGRATE the improvements from the NEW UPSTREAM VERSION: new sections,
   corrected instructions, new frontmatter fields, rewritten descriptions.
3. When the same sentence/section differs and you cannot keep both, prefer
   MY CURRENT VERSION for user-specific content and the NEW UPSTREAM VERSION
   for product instructions (tool names, API shapes, safety rules).
4. If the file has YAML frontmatter, it must remain valid YAML and the
   `name:` field must stay exactly "{skill}".
5. Output ONLY the merged file content. No commentary, no code fences, no
   explanations before or after.
"""


def _agent_argv(prompt: str) -> list:
    """One-shot agent argv. `chat -q` prints ONLY the reply on stdout (the
    session trailer goes to stderr) — same invocation the behavioral eval
    uses. Kept as a function so tests can validate the shape against the
    real CLI parser (a bogus flag here once failed every merge at runtime).
    """
    return [
        sys.executable, "-m", "elevate_cli.main", "chat",
        "-q", prompt, "--max-turns", "2", "-Q", "--source", "tool",
    ]


def _default_agent_merge(prompt: str) -> Optional[str]:
    """Run the box's own agent one-shot and return its raw text output."""
    try:
        result = subprocess.run(
            _agent_argv(prompt),
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("agent merge call failed: %s", e)
        return None
    if result.returncode != 0:
        logger.warning("agent merge exited %s: %s", result.returncode, result.stderr[:300])
        return None
    return result.stdout


def _strip_fence(text: str) -> str:
    """Unwrap output the model wrapped in a single markdown code fence."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]) + "\n"
    return text if text.endswith("\n") else text + "\n"


def _verify_merged(rel: str, content: str, expected_name: str, tmp_dir: Path) -> bool:
    """Cheap sanity gate: non-trivial output; SKILL.md keeps its identity."""
    if len(content.strip()) < 20:
        return False
    if Path(rel).name == "SKILL.md":
        probe = tmp_dir / "SKILL.md.probe"
        try:
            probe.write_text(content, encoding="utf-8")
            return _read_skill_name(probe, fallback="") == expected_name
        finally:
            probe.unlink(missing_ok=True)
    return True


def list_pending() -> List[dict]:
    """All queued merge jobs, oldest first."""
    if not pending_merges_root().is_dir():
        return []
    entries = []
    for jf in sorted(pending_merges_root().glob("*.json")):
        try:
            entry = json.loads(jf.read_text(encoding="utf-8"))
            entry["_json_path"] = str(jf)
            entries.append(entry)
        except (ValueError, OSError):
            logger.debug("unreadable pending-merge entry: %s", jf)
    entries.sort(key=lambda e: e.get("queued_at", 0))
    return entries


def _files_needing_agent(entry: dict, dest: Path, new_copy: Path) -> Dict[str, str]:
    """rel -> reason. Conflicted files from the queue entry; for bootstrap
    entries (no recorded base) every file where user and upstream disagree."""
    user = _read_file_map(dest)
    new = _read_file_map(new_copy)
    if not entry.get("bootstrap"):
        return {rel: "conflict" for rel in entry.get("conflicts", []) if rel in user or rel in new}
    return {
        rel: "bootstrap"
        for rel in sorted(set(user) & set(new))
        if user[rel] != new[rel]
    }


def run_pending_merges(
    skill: Optional[str] = None,
    quiet: bool = False,
    agent_merge: Callable[[str], Optional[str]] = _default_agent_merge,
) -> dict:
    """Drain the pending-merge queue via the agent.

    Returns dict: merged (list), failed (list of {skill, reason}), pending_before (int).
    """
    entries = list_pending()
    if skill:
        entries = [e for e in entries if e.get("skill") == skill]
    merged: List[str] = []
    failed: List[dict] = []

    for entry in entries:
        name = entry.get("skill", "?")
        dest = Path(entry.get("dest", ""))
        new_copy = Path(entry.get("new_copy", ""))
        json_path = Path(entry["_json_path"])

        if not dest.is_dir() or not new_copy.is_dir():
            # User deleted the skill (respected) or queue is torn — drop entry.
            json_path.unlink(missing_ok=True)
            shutil.rmtree(new_copy, ignore_errors=True)
            continue

        todo = _files_needing_agent(entry, dest, new_copy)
        results: Dict[str, str] = {}
        ok = True
        for rel in todo:
            user_text = (dest / rel).read_text(encoding="utf-8", errors="replace") if (dest / rel).exists() else ""
            new_text = (new_copy / rel).read_text(encoding="utf-8", errors="replace") if (new_copy / rel).exists() else ""
            base_dir = entry.get("base")
            base_text = ""
            if base_dir and (Path(base_dir) / rel).exists():
                base_text = (Path(base_dir) / rel).read_text(encoding="utf-8", errors="replace")

            prompt = _MERGE_RULES.format(skill=name, rel=rel)
            if base_text:
                prompt += f"\n--- ORIGINAL BASE VERSION (what both sides started from) ---\n{base_text}\n"
            prompt += f"\n--- MY CURRENT VERSION (user-customized — preserve these changes) ---\n{user_text}\n"
            prompt += f"\n--- NEW UPSTREAM VERSION (improvements to integrate) ---\n{new_text}\n"

            out = agent_merge(prompt)
            if out is None:
                ok = False
                failed.append({"skill": name, "reason": f"agent call failed on {rel}"})
                break
            content = _strip_fence(out)
            if not _verify_merged(rel, content, name, pending_merges_root()):
                ok = False
                failed.append({"skill": name, "reason": f"merged {rel} failed verification"})
                break
            results[rel] = content

        if not ok:
            if not quiet:
                print(f"  ! {name}: left queued ({failed[-1]['reason']})")
            continue

        # All files verified — apply atomically-ish with a premerge backup.
        backup = dest.with_suffix(".bak-premerge")
        try:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(dest, backup)
            # Mechanical part: files only upstream has are new — copy them in.
            user_files = _read_file_map(dest)
            for rel, content in _read_file_map(new_copy).items():
                if rel not in user_files and rel not in results:
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            for rel, content in results.items():
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            # Converge tracking: base := the version we just merged toward.
            _write_base_snapshot(name, new_copy)
            manifest = _read_manifest()
            if entry.get("bundled_hash"):
                manifest[name] = entry["bundled_hash"]
                _write_manifest(manifest)
            json_path.unlink(missing_ok=True)
            shutil.rmtree(new_copy, ignore_errors=True)
            merged.append(name)
            if not quiet:
                print(f"  ✓ {name}: merged {len(results)} file(s), customizations kept (backup: {backup.name})")
        except (OSError, IOError) as e:
            # Restore the untouched copy; keep the queue entry for a retry.
            if backup.exists():
                shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(backup), str(dest))
            failed.append({"skill": name, "reason": f"write failed: {e}"})
            if not quiet:
                print(f"  ! {name}: write failed, restored original ({e})")

    return {"merged": merged, "failed": failed, "pending_before": len(entries)}
