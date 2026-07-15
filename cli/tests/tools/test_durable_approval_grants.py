"""Exact-Beta Approval Grant durability, identity, and failure boundaries."""

import concurrent.futures
import hashlib
import json
import os
import time
from types import SimpleNamespace

import pytest

from elevate_state import SessionDB
from gateway.session_context import clear_session_vars, set_session_vars
from tools import approval
import tools.tirith_security


_SESSION_KEY = "beta-durable-approval"
_COMMAND = "rm -rf /tmp/elevate-durable-approval"
_REQUEST_TWO_RESOLVERS = "0" * 31 + "1"
_REQUEST_CONTEXT = "0" * 31 + "2"
_REQUEST_EXPIRED = "0" * 31 + "3"
_REQUEST_OLD_PENDING = "0" * 31 + "4"
_REQUEST_OLD_EXPIRED = "0" * 31 + "5"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _grant_kwargs(
    request_id: str,
    boot_id: str,
    *,
    created_at: float | None = None,
    expires_at: float | None = None,
) -> dict:
    created = time.time() if created_at is None else created_at
    expiry = created + 300 if expires_at is None else expires_at
    policy = approval.ExecutionPolicy.for_mode("turn-1", "default")
    return {
        "request_id": request_id,
        "boot_id": boot_id,
        "session_key_digest": _digest(_SESSION_KEY),
        "session_id": "session-1",
        "root_correlation_id": "corr_" + "a" * 32,
        "turn_id": "turn-1",
        "tool_identity": "terminal",
        "command_digest": _digest(_COMMAND),
        "canonical_args_digest": _digest(f"args:{_COMMAND}"),
        "accepted_policy": policy.to_dict(),
        "policy_revision": 3,
        "effect_set": sorted(str(effect) for effect in policy.allowed_effects),
        "allowed_actor_id": "u1",
        "delivery_platform": "telegram",
        "delivery_chat_id": "c1",
        "delivery_thread_id": "t1",
        "origin_message_id": "m1",
        "created_at": created,
        "expires_at": expiry,
    }


def _resolve_kwargs(boot_id: str) -> dict:
    return {
        "boot_id": boot_id,
        "session_key_digest": _digest(_SESSION_KEY),
        "expected_root_correlation_id": "corr_" + "a" * 32,
        "expected_turn_id": "turn-1",
        "expected_command_digest": _digest(_COMMAND),
        "expected_origin_message_id": "m1",
        "target_state": "approved",
        "decision": "once",
        "resolution_reason": "user_response",
        "resolver_identity": "u1",
        "resolver_context": {
            "actor_id": "u1",
            "platform": "telegram",
            "chat_id": "c1",
            "thread_id": "t1",
            "origin_message_id": "m1",
        },
    }


@pytest.fixture(autouse=True)
def _exact_beta(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_INTERACTIVE", "1")
    monkeypatch.setattr(
        tools.tirith_security,
        "check_command_security",
        lambda _command: {"action": "allow", "findings": [], "summary": ""},
    )
    approval.clear_session(_SESSION_KEY)
    approval._gateway_notify_cbs.clear()
    approval._gateway_grant_stores.clear()
    yield
    approval.clear_session(_SESSION_KEY)
    approval._gateway_notify_cbs.clear()
    approval._gateway_grant_stores.clear()


def test_two_resolvers_produce_exactly_one_terminal_transition(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    boot_id = "1" * 32
    db.activate_approval_boot(boot_id)
    db.prepare_approval_grant(**_grant_kwargs(_REQUEST_TWO_RESOLVERS, boot_id))

    def resolve() -> int:
        return db.resolve_approval_grant(
            _REQUEST_TWO_RESOLVERS,
            **_resolve_kwargs(boot_id),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: resolve(), range(2)))

    assert sorted(results) == [0, 1]
    grant = db.get_approval_grant(_REQUEST_TWO_RESOLVERS)
    assert grant["state"] == "approved"
    assert grant["decision"] == "once"
    assert grant["resolver_identity"] == "u1"


def test_wrong_request_actor_delivery_and_message_context_fail_closed(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    boot_id = "2" * 32
    db.activate_approval_boot(boot_id)
    db.prepare_approval_grant(**_grant_kwargs(_REQUEST_CONTEXT, boot_id))
    valid = _resolve_kwargs(boot_id)

    assert db.resolve_approval_grant("wrong-request", **valid) == 0

    wrong_actor = dict(valid)
    wrong_actor["resolver_identity"] = "u2"
    wrong_actor["resolver_context"] = {
        **valid["resolver_context"],
        "actor_id": "u2",
    }
    assert db.resolve_approval_grant(_REQUEST_CONTEXT, **wrong_actor) == 0

    mismatched_actor_fields = dict(valid)
    mismatched_actor_fields["resolver_context"] = {
        **valid["resolver_context"],
        "actor_id": "u2",
    }
    assert db.resolve_approval_grant(
        _REQUEST_CONTEXT, **mismatched_actor_fields
    ) == 0

    wrong_delivery = dict(valid)
    wrong_delivery["resolver_context"] = {
        **valid["resolver_context"],
        "chat_id": "c2",
    }
    assert db.resolve_approval_grant(_REQUEST_CONTEXT, **wrong_delivery) == 0

    wrong_message = dict(valid)
    wrong_message["expected_origin_message_id"] = "m2"
    assert db.resolve_approval_grant(_REQUEST_CONTEXT, **wrong_message) == 0
    assert db.get_approval_grant(_REQUEST_CONTEXT)["state"] == "pending"

    assert db.resolve_approval_grant(_REQUEST_CONTEXT, **valid) == 1


def test_expired_grant_cannot_be_approved(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    boot_id = "3" * 32
    db.activate_approval_boot(boot_id)
    now = time.time()
    db.prepare_approval_grant(
        **_grant_kwargs(
            _REQUEST_EXPIRED,
            boot_id,
            created_at=now - 10,
            expires_at=now - 1,
        )
    )

    assert db.resolve_approval_grant(
        _REQUEST_EXPIRED,
        now=now,
        **_resolve_kwargs(boot_id),
    ) == 0
    grant = db.get_approval_grant(_REQUEST_EXPIRED)
    assert grant["state"] == "expired"
    assert grant["decision"] == "timeout"


def test_dead_prior_boot_is_cancelled_or_expired_on_restart(tmp_path):
    path = tmp_path / "state.db"
    old = SessionDB(path)
    old_boot = "4" * 32
    old.activate_approval_boot(old_boot, process_id=2_000_000_000)
    now = time.time()
    old.prepare_approval_grant(
        **_grant_kwargs(_REQUEST_OLD_PENDING, old_boot, created_at=now - 1)
    )
    old.prepare_approval_grant(
        **_grant_kwargs(
            _REQUEST_OLD_EXPIRED,
            old_boot,
            created_at=now - 10,
            expires_at=now - 1,
        )
    )
    old.close()

    restarted = SessionDB(path)
    new_boot = "5" * 32
    assert restarted.activate_approval_boot(new_boot) is True
    terminal = restarted.cancel_prior_boot_approval_grants(new_boot, now=now)

    assert {grant["request_id"] for grant in terminal} == {
        _REQUEST_OLD_PENDING,
        _REQUEST_OLD_EXPIRED,
    }
    assert restarted.get_approval_grant(_REQUEST_OLD_PENDING)["state"] == "cancelled"
    assert restarted.get_approval_grant(_REQUEST_OLD_EXPIRED)["state"] == "expired"
    assert restarted.resolve_approval_grant(
        _REQUEST_OLD_PENDING,
        **_resolve_kwargs(old_boot),
    ) == 0


def test_second_live_boot_fails_closed(tmp_path):
    path = tmp_path / "state.db"
    first = SessionDB(path)
    second = SessionDB(path)
    first.activate_approval_boot("6" * 32, process_id=os.getpid())

    with pytest.raises(RuntimeError, match="another live process"):
        second.activate_approval_boot("7" * 32, process_id=os.getpid())


def test_same_pid_with_new_process_start_can_take_over_stale_lease(tmp_path):
    path = tmp_path / "state.db"
    before_exec = SessionDB(path)
    after_exec = SessionDB(path)
    before_exec.activate_approval_boot(
        "8" * 32,
        process_id=os.getpid(),
        process_start_id="process-start-before-exec",
    )

    assert after_exec.activate_approval_boot(
        "9" * 32,
        process_id=os.getpid(),
        process_start_id="process-start-after-exec",
    ) is True


def test_reused_live_pid_with_new_create_time_is_not_the_lease_owner(
    tmp_path,
    monkeypatch,
):
    import elevate_state

    path = tmp_path / "state.db"
    before_reuse = SessionDB(path)
    after_reuse = SessionDB(path)
    reused_pid = os.getpid() + 100_000
    before_reuse.activate_approval_boot(
        "a" * 32,
        process_id=reused_pid,
        process_start_id="old-process-start",
        process_create_time=100.0,
    )
    monkeypatch.setattr(
        elevate_state.psutil,
        "Process",
        lambda _pid: SimpleNamespace(create_time=lambda: 200.0),
    )

    assert after_reuse.activate_approval_boot(
        "b" * 32,
        process_id=os.getpid(),
        process_start_id="new-process-start",
        process_create_time=200.0,
    ) is True


def test_forked_child_refreshes_its_process_create_time(tmp_path, monkeypatch):
    import elevate_state

    db = SessionDB(tmp_path / "state.db")
    child_pid = elevate_state._PROCESS_IMPORT_PID + 100_000
    monkeypatch.setattr(elevate_state.os, "getpid", lambda: child_pid)
    monkeypatch.setattr(
        elevate_state.psutil,
        "Process",
        lambda _pid: SimpleNamespace(create_time=lambda: 222.0),
    )

    db.activate_approval_boot("c" * 32, process_id=child_pid)

    raw = db._conn.execute(
        "SELECT value FROM state_meta WHERE key = 'approval_grants.active_boot'"
    ).fetchone()[0]
    assert json.loads(raw)["owners"][0]["process_create_time"] == 222.0


def test_shared_boot_keeps_all_live_process_owners(tmp_path):
    path = tmp_path / "state.db"
    first = SessionDB(path)
    sibling = SessionDB(path)
    challenger = SessionDB(path)
    shared_boot = "c" * 32
    first.activate_approval_boot(
        shared_boot,
        process_id=2_000_000_000,
        process_start_id="dead-parent",
        process_create_time=100.0,
    )
    sibling.activate_approval_boot(shared_boot, process_id=os.getpid())

    with pytest.raises(RuntimeError, match="another live process"):
        challenger.activate_approval_boot(
            "d" * 32,
            process_id=os.getpid() + 1,
            process_start_id="challenger",
            process_create_time=200.0,
        )


class _FailingApprovalStore:
    def activate_approval_boot(self, _boot_id, *, process_id):
        return False

    def cancel_prior_boot_approval_grants(self, _boot_id):
        return []

    def prepare_approval_grant(self, **_kwargs):
        raise OSError("read-only state store")


class _FailingResolverStore:
    def resolve_approval_grant(self, *_args, **_kwargs):
        raise OSError("resolver write failed")


def _run_guard_with_policy(callback, store):
    policy = approval.ExecutionPolicy.for_mode("turn-integrated", "default")
    effect_context = approval.ApprovalEffectContext(
        session_id="session-integrated",
        invocation_id="call-integrated",
        tool_name="terminal",
        canonical_args_digest=approval._approval_sha256({"command": _COMMAND}),
        accepted_policy=policy,
        policy_revision=1,
        declared_effects={"destructive"},
    )
    session_tokens = set_session_vars(
        platform="tui",
        chat_id=_SESSION_KEY,
        user_id="tui:local-user",
        session_key=_SESSION_KEY,
        message_id="origin-1",
        correlation_id="corr_" + "a" * 32,
    )
    policy_token = approval.set_current_execution_policy(
        policy,
        policy_revision=1,
    )
    try:
        approval.register_gateway_notify(
            _SESSION_KEY,
            callback,
            approval_store=store,
        )
        return approval.check_all_command_guards(
            _COMMAND,
            "local",
            approval_effect_context=effect_context,
        )
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)


def test_unwritable_persistence_blocks_before_notification():
    notified = []

    result = _run_guard_with_policy(
        lambda data: notified.append(data),
        _FailingApprovalStore(),
    )

    assert result["approved"] is False
    assert "no approval request was sent" in result["message"].lower()
    assert notified == []
    assert not approval.has_blocking_approval(_SESSION_KEY)


def test_resolver_store_failure_never_publishes_success():
    entry = approval._ApprovalEntry(
        {"command": _COMMAND},
        grant_store=_FailingResolverStore(),
        grant_context={
            "boot_id": approval._APPROVAL_BOOT_ID,
            "session_key_digest": approval._approval_sha256(
                {"session_key": _SESSION_KEY}
            ),
            "root_correlation_id": "",
            "turn_id": "turn-resolver-failure",
            "command_digest": approval._approval_sha256({"command": _COMMAND}),
            "origin_message_id": "origin-1",
        },
    )
    approval._gateway_queues[_SESSION_KEY] = [entry]

    resolved = approval.resolve_gateway_approval(
        _SESSION_KEY,
        "once",
        request_id=entry.request_id,
        resolver_identity="u1",
        resolver_context={
            "actor_id": "u1",
            "platform": "telegram",
            "chat_id": "c1",
        },
    )

    assert resolved == 0
    assert not entry.event.is_set()
    assert approval._gateway_queues[_SESSION_KEY] == [entry]


def test_explicitly_missing_store_blocks_before_notification():
    notified = []

    result = _run_guard_with_policy(
        lambda data: notified.append(data),
        None,
    )

    assert result["approved"] is False
    assert "no approval request was sent" in result["message"].lower()
    assert notified == []


def test_corrupt_boot_lease_blocks_before_notification(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db._conn.execute(
        "INSERT INTO state_meta (key, value) VALUES (?, ?)",
        ("approval_grants.active_boot", "not-json"),
    )
    notified = []

    result = _run_guard_with_policy(
        lambda data: notified.append(data),
        db,
    )

    assert result["approved"] is False
    assert notified == []
    assert db._conn.execute("SELECT COUNT(*) FROM approval_grants").fetchone()[0] == 0


def test_malformed_boot_lease_owner_blocks_before_notification(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db._conn.execute(
        "INSERT INTO state_meta (key, value) VALUES (?, ?)",
        (
            "approval_grants.active_boot",
            json.dumps({"boot_id": "f" * 32, "owners": [{}]}),
        ),
    )
    notified = []

    result = _run_guard_with_policy(
        lambda data: notified.append(data),
        db,
    )

    assert result["approved"] is False
    assert notified == []
    assert db._conn.execute("SELECT COUNT(*) FROM approval_grants").fetchone()[0] == 0


def test_notify_crash_cancels_already_persisted_grant(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    attempted = []

    def crash_before_delivery(data):
        attempted.append(data)
        raise RuntimeError("transport crashed before delivery")

    result = _run_guard_with_policy(crash_before_delivery, db)

    assert result["approved"] is False
    assert "failed to send" in result["message"].lower()
    request_id = attempted[0]["request_id"]
    grant = db.get_approval_grant(request_id)
    assert grant["state"] == "cancelled"
    assert grant["resolution_reason"] == "notify_failed"


def test_unsuccessful_send_result_cancels_persisted_grant(tmp_path):
    from gateway.run import _require_approval_delivery

    db = SessionDB(tmp_path / "state.db")
    attempted = []

    def return_failure_before_delivery(data):
        attempted.append(data)
        _require_approval_delivery(
            SimpleNamespace(success=False, error="transport rejected message"),
            delivery_name="text approval delivery",
        )

    result = _run_guard_with_policy(return_failure_before_delivery, db)

    assert result["approved"] is False
    assert "failed to send" in result["message"].lower()
    request_id = attempted[0]["request_id"]
    grant = db.get_approval_grant(request_id)
    assert grant["state"] == "cancelled"
    assert grant["resolution_reason"] == "notify_failed"


def test_button_delivery_requires_callback_message_identity():
    from gateway.run import _require_approval_delivery

    with pytest.raises(RuntimeError, match="no message identity"):
        _require_approval_delivery(
            SimpleNamespace(success=True, message_id=None),
            delivery_name="button-based approval delivery",
            require_message_id=True,
        )


def test_missing_policy_receipt_blocks_before_notification(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    notified = []
    session_tokens = set_session_vars(
        platform="tui",
        chat_id=_SESSION_KEY,
        user_id="tui:local-user",
        session_key=_SESSION_KEY,
        message_id="origin-1",
    )
    try:
        approval.register_gateway_notify(
            _SESSION_KEY,
            lambda data: notified.append(data),
            approval_store=db,
        )
        result = approval.check_all_command_guards(_COMMAND, "local")
    finally:
        clear_session_vars(session_tokens)

    assert result["approved"] is False
    assert notified == []
    assert db._conn.execute("SELECT COUNT(*) FROM approval_grants").fetchone()[0] == 0


def test_missing_actor_blocks_before_notification(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    notified = []
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="c1",
        user_id="",
        session_key=_SESSION_KEY,
        message_id="origin-1",
    )
    policy_token = approval.set_current_execution_policy(
        approval.ExecutionPolicy.for_mode("turn-missing-actor", "default"),
        policy_revision=1,
    )
    try:
        approval.register_gateway_notify(
            _SESSION_KEY,
            lambda data: notified.append(data),
            approval_store=db,
        )
        result = approval.check_all_command_guards(_COMMAND, "local")
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)

    assert result["approved"] is False
    assert notified == []
    assert db._conn.execute("SELECT COUNT(*) FROM approval_grants").fetchone()[0] == 0


def test_no_callback_never_creates_memory_only_beta_approval():
    session_tokens = set_session_vars(
        platform="tui",
        chat_id=_SESSION_KEY,
        session_key=_SESSION_KEY,
    )
    try:
        result = approval.check_all_command_guards(_COMMAND, "local")
    finally:
        clear_session_vars(session_tokens)

    assert result["approved"] is False
    assert result["status"] == "approval_bridge_unavailable"
    assert _SESSION_KEY not in approval._pending
    assert not approval.has_blocking_approval(_SESSION_KEY)
