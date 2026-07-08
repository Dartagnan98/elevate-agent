"""A2 regression — FactRetriever reads must hold the store lock.

The retriever runs on a background prefetch daemon thread sharing one
autocommit=False connection with main-thread writes. If reads bypass
``store._lock`` they collide with a concurrent write ("another operation is in
progress") and their error-path rollback aborts the writer's uncommitted
transaction — silent memory loss. This asserts the invariant directly (a
retriever read acquires the lock) plus a concurrent-access no-crash smoke.
"""
from __future__ import annotations

import threading

from plugins.memory.holographic import HolographicMemoryProvider


def _provider(tmp_path):
    provider = HolographicMemoryProvider(config={
        "db_path": str(tmp_path / "memory.db"),
        "embedding_enabled": "false",
        "turn_journal_enabled": "false",
        "organize_on_session_end": "false",
        "organize_every_n_turns": "0",
    })
    provider.initialize("session-lock-test")
    return provider


class _CountingLock:
    """Delegates to a real RLock but counts every acquisition."""

    def __init__(self, inner):
        self._inner = inner
        self.enters = 0

    def __enter__(self):
        self.enters += 1
        return self._inner.__enter__()

    def __exit__(self, *a):
        return self._inner.__exit__(*a)

    def acquire(self, *a, **k):
        self.enters += 1
        return self._inner.acquire(*a, **k)

    def release(self):
        return self._inner.release()


def test_retriever_read_holds_store_lock(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    retriever = provider._retriever
    store.add_fact("Client Jane budget is 500000", category="client", explicit=True)

    counting = _CountingLock(store._lock)
    store._lock = counting
    counting.enters = 0

    # _fts_candidates does NOT call record_retrieval_events, so every lock
    # acquisition observed here comes from the read helper itself. Pre-fix this
    # read went straight to store._conn and would count zero.
    retriever._fts_candidates("Jane budget", None, 0.0, 10)

    assert counting.enters >= 1, "FactRetriever read did not acquire store._lock"


def test_concurrent_reads_and_writes_do_not_crash(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    retriever = provider._retriever
    for i in range(5):
        store.add_fact(f"seed fact {i} about client budgets", category="client", explicit=True)

    errors: list[Exception] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                retriever.search("budget", limit=5)
            except Exception as exc:  # noqa: BLE001 - the whole point is to catch a collision
                errors.append(exc)
                return

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(20):
            store.add_fact(f"concurrent fact {i} about new listings", category="client", explicit=True)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)

    # The real regression signal: concurrent reads never collided with a write
    # ("another operation in progress") nor raised — pre-fix this was the crash.
    assert not errors, f"concurrent read/write raised: {errors[:3]}"
    # Store is intact and readable (near-duplicate content merges, so the exact
    # count is not asserted — see finding C3; the point is it wasn't wiped).
    total = store._read_all("SELECT COUNT(*) AS n FROM facts")[0]["n"]
    assert total >= 1, f"store lost all facts, got {total}"
