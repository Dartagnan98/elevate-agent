"""Admin onboarding chat must never invent readiness or accept partial output."""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes.admin_onboarding import (
    _onboarding_chat_context,
    _onboarding_fallback_reply,
    create_admin_onboarding_router,
)


def _setup_snapshot(*, complete: bool = False) -> dict:
    calendar_ready = complete
    return {
        "profile": {
            "realtorLegalName": "Test Realtor",
            "brokerageName": "Test Brokerage",
            "province": "BC",
        },
        "items": [
            {
                "key": "calendar",
                "label": "Calendar",
                "status": "connected",
                "provider": "Google Calendar",
            }
        ],
        "readiness": [
            {
                "key": "calendar",
                "label": "Calendar",
                "ready": calendar_ready,
                "state": "ready" if calendar_ready else "needs_runtime_verification",
                "action": (
                    "No action needed."
                    if calendar_ready
                    else "Connect or verify the live account, then run Verify connections."
                ),
            }
        ],
        "complete": complete,
        "requiredCount": 1,
        "completedRequiredCount": 1 if complete else 0,
        "missingRequiredKeys": [] if complete else ["calendar"],
        "completionPct": 100 if complete else 0,
    }


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_admin_onboarding_router())
    return TestClient(app)


def test_snapshot_read_failure_is_503_not_false_complete(monkeypatch):
    import elevate_cli.data as data

    @contextmanager
    def _broken_connect():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(data, "connect", _broken_connect)

    response = _client().post(
        "/api/admin/onboarding/chat",
        json={"messages": [{"role": "user", "content": "Where are we at?"}]},
    )

    assert response.status_code == 503
    assert "cannot be verified" in response.json()["detail"]


def test_empty_snapshot_is_503_not_false_complete(monkeypatch):
    import elevate_cli.data as data

    @contextmanager
    def _connect():
        yield object()

    monkeypatch.setattr(data, "connect", _connect)
    monkeypatch.setattr(data, "get_admin_setup", lambda _conn: {})

    response = _client().post(
        "/api/admin/onboarding/chat",
        json={"messages": [{"role": "user", "content": "status"}]},
    )

    assert response.status_code == 503
    assert "cannot be verified" in response.json()["detail"]


def test_empty_readiness_is_503_not_false_complete(monkeypatch):
    import elevate_cli.data as data

    @contextmanager
    def _connect():
        yield object()

    snapshot = _setup_snapshot()
    snapshot["readiness"] = []
    snapshot["missingRequiredKeys"] = []
    monkeypatch.setattr(data, "connect", _connect)
    monkeypatch.setattr(data, "get_admin_setup", lambda _conn: snapshot)

    response = _client().post(
        "/api/admin/onboarding/chat",
        json={"messages": [{"role": "user", "content": "status"}]},
    )

    assert response.status_code == 503
    assert "cannot be verified" in response.json()["detail"]


def test_pending_verification_uses_authoritative_user_action():
    setup = _setup_snapshot()

    context = _onboarding_chat_context(setup)
    reply = _onboarding_fallback_reply(
        [{"role": "user", "content": "Where are we at?"}],
        setup,
    )

    assert "user action required" in context
    assert "run Verify connections" in context
    assert "run Verify connections" in reply
    assert "clear automatically" not in reply
    assert "No user action needed" not in reply


def test_readiness_truth_overrides_stale_empty_missing_key_cache():
    setup = _setup_snapshot()
    setup["missingRequiredKeys"] = []
    setup["completionPct"] = 100
    setup["completedRequiredCount"] = 1

    context = _onboarding_chat_context(setup)
    reply = _onboarding_fallback_reply(
        [{"role": "user", "content": "Where are we at?"}],
        setup,
    )

    assert "Completion: 0% (0/1)" in context
    assert "All required items present" not in context
    assert "Everything required is in" not in reply
    assert "Verify connections" in reply


def test_length_reply_is_discarded_for_ground_truth_fallback(monkeypatch):
    import agent.auxiliary_client as auxiliary_client
    import elevate_cli.data as data

    setup = _setup_snapshot()

    @contextmanager
    def _connect():
        yield object()

    partial = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(
                    content="BC is fully set up and ready",
                    tool_calls=None,
                ),
            )
        ]
    )
    llm_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: partial)
        )
    )
    monkeypatch.setattr(data, "connect", _connect)
    monkeypatch.setattr(data, "get_admin_setup", lambda _conn: setup)
    monkeypatch.setattr(
        auxiliary_client,
        "get_text_auxiliary_client",
        lambda _task: (llm_client, "test-model"),
    )
    monkeypatch.setattr(
        auxiliary_client,
        "_validate_llm_response",
        lambda response, _task: response,
    )

    response = _client().post(
        "/api/admin/onboarding/chat",
        json={"messages": [{"role": "user", "content": "Where are we at?"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "fully set up and ready" not in body["reply"]
    assert "Verify connections" in body["reply"]
    assert "warning" in body


def test_stop_status_reply_cannot_override_incomplete_readiness(monkeypatch):
    import agent.auxiliary_client as auxiliary_client
    import elevate_cli.data as data

    setup = _setup_snapshot()

    @contextmanager
    def _connect():
        yield object()

    false_ready = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content="BC is fully set up and ready to go.",
                    tool_calls=None,
                ),
            )
        ]
    )
    llm_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: false_ready)
        )
    )
    monkeypatch.setattr(data, "connect", _connect)
    monkeypatch.setattr(data, "get_admin_setup", lambda _conn: setup)
    monkeypatch.setattr(
        auxiliary_client,
        "get_text_auxiliary_client",
        lambda _task: (llm_client, "test-model"),
    )
    monkeypatch.setattr(
        auxiliary_client,
        "_validate_llm_response",
        lambda response, _task: response,
    )

    response = _client().post(
        "/api/admin/onboarding/chat",
        json={"messages": [{"role": "user", "content": "What's our status?"}]},
    )

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "fully set up" not in reply
    assert "Verify connections" in reply
