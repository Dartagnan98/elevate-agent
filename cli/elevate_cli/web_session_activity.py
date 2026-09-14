from __future__ import annotations

from typing import Any


def gateway_session_run_states() -> tuple[set[str], set[str]]:
    """(running_keys, known_keys) for sessions the in-process gateway hosts."""
    running: set[str] = set()
    known: set[str] = set()
    try:
        from tui_gateway import server as _gw

        for sess in list(getattr(_gw, "_sessions", {}).values()):
            if not isinstance(sess, dict):
                continue
            keys = [
                str(k)
                for k in (sess.get("session_key"), sess.get("session_id"))
                if k
            ]
            known.update(keys)
            if sess.get("running"):
                running.update(keys)
    except Exception:
        pass
    return running, known


def live_subagent_child_session_ids() -> set[str]:
    """Child session ids currently present in the live delegation registry."""
    ids: set[str] = set()
    try:
        from tools.delegate_tool import list_active_subagents

        for record in list_active_subagents():
            if not isinstance(record, dict):
                continue
            child_session_id = str(record.get("child_session_id") or "").strip()
            if child_session_id:
                ids.add(child_session_id)
    except Exception:
        pass
    return ids


def mark_session_activity(
    sessions: list[dict[str, Any]],
    now: float,
    *,
    session_active_window_sec: int,
    gateway_session_run_states_func=gateway_session_run_states,
) -> None:
    """Stamp ``is_active`` on session list rows."""
    running, known = gateway_session_run_states_func()
    for s in sessions:
        sid = str(s.get("id") or "")
        if sid in running:
            s["is_active"] = True
        elif sid in known:
            s["is_active"] = False
        else:
            s["is_active"] = (
                s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0)))
                < session_active_window_sec
            )


_SESSION_LIST_FIELDS = (
    "id",
    "source",
    "user_id",
    "model",
    "parent_session_id",
    "started_at",
    "ended_at",
    "end_reason",
    "message_count",
    "tool_call_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "title",
    "api_call_count",
    "preview",
    "last_active",
    "_lineage_root_id",
    "is_active",
)


def session_list_payload(session: dict[str, Any]) -> dict[str, Any]:
    """Return only fields needed by dashboard session lists."""
    return {key: session.get(key) for key in _SESSION_LIST_FIELDS if key in session}


def platform_chat_sources() -> list[str]:
    """Gateway chat-platform sources hidden from the app's session sidebar."""
    try:
        from gateway.config import Platform

        return [p.value for p in Platform if p.value != "local"]
    except Exception:
        return [
            "telegram", "discord", "whatsapp", "slack", "signal",
            "mattermost", "matrix", "homeassistant", "email", "sms",
            "dingtalk", "api_server", "webhook", "feishu", "wecom",
            "wecom_callback", "weixin", "bluebubbles", "qqbot", "yuanbao",
            "msgraph_webhook",
        ]
