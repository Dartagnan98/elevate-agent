"""Truth and persistence boundaries for per-deal Ask Ozzie chat."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import elevate_cli.web_routes.admin_deal_chat as deal_chat


_DEAL_ID = "deal-123"
_ADDRESS = "123 Main Street"
_CONTEXT = {
    "address": _ADDRESS,
    "context": (
        "--- DEAL SNAPSHOT (ground truth) ---\n"
        f"Property: {_ADDRESS}\n"
        "Current stage: Accepted offer (stage 3)\n"
        "Price: $500,000"
    ),
}
_PARTIAL = "The authoritative price is $999,999."


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(deal_chat.create_admin_deal_chat_router())
    return TestClient(app)


def _response(*, finish_reason=..., content: str = _PARTIAL, tool_calls=None):
    choice_values = {
        "message": SimpleNamespace(content=content, tool_calls=tool_calls),
    }
    if finish_reason is not ...:
        choice_values["finish_reason"] = finish_reason
    return SimpleNamespace(choices=[SimpleNamespace(**choice_values)])


def _install_llm(monkeypatch, response) -> None:
    import agent.auxiliary_client as auxiliary_client

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response),
        ),
    )
    monkeypatch.setattr(
        auxiliary_client,
        "get_text_auxiliary_client",
        lambda _task: (client, "test-model"),
    )
    # Exercise this route's terminal-status contract independently of the
    # shared validator's current policy.
    monkeypatch.setattr(
        auxiliary_client,
        "_validate_llm_response",
        lambda raw, _task: raw,
    )


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(_response(finish_reason="length"), id="length"),
        pytest.param(_response(), id="missing"),
        pytest.param(_response(finish_reason="future_status"), id="unknown"),
        pytest.param(
            _response(finish_reason="tool_calls", tool_calls=[{"id": "call-1"}]),
            id="tool-calls-status",
        ),
        pytest.param(
            _response(finish_reason="stop", tool_calls=[{"id": "call-1"}]),
            id="stop-with-tool-calls",
        ),
    ],
)
def test_non_terminal_or_non_text_response_discards_partial_and_persists_fallback(
    monkeypatch,
    response,
):
    monkeypatch.setattr(deal_chat, "_deal_chat_context", lambda _deal_id: _CONTEXT)
    _install_llm(monkeypatch, response)

    result = _client().post(
        f"/api/admin/deals/{_DEAL_ID}/chat",
        json={"message": "What is the price?"},
    )

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["reply"] == f"{_ADDRESS} is at $500,000."
    assert body["model"] is None
    assert _PARTIAL not in result.text

    persisted = json.loads(deal_chat._chat_path(_DEAL_ID).read_text("utf-8"))
    assert persisted["messages"][-1]["content"] == body["reply"]
    assert _PARTIAL not in json.dumps(persisted)


def test_exact_text_only_stop_is_authoritative(monkeypatch):
    monkeypatch.setattr(deal_chat, "_deal_chat_context", lambda _deal_id: _CONTEXT)
    response = _response(
        finish_reason="stop",
        content="The verified price is $500,000.",
    )
    _install_llm(monkeypatch, response)

    result = _client().post(
        f"/api/admin/deals/{_DEAL_ID}/chat",
        json={"message": "What is the price?"},
    )

    assert result.status_code == 200, result.text
    assert result.json()["reply"] == "The verified price is $500,000."
    assert result.json()["model"] == "test-model"


def test_exact_stop_false_complete_cannot_override_or_enter_open_tasks_transcript(
    monkeypatch,
):
    context = {
        "address": _ADDRESS,
        "context": (
            "--- DEAL SNAPSHOT (ground truth) ---\n"
            f"Property: {_ADDRESS}\n"
            "Current stage: Accepted offer (stage 3)\n"
            "Open tasks: forms [running]"
        ),
    }
    false_complete = "Everything is complete and nothing is pending."
    monkeypatch.setattr(deal_chat, "_deal_chat_context", lambda _deal_id: context)
    _install_llm(
        monkeypatch,
        _response(finish_reason="stop", content=false_complete),
    )

    result = _client().post(
        f"/api/admin/deals/{_DEAL_ID}/chat",
        json={"message": "Is everything done?"},
    )

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["reply"] == f"Open on {_ADDRESS}: forms [running]."
    assert body["model"] is None
    assert false_complete not in result.text

    persisted = json.loads(deal_chat._chat_path(_DEAL_ID).read_text("utf-8"))
    assert persisted["messages"][-1]["content"] == body["reply"]
    assert false_complete not in json.dumps(persisted)


def test_load_transcript_propagates_read_errors(monkeypatch):
    path = deal_chat._chat_path(_DEAL_ID)
    path.parent.mkdir(parents=True)
    path.write_text('{"messages": []}', "utf-8")
    original_read_text = Path.read_text

    def _broken_read_text(self, *args, **kwargs):
        if self == path:
            raise OSError("read failed")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _broken_read_text)

    with pytest.raises(OSError, match="read failed"):
        deal_chat._load_transcript(_DEAL_ID)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="missing-messages"),
        pytest.param({"messages": "not-a-list"}, id="messages-not-list"),
        pytest.param({"messages": ["not-an-object"]}, id="entry-not-object"),
        pytest.param(
            {"messages": [{"role": "system", "content": "unsafe"}]},
            id="invalid-role",
        ),
        pytest.param(
            {"messages": [{"role": "user", "content": 123}]},
            id="invalid-content",
        ),
    ],
)
def test_load_transcript_propagates_schema_corruption(payload):
    path = deal_chat._chat_path(_DEAL_ID)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), "utf-8")

    with pytest.raises(ValueError):
        deal_chat._load_transcript(_DEAL_ID)


def test_corrupt_json_is_non_success_for_get_and_post_and_is_not_overwritten(monkeypatch):
    path = deal_chat._chat_path(_DEAL_ID)
    path.parent.mkdir(parents=True)
    corrupted = "{not-json"
    path.write_text(corrupted, "utf-8")
    monkeypatch.setattr(deal_chat, "_deal_chat_context", lambda _deal_id: _CONTEXT)

    with pytest.raises(json.JSONDecodeError):
        deal_chat._load_transcript(_DEAL_ID)

    client = _client()
    get_result = client.get(f"/api/admin/deals/{_DEAL_ID}/chat")
    post_result = client.post(
        f"/api/admin/deals/{_DEAL_ID}/chat",
        json={"message": "What is the price?"},
    )

    assert get_result.status_code == 500
    assert post_result.status_code == 500
    assert get_result.json()["detail"] == "Deal chat transcript could not be read safely."
    assert post_result.json()["detail"] == "Deal chat transcript could not be read safely."
    assert path.read_text("utf-8") == corrupted


def test_save_transcript_propagates_replace_failure(monkeypatch):
    def _broken_replace(self, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", _broken_replace)

    with pytest.raises(OSError, match="replace failed"):
        deal_chat._save_transcript(
            _DEAL_ID,
            [{"role": "user", "content": "hello", "ts": "2026-07-13T00:00:00Z"}],
        )


def test_post_does_not_report_success_when_transcript_save_fails(monkeypatch):
    monkeypatch.setattr(deal_chat, "_deal_chat_context", lambda _deal_id: _CONTEXT)
    monkeypatch.setattr(
        deal_chat,
        "_save_transcript",
        lambda _deal_id, _messages: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = _client().post(
        f"/api/admin/deals/{_DEAL_ID}/chat",
        json={"message": "What is the price?"},
    )

    assert result.status_code == 500
    assert result.json() == {"detail": "Deal chat response could not be saved."}
    assert '"ok":true' not in result.text
