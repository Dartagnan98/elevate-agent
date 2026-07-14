"""Tests for the unused atomic registry shadow-execution primitive."""

import asyncio
import hashlib
import json
import sys
import threading
import types
from dataclasses import FrozenInstanceError

import pytest

from tools.approval import (
    Effect,
    EffectKind,
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
    mode: ExecutionPolicyMode = ExecutionPolicyMode.READ_ONLY,
) -> ExecutionPolicy:
    return ExecutionPolicy.for_mode("turn-shadow", mode)


def _context(
    invocation_id: str = "call-shadow",
    *,
    accepted_turn_id: str = "turn-shadow",
    policy_revision: int = 0,
) -> ToolCallContext:
    return ToolCallContext(
        session_id="session-shadow",
        invocation_id=invocation_id,
        accepted_turn_id=accepted_turn_id,
        policy_revision=policy_revision,
    )


def test_entry_id_is_monotonic_for_every_successful_registration() -> None:
    registry = ToolRegistry()

    registry.register("tool", "core", _schema("tool"), lambda _args: "first")
    first = registry.get_entry("tool").entry_id
    registry.register("tool", "core", _schema("tool"), lambda _args: "second")
    second = registry.get_entry("tool").entry_id
    registry.deregister("tool")
    registry.register("tool", "core", _schema("tool"), lambda _args: "third")
    third = registry.get_entry("tool").entry_id

    assert first < second < third


def test_prepare_binds_exact_args_entry_effects_resolver_and_policy() -> None:
    registry = ToolRegistry()
    resolver_args = []
    handler_args = []

    def resolve(args: dict):
        resolver_args.append(args)
        return {"read"}

    def handler(args: dict) -> str:
        handler_args.append(args)
        return json.dumps(args)

    registry.register(
        "snapshot",
        "core",
        _schema("snapshot"),
        handler,
        effects={"read"},
        effect_resolver=resolve,
    )
    policy = _policy()
    original_args = {"b": [2], "a": 1}
    token = set_current_execution_policy(policy)
    try:
        prepared = registry._prepare_shadow_call(
            "snapshot",
            original_args,
            _context("call-snapshot", policy_revision=3),
        )
    finally:
        reset_current_execution_policy(token)

    original_args["b"].append(3)
    outcome = registry._start_prepared_shadow(prepared)
    expected_json = '{"a":1,"b":[2]}'

    assert outcome.started is True
    assert json.loads(outcome.result) == {"a": 1, "b": [2]}
    assert resolver_args == [{"a": 1, "b": [2]}]
    assert handler_args == [{"a": 1, "b": [2]}]
    assert prepared.canonical_args_json == expected_json
    assert prepared.args_digest == hashlib.sha256(expected_json.encode()).hexdigest()
    assert prepared.captured_handler is handler
    assert prepared.captured_effect_resolver is resolve
    assert prepared.captured_effects == frozenset({Effect(EffectKind.READ)})
    assert prepared.execution_policy is policy
    assert prepared.context == _context("call-snapshot", policy_revision=3)
    assert prepared.authorization.allowed is True
    with pytest.raises(FrozenInstanceError):
        prepared.entry_id = 999  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        prepared.context.policy_revision = 4  # type: ignore[misc]


def test_denied_authorization_is_observed_but_not_enforced() -> None:
    registry = ToolRegistry()
    calls = []

    def handler(args: dict) -> str:
        calls.append(args)
        return "executed"

    registry.register(
        "writer",
        "core",
        _schema("writer"),
        handler,
        effects={"write_external:crm"},
    )

    outcome = registry.execute_shadow(
        "writer",
        {"record": "123"},
        context=_context("call-writer"),
        execution_policy=_policy(),
    )

    assert outcome.started is True
    assert outcome.result == "executed"
    assert calls == [{"record": "123"}]
    assert outcome.prepared.authorization.allowed is False
    assert outcome.prepared.authorization.reason == "effect_not_allowed"


def test_context_turn_identity_must_match_captured_policy() -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "identity",
        "core",
        _schema("identity"),
        lambda args: calls.append(args) or "unexpected",
        effects={"read"},
    )

    with pytest.raises(ValueError, match="accepted_turn_id does not match"):
        registry.execute_shadow(
            "identity",
            {},
            context=_context(accepted_turn_id="another-turn"),
            execution_policy=_policy(),
        )

    assert calls == []


def test_shadow_api_rejects_unbound_start_time_handler_kwargs() -> None:
    registry = ToolRegistry()
    registry.register(
        "bound_inputs",
        "core",
        _schema("bound_inputs"),
        lambda _args: "unexpected",
        effects={"read"},
    )

    with pytest.raises(TypeError, match="unexpected_handler_context"):
        registry.execute_shadow(
            "bound_inputs",
            {},
            context=_context("call-no-unbound-inputs"),
            execution_policy=_policy(),
            unexpected_handler_context=object(),
        )


def test_execute_shadow_runs_async_captured_handler(monkeypatch) -> None:
    registry = ToolRegistry()
    seen = []

    async def handler(args: dict) -> str:
        await asyncio.sleep(0)
        seen.append(args)
        return "async-result"

    model_tools = types.ModuleType("model_tools")
    model_tools._run_async = asyncio.run
    model_tools._sanitize_tool_error = lambda raw: raw
    monkeypatch.setitem(sys.modules, "model_tools", model_tools)
    registry.register(
        "async_tool",
        "core",
        _schema("async_tool"),
        handler,
        is_async=True,
        effects={"read"},
    )

    outcome = registry.execute_shadow(
        "async_tool",
        {"value": 7},
        context=_context("call-async"),
        execution_policy=_policy(),
    )

    assert outcome.started is True
    assert outcome.result == "async-result"
    assert seen == [{"value": 7}]


@pytest.mark.parametrize(
    "bad_args",
    [
        ["not", "an", "object"],
        {"value": object()},
        {1: "non-string-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
    ],
    ids=[
        "non-dict",
        "non-json-value",
        "non-string-key",
        "nan",
        "positive-infinity",
        "negative-infinity",
    ],
)
def test_malformed_non_dict_and_non_finite_args_fail_closed(bad_args) -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "strict",
        "core",
        _schema("strict"),
        lambda args: calls.append(args) or "unexpected",
        effects={"read"},
    )

    outcome = registry.execute_shadow(
        "strict",
        bad_args,
        context=_context("call-invalid"),
        execution_policy=_policy(),
    )

    assert outcome.started is False
    assert calls == []
    assert outcome.prepared.canonical_args_json is None
    assert outcome.prepared.args_digest is None
    assert outcome.prepared.preparation_error.startswith("invalid_arguments:")
    assert Effect(EffectKind.UNKNOWN) in outcome.prepared.resolved_effects
    assert outcome.prepared.authorization.allowed is False
    assert outcome.prepared.authorization.reason == "unknown_effect"
    assert json.loads(outcome.result)["shadow_status"] == "invalid_arguments"


def test_legacy_dispatch_still_receives_non_dict_args_unchanged() -> None:
    registry = ToolRegistry()
    seen = []

    def handler(args) -> str:
        seen.append(args)
        return "legacy-result"

    registry.register("legacy", "core", _schema("legacy"), handler)
    raw_args = ["legacy", "shape"]

    assert registry.dispatch("legacy", raw_args) == "legacy-result"
    assert seen == [raw_args]


def test_resolver_failure_adds_unknown_and_does_not_block_shadow_handler() -> None:
    registry = ToolRegistry()
    calls = []

    def broken_resolver(_args: dict):
        raise RuntimeError("boom")

    def handler(args: dict) -> str:
        calls.append(args)
        return "handler-ran"

    registry.register(
        "broken_resolver",
        "core",
        _schema("broken_resolver"),
        handler,
        effects={"read"},
        effect_resolver=broken_resolver,
    )

    outcome = registry.execute_shadow(
        "broken_resolver",
        {},
        context=_context("call-resolver"),
        execution_policy=_policy(),
    )

    assert outcome.started is True
    assert outcome.result == "handler-ran"
    assert calls == [{}]
    assert outcome.prepared.resolved_effects == frozenset({
        Effect(EffectKind.READ),
        Effect(EffectKind.UNKNOWN),
    })
    assert outcome.prepared.effect_resolution_error == (
        "resolver_exception:RuntimeError:boom"
    )
    assert outcome.prepared.authorization.allowed is False


def test_replacement_before_start_denies_prepared_call() -> None:
    registry = ToolRegistry()
    old_calls = []
    new_calls = []

    def old_handler(args: dict) -> str:
        old_calls.append(args)
        return "old"

    def new_handler(args: dict) -> str:
        new_calls.append(args)
        return "new"

    registry.register("race", "core", _schema("race"), old_handler, effects={"read"})
    prepared = registry._prepare_shadow_call(
        "race",
        {},
        _context("call-replace-before-start"),
        _policy(),
    )
    registry.register("race", "core", _schema("race"), new_handler, effects={"read"})

    outcome = registry._start_prepared_shadow(prepared)

    assert outcome.started is False
    assert outcome.stale_reason == "entry_replaced"
    assert old_calls == []
    assert new_calls == []
    assert json.loads(outcome.result)["shadow_status"] == "stale_registration"


def test_deregister_before_start_denies_prepared_call() -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "race",
        "core",
        _schema("race"),
        lambda args: calls.append(args) or "unexpected",
        effects={"read"},
    )
    prepared = registry._prepare_shadow_call(
        "race",
        {},
        _context("call-deregister-before-start"),
        _policy(),
    )
    registry.deregister("race")

    outcome = registry._start_prepared_shadow(prepared)

    assert outcome.started is False
    assert outcome.stale_reason == "deregistered"
    assert calls == []


def test_unrelated_generation_mutation_does_not_invalidate_entry() -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "target",
        "core",
        _schema("target"),
        lambda args: calls.append(args) or "target-result",
        effects={"read"},
    )
    prepared = registry._prepare_shadow_call(
        "target",
        {"x": 1},
        _context("call-unrelated-mutation"),
        _policy(),
    )
    registry.register(
        "unrelated",
        "core",
        _schema("unrelated"),
        lambda _args: "unrelated-result",
        effects={"read"},
    )

    outcome = registry._start_prepared_shadow(prepared)

    assert outcome.started is True
    assert outcome.result == "target-result"
    assert calls == [{"x": 1}]
    assert outcome.start_generation > prepared.registry_generation


def test_replacement_after_start_linearization_runs_captured_old_handler() -> None:
    registry = ToolRegistry()
    entered_handler = threading.Event()
    release_handler = threading.Event()
    old_calls = []
    new_calls = []
    outcomes = []

    def old_handler(args: dict) -> str:
        old_calls.append(args)
        entered_handler.set()
        assert release_handler.wait(timeout=5)
        return "captured-old"

    def new_handler(args: dict) -> str:
        new_calls.append(args)
        return "replacement"

    registry.register("race", "core", _schema("race"), old_handler, effects={"read"})
    prepared = registry._prepare_shadow_call(
        "race",
        {"x": 1},
        _context("call-linearized"),
        _policy(),
    )
    worker = threading.Thread(
        target=lambda: outcomes.append(registry._start_prepared_shadow(prepared)),
        daemon=True,
    )
    worker.start()
    assert entered_handler.wait(timeout=5)

    registry.register("race", "core", _schema("race"), new_handler, effects={"read"})
    release_handler.set()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert len(outcomes) == 1
    assert outcomes[0].started is True
    assert outcomes[0].result == "captured-old"
    assert old_calls == [{"x": 1}]
    assert new_calls == []
    assert registry.get_entry("race").handler is new_handler
    assert outcomes[0].start_generation < registry._generation
