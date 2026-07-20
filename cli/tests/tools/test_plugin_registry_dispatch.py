"""Parity + adversarial tests for the ``PluginContext.dispatch_tool`` migration (A2b lane 7).

``elevate_cli.plugins.PluginContext.dispatch_tool`` used to call
``registry.dispatch(tool_name, args, **kwargs)`` directly — the legacy,
non-atomic adapter that bypassed the shadow-dispatch boundary entirely — after
injecting the CLI parent agent as a raw ``parent_agent`` dispatch kwarg.  It now
routes through ``model_tools.dispatch_agent_owned_registry_tool`` (the common
adapter every agent-loop tool branch already uses), so every plugin-issued tool
call is captured with a frozen registration identity, canonical args digest, and
accepted-turn policy context.  The parent agent — process state that the
adapter's JSON-frozen snapshots reject by design — rides the ``delegate_task``
module companion for exactly one dispatch instead of a dispatch kwarg.

This is the LAST unmigrated agent-loop bypass lane, and it retires the temporary
``kw.get("parent_agent")`` fallback that lane 4 left in ``delegate_task``'s
registered handler for this path — the companion is now the one and only parent
channel (see ``test_delegate_registry_dispatch.py``'s
``test_kw_parent_agent_channel_is_retired``).

Bar (recipe): byte-identical caller behavior for Stable.  Durable identity
(``session_id`` + ``tool_call_id``) is typically absent for plugin callers, so
the adapter's byte-parity legacy fallback path must stay reachable and identical;
a plugin that DOES pass session/tool ids gets the atomic shadow path.

The filename carries a ``registry`` substring so the effect/policy/shadow/registry
sweep picks it up.
"""

import concurrent.futures
import contextvars
import json
import threading
from unittest.mock import patch

import pytest

from elevate_cli.plugins import PluginContext, PluginManager, PluginManifest
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.delegate_tool import _DELEGATE_PARENT_COMPANION
from tools.registry import registry


# A parent-agent stand-in.  The delegate seam only forwards it by reference; the
# ``agent_id``/``name`` attrs mirror a real AIAgent so any accidental agent-id
# resolver still finds a value.
class _ParentSentinel:
    def __init__(self, tag="parent"):
        self.tag = tag
        self.agent_id = tag
        self.name = tag


class _CliRef:
    """Minimal ``_cli_ref`` stand-in.  A plain object (not a MagicMock) so
    ``getattr(cli, "agent", None)`` returns exactly what we set — MagicMock would
    auto-vivify a truthy ``agent`` and defeat the None-path tests."""

    def __init__(self, agent=None):
        self.agent = agent


def _make_ctx(cli_agent="__unset__", cli_ref="__unset__"):
    """Build a real PluginContext wired to an optional CLI parent agent."""
    mgr = PluginManager()
    manifest = PluginManifest(name="lane7-test-plugin", source="user")
    ctx = PluginContext(manifest, mgr)
    if cli_ref != "__unset__":
        mgr._cli_ref = cli_ref
    elif cli_agent != "__unset__":
        mgr._cli_ref = _CliRef(agent=cli_agent)
    return ctx


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus a durable revision."""
    policy = ExecutionPolicy.for_mode("turn-plugin-lane", "read_only")
    token = set_current_execution_policy(policy, policy_revision=5)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class _ScratchTool:
    """Register one scratch registry tool for the duration of a test."""

    def __init__(self, name, handler, *, is_async=False):
        self.name = name
        registry.register(
            name=name,
            toolset="_test-plugin-lane7",
            schema={
                "name": name,
                "description": "lane-7 scratch tool",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=handler,
            is_async=is_async,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        registry.deregister(self.name)
        return False


def _recording_handler(record):
    """A scratch handler that records exactly what args/kwargs reached it."""

    def handler(args, **kw):
        record.append({"args": args, "kw": dict(kw)})
        return json.dumps({"ok": True, "seen_args": args})

    return handler


def _delegate_spy(record):
    """A ``delegate_task`` replacement that records its call and never spawns."""

    def spy(**kwargs):
        record.append(kwargs)
        return json.dumps({"success": True, "result": "spy"})

    return spy


# =========================================================================
# Parity (recipe step 6) — byte-identical Stable behavior
# =========================================================================


class TestPluginDispatchParity:
    def test_no_identity_no_parent_matches_legacy_dispatch(self):
        """Gateway mode (no CLI ref, no durable identity): the adapter takes its
        legacy fallback and the underlying handler runs exactly once with the
        identical args and ONLY the frozen ``task_id``/``user_task`` kwargs — the
        byte-parity legacy path the migration must preserve."""
        record = []
        ctx = _make_ctx(cli_ref=None)
        with _ScratchTool("_lane7_parity_tool", _recording_handler(record)):
            result = ctx.dispatch_tool("_lane7_parity_tool", {"x": 1})
        assert json.loads(result) == {"ok": True, "seen_args": {"x": 1}}
        assert len(record) == 1
        assert record[0]["args"] == {"x": 1}
        # Only the adapter's frozen handler-kwargs reach the handler; no smuggled
        # state, no leftover plugin kwargs.
        assert record[0]["kw"] == {"task_id": None, "user_task": None}

    def test_unknown_tool_returns_legacy_unknown_payload(self):
        """A hallucinated tool name keeps the exact legacy unknown-tool payload."""
        ctx = _make_ctx(cli_ref=None)
        result = json.loads(ctx.dispatch_tool("_lane7_no_such_tool", {}))
        assert result == {"error": "Unknown tool: _lane7_no_such_tool"}

    def test_return_value_passes_through_unchanged(self):
        """The raw JSON string from the handler is returned verbatim."""
        ctx = _make_ctx(cli_ref=None)

        def handler(args, **kw):
            return '{"custom": "payload", "n": 42}'

        with _ScratchTool("_lane7_passthrough_tool", handler):
            result = ctx.dispatch_tool("_lane7_passthrough_tool", {})
        assert result == '{"custom": "payload", "n": 42}'

    def test_parent_from_cli_ref_reaches_delegate_via_companion(self):
        """The CLI parent agent is delivered to ``delegate_task`` EXCLUSIVELY
        through the companion (never a handler kwarg), and the binding is cleared
        after the dispatch."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        agent = _ParentSentinel("cli-agent")
        ctx = _make_ctx(cli_agent=agent)
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(ctx.dispatch_tool("delegate_task", {"goal": "go"}))
        assert result == {"success": True, "result": "spy"}
        assert len(calls) == 1
        assert calls[0]["parent_agent"] is agent
        assert calls[0]["goal"] == "go"
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_routed_dispatch_with_identity_traverses_atomic_boundary(
        self, monkeypatch, accepted_turn_policy
    ):
        """A plugin that passes session/tool ids gets the atomic shadow path:
        the call traverses ``execute_shadow`` with the frozen
        session/invocation/turn identity, a 64-char args digest, and a started
        handler."""
        record = []
        captured = {}
        real_execute_shadow = registry.execute_shadow

        def shadow_spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["name"] = name
            captured["context"] = outcome.prepared.context
            captured["args_digest"] = outcome.prepared.args_digest
            captured["started"] = outcome.started
            return outcome

        monkeypatch.setattr(registry, "execute_shadow", shadow_spy)
        ctx = _make_ctx(cli_ref=None)
        with _ScratchTool("_lane7_shadow_tool", _recording_handler(record)):
            result = json.loads(
                ctx.dispatch_tool(
                    "_lane7_shadow_tool",
                    {"q": "hi"},
                    session_id="session-plugin",
                    tool_call_id="call-plugin-shadow",
                )
            )
        assert result == {"ok": True, "seen_args": {"q": "hi"}}
        assert captured["name"] == "_lane7_shadow_tool"
        assert captured["started"] is True
        assert captured["context"].session_id == "session-plugin"
        assert captured["context"].invocation_id == "call-plugin-shadow"
        assert captured["context"].accepted_turn_id == "turn-plugin-lane"
        assert captured["context"].policy_revision == 5
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64
        assert len(record) == 1

    def test_identity_path_delivers_parent_via_companion(
        self, monkeypatch, accepted_turn_policy
    ):
        """The identity (atomic shadow) path ALSO delivers the CLI parent through
        the companion — not a handler kwarg — and clears it afterwards.  Covers
        the parent+durable-identity combination end-to-end through the adapter."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        agent = _ParentSentinel("cli-agent")
        ctx = _make_ctx(cli_agent=agent)
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            result = json.loads(
                ctx.dispatch_tool(
                    "delegate_task",
                    {"goal": "go"},
                    session_id="session-plugin-id",
                    tool_call_id="call-plugin-id",
                )
            )
        assert result == {"success": True, "result": "spy"}
        assert len(calls) == 1
        assert calls[0]["parent_agent"] is agent
        assert _DELEGATE_PARENT_COMPANION.get() is None


# =========================================================================
# Parent-agent resolution parity (preserves the pre-migration semantics)
# =========================================================================


class TestPluginParentResolution:
    def test_explicit_parent_agent_overrides_cli_ref(self):
        """An explicit ``parent_agent`` kwarg wins over the resolved CLI agent,
        matching the previous ``"parent_agent" not in kwargs`` semantics — and it
        still reaches ``delegate_task`` through the companion, not a kwarg."""
        cli_agent = _ParentSentinel("cli")
        explicit = _ParentSentinel("explicit")
        ctx = _make_ctx(cli_agent=cli_agent)
        calls = []
        with patch("tools.delegate_tool.delegate_task", _delegate_spy(calls)):
            json.loads(
                ctx.dispatch_tool(
                    "delegate_task", {"goal": "go"}, parent_agent=explicit
                )
            )
        assert len(calls) == 1
        assert calls[0]["parent_agent"] is explicit
        assert calls[0]["parent_agent"] is not cli_agent

    def test_no_parent_when_no_cli_ref(self):
        """Gateway mode (``_cli_ref`` None): no companion is bound, so
        ``delegate_task`` gets ``parent_agent=None`` and returns its typed
        "requires a parent agent context" error — byte-identical to the
        pre-migration agent-less dispatch."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        ctx = _make_ctx(cli_ref=None)
        result = json.loads(ctx.dispatch_tool("delegate_task", {"goal": "go"}))
        assert result["error"] == "delegate_task requires a parent agent context."
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_no_parent_when_cli_agent_is_none(self):
        """CLI ref exists but its agent is not yet initialized (None): no parent
        is injected — same as the pre-migration guard."""
        assert _DELEGATE_PARENT_COMPANION.get() is None
        ctx = _make_ctx(cli_agent=None)
        result = json.loads(ctx.dispatch_tool("delegate_task", {"goal": "go"}))
        assert result["error"] == "delegate_task requires a parent agent context."
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_explicit_none_parent_suppresses_cli_ref_injection(self):
        """An explicit ``parent_agent=None`` is honored as "no parent" and is NOT
        overridden by the CLI agent — the pre-migration ``"parent_agent" not in
        kwargs`` check treated an explicit key (even None) as caller intent."""
        cli_agent = _ParentSentinel("cli")
        ctx = _make_ctx(cli_agent=cli_agent)
        result = json.loads(
            ctx.dispatch_tool("delegate_task", {"goal": "go"}, parent_agent=None)
        )
        assert result["error"] == "delegate_task requires a parent agent context."


# =========================================================================
# Adversarial (recipe step 7)
# =========================================================================


class TestPluginDispatchAdversarial:
    def test_arbitrary_kwargs_cannot_smuggle_process_state(self):
        """The atomic boundary is the security benefit of this lane: a callable
        or object forced through the plugin's ``**kwargs`` (the old raw-dispatch
        channel) can NEVER reach the handler.  Only ``task_id``/``user_task``
        cross; the smuggled ``store``/``db``/``callback`` keys are dropped."""
        record = []
        ctx = _make_ctx(cli_ref=None)
        smuggled = object()

        def evil_callback():  # pragma: no cover - must never run
            raise AssertionError("smuggled callback reached the handler")

        with _ScratchTool("_lane7_smuggle_tool", _recording_handler(record)):
            ctx.dispatch_tool(
                "_lane7_smuggle_tool",
                {"a": 1},
                store=smuggled,
                db=smuggled,
                callback=evil_callback,
                current_session_id="sneaky",
            )
        assert len(record) == 1
        assert record[0]["kw"] == {"task_id": None, "user_task": None}
        assert "store" not in record[0]["kw"]
        assert "db" not in record[0]["kw"]
        assert "callback" not in record[0]["kw"]

    def test_companion_cleared_after_dispatch_when_handler_raises(self):
        """Even when the routed handler raises, the parent companion is unbound
        on the way out (adapter ``finally`` hygiene through the plugin lane)."""
        agent = _ParentSentinel("cli")
        ctx = _make_ctx(cli_agent=agent)

        def boom(**kwargs):
            raise RuntimeError("delegate exploded")

        with patch("tools.delegate_tool.delegate_task", boom):
            result = json.loads(ctx.dispatch_tool("delegate_task", {"goal": "x"}))
        assert "error" in result
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_companion_cleared_when_handler_raises_base_exception(self):
        """A ``BaseException`` (``KeyboardInterrupt``) from the handler is NOT
        swallowed by ``registry.dispatch`` (which only catches ``Exception``); it
        propagates through the no-identity ``ExitStack``, which still unbinds the
        parent companion on its way out — proving hygiene on the propagating
        control-flow path, not just the swallowed-error path."""
        agent = _ParentSentinel("cli")
        ctx = _make_ctx(cli_agent=agent)

        def interrupt(**kwargs):
            raise KeyboardInterrupt()

        with patch("tools.delegate_tool.delegate_task", interrupt):
            with pytest.raises(KeyboardInterrupt):
                ctx.dispatch_tool("delegate_task", {"goal": "x"})
        assert _DELEGATE_PARENT_COMPANION.get() is None

    def test_exact_beta_no_identity_fails_closed_with_legacy_payload(
        self, monkeypatch
    ):
        """Under exact Beta a plugin dispatch WITHOUT a durable identity (the
        typical plugin) stays on the legacy ``registry.dispatch`` fallback, which
        fail-closes with ``legacy_dispatch_block`` BEFORE any handler — BYTE-
        IDENTICAL to the pre-migration payload.  This is why the no-identity case
        keeps ``registry.dispatch`` rather than the adapter's preflight (which
        would substitute ``effect_context_block``); the pinned
        ``test_plugin_context_cannot_bypass_exact_beta_legacy_dispatch`` locks
        this exact behavior."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        record = []
        ctx = _make_ctx(cli_ref=None)
        with _ScratchTool("_lane7_beta_noid_tool", _recording_handler(record)):
            result = json.loads(ctx.dispatch_tool("_lane7_beta_noid_tool", {}))
        assert result["shadow_status"] == "legacy_dispatch_block"
        assert record == []  # handler never ran

    def test_exact_beta_undeclared_tool_with_identity_fails_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact Beta a plugin dispatch WITH a durable identity of an
        UNDECLARED (UNKNOWN-effect) tool is refused BEFORE the handler with
        ``effect_policy_block`` — declaration != allowance, fail closed."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        record = []
        ctx = _make_ctx(cli_ref=None)
        with _ScratchTool("_lane7_beta_id_tool", _recording_handler(record)):
            result = json.loads(
                ctx.dispatch_tool(
                    "_lane7_beta_id_tool",
                    {},
                    session_id="session-beta",
                    tool_call_id="call-beta",
                )
            )
        assert result["shadow_status"] == "effect_policy_block"
        assert record == []  # handler never ran

    def test_concurrent_plugin_dispatch_isolates_parents(self):
        """Two overlapping plugin dispatches each bind their OWN CLI parent
        agent; while both handlers are simultaneously inside the boundary each
        resolves only its own companion value, with both bindings cleared."""
        barrier = threading.Barrier(2, timeout=5)
        agents = {"a": _ParentSentinel("a"), "b": _ParentSentinel("b")}
        seen = {}
        seen_lock = threading.Lock()

        def gated_delegate(**kwargs):
            barrier.wait()
            parent = kwargs["parent_agent"]
            with seen_lock:
                seen[parent.tag] = parent
            return json.dumps({"success": True, "result": parent.tag})

        def worker(tag):
            ctx = _make_ctx(cli_agent=agents[tag])
            return ctx.dispatch_tool("delegate_task", {"goal": tag})

        with patch("tools.delegate_tool.delegate_task", gated_delegate):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="plugin-iso"
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    context = contextvars.copy_context()
                    futures.append(pool.submit(context.run, worker, tag))
                results = [json.loads(f.result(timeout=10)) for f in futures]

        assert {r["result"] for r in results} == {"a", "b"}
        assert seen["a"] is agents["a"]
        assert seen["b"] is agents["b"]
        assert _DELEGATE_PARENT_COMPANION.get() is None
