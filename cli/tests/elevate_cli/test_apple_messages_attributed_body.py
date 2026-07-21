"""The Apple Messages ingester must read bodies out of ``attributedBody``.

Regression cover for the data-loss bug where the connector read only
``message.text`` — NULL for ~94% of messages on macOS Ventura+ — and imported
almost the entire message history with an empty body.

Uses an in-memory database shaped like ``chat.db`` and the connector's own
query, so the SELECT column list is covered too (a fix that decodes the blob
but forgets to select it would still fail here).
"""

from __future__ import annotations

import sqlite3

import pytest

from elevate_cli.source_connector_modules.apple_messages import _message_text

HEADER = b"\x04\x0bstreamtyped\x81\xe8\x03"
PREFIX = (
    HEADER
    + b"\x84\x01\x40"
    + b"\x84\x84\x84\x12NSAttributedString\x00"
    + b"\x84\x84\x08NSObject\x00"
    + b"\x85\x92"
    + b"\x84\x84\x84\x08NSString\x01\x94"
)


def _blob(text: str) -> bytes:
    payload = text.encode("utf-8")
    length = bytes([len(payload)]) if len(payload) < 0x80 else b"\x81" + len(payload).to_bytes(2, "little")
    return PREFIX + b"\x84\x01\x2b" + length + payload


@pytest.fixture()
def chat_db():
    """A minimal stand-in for ~/Library/Messages/chat.db."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, guid TEXT, date INTEGER,
            text TEXT, attributedBody BLOB, is_from_me INTEGER,
            service TEXT, handle_id INTEGER
        );
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY, guid TEXT,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        INSERT INTO handle VALUES (1, '+15555550123');
        INSERT INTO chat VALUES (1, 'iMessage;-;+15555550123', '+15555550123', '');
        """
    )
    yield conn
    conn.close()


# The connector's real query, minus ORDER BY, so the test breaks if the
# attributedBody column is ever dropped from the SELECT list.
CONNECTOR_QUERY = """
    SELECT
        m.ROWID AS message_rowid,
        m.guid AS message_guid,
        m.date AS message_date,
        m.text AS message_text,
        m.attributedBody AS message_attributed_body,
        m.is_from_me AS is_from_me,
        m.service AS service,
        h.id AS handle_id,
        c.ROWID AS chat_rowid,
        c.guid AS chat_guid,
        c.chat_identifier AS chat_identifier,
        c.display_name AS chat_display_name
    FROM message m
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN chat c ON c.ROWID = cmj.chat_id
    WHERE m.date IS NOT NULL
"""


def _insert(conn, rowid, text, blob):
    conn.execute(
        "INSERT INTO message VALUES (?,?,?,?,?,?,?,?)",
        (rowid, f"guid-{rowid}", 700000000000000000, text, blob, 0, "iMessage", 1),
    )
    conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (rowid,))


def _rows(conn):
    return {r["message_rowid"]: r for r in conn.execute(CONNECTOR_QUERY)}


def test_modern_message_body_is_recovered_from_attributed_body(chat_db):
    """The bug: text is NULL, the body is only in the blob."""
    _insert(chat_db, 1, None, _blob("the message that used to be lost"))
    assert _message_text(_rows(chat_db)[1]) == "the message that used to be lost"


def test_legacy_plain_text_column_still_wins(chat_db):
    _insert(chat_db, 1, "plain legacy text", _blob("blob version"))
    assert _message_text(_rows(chat_db)[1]) == "plain legacy text"


def test_blank_text_column_falls_through_to_blob(chat_db):
    _insert(chat_db, 1, "   ", _blob("real body"))
    assert _message_text(_rows(chat_db)[1]) == "real body"


def test_genuinely_bodiless_message_stays_empty(chat_db):
    """Attachment-only messages have neither text nor a decodable blob."""
    _insert(chat_db, 1, None, None)
    assert _message_text(_rows(chat_db)[1]) == ""


def test_unparsable_blob_degrades_instead_of_crashing(chat_db):
    _insert(chat_db, 1, None, b"\x00\x01 not a typedstream")
    assert _message_text(_rows(chat_db)[1]) == ""


def test_emoji_and_accents_survive_the_round_trip(chat_db):
    body = "on my way 🚗 — café at 3?"
    _insert(chat_db, 1, None, _blob(body))
    assert _message_text(_rows(chat_db)[1]) == body


def test_result_is_stripped(chat_db):
    _insert(chat_db, 1, None, _blob("  padded  "))
    assert _message_text(_rows(chat_db)[1]) == "padded"


def test_missing_column_is_tolerated():
    """Older callers may pass a row without the new column; must not raise."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT NULL AS message_text").fetchone()
    assert _message_text(row) == ""
    conn.close()


def test_mixed_history_recovers_the_modern_majority(chat_db):
    """Shape of the real regression: a few legacy rows, mostly modern ones."""
    _insert(chat_db, 1, "legacy", None)
    for i in range(2, 12):
        _insert(chat_db, i, None, _blob(f"modern message {i}"))
    rows = _rows(chat_db)
    bodies = [_message_text(rows[i]) for i in sorted(rows)]
    assert sum(1 for b in bodies if b) == 11
