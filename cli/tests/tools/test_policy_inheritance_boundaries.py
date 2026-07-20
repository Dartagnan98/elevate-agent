"""Boundary proofs for accepted-turn policy inheritance (package A4).

Durable-trail, retry, resume/cold-recovery, and meta/update coverage over
REAL stores (SessionDB) and the real registry/broker chokepoint:

* a child claim durably references the parent receipt — same accepted-turn
  identity, same policy revision, the parent policy's canonical digest —
  and the sessions table completes the chain back to the parent session;
* a retried tool call re-binds the ORIGINAL frozen policy: a widened
  ambient policy between preparation and start can neither start a denied
  call nor be recorded on a claim, and a re-dispatched invocation identity
  can never re-invoke;
* resume/cold recovery: prior-boot in-flight claims terminalize as
  ``unknown`` (never failed/succeeded), stay permanently burned, and a
  dead boot cannot terminalize anything after the new lease activates;
* meta/update: mid-turn CAS narrowing is revision-checked, widening raises
  with pre-state preserved, and rebinding from the durable receipt (the
  resume path) feeds children the narrowed policy at the new revision.
"""

from __future__ import annotations

import hashlib
import json
import time

import pytest

import tools.effect_broker as effect_broker
from elevate_state import SessionDB
from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    InheritedPolicyBinding,
    PolicyWideningError,
    capture_inherited_execution_policy,
    inherited_execution_policy_scope,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import ToolCallContext, ToolRegistry

PARENT_SESSION = "parent-session-a4"
CHILD_SESSION = "child-session-a4"
PARENT_TURN = "turn-a4"


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": f"A {name} tool",
        "parameters": {"type": "object", "properties": {}},
    }


def _policy(mode: str = "draft_only", turn: str = PARENT_TURN) -> ExecutionPolicy:
    return ExecutionPolicy.for_mode(turn, ExecutionPolicyMode.parse(mode))


def _policy_digest(policy: ExecutionPolicy) -> str:
    canonical = json.dumps(
        policy.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _child_context(
    policy: ExecutionPolicy,
    revision: int,
    invocation_id: str = "call-child-a4",
) -> ToolCallContext:
    return ToolCallContext(
        session_id=CHILD_SESSION,
        invocation_id=invocation_id,
        accepted_turn_id=policy.accepted_turn_id,
        policy_revision=revision,
    )


@pytest.fixture
def broker_db(tmp_path, monkeypatch) -> SessionDB:
    db = SessionDB(tmp_path / "state.db")
    monkeypatch.setattr(effect_broker, "_store_override", db)
    monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
    return db


def _writer_registry(calls):
    registry = ToolRegistry()
    registry.register(
        "draft_writer",
        "core",
        _schema("draft_writer"),
        lambda args, **kwargs: calls.append(dict(args)) or "wrote-draft",
        effects={"write_local:draft"},
    )
    return registry


def _prepare_parent_receipt(db: SessionDB, policy: ExecutionPolicy) -> dict:
    db._insert_session_row(PARENT_SESSION, "gateway")
    db._insert_session_row(
        CHILD_SESSION, "delegate", parent_session_id=PARENT_SESSION
    )
    return db.prepare_prompt_receipt(
        PARENT_SESSION,
        "please do the thing",
        assistant_message_id="assistant-a4",
        client_message_id=policy.accepted_turn_id,
        payload={"text": "please do the thing"},
        accepted_policy=policy,
    )


class TestChildClaimReferencesParentReceipt:
    def test_child_claim_carries_parent_turn_revision_and_policy_digest(
        self, broker_db, monkeypatch
    ):
        """The durable inheritance chain: child effect claim -> parent
        accepted turn + revision + policy digest; child session row ->
        parent session; parent session + turn -> the prompt receipt."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        parent_policy = _policy("draft_only")
        receipt = _prepare_parent_receipt(broker_db, parent_policy)
        assert receipt["policy_revision"] == 0

        calls = []
        registry = _writer_registry(calls)

        # Dispatch-time capture on the parent's thread, bind on the child's.
        token = set_current_execution_policy(parent_policy, policy_revision=0)
        try:
            binding = capture_inherited_execution_policy(
                parent_session_id=PARENT_SESSION
            )
        finally:
            reset_current_execution_policy(token)

        with inherited_execution_policy_scope(binding):
            # execution_policy defaults to the CURRENT bound policy — the
            # scope integration is exactly what a child dispatch exercises.
            outcome = registry.execute_shadow(
                "draft_writer",
                {"value": 1},
                context=_child_context(binding.policy, binding.policy_revision),
            )

        assert outcome.started is True
        assert calls == [{"value": 1}]
        claim = broker_db.get_tool_effect_receipt_for_invocation(
            CHILD_SESSION, "call-child-a4"
        )
        assert claim is not None
        assert claim["status"] == "succeeded"
        assert claim["session_id"] == CHILD_SESSION
        assert claim["turn_id"] == PARENT_TURN
        assert claim["policy_revision"] == 0
        assert claim["accepted_policy_digest"] == _policy_digest(parent_policy)

        # Chain closure: child session -> parent session -> prompt receipt.
        child_row = broker_db.get_session(CHILD_SESSION)
        assert child_row["parent_session_id"] == PARENT_SESSION
        parent_receipt = broker_db.get_prompt_receipt(
            PARENT_SESSION, claim["turn_id"]
        )
        assert parent_receipt is not None
        assert (
            ExecutionPolicy.from_dict(parent_receipt["effective_policy"])
            == parent_policy
        )

    def test_child_cannot_claim_beyond_its_inherited_policy(
        self, broker_db, monkeypatch
    ):
        """A read-only inheritance fails a write claim closed at the store:
        the child's claim row can never record more capability than the
        derived policy grants."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        parent_policy = _policy("read_only")
        _prepare_parent_receipt(broker_db, parent_policy)

        calls = []
        registry = _writer_registry(calls)
        token = set_current_execution_policy(parent_policy, policy_revision=0)
        try:
            binding = capture_inherited_execution_policy(
                parent_session_id=PARENT_SESSION
            )
        finally:
            reset_current_execution_policy(token)

        with inherited_execution_policy_scope(binding):
            outcome = registry.execute_shadow(
                "draft_writer",
                {"value": 2},
                context=_child_context(
                    binding.policy, binding.policy_revision, "call-denied"
                ),
            )

        assert outcome.started is False
        assert json.loads(outcome.result)["shadow_status"] == (
            "effect_policy_block"
        )
        assert calls == []
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                CHILD_SESSION, "call-denied"
            )
            is None
        )


class TestRetryRebindsOriginalPolicy:
    def test_widened_ambient_cannot_start_a_frozen_denied_call(
        self, broker_db, monkeypatch
    ):
        """Retry boundary: a call prepared under the ORIGINAL read-only
        policy stays denied at start even when the ambient contextvar has
        since been widened — no re-resolution, no claim, no handler."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)
        original = _policy("read_only")

        prepared = registry.prepare_shadow(
            "draft_writer",
            {"value": 3},
            context=_child_context(original, 0, "call-frozen"),
            execution_policy=original,
        )
        assert prepared.authorization.allowed is False

        widened = _policy("draft_only")
        token = set_current_execution_policy(widened, policy_revision=1)
        try:
            outcome = registry.execute_prepared_shadow(prepared)
        finally:
            reset_current_execution_policy(token)

        assert outcome.started is False
        assert json.loads(outcome.result)["shadow_status"] == (
            "effect_policy_block"
        )
        assert calls == []
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                CHILD_SESSION, "call-frozen"
            )
            is None
        )

    def test_allowed_frozen_call_records_the_original_policy_not_ambient(
        self, broker_db, monkeypatch
    ):
        """The claim row is written from the FROZEN policy: a wider ambient
        policy bound at start time never reaches the durable trail."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)
        original = _policy("draft_only")

        prepared = registry.prepare_shadow(
            "draft_writer",
            {"value": 4},
            context=_child_context(original, 2, "call-original"),
            execution_policy=original,
        )
        wider = _policy("default")
        token = set_current_execution_policy(wider, policy_revision=9)
        try:
            outcome = registry.execute_prepared_shadow(prepared)
        finally:
            reset_current_execution_policy(token)

        assert outcome.started is True
        claim = broker_db.get_tool_effect_receipt_for_invocation(
            CHILD_SESSION, "call-original"
        )
        assert claim["policy_revision"] == 2
        assert claim["accepted_policy_digest"] == _policy_digest(original)
        assert claim["accepted_policy_digest"] != _policy_digest(wider)

    def test_adapter_blocks_a_mid_dispatch_policy_swap_as_stale(
        self, broker_db, monkeypatch
    ):
        """A policy rebind between the exact-Beta preflight and the dispatch
        is refused as a stale context — the frozen preparation is only valid
        under the exact policy binding that produced it."""
        from model_tools import (
            _dispatch_model_registry_call,
            _prepare_exact_beta_registry_call,
        )
        from tools.registry import registry as global_registry

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        tool_name = "a4_swap_draft_writer"
        calls = []
        global_registry.register(
            tool_name,
            "core",
            _schema(tool_name),
            lambda args, **kwargs: calls.append(dict(args)) or "wrote",
            effects={"write_local:draft"},
        )
        try:
            original = _policy("draft_only")
            token = set_current_execution_policy(original, policy_revision=0)
            try:
                prepared, block = _prepare_exact_beta_registry_call(
                    tool_name,
                    {"value": 5},
                    handler_kwargs={"task_id": None, "user_task": None},
                    session_id=CHILD_SESSION,
                    tool_call_id="call-swap",
                )
                assert block is None and prepared is not None
            finally:
                reset_current_execution_policy(token)

            # Mid-turn update: a NEW policy object (even an equal one would
            # do — identity is the contract) bound before the dispatch.
            swapped = _policy("draft_only")
            token = set_current_execution_policy(swapped, policy_revision=0)
            try:
                result, blocked, receipt = _dispatch_model_registry_call(
                    tool_name,
                    {"value": 5},
                    handler_kwargs={"task_id": None, "user_task": None},
                    session_id=CHILD_SESSION,
                    tool_call_id="call-swap",
                    prepared_call=prepared,
                )
            finally:
                reset_current_execution_policy(token)
        finally:
            global_registry.deregister(tool_name)

        assert blocked is True
        assert json.loads(result)["shadow_status"] == "effect_context_block"
        assert calls == []
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                CHILD_SESSION, "call-swap"
            )
            is None
        )

    def test_retried_invocation_identity_can_never_reinvoke(
        self, broker_db, monkeypatch
    ):
        """Post-claim no-retry: the same durable invocation identity refuses
        a second start even under the identical original policy binding."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)
        policy = _policy("draft_only")

        first = registry.execute_shadow(
            "draft_writer",
            {"value": 6},
            context=_child_context(policy, 0, "call-retry"),
            execution_policy=policy,
        )
        assert first.started is True and len(calls) == 1

        retry = registry.execute_shadow(
            "draft_writer",
            {"value": 6},
            context=_child_context(policy, 0, "call-retry"),
            execution_policy=policy,
        )
        assert retry.started is False
        assert len(calls) == 1
        assert json.loads(retry.result)["shadow_status"] == (
            effect_broker.CLAIM_STATUS_CONFLICT
        )


class TestResumeColdRecovery:
    def _burn_prior_boot_claim(self, db: SessionDB, policy: ExecutionPolicy):
        old_boot = "b" * 32
        db.activate_approval_boot(
            old_boot,
            process_id=999_999,
            process_create_time=time.time() - 3600,
        )
        claim = db.claim_tool_effect(
            claim_id="c" * 32,
            boot_id=old_boot,
            session_id=CHILD_SESSION,
            invocation_id="call-interrupted",
            turn_id=policy.accepted_turn_id,
            tool_name="draft_writer",
            entry_id=1,
            registry_generation=1,
            canonical_args_digest="0" * 64,
            handler_kwargs_digest=None,
            accepted_policy=policy.to_dict(),
            policy_revision=0,
            effect_set=["write_local:draft"],
        )
        assert claim is not None
        return old_boot

    def test_resumed_session_rebinds_durable_state_and_interrupted_stays_burned(
        self, broker_db, monkeypatch
    ):
        """Resume: the prior boot's in-flight claim terminalizes ``unknown``
        (persists interrupted) and its invocation identity can NEVER
        re-execute, while fresh invocations under the rebound durable
        policy proceed normally."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = _policy("draft_only")
        self._burn_prior_boot_claim(broker_db, policy)

        calls = []
        registry = _writer_registry(calls)

        # The resumed process re-binds from durable state (the receipt's
        # effective policy at its stored revision) — simulated here by the
        # inherited binding — and dispatches a FRESH invocation.
        with inherited_execution_policy_scope(
            # what a resume rebind from durable state produces
            InheritedPolicyBinding(policy, 0, PARENT_SESSION)
        ):
            fresh = registry.execute_shadow(
                "draft_writer",
                {"value": 7},
                context=_child_context(policy, 0, "call-fresh-after-resume"),
            )
        assert fresh.started is True and len(calls) == 1

        # The interrupted claim persisted as unknown — not failed, not
        # succeeded — and is permanently burned.
        crashed = broker_db.get_tool_effect_receipt("c" * 32)
        assert crashed["status"] == "unknown"
        assert crashed["failure_code"] == "prior_boot_crash_window"

        replay = registry.execute_shadow(
            "draft_writer",
            {"value": 7},
            context=_child_context(policy, 0, "call-interrupted"),
            execution_policy=policy,
        )
        assert replay.started is False
        assert len(calls) == 1
        assert json.loads(replay.result)["shadow_status"] == (
            effect_broker.CLAIM_STATUS_CONFLICT
        )

    def test_dead_boot_cannot_terminalize_after_the_new_lease(
        self, broker_db, monkeypatch
    ):
        """A zombie worker from the crashed boot cannot rewrite the durable
        truth: its completion CAS misses once the new lease is active."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = _policy("draft_only")
        old_boot = self._burn_prior_boot_claim(broker_db, policy)

        calls = []
        registry = _writer_registry(calls)
        # First broker use activates the new lease + runs the cleanup.
        registry.execute_shadow(
            "draft_writer",
            {"value": 8},
            context=_child_context(policy, 0, "call-lease"),
            execution_policy=policy,
        )
        # The zombie tries to claim success for the interrupted invocation.
        assert (
            broker_db.complete_tool_effect(
                claim_id="c" * 32,
                boot_id=old_boot,
                status="succeeded",
                result_digest="0" * 64,
                failure_code=None,
            )
            == 0
        )
        assert broker_db.get_tool_effect_receipt("c" * 32)["status"] == "unknown"


class TestMetaUpdateBoundary:
    def test_mid_turn_widening_raises_and_preserves_pre_state(self, broker_db):
        parent_policy = _policy("draft_only")
        _prepare_parent_receipt(broker_db, parent_policy)

        narrowed = parent_policy.narrow(
            {"read"}, mode=ExecutionPolicyMode.READ_ONLY
        )
        updated = broker_db.narrow_prompt_receipt_policy(
            PARENT_SESSION,
            PARENT_TURN,
            expected_revision=0,
            narrowed_policy=narrowed,
        )
        assert updated["policy_revision"] == 1
        assert (
            ExecutionPolicy.from_dict(updated["effective_policy"]) == narrowed
        )

        # Widening back to draft-only exceeds the CURRENT effective ceiling.
        with pytest.raises((ValueError, PolicyWideningError)):
            broker_db.narrow_prompt_receipt_policy(
                PARENT_SESSION,
                PARENT_TURN,
                expected_revision=1,
                narrowed_policy=parent_policy,
            )
        preserved = broker_db.get_prompt_receipt(PARENT_SESSION, PARENT_TURN)
        assert preserved["policy_revision"] == 1
        assert (
            ExecutionPolicy.from_dict(preserved["effective_policy"]) == narrowed
        )
        # The accepted policy is immutable throughout.
        assert (
            ExecutionPolicy.from_dict(preserved["accepted_policy"])
            == parent_policy
        )

    def test_stale_revision_cas_never_mutates(self, broker_db):
        parent_policy = _policy("draft_only")
        _prepare_parent_receipt(broker_db, parent_policy)
        narrowed = parent_policy.narrow(
            {"read"}, mode=ExecutionPolicyMode.READ_ONLY
        )
        assert (
            broker_db.narrow_prompt_receipt_policy(
                PARENT_SESSION,
                PARENT_TURN,
                expected_revision=5,  # stale
                narrowed_policy=narrowed,
            )
            is None
        )
        preserved = broker_db.get_prompt_receipt(PARENT_SESSION, PARENT_TURN)
        assert preserved["policy_revision"] == 0
        assert (
            ExecutionPolicy.from_dict(preserved["effective_policy"])
            == parent_policy
        )

    def test_rebound_narrowed_policy_feeds_children_at_the_new_revision(
        self, broker_db, monkeypatch
    ):
        """Resume-after-narrow: rebinding from the durable receipt (the
        f26127b88 discipline, generalized) yields children that claim at the
        NEW revision under the narrowed policy — and a write under the
        narrowed inheritance fails closed with no claim row."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        parent_policy = _policy("draft_only")
        _prepare_parent_receipt(broker_db, parent_policy)
        narrowed = parent_policy.narrow(
            {"read"}, mode=ExecutionPolicyMode.READ_ONLY
        )
        updated = broker_db.narrow_prompt_receipt_policy(
            PARENT_SESSION,
            PARENT_TURN,
            expected_revision=0,
            narrowed_policy=narrowed,
        )

        rebound = ExecutionPolicy.from_dict(updated["effective_policy"])
        token = set_current_execution_policy(
            rebound, policy_revision=updated["policy_revision"]
        )
        try:
            binding = capture_inherited_execution_policy(
                parent_session_id=PARENT_SESSION
            )
        finally:
            reset_current_execution_policy(token)
        assert binding.policy == narrowed
        assert binding.policy_revision == 1

        calls = []
        registry = _writer_registry(calls)
        with inherited_execution_policy_scope(binding):
            outcome = registry.execute_shadow(
                "draft_writer",
                {"value": 9},
                context=_child_context(
                    binding.policy, binding.policy_revision, "call-narrowed"
                ),
            )
        assert outcome.started is False
        assert json.loads(outcome.result)["shadow_status"] == (
            "effect_policy_block"
        )
        assert calls == []
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                CHILD_SESSION, "call-narrowed"
            )
            is None
        )

    def test_stale_binding_after_narrow_still_claims_at_its_own_revision(
        self, broker_db, monkeypatch
    ):
        """Frozen-at-dispatch semantics, durably evidenced: a child bound
        BEFORE a mid-turn narrow claims at ITS captured revision and policy
        digest, so the trail shows exactly which state the child ran under —
        it can never masquerade as the newer revision."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        parent_policy = _policy("draft_only")
        _prepare_parent_receipt(broker_db, parent_policy)

        token = set_current_execution_policy(parent_policy, policy_revision=0)
        try:
            stale_binding = capture_inherited_execution_policy(
                parent_session_id=PARENT_SESSION
            )
        finally:
            reset_current_execution_policy(token)

        narrowed = parent_policy.narrow(
            {"read"}, mode=ExecutionPolicyMode.READ_ONLY
        )
        broker_db.narrow_prompt_receipt_policy(
            PARENT_SESSION,
            PARENT_TURN,
            expected_revision=0,
            narrowed_policy=narrowed,
        )

        calls = []
        registry = _writer_registry(calls)
        with inherited_execution_policy_scope(stale_binding):
            outcome = registry.execute_shadow(
                "draft_writer",
                {"value": 10},
                context=_child_context(
                    stale_binding.policy,
                    stale_binding.policy_revision,
                    "call-stale-binding",
                ),
            )
        assert outcome.started is True
        claim = broker_db.get_tool_effect_receipt_for_invocation(
            CHILD_SESSION, "call-stale-binding"
        )
        assert claim["policy_revision"] == 0
        assert claim["accepted_policy_digest"] == _policy_digest(parent_policy)
