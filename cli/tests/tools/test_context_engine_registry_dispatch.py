"""A2b lane-3 migration tests — every context-engine (``lcm_*``) tool routes
through the atomic registry shadow boundary
(``model_tools.dispatch_agent_owned_registry_tool``).

The agent loop historically dispatched context-engine tools straight into
``context_compressor.handle_tool_call(name, args, messages=messages)``,
bypassing the atomic shadow boundary.  This lane moves them onto the common
adapter via ``dispatch_context_engine_tool_via_registry``.  These tests prove:

* byte-identical caller behavior (routed == direct) on the legacy fallback
  path — including the live ``messages`` list being mutated by reference and
  the exact ``{"error": "Context engine tool '<name>' failed: …"}`` wrapper —
  and correct atomic-boundary traversal with a durable identity;
* truthful, fail-closed effect declarations — every context-engine tool is
  registered UNKNOWN (no proven pure-read path);
* companion hygiene (the live engine AND the messages list ride ONLY through
  the dispatch-scoped companion, never through model args or handler kwargs,
  and are cleared after — including on handler exception);
* the name-collision guard (a context-engine tool name colliding with an
  unrelated toolset's entry stays on the direct engine path, never misroutes);
* cross-engine isolation under concurrent dispatch;
* fail-closed refusal under exact Realtor Beta (UNKNOWN effect + missing
  durable identity), and stale-registration fail-closed.

The file lives under ``tests/tools/`` with a ``registry``/``dispatch``
substring so the effect/policy/shadow/registry sweep picks it up.
"""

import concurrent.futures
import contextvars
import json
import threading

import pytest
from unittest.mock import MagicMock

from agent.context_engine_dispatch import (
    CONTEXT_ENGINE_TOOLSET,
    _CONTEXT_ENGINE_COMPANION,
    dispatch_context_engine_tool_via_registry,
    ensure_registry_routed_context_engine_tool,
    ensure_registry_routed_context_engine_tools,
)
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
def _clean_context_engine_registry():
    """Deregister every ``context-engine`` entry a test created.

    Registration is process-global; tests build fake engines, so any
    registration created inside one test must be removed afterward to keep the
    shared registry clean for the rest of the suite.
    """

    def _ce_entries() -> set:
        return {
            name
            for name, toolset in registry.get_tool_to_toolset_map().items()
            if toolset == CONTEXT_ENGINE_TOOLSET
        }

    pre_existing = _ce_entries()
    yield
    for name in _ce_entries() - pre_existing:
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


_LCM_GREP_SCHEMA = {
    "name": "lcm_grep",
    "description": "grep the compacted context DAG",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    },
}
_LCM_EXPAND_SCHEMA = {
    "name": "lcm_expand",
    "description": "expand a compacted context node",
    "parameters": {
        "type": "object",
        "properties": {"node": {"type": "string"}},
    },
}


class FakeContextEngine:
    """Minimal context engine exposing ``lcm_*`` tools for routing tests.

    ``handle_tool_call`` records its inputs, optionally appends to the live
    ``messages`` list (proving reference binding, i.e. live ingestion), and
    can be told to raise (proving the byte-identical error wrapper).
    """

    def __init__(self, tools=None, marker=None, ingest=False, raises=None):
        self._tools = tools if tools is not None else [_LCM_GREP_SCHEMA, _LCM_EXPAND_SCHEMA]
        self._marker = marker
        self._ingest = ingest
        self._raises = raises
        self.calls = []

    def get_tool_schemas(self):
        return self._tools

    def handle_tool_call(self, name, args, **kwargs):
        messages = kwargs.get("messages")
        self.calls.append(
            (
                name,
                dict(args) if isinstance(args, dict) else args,
                "messages" in kwargs,
                messages is not None,
            )
        )
        if self._raises is not None:
            raise self._raises
        if self._ingest and isinstance(messages, list):
            messages.append({"role": "system", "content": f"ingested:{name}"})
        if self._marker is not None:
            return json.dumps({"marker": self._marker, "tool": name})
        return json.dumps({"handled": name, "args": args})


def _legacy_branch_result(engine, messages, name, args):
    """Reproduce the exact pre-migration agent-loop branch payload."""
    try:
        return engine.handle_tool_call(name, args, messages=messages)
    except Exception as tool_error:  # noqa: BLE001 - mirrors the branch verbatim
        return json.dumps(
            {"error": f"Context engine tool '{name}' failed: {tool_error}"}
        )


# ---------------------------------------------------------------------------
# Registration + truthful effects
# ---------------------------------------------------------------------------


class TestContextEngineToolRegistration:
    def test_announced_tools_registered_under_hidden_toolset(self):
        engine = FakeContextEngine()
        ensure_registry_routed_context_engine_tools(engine)
        for name in ("lcm_grep", "lcm_expand"):
            entry = registry.get_entry(name)
            assert entry is not None, name
            assert entry.toolset == CONTEXT_ENGINE_TOOLSET

    def test_hidden_toolset_keeps_tools_out_of_model_schemas(self):
        import toolsets

        ensure_registry_routed_context_engine_tools(FakeContextEngine())
        assert CONTEXT_ENGINE_TOOLSET not in toolsets.get_all_toolsets()
        assert not set(toolsets.resolve_toolset("all")).intersection(
            {"lcm_grep", "lcm_expand"}
        )

    def test_context_engine_tools_are_declared_unknown(self):
        ensure_registry_routed_context_engine_tools(FakeContextEngine())
        # No pure-read path is proven for context-engine tools (they mutate
        # compression state by design), so they are UNKNOWN — restricted
        # policies fail closed.
        for name in ("lcm_grep", "lcm_expand"):
            metadata = registry.get_effect_metadata(name)
            assert metadata["declared"] is False, name
            assert metadata["has_resolver"] is False, name
            assert sorted(str(e) for e in metadata["effects"]) == ["unknown"], name
            assert sorted(
                str(e) for e in registry.resolve_effects(name, {"query": "x"})
            ) == ["unknown"], name

    def test_registration_is_idempotent_across_engines(self):
        ensure_registry_routed_context_engine_tools(FakeContextEngine())
        first = {
            name: registry.get_entry(name).entry_id
            for name in ("lcm_grep", "lcm_expand")
        }
        # A second agent's engine must not rotate the registration identity.
        ensure_registry_routed_context_engine_tools(FakeContextEngine())
        for name, entry_id in first.items():
            assert registry.get_entry(name).entry_id == entry_id

    def test_malformed_schema_is_skipped(self):
        # Non-dict schema entry: registration for it is skipped, and a valid
        # sibling still registers.
        engine = FakeContextEngine(tools=["not-a-dict", _LCM_GREP_SCHEMA])
        ensure_registry_routed_context_engine_tools(engine)
        assert registry.get_entry("lcm_grep") is not None

    def test_name_collision_with_core_tool_keeps_direct_engine_path(self):
        """A context-engine tool whose name collides with an unrelated
        toolset's registry entry must NOT dispatch to that entry — it stays on
        the direct engine path, byte-identical to the pre-migration branch."""
        core_calls = []

        def _core_handler(args, **kwargs):
            core_calls.append(args)
            return json.dumps({"who": "core-tool"})

        registry.register(
            name="lcm_grep",
            toolset="_test-core-collision",
            schema={
                "name": "lcm_grep",
                "description": "unrelated core tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=_core_handler,
        )
        try:
            engine = FakeContextEngine()
            ensure_registry_routed_context_engine_tools(engine)
            # Registration must not have hijacked the core entry.
            assert registry.get_entry("lcm_grep").toolset == "_test-core-collision"
            msgs = [{"role": "user", "content": "hi"}]
            routed = json.loads(
                dispatch_context_engine_tool_via_registry(
                    engine,
                    msgs,
                    "lcm_grep",
                    {"query": "x"},
                    task_id="t",
                    session_id="s",
                    tool_call_id="c",
                )
            )
            # The ENGINE ran, not the colliding core tool.
            assert routed["handled"] == "lcm_grep"
            assert core_calls == []
            assert engine.calls == [("lcm_grep", {"query": "x"}, True, True)]
        finally:
            registry.deregister("lcm_grep")


# ---------------------------------------------------------------------------
# Parity — routed dispatch is byte-identical to the direct engine path
# ---------------------------------------------------------------------------


class TestContextEngineToolParity:
    def test_routed_dispatch_matches_direct_engine_dispatch(self):
        engine = FakeContextEngine()
        args = {"query": "alice"}
        direct = engine.handle_tool_call("lcm_grep", dict(args), messages=[])
        routed = dispatch_context_engine_tool_via_registry(
            FakeContextEngine(),
            [],
            "lcm_grep",
            dict(args),
            task_id="task-ce",
            session_id="session-ce",
            tool_call_id="call-ce-parity",
        )
        assert routed == direct
        assert json.loads(routed)["handled"] == "lcm_grep"

    def test_routed_dispatch_mutates_live_messages_by_reference(self):
        """The handler ingests into the SAME messages list the agent loop
        owns — the list rides the companion by reference, not serialized."""
        engine = FakeContextEngine(ingest=True)
        msgs = [{"role": "user", "content": "hi"}]
        legacy_engine = FakeContextEngine(ingest=True)
        legacy_msgs = [{"role": "user", "content": "hi"}]

        routed = dispatch_context_engine_tool_via_registry(
            engine,
            msgs,
            "lcm_grep",
            {"query": "x"},
            task_id="t",
            session_id="s",
            tool_call_id="c",
        )
        legacy = _legacy_branch_result(
            legacy_engine, legacy_msgs, "lcm_grep", {"query": "x"}
        )
        assert routed == legacy
        # Both paths appended the ingested message in place.
        assert msgs == legacy_msgs
        assert msgs[-1] == {"role": "system", "content": "ingested:lcm_grep"}
        assert len(msgs) == 2

    def test_exception_wrapper_is_byte_identical_to_legacy_branch(self):
        """When the engine's ``handle_tool_call`` raises, the routed payload is
        byte-identical to the legacy branch's
        ``{"error": "Context engine tool '<name>' failed: …"}``."""
        boom = RuntimeError("boom")
        routed = dispatch_context_engine_tool_via_registry(
            FakeContextEngine(raises=boom),
            [],
            "lcm_grep",
            {"query": "x"},
            task_id="t",
            session_id="s",
            tool_call_id="c",
        )
        legacy = _legacy_branch_result(
            FakeContextEngine(raises=boom), [], "lcm_grep", {"query": "x"}
        )
        assert routed == legacy
        assert json.loads(routed) == {
            "error": "Context engine tool 'lcm_grep' failed: boom"
        }

    def test_routed_dispatch_traverses_atomic_boundary_with_unknown_effects(
        self, set_policy
    ):
        engine = FakeContextEngine()
        ensure_registry_routed_context_engine_tools(engine)
        policy = ExecutionPolicy.for_mode("turn-lcm-routing", "read_only")
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
                dispatch_context_engine_tool_via_registry(
                    engine,
                    [],
                    "lcm_grep",
                    {"query": "bob"},
                    task_id="task-ce",
                    session_id="session-ce",
                    tool_call_id="call-ce-shadow",
                )
            )
        finally:
            registry.execute_shadow = real_execute_shadow

        # Observational (non-enforcing outside Beta): the handler still runs
        # even though the effect surface is UNKNOWN.
        assert result["handled"] == "lcm_grep"
        assert captured["name"] == "lcm_grep"
        assert captured["started"] is True
        assert captured["effects"] == ["unknown"]
        assert captured["context"].session_id == "session-ce"
        assert captured["context"].invocation_id == "call-ce-shadow"
        assert captured["context"].accepted_turn_id == "turn-lcm-routing"
        assert captured["context"].policy_revision == 5
        assert len(captured["args_digest"]) == 64


# ---------------------------------------------------------------------------
# Companion hygiene / smuggled state
# ---------------------------------------------------------------------------


class TestContextEngineToolCompanionHygiene:
    def test_binding_cleared_after_routed_dispatch(self):
        dispatch_context_engine_tool_via_registry(
            FakeContextEngine(),
            [],
            "lcm_grep",
            {"query": "x"},
            task_id="t",
            session_id="s",
            tool_call_id="c",
        )
        assert _CONTEXT_ENGINE_COMPANION.get() is None

    def test_registered_handler_without_binding_returns_typed_error(self):
        """The global registration is inert without a dispatch-scoped engine:
        a post-dispatch legacy ``registry.dispatch`` never reaches an engine.
        """
        ensure_registry_routed_context_engine_tools(FakeContextEngine())
        result = json.loads(registry.dispatch("lcm_grep", {"query": "x"}))
        assert "no active context engine" in result["error"]
        assert _CONTEXT_ENGINE_COMPANION.get() is None

    def test_binding_cleared_even_when_engine_raises(self):
        result = json.loads(
            dispatch_context_engine_tool_via_registry(
                FakeContextEngine(raises=RuntimeError("boom")),
                [],
                "lcm_grep",
                {"query": "x"},
                task_id="t",
                session_id="s",
                tool_call_id="c",
            )
        )
        assert "failed" in result["error"]
        assert _CONTEXT_ENGINE_COMPANION.get() is None

    def test_model_args_cannot_masquerade_as_state(self):
        """Model-controlled arguments are passed through as data only; the
        live engine + messages ride exclusively through the companion."""
        engine = FakeContextEngine()
        smuggle = {"engine": "fake", "messages": "fake", "query": "real"}
        routed = json.loads(
            dispatch_context_engine_tool_via_registry(
                engine,
                [],
                "lcm_grep",
                dict(smuggle),
                task_id="t",
                session_id="s",
                tool_call_id="c",
            )
        )
        assert routed["handled"] == "lcm_grep"
        # The args reach the engine verbatim; nothing is treated as state, and
        # the real messages list (not the smuggled string) was passed.
        assert engine.calls == [("lcm_grep", smuggle, True, True)]

    def test_smuggled_handler_kwargs_never_reach_the_engine(self):
        """A callable/object forced through dispatch handler kwargs (task_id/
        user_task/enabled_tools JSON snapshot) never reaches the handler seam:
        the handler ignores ``**_kwargs`` and reads state from the companion.
        """
        engine = FakeContextEngine()
        ensure_registry_routed_context_engine_tools(engine)
        # Invoke the registered handler with a bogus kwarg forced in; without a
        # binding it must still fail closed to the typed error, never using the
        # smuggled kwarg as engine/messages.
        raw = json.loads(
            registry.get_entry("lcm_grep").handler(
                {"query": "x"}, messages=["smuggled"], engine="smuggled"
            )
        )
        assert "no active context engine" in raw["error"]
        assert engine.calls == []


# ---------------------------------------------------------------------------
# Fail-closed: stale registration + exact Realtor Beta
# ---------------------------------------------------------------------------


class TestContextEngineToolFailClosed:
    def test_stale_registration_fails_closed_before_engine(
        self, monkeypatch, set_policy
    ):
        engine = FakeContextEngine()
        engine.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        ensure_registry_routed_context_engine_tool("lcm_grep", _LCM_GREP_SCHEMA)
        policy = ExecutionPolicy.for_mode("turn-lcm-stale", "read_only")
        set_policy(policy, 6)
        entry = registry.get_entry("lcm_grep")
        real_prepare = registry.prepare_shadow

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "lcm_grep":
                registry.register(
                    name="lcm_grep",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_context_engine_tool_via_registry(
                engine,
                [],
                "lcm_grep",
                {"query": "x"},
                task_id="t",
                session_id="s",
                tool_call_id="call-ce-stale",
            )
        )
        assert result["shadow_status"] == "stale_registration"
        engine.handle_tool_call.assert_not_called()

    def test_unknown_effects_fail_closed_under_beta_enforcement(
        self, monkeypatch, set_policy
    ):
        """If enforcement reaches these tools with a durable identity, the
        UNKNOWN declaration is refused BEFORE the engine runs."""
        engine = FakeContextEngine()
        engine.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        # Register in stable, then enforce Beta for the dispatch itself.
        ensure_registry_routed_context_engine_tool("lcm_grep", _LCM_GREP_SCHEMA)
        assert registry.get_entry("lcm_grep") is not None
        policy = ExecutionPolicy.for_mode("turn-lcm-beta", "read_only")
        set_policy(policy, 4)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        result = json.loads(
            dispatch_context_engine_tool_via_registry(
                engine,
                [],
                "lcm_grep",
                {"query": "x"},
                task_id="t",
                session_id="session-ce",
                tool_call_id="call-ce-beta",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        engine.handle_tool_call.assert_not_called()

    def test_missing_durable_identity_fails_closed_under_beta(
        self, monkeypatch, set_policy
    ):
        """Under exact Beta a missing durable identity (no tool_call_id) is
        refused with the context block, before the engine runs."""
        engine = FakeContextEngine()
        engine.handle_tool_call = MagicMock(return_value='{"unexpected":true}')
        ensure_registry_routed_context_engine_tool("lcm_grep", _LCM_GREP_SCHEMA)
        policy = ExecutionPolicy.for_mode("turn-lcm-noid", "read_only")
        set_policy(policy, 3)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        result = json.loads(
            dispatch_context_engine_tool_via_registry(
                engine,
                [],
                "lcm_grep",
                {"query": "x"},
                task_id="t",
                session_id="session-ce",
                tool_call_id="",  # missing durable identity
            )
        )
        assert result["shadow_status"] == "effect_context_block"
        engine.handle_tool_call.assert_not_called()

    def test_runtime_beta_preflight_blocks_registered_lcm(
        self, monkeypatch, set_policy
    ):
        """The real runtime exact-Beta path routes ``lcm_*`` through
        ``_invoke_tool`` (the sequential ``elif exact_beta`` branch), whose
        preflight is ``exact_beta_tool_preflight_block`` — the SAME
        ``_prepare_exact_beta_registry_call`` the adapter uses.  Registering the
        tool UNKNOWN makes that shared preflight fail it closed BEFORE any
        branch/handler runs, so the bypass is closed under Beta without a
        redundant ``_invoke_tool`` branch (context-engine was never dispatched
        through ``_invoke_tool``).
        """
        from model_tools import exact_beta_tool_preflight_block

        ensure_registry_routed_context_engine_tool("lcm_grep", _LCM_GREP_SCHEMA)
        policy = ExecutionPolicy.for_mode("turn-lcm-runtime-preflight", "read_only")
        set_policy(policy, 7)
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        block = exact_beta_tool_preflight_block(
            "lcm_grep",
            {"query": "x"},
            session_id="session-ce",
            tool_call_id="call-ce-runtime-pf",
        )
        assert block is not None
        assert json.loads(block)["shadow_status"] == "effect_policy_block"


# ---------------------------------------------------------------------------
# Concurrency isolation — the companion holds a shared, mutable engine + list
# ---------------------------------------------------------------------------


class TestContextEngineToolConcurrencyIsolation:
    def test_cross_engine_isolation_under_concurrent_dispatch(self):
        """Two engines dispatching the same tool name on two worker threads
        each resolve THEIR OWN engine + messages through the companion while
        both are simultaneously inside the handler (barrier held mid-engine)."""
        barrier = threading.Barrier(2, timeout=5)

        class _BarrierEngine(FakeContextEngine):
            def __init__(self, marker):
                super().__init__(marker=marker)
                self._marker_barrier = barrier

            def handle_tool_call(self, name, args, **kwargs):
                messages = kwargs.get("messages")
                # Block so both dispatches are mid-handler at the same instant.
                self._marker_barrier.wait()
                # Prove each thread sees its OWN messages list.
                if isinstance(messages, list):
                    messages.append(self._marker)
                return json.dumps({"marker": self._marker})

        engine_a = _BarrierEngine("A")
        engine_b = _BarrierEngine("B")
        engines = {"a": engine_a, "b": engine_b}
        msg_lists = {"a": ["a0"], "b": ["b0"]}

        def worker(tag):
            return dispatch_context_engine_tool_via_registry(
                engines[tag],
                msg_lists[tag],
                "lcm_grep",
                {"query": tag},
                task_id="t",
                session_id=f"session-{tag}",
                tool_call_id=f"call-{tag}",
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="ce-iso"
        ) as pool:
            futures = {}
            for tag in ("a", "b"):
                ctx = contextvars.copy_context()
                futures[tag] = pool.submit(ctx.run, worker, tag)
            results = {
                tag: json.loads(f.result(timeout=10)) for tag, f in futures.items()
            }

        # Thread a routed to engine a (marker "A"), b to "B".
        assert results["a"]["marker"] == "A"
        assert results["b"]["marker"] == "B"
        # Each thread ingested into its own messages list, never the other's.
        assert msg_lists["a"] == ["a0", "A"]
        assert msg_lists["b"] == ["b0", "B"]
        assert _CONTEXT_ENGINE_COMPANION.get() is None
