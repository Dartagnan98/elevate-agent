"""Local database bootstrap for Elevate installs."""

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
    """Create and migrate the local stores used by a base install.

    The operational store is embedded Postgres and applies its numbered
    migrations on first connect. The session and memory stores create their
    own schemas from their
    constructors. This function makes that first-touch explicit for installers,
    doctors, and production smoke checks.
    """

    results: list[LocalDatabaseInitResult] = []

    try:
        from elevate_cli.data.connection import connect
        from elevate_cli.data.pg_server import pg_data_dir

        path = pg_data_dir()
        with connect() as conn:
            # Make a fresh install usable before any dashboard page is opened.
            # The migrations create the tables; these idempotent calls seed the
            # default Admin actions, setup rows, pack onboarding rows, and any
            # local province guide material already present in ELEVATE_HOME.
            from elevate_cli.data.admin_setup import get_admin_setup
            from elevate_cli.data.dispatch import ensure_default_admin_actions
            from elevate_cli.data.pack_onboarding import get_pack_onboarding
            from elevate_cli.data.province_guides import import_exp_agent_centre

            ensure_default_admin_actions(conn)
            get_admin_setup(conn)
            get_pack_onboarding(conn)
            import_exp_agent_centre(conn)
            applied = conn.execute("SELECT COUNT(*) FROM _schema_migrations").fetchone()
            admin_actions = conn.execute("SELECT COUNT(*) FROM admin_action_registry").fetchone()
            pack_items = conn.execute("SELECT COUNT(*) FROM pack_onboarding_items").fetchone()
        count = int(applied[0] if applied else 0)
        action_count = int(admin_actions[0] if admin_actions else 0)
        pack_item_count = int(pack_items[0] if pack_items else 0)
        results.append(
            _ok(
                "operational",
                path,
                f"{count} schema migrations applied; {action_count} admin actions; {pack_item_count} onboarding items",
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced in installer output
        try:
            from elevate_cli.data.pg_server import pg_data_dir

            path = pg_data_dir()
        except Exception:
            path = Path("~/.elevate/pgdata").expanduser()
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

    try:
        from elevate_cli import outreach_db
        from elevate_cli.data.pg_server import pg_data_dir

        seeded = outreach_db.seed_all_templates()
        path = pg_data_dir()
        inserted = len(seeded.get("inserted", []))
        skipped = len(seeded.get("skipped", []))
        results.append(_ok("outreach", path, f"{inserted} templates inserted; {skipped} already present"))
    except Exception as exc:  # pragma: no cover - surfaced in installer output
        try:
            from elevate_cli.data.pg_server import pg_data_dir

            path = pg_data_dir()
        except Exception:
            path = Path("~/.elevate/pgdata").expanduser()
        results.append(_fail("outreach", path, exc))

    # Register the recurring connector-sync launchd jobs so a fresh install
    # starts pulling apple-messages / crm / social on its own schedule. Same
    # ELEVATE_HOME used for the operational DB above is baked into the plists,
    # so multiple profiles / installs don't trample each other. Idempotent —
    # re-running ``elevate db init`` refreshes the plists in place.
    try:
        from elevate_cli import sync_scheduler as _ss

        scheduler_results = _ss.install_all()
        ok_count = sum(1 for r in scheduler_results if r.ok and r.action in ("installed", "refreshed"))
        skip_count = sum(1 for r in scheduler_results if r.ok and r.action == "skipped")
        fail_count = sum(1 for r in scheduler_results if not r.ok)
        unsupp_count = sum(1 for r in scheduler_results if r.action == "unsupported")
        plist_dir = Path("~/Library/LaunchAgents").expanduser()
        if unsupp_count and not ok_count:
            results.append(_ok("sync-scheduler", plist_dir, "skipped — not macOS"))
        elif fail_count:
            errs = "; ".join(f"{r.job.source_id}: {r.message}" for r in scheduler_results if not r.ok)
            results.append(LocalDatabaseInitResult(
                name="sync-scheduler", path=plist_dir, ok=False, message=errs,
            ))
        else:
            results.append(_ok(
                "sync-scheduler", plist_dir,
                f"{ok_count} installed/refreshed; {skip_count} already current",
            ))
    except Exception as exc:  # pragma: no cover - surfaced in installer output
        plist_dir = Path("~/Library/LaunchAgents").expanduser()
        results.append(_fail("sync-scheduler", plist_dir, exc))

    return results


def print_database_init_results(
    results: Iterable[LocalDatabaseInitResult], *, quiet: bool = False
) -> int:
    failures = [result for result in results if not result.ok]
    if quiet:
        return 1 if failures else 0

    print("Elevate local databases")
    for result in results:
        marker = "ok" if result.ok else "failed"
        print(f"- {result.name}: {marker} - {result.path}")
        if result.message:
            print(f"  {result.message}")
    return 1 if failures else 0


def find_sqlite_backups(root: Path | None = None) -> list[Path]:
    """Locate the SQLite snapshot files left behind by the PG migration.

    Two patterns are produced by the migration scripts:

    * ``<name>.pre-pg-migration`` / ``<name>.pre-pg-aux-migration`` —
      snapshots taken immediately before the legacy SQLite → PG copy.
    * ``state.db.bak-pre-ghost-cleanup-<ts>`` — a dated snapshot of
      ``state.db`` taken before the SessionDB ghost-row cleanup.

    We never touch live ``.db`` / ``.sqlite`` files or their WAL/SHM
    siblings — only the explicitly named backup variants.
    """
    if root is None:
        root = Path.home() / ".elevate"
    if not root.exists():
        return []

    patterns = (
        "*.pre-pg-migration",
        "*.pre-pg-aux-migration",
        "state.db.bak-*",
    )
    found: list[Path] = []
    for pat in patterns:
        # ~/.elevate top-level
        found.extend(sorted(root.glob(pat)))
        # ~/.elevate/data subdir (operational store lives here)
        data_dir = root / "data"
        if data_dir.exists():
            found.extend(sorted(data_dir.glob(pat)))
    # Dedupe while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in found:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def purge_sqlite_backups(
    root: Path | None = None, *, dry_run: bool = True, quiet: bool = False
) -> int:
    """Delete the SQLite snapshots left by the PG migration.

    Defaults to dry-run to make this safe to wire into doctors and
    runbooks; the caller must pass ``dry_run=False`` to actually remove
    files. Returns 0 on success (or no-op), 1 if any deletion failed.
    """
    backups = find_sqlite_backups(root)
    if not backups:
        if not quiet:
            print("No SQLite migration backup files found.")
        return 0

    total_bytes = 0
    failures: list[tuple[Path, Exception]] = []
    for p in backups:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        total_bytes += size
        if not quiet:
            print(f"  {'would remove' if dry_run else 'removing'}: {p} ({size:,} bytes)")
        if dry_run:
            continue
        try:
            p.unlink()
        except OSError as exc:
            failures.append((p, exc))

    if not quiet:
        verb = "would free" if dry_run else "freed"
        print(f"{verb} ~{total_bytes / 1_000_000:.1f} MB across {len(backups)} file(s).")
        if dry_run:
            print("Pass --confirm to actually delete.")
    return 1 if failures else 0


def cmd_db(args) -> int:
    action = getattr(args, "db_action", "init")
    if action == "purge-sqlite-backup":
        return purge_sqlite_backups(
            dry_run=not getattr(args, "confirm", False),
            quiet=getattr(args, "quiet", False),
        )
    if action != "init":
        raise SystemExit(f"Unknown db action: {action}")
    results = initialize_local_databases(include_memory=not getattr(args, "no_memory", False))
    return print_database_init_results(results, quiet=getattr(args, "quiet", False))
