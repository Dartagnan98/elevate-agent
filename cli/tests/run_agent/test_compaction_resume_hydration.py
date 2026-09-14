"""Step 4 of the compaction redesign — resume reads cursor+summary, not tip-walk.

A new-style session never rotates: the full append-only transcript stays in the
session row and the payload cursor + synthetic summary live as session METADATA.
``AIAgent.__init__`` hydrates that metadata for fresh AND resumed sessions
through one path (create_session is INSERT-OR-IGNORE so resume preserves the
persisted compaction columns).

These tests prove a fresh agent rebuilt on the SAME session_id picks up the
persisted (cursor, summary), and that a legacy session (cursor 0 / NULL summary)
hydrates to the no-compaction sentinel — leaving the legacy tip-walk read path in
charge.
"""

import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from elevate_state import SessionDB


def _make_agent(session_db, session_id):
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent
        return AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            session_db=session_db,
            session_id=session_id,
            skip_context_files=True,
            skip_memory=True,
        )


def test_resume_hydrates_persisted_cursor_and_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = SessionDB(db_path=Path(tmpdir) / "state.db")
        # First agent build creates the row at the legacy sentinel.
        a1 = _make_agent(db, "sess-resume")
        assert a1.compaction_cursor == 0
        assert a1.compaction_summary is None

        # A compaction persisted (summary, cursor) as session metadata.
        db.update_compaction("sess-resume", "HANDOFF: did the first 12 turns", 12)

        # Resume: a brand-new agent on the SAME session_id must hydrate them.
        a2 = _make_agent(db, "sess-resume")
        assert a2.compaction_cursor == 12
        assert a2.compaction_summary == "HANDOFF: did the first 12 turns"


def test_legacy_session_hydrates_to_sentinel():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = SessionDB(db_path=Path(tmpdir) / "state.db")
        # Simulate a pre-redesign session row that never carried compaction
        # metadata (the columns self-heal to defaults).
        db.create_session(session_id="legacy-sess", source="cli")
        agent = _make_agent(db, "legacy-sess")
        # cursor 0 / None summary is the legacy sentinel — tip-walk read path
        # stays in charge for this session.
        assert agent.compaction_cursor == 0
        assert agent.compaction_summary is None


def test_create_session_does_not_clobber_compaction_on_resume():
    # The resume agent build calls create_session (INSERT OR IGNORE); it must
    # NOT reset an existing row's compaction columns.
    with tempfile.TemporaryDirectory() as tmpdir:
        db = SessionDB(db_path=Path(tmpdir) / "state.db")
        db.create_session(session_id="s", source="cli")
        db.update_compaction("s", "summary", 9)
        # Re-create (idempotent upsert path the agent build uses).
        db.create_session(session_id="s", source="cli")
        row = db.get_session("s")
        assert row["compaction_cursor"] == 9
        assert row["compaction_summary"] == "summary"
