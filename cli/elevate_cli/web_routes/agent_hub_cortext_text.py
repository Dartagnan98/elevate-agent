"""Text and goal parsing helpers for Cortext agent-pack conversion."""

import json
import re
from typing import Any, Optional


def first_markdown_paragraph(text: str) -> str:
    for part in re.split(r"\n{2,}", text or ""):
        clean = re.sub(r"^#+\s*", "", part, flags=re.MULTILINE).strip()
        if clean:
            return clean
    return ""


def markdown_section(text: str, heading: str) -> str:
    lines = str(text or "").splitlines()
    target = heading.strip().lower()
    start = -1
    for index, line in enumerate(lines):
        if re.sub(r"^#+\s*", "", line).strip().lower() == target:
            start = index
            break
    if start < 0:
        return ""
    body: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^#{1,6}\s+\S", line):
            break
        body.append(line)
    return "\n".join(body).strip()


def markdown_bullets(text: str) -> list[str]:
    out: list[str] = []
    for line in str(text or "").splitlines():
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if not match:
            continue
        item = re.sub(r"^\[[ xX]\]\s*", "", match.group(1).strip())
        if item:
            out.append(item)
    return out


def merge_unique(*groups: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        values = group if isinstance(group, list) else re.split(r"[,\n]", group) if isinstance(group, str) else []
        for value in values:
            clean = str(value or "").strip()
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            out.append(clean)
    return out


def extract_skill_refs(*texts: str) -> list[str]:
    refs: list[str] = []
    for text in texts:
        refs.extend(re.findall(r"(?:^|[/\"\s])skills/([a-z0-9._-]+)/SKILL\.md", text or "", flags=re.I))
        refs.extend(re.findall(r"\.claude/skills/([a-z0-9._-]+)/SKILL\.md", text or "", flags=re.I))
    return merge_unique(refs)


def extract_toolsets(tools_text: str, config: dict[str, Any]) -> list[str]:
    configured = merge_unique(config.get("toolsets"), config.get("tool_sets"), config.get("enabled_toolsets"))
    inferred: list[str] = []
    lower = str(tools_text or "").lower()
    if re.search(r"\b(agent_handoff|handoff|send-message|check-inbox)\b", lower):
        inferred.append("agent_handoff")
    if re.search(r"\b(create-task|update-task|complete-task|list-tasks|create-approval|list-approvals|post-activity|log-event|heartbeat|update-heartbeat|read-all-heartbeats|create-experiment|run-experiment|evaluate-experiment|list-experiments|browse-catalog|list-skills)\b", lower):
        inferred.append("agent_bus")
    if re.search(r"\b(kb-query|memory|knowledge-base|knowledge base)\b", lower):
        inferred.append("memory")
    return merge_unique(configured, inferred, ["agent_bus", "agent_handoff", "memory"])


def goals_from_json(raw: str) -> Optional[dict[str, Any]]:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    obj = {"goals": parsed} if isinstance(parsed, list) else parsed if isinstance(parsed, dict) else {}
    raw_goals = obj.get("goals") if isinstance(obj.get("goals"), list) else obj.get("items") if isinstance(obj.get("items"), list) else []
    goals: list[dict[str, Any]] = []
    for index, item in enumerate(raw_goals):
        if isinstance(item, str):
            title = item.strip()
            progress = 0
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or item.get("goal") or item.get("text") or "").strip()
            try:
                progress = max(0, min(100, int(item.get("progress") or item.get("percent") or item.get("completion") or 0)))
            except Exception:
                progress = 0
        else:
            continue
        if title:
            goals.append({"title": title, "progress": progress, "order": index})
    daily_focus = str(obj.get("daily_focus") or obj.get("dailyFocus") or obj.get("focus") or "").strip()
    bottleneck = str(obj.get("bottleneck") or obj.get("blocker") or "").strip()
    if not goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": goals}


def goals_from_markdown(raw: str) -> Optional[dict[str, Any]]:
    if not raw.strip():
        return None
    goals: list[dict[str, Any]] = []
    daily_focus = ""
    bottleneck = ""
    for line in raw.splitlines():
        clean = line.strip()
        if not clean:
            continue
        daily = re.match(r"^daily[_\s-]*focus\s*:\s*(.+)$", clean, flags=re.I)
        if daily:
            daily_focus = daily.group(1).strip()
            continue
        blocker = re.match(r"^bottleneck\s*:\s*(.+)$", clean, flags=re.I)
        if blocker:
            bottleneck = blocker.group(1).strip()
            continue
        match = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", clean)
        if not match:
            continue
        title = re.sub(r"^\[[ xX]\]\s*", "", match.group(1).strip())
        progress = 0
        progress_match = re.search(r"(?:^|\s)(\d{1,3})%\s*$", title)
        if progress_match:
            progress = max(0, min(100, int(progress_match.group(1))))
            title = title[:progress_match.start()].strip()
        if title and not re.match(r"^(daily[_\s-]*focus|bottleneck)", title, flags=re.I):
            goals.append({"title": title, "progress": progress, "order": len(goals)})
    if not goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": goals}


def merge_goal_seed(*seeds: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    merged_goals: list[dict[str, Any]] = []
    seen: set[str] = set()
    daily_focus = ""
    bottleneck = ""
    for seed in seeds:
        if not seed:
            continue
        daily_focus = daily_focus or str(seed.get("daily_focus") or "")
        bottleneck = bottleneck or str(seed.get("bottleneck") or "")
        for goal in seed.get("goals") or []:
            title = str(goal.get("title") or "").strip() if isinstance(goal, dict) else ""
            key = title.lower()
            if not title or key in seen:
                continue
            seen.add(key)
            merged_goals.append({"title": title, "progress": int(goal.get("progress") or 0), "order": len(merged_goals)})
    if not merged_goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": merged_goals}
