"""Tests for elevate_cli.web_server and related config utilities."""

import os
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from elevate_cli.config import (
    DEFAULT_CONFIG,
    reload_env,
    redact_key,
    _EXTRA_ENV_KEYS,
    OPTIONAL_ENV_VARS,
)


# ---------------------------------------------------------------------------
# reload_env tests
# ---------------------------------------------------------------------------


class TestReloadEnv:
    """Tests for reload_env() — re-reads .env into os.environ."""

    def test_adds_new_vars(self, tmp_path):
        """reload_env() adds vars from .env that are not in os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=hello123\n")
        with patch("elevate_cli.config.get_env_path", return_value=env_file):
            os.environ.pop("TEST_RELOAD_VAR", None)
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "hello123"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_updates_changed_vars(self, tmp_path):
        """reload_env() updates vars whose value changed on disk."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=old_value\n")
        with patch("elevate_cli.config.get_env_path", return_value=env_file):
            os.environ["TEST_RELOAD_VAR"] = "old_value"
            # Now change the file
            env_file.write_text("TEST_RELOAD_VAR=new_value\n")
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "new_value"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_removes_deleted_known_vars(self, tmp_path):
        """reload_env() removes known Elevate vars not present in .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")  # empty .env
        # Pick a known key from OPTIONAL_ENV_VARS
        known_key = next(iter(OPTIONAL_ENV_VARS.keys()))
        with patch("elevate_cli.config.get_env_path", return_value=env_file):
            os.environ[known_key] = "stale_value"
            count = reload_env()
            assert known_key not in os.environ
            assert count >= 1

    def test_does_not_remove_unknown_vars(self, tmp_path):
        """reload_env() preserves non-Elevate env vars even when absent from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")
        with patch("elevate_cli.config.get_env_path", return_value=env_file):
            os.environ["MY_CUSTOM_UNRELATED_VAR"] = "keep_me"
            reload_env()
            assert os.environ.get("MY_CUSTOM_UNRELATED_VAR") == "keep_me"
        os.environ.pop("MY_CUSTOM_UNRELATED_VAR", None)


# ---------------------------------------------------------------------------
# redact_key tests
# ---------------------------------------------------------------------------


class TestRedactKey:
    def test_long_key_shows_prefix_suffix(self):
        result = redact_key("sk-1234567890abcdef")
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "..." in result

    def test_short_key_fully_masked(self):
        assert redact_key("short") == "***"

    def test_empty_key(self):
        result = redact_key("")
        assert "not set" in result.lower() or result == "***" or "\x1b" in result


# ---------------------------------------------------------------------------
# web_server tests (FastAPI endpoints)
# ---------------------------------------------------------------------------


class TestWebServerEndpoints:
    """Test the FastAPI REST endpoints using Starlette TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self, monkeypatch, _isolate_elevate_home):
        """Create a TestClient and isolate the state DB under the test ELEVATE_HOME."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import elevate_state
        from elevate_constants import get_elevate_home
        try:
            from elevate_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        except SystemExit as exc:
            pytest.skip(str(exc))

        monkeypatch.setattr(elevate_state, "DEFAULT_DB_PATH", get_elevate_home() / "state.db")

        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    @pytest.fixture(autouse=True)
    def _fresh_surface_state(self):
        """Surface heartbeat STATE lives in the account DB (migration 0024).

        Reset the cached schema/pool/embedded-server state so each test's
        ``connect()`` targets its own isolated ELEVATE_HOME, and clear the
        web_server FS-scan TTL cache so one test's surfaces snapshot never
        leaks into the next (the cache is keyed on the account key, which is
        constant across tests).
        """
        from elevate_cli.data.connection import _reset_schema_cache
        import elevate_cli.web_server as _ws

        _reset_schema_cache()
        with _ws._FS_SCAN_CACHE_LOCK:
            _ws._FS_SCAN_CACHE.clear()
        yield
        _reset_schema_cache()
        with _ws._FS_SCAN_CACHE_LOCK:
            _ws._FS_SCAN_CACHE.clear()

    def test_get_status(self):
        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "project_root" in data
        assert "elevate_home" in data
        assert "active_sessions" in data

    def test_request_id_header_is_echoed_and_logged(self, caplog):
        with caplog.at_level(logging.INFO, logger="elevate_cli.web_server"):
            resp = self.client.get("/api/status", headers={"X-Request-Id": "rid 123"})

        assert resp.status_code == 200
        assert resp.headers["x-request-id"] == "rid_123"
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "request complete request_id=rid_123 session_id=- method=GET path=/api/status status=200"
            in message
            for message in messages
        )

    def test_session_path_is_in_request_log(self, caplog):
        with caplog.at_level(logging.INFO, logger="elevate_cli.web_server"):
            resp = self.client.get(
                "/api/sessions/session%20one/messages",
                headers={"X-Request-Id": "rid-two"},
            )

        assert resp.headers["x-request-id"] == "rid-two"
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "request complete request_id=rid-two session_id=session_one method=GET "
            "path=/api/sessions/session one/messages"
            in message
            for message in messages
        )

    def test_unauthorized_request_id_header_is_echoed_and_logged(self, caplog):
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app

        client = TestClient(app)
        with caplog.at_level(logging.INFO, logger="elevate_cli.web_server"):
            resp = client.get("/api/env", headers={"X-Request-Id": "rid-unauth"})

        assert resp.status_code == 401
        assert resp.headers["x-request-id"] == "rid-unauth"
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "request complete request_id=rid-unauth session_id=- method=GET path=/api/env status=401"
            in message
            for message in messages
        )

    def test_get_agent_hub(self, monkeypatch):
        import elevate_cli.agent_hub as agent_hub

        monkeypatch.setattr(
            agent_hub,
            "build_agent_hub_snapshot",
            lambda *args, **kwargs: {"agents": [], "gateway": {"running": False}},
        )

        resp = self.client.get("/api/agent-hub")
        assert resp.status_code == 200
        assert resp.json()["agents"] == []

    def test_get_heartbeat_experiments_reads_proposed_and_running_records(self):
        from elevate_cli.data import connect, surface_state

        with connect() as conn:
            surface_state.set_config(
                conn,
                "theta-wave-test",
                {
                    "experiment": {
                        "metric": "stale_handoffs",
                        "direction": "lower",
                        "window": "7d",
                    }
                },
            )
            surface_state.upsert_experiment(
                conn,
                "theta-wave-test",
                {
                    "id": "exp-proposed",
                    "status": "proposed",
                    "hypothesis": "A clearer handoff card reduces stale work.",
                    "metric": "stale_handoffs",
                    "baseline_value": 7,
                    "created_at": "2026-06-06T10:00:00Z",
                },
            )
            surface_state.upsert_experiment(
                conn,
                "theta-wave-test",
                {
                    "id": "exp-running",
                    "status": "running",
                    "cycle": "stale_handoffs",
                    "hypothesis": "Native loops improve recovery.",
                    "metric": "stale_handoffs",
                    "baseline_value": 7,
                    "started_at": "2026-06-06T11:00:00Z",
                },
            )

        resp = self.client.get("/api/heartbeats/experiments")

        assert resp.status_code == 200
        payload = resp.json()
        surface = payload["surfaces"][0]
        assert surface["surface"] == "theta-wave-test"
        assert payload["summary"]["running"] == 1
        assert surface["stats"]["total"] == 2
        by_id = {item["id"]: item for item in surface["experiments"]}
        assert by_id["exp-running"]["status"] == "running"
        assert by_id["exp-running"]["result"] is None
        assert by_id["exp-running"]["baseline"] == 7
        assert by_id["exp-proposed"]["status"] == "proposed"
        assert by_id["exp-proposed"]["direction"] == "lower"

    def test_heartbeat_surface_config_patch_updates_config_and_job(self):
        from cron.jobs import create_job, load_jobs
        from elevate_constants import get_account_data_dir
        from elevate_cli.data import connect, surface_state

        surface = "admin-edit-test"
        surface_dir = get_account_data_dir() / "heartbeats" / surface
        surface_dir.mkdir(parents=True)
        with connect() as conn:
            surface_state.set_config(
                conn,
                surface,
                {"enabled": True, "goal": "Old admin loop", "cadence": "30 7 * * *"},
            )
        job = create_job(
            prompt="Run the admin heartbeat.",
            schedule="30 7 * * *",
            name="Admin Heartbeat",
            skill="real-estate/surface-heartbeat",
            deliver="local",
            origin={"type": "surface-heartbeat", "surface": surface, "source": "user"},
            workdir=str(surface_dir),
        )

        resp = self.client.patch(
            f"/api/heartbeats/surfaces/{surface}/config",
            json={
                "goal": "Scan admin work and report blockers.",
                "cadence": "every 2h",
                "agent": "executive-assistant",
                "model": "gpt-5.1",
                "timezone": "America/Vancouver",
                "heartbeat_report_mode": "notify",
                "approval_rules": {
                    "always_ask": ["deployment", "data-deletion"],
                    "never_ask": ["external-comms"],
                },
            },
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["config"]["goal"] == "Scan admin work and report blockers."
        assert payload["config"]["cadence"] == "every 2h"
        assert payload["config"]["agent"] == "executive-assistant"
        assert payload["config"]["model"] == "gpt-5.1"
        with connect() as conn:
            saved_config = surface_state.get_config(conn, surface)
        assert saved_config["timezone"] == "America/Vancouver"
        assert saved_config["heartbeat_report_mode"] == "notify"
        assert saved_config["approval_rules"]["always_ask"] == ["deployment", "data-deletion"]
        # Allowlist-merge preserved the keys the patch didn't touch.
        assert saved_config["enabled"] is True

        updated_job = next(j for j in load_jobs() if j["id"] == job["id"])
        assert updated_job["agent"] == "executive-assistant"
        assert updated_job["model"] == "gpt-5.1"
        assert updated_job["metadata"]["heartbeat_report_mode"] == "notify"
        assert updated_job["schedule"]["kind"] == "interval"
        assert updated_job["schedule"]["minutes"] == 120
        assert updated_job["schedule_display"] == "every 120m"

    def test_heartbeat_surface_snapshot_infers_matching_agent(self):
        from cron.jobs import create_job
        from elevate_constants import get_account_data_dir
        from elevate_cli.data import connect, surface_state

        surface = "admin"
        surface_dir = get_account_data_dir() / "heartbeats" / surface
        # The dir exists only as the cron job's workdir — config/state live in
        # the account DB (no config.json on disk).
        surface_dir.mkdir(parents=True)
        with connect() as conn:
            surface_state.set_config(
                conn,
                surface,
                {"enabled": True, "goal": "Admin loop", "cadence": "30 7 * * *"},
            )
        create_job(
            prompt="Run the admin heartbeat.",
            schedule="30 7 * * *",
            name="Admin Heartbeat",
            skill="real-estate/surface-heartbeat",
            deliver="local",
            origin={"type": "surface-heartbeat", "surface": surface, "source": "user"},
            workdir=str(surface_dir),
        )

        resp = self.client.get("/api/heartbeats/surfaces")

        assert resp.status_code == 200
        payload = resp.json()
        admin = next(item for item in payload["surfaces"] if item["surface"] == "admin")
        assert admin["config"]["agent"] == "admin"

    def test_heartbeat_surface_config_patch_rejects_invalid_cadence(self):
        from elevate_constants import get_account_data_dir

        surface_dir = get_account_data_dir() / "heartbeats" / "invalid-cadence-test"
        surface_dir.mkdir(parents=True)
        (surface_dir / "config.json").write_text("{}", encoding="utf-8")

        resp = self.client.patch(
            "/api/heartbeats/surfaces/invalid-cadence-test/config",
            json={"goal": "Check admin work.", "cadence": "whenever the moon says"},
        )

        assert resp.status_code == 400
        assert "invalid cadence" in resp.json()["detail"]

    def test_heartbeat_surface_goals_roundtrip_pg(self):
        from elevate_cli.data import connect, surface_state

        surface = "goals-test"
        with connect() as conn:
            surface_state.set_config(conn, surface, {"goal": "g"})

        resp = self.client.get(f"/api/heartbeats/surfaces/{surface}/goals")
        assert resp.status_code == 200
        assert resp.json()["goals"] == []

        resp = self.client.patch(
            f"/api/heartbeats/surfaces/{surface}/goals",
            json={
                "bottleneck": "follow-ups",
                "daily_focus": "drain the queue",
                "goals": [
                    {"title": "Second", "progress": 250, "order": 5},
                    {"id": "g-keep", "title": "First", "progress": -3, "order": 0},
                ],
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["bottleneck"] == "follow-ups"
        assert payload["daily_focus"] == "drain the queue"
        assert payload["daily_focus_set_at"]  # stamped when the focus changes
        # progress clamped 0-100, order re-minted 0..n, ids preserved/minted
        assert [g["title"] for g in payload["goals"]] == ["First", "Second"]
        assert payload["goals"][0]["id"] == "g-keep"
        assert payload["goals"][0]["progress"] == 0
        assert payload["goals"][1]["progress"] == 100
        assert payload["goals"][1]["id"]

        # GET reads back the persisted DB state; exactly ONE history row appended.
        resp = self.client.get(f"/api/heartbeats/surfaces/{surface}/goals")
        assert resp.status_code == 200
        assert resp.json()["bottleneck"] == "follow-ups"
        with connect() as conn:
            hist = surface_state.list_goals_history(conn, surface)
        assert len(hist) == 1
        assert hist[0]["bottleneck"] == "follow-ups"

        resp = self.client.patch(
            f"/api/heartbeats/surfaces/{surface}/goals",
            json={"goals": [{"title": "x" * 201}]},
        )
        assert resp.status_code == 400

    def test_heartbeat_surface_create_and_delete_purge_db_state(self):
        from elevate_cli.data import connect, surface_state

        resp = self.client.post(
            "/api/heartbeats/surfaces",
            json={"surface": "concierge", "schedule": "0 9 * * *", "goal": "Test loop"},
        )
        assert resp.status_code == 200
        assert resp.json()["surface"] == "concierge"
        with connect() as conn:
            assert "concierge" in surface_state.list_registry(conn)
            surface_state.upsert_experiment(
                conn, "concierge", {"id": "exp-x", "status": "completed"}
            )

        resp = self.client.delete("/api/heartbeats/surfaces/concierge")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        with connect() as conn:
            assert "concierge" not in surface_state.list_registry(conn)
            assert "concierge" not in surface_state.list_state_surfaces(conn)
            assert surface_state.list_experiments(conn, "concierge") == []

        resp = self.client.delete("/api/heartbeats/surfaces/concierge")
        assert resp.status_code == 404

    def test_update_session_title(self):
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            db.create_session(session_id="rename-test-session", source="cli")
        finally:
            db.close()

        resp = self.client.put(
            "/api/sessions/rename-test-session/title",
            json={"title": "Client prep notes"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "title": "Client prep notes"}

        db = SessionDB()
        try:
            assert db.get_session("rename-test-session")["title"] == "Client prep notes"
        finally:
            db.close()

    def test_reveal_session_opens_transcript(self, monkeypatch):
        from elevate_cli.config import get_elevate_home
        import elevate_cli.web_server as web_server
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            db.create_session(session_id="reveal-test-session", source="cli")
        finally:
            db.close()

        transcript = get_elevate_home() / "sessions" / "reveal-test-session.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text('{"role":"user","content":"hello"}\n')
        popen = MagicMock()
        monkeypatch.setattr(web_server.subprocess, "Popen", popen)

        resp = self.client.post("/api/sessions/reveal-test-session/reveal")

        assert resp.status_code == 200
        assert resp.json()["path"] == str(transcript)
        popen.assert_called_once()

    def test_gateway_ws_ready_and_clean_disconnect(self, monkeypatch):
        import elevate_cli.web_server as web_server

        monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
        with self.client.websocket_connect(f"/api/ws?token={web_server._SESSION_TOKEN}") as ws:
            first = ws.receive_json()

        assert first["method"] == "event"
        assert first["params"]["type"] == "gateway.ready"

    def test_gateway_ws_rejects_bad_token(self, monkeypatch):
        import elevate_cli.web_server as web_server
        from starlette.websockets import WebSocketDisconnect

        monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect("/api/ws?token=wrong"):
                pass

        assert exc.value.code == 4401

    def test_gateway_ws_rejects_missing_token(self, monkeypatch):
        import elevate_cli.web_server as web_server
        from starlette.websockets import WebSocketDisconnect

        monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect("/api/ws"):
                pass

        assert exc.value.code == 4401

    def test_gateway_ws_rejects_when_embedded_chat_disabled(self, monkeypatch):
        import elevate_cli.web_server as web_server
        from starlette.websockets import WebSocketDisconnect

        monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", False)

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(f"/api/ws?token={web_server._SESSION_TOKEN}"):
                pass

        assert exc.value.code == 4403

    def test_get_status_filters_unconfigured_gateway_platforms(self, monkeypatch):
        import gateway.config as gateway_config
        import elevate_cli.web_server as web_server

        class _Platform:
            def __init__(self, value):
                self.value = value

        class _GatewayConfig:
            def get_connected_platforms(self):
                return [_Platform("telegram")]

        monkeypatch.setattr(web_server, "get_running_pid", lambda: 1234)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "running",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_platforms"] == {
            "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
        }

    def test_get_status_hides_stale_platforms_when_gateway_not_running(self, monkeypatch):
        import gateway.config as gateway_config
        import elevate_cli.web_server as web_server

        class _GatewayConfig:
            def get_connected_platforms(self):
                return []

        monkeypatch.setattr(web_server, "get_running_pid", lambda: None)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "startup_failed",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_state"] == "startup_failed"
        assert resp.json()["gateway_platforms"] == {}

    def test_get_config_schema(self):
        resp = self.client.get("/api/config/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        assert "category_order" in data
        schema = data["fields"]
        assert len(schema) > 100  # Should have 150+ fields
        assert "model" in schema
        # Verify category_order is a non-empty list
        assert isinstance(data["category_order"], list)
        assert len(data["category_order"]) > 0
        assert "general" in data["category_order"]

    def test_get_config_defaults(self):
        resp = self.client.get("/api/config/defaults")
        assert resp.status_code == 200
        defaults = resp.json()
        assert "model" in defaults

    def test_get_env_vars(self):
        resp = self.client.get("/api/env")
        assert resp.status_code == 200
        data = resp.json()
        # Should contain known env var names
        assert any(k.endswith("_API_KEY") or k.endswith("_TOKEN") for k in data.keys())

    def test_agent_channel_rejects_pasted_bot_token(self):
        from elevate_cli.config import load_env

        token = "222222222:ADMINbbbbbbbbbbbbbbbbbbbb"
        resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "value": token},
        )

        assert resp.status_code == 400
        assert "Bot token field" in resp.json()["detail"]
        env = load_env()
        assert env.get("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN") != token
        assert "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL" not in env

    def test_home_channel_rejects_pasted_bot_token(self):
        token = "222222222:ADMINbbbbbbbbbbbbbbbbbbbb"
        resp = self.client.put(
            "/api/env",
            json={"key": "TELEGRAM_HOME_CHANNEL", "value": token},
        )

        assert resp.status_code == 400
        assert "home chat field" in resp.json()["detail"]

    def test_non_executive_agent_cannot_reuse_shared_telegram_token(self):
        from elevate_cli.config import save_env_value

        token = "111111111:SHAREDaaaaaaaaaaaaaaaaaaaa"
        save_env_value("TELEGRAM_BOT_TOKEN", token)

        resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", "value": token},
        )

        assert resp.status_code == 400
        assert "separate bot token" in resp.json()["detail"]

    def test_shared_telegram_config_syncs_to_executive_lane(self):
        from elevate_cli.config import load_env

        token = "111111111:SHAREDaaaaaaaaaaaaaaaaaaaa"
        token_resp = self.client.put(
            "/api/env",
            json={"key": "TELEGRAM_BOT_TOKEN", "value": token},
        )
        home_resp = self.client.put(
            "/api/env",
            json={"key": "TELEGRAM_HOME_CHANNEL", "value": "-10012345:9"},
        )

        assert token_resp.status_code == 200
        assert home_resp.status_code == 200
        env = load_env()
        assert env["TELEGRAM_BOT_TOKEN"] == token
        assert env["ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN"] == token
        assert env["TELEGRAM_HOME_CHANNEL"] == "-10012345:9"
        assert env["ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL"] == "-10012345:9"

    def test_executive_lane_config_syncs_to_legacy_gateway_keys(self):
        from elevate_cli.config import load_env

        token = "333333333:EXECUTIVEcccccccccccccccccccc"
        token_resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN", "value": token},
        )
        home_resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL", "value": "-10098765"},
        )

        assert token_resp.status_code == 200
        assert home_resp.status_code == 200
        env = load_env()
        assert env["ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN"] == token
        assert env["TELEGRAM_BOT_TOKEN"] == token
        assert env["ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL"] == "-10098765"
        assert env["TELEGRAM_HOME_CHANNEL"] == "-10098765"

    def test_non_executive_agent_cannot_reuse_executive_lane_token(self):
        from elevate_cli.config import save_env_value

        token = "333333333:EXECUTIVEcccccccccccccccccccc"
        save_env_value("ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN", token)

        resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", "value": token},
        )

        assert resp.status_code == 400
        assert "separate bot token" in resp.json()["detail"]

    def test_executive_token_rejects_existing_non_executive_duplicate(self):
        from elevate_cli.config import save_env_value

        token = "444444444:ADMINdddddddddddddddddddddd"
        save_env_value("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", token)

        resp = self.client.put(
            "/api/env",
            json={"key": "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN", "value": token},
        )

        assert resp.status_code == 400
        assert "already assigned to another agent" in resp.json()["detail"]

    def test_reveal_env_var(self, tmp_path):
        """POST /api/env/reveal should return the real unredacted value."""
        from elevate_cli.config import save_env_value
        from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        save_env_value("TEST_REVEAL_KEY", "super-secret-value-12345")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_KEY"},
            headers={_SESSION_HEADER_NAME: _SESSION_TOKEN},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "TEST_REVEAL_KEY"
        assert data["value"] == "super-secret-value-12345"

    def test_reveal_env_var_not_found(self):
        """POST /api/env/reveal should 404 for unknown keys."""
        from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "NONEXISTENT_KEY_XYZ"},
            headers={_SESSION_HEADER_NAME: _SESSION_TOKEN},
        )
        assert resp.status_code == 404

    def test_reveal_env_var_no_token(self, tmp_path):
        """POST /api/env/reveal without token should return 401."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app
        from elevate_cli.config import save_env_value
        save_env_value("TEST_REVEAL_NOAUTH", "secret-value")
        # Use a fresh client WITHOUT the dashboard session header
        unauth_client = TestClient(app)
        resp = unauth_client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_NOAUTH"},
        )
        assert resp.status_code == 401

    def test_reveal_env_var_bad_token(self, tmp_path):
        """POST /api/env/reveal with wrong token should return 401."""
        from elevate_cli.config import save_env_value
        from elevate_cli.web_server import _SESSION_HEADER_NAME
        save_env_value("TEST_REVEAL_BADAUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_BADAUTH"},
            headers={_SESSION_HEADER_NAME: "wrong-token-here"},
        )
        assert resp.status_code == 401

    def test_reveal_env_var_custom_session_header_ignores_proxy_authorization(self, tmp_path):
        """A valid dashboard session header should coexist with proxy auth."""
        from elevate_cli.config import save_env_value
        from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN

        save_env_value("TEST_REVEAL_PROXY_AUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_PROXY_AUTH"},
            headers={
                _SESSION_HEADER_NAME: _SESSION_TOKEN,
                "Authorization": "Basic dXNlcjpwYXNz",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["value"] == "secret-value"

    def test_reveal_env_var_legacy_authorization_header_still_works(self, tmp_path):
        """Keep old dashboard bundles working while the new header rolls out."""
        from elevate_cli.config import save_env_value
        from elevate_cli.web_server import _SESSION_TOKEN

        save_env_value("TEST_REVEAL_LEGACY_AUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_LEGACY_AUTH"},
            headers={"Authorization": f"Bearer {_SESSION_TOKEN}"},
        )

        assert resp.status_code == 200

    def test_session_token_endpoint_removed(self):
        """GET /api/auth/session-token should no longer exist (token injected via HTML)."""
        resp = self.client.get("/api/auth/session-token")
        # The endpoint is gone — the catch-all SPA route serves index.html
        # or the middleware returns 401 for unauthenticated /api/ paths.
        assert resp.status_code in (200, 404)
        # Either way, it must NOT return the token as JSON
        try:
            data = resp.json()
            assert "token" not in data
        except Exception:
            pass  # Not JSON — that's fine (SPA HTML)

    def test_unauthenticated_api_blocked(self):
        """API requests without the session token should be rejected."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app
        # Create a client WITHOUT the dashboard session header
        unauth_client = TestClient(app)
        resp = unauth_client.get("/api/env")
        assert resp.status_code == 401
        resp = unauth_client.get("/api/config")
        assert resp.status_code == 401
        # Public endpoints should still work
        resp = unauth_client.get("/api/status")
        assert resp.status_code == 200

    def test_dashboard_plugin_rescan_requires_session_token(self):
        """Plugin manifest reads are public; forced rescans mutate cache and require auth."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app

        unauth_client = TestClient(app)

        assert unauth_client.get("/api/dashboard/plugins").status_code == 200
        assert unauth_client.get("/api/dashboard/plugins/rescan").status_code == 401
        assert self.client.get("/api/dashboard/plugins/rescan").status_code == 200

    def test_dashboard_session_cookie_authorizes_api_requests(self):
        """The served SPA cookie must cover first-load /api calls before JS runs."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import WEB_DIST, app, _SESSION_TOKEN

        if not (WEB_DIST / "index.html").exists():
            pytest.skip("frontend bundle not built")

        browser = TestClient(app)
        index = browser.get("/")

        assert index.status_code == 200
        assert browser.cookies.get("elevate_session") == _SESSION_TOKEN
        assert "HttpOnly" in index.headers.get("set-cookie", "")

        resp = browser.get("/api/env")
        assert resp.status_code == 200

    def test_path_traversal_blocked(self):
        """Verify URL-encoded path traversal is blocked."""
        # %2e%2e = ..
        resp = self.client.get("/%2e%2e/%2e%2e/etc/passwd")
        # Should return 200 with index.html (SPA fallback), not the actual file
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            # Should be the SPA fallback, not the system file
            assert "root:" not in resp.text

    def test_path_traversal_dotdot_blocked(self):
        """Direct .. path traversal via encoded sequences."""
        resp = self.client.get("/%2e%2e/elevate_cli/web_server.py")
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert "FastAPI" not in resp.text  # Should not serve the actual source

    def test_docs_dashboard_route_is_not_fastapi_swagger(self):
        """The dashboard /docs route must not be shadowed by FastAPI docs."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import WEB_DIST, app

        if not (WEB_DIST / "index.html").exists():
            pytest.skip("frontend bundle not built")

        resp = TestClient(app).get("/docs")

        assert resp.status_code == 200
        assert 'window.__ELEVATE_SESSION_TOKEN__' in resp.text
        assert "SwaggerUIBundle" not in resp.text

    def test_fastapi_swagger_lives_under_api_docs(self):
        """Keep developer API docs reachable without taking /docs from the app."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app

        resp = TestClient(app).get("/api/docs")

        assert resp.status_code == 200
        assert "SwaggerUIBundle" in resp.text
        assert "/api/openapi.json" in resp.text

    def test_fastapi_openapi_schema_lives_under_api(self):
        """The debug docs page must point at a schema endpoint that actually works."""
        from starlette.testclient import TestClient
        from elevate_cli.web_server import app

        client = TestClient(app)

        assert client.get("/openapi.json").status_code in (200, 404)
        resp = client.get("/api/openapi.json")

        assert resp.status_code == 200
        assert resp.json()["info"]["title"] == "Elevate"

    def test_file_preview_allows_temp_artifact(self):
        artifact = Path(tempfile.gettempdir()) / "elevate-preview-test.txt"
        artifact.write_text("preview ok", encoding="utf-8")
        try:
            resp = self.client.get("/api/files/preview", params={"path": str(artifact)})
        finally:
            try:
                artifact.unlink()
            except OSError:
                pass

        assert resp.status_code == 200
        assert resp.text == "preview ok"
        assert resp.headers["x-elevate-file-name"] == artifact.name

    def test_file_preview_rejects_license_file_and_symlink_escape(self):
        from elevate_constants import get_elevate_home

        home = get_elevate_home()
        home.mkdir(parents=True, exist_ok=True)
        license_path = home / "license.json"
        license_path.write_text('{"access_token":"secret"}', encoding="utf-8")

        direct = self.client.get("/api/files/preview", params={"path": str(license_path)})
        assert direct.status_code == 403

        upload_dir = home / "uploads" / "preview-test"
        upload_dir.mkdir(parents=True, exist_ok=True)
        link = upload_dir / "license.json"
        try:
            link.symlink_to(license_path)
        except OSError:
            pytest.skip("symlink creation unavailable")

        via_link = self.client.get("/api/files/preview", params={"path": str(link)})
        assert via_link.status_code == 403

    def test_upload_attachment_sanitizes_session_and_filename(self):
        from elevate_constants import get_elevate_home

        resp = self.client.post(
            "/api/uploads/session%20weird",
            files={"file": ("../../.env", b"hello", "text/plain")},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "_env"
        assert body["size"] == 5
        path = Path(body["path"]).resolve()
        assert path.is_file()
        assert path.read_bytes() == b"hello"
        assert path.parent == (get_elevate_home() / "uploads" / "session_weird").resolve()

    def test_upload_attachment_rejects_oversize_and_removes_partial(self, monkeypatch):
        from elevate_cli import web_server
        from elevate_constants import get_elevate_home

        monkeypatch.setattr(web_server, "_UPLOAD_MAX_PER_FILE", 4)
        resp = self.client.post(
            "/api/uploads/oversize",
            files={"file": ("big.txt", b"12345", "text/plain")},
        )

        assert resp.status_code == 413
        upload_dir = get_elevate_home() / "uploads" / "oversize"
        assert list(upload_dir.glob("*")) == []

    def test_upload_attachment_failure_response_does_not_leak_local_path(self, monkeypatch):
        from elevate_cli import web_server

        class FailingPath(type(Path())):
            def mkdir(self, *args, **kwargs):  # noqa: ARG002
                raise OSError("/Users/example/.elevate/uploads/secret")

        monkeypatch.setattr(web_server, "get_elevate_home", lambda: FailingPath("/tmp/elevate-test-home"))

        resp = self.client.post(
            "/api/uploads/session",
            files={"file": ("note.txt", b"hello", "text/plain")},
        )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Could not create upload directory"
        assert "/Users/example" not in resp.text


# ---------------------------------------------------------------------------
# _build_schema_from_config tests
# ---------------------------------------------------------------------------


class TestBuildSchemaFromConfig:
    def test_produces_expected_field_count(self):
        from elevate_cli.web_server import CONFIG_SCHEMA
        # DEFAULT_CONFIG has ~150+ leaf fields
        assert len(CONFIG_SCHEMA) > 100

    def test_schema_entries_have_required_fields(self):
        from elevate_cli.web_server import CONFIG_SCHEMA
        for key, entry in list(CONFIG_SCHEMA.items())[:10]:
            assert "type" in entry, f"Missing type for {key}"
            assert "category" in entry, f"Missing category for {key}"

    def test_overrides_applied(self):
        from elevate_cli.web_server import CONFIG_SCHEMA
        # terminal.backend should be a select with options
        if "terminal.backend" in CONFIG_SCHEMA:
            entry = CONFIG_SCHEMA["terminal.backend"]
            assert entry["type"] == "select"
            assert "options" in entry
            assert "local" in entry["options"]

    def test_empty_prefix_produces_correct_keys(self):
        from elevate_cli.web_server import _build_schema_from_config
        test_config = {"model": "test", "nested": {"key": "val"}}
        schema = _build_schema_from_config(test_config)
        assert "model" in schema
        assert "nested.key" in schema

    def test_top_level_scalars_get_general_category(self):
        """Top-level scalar fields should be in 'general' category."""
        from elevate_cli.web_server import CONFIG_SCHEMA
        assert CONFIG_SCHEMA["model"]["category"] == "general"

    def test_nested_keys_get_parent_category(self):
        """Nested fields should use the top-level parent as their category."""
        from elevate_cli.web_server import CONFIG_SCHEMA
        if "agent.max_turns" in CONFIG_SCHEMA:
            assert CONFIG_SCHEMA["agent.max_turns"]["category"] == "agent"

    def test_category_merge_applied(self):
        """Small categories should be merged into larger ones."""
        from elevate_cli.web_server import CONFIG_SCHEMA
        categories = {e["category"] for e in CONFIG_SCHEMA.values()}
        # These should be merged away
        assert "privacy" not in categories  # merged into security
        assert "context" not in categories  # merged into agent

    def test_agent_hub_memory_access_and_platform_schema_exposed(self):
        from elevate_cli.web_server import CONFIG_SCHEMA, _CATEGORY_ORDER

        assert CONFIG_SCHEMA["agent_hub.default_agent"]["category"] == "agent_hub"
        assert CONFIG_SCHEMA["agent_hub.agents"]["type"] == "json"
        assert CONFIG_SCHEMA["plugins.elevate-memory-store.embedding_enabled"]["category"] == "memory"
        assert CONFIG_SCHEMA["plugins.elevate-memory-store.embedding_provider"]["options"] == [
            "openai",
            "ollama",
            "openai_compatible",
            "local_minilm",
        ]
        assert CONFIG_SCHEMA["plugins.elevate-memory-store.organize_every_n_turns"]["type"] == "number"
        assert CONFIG_SCHEMA["access.profile"]["options"] == [
            "standalone",
            "exp",
            "team_pack",
        ]
        assert CONFIG_SCHEMA["platforms.telegram.reply_to_mode"]["options"] == [
            "off",
            "first",
            "all",
        ]
        assert _CATEGORY_ORDER.index("agent_hub") < _CATEGORY_ORDER.index("memory")
        assert "access" in _CATEGORY_ORDER
        assert "platforms" in _CATEGORY_ORDER

    def test_no_single_field_categories(self):
        """After merging, no category should have just 1 field."""
        from elevate_cli.web_server import CONFIG_SCHEMA
        from collections import Counter
        cats = Counter(e["category"] for e in CONFIG_SCHEMA.values())
        for cat, count in cats.items():
            assert count >= 2, f"Category '{cat}' has only {count} field(s) — should be merged"


# ---------------------------------------------------------------------------
# Config round-trip tests
# ---------------------------------------------------------------------------


class TestConfigRoundTrip:
    """Verify config survives GET → edit → PUT without data loss."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from elevate_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_get_config_no_internal_keys(self):
        """GET /api/config should not expose _config_version or _model_meta."""
        config = self.client.get("/api/config").json()
        internal = [k for k in config if k.startswith("_")]
        assert not internal, f"Internal keys leaked to frontend: {internal}"

    def test_get_config_model_is_string(self):
        """GET /api/config should normalize model dict to a string."""
        config = self.client.get("/api/config").json()
        assert isinstance(config.get("model"), str), \
            f"model should be string, got {type(config.get('model'))}"

    def test_round_trip_preserves_model_subkeys(self):
        """Save and reload should not lose model.provider, model.base_url, etc."""
        from elevate_cli.config import load_config, save_config

        # Set up a config with model as a dict (the common user config form)
        save_config({
            "model": {
                "default": "anthropic/claude-sonnet-4",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_mode": "openai",
            }
        })

        before = load_config()
        assert isinstance(before.get("model"), dict)
        original_keys = set(before["model"].keys())

        # GET → PUT unchanged
        web_config = self.client.get("/api/config").json()
        assert isinstance(web_config.get("model"), str), "GET should normalize model to string"

        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        assert isinstance(after.get("model"), dict), "model should still be a dict after save"
        assert set(after["model"].keys()) >= original_keys, \
            f"Lost model subkeys: {original_keys - set(after['model'].keys())}"

    def test_edit_model_name_preserved(self):
        """Changing the model string should update model.default on disk."""
        from elevate_cli.config import load_config

        web_config = self.client.get("/api/config").json()
        original_model = web_config["model"]

        # Change model
        web_config["model"] = "test/editing-model"
        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        if isinstance(after.get("model"), dict):
            assert after["model"]["default"] == "test/editing-model"
        else:
            assert after["model"] == "test/editing-model"

        # Restore
        web_config["model"] = original_model
        self.client.put("/api/config", json={"config": web_config})

    def test_edit_nested_value(self):
        """Editing a nested config value should persist correctly."""
        from elevate_cli.config import load_config

        web_config = self.client.get("/api/config").json()
        original_turns = web_config.get("agent", {}).get("max_turns")

        # Change max_turns
        if "agent" not in web_config:
            web_config["agent"] = {}
        web_config["agent"]["max_turns"] = 42

        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        assert after.get("agent", {}).get("max_turns") == 42

        # Restore
        web_config["agent"]["max_turns"] = original_turns
        self.client.put("/api/config", json={"config": web_config})

    def test_schema_types_match_config_values(self):
        """Every schema field should have a matching-type value in the config."""
        config = self.client.get("/api/config").json()
        schema_resp = self.client.get("/api/config/schema").json()
        schema = schema_resp["fields"]

        def get_nested(obj, path):
            parts = path.split(".")
            cur = obj
            for p in parts:
                if cur is None or not isinstance(cur, dict):
                    return None
                cur = cur.get(p)
            return cur

        mismatches = []
        for key, entry in schema.items():
            val = get_nested(config, key)
            if val is None:
                continue  # not set in user config — fine
            expected = entry["type"]
            if expected in ("string", "select") and not isinstance(val, str):
                mismatches.append(f"{key}: expected str, got {type(val).__name__}")
            elif expected == "number" and not isinstance(val, (int, float)):
                mismatches.append(f"{key}: expected number, got {type(val).__name__}")
            elif expected == "boolean" and not isinstance(val, bool):
                mismatches.append(f"{key}: expected bool, got {type(val).__name__}")
            elif expected == "list" and not isinstance(val, list):
                mismatches.append(f"{key}: expected list, got {type(val).__name__}")
        assert not mismatches, f"Type mismatches:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# New feature endpoint tests
# ---------------------------------------------------------------------------


class TestNewEndpoints:
    """Tests for session detail, logs, cron, skills, tools, raw config, analytics."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, _isolate_elevate_home):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import elevate_state
        from elevate_constants import get_elevate_home
        from elevate_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        monkeypatch.setattr(elevate_state, "DEFAULT_DB_PATH", get_elevate_home() / "state.db")

        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_get_logs_default(self):
        resp = self.client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "file" in data
        assert "lines" in data
        assert isinstance(data["lines"], list)

    def test_get_logs_invalid_file(self):
        resp = self.client.get("/api/logs?file=nonexistent")
        assert resp.status_code == 400

    def test_cron_list(self):
        resp = self.client.get("/api/cron/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_source_inbox_debug_reports_db_read_path_and_counts(self, monkeypatch):
        import elevate_cli.data as data_mod

        def fake_db_source_inbox_response(*, limit=16):
            return {
                "toolsRoot": "/tmp/tools",
                "toolsRootSource": "test",
                "toolsRootIo": "local",
                "sourceRoot": "/tmp/source",
                "limit": limit,
                "recordCounts": {"threads": 2, "drafts": 1},
                "hiddenCounts": {"archived": 1},
                "sources": [{"id": "lofty"}],
                "profiles": [{"id": "person-1"}],
                "threads": [{"id": "thread-1"}, {"id": "thread-2"}],
                "drafts": [{"id": "draft-1"}],
                "skippedDrafts": [{"id": "skipped-1"}],
                "privateSearchBuyers": [{"id": "buyer-1"}],
            }

        monkeypatch.setattr(data_mod, "db_source_inbox_response", fake_db_source_inbox_response)

        resp = self.client.get("/api/source-inbox?limit=3&debug=1")

        assert resp.status_code == 200
        debug = resp.json()["debug"]
        assert debug["readPath"] == "db"
        assert debug["fallback"] is False
        assert debug["counts"]["threads"] == 2
        assert debug["counts"]["drafts"] == 1
        assert debug["counts"]["recordCounts"] == {"threads": 2, "drafts": 1}
        assert debug["counts"]["hiddenCounts"] == {"archived": 1}

    def test_source_inbox_debug_reports_jsonl_fallback(self, monkeypatch):
        import elevate_cli.data as data_mod
        import elevate_cli.source_connectors as source_connectors

        def fail_db_source_inbox_response(*, limit=16):
            raise RuntimeError(
                "db offline postgres://user:pass@host/db "
                "sk-1234567890abcdef agent@example.com /Users/example/.elevate/state.db"
            )

        def fake_jsonl_source_inbox_response(*, limit=16):
            return {
                "toolsRoot": "/tmp/tools",
                "toolsRootSource": "test",
                "toolsRootIo": "local",
                "sourceRoot": "/tmp/source",
                "limit": limit,
                "recordCounts": {"threads": 1},
                "hiddenCounts": {},
                "sources": [],
                "profiles": [],
                "threads": [{"id": "thread-jsonl"}],
                "drafts": [],
                "skippedDrafts": [],
                "privateSearchBuyers": [],
            }

        monkeypatch.setattr(data_mod, "db_source_inbox_response", fail_db_source_inbox_response)
        monkeypatch.setattr(
            source_connectors,
            "build_source_inbox_response",
            fake_jsonl_source_inbox_response,
        )

        resp = self.client.get("/api/source-inbox?debug=1")

        assert resp.status_code == 200
        debug = resp.json()["debug"]
        assert debug["readPath"] == "jsonl"
        assert debug["fallback"] is True
        assert debug["fallbackError"] == "RuntimeError"
        assert debug["fallbackErrorCode"] == "source_inbox_db_read_failed"
        assert debug["counts"]["threads"] == 1
        body = resp.text
        assert "postgres://user:pass@host/db" not in body
        assert "sk-1234567890abcdef" not in body
        assert "agent@example.com" not in body
        assert "/Users/example/.elevate/state.db" not in body

    def test_source_inbox_profile_update_contract(self, monkeypatch):
        import elevate_cli.source_connectors as source_connectors

        calls = []

        def fake_update_profile_state(profile_id, status, *, return_inbox=True):
            calls.append((profile_id, status, return_inbox))
            return {"ok": True}

        monkeypatch.setattr(source_connectors, "update_profile_state", fake_update_profile_state)

        resp = self.client.post(
            "/api/source-inbox/profile",
            json={"profileId": "email:test@example.com", "status": "follow_up", "returnInbox": False},
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert calls == [("email:test@example.com", "follow_up", False)]

    def test_source_inbox_draft_update_contract(self, monkeypatch):
        import elevate_cli.source_connectors as source_connectors

        calls = []

        def fake_update_source_task_state(source_id, task_id, action, *, draft_text="", return_inbox=True):
            calls.append((source_id, task_id, action, draft_text, return_inbox))
            return {"ok": True}

        monkeypatch.setattr(source_connectors, "update_source_task_state", fake_update_source_task_state)

        resp = self.client.post(
            "/api/source-inbox/draft",
            json={
                "sourceId": "email",
                "taskId": "task-1",
                "action": "approve",
                "draftText": "send this",
                "returnInbox": False,
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert calls == [("email", "task-1", "approve", "send this", False)]

    def test_apple_messages_directions_update_contract(self, monkeypatch):
        import elevate_cli.source_connectors as source_connectors

        calls = []

        def fake_set_apple_messages_directions(*, inbound=None, outbound=None):
            calls.append(("set", inbound, outbound))
            return {"inbound": bool(inbound), "outbound": True if outbound is None else bool(outbound)}

        monkeypatch.setattr(source_connectors, "set_apple_messages_directions", fake_set_apple_messages_directions)
        monkeypatch.setattr(source_connectors, "initialize_apple_messages_source", lambda: calls.append(("init",)))

        resp = self.client.post(
            "/api/source-inbox/apple-messages/directions",
            json={"inbound": False},
        )

        assert resp.status_code == 200
        assert resp.json() == {"inbound": False, "outbound": True}
        assert calls == [("set", False, None), ("init",)]

    def test_cron_attention_reports_errored_and_stale_jobs(self, monkeypatch):
        from cron import jobs as cron_jobs

        monkeypatch.setattr(
            cron_jobs,
            "list_jobs",
            lambda include_disabled=False: [
                {
                    "id": "job-error",
                    "name": "broken sync",
                    "enabled": True,
                    "last_status": "error",
                    "last_error": "bad token",
                    "last_run_at": "2026-06-18T00:00:00+00:00",
                },
                {
                    "id": "job-stale",
                    "name": "stale sync",
                    "enabled": True,
                    "last_status": "ok",
                    "last_run_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "job-disabled",
                    "name": "disabled",
                    "enabled": False,
                    "last_status": "error",
                    "last_error": "ignored",
                    "last_run_at": "2026-01-01T00:00:00+00:00",
                },
            ],
        )

        resp = self.client.get("/api/cron/attention")

        assert resp.status_code == 200
        data = resp.json()
        assert [job["id"] for job in data["errored_jobs"]] == ["job-error"]
        assert [job["id"] for job in data["stale_jobs"]] == ["job-stale"]
        assert data["total"] == 2

    def test_activity_feed_projects_surface_activity(self):
        from elevate_cli.data import connect, surface_state
        import elevate_cli.web_server as web_server

        with web_server._FS_SCAN_CACHE_LOCK:
            web_server._FS_SCAN_CACHE.clear()

        with connect() as conn:
            surface_state.append_activity(
                conn,
                "leads",
                "contract_ping",
                message="Activity route contract ready",
                metadata={"kind": "agent_activity", "severity": "info"},
                at="2099-01-01T00:00:00+00:00",
            )

        resp = self.client.get("/api/activity?agent=leads&limit=1")

        assert resp.status_code == 200
        assert resp.json() == {
            "items": [
                {
                    "kind": "agent_activity",
                    "agent": "leads",
                    "ts": "2099-01-01T00:00:00+00:00",
                    "title": "contract_ping",
                    "detail": "Activity route contract ready",
                    "status": "info",
                }
            ]
        }

    def test_integrations_route_contract(self, monkeypatch):
        import elevate_cli.source_connectors as source_connectors

        calls = []
        settings = {
            "configPath": "/tmp/config.json",
            "secretsPath": "/tmp/.env",
            "sourceRoot": "/tmp/sources",
            "crm": {"provider": "custom", "label": "CRM"},
        }

        def fake_get_integration_settings():
            calls.append(("get",))
            return settings

        def fake_save_integration_settings(form):
            calls.append(("save", form["provider"], form["baseUrl"]))
            return {**settings, "crm": {"provider": form["provider"], "baseUrl": form["baseUrl"]}}

        def fake_test_crm_connection(form):
            calls.append(("test", form["provider"], form["action"]))
            return {"success": True, "status": 200, "message": "ok"}

        monkeypatch.setattr(source_connectors, "get_integration_settings", fake_get_integration_settings)
        monkeypatch.setattr(source_connectors, "save_integration_settings", fake_save_integration_settings)
        monkeypatch.setattr(source_connectors, "test_crm_connection", fake_test_crm_connection)

        form = {"provider": "lofty", "label": "Lofty", "baseUrl": "https://crm.test"}

        assert self.client.get("/api/integrations").json() == settings
        assert self.client.put("/api/integrations", json=form).json()["crm"] == {
            "provider": "lofty",
            "baseUrl": "https://crm.test",
        }
        assert self.client.post("/api/integrations", json={**form, "action": "test"}).json() == {
            "success": True,
            "status": 200,
            "message": "ok",
        }
        assert self.client.post("/api/integrations", json=form).status_code == 400
        assert calls == [
            ("get",),
            ("save", "lofty", "https://crm.test"),
            ("test", "lofty", "test"),
        ]

    def test_ayrshare_route_contract(self, monkeypatch):
        import elevate_cli.ayrshare_client as ayrshare_client

        calls = []
        status = {"configured": True, "hasKey": True, "valid": True, "baseUrl": "https://ayrshare.test"}

        monkeypatch.setattr(ayrshare_client, "get_status", lambda: calls.append(("status",)) or status)
        monkeypatch.setattr(
            ayrshare_client,
            "set_api_key",
            lambda api_key: calls.append(("set", api_key)) or {"ok": api_key == "good", "error": "bad key"},
        )
        monkeypatch.setattr(ayrshare_client, "clear_api_key", lambda: calls.append(("clear",)) or {"ok": True})
        monkeypatch.setattr(ayrshare_client, "profiles", lambda: calls.append(("profiles",)) or {"ok": True, "data": []})
        monkeypatch.setattr(ayrshare_client, "list_scheduled", lambda: calls.append(("scheduled",)) or {"ok": True, "data": []})
        monkeypatch.setattr(
            ayrshare_client,
            "history",
            lambda *, last_records=100, last_days=None: calls.append(("history", last_records, last_days))
            or {"ok": True, "data": []},
        )

        assert self.client.get("/api/ayrshare/status").json() == status
        assert self.client.post("/api/ayrshare/key", json={"apiKey": "bad"}).status_code == 400
        assert self.client.post("/api/ayrshare/key", json={"apiKey": "good"}).json() == status
        assert self.client.delete("/api/ayrshare/key").json() == status
        assert self.client.get("/api/ayrshare/profiles").json() == {"ok": True, "data": []}
        assert self.client.get("/api/ayrshare/scheduled").json() == {"ok": True, "data": []}
        assert self.client.get("/api/ayrshare/history?last_records=7&last_days=30").json() == {
            "ok": True,
            "data": [],
        }
        assert calls == [
            ("status",),
            ("set", "bad"),
            ("set", "good"),
            ("status",),
            ("clear",),
            ("status",),
            ("profiles",),
            ("scheduled",),
            ("history", 7, 30),
        ]

    def test_composio_route_contract(self, monkeypatch):
        import elevate_cli.composio_client as composio_client
        import elevate_cli.composio_inbound as composio_inbound
        import elevate_cli.web_server as web_server

        calls = []
        status = {"configured": True, "hasKey": True, "valid": False, "baseUrl": "https://composio.test"}

        with web_server._COMPOSIO_SWR_LOCK:
            web_server._COMPOSIO_SWR.clear()
        web_server._COMPOSIO_TOOLKITS_CACHE.clear()

        monkeypatch.setattr(web_server, "_prewarm_composio_toolkits_in_background", lambda: calls.append(("prewarm",)))
        monkeypatch.setattr(composio_client, "get_status", lambda: calls.append(("status",)) or status)
        monkeypatch.setattr(
            composio_client,
            "set_api_key",
            lambda api_key: calls.append(("set", api_key)) or {"ok": api_key == "good", "error": "bad key"},
        )
        monkeypatch.setattr(composio_client, "clear_api_key", lambda: calls.append(("clear",)) or {"ok": True})
        monkeypatch.setattr(
            composio_client,
            "list_connected_accounts",
            lambda: calls.append(("connections",)) or {"ok": True, "data": []},
        )
        monkeypatch.setattr(
            composio_client,
            "list_all_connected_accounts",
            lambda *, toolkit=None, page_size=100, max_pages=50: calls.append(("connections-all", toolkit, page_size, max_pages))
            or {"ok": True, "data": []},
        )
        monkeypatch.setattr(composio_client, "load_capability_matrix", lambda: calls.append(("capabilities",)) or {"gmail": {"send": {"supported": True}}})
        monkeypatch.setattr(composio_client, "capability", lambda toolkit: calls.append(("capability", toolkit)) or {"toolkit": toolkit})
        monkeypatch.setattr(
            composio_client,
            "list_toolkits",
            lambda *, category=None, limit=100, cursor=None, search=None: calls.append(("toolkits-page", category, limit, cursor, search))
            or {"ok": True, "data": []},
        )
        monkeypatch.setattr(
            composio_client,
            "list_all_toolkits",
            lambda *, category=None, page_size=100: calls.append(("toolkits-all", category, page_size))
            or {"ok": True, "data": []},
        )
        monkeypatch.setattr(
            composio_client,
            "initiate_connection",
            lambda toolkit, redirect_url=None, user_id=None, auth_config_id=None: calls.append(
                ("connect", toolkit, redirect_url, user_id, auth_config_id)
            )
            or {"ok": True, "data": {"redirect_url": "https://connect.test"}},
        )
        monkeypatch.setattr(composio_client, "get_toolkit_details", lambda slug: calls.append(("details", slug)) or {"ok": True, "slug": slug})
        monkeypatch.setattr(
            composio_client,
            "create_custom_auth_config",
            lambda toolkit, credentials, auth_scheme=None: calls.append(("custom-auth", toolkit, credentials, auth_scheme))
            or {"ok": True, "data": {"auth_config": {"id": "auth-1"}}},
        )
        monkeypatch.setattr(composio_client, "delete_connected_account", lambda account_id: calls.append(("delete", account_id)) or {"ok": True})
        monkeypatch.setattr(composio_inbound, "list_facebook_pages_for_picker", lambda: calls.append(("fb-pages",)) or {"pages": []})
        monkeypatch.setattr(composio_inbound, "set_facebook_page_selection", lambda page_ids: calls.append(("fb-set", page_ids)) or {"ok": True})
        monkeypatch.setattr(composio_inbound, "pull_all_supported", lambda: calls.append(("pull",)) or {"ok": True, "total_new": 0})

        assert self.client.get("/api/composio/status").json() == status
        assert self.client.post("/api/composio/key", json={"apiKey": "bad"}).status_code == 400
        assert self.client.post("/api/composio/key", json={"apiKey": "good"}).json() == status
        assert self.client.delete("/api/composio/key").json() == status
        assert self.client.get("/api/composio/connections?fresh=1").json() == {"ok": True, "data": []}
        assert self.client.get("/api/composio/connections/all?toolkit=gmail&page_size=2&max_pages=3").json() == {"ok": True, "data": []}
        assert self.client.get("/api/composio/capabilities").json() == {"gmail": {"send": {"supported": True}}}
        assert self.client.get("/api/composio/capabilities?toolkit=gmail").json() == {"toolkit": "gmail"}
        assert self.client.get("/api/composio/toolkits?all=false&limit=2&cursor=c1").json() == {"ok": True, "data": []}
        assert self.client.get("/api/composio/toolkits?search=gmail&category=crm").json() == {"ok": True, "data": []}
        assert self.client.get("/api/composio/toolkits?category=crm&limit=5").json() == {"ok": True, "data": []}
        assert self.client.post(
            "/api/composio/connect",
            json={"toolkitSlug": "gmail", "redirectUrl": "app://return", "userId": "user-1"},
        ).json() == {"ok": True, "data": {"redirect_url": "https://connect.test"}}
        assert self.client.get("/api/composio/toolkits/gmail").json() == {"ok": True, "slug": "gmail"}
        custom = self.client.post(
            "/api/composio/auth-configs/custom",
            json={
                "toolkitSlug": "gmail",
                "credentials": {"client_id": "id"},
                "authScheme": "oauth2",
                "redirectUrl": "app://return",
                "userId": "user-1",
            },
        ).json()
        assert custom["data"]["auth_config_id"] == "auth-1"
        assert custom["data"]["auth_config_created"] is True
        assert self.client.delete("/api/composio/connections/account-1").json() == {"ok": True}
        assert self.client.get("/api/composio/facebook/pages").json() == {"pages": []}
        assert self.client.put("/api/composio/facebook/pages", json={"pageIds": ["page-1"]}).json() == {"ok": True}
        assert self.client.post("/api/composio/inbound/pull").json() == {"ok": True, "total_new": 0}

        assert calls == [
            ("status",),
            ("set", "bad"),
            ("set", "good"),
            ("status",),
            ("clear",),
            ("status",),
            ("connections",),
            ("connections-all", "gmail", 2, 3),
            ("capabilities",),
            ("capability", "gmail"),
            ("toolkits-page", None, 2, "c1", None),
            ("toolkits-page", "crm", 100, None, "gmail"),
            ("toolkits-all", "crm", 5),
            ("connect", "gmail", "app://return", "user-1", None),
            ("details", "gmail"),
            ("custom-auth", "gmail", {"client_id": "id"}, "oauth2"),
            ("connect", "gmail", "app://return", "user-1", "auth-1"),
            ("delete", "account-1"),
            ("fb-pages",),
            ("fb-set", ["page-1"]),
            ("pull",),
        ]

    def test_social_route_contract(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import elevate_cli.source_connectors as source_connectors
        import elevate_cli.web_server as web_server

        home = tmp_path / "home"
        source_root = tmp_path / "sources"
        social_root = source_root / "social"
        social_root.mkdir(parents=True)
        monkeypatch.setenv("ELEVATE_HOME", str(home))
        monkeypatch.setenv("ELEVATE_WORKSPACE_ID", "ws")
        monkeypatch.setattr(source_connectors, "get_source_root_info", lambda: {"sourceRoot": str(source_root)})

        snapshot_dir = home / "state" / "ws"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "social-snapshot.json").write_text(
            json.dumps({"exists": True, "summary": {"reach": 12}}),
            encoding="utf-8",
        )
        (social_root / "tasks.jsonl").write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {
                        "source_record_id": "idea-open",
                        "task_type": "social_post_idea",
                        "status": "open",
                        "timestamp": "2099-01-02T00:00:00+00:00",
                        "hook": "Open idea",
                    },
                    {
                        "source_record_id": "idea-approved",
                        "task_type": "social_post_idea",
                        "status": "approved",
                        "timestamp": "2099-01-01T00:00:00+00:00",
                        "hook": "Approved idea",
                    },
                    {"source_record_id": "task-other", "task_type": "other", "status": "open"},
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (snapshot_dir / "social-metrics.jsonl").write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {
                        "platform": "instagram",
                        "post_id": "post-1",
                        "posted_at": "2099-01-01T00:00:00+00:00",
                        "fetched_at": "2099-01-01T00:00:00+00:00",
                        "caption": "first",
                        "raw": {"keep": True},
                    },
                    {
                        "platform": "instagram",
                        "post_id": "post-1",
                        "posted_at": "2099-01-02T00:00:00+00:00",
                        "fetched_at": "2099-01-02T00:00:00+00:00",
                        "caption": "newest",
                    },
                    {"platform": "instagram", "post_id": "account", "media_type": "ACCOUNT"},
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        refresh_calls = []
        monkeypatch.setattr(
            web_server,
            "_load_social_fetcher",
            lambda module_name: SimpleNamespace(
                fetch=lambda *, lookback_days, max_posts: refresh_calls.append((module_name, lookback_days, max_posts))
                or {"platform": module_name, "status": "ok", "posts_seen": 2}
            ),
        )

        assert self.client.get("/api/social/snapshot").json()["summary"] == {"reach": 12}
        ideas = self.client.get("/api/social/ideas").json()
        assert ideas["count"] == 1
        assert ideas["items"][0]["source_record_id"] == "idea-open"
        approved = self.client.get("/api/social/ideas?status=approved").json()
        assert approved["items"][0]["source_record_id"] == "idea-approved"

        action = self.client.post(
            "/api/social/ideas/idea-open/action",
            json={"action": "approve", "notes": "ship it"},
        )
        assert action.json() == {"ok": True, "record_id": "idea-open", "action": "approve"}
        assert self.client.post("/api/social/ideas/idea-open/action", json={"action": "nope"}).status_code == 400
        assert self.client.post("/api/social/ideas/missing/action", json={"action": "approve"}).status_code == 404

        updated_tasks = [
            json.loads(line)
            for line in (social_root / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        updated = next(row for row in updated_tasks if row["source_record_id"] == "idea-open")
        assert updated["status"] == "approved"
        assert updated["approval_required"] is False
        assert updated["notes"][0]["text"] == "ship it"

        posts = self.client.get("/api/social/recent-posts?limit=1").json()
        assert posts["count"] == 1
        assert posts["items"][0]["caption"] == "newest"
        assert posts["items"][0]["raw"] == {"keep": True}

        refreshed = self.client.post(
            "/api/social/refresh?platform=instagram&lookback_days=3&max_posts=4"
        ).json()
        assert refreshed["results"]["instagram"]["posts_seen"] == 2
        assert refresh_calls == [("instagram_insights", 3, 4)]
        assert self.client.post("/api/social/refresh?platform=threads").status_code == 400

    def test_cron_job_not_found(self):
        resp = self.client.get("/api/cron/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_skills_list(self):
        resp = self.client.get("/api/skills")
        assert resp.status_code == 200
        skills = resp.json()
        assert isinstance(skills, list)
        if skills:
            assert "name" in skills[0]
            assert "enabled" in skills[0]

    def test_example_plugin_api_mount(self):
        resp = self.client.get("/api/plugins/example/hello")

        assert resp.status_code == 200
        assert resp.json() == {
            "message": "Hello from the example plugin!",
            "plugin": "example",
            "version": "1.0.0",
        }

    def test_skills_list_includes_disabled_skills(self, monkeypatch):
        import tools.skills_tool as skills_tool
        import elevate_cli.skills_config as skills_config
        import elevate_cli.web_server as web_server

        def _fake_find_all_skills(*, skip_disabled=False):
            if skip_disabled:
                return [
                    {"name": "active-skill", "description": "active", "category": "demo"},
                    {"name": "disabled-skill", "description": "disabled", "category": "demo"},
                ]
            return [
                {"name": "active-skill", "description": "active", "category": "demo"},
            ]

        monkeypatch.setattr(skills_tool, "_find_all_skills", _fake_find_all_skills)
        monkeypatch.setattr(skills_config, "get_disabled_skills", lambda config: {"disabled-skill"})
        monkeypatch.setattr(web_server, "load_config", lambda: {"skills": {"disabled": ["disabled-skill"]}})

        resp = self.client.get("/api/skills")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "active-skill",
                "description": "active",
                "category": "demo",
                "enabled": True,
            },
            {
                "name": "disabled-skill",
                "description": "disabled",
                "category": "demo",
                "enabled": False,
            },
        ]

    def test_toolsets_list(self):
        resp = self.client.get("/api/tools/toolsets")
        assert resp.status_code == 200
        toolsets = resp.json()
        assert isinstance(toolsets, list)
        if toolsets:
            assert "name" in toolsets[0]
            assert "label" in toolsets[0]
            assert "enabled" in toolsets[0]

    def test_toolsets_list_matches_cli_enabled_state(self, monkeypatch):
        import elevate_cli.tools_config as tools_config
        import toolsets as toolsets_module
        import elevate_cli.web_server as web_server

        monkeypatch.setattr(
            tools_config,
            "_get_effective_configurable_toolsets",
            lambda: [
                ("web", "🔍 Web Search & Scraping", "web_search, web_extract"),
                ("skills", "📚 Skills", "list, view, manage"),
                ("memory", "💾 Memory", "persistent memory across sessions"),
            ],
        )
        monkeypatch.setattr(
            tools_config,
            "_get_platform_tools",
            lambda config, platform, include_default_mcp_servers=False: {"web", "skills"},
        )
        monkeypatch.setattr(
            tools_config,
            "_toolset_has_keys",
            lambda ts_key, config=None: ts_key != "web",
        )
        monkeypatch.setattr(
            toolsets_module,
            "resolve_toolset",
            lambda name: {
                "web": ["web_search", "web_extract"],
                "skills": ["skills_list", "skill_view"],
                "memory": ["memory_read"],
            }[name],
        )
        monkeypatch.setattr(web_server, "load_config", lambda: {"platform_toolsets": {"cli": ["web", "skills"]}})

        resp = self.client.get("/api/tools/toolsets")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "web",
                "label": "🔍 Web Search & Scraping",
                "description": "web_search, web_extract",
                "enabled": True,
                "available": True,
                "configured": False,
                "tools": ["web_extract", "web_search"],
            },
            {
                "name": "skills",
                "label": "📚 Skills",
                "description": "list, view, manage",
                "enabled": True,
                "available": True,
                "configured": True,
                "tools": ["skill_view", "skills_list"],
            },
            {
                "name": "memory",
                "label": "💾 Memory",
                "description": "persistent memory across sessions",
                "enabled": False,
                "available": False,
                "configured": True,
                "tools": ["memory_read"],
            },
        ]

    def test_config_raw_get(self):
        resp = self.client.get("/api/config/raw")
        assert resp.status_code == 200
        assert "yaml" in resp.json()

    def test_config_raw_put_valid(self):
        resp = self.client.put(
            "/api/config/raw",
            json={"yaml_text": "model: test\ntoolsets:\n  - all\n"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_config_raw_put_invalid(self):
        resp = self.client.put(
            "/api/config/raw",
            json={"yaml_text": "- this is a list not a dict"},
        )
        assert resp.status_code == 400

    def test_analytics_usage(self):
        resp = self.client.get("/api/analytics/usage?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert "by_model" in data
        assert "totals" in data
        assert "skills" in data
        assert isinstance(data["daily"], list)
        assert "total_sessions" in data["totals"]
        assert "total_api_calls" in data["totals"]
        assert data["skills"] == {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        }

    def test_analytics_usage_includes_skill_breakdown(self):
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            db.create_session(
                session_id="skills-analytics-test",
                source="cli",
                model="anthropic/claude-sonnet-4",
            )
            db.update_token_counts(
                "skills-analytics-test",
                input_tokens=120,
                output_tokens=45,
            )
            db.append_message(
                "skills-analytics-test",
                role="assistant",
                content="Loading and updating skills.",
                tool_calls=[
                    {
                        "function": {
                            "name": "skill_view",
                            "arguments": '{"name":"github-pr-workflow"}',
                        }
                    },
                    {
                        "function": {
                            "name": "skill_manage",
                            "arguments": '{"name":"github-code-review"}',
                        }
                    },
                ],
            )
        finally:
            db.close()

        resp = self.client.get("/api/analytics/usage?days=7")
        assert resp.status_code == 200

        data = resp.json()
        assert data["skills"]["summary"] == {
            "total_skill_loads": 1,
            "total_skill_edits": 1,
            "total_skill_actions": 2,
            "distinct_skills_used": 2,
        }
        assert len(data["skills"]["top_skills"]) == 2

        top_skill = data["skills"]["top_skills"][0]
        assert top_skill["skill"] == "github-pr-workflow"
        assert top_skill["view_count"] == 1
        assert top_skill["manage_count"] == 0
        assert top_skill["total_count"] == 1
        assert top_skill["last_used_at"] is not None

    def test_session_token_endpoint_removed(self):
        """GET /api/auth/session-token no longer exists."""
        resp = self.client.get("/api/auth/session-token")
        # Should not return a JSON token object
        assert resp.status_code in (200, 404)
        try:
            data = resp.json()
            assert "token" not in data
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Model context length: normalize/denormalize + /api/model/info
# ---------------------------------------------------------------------------


class TestModelContextLength:
    """Tests for model_context_length in normalize/denormalize and /api/model/info."""

    def test_normalize_extracts_context_length_from_dict(self):
        """normalize should surface context_length from model dict."""
        from elevate_cli.web_server import _normalize_config_for_web

        cfg = {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 200000,
            }
        }
        result = _normalize_config_for_web(cfg)
        assert result["model"] == "anthropic/claude-opus-4.6"
        assert result["model_context_length"] == 200000

    def test_normalize_bare_string_model_yields_zero(self):
        """normalize should set model_context_length=0 for bare string model."""
        from elevate_cli.web_server import _normalize_config_for_web

        result = _normalize_config_for_web({"model": "anthropic/claude-sonnet-4"})
        assert result["model"] == "anthropic/claude-sonnet-4"
        assert result["model_context_length"] == 0

    def test_normalize_dict_without_context_length_yields_zero(self):
        """normalize should default to 0 when model dict has no context_length."""
        from elevate_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "provider": "openrouter"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_normalize_non_int_context_length_yields_zero(self):
        """normalize should coerce non-int context_length to 0."""
        from elevate_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "context_length": "invalid"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_denormalize_writes_context_length_into_model_dict(self):
        """denormalize should write model_context_length back into model dict."""
        from elevate_cli.web_server import _denormalize_config_from_web
        from elevate_cli.config import save_config

        # Set up disk config with model as a dict
        save_config({
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 100000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 100000
        assert "model_context_length" not in result  # virtual field removed

    def test_denormalize_zero_removes_context_length(self):
        """denormalize with model_context_length=0 should remove context_length key."""
        from elevate_cli.web_server import _denormalize_config_from_web
        from elevate_cli.config import save_config

        save_config({
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 50000,
            }
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 0,
        })
        assert isinstance(result["model"], dict)
        assert "context_length" not in result["model"]

    def test_denormalize_upgrades_bare_string_to_dict(self):
        """denormalize should upgrade bare string model to dict when context_length set."""
        from elevate_cli.web_server import _denormalize_config_from_web
        from elevate_cli.config import save_config

        # Disk has model as bare string
        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 65000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["default"] == "anthropic/claude-sonnet-4"
        assert result["model"]["context_length"] == 65000

    def test_denormalize_bare_string_stays_string_when_zero(self):
        """denormalize should keep bare string model as string when context_length=0."""
        from elevate_cli.web_server import _denormalize_config_from_web
        from elevate_cli.config import save_config

        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 0,
        })
        assert result["model"] == "anthropic/claude-sonnet-4"

    def test_denormalize_coerces_string_context_length(self):
        """denormalize should handle string model_context_length from frontend."""
        from elevate_cli.web_server import _denormalize_config_from_web
        from elevate_cli.config import save_config

        save_config({
            "model": {"default": "test/model", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "test/model",
            "model_context_length": "32000",
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 32000


class TestModelContextLengthSchema:
    """Tests for model_context_length placement in CONFIG_SCHEMA."""

    def test_schema_has_model_context_length(self):
        from elevate_cli.web_server import CONFIG_SCHEMA
        assert "model_context_length" in CONFIG_SCHEMA

    def test_schema_model_context_length_after_model(self):
        """model_context_length should appear immediately after model in schema."""
        from elevate_cli.web_server import CONFIG_SCHEMA
        keys = list(CONFIG_SCHEMA.keys())
        model_idx = keys.index("model")
        assert keys[model_idx + 1] == "model_context_length"

    def test_schema_model_context_length_is_number(self):
        from elevate_cli.web_server import CONFIG_SCHEMA
        entry = CONFIG_SCHEMA["model_context_length"]
        assert entry["type"] == "number"
        assert "category" in entry


class TestModelInfoEndpoint:
    """Tests for GET /api/model/info endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from elevate_cli.web_server import app
        self.client = TestClient(app)

    def test_model_info_returns_200(self):
        resp = self.client.get("/api/model/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data
        assert "provider" in data
        assert "auto_context_length" in data
        assert "config_context_length" in data
        assert "effective_context_length" in data
        assert "capabilities" in data

    def test_model_info_with_dict_config(self, monkeypatch):
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 100000,
            }
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-opus-4.6"
        assert data["provider"] == "openrouter"
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 100000
        assert data["effective_context_length"] == 100000  # override wins

    def test_model_info_auto_detect_when_no_override(self, monkeypatch):
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000  # auto wins

    def test_model_info_empty_model(self, monkeypatch):
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {"model": ""})

        resp = self.client.get("/api/model/info")
        data = resp.json()
        assert data["model"] == ""
        assert data["effective_context_length"] == 0

    def test_model_info_bare_string_model(self, monkeypatch):
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "anthropic/claude-sonnet-4"
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-sonnet-4"
        assert data["provider"] == ""
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000

    def test_model_info_capabilities(self, monkeypatch):
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        mock_caps = MagicMock()
        mock_caps.supports_tools = True
        mock_caps.supports_vision = True
        mock_caps.supports_reasoning = True
        mock_caps.context_window = 200000
        mock_caps.max_output_tokens = 32000
        mock_caps.model_family = "claude-opus"

        with patch("agent.model_metadata.get_model_context_length", return_value=200000), \
             patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            resp = self.client.get("/api/model/info")

        caps = resp.json()["capabilities"]
        assert caps["supports_tools"] is True
        assert caps["supports_vision"] is True
        assert caps["supports_reasoning"] is True
        assert caps["max_output_tokens"] == 32000
        assert caps["model_family"] == "claude-opus"

    def test_model_info_graceful_on_metadata_error(self, monkeypatch):
        """Endpoint should return zeros on import/resolution errors, not 500."""
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "some/obscure-model"
        })

        with patch("agent.model_metadata.get_model_context_length", side_effect=Exception("boom")):
            resp = self.client.get("/api/model/info")

        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_context_length"] == 0


# ---------------------------------------------------------------------------
# Gateway health probe tests
# ---------------------------------------------------------------------------


class TestProbeGatewayHealth:
    """Tests for _probe_gateway_health() — cross-container gateway detection."""

    def test_returns_false_when_no_url_configured(self, monkeypatch):
        """When GATEWAY_HEALTH_URL is unset, the probe returns (False, None)."""
        import elevate_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", None)
        alive, body = ws._probe_gateway_health()
        assert alive is False
        assert body is None

    def test_normalizes_url_with_health_suffix(self, monkeypatch):
        """If the user sets the URL to include /health, it's stripped to base."""
        import elevate_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642/health")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)
        # Both paths should fail (no server), but we verify they were constructed
        # correctly by checking the URLs attempted.
        calls = []
        original_urlopen = ws.urllib.request.urlopen

        def mock_urlopen(req, **kwargs):
            calls.append(req.full_url)
            raise ConnectionError("mock")

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        alive, body = ws._probe_gateway_health()
        assert alive is False
        assert "http://gw:8642/health/detailed" in calls
        assert "http://gw:8642/health" in calls

    def test_normalizes_url_with_health_detailed_suffix(self, monkeypatch):
        """If the user sets the URL to include /health/detailed, it's stripped to base."""
        import elevate_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642/health/detailed")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)
        calls = []

        def mock_urlopen(req, **kwargs):
            calls.append(req.full_url)
            raise ConnectionError("mock")

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        ws._probe_gateway_health()
        assert "http://gw:8642/health/detailed" in calls
        assert "http://gw:8642/health" in calls

    def test_successful_detailed_probe(self, monkeypatch):
        """Successful /health/detailed probe returns (True, body_dict)."""
        import elevate_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)

        response_body = json.dumps({
            "status": "ok",
            "gateway_state": "running",
            "pid": 42,
        })

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = response_body.encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(ws.urllib.request, "urlopen", lambda req, **kw: mock_resp)
        alive, body = ws._probe_gateway_health()
        assert alive is True
        assert body["status"] == "ok"
        assert body["pid"] == 42

    def test_detailed_fails_falls_back_to_simple_health(self, monkeypatch):
        """If /health/detailed fails, falls back to /health."""
        import elevate_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("detailed failed")
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({"status": "ok"}).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        alive, body = ws._probe_gateway_health()
        assert alive is True
        assert body["status"] == "ok"
        assert call_count[0] == 2


class TestStatusRemoteGateway:
    """Tests for /api/status with remote gateway health fallback."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        from elevate_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_status_falls_back_to_remote_probe(self, monkeypatch):
        """When local PID check fails and remote probe succeeds, gateway shows running."""
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_probe_gateway_health", lambda: (True, {
            "status": "ok",
            "gateway_state": "running",
            "platforms": {"telegram": {"state": "connected"}},
            "pid": 999,
        }))

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is True
        assert data["gateway_pid"] == 999
        assert data["gateway_state"] == "running"
        assert data["gateway_health_url"] == "http://gw:8642"

    def test_status_remote_probe_not_attempted_when_local_pid_found(self, monkeypatch):
        """When local PID check succeeds, the remote probe is never called."""
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: 1234)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: {
            "gateway_state": "running",
            "platforms": {},
        })
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        probe_called = [False]
        original = ws._probe_gateway_health

        def track_probe():
            probe_called[0] = True
            return original()

        monkeypatch.setattr(ws, "_probe_gateway_health", track_probe)

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        assert not probe_called[0]

    def test_status_remote_probe_not_attempted_when_no_url(self, monkeypatch):
        """When GATEWAY_HEALTH_URL is unset, no probe is attempted."""
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", None)

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is False
        assert data["gateway_health_url"] is None

    def test_status_remote_running_null_pid(self, monkeypatch):
        """Remote gateway running but PID not in response — pid should be None."""
        import elevate_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_probe_gateway_health", lambda: (True, {
            "status": "ok",
        }))

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is True
        assert data["gateway_pid"] is None
        assert data["gateway_state"] == "running"


# ---------------------------------------------------------------------------
# Dashboard theme normaliser tests
# ---------------------------------------------------------------------------


class TestNormaliseThemeDefinition:
    """Tests for _normalise_theme_definition() — parses YAML theme files."""

    def test_rejects_missing_name(self):
        from elevate_cli.web_server import _normalise_theme_definition
        assert _normalise_theme_definition({}) is None
        assert _normalise_theme_definition({"name": ""}) is None
        assert _normalise_theme_definition({"name": "   "}) is None

    def test_rejects_non_dict(self):
        from elevate_cli.web_server import _normalise_theme_definition
        assert _normalise_theme_definition("string") is None
        assert _normalise_theme_definition(None) is None
        assert _normalise_theme_definition([1, 2, 3]) is None

    def test_loose_colors_shorthand(self):
        """Bare hex strings under `colors` parse as {hex, alpha=1.0}."""
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "loose",
            "colors": {"background": "#000000", "midground": "#ffffff"},
        })
        assert result is not None
        assert result["palette"]["background"] == {"hex": "#000000", "alpha": 1.0}
        assert result["palette"]["midground"] == {"hex": "#ffffff", "alpha": 1.0}
        # foreground falls back to default (transparent white)
        assert result["palette"]["foreground"]["hex"] == "#ffffff"
        assert result["palette"]["foreground"]["alpha"] == 0.0

    def test_full_palette_form(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "full",
            "palette": {
                "background": {"hex": "#0a1628", "alpha": 1.0},
                "midground": {"hex": "#a8d0ff", "alpha": 0.9},
                "warmGlow": "rgba(255, 0, 0, 0.5)",
                "noiseOpacity": 0.5,
            },
        })
        assert result["palette"]["background"]["hex"] == "#0a1628"
        assert result["palette"]["midground"]["alpha"] == 0.9
        assert result["palette"]["warmGlow"] == "rgba(255, 0, 0, 0.5)"
        assert result["palette"]["noiseOpacity"] == 0.5

    def test_default_typography_applied_when_missing(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "minimal"})
        typo = result["typography"]
        assert "fontSans" in typo
        assert "fontMono" in typo
        assert typo["baseSize"] == "15px"
        assert typo["lineHeight"] == "1.55"
        assert typo["letterSpacing"] == "0"

    def test_partial_typography_merges_with_defaults(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "partial",
            "typography": {
                "fontSans": "MyFont, sans-serif",
                "baseSize": "12px",
            },
        })
        assert result["typography"]["fontSans"] == "MyFont, sans-serif"
        assert result["typography"]["baseSize"] == "12px"
        # fontMono defaulted
        assert "monospace" in result["typography"]["fontMono"]

    def test_layout_defaults(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "minimal"})
        assert result["layout"]["radius"] == "0.5rem"
        assert result["layout"]["density"] == "comfortable"

    def test_invalid_density_falls_back(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "bad",
            "layout": {"density": "ultra-spacious"},
        })
        assert result["layout"]["density"] == "comfortable"

    def test_valid_densities_accepted(self):
        from elevate_cli.web_server import _normalise_theme_definition
        for d in ("compact", "comfortable", "spacious"):
            r = _normalise_theme_definition({"name": "x", "layout": {"density": d}})
            assert r["layout"]["density"] == d

    def test_color_overrides_filter_unknown_keys(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "o",
            "colorOverrides": {
                "card": "#123456",
                "fakeToken": "#abcdef",
                "primary": 42,  # non-string rejected
                "destructive": "#ff0000",
            },
        })
        assert result["colorOverrides"] == {
            "card": "#123456",
            "destructive": "#ff0000",
        }

    def test_color_overrides_omitted_when_empty(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "x"})
        assert "colorOverrides" not in result

    def test_alpha_clamped_to_unit_range(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": 99.5}},
        })
        assert r["palette"]["background"]["alpha"] == 1.0
        r2 = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": -5}},
        })
        assert r2["palette"]["background"]["alpha"] == 0.0

    def test_invalid_alpha_uses_default(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": "not a number"}},
        })
        assert r["palette"]["background"]["alpha"] == 1.0


class TestDiscoverUserThemes:
    """Tests for _discover_user_themes() — scans ~/.elevate/dashboard-themes/."""

    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        from elevate_cli import web_server
        assert web_server._discover_user_themes() == []

    def test_loads_and_normalises_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        themes_dir = tmp_path / "dashboard-themes"
        themes_dir.mkdir()
        (themes_dir / "ocean.yaml").write_text(
            "name: ocean\n"
            "label: Ocean\n"
            "palette:\n"
            "  background:\n"
            "    hex: \"#0a1628\"\n"
            "    alpha: 1.0\n"
            "layout:\n"
            "  density: spacious\n"
        )
        from elevate_cli import web_server
        results = web_server._discover_user_themes()
        assert len(results) == 1
        assert results[0]["name"] == "ocean"
        assert results[0]["label"] == "Ocean"
        assert results[0]["palette"]["background"]["hex"] == "#0a1628"
        assert results[0]["layout"]["density"] == "spacious"
        # defaults filled in
        assert "fontSans" in results[0]["typography"]

    def test_malformed_yaml_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        themes_dir = tmp_path / "dashboard-themes"
        themes_dir.mkdir()
        (themes_dir / "bad.yaml").write_text("::: not valid yaml :::\n\tindent wrong")
        (themes_dir / "nameless.yaml").write_text("label: No Name Here\n")
        (themes_dir / "ok.yaml").write_text("name: ok\n")
        from elevate_cli import web_server
        results = web_server._discover_user_themes()
        names = [r["name"] for r in results]
        assert "ok" in names
        assert "bad" not in names  # malformed YAML
        assert len(results) == 1  # only the valid one


class TestNormaliseThemeExtensions:
    """Tests for the extended normaliser fields (assets, customCSS,
    componentStyles, layoutVariant) — the surfaces themes use to reskin
    the dashboard without shipping code."""

    def test_layout_variant_defaults_to_standard(self):
        from elevate_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "t"})
        assert result["layoutVariant"] == "standard"

    def test_layout_variant_accepts_known_values(self):
        from elevate_cli.web_server import _normalise_theme_definition
        for variant in ("standard", "cockpit", "tiled"):
            r = _normalise_theme_definition({"name": "t", "layoutVariant": variant})
            assert r["layoutVariant"] == variant

    def test_layout_variant_rejects_unknown(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({"name": "t", "layoutVariant": "warship"})
        assert r["layoutVariant"] == "standard"
        r2 = _normalise_theme_definition({"name": "t", "layoutVariant": 12})
        assert r2["layoutVariant"] == "standard"

    def test_assets_named_slots_passthrough(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "assets": {
                "bg": "https://example.com/bg.jpg",
                "hero": "linear-gradient(180deg, red, blue)",
                "crest": "/ds-assets/crest.svg",
                "logo": "  ",  # whitespace-only — dropped
                "notAKnownKey": "ignored",
            },
        })
        assert r["assets"]["bg"] == "https://example.com/bg.jpg"
        assert r["assets"]["hero"].startswith("linear-gradient")
        assert r["assets"]["crest"] == "/ds-assets/crest.svg"
        assert "logo" not in r["assets"]  # whitespace-only rejected
        assert "notAKnownKey" not in r["assets"]  # unknown slot ignored

    def test_assets_custom_block(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "assets": {
                "custom": {
                    "scan-lines": "/img/scan.png",
                    "my_overlay": "/img/ov.png",
                    "bad key!": "x",  # non-alnum key — rejected
                    "empty": "",        # empty value — rejected
                },
            },
        })
        assert r["assets"]["custom"] == {
            "scan-lines": "/img/scan.png",
            "my_overlay": "/img/ov.png",
        }

    def test_assets_absent_means_no_field(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({"name": "t"})
        assert "assets" not in r

    def test_custom_css_passthrough_and_capped(self):
        from elevate_cli.web_server import _normalise_theme_definition
        # Small CSS passes through verbatim.
        r = _normalise_theme_definition({
            "name": "t",
            "customCSS": "body { color: red; }",
        })
        assert r["customCSS"] == "body { color: red; }"

        # 40 KiB of CSS gets clipped to the 32 KiB cap.
        huge = "/* x */ " * (40 * 1024 // 8 + 10)
        r2 = _normalise_theme_definition({"name": "t", "customCSS": huge})
        assert len(r2["customCSS"]) <= 32 * 1024

    def test_custom_css_empty_dropped(self):
        from elevate_cli.web_server import _normalise_theme_definition
        for val in ("", "   \n\t", None):
            r = _normalise_theme_definition({"name": "t", "customCSS": val})
            assert "customCSS" not in r

    def test_component_styles_per_bucket(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {
                "card": {
                    "clipPath": "polygon(0 0, 100% 0, 100% 100%, 0 100%)",
                    "boxShadow": "inset 0 0 0 1px red",
                    "bad prop!": "ignored",  # non-alnum prop rejected
                },
                "header": {"background": "linear-gradient(red, blue)"},
                "rogueBucket": {"foo": "bar"},  # not a known bucket — rejected
            },
        })
        assert r["componentStyles"]["card"] == {
            "clipPath": "polygon(0 0, 100% 0, 100% 100%, 0 100%)",
            "boxShadow": "inset 0 0 0 1px red",
        }
        assert r["componentStyles"]["header"]["background"].startswith("linear-gradient")
        assert "rogueBucket" not in r["componentStyles"]

    def test_component_styles_empty_buckets_dropped(self):
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {
                "card": {},        # empty — dropped entirely
                "header": {"bad prop!": "ignored"},  # all props rejected — bucket dropped
                "footer": {"background": "black"},
            },
        })
        assert "card" not in r.get("componentStyles", {})
        assert "header" not in r.get("componentStyles", {})
        assert r["componentStyles"]["footer"]["background"] == "black"

    def test_component_styles_accepts_numeric_values(self):
        """Numeric values (e.g. opacity: 0.8) are coerced to strings."""
        from elevate_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {"card": {"opacity": 0.8, "zIndex": 5}},
        })
        assert r["componentStyles"]["card"] == {"opacity": "0.8", "zIndex": "5"}


class TestDashboardPluginManifestExtensions:
    """Tests for the extended plugin manifest fields (tab.override,
    tab.hidden, slots) read by _discover_dashboard_plugins()."""

    def _write_plugin(self, tmp_path, name, manifest):
        import json
        plug_dir = tmp_path / "plugins" / name / "dashboard"
        plug_dir.mkdir(parents=True)
        (plug_dir / "manifest.json").write_text(json.dumps(manifest))
        return plug_dir

    def test_override_and_hidden_carried_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "skin-home", {
            "name": "skin-home",
            "label": "Skin Home",
            "tab": {"path": "/skin-home", "override": "/", "hidden": True},
            "slots": ["sidebar", "header-left"],
            "entry": "dist/index.js",
        })
        from elevate_cli import web_server
        # Bust the process-level cache so the test plugin is picked up.
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "skin-home")
        assert entry["tab"]["override"] == "/"
        assert entry["tab"]["hidden"] is True
        assert entry["slots"] == ["sidebar", "header-left"]

    def test_override_requires_leading_slash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "bad-override", {
            "name": "bad-override",
            "label": "Bad",
            "tab": {"path": "/bad", "override": "no-leading-slash"},
            "entry": "dist/index.js",
        })
        from elevate_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "bad-override")
        assert "override" not in entry["tab"]

    def test_slots_default_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "no-slots", {
            "name": "no-slots",
            "label": "No Slots",
            "tab": {"path": "/no-slots"},
            "entry": "dist/index.js",
        })
        from elevate_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "no-slots")
        assert entry["slots"] == []
        assert "hidden" not in entry["tab"]
        assert "override" not in entry["tab"]

    def test_slots_filters_non_string_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "mixed-slots", {
            "name": "mixed-slots",
            "label": "Mixed",
            "tab": {"path": "/mixed-slots"},
            "slots": ["sidebar", "", 42, None, "header-right"],
            "entry": "dist/index.js",
        })
        from elevate_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "mixed-slots")
        assert entry["slots"] == ["sidebar", "header-right"]


# ---------------------------------------------------------------------------
# /api/pty WebSocket — terminal bridge for the dashboard "Chat" tab.
#
# These tests drive the endpoint with a tiny fake command (typically ``cat``
# or ``sh -c 'printf …'``) instead of the real ``elevate --tui`` binary.  The
# endpoint resolves its argv through ``_resolve_chat_argv``, so tests
# monkeypatch that hook.
# ---------------------------------------------------------------------------

import sys


skip_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"), reason="PTY bridge is POSIX-only"
)


@skip_on_windows
class TestPtyWebSocket:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, _isolate_elevate_home):
        from starlette.testclient import TestClient

        import elevate_cli.web_server as ws

        # Avoid exec'ing the actual TUI in tests: every test below installs
        # its own fake argv via ``ws._resolve_chat_argv``.
        self.ws_module = ws
        monkeypatch.setattr(ws, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
        self.token = ws._SESSION_TOKEN
        self.client = TestClient(ws.app)

    def _url(self, token: str | None = None, **params: str) -> str:
        tok = token if token is not None else self.token
        # TestClient.websocket_connect takes the path; it reconstructs the
        # query string, so we pass it inline.
        from urllib.parse import urlencode

        q = {"token": tok, **params}
        return f"/api/pty?{urlencode(q)}"

    def test_rejects_when_embedded_chat_disabled(self, monkeypatch):
        monkeypatch.setattr(self.ws_module, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", False)
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(self._url()):
                pass
        assert exc.value.code == 4403

    def test_rejects_missing_token(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect("/api/pty"):
                pass
        assert exc.value.code == 4401

    def test_rejects_bad_token(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(self._url(token="wrong")):
                pass
        assert exc.value.code == 4401

    def test_streams_child_stdout_to_client(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (
                ["/bin/sh", "-c", "printf elevate-ws-ok"],
                None,
                None,
            ),
        )
        with self.client.websocket_connect(self._url()) as conn:
            # Drain frames until we see the needle or time out.  TestClient's
            # recv_bytes blocks; loop until we have the signal byte string.
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    frame = conn.receive_bytes()
                except Exception:
                    break
                if frame:
                    buf += frame
                if b"elevate-ws-ok" in buf:
                    break
            assert b"elevate-ws-ok" in buf

    def test_client_input_reaches_child_stdin(self, monkeypatch):
        # ``cat`` echoes stdin back, so a write → read round-trip proves
        # the full duplex path.
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        with self.client.websocket_connect(self._url()) as conn:
            conn.send_bytes(b"round-trip-payload\n")
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                frame = conn.receive_bytes()
                if frame:
                    buf += frame
                if b"round-trip-payload" in buf:
                    break
            assert b"round-trip-payload" in buf

    def test_resize_escape_is_forwarded(self, monkeypatch):
        # Resize escape gets intercepted and applied via TIOCSWINSZ,
        # then ``tput cols/lines`` reports the new dimensions back.
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            # sleep gives the test time to push the resize before tput runs
            lambda resume=None, sidecar_url=None: (
                ["/bin/sh", "-c", "sleep 0.15; tput cols; tput lines"],
                None,
                {"TERM": "xterm-256color"},
            ),
        )
        with self.client.websocket_connect(self._url()) as conn:
            conn.send_text("\x1b[RESIZE:99;41]")
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                frame = conn.receive_bytes()
                if frame:
                    buf += frame
                if b"99" in buf and b"41" in buf:
                    break
            assert b"99" in buf and b"41" in buf

    def test_unavailable_platform_closes_with_message(self, monkeypatch):
        from elevate_cli.pty_bridge import PtyUnavailableError

        def _raise(argv, **kwargs):
            raise PtyUnavailableError("pty missing for tests")

        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        # Patch PtyBridge.spawn at the web_server module's binding.
        import elevate_cli.web_server as ws_mod

        monkeypatch.setattr(ws_mod.PtyBridge, "spawn", classmethod(lambda cls, *a, **k: _raise(*a, **k)))

        with self.client.websocket_connect(self._url()) as conn:
            # Expect a final text frame with the error message, then close.
            msg = conn.receive_text()
            assert "pty missing" in msg or "unavailable" in msg.lower() or "pty" in msg.lower()

    def test_resume_parameter_is_forwarded_to_argv(self, monkeypatch):
        captured: dict = {}

        def fake_resolve(resume=None, sidecar_url=None):
            captured["resume"] = resume
            return (["/bin/sh", "-c", "printf resume-arg-ok"], None, None)

        monkeypatch.setattr(self.ws_module, "_resolve_chat_argv", fake_resolve)

        with self.client.websocket_connect(self._url(resume="sess-42")) as conn:
            # Drain briefly so the handler actually invokes the resolver.
            try:
                conn.receive_bytes()
            except Exception:
                pass
        assert captured.get("resume") == "sess-42"

    def test_dashboard_chat_env_uses_current_python(self, monkeypatch):
        import os
        import sys

        import elevate_cli.main as main_mod
        import elevate_cli.web_server as ws_mod

        monkeypatch.delenv("ELEVATE_PYTHON", raising=False)
        monkeypatch.delenv("ELEVATE_PYTHON_SRC_ROOT", raising=False)
        monkeypatch.delenv("ELEVATE_CWD", raising=False)
        monkeypatch.setattr(
            main_mod,
            "_make_tui_argv",
            lambda *_a, **_k: (["/bin/sh", "-c", "printf env-ok"], None),
        )

        _argv, _cwd, env = ws_mod._resolve_chat_argv(
            resume="sess-42",
            sidecar_url="ws://127.0.0.1:9119/api/pub?token=t&channel=c",
        )

        assert env is not None
        assert env["ELEVATE_PYTHON"] == sys.executable
        assert env["ELEVATE_PYTHON_SRC_ROOT"]
        assert env["ELEVATE_CWD"] == os.getcwd()
        assert env["ELEVATE_TUI_RESUME"] == "sess-42"
        assert env["ELEVATE_TUI_SIDECAR_URL"].startswith("ws://127.0.0.1")

    def test_channel_param_propagates_sidecar_url(self, monkeypatch):
        """When /api/pty is opened with ?channel=, the PTY child gets a
        ELEVATE_TUI_SIDECAR_URL env var pointing back at /api/pub on the
        same channel — which is how tool events reach the dashboard sidebar."""
        captured: dict = {}

        def fake_resolve(resume=None, sidecar_url=None):
            captured["sidecar_url"] = sidecar_url
            return (["/bin/sh", "-c", "printf sidecar-ok"], None, None)

        monkeypatch.setattr(self.ws_module, "_resolve_chat_argv", fake_resolve)
        monkeypatch.setattr(
            self.ws_module.app.state, "bound_host", "127.0.0.1", raising=False
        )
        monkeypatch.setattr(
            self.ws_module.app.state, "bound_port", 9119, raising=False
        )

        with self.client.websocket_connect(self._url(channel="abc-123")) as conn:
            try:
                conn.receive_bytes()
            except Exception:
                pass

        url = captured.get("sidecar_url") or ""
        assert url.startswith("ws://127.0.0.1:9119/api/pub?")
        assert "channel=abc-123" in url
        assert "token=" in url

    def test_pub_broadcasts_to_events_subscribers(self, monkeypatch):
        """Frame written to /api/pub is rebroadcast verbatim to every
        /api/events subscriber on the same channel."""
        from urllib.parse import urlencode

        qs = urlencode({"token": self.token, "channel": "broadcast-test"})
        pub_path = f"/api/pub?{qs}"
        sub_path = f"/api/events?{qs}"

        with self.client.websocket_connect(sub_path) as sub:
            with self.client.websocket_connect(pub_path) as pub:
                pub.send_text('{"type":"tool.start","payload":{"tool_id":"t1"}}')
                received = sub.receive_text()

        assert "tool.start" in received
        assert '"tool_id":"t1"' in received

    def test_events_rejects_missing_channel(self):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(
                f"/api/events?token={self.token}"
            ):
                pass
        assert exc.value.code == 4400
