"""Package A5 — exact-Beta enforcement flip proof and shadow-evidence campaign.

SEQ-020D's exit gate needs enforcement ON for exact Realtor Beta at every
registry-governed seam, with Stable byte-identical observational behavior.
The machinery landed incrementally (A1 declarations, A2a/A2b adapter +
lane migrations, A3 broker, A4 inheritance); this suite is the A5-level
proof that the flip is REAL and COMPLETE:

1. **Seam matrix** — a denied or UNKNOWN-effect call is refused with its
   typed payload BEFORE any handler at every seam: adapter preflight,
   atomic registry start, legacy dispatch, missing durable identity.
2. **Flip neutrality (shadow-vs-enforced equivalence)** — the same frozen
   call produces the IDENTICAL authorization decision under Stable and
   under exact Beta; the flip changes only whether a denial blocks the
   start.  Legitimate flows are untouched; illegitimate ones become real
   blocks.
3. **Registry-wide campaign** — over the REAL production registry: every
   undeclared registration is refused with a typed payload under exact
   Beta before any handler could run; the declared read surface
   authorizes clean (zero would-be-blocked calls) under the Beta
   read-only cohort policy; every declared beyond-read effect is denied
   under read-only and allowed only when inside the draft-only ceiling.
4. **Live-DB drill** — an allowed beyond-read call under exact Beta runs
   against a real ``SessionDB`` effect store: durable one-winner claim,
   terminal receipt, and duplicate-invocation refusal.
"""

from __future__ import annotations

import json

import pytest

import tools.effect_broker as effect_broker
from elevate_state import SessionDB
from model_tools import dispatch_agent_owned_registry_tool
from tools.approval import (
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import ToolCallContext, ToolRegistry, registry as production_registry


TURN = "turn-a5-flip"


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": f"A5 scratch tool {name}",
        "parameters": {"type": "object", "properties": {}},
    }


def _policy(mode: ExecutionPolicyMode = ExecutionPolicyMode.READ_ONLY) -> ExecutionPolicy:
    return ExecutionPolicy.for_mode(TURN, mode)


def _context(invocation_id: str = "call-a5") -> ToolCallContext:
    return ToolCallContext(
        session_id="session-a5",
        invocation_id=invocation_id,
        accepted_turn_id=TURN,
        policy_revision=3,
    )


@pytest.fixture
def broker_db(tmp_path, monkeypatch) -> SessionDB:
    db = SessionDB(tmp_path / "state.db")
    monkeypatch.setattr(effect_broker, "_store_override", db)
    monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
    return db


@pytest.fixture
def bound_read_only_policy():
    policy = _policy(ExecutionPolicyMode.READ_ONLY)
    token = set_current_execution_policy(policy, policy_revision=3)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


@pytest.fixture
def bound_draft_only_policy():
    policy = _policy(ExecutionPolicyMode.DRAFT_ONLY)
    token = set_current_execution_policy(policy, policy_revision=3)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class _ScratchTool:
    """Register one scratch tool on the production registry for one test."""

    def __init__(self, name, handler, *, effects=None, is_async=False):
        self.name = name
        production_registry.register(
            name=name,
            toolset="_test-a5-flip",
            schema=_schema(name),
            handler=handler,
            is_async=is_async,
            effects=effects,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        production_registry.deregister(self.name)
        return False


def _adapter_dispatch(name, args=None, *, with_identity=True, suffix=""):
    kwargs = {"task_id": "task-a5"}
    if with_identity:
        kwargs["session_id"] = "session-a5" + suffix
        kwargs["tool_call_id"] = "call-a5" + suffix
    return dispatch_agent_owned_registry_tool(name, args or {}, **kwargs)


# =========================================================================
# 1. Seam matrix: typed refusal BEFORE any handler, at every seam
# =========================================================================


class TestExactBetaSeamMatrix:
    def test_denied_declared_effect_refused_before_handler(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_external_writer",
            lambda args, **kw: calls.append(1) or "sent",
            effects={"message_external"},
        ):
            payload = json.loads(_adapter_dispatch("_a5_external_writer"))

        assert payload["shadow_status"] == "effect_policy_block"
        assert "No handler was run" in payload["error"]
        assert calls == []

    def test_unknown_effect_refused_before_handler(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_undeclared", lambda args, **kw: calls.append(1) or "ran"
        ):
            payload = json.loads(_adapter_dispatch("_a5_undeclared"))

        assert payload["shadow_status"] == "effect_policy_block"
        assert calls == []

    def test_missing_durable_identity_refused_before_handler(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_read_no_identity",
            lambda args, **kw: calls.append(1) or "read",
            effects={"read"},
        ):
            payload = json.loads(
                _adapter_dispatch("_a5_read_no_identity", with_identity=False)
            )

        assert payload["shadow_status"] == "effect_context_block"
        assert calls == []

    def test_missing_policy_refused_before_handler(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_read_no_policy",
            lambda args, **kw: calls.append(1) or "read",
            effects={"read"},
        ):
            payload = json.loads(_adapter_dispatch("_a5_read_no_policy"))

        assert payload["shadow_status"] == "effect_context_block"
        assert calls == []

    def test_legacy_dispatch_refused_under_exact_beta(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_legacy", lambda args, **kw: calls.append(1) or "ran",
            effects={"read"},
        ):
            payload = json.loads(
                production_registry.dispatch("_a5_legacy", {})
            )

        assert payload["shadow_status"] == "legacy_dispatch_block"
        assert calls == []

    def test_declared_read_call_starts_and_returns_handler_result(
        self, monkeypatch, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_pure_read",
            lambda args, **kw: calls.append(dict(args)) or '{"rows": []}',
            effects={"read"},
        ):
            result = _adapter_dispatch("_a5_pure_read", {"q": "x"})

        assert result == '{"rows": []}'
        assert calls == [{"q": "x"}]


# =========================================================================
# 2. Flip neutrality: identical decisions, enforcement only changes starts
# =========================================================================


_DECISION_MATRIX = [
    ("read", ExecutionPolicyMode.READ_ONLY, True),
    ("read", ExecutionPolicyMode.DRAFT_ONLY, True),
    ("write_local:draft", ExecutionPolicyMode.READ_ONLY, False),
    ("write_local:draft", ExecutionPolicyMode.DRAFT_ONLY, True),
    ("write_external", ExecutionPolicyMode.DRAFT_ONLY, False),
    ("message_external", ExecutionPolicyMode.DRAFT_ONLY, False),
    ("destructive", ExecutionPolicyMode.DRAFT_ONLY, False),
    (None, ExecutionPolicyMode.DRAFT_ONLY, False),  # undeclared -> unknown
]


class TestFlipNeutrality:
    @pytest.mark.parametrize("effect,mode,expect_allowed", _DECISION_MATRIX)
    def test_shadow_and_enforced_decisions_are_identical(
        self, monkeypatch, broker_db, effect, mode, expect_allowed
    ):
        """The SAME frozen call authorizes identically under Stable and
        exact Beta; only the start outcome differs on denial."""
        outcomes = {}
        for channel in ("stable", "beta"):
            if channel == "beta":
                monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
            else:
                monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
            calls = []
            reg = ToolRegistry()
            reg.register(
                "probe",
                "core",
                _schema("probe"),
                lambda args, **kw: calls.append(1) or "ran",
                effects={effect} if effect is not None else None,
            )
            outcome = reg.execute_shadow(
                "probe",
                {},
                context=_context(f"call-{channel}-{effect}-{mode.value}"),
                execution_policy=_policy(mode),
            )
            outcomes[channel] = (outcome, list(calls))

        stable_outcome, stable_calls = outcomes["stable"]
        beta_outcome, beta_calls = outcomes["beta"]

        # Decision equivalence: the flip does not change WHAT is authorized.
        for field in ("allowed", "reason", "denied_effects", "requested_effects"):
            assert getattr(stable_outcome.prepared.authorization, field) == getattr(
                beta_outcome.prepared.authorization, field
            )
        assert stable_outcome.prepared.authorization.allowed is expect_allowed

        # Stable is observational: the handler ALWAYS ran.
        assert stable_outcome.started is True
        assert stable_calls == [1]

        if expect_allowed:
            # Legitimate flow: the flip changes nothing.
            assert beta_outcome.started is True
            assert beta_calls == [1]
            assert beta_outcome.result == "ran"
        else:
            # Illegitimate flow: the block is real, typed, and pre-handler.
            assert beta_outcome.started is False
            assert beta_calls == []
            payload = json.loads(beta_outcome.result)
            assert payload["shadow_status"] == "effect_policy_block"


# =========================================================================
# 3. Registry-wide shadow-evidence campaign (real production registry)
# =========================================================================


def _production_partition():
    declared, undeclared = [], []
    for name in production_registry.get_all_tool_names():
        meta = production_registry.get_effect_metadata(name)
        (declared if meta["declared"] else undeclared).append((name, meta))
    return declared, undeclared


class TestRegistryWideCampaign:
    def test_partition_is_nonempty_and_sane(self):
        declared, undeclared = _production_partition()
        assert declared, "expected a declared surface (A1 batches landed)"
        assert undeclared, "expected UNKNOWN registrations to remain (69/90-era)"

    def test_every_undeclared_registration_refused_typed_before_handler(
        self, monkeypatch, bound_read_only_policy
    ):
        """100% typed refusals for the undeclared surface under exact Beta.

        Safe to drive for real: the refusal is produced strictly BEFORE the
        handler, so no production handler can run.  Any started call here
        would itself be the failure.
        """
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        declared, undeclared = _production_partition()
        refused = {}
        for name, _meta in undeclared:
            result = _adapter_dispatch(name, {}, suffix=f"-{name}")
            payload = json.loads(result)
            assert payload.get("shadow_status") == "effect_policy_block", (
                f"undeclared tool {name!r} was not refused with the typed "
                f"policy block: {result[:200]}"
            )
            assert "No handler was run" in payload["error"]
            refused[name] = payload["shadow_status"]
        assert len(refused) == len(undeclared)

    def test_declared_static_read_surface_authorizes_clean_under_read_only(self):
        """Zero would-be-blocked calls in the legitimate read path: every
        declared tool whose static surface is pure read authorizes clean
        under the Beta read-only cohort policy."""
        declared, _undeclared = _production_partition()
        read_only = _policy(ExecutionPolicyMode.READ_ONLY)
        static_read = [
            (name, meta)
            for name, meta in declared
            if meta["effects"]
            and all(e.kind is EffectKind.READ for e in meta["effects"])
        ]
        assert static_read, "expected statically read-declared tools"
        for name, meta in static_read:
            decision = authorize_effects(read_only, meta["effects"])
            assert decision.allowed, (
                f"read-declared tool {name!r} would be blocked in the "
                f"legitimate read path: {decision.reason}"
            )

    def test_declared_beyond_read_effects_never_fail_open(self):
        """Every declared beyond-read effect is denied under read-only and
        allowed under draft-only ONLY when inside the draft ceiling."""
        declared, _undeclared = _production_partition()
        read_only = _policy(ExecutionPolicyMode.READ_ONLY)
        draft_only = _policy(ExecutionPolicyMode.DRAFT_ONLY)
        beyond = [
            (name, effect)
            for name, meta in declared
            for effect in meta["effects"]
            if effect.kind is not EffectKind.READ
        ]
        for name, effect in beyond:
            assert not authorize_effects(read_only, {effect}).allowed, (
                f"{name!r} beyond-read effect {effect} authorized under "
                "read-only"
            )
            draft_decision = authorize_effects(draft_only, {effect})
            in_draft_ceiling = authorize_effects(
                draft_only, {effect}
            ).allowed
            # Consistency: draft-only may only ever admit the draft ceiling
            # (read / write_local:draft / write_local:session_plan).
            if in_draft_ceiling:
                assert effect.kind is EffectKind.WRITE_LOCAL
                assert effect.scope in {"draft", "session_plan"}
            else:
                assert not draft_decision.allowed

    def test_no_declared_effect_is_unknown(self):
        """A declared surface must never smuggle ``unknown`` as capability."""
        declared, _undeclared = _production_partition()
        for name, meta in declared:
            for effect in meta["effects"]:
                assert effect.kind is not EffectKind.UNKNOWN, name


# =========================================================================
# 4. Live-DB drill: allowed beyond-read claims + duplicate refusal
# =========================================================================


class TestLiveStoreDrill:
    def test_allowed_draft_write_claims_receipts_and_burns_identity(
        self, monkeypatch, broker_db, bound_draft_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_draft_writer",
            lambda args, **kw: calls.append(1) or "wrote-draft",
            effects={"write_local:draft"},
        ):
            first = _adapter_dispatch("_a5_draft_writer", {"body": "hi"})
            second = _adapter_dispatch("_a5_draft_writer", {"body": "hi"})

        assert first == "wrote-draft"
        assert calls == [1], "duplicate invocation identity re-invoked the handler"
        duplicate = json.loads(second)
        assert duplicate["shadow_status"] == "effect_claim_conflict"

        receipt = broker_db.get_tool_effect_receipt_for_invocation(
            "session-a5", "call-a5"
        )
        assert receipt is not None
        assert receipt["status"] == "succeeded"
        assert receipt["tool_name"] == "_a5_draft_writer"
        assert receipt["session_id"] == "session-a5"

    def test_denied_write_leaves_zero_durable_trail(
        self, monkeypatch, broker_db, bound_read_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        calls = []

        with _ScratchTool(
            "_a5_denied_writer",
            lambda args, **kw: calls.append(1) or "wrote",
            effects={"write_local:draft"},
        ):
            payload = json.loads(_adapter_dispatch("_a5_denied_writer"))

        assert payload["shadow_status"] == "effect_policy_block"
        assert calls == []
        assert (
            broker_db.get_tool_effect_receipt_for_invocation(
                "session-a5", "call-a5"
            )
            is None
        )

    def test_unavailable_store_fails_beyond_read_closed(
        self, monkeypatch, bound_draft_only_policy
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(effect_broker, "_store_override", None)
        monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
        calls = []

        with _ScratchTool(
            "_a5_storeless_writer",
            lambda args, **kw: calls.append(1) or "wrote",
            effects={"write_local:draft"},
        ):
            payload = json.loads(_adapter_dispatch("_a5_storeless_writer"))

        assert payload["shadow_status"] == "effect_claim_unavailable"
        assert calls == []
