"""Local SQLite database bootstrap for Elevate installs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LocalDatabaseInitResult:
    name: str
    path: Path
    ok: bool
    message: str


def _ok(name: str, path: Path, message: str) -> LocalDatabaseInitResult:
    return LocalDatabaseInitResult(name=name, path=path, ok=True, message=message)


def _fail(name: str, path: Path, error: Exception) -> LocalDatabaseInitResult:
    return LocalDatabaseInitResult(name=name, path=path, ok=False, message=str(error))


def initialize_local_databases(*, include_memory: bool = True) -> list[LocalDatabaseInitResult]:
    """Create and migrate the local SQLite stores used by a base install.

    The operational store applies its numbered migrations on first connect.
    The session and memory stores create their own schemas from their
    constructors. This function makes that first-touch explicit for installers,
    doctors, and production smoke checks.
    """

    results: list[LocalDatabaseInitResult] = []

    try:
        from elevate_cli.data.connection import connect
        from elevate_cli.data.paths import operational_db_path

        path = operational_db_path()
        with connect() as conn:
            applied = conn.execute("SELECT COUNT(*) FROM _schema_migrations").fetchone()
        count = int(applied[0] if applied else 0)
        results.append(_ok("operational", path, f"{count} schema migrations applied"))
    except Exception as exc:  # pragma: no cover - surfaced in installer output
        try:
            from elevate_cli.data.paths import operational_db_path

            path = operational_db_path()
        except Exception:
            path = Path("~/.elevate/data/operational.db").expanduser()
        results.append(_fail("operational", path, exc))

    try:
        from elevate_state import SessionDB

        db = SessionDB()
        path = Path(db.db_path)
        db.close()
        results.append(_ok("sessions", path, "session store ready"))
    except Exception as exc:  # pragma: no cover - surfaced in installer output
        try:
            from elevate_state import DEFAULT_DB_PATH

            path = Path(DEFAULT_DB_PATH)
        except Exception:
            path = Path("~/.elevate/state.db").expanduser()
        results.append(_fail("sessions", path, exc))

    if include_memory:
        try:
            from plugins.memory.holographic.store import MemoryStore

            store = MemoryStore()
            path = Path(store.db_path)
            store.close()
            results.append(_ok("memory", path, "memory store ready"))
        except Exception as exc:  # pragma: no cover - surfaced in installer output
            try:
                from elevate_constants import get_elevate_home

                path = get_elevate_home() / "memory_store.db"
            except Exception:
                path = Path("~/.elevate/memory_store.db").expanduser()
            results.append(_fail("memory", path, exc))

    return results


def print_database_init_results(
    results: Iterable[LocalDatabaseInitResult], *, quiet: bool = False
) -> int:
    failures = [result for result in results if not result.ok]
    if quiet:
        return 1 if failures else 0

    print("Elevate local SQLite databases")
    for result in results:
        marker = "ok" if result.ok else "failed"
        print(f"- {result.name}: {marker} - {result.path}")
        if result.message:
            print(f"  {result.message}")
    return 1 if failures else 0


def cmd_db(args) -> int:
    action = getattr(args, "db_action", "init")
    if action != "init":
        raise SystemExit(f"Unknown db action: {action}")
    results = initialize_local_databases(include_memory=not getattr(args, "no_memory", False))
    return print_database_init_results(results, quiet=getattr(args, "quiet", False))
