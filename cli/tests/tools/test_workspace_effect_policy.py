"""The workspace ceiling (package ERB-405): what the agent may do to its own
board and browser, and what it still may not do through unrelated tools.

Realtor Beta's containment made the agent read-only/draft-only. That is
correct for unrelated tools that reach a human or a third-party system, and
wrong for the realtor's own board and explicitly autonomous browser. The
browser exception is scope-bound so it cannot authorize messaging, terminal,
CRM, or financial tools merely because they declare the same effect kind.

These tests pin the line from both sides:

* every self-directed local capability and scoped browser capability is
  ADMITTED;
* every non-browser outbound, destructive, spawning, financial, unscoped, or
  unknown capability is REFUSED — including when it is bundled together with
  a perfectly legitimate local write;
* the mode lattice still only narrows, so a delegated child can inherit the
  board but can never escalate off it.
"""

from __future__ import annotations

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    PolicyWideningError,
    authorize_effects,
    capture_inherited_execution_policy,
    current_policy_permits_effect,
    derive_child_execution_policy,
    execution_policy_for_permission_mode,
    get_current_execution_policy,
    get_current_execution_policy_revision,
    inherited_execution_policy_scope,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.effect_broker import claim_required_for_effects

# ---------------------------------------------------------------------------
# The contract, written out longhand
# ---------------------------------------------------------------------------

# Everything the agent may do to its own workspace.
ADMITTED = [
    "read",
    "read:kanban",
    "read:leads",
    "read:deals",
    "read:skills",
    "read:files",
    "read:memory",
    "read:composio",
    "read:browser",
    "write_local:draft",
    "write_local:session_plan",
    "write_local:kanban",
    "write_local:leads",
    "write_local:deals",
    "write_local:working_state",
    "write_local:memory",
    "write_local:skill_usage",
    "write_local:browser",
    "write_external:browser",
    "message_external:browser",
    "destructive:browser",
    "credential_access:browser",
    "financial:browser",
    "spawn:browser",
    "credential_access:composio",
]

# Everything that reaches a human, a third-party system, the user's data at
# large, their money, or a new process — plus the two shapes that would
# quietly widen the ceiling if they were ever admitted (an UNSCOPED
# write_local, and a scope nobody enumerated).
REFUSED = [
    "message_external",
    "message_external:sms",
    "message_external:email",
    "message_external:telegram",
    "write_external",
    "write_external:crm",
    "write_external:mls",
    "destructive",
    "destructive:scratch_workspace",
    "financial",
    "spawn",
    "spawn:cron",
    "credential_access",
    "credential_access:discord",
    "credential_access:feishu",
    "credential_access:homeassistant",
    "write_local",
    "write_local:outbound_queue",
    "write_local:config",
    "unknown",
]


def _workspace(turn: str = "turn-workspace") -> ExecutionPolicy:
    return ExecutionPolicy.for_mode(turn, ExecutionPolicyMode.WORKSPACE)


@pytest.fixture(autouse=True)
def _no_ambient_policy():
    assert get_current_execution_policy() is None
    yield
    assert get_current_execution_policy() is None


# ---------------------------------------------------------------------------
# Ceiling composition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("effect", ADMITTED)
def test_workspace_admits_every_self_directed_capability(effect: str) -> None:
    decision = authorize_effects(_workspace(), {effect})
    assert decision.allowed is True, effect
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize("effect", REFUSED)
def test_workspace_refuses_everything_that_leaves_the_workspace(effect: str) -> None:
    decision = authorize_effects(_workspace(), {effect})
    assert decision.allowed is False, effect
    assert decision.reason in {"effect_not_allowed", "unknown_effect"}


def test_every_non_read_workspace_capability_is_scoped() -> None:
    """An unscoped grant would absorb every future scope of its kind.

    ``_effect_is_within`` treats an unscoped capability as covering all
    scopes, so ``write_local`` (bare) in the ceiling would silently authorize
    a ``write_local:outbound_queue`` invented next quarter.
    """
    for effect in _workspace().allowed_effects:
        if effect.kind is EffectKind.READ:
            continue
        assert effect.scope, f"{effect} must be scoped"


def test_workspace_admits_outward_or_dangerous_kinds_only_for_browser() -> None:
    forbidden = {
        EffectKind.WRITE_EXTERNAL,
        EffectKind.MESSAGE_EXTERNAL,
        EffectKind.DESTRUCTIVE,
        EffectKind.FINANCIAL,
        EffectKind.SPAWN,
        EffectKind.UNKNOWN,
    }
    for effect in _workspace().allowed_effects:
        if effect.kind in forbidden:
            assert effect.scope == "browser"


def test_workspace_is_a_strict_superset_of_draft_only() -> None:
    """Keeps the mode lattice a lattice; drafting still works under it."""
    workspace = _workspace().allowed_effects
    draft = ExecutionPolicy.for_mode("t", ExecutionPolicyMode.DRAFT_ONLY).allowed_effects
    assert draft < workspace


def test_workspace_is_strictly_below_default() -> None:
    default = ExecutionPolicy.for_mode("t", ExecutionPolicyMode.DEFAULT).allowed_effects
    assert _workspace().allowed_effects != default
    for effect in _workspace().allowed_effects:
        assert authorize_effects(
            ExecutionPolicy.for_mode("t", ExecutionPolicyMode.DEFAULT), {effect}
        ).allowed


def test_unknown_is_still_denied_under_the_workspace_ceiling() -> None:
    decision = authorize_effects(_workspace(), {Effect(EffectKind.UNKNOWN)})
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_empty_and_missing_declarations_still_fail_closed() -> None:
    for declaration in (None, [], set(), frozenset()):
        decision = authorize_effects(_workspace(), declaration)
        assert decision.allowed is False
        assert decision.reason == "unknown_effect"


def test_a_workspace_policy_cannot_be_built_with_an_outward_effect() -> None:
    with pytest.raises(ValueError, match="exceed"):
        ExecutionPolicy(
            accepted_turn_id="t",
            mode=ExecutionPolicyMode.WORKSPACE,
            allowed_effects={Effect.parse("message_external:sms")},
        )


# ---------------------------------------------------------------------------
# The adversarial case: local write bundled with an outward reach
# ---------------------------------------------------------------------------


MIXED_DECLARATIONS = [
    # A "board" tool that also texts the client.
    {"read:kanban", "write_local:kanban", "message_external:sms"},
    # A lead-labeller that mirrors to the realtor's CRM.
    {"read:leads", "write_local:leads", "write_external:crm"},
    # A note-taker that emails the note out.
    {"write_local:working_state", "message_external:email"},
    # A plan writer that spawns a background job.
    {"write_local:session_plan", "spawn"},
    # A card-closer that deletes a directory.
    {"write_local:kanban", "destructive"},
    # A memory writer that reads a credential it was not granted.
    {"write_local:memory", "credential_access:discord"},
]


@pytest.mark.parametrize("declaration", MIXED_DECLARATIONS)
def test_a_tool_that_writes_locally_and_reaches_outward_is_refused(
    declaration: set,
) -> None:
    """The structural guarantee, stated as a test.

    Authorization is set containment over EVERY declared effect, so one
    capability outside the ceiling refuses the whole call. Nothing here keys
    on a tool name, a toolset, or a description — a tool cannot earn its way
    in by being called ``kanban_something``.
    """
    decision = authorize_effects(_workspace(), declaration)
    assert decision.allowed is False
    assert decision.reason == "effect_not_allowed"
    assert decision.denied_effects  # names exactly which capability lost


@pytest.mark.parametrize("declaration", MIXED_DECLARATIONS)
def test_the_local_half_alone_would_have_been_allowed(declaration: set) -> None:
    """Proves the refusals above are caused by the outward half, not the local
    half — i.e. the ceiling is discriminating, not just restrictive."""
    policy = _workspace()
    local_half = {
        effect
        for effect in declaration
        if authorize_effects(policy, {effect}).allowed
    }
    assert local_half, declaration
    assert authorize_effects(policy, local_half).allowed is True


# ---------------------------------------------------------------------------
# Inheritance: a child gets <= parent, and can never climb back up
# ---------------------------------------------------------------------------


def test_child_inherits_the_board_but_cannot_escalate() -> None:
    parent = _workspace("turn-parent")
    child = derive_child_execution_policy(parent)
    assert child.mode is ExecutionPolicyMode.WORKSPACE
    assert child.allowed_effects == parent.allowed_effects
    assert child.accepted_turn_id == parent.accepted_turn_id
    assert authorize_effects(child, {"write_local:kanban"}).allowed is True
    assert authorize_effects(child, {"message_external:sms"}).allowed is False


def test_child_can_be_narrowed_below_the_board() -> None:
    parent = _workspace("turn-parent")
    for mode in (
        ExecutionPolicyMode.DRAFT_ONLY,
        ExecutionPolicyMode.PLAN,
        ExecutionPolicyMode.READ_ONLY,
    ):
        child = derive_child_execution_policy(
            parent,
            allowed_effects=ExecutionPolicy.for_mode("t", mode).allowed_effects,
            mode=mode,
        )
        assert child.mode is mode
        assert authorize_effects(child, {"write_local:kanban"}).allowed is False


@pytest.mark.parametrize(
    "parent_mode",
    [
        ExecutionPolicyMode.READ_ONLY,
        ExecutionPolicyMode.PLAN,
        ExecutionPolicyMode.DRAFT_ONLY,
    ],
)
def test_a_narrower_parent_cannot_hand_a_child_the_board(
    parent_mode: ExecutionPolicyMode,
) -> None:
    parent = ExecutionPolicy.for_mode("turn-narrow", parent_mode)
    with pytest.raises(PolicyWideningError):
        derive_child_execution_policy(parent, mode=ExecutionPolicyMode.WORKSPACE)


@pytest.mark.parametrize("effect", ["write_local:kanban", "write_local:deals"])
def test_a_narrower_parent_cannot_hand_a_child_a_board_effect(effect: str) -> None:
    parent = ExecutionPolicy.for_mode("turn-narrow", ExecutionPolicyMode.DRAFT_ONLY)
    with pytest.raises(PolicyWideningError):
        derive_child_execution_policy(parent, allowed_effects={effect})


def test_a_board_child_cannot_add_an_outward_effect() -> None:
    parent = _workspace("turn-parent")
    for escalation in ("message_external:sms", "write_external:crm", "spawn"):
        with pytest.raises(PolicyWideningError):
            derive_child_execution_policy(
                parent, allowed_effects=set(parent.allowed_effects) | {escalation}
            )


def test_a_forged_policy_subclass_still_cannot_widen_a_child() -> None:
    class ForgedPolicy(ExecutionPolicy):
        def narrow(self, allowed_effects, *, mode=None):  # type: ignore[override]
            return ExecutionPolicy(
                accepted_turn_id=self.accepted_turn_id,
                mode=ExecutionPolicyMode.DEFAULT,
                allowed_effects={Effect.parse("message_external:sms")},
            )

    forged = ForgedPolicy(
        accepted_turn_id="turn-forged",
        mode=ExecutionPolicyMode.WORKSPACE,
        allowed_effects=_workspace().allowed_effects,
    )
    with pytest.raises(PolicyWideningError):
        derive_child_execution_policy(forged)


# ---------------------------------------------------------------------------
# Beta cohort clamp
# ---------------------------------------------------------------------------


@pytest.fixture
def beta_channel(monkeypatch):
    # Bundle-controlled, exactly lowercase — the clamp keys on that value.
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    yield


@pytest.mark.parametrize(
    "permission_mode", ["default", "acceptEdits"]
)
def test_the_mode_a_realtor_actually_runs_in_reaches_the_board(
    beta_channel, permission_mode: str
) -> None:
    """A ceiling that only lifted in an opt-in mode would not be a fix."""
    policy = execution_policy_for_permission_mode("turn-beta", permission_mode)
    assert policy.mode is ExecutionPolicyMode.WORKSPACE
    for effect in (
        "write_local:kanban",
        "write_local:leads",
        "write_local:deals",
        "write_local:working_state",
        "write_local:session_plan",
        "write_local:memory",
        "write_local:skill_usage",
        "credential_access:composio",
        "write_local:browser",
        "write_external:browser",
        "message_external:browser",
        "destructive:browser",
        "credential_access:browser",
        "financial:browser",
        "spawn:browser",
    ):
        assert authorize_effects(policy, {effect}).allowed is True, effect
    for effect in ("message_external:sms", "write_external:crm", "spawn"):
        assert authorize_effects(policy, {effect}).allowed is False, effect


def test_explicit_beta_bypass_reaches_the_standard_autonomous_ceiling(
    beta_channel,
) -> None:
    policy = execution_policy_for_permission_mode(
        "turn-beta-bypass",
        "bypassPermissions",
    )
    assert policy.mode is ExecutionPolicyMode.DEFAULT
    for effect in ("message_external:sms", "write_external:crm", "spawn"):
        assert authorize_effects(policy, {effect}).allowed is True, effect


def test_beta_operator_can_still_narrow_below_the_board(beta_channel) -> None:
    assert (
        execution_policy_for_permission_mode("t", "read_only").mode
        is ExecutionPolicyMode.READ_ONLY
    )
    assert (
        execution_policy_for_permission_mode("t", "plan").mode
        is ExecutionPolicyMode.PLAN
    )


def test_an_explicit_bypass_binding_is_carried_intact_under_beta(
    beta_channel,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tools.approval.get_permission_mode",
        lambda: "bypassPermissions",
    )
    wide = ExecutionPolicy.for_mode("turn-wide", ExecutionPolicyMode.DEFAULT)
    token = set_current_execution_policy(wide, policy_revision=7)
    try:
        binding = capture_inherited_execution_policy(parent_session_id="s")
    finally:
        reset_current_execution_policy(token)
    assert binding.policy == wide
    assert binding.policy_revision == 7
    assert binding.beta_bypass_permissions is True


def test_a_workspace_binding_is_carried_intact_under_beta(beta_channel) -> None:
    parent = _workspace("turn-parent")
    token = set_current_execution_policy(parent, policy_revision=4)
    try:
        binding = capture_inherited_execution_policy(parent_session_id="s")
    finally:
        reset_current_execution_policy(token)
    assert binding.policy is not None
    assert binding.policy.mode is ExecutionPolicyMode.WORKSPACE
    assert binding.policy_revision == 4

    with inherited_execution_policy_scope(binding) as bound:
        assert bound.policy is not None
        assert get_current_execution_policy() is bound.policy
        assert get_current_execution_policy_revision() == 4
        assert authorize_effects(bound.policy, {"write_local:deals"}).allowed
        assert not authorize_effects(bound.policy, {"message_external"}).allowed


# ---------------------------------------------------------------------------
# Durable evidence: every board write is claim-required
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "effect",
    [
        "write_local:kanban",
        "write_local:leads",
        "write_local:deals",
        "write_local:working_state",
        "write_local:memory",
        "write_local:skill_usage",
        "write_local:session_plan",
        "credential_access:composio",
    ],
)
def test_board_writes_require_a_durable_claim(effect: str) -> None:
    """Beyond-read means claim + receipt: one winner, durably evidenced."""
    assert claim_required_for_effects({Effect.parse(effect)}) is True


def test_pure_reads_do_not_require_a_claim() -> None:
    assert claim_required_for_effects({Effect.parse("read:deals")}) is False
    assert claim_required_for_effects({Effect(EffectKind.READ)}) is False


def test_a_mixed_read_and_board_write_still_requires_a_claim() -> None:
    assert (
        claim_required_for_effects(
            {Effect.parse("read:deals"), Effect.parse("write_local:deals")}
        )
        is True
    )


# ---------------------------------------------------------------------------
# The severance predicate
# ---------------------------------------------------------------------------


def test_severance_predicate_permits_when_no_policy_is_bound() -> None:
    """Unbound == the pre-policy legacy path; Stable must stay byte-identical."""
    assert current_policy_permits_effect("spawn") is True
    assert current_policy_permits_effect("write_external:crm") is True
    assert current_policy_permits_effect("destructive") is True


@pytest.mark.parametrize(
    "effect", ["spawn", "write_external:crm", "destructive", "message_external"]
)
def test_severance_predicate_denies_outward_effects_under_the_board(
    effect: str,
) -> None:
    token = set_current_execution_policy(_workspace(), policy_revision=1)
    try:
        assert current_policy_permits_effect(effect) is False
    finally:
        reset_current_execution_policy(token)


@pytest.mark.parametrize(
    "effect", ["spawn", "write_external:crm", "destructive", "message_external"]
)
def test_severance_predicate_permits_outward_effects_under_default(
    effect: str,
) -> None:
    """Stable's DEFAULT ceiling keeps every branch reachable, unchanged."""
    token = set_current_execution_policy(
        ExecutionPolicy.for_mode("turn-default", ExecutionPolicyMode.DEFAULT),
        policy_revision=1,
    )
    try:
        assert current_policy_permits_effect(effect) is True
    finally:
        reset_current_execution_policy(token)


# ---------------------------------------------------------------------------
# The gateway's second Beta ceiling
#
# There are TWO independent Beta clamps: ``approval._beta_ceiling_rejects``
# (inheritance) and the gateway's prompt-receipt check. Raising one and not the
# other does not fail loudly as a policy bug — ``narrow`` RAISES on a wider
# receipt, the gateway catches it and interrupts the turn as untrusted, so the
# symptom is "the agent stopped working" with no policy error anywhere. These
# tests drive the real receipt path so the two clamps cannot drift again.
# ---------------------------------------------------------------------------


def _receipt_for(
    policy: ExecutionPolicy,
    *,
    permission_mode: str | None = None,
) -> dict:
    receipt = {
        "client_message_id": policy.accepted_turn_id,
        "policy_revision": 1,
        "accepted_policy": policy.to_dict(),
        "effective_policy": policy.to_dict(),
    }
    if permission_mode is not None:
        receipt["payload"] = {"permission_mode": permission_mode}
    return receipt


def test_the_gateway_accepts_the_policy_a_realtor_turn_produces(
    beta_channel,
) -> None:
    from tui_gateway.server import _execution_policy_from_receipt

    policy = execution_policy_for_permission_mode("msg-workspace", "default")
    restored = _execution_policy_from_receipt(_receipt_for(policy))

    assert restored.mode is ExecutionPolicyMode.WORKSPACE
    assert restored.allowed_effects == policy.allowed_effects
    assert authorize_effects(restored, {"write_local:kanban"}).allowed is True


def test_the_gateway_accepts_an_explicit_bypass_receipt(
    beta_channel,
) -> None:
    from tui_gateway.server import _execution_policy_from_receipt

    wide = ExecutionPolicy.for_mode("msg-wide", ExecutionPolicyMode.DEFAULT)
    with pytest.raises(ValueError, match="exceeds Beta ceiling"):
        _execution_policy_from_receipt(_receipt_for(wide))
    assert (
        _execution_policy_from_receipt(
            _receipt_for(wide, permission_mode="bypassPermissions")
        ).mode
        is ExecutionPolicyMode.DEFAULT
    )


@pytest.mark.parametrize(
    "mode",
    [
        ExecutionPolicyMode.READ_ONLY,
        ExecutionPolicyMode.PLAN,
        ExecutionPolicyMode.DRAFT_ONLY,
        ExecutionPolicyMode.WORKSPACE,
        ExecutionPolicyMode.DEFAULT,
    ],
)
def test_the_gateway_accepts_every_mode_at_or_below_the_cohort(
    beta_channel, mode: ExecutionPolicyMode
) -> None:
    from tui_gateway.server import _execution_policy_from_receipt

    policy = ExecutionPolicy.for_mode(f"msg-{mode.value}", mode)
    permission_mode = (
        "bypassPermissions"
        if mode is ExecutionPolicyMode.DEFAULT
        else None
    )
    assert (
        _execution_policy_from_receipt(
            _receipt_for(policy, permission_mode=permission_mode)
        ).mode
        is mode
    )


def test_the_two_beta_clamps_agree() -> None:
    """Both clamps must name the same cohort maximum, by construction."""
    import inspect

    from tools import approval
    from tui_gateway import server

    assert approval.BETA_COHORT_POLICY_MODE is ExecutionPolicyMode.WORKSPACE
    assert approval.BETA_BYPASS_POLICY_MODE is ExecutionPolicyMode.DEFAULT
    source = inspect.getsource(server._execution_policy_from_receipt)
    assert "BETA_COHORT_POLICY_MODE" in source
    # A hardcoded mode here is what rotted last time.
    for literal in ("ExecutionPolicyMode.DRAFT_ONLY", "ExecutionPolicyMode.WORKSPACE"):
        assert literal not in source


def test_no_third_ceiling_can_appear_outside_the_policy_module() -> None:
    """The invariant that actually prevents a THIRD clamp being written.

    A second Beta ceiling already existed in the gateway and silently kept the
    old cohort maximum; because ``narrow`` raises rather than returning a
    mismatch, that reads as "the agent stopped responding", not as a policy
    error. The only durable defence is that no shipping module outside
    ``tools/approval.py`` names an ``ExecutionPolicyMode`` member at all —
    every consumer takes the exported constant instead.
    """
    import subprocess
    from pathlib import Path

    cli_root = Path(__file__).resolve().parents[2]
    hits = subprocess.run(
        [
            "grep", "-rn", "--include=*.py", "ExecutionPolicyMode.",
            str(cli_root / "tools"),
            str(cli_root / "elevate_cli"),
            str(cli_root / "tui_gateway"),
            str(cli_root / "agent"),
            str(cli_root / "plugins"),
        ],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    offenders = []
    for line in hits:
        path, _, rest = line.partition(":")
        if path.endswith("tools/approval.py"):
            continue
        code = rest.partition(":")[2].strip()
        if code.startswith("#"):
            continue
        offenders.append(line)
    assert offenders == [], (
        "a policy ceiling was named outside tools/approval.py; import "
        f"BETA_COHORT_POLICY_MODE instead: {offenders}"
    )


def test_severance_predicate_denies_when_evaluation_fails(monkeypatch) -> None:
    token = set_current_execution_policy(_workspace(), policy_revision=1)
    try:
        monkeypatch.setattr(
            "tools.approval.authorize_effects",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert current_policy_permits_effect("spawn") is False
    finally:
        reset_current_execution_policy(token)
