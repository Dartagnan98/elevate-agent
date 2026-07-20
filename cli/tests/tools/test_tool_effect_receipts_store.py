"""Durable general-registry tool-effect receipts: one-winner claims, terminal
receipts, crash-window cleanup, and outcome-immutable transform evidence.

Store-level adversarial coverage for the A3 broker generalization of the
``0bbb80997`` terminal machinery (``tool_effect_receipts`` plus the new
approval-receipt transform CAS).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

import pytest

from elevate_state import SessionDB
from tools import approval


_BOOT = "a" * 32
_OLD_BOOT = "b" * 32
_SESSION = "session-tool-effect"
_INVOCATION = "call-tool-effect"


def _sha(value: object) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _policy() -> approval.ExecutionPolicy:
    return approval.ExecutionPolicy.for_mode("turn-tool-effect", "draft_only")


def _db(tmp_path) -> SessionDB:
    return SessionDB(tmp_path / "state.db")


def _claim_kwargs(**overrides) -> dict:
    policy = _policy()
    kwargs = {
        "claim_id": uuid.uuid4().hex,
        "boot_id": _BOOT,
        "session_id": _SESSION,
        "invocation_id": _INVOCATION,
        "turn_id": policy.accepted_turn_id,
        "tool_name": "draft_writer",
        "entry_id": 7,
        "registry_generation": 21,
        "canonical_args_digest": _sha({"value": 1}),
        "handler_kwargs_digest": _sha({"task_id": None}),
        "accepted_policy": policy.to_dict(),
        "policy_revision": 3,
        "effect_set": ["write_local:draft"],
    }
    kwargs.update(overrides)
    return kwargs


class TestToolEffectClaim:
    def test_claim_is_one_winner_per_invocation_identity(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)

        first = db.claim_tool_effect(**_claim_kwargs())
        assert first is not None and first["status"] == "claimed"
        assert first["effect_set"] == ["write_local:draft"]

        # A second claim for the SAME durable invocation identity can never
        # re-claim — regardless of a fresh claim_id.
        duplicate = db.claim_tool_effect(**_claim_kwargs())
        assert duplicate is None

        # A different invocation identity claims independently.
        other = db.claim_tool_effect(
            **_claim_kwargs(invocation_id="call-tool-effect-2")
        )
        assert other is not None and other["status"] == "claimed"

    def test_claim_requires_an_active_boot_lease(self, tmp_path):
        db = _db(tmp_path)
        with pytest.raises(RuntimeError):
            db.claim_tool_effect(**_claim_kwargs())

    def test_claim_refuses_a_foreign_boot(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        assert db.claim_tool_effect(**_claim_kwargs(boot_id="c" * 32)) is None

    def test_claim_rejects_effects_exceeding_the_accepted_policy(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        with pytest.raises(ValueError):
            db.claim_tool_effect(**_claim_kwargs(effect_set=["destructive"]))

    def test_claim_rejects_turn_policy_mismatch(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        with pytest.raises(ValueError):
            db.claim_tool_effect(**_claim_kwargs(turn_id="turn-other"))


class TestToolEffectCompletion:
    def test_success_receipt_requires_a_result_digest(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claimed = db.claim_tool_effect(**_claim_kwargs())
        with pytest.raises(ValueError):
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="succeeded",
                result_digest=None,
                failure_code=None,
            )

    def test_terminal_receipt_is_written_exactly_once(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claimed = db.claim_tool_effect(**_claim_kwargs())
        digest = _sha("result-body")
        assert (
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="succeeded",
                result_digest=digest,
                failure_code=None,
            )
            == 1
        )
        receipt = db.get_tool_effect_receipt(claimed["claim_id"])
        assert receipt["status"] == "succeeded"
        assert receipt["result_digest"] == digest
        # Replay of the terminal transition is refused.
        assert (
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="failed",
                result_digest=None,
                failure_code="handler_exception",
            )
            == 0
        )
        assert db.get_tool_effect_receipt(claimed["claim_id"])["status"] == (
            "succeeded"
        )

    def test_completion_shape_validation_fails_closed(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claimed = db.claim_tool_effect(**_claim_kwargs())
        with pytest.raises(ValueError):
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="unknown",
                result_digest=_sha("x"),
                failure_code="final_receipt_unavailable",
            )
        with pytest.raises(ValueError):
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="failed",
                result_digest=None,
                failure_code=None,
            )
        with pytest.raises(ValueError):
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="failed",
                result_digest=None,
                failure_code="Handler:Exception",
            )

    def test_completion_refuses_a_foreign_boot(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claimed = db.claim_tool_effect(**_claim_kwargs())
        assert (
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id="c" * 32,
                status="succeeded",
                result_digest=_sha("x"),
                failure_code=None,
            )
            == 0
        )


class TestPriorBootCleanup:
    def test_crash_window_claims_terminalize_unknown(self, tmp_path):
        db = _db(tmp_path)
        # A dead prior process owned the old lease.
        db.activate_approval_boot(
            _OLD_BOOT,
            process_id=999_999,
            process_create_time=time.time() - 3600,
        )
        stale = db.claim_tool_effect(**_claim_kwargs(boot_id=_OLD_BOOT))
        assert stale is not None

        assert db.activate_approval_boot(_BOOT) is True
        terminal = db.mark_prior_boot_tool_effects_unknown(_BOOT)
        assert len(terminal) == 1
        assert terminal[0]["status"] == "unknown"
        assert terminal[0]["failure_code"] == "prior_boot_crash_window"

        receipt = db.get_tool_effect_receipt(stale["claim_id"])
        assert receipt["status"] == "unknown"
        # And the crash-window invocation identity stays burned: the same
        # (session, invocation) can never be re-claimed after a restart.
        assert db.claim_tool_effect(**_claim_kwargs()) is None

    def test_current_boot_claims_are_left_alone(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        live = db.claim_tool_effect(**_claim_kwargs())
        assert db.mark_prior_boot_tool_effects_unknown(_BOOT) == []
        assert db.get_tool_effect_receipt(live["claim_id"])["status"] == "claimed"


class TestResultTransformEvidence:
    def _terminal_receipt(self, db, *, result_digest):
        claimed = db.claim_tool_effect(**_claim_kwargs())
        assert (
            db.complete_tool_effect(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                status="succeeded",
                result_digest=result_digest,
                failure_code=None,
            )
            == 1
        )
        return claimed["claim_id"]

    def test_transform_binds_once_and_is_digest_anchored(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        pre = _sha("original-result")
        post = _sha("rewritten-result")
        claim_id = self._terminal_receipt(db, result_digest=pre)

        assert (
            db.record_tool_effect_result_transform(
                claim_id=claim_id,
                boot_id=_BOOT,
                original_result_digest=pre,
                transformed_result_digest=post,
            )
            == 1
        )
        receipt = db.get_tool_effect_receipt(claim_id)
        assert receipt["transformed_result_digest"] == post
        # Idempotent for the identical pair …
        assert (
            db.record_tool_effect_result_transform(
                claim_id=claim_id,
                boot_id=_BOOT,
                original_result_digest=pre,
                transformed_result_digest=post,
            )
            == 1
        )
        # … but a second, different rewrite is refused.
        assert (
            db.record_tool_effect_result_transform(
                claim_id=claim_id,
                boot_id=_BOOT,
                original_result_digest=pre,
                transformed_result_digest=_sha("another-rewrite"),
            )
            == 0
        )
        assert db.get_tool_effect_receipt(claim_id)[
            "transformed_result_digest"
        ] == post

    def test_transform_refuses_a_mismatched_original_digest(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claim_id = self._terminal_receipt(db, result_digest=_sha("real-result"))
        assert (
            db.record_tool_effect_result_transform(
                claim_id=claim_id,
                boot_id=_BOOT,
                original_result_digest=_sha("forged-original"),
                transformed_result_digest=_sha("rewrite"),
            )
            == 0
        )

    def test_transform_refuses_nonterminal_receipts(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        claimed = db.claim_tool_effect(**_claim_kwargs())
        assert (
            db.record_tool_effect_result_transform(
                claim_id=claimed["claim_id"],
                boot_id=_BOOT,
                original_result_digest=_sha("x"),
                transformed_result_digest=_sha("y"),
            )
            == 0
        )

    def test_transform_cannot_touch_the_recorded_outcome(self, tmp_path):
        db = _db(tmp_path)
        db.activate_approval_boot(_BOOT)
        pre = _sha("outcome-anchored")
        claim_id = self._terminal_receipt(db, result_digest=pre)
        before = db.get_tool_effect_receipt(claim_id)
        db.record_tool_effect_result_transform(
            claim_id=claim_id,
            boot_id=_BOOT,
            original_result_digest=pre,
            transformed_result_digest=_sha("evidenced-rewrite"),
        )
        after = db.get_tool_effect_receipt(claim_id)
        for outcome_field in (
            "status",
            "completed_at",
            "result_digest",
            "failure_code",
            "canonical_args_digest",
            "accepted_policy_digest",
            "policy_revision",
        ):
            assert after[outcome_field] == before[outcome_field]


class TestApprovalReceiptTransformEvidence:
    """The terminal (Approval Grant) receipt gains the same evidence CAS."""

    def _terminal_approval_receipt(self, db) -> dict:
        boot = _BOOT
        request_id = f"{1:032x}"
        db.activate_approval_boot(boot)
        policy = approval.ExecutionPolicy.for_mode("turn-effect", "default")
        created_at = time.time()
        db.prepare_approval_grant(
            request_id=request_id,
            boot_id=boot,
            session_key_digest=_sha("session-key"),
            session_id=_SESSION,
            root_correlation_id="corr_" + "b" * 32,
            turn_id=policy.accepted_turn_id,
            invocation_id=_INVOCATION,
            tool_identity="terminal",
            command_digest=_sha({"command": "rm -rf /tmp/x"}),
            canonical_args_digest=_sha({"command": "rm -rf /tmp/x"}),
            accepted_policy=policy.to_dict(),
            policy_revision=4,
            effect_set=["destructive"],
            allowed_actor_id="user-effect",
            delivery_platform="telegram",
            delivery_chat_id="chat-effect",
            delivery_thread_id="thread-effect",
            origin_message_id="message-effect",
            created_at=created_at,
            expires_at=created_at + 300,
        )
        assert (
            db.resolve_approval_grant(
                request_id,
                boot_id=boot,
                session_key_digest=_sha("session-key"),
                expected_root_correlation_id="corr_" + "b" * 32,
                expected_turn_id=policy.accepted_turn_id,
                expected_command_digest=_sha({"command": "rm -rf /tmp/x"}),
                expected_origin_message_id="message-effect",
                target_state="approved",
                decision="once",
                resolution_reason="user_response",
                resolver_identity="user-effect",
                resolver_context={
                    "actor_id": "user-effect",
                    "platform": "telegram",
                    "chat_id": "chat-effect",
                    "thread_id": "thread-effect",
                    "origin_message_id": "message-effect",
                },
                now=created_at + 1,
            )
            == 1
        )
        claim_id = f"{101:032x}"
        receipt = db.claim_approval_effect(
            request_id=request_id,
            claim_id=claim_id,
            boot_id=boot,
            session_key_digest=_sha("session-key"),
            session_id=_SESSION,
            root_correlation_id="corr_" + "b" * 32,
            turn_id=policy.accepted_turn_id,
            invocation_id=_INVOCATION,
            tool_name="terminal",
            command_digest=_sha({"command": "rm -rf /tmp/x"}),
            canonical_args_digest=_sha({"command": "rm -rf /tmp/x"}),
            accepted_policy=policy.to_dict(),
            policy_revision=4,
            principal_id="user-effect",
            effect_set=["destructive"],
            expected_origin_message_id="message-effect",
            now=created_at + 2,
        )
        assert receipt is not None and receipt["status"] == "claimed"
        assert (
            db.complete_approval_effect(
                claim_id=claim_id,
                request_id=request_id,
                boot_id=boot,
                status="succeeded",
                result_digest=_sha({"returncode": 0}),
                failure_code=None,
                completed_at=created_at + 3,
            )
            == 1
        )
        return {"claim_id": claim_id, "request_id": request_id, "boot_id": boot}

    def test_terminal_receipt_transform_evidence_binds_once(self, tmp_path):
        db = _db(tmp_path)
        ids = self._terminal_approval_receipt(db)
        pre = _sha({"output": "real output"})
        post = _sha({"output": "rewritten output"})
        assert (
            db.record_approval_effect_result_transform(
                claim_id=ids["claim_id"],
                request_id=ids["request_id"],
                boot_id=ids["boot_id"],
                transform_pre_digest=pre,
                transform_post_digest=post,
            )
            == 1
        )
        receipt = db.get_approval_effect_receipt(ids["claim_id"])
        assert receipt["transform_pre_digest"] == pre
        assert receipt["transform_post_digest"] == post
        # Single-set: a different rewrite is refused, outcome untouched.
        assert (
            db.record_approval_effect_result_transform(
                claim_id=ids["claim_id"],
                request_id=ids["request_id"],
                boot_id=ids["boot_id"],
                transform_pre_digest=pre,
                transform_post_digest=_sha({"output": "second rewrite"}),
            )
            == 0
        )
        after = db.get_approval_effect_receipt(ids["claim_id"])
        assert after["status"] == "succeeded"
        assert after["transform_post_digest"] == post

    def test_terminal_receipt_transform_requires_terminal_status(self, tmp_path):
        db = _db(tmp_path)
        boot = _BOOT
        db.activate_approval_boot(boot)
        # No receipt rows at all: CAS must refuse.
        assert (
            db.record_approval_effect_result_transform(
                claim_id=f"{7:032x}",
                request_id=f"{8:032x}",
                boot_id=boot,
                transform_pre_digest=_sha("a"),
                transform_post_digest=_sha("b"),
            )
            == 0
        )
