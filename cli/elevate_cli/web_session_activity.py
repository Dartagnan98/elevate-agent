from __future__ import annotations

from typing import Any


def _gateway_session_keys(session: dict[str, Any]) -> set[str]:
    """Return every durable identity currently bound to one live actor."""
    values: list[Any] = [session.get("session_key"), session.get("session_id")]
    aliases = session.get("registry_aliases")
    if isinstance(aliases, (set, frozenset, list, tuple)):
        values.extend(aliases)
    return {
        normalized
        for value in values
        if (normalized := str(value or "").strip())
    }


def _project_exact_beta_session_models(
    sessions: list[dict[str, Any]],
    runtime_models: dict[str, str],
) -> None:
    """Attach proven live Beta runtime models without rewriting history.

    ``sessions.model`` records the model that created the durable session and
    is intentionally append-only historical metadata.  A runtime model is only
    projected when the in-process gateway has a ready actor for that exact
    session.  Invalid config, ended rows, and cold sessions therefore retain
    their historical truth instead of being labelled with a model they have
    not actually started.
    """
    from elevate_cli.beta_provider_policy import beta_provider_policy_active

    if not beta_provider_policy_active():
        return

    for session in sessions:
        session_id = str(session.get("id") or "")
        current_model = str(runtime_models.get(session_id) or "").strip()
        if not current_model:
            continue
        historical_model = str(session.get("model") or "").strip()
        if historical_model and historical_model != current_model:
            session["historical_model"] = historical_model
        session["runtime_model"] = current_model


def gateway_session_run_states() -> tuple[set[str], set[str]]:
    """(running_keys, known_keys) for sessions the in-process gateway hosts."""
    running: set[str] = set()
    known: set[str] = set()
    try:
        from tui_gateway import server as _gw

        for sess in list(getattr(_gw, "_sessions", {}).values()):
            if not isinstance(sess, dict):
                continue
            keys = _gateway_session_keys(sess)
            known.update(keys)
            if sess.get("running"):
                running.update(keys)
    except Exception:
        pass
    return running, known


def gateway_session_runtime_models() -> dict[str, str]:
    """Return models proven by ready, non-repairing in-process actors."""
    models: dict[str, str] = {}
    try:
        from tui_gateway import server as _gw

        for sess in list(getattr(_gw, "_sessions", {}).values()):
            if (
                not isinstance(sess, dict)
                or sess.get("registry_resetting")
                or sess.get("beta_runtime_repair_id")
                or sess.get("agent_error")
            ):
                continue
            agent = sess.get("agent")
            ready = sess.get("agent_ready")
            if agent is None or (ready is not None and not ready.is_set()):
                continue
            model = str(getattr(agent, "model", "") or "").strip()
            if not model:
                continue
            for key in _gateway_session_keys(sess):
                models[key] = model
    except Exception:
        pass
    return models


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
    gateway_session_runtime_models_func=gateway_session_runtime_models,
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
    _project_exact_beta_session_models(
        sessions,
        gateway_session_runtime_models_func(),
    )


_SESSION_LIST_FIELDS = (
    "id",
    "source",
    "user_id",
    "model",
    "historical_model",
    "runtime_model",
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
