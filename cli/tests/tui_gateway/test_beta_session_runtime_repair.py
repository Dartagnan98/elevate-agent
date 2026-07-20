"""Realtor Beta regressions for stale persisted provider/session state."""

from __future__ import annotations

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from elevate_cli import auth
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    BetaProviderPolicyError,
    beta_runtime_repair_blocked_reason,
    beta_runtime_repair_generation,
    clear_beta_runtime_repair_state,
    mark_beta_runtime_repair_pending,
    read_beta_codex_auth_status,
)
from elevate_cli.web_session_activity import mark_session_activity
from tui_gateway import server


class _Agent:
    def __init__(self, model: str, provider: str) -> None:
        self.model = model
        self.provider = provider
        self.close_calls = 0
        self.interrupt_calls = 0

    def close_memory_connections(self) -> None:
        self.close_calls += 1

    def shutdown_memory_provider(self) -> None:
        self.close_calls += 1

    def interrupt(self) -> None:
        self.interrupt_calls += 1


class _PersistedGeminiDB:
    def __init__(self, session_id: str, history: list[dict]) -> None:
        self.row = {
            "id": session_id,
            "model": "gemini-2.5-flash",
            "ended_at": None,
            "parent_session_id": None,
            "compaction_cursor": 0,
        }
        self.history = history

    def resolve_session_id(self, value: str) -> str:
        return value

    def get_session(self, session_id: str):
        return self.row if session_id == self.row["id"] else None

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
        return [dict(message) for message in self.history]

    def get_recoverable_prompt_receipt(self, _session_id: str):
        return None


def _release_test_delegate_repair_leases() -> None:
    from tools.delegate_tool import (
        release_delegate_provider_repair,
        set_spawn_paused,
    )

    with server._beta_runtime_repair_targets_lock:
        leases = list(server._beta_runtime_delegate_repair_leases.values())
    for lease in leases:
        try:
            release_delegate_provider_repair(lease)
        except RuntimeError:
            pass
    with server._beta_runtime_repair_targets_lock:
        server._beta_runtime_delegate_repair_leases.clear()
    set_spawn_paused(False)


@pytest.fixture(autouse=True)
def _isolated_beta_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    from elevate_cli.web_routes import chat_websockets

    monkeypatch.setattr(
        chat_websockets,
        "_dashboard_repair_control_plane_ready",
        True,
    )
    with chat_websockets._pty_repair_condition:
        chat_websockets._active_pty_bridges.clear()
        chat_websockets._pty_publishers.clear()
        chat_websockets._pty_repair_barrier = None
    _release_test_delegate_repair_leases()
    server.install_exact_beta_sidecar_registration_check(None)
    with server._session_registry_lock:
        server._sessions.clear()
        server._session_aliases.clear()
        server._resume_reservations.clear()
    with server._beta_runtime_repair_targets_lock:
        server._beta_runtime_repair_targets.clear()
        server._beta_runtime_repair_completed.clear()
        server._beta_runtime_control_receipts.clear()
        server._beta_runtime_control_attempts.clear()
    clear_beta_runtime_repair_state()
    yield
    clear_beta_runtime_repair_state()
    _release_test_delegate_repair_leases()
    server.install_exact_beta_sidecar_registration_check(None)
    with server._beta_runtime_repair_targets_lock:
        server._beta_runtime_repair_targets.clear()
        server._beta_runtime_repair_completed.clear()
        server._beta_runtime_control_receipts.clear()
        server._beta_runtime_control_attempts.clear()
    with server._session_registry_lock:
        server._sessions.clear()
        server._session_aliases.clear()
        server._resume_reservations.clear()
    with chat_websockets._pty_repair_condition:
        chat_websockets._active_pty_bridges.clear()
        chat_websockets._pty_publishers.clear()
        chat_websockets._pty_repair_barrier = None


def _write_valid_beta_auth(home) -> None:
    (home / "auth.json").write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider": BETA_ALLOWED_PROVIDER,
                "providers": {
                    BETA_ALLOWED_PROVIDER: {
                        "tokens": {
                            "access_token": "valid-local-beta-token",
                            "refresh_token": "valid-local-beta-refresh",
                        },
                        "auth_mode": "chatgpt",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _install_live_session(sid: str, persisted_id: str, agent: _Agent) -> dict:
    ready = threading.Event()
    ready.set()
    history = [
        {"role": "user", "content": "historical question"},
        {"role": "assistant", "content": "historical answer"},
    ]
    session = {
        "agent": agent,
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
        "history": history,
        "history_lock": threading.Lock(),
        "history_version": 7,
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


def _patch_agent_rebuild(monkeypatch, new_agent: _Agent) -> None:
    monkeypatch.setattr(server, "_make_agent", lambda *_args, **_kwargs: new_agent)
    monkeypatch.setattr(
        server,
        "_session_info",
        lambda agent: {"model": agent.model, "provider": agent.provider},
    )
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda _session: None)
    monkeypatch.setattr(server, "_set_session_context", lambda *_args: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda *_args: None)
    monkeypatch.setattr(server, "_load_show_reasoning", lambda: False)
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "all")


def test_beta_tui_model_switch_stops_before_actor_env_or_config_mutation(
    monkeypatch,
):
    agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = {"agent": agent, "running": False, "session_key": "beta-model"}
    monkeypatch.setenv("ELEVATE_MODEL", "gpt-5.5")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", BETA_ALLOWED_PROVIDER)
    monkeypatch.setattr(
        "elevate_cli.model_switch.parse_model_flags",
        lambda *_args, **_kwargs: pytest.fail("Beta model flags were parsed"),
    )
    monkeypatch.setattr(
        server,
        "_persist_model_switch",
        lambda *_args, **_kwargs: pytest.fail("Beta model switch persisted"),
    )

    with pytest.raises(BetaProviderPolicyError) as caught:
        server._apply_model_switch(
            "beta-model",
            session,
            "gpt-5.4 --global",
        )

    assert caught.value.code == "beta_app_onboarding_required"
    assert agent.model == "gpt-5.5"
    assert agent.provider == BETA_ALLOWED_PROVIDER
    assert os.environ["ELEVATE_MODEL"] == "gpt-5.5"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == BETA_ALLOWED_PROVIDER


def test_beta_tui_config_set_and_model_slash_return_app_guidance_without_mutation(
    monkeypatch,
):
    sid = "beta-model-rpc"
    agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = {"agent": agent, "running": False, "session_key": sid}
    server._sessions[sid] = session
    monkeypatch.setenv("ELEVATE_MODEL", "gpt-5.5")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", BETA_ALLOWED_PROVIDER)
    monkeypatch.setattr(
        server,
        "_persist_model_switch",
        lambda *_args, **_kwargs: pytest.fail("Beta model switch persisted"),
    )

    response = server.handle_request(
        {
            "id": "beta-model-config-set",
            "method": "config.set",
            "params": {
                "session_id": sid,
                "key": "model",
                "value": "gpt-5.4 --global",
            },
        }
    )
    slash_warning = server._mirror_slash_side_effects(
        sid,
        session,
        "/model gpt-5.4 --global",
    )

    assert response["error"]["code"] == 5001
    assert "beta_app_onboarding_required" in response["error"]["message"]
    assert "beta_app_onboarding_required" in slash_warning
    assert agent.model == "gpt-5.5"
    assert agent.provider == BETA_ALLOWED_PROVIDER
    assert os.environ["ELEVATE_MODEL"] == "gpt-5.5"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == BETA_ALLOWED_PROVIDER


def test_beta_sidecar_disconnect_blocks_all_actor_and_prompt_admission():
    registration = {"ready": False}
    server.install_exact_beta_sidecar_registration_check(
        lambda: registration["ready"]
    )

    for method, params in (
        ("session.create", {}),
        ("session.resume", {"session_id": "persisted"}),
        ("session.branch", {"session_id": "live"}),
        ("prompt.submit", {"session_id": "live", "text": "continue"}),
    ):
        response = server._methods[method](f"disconnected-{method}", params)
        assert response["error"]["code"] == 5032
        assert "registration" in response["error"]["message"]

    registration["ready"] = True
    assert server._beta_runtime_repair_admission_error("ready") is None


def test_persisted_gemini_session_cold_resume_uses_repaired_codex_runtime(
    tmp_path,
    monkeypatch,
):
    """The old row stays historical while the resumed actor is Codex."""
    _write_valid_beta_auth(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")

    auth._update_config_for_provider(BETA_ALLOWED_PROVIDER, BETA_CODEX_BASE_URL)

    assert "ELEVATE_MODEL" not in os.environ
    assert "ELEVATE_INFERENCE_PROVIDER" not in os.environ
    repaired = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert repaired["model"]["provider"] == BETA_ALLOWED_PROVIDER
    assert repaired["model"]["default"] == "gpt-5.5"

    persisted_id = "20260715_120000_gemini_history"
    history = [
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "Historical Gemini answer"},
    ]
    db = _PersistedGeminiDB(persisted_id, history)
    seen_models: list[str] = []

    def _make_agent(_sid, _key, **_kwargs):
        model = server._resolve_model()
        seen_models.append(model)
        return _Agent(model, BETA_ALLOWED_PROVIDER)

    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_make_agent", _make_agent)
    monkeypatch.setattr(server, "_enable_gateway_prompts", lambda: None)
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_recover_pending_prompt", lambda *_args: False)
    monkeypatch.setattr(
        server,
        "_session_info",
        lambda agent: {"model": agent.model, "provider": agent.provider},
    )
    monkeypatch.setattr(
        server,
        "_light_session_info",
        lambda agent=None: {
            "model": getattr(agent, "model", None) or server._resolve_model()
        },
    )
    monkeypatch.setattr(server, "_set_session_context", lambda *_args: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda *_args: None)
    monkeypatch.setattr(server, "_load_show_reasoning", lambda: False)
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "all")
    monkeypatch.setattr(server, "_restart_slash_worker", lambda _session: None)
    monkeypatch.setattr(
        server,
        "_SlashWorker",
        lambda *_args, **_kwargs: SimpleNamespace(close=lambda: None),
    )

    response = server._methods["session.resume"](
        "resume-gemini",
        {"session_id": persisted_id, "include_messages": True},
    )

    assert "error" not in response
    sid = response["result"]["session_id"]
    assert server._sessions[sid]["agent_ready"].wait(timeout=3)
    assert response["result"]["info"]["model"] == "gpt-5.5"
    assert [message["text"] for message in response["result"]["messages"]] == [
        "What documents do I need?",
        "Historical Gemini answer",
    ]
    assert seen_models == ["gpt-5.5"]
    assert server._sessions[sid]["agent"].provider == BETA_ALLOWED_PROVIDER
    assert server._sessions[sid]["history"] == history
    assert db.row["model"] == "gemini-2.5-flash"


def test_beta_disconnect_freezes_cached_actor_and_reauth_rebuilds_same_generation(
    tmp_path,
    monkeypatch,
):
    from tools.delegate_tool import is_spawn_paused

    _write_valid_beta_auth(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-codex\n"
        "  default: gpt-5.5\n"
        "  base_url: https://chatgpt.com/backend-api/codex\n"
        "  api_mode: codex_responses\n",
        encoding="utf-8",
    )
    cached_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    cached_agent.api_key = "cached-token-that-must-not-run"
    rebuilt_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session(
        "disconnect-live", "persisted-disconnect", cached_agent
    )
    session["running"] = True
    _patch_agent_rebuild(monkeypatch, rebuilt_agent)

    def stop_cached_turn(_sid, target, **_kwargs):
        cached_agent.interrupt()
        target["running"] = False
        return {"quiesced": True, "running": False}

    monkeypatch.setattr(server, "_request_session_stop", stop_cached_turn)

    cleared = auth.disconnect_exact_beta_provider_auth(BETA_ALLOWED_PROVIDER)

    repair_id = beta_runtime_repair_generation()
    assert cleared is True
    assert repair_id is not None
    assert cached_agent.interrupt_calls == 1
    assert session["agent"] is cached_agent
    assert read_beta_codex_auth_status(tmp_path)["logged_in"] is False
    assert beta_runtime_repair_blocked_reason() == "beta_codex_auth_required"
    assert is_spawn_paused() is True
    blocked_prompt = server._methods["prompt.submit"](
        "cached-token-prompt",
        {"session_id": "disconnect-live", "text": "keep going"},
    )
    assert blocked_prompt["error"]["code"] == 5032
    assert cached_agent.interrupt_calls == 1

    _write_valid_beta_auth(tmp_path)
    auth._update_config_for_provider(BETA_ALLOWED_PROVIDER, BETA_CODEX_BASE_URL)

    assert beta_runtime_repair_generation() is None
    assert beta_runtime_repair_blocked_reason() is None
    assert is_spawn_paused() is False
    assert session["agent"] is rebuilt_agent
    assert cached_agent.close_calls == 1


def test_noncooperative_turn_blocks_disconnect_before_auth_deletion(
    tmp_path,
    monkeypatch,
):
    from tools.delegate_tool import is_spawn_paused

    _write_valid_beta_auth(tmp_path)
    auth_path = tmp_path / "auth.json"
    before_auth = json.loads(auth_path.read_text(encoding="utf-8"))
    agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session(
        "noncooperative", "persisted-noncooperative", agent
    )
    session["running"] = True
    monkeypatch.setattr(
        server,
        "_request_session_stop",
        lambda *_args, **_kwargs: {"quiesced": False, "running": True},
    )
    real_prepare = server.prepare_exact_beta_runtime_sessions
    monkeypatch.setattr(
        server,
        "prepare_exact_beta_runtime_sessions",
        lambda repair_id: real_prepare(repair_id, timeout_s=0.1),
    )

    with pytest.raises(TimeoutError, match="did not quiesce"):
        auth.disconnect_exact_beta_provider_auth(BETA_ALLOWED_PROVIDER)

    after_auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert after_auth.get("active_provider") == before_auth.get("active_provider")
    assert after_auth["providers"][BETA_ALLOWED_PROVIDER] == (
        before_auth["providers"][BETA_ALLOWED_PROVIDER]
    )
    assert read_beta_codex_auth_status(tmp_path)["logged_in"] is True
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"
    assert is_spawn_paused() is True


def test_live_gemini_agent_is_rebuilt_without_erasing_history(monkeypatch):
    old_agent = _Agent("gemini-2.5-flash", "gemini")
    new_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session("live-sid", "persisted-live", old_agent)
    session["attached_images"] = ["/tmp/staged-listing-photo.png"]
    session["attached_videos"] = ["/tmp/staged-walkthrough.mov"]
    session["attached_files"] = ["/tmp/staged-contract.pdf"]
    session["edit_snapshots"] = {"/tmp/staged-contract.pdf": "snapshot"}
    session["image_counter"] = 4
    original_history = [dict(message) for message in session["history"]]
    _patch_agent_rebuild(monkeypatch, new_agent)

    result = server.invalidate_exact_beta_runtime_sessions()

    assert result == {"marked": 1, "rebuilt": 1, "draining": 0}
    assert session["agent"] is new_agent
    assert session["history"] == original_history
    assert session["history_version"] == 7
    assert session["attached_images"] == ["/tmp/staged-listing-photo.png"]
    assert session["attached_videos"] == ["/tmp/staged-walkthrough.mov"]
    assert session["attached_files"] == ["/tmp/staged-contract.pdf"]
    assert session["edit_snapshots"] == {
        "/tmp/staged-contract.pdf": "snapshot"
    }
    assert session["image_counter"] == 4
    assert old_agent.close_calls == 1
    assert "beta_runtime_repair_id" not in session
    assert server._session_aliases["persisted-live"] == "live-sid"


def test_running_gemini_agent_is_stopped_before_async_rebuild(monkeypatch):
    old_agent = _Agent("gemini-2.5-flash", "gemini")
    new_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session("running-sid", "persisted-running", old_agent)
    session["running"] = True
    _patch_agent_rebuild(monkeypatch, new_agent)
    stop_calls = []

    def _stop(sid, target, **kwargs):
        stop_calls.append((sid, kwargs["reason"], target["agent"]))
        target["running"] = False
        return {"quiesced": True, "running": False}

    monkeypatch.setattr(server, "_request_session_stop", _stop)

    result = server.invalidate_exact_beta_runtime_sessions()

    assert result == {"marked": 1, "rebuilt": 0, "draining": 1}
    deadline = time.monotonic() + 3
    while session.get("agent") is old_agent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stop_calls == [
        ("running-sid", "beta_provider_repaired", old_agent)
    ]
    assert session["agent"] is new_agent
    assert old_agent.close_calls == 1
    assert session["history_version"] == 7


def test_two_phase_control_waits_for_actual_rebuild_and_preserves_compose_state(
    monkeypatch,
):
    repair_id = "a" * 32
    old_agent = _Agent("gemini-2.5-flash", "gemini")
    new_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session("two-phase", "persisted-two-phase", old_agent)
    session["running"] = True
    session["attached_images"] = ["/tmp/listing.png"]
    session["attached_videos"] = ["/tmp/walkthrough.mov"]
    session["attached_files"] = ["/tmp/contract.pdf"]
    session["edit_snapshots"] = {"/tmp/contract.pdf": "draft"}
    session["image_counter"] = 3
    original_history = [dict(message) for message in session["history"]]
    _patch_agent_rebuild(monkeypatch, new_agent)

    def stop_after_quiescence(_sid, target, **_kwargs):
        def finish_turn():
            time.sleep(0.08)
            with target["history_lock"]:
                target["running"] = False

        threading.Thread(target=finish_turn, daemon=True).start()
        return {"quiesced": False, "running": True}

    monkeypatch.setattr(server, "_request_session_stop", stop_after_quiescence)

    started = time.monotonic()
    prepared = server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "1" * 32, "attempt_seq": 1, "phase": "prepare"}
    )
    assert time.monotonic() - started >= 0.05
    assert prepared == {
        "repair_id": repair_id,
        "marked": 1,
        "running": 1,
        "quiesced": 1,
        "pending": 0,
    }
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"
    for method, params in (
        ("session.create", {}),
        ("session.resume", {"session_id": "persisted-two-phase"}),
        ("session.branch", {"session_id": "two-phase"}),
        ("prompt.submit", {"session_id": "two-phase", "text": "continue"}),
    ):
        response = server._methods[method](f"blocked-{method}", params)
        assert response["error"]["code"] == 5032

    completed = server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "1" * 32, "attempt_seq": 1, "phase": "commit"}
    )
    assert completed == {
        "repair_id": repair_id,
        "marked": 1,
        "rebuilt": 1,
        "pending": 0,
    }
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"
    released = server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "1" * 32, "attempt_seq": 1, "phase": "release"}
    )
    assert released == {"repair_id": repair_id, "released": True}
    assert beta_runtime_repair_blocked_reason() is None
    assert session["agent"] is new_agent
    assert session["history"] == original_history
    assert session["history_version"] == 7
    assert session["attached_images"] == ["/tmp/listing.png"]
    assert session["attached_videos"] == ["/tmp/walkthrough.mov"]
    assert session["attached_files"] == ["/tmp/contract.pdf"]
    assert session["edit_snapshots"] == {"/tmp/contract.pdf": "draft"}
    assert session["image_counter"] == 3


def test_same_generation_prepare_failure_is_retryable(monkeypatch):
    from tools.delegate_tool import is_spawn_paused

    repair_id = "b" * 32
    old_agent = _Agent("gemini-2.5-flash", "gemini")
    new_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session("retry-sid", "persisted-retry", old_agent)
    session["running"] = True
    _patch_agent_rebuild(monkeypatch, new_agent)
    stop_attempts = 0

    def flaky_stop(_sid, target, **_kwargs):
        nonlocal stop_attempts
        stop_attempts += 1
        if stop_attempts == 1:
            raise RuntimeError("simulated prepare stop failure")
        target["running"] = False
        return {"quiesced": True, "running": False}

    monkeypatch.setattr(server, "_request_session_stop", flaky_stop)
    with pytest.raises(RuntimeError, match="simulated prepare stop failure"):
        server.handle_exact_beta_runtime_control(
            {"repair_id": repair_id, "attempt": "2" * 32, "attempt_seq": 1, "phase": "prepare"}
        )
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"
    assert session["beta_runtime_repair_id"] == repair_id
    assert is_spawn_paused() is True
    retained_lease = server._beta_runtime_delegate_repair_leases[repair_id]

    prepared = server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "3" * 32, "attempt_seq": 2, "phase": "prepare"}
    )
    assert prepared["marked"] == 1
    completed = server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "3" * 32, "attempt_seq": 2, "phase": "commit"}
    )
    assert completed["marked"] == completed["rebuilt"] == 1
    assert stop_attempts == 2
    assert server._beta_runtime_delegate_repair_leases[repair_id] is retained_lease
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"
    server.handle_exact_beta_runtime_control(
        {"repair_id": repair_id, "attempt": "3" * 32, "attempt_seq": 2, "phase": "release"}
    )
    assert beta_runtime_repair_blocked_reason() is None
    assert repair_id not in server._beta_runtime_delegate_repair_leases
    assert is_spawn_paused() is False


def test_delegate_repair_release_restores_preexisting_spawn_pause():
    from tools.delegate_tool import is_spawn_paused, set_spawn_paused

    repair_id = "0" * 32
    set_spawn_paused(True)

    prepared = server.prepare_exact_beta_runtime_sessions(repair_id)
    completed = server.complete_exact_beta_runtime_sessions(repair_id)
    released = server.release_exact_beta_runtime_sessions(repair_id)
    clear_beta_runtime_repair_state(expected_generation=repair_id)

    assert prepared == {
        "repair_id": repair_id,
        "marked": 0,
        "running": 0,
        "quiesced": 0,
        "pending": 0,
    }
    assert completed == {
        "repair_id": repair_id,
        "marked": 0,
        "rebuilt": 0,
        "pending": 0,
    }
    assert released == {"repair_id": repair_id, "released": True}
    assert is_spawn_paused() is True
    set_spawn_paused(False)


def test_control_release_restores_delegate_before_opening_prompt_admission(
    monkeypatch,
):
    from elevate_cli.beta_provider_policy import beta_runtime_repair_blocked_reason
    from tools.delegate_tool import is_spawn_paused

    repair_id = "1" * 32
    attempt = "2" * 32
    common = {
        "repair_id": repair_id,
        "attempt": attempt,
        "attempt_seq": 1,
    }
    server.handle_exact_beta_runtime_control({**common, "phase": "prepare"})
    server.handle_exact_beta_runtime_control({**common, "phase": "commit"})
    real_release = server.release_exact_beta_runtime_sessions
    observed: list[tuple[str | None, bool]] = []

    def observed_release(generation):
        observed.append(
            (beta_runtime_repair_blocked_reason(), is_spawn_paused())
        )
        result = real_release(generation)
        observed.append(
            (beta_runtime_repair_blocked_reason(), is_spawn_paused())
        )
        return result

    monkeypatch.setattr(
        server,
        "release_exact_beta_runtime_sessions",
        observed_release,
    )

    released = server.handle_exact_beta_runtime_control(
        {**common, "phase": "release"}
    )

    assert released == {"repair_id": repair_id, "released": True}
    assert observed == [
        ("beta_provider_repair_pending", True),
        ("beta_provider_repair_pending", False),
    ]
    assert beta_runtime_repair_blocked_reason() is None
    assert is_spawn_paused() is False


def test_control_release_failure_keeps_prompt_and_delegate_gates_closed(
    monkeypatch,
):
    from tools.delegate_tool import is_spawn_paused

    repair_id = "3" * 32
    attempt = "4" * 32
    common = {
        "repair_id": repair_id,
        "attempt": attempt,
        "attempt_seq": 1,
    }
    server.handle_exact_beta_runtime_control({**common, "phase": "prepare"})
    server.handle_exact_beta_runtime_control({**common, "phase": "commit"})

    def failed_release(generation):
        assert generation == repair_id
        assert beta_runtime_repair_blocked_reason() == (
            "beta_provider_repair_pending"
        )
        assert is_spawn_paused() is True
        raise RuntimeError("simulated delegate lease release failure")

    monkeypatch.setattr(
        server,
        "release_exact_beta_runtime_sessions",
        failed_release,
    )

    with pytest.raises(
        RuntimeError, match="simulated delegate lease release failure"
    ):
        server.handle_exact_beta_runtime_control(
            {**common, "phase": "release"}
        )

    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"
    assert repair_id in server._beta_runtime_delegate_repair_leases
    assert is_spawn_paused() is True


def test_commit_waits_for_prepared_async_builder_then_rebuilds_its_stale_actor(
    monkeypatch,
):
    repair_id = "f" * 32
    placeholder = _Agent("gemini-placeholder", "gemini")
    stale_builder_agent = _Agent("gemini-2.5-flash", "gemini")
    canonical_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session(
        "builder-sid", "persisted-builder", placeholder
    )
    session["agent_ready"].clear()
    reservation = server._ResumeReservation({"persisted-builder"})
    reservation.sid = "builder-sid"
    reservation.session = session
    with server._session_registry_lock:
        server._resume_reservations["persisted-builder"] = reservation
    _patch_agent_rebuild(monkeypatch, canonical_agent)

    def finish_old_builder():
        time.sleep(0.08)
        with session["history_lock"]:
            session["agent"] = stale_builder_agent
        with server._session_registry_lock:
            server._resume_reservations.pop("persisted-builder", None)
        session["agent_ready"].set()

    threading.Thread(target=finish_old_builder, daemon=True).start()
    started = time.monotonic()
    prepared = server.prepare_exact_beta_runtime_sessions(repair_id)

    assert time.monotonic() - started >= 0.05
    assert prepared["marked"] == prepared["quiesced"] == 1
    completed = server.complete_exact_beta_runtime_sessions(repair_id)

    assert completed["marked"] == completed["rebuilt"] == 1
    assert session["agent"] is canonical_agent
    assert stale_builder_agent.close_calls == 1


@pytest.mark.parametrize("lane", ["create", "resume", "branch"])
def test_actor_publication_linearization_rejects_all_admission_lanes(lane):
    repair_id = "c" * 32
    key = f"{lane}-publication"
    reservation = server._ResumeReservation({key})
    session = {
        "history_lock": threading.Lock(),
        "session_key": key,
        "running": False,
    }
    with server._session_registry_lock:
        server._resume_reservations[key] = reservation
    mark_beta_runtime_repair_pending(repair_id)

    with pytest.raises(RuntimeError, match="blocked session publication"):
        # create/resume publish directly here; branch publishes through
        # _init_session, which delegates to this same linearization point.
        server._publish_resume_reservation(
            reservation,
            f"{lane}-sid",
            session,
        )
    assert f"{lane}-sid" not in server._sessions
    clear_beta_runtime_repair_state(expected_generation=repair_id)


def test_superseding_runtime_generation_is_rejected(monkeypatch):
    first = "d" * 32
    second = "e" * 32
    mark_beta_runtime_repair_pending(first)
    with pytest.raises(RuntimeError, match="another Realtor Beta runtime repair"):
        server.prepare_exact_beta_runtime_sessions(second)
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"


def test_control_receipts_are_idempotent_per_attempt_but_new_attempt_refences():
    repair_id = "7" * 32
    first_attempt = "8" * 32
    frames = {
        phase: {
            "repair_id": repair_id,
            "attempt": first_attempt,
            "attempt_seq": 1,
            "phase": phase,
        }
        for phase in ("prepare", "commit", "release")
    }

    prepare = server.handle_exact_beta_runtime_control(frames["prepare"])
    assert server.handle_exact_beta_runtime_control(frames["prepare"]) == prepare
    commit = server.handle_exact_beta_runtime_control(frames["commit"])
    assert server.handle_exact_beta_runtime_control(frames["commit"]) == commit
    release = server.handle_exact_beta_runtime_control(frames["release"])
    assert server.handle_exact_beta_runtime_control(frames["release"]) == release
    assert beta_runtime_repair_blocked_reason() is None

    # Same repair generation, new barrier attempt after a lost aggregate ACK:
    # prepare must execute again and close admission, not reuse old success.
    second_prepare = server.handle_exact_beta_runtime_control(
        {
            "repair_id": repair_id,
            "attempt": "9" * 32,
            "attempt_seq": 2,
            "phase": "prepare",
        }
    )
    assert second_prepare["repair_id"] == repair_id
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"


def test_unseen_delayed_old_commit_and_release_cannot_touch_new_attempt():
    repair_id = "4" * 32
    old_attempt = "5" * 32
    new_attempt = "6" * 32
    server.handle_exact_beta_runtime_control(
        {
            "repair_id": repair_id,
            "attempt": old_attempt,
            "attempt_seq": 1,
            "phase": "prepare",
        }
    )
    server.handle_exact_beta_runtime_control(
        {
            "repair_id": repair_id,
            "attempt": new_attempt,
            "attempt_seq": 2,
            "phase": "prepare",
        }
    )

    for phase in ("commit", "release"):
        with pytest.raises(ValueError, match="stale provider-repair"):
            server.handle_exact_beta_runtime_control(
                {
                    "repair_id": repair_id,
                    "attempt": old_attempt,
                    "attempt_seq": 1,
                    "phase": phase,
                }
            )
        assert beta_runtime_repair_blocked_reason() == (
            "beta_provider_repair_pending"
        )

    committed = server.handle_exact_beta_runtime_control(
        {
            "repair_id": repair_id,
            "attempt": new_attempt,
            "attempt_seq": 2,
            "phase": "commit",
        }
    )
    assert committed["pending"] == 0


def test_one_broken_stop_cannot_leave_later_sessions_ungated(monkeypatch):
    first_agent = _Agent("gemini-2.5-flash", "gemini")
    second_agent = _Agent("gemini-2.5-flash", "gemini")
    first = _install_live_session("first-sid", "persisted-first", first_agent)
    second = _install_live_session("second-sid", "persisted-second", second_agent)
    first["running"] = True
    second["running"] = True
    stop_calls: list[str] = []

    def _stop(sid, _target, **_kwargs):
        stop_calls.append(sid)
        if sid == "first-sid":
            # Every actor must already carry the admission gate before work on
            # the first actor can fail.
            assert first.get("beta_runtime_repair_id")
            assert second.get("beta_runtime_repair_id")
            raise RuntimeError("simulated stop failure")
        return {"quiesced": False, "running": True}

    monkeypatch.setattr(server, "_request_session_stop", _stop)
    monkeypatch.setattr(
        server.threading,
        "Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )

    result = server.invalidate_exact_beta_runtime_sessions()

    assert result == {"marked": 2, "rebuilt": 0, "draining": 2}
    assert stop_calls == ["first-sid", "second-sid"]
    assert first.get("beta_runtime_repair_id")
    assert second.get("beta_runtime_repair_id")


def test_delayed_repair_stop_cannot_cancel_a_new_generation(monkeypatch):
    old_agent = _Agent("gemini-2.5-flash", "gemini")
    new_agent = _Agent("gpt-5.5", BETA_ALLOWED_PROVIDER)
    session = _install_live_session("race-sid", "persisted-race", old_agent)
    session["running"] = True
    observed_repair_ids: list[str] = []
    real_stop = server._request_session_stop

    def _delayed_stop(sid, target, **kwargs):
        repair_id = kwargs.get("expected_repair_id")
        assert isinstance(repair_id, str) and repair_id
        observed_repair_ids.append(repair_id)

        # Model the old turn winning terminal state, prompt fast-path rebuilding
        # the actor, and a new Codex turn being admitted before delayed Stop.
        target["running"] = False
        target["beta_runtime_repair_id"] = repair_id
        target["agent"] = new_agent
        target.pop("beta_runtime_repair_id")
        target["running"] = True
        return real_stop(sid, target, **kwargs)

    monkeypatch.setattr(server, "_request_session_stop", _delayed_stop)
    monkeypatch.setattr(
        server.threading,
        "Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )

    result = server.invalidate_exact_beta_runtime_sessions()

    assert result == {"marked": 1, "rebuilt": 0, "draining": 1}
    assert len(observed_repair_ids) == 1
    assert session["agent"] is new_agent
    assert session["running"] is True
    assert old_agent.interrupt_calls == 0
    assert new_agent.interrupt_calls == 0


def test_session_list_projects_codex_and_retains_historical_gemini(
    tmp_path,
    monkeypatch,
):
    _write_valid_beta_auth(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.4\n",
        encoding="utf-8",
    )
    rows = [
        {
            "id": "historical",
            "model": "gemini-2.5-flash",
            "ended_at": None,
            "started_at": 1.0,
            "last_active": 1.0,
        }
    ]

    mark_session_activity(
        rows,
        2.0,
        session_active_window_sec=300,
        gateway_session_run_states_func=lambda: (set(), set()),
        gateway_session_runtime_models_func=lambda: {
            "historical": "gpt-5.4"
        },
    )

    assert rows[0]["model"] == "gemini-2.5-flash"
    assert rows[0]["runtime_model"] == "gpt-5.4"
    assert rows[0]["historical_model"] == "gemini-2.5-flash"

    # The dashboard's slim session list can surface a compression root while
    # the live actor is bound to its active tip. Registry aliases are the
    # authoritative bridge; omitting them falsely shows the root's old Gemini
    # model even though that exact conversation is live on Codex.
    agent = _Agent("gpt-5.4", BETA_ALLOWED_PROVIDER)
    aliased = _install_live_session("alias-sid", "active-tip", agent)
    aliased["registry_aliases"].add("historical-root")
    alias_rows = [
        {
            "id": "historical-root",
            "model": "gemini-2.5-flash",
            "ended_at": None,
            "started_at": 1.0,
            "last_active": 1.0,
        }
    ]
    mark_session_activity(
        alias_rows,
        2.0,
        session_active_window_sec=300,
    )
    assert alias_rows[0]["is_active"] is False
    assert alias_rows[0]["runtime_model"] == "gpt-5.4"
    assert alias_rows[0]["historical_model"] == "gemini-2.5-flash"

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    stable_rows = [{"id": "stable", "model": "gemini-2.5-flash"}]
    mark_session_activity(
        stable_rows,
        2.0,
        session_active_window_sec=300,
        gateway_session_run_states_func=lambda: (set(), {"stable"}),
        gateway_session_runtime_models_func=lambda: {"stable": "gpt-5.4"},
    )
    assert stable_rows == [
        {"id": "stable", "model": "gemini-2.5-flash", "is_active": False}
    ]


def test_hostile_model_env_set_after_repair_stays_blocked(tmp_path, monkeypatch):
    _write_valid_beta_auth(tmp_path)
    auth._update_config_for_provider(BETA_ALLOWED_PROVIDER, BETA_CODEX_BASE_URL)
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")

    with pytest.raises(BetaProviderPolicyError) as exc:
        server._resolve_model()

    assert exc.value.code == "beta_model_not_allowed"
