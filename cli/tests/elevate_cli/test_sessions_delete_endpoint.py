from fastapi.testclient import TestClient

from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app


def test_delete_session_endpoint_deletes_pg_chat_session(monkeypatch):
    class FakeDB:
        def resolve_session_id(self, session_id):
            return session_id

        def delete_session(self, session_id):
            return False

        def close(self):
            pass

    deleted = []

    def fake_delete_chat_session(session_id):
        deleted.append(session_id)
        return True

    import elevate_state
    from elevate_cli.data import chat_sessions

    monkeypatch.setattr(elevate_state, "SessionDB", FakeDB)
    monkeypatch.setattr(chat_sessions, "delete_session", fake_delete_chat_session)

    client = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    response = client.delete("/api/sessions/pg-session")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert deleted == ["pg-session"]
