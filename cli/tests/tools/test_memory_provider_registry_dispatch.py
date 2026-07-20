"""A2b lane-2 migration tests — every memory-provider tool routes through the
atomic registry shadow boundary (``model_tools.dispatch_agent_owned_registry_tool``).

Wave 1 migrated only ``fact_store`` / ``fact_feedback`` (holographic memory's
two hand-classified tools); every OTHER provider tool (``hindsight_*``,
``honcho_*``, ``mem0_*``, …) still dispatched straight into
``MemoryManager.handle_tool_call``.  This lane moves those onto the common
adapter as well.  These tests prove:

* byte-identical caller behavior (routed == direct) on the legacy fallback
  path and correct atomic-boundary traversal with a durable identity;
* truthful, fail-closed effect declarations — classified tools declare
  ``write_local:memory``, every other provider tool is registered UNKNOWN;
* companion hygiene (the live manager rides ONLY through the dispatch-scoped
  companion, never through model args or handler kwargs, and is cleared after);
* cross-manager isolation under concurrent dispatch;
* inertness + fail-closed refusal under exact Realtor Beta.

The file lives under ``tests/tools/`` (with a ``registry``/``dispatch``
substring) so the effect/policy/shadow/registry sweep picks it up.
"""

import concurrent.futures
import contextvars
import json
import threading

import pytest
from unittest.mock import MagicMock

from agent.memory_manager import (
    MEMORY_PROVIDER_TOOLSET,
    MemoryManager,
    _MEMORY_MANAGER_COMPANION,
    dispatch_memory_tool_via_registry,
)
from agent.memory_provider import MemoryProvider
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_memory_provider_registry():
    """Deregister every ``memory-provider`` entry a test created.

    Registration is process-global; tests build managers with fake providers,
    so any registration created inside one test must be removed afterward to
    keep the shared registry clean for the rest of the suite.
    """
    def _memory_entries() -> set[str]:
        return {
            name
            for name, toolset in registry.get_tool_to_toolset_map().items()
            if toolset == MEMORY_PROVIDER_TOOLSET
        }

    pre_existing = _memory_entries()
    yield
    for name in _memory_entries() - pre_existing:
        registry.deregister(name)


@pytest.fixture
def set_policy():
    """Bind accepted-turn policies for a test and reset every one at teardown."""
    tokens = []

    def _set(policy, revision):
        tokens.append(set_current_execution_policy(policy, policy_revision=revision))
        return policy

    yield _set
    for token in reversed(tokens):
        reset_current_execution_policy(token)


_HINDSIGHT_RECALL_SCHEMA = {
    "name": "hindsight_recall",
    "description": "recall from hindsight memory",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    },
}
_HINDSIGHT_RETAIN_SCHEMA = {
    "name": "hindsight_retain",
    "description": "retain into hindsight memory",
    "parameters": {
        "type": "object",
        "properties": {"content": {"type": "string"}},
    },
}


class FakeExternalProvider(MemoryProvider):
    """Minimal external (non-holographic) provider for routing tests."""

    def __init__(self, name="hindsight", tools=None, result_marker=None):
        self._name = name
        self._tools = tools or [_HINDSIGHT_RECALL_SCHEMA, _HINDSIGHT_RETAIN_SCHEMA]
        self._result_marker = result_marker
        self.calls = []

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id, **kwargs):
        return None

    def get_tool_schemas(self):
        return self._tools

    def handle_tool_call(self, tool_name, args, **kwargs):
        self.calls.append((tool_name, dict(args) if isinstance(args, dict) else args))
        if self._result_marker is not None:
            return json.dumps({"marker": self._result_marker, "tool": tool_name})
        return json.dumps({"handled": tool_name, "args": args})


def _manager(provider=None):
    mgr = MemoryManager()
    provider = provider or FakeExternalProvider()
    mgr.add_provider(provider)
    return mgr, provider


# ---------------------------------------------------------------------------
# Registration + truthful effects
# ---------------------------------------------------------------------------


class TestProviderToolRegistration:
    def test_all_provider_tools_registered_under_hidden_toolset(self):
        _mgr, _provider = _manager()
        for name in ("hindsight_recall", "hindsight_retain"):
            entry = registry.get_entry(name)
            assert entry is not None, name
            assert entry.toolset == MEMORY_PROVIDER_TOOLSET

    def test_hidden_toolset_keeps_provider_tools_out_of_model_schemas(self):
        import toolsets

        _mgr, _provider = _manager()
        # The dispatch-only toolset never surfaces in enumeration.
        assert MEMORY_PROVIDER_TOOLSET not in toolsets.get_all_toolsets()
        assert not set(toolsets.resolve_toolset("all")).intersection(
            {"hindsight_recall", "hindsight_retain"}
        )

    def test_unclassified_provider_tools_are_declared_unknown(self):
        _mgr, _provider = _manager()
        # No pure-read path is proven for external provider tools, so they
        # are registered UNKNOWN (undeclared) — restricted policies fail closed.
        for name in ("hindsight_recall", "hindsight_retain"):
            metadata = registry.get_effect_metadata(name)
            assert metadata["declared"] is False, name
            assert metadata["has_resolver"] is False, name
            assert sorted(str(e) for e in metadata["effects"]) == ["unknown"], name
            assert sorted(
                str(e) for e in registry.resolve_effects(name, {"query": "x"})
            ) == ["unknown"], name

    def test_registration_is_idempotent_across_managers(self):
        _mgr_a, _pa = _manager()
        first = {
            name: registry.get_entry(name).entry_id
            for name in ("hindsight_recall", "hindsight_retain")
        }
        # A second agent's manager must not rotate the registration identity.
        _mgr_b, _pb = _manager()
        for name, entry_id in first.items():
            assert registry.get_entry(name).entry_id == entry_id

    def test_name_collision_with_core_tool_keeps_direct_provider_path(self):
        """A provider tool whose name collides with an unrelated toolset's
        registry entry must NOT dispatch to that entry — it stays on the
        direct provider path, byte-identical to the pre-migration branch."""
        core_calls = []

        def _core_handler(args, **kwargs):
            core_calls.append(args)
            return json.dumps({"who": "core-tool"})

        registry.register(
            name="hindsight_recall",
            toolset="_test-core-collision",
            schema={
                "name": "hindsight_recall",
                "description": "unrelated core tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=_core_handler,
        )
        try:
            mgr, provider = _manager()
            # Registration must not have hijacked the core entry.
            assert registry.get_entry("hindsight_recall").toolset == "_test-core-collision"
            routed = json.loads(
                dispatch_memory_tool_via_registry(
                    mgr,
                    "hindsight_recall",
                    {"query": "x"},
                    task_id="t",
                    session_id="s",
                    tool_call_id="c",
                )
            )
            # The PROVIDER ran, not the colliding core tool.
            assert routed["handled"] == "hindsight_recall"
            assert core_calls == []
            assert provider.calls == [("hindsight_recall", {"query": "x"})]
        finally:
            registry.deregister("hindsight_recall")

    def test_malformed_schema_keeps_direct_fallback(self):
        """A provider whose schema inventory raises never blocks dispatch: the
        tool stays unregistered and the wrapper falls back to the direct path.
        """
        class _BrokenProvider(FakeExternalProvider):
            def get_tool_schemas(self):
                # Non-dict schema entry: registration for this name is skipped.
                return ["not-a-dict"]

            def has_broken_inventory(self):
                return True

        mgr = MemoryManager()
        provider = _BrokenProvider()
        # _tool_to_provider indexing tolerates the bad schema list.
        mgr._tool_to_provider["hindsight_recall"] = provider
        mgr.ensure_registry_routed_tools_registered()
        assert registry.get_entry("hindsight_recall") is None
        result = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_recall",
                {"query": "x"},
                task_id="t",
                session_id="s",
                tool_call_id="c",
            )
        )
        assert result["handled"] == "hindsight_recall"
        assert provider.calls == [("hindsight_recall", {"query": "x"})]


# ---------------------------------------------------------------------------
# Parity — routed dispatch is byte-identical to the direct manager path
# ---------------------------------------------------------------------------


class TestProviderToolParity:
    def test_routed_dispatch_matches_direct_manager_dispatch(self):
        mgr, provider = _manager()
        args = {"query": "alice"}
        direct = mgr.handle_tool_call("hindsight_recall", dict(args))
        routed = dispatch_memory_tool_via_registry(
            mgr,
            "hindsight_recall",
            dict(args),
            task_id="task-mem",
            session_id="session-mem",
            tool_call_id="call-mem-parity",
        )
        assert routed == direct
        assert json.loads(routed)["handled"] == "hindsight_recall"
        # Direct + routed each invoked the provider exactly once, same inputs.
        assert provider.calls == [
            ("hindsight_recall", {"query": "alice"}),
            ("hindsight_recall", {"query": "alice"}),
        ]

    def test_routed_dispatch_traverses_atomic_boundary_with_unknown_effects(
        self, set_policy
    ):
        mgr, _provider = _manager()
        policy = ExecutionPolicy.for_mode("turn-hindsight-routing", "read_only")
        set_policy(policy, 5)
        captured = {}
        real_execute_shadow = registry.execute_shadow

        def spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["name"] = name
            captured["context"] = outcome.prepared.context
            captured["args_digest"] = outcome.prepared.args_digest
            captured["effects"] = sorted(
                str(e) for e in outcome.prepared.resolved_effects
            )
            captured["started"] = outcome.started
            return outcome

        registry.execute_shadow = spy
        try:
            result = json.loads(
                dispatch_memory_tool_via_registry(
                    mgr,
                    "hindsight_recall",
                    {"query": "bob"},
                    task_id="task-mem",
                    session_id="session-mem",
                    tool_call_id="call-mem-shadow",
                )
            )
        finally:
            registry.execute_shadow = real_execute_shadow

        # Observational (non-enforcing outside Beta): the handler still runs
        # even though the effect surface is UNKNOWN.
        assert result["handled"] == "hindsight_recall"
        assert captured["name"] == "hindsight_recall"
        assert captured["started"] is True
        assert captured["effects"] == ["unknown"]
        assert captured["context"].session_id == "session-mem"
        assert captured["context"].invocation_id == "call-mem-shadow"
        assert captured["context"].accepted_turn_id == "turn-hindsight-routing"
        assert captured["context"].policy_revision == 5
        assert len(captured["args_digest"]) == 64

    def test_manager_write_policy_still_enforced_through_routing(self):
        mgr, provider = _manager()
        provider.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        mgr.set_agent_policy("agent-x", {"write_policy": "read_only"})

        routed = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_retain",
                {"action": "add", "content": "blocked"},
                task_id="task-mem",
                session_id="session-mem",
                tool_call_id="call-mem-policy",
            )
        )
        direct = json.loads(
            mgr.handle_tool_call(
                "hindsight_retain", {"action": "add", "content": "blocked"}
            )
        )
        assert routed == direct
        assert "write policy blocks" in routed["error"]
        provider.handle_tool_call.assert_not_called()


# ---------------------------------------------------------------------------
# Companion hygiene / smuggled state
# ---------------------------------------------------------------------------


class TestProviderToolCompanionHygiene:
    def test_binding_cleared_after_routed_dispatch(self):
        mgr, _provider = _manager()
        dispatch_memory_tool_via_registry(
            mgr,
            "hindsight_recall",
            {"query": "x"},
            task_id="t",
            session_id="s",
            tool_call_id="c",
        )
        assert _MEMORY_MANAGER_COMPANION.get() is None

    def test_registered_handler_without_binding_returns_typed_error(self):
        """The global registration is inert without a dispatch-scoped manager:
        a post-dispatch legacy ``registry.dispatch`` never reaches a provider.
        """
        _mgr, provider = _manager()
        provider.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        result = json.loads(
            registry.get_entry("hindsight_recall").handler({"query": "x"})
        )
        assert "no active memory provider" in result["error"]
        provider.handle_tool_call.assert_not_called()
        assert _MEMORY_MANAGER_COMPANION.get() is None

    def test_binding_cleared_even_when_provider_raises(self):
        mgr, provider = _manager()
        provider.handle_tool_call = MagicMock(side_effect=RuntimeError("boom"))
        # handle_tool_call swallows the provider error into a typed payload.
        result = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_recall",
                {"query": "x"},
                task_id="t",
                session_id="s",
                tool_call_id="c",
            )
        )
        assert "failed" in result["error"]
        assert _MEMORY_MANAGER_COMPANION.get() is None

    def test_model_args_cannot_masquerade_as_the_manager(self):
        """Model-controlled arguments are passed through as data only; the
        live manager rides exclusively through the companion channel."""
        mgr, provider = _manager()
        smuggle = {"manager": "fake", "store": "fake", "query": "real"}
        routed = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_recall",
                dict(smuggle),
                task_id="t",
                session_id="s",
                tool_call_id="c",
            )
        )
        assert routed["handled"] == "hindsight_recall"
        # The args reach the provider verbatim; nothing is treated as state.
        assert provider.calls == [("hindsight_recall", smuggle)]


# ---------------------------------------------------------------------------
# Fail-closed: stale registration + exact Realtor Beta
# ---------------------------------------------------------------------------


class TestProviderToolFailClosed:
    def test_stale_registration_fails_closed_before_provider(
        self, monkeypatch, set_policy
    ):
        mgr, provider = _manager()
        provider.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        policy = ExecutionPolicy.for_mode("turn-hindsight-stale", "read_only")
        set_policy(policy, 6)
        entry = registry.get_entry("hindsight_recall")
        real_prepare = registry.prepare_shadow

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "hindsight_recall":
                registry.register(
                    name="hindsight_recall",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_recall",
                {"query": "x"},
                task_id="t",
                session_id="s",
                tool_call_id="call-mem-stale",
            )
        )
        assert result["shadow_status"] == "stale_registration"
        provider.handle_tool_call.assert_not_called()

    def test_provider_tool_is_inert_under_exact_beta(self, monkeypatch):
        """Under exact Realtor Beta the whole branch is skipped — the agent
        loop only enters it when ``has_tool`` is True, and that returns False.
        """
        mgr, _provider = _manager()
        assert mgr.has_tool("hindsight_recall") is True
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        assert mgr.has_tool("hindsight_recall") is False

    def test_unknown_effects_fail_closed_under_beta_enforcement(
        self, monkeypatch, set_policy
    ):
        """If enforcement ever reaches these tools with a durable identity,
        the UNKNOWN declaration is refused BEFORE the provider runs."""
        mgr, provider = _manager()
        provider.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        # Register in stable, then enforce Beta for the dispatch itself.
        assert registry.get_entry("hindsight_recall") is not None
        policy = ExecutionPolicy.for_mode("turn-hindsight-beta", "read_only")
        set_policy(policy, 4)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        result = json.loads(
            dispatch_memory_tool_via_registry(
                mgr,
                "hindsight_recall",
                {"query": "x"},
                task_id="t",
                session_id="session-mem",
                tool_call_id="call-mem-beta",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        provider.handle_tool_call.assert_not_called()


# ---------------------------------------------------------------------------
# Concurrency isolation — the companion holds a shared, mutable manager
# ---------------------------------------------------------------------------


class TestProviderToolConcurrencyIsolation:
    def test_cross_manager_isolation_under_concurrent_dispatch(self):
        """Two managers dispatching the same tool name on two worker threads
        each resolve THEIR OWN manager through the companion while both are
        simultaneously inside the handler (barrier held mid-provider)."""
        barrier = threading.Barrier(2, timeout=5)

        class _BarrierProvider(FakeExternalProvider):
            def __init__(self, marker):
                super().__init__(name="hindsight", result_marker=marker)
                self._marker_barrier = barrier

            def handle_tool_call(self, tool_name, args, **kwargs):
                # Block so both dispatches are mid-handler at the same instant.
                self._marker_barrier.wait()
                return json.dumps({"marker": self._result_marker})

        mgr_a, _pa = _manager(_BarrierProvider("A"))
        mgr_b, _pb = _manager(_BarrierProvider("B"))
        managers = {"a": mgr_a, "b": mgr_b}

        def worker(tag):
            return dispatch_memory_tool_via_registry(
                managers[tag],
                "hindsight_recall",
                {"query": tag},
                task_id="t",
                session_id=f"session-{tag}",
                tool_call_id=f"call-{tag}",
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="mem-iso"
        ) as pool:
            futures = {}
            for tag in ("a", "b"):
                ctx = contextvars.copy_context()
                futures[tag] = pool.submit(ctx.run, worker, tag)
            results = {tag: json.loads(f.result(timeout=10)) for tag, f in futures.items()}

        # Thread a routed to manager a's provider (marker "A"), b to "B".
        assert results["a"]["marker"] == "A"
        assert results["b"]["marker"] == "B"
        assert _MEMORY_MANAGER_COMPANION.get() is None
