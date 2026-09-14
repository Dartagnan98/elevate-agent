from __future__ import annotations

import threading
import time


_SESSION_DB_SINGLETON = None
_SESSION_DB_SINGLETON_LOCK = threading.Lock()


class _SharedSessionDB:
    """Per-request handle over the process-wide SessionDB."""

    __slots__ = ("_db",)

    def __init__(self, db):
        object.__setattr__(self, "_db", db)

    def close(self):  # shared instance lives for the process; do not close
        return None

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_db"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_db"), name, value)


def _get_session_db():
    """Return a handle over the process-wide shared SessionDB."""
    global _SESSION_DB_SINGLETON
    from elevate_state import SessionDB
    import elevate_state as _es

    target_path = _es.DEFAULT_DB_PATH
    db = _SESSION_DB_SINGLETON
    if db is None or getattr(db, "db_path", None) != target_path:
        with _SESSION_DB_SINGLETON_LOCK:
            db = _SESSION_DB_SINGLETON
            if db is None or getattr(db, "db_path", None) != target_path:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                _SESSION_DB_SINGLETON = SessionDB()
            db = _SESSION_DB_SINGLETON
    return _SharedSessionDB(db)


_FS_SCAN_CACHE: dict = {}
_FS_SCAN_CACHE_LOCK = threading.Lock()


def _account_key_safe() -> str:
    try:
        from elevate_constants import get_account_key

        return get_account_key()
    except Exception:
        return "_default"


def _fs_cache_get(name: str):
    """Return cached value for (current account, name) if still fresh, else None."""
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        ent = _FS_SCAN_CACHE.get(key)
        if ent is not None and ent[0] > time.monotonic():
            return ent[1]
    return None


def _fs_cache_put(name: str, value, ttl_seconds: float) -> None:
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        _FS_SCAN_CACHE[key] = (time.monotonic() + ttl_seconds, value)


def _fs_cache_invalidate(name: str) -> None:
    """Drop the current account's cached entry for ``name``."""
    key = (_account_key_safe(), name)
    with _FS_SCAN_CACHE_LOCK:
        _FS_SCAN_CACHE.pop(key, None)
