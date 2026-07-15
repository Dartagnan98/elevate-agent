"""Concurrency regressions for persisted TUI session actor ownership."""

from __future__ import annotations

import threading
import time
import types

import pytest

from tui_gateway import server
from tui_gateway.transport import bind_transport, reset_transport


class _Transport:
    def __init__(self, name: str):
        self.name = name
        self.frames: list[dict] = []

    def write(self, frame: dict) -> bool:
        self.frames.append(frame)
        return True

    def close(self) -> None:
        return None


class _DB:
    def __init__(self, *session_ids: str):
        self.rows = {
            session_id: {
                "id": session_id,
                "ended_at": None,
                "parent_session_id": None,
            }
            for session_id in session_ids
        }

    def resolve_session_id(self, value: str) -> str:
        return value

    def get_session(self, session_id: str):
        return self.rows.get(session_id)

    def get_session_by_title(self, _title: str):
        return None

    def resolve_canonical_session_identity(self, session_id: str) -> dict:
        return {
            "requested_session_id": session_id,
            "lineage_root_id": session_id,
            "active_session_id": session_id,
            "session_kind": "chat",
            "is_compression_tip": True,
        }

    def get_compression_tip(self, session_id: str) -> str:
        return session_id

    def reopen_session(self, _session_id: str) -> None:
        return None

    def get_messages_as_conversation(self, _session_id: str) -> list[dict]:
        return []

    def get_recoverable_prompt_receipt(self, _session_id: str):
        return None


class _Agent:
    model = "test/model"

    def close_memory_connections(self) -> None:
        return None

    def shutdown_memory_provider(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    with server._session_registry_lock:
        server._sessions.clear()
        server._session_aliases.clear()
        server._resume_reservations.clear()
    server._active_prompt_claims.clear()

    monkeypatch.setattr(server, "_enable_gateway_prompts", lambda: None)
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_recover_pending_prompt", lambda *_args: False)
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "test/model"})
    monkeypatch.setattr(
        server,
        "_light_session_info",
        lambda _agent=None: {"model": "test/model"},
    )
    monkeypatch.setattr(server, "_set_session_context", lambda *_a, **_kw: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(server, "_load_show_reasoning", lambda: False)
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "all")
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(server, "_resolve_model", lambda: "test/model")
    monkeypatch.setattr(server, "_restart_slash_worker", lambda _session: None)
    monkeypatch.setattr(server, "_probe_credentials", lambda _agent: None)
    monkeypatch.setattr(server, "_probe_config_health", lambda _cfg: None)

    class _Worker:
        def __init__(self, *_args, **_kwargs):
            pass

        def close(self) -> None:
            return None

    monkeypatch.setattr(server, "_SlashWorker", _Worker)

    from tools import approval

    monkeypatch.setattr(approval, "register_gateway_notify", lambda *_a, **_kw: None)
    monkeypatch.setattr(approval, "unregister_gateway_notify", lambda *_a, **_kw: None)
    monkeypatch.setattr(approval, "load_permanent_allowlist", lambda: None)

    yield

    deadline = time.monotonic() + 3
    while (
        any(
            not session.get("agent_ready", threading.Event()).is_set()
            for session in list(server._sessions.values())
            if session.get("agent_ready") is not None
        )
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    with server._session_registry_lock:
        server._sessions.clear()
        server._session_aliases.clear()
        server._resume_reservations.clear()
    server._active_prompt_claims.clear()


def _resume(session_id: str, *, rid: str, transport=None) -> dict:
    token = bind_transport(transport) if transport is not None else None
    try:
        return server.handle_request(
            {
                "id": rid,
                "method": "session.resume",
                "params": {"session_id": session_id},
            }
        )
    finally:
        if token is not None:
            reset_transport(token)


def _wait_ready(sid: str, timeout: float = 3.0) -> dict:
    session = server._sessions[sid]
    assert session["agent_ready"].wait(timeout=timeout)
    return session


def _install_live_session(sid: str, persisted_id: str, agent=None) -> dict:
    ready = threading.Event()
    ready.set()
    session = {
        "agent": agent or _Agent(),
        "agent_error": None,
        "agent_ready": ready,
        "attached_files": [],
        "attached_images": [],
        "attached_videos": [],
        "cols": 80,
        "edit_snapshots": {},
        "events": [],
        "events_lock": threading.Lock(),
        "events_seq": 0,
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "registry_aliases": {persisted_id},
        "running": False,
        "session_key": persisted_id,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        "tool_started_at": {},
        "running_tools": {},
    }
    server._sessions[sid] = session
    server._session_aliases[persisted_id] = sid
    return session


def test_two_cold_resumes_publish_one_actor_and_share_turn_latch(monkeypatch, tmp_path):
    from elevate_state import SessionDB
    from gateway import guardrails, usage_ledger

    persisted_id = "20260714_120000_singleflight"
    durable_db = SessionDB(db_path=tmp_path / "state.db")
    durable_db.create_session(persisted_id, source="tui")

    identity_barrier = threading.Barrier(2)
    identity_calls = 0
    identity_lock = threading.Lock()
    release_hydration = threading.Event()
    owner_hydrating = threading.Event()

    class _BarrierDB:
        def __getattr__(self, name):
            return getattr(durable_db, name)

        def resolve_canonical_session_identity(self, session_id: str) -> dict:
            nonlocal identity_calls
            with identity_lock:
                identity_calls += 1
                call = identity_calls
            if call <= 2:
                identity_barrier.wait(timeout=3)
            return durable_db.resolve_canonical_session_identity(session_id)

        def reopen_session(self, session_id: str) -> None:
            owner_hydrating.set()
            assert release_hydration.wait(timeout=3)
            durable_db.reopen_session(session_id)

    db = _BarrierDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)

    waiter_joined = threading.Event()
    real_reserve = server._reserve_resumed_session

    def _observed_reserve(aliases):
        disposition, owner = real_reserve(aliases)
        if disposition == "wait":
            waiter_joined.set()
        return disposition, owner

    monkeypatch.setattr(server, "_reserve_resumed_session", _observed_reserve)

    run_started = threading.Event()
    release_run = threading.Event()
    run_finished = threading.Event()
    agent_runs = 0
    agent_builds = 0
    agent_lock = threading.Lock()

    class _RunningAgent(_Agent):
        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            nonlocal agent_runs
            with agent_lock:
                agent_runs += 1
            run_started.set()
            assert release_run.wait(timeout=5)
            run_finished.set()
            return {
                "final_response": "done",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                    {"role": "assistant", "content": "done"},
                ],
            }

    def _make_agent(*_args, **_kwargs):
        nonlocal agent_builds
        with agent_lock:
            agent_builds += 1
        return _RunningAgent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(guardrails, "record_guardrail_block", lambda **_kwargs: None)
    monkeypatch.setattr(usage_ledger, "record_gateway_turn", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(server, "render_diff", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(server, "_record_tui_turn_usage", lambda **_kwargs: None)

    transports = [_Transport("one"), _Transport("two")]
    responses: list[dict] = []
    sid = ""

    def _resume_in_thread(index: int) -> None:
        responses.append(
            _resume(
                persisted_id,
                rid=f"resume-{index}",
                transport=transports[index],
            )
        )

    threads = [
        threading.Thread(target=_resume_in_thread, args=(index,)) for index in range(2)
    ]
    try:
        for thread in threads:
            thread.start()
        assert owner_hydrating.wait(timeout=3)
        assert waiter_joined.wait(timeout=3)
        release_hydration.set()
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive()

        assert len(responses) == 2
        assert all("error" not in response for response in responses)
        gateway_ids = {response["result"]["session_id"] for response in responses}
        assert len(gateway_ids) == 1
        sid = gateway_ids.pop()
        session = _wait_ready(sid)
        assert agent_builds == 1
        assert {id(transport) for transport in session["transports"]} == {
            id(transport) for transport in transports
        }

        prompt_barrier = threading.Barrier(3)
        prompt_responses: list[dict] = []

        def _submit(index: int) -> None:
            prompt_barrier.wait(timeout=3)
            prompt_responses.append(
                server.handle_request(
                    {
                        "id": f"prompt-{index}",
                        "method": "prompt.submit",
                        "params": {
                            "session_id": sid,
                            "text": f"distinct prompt {index}",
                            "user_message_id": f"distinct-{index}",
                        },
                    }
                )
            )

        submitters = [
            threading.Thread(target=_submit, args=(index,)) for index in range(2)
        ]
        for submitter in submitters:
            submitter.start()
        prompt_barrier.wait(timeout=3)
        for submitter in submitters:
            submitter.join(timeout=3)
            assert not submitter.is_alive()

        assert run_started.wait(timeout=3)
        assert len(prompt_responses) == 2
        assert (
            sum(
                response.get("result", {}).get("status") == "streaming"
                for response in prompt_responses
            )
            == 1
        )
        assert (
            sum(
                response.get("error", {}).get("code") == 4009
                for response in prompt_responses
            )
            == 1
        )
        assert agent_runs == 1
    finally:
        release_hydration.set()
        release_run.set()
        run_finished.wait(timeout=3)
        deadline = time.monotonic() + 3
        while (
            sid
            and server._sessions.get(sid, {}).get("running")
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        while (
            durable_db.get_recoverable_prompt_receipt(persisted_id)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        durable_db.close()


def test_build_failure_removes_every_alias_and_allows_clean_retry(monkeypatch):
    persisted_id = "20260714_120100_retry"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)

    release_failure = threading.Event()
    calls = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert release_failure.wait(timeout=3)
            raise RuntimeError("synthetic build failure")
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    first = _resume(persisted_id, rid="first")
    first_sid = first["result"]["session_id"]
    first_ready = server._sessions[first_sid]["agent_ready"]
    release_failure.set()
    assert first_ready.wait(timeout=3)

    assert first_sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations

    second = _resume(persisted_id, rid="second")
    second_sid = second["result"]["session_id"]
    assert second_sid != first_sid
    _wait_ready(second_sid)
    assert calls == 2


def test_root_and_active_lineage_ids_share_one_cold_actor(monkeypatch):
    root_id = "20260714_120125_root"
    active_id = "20260714_120125_active"
    identity_barrier = threading.Barrier(2)
    identity_calls = 0
    identity_lock = threading.Lock()
    release_hydration = threading.Event()
    owner_hydrating = threading.Event()

    class _LineageDB(_DB):
        def resolve_canonical_session_identity(self, session_id: str) -> dict:
            nonlocal identity_calls
            with identity_lock:
                identity_calls += 1
                call = identity_calls
            if call <= 2:
                identity_barrier.wait(timeout=3)
            return {
                "requested_session_id": session_id,
                "lineage_root_id": root_id,
                "active_session_id": active_id,
                "session_kind": "chat",
                "is_compression_tip": session_id == active_id,
            }

        def get_compression_tip(self, _session_id: str) -> str:
            return active_id

        def reopen_session(self, _session_id: str) -> None:
            owner_hydrating.set()
            assert release_hydration.wait(timeout=3)

    db = _LineageDB(root_id, active_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    waiter_joined = threading.Event()
    real_reserve = server._reserve_resumed_session

    def _observed_reserve(aliases):
        disposition, owner = real_reserve(aliases)
        if disposition == "wait":
            waiter_joined.set()
        return disposition, owner

    monkeypatch.setattr(server, "_reserve_resumed_session", _observed_reserve)
    responses: list[dict] = []
    callers = [
        threading.Thread(
            target=lambda session_id=session_id: responses.append(
                _resume(session_id, rid=session_id)
            )
        )
        for session_id in (root_id, active_id)
    ]
    for caller in callers:
        caller.start()
    assert owner_hydrating.wait(timeout=3)
    assert waiter_joined.wait(timeout=3)
    release_hydration.set()
    for caller in callers:
        caller.join(timeout=3)
        assert not caller.is_alive()

    gateway_ids = {response["result"]["session_id"] for response in responses}
    assert len(gateway_ids) == 1
    sid = gateway_ids.pop()
    _wait_ready(sid)
    assert builds == 1
    assert server._session_aliases[root_id] == sid
    assert server._session_aliases[active_id] == sid


def test_indexed_alias_cannot_hide_unindexed_duplicate_actor(monkeypatch):
    persisted_id = "20260714_120140_corrupt_duplicate"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    indexed = {"session_key": persisted_id}
    unindexed = {"session_key": persisted_id}
    server._sessions["indexed"] = indexed
    server._sessions["unindexed"] = unindexed
    server._session_aliases[persisted_id] = "indexed"

    response = _resume(persisted_id, rid="corrupt-duplicate")

    assert response["error"] == {
        "code": 5032,
        "message": (
            "session resume coordination failed: canonical identity matches "
            "multiple live actors"
        ),
    }
    assert server._sessions["indexed"] is indexed
    assert server._sessions["unindexed"] is unindexed
    assert builds == 0


def test_session_create_reservation_wins_publication_race_with_resume(monkeypatch):
    persisted_id = "20260714_120150_create"
    durable_row_visible = threading.Event()
    release_create = threading.Event()

    class _CreationDB(_DB):
        def __init__(self):
            super().__init__()

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {
                "id": key,
                "ended_at": None,
                "parent_session_id": None,
            }
            durable_row_visible.set()
            assert release_create.wait(timeout=3)

    db = _CreationDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: persisted_id)

    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    waiter_joined = threading.Event()
    real_reserve = server._reserve_resumed_session

    def _observed_reserve(aliases):
        disposition, owner = real_reserve(aliases)
        if disposition == "wait":
            waiter_joined.set()
        return disposition, owner

    monkeypatch.setattr(server, "_reserve_resumed_session", _observed_reserve)
    transports = [_Transport("create"), _Transport("resume")]
    responses: dict[str, dict] = {}

    def _create() -> None:
        token = bind_transport(transports[0])
        try:
            responses["create"] = server.handle_request(
                {"id": "create", "method": "session.create", "params": {}}
            )
        finally:
            reset_transport(token)

    def _resume_created() -> None:
        responses["resume"] = _resume(
            persisted_id,
            rid="resume-created",
            transport=transports[1],
        )

    creator = threading.Thread(target=_create)
    resumer = threading.Thread(target=_resume_created)
    creator.start()
    assert durable_row_visible.wait(timeout=3)
    resumer.start()
    assert waiter_joined.wait(timeout=3)
    release_create.set()
    creator.join(timeout=3)
    resumer.join(timeout=3)

    assert not creator.is_alive()
    assert not resumer.is_alive()
    assert all("error" not in response for response in responses.values())
    gateway_ids = {response["result"]["session_id"] for response in responses.values()}
    assert len(gateway_ids) == 1
    sid = gateway_ids.pop()
    session = _wait_ready(sid)
    assert builds == 1
    assert {id(transport) for transport in session["transports"]} == {
        id(transport) for transport in transports
    }


def test_pre_hydration_setup_failure_releases_owner_reservation(monkeypatch):
    persisted_id = "20260714_120175_setup_failure"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)

    def _fail_setup(*_args, **_kwargs):
        raise RuntimeError("synthetic replay setup failure")

    monkeypatch.setattr(server, "_subagent_replay_from_live_parent", _fail_setup)

    response = _resume(persisted_id, rid="setup-failure")

    assert response["error"]["code"] == 5000
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations
    assert server._sessions == {}


def test_branch_reservation_wins_publication_race_with_resume(monkeypatch):
    source_id = "20260714_120180_source"
    branch_id = "20260714_120180_branch"
    durable_row_visible = threading.Event()
    release_branch = threading.Event()

    class _BranchDB(_DB):
        def __init__(self):
            super().__init__(source_id)

        def get_session_title(self, _session_id: str) -> str:
            return "Source"

        def get_next_title_in_lineage(self, _title: str) -> str:
            return "Source (2)"

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {
                "id": key,
                "ended_at": None,
                "parent_session_id": source_id,
            }
            durable_row_visible.set()
            assert release_branch.wait(timeout=3)

        def append_message(self, **_kwargs) -> None:
            return None

        def set_session_title(self, _session_id: str, _title: str) -> None:
            return None

    db = _BranchDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: branch_id)

    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    source_session = {
        "agent": _Agent(),
        "cols": 80,
        "history": [{"role": "user", "content": "source prompt"}],
        "history_lock": threading.Lock(),
        "running": False,
        "session_key": source_id,
    }
    server._sessions["source-gateway"] = source_session

    waiter_joined = threading.Event()
    real_reserve = server._reserve_resumed_session

    def _observed_reserve(aliases):
        disposition, owner = real_reserve(aliases)
        if disposition == "wait":
            waiter_joined.set()
        return disposition, owner

    monkeypatch.setattr(server, "_reserve_resumed_session", _observed_reserve)
    responses: dict[str, dict] = {}

    def _branch() -> None:
        responses["branch"] = server.handle_request(
            {
                "id": "branch",
                "method": "session.branch",
                "params": {"session_id": "source-gateway"},
            }
        )

    def _resume_branch() -> None:
        responses["resume"] = _resume(branch_id, rid="resume-branch")

    brancher = threading.Thread(target=_branch)
    resumer = threading.Thread(target=_resume_branch)
    brancher.start()
    assert durable_row_visible.wait(timeout=3)
    resumer.start()
    assert waiter_joined.wait(timeout=3)
    release_branch.set()
    brancher.join(timeout=3)
    resumer.join(timeout=3)

    assert not brancher.is_alive()
    assert not resumer.is_alive()
    assert all("error" not in response for response in responses.values())
    assert (
        responses["branch"]["result"]["session_id"]
        == responses["resume"]["result"]["session_id"]
    )
    assert builds == 1


def test_branch_prompt_waits_until_callback_wiring_is_ready(monkeypatch):
    source_id = "20260714_120185_branch_ready_source"
    branch_id = "20260714_120185_branch_ready_child"

    class _BranchDB(_DB):
        def __init__(self):
            super().__init__(source_id)
            self.prepare_calls = 0

        def get_session_title(self, _session_id: str) -> str:
            return "Source"

        def get_next_title_in_lineage(self, _title: str) -> str:
            return "Source (2)"

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {
                "id": key,
                "ended_at": None,
                "parent_session_id": source_id,
            }

        def append_message(self, **_kwargs) -> None:
            return None

        def set_session_title(self, _session_id: str, _title: str) -> None:
            return None

        def prepare_prompt_receipt(self, *_args, **_kwargs):
            self.prepare_calls += 1
            raise AssertionError("prompt entered before branch wiring completed")

    db = _BranchDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: branch_id)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())
    monkeypatch.setattr(server, "_license_signed_in", lambda: False)
    source = _install_live_session("branch-ready-source", source_id)
    source["history"] = [{"role": "user", "content": "source prompt"}]

    wiring_started = threading.Event()
    release_wiring = threading.Event()

    def _wire(_sid: str) -> None:
        wiring_started.set()
        assert release_wiring.wait(timeout=3)

    monkeypatch.setattr(server, "_wire_callbacks", _wire)
    branch_responses: list[dict] = []
    prompt_responses: list[dict] = []
    brancher = threading.Thread(
        target=lambda: branch_responses.append(
            server.handle_request(
                {
                    "id": "branch-ready",
                    "method": "session.branch",
                    "params": {"session_id": "branch-ready-source"},
                }
            )
        )
    )
    brancher.start()
    assert wiring_started.wait(timeout=3)
    branch_sid, branch_session = next(
        (candidate_sid, candidate)
        for candidate_sid, candidate in server._sessions.items()
        if candidate_sid != "branch-ready-source"
    )
    assert branch_session["agent_ready"].is_set() is False

    resumed = _resume(branch_id, rid="resume-unwired-branch")
    assert resumed["result"]["session_id"] == branch_sid
    assert resumed["result"]["agent_ready"] is False

    prompt = threading.Thread(
        target=lambda: prompt_responses.append(
            server.handle_request(
                {
                    "id": "prompt-unwired-branch",
                    "method": "prompt.submit",
                    "params": {
                        "session_id": branch_sid,
                        "text": "wait for callbacks",
                        "user_message_id": "prompt-unwired-branch-user",
                    },
                }
            )
        )
    )
    prompt.start()
    time.sleep(0.05)
    assert prompt.is_alive()
    assert db.prepare_calls == 0

    release_wiring.set()
    brancher.join(timeout=3)
    prompt.join(timeout=3)

    assert not brancher.is_alive()
    assert not prompt.is_alive()
    assert "error" not in branch_responses[0]
    assert branch_responses[0]["result"]["session_id"] == branch_sid
    assert prompt_responses[0]["result"]["status"] == "sign_in_required"
    assert branch_session["agent_ready"].is_set() is True
    assert db.prepare_calls == 0


def test_branch_wiring_failure_wakes_waiters_and_removes_actor(monkeypatch):
    source_id = "20260714_120187_branch_failure_source"
    branch_id = "20260714_120187_branch_failure_child"

    class _BranchDB(_DB):
        def __init__(self):
            super().__init__(source_id)
            self.prepare_calls = 0

        def get_session_title(self, _session_id: str) -> str:
            return "Source"

        def get_next_title_in_lineage(self, _title: str) -> str:
            return "Source (2)"

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {"id": key, "parent_session_id": source_id}

        def append_message(self, **_kwargs) -> None:
            return None

        def set_session_title(self, _session_id: str, _title: str) -> None:
            return None

        def prepare_prompt_receipt(self, *_args, **_kwargs):
            self.prepare_calls += 1
            raise AssertionError("failed branch persisted a prompt")

    class _BranchAgent(_Agent):
        def __init__(self):
            self.close_calls = 0
            self.runs = 0

        def close_memory_connections(self) -> None:
            self.close_calls += 1

        def run_conversation(self, *_args, **_kwargs):
            self.runs += 1
            return {"final_response": "unexpected", "messages": []}

    db = _BranchDB()
    agent = _BranchAgent()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: branch_id)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: agent)
    _install_live_session("branch-failure-source", source_id)["history"] = [
        {"role": "user", "content": "source prompt"}
    ]
    wiring_started = threading.Event()
    release_wiring = threading.Event()

    def _wire(_sid: str) -> None:
        wiring_started.set()
        assert release_wiring.wait(timeout=3)
        raise RuntimeError("synthetic callback wiring failure")

    monkeypatch.setattr(server, "_wire_callbacks", _wire)
    branch_responses: list[dict] = []
    prompt_responses: list[dict] = []
    brancher = threading.Thread(
        target=lambda: branch_responses.append(
            server.handle_request(
                {
                    "id": "branch-wiring-failure",
                    "method": "session.branch",
                    "params": {"session_id": "branch-failure-source"},
                }
            )
        )
    )
    brancher.start()
    assert wiring_started.wait(timeout=3)
    branch_sid, branch_session = next(
        (candidate_sid, candidate)
        for candidate_sid, candidate in server._sessions.items()
        if candidate_sid != "branch-failure-source"
    )
    prompt = threading.Thread(
        target=lambda: prompt_responses.append(
            server.handle_request(
                {
                    "id": "prompt-failed-branch",
                    "method": "prompt.submit",
                    "params": {
                        "session_id": branch_sid,
                        "text": "must wake with wiring error",
                    },
                }
            )
        )
    )
    prompt.start()
    time.sleep(0.05)
    assert prompt.is_alive()

    release_wiring.set()
    brancher.join(timeout=3)
    prompt.join(timeout=3)

    assert not brancher.is_alive()
    assert not prompt.is_alive()
    assert branch_responses[0]["error"]["code"] == 5000
    assert (
        "synthetic callback wiring failure" in branch_responses[0]["error"]["message"]
    )
    assert prompt_responses[0]["error"] == {
        "code": 5032,
        "message": "synthetic callback wiring failure",
    }
    assert branch_session["agent_ready"].is_set() is True
    assert branch_session["agent_error"] == "synthetic callback wiring failure"
    assert branch_sid not in server._sessions
    assert branch_id not in server._session_aliases
    assert branch_id not in server._resume_reservations
    assert db.prepare_calls == 0
    assert agent.runs == 0
    assert agent.close_calls == 1


def test_close_during_branch_wiring_fails_branch_and_cleans_runtime(monkeypatch):
    from tools import approval

    source_id = "20260714_120189_branch_close_source"
    branch_id = "20260714_120189_branch_close_child"

    class _BranchDB(_DB):
        def __init__(self):
            super().__init__(source_id)

        def get_session_title(self, _session_id: str) -> str:
            return "Source"

        def get_next_title_in_lineage(self, _title: str) -> str:
            return "Source (2)"

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {"id": key, "parent_session_id": source_id}

        def append_message(self, **_kwargs) -> None:
            return None

        def set_session_title(self, _session_id: str, _title: str) -> None:
            return None

    class _BranchAgent(_Agent):
        def __init__(self):
            self.close_calls = 0
            self.shutdown_calls = 0

        def close_memory_connections(self) -> None:
            self.close_calls += 1

        def shutdown_memory_provider(self) -> None:
            self.shutdown_calls += 1

    db = _BranchDB()
    agent = _BranchAgent()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: branch_id)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: agent)
    _install_live_session("branch-close-source", source_id)["history"] = [
        {"role": "user", "content": "source prompt"}
    ]
    registered: set[str] = set()
    unregister_calls: list[str] = []
    monkeypatch.setattr(
        approval,
        "register_gateway_notify",
        lambda key, *_a, **_kw: registered.add(key),
    )

    def _unregister(key: str) -> None:
        unregister_calls.append(key)
        registered.discard(key)

    monkeypatch.setattr(approval, "unregister_gateway_notify", _unregister)
    wiring_started = threading.Event()
    release_wiring = threading.Event()

    def _wire(_sid: str) -> None:
        wiring_started.set()
        assert release_wiring.wait(timeout=3)

    monkeypatch.setattr(server, "_wire_callbacks", _wire)
    branch_responses: list[dict] = []
    brancher = threading.Thread(
        target=lambda: branch_responses.append(
            server.handle_request(
                {
                    "id": "branch-close-during-wiring",
                    "method": "session.branch",
                    "params": {"session_id": "branch-close-source"},
                }
            )
        )
    )
    brancher.start()
    assert wiring_started.wait(timeout=3)
    branch_sid, branch_session = next(
        (candidate_sid, candidate)
        for candidate_sid, candidate in server._sessions.items()
        if candidate_sid != "branch-close-source"
    )
    assert branch_id in registered

    closed = server.handle_request(
        {
            "id": "close-unwired-branch",
            "method": "session.close",
            "params": {"session_id": branch_sid},
        }
    )
    assert closed["result"]["closed"] is True
    assert branch_sid not in server._sessions
    release_wiring.set()
    brancher.join(timeout=3)

    assert not brancher.is_alive()
    assert branch_responses[0]["error"]["code"] == 5000
    assert (
        "session closed before branch response"
        in branch_responses[0]["error"]["message"]
    )
    assert branch_session["agent_ready"].is_set() is True
    assert branch_id not in server._session_aliases
    assert branch_id not in server._resume_reservations
    assert registered == set()
    assert branch_id in unregister_calls
    assert agent.shutdown_calls == 1
    assert agent.close_calls == 0


def test_close_cleans_aliases_and_context_reset_republishes_one_actor(monkeypatch):
    persisted_id = "20260714_120200_cleanup"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    reset_requested = threading.Event()
    reset_started = threading.Event()
    release_reset = threading.Event()

    def _make_agent(*_args, **_kwargs):
        if reset_requested.is_set():
            reset_started.set()
            assert release_reset.wait(timeout=3)
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    first = _resume(persisted_id, rid="first")
    first_sid = first["result"]["session_id"]
    _wait_ready(first_sid)
    assert server._session_aliases[persisted_id] == first_sid

    closed = server.handle_request(
        {
            "id": "close",
            "method": "session.close",
            "params": {"session_id": first_sid},
        }
    )
    assert closed["result"]["closed"] is True
    assert first_sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations

    second = _resume(persisted_id, rid="second")
    second_sid = second["result"]["session_id"]
    second_session = _wait_ready(second_sid)
    assert second_sid != first_sid
    assert server._session_aliases[persisted_id] == second_sid

    waiter_joined = threading.Event()
    real_reserve = server._reserve_resumed_session

    def _observed_reserve(aliases):
        disposition, owner = real_reserve(aliases)
        if disposition == "wait":
            waiter_joined.set()
        return disposition, owner

    monkeypatch.setattr(server, "_reserve_resumed_session", _observed_reserve)
    reset_errors: list[Exception] = []
    reset_resume: list[dict] = []

    def _reset() -> None:
        try:
            server._reset_session_agent(second_sid, second_session)
        except Exception as exc:
            reset_errors.append(exc)

    reset_requested.set()
    resetter = threading.Thread(target=_reset)
    resetter.start()
    assert reset_started.wait(timeout=3)
    resumer = threading.Thread(
        target=lambda: reset_resume.append(
            _resume(persisted_id, rid="resume-during-reset")
        )
    )
    resumer.start()
    assert waiter_joined.wait(timeout=3)
    release_reset.set()
    resetter.join(timeout=3)
    resumer.join(timeout=3)

    assert not resetter.is_alive()
    assert not resumer.is_alive()
    assert reset_errors == []
    assert reset_resume[0]["result"]["session_id"] == second_sid
    assert server._session_aliases[persisted_id] == second_sid
    assert persisted_id not in server._resume_reservations
    assert "registry_resetting" not in second_session
    assert server._sessions[second_sid] is second_session


@pytest.mark.parametrize("reset_fails", [False, True])
def test_prompt_admission_cannot_cross_context_reset_fence(
    monkeypatch,
    reset_fails: bool,
):
    from gateway import guardrails

    persisted_id = f"20260714_120250_prompt_reset_{int(reset_fails)}"
    sid = f"prompt-reset-{int(reset_fails)}"

    class _AdmissionDB(_DB):
        def __init__(self):
            super().__init__(persisted_id)
            self.prepare_calls = 0

        def prepare_prompt_receipt(self, *_args, **_kwargs):
            self.prepare_calls += 1
            raise AssertionError("reset-fenced prompt persisted a receipt")

    class _CountingAgent(_Agent):
        def __init__(self):
            self.runs = 0

        def run_conversation(self, *_args, **_kwargs):
            self.runs += 1
            return {"final_response": "unexpected", "messages": []}

    db = _AdmissionDB()
    old_agent = _CountingAgent()
    session = _install_live_session(sid, persisted_id, old_agent)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )

    prompt_past_lookup = threading.Event()
    release_prompt = threading.Event()

    def _license_gate() -> bool:
        prompt_past_lookup.set()
        assert release_prompt.wait(timeout=3)
        return True

    reset_building = threading.Event()
    release_reset = threading.Event()

    def _make_agent(*_args, **_kwargs):
        reset_building.set()
        assert release_reset.wait(timeout=3)
        if reset_fails:
            raise RuntimeError("synthetic fenced reset failure")
        return _CountingAgent()

    monkeypatch.setattr(server, "_license_signed_in", _license_gate)
    monkeypatch.setattr(server, "_make_agent", _make_agent)

    prompt_responses: list[dict] = []
    reset_errors: list[Exception] = []
    prompt = threading.Thread(
        target=lambda: prompt_responses.append(
            server.handle_request(
                {
                    "id": "prompt-during-reset",
                    "method": "prompt.submit",
                    "params": {
                        "session_id": sid,
                        "text": "must not run on stale context",
                        "user_message_id": "prompt-during-reset-user",
                    },
                }
            )
        )
    )

    def _reset() -> None:
        try:
            server._reset_session_agent(sid, session)
        except Exception as exc:
            reset_errors.append(exc)

    resetter = threading.Thread(target=_reset)
    prompt.start()
    assert prompt_past_lookup.wait(timeout=3)
    resetter.start()
    assert reset_building.wait(timeout=3)

    if reset_fails:
        release_reset.set()
        resetter.join(timeout=3)
        assert not resetter.is_alive()
        assert sid not in server._sessions
        release_prompt.set()
    else:
        # The live rebuilding fence rejects before reset can clear or overwrite
        # the session's turn latch.
        release_prompt.set()

    prompt.join(timeout=3)
    assert not prompt.is_alive()
    if not reset_fails:
        release_reset.set()
        resetter.join(timeout=3)
        assert not resetter.is_alive()

    assert prompt_responses[0]["error"]["code"] == 5032
    assert db.prepare_calls == 0
    assert old_agent.runs == 0
    assert session.get("running") is False
    if reset_fails:
        assert len(reset_errors) == 1
        assert "synthetic fenced reset failure" in str(reset_errors[0])
        assert sid not in server._sessions
        assert session.get("registry_resetting") is True
    else:
        assert reset_errors == []
        assert server._sessions[sid] is session
        assert "registry_resetting" not in session


def test_only_safe_turn_finally_reset_preserves_running_latch(monkeypatch):
    persisted_id = "20260714_120275_overflow_reset"
    sid = "overflow-reset"
    session = _install_live_session(sid, persisted_id)
    session["running"] = True
    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    with pytest.raises(server._SessionResetRejected, match="session busy"):
        server._reset_session_agent(sid, session)
    assert builds == 0
    assert server._sessions[sid] is session
    assert session["running"] is True

    server._reset_session_agent(sid, session, allow_running=True)
    assert builds == 1
    assert session["running"] is True
    server._mark_session_idle(session)
    assert session["running"] is False


def test_context_overflow_keeps_prompt_fenced_until_reset_claims_actor(
    monkeypatch,
    tmp_path,
):
    from elevate_state import SessionDB
    from gateway import guardrails, usage_ledger

    persisted_id = "20260714_120280_overflow_prompt_fence"
    sid = "overflow-prompt-fence"
    db = SessionDB(db_path=tmp_path / "overflow-prompt-fence.db")
    db.create_session(persisted_id, source="tui")
    prepare_calls = 0
    real_prepare = db.prepare_prompt_receipt

    def _prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(db, "prepare_prompt_receipt", _prepare)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(guardrails, "record_guardrail_block", lambda **_kwargs: None)
    monkeypatch.setattr(usage_ledger, "record_gateway_turn", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(server, "render_diff", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(server, "_record_tui_turn_usage", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_record_backend_event", lambda *_a, **_kw: None)

    complete_emitted = threading.Event()

    def _emit(event_type: str, _sid: str, _payload: dict) -> None:
        if event_type == "message.complete":
            complete_emitted.set()

    monkeypatch.setattr(server, "_emit", _emit)

    class _OverflowAgent(_Agent):
        def __init__(self):
            self.runs = 0

        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            self.runs += 1
            return {
                "completed": False,
                "error": "maximum context length exceeded",
                "failed": True,
                "final_response": "maximum context length exceeded",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                    {
                        "role": "assistant",
                        "content": "maximum context length exceeded",
                        "finish_reason": "error",
                    },
                ],
            }

    old_agent = _OverflowAgent()
    session = _install_live_session(sid, persisted_id, old_agent)
    reset_entered = threading.Event()
    release_reset = threading.Event()
    reset_calls = 0
    real_reset = server._reset_tui_context_overflow_session

    def _blocked_reset(reset_sid: str, reset_session: dict, reset_db) -> None:
        nonlocal reset_calls
        reset_calls += 1
        reset_entered.set()
        assert release_reset.wait(timeout=3)
        real_reset(reset_sid, reset_session, reset_db)

    monkeypatch.setattr(server, "_reset_tui_context_overflow_session", _blocked_reset)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())

    first = server.handle_request(
        {
            "id": "overflow-first",
            "method": "prompt.submit",
            "params": {
                "session_id": sid,
                "text": "overflow this turn",
                "user_message_id": "overflow-first-user",
            },
        }
    )
    try:
        assert first["result"]["status"] == "streaming"
        assert complete_emitted.wait(timeout=3)
        assert reset_entered.wait(timeout=3)
        assert session["running"] is True

        second = server.handle_request(
            {
                "id": "overflow-second",
                "method": "prompt.submit",
                "params": {
                    "session_id": sid,
                    "text": "must wait for clean actor",
                    "user_message_id": "overflow-second-user",
                },
            }
        )
        assert second["error"] == {"code": 4009, "message": "session busy"}
        assert prepare_calls == 1
        assert old_agent.runs == 1
        assert reset_calls == 1
    finally:
        release_reset.set()
        deadline = time.monotonic() + 3
        while session.get("running") and time.monotonic() < deadline:
            time.sleep(0.01)
        while (
            db.get_recoverable_prompt_receipt(persisted_id)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        server.handle_request(
            {
                "id": "overflow-force-close",
                "method": "session.close",
                "params": {"session_id": sid, "force": True},
            }
        )
        db.close()

    assert session["running"] is False
    assert reset_calls == 1
    assert old_agent.runs == 1


def test_normal_close_wins_before_prompt_admission_without_orphan_receipt(
    monkeypatch,
):
    from gateway import guardrails

    persisted_id = "20260714_120285_prompt_close"
    sid = "prompt-close"

    class _AdmissionDB(_DB):
        def __init__(self):
            super().__init__(persisted_id)
            self.prepare_calls = 0

        def prepare_prompt_receipt(self, *_args, **_kwargs):
            self.prepare_calls += 1
            raise AssertionError("closed actor persisted a prompt receipt")

    class _CountingAgent(_Agent):
        def __init__(self):
            self.runs = 0

        def run_conversation(self, *_args, **_kwargs):
            self.runs += 1
            return {"final_response": "unexpected", "messages": []}

    db = _AdmissionDB()
    agent = _CountingAgent()
    _install_live_session(sid, persisted_id, agent)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )
    prompt_past_lookup = threading.Event()
    release_prompt = threading.Event()

    def _license_gate() -> bool:
        prompt_past_lookup.set()
        assert release_prompt.wait(timeout=3)
        return True

    monkeypatch.setattr(server, "_license_signed_in", _license_gate)
    prompt_responses: list[dict] = []
    prompt = threading.Thread(
        target=lambda: prompt_responses.append(
            server.handle_request(
                {
                    "id": "prompt-close-race",
                    "method": "prompt.submit",
                    "params": {
                        "session_id": sid,
                        "text": "must not outlive close",
                        "user_message_id": "prompt-close-user",
                    },
                }
            )
        )
    )
    prompt.start()
    assert prompt_past_lookup.wait(timeout=3)

    closed = server.handle_request(
        {
            "id": "close-before-admission",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert closed["result"]["closed"] is True
    release_prompt.set()
    prompt.join(timeout=3)

    assert not prompt.is_alive()
    assert prompt_responses[0]["error"]["code"] == 5032
    assert db.prepare_calls == 0
    assert agent.runs == 0
    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases


def test_live_resume_pin_makes_concurrent_normal_close_detach(monkeypatch):
    persisted_id = "20260714_120287_live_resume_close"
    sid = "live-resume-close"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    session = _install_live_session(sid, persisted_id)
    setup_started = threading.Event()
    release_setup = threading.Event()

    def _blocked_setup(*_args, **_kwargs):
        setup_started.set()
        assert release_setup.wait(timeout=3)
        return [], 0, False, False

    monkeypatch.setattr(server, "_subagent_replay_from_live_parent", _blocked_setup)
    resume_responses: list[dict] = []
    resumer = threading.Thread(
        target=lambda: resume_responses.append(
            _resume(persisted_id, rid="live-resume-close-race")
        )
    )
    resumer.start()
    assert setup_started.wait(timeout=3)
    assert session["registry_resume_pins"] == 1

    closed = server.handle_request(
        {
            "id": "close-pinned-live-resume",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert closed["result"] == {
        "closed": False,
        "detached": True,
        "running": False,
        "persisted_session_id": persisted_id,
    }
    assert server._sessions[sid] is session

    release_setup.set()
    resumer.join(timeout=3)

    assert not resumer.is_alive()
    assert resume_responses[0]["result"]["session_id"] == sid
    assert server._sessions[sid] is session
    assert session["registry_resume_pins"] == 0


def test_live_resume_exception_always_releases_lifetime_pin(monkeypatch):
    persisted_id = "20260714_120287_live_resume_exception"
    sid = "live-resume-exception"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    session = _install_live_session(sid, persisted_id)
    monkeypatch.setattr(
        server,
        "_light_session_info",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            RuntimeError("synthetic post-pin response failure")
        ),
    )

    with pytest.raises(RuntimeError, match="synthetic post-pin response failure"):
        _resume(persisted_id, rid="live-resume-pin-exception")

    assert session["registry_resume_pins"] == 0
    closed = server.handle_request(
        {
            "id": "close-after-pin-exception",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert closed["result"]["closed"] is True
    assert sid not in server._sessions


def test_context_reset_waits_for_live_resume_lifetime_pin(monkeypatch):
    persisted_id = "20260714_120287_live_resume_reset"
    sid = "live-resume-reset"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    session = _install_live_session(sid, persisted_id)
    setup_started = threading.Event()
    release_setup = threading.Event()
    builds = 0

    def _blocked_setup(*_args, **_kwargs):
        setup_started.set()
        assert release_setup.wait(timeout=3)
        return [], 0, False, False

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_subagent_replay_from_live_parent", _blocked_setup)
    monkeypatch.setattr(server, "_make_agent", _make_agent)
    resume_responses: list[dict] = []
    reset_errors: list[Exception] = []
    resumer = threading.Thread(
        target=lambda: resume_responses.append(
            _resume(persisted_id, rid="live-resume-before-reset")
        )
    )

    def _reset() -> None:
        try:
            server._reset_session_agent(sid, session)
        except Exception as exc:
            reset_errors.append(exc)

    resetter = threading.Thread(target=_reset)
    resumer.start()
    assert setup_started.wait(timeout=3)
    resetter.start()
    time.sleep(0.05)
    assert resetter.is_alive()
    assert builds == 0

    release_setup.set()
    resumer.join(timeout=3)
    resetter.join(timeout=3)

    assert not resumer.is_alive()
    assert not resetter.is_alive()
    assert resume_responses[0]["result"]["session_id"] == sid
    assert reset_errors == []
    assert builds == 1
    assert server._sessions[sid] is session
    assert session["registry_resume_pins"] == 0
    assert "registry_resetting" not in session


def test_cold_owner_response_pin_prevents_waiter_close_from_returning_dead_sid(
    monkeypatch,
):
    persisted_id = "20260714_120287_cold_owner_pin"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())
    owner_building_response = threading.Event()
    release_owner_response = threading.Event()

    def _light_info(agent=None):
        if threading.current_thread().name == "cold-owner-response":
            owner_building_response.set()
            assert release_owner_response.wait(timeout=3)
        return {"model": "test/model"}

    monkeypatch.setattr(server, "_light_session_info", _light_info)
    owner_responses: list[dict] = []
    owner = threading.Thread(
        name="cold-owner-response",
        target=lambda: owner_responses.append(
            _resume(persisted_id, rid="cold-owner-pinned-response")
        ),
    )
    owner.start()
    assert owner_building_response.wait(timeout=3)
    sid, session = next(iter(server._sessions.items()))
    assert session["registry_resume_pins"] >= 1

    waiter = _resume(persisted_id, rid="cold-owner-waiter")
    assert waiter["result"]["session_id"] == sid
    closed = server.handle_request(
        {
            "id": "close-cold-owner-response",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert closed["result"]["closed"] is False
    assert closed["result"]["detached"] is True
    assert server._sessions[sid] is session

    release_owner_response.set()
    owner.join(timeout=3)

    assert not owner.is_alive()
    assert owner_responses[0]["result"]["session_id"] == sid
    assert server._sessions[sid] is session
    assert session["registry_resume_pins"] == 0


def test_cold_owner_response_observes_build_failure_before_success(monkeypatch):
    persisted_id = "20260714_120287_cold_owner_failure"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    build_started = threading.Event()
    release_build = threading.Event()
    response_building = threading.Event()
    release_response = threading.Event()

    def _make_agent(*_args, **_kwargs):
        build_started.set()
        assert release_build.wait(timeout=3)
        raise RuntimeError("synthetic owner build failure")

    def _light_info(agent=None):
        if threading.current_thread().name == "cold-owner-failure":
            response_building.set()
            assert release_response.wait(timeout=3)
        return {"model": "test/model"}

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    monkeypatch.setattr(server, "_light_session_info", _light_info)
    responses: list[dict] = []
    owner = threading.Thread(
        name="cold-owner-failure",
        target=lambda: responses.append(
            _resume(persisted_id, rid="cold-owner-failure-response")
        ),
    )
    owner.start()
    assert build_started.wait(timeout=3)
    assert response_building.wait(timeout=3)
    sid, session = next(iter(server._sessions.items()))
    assert session["registry_resume_pins"] == 1

    release_build.set()
    assert session["agent_ready"].wait(timeout=3)
    assert session["agent_error"] == "synthetic owner build failure"
    assert server._sessions[sid] is session
    assert session["registry_deferred_remove_sid"] == sid
    release_response.set()
    owner.join(timeout=3)

    assert not owner.is_alive()
    assert responses[0]["error"] == {
        "code": 5032,
        "message": "synthetic owner build failure",
    }
    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations
    assert session["registry_resume_pins"] == 0


def test_live_waiter_response_observes_cold_build_failure(monkeypatch):
    persisted_id = "20260714_120287_cold_waiter_failure"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    build_started = threading.Event()
    release_build = threading.Event()

    def _make_agent(*_args, **_kwargs):
        build_started.set()
        assert release_build.wait(timeout=3)
        raise RuntimeError("synthetic waiter build failure")

    waiter_setup = threading.Event()
    release_waiter = threading.Event()

    def _setup(*_args, **_kwargs):
        if threading.current_thread().name == "cold-live-waiter":
            waiter_setup.set()
            assert release_waiter.wait(timeout=3)
        return [], 0, False, False

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    monkeypatch.setattr(server, "_subagent_replay_from_live_parent", _setup)
    owner = _resume(persisted_id, rid="cold-owner-before-waiter-failure")
    sid = owner["result"]["session_id"]
    session = server._sessions[sid]
    assert build_started.wait(timeout=3)

    waiter_responses: list[dict] = []
    waiter = threading.Thread(
        name="cold-live-waiter",
        target=lambda: waiter_responses.append(
            _resume(persisted_id, rid="cold-live-waiter-failure")
        ),
    )
    waiter.start()
    assert waiter_setup.wait(timeout=3)
    assert session["registry_resume_pins"] == 1

    release_build.set()
    assert session["agent_ready"].wait(timeout=3)
    assert server._sessions[sid] is session
    release_waiter.set()
    waiter.join(timeout=3)

    assert not waiter.is_alive()
    assert waiter_responses[0]["error"] == {
        "code": 5032,
        "message": "synthetic waiter build failure",
    }
    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations
    assert session["registry_resume_pins"] == 0


def test_create_response_pin_prevents_concurrent_close_from_returning_dead_sid(
    monkeypatch,
):
    persisted_id = "20260714_120287_create_response_pin"

    class _CreationDB(_DB):
        def __init__(self):
            super().__init__()

        def create_session(self, key: str, **_kwargs) -> None:
            self.rows[key] = {"id": key, "parent_session_id": None}

    db = _CreationDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_new_session_key", lambda: persisted_id)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())
    response_building = threading.Event()
    release_response = threading.Event()

    def _terminal_cwd() -> str:
        if threading.current_thread().name == "create-owner-response":
            response_building.set()
            assert release_response.wait(timeout=3)
        return "/tmp"

    monkeypatch.setattr(server, "_terminal_cwd", _terminal_cwd)
    responses: list[dict] = []
    creator = threading.Thread(
        name="create-owner-response",
        target=lambda: responses.append(
            server.handle_request(
                {
                    "id": "create-pinned-response",
                    "method": "session.create",
                    "params": {},
                }
            )
        ),
    )
    creator.start()
    assert response_building.wait(timeout=3)
    sid, session = next(iter(server._sessions.items()))
    assert session["registry_resume_pins"] == 1

    closed = server.handle_request(
        {
            "id": "close-create-response",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert closed["result"] == {
        "closed": False,
        "detached": True,
        "running": False,
        "persisted_session_id": persisted_id,
    }
    release_response.set()
    creator.join(timeout=3)

    assert not creator.is_alive()
    assert responses[0]["result"]["session_id"] == sid
    assert server._sessions[sid] is session
    assert session["registry_resume_pins"] == 0


def test_close_wakes_rpc_waiting_for_published_actor_build(monkeypatch):
    persisted_id = "20260714_120288_close_build_waiter"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    build_started = threading.Event()
    release_build = threading.Event()
    orphan_cleaned = threading.Event()

    class _BuiltAgent(_Agent):
        def close_memory_connections(self) -> None:
            orphan_cleaned.set()

    def _make_agent(*_args, **_kwargs):
        build_started.set()
        assert release_build.wait(timeout=3)
        return _BuiltAgent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    resumed = _resume(persisted_id, rid="publish-building-actor")
    sid = resumed["result"]["session_id"]
    session = server._sessions[sid]
    assert build_started.wait(timeout=3)
    assert session["agent_ready"].is_set() is False

    wait_started = threading.Event()
    real_wait = server._wait_agent

    def _observed_wait(wait_session: dict, rid: str, timeout: float = 30.0):
        wait_started.set()
        return real_wait(wait_session, rid, timeout)

    monkeypatch.setattr(server, "_wait_agent", _observed_wait)
    usage_responses: list[dict] = []
    waiter = threading.Thread(
        target=lambda: usage_responses.append(
            server.handle_request(
                {
                    "id": "usage-waiting-on-build",
                    "method": "session.usage",
                    "params": {"session_id": sid},
                }
            )
        )
    )
    waiter.start()
    assert wait_started.wait(timeout=3)

    started = time.monotonic()
    closed = server.handle_request(
        {
            "id": "close-building-actor",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    waiter.join(timeout=1)

    assert closed["result"]["closed"] is True
    assert not waiter.is_alive()
    assert time.monotonic() - started < 0.5
    assert usage_responses[0]["error"] == {
        "code": 5032,
        "message": "session closed",
    }
    assert session["agent_ready"].is_set() is True
    assert session["agent_error"] == "session closed"
    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations

    release_build.set()
    assert orphan_cleaned.wait(timeout=3)


def test_prompt_admission_wins_before_normal_close_and_forces_detach(
    monkeypatch,
    tmp_path,
):
    from elevate_state import SessionDB
    from gateway import guardrails, usage_ledger

    persisted_id = "20260714_120290_prompt_close_detach"
    sid = "prompt-close-detach"
    db = SessionDB(db_path=tmp_path / "prompt-close-detach.db")
    db.create_session(persisted_id, source="tui")
    receipt_started = threading.Event()
    release_receipt = threading.Event()
    prepare_calls = 0
    real_prepare = db.prepare_prompt_receipt

    def _prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        receipt_started.set()
        assert release_receipt.wait(timeout=3)
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(db, "prepare_prompt_receipt", _prepare)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(guardrails, "record_guardrail_block", lambda **_kwargs: None)
    monkeypatch.setattr(usage_ledger, "record_gateway_turn", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(server, "render_diff", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(server, "_record_tui_turn_usage", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_record_backend_event", lambda *_a, **_kw: None)

    run_started = threading.Event()
    release_run = threading.Event()

    class _RunningAgent(_Agent):
        def __init__(self):
            self.runs = 0

        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            self.runs += 1
            run_started.set()
            assert release_run.wait(timeout=5)
            return {
                "final_response": "done",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                    {"role": "assistant", "content": "done"},
                ],
            }

    agent = _RunningAgent()
    session = _install_live_session(sid, persisted_id, agent)
    prompt_responses: list[dict] = []
    close_responses: list[dict] = []
    prompt = threading.Thread(
        target=lambda: prompt_responses.append(
            server.handle_request(
                {
                    "id": "prompt-wins-close-race",
                    "method": "prompt.submit",
                    "params": {
                        "session_id": sid,
                        "text": "run exactly once",
                        "user_message_id": "prompt-wins-close-user",
                    },
                }
            )
        )
    )
    close = threading.Thread(
        target=lambda: close_responses.append(
            server.handle_request(
                {
                    "id": "close-after-admission",
                    "method": "session.close",
                    "params": {"session_id": sid},
                }
            )
        )
    )
    try:
        prompt.start()
        assert receipt_started.wait(timeout=3)
        close.start()
        time.sleep(0.05)
        assert close.is_alive()
        release_receipt.set()
        prompt.join(timeout=3)
        close.join(timeout=3)

        assert not prompt.is_alive()
        assert not close.is_alive()
        assert prompt_responses[0]["result"]["status"] == "streaming"
        assert close_responses[0]["result"] == {
            "closed": False,
            "detached": True,
            "running": True,
            "persisted_session_id": persisted_id,
        }
        assert run_started.wait(timeout=3)
        assert prepare_calls == 1
        assert agent.runs == 1
        assert server._sessions[sid] is session
    finally:
        release_receipt.set()
        release_run.set()
        prompt.join(timeout=3)
        close.join(timeout=3)
        deadline = time.monotonic() + 3
        while session.get("running") and time.monotonic() < deadline:
            time.sleep(0.01)
        while (
            db.get_recoverable_prompt_receipt(persisted_id)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        server.handle_request(
            {
                "id": "force-close-cleanup",
                "method": "session.close",
                "params": {"session_id": sid, "force": True},
            }
        )
        db.close()


def test_different_persisted_sessions_build_independently(monkeypatch):
    session_ids = ("20260714_120300_a", "20260714_120300_b")
    db = _DB(*session_ids)
    monkeypatch.setattr(server, "_get_db", lambda: db)

    build_barrier = threading.Barrier(2)
    built: list[str] = []
    built_lock = threading.Lock()

    def _make_agent(_sid, key, **_kwargs):
        with built_lock:
            built.append(key)
        build_barrier.wait(timeout=3)
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    responses = [_resume(session_id, rid=session_id) for session_id in session_ids]
    gateway_ids = [response["result"]["session_id"] for response in responses]
    for sid in gateway_ids:
        _wait_ready(sid)

    assert len(set(gateway_ids)) == 2
    assert set(built) == set(session_ids)


def test_context_reset_build_failure_cleans_actor_for_cold_retry(monkeypatch):
    persisted_id = "20260714_120350_reset_retry"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())

    first = _resume(persisted_id, rid="first")
    first_sid = first["result"]["session_id"]
    first_session = _wait_ready(first_sid)

    def _fail_reset(*_args, **_kwargs):
        raise RuntimeError("synthetic reset build failure")

    monkeypatch.setattr(server, "_make_agent", _fail_reset)
    with pytest.raises(RuntimeError, match="synthetic reset build failure"):
        server._reset_session_agent(first_sid, first_session)

    assert first_sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations

    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_kw: _Agent())
    second = _resume(persisted_id, rid="second")
    second_sid = second["result"]["session_id"]
    assert second_sid != first_sid
    _wait_ready(second_sid)


def test_context_reset_failure_closes_worker_and_unregisters_notify(monkeypatch):
    from tools import approval

    persisted_id = "20260714_120360_reset_runtime_cleanup"
    sid = "reset-runtime-cleanup"

    class _OldAgent(_Agent):
        def __init__(self):
            self.close_calls = 0

        def close_memory_connections(self) -> None:
            self.close_calls += 1

    class _Worker:
        def __init__(self):
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    old_agent = _OldAgent()
    worker = _Worker()
    session = _install_live_session(sid, persisted_id, old_agent)
    session["slash_worker"] = worker
    unregister_calls: list[str] = []
    monkeypatch.setattr(
        approval,
        "unregister_gateway_notify",
        lambda key: unregister_calls.append(key),
    )
    monkeypatch.setattr(
        server,
        "_make_agent",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            RuntimeError("synthetic reset runtime failure")
        ),
    )

    with pytest.raises(RuntimeError, match="synthetic reset runtime failure"):
        server._reset_session_agent(sid, session)

    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations
    assert worker.close_calls == 1
    assert unregister_calls == [persisted_id]
    assert old_agent.close_calls == 1
    assert session["agent_memory_released"] is True


def test_personality_reset_failure_does_not_reuse_removed_actor(monkeypatch):
    persisted_id = "20260714_120375_personality_failure"
    sid = "personality-failure"
    emitted: list[tuple] = []

    class _OldAgent:
        def __init__(self):
            self.close_calls = 0
            self.ephemeral_system_prompt = "old prompt"
            self._cached_system_prompt = "old cache"

        def close_memory_connections(self) -> None:
            self.close_calls += 1

    old_agent = _OldAgent()
    session = {
        "agent": old_agent,
        "history_lock": threading.Lock(),
        "registry_aliases": {persisted_id},
        "running": False,
        "session_key": persisted_id,
    }
    server._sessions[sid] = session
    server._session_aliases[persisted_id] = sid

    def _fail_reset(*_args, **_kwargs):
        raise RuntimeError("synthetic personality reset failure")

    monkeypatch.setattr(server, "_make_agent", _fail_reset)
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda _cfg=None: {"helpful": "new prompt"},
    )
    monkeypatch.setattr(server, "_write_config_key", lambda *_args: None)
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

    response = server.handle_request(
        {
            "id": "personality-config",
            "method": "config.set",
            "params": {
                "session_id": sid,
                "key": "personality",
                "value": "helpful",
            },
        }
    )

    assert response["error"] == {
        "code": 5001,
        "message": "synthetic personality reset failure",
    }
    assert sid not in server._sessions
    assert persisted_id not in server._session_aliases
    assert persisted_id not in server._resume_reservations
    assert session["agent"] is None
    assert old_agent.ephemeral_system_prompt == "old prompt"
    assert old_agent._cached_system_prompt == "old cache"
    assert old_agent.close_calls == 1
    assert emitted == []


def test_agent_build_can_reenter_resume_without_deadlock(monkeypatch):
    persisted_id = "20260714_120400_reentrant"
    db = _DB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    nested: list[dict] = []

    def _make_agent(sid, _key, **_kwargs):
        nested.append(_resume(persisted_id, rid="nested"))
        assert nested[-1]["result"]["session_id"] == sid
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    outer = _resume(persisted_id, rid="outer")
    sid = outer["result"]["session_id"]
    _wait_ready(sid)

    assert len(nested) == 1
    assert nested[0]["result"]["session_id"] == sid


def test_agent_build_reentrant_resume_defers_receipt_recovery_until_ready(monkeypatch):
    persisted_id = "20260714_120425_reentrant_receipt"

    class _ReceiptDB(_DB):
        def get_recoverable_prompt_receipt(self, _session_id: str):
            return {"client_message_id": "recover-me", "status": "pending"}

    db = _ReceiptDB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    nested: list[dict] = []
    nested_elapsed: list[float] = []
    recoveries: list[tuple[str, bool]] = []

    def _recover(sid: str, session: dict) -> bool:
        recoveries.append((sid, session["agent_ready"].is_set()))
        return True

    def _make_agent(sid, _key, **_kwargs):
        started = time.monotonic()
        nested.append(_resume(persisted_id, rid="nested-with-receipt"))
        nested_elapsed.append(time.monotonic() - started)
        assert nested[-1]["result"]["session_id"] == sid
        assert nested[-1]["result"]["agent_ready"] is False
        return _Agent()

    monkeypatch.setattr(server, "_recover_pending_prompt", _recover)
    monkeypatch.setattr(server, "_make_agent", _make_agent)

    outer = _resume(persisted_id, rid="outer-with-receipt")
    sid = outer["result"]["session_id"]
    _wait_ready(sid)

    assert nested_elapsed[0] < 0.5
    assert recoveries == [(sid, True)]


def test_canonical_identity_failure_never_degrades_to_two_physical_actors(
    monkeypatch,
):
    root_id = "20260714_120450_identity_root"
    active_id = "20260714_120450_identity_active"

    class _FailingIdentityDB(_DB):
        def resolve_canonical_session_identity(self, _session_id: str) -> dict:
            raise RuntimeError("canonical store unavailable")

    db = _FailingIdentityDB(root_id, active_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)

    responses = [
        _resume(root_id, rid="identity-root"),
        _resume(active_id, rid="identity-active"),
    ]

    assert all(response["error"]["code"] == 5032 for response in responses)
    assert all(
        "canonical store unavailable" in response["error"]["message"]
        for response in responses
    )
    assert builds == 0
    assert server._sessions == {}
    assert server._session_aliases == {}
    assert server._resume_reservations == {}


def test_wait_timeout_fails_closed_without_stealing_owner(monkeypatch):
    persisted_id = "20260714_120500_timeout"
    owner_hydrating = threading.Event()
    release_owner = threading.Event()

    class _SlowDB(_DB):
        def reopen_session(self, _session_id: str) -> None:
            owner_hydrating.set()
            assert release_owner.wait(timeout=3)

    db = _SlowDB(persisted_id)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_RESUME_RESERVATION_WAIT_S", 0.05)
    builds = 0

    def _make_agent(*_args, **_kwargs):
        nonlocal builds
        builds += 1
        return _Agent()

    monkeypatch.setattr(server, "_make_agent", _make_agent)
    owner_response: list[dict] = []
    owner = threading.Thread(
        target=lambda: owner_response.append(_resume(persisted_id, rid="owner"))
    )
    owner.start()
    assert owner_hydrating.wait(timeout=3)

    timed_out = _resume(persisted_id, rid="waiter")
    assert timed_out["error"]["code"] == 5032
    assert "timed out" in timed_out["error"]["message"]
    assert persisted_id in server._resume_reservations
    assert builds == 0

    release_owner.set()
    owner.join(timeout=3)
    assert not owner.is_alive()
    assert "error" not in owner_response[0]
    sid = owner_response[0]["result"]["session_id"]
    _wait_ready(sid)
    assert builds == 1
    assert server._session_aliases[persisted_id] == sid
    assert persisted_id not in server._resume_reservations
