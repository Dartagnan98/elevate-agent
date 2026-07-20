#!/usr/bin/env python3
"""Process-state companion bindings for agent-owned registry dispatch.

The atomic registry boundary (``registry.prepare_shadow`` /
``execute_prepared_shadow``) freezes tool *data* — canonical JSON arguments
and a small JSON-only handler-kwargs snapshot.  Some agent-owned tools also
need live *process state* that can never ride in that snapshot: clarify's
platform UI callback, the active ``MemoryManager`` instance.  Smuggling such
objects through dispatch kwargs is rejected by canonicalization on purpose;
this module is the one supported channel instead.

Contract (the "companion pattern" from the ERB-406 A2a adapter):

* One module-level :class:`DispatchCompanion` per piece of process state,
  owned by the tool's module.  The registered handler is the only consumer
  and must resolve :meth:`DispatchCompanion.get` eagerly at handler start —
  never store the companion for lazy reads (a generator or callback that
  reads it after dispatch returns observes ``None`` or, worse on a shared
  thread, a later dispatch's binding).
* Bindings are scoped to exactly one dispatch: the caller passes
  ``companion.bound(value)`` through
  ``model_tools.dispatch_agent_owned_registry_tool(..., companions=...)``
  (or an equivalent ``with`` block around exactly one dispatch call).
* Cleared on every exit path.  The unbind runs in a ``finally`` block, so
  ordinary returns, handler error payloads, raised exceptions, and
  ``BaseException`` control flow (``asyncio.CancelledError``,
  ``KeyboardInterrupt``) all restore the previous value.
* Thread and task isolation come from :mod:`contextvars` semantics: a new
  thread starts with an empty context, and an ``asyncio`` task snapshots its
  context at creation, so a binding made in one thread/task is invisible to
  every other thread/task unless the caller explicitly propagates a copied
  context (the concurrent agent loop's ``contextvars.copy_context()`` +
  ``Context.run`` worker pattern).
* **Generation-stamped liveness (A3 hardening of the two A2a P3 residuals).**
  Copied contexts outlive the dispatch that created them: ``_run_async``'s
  running-loop branch abandons its worker thread on timeout
  (``ELEVATE_ASYNC_TOOL_TIMEOUT_S``, default 300 s) while the coroutine
  keeps running inside a ``copy_context()`` snapshot that still *contains*
  the binding.  Every binding therefore carries a per-companion generation
  that is retired in the same ``finally`` that unbinds it, and
  :meth:`get` validates the generation against the live set before
  returning the value.  A dead/abandoned task holding a stale context
  snapshot structurally cannot validate a retired generation: it observes
  ``None`` exactly as if it were outside any binding, and the handler's
  typed "not available" path takes over.  This converts the
  abandoned-async-task stale-binding residual and the timeout-bounded
  companion lifetime from timing accidents into impossibilities.
* Re-entrancy is DEFINED AS SUPPORTED via stacked tokens: a handler that
  performs a nested dispatch may rebind the same companion; the inner
  binding wins for the inner dispatch and the outer value is restored when
  the inner dispatch exits (strict LIFO).  Non-LIFO unbinds — exiting a
  binding in a different ``contextvars`` context than the one that entered
  it — are a hygiene violation and raise :class:`CompanionBindingError`
  instead of silently leaking the stale binding (the generation is retired
  FIRST, so even that error path leaves nothing readable behind).
"""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import threading
from typing import Any, Iterator, Optional, Tuple


class CompanionBindingError(RuntimeError):
    """A companion binding could not be unbound in the entering context.

    Raised when ``bound()``'s exit runs in a different ``contextvars``
    context than its enter (for example a binding smuggled across
    ``Context.run`` boundaries or non-LIFO manual token juggling).  The
    original context would silently keep the stale binding token, so this
    fails loudly instead — and because the binding's generation is retired
    before the reset attempt, the leftover token can never resolve to the
    bound value again.
    """


class DispatchCompanion:
    """One piece of dispatch-scoped process state behind a context variable."""

    __slots__ = ("_name", "_var", "_generations", "_live", "_live_lock")

    def __init__(self, name: str):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("companion name is required")
        self._name = name.strip()
        self._var: contextvars.ContextVar[
            Optional[Tuple[int, Optional[Any]]]
        ] = contextvars.ContextVar(self._name, default=None)
        # Monotonic per-companion binding generations plus the set of
        # generations that are currently live.  ``get()`` refuses to resolve
        # a binding whose generation was retired, no matter which context
        # snapshot is asking.
        self._generations = itertools.count(1)
        self._live: set[int] = set()
        self._live_lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def get(self) -> Optional[Any]:
        """Return the currently bound live value, or ``None`` otherwise.

        Registered handlers must call this eagerly at handler start.  A
        ``None`` result means the handler was reached outside the routed
        dispatch boundary (legacy dispatch without an agent, plugin dispatch,
        hallucinated calls) — or from a stale context snapshot whose dispatch
        already exited (an abandoned ``_run_async`` worker past its timeout).
        Either way the handler must return its typed "not available" error
        rather than guessing at ambient state.
        """
        binding = self._var.get()
        if binding is None:
            return None
        generation, value = binding
        with self._live_lock:
            if generation not in self._live:
                return None
        return value

    @contextlib.contextmanager
    def bound(self, value: Optional[Any]) -> Iterator[Optional[Any]]:
        """Bind *value* for exactly one dispatch in the current context."""
        generation = next(self._generations)
        with self._live_lock:
            self._live.add(generation)
        token = self._var.set((generation, value))
        try:
            yield value
        finally:
            # Retire the generation BEFORE the contextvar reset: from this
            # point no context snapshot — including one held by an abandoned
            # worker thread — can resolve this binding, even if the reset
            # below fails with CompanionBindingError.
            with self._live_lock:
                self._live.discard(generation)
            try:
                self._var.reset(token)
            except ValueError as exc:
                raise CompanionBindingError(
                    f"companion '{self._name}' was unbound in a different "
                    "context than the one that bound it; the entering "
                    "context still holds a stale binding"
                ) from exc
