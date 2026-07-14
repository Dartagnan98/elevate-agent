from types import SimpleNamespace

import pytest

from elevate_cli import outreach_db, sender


def test_unregistered_channel_fails_closed_instead_of_stub_success(monkeypatch):
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    outcomes = []

    def fake_failed(queue_id, *, error):
        outcomes.append((queue_id, error))
        return {"id": queue_id, "status": outreach_db.SEND_STATUS_FAILED, "lastError": error}

    monkeypatch.setattr(outreach_db, "mark_failed", fake_failed)
    monkeypatch.setattr(
        outreach_db,
        "mark_sent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported channel must not be marked sent")),
    )

    result = sender.dispatch_one({
        "id": "queue-1",
        "channel": "crm_note",
        "attempts": 0,
        "payload": {"draft_text": "Internal note"},
    })

    assert result["status"] == outreach_db.SEND_STATUS_FAILED
    assert outcomes == [(
        "queue-1",
        "unsupported outbound channel 'crm_note': no dispatcher is registered; no message was sent",
    )]


def test_explicit_sandbox_is_the_only_unknown_channel_stub_path(monkeypatch):
    monkeypatch.setenv("ELEVATE_OUTREACH_SANDBOX", "1")

    assert sender.get_dispatcher("crm_note") is sender._stub_dispatch


def test_unknown_channel_outside_sandbox_never_resolves_to_stub(monkeypatch):
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)

    assert sender.get_dispatcher("crm_note") is sender._unsupported_dispatch


@pytest.mark.parametrize(
    ("channel", "returncode"),
    [
        ("email", 0),
        ("social_dm", 9),
    ],
)
def test_free_form_sent_stdout_can_never_become_sent(monkeypatch, channel, returncode):
    """Neither a clean nor non-zero `SENT` line is provider evidence."""
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    spawned = []

    def fake_run(*args, **kwargs):
        spawned.append((args, kwargs))
        return SimpleNamespace(
            returncode=returncode,
            stdout="analysis\nSENT hallucinated-provider-id\n",
            stderr="agent failed" if returncode else "",
        )

    failures = []
    monkeypatch.setattr(sender.subprocess, "run", fake_run)
    monkeypatch.setitem(sender._DISPATCHERS, channel, sender._send_agent_dispatch)
    monkeypatch.setattr(
        outreach_db,
        "mark_sent",
        lambda *_args, **_kwargs: pytest.fail("free-form stdout must never mark a row sent"),
    )
    monkeypatch.setattr(
        outreach_db,
        "mark_failed",
        lambda queue_id, *, error: failures.append((queue_id, error))
        or {"id": queue_id, "status": outreach_db.SEND_STATUS_FAILED, "lastError": error},
    )

    result = sender.dispatch_one({
        "id": f"queue-{channel}",
        "channel": channel,
        "attempts": 0,
        "payload": {"draft_text": "Hello"},
    })

    assert result["status"] == outreach_db.SEND_STATUS_FAILED
    assert "transport unavailable / no provider receipt" in result["lastError"]
    # The unsafe agent is not even invoked: invoking then failing could cause
    # an outcome-unknown duplicate if the tool happened to deliver first.
    assert spawned == []


@pytest.mark.parametrize("channel", ["email", "social_dm"])
def test_unverified_agent_transports_are_not_registered_by_default(monkeypatch, channel):
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    monkeypatch.delitem(sender._DISPATCHERS, channel, raising=False)

    assert sender.get_dispatcher(channel) is sender._unsupported_dispatch


def test_composio_success_without_provider_receipt_fails_closed(monkeypatch):
    from elevate_cli import composio_client

    monkeypatch.setattr(
        composio_client,
        "execute_tool",
        lambda *_args, **_kwargs: {"ok": True, "data": {"successful": True}},
    )
    dispatch = sender.composio_dispatcher("gmail")

    with pytest.raises(sender.SenderPermanentError) as exc_info:
        dispatch({
            "id": "queue-composio-no-receipt",
            "channel": "email",
            "payload": {
                "connected_account_id": "account-1",
                "slug": "GMAIL_SEND_EMAIL",
                "args": {"to": "lead@example.com", "body": "Hello"},
            },
        })

    assert "transport unavailable / no provider receipt" in str(exc_info.value)
    assert "verify before retrying" in str(exc_info.value)


def test_composio_rejected_tool_body_never_becomes_sent(monkeypatch):
    from elevate_cli import composio_client

    monkeypatch.setattr(
        composio_client,
        "execute_tool",
        lambda *_args, **_kwargs: {
            "ok": True,
            "data": {
                "successful": False,
                "error": "provider rejected",
                "execution_id": "exec-synthetic",
            },
        },
    )
    dispatch = sender.composio_dispatcher("gmail")

    with pytest.raises(sender.SenderPermanentError) as exc_info:
        dispatch({
            "id": "queue-composio-rejected",
            "channel": "email",
            "payload": {
                "connected_account_id": "account-1",
                "slug": "GMAIL_SEND_EMAIL",
                "args": {"to": "lead@example.com", "body": "Hello"},
            },
        })

    assert "provider tool rejected" in str(exc_info.value)
    assert "provider rejected" in str(exc_info.value)


def test_composio_wrapper_execution_id_is_not_provider_receipt(monkeypatch):
    from elevate_cli import composio_client

    monkeypatch.setattr(
        composio_client,
        "execute_tool",
        lambda *_args, **_kwargs: {
            "ok": True,
            "data": {
                "successful": True,
                "execution_id": "exec-synthetic",
                "id": "wrapper-log-id",
                "data": {},
            },
        },
    )
    dispatch = sender.composio_dispatcher("gmail")

    with pytest.raises(sender.SenderPermanentError) as exc_info:
        dispatch({
            "id": "queue-composio-wrapper-only",
            "channel": "email",
            "payload": {
                "connected_account_id": "account-1",
                "slug": "GMAIL_SEND_EMAIL",
                "args": {"to": "lead@example.com", "body": "Hello"},
            },
        })

    assert "no provider receipt" in str(exc_info.value)


def test_composio_nested_provider_receipt_is_accepted(monkeypatch):
    from elevate_cli import composio_client

    monkeypatch.setattr(
        composio_client,
        "execute_tool",
        lambda *_args, **_kwargs: {
            "ok": True,
            "data": {
                "successful": True,
                "execution_id": "exec-observability-only",
                "data": {"message_id": "gmail-provider-message-1"},
            },
        },
    )

    provider_id, metadata = sender.composio_dispatcher("gmail")({
        "id": "queue-composio-provider-receipt",
        "channel": "email",
        "payload": {
            "connected_account_id": "account-1",
            "slug": "GMAIL_SEND_EMAIL",
            "args": {"to": "lead@example.com", "body": "Hello"},
        },
    })

    assert provider_id == "gmail-provider-message-1"
    assert metadata["toolkit"] == "gmail"


def test_dispatch_one_refuses_sms_when_profile_outbound_is_off(monkeypatch):
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    failures = []
    monkeypatch.setattr(sender, "apple_messages_outbound_enabled", lambda config=None: False)
    monkeypatch.setitem(
        sender._DISPATCHERS,
        "sms",
        lambda _row: pytest.fail("disabled Apple Messages transport must not run"),
    )
    monkeypatch.setattr(
        outreach_db,
        "mark_failed",
        lambda queue_id, *, error: failures.append((queue_id, error))
        or {"id": queue_id, "status": outreach_db.SEND_STATUS_FAILED, "lastError": error},
    )

    result = sender.dispatch_one({
        "id": "queue-sms-off",
        "channel": "sms",
        "attempts": 0,
        "payload": {"draft_text": "Do not send"},
    })

    assert result["status"] == outreach_db.SEND_STATUS_FAILED
    assert failures == [
        ("queue-sms-off", sender.APPLE_MESSAGES_OUTBOUND_DISABLED_ERROR),
    ]


def test_sms_kill_switch_uses_supplied_profile_config(monkeypatch):
    from elevate_cli import source_connectors

    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    profile_config = {"profile": "beta-realtor"}
    seen = []
    monkeypatch.setattr(
        source_connectors,
        "get_apple_messages_directions",
        lambda config=None: seen.append(config) or {"inbound": True, "outbound": False},
    )

    assert sender.apple_messages_outbound_enabled(profile_config) is False
    assert seen == [profile_config]


def test_explicit_sandbox_stub_bypasses_real_sms_kill_switch(monkeypatch):
    monkeypatch.setenv("ELEVATE_OUTREACH_SANDBOX", "1")
    monkeypatch.setattr(sender, "apple_messages_outbound_enabled", lambda config=None: False)
    monkeypatch.setattr(
        outreach_db,
        "mark_sent",
        lambda queue_id, provider_id: {
            "id": queue_id,
            "status": outreach_db.SEND_STATUS_SENT,
            "providerMessageId": provider_id,
        },
    )

    result = sender.dispatch_one({
        "id": "queue-sandbox-sms",
        "taskId": "task-sandbox-sms",
        "channel": "sms",
        "attempts": 0,
        "payload": {"draft_text": "Safe simulation"},
    })

    assert result["status"] == outreach_db.SEND_STATUS_SENT
    assert result["providerMessageId"].startswith("stub-sms-")


def test_tick_recovers_stale_sends_before_claiming_due_rows(monkeypatch):
    calls = []
    monkeypatch.setattr(
        outreach_db,
        "recover_stale_sends",
        lambda: calls.append("recover") or {"sent": 1, "failed": 2},
    )
    monkeypatch.setattr(
        outreach_db,
        "claim_due_sends",
        lambda **_kwargs: calls.append("claim") or [],
    )

    result = sender.tick(batch=1)

    assert calls == ["recover", "claim"]
    assert result["recovered_sent"] == 1
    assert result["recovered_failed"] == 2


def test_tick_leaves_sms_queued_when_outbound_is_off(monkeypatch):
    claimed_with = []
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    monkeypatch.setattr(sender, "apple_messages_outbound_enabled", lambda config=None: False)
    monkeypatch.setattr(
        outreach_db,
        "recover_stale_sends",
        lambda: {"sent": 0, "failed": 0},
    )
    monkeypatch.setattr(
        outreach_db,
        "claim_due_sends",
        lambda **kwargs: claimed_with.append(kwargs) or [],
    )

    result = sender.tick(batch=4)

    assert result["claimed"] == 0
    assert claimed_with[0]["limit"] == 4
    assert "sms" in claimed_with[0]["skip_channels"]
