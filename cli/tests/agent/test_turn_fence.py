from __future__ import annotations

import contextvars
import threading
from collections.abc import Mapping

import pytest

from agent.turn_fence import (
    TurnBusy,
    TurnCancelled,
    TurnFence,
    TurnPermit,
    TurnToken,
    acquire_current_turn_permit,
    acquire_owned_current_turn_permit,
    bind_turn_fence,
    current_turn_cancelled,
    current_turn_persist_allowed,
    current_turn_publish_allowed,
    seal_current_turn_terminal,
)


def test_cancellation_winner_blocks_model_or_effect_start() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    snapshot = fence.request_cancel(token, reason="stop")

    assert snapshot["state"] == "cancelling"
    assert snapshot["quiesced"] is False
    with pytest.raises(TurnCancelled, match="stop"):
        fence.acquire_permit(token, "model")
    with pytest.raises(TurnCancelled, match="stop"):
        fence.acquire_permit(token, "tool", {"name": "send_message"})


def test_permit_winner_keeps_cancellation_stopping_until_release_and_worker_exit() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "tool", {"name": "admin_deal"})

    stopping = fence.request_cancel(token, reason="stop")

    assert stopping["state"] == "cancelling"
    assert stopping["in_flight_permits"] == 1
    assert stopping["quiesced"] is False

    worker_done = fence.finish_worker(token, terminal_status="interrupted")
    assert worker_done["state"] == "cancelling"
    assert worker_done["quiesced"] is False

    permit.release()
    assert fence.wait_quiesced(timeout=0.1)
    assert fence.snapshot()["state"] == "idle"


def test_new_turn_is_busy_until_cancelled_worker_quiesces() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    fence.request_cancel(token, reason="stop")

    with pytest.raises(TurnBusy, match="cancelling"):
        fence.begin_turn("prompt-2", "owner")

    fence.finish_worker(token, terminal_status="interrupted")
    next_token = fence.begin_turn("prompt-2", "owner")
    assert next_token.generation == token.generation + 1


def test_generation_scoped_wait_does_not_cross_into_next_turn() -> None:
    fence = TurnFence()
    first = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(first)
    fence.finish_worker(first, terminal_status="completed")

    second = fence.begin_turn("prompt-2", "owner")

    assert fence.wait_quiesced(timeout=0.01) is False
    assert fence.wait_generation_quiesced(first, timeout=0.01) is True
    assert fence.wait_generation_quiesced(second, timeout=0.01) is False

    forged = TurnToken(
        generation=first.generation,
        prompt_id=first.prompt_id,
        owner_id=first.owner_id,
    )
    with pytest.raises(TurnCancelled, match="another fence"):
        fence.wait_generation_quiesced(forged, timeout=0.01)

    foreign_fence = TurnFence()
    foreign = foreign_fence.begin_turn("foreign", "owner")
    with pytest.raises(TurnCancelled, match="another fence"):
        fence.wait_generation_quiesced(foreign, timeout=0.01)

    fence.abandon_admission(second, reason="test cleanup")
    foreign_fence.abandon_admission(foreign, reason="test cleanup")


def test_terminal_seal_allows_only_explicit_background_permits_to_drain() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    background = fence.acquire_background_permit(
        token,
        "memory_prefetch",
    )
    model_result = fence.acquire_permit(token, "model_result")

    with pytest.raises(TurnBusy, match="model_result"):
        fence.seal_terminal(token, terminal_status="completed")

    model_result.release()
    sealed = fence.seal_terminal(token, terminal_status="completed")
    assert sealed["terminal_committed"] is True
    assert sealed["permits_by_kind"] == {"memory_prefetch": 1}

    draining = fence.finish_worker(token, terminal_status="completed")
    assert draining["state"] == TurnFence.CANCELLING
    assert fence.wait_generation_quiesced(token, timeout=0.01) is False

    background.release()
    assert fence.wait_generation_quiesced(token, timeout=1) is True
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_general_metadata_cannot_weaken_terminal_sensitive_permits() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    tool = fence.acquire_permit(
        token,
        "tool",
        {"terminal_sensitive": False},
    )

    with pytest.raises(TurnBusy, match="tool"):
        fence.seal_terminal(token, terminal_status="completed")
    with pytest.raises(ValueError, match="not background-safe"):
        fence.acquire_background_permit(token, "model_result")

    tool.release()
    fence.seal_terminal(token, terminal_status="completed")
    fence.finish_worker(token, terminal_status="completed")
    assert fence.wait_generation_quiesced(token, timeout=1)


def test_force_close_stays_registered_until_worker_and_permits_quiesce() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "model")

    closing = fence.request_cancel(
        token,
        reason="force close",
        close_requested=True,
    )

    assert closing["state"] == "cancelling"
    assert closing["close_requested"] is True
    assert closing["quiesced"] is False
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.snapshot()["state"] == "cancelling"
    permit.release()
    assert fence.wait_quiesced(timeout=0.1)
    assert fence.snapshot()["state"] == "closed"
    with pytest.raises(TurnBusy, match="closed"):
        fence.begin_turn("prompt-2", "owner")


def test_stale_token_cannot_publish_persist_finalize_or_clear_new_turn() -> None:
    fence = TurnFence()
    old = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(old)
    fence.finish_worker(old, terminal_status="complete")
    current = fence.begin_turn("prompt-2", "owner")

    assert fence.can_publish(old) is False
    assert fence.can_persist(old) is False
    assert fence.can_finalize(old) is False
    with pytest.raises(TurnCancelled, match="stale"):
        fence.finish_worker(old, terminal_status="interrupted")
    assert fence.current_token() is current
    assert fence.snapshot()["state"] == "running"


def test_context_binding_is_optional_and_copies_into_concurrent_worker() -> None:
    # Non-gateway callers receive a no-op permit and retain existing behavior.
    with acquire_current_turn_permit("model"):
        pass
    assert current_turn_publish_allowed() is True
    assert current_turn_persist_allowed() is True

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    acquired = threading.Event()
    release = threading.Event()

    def worker() -> None:
        with acquire_current_turn_permit("tool"):
            acquired.set()
            release.wait(timeout=1)

    with bind_turn_fence(fence, token):
        ctx = contextvars.copy_context()
        thread = threading.Thread(target=ctx.run, args=(worker,))
        thread.start()
        assert acquired.wait(timeout=1)
        fence.request_cancel(token, reason="stop")
        assert current_turn_cancelled() is True
        assert current_turn_publish_allowed() is False
        assert current_turn_persist_allowed() is False
        release.set()
        thread.join(timeout=1)

    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=0.1)


def test_gateway_deferred_terminal_seal_keeps_continuation_permits_open() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    with bind_turn_fence(fence, token, defer_terminal_seal=True):
        deferred = seal_current_turn_terminal("completed")
        assert deferred["terminal_committed"] is False
        assert deferred["terminal_status"] == "completed"
        assert current_turn_publish_allowed() is True
        with acquire_current_turn_permit("continuation_model"):
            pass

    sealed = fence.seal_terminal(token, terminal_status="completed")
    assert sealed["terminal_committed"] is True
    fence.finish_worker(token, terminal_status="completed")
    assert fence.wait_generation_quiesced(token, timeout=1)


def test_admission_reserves_worker_before_thread_start() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")

    stopping = fence.request_cancel(token, reason="stop before dispatch")

    assert stopping["worker_active"] is True
    assert stopping["quiesced"] is False
    fence.abandon_admission(token, reason="worker did not start")
    assert fence.wait_quiesced(timeout=0.1)


def test_permit_release_is_thread_safe_and_idempotent() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "tool")
    start = threading.Barrier(9)
    errors: list[BaseException] = []

    def _release() -> None:
        start.wait(timeout=2)
        try:
            permit.release()
        except BaseException as exc:  # capture every racing failure
            errors.append(exc)

    workers = [threading.Thread(target=_release) for _ in range(8)]
    for worker in workers:
        worker.start()
    start.wait(timeout=2)
    for worker in workers:
        worker.join(timeout=2)

    assert errors == []
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="completed")
    assert fence.wait_quiesced(timeout=1)


def test_worker_binding_rejects_duplicate_and_different_thread() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    with pytest.raises(TurnBusy, match="already bound"):
        fence.bind_worker(token)

    outcome: dict[str, BaseException] = {}

    def _bind_again() -> None:
        try:
            fence.bind_worker(token)
        except BaseException as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=_bind_again)
    worker.start()
    worker.join(timeout=2)

    assert isinstance(outcome.get("error"), TurnBusy)
    fence.finish_worker(token, terminal_status="completed")
    assert fence.wait_quiesced(timeout=1)


def test_control_thread_cannot_finish_a_bound_live_worker() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    worker_bound = threading.Event()
    release_worker = threading.Event()

    def _worker() -> None:
        fence.bind_worker(token)
        worker_bound.set()
        assert release_worker.wait(timeout=2)
        fence.finish_worker(token, terminal_status="completed")

    worker = threading.Thread(target=_worker)
    worker.start()
    assert worker_bound.wait(timeout=1)

    with pytest.raises(TurnBusy, match="must finish itself"):
        fence.finish_worker(token, terminal_status="interrupted")
    with pytest.raises(TurnBusy, match="running"):
        fence.begin_turn("prompt-2", "owner")

    snapshot = fence.snapshot()
    assert snapshot["worker_active"] is True
    assert snapshot["worker_ident"] == worker.ident

    release_worker.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)
    next_token = fence.begin_turn("prompt-2", "owner")
    assert next_token.generation == token.generation + 1


def test_unbound_admission_cannot_be_finished_by_control_thread() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")

    with pytest.raises(TurnBusy, match="not bound"):
        fence.finish_worker(token, terminal_status="interrupted")

    snapshot = fence.snapshot()
    assert snapshot["state"] == TurnFence.RUNNING
    assert snapshot["worker_active"] is True
    assert snapshot["quiesced"] is False
    fence.abandon_admission(token, reason="Thread.start failed")
    assert fence.wait_quiesced(timeout=1)


def test_worker_finish_is_one_shot() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    fence.finish_worker(token, terminal_status="completed")

    with pytest.raises(TurnCancelled, match="already finished"):
        fence.finish_worker(token, terminal_status="completed")

    assert fence.wait_quiesced(timeout=1)


def test_acquire_requires_bound_worker_and_hostile_metadata_cannot_leak() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    with pytest.raises(TurnCancelled):
        fence.acquire_permit(token, "model")
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.bind_worker(token)

    class ExplodingMapping(Mapping):
        def __iter__(self):
            raise KeyboardInterrupt("mapping exploded")

        def __len__(self):
            return 1

        def __getitem__(self, _key):
            raise KeyError

    with pytest.raises(KeyboardInterrupt, match="mapping exploded"):
        fence.acquire_permit(token, "tool", ExplodingMapping())
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_reentrant_metadata_cancel_is_rechecked_before_registration() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    class CancellingMapping(Mapping):
        def __iter__(self):
            fence.request_cancel(token, reason="mapping cancelled")
            return iter(())

        def __len__(self):
            return 0

        def __getitem__(self, _key):
            raise KeyError

    with pytest.raises(TurnCancelled, match="mapping cancelled"):
        fence.acquire_permit(token, "tool", CancellingMapping())
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=1)


def test_registration_baseexception_rolls_back_counts() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    class ExplodingIdentityMap(dict):
        def __setitem__(self, _key, _value):
            raise KeyboardInterrupt("registry add")

    fence._active_permits = ExplodingIdentityMap()
    with pytest.raises(KeyboardInterrupt, match="registry add"):
        fence.acquire_permit(token, "tool")
    assert fence.snapshot()["in_flight_permits"] == 0
    fence._active_permits = {}
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_exact_identity_registry_rejects_equal_forged_permit() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    real = fence.acquire_permit(token, "tool")

    class EqualPermit(TurnPermit):
        def __hash__(self):
            return hash(real)

        def __eq__(self, _other):
            return True

    forged = EqualPermit(fence, token, "tool", {})
    with pytest.raises(TurnCancelled, match="not registered"):
        forged.assert_active_for("tool")
    assert fence.snapshot()["in_flight_permits"] == 1
    real.release()
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_one_permit_cannot_be_entered_by_two_operations() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "tool")
    entered = threading.Event()
    release = threading.Event()

    def _first() -> None:
        with permit:
            entered.set()
            assert release.wait(timeout=2)

    worker = threading.Thread(target=_first)
    worker.start()
    assert entered.wait(timeout=1)
    with pytest.raises(TurnCancelled, match="already entered"):
        permit.__enter__()
    release.set()
    worker.join(timeout=2)
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_owned_registry_add_failure_releases_committed_fence_permit(
    monkeypatch,
) -> None:
    import agent.turn_fence as turn_fence

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    def _explode_add(_self, _permit):
        raise KeyboardInterrupt("owned add")

    monkeypatch.setattr(turn_fence._OwnedPermitRegistry, "add", _explode_add)
    with bind_turn_fence(fence, token):
        with pytest.raises(KeyboardInterrupt, match="owned add"):
            acquire_owned_current_turn_permit("model")
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_binding_cleanup_attempts_all_permits_and_retries_one_shot_failure(
    monkeypatch,
) -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    original_release = fence._release_permit
    failed_once = False
    attempted_kinds: list[str] = []

    def _release_once_then_raise(permit, permit_token, kind):
        nonlocal failed_once
        attempted_kinds.append(kind)
        if not failed_once:
            failed_once = True
            raise KeyboardInterrupt("before unregister")
        original_release(permit, permit_token, kind)

    monkeypatch.setattr(fence, "_release_permit", _release_once_then_raise)
    with pytest.raises(KeyboardInterrupt, match="before unregister"):
        with bind_turn_fence(fence, token):
            acquire_owned_current_turn_permit("first")
            acquire_owned_current_turn_permit("second")
    assert fence.snapshot()["in_flight_permits"] == 0
    assert {"first", "second"}.issubset(attempted_kinds)
    assert len(attempted_kinds) == 3
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_finish_reconciles_after_one_shot_settlement_failure(
    monkeypatch,
) -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    original_settle = fence._settle_if_quiescent_locked
    calls = 0

    def _settle_once_then_work():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("settle once")
        return original_settle()

    monkeypatch.setattr(
        fence, "_settle_if_quiescent_locked", _settle_once_then_work
    )
    with pytest.raises(KeyboardInterrupt, match="settle once"):
        fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_release_reconciles_after_one_shot_settlement_failure(
    monkeypatch,
) -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "tool")
    fence.request_cancel(token, reason="stop")
    fence.finish_worker(token, terminal_status="interrupted")
    original_settle = fence._settle_if_quiescent_locked
    calls = 0

    def _settle_once_then_work():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("release settle once")
        return original_settle()

    monkeypatch.setattr(
        fence, "_settle_if_quiescent_locked", _settle_once_then_work
    )
    with pytest.raises(KeyboardInterrupt, match="release settle once"):
        permit.release()
    assert fence.snapshot()["in_flight_permits"] == 0
    assert fence.wait_quiesced(timeout=1)
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_abandon_reconciles_after_one_shot_settlement_failure(
    monkeypatch,
) -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    original_settle = fence._settle_if_quiescent_locked
    calls = 0

    def _settle_once_then_work():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("abandon settle once")
        return original_settle()

    monkeypatch.setattr(
        fence, "_settle_if_quiescent_locked", _settle_once_then_work
    )
    with pytest.raises(KeyboardInterrupt, match="abandon settle once"):
        fence.abandon_admission(token, reason="start failed")
    assert fence.snapshot()["worker_active"] is False
    assert fence.wait_quiesced(timeout=1)
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_hostile_string_normalization_never_half_mutates_lifecycle() -> None:
    class BadString:
        def __str__(self):
            raise KeyboardInterrupt("bad str")

    fence = TurnFence()
    with pytest.raises(KeyboardInterrupt, match="bad str"):
        fence.begin_turn(BadString(), "owner")
    assert fence.snapshot()["state"] == TurnFence.IDLE

    token = fence.begin_turn("prompt", "owner")
    fence.bind_worker(token)
    with pytest.raises(KeyboardInterrupt, match="bad str"):
        fence.request_cancel(token, reason=BadString())
    assert fence.snapshot()["state"] == TurnFence.RUNNING
    with pytest.raises(KeyboardInterrupt, match="bad str"):
        fence.finish_worker(token, terminal_status=BadString())
    assert fence.snapshot()["worker_active"] is True
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_equal_by_value_turn_token_cannot_authorize_current_generation() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    forged = TurnToken(
        generation=token.generation,
        prompt_id=token.prompt_id,
        owner_id=token.owner_id,
    )

    assert forged == token
    assert forged is not token
    assert fence.can_publish(forged) is False
    with pytest.raises(TurnCancelled, match="stale turn generation"):
        fence.acquire_permit(forged, "model")

    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_released_or_wrong_kind_permit_cannot_authorize_bookkeeping() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "tool_batch_transaction")

    with pytest.raises(TurnCancelled, match="cannot authorize"):
        permit.assert_active_for("model")
    permit.release()
    with pytest.raises(TurnCancelled, match="already released"):
        permit.assert_active_for("tool_batch_transaction")
    with pytest.raises(TurnCancelled, match="already released"):
        permit.__enter__()

    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


def test_finishing_worker_with_live_permit_blocks_publish_and_new_acquire() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)
    permit = fence.acquire_permit(token, "model")

    snapshot = fence.finish_worker(token, terminal_status="complete")

    assert snapshot["state"] == TurnFence.CANCELLING
    assert fence.can_publish(token) is False
    assert fence.can_persist(token) is False
    with pytest.raises(TurnCancelled):
        fence.acquire_permit(token, "tool")
    assert not fence.wait_quiesced(timeout=0.01)

    permit.release()
    assert fence.wait_quiesced(timeout=1)


def test_escaped_copied_context_cannot_add_owned_permit_after_binding_close() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "owner")
    fence.bind_worker(token)

    with bind_turn_fence(fence, token):
        escaped_context = contextvars.copy_context()

    with pytest.raises(TurnCancelled, match="binding already finished"):
        escaped_context.run(acquire_owned_current_turn_permit, "model")
    assert fence.snapshot()["in_flight_permits"] == 0

    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)
