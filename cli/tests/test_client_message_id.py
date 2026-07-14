"""Stable per-message identity (client_message_id) — persistence layer.

Phase 1 of plans/chat-transcript-refactor.md: every message row carries a
stable id minted at append time; legacy rows hydrate with a deterministic
``legacy.{session}.{ordinal}`` fallback; the platform message id namespace
(telegram/yuanbao) is never confused with ours.
"""

import json
import sqlite3
import threading
import time

import pytest

from elevate_state import SessionDB
from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    PolicyWideningError,
)


@pytest.fixture()
def db(tmp_path):
    session_db = SessionDB(db_path=tmp_path / "state.db")
    yield session_db
    session_db.close()


def _raw_row(db, session_id, *, index=0):
    cur = db._conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
    )
    rows = cur.fetchall()
    return rows[index]


def _receipt_count(db, session_id):
    row = db._conn.execute(
        "SELECT COUNT(*) FROM prompt_receipts WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row[0]


def _prepare_receipt(db, session_id, *, message_id="user-1", content="first"):
    return db.prepare_prompt_receipt(
        session_id,
        content,
        assistant_message_id="assistant-1",
        client_message_id=message_id,
        payload={"text": content},
    )


class TestAppendMessageMint:
    def test_default_mint_uuid(self, db):
        db.create_session(session_id="s1", source="cli")
        db.append_message("s1", "user", content="hi")
        row = _raw_row(db, "s1")
        cmid = row["client_message_id"]
        assert isinstance(cmid, str) and len(cmid) == 32  # uuid4().hex

    def test_explicit_id_round_trips(self, db):
        db.create_session(session_id="s1", source="cli")
        db.append_message("s1", "assistant", content="yo", client_message_id="abc123")
        assert _raw_row(db, "s1")["client_message_id"] == "abc123"

    def test_every_row_gets_distinct_ids(self, db):
        db.create_session(session_id="s1", source="cli")
        for i in range(3):
            db.append_message("s1", "user", content=f"m{i}")
        ids = {
            r["client_message_id"]
            for r in db._conn.execute(
                "SELECT client_message_id FROM messages WHERE session_id='s1'"
            ).fetchall()
        }
        assert len(ids) == 3
        assert all(ids)

    def test_platform_id_is_independent(self, db):
        """client_message_id never aliases platform_message_id."""
        db.create_session(session_id="s1", source="telegram")
        db.append_message(
            "s1", "user", content="from tg",
            platform_message_id="tg-777", client_message_id="ours-1",
        )
        row = _raw_row(db, "s1")
        assert row["platform_message_id"] == "tg-777"
        assert row["client_message_id"] == "ours-1"


class TestPromptReceipt:
    def test_policy_round_trips_with_atomic_receipt_prepare(self, db):
        db.create_session(session_id="s1", source="tui")
        policy = ExecutionPolicy.for_mode("user-policy", ExecutionPolicyMode.PLAN)

        receipt = db.prepare_prompt_receipt(
            "s1",
            "inspect the deal",
            assistant_message_id="assistant-policy",
            client_message_id="user-policy",
            payload={"text": "inspect the deal"},
            accepted_policy=policy,
        )

        expected = policy.to_dict()
        assert receipt["accepted_policy"] == expected
        assert receipt["effective_policy"] == expected
        assert receipt["policy_revision"] == 0
        assert db.get_prompt_receipt("s1", "user-policy") == {
            key: value for key, value in receipt.items() if key != "inserted"
        }
        recovered = db.get_recoverable_prompt_receipt("s1")
        assert recovered["accepted_policy"] == expected
        assert recovered["effective_policy"] == expected

        raw = db._conn.execute(
            "SELECT accepted_policy_json, effective_policy_json "
            "FROM prompt_receipts WHERE session_id = ? AND client_message_id = ?",
            ("s1", "user-policy"),
        ).fetchone()
        assert raw["accepted_policy_json"] == raw["effective_policy_json"]

    def test_policy_identity_mismatch_rolls_back_entire_prepare(self, db):
        db.create_session(session_id="s1", source="tui")
        policy = ExecutionPolicy.for_mode("another-turn", ExecutionPolicyMode.PLAN)

        with pytest.raises(ValueError, match="must match client_message_id"):
            db.prepare_prompt_receipt(
                "s1",
                "inspect the deal",
                assistant_message_id="assistant-policy",
                client_message_id="user-policy",
                payload={"text": "inspect the deal"},
                accepted_policy=policy,
            )

        assert db.get_messages("s1") == []
        assert _receipt_count(db, "s1") == 0

    def test_retry_cannot_replace_original_policy(self, db):
        db.create_session(session_id="s1", source="tui")
        original = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.READ_ONLY)
        replacement = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)

        first = db.prepare_prompt_receipt(
            "s1",
            "inspect",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "inspect"},
            accepted_policy=original,
        )
        duplicate = db.prepare_prompt_receipt(
            "s1",
            "inspect",
            assistant_message_id="assistant-ignored",
            client_message_id="user-1",
            payload={"text": "inspect"},
            accepted_policy=replacement,
        )

        assert first["accepted_policy"] == original.to_dict()
        assert duplicate["inserted"] is False
        assert duplicate["accepted_policy"] == original.to_dict()
        assert duplicate["effective_policy"] == original.to_dict()
        assert duplicate["policy_revision"] == 0

    def test_policy_cas_narrows_effective_policy_only(self, db):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)
        db.prepare_prompt_receipt(
            "s1",
            "prepare a plan",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "prepare a plan"},
            accepted_policy=accepted,
        )
        narrowed = accepted.narrow({"read"}, mode=ExecutionPolicyMode.PLAN)

        updated = db.narrow_prompt_receipt_policy(
            "s1",
            "user-1",
            expected_revision=0,
            narrowed_policy=narrowed,
        )

        assert updated["accepted_policy"] == accepted.to_dict()
        assert updated["effective_policy"] == narrowed.to_dict()
        assert updated["policy_revision"] == 1
        assert db.narrow_prompt_receipt_policy(
            "s1",
            "user-1",
            expected_revision=0,
            narrowed_policy=narrowed,
        ) is None

    def test_policy_cas_rejects_widening_without_mutation(self, db):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.PLAN)
        db.prepare_prompt_receipt(
            "s1",
            "prepare a plan",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "prepare a plan"},
            accepted_policy=accepted,
        )
        widened = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)

        with pytest.raises(PolicyWideningError):
            db.narrow_prompt_receipt_policy(
                "s1",
                "user-1",
                expected_revision=0,
                narrowed_policy=widened,
            )

        stored = db.get_prompt_receipt("s1", "user-1")
        assert stored["accepted_policy"] == accepted.to_dict()
        assert stored["effective_policy"] == accepted.to_dict()
        assert stored["policy_revision"] == 0

    def test_policy_cas_has_one_winner_across_real_concurrent_connections(
        self,
        db,
    ):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)
        db.prepare_prompt_receipt(
            "s1",
            "prepare a plan",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "prepare a plan"},
            accepted_policy=accepted,
        )
        candidates = [
            accepted.narrow(
                {"read", "write_local:session_plan"},
                mode=ExecutionPolicyMode.PLAN,
            ),
            accepted.narrow({"read"}, mode=ExecutionPolicyMode.READ_ONLY),
        ]
        connections = [SessionDB(db_path=db.db_path), SessionDB(db_path=db.db_path)]
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def _narrow(connection, candidate):
            try:
                barrier.wait(timeout=5)
                results.append(
                    connection.narrow_prompt_receipt_policy(
                        "s1",
                        "user-1",
                        expected_revision=0,
                        narrowed_policy=candidate,
                    )
                )
            except Exception as exc:
                errors.append(exc)

        workers = [
            threading.Thread(target=_narrow, args=(connection, candidate))
            for connection, candidate in zip(connections, candidates)
        ]
        try:
            for worker in workers:
                worker.start()
            barrier.wait(timeout=5)
            for worker in workers:
                worker.join(timeout=10)

            assert all(not worker.is_alive() for worker in workers)
            assert errors == []
            assert len(results) == 2
            assert sum(result is not None for result in results) == 1
            stored = db.get_prompt_receipt("s1", "user-1")
            assert stored["policy_revision"] == 1
            assert stored["effective_policy"] in [
                candidate.to_dict() for candidate in candidates
            ]
        finally:
            for connection in connections:
                connection.close()

    def test_policy_cas_fails_closed_on_malformed_stored_accepted_policy(self, db):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)
        db.prepare_prompt_receipt(
            "s1",
            "prepare a plan",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "prepare a plan"},
            accepted_policy=accepted,
        )
        db._conn.execute(
            "UPDATE prompt_receipts SET accepted_policy_json = ? "
            "WHERE session_id = ? AND client_message_id = ?",
            ("{malformed", "s1", "user-1"),
        )

        with pytest.raises(ValueError, match="stored accepted execution policy"):
            db.narrow_prompt_receipt_policy(
                "s1",
                "user-1",
                expected_revision=0,
                narrowed_policy=accepted.narrow({"read"}),
            )

        raw = db._conn.execute(
            "SELECT policy_revision, effective_policy_json "
            "FROM prompt_receipts WHERE session_id = ? AND client_message_id = ?",
            ("s1", "user-1"),
        ).fetchone()
        assert raw["policy_revision"] == 0
        assert raw["effective_policy_json"] is not None

    def test_policy_cas_rejects_inconsistent_stored_effective_ceiling(self, db):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.READ_ONLY)
        db.prepare_prompt_receipt(
            "s1",
            "inspect",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "inspect"},
            accepted_policy=accepted,
        )
        broader = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)
        db._conn.execute(
            "UPDATE prompt_receipts SET effective_policy_json = ? "
            "WHERE session_id = ? AND client_message_id = ?",
            (
                json.dumps(
                    broader.to_dict(), sort_keys=True, separators=(",", ":")
                ),
                "s1",
                "user-1",
            ),
        )

        with pytest.raises((PolicyWideningError, ValueError)):
            db.narrow_prompt_receipt_policy(
                "s1",
                "user-1",
                expected_revision=0,
                narrowed_policy=accepted,
            )

        stored = db.get_prompt_receipt("s1", "user-1")
        assert stored["accepted_policy"] == accepted.to_dict()
        assert stored["effective_policy"] == broader.to_dict()
        assert stored["policy_revision"] == 0

    def test_legacy_policyless_receipt_cannot_be_narrowed(self, db):
        db.create_session(session_id="s1", source="tui")
        receipt = _prepare_receipt(db, "s1")
        candidate = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.READ_ONLY)

        assert receipt["accepted_policy"] is None
        assert receipt["effective_policy"] is None
        assert receipt["policy_revision"] == 0
        assert db.narrow_prompt_receipt_policy(
            "s1",
            "user-1",
            expected_revision=0,
            narrowed_policy=candidate,
        ) is None

    def test_terminal_receipt_policy_cannot_be_narrowed(self, db):
        db.create_session(session_id="s1", source="tui")
        accepted = ExecutionPolicy.for_mode("user-1", ExecutionPolicyMode.DEFAULT)
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
            accepted_policy=accepted,
        )
        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="complete"
        ) is True

        assert db.narrow_prompt_receipt_policy(
            "s1",
            "user-1",
            expected_revision=0,
            narrowed_policy=accepted.narrow({"read"}),
        ) is None

    def test_atomic_policy_interrupt_persists_one_idempotent_assistant(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")

        for _attempt in range(2):
            assert db.interrupt_prompt_receipt_with_assistant(
                "s1",
                "user-1",
                owner_id="secure-recovery",
                assistant_message_id="assistant-1",
                assistant_content="Nothing was run. Please resend the request.",
            ) is True

        receipt = db.get_prompt_receipt("s1", "user-1")
        assert receipt["status"] == "interrupted"
        assert receipt["owner_id"] == "secure-recovery"
        assert db.get_recoverable_prompt_receipt("s1") is None
        messages = db.get_messages_as_conversation("s1")
        assert [(message["role"], message["client_message_id"]) for message in messages] == [
            ("user", "user-1"),
            ("assistant", "assistant-1"),
        ]
        assert messages[-1]["finish_reason"] == "interrupted"
        assert db.get_session("s1")["message_count"] == 2

    def test_atomic_policy_interrupt_rolls_back_on_assistant_insert_failure(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")
        db._conn.execute(
            "CREATE TRIGGER fail_policy_interrupt_assistant "
            "BEFORE INSERT ON messages "
            "WHEN NEW.client_message_id = 'assistant-1' "
            "BEGIN SELECT RAISE(ABORT, 'injected assistant write failure'); END"
        )

        with pytest.raises(sqlite3.IntegrityError, match="injected assistant"):
            db.interrupt_prompt_receipt_with_assistant(
                "s1",
                "user-1",
                owner_id="secure-recovery",
                assistant_message_id="assistant-1",
                assistant_content="Nothing was run. Please resend the request.",
            )

        receipt = db.get_prompt_receipt("s1", "user-1")
        assert receipt["status"] == "pending"
        assert receipt["owner_id"] is None
        assert db.get_recoverable_prompt_receipt("s1")["status"] == "pending"
        messages = db.get_messages_as_conversation("s1")
        assert [(message["role"], message["client_message_id"]) for message in messages] == [
            ("user", "user-1"),
        ]
        assert db.get_session("s1")["message_count"] == 1

    def test_retry_returns_original_row_without_duplicate(self, db):
        db.create_session(session_id="s1", source="tui")
        payload = {"text": "send the offer", "persist_user_message": None}

        first = db.prepare_prompt_receipt(
            "s1",
            "send the offer",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload=payload,
        )
        retry = db.prepare_prompt_receipt(
            "s1",
            "send the offer",
            assistant_message_id="ignored-on-retry",
            client_message_id="user-1",
            payload=payload,
        )

        assert (first["inserted"], retry["inserted"]) == (True, False)
        assert retry["assistant_message_id"] == "assistant-1"
        assert retry["status"] == "pending"
        assert len(db.get_messages("s1")) == 1
        assert db.get_session("s1")["message_count"] == 1

    def test_retry_id_cannot_alias_different_prompt(self, db):
        db.create_session(session_id="s1", source="tui")
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
        )

        with pytest.raises(ValueError, match="different prompt"):
            db.prepare_prompt_receipt(
                "s1",
                "second",
                assistant_message_id="assistant-2",
                client_message_id="user-1",
                payload={"text": "second"},
            )

    def test_claim_is_single_owner_and_terminal(self, db):
        db.create_session(session_id="s1", source="tui")
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
        )

        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is False
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="complete"
        ) is True
        assert db.get_recoverable_prompt_receipt("s1") is None

    def test_deferred_terminal_receipt_is_not_restart_recoverable(self, db):
        db.create_session(session_id="s1", source="tui")
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
        )

        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="deferred"
        ) is True
        assert db.get_recoverable_prompt_receipt("s1") is None

    def test_waiting_input_receipt_is_terminal_not_restart_recoverable(self, db):
        db.create_session(session_id="s1", source="tui")
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
        )

        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="waiting_input"
        ) is True
        assert db.get_recoverable_prompt_receipt("s1") is None

    def test_update_message_finish_reason_round_trips(self, db):
        db.create_session(session_id="s1", source="tui")
        db.append_message(
            "s1",
            "assistant",
            content="Which province?",
            finish_reason="incomplete",
            client_message_id="assistant-1",
        )

        assert db.update_message_finish_reason(
            "s1", "assistant-1", "needs_input"
        ) is True
        assert db.get_messages_as_conversation("s1")[0]["finish_reason"] == "needs_input"

    def test_preserved_terminal_receipt_stays_idempotent_after_replay_clear(self, db):
        db.create_session(session_id="s1", source="tui")
        first = _prepare_receipt(
            db,
            "s1",
            message_id="overflow-user",
            content="oversized prompt",
        )
        assert db.claim_prompt_receipt(
            "s1", "overflow-user", owner_id="owner-a"
        ) is True
        assert db.finish_prompt_receipt(
            "s1", "overflow-user", owner_id="owner-a", status="error"
        ) is True

        db.replace_messages("s1", [], preserve_prompt_receipts=True)

        duplicate = _prepare_receipt(
            db,
            "s1",
            message_id="overflow-user",
            content="oversized prompt",
        )
        assert duplicate["inserted"] is False
        assert duplicate["status"] == "error"
        assert duplicate["assistant_message_id"] == first["assistant_message_id"]
        assert db.get_messages("s1") == []

        with pytest.raises(ValueError, match="different prompt"):
            _prepare_receipt(
                db,
                "s1",
                message_id="overflow-user",
                content="different prompt",
            )

    def test_dead_owner_claim_can_be_recovered_once(self, db):
        db.create_session(session_id="s1", source="tui")
        db.prepare_prompt_receipt(
            "s1",
            "first",
            assistant_message_id="assistant-1",
            client_message_id="user-1",
            payload={"text": "first"},
        )
        db.claim_prompt_receipt("s1", "user-1", owner_id="old-owner")

        assert db.claim_prompt_receipt(
            "s1",
            "user-1",
            owner_id="new-owner",
            reclaim_owner_id="old-owner",
        ) is True
        assert db.claim_prompt_receipt(
            "s1",
            "user-1",
            owner_id="third-owner",
            reclaim_owner_id="old-owner",
        ) is False


class TestPromptReceiptLifecycle:
    def test_clear_removes_receipts_and_allows_same_id_again(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")

        db.clear_messages("s1")

        assert db.get_messages("s1") == []
        assert db.get_session("s1")["message_count"] == 0
        assert _receipt_count(db, "s1") == 0

        retry = _prepare_receipt(db, "s1")
        assert retry["inserted"] is True
        assert len(db.get_messages("s1")) == 1
        assert _receipt_count(db, "s1") == 1

    def test_replace_invalidates_terminal_receipt_without_duplicate_user(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")
        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="complete"
        ) is True

        history = [
            {"role": "user", "content": "first", "client_message_id": "user-1"}
        ]
        db.replace_messages("s1", history)

        assert _receipt_count(db, "s1") == 0
        recreated = _prepare_receipt(db, "s1")
        assert recreated["inserted"] is True
        assert len(db.get_messages("s1")) == 1
        assert _receipt_count(db, "s1") == 1

    def test_delete_session_with_pending_receipt(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")

        assert db.delete_session("s1") is True
        assert db.get_session("s1") is None
        assert _receipt_count(db, "s1") == 0

    def test_prune_session_with_terminal_receipt(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")
        assert db.claim_prompt_receipt("s1", "user-1", owner_id="owner-a") is True
        assert db.finish_prompt_receipt(
            "s1", "user-1", owner_id="owner-a", status="complete"
        ) is True
        db.end_session("s1", end_reason="done")
        db._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (time.time() - 100 * 86400, "s1"),
        )
        db._conn.commit()

        assert db.prune_sessions(older_than_days=90) == 1
        assert db.get_session("s1") is None
        assert _receipt_count(db, "s1") == 0

    def test_ghost_prune_removes_orphaned_receipt(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")
        db.end_session("s1", end_reason="done")
        db._conn.execute("DELETE FROM messages WHERE session_id = ?", ("s1",))
        db._conn.execute(
            "UPDATE sessions SET started_at = ?, message_count = 0 WHERE id = ?",
            (time.time() - 2 * 86400, "s1"),
        )
        db._conn.commit()

        assert db.prune_empty_ghost_sessions() == 1
        assert db.get_session("s1") is None
        assert _receipt_count(db, "s1") == 0

    def test_receipt_foreign_key_cascades_on_direct_session_delete(self, db):
        db.create_session(session_id="s1", source="tui")
        _prepare_receipt(db, "s1")
        db._conn.execute("DELETE FROM messages WHERE session_id = ?", ("s1",))
        db._conn.execute("DELETE FROM sessions WHERE id = ?", ("s1",))
        db._conn.commit()

        assert _receipt_count(db, "s1") == 0


class TestSchemaReconcile:
    def test_old_db_file_gains_column_on_open(self, tmp_path):
        """A pre-upgrade state.db (no client_message_id column) is upgraded
        declaratively by _reconcile_columns on construction."""
        db_path = tmp_path / "old_state.db"
        # Build a REAL current-schema DB, then strip the new column to
        # simulate a pre-upgrade file (avoids hand-maintaining a schema copy).
        seed = SessionDB(db_path=db_path)
        seed.create_session(session_id="legacy-s", source="cli")
        seed.append_message("legacy-s", "user", content="old row")
        seed.close()
        conn = sqlite3.connect(str(db_path))
        conn.execute("ALTER TABLE messages DROP COLUMN client_message_id")
        conn.commit()
        conn.close()

        db = SessionDB(db_path=db_path)
        try:
            cols = {
                r[1]
                for r in db._conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            assert "client_message_id" in cols
            row = db._conn.execute(
                "SELECT client_message_id FROM messages WHERE session_id='legacy-s'"
            ).fetchone()
            assert row[0] is None  # legacy rows stay NULL; readers mint fallback
        finally:
            db.close()

    def test_old_prompt_receipts_gain_nullable_policy_columns(self, tmp_path):
        db_path = tmp_path / "old_policy_state.db"
        seed = SessionDB(db_path=db_path)
        seed.create_session(session_id="legacy-s", source="tui")
        _prepare_receipt(seed, "legacy-s")
        seed.close()

        conn = sqlite3.connect(str(db_path))
        conn.execute("ALTER TABLE prompt_receipts DROP COLUMN accepted_policy_json")
        conn.execute("ALTER TABLE prompt_receipts DROP COLUMN effective_policy_json")
        conn.execute("ALTER TABLE prompt_receipts DROP COLUMN policy_revision")
        conn.commit()
        conn.close()

        db = SessionDB(db_path=db_path)
        try:
            columns = {
                row[1]: row
                for row in db._conn.execute(
                    "PRAGMA table_info(prompt_receipts)"
                ).fetchall()
            }
            assert {
                "accepted_policy_json",
                "effective_policy_json",
                "policy_revision",
            }.issubset(columns)
            assert columns["accepted_policy_json"][3] == 0
            assert columns["effective_policy_json"][3] == 0
            assert columns["policy_revision"][3] == 1
            assert columns["policy_revision"][4] == "0"

            receipt = db.get_prompt_receipt("legacy-s", "user-1")
            assert receipt["accepted_policy"] is None
            assert receipt["effective_policy"] is None
            assert receipt["policy_revision"] == 0
        finally:
            db.close()


class TestConversationReaderStamping:
    def test_real_ids_pass_through(self, db, monkeypatch):
        monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
        db.create_session(session_id="s1", source="cli")
        db.append_message("s1", "user", content="q", client_message_id="u-1")
        db.append_message("s1", "assistant", content="a", client_message_id="a-1")
        msgs = db.get_messages_as_conversation("s1")
        assert [m["client_message_id"] for m in msgs] == ["u-1", "a-1"]

    def test_legacy_rows_get_deterministic_fallback(self, db, monkeypatch):
        monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
        db.create_session(session_id="s1", source="cli")
        db.append_message("s1", "user", content="q")
        db.append_message("s1", "assistant", content="a")
        # Simulate pre-upgrade rows: NULL out the ids.
        db._conn.execute("UPDATE messages SET client_message_id = NULL")
        db._conn.commit()
        first = db.get_messages_as_conversation("s1")
        second = db.get_messages_as_conversation("s1")
        assert [m["client_message_id"] for m in first] == [
            "legacy.s1.0",
            "legacy.s1.1",
        ]
        # Deterministic across reads.
        assert [m["client_message_id"] for m in first] == [
            m["client_message_id"] for m in second
        ]

    def test_platform_message_id_namespace_untouched(self, db, monkeypatch):
        """msg['message_id'] stays the PLATFORM id; ours is a separate key."""
        monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
        db.create_session(session_id="s1", source="telegram")
        db.append_message(
            "s1", "user", content="x",
            platform_message_id="tg-9", client_message_id="ours-9",
        )
        msg = db.get_messages_as_conversation("s1")[0]
        assert msg["message_id"] == "tg-9"
        assert msg["client_message_id"] == "ours-9"


class TestReplaceMessagesPreservesIds:
    def test_rewrite_keeps_existing_and_mints_missing(self, db, monkeypatch):
        monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
        db.create_session(session_id="s1", source="cli")
        history = [
            {"role": "user", "content": "q", "client_message_id": "keep-me"},
            {"role": "assistant", "content": "a"},  # no id -> minted
        ]
        db.replace_messages("s1", history)
        msgs = db.get_messages_as_conversation("s1")
        assert msgs[0]["client_message_id"] == "keep-me"
        assert msgs[1]["client_message_id"]
        assert msgs[1]["client_message_id"] != "keep-me"
        # The in-memory dicts were stamped too (rewrite flows keep identity).
        assert history[1]["client_message_id"] == msgs[1]["client_message_id"]
