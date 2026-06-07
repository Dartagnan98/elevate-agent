"""Agent Hub policy evaluation helpers.

This module is intentionally store-light: Agent Hub config remains the policy
source, ``surface_approvals`` remains the dashboard approval store, and
``agent_handoffs`` remains the visible work bus.
"""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


HIGH_RISK_CATEGORIES = {
    "external_send",
    "external_comms",
    "data_deletion",
    "delete",
    "deployment",
    "financial",
    "legal",
}

_SURFACE_APPROVAL_CATEGORY = {
    "deployment": "deployment",
    "financial": "financial",
    "cost": "financial",
    "external_send": "external-comms",
    "external_comms": "external-comms",
    "data_deletion": "data-deletion",
    "delete": "data-deletion",
    "access": "other",
}


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    cleaned: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            cleaned.append(ch)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    return "".join(cleaned).strip("-")


def _rule_key(value: Any) -> str:
    return _slug(value).replace("-", "_")


def _as_rules(value: Any) -> set[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = []
    return {_rule_key(item) for item in raw if str(item or "").strip()}


def _agent(agent_id: str) -> Mapping[str, Any]:
    try:
        from elevate_cli.agent_hub import get_agent_def

        agent = get_agent_def(agent_id)
        return agent if isinstance(agent, Mapping) else {}
    except Exception:
        return {}


def _surface_category(category: str) -> str:
    return _SURFACE_APPROVAL_CATEGORY.get(category, "other")


def _approval_title(agent_id: str, action: str, category: str) -> str:
    label = action.replace("_", " ").replace("-", " ").strip() or "agent action"
    return f"Approve {agent_id}: {label} ({category})"


def evaluate_agent_policy(
    agent_id: str,
    *,
    action: str,
    category: str = "other",
    conn: sqlite3.Connection | None = None,
    create_approval: bool = False,
    surface: str | None = None,
    description: str | None = None,
    actor: str = "system",
    resource: str | None = None,
) -> dict[str, Any]:
    """Return an allow/deny/approval-required decision for one agent action."""
    clean_agent = _slug(agent_id) or "executive-assistant"
    clean_action = _rule_key(action)
    clean_category = _rule_key(category or action or "other")
    agent = _agent(clean_agent)
    if not agent:
        return {
            "decision": "deny",
            "reason": "agent_not_found",
            "agentId": clean_agent,
            "action": action,
            "category": clean_category,
        }
    if agent.get("enabled") is False:
        return {
            "decision": "deny",
            "reason": "agent_suspended",
            "agentId": clean_agent,
            "action": action,
            "category": clean_category,
        }

    safety = agent.get("safety") if isinstance(agent.get("safety"), Mapping) else {}
    always = _as_rules(safety.get("always_ask"))
    never = _as_rules(safety.get("never_ask"))
    mode = _rule_key(safety.get("approval_mode") or "confirm_external_send")
    matches = {clean_action, clean_category}

    if matches & never:
        return {
            "decision": "allow",
            "reason": "never_ask_rule",
            "agentId": clean_agent,
            "action": action,
            "category": clean_category,
        }

    needs_approval = bool(matches & always)
    if mode in {"always_confirm", "always_ask", "manual"}:
        needs_approval = True
    if mode == "confirm_external_send" and clean_category in HIGH_RISK_CATEGORIES:
        needs_approval = True
    if clean_category in {"data_deletion", "deployment", "financial", "legal"}:
        needs_approval = True

    if not needs_approval:
        return {
            "decision": "allow",
            "reason": "policy_allows",
            "agentId": clean_agent,
            "action": action,
            "category": clean_category,
        }

    approval = None
    if create_approval and conn is not None:
        from elevate_cli.data import surface_tasks

        approval = surface_tasks.create_approval(
            conn,
            title=_approval_title(clean_agent, action, clean_category),
            category=_surface_category(clean_category),
            description=description
            or f"{clean_agent} requested {action} on {resource or surface or clean_category}.",
            surface=surface or clean_agent,
        )

    return {
        "decision": "approval_required",
        "reason": "safety_policy",
        "agentId": clean_agent,
        "action": action,
        "category": clean_category,
        "approval": approval,
        "actor": actor,
    }


def agent_lifecycle_status(
    agent_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return configured lifecycle limits plus observed handoff failure counts."""
    clean_agent = _slug(agent_id) or "executive-assistant"
    agent = _agent(clean_agent)
    lifecycle = agent.get("lifecycle") if isinstance(agent.get("lifecycle"), Mapping) else {}
    max_per_day = _to_int(lifecycle.get("max_crashes_per_day"))
    window_seconds = _to_int(lifecycle.get("crash_window_seconds"))
    window_max = _to_int(lifecycle.get("crash_window_max"))
    daily_failures = 0
    window_failures = 0
    if conn is not None:
        now = datetime.now(timezone.utc)
        daily_cutoff = (now - timedelta(days=1)).isoformat()
        daily_failures = _failed_handoffs_since(conn, clean_agent, daily_cutoff)
        if window_seconds:
            window_cutoff = (now - timedelta(seconds=window_seconds)).isoformat()
            window_failures = _failed_handoffs_since(conn, clean_agent, window_cutoff)
    suspended = False
    reason = ""
    if max_per_day and daily_failures >= max_per_day:
        suspended = True
        reason = "max_crashes_per_day"
    if window_max and window_failures >= window_max:
        suspended = True
        reason = "crash_window"
    return {
        "agentId": clean_agent,
        "startupDelay": _to_int(lifecycle.get("startup_delay")) or 0,
        "maxSessionSeconds": _to_int(lifecycle.get("max_session_seconds")),
        "maxCrashesPerDay": max_per_day,
        "crashWindowSeconds": window_seconds,
        "crashWindowMax": window_max,
        "dailyFailures": daily_failures,
        "windowFailures": window_failures,
        "suspended": suspended,
        "reason": reason,
    }


def record_agent_context_pressure(
    agent_id: str,
    *,
    session_id: str,
    current_tokens: int,
    context_limit: int,
    summary: str = "",
    conn: sqlite3.Connection | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Record native context-pressure observability and queue continuation if needed."""
    clean_agent = _slug(agent_id)
    if not clean_agent or not context_limit or context_limit <= 0:
        return {"recorded": False, "reason": "missing_agent_or_context"}
    percent = round((max(0, int(current_tokens)) / int(context_limit)) * 100, 2)
    agent = _agent(clean_agent)
    runtime = agent.get("runtime") if isinstance(agent.get("runtime"), Mapping) else {}
    routing = agent.get("routing") if isinstance(agent.get("routing"), Mapping) else {}
    warning_threshold = _to_int(runtime.get("context_warning_threshold"))
    handoff_threshold = _to_int(runtime.get("context_handoff_threshold"))
    event_kind = ""
    if warning_threshold and percent >= warning_threshold:
        event_kind = "context_warning"
    if handoff_threshold and percent >= handoff_threshold:
        event_kind = "context_handoff"
    if not event_kind:
        return {"recorded": False, "percent": percent, "reason": "below_threshold"}

    event = {
        "kind": event_kind,
        "agent": clean_agent,
        "sessionId": session_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "title": "Context pressure" if event_kind == "context_warning" else "Context handoff queued",
        "detail": summary or f"{percent}% of context window used",
        "status": "warning" if event_kind == "context_warning" else "handoff",
        "tokens": int(current_tokens),
        "contextLimit": int(context_limit),
        "percent": percent,
        "thresholds": {
            "warning": warning_threshold,
            "handoff": handoff_threshold,
        },
    }
    handoff = None
    if event_kind == "context_handoff" and conn is not None:
        target = _slug(routing.get("escalation_target"))
        if not target:
            raw_targets = routing.get("handoff_targets") or routing.get("handoffTargets") or []
            if isinstance(raw_targets, str):
                raw_targets = [raw_targets]
            if isinstance(raw_targets, (list, tuple, set)):
                for item in raw_targets:
                    target = _slug(item)
                    if target:
                        break
        target = target or clean_agent
        from_agent = clean_agent if target != clean_agent else "system"
        try:
            from elevate_cli.data.agent_handoffs import create_agent_handoff

            handoff = create_agent_handoff(
                conn,
                from_agent_id=from_agent,
                to_agent_id=target,
                title=f"Continue compressed context for {clean_agent}",
                task=(
                    "Context pressure crossed the configured handoff threshold. "
                    "Review the compressed session summary and continue routing the work "
                    "inside Elevate without restarting any daemon session.\n\n"
                    f"Session: {session_id}\n"
                    f"Source agent: {clean_agent}\n"
                    f"Continuation target: {target}\n"
                    f"Context: {current_tokens}/{context_limit} tokens ({percent}%)\n\n"
                    f"Summary:\n{summary or '(summary unavailable)'}"
                ),
                priority=str(routing.get("default_priority") or "normal"),
                source_run_id=session_id,
                payload={
                    "source": "context_pressure",
                    "event": event,
                    "sourceAgentId": clean_agent,
                    "continuationTarget": target,
                    "handoffPolicy": "native_continuation",
                },
                idempotency_key=f"context-pressure:{clean_agent}:{session_id}",
                create_cron_job=False,
                actor=actor,
            )
            if isinstance(handoff, Mapping):
                event["handoffId"] = handoff.get("id")
                event["targetAgent"] = handoff.get("toAgentId")
                event["fromAgent"] = handoff.get("fromAgentId")
        except Exception as exc:
            event["handoffError"] = str(exc)
    try:
        from elevate_cli.data.paths import data_root

        path = data_root() / "agent_context_pressure.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass
    return {"recorded": True, "event": event, "handoff": handoff}


def _to_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else 0 if parsed == 0 else None


def _failed_handoffs_since(conn: sqlite3.Connection, agent_id: str, cutoff: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM agent_handoffs
        WHERE to_agent_id = ?
          AND status = 'failed'
          AND COALESCE(completed_at, updated_at, created_at) >= ?
        """,
        (agent_id, cutoff),
    ).fetchone()
    return int(row["count"] if row and row["count"] is not None else 0)
