"""Parse the `steps:` declaration out of an Elevate skill's frontmatter.

The cron form on `/leads` (Phase 3 of the build plan) reads this to preview
which steps a skill-bound cron job will run, and at what tier each step
should resolve. Tier -> concrete model is resolved at execution time by
`tier_resolver.py` against the user's harness config — never hardcoded
in the skill file itself.

Surface used by:
- `web_server.py` cron form preview (`GET /api/skills/{slug}/steps`)
- future per-step model picker (v2)

The skill itself still launches one job-level prompt today — `scheduler.py`
runs a single `AIAgent` per cron job. Per-step execution is v2.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml


_log = logging.getLogger(__name__)

_VALID_TIERS = {"orchestrator", "draft", "utility", "send"}


def _split_frontmatter(text: str) -> dict[str, Any] | None:
    """Return the YAML frontmatter dict, or None if the file has none.

    SKILL.md files start with `---\\n...\\n---\\n` per the skill spec.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    raw = text[3:end].lstrip("\n")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        _log.warning("skill frontmatter parse failed: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def parse_steps_from_text(text: str, *, source: str = "<text>") -> list[dict[str, Any]]:
    """Same as `parse_steps` but takes raw SKILL.md content."""
    fm = _split_frontmatter(text)
    if not fm:
        return []

    raw_steps = fm.get("steps")
    if not isinstance(raw_steps, list):
        return []

    steps: list[dict[str, Any]] = []
    for entry in raw_steps:
        if not isinstance(entry, dict):
            continue
        step_id = str(entry.get("id", "")).strip()
        tier = str(entry.get("tier", "")).strip().lower()
        desc = str(entry.get("description", "")).strip()
        if not step_id or not tier:
            continue
        if tier not in _VALID_TIERS:
            _log.info(
                "skill %s declares step '%s' with unknown tier '%s' — passing through",
                source, step_id, tier,
            )
        steps.append({"id": step_id, "tier": tier, "description": desc})
    return steps


def parse_steps(skill_md_path: str | Path) -> list[dict[str, Any]]:
    """Return the validated `steps:` list from a SKILL.md, or `[]`.

    Each step dict has at minimum: `id`, `tier`, `description`. Unknown
    tiers are kept as-is (resolver decides), but logged so the cron form
    can warn the user that a tier won't map to one of their configured
    models.
    """
    path = Path(skill_md_path)
    if not path.is_file():
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("failed to read %s: %s", path, exc)
        return []

    return parse_steps_from_text(text, source=path.parent.name)
