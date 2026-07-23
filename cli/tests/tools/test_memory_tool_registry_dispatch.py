"""Parity + adversarial tests for the built-in ``memory`` agent-loop lane (A2b lane 5).

The four agent-loop built-in-``memory`` branches (``run_agent._invoke_tool``
concurrent + ``_execute_tool_calls_sequential_impl``, ``agent.tool_executor``,
``agent.agent_runtime_helpers``) used to call ``memory_tool(store=self._memory_store)``
directly and then fire the external-provider bridge
(``MemoryManager.on_memory_write``) inline in the branch, bypassing the atomic
shadow-dispatch boundary and sourcing the per-agent ``MemoryStore`` through the
registered handler's ``kw.get("store")`` seam — a channel the shadow path's
JSON-only handler-kwargs snapshot can never carry.  They now route through
``tools.memory_tool.dispatch_builtin_memory_via_registry`` onto
``model_tools.dispatch_agent_owned_registry_tool``, binding the store + manager +
bridge metadata through a module-level :class:`DispatchCompanion` for exactly one
dispatch.

These tests prove byte-identical caller behavior (the Stable bar) and lock the
two migration traps the recipe calls out for this lane:

  1. the ``on_memory_write`` provider bridge is a hidden POST-result effect and
     now runs INSIDE the registered handler — it fires for add/replace on an
     allowed dispatch and NEVER on a blocked / stale / denied dispatch whose
     handler never starts; and

  2. the store is reachable only through the companion, only inside one dispatch,
     and never on a blocked/stale/denied path or from smuggled arguments.

Effect honesty: the registration is UNKNOWN (``effects=None``) because every
valid memory action writes and the provider bridge reaches an unbounded external
surface — so a restricted accepted turn fails closed under exact Realtor Beta.

The ``_memory_policy_block`` gate stays in the CALLER (it diverges across the four
copies), so its "fires before any effect" invariant is proven at the live branch
in ``tests/run_agent/test_run_agent.py``; here the seam under attack is the memory
store + provider bridge specifically.  The adapter's own hygiene is covered by
``tests/tools/test_agent_owned_registry_dispatch.py``.
"""

import concurrent.futures
import contextvars
import json
import threading
from unittest.mock import patch

import pytest

from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry
import tools.memory_tool as memory_module
from tools.memory_tool import (
    MemoryStore,
    _MEMORY_TOOL_COMPANION,
    _registered_memory_tool_handler,
    dispatch_builtin_memory_via_registry,
    memory_tool,
)


_ADD_ARGS = {"action": "add", "target": "memory", "content": "durable fact"}
_REMOVE_ARGS = {"action": "remove", "target": "memory", "old_text": "durable fact"}


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus a durable revision."""
    policy = ExecutionPolicy.for_mode("turn-memory-lane", "read_only")
    token = set_current_execution_policy(policy, policy_revision=9)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class _RecordingStore:
    """Minimal ``MemoryStore``-shaped fake: records writes, no disk.

    ``memory_tool`` validates target/action then calls ``store.<action>`` and
    ``json.dumps`` the returned dict.  A deterministic return makes routed and
    direct dispatch byte-comparable without touching the shared memories dir.
    """

    def __init__(self, tag="store"):
        self.tag = tag
        self.calls = []

    def add(self, target, content):
        self.calls.append(("add", target, content))
        return {"success": True, "op": "add", "target": target, "content": content}

    def replace(self, target, old_text, new_content):
        self.calls.append(("replace", target, old_text, new_content))
        return {"success": True, "op": "replace", "target": target}

    def remove(self, target, old_text):
        self.calls.append(("remove", target, old_text))
        return {"success": True, "op": "remove", "target": target}


class _RecordingManager:
    """Fake ``MemoryManager`` capturing the ``on_memory_write`` bridge calls."""

    def __init__(self):
        self.writes = []

    def on_memory_write(self, action, target, content, metadata=None):
        self.writes.append((action, target, content, metadata))


# =========================================================================
# Parity (recipe step 6)
# =========================================================================


@pytest.fixture(autouse=True)
def _local_memory_provider(monkeypatch):
    """Pin the config-bounded memory resolver to its local branch for every
    test in this module. Other files' ELEVATE_HOME fixtures can leave an
    external provider configured, flipping resolve_effects to UNKNOWN and
    making dispatch tests order-dependent under xdist."""
    import elevate_cli.config as _config_mod

    real = _config_mod.load_config

    def _local(*args, **kwargs):
        cfg = dict(real(*args, **kwargs))
        cfg["memory"] = dict(cfg.get("memory") or {})
        cfg["memory"]["provider"] = ""
        return cfg

    monkeypatch.setattr(_config_mod, "load_config", _local)


class TestMemoryRegistryDispatchParity:
    def test_legacy_fallback_matches_direct_call_and_runs_impl_once(self):
        """No durable identity → legacy ``registry.dispatch`` payload, and the
        underlying ``memory_tool`` implementation runs exactly once with the
        model args plus the companion-bound store (never a kw store)."""
        routed_store = _RecordingStore("routed")
        direct_store = _RecordingStore("direct")

        calls = []
        real_memory_tool = memory_tool

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real_memory_tool(*args, **kwargs)

        with patch("tools.memory_tool.memory_tool", spy):
            routed = dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS), store=routed_store
            )

        direct = real_memory_tool(
            action="add", target="memory", content="durable fact", store=direct_store
        )

        assert routed == direct
        assert json.loads(routed)["op"] == "add"
        # Impl invoked exactly once, carrying the bound store — never kw store.
        assert len(calls) == 1
        assert calls[0]["store"] is routed_store
        assert routed_store.calls == direct_store.calls

    def test_routed_dispatch_traverses_atomic_boundary(self, monkeypatch):
        """Durable identity → the call traverses ``execute_shadow`` with the
        frozen session/invocation/turn identity, a 64-char args digest, the
        truthful UNKNOWN effect, and a started handler that writes the bound
        store."""
        store = _RecordingStore()
        policy = ExecutionPolicy.for_mode("turn-memory-routing", "read_only")
        token = set_current_execution_policy(policy, policy_revision=11)
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

        monkeypatch.setattr(registry, "execute_shadow", spy)
        try:
            result = json.loads(
                dispatch_builtin_memory_via_registry(
                    dict(_ADD_ARGS),
                    store=store,
                    task_id="task-memory",
                    session_id="session-memory",
                    tool_call_id="call-memory-shadow",
                )
            )
        finally:
            reset_current_execution_policy(token)

        assert result["op"] == "add"
        assert captured["name"] == "memory"
        assert captured["started"] is True
        assert captured["effects"] == ["write_local:memory"]  # config-bounded: local provider
        assert captured["context"].session_id == "session-memory"
        assert captured["context"].invocation_id == "call-memory-shadow"
        assert captured["context"].accepted_turn_id == "turn-memory-routing"
        assert captured["context"].policy_revision == 11
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64
        # The bound store — not any ambient one — was actually written.
        assert store.calls == [("add", "memory", "durable fact")]

    def test_routed_dispatch_writes_real_memory_store(self, monkeypatch, tmp_path):
        """End-to-end through the boundary with a real ``MemoryStore``: the add
        persists to the isolated MEMORY.md exactly as the direct branch did."""
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        store = MemoryStore()
        store.load_from_disk()
        policy = ExecutionPolicy.for_mode("turn-memory-real", "read_only")
        token = set_current_execution_policy(policy, policy_revision=4)
        try:
            result = json.loads(
                dispatch_builtin_memory_via_registry(
                    dict(_ADD_ARGS),
                    store=store,
                    session_id="session-memory-real",
                    tool_call_id="call-memory-real",
                )
            )
        finally:
            reset_current_execution_policy(token)

        assert result["success"] is True
        assert "durable fact" in store.memory_entries
        on_disk = (tmp_path / "memories" / "MEMORY.md").read_text(encoding="utf-8")
        assert "durable fact" in on_disk

    def test_legacy_dispatch_outside_binding_returns_not_available(self):
        """A registered-handler call reached WITHOUT the companion binding
        (legacy ``registry.dispatch`` without an agent, plugin dispatch,
        hallucinated calls) returns memory's byte-identical "not available"
        typed error — the pre-migration lambda's ``kw.get("store")`` was likewise
        ``None`` off the agent loop — and never touches a live store."""
        assert _MEMORY_TOOL_COMPANION.get() is None
        result = json.loads(registry.dispatch("memory", dict(_ADD_ARGS)))
        assert result["success"] is False
        assert "Memory is not available" in result["error"]
        assert _MEMORY_TOOL_COMPANION.get() is None


# =========================================================================
# on_memory_write provider bridge (recipe step 7 #6)
# =========================================================================


class TestMemoryProviderBridge:
    def test_bridge_fires_inside_boundary_for_add(self, accepted_turn_policy):
        """add through the boundary fires ``on_memory_write`` exactly once with
        the (action, target, content, metadata) the caller supplied."""
        store = _RecordingStore()
        manager = _RecordingManager()
        meta = {"session_id": "session-bridge", "agent_id": "agent-7"}

        dispatch_builtin_memory_via_registry(
            dict(_ADD_ARGS),
            store=store,
            manager=manager,
            metadata_factory=lambda: meta,
            session_id="session-bridge",
            tool_call_id="call-bridge-add",
        )

        assert manager.writes == [("add", "memory", "durable fact", meta)]

    def test_bridge_fires_for_replace(self, accepted_turn_policy):
        store = _RecordingStore()
        manager = _RecordingManager()
        meta = {"session_id": "s", "agent_id": "a"}
        args = {
            "action": "replace",
            "target": "user",
            "old_text": "old",
            "content": "new pref",
        }

        dispatch_builtin_memory_via_registry(
            args,
            store=store,
            manager=manager,
            metadata_factory=lambda: meta,
            session_id="session-bridge-r",
            tool_call_id="call-bridge-replace",
        )

        assert manager.writes == [("replace", "user", "new pref", meta)]

    def test_bridge_skips_remove(self, accepted_turn_policy):
        """The bridge intentionally skips 'remove' — only add/replace notify,
        matching the pre-migration branch guard."""
        store = _RecordingStore()
        manager = _RecordingManager()

        dispatch_builtin_memory_via_registry(
            dict(_REMOVE_ARGS),
            store=store,
            manager=manager,
            metadata_factory=None,
            session_id="session-bridge-rm",
            tool_call_id="call-bridge-remove",
        )

        assert store.calls == [("remove", "memory", "durable fact")]
        assert manager.writes == []  # remove never bridges

    def test_bridge_swallows_provider_failure(self, accepted_turn_policy):
        """A raising provider bridge never fails the tool (same swallow
        semantics as the inline branch)."""
        store = _RecordingStore()

        class _BoomManager:
            def on_memory_write(self, *a, **k):
                raise RuntimeError("provider down")

        result = json.loads(
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                manager=_BoomManager(),
                metadata_factory=lambda: {"x": 1},
                session_id="session-boom",
                tool_call_id="call-boom",
            )
        )
        assert result["op"] == "add"  # write succeeded despite bridge failure
        assert store.calls == [("add", "memory", "durable fact")]

    def test_raising_metadata_factory_never_loses_the_store_write(
        self, accepted_turn_policy
    ):
        """A raising metadata builder is swallowed INSIDE the bridge block and
        never blocks or loses the store write — byte-identical to the extracted
        branches (copies 3 & 4) that built ``_build_memory_write_metadata`` as an
        argument to ``on_memory_write`` inside its ``try/except`` AFTER the
        write.  Regression guard for the factory-vs-prebuilt-dict fix."""
        store = _RecordingStore()
        manager = _RecordingManager()

        def boom_factory():
            raise RuntimeError("metadata build exploded")

        result = json.loads(
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                manager=manager,
                metadata_factory=boom_factory,
                session_id="session-meta-boom",
                tool_call_id="call-meta-boom",
            )
        )
        assert result["op"] == "add"  # the write completed
        assert store.calls == [("add", "memory", "durable fact")]  # write happened
        assert manager.writes == []  # bridge aborted on the raising build, swallowed

    def test_bridge_does_not_fire_on_exact_beta_denied(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta a denied add is refused BEFORE the handler — the
        store is never written AND the provider bridge never fires."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        store = _RecordingStore()
        manager = _RecordingManager()

        result = json.loads(
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                manager=manager,
                metadata_factory=lambda: {"x": 1},
                session_id="session-beta-bridge",
                tool_call_id="call-beta-bridge",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        assert store.calls == []  # handler never ran
        assert manager.writes == []  # bridge never fired
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_bridge_does_not_fire_on_stale_registration(
        self, monkeypatch, accepted_turn_policy
    ):
        """A registration replaced between prepare and start runs no handler, so
        neither the store write nor the provider bridge happens."""
        store = _RecordingStore()
        manager = _RecordingManager()
        real_prepare = registry.prepare_shadow
        entry = registry.get_entry("memory")

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "memory":
                registry.register(
                    name="memory",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                    check_fn=entry.check_fn,
                    emoji=entry.emoji,
                    effect_resolver=entry.effect_resolver,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                manager=manager,
                metadata_factory=lambda: {"x": 1},
                session_id="session-stale-bridge",
                tool_call_id="call-stale-bridge",
            )
        )

        assert result["shadow_status"] == "stale_registration"
        assert store.calls == []
        assert manager.writes == []
        assert _MEMORY_TOOL_COMPANION.get() is None


# =========================================================================
# Adversarial (recipe step 7)
# =========================================================================


class TestMemoryRegistryDispatchAdversarial:
    def test_store_arg_cannot_override_companion_channel(self, accepted_turn_policy):
        """Model-controlled arguments never masquerade as the store: a
        (JSON-valid) ``store`` key in args is ignored and only the
        companion-bound store is written."""
        real_store = _RecordingStore()
        args = dict(_ADD_ARGS)
        args["store"] = "decoy-store"  # smuggle attempt via model args

        json.loads(
            dispatch_builtin_memory_via_registry(
                args,
                store=real_store,
                session_id="session-smuggle",
                tool_call_id="call-smuggle",
            )
        )

        assert real_store.calls == [("add", "memory", "durable fact")]
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_nonserializable_store_in_args_fails_closed_before_seam(
        self, accepted_turn_policy
    ):
        """An actual store OBJECT smuggled through args can never reach the
        handler seam: canonicalization rejects the non-JSON value and the call
        fails closed (``invalid_arguments``) before any handler runs, so the
        real store is untouched."""

        class _Tripwire:
            def add(self, *a, **k):  # pragma: no cover - must never run
                raise AssertionError("smuggled store was written")

        real_store = _RecordingStore()
        args = dict(_ADD_ARGS)
        args["store"] = _Tripwire()  # non-JSON object smuggled via model args

        result = json.loads(
            dispatch_builtin_memory_via_registry(
                args,
                store=real_store,
                session_id="session-smuggle-obj",
                tool_call_id="call-smuggle-obj",
            )
        )

        assert result["shadow_status"] == "invalid_arguments"
        assert real_store.calls == []  # handler never ran
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_manager_arg_cannot_reach_bridge_seam(self, accepted_turn_policy):
        """A JSON-valid ``manager`` key in args cannot trigger the bridge — the
        bridge fires only from the companion-bound manager."""
        store = _RecordingStore()
        args = dict(_ADD_ARGS)
        args["manager"] = "decoy-manager"

        dispatch_builtin_memory_via_registry(
            args,
            store=store,
            manager=None,  # no bound manager → no bridge
            metadata_factory=None,
            session_id="session-mgr-smuggle",
            tool_call_id="call-mgr-smuggle",
        )

        assert store.calls == [("add", "memory", "durable fact")]
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_binding_cleared_after_success(self, accepted_turn_policy):
        """The binding is scoped to exactly one dispatch: a post-dispatch legacy
        dispatch gets "not available" and the companion reads None."""
        store = _RecordingStore()
        dispatch_builtin_memory_via_registry(
            dict(_ADD_ARGS),
            store=store,
            session_id="session-clear",
            tool_call_id="call-clear",
        )
        assert _MEMORY_TOOL_COMPANION.get() is None
        after = json.loads(registry.dispatch("memory", dict(_ADD_ARGS)))
        assert "Memory is not available" in after["error"]

    def test_binding_cleared_when_impl_raises(self, accepted_turn_policy):
        """Even when the underlying ``memory_tool`` implementation raises, the
        companion is unbound on the way out and the store cannot leak to a later
        dispatch."""
        store = _RecordingStore()

        def boom(*_a, **_k):
            raise RuntimeError("memory impl exploded")

        with patch("tools.memory_tool.memory_tool", boom):
            result = json.loads(
                dispatch_builtin_memory_via_registry(
                    dict(_ADD_ARGS),
                    store=store,
                    session_id="session-raise",
                    tool_call_id="call-raise",
                )
            )
        assert "error" in result  # shadow captures the handler exception
        assert _MEMORY_TOOL_COMPANION.get() is None
        after = json.loads(registry.dispatch("memory", dict(_REMOVE_ARGS)))
        assert "Memory is not available" in after["error"]

    def test_lazy_companion_read_after_dispatch_observes_nothing(
        self, accepted_turn_policy
    ):
        """A handler that captured the companion for a lazy read after dispatch
        would observe None — the binding does not outlive the dispatch."""
        store = _RecordingStore()
        seen = {}

        def peek_handler(args, **kwargs):
            seen["during"] = _MEMORY_TOOL_COMPANION.get()
            return _registered_memory_tool_handler(args, **kwargs)

        entry = registry.get_entry("memory")
        registry.register(
            name="memory",
            toolset=entry.toolset,
            schema=entry.schema,
            handler=peek_handler,
            check_fn=entry.check_fn,
            emoji=entry.emoji,
            effect_resolver=entry.effect_resolver,
        )
        try:
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                session_id="session-lazy",
                tool_call_id="call-lazy",
            )
        finally:
            registry.register(
                name="memory",
                toolset=entry.toolset,
                schema=entry.schema,
                handler=entry.handler,
                check_fn=entry.check_fn,
                emoji=entry.emoji,
                effect_resolver=entry.effect_resolver,
            )

        assert seen["during"] is not None  # visible INSIDE the dispatch
        assert seen["during"].store is store
        assert _MEMORY_TOOL_COMPANION.get() is None  # gone AFTER

    def test_exact_beta_denied_fails_before_impl(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement an UNKNOWN-effect memory call against a
        read-only accepted turn is refused BEFORE the handler with
        ``effect_policy_block`` — the same fail-closed proof the gate-pinned
        run_agent Beta tests assert for the direct branch, now through the
        adapter."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        store = _RecordingStore()
        result = json.loads(
            dispatch_builtin_memory_via_registry(
                dict(_ADD_ARGS),
                store=store,
                session_id="session-beta",
                tool_call_id="call-beta",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        assert store.calls == []  # handler never ran
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_exact_beta_missing_identity_fails_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a call missing a durable identity is
        refused before any handler with ``effect_context_block``."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        store = _RecordingStore()
        result = json.loads(
            dispatch_builtin_memory_via_registry(dict(_ADD_ARGS), store=store)
        )
        assert result["shadow_status"] == "effect_context_block"
        assert store.calls == []
        assert _MEMORY_TOOL_COMPANION.get() is None

    def test_cross_thread_store_isolation_under_concurrent_dispatch(self):
        """Two overlapping dispatches (the agent loop's copy_context +
        Context.run worker pattern) each bind their OWN store + manager; while
        both handlers are simultaneously inside the boundary each writes only to
        its own store and bridges only its own manager, with no
        cross-contamination and both bindings cleared."""
        barrier = threading.Barrier(2, timeout=5)
        original_memory_tool = memory_tool

        def gated_memory_tool(*args, **kwargs):
            # Force both handlers inside the boundary at the same instant with
            # their bindings live before either writes.
            barrier.wait()
            return original_memory_tool(*args, **kwargs)

        stores = {"a": _RecordingStore("a"), "b": _RecordingStore("b")}
        managers = {"a": _RecordingManager(), "b": _RecordingManager()}

        def worker(tag):
            policy = ExecutionPolicy.for_mode(f"turn-memory-iso-{tag}", "read_only")
            token = set_current_execution_policy(policy, policy_revision=2)
            try:
                return dispatch_builtin_memory_via_registry(
                    {"action": "add", "target": "memory", "content": tag},
                    store=stores[tag],
                    manager=managers[tag],
                    metadata_factory=lambda: {"tag": tag},
                    session_id=f"session-iso-{tag}",
                    tool_call_id=f"call-iso-{tag}",
                )
            finally:
                reset_current_execution_policy(token)

        with patch("tools.memory_tool.memory_tool", gated_memory_tool):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="mem-iso"
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    ctx = contextvars.copy_context()
                    futures.append(pool.submit(ctx.run, worker, tag))
                results = [f.result(timeout=10) for f in futures]

        assert all(json.loads(r)["op"] == "add" for r in results)
        assert stores["a"].calls == [("add", "memory", "a")]
        assert stores["b"].calls == [("add", "memory", "b")]
        assert managers["a"].writes == [("add", "memory", "a", {"tag": "a"})]
        assert managers["b"].writes == [("add", "memory", "b", {"tag": "b"})]
        assert _MEMORY_TOOL_COMPANION.get() is None


# =========================================================================
# Registration truthfulness (guards the migrated declaration)
# =========================================================================


class TestMemoryRegistryDeclaration:
    def test_handler_swapped_to_companion_backed_unknown_registration(self):
        """The registered handler is the companion-backed handler and effects
        are CONFIG-BOUNDED (2026-07-23): a local/empty memory provider proves
        write_local:memory; an external provider still resolves UNKNOWN and a
        restricted policy fails closed — no static widening."""
        entry = registry.get_entry("memory")
        assert entry is not None
        assert entry.handler is memory_module._registered_memory_tool_handler
        assert entry.effects is None
        assert entry.effect_resolver is memory_module._memory_effect_resolver
        resolved = registry.resolve_effects("memory", _ADD_ARGS)
        assert sorted(str(e) for e in resolved) == ["write_local:memory"]
