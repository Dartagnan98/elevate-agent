"""Unit adversarial coverage for the general effect claim/receipt broker."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid

import pytest

import tools.effect_broker as effect_broker
from elevate_state import SessionDB
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from tools.registry import ToolCallContext, ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": f"A {name} tool",
        "parameters": {"type": "object", "properties": {}},
    }


def _policy(mode: str = "draft_only") -> ExecutionPolicy:
    return ExecutionPolicy.for_mode("turn-broker", ExecutionPolicyMode.parse(mode))


def _context(invocation_id: str = "call-broker") -> ToolCallContext:
    return ToolCallContext(
        session_id="session-broker",
        invocation_id=invocation_id,
        accepted_turn_id="turn-broker",
        policy_revision=2,
    )


def _prepared(registry: ToolRegistry, *, invocation_id: str = "call-broker"):
    return registry.prepare_shadow(
        "draft_writer",
        {"value": 1},
        context=_context(invocation_id),
        execution_policy=_policy(),
    )


@pytest.fixture
def writer_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "draft_writer",
        "core",
        _schema("draft_writer"),
        lambda args, **kwargs: json.dumps({"wrote": args}),
        effects={"write_local:draft"},
    )
    return registry


@pytest.fixture
def broker_db(tmp_path, monkeypatch) -> SessionDB:
    db = SessionDB(tmp_path / "state.db")
    monkeypatch.setattr(effect_broker, "_store_override", db)
    monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
    return db


class TestClaimRequiredClassification:
    def test_pure_read_effects_do_not_require_a_claim(self):
        assert (
            effect_broker.claim_required_for_effects(
                frozenset({Effect(EffectKind.READ), Effect(EffectKind.READ, "deals")})
            )
            is False
        )

    @pytest.mark.parametrize(
        "beyond",
        [
            Effect(EffectKind.WRITE_LOCAL, "draft"),
            Effect(EffectKind.WRITE_EXTERNAL),
            Effect(EffectKind.MESSAGE_EXTERNAL, "sms"),
            Effect(EffectKind.DESTRUCTIVE),
            Effect(EffectKind.CREDENTIAL_ACCESS, "composio"),
            Effect(EffectKind.FINANCIAL),
            Effect(EffectKind.SPAWN),
            Effect(EffectKind.UNKNOWN),
        ],
    )
    def test_any_beyond_read_effect_requires_a_claim(self, beyond):
        assert (
            effect_broker.claim_required_for_effects(
                frozenset({Effect(EffectKind.READ), beyond})
            )
            is True
        )

    def test_empty_and_malformed_effect_sets_fail_safe(self):
        assert effect_broker.claim_required_for_effects(frozenset()) is True
        assert effect_broker.claim_required_for_effects(None) is True


class TestAcquireRevalidation:
    def test_acquire_refuses_outside_exact_beta(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert decision.claim is None
        assert decision.status_code == effect_broker.CLAIM_STATUS_UNAVAILABLE

    def test_acquire_claims_a_valid_prepared_call(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert decision.claim is not None
        receipt = broker_db.get_tool_effect_receipt(decision.claim.claim_id)
        assert receipt["status"] == "claimed"
        assert receipt["tool_name"] == "draft_writer"
        assert receipt["effect_set"] == ["write_local:draft"]
        assert receipt["policy_revision"] == 2

    def test_tampered_args_digest_is_refused_before_any_claim(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        forged = dataclasses.replace(
            _prepared(writer_registry), args_digest="0" * 64
        )
        decision = effect_broker.acquire_prepared_effect_claim(forged)
        assert decision.claim is None
        assert decision.status_code == effect_broker.CLAIM_STATUS_REVALIDATION
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                "session-broker", "call-broker"
            )
            is None
        )

    def test_forged_authorization_cannot_pass_reauthorization(
        self, writer_registry, broker_db, monkeypatch
    ):
        """A PreparedToolCall whose frozen ``authorization`` claims 'allowed'
        while its effects actually exceed the frozen policy is re-evaluated
        from first principles and refused."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        genuine = _prepared(writer_registry)
        forged = dataclasses.replace(
            genuine,
            resolved_effects=frozenset({Effect(EffectKind.DESTRUCTIVE)}),
        )
        decision = effect_broker.acquire_prepared_effect_claim(forged)
        assert decision.claim is None
        assert decision.status_code == effect_broker.CLAIM_STATUS_REVALIDATION

    def test_unknown_effects_are_refused(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        forged = dataclasses.replace(
            _prepared(writer_registry),
            resolved_effects=frozenset({Effect(EffectKind.UNKNOWN)}),
        )
        decision = effect_broker.acquire_prepared_effect_claim(forged)
        assert decision.claim is None
        assert decision.status_code == effect_broker.CLAIM_STATUS_REVALIDATION

    def test_unavailable_store_fails_closed(
        self, writer_registry, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(effect_broker, "_store_override", None)
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert decision.claim is None
        assert decision.status_code == effect_broker.CLAIM_STATUS_UNAVAILABLE

    def test_duplicate_invocation_identity_conflicts(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        first = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert first.claim is not None
        second = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert second.claim is None
        assert second.status_code == effect_broker.CLAIM_STATUS_CONFLICT


class _SelectiveFailureStore:
    """Delegating store that fails specific completion statuses."""

    def __init__(self, inner, *, fail_statuses):
        self._inner = inner
        self._fail_statuses = set(fail_statuses)
        self.completion_attempts = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def complete_tool_effect(self, **kwargs):
        self.completion_attempts.append(kwargs["status"])
        if kwargs["status"] in self._fail_statuses:
            raise RuntimeError("simulated receipt persistence failure")
        return self._inner.complete_tool_effect(**kwargs)


class TestFinishEffectClaim:
    def _claim(self, writer_registry, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        assert decision.claim is not None
        return decision.claim

    def test_success_receipt_records_the_result_digest(
        self, writer_registry, broker_db, monkeypatch
    ):
        claim = self._claim(writer_registry, monkeypatch)
        final = effect_broker.finish_effect_claim(
            claim, status="succeeded", result_identity='{"ok":true}'
        )
        assert final == "succeeded"
        receipt = broker_db.get_tool_effect_receipt(claim.claim_id)
        assert receipt["status"] == "succeeded"
        assert receipt["result_digest"] == hashlib.sha256(
            b'{"ok":true}'
        ).hexdigest()

    def test_receipt_loss_degrades_to_durable_unknown(
        self, writer_registry, broker_db, monkeypatch
    ):
        claim = self._claim(writer_registry, monkeypatch)
        flaky = _SelectiveFailureStore(broker_db, fail_statuses={"succeeded"})
        flaky_claim = dataclasses.replace(claim, store=flaky)
        final = effect_broker.finish_effect_claim(
            flaky_claim, status="succeeded", result_identity="result"
        )
        assert final == "unknown"
        assert flaky.completion_attempts == ["succeeded", "unknown"]
        receipt = broker_db.get_tool_effect_receipt(claim.claim_id)
        assert receipt["status"] == "unknown"
        assert receipt["failure_code"] == "final_receipt_unavailable"

    def test_total_receipt_loss_still_reports_unknown(
        self, writer_registry, broker_db, monkeypatch
    ):
        claim = self._claim(writer_registry, monkeypatch)
        flaky = _SelectiveFailureStore(
            broker_db, fail_statuses={"succeeded", "unknown"}
        )
        flaky_claim = dataclasses.replace(claim, store=flaky)
        final = effect_broker.finish_effect_claim(
            flaky_claim, status="succeeded", result_identity="result"
        )
        assert final == "unknown"
        # The durable row stays in the claimed crash window: a restart
        # terminalizes it; the in-process answer was never success.
        receipt = broker_db.get_tool_effect_receipt(claim.claim_id)
        assert receipt["status"] == "claimed"


class TestBindTransformedResult:
    def test_bind_evidences_a_rewrite_against_the_receipt(
        self, writer_registry, broker_db, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry)
        )
        claim = decision.claim
        assert (
            effect_broker.finish_effect_claim(
                claim, status="succeeded", result_identity="original"
            )
            == "succeeded"
        )
        assert (
            effect_broker.bind_transformed_result(claim, "original", "rewritten")
            is True
        )
        receipt = broker_db.get_tool_effect_receipt(claim.claim_id)
        assert receipt["transformed_result_digest"] == hashlib.sha256(
            b"rewritten"
        ).hexdigest()
        # A rewrite that lies about the original is refused.
        assert (
            effect_broker.bind_transformed_result(claim, "forged", "other")
            is False
        )

    def test_bind_fails_closed_without_a_store(self):
        assert (
            effect_broker.bind_transformed_result(object(), "a", "b") is False
        )


class TestModelResultDigest:
    def test_string_results_digest_their_utf8_bytes(self):
        assert effect_broker.model_result_digest("abc") == hashlib.sha256(
            b"abc"
        ).hexdigest()

    def test_non_string_results_digest_canonical_json(self):
        digest = effect_broker.model_result_digest({"b": 1, "a": 2})
        canonical = json.dumps(
            {"b": 1, "a": 2},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
        assert digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TestGuardBetaResultIntegrity:
    def test_matching_digest_passes_through(self):
        from model_tools import _guard_beta_result_integrity

        ref = effect_broker.ToolEffectReceiptRef(
            claim_id=uuid.uuid4().hex,
            session_id="s",
            invocation_id="i",
            tool_name="draft_writer",
            final_status="succeeded",
            expected_result_digests=frozenset(
                {effect_broker.model_result_digest("payload")}
            ),
        )
        assert _guard_beta_result_integrity("draft_writer", ref, "payload") == (
            "payload"
        )

    def test_unevidenced_rewrite_is_withheld(self):
        from model_tools import _guard_beta_result_integrity

        ref = effect_broker.ToolEffectReceiptRef(
            claim_id=uuid.uuid4().hex,
            session_id="s",
            invocation_id="i",
            tool_name="draft_writer",
            final_status="succeeded",
            expected_result_digests=frozenset(
                {effect_broker.model_result_digest("payload")}
            ),
        )
        guarded = _guard_beta_result_integrity(
            "draft_writer", ref, "tampered-payload"
        )
        assert json.loads(guarded)["shadow_status"] == "effect_result_tamper"

    def test_no_receipt_is_byte_transparent(self):
        from model_tools import _guard_beta_result_integrity

        assert _guard_beta_result_integrity("reader", None, "anything") == (
            "anything"
        )

    def test_evidenced_rewrite_passes_the_guard(
        self, writer_registry, broker_db, monkeypatch
    ):
        """A rewrite bound to the durable receipt via bind_transformed_result
        is legitimate model-visible output; an unevidenced one stays
        fail-closed."""
        from model_tools import _guard_beta_result_integrity

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        decision = effect_broker.acquire_prepared_effect_claim(
            _prepared(writer_registry, invocation_id="call-guard-evidence")
        )
        claim = decision.claim
        assert (
            effect_broker.finish_effect_claim(
                claim, status="succeeded", result_identity="original"
            )
            == "succeeded"
        )
        ref = effect_broker.ToolEffectReceiptRef(
            claim_id=claim.claim_id,
            session_id=claim.session_id,
            invocation_id=claim.invocation_id,
            tool_name=claim.tool_name,
            final_status="succeeded",
            expected_result_digests=frozenset(
                {effect_broker.model_result_digest("original")}
            ),
        )
        # Unevidenced rewrite: withheld.
        withheld = _guard_beta_result_integrity(
            "draft_writer", ref, "rewritten"
        )
        assert json.loads(withheld)["shadow_status"] == "effect_result_tamper"
        # Evidence the rewrite, then the SAME output passes the guard.
        assert (
            effect_broker.bind_transformed_result(claim, "original", "rewritten")
            is True
        )
        assert (
            _guard_beta_result_integrity("draft_writer", ref, "rewritten")
            == "rewritten"
        )
        # A different, still-unevidenced rewrite remains withheld.
        other = _guard_beta_result_integrity("draft_writer", ref, "other")
        assert json.loads(other)["shadow_status"] == "effect_result_tamper"
