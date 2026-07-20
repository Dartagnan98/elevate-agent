"""Parity + adversarial tests for the ``session_search`` agent-loop lane (A2b lane 6).

The four agent-loop ``session_search`` branches (``run_agent._invoke_tool``
concurrent + ``_execute_tool_calls_sequential_impl``, ``agent.tool_executor``,
``agent.agent_runtime_helpers``) used to special-case ``session_search`` BEFORE the
registry: each injected the agent's write-capable :class:`SessionDB`
(``self._session_db`` / ``agent._get_session_db_for_recall()``) plus the current
session id straight into ``session_search(db=…, current_session_id=…)``, bypassing
the atomic shadow-dispatch boundary and sourcing the DB through the registered
handler's ``kw.get("db")`` seam — a channel the shadow path's JSON-only
handler-kwargs snapshot can never carry.  On the fallback ``db=None`` the tool
BOOTSTRAPPED a fresh ``SessionDB()`` (mkdir + WAL + schema-init + a PG-first
``list_sessions_rich`` reader on a bootstrapping ``connect()``) — a hidden write
masquerading as a recall read.

They now route through
``tools.session_search_tool.dispatch_session_search_via_registry`` onto
``model_tools.dispatch_agent_owned_registry_tool``, binding the injected DB +
current session id through a module-level :class:`DispatchCompanion` (holding an
immutable struct so "no binding at all" is distinguishable from "bound but DB is
None") for exactly one dispatch.  The migrated handler NEVER constructs a fallback
``SessionDB``: with no binding — or a bound-but-``None`` DB — it returns the typed
``{"success": false, "error": "Session database not available."}`` payload rather
than bootstrapping a store off the agent loop.

These tests prove byte-identical caller behavior (the Stable bar) and lock the
lane's signature trap (no fallback bootstrap).  Effect honesty: the registration
is UNKNOWN (``effects=None``) — ``session_search`` presents as a recall read but
its readers still ride the bootstrapping ``connect()`` (out of scope to repair
this lane), so a restricted accepted turn fails closed under exact Realtor Beta.
The adapter's own hygiene is covered by
``tests/tools/test_agent_owned_registry_dispatch.py``.
"""

import concurrent.futures
import contextvars
import json
import threading
from unittest.mock import patch

import pytest

import elevate_state
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import registry
import tools.session_search_tool as ss_module
from tools.session_search_tool import (
    _SESSION_SEARCH_COMPANION,
    _registered_session_search_handler,
    dispatch_session_search_via_registry,
    session_search,
)


_UNAVAILABLE = {"success": False, "error": "Session database not available."}


class _FakeSessionDB:
    """Minimal ``SessionDB``-shaped fake: deterministic reads, records calls.

    Deterministic returns make routed and direct dispatch byte-comparable
    without touching a real state.db.  ``list_sessions_rich`` drives BROWSE,
    ``search_messages`` drives DISCOVERY, and ``get_messages_around`` drives
    SCROLL.
    """

    def __init__(self, tag="db"):
        self.tag = tag
        self.calls = []

    def list_sessions_rich(self, **kw):
        self.calls.append(("list_sessions_rich", kw))
        return [
            {
                "id": "s1",
                "title": "First session",
                "source": "cli",
                "started_at": 1000,
                "last_active": 2000,
                "message_count": 5,
                "preview": "hello world",
                "parent_session_id": None,
            }
        ]

    def search_messages(self, **kw):
        self.calls.append(("search_messages", kw))
        return []  # deterministic empty -> "No matching sessions found."

    def get_session(self, sid):
        self.calls.append(("get_session", sid))
        return {
            "id": sid,
            "parent_session_id": None,
            "started_at": 1000,
            "source": "cli",
            "model": "m",
            "title": "T",
        }

    def get_messages_around(self, sid, around_id, window=5):
        self.calls.append(("get_messages_around", sid, around_id, window))
        return {
            "window": [
                {"id": around_id, "role": "user", "content": "anchor", "timestamp": 1000}
            ],
            "messages_before": 0,
            "messages_after": 0,
        }

    def get_anchored_view(self, sid, msg_id, window=2, bookend=1):
        self.calls.append(("get_anchored_view", sid, msg_id, window, bookend))
        return {
            "window": [],
            "bookend_start": [],
            "bookend_end": [],
            "messages_before": 0,
            "messages_after": 0,
        }


class _DetonatingSessionDB:
    """A SessionDB replacement that explodes if the tool ever tries to bootstrap."""

    instances = 0

    def __init__(self, *a, **k):  # pragma: no cover - must never run
        type(self).instances += 1
        raise AssertionError(
            "session_search bootstrapped a fallback SessionDB (mkdir/WAL/schema-init)"
        )


@pytest.fixture
def accepted_turn_policy():
    """Bind one Stable accepted-turn policy plus a durable revision."""
    policy = ExecutionPolicy.for_mode("turn-session-search-lane", "read_only")
    token = set_current_execution_policy(policy, policy_revision=9)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


# =========================================================================
# Parity (recipe step 6)
# =========================================================================


class TestSessionSearchRegistryDispatchParity:
    def test_legacy_fallback_matches_direct_call_and_runs_impl_once(self):
        """No durable identity -> legacy ``registry.dispatch`` payload, and the
        underlying ``session_search`` runs exactly once with the model args plus
        the companion-bound DB (never a kw DB)."""
        routed_db = _FakeSessionDB("routed")
        direct_db = _FakeSessionDB("direct")

        calls = []
        real_session_search = session_search

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real_session_search(*args, **kwargs)

        with patch("tools.session_search_tool.session_search", spy):
            routed = dispatch_session_search_via_registry(
                {}, db=routed_db, current_session_id=None
            )

        direct = real_session_search(query="", limit=3, db=direct_db, current_session_id=None)

        assert routed == direct
        assert json.loads(routed)["mode"] == "browse"
        # Impl invoked exactly once, carrying the bound DB — never a kw DB.
        assert len(calls) == 1
        assert calls[0]["db"] is routed_db
        assert routed_db.calls == direct_db.calls

    def test_routed_dispatch_traverses_atomic_boundary(self, monkeypatch):
        """Durable identity -> the call traverses ``execute_shadow`` with the
        frozen session/invocation/turn identity, a 64-char args digest, the
        truthful UNKNOWN effect, a started handler, and the bound DB read."""
        db = _FakeSessionDB()
        policy = ExecutionPolicy.for_mode("turn-session-routing", "read_only")
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
                dispatch_session_search_via_registry(
                    {},
                    db=db,
                    current_session_id=None,
                    task_id="task-ss",
                    session_id="session-ss",
                    tool_call_id="call-ss-shadow",
                )
            )
        finally:
            reset_current_execution_policy(token)

        assert result["mode"] == "browse"
        assert captured["name"] == "session_search"
        assert captured["started"] is True
        assert captured["effects"] == ["unknown"]
        assert captured["context"].session_id == "session-ss"
        assert captured["context"].invocation_id == "call-ss-shadow"
        assert captured["context"].accepted_turn_id == "turn-session-routing"
        assert captured["context"].policy_revision == 11
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64
        # The bound DB — not any bootstrapped one — served the browse read.
        assert ("list_sessions_rich", {
            "limit": 8,
            "exclude_sources": ["tool"],
            "order_by_last_active": True,
        }) in db.calls

    def test_extracted_wide_shape_forwards_scroll_byte_identical(self):
        """The extracted copies forward the FULL arg shape; routing a scroll
        request reproduces the direct ``session_search`` scroll call exactly."""
        routed_db = _FakeSessionDB("routed")
        direct_db = _FakeSessionDB("direct")
        wide_args = {"session_id": "s1", "around_message_id": 5, "window": 5}

        routed = dispatch_session_search_via_registry(
            dict(wide_args), db=routed_db, current_session_id=None
        )
        direct = session_search(
            session_id="s1",
            around_message_id=5,
            window=5,
            db=direct_db,
            current_session_id=None,
        )

        assert routed == direct
        assert json.loads(routed)["mode"] == "scroll"
        assert routed_db.calls == direct_db.calls

    def test_run_agent_narrow_shape_drops_scroll_and_sort(self):
        """The ``run_agent`` branches forward only query/role_filter/limit, so a
        model scroll/sort request routed through the NARROW dict those branches
        build is ignored (browse), byte-identical to the pre-migration branch
        that never passed session_id/around_message_id/window/sort."""
        db = _FakeSessionDB()
        model_args = {
            "query": "",
            "session_id": "s1",
            "around_message_id": 5,
            "sort": "newest",
        }
        # Exactly the narrowed dict the run_agent branches build:
        narrow = {
            "query": model_args.get("query", ""),
            "role_filter": model_args.get("role_filter"),
            "limit": model_args.get("limit", 3),
        }
        result = json.loads(
            dispatch_session_search_via_registry(narrow, db=db, current_session_id=None)
        )
        assert result["mode"] == "browse"  # scroll dropped
        # The scroll primitive was never reached; browse read was.
        assert not any(c[0] == "get_messages_around" for c in db.calls)
        assert any(c[0] == "list_sessions_rich" for c in db.calls)

    def test_branch_typed_error_is_byte_identical(self):
        """The handler's no-DB refusal is byte-identical to the ``run_agent``
        agent-loop branch's own ``{"success": false, "error": "Session database
        not available."}`` pre-dispatch payload."""
        assert _SESSION_SEARCH_COMPANION.get() is None
        result = registry.dispatch("session_search", {})
        assert json.loads(result) == _UNAVAILABLE
        # byte-identical to what the run_agent branch returns directly:
        assert result == json.dumps(_UNAVAILABLE)


# =========================================================================
# No-bootstrap trap (lane signature — recipe step 3 + task brief)
# =========================================================================


class TestSessionSearchNeverBootstraps:
    def test_legacy_dispatch_outside_binding_never_constructs_sessiondb(
        self, monkeypatch
    ):
        """A registered-handler call reached WITHOUT the companion binding
        (legacy ``registry.dispatch``, plugin dispatch, hallucinated call)
        returns the typed "not available" error and NEVER bootstraps a fallback
        ``SessionDB`` — the whole point of the migration."""
        _DetonatingSessionDB.instances = 0
        monkeypatch.setattr(elevate_state, "SessionDB", _DetonatingSessionDB)
        assert _SESSION_SEARCH_COMPANION.get() is None

        result = json.loads(registry.dispatch("session_search", {"query": "anything"}))

        assert result == _UNAVAILABLE
        assert _DetonatingSessionDB.instances == 0  # no mkdir/WAL/schema-init
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_bound_but_none_db_refuses_without_bootstrap(self, monkeypatch):
        """A struct bound with ``db=None`` (distinct from "no binding at all")
        is refused with the typed error and never bootstraps — the struct makes
        both cases explicit."""
        _DetonatingSessionDB.instances = 0
        monkeypatch.setattr(elevate_state, "SessionDB", _DetonatingSessionDB)

        result = json.loads(
            dispatch_session_search_via_registry(
                {"query": "x"},
                db=None,
                current_session_id=None,
                session_id="session-none-db",
                tool_call_id="call-none-db",
            )
        )

        assert result == _UNAVAILABLE
        assert _DetonatingSessionDB.instances == 0
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_handler_direct_no_binding_returns_typed_error(self, monkeypatch):
        """Calling the registered handler directly with no binding returns the
        typed error and does not touch ``session_search`` at all."""
        _DetonatingSessionDB.instances = 0
        monkeypatch.setattr(elevate_state, "SessionDB", _DetonatingSessionDB)
        with patch("tools.session_search_tool.session_search") as ss:
            result = json.loads(_registered_session_search_handler({"query": "x"}))
        assert result == _UNAVAILABLE
        ss.assert_not_called()
        assert _DetonatingSessionDB.instances == 0


# =========================================================================
# Adversarial (recipe step 7)
# =========================================================================


class TestSessionSearchRegistryDispatchAdversarial:
    def test_db_arg_cannot_override_companion_channel(self, accepted_turn_policy):
        """A (JSON-valid) ``db`` key in model args is ignored — only the
        companion-bound DB is read."""
        real_db = _FakeSessionDB()
        args = {"query": "", "db": "decoy-db"}

        json.loads(
            dispatch_session_search_via_registry(
                args,
                db=real_db,
                current_session_id=None,
                session_id="session-smuggle",
                tool_call_id="call-smuggle",
            )
        )

        assert any(c[0] == "list_sessions_rich" for c in real_db.calls)
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_current_session_id_arg_cannot_override_companion(
        self, accepted_turn_policy
    ):
        """A ``current_session_id`` key in model args is ignored — the current
        session id rides only through the companion struct."""
        real_db = _FakeSessionDB()
        # If args["current_session_id"] leaked into session_search, the browse
        # path would _resolve_to_parent(db, "leaked") -> get_session("leaked").
        args = {"query": "", "current_session_id": "leaked-sid"}

        dispatch_session_search_via_registry(
            args,
            db=real_db,
            current_session_id=None,
            session_id="session-cs-smuggle",
            tool_call_id="call-cs-smuggle",
        )

        assert not any(c == ("get_session", "leaked-sid") for c in real_db.calls)
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_nonserializable_db_in_args_fails_closed_before_seam(
        self, accepted_turn_policy
    ):
        """An actual DB OBJECT smuggled through args can never reach the seam:
        canonicalization rejects the non-JSON value and the call fails closed
        (``invalid_arguments``) before any handler runs, so the real DB is
        untouched."""

        class _Tripwire:
            def list_sessions_rich(self, *a, **k):  # pragma: no cover - never runs
                raise AssertionError("smuggled DB was read")

        real_db = _FakeSessionDB()
        args = {"query": "", "db": _Tripwire()}

        result = json.loads(
            dispatch_session_search_via_registry(
                args,
                db=real_db,
                current_session_id=None,
                session_id="session-smuggle-obj",
                tool_call_id="call-smuggle-obj",
            )
        )

        assert result["shadow_status"] == "invalid_arguments"
        assert real_db.calls == []  # handler never ran
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_binding_cleared_after_success(self, accepted_turn_policy):
        """The binding is scoped to exactly one dispatch: a post-dispatch legacy
        dispatch gets "not available" and the companion reads None."""
        db = _FakeSessionDB()
        dispatch_session_search_via_registry(
            {}, db=db, current_session_id=None,
            session_id="session-clear", tool_call_id="call-clear",
        )
        assert _SESSION_SEARCH_COMPANION.get() is None
        after = json.loads(registry.dispatch("session_search", {}))
        assert after == _UNAVAILABLE

    def test_binding_cleared_when_impl_raises(self, accepted_turn_policy):
        """Even when ``session_search`` raises, the companion is unbound on the
        way out and the DB cannot leak to a later dispatch."""
        db = _FakeSessionDB()

        def boom(*_a, **_k):
            raise RuntimeError("session_search impl exploded")

        with patch("tools.session_search_tool.session_search", boom):
            result = json.loads(
                dispatch_session_search_via_registry(
                    {}, db=db, current_session_id=None,
                    session_id="session-raise", tool_call_id="call-raise",
                )
            )
        assert "error" in result  # shadow captures the handler exception
        assert _SESSION_SEARCH_COMPANION.get() is None
        after = json.loads(registry.dispatch("session_search", {}))
        assert after == _UNAVAILABLE

    def test_lazy_companion_read_after_dispatch_observes_nothing(
        self, accepted_turn_policy
    ):
        """A handler that captured the companion for a lazy read after dispatch
        would observe None — the binding does not outlive the dispatch."""
        db = _FakeSessionDB()
        seen = {}

        def peek_handler(args, **kwargs):
            seen["during"] = _SESSION_SEARCH_COMPANION.get()
            return _registered_session_search_handler(args, **kwargs)

        entry = registry.get_entry("session_search")
        registry.register(
            name="session_search",
            toolset=entry.toolset,
            schema=entry.schema,
            handler=peek_handler,
            check_fn=entry.check_fn,
            emoji=entry.emoji,
        )
        try:
            dispatch_session_search_via_registry(
                {}, db=db, current_session_id=None,
                session_id="session-lazy", tool_call_id="call-lazy",
            )
        finally:
            registry.register(
                name="session_search",
                toolset=entry.toolset,
                schema=entry.schema,
                handler=entry.handler,
                check_fn=entry.check_fn,
                emoji=entry.emoji,
            )

        assert seen["during"] is not None  # visible INSIDE the dispatch
        assert seen["during"].db is db
        assert _SESSION_SEARCH_COMPANION.get() is None  # gone AFTER

    def test_exact_beta_denied_fails_before_impl(self, monkeypatch, accepted_turn_policy):
        """Under exact-Beta enforcement an UNKNOWN-effect session_search call
        against a read-only accepted turn is refused BEFORE the handler with
        ``effect_policy_block`` — the same fail-closed proof the gate-pinned
        run_agent Beta test asserts for the direct branch, now through the
        adapter — and the DB is never read."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        db = _FakeSessionDB()
        result = json.loads(
            dispatch_session_search_via_registry(
                {}, db=db, current_session_id=None,
                session_id="session-beta", tool_call_id="call-beta",
            )
        )
        assert result["shadow_status"] == "effect_policy_block"
        assert db.calls == []  # handler never ran
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_exact_beta_missing_identity_fails_closed(
        self, monkeypatch, accepted_turn_policy
    ):
        """Under exact-Beta enforcement a call missing a durable identity is
        refused before any handler with ``effect_context_block``."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        db = _FakeSessionDB()
        result = json.loads(
            dispatch_session_search_via_registry({}, db=db, current_session_id=None)
        )
        assert result["shadow_status"] == "effect_context_block"
        assert db.calls == []
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_stale_registration_runs_no_handler(self, monkeypatch, accepted_turn_policy):
        """A registration replaced between prepare and start runs no handler, so
        the DB is never read."""
        db = _FakeSessionDB()
        real_prepare = registry.prepare_shadow
        entry = registry.get_entry("session_search")

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "session_search":
                registry.register(
                    name="session_search",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                    check_fn=entry.check_fn,
                    emoji=entry.emoji,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_session_search_via_registry(
                {}, db=db, current_session_id=None,
                session_id="session-stale", tool_call_id="call-stale",
            )
        )

        assert result["shadow_status"] == "stale_registration"
        assert db.calls == []
        assert _SESSION_SEARCH_COMPANION.get() is None

    def test_cross_thread_db_isolation_under_concurrent_dispatch(self):
        """Two overlapping dispatches (the agent loop's copy_context +
        Context.run worker pattern) each bind their OWN DB; while both handlers
        are simultaneously inside the boundary each reads only its own DB, with
        no cross-contamination and both bindings cleared."""
        barrier = threading.Barrier(2, timeout=5)
        original_session_search = session_search

        def gated_session_search(*args, **kwargs):
            barrier.wait()
            return original_session_search(*args, **kwargs)

        dbs = {"a": _FakeSessionDB("a"), "b": _FakeSessionDB("b")}

        def worker(tag):
            policy = ExecutionPolicy.for_mode(f"turn-ss-iso-{tag}", "read_only")
            token = set_current_execution_policy(policy, policy_revision=2)
            try:
                return dispatch_session_search_via_registry(
                    {}, db=dbs[tag], current_session_id=None,
                    session_id=f"session-iso-{tag}", tool_call_id=f"call-iso-{tag}",
                )
            finally:
                reset_current_execution_policy(token)

        with patch("tools.session_search_tool.session_search", gated_session_search):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="ss-iso"
            ) as pool:
                futures = []
                for tag in ("a", "b"):
                    ctx = contextvars.copy_context()
                    futures.append(pool.submit(ctx.run, worker, tag))
                results = [f.result(timeout=10) for f in futures]

        assert all(json.loads(r)["mode"] == "browse" for r in results)
        # Each DB was read exactly once, by its own worker only.
        assert [c[0] for c in dbs["a"].calls] == ["list_sessions_rich"]
        assert [c[0] for c in dbs["b"].calls] == ["list_sessions_rich"]
        assert _SESSION_SEARCH_COMPANION.get() is None


# =========================================================================
# Registration truthfulness (guards the migrated declaration)
# =========================================================================


class TestSessionSearchRegistryDeclaration:
    def test_handler_swapped_to_companion_backed_unknown_registration(self):
        """The registered handler is the companion-backed handler and effects
        stay UNKNOWN (``effects=None``, no resolver) — no static widening: a
        restricted policy fails closed rather than assuming a bounded read."""
        entry = registry.get_entry("session_search")
        assert entry is not None
        assert entry.handler is ss_module._registered_session_search_handler
        assert entry.effects is None
        assert entry.effect_resolver is None
        resolved = registry.resolve_effects("session_search", {"query": "x"})
        assert sorted(e.kind.value for e in resolved) == ["unknown"]
