from __future__ import annotations

import subprocess
from contextlib import contextmanager


def test_imessage_dispatch_uses_imsg_gateway(monkeypatch):
    from elevate_cli import sender

    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/imsg" if name == "imsg" else None

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="sent\n", stderr="")

    monkeypatch.setattr(sender.shutil, "which", fake_which)
    monkeypatch.setattr(sender.subprocess, "run", fake_run)

    pmid, info = sender._messages_native_dispatch(
        {
            "id": "q1",
            "channel": "imessage",
            "payload": {
                "draft_text": "Lead Desk test",
                "recipient": {"phone": "+12505550123"},
                "safety": {"test_send": True},
            },
        }
    )

    assert pmid.startswith("imsg-")
    assert info["gateway"] == "imsg"
    assert calls == [[
        "/usr/local/bin/imsg",
        "send",
        "--to",
        "+12505550123",
        "--text",
        "Lead Desk test",
        "--service",
        "imessage",
    ]]


def test_messages_dispatch_blocked_until_live_confirmed(monkeypatch):
    from elevate_cli import outreach_db, sender

    monkeypatch.delenv("ELEVATE_MESSAGES_LIVE_CONFIRMED", raising=False)
    monkeypatch.delenv("ELEVATE_MESSAGES_TEST_RECIPIENT", raising=False)

    calls: dict[str, object] = {}

    def fake_mark_retrying(queue_id: str, *, error: str, next_retry_at: str):
        calls["retrying"] = {"queue_id": queue_id, "error": error, "next_retry_at": next_retry_at}
        return {"id": queue_id, "status": outreach_db.SEND_STATUS_RETRYING, "lastError": error}

    def fake_dispatch(_row):
        raise AssertionError("dispatcher should not be called before self-test confirmation")

    monkeypatch.setattr(outreach_db, "mark_retrying", fake_mark_retrying)
    monkeypatch.setattr(sender, "get_dispatcher", lambda channel: fake_dispatch)

    result = sender.dispatch_one(
        {
            "id": "q1",
            "channel": "imessage",
            "status": outreach_db.SEND_STATUS_SENDING,
            "attempts": 0,
            "payload": {
                "draft_text": "Hi lead",
                "recipient": {"phone": "+12505550123"},
            },
        }
    )

    assert result["status"] == outreach_db.SEND_STATUS_RETRYING
    retrying = calls["retrying"]
    assert isinstance(retrying, dict)
    assert "messages-live-gated" in str(retrying["error"])


def test_messages_self_test_sends_exactly_one(monkeypatch):
    from elevate_cli import sender

    sent: list[dict] = []

    def fake_dispatch(row):
        sent.append(row)
        return "imsg-test123", {"gateway": "imsg"}

    monkeypatch.setattr(sender, "get_dispatcher", lambda channel: fake_dispatch)

    result = sender.send_messages_self_test("+12505550123", "test body")

    assert result["providerMessageId"] == "imsg-test123"
    assert len(sent) == 1
    assert sent[0]["channel"] == "imessage"
    assert sent[0]["payload"]["draft_text"] == "test body"
    assert sent[0]["payload"]["safety"] == {"test_send": True}
