"""Atomic registry shadow execution bound to durable effect claims/receipts.

Integration proofs that the exact-Beta broker generalization holds at the
one physical chokepoint every lane traverses (``_start_prepared_shadow``):
one-winner claims, terminal receipts, receipt-loss success suppression,
crash-window terminalization, interruption handling, adapter threading, and
strict Stable byte parity.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import tools.effect_broker as effect_broker
from elevate_state import SessionDB
from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import ToolCallContext, ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": f"A {name} tool",
        "parameters": {"type": "object", "properties": {}},
    }


def _policy(
    mode: ExecutionPolicyMode = ExecutionPolicyMode.DRAFT_ONLY,
) -> ExecutionPolicy:
    return ExecutionPolicy.for_mode("turn-claims", mode)


def _context(invocation_id: str = "call-claims") -> ToolCallContext:
    return ToolCallContext(
        session_id="session-claims",
        invocation_id=invocation_id,
        accepted_turn_id="turn-claims",
        policy_revision=1,
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


class TestBetaClaimBoundExecution:
    def test_allowed_write_runs_once_with_a_succeeded_receipt(
        self, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)

        outcome = registry.execute_shadow(
            "draft_writer",
            {"value": 7},
            context=_context(),
            execution_policy=_policy(),
        )

        assert outcome.started is True
        assert outcome.result == "wrote-draft"
        assert calls == [{"value": 7}]
        ref = outcome.effect_receipt
        assert ref is not None and ref.final_status == "succeeded"
        receipt = broker_db.get_tool_effect_receipt(ref.claim_id)
        assert receipt["status"] == "succeeded"
        assert receipt["result_digest"] == effect_broker.model_result_digest(
            "wrote-draft"
        )
        assert receipt["effect_set"] == ["write_local:draft"]
        assert receipt["session_id"] == "session-claims"
        assert receipt["invocation_id"] == "call-claims"

    def test_duplicate_invocation_identity_cannot_reinvoke(
        self, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)

        first = registry.execute_shadow(
            "draft_writer",
            {"value": 1},
            context=_context(),
            execution_policy=_policy(),
        )
        assert first.started is True and len(calls) == 1

        replay = registry.execute_shadow(
            "draft_writer",
            {"value": 1},
            context=_context(),
            execution_policy=_policy(),
        )
        assert replay.started is False
        assert len(calls) == 1  # the handler never ran again
        payload = json.loads(replay.result)
        assert payload["shadow_status"] == effect_broker.CLAIM_STATUS_CONFLICT

    def test_read_only_calls_never_claim(self, broker_db, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        registry = ToolRegistry()
        registry.register(
            "reader",
            "core",
            _schema("reader"),
            lambda args, **kwargs: "read-result",
            effects={"read:deals"},
        )
        outcome = registry.execute_shadow(
            "reader",
            {"deal": "1"},
            context=_context("call-read"),
            execution_policy=_policy(ExecutionPolicyMode.READ_ONLY),
        )
        assert outcome.started is True
        assert outcome.effect_receipt is None
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                "session-claims", "call-read"
            )
            is None
        )

    def test_handler_exception_records_a_failed_receipt(
        self, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        registry = ToolRegistry()

        def exploding(args, **kwargs):
            raise ValueError("boom")

        registry.register(
            "exploding_writer",
            "core",
            _schema("exploding_writer"),
            exploding,
            effects={"write_local:draft"},
        )
        outcome = registry.execute_shadow(
            "exploding_writer",
            {},
            context=_context("call-explode"),
            execution_policy=_policy(),
        )
        assert outcome.started is True
        assert outcome.execution_error == "handler_exception:ValueError"
        ref = outcome.effect_receipt
        assert ref is not None and ref.final_status == "failed"
        receipt = broker_db.get_tool_effect_receipt(ref.claim_id)
        assert receipt["status"] == "failed"
        assert receipt["failure_code"] == "handler_exception"
        # The failed receipt still anchors the model-visible error payload.
        assert receipt["result_digest"] == effect_broker.model_result_digest(
            outcome.result
        )

    def test_receipt_loss_suppresses_success(self, broker_db, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []
        registry = _writer_registry(calls)

        real_finish = effect_broker.finish_effect_claim

        def losing_finish(claim, *, status, result_identity=None, failure_code=None):
            if status == "succeeded":
                # Simulate the terminal receipt write failing durably.
                broken = dataclasses.replace(claim, store=_NoCompleteStore())
                return real_finish(
                    broken,
                    status=status,
                    result_identity=result_identity,
                    failure_code=failure_code,
                )
            return real_finish(
                claim,
                status=status,
                result_identity=result_identity,
                failure_code=failure_code,
            )

        monkeypatch.setattr(effect_broker, "finish_effect_claim", losing_finish)
        outcome = registry.execute_shadow(
            "draft_writer",
            {"value": 3},
            context=_context("call-receipt-loss"),
            execution_policy=_policy(),
        )
        # The handler DID run (physical truth) …
        assert outcome.started is True
        assert calls == [{"value": 3}]
        # … but its success is suppressed behind the typed unknown payload.
        payload = json.loads(outcome.result)
        assert payload["shadow_status"] == effect_broker.RECEIPT_STATUS_UNAVAILABLE
        assert outcome.execution_error == "effect_receipt_unavailable"
        ref = outcome.effect_receipt
        assert ref is not None and ref.final_status == "unknown"
        # The receipt ref anchors the REPLACED payload, so the guard lets the
        # typed error through and nothing else.
        assert effect_broker.model_result_digest(outcome.result) in (
            ref.expected_result_digests
        )

    def test_store_unavailable_fails_closed_before_the_handler(
        self, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(effect_broker, "_store_override", None)
        calls = []
        registry = _writer_registry(calls)
        outcome = registry.execute_shadow(
            "draft_writer",
            {"value": 9},
            context=_context("call-no-store"),
            execution_policy=_policy(),
        )
        assert outcome.started is False
        assert calls == []
        payload = json.loads(outcome.result)
        assert payload["shadow_status"] == effect_broker.CLAIM_STATUS_UNAVAILABLE

    def test_interruption_terminalizes_the_claim_unknown(
        self, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        registry = ToolRegistry()

        def interrupted(args, **kwargs):
            raise KeyboardInterrupt()

        registry.register(
            "interrupted_writer",
            "core",
            _schema("interrupted_writer"),
            interrupted,
            effects={"write_local:draft"},
        )
        with pytest.raises(KeyboardInterrupt):
            registry.execute_shadow(
                "interrupted_writer",
                {},
                context=_context("call-interrupt"),
                execution_policy=_policy(),
            )
        receipt = broker_db.get_tool_effect_receipt_for_invocation(
            "session-claims", "call-interrupt"
        )
        assert receipt is not None
        assert receipt["status"] == "unknown"
        assert receipt["failure_code"] == "execution_interrupted"

    def test_abandoned_async_timeout_terminalizes_unknown(
        self, broker_db, monkeypatch
    ):
        """An async beyond-read handler abandoned past the ``_run_async``
        timeout may still be applying its effect.  The receipt terminalizes
        ``unknown`` (never ``failed``) and the model sees the typed
        do-not-retry payload instead of a plain retryable error."""
        import asyncio

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setenv("ELEVATE_ASYNC_TOOL_TIMEOUT_S", "0.2")
        registry = ToolRegistry()

        async def slow_writer(args, **kwargs):
            await asyncio.sleep(3)
            return "late-write"

        registry.register(
            "slow_async_writer",
            "core",
            _schema("slow_async_writer"),
            slow_writer,
            is_async=True,
            effects={"write_local:draft"},
        )

        async def driver():
            # Synchronous registry call from within a running loop drives
            # _run_async's abandon-on-timeout worker branch.
            return registry.execute_shadow(
                "slow_async_writer",
                {"value": 1},
                context=_context("call-abandoned"),
                execution_policy=_policy(),
            )

        outcome = asyncio.run(driver())

        assert outcome.started is True
        payload = json.loads(outcome.result)
        assert payload["shadow_status"] == "effect_outcome_unknown"
        ref = outcome.effect_receipt
        assert ref is not None and ref.final_status == "unknown"
        receipt = broker_db.get_tool_effect_receipt(ref.claim_id)
        assert receipt["status"] == "unknown"
        assert receipt["failure_code"] == "execution_timeout_abandoned"
        # The abandoned invocation identity stays burned.
        replay_refused = broker_db.claim_tool_effect(
            claim_id="a" * 32,
            boot_id=receipt["boot_id"],
            session_id="session-claims",
            invocation_id="call-abandoned",
            turn_id="turn-claims",
            tool_name="slow_async_writer",
            entry_id=1,
            registry_generation=1,
            canonical_args_digest="0" * 64,
            handler_kwargs_digest=None,
            accepted_policy=_policy().to_dict(),
            policy_revision=1,
            effect_set=["write_local:draft"],
        )
        assert replay_refused is None

    def test_prior_boot_claims_terminalize_on_first_broker_use(
        self, tmp_path, monkeypatch
    ):
        import time as _time

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        db = SessionDB(tmp_path / "state.db")
        old_boot = "b" * 32
        db.activate_approval_boot(
            old_boot,
            process_id=999_999,
            process_create_time=_time.time() - 3600,
        )
        policy = _policy()
        stale = db.claim_tool_effect(
            claim_id="c" * 32,
            boot_id=old_boot,
            session_id="session-claims",
            invocation_id="call-crashed",
            turn_id=policy.accepted_turn_id,
            tool_name="draft_writer",
            entry_id=1,
            registry_generation=1,
            canonical_args_digest="0" * 64,
            handler_kwargs_digest=None,
            accepted_policy=policy.to_dict(),
            policy_revision=1,
            effect_set=["write_local:draft"],
        )
        assert stale is not None

        monkeypatch.setattr(effect_broker, "_store_override", db)
        monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
        calls = []
        registry = _writer_registry(calls)
        outcome = registry.execute_shadow(
            "draft_writer",
            {"value": 5},
            context=_context("call-after-crash"),
            execution_policy=policy,
        )
        assert outcome.started is True

        crashed = db.get_tool_effect_receipt("c" * 32)
        assert crashed["status"] == "unknown"
        assert crashed["failure_code"] == "prior_boot_crash_window"
        # The crashed invocation identity stays burned across the restart.
        replay = registry.execute_shadow(
            "draft_writer",
            {"value": 5},
            context=_context("call-crashed"),
            execution_policy=policy,
        )
        assert replay.started is False
        assert json.loads(replay.result)["shadow_status"] == (
            effect_broker.CLAIM_STATUS_CONFLICT
        )


class _NoCompleteStore:
    def complete_tool_effect(self, **_kwargs):
        raise RuntimeError("simulated durable receipt outage")


class TestStableByteParity:
    def test_outside_beta_no_claim_no_receipt_no_behavior_change(
        self, broker_db, monkeypatch
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        calls = []
        registry = _writer_registry(calls)
        outcome = registry.execute_shadow(
            "draft_writer",
            {"value": 11},
            context=_context("call-stable"),
            execution_policy=_policy(ExecutionPolicyMode.READ_ONLY),
        )
        # Observational outside Beta: even a policy-denied write starts.
        assert outcome.started is True
        assert outcome.result == "wrote-draft"
        assert outcome.effect_receipt is None
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                "session-claims", "call-stable"
            )
            is None
        )


class TestAdapterThreading:
    def test_adapter_dispatch_produces_a_bound_receipt(
        self, broker_db, monkeypatch
    ):
        """The full agent-owned adapter path (preflight -> prepared atomic
        execution -> integrity guard) carries the claim/receipt trail."""
        from model_tools import dispatch_agent_owned_registry_tool
        from tools.registry import registry as global_registry

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        tool_name = "a3_adapter_draft_writer"
        global_registry.register(
            tool_name,
            "core",
            _schema(tool_name),
            lambda args, **kwargs: json.dumps({"ok": True, "args": args}),
            effects={"write_local:draft"},
        )
        try:
            policy = ExecutionPolicy.for_mode("turn-adapter-claims", "draft_only")
            token = set_current_execution_policy(policy, policy_revision=6)
            try:
                result = dispatch_agent_owned_registry_tool(
                    tool_name,
                    {"value": 1},
                    session_id="session-adapter-claims",
                    tool_call_id="call-adapter-claims",
                )
            finally:
                reset_current_execution_policy(token)
        finally:
            global_registry.deregister(tool_name)

        assert json.loads(result)["ok"] is True
        receipt = broker_db.get_tool_effect_receipt_for_invocation(
            "session-adapter-claims", "call-adapter-claims"
        )
        assert receipt is not None
        assert receipt["status"] == "succeeded"
        assert receipt["tool_name"] == tool_name
        assert receipt["policy_revision"] == 6
        assert receipt["result_digest"] == effect_broker.model_result_digest(
            result
        )
