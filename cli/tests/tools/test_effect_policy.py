"""Focused tests for the accepted-turn effect-policy foundation."""

from dataclasses import FrozenInstanceError

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    PERMISSION_MODE_POLICY_MODES,
    PolicyWideningError,
    authorize_effects,
    execution_policy_for_permission_mode,
    get_current_execution_policy,
    get_current_execution_policy_revision,
    get_session_permission_mode_for_policy,
    reset_current_execution_policy,
    set_current_execution_policy,
    set_session_permission_mode,
)
from tools import approval
from tools.registry import ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {}},
    }


def _handler(_args, **_kwargs) -> str:
    return "{}"


# The exact-Beta cohort maximum. Written out longhand rather than derived from
# the implementation so a change to the ceiling has to be made deliberately in
# two places, and shows up as a diff a reviewer reads.
WORKSPACE_EFFECT_NAMES = {
    "read",
    "write_local:draft",
    "write_local:session_plan",
    "write_local:kanban",
    "write_local:tasks",
    "write_local:leads",
    "write_local:deals",
    "write_local:working_state",
    "write_local:memory",
    "write_local:activity",
    # 2026-07-23 third batch: asking permission (inert until the human
    # resolves it on the dashboard) and the agent's own liveness row.
    "write_local:approvals",
    "write_local:heartbeat",
    "write_local:skill_usage",
    "write_local:browser",
    "write_external:browser",
    "message_external:browser",
    "destructive:browser",
    "credential_access:browser",
    "financial:browser",
    "spawn:browser",
    "credential_access:composio",
}
DEFAULT_EFFECT_NAMES = {
    "read",
    "write_local",
    "write_external",
    "message_external",
    "destructive",
    "credential_access",
    "financial",
    "spawn",
}


def test_effect_vocabulary_parses_scoped_values_canonically() -> None:
    assert Effect.parse("write_external:CRM") == Effect(
        EffectKind.WRITE_EXTERNAL,
        "crm",
    )
    assert str(Effect.parse("message_external:sms")) == "message_external:sms"
    assert {kind.value for kind in EffectKind} == {
        "read",
        "write_local",
        "write_external",
        "message_external",
        "destructive",
        "credential_access",
        "financial",
        "spawn",
        "unknown",
    }


def test_execution_policy_is_frozen_and_narrowing_keeps_original() -> None:
    policy = ExecutionPolicy.for_mode("turn-123", ExecutionPolicyMode.DEFAULT)
    narrowed = policy.narrow({"read", "write_local:workspace"})

    assert narrowed is not policy
    assert narrowed.accepted_turn_id == "turn-123"
    assert narrowed.allowed_effects == frozenset({
        Effect.parse("read"),
        Effect.parse("write_local:workspace"),
    })
    assert Effect.parse("message_external") in policy.allowed_effects
    with pytest.raises(FrozenInstanceError):
        policy.mode = ExecutionPolicyMode.PLAN  # type: ignore[misc]
    with pytest.raises(AttributeError):
        policy.allowed_effects.add(Effect.parse("unknown"))  # type: ignore[attr-defined]


def test_execution_policy_persistence_round_trip_is_canonical() -> None:
    policy = ExecutionPolicy.for_mode("turn-persisted", ExecutionPolicyMode.PLAN)

    encoded = policy.to_dict()

    assert encoded == {
        "schema_version": 1,
        "accepted_turn_id": "turn-persisted",
        "mode": "plan",
        "allowed_effects": ["read", "write_local:session_plan"],
    }
    assert ExecutionPolicy.from_dict(encoded) == policy


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"schema_version": 2},
        {
            "schema_version": 1,
            "accepted_turn_id": "turn-invalid",
            "mode": "read_only",
            "allowed_effects": "read",
        },
    ],
)
def test_execution_policy_persistence_rejects_unknown_or_malformed_data(
    data: dict,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ExecutionPolicy.from_dict(data)


@pytest.mark.parametrize(
    ("permission_mode", "expected_mode"),
    [
        ("default", ExecutionPolicyMode.DEFAULT),
        ("acceptEdits", ExecutionPolicyMode.DEFAULT),
        ("plan", ExecutionPolicyMode.PLAN),
        ("bypassPermissions", ExecutionPolicyMode.DEFAULT),
        ("read_only", ExecutionPolicyMode.READ_ONLY),
    ],
)
def test_permission_mode_mapping_is_total_outside_beta(
    monkeypatch,
    permission_mode: str,
    expected_mode: ExecutionPolicyMode,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")

    policy = execution_policy_for_permission_mode("turn-mapped", permission_mode)

    assert policy == ExecutionPolicy.for_mode("turn-mapped", expected_mode)


@pytest.mark.parametrize("permission_mode", ["", "acceptedits", "unknown", None])
def test_permission_mode_mapping_never_falls_back_for_unknown_values(
    monkeypatch,
    permission_mode,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")

    with pytest.raises((TypeError, ValueError)):
        execution_policy_for_permission_mode("turn-unknown", permission_mode)


def test_unknown_session_and_config_modes_reach_policy_mapper_unsanitized(
    monkeypatch,
) -> None:
    with pytest.raises(ValueError, match="Unknown permission mode"):
        set_session_permission_mode("strict-policy-session", "futureMode")

    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: {"permission_mode": "futureMode"},
    )
    configured = get_session_permission_mode_for_policy("unconfigured-session")
    assert configured == "futureMode"
    with pytest.raises(ValueError, match="Unknown permission mode"):
        execution_policy_for_permission_mode("turn-config", configured)


@pytest.mark.parametrize(
    ("permission_mode", "expected_mode", "expected_effects"),
    [
        (
            "default",
            ExecutionPolicyMode.WORKSPACE,
            WORKSPACE_EFFECT_NAMES,
        ),
        (
            "acceptEdits",
            ExecutionPolicyMode.WORKSPACE,
            WORKSPACE_EFFECT_NAMES,
        ),
        (
            "bypassPermissions",
            ExecutionPolicyMode.DEFAULT,
            DEFAULT_EFFECT_NAMES,
        ),
        (
            "plan",
            ExecutionPolicyMode.PLAN,
            {"read", "write_local:session_plan"},
        ),
        ("read_only", ExecutionPolicyMode.READ_ONLY, {"read"}),
    ],
)
def test_realtor_beta_permission_modes_map_to_their_explicit_ceiling(
    monkeypatch,
    permission_mode: str,
    expected_mode: ExecutionPolicyMode,
    expected_effects: set[str],
) -> None:
    # The Beta channel value is bundle-controlled and exactly lowercase; the
    # clamp keys on that exact value, and noncanonical casings deliberately
    # keep Stable behavior (see test_beta_approval_bypass case-mismatch tests).
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    policy = execution_policy_for_permission_mode("turn-beta", permission_mode)

    assert policy.mode is expected_mode
    assert {str(effect) for effect in policy.allowed_effects} == expected_effects


@pytest.mark.parametrize("channel", ["BeTa", "BETA", " beta"])
def test_noncanonical_beta_channel_keeps_stable_permission_modes(
    monkeypatch,
    channel: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", channel)
    clamped = execution_policy_for_permission_mode("turn-x", "bypassPermissions")
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    stable = execution_policy_for_permission_mode("turn-x", "bypassPermissions")
    assert clamped.mode is stable.mode
    assert clamped.allowed_effects == stable.allowed_effects


def test_policy_ceiling_and_permission_mappings_are_immutable() -> None:
    with pytest.raises(TypeError):
        PERMISSION_MODE_POLICY_MODES["default"] = ExecutionPolicyMode.READ_ONLY
    with pytest.raises(TypeError):
        approval._BETA_PERMISSION_MODE_POLICY_MODES["default"] = (
            ExecutionPolicyMode.DEFAULT
        )
    with pytest.raises(TypeError):
        approval._POLICY_MODE_CEILINGS[ExecutionPolicyMode.DEFAULT] = frozenset()


def test_execution_policy_context_binding_restores_prior_value() -> None:
    outer = ExecutionPolicy.for_mode("turn-outer", ExecutionPolicyMode.READ_ONLY)
    inner = ExecutionPolicy.for_mode("turn-inner", ExecutionPolicyMode.PLAN)
    assert get_current_execution_policy() is None
    assert get_current_execution_policy_revision() is None

    outer_token = set_current_execution_policy(outer, policy_revision=4)
    inner_token = set_current_execution_policy(inner)
    try:
        assert get_current_execution_policy() is inner
        assert get_current_execution_policy_revision() is None
        reset_current_execution_policy(inner_token)
        assert get_current_execution_policy() is outer
        assert get_current_execution_policy_revision() == 4
    finally:
        reset_current_execution_policy(outer_token)

    assert get_current_execution_policy() is None
    assert get_current_execution_policy_revision() is None


@pytest.mark.parametrize("revision", [True, -1, 1.5, "1"])
def test_execution_policy_context_rejects_invalid_revision_without_leaking(
    revision,
) -> None:
    policy = ExecutionPolicy.for_mode("turn-invalid-revision", "read_only")

    with pytest.raises((TypeError, ValueError)):
        set_current_execution_policy(policy, policy_revision=revision)

    assert get_current_execution_policy() is None
    assert get_current_execution_policy_revision() is None


def test_narrow_rejects_effect_scope_and_mode_widening() -> None:
    scoped = ExecutionPolicy(
        accepted_turn_id="turn-scoped",
        mode=ExecutionPolicyMode.DEFAULT,
        allowed_effects=frozenset({Effect.parse("write_local:draft")}),
    )
    with pytest.raises(PolicyWideningError, match="write_local"):
        scoped.narrow({"write_local"})

    plan = ExecutionPolicy.for_mode("turn-plan", ExecutionPolicyMode.PLAN)
    with pytest.raises(PolicyWideningError, match="message_external"):
        plan.narrow({"read", "message_external:sms"})
    with pytest.raises(PolicyWideningError, match="policy mode"):
        plan.narrow({"read"}, mode=ExecutionPolicyMode.DEFAULT)

    read_only = ExecutionPolicy.for_mode("turn-read", ExecutionPolicyMode.READ_ONLY)
    with pytest.raises(PolicyWideningError, match="policy mode"):
        read_only.narrow({"read"}, mode=ExecutionPolicyMode.DRAFT_ONLY)


def test_draft_only_ceiling_cannot_be_forged_with_external_capabilities() -> None:
    with pytest.raises(ValueError, match="draft_only policy ceiling"):
        ExecutionPolicy(
            accepted_turn_id="turn-draft",
            mode=ExecutionPolicyMode.DRAFT_ONLY,
            allowed_effects=frozenset({Effect.parse("write_external:crm")}),
        )


@pytest.mark.parametrize(
    ("mode", "effect", "expected"),
    [
        (ExecutionPolicyMode.PLAN, "read", True),
        (ExecutionPolicyMode.PLAN, "write_local:session_plan", True),
        (ExecutionPolicyMode.PLAN, "write_local:workspace", False),
        (ExecutionPolicyMode.READ_ONLY, "write_local:draft", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_local:draft", True),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_local:session_plan", True),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_external:draft", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_external:crm", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_external:mls", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "write_external:calendar", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "message_external:sms", False),
        (ExecutionPolicyMode.DRAFT_ONLY, "financial", False),
    ],
)
def test_restricted_policy_authorization_is_fail_closed(
    mode: ExecutionPolicyMode,
    effect: str,
    expected: bool,
) -> None:
    policy = ExecutionPolicy.for_mode(f"turn-{mode.value}", mode)
    decision = authorize_effects(policy, {effect})

    assert decision.allowed is expected
    assert bool(decision) is expected
    assert decision.reason == ("allowed" if expected else "effect_not_allowed")


def test_unknown_and_missing_effects_are_denied_even_with_default_policy() -> None:
    policy = ExecutionPolicy.for_mode("turn-default", ExecutionPolicyMode.DEFAULT)

    for effects in ({"unknown"}, None, set(), {"not_a_real_effect"}):
        decision = authorize_effects(policy, effects)
        assert decision.allowed is False
        assert decision.reason == "unknown_effect"
        assert decision.denied_effects == frozenset({Effect(EffectKind.UNKNOWN)})

    missing_policy = authorize_effects(None, {"read"})
    assert missing_policy.allowed is False
    assert missing_policy.reason == "missing_policy"


def test_multi_effect_call_denies_the_entire_operation() -> None:
    policy = ExecutionPolicy.for_mode("turn-read", ExecutionPolicyMode.READ_ONLY)
    decision = authorize_effects(
        policy,
        {"read", "write_external:crm", "message_external:email"},
    )

    assert decision.allowed is False
    assert decision.denied_effects == frozenset({
        Effect.parse("write_external:crm"),
        Effect.parse("message_external:email"),
    })


def test_registry_undeclared_and_unknown_dynamic_tools_resolve_unknown() -> None:
    registry = ToolRegistry()
    registry.register(
        name="dynamic_plugin_tool",
        toolset="mcp-example",
        schema=_schema("dynamic_plugin_tool"),
        handler=_handler,
    )

    unknown = frozenset({Effect(EffectKind.UNKNOWN)})
    assert registry.resolve_effects("dynamic_plugin_tool", {}) == unknown
    assert registry.resolve_effects("not_registered", {}) == unknown
    assert registry.get_effect_metadata("dynamic_plugin_tool") == {
        "declared": False,
        "effects": unknown,
        "has_resolver": False,
    }
    decision = authorize_effects(
        ExecutionPolicy.for_mode("turn-plan", ExecutionPolicyMode.PLAN),
        registry.resolve_effects("dynamic_plugin_tool", {}),
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_registry_static_metadata_and_argument_resolver_are_introspectable() -> None:
    registry = ToolRegistry()

    def resolve(args: dict):
        if args.get("action") == "update":
            return {"write_external:crm"}
        return {"read"}

    registry.register(
        name="crm",
        toolset="real-estate",
        schema=_schema("crm"),
        handler=_handler,
        effects={"credential_access:crm"},
        effect_resolver=resolve,
    )

    metadata = registry.get_effect_metadata("crm")
    assert metadata == {
        "declared": True,
        "effects": frozenset({Effect.parse("credential_access:crm")}),
        "has_resolver": True,
    }
    assert registry.resolve_effects("crm", {"action": "read"}) == frozenset({
        Effect.parse("credential_access:crm"),
        Effect.parse("read"),
    })
    assert registry.resolve_effects("crm", {"action": "update"}) == frozenset({
        Effect.parse("credential_access:crm"),
        Effect.parse("write_external:crm"),
    })


def test_registry_resolver_only_metadata_is_declared_without_static_unknown() -> None:
    registry = ToolRegistry()
    registry.register(
        name="resolver_only",
        toolset="plugin",
        schema=_schema("resolver_only"),
        handler=_handler,
        effect_resolver=lambda _args: {"read"},
    )

    assert registry.get_effect_metadata("resolver_only") == {
        "declared": True,
        "effects": frozenset(),
        "has_resolver": True,
    }
    assert registry.resolve_effects("resolver_only", {}) == frozenset({
        Effect.parse("read"),
    })


@pytest.mark.parametrize("dynamic_effects", [None, set()])
def test_registry_empty_dynamic_resolution_adds_unknown_and_denies(
    dynamic_effects,
) -> None:
    registry = ToolRegistry()
    registry.register(
        name="incomplete_dynamic_tool",
        toolset="plugin",
        schema=_schema("incomplete_dynamic_tool"),
        handler=_handler,
        effects={"read"},
        effect_resolver=lambda _args: dynamic_effects,
    )

    effects = registry.resolve_effects(
        "incomplete_dynamic_tool",
        {"action": "unclassified_mutation"},
    )
    assert effects == frozenset({
        Effect.parse("read"),
        Effect(EffectKind.UNKNOWN),
    })
    decision = authorize_effects(
        ExecutionPolicy.for_mode("turn-read", ExecutionPolicyMode.READ_ONLY),
        effects,
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_registry_non_dict_resolver_args_add_unknown_without_coercion() -> None:
    registry = ToolRegistry()
    resolver_calls = []

    def resolve(args: dict):
        resolver_calls.append(args)
        return {"read"}

    registry.register(
        name="shape_sensitive_tool",
        toolset="plugin",
        schema=_schema("shape_sensitive_tool"),
        handler=_handler,
        effects={"read"},
        effect_resolver=resolve,
    )

    effects = registry.resolve_effects(
        "shape_sensitive_tool",
        ["mutating", "payload"],  # type: ignore[arg-type]
    )
    assert resolver_calls == []
    assert effects == frozenset({
        Effect.parse("read"),
        Effect(EffectKind.UNKNOWN),
    })
    decision = authorize_effects(
        ExecutionPolicy.for_mode("turn-read", ExecutionPolicyMode.READ_ONLY),
        effects,
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_registry_resolver_failure_adds_unknown_instead_of_failing_open() -> None:
    registry = ToolRegistry()
    registry.register(
        name="broken_dynamic_tool",
        toolset="plugin",
        schema=_schema("broken_dynamic_tool"),
        handler=_handler,
        effects={"read"},
        effect_resolver=lambda _args: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert registry.resolve_effects("broken_dynamic_tool", {}) == frozenset({
        Effect.parse("read"),
        Effect(EffectKind.UNKNOWN),
    })


def test_registry_effect_metadata_does_not_change_dispatch_behavior() -> None:
    registry = ToolRegistry()
    registry.register(
        name="still_dispatches",
        toolset="core",
        schema=_schema("still_dispatches"),
        handler=_handler,
        effects={"destructive"},
    )

    assert registry.dispatch("still_dispatches", {}) == "{}"
