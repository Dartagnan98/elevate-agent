"""Focused tests for the accepted-turn effect-policy foundation."""

from dataclasses import FrozenInstanceError

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    PolicyWideningError,
    authorize_effects,
)
from tools.registry import ToolRegistry


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {}},
    }


def _handler(_args, **_kwargs) -> str:
    return "{}"


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
