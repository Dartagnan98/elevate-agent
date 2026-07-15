"""Exact-Beta effect-time Approval Grant claim and receipt boundaries."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time

import pytest

from elevate_state import SessionDB
from gateway.session_context import clear_session_vars, set_session_vars
from tools import approval


_BOOT = "a" * 32
_ROOT = "corr_" + "b" * 32
_SESSION = "session-effect"
_INVOCATION = "call-effect"
_TOOL = "terminal"
_COMMAND = "rm -rf /tmp/elevate-effect-test"
_ACTOR = "user-effect"
_ORIGIN = "message-effect"


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


def _request(index: int) -> str:
    return f"{index:032x}"


def _seed_approved_grant(
    db: SessionDB,
    *,
    request_id: str = _request(1),
    boot_id: str = _BOOT,
    session_id: str = _SESSION,
    invocation_id: str = _INVOCATION,
    now: float | None = None,
    activate_boot: bool = True,
) -> dict:
    created_at = time.time() if now is None else now
    if activate_boot:
        db.activate_approval_boot(boot_id)
    policy = approval.ExecutionPolicy.for_mode("turn-effect", "default")
    grant = {
        "request_id": request_id,
        "boot_id": boot_id,
        "session_key_digest": _sha("session-key"),
        "session_id": session_id,
        "root_correlation_id": _ROOT,
        "turn_id": policy.accepted_turn_id,
        "invocation_id": invocation_id,
        "tool_identity": _TOOL,
        "command_digest": _sha({"command": _COMMAND}),
        "canonical_args_digest": _sha({"command": _COMMAND}),
        "accepted_policy": policy.to_dict(),
        "policy_revision": 4,
        "effect_set": ["destructive"],
        "allowed_actor_id": _ACTOR,
        "delivery_platform": "telegram",
        "delivery_chat_id": "chat-effect",
        "delivery_thread_id": "thread-effect",
        "origin_message_id": _ORIGIN,
        "created_at": created_at,
        "expires_at": created_at + 300,
    }
    db.prepare_approval_grant(**grant)
    assert (
        db.resolve_approval_grant(
            request_id,
            boot_id=boot_id,
            session_key_digest=grant["session_key_digest"],
            expected_root_correlation_id=_ROOT,
            expected_turn_id=policy.accepted_turn_id,
            expected_command_digest=grant["command_digest"],
            expected_origin_message_id=_ORIGIN,
            target_state="approved",
            decision="once",
            resolution_reason="user_response",
            resolver_identity=_ACTOR,
            resolver_context={
                "actor_id": _ACTOR,
                "platform": "telegram",
                "chat_id": "chat-effect",
                "thread_id": "thread-effect",
                "origin_message_id": _ORIGIN,
            },
            now=created_at + 1,
        )
        == 1
    )
    return {
        "request_id": request_id,
        "claim_id": _request(100 + int(request_id, 16)),
        "boot_id": boot_id,
        "session_key_digest": grant["session_key_digest"],
        "session_id": session_id,
        "root_correlation_id": _ROOT,
        "turn_id": policy.accepted_turn_id,
        "invocation_id": invocation_id,
        "tool_name": _TOOL,
        "command_digest": grant["command_digest"],
        "canonical_args_digest": grant["canonical_args_digest"],
        "accepted_policy": policy.to_dict(),
        "policy_revision": 4,
        "principal_id": _ACTOR,
        "effect_set": ["destructive"],
        "expected_origin_message_id": _ORIGIN,
        "now": created_at + 2,
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_id", _request(99)),
        ("boot_id", "0" * 32),
        ("session_key_digest", "0" * 64),
        ("session_id", "wrong-session"),
        ("root_correlation_id", "corr_" + "0" * 32),
        ("invocation_id", "wrong-call"),
        ("tool_name", "wrong-tool"),
        ("command_digest", "1" * 64),
        ("canonical_args_digest", "2" * 64),
        ("policy_revision", 5),
        ("principal_id", "wrong-user"),
        ("effect_set", ["spawn"]),
        ("expected_origin_message_id", "wrong-message"),
    ],
)
def test_wrong_claim_identity_never_claims(
    tmp_path,
    field,
    replacement,
):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db)
    claim[field] = replacement

    assert db.claim_approval_effect(**claim) is None
    assert db.get_approval_grant(_request(1))["effect_state"] == "unclaimed"
    assert (
        db._conn.execute("SELECT COUNT(*) FROM approval_effect_receipts").fetchone()[0]
        == 0
    )


def test_wrong_turn_and_policy_pair_never_claims(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db)
    wrong_policy = approval.ExecutionPolicy.for_mode("wrong-turn", "default")
    claim["turn_id"] = "wrong-turn"
    claim["accepted_policy"] = wrong_policy.to_dict()

    assert db.claim_approval_effect(**claim) is None
    assert db.get_approval_grant(_request(1))["effect_state"] == "unclaimed"


@pytest.mark.parametrize(
    ("state", "decision"),
    [("pending", None), ("denied", "deny"), ("approved", "session")],
)
def test_nonterminal_or_non_once_approval_never_claims(
    tmp_path,
    state,
    decision,
):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db)
    db._conn.execute(
        "UPDATE approval_grants SET state = ?, decision = ? WHERE request_id = ?",
        (state, decision, claim["request_id"]),
    )
    db._conn.commit()

    assert db.claim_approval_effect(**claim) is None
    assert db.get_approval_grant(claim["request_id"])["effect_state"] == (
        "unclaimed"
    )


def test_concurrent_claimers_have_exactly_one_winner(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    base = _seed_approved_grant(db)

    def claim(index: int):
        candidate = dict(base, claim_id=_request(200 + index))
        return db.claim_approval_effect(**candidate)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (1, 2)))

    assert sum(result is not None for result in results) == 1
    receipt = next(result for result in results if result is not None)
    assert receipt["status"] == "claimed"
    assert db.get_approval_grant(_request(1))["effect_state"] == "claimed"
    assert (
        db._conn.execute("SELECT COUNT(*) FROM approval_effect_receipts").fetchone()[0]
        == 1
    )


def test_duplicate_invocation_across_requests_has_one_winner(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    first = _seed_approved_grant(db, request_id=_request(2))
    second = _seed_approved_grant(db, request_id=_request(3))
    second["claim_id"] = _request(303)

    assert db.claim_approval_effect(**first) is not None
    assert db.claim_approval_effect(**second) is None
    assert db.get_approval_grant(_request(2))["effect_state"] == "claimed"
    assert db.get_approval_grant(_request(3))["effect_state"] == "unclaimed"


def test_expired_grant_cannot_be_claimed(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db)
    claim["now"] += 500

    assert db.claim_approval_effect(**claim) is None
    assert db.get_approval_grant(_request(1))["effect_state"] == "expired"


def test_success_and_failure_receipts_are_terminal_and_idempotent(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    success = _seed_approved_grant(db, request_id=_request(4))
    success_receipt = db.claim_approval_effect(**success)
    assert success_receipt is not None
    assert (
        db.complete_approval_effect(
            claim_id=success["claim_id"],
            request_id=success["request_id"],
            boot_id=success["boot_id"],
            status="succeeded",
            result_digest=_sha({"returncode": 0}),
            failure_code=None,
            completed_at=success["now"] + 1,
        )
        == 1
    )
    assert (
        db.complete_approval_effect(
            claim_id=success["claim_id"],
            request_id=success["request_id"],
            boot_id=success["boot_id"],
            status="succeeded",
            result_digest=_sha({"returncode": 0}),
            failure_code=None,
            completed_at=success["now"] + 2,
        )
        == 0
    )
    assert db.get_approval_effect_receipt(success["claim_id"])["status"] == (
        "succeeded"
    )

    failure = _seed_approved_grant(
        db,
        request_id=_request(5),
        invocation_id="call-effect-failure",
    )
    assert db.claim_approval_effect(**failure) is not None
    assert (
        db.complete_approval_effect(
            claim_id=failure["claim_id"],
            request_id=failure["request_id"],
            boot_id=failure["boot_id"],
            status="failed",
            result_digest=_sha({"returncode": 2}),
            failure_code="command_exit_nonzero",
            completed_at=failure["now"] + 1,
        )
        == 1
    )
    receipt = db.get_approval_effect_receipt(failure["claim_id"])
    assert receipt["status"] == "failed"
    assert receipt["failure_code"] == "command_exit_nonzero"


def test_completion_chronology_and_status_coherence_fail_closed(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db, request_id=_request(6))
    assert db.claim_approval_effect(**claim) is not None
    base = {
        "claim_id": claim["claim_id"],
        "request_id": claim["request_id"],
        "boot_id": claim["boot_id"],
        "result_digest": None,
        "completed_at": claim["now"] + 1,
    }

    with pytest.raises(ValueError, match="failure code"):
        db.complete_approval_effect(
            **base,
            status="succeeded",
            failure_code="not_a_success",
        )
    with pytest.raises(ValueError, match="require a failure code"):
        db.complete_approval_effect(
            **base,
            status="failed",
            failure_code=None,
        )
    with pytest.raises(ValueError, match="cannot claim a result digest"):
        db.complete_approval_effect(
            **dict(base, result_digest=_sha("unknown")),
            status="unknown",
            failure_code="ambiguous",
        )
    with pytest.raises(ValueError, match="cannot precede"):
        db.complete_approval_effect(
            **dict(base, completed_at=claim["now"] - 1),
            status="unknown",
            failure_code="clock_regressed",
        )
    assert db.get_approval_effect_receipt(claim["claim_id"])["status"] == ("claimed")


def test_restart_terminalizes_both_crash_windows_as_unknown(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    old_boot = "d" * 32
    new_boot = "e" * 32
    # The synthetic owner is absent, so a later activation represents a
    # genuine process restart rather than two live processes stealing a lease.
    db.activate_approval_boot(
        old_boot,
        process_id=999_999,
        process_start_id="old-process",
        process_create_time=1.0,
    )
    claim = _seed_approved_grant(
        db,
        request_id=_request(7),
        boot_id=old_boot,
        invocation_id="call-crash-window",
        activate_boot=False,
    )
    assert db.claim_approval_effect(**claim) is not None

    # A durable claim is intentionally indistinguishable between a crash just
    # before invocation and one just after invocation but before completion.
    assert db.activate_approval_boot(new_boot) is True
    terminal = db.mark_prior_boot_approval_effects_unknown(
        new_boot,
        now=claim["now"] + 5,
    )

    assert len(terminal) == 1
    assert terminal[0]["status"] == "unknown"
    assert terminal[0]["failure_code"] == "prior_boot_crash_window"
    assert db.get_approval_grant(claim["request_id"])["effect_state"] == ("unknown")
    assert db.claim_approval_effect(**claim) is None


def test_restart_cleanup_rejects_backward_completion_time(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    old_boot = "f" * 32
    new_boot = "1" * 32
    db.activate_approval_boot(
        old_boot,
        process_id=999_998,
        process_start_id="old-process",
        process_create_time=1.0,
    )
    claim = _seed_approved_grant(
        db,
        request_id=_request(8),
        boot_id=old_boot,
        invocation_id="call-clock-window",
        activate_boot=False,
    )
    assert db.claim_approval_effect(**claim) is not None
    assert db.activate_approval_boot(new_boot) is True

    with pytest.raises(ValueError, match="cannot precede"):
        db.mark_prior_boot_approval_effects_unknown(
            new_boot,
            now=claim["now"] - 1,
        )
    assert db.get_approval_effect_receipt(claim["claim_id"])["status"] == ("claimed")


def test_claim_write_failure_leaves_no_authorization(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db, request_id=_request(9))

    def fail_write(_fn):
        raise OSError("disk unavailable")

    monkeypatch.setattr(db, "_execute_write", fail_write)
    with pytest.raises(OSError, match="disk unavailable"):
        db.claim_approval_effect(**claim)
    assert db.get_approval_grant(claim["request_id"])["effect_state"] == ("unclaimed")


def test_receipt_contains_no_raw_command_or_arguments(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    claim = _seed_approved_grant(db, request_id=_request(10))
    receipt = db.claim_approval_effect(**claim)

    assert receipt is not None
    serialized = json.dumps(receipt, sort_keys=True)
    assert _COMMAND not in serialized
    assert "command" not in receipt
    assert receipt["canonical_args_digest"] == _sha({"command": _COMMAND})


class _CapturingClaimStore:
    def __init__(self):
        self.calls = []

    def claim_approval_effect(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "claimed"}


def _runtime_claim_entry(store, policy):
    context = approval.ApprovalEffectContext(
        session_id=_SESSION,
        invocation_id=_INVOCATION,
        tool_name=_TOOL,
        canonical_args_digest=approval._approval_sha256({"command": _COMMAND}),
        accepted_policy=policy,
        policy_revision=4,
        declared_effects={"destructive"},
    )
    entry = approval._ApprovalEntry(
        {"command": _COMMAND, "correlation_id": _ROOT},
        grant_store=store,
        effect_context=context,
        grant_context={
            "boot_id": _BOOT,
            "session_key_digest": _sha("session-key"),
            "root_correlation_id": _ROOT,
            "turn_id": policy.accepted_turn_id,
            "command_digest": approval._approval_sha256({"command": _COMMAND}),
            "principal_id": _ACTOR,
            "origin_message_id": _ORIGIN,
        },
    )
    return entry, context


def test_runtime_claim_revalidates_current_policy_principal_root_and_args(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    store = _CapturingClaimStore()
    policy = approval.ExecutionPolicy.for_mode("turn-effect", "default")
    entry, context = _runtime_claim_entry(store, policy)
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="chat-effect",
        thread_id="thread-effect",
        user_id=_ACTOR,
        session_key="session-key",
        message_id=_ORIGIN,
        correlation_id=_ROOT,
    )
    policy_token = approval.set_current_execution_policy(
        policy,
        policy_revision=4,
    )
    try:
        claim = approval.claim_approved_effect(
            entry,
            context,
            {"command": _COMMAND},
        )
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)

    assert isinstance(claim, approval.ApprovalEffectClaim)
    assert len(store.calls) == 1
    persisted = store.calls[0]
    assert persisted["session_id"] == _SESSION
    assert persisted["invocation_id"] == _INVOCATION
    assert persisted["principal_id"] == _ACTOR
    assert persisted["root_correlation_id"] == _ROOT
    assert persisted["canonical_args_digest"] == context.canonical_args_digest
    assert persisted["policy_revision"] == 4
    assert persisted["effect_set"] == ["destructive"]


@pytest.mark.parametrize(
    "mismatch",
    ["policy_revision", "principal", "root", "arguments", "context"],
)
def test_runtime_claim_mismatch_never_reaches_state_store(
    monkeypatch,
    mismatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    store = _CapturingClaimStore()
    policy = approval.ExecutionPolicy.for_mode("turn-effect", "default")
    entry, context = _runtime_claim_entry(store, policy)
    principal = "wrong-user" if mismatch == "principal" else _ACTOR
    root = "corr_" + "0" * 32 if mismatch == "root" else _ROOT
    args = (
        {"command": "different"} if mismatch == "arguments" else {"command": _COMMAND}
    )
    supplied_context = (
        approval.ApprovalEffectContext(
            session_id=_SESSION,
            invocation_id="different-call",
            tool_name=_TOOL,
            canonical_args_digest=context.canonical_args_digest,
            accepted_policy=policy,
            policy_revision=4,
            declared_effects={"destructive"},
        )
        if mismatch == "context"
        else context
    )
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="chat-effect",
        thread_id="thread-effect",
        user_id=principal,
        session_key="session-key",
        message_id=_ORIGIN,
        correlation_id=root,
    )
    policy_token = approval.set_current_execution_policy(
        policy,
        policy_revision=5 if mismatch == "policy_revision" else 4,
    )
    try:
        claim = approval.claim_approved_effect(
            entry,
            supplied_context,
            args,
        )
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)

    assert claim is None
    assert store.calls == []
