"""Process-local generation and effect fencing for one live agent actor.

The fence is deliberately independent from the TUI and platform gateways.  A
gateway owns one :class:`TurnFence` per live actor and hands the exact
:class:`TurnToken` to the worker that executes the accepted turn.  Model and
tool calls acquire short-lived permits immediately before invoking external
code; cancellation and permit acquisition therefore have one linearization
point without holding the fence lock during I/O.

This is an in-process safety boundary.  It cannot undo an operation whose
permit already won, and it is not a substitute for provider idempotency keys or
durable outbox receipts.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterator, Mapping


class TurnBusy(RuntimeError):
    """Raised when a new turn is admitted before the prior one quiesces."""


class TurnCancelled(RuntimeError):
    """Raised when cancellation wins before an operation permit is acquired."""


@dataclass(frozen=True, slots=True)
class TurnToken:
    """Unforgeable-by-value capability for one admitted turn generation."""

    generation: int
    prompt_id: str
    owner_id: str
    _fence_identity: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )


class TurnPermit:
    """One operation permit acquired from :class:`TurnFence`.

    ``release`` is idempotent so defensive cleanup paths can call it safely.
    The object is also a context manager for the normal case.
    """

    __slots__ = (
        "_fence",
        "_token",
        "_kind",
        "_metadata",
        "_terminal_sensitive",
        "_released",
        "_entered",
        "_release_lock",
    )

    def __init__(
        self,
        fence: "TurnFence",
        token: TurnToken,
        kind: str,
        metadata: Mapping[str, Any] | None,
        *,
        terminal_sensitive: bool = True,
    ) -> None:
        self._fence = fence
        self._token = token
        self._kind = str(kind or "operation")
        self._metadata = MappingProxyType(
            dict(metadata if metadata is not None else {})
        )
        self._terminal_sensitive = bool(terminal_sensitive)
        self._released = False
        self._entered = False
        self._release_lock = threading.Lock()

    def __enter__(self) -> "TurnPermit":
        with self._release_lock:
            if self._released:
                raise TurnCancelled("turn permit was already released")
            if self._entered:
                raise TurnCancelled("turn permit is already entered")
            self._fence._assert_active_permit(
                self, self._token, self._kind
            )
            self._entered = True
            return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()

    def release(self) -> None:
        # Permits are intentionally transferable between provider/tool workers
        # and their result-projection owner.  Cleanup stacks and normal paths
        # may therefore race to release the same object from different threads.
        # Linearize the idempotency bit before touching the fence count.
        with self._release_lock:
            if self._released:
                return
            # Keep the idempotency bit retryable until fence reconciliation
            # succeeds.  A BaseException injected at this boundary must not
            # turn all later cleanup attempts into no-ops and wedge the actor.
            try:
                self._fence._release_permit(self, self._token, self._kind)
            except BaseException:
                # A wrapper may raise after the fence already committed the
                # unregister.  In that case the actor is safe and retrying the
                # exact release would be wrong; otherwise leave it retryable.
                if not self._fence._permit_is_registered(self):
                    self._released = True
                raise
            else:
                self._released = True

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def terminal_sensitive(self) -> bool:
        return self._terminal_sensitive

    def assert_active_for(self, kind: str) -> None:
        """Validate this exact live capability for retained bookkeeping.

        Ordinary callers should use the permit as a context manager.  This
        narrower assertion exists for code that must finish terminal
        bookkeeping after cancellation without acquiring a new effect permit.
        """
        expected_kind = str(kind or "operation")
        with self._release_lock:
            if self._released:
                raise TurnCancelled("turn permit was already released")
            if self._kind != expected_kind:
                raise TurnCancelled(
                    f"turn permit kind {self._kind!r} cannot authorize "
                    f"{expected_kind!r}"
                )
            self._fence._assert_active_permit(
                self, self._token, expected_kind
            )


class _NoopPermit:
    """Backward-compatible permit used by non-gateway AIAgent callers."""

    __slots__ = ()

    def __enter__(self) -> "_NoopPermit":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def release(self) -> None:
        return None


class TurnFence:
    """One monotonic turn state machine for a live actor.

    State transitions are lock-linearized::

        IDLE -> RUNNING(g) -> CANCELLING(g) -> IDLE | CLOSED
                         -> IDLE | CLOSED

    Admission marks the worker as pending immediately, so a Stop racing the
    thread start cannot falsely observe quiescence.  ``finish_worker`` is the
    only operation that releases that worker ownership.  A cancelling turn is
    quiescent only after both the worker and every already-won permit exit.
    """

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CLOSED = "closed"
    _BACKGROUND_PERMIT_KINDS = frozenset({"memory_prefetch"})

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._identity = object()
        self._generation = 0
        self._last_quiesced_generation = 0
        self._state = self.IDLE
        self._token: TurnToken | None = None
        self._cancel_event = threading.Event()
        self._quiesced = threading.Event()
        self._quiesced.set()
        self._worker_active = False
        self._worker_ident: int | None = None
        self._in_flight_permits = 0
        self._permits_by_kind: dict[str, int] = {}
        self._active_permits: dict[
            int, tuple[TurnPermit, TurnToken, str]
        ] = {}
        self._cancel_reason = ""
        self._close_requested = False
        self._finish_requested = False
        self._terminal_status = ""
        self._terminal_committed = False

    def begin_turn(self, prompt_id: str, owner_id: str) -> TurnToken:
        """Admit a turn or fail while an earlier generation is not quiescent."""
        normalized_prompt_id = str(prompt_id or "")
        normalized_owner_id = str(owner_id or "")
        with self._condition:
            if self._state == self.CLOSED:
                raise TurnBusy("actor is closed")
            if (
                self._state != self.IDLE
                or self._worker_active
                or self._in_flight_permits
            ):
                raise TurnBusy(f"actor is {self._state}")
            self._generation += 1
            token = TurnToken(
                generation=self._generation,
                prompt_id=normalized_prompt_id,
                owner_id=normalized_owner_id,
                _fence_identity=self._identity,
            )
            self._token = token
            self._state = self.RUNNING
            self._cancel_event = threading.Event()
            self._quiesced.clear()
            # Admission itself reserves the worker.  This closes the window
            # between returning the prompt acknowledgement and Thread.start().
            self._worker_active = True
            self._worker_ident = None
            self._in_flight_permits = 0
            self._permits_by_kind = {}
            self._active_permits = {}
            self._cancel_reason = ""
            self._close_requested = False
            self._finish_requested = False
            self._terminal_status = ""
            self._terminal_committed = False
            self._condition.notify_all()
            return token

    def bind_worker(self, token: TurnToken) -> None:
        """Bind the admitted generation to the current worker thread."""
        with self._condition:
            self._require_current_locked(token)
            if not self._worker_active:
                raise TurnCancelled("turn worker already quiesced")
            if self._worker_ident is not None:
                raise TurnBusy(
                    "turn worker is already bound "
                    f"to thread {self._worker_ident}"
                )
            self._worker_ident = threading.get_ident()
            self._condition.notify_all()

    def request_cancel(
        self,
        token: TurnToken | None = None,
        *,
        reason: str,
        close_requested: bool = False,
    ) -> dict[str, Any]:
        """Linearize cancellation against future operation acquisition."""
        normalized_reason = str(reason or "cancelled")
        normalized_close_requested = bool(close_requested)
        with self._condition:
            if self._state == self.CLOSED:
                return self._snapshot_locked()
            if self._state == self.IDLE:
                if normalized_close_requested:
                    self._close_requested = True
                    self._state = self.CLOSED
                self._quiesced.set()
                self._condition.notify_all()
                return self._snapshot_locked()
            if token is not None:
                self._require_current_locked(token)
            if self._terminal_committed:
                # Completion already won the terminal seal. A later Stop may
                # request actor closure, but it cannot retroactively cancel a
                # result whose final permit release and terminal truth were
                # committed under this same lock.
                self._close_requested = (
                    self._close_requested or normalized_close_requested
                )
                self._condition.notify_all()
                return self._snapshot_locked()
            self._state = self.CANCELLING
            self._cancel_reason = normalized_reason
            self._close_requested = (
                self._close_requested or normalized_close_requested
            )
            self._cancel_event.set()
            self._condition.notify_all()
            return self._snapshot_locked()

    def acquire_permit(
        self,
        token: TurnToken,
        kind: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> TurnPermit:
        """Acquire an operation permit if this generation is still RUNNING.

        The lock is released before the returned permit is used, so provider,
        tool, and external-effect code never runs while holding the fence lock.
        """
        return self._acquire_permit(
            token,
            kind,
            metadata,
            terminal_sensitive=True,
        )

    def acquire_background_permit(
        self,
        token: TurnToken,
        kind: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> TurnPermit:
        """Acquire an explicitly allowlisted permit that may outlive sealing."""
        normalized_kind = str(kind or "operation")
        if normalized_kind not in self._BACKGROUND_PERMIT_KINDS:
            raise ValueError(
                f"permit kind {normalized_kind!r} is not background-safe"
            )
        return self._acquire_permit(
            token,
            normalized_kind,
            metadata,
            terminal_sensitive=False,
        )

    def _acquire_permit(
        self,
        token: TurnToken,
        kind: str,
        metadata: Mapping[str, Any] | None,
        *,
        terminal_sensitive: bool,
    ) -> TurnPermit:
        normalized_kind = str(kind or "operation")
        # Copy arbitrary user mappings before taking the fence lock.  A
        # re-entrant Mapping may cancel the turn or raise during iteration; in
        # either case the state check below remains the acquisition
        # linearization point and no count has been changed yet.
        permit = TurnPermit(
            self,
            token,
            normalized_kind,
            metadata,
            terminal_sensitive=terminal_sensitive,
        )
        with self._condition:
            self._require_current_locked(token)
            if (
                self._state != self.RUNNING
                or self._cancel_event.is_set()
                or self._finish_requested
                or self._worker_ident is None
            ):
                raise TurnCancelled(
                    self._cancel_reason or "turn was cancelled before operation start"
                )
            old_in_flight = self._in_flight_permits
            old_kind_count = self._permits_by_kind.get(normalized_kind, 0)
            try:
                # Register identity before publishing counts.  Roll every
                # field back if even a BaseException lands at this seam.
                self._active_permits[id(permit)] = (
                    permit,
                    token,
                    normalized_kind,
                )
                self._permits_by_kind[normalized_kind] = old_kind_count + 1
                self._in_flight_permits = old_in_flight + 1
                self._condition.notify_all()
            except BaseException:
                registered = self._active_permits.get(id(permit))
                if registered is not None and registered[0] is permit:
                    self._active_permits.pop(id(permit), None)
                self._in_flight_permits = old_in_flight
                if old_kind_count:
                    self._permits_by_kind[normalized_kind] = old_kind_count
                else:
                    self._permits_by_kind.pop(normalized_kind, None)
                self._condition.notify_all()
                raise
        return permit

    def _release_permit(
        self,
        permit: TurnPermit,
        token: TurnToken,
        kind: str,
    ) -> None:
        with self._condition:
            # A permit can only outlive its own current generation because a
            # new generation is forbidden until worker + permits quiesce.
            self._require_current_locked(token)
            registered = self._active_permits.get(id(permit))
            if (
                registered is None
                or registered[0] is not permit
                or registered[1] is not token
            ):
                raise TurnCancelled(
                    "turn permit is not registered with this generation"
                )
            registered_kind = registered[2]
            if self._in_flight_permits <= 0:
                raise RuntimeError("turn permit count underflow")
            old_in_flight = self._in_flight_permits
            old_kind_count = self._permits_by_kind.get(registered_kind, 0)
            try:
                self._active_permits.pop(id(permit))
                self._in_flight_permits = old_in_flight - 1
                remaining = old_kind_count - 1
                if remaining > 0:
                    self._permits_by_kind[registered_kind] = remaining
                else:
                    self._permits_by_kind.pop(registered_kind, None)
            except BaseException:
                self._active_permits[id(permit)] = registered
                self._in_flight_permits = old_in_flight
                if old_kind_count:
                    self._permits_by_kind[registered_kind] = old_kind_count
                else:
                    self._permits_by_kind.pop(registered_kind, None)
                self._condition.notify_all()
                raise
            self._reconcile_after_mutation_locked()

    def _permit_is_registered(self, permit: TurnPermit) -> bool:
        with self._lock:
            registered = self._active_permits.get(id(permit))
            return registered is not None and registered[0] is permit

    def _assert_active_permit(
        self,
        permit: TurnPermit,
        token: TurnToken,
        kind: str,
    ) -> None:
        """Verify a retained permit still belongs to this exact generation."""
        with self._condition:
            self._require_current_locked(token)
            registered = self._active_permits.get(id(permit))
            if (
                registered is None
                or registered[0] is not permit
                or registered[1] is not token
                or registered[2] != kind
            ):
                raise TurnCancelled(
                    "turn permit is not registered with this generation"
                )
            if self._state not in {self.RUNNING, self.CANCELLING}:
                raise TurnCancelled("turn is no longer active")
            if self._in_flight_permits <= 0:
                raise TurnCancelled("turn has no retained permits")
            if self._permits_by_kind.get(kind, 0) <= 0:
                raise TurnCancelled(
                    f"turn has no retained {kind!r} permit"
                )

    def finish_worker(self, token: TurnToken, *, terminal_status: str) -> dict[str, Any]:
        """Release worker ownership after local publication/persistence ends."""
        normalized_terminal_status = str(terminal_status or "error")
        with self._condition:
            self._require_current_locked(token)
            if not self._worker_active:
                raise TurnCancelled("turn worker already finished")
            if self._worker_ident is None:
                raise TurnBusy(
                    "admitted turn worker is not bound; use abandon_admission "
                    "only when Thread.start fails"
                )
            if self._worker_ident != threading.get_ident():
                raise TurnBusy(
                    "bound turn worker must finish itself "
                    f"(bound to thread {self._worker_ident})"
                )
            self._worker_active = False
            self._worker_ident = None
            self._finish_requested = True
            if not self._terminal_committed:
                self._terminal_status = normalized_terminal_status
            if self._in_flight_permits and self._state == self.RUNNING:
                # No operation may be admitted or published after the owning
                # worker exits.  Existing transferable permits may only drain.
                self._state = self.CANCELLING
                self._cancel_reason = "turn worker finished; draining permits"
                self._cancel_event.set()
            self._reconcile_after_mutation_locked()
            return self._snapshot_locked()

    def seal_terminal(
        self,
        token: TurnToken,
        *,
        terminal_status: str,
    ) -> dict[str, Any]:
        """Atomically linearize final result truth against Stop.

        The conversation worker calls this only after releasing every retained
        result permit. A Stop that already won leaves the fence cancelling and
        the returned snapshot says so. Otherwise the terminal seal wins and
        later cancellation cannot retroactively contradict the completed
        result while the outer actor finishes publishing it.
        """
        normalized_terminal_status = str(terminal_status or "error")
        with self._condition:
            self._require_current_locked(token)
            if not self._worker_active:
                raise TurnCancelled("turn worker already finished")
            if self._worker_ident != threading.get_ident():
                raise TurnBusy("bound turn worker must seal its own terminal")
            if self._state == self.CANCELLING or self._cancel_event.is_set():
                return self._snapshot_locked()
            terminal_sensitive_kinds = sorted(
                registered[2]
                for registered in self._active_permits.values()
                if registered[0].terminal_sensitive
            )
            if terminal_sensitive_kinds:
                raise TurnBusy(
                    "cannot seal terminal while terminal-sensitive permits "
                    f"are live: {', '.join(terminal_sensitive_kinds)}"
                )
            if self._state != self.RUNNING:
                raise TurnCancelled("turn is no longer running")
            self._finish_requested = True
            self._terminal_status = normalized_terminal_status
            self._terminal_committed = True
            self._condition.notify_all()
            return self._snapshot_locked()

    def abandon_admission(self, token: TurnToken, *, reason: str) -> dict[str, Any]:
        """Release a turn whose worker thread could not be started."""
        normalized_reason = str(reason or "worker did not start")
        with self._condition:
            self._require_current_locked(token)
            if not self._worker_active:
                raise TurnCancelled("turn worker already finished")
            if self._worker_ident is not None:
                raise TurnBusy("cannot abandon an already-bound turn worker")
            self._state = self.CANCELLING
            self._cancel_reason = normalized_reason
            self._cancel_event.set()
            self._worker_active = False
            self._finish_requested = True
            self._terminal_status = "error"
            self._reconcile_after_mutation_locked()
            return self._snapshot_locked()

    def can_publish(self, token: TurnToken) -> bool:
        """Whether non-terminal output may still escape this generation."""
        with self._lock:
            return (
                self._is_current_locked(token)
                and self._state == self.RUNNING
                and self._worker_active
                and not self._finish_requested
            )

    def can_persist(self, token: TurnToken) -> bool:
        """Whether agent-side transcript projection may still be written."""
        return self.can_publish(token)

    def can_finalize(self, token: TurnToken) -> bool:
        """Whether this worker may commit its exact terminal receipt.

        Cancellation suppresses ordinary deltas/history writes but the owning
        worker must still be able to atomically terminalize the accepted prompt
        as interrupted.  Stale generations and already-quiesced workers cannot.
        """
        with self._lock:
            return (
                self._is_current_locked(token)
                and self._worker_active
                and self._state in {self.RUNNING, self.CANCELLING}
            )

    def is_cancelled(self, token: TurnToken) -> bool:
        with self._lock:
            return (
                not self._is_current_locked(token)
                or self._state == self.CANCELLING
                or self._cancel_event.is_set()
            )

    def cancel_event(self, token: TurnToken) -> threading.Event:
        with self._lock:
            self._require_current_locked(token)
            return self._cancel_event

    def wait_quiesced(self, timeout: float | None = None) -> bool:
        """Wait for actor-wide quiescence of the currently visible turn."""
        return self._quiesced.wait(timeout=timeout)

    def wait_generation_quiesced(
        self,
        token: TurnToken,
        timeout: float | None = None,
    ) -> bool:
        """Wait only for the exact admitted generation represented by token."""
        with self._condition:
            if token._fence_identity is not self._identity:
                raise TurnCancelled("turn token belongs to another fence")
            if token.generation <= 0 or token.generation > self._generation:
                raise TurnCancelled("unknown turn generation")
            return self._condition.wait_for(
                lambda: self._last_quiesced_generation >= token.generation,
                timeout=timeout,
            )

    def current_token(self) -> TurnToken | None:
        with self._lock:
            return self._token

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _is_current_locked(self, token: TurnToken) -> bool:
        return self._token is token and token.generation == self._generation

    def _require_current_locked(self, token: TurnToken) -> None:
        if not self._is_current_locked(token):
            raise TurnCancelled("stale turn generation")

    def _settle_if_quiescent_locked(self) -> None:
        if (
            self._finish_requested
            and not self._worker_active
            and self._in_flight_permits == 0
        ):
            if self._token is not None:
                self._last_quiesced_generation = max(
                    self._last_quiesced_generation,
                    self._token.generation,
                )
            self._state = self.CLOSED if self._close_requested else self.IDLE
            self._quiesced.set()

    def _reconcile_after_mutation_locked(self) -> None:
        """Settle/notify even when a one-shot BaseException hits cleanup."""
        first_error: BaseException | None = None
        try:
            self._settle_if_quiescent_locked()
        except BaseException as exc:
            first_error = exc
            # A fault injected after ownership/count mutation must not leave
            # the actor permanently non-quiescent. Retry reconciliation once;
            # the original error is still surfaced after state is safe.
            self._settle_if_quiescent_locked()
        finally:
            self._condition.notify_all()
        if first_error is not None:
            raise first_error

    def _snapshot_locked(self) -> dict[str, Any]:
        token = self._token
        return {
            "generation": self._generation,
            "last_quiesced_generation": self._last_quiesced_generation,
            "prompt_id": token.prompt_id if token is not None else "",
            "owner_id": token.owner_id if token is not None else "",
            "state": self._state,
            "cancelled": self._cancel_event.is_set(),
            "cancel_reason": self._cancel_reason,
            "close_requested": self._close_requested,
            "worker_active": self._worker_active,
            "worker_ident": self._worker_ident,
            "in_flight_permits": self._in_flight_permits,
            "permits_by_kind": dict(self._permits_by_kind),
            "terminal_status": self._terminal_status,
            "terminal_committed": self._terminal_committed,
            "quiesced": self._quiesced.is_set(),
        }


_CURRENT_TURN: contextvars.ContextVar[
    tuple[TurnFence, TurnToken] | None
] = contextvars.ContextVar("elevate_current_turn_fence", default=None)
class _OwnedPermitRegistry:
    """Thread-safe cleanup registry for permits owned by one binding.

    ``contextvars.copy_context`` copies object references, not object state.  A
    plain list here was therefore shared by the conversation worker and raw
    provider workers without synchronization.  More importantly, binding
    cleanup could release a permit after it had been transferred to a raw
    worker.  This registry gives transfer and cleanup one lock-linearized
    detach/drain boundary.
    """

    __slots__ = ("_lock", "_permits", "_closed")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._permits: dict[int, TurnPermit] = {}
        self._closed = False

    def add(self, permit: TurnPermit) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._permits[id(permit)] = permit
            return True

    def detach(self, permit: TurnPermit) -> bool:
        """Transfer cleanup ownership away from this binding exactly once."""
        with self._lock:
            if self._permits.get(id(permit)) is not permit:
                return False
            self._permits.pop(id(permit))
            return True

    def contains(self, permit: TurnPermit) -> bool:
        with self._lock:
            return self._permits.get(id(permit)) is permit

    def close_and_snapshot(self) -> list[TurnPermit]:
        """Atomically close and claim every still-owned permit."""
        with self._lock:
            permits = list(self._permits.values())
            self._permits.clear()
            self._closed = True
            return permits


_CURRENT_OWNED_PERMITS: contextvars.ContextVar[
    _OwnedPermitRegistry | None
] = contextvars.ContextVar("elevate_current_turn_owned_permits", default=None)


@contextlib.contextmanager
def bind_turn_fence(
    fence: TurnFence | None,
    token: TurnToken | None,
) -> Iterator[None]:
    """Bind a gateway turn to this execution context.

    Passing ``None`` preserves the behavior of CLI, cron, tests, and other
    non-gateway callers.
    """
    if fence is None or token is None:
        yield
        return
    context_token = _CURRENT_TURN.set((fence, token))
    owned_permits = _OwnedPermitRegistry()
    owned_token = _CURRENT_OWNED_PERMITS.set(owned_permits)
    try:
        yield
    finally:
        # Transferred result permits normally release inside run_conversation.
        # This binding-level cleanup is the BaseException backstop: an
        # unexpected escape cannot wedge the actor after the gateway leaves
        # the exact generation context. Permits are idempotent, so already-
        # released normal paths are safe to revisit here.
        try:
            first_error: BaseException | None = None
            failed_permits: list[TurnPermit] = []
            for permit in owned_permits.close_and_snapshot():
                try:
                    permit.release()
                except BaseException as exc:
                    failed_permits.append(permit)
                    if first_error is None:
                        first_error = exc
            # Retry every failed one after attempting the full set. This
            # heals one-shot cleanup faults. A persistent double-fault remains
            # fail-closed (active permit/count, no false quiescence) and is
            # surfaced; exact recovery belongs to a higher-level supervisor.
            for permit in failed_permits:
                try:
                    permit.release()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
            if first_error is not None:
                raise first_error
        finally:
            _CURRENT_OWNED_PERMITS.reset(owned_token)
            _CURRENT_TURN.reset(context_token)


def current_turn_binding() -> tuple[TurnFence, TurnToken] | None:
    return _CURRENT_TURN.get()


def acquire_current_turn_permit(
    kind: str,
    metadata: Mapping[str, Any] | None = None,
) -> TurnPermit | _NoopPermit:
    binding = _CURRENT_TURN.get()
    if binding is None:
        return _NoopPermit()
    fence, token = binding
    return fence.acquire_permit(token, kind, metadata)


def acquire_current_turn_background_permit(
    kind: str,
    metadata: Mapping[str, Any] | None = None,
) -> TurnPermit | _NoopPermit:
    """Acquire one explicitly allowlisted background permit for this turn."""
    binding = _CURRENT_TURN.get()
    if binding is None:
        return _NoopPermit()
    fence, token = binding
    return fence.acquire_background_permit(token, kind, metadata)


def acquire_owned_current_turn_permit(
    kind: str,
    metadata: Mapping[str, Any] | None = None,
) -> TurnPermit | _NoopPermit:
    """Acquire a transferable permit with binding-exit failure cleanup."""
    permit = acquire_current_turn_permit(kind, metadata)
    owned_permits = _CURRENT_OWNED_PERMITS.get()
    if owned_permits is not None and isinstance(permit, TurnPermit):
        try:
            registered = owned_permits.add(permit)
        except BaseException as exc:
            try:
                permit.release()
            except BaseException as cleanup_exc:
                raise exc from cleanup_exc
            raise
        if not registered:
            permit.release()
            raise TurnCancelled("turn binding already finished")
    return permit


def detach_owned_current_turn_permit(
    permit: TurnPermit | _NoopPermit | None,
) -> bool:
    """Detach an exact permit after successful ownership transfer.

    Raw provider/tool workers call this only after ``Thread.start`` succeeds.
    Once detached, binding-exit cleanup cannot release the permit; the
    receiving worker must release it in its own ``finally`` path.
    """
    owned_permits = _CURRENT_OWNED_PERMITS.get()
    if owned_permits is None or not isinstance(permit, TurnPermit):
        return False
    return owned_permits.detach(permit)


def reattach_owned_current_turn_permit(
    permit: TurnPermit | _NoopPermit | None,
) -> bool:
    """Restore the binding cleanup backstop after a failed pre-start handoff."""
    owned_permits = _CURRENT_OWNED_PERMITS.get()
    if owned_permits is None or not isinstance(permit, TurnPermit):
        return False
    return owned_permits.add(permit)


def release_attached_owned_current_turn_permit(
    permit: TurnPermit | _NoopPermit | None,
) -> bool:
    """Release only when the current binding still owns the permit.

    A false return means cleanup ownership was already transferred to a child
    worker.  Callers must not release in that case even if their polling frame
    has returned.
    """
    if permit is None:
        return False
    owned_permits = _CURRENT_OWNED_PERMITS.get()
    if isinstance(permit, TurnPermit):
        if owned_permits is None or not owned_permits.contains(permit):
            return False
        # Release while the binding still owns the cleanup backstop.  If a
        # BaseException escapes, bind_turn_fence's drain can retry it.  Only a
        # successful (or concurrently idempotent) release is detached.
        permit.release()
        owned_permits.detach(permit)
        return True
    permit.release()
    return True


def current_turn_cancelled() -> bool:
    binding = _CURRENT_TURN.get()
    if binding is None:
        return False
    fence, token = binding
    return fence.is_cancelled(token)


def seal_current_turn_terminal(terminal_status: str) -> dict[str, Any]:
    """Seal final truth for the bound generation after all permits drain."""
    binding = _CURRENT_TURN.get()
    if binding is None:
        return {
            "cancelled": False,
            "terminal_committed": True,
            "terminal_status": str(terminal_status or "error"),
        }
    fence, token = binding
    return fence.seal_terminal(
        token,
        terminal_status=terminal_status,
    )


def current_turn_publish_allowed() -> bool:
    binding = _CURRENT_TURN.get()
    if binding is None:
        return True
    fence, token = binding
    return fence.can_publish(token)


def current_turn_persist_allowed() -> bool:
    binding = _CURRENT_TURN.get()
    if binding is None:
        return True
    fence, token = binding
    return fence.can_persist(token)
