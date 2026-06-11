#!/usr/bin/env python3
"""manage_agent — first-class fleet reconfiguration for the orchestrator.

Lets the Executive Assistant reconfigure the Agent Hub WITHOUT hand-editing
config.yaml or (dangerously) files inside the signed app bundle: add/remove
toolsets + skills on any agent (including itself), change role/description/
prompt/enabled, create new agents, and retire them. Everything writes to the
per-account agent store via elevate_cli.agent_hub (the same path the dashboard
UI uses), so changes persist and apply to new/restarted agent sessions.

Never edits the app bundle. Changes take effect for new agent runs; a live
agent picks them up on its next session/restart.
"""

import json
from typing import Any, List, Optional


def check_manage_agent_requirements() -> bool:
    return True


def _slugify(v: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", str(v or "").strip().lower()).strip("-")


def _agent_summary(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "role": a.get("role"),
        "enabled": a.get("enabled", True),
        "toolsets": list(a.get("toolsets") or []),
        "skills": list(a.get("skills") or []),
    }


def _valid_toolsets() -> set:
    """All toolset names an agent can be given: the static TOOLSETS catalog
    UNION the registry's registered toolsets (e.g. 'composio', MCP toolsets),
    minus internal/excluded ones."""
    names: set = set()
    try:
        from toolsets import TOOLSETS

        names |= set(TOOLSETS.keys())
    except Exception:
        pass
    try:
        from tools.registry import registry

        names |= set(registry.get_registered_toolset_names())
    except Exception:
        pass
    return {n for n in names if n and not n.startswith("hermes-") and n not in {"debugging", "safe", "moa", "rl"}}


def _all_agent_ids() -> List[str]:
    from elevate_cli.agent_hub import _load_agent_defs
    from elevate_cli.config import load_config

    return [
        _slugify(str(a.get("id") or ""))
        for a in _load_agent_defs(load_config())
        if isinstance(a, dict) and a.get("id")
    ]


def _resolve_targets(agent: Optional[str]) -> List[str]:
    """'all'/'*' → every installed agent; else the single slugged id."""
    a = (agent or "").strip().lower()
    if a in {"all", "*", "every", "everyone"}:
        return _all_agent_ids()
    slug = _slugify(a)
    return [slug] if slug else []


def manage_agent(
    action: Optional[str] = None,
    agent: Optional[str] = None,
    toolset: Optional[str] = None,
    skill: Optional[str] = None,
    role: Optional[str] = None,
    description: Optional[str] = None,
    prompt: Optional[str] = None,
    name: Optional[str] = None,
    enabled: Optional[bool] = None,
    **_extra: Any,
) -> str:
    act = (action or "").strip().lower().replace("-", "_")
    try:
        from elevate_cli.agent_hub import (
            get_agent_def,
            update_agent_config,
            create_agent_config,
            delete_agent_config,
        )
        from toolsets import TOOLSETS
    except Exception as exc:
        return json.dumps({"error": f"agent_hub unavailable: {exc}"})

    # ── Inspect ────────────────────────────────────────────────────────────
    if act in {"list", "agents", ""}:
        try:
            from elevate_cli.agent_hub import _load_agent_defs
            from elevate_cli.config import load_config

            agents = [
                _agent_summary(a)
                for a in _load_agent_defs(load_config())
                if isinstance(a, dict)
            ]
            return json.dumps({"action": "list", "agents": agents}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": f"list failed: {exc}"})

    if act in {"available", "available_toolsets", "catalog"}:
        names = sorted(_valid_toolsets())
        return json.dumps(
            {
                "action": "available",
                "toolsets": names,
                "note": "Skills: use the skills tool (list) to see installable skill names.",
            },
            ensure_ascii=False,
        )

    if act in {"get", "show"}:
        targets = _resolve_targets(agent)
        if not targets:
            return json.dumps({"error": "agent id required"})
        out = []
        for tid in targets:
            d = get_agent_def(tid)
            if d:
                out.append(_agent_summary(d))
        return json.dumps({"action": "get", "agents": out}, ensure_ascii=False)

    # ── Mutate: toolsets / skills (add/remove, supports agent='all') ────────
    list_field = None
    item = None
    add = None
    if act in {"add_toolset", "enable_toolset", "give_toolset"}:
        list_field, item, add = "toolsets", (toolset or "").strip(), True
    elif act in {"remove_toolset", "disable_toolset"}:
        list_field, item, add = "toolsets", (toolset or "").strip(), False
    elif act in {"add_skill", "give_skill"}:
        list_field, item, add = "skills", (skill or "").strip(), True
    elif act in {"remove_skill"}:
        list_field, item, add = "skills", (skill or "").strip(), False

    if list_field is not None:
        if not item:
            return json.dumps({"error": f"{list_field[:-1]} name required"})
        if list_field == "toolsets" and add and item not in _valid_toolsets():
            return json.dumps(
                {"error": f"unknown toolset '{item}'. Use action='available' to list valid toolsets."}
            )
        targets = _resolve_targets(agent)
        if not targets:
            return json.dumps({"error": "agent id required (or 'all')"})
        results = []
        for tid in targets:
            try:
                d = get_agent_def(tid)
                if not d:
                    results.append({"agent": tid, "ok": False, "error": "not found"})
                    continue
                cur = list(d.get(list_field) or [])
                if add:
                    if item in cur:
                        results.append({"agent": tid, "ok": True, "unchanged": True})
                        continue
                    cur.append(item)
                else:
                    if item not in cur:
                        results.append({"agent": tid, "ok": True, "unchanged": True})
                        continue
                    cur = [x for x in cur if x != item]
                update_agent_config(tid, {list_field: cur})
                results.append({"agent": tid, "ok": True, list_field: cur})
            except Exception as exc:
                results.append({"agent": tid, "ok": False, "error": str(exc)})
        return json.dumps(
            {
                "action": act,
                "item": item,
                "results": results,
                "note": "Applied to the persisted agent store. New/restarted agent sessions pick it up; a live session updates on its next restart.",
            },
            ensure_ascii=False,
        )

    # ── Mutate: general fields ──────────────────────────────────────────────
    if act in {"set", "update", "configure"}:
        targets = _resolve_targets(agent)
        if not targets:
            return json.dumps({"error": "agent id required"})
        patch: dict = {}
        if role is not None:
            patch["role"] = role
        if description is not None:
            patch["description"] = description
        if prompt is not None:
            patch["prompt"] = prompt
        if name is not None:
            patch["name"] = name
        if enabled is not None:
            patch["enabled"] = bool(enabled)
        if not patch:
            return json.dumps({"error": "nothing to set (role/description/prompt/name/enabled)"})
        results = []
        for tid in targets:
            try:
                update_agent_config(tid, patch)
                results.append({"agent": tid, "ok": True, "set": list(patch.keys())})
            except Exception as exc:
                results.append({"agent": tid, "ok": False, "error": str(exc)})
        return json.dumps({"action": "set", "results": results}, ensure_ascii=False)

    # ── Create / retire ─────────────────────────────────────────────────────
    if act in {"create", "create_agent", "add_agent"}:
        if not (name or agent):
            return json.dumps({"error": "name (and/or id) required to create an agent"})
        payload: dict = {
            "id": _slugify(agent or name),
            "name": name or agent,
            "role": role or "support",
            "description": description or "",
            "prompt": prompt or "",
        }
        try:
            created = create_agent_config(payload)
            return json.dumps({"action": "create", "agent": _agent_summary(created)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": f"create failed: {exc}"})

    if act in {"retire", "delete", "remove_agent", "delete_agent"}:
        targets = _resolve_targets(agent)
        if not targets:
            return json.dumps({"error": "agent id required"})
        results = []
        for tid in targets:
            try:
                delete_agent_config(tid)
                results.append({"agent": tid, "ok": True})
            except Exception as exc:
                results.append({"agent": tid, "ok": False, "error": str(exc)})
        return json.dumps({"action": "retire", "results": results}, ensure_ascii=False)

    return json.dumps(
        {
            "error": f"unknown action '{action}'",
            "valid_actions": [
                "list", "available", "get",
                "add_toolset", "remove_toolset", "add_skill", "remove_skill",
                "set", "create", "retire",
            ],
        }
    )


MANAGE_AGENT_SCHEMA = {
    "name": "manage_agent",
    "description": (
        "Reconfigure the Agent Hub fleet at runtime — add/remove TOOLSETS and "
        "SKILLS on any agent (including yourself), change an agent's role/"
        "description/prompt, enable/disable, create new agents, or retire them. "
        "Use this INSTEAD of editing config.yaml or any files (NEVER edit files "
        "inside the app bundle — that breaks the app). Changes persist to the "
        "agent store and apply to new/restarted agent sessions.\n\n"
        "Common: action='available' to see valid toolset names; action='list' to "
        "see every agent's current toolsets/skills; action='add_toolset' with "
        "agent='all' to give every agent a toolset (e.g. toolset='composio'); "
        "action='add_skill' to grant a skill. Use agent='all' to apply fleet-wide."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list", "available", "get",
                    "add_toolset", "remove_toolset", "add_skill", "remove_skill",
                    "set", "create", "retire",
                ],
                "description": "What to do.",
            },
            "agent": {
                "type": "string",
                "description": "Target agent id (e.g. 'admin', 'executive-assistant'), or 'all' for every agent.",
            },
            "toolset": {"type": "string", "description": "Toolset name for add_toolset/remove_toolset."},
            "skill": {"type": "string", "description": "Skill name for add_skill/remove_skill."},
            "role": {"type": "string", "description": "For set/create."},
            "description": {"type": "string", "description": "For set/create."},
            "prompt": {"type": "string", "description": "For set/create."},
            "name": {"type": "string", "description": "For set/create."},
            "enabled": {"type": "boolean", "description": "For set: enable/disable the agent."},
        },
        "required": ["action"],
    },
}


from tools.registry import registry

registry.register(
    name="manage_agent",
    toolset="agent_management",
    schema=MANAGE_AGENT_SCHEMA,
    handler=lambda args, **kw: manage_agent(
        action=args.get("action"),
        agent=args.get("agent"),
        toolset=args.get("toolset"),
        skill=args.get("skill"),
        role=args.get("role"),
        description=args.get("description"),
        prompt=args.get("prompt"),
        name=args.get("name"),
        enabled=args.get("enabled"),
    ),
    check_fn=check_manage_agent_requirements,
    emoji="🛠️",
)
