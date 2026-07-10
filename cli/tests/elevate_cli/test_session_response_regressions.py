import inspect
import threading
from types import SimpleNamespace

from elevate_cli.data import chat_sessions
from elevate_cli.web_routes.sessions import create_sessions_router
from tui_gateway import server


def test_session_db_routes_are_sync_for_fastapi_threadpool():
    router = create_sessions_router(
        get_session_db=lambda: None,
        platform_chat_sources=lambda: [],
        mark_session_activity=lambda sessions, now: None,
        session_list_payload=lambda session: session,
    )
    endpoints = {route.path: route.endpoint for route in router.routes}

    assert not inspect.iscoroutinefunction(endpoints["/api/sessions"])
    assert not inspect.iscoroutinefunction(endpoints["/api/sessions/search"])


def test_slim_session_list_uses_one_query_and_skips_identity_resolution(monkeypatch):
    rows = [
        {
            "id": f"session-{index}",
            "source": "tui",
            "started_at": float(index),
            "ended_at": None,
            "last_active": float(index),
            "message_count": 1,
            "title": None,
            "preview": "hello",
        }
        for index in range(200)
    ]
    queries: list[str] = []
    identity_calls: list[str] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, _params):
            queries.append(query)
            return SimpleNamespace(fetchall=lambda: rows)

    monkeypatch.setattr(chat_sessions, "connect", FakeConnection)

    def resolve_identity(session_id):
        identity_calls.append(session_id)
        return {
            "requested_session_id": session_id,
            "lineage_root_id": session_id,
            "active_session_id": session_id,
            "session_kind": "chat",
            "is_compression_tip": True,
        }

    monkeypatch.setattr(
        chat_sessions, "resolve_canonical_session_identity", resolve_identity
    )

    result = chat_sessions.list_session_summaries(limit=200)

    assert len(result) == 200
    assert len(queries) == 1
    assert identity_calls == []


def test_session_create_returns_known_identity_without_resolving_it(monkeypatch):
    identity_calls: list[str] = []
    release_identity_lookup = threading.Event()

    class FakeDB:
        def create_session(self, *_args, **_kwargs):
            return None

        def resolve_canonical_session_identity(self, session_id):
            identity_calls.append(session_id)
            release_identity_lookup.wait(timeout=1)
            return {
                "requested_session_id": session_id,
                "lineage_root_id": session_id,
                "active_session_id": session_id,
                "session_kind": "chat",
                "is_compression_tip": True,
            }

    class FakeAgent:
        model = "test-model"
        provider = "test-provider"
        base_url = ""
        api_key = ""

    key = "new-root-session"
    monkeypatch.setattr(server, "_new_session_key", lambda: key)
    monkeypatch.setattr(server, "_enable_gateway_prompts", lambda: None)
    monkeypatch.setattr(server, "_load_show_reasoning", lambda: False)
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "compact")
    monkeypatch.setattr(server, "_make_agent", lambda _sid, _key: FakeAgent())
    monkeypatch.setattr(server, "_get_db", lambda: FakeDB())
    monkeypatch.setattr(server, "_resolve_model", lambda: "test-model")
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "test-model"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _agent: None)
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(server, "_probe_config_health", lambda _cfg: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)

    import tools.approval as approval

    monkeypatch.setattr(approval, "register_gateway_notify", lambda _key, _cb: None)
    monkeypatch.setattr(approval, "load_permanent_allowlist", lambda: None)

    response = server.handle_request(
        {"id": "create", "method": "session.create", "params": {"cols": 80}}
    )
    result = response["result"]
    sid = result["session_id"]
    try:
        assert result["persisted_session_id"] == key
        assert result["requested_session_id"] == key
        assert result["lineage_root_id"] == key
        assert result["active_session_id"] == key
        assert result["session_kind"] == "chat"
        assert result["is_compression_tip"] is True
        assert identity_calls == []
        assert server._sessions[sid]["agent_ready"].wait(timeout=2)
    finally:
        release_identity_lookup.set()
        server._sessions.pop(sid, None)
