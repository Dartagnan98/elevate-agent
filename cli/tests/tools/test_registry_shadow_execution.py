"""Tests for the atomic registry shadow-execution primitive."""

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
    handler_calls = []

    def resolve(args: dict):
        resolver_args.append(args)
        return {"read"}

    def handler(args: dict, **kwargs) -> str:
        handler_calls.append((args, kwargs))
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
    original_handler_kwargs = {
        "task_id": "task-snapshot",
        "user_task": None,
        "enabled_tools": ["skills_list"],
    }
    token = set_current_execution_policy(policy)
    try:
        prepared = registry._prepare_shadow_call(
            "snapshot",
            original_args,
            _context("call-snapshot", policy_revision=3),
            handler_kwargs=original_handler_kwargs,
        )
    finally:
        reset_current_execution_policy(token)

    original_args["b"].append(3)
    original_handler_kwargs["enabled_tools"].append("terminal")
    original_handler_kwargs["task_id"] = "mutated"
    outcome = registry._start_prepared_shadow(prepared)
    expected_json = '{"a":1,"b":[2]}'
    expected_handler_kwargs_json = (
        '{"enabled_tools":["skills_list"],'
        '"task_id":"task-snapshot","user_task":null}'
    )

    assert outcome.started is True
    assert json.loads(outcome.result) == {"a": 1, "b": [2]}
    assert resolver_args == [{"a": 1, "b": [2]}]
    assert handler_calls == [
        (
            {"a": 1, "b": [2]},
            {
                "enabled_tools": ["skills_list"],
                "task_id": "task-snapshot",
                "user_task": None,
            },
        )
    ]
    assert prepared.canonical_args_json == expected_json
    assert prepared.args_digest == hashlib.sha256(expected_json.encode()).hexdigest()
    assert prepared.canonical_handler_kwargs_json == expected_handler_kwargs_json
    assert prepared.handler_kwargs_digest == hashlib.sha256(
        expected_handler_kwargs_json.encode()
    ).hexdigest()
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


def test_exact_beta_terminal_denial_blocks_before_handler(monkeypatch) -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "terminal",
        "terminal",
        _schema("terminal"),
        lambda args: calls.append(args) or "unexpected",
        effects={"destructive"},
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    outcome = registry.execute_shadow(
        "terminal",
        {"command": "rm -rf /tmp/example"},
        context=_context("call-beta-terminal"),
        execution_policy=_policy(ExecutionPolicyMode.READ_ONLY),
    )

    assert outcome.started is False
    assert calls == []
    assert json.loads(outcome.result)["shadow_status"] == "effect_policy_block"


def test_exact_beta_terminal_unknown_effect_blocks_before_handler(monkeypatch) -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "terminal",
        "terminal",
        _schema("terminal"),
        lambda args: calls.append(args) or "unexpected",
        effect_resolver=lambda _args: {"unknown"},
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    outcome = registry.execute_shadow(
        "terminal",
        {"command": "opaque shell input"},
        context=_context("call-beta-terminal-unknown"),
        execution_policy=_policy(ExecutionPolicyMode.READ_ONLY),
    )

    assert outcome.started is False
    assert calls == []
    assert outcome.prepared.authorization.reason == "unknown_effect"
    assert json.loads(outcome.result)["shadow_status"] == "effect_policy_block"


def test_stable_terminal_denial_remains_observational(monkeypatch) -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "terminal",
        "terminal",
        _schema("terminal"),
        lambda args: calls.append(args) or "stable-result",
        effects={"destructive"},
    )
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)

    outcome = registry.execute_shadow(
        "terminal",
        {"command": "rm -rf /tmp/example"},
        context=_context("call-stable-terminal"),
        execution_policy=_policy(ExecutionPolicyMode.READ_ONLY),
    )

    assert outcome.started is True
    assert outcome.result == "stable-result"
    assert calls == [{"command": "rm -rf /tmp/example"}]
    assert outcome.prepared.authorization.allowed is False


def test_caught_handler_exception_has_explicit_execution_error() -> None:
    registry = ToolRegistry()

    def fail(_args):
        raise RuntimeError("handler failed")

    registry.register("failing", "core", _schema("failing"), fail, effects={"read"})

    outcome = registry.execute_shadow(
        "failing",
        {},
        context=_context("call-handler-error"),
        execution_policy=_policy(),
    )

    assert outcome.started is True
    assert outcome.execution_error == "handler_exception:RuntimeError"
    payload = json.loads(outcome.result)
    assert "handler failed" in payload["error"]
    assert "shadow_status" not in payload


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


@pytest.mark.parametrize(
    "handler_kwargs",
    [
        {"parent_agent": object()},
        {"task_id": object()},
        {"enabled_tools": ["read_file", object()]},
        {"user_task": float("nan")},
    ],
    ids=["opaque-parent-agent", "opaque-task", "opaque-enabled", "non-finite"],
)
def test_non_json_or_opaque_handler_context_never_starts(handler_kwargs) -> None:
    registry = ToolRegistry()
    calls = []
    registry.register(
        "strict_context",
        "core",
        _schema("strict_context"),
        lambda args, **kwargs: calls.append((args, kwargs)) or "unexpected",
        effects={"read"},
    )

    outcome = registry.execute_shadow(
        "strict_context",
        {},
        context=_context("call-invalid-context"),
        execution_policy=_policy(),
        handler_kwargs=handler_kwargs,
    )

    assert outcome.started is False
    assert calls == []
    assert outcome.prepared.canonical_args_json == "{}"
    assert outcome.prepared.args_digest == hashlib.sha256(b"{}").hexdigest()
    assert outcome.prepared.canonical_handler_kwargs_json is None
    assert outcome.prepared.handler_kwargs_digest is None
    assert outcome.prepared.preparation_error.startswith("invalid_handler_context:")
    assert json.loads(outcome.result)["shadow_status"] == "invalid_handler_context"


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


def test_shadow_preserves_sync_non_string_result_parity() -> None:
    registry = ToolRegistry()
    payload = {"_multimodal": True, "content": [{"type": "text", "text": "ok"}]}

    def handler(_args: dict, **_kwargs):
        return payload

    registry.register(
        "sync_multimodal",
        "core",
        _schema("sync_multimodal"),
        handler,
        effects={"read"},
    )

    legacy = registry.dispatch("sync_multimodal", {}, task_id="task-sync")
    outcome = registry.execute_shadow(
        "sync_multimodal",
        {},
        context=_context("call-sync-multimodal"),
        execution_policy=_policy(),
        handler_kwargs={"task_id": "task-sync"},
    )

    assert legacy is payload
    assert outcome.result is payload
    assert type(outcome.result) is type(legacy)


def test_shadow_preserves_async_non_string_result_parity(monkeypatch) -> None:
    registry = ToolRegistry()
    payload = [
        {"type": "text", "text": "ok"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]

    async def handler(_args: dict, **_kwargs):
        await asyncio.sleep(0)
        return payload

    model_tools = types.ModuleType("model_tools")
    model_tools._run_async = asyncio.run
    model_tools._sanitize_tool_error = lambda raw: raw
    monkeypatch.setitem(sys.modules, "model_tools", model_tools)
    registry.register(
        "async_multimodal",
        "core",
        _schema("async_multimodal"),
        handler,
        is_async=True,
        effects={"read"},
    )

    legacy = registry.dispatch("async_multimodal", {}, user_task="show it")
    outcome = registry.execute_shadow(
        "async_multimodal",
        {},
        context=_context("call-async-multimodal"),
        execution_policy=_policy(),
        handler_kwargs={"user_task": "show it"},
    )

    assert legacy is payload
    assert outcome.result is payload
    assert type(outcome.result) is type(legacy)


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


@pytest.mark.parametrize(
    "mutation",
    ["handler", "is_async", "effects", "effect_resolver"],
)
def test_direct_entry_mutation_before_start_denies_prepared_call(mutation) -> None:
    registry = ToolRegistry()
    calls = []

    def original_handler(args: dict) -> str:
        calls.append(("original", args))
        return "original"

    def original_resolver(_args: dict):
        return {"read"}

    registry.register(
        "mutable",
        "core",
        _schema("mutable"),
        original_handler,
        effects={"read"},
        effect_resolver=original_resolver,
    )
    prepared = registry._prepare_shadow_call(
        "mutable",
        {},
        _context(f"call-mutate-{mutation}"),
        _policy(),
    )
    entry = registry.get_entry("mutable")
    assert entry is not None

    if mutation == "handler":
        entry.handler = lambda args: calls.append(("replacement", args)) or "bad"
    elif mutation == "is_async":
        entry.is_async = True
    elif mutation == "effects":
        entry.effects = frozenset({Effect(EffectKind.WRITE_EXTERNAL, "crm")})
    else:
        entry.effect_resolver = lambda _args: {"write_external:crm"}

    outcome = registry._start_prepared_shadow(prepared)

    assert outcome.started is False
    assert outcome.stale_reason == "entry_mutated"
    assert calls == []
    assert json.loads(outcome.result)["shadow_status"] == "stale_registration"


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
