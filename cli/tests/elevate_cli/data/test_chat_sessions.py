import sqlite3

from elevate_cli.data import chat_sessions


def test_delete_session_orphans_children_and_cascades_messages(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            parent_session_id TEXT REFERENCES chat_sessions(id)
        );
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            content TEXT
        );
        """
    )
    conn.execute("INSERT INTO chat_sessions (id) VALUES ('parent')")
    conn.execute(
        "INSERT INTO chat_sessions (id, parent_session_id) VALUES ('child', 'parent')"
    )
    conn.execute(
        "INSERT INTO chat_messages (session_id, content) VALUES ('parent', 'hi')"
    )
    conn.commit()
    monkeypatch.setattr(chat_sessions, "connect", lambda: conn)

    assert chat_sessions.delete_session("parent") is True

    assert conn.execute(
        "SELECT COUNT(*) FROM chat_sessions WHERE id = 'parent'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT parent_session_id FROM chat_sessions WHERE id = 'child'"
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'parent'"
    ).fetchone()[0] == 0


def test_delete_session_returns_false_when_missing(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
    conn.commit()
    monkeypatch.setattr(chat_sessions, "connect", lambda: conn)

    assert chat_sessions.delete_session("missing") is False
