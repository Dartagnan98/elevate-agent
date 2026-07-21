"""Repair tool — restore iMessage bodies lost to the ``attributedBody`` gap.

Background
----------
``source_connector_modules/apple_messages.py`` used to read message text only
from ``chat.db``'s legacy ``message.text`` column. On macOS Ventura and newer
that column is NULL for the overwhelming majority of messages — the body lives
in the ``attributedBody`` typedstream blob. Every affected message was
therefore ingested with ``payload_json = {"body": ""}``.

This tool re-reads ``chat.db`` (strictly read-only), decodes ``attributedBody``,
and repairs the existing ``events`` rows **in place**.

Why in-place and not a re-ingest
--------------------------------
``event_hash = sha256(source_id|thread_key|ts|sha256(body))`` — the body is part
of the row's identity. Re-running the connector after the decoder fix would
compute *different* hashes for the same messages and insert ~205k duplicates
instead of deduplicating. So this tool:

* matches an existing event by recomputing the hash it was *given* at ingest
  time (body ``""``), which is exact and index-backed; and
* rewrites both ``payload_json`` **and** ``event_hash`` to the values the row
  *should* have had.

That second part is what makes the next live sync a no-op: the connector will
compute exactly the repaired hash, hit ``uniq_events_event_hash``, and skip.

**Run this backfill before shipping the decoder fix**, or the first sync after
the fix will duplicate the affected history.

Safety
------
* ``chat.db`` is opened ``mode=ro``; this tool never writes to it.
* Dry-run is the default. ``--apply`` is required to write.
* ``--apply`` takes a full ``pg_dump`` backup first and refuses to continue if
  the dump is missing or empty.
* Every update is guarded by ``body = ''``, so the tool is idempotent and
  safely resumable — interrupt it and re-run, already-repaired rows are skipped.

Usage::

    # 1. see what would change (writes nothing)
    python -m elevate_cli.apple_messages_body_backfill

    # 2. canary: repair 200 rows, then eyeball the app
    python -m elevate_cli.apple_messages_body_backfill --apply --limit 200

    # 3. full run
    python -m elevate_cli.apple_messages_body_backfill --apply

    # 4. confirm
    python -m elevate_cli.apple_messages_body_backfill --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
SOURCE_ID = "apple-messages"
CHANNEL = "imessage"
DEFAULT_BATCH = 2000


# ─── helpers mirrored from the ingest path (kept byte-identical) ────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_event_hash(*, source_id: str, thread_key: str | None, ts: str, body: str | None) -> str:
    """Same formula as ``elevate_cli.data._util.compute_event_hash``."""
    return _sha256(f"{source_id}|{thread_key or ''}|{ts}|{_sha256(body or '')}")


def _apple_dt(raw_value: Any) -> datetime | None:
    """Same conversion as ``apple_messages._apple_dt``."""
    try:
        value = int(raw_value)
    except Exception:
        return None
    if value <= 0:
        return None
    seconds = value / 1_000_000_000 if value > 10_000_000_000 else value
    return APPLE_EPOCH + timedelta(seconds=seconds)


def _chat_db_path() -> Path:
    override = os.getenv("ELEVATE_APPLE_MESSAGES_CHAT_DB", "").strip()
    if override:
        return Path(os.path.expandvars(override)).expanduser()
    return Path.home() / "Library" / "Messages" / "chat.db"


def _sqlite_ro_uri(path: Path) -> str:
    return "file:" + urllib.parse.quote(str(path)) + "?mode=ro"


# ─── chat.db side: build hash -> recovered text ─────────────────────────


def build_recovery_map(chat_db: Path, *, verbose: bool = True) -> dict[str, str]:
    """Map ``event_hash(body="")`` -> decoded text, for every repairable message.

    Mirrors the connector's row loop exactly so the reconstructed identity
    matches what was originally written.
    """
    from elevate_cli.source_connector_modules.apple_typedstream import (
        decode_attributed_body,
    )

    conn = sqlite3.connect(_sqlite_ro_uri(chat_db), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT m.date AS message_date,
               m.text AS message_text,
               m.attributedBody AS message_attributed_body,
               h.id AS handle_id,
               c.ROWID AS chat_rowid
        FROM message m
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN chat c ON c.ROWID = cmj.chat_id
        WHERE m.date IS NOT NULL
        ORDER BY m.date ASC, m.ROWID ASC
    """
    recovered: dict[str, str] = {}
    scanned = 0
    try:
        for row in conn.execute(query):
            scanned += 1
            if str(row["message_text"] or "").strip():
                continue  # this one already ingested fine
            dt = _apple_dt(row["message_date"])
            if not dt:
                continue
            text = decode_attributed_body(row["message_attributed_body"]).strip()
            if not text:
                continue
            handle = str(row["handle_id"] or "").strip()
            chat_rowid = row["chat_rowid"]
            thread_key = (
                f"apple-chat:{chat_rowid}"
                if chat_rowid is not None
                else f"apple-handle:{handle or 'unknown'}"
            )
            key = compute_event_hash(
                source_id=SOURCE_ID, thread_key=thread_key, ts=dt.isoformat(), body=""
            )
            recovered[key] = text
    finally:
        conn.close()
    if verbose:
        print(f"  chat.db rows scanned          : {scanned:,}")
        print(f"  repairable messages decoded   : {len(recovered):,}")
    return recovered


# ─── postgres side ─────────────────────────────────────────────────────


def _database_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    from elevate_constants import get_account_key

    return f"elevate_op_{get_account_key()}"


def _connect(dbname: str, *, autocommit: bool = False):
    import psycopg
    from elevate_cli.data import pg_server

    return psycopg.connect(pg_server.get_uri(dbname), autocommit=autocommit)


EMPTY_BODY_PREDICATE = (
    "COALESCE(NULLIF(TRIM(payload_json::jsonb->>'body'), ''), '') = ''"
)


def count_broken(conn, *, channel: str = CHANNEL) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM events WHERE channel=%s AND {EMPTY_BODY_PREDICATE}",
        (channel,),
    ).fetchone()[0]


def _fetch_page(conn, *, channel: str, after_ts: str | None, after_id: str | None, size: int):
    """Keyset page of empty-body events, ordered by ``(ts, id)``.

    Keyset (not OFFSET, not "re-query the shrinking set") guarantees strict
    forward progress even when a page contains rows we cannot repair, so the
    loop can never stall on unmatched messages.
    """
    sql = (
        "SELECT e.id, e.event_hash, e.payload_json, e.source_id, e.ts, c.thread_key "
        "FROM events e LEFT JOIN conversations c ON c.id = e.conversation_id "
        f"WHERE e.channel=%s AND {EMPTY_BODY_PREDICATE.replace('payload_json', 'e.payload_json')} "
    )
    params: list[Any] = [channel]
    if after_ts is not None:
        sql += "AND (e.ts, e.id) > (%s, %s) "
        params += [after_ts, after_id]
    sql += "ORDER BY e.ts, e.id LIMIT %s"
    params.append(size)
    return conn.execute(sql, params).fetchall()


def _take_backup(dbname: str, dest: Path) -> Path:
    """Full ``pg_dump`` of the target database. Raises unless a real file lands."""
    import pgserver
    from elevate_cli.data import pg_server

    pg_dump = Path(pgserver.__file__).parent / "pginstall" / "bin" / "pg_dump"
    if not pg_dump.exists():
        raise RuntimeError(f"pg_dump not found at {pg_dump}; refusing to write without a backup")
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  taking backup -> {dest}")
    proc = subprocess.run(
        [str(pg_dump), "--format=custom", "--file", str(dest), pg_server.get_uri(dbname)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"pg_dump produced no data at {dest}; refusing to continue")
    print(f"  backup OK ({dest.stat().st_size:,} bytes)")
    return dest


def _state_path(dbname: str) -> Path:
    return Path.home() / ".elevate" / "backups" / f".{dbname}-imessage-body-backfill.state.json"


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


# ─── the repair ────────────────────────────────────────────────────────


def run(
    *,
    apply: bool,
    dbname: str,
    channel: str = CHANNEL,
    batch: int = DEFAULT_BATCH,
    limit: int | None = None,
    backup_path: Path | None = None,
    resume: bool = True,
) -> dict[str, int]:
    import psycopg
    from elevate_cli.data._util import encode_payload

    chat_db = _chat_db_path()
    print(f"chat.db  : {chat_db}")
    print(f"database : {dbname}")
    print(f"mode     : {'APPLY (writes)' if apply else 'DRY RUN (no writes)'}")
    if not chat_db.exists():
        raise SystemExit(f"chat.db not found at {chat_db}")

    print("\n[1/3] decoding chat.db (read-only)")
    recovery = build_recovery_map(chat_db)

    stats = {"broken": 0, "matched": 0, "updated": 0, "hash_conflicts": 0, "unmatched": 0, "chars": 0}
    state_path = _state_path(dbname)
    state = _load_state(state_path) if (apply and resume) else {}
    after_ts, after_id = state.get("after_ts"), state.get("after_id")
    if after_ts:
        print(f"  resuming after ts={after_ts}")

    if apply:
        if backup_path is None:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup_path = (
                Path.home() / ".elevate" / "backups"
                / f"{dbname}-pre-imessage-body-backfill-{stamp}.dump"
            )
        if not state.get("backup"):
            _take_backup(dbname, backup_path)
            state["backup"] = str(backup_path)
            _save_state(state_path, state)
        else:
            print(f"  reusing backup from earlier run: {state['backup']}")

    with _connect(dbname, autocommit=False) as conn:
        stats["broken"] = count_broken(conn, channel=channel)
        print(f"\n[2/3] events with an empty body : {stats['broken']:,}")
        print("\n[3/3] " + ("repairing" if apply else "scanning (no writes)"))

        seen = 0
        t0 = time.time()
        while True:
            size = batch if limit is None else min(batch, limit - seen)
            if size <= 0:
                break
            rows = _fetch_page(
                conn, channel=channel, after_ts=after_ts, after_id=after_id, size=size
            )
            if not rows:
                break
            touched = 0
            for eid, ehash, payload_json, source_id, ts, thread_key in rows:
                after_ts, after_id = ts, eid
                seen += 1
                text = recovery.get(ehash)
                if text is None:
                    stats["unmatched"] += 1
                    continue
                stats["matched"] += 1
                stats["chars"] += len(text)
                if not apply:
                    continue
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                    if not isinstance(payload, dict):
                        payload = {}
                except Exception:
                    payload = {}
                payload["body"] = text
                new_pj, new_ref = encode_payload(payload)
                # The identity the row should have had, so the next live sync
                # recomputes the same hash and deduplicates instead of inserting.
                new_hash = compute_event_hash(
                    source_id=source_id, thread_key=thread_key, ts=ts, body=text
                )
                try:
                    with conn.transaction():
                        conn.execute(
                            "UPDATE events SET payload_json=%s, payload_ref=%s, event_hash=%s "
                            f"WHERE id=%s AND {EMPTY_BODY_PREDICATE}",
                            (new_pj, new_ref, new_hash, eid),
                        )
                except psycopg.errors.UniqueViolation:
                    # Another event already owns the repaired identity (true
                    # duplicate message). Restore the text; leave the hash.
                    stats["hash_conflicts"] += 1
                    with conn.transaction():
                        conn.execute(
                            "UPDATE events SET payload_json=%s, payload_ref=%s "
                            f"WHERE id=%s AND {EMPTY_BODY_PREDICATE}",
                            (new_pj, new_ref, eid),
                        )
                stats["updated"] += 1
                touched += 1
            if apply:
                conn.commit()
                _save_state(
                    state_path,
                    {**state, "after_ts": after_ts, "after_id": after_id,
                     "updated": stats["updated"]},
                )
            else:
                conn.rollback()
            rate = seen / max(time.time() - t0, 0.001)
            print(
                f"      scanned {seen:>7,}  repaired {stats['updated']:>7,}  "
                f"unmatched {stats['unmatched']:>5,}  ({rate:,.0f} rows/s)"
            )

    if not apply:
        print(
            f"\nDRY RUN — nothing written."
            f"\n  would repair : {stats['matched']:,} events ({stats['chars']:,} characters)"
            f"\n  unmatched    : {stats['unmatched']:,} (no decodable source message)"
            f"\n\nRe-run with --apply to repair (a pg_dump backup is taken first)."
        )
    else:
        print(
            f"\ndone. repaired={stats['updated']:,} chars={stats['chars']:,} "
            f"unmatched={stats['unmatched']:,} hash_conflicts={stats['hash_conflicts']:,}"
            f"\nbackup: {state.get('backup')}"
        )
        try:
            state_path.unlink()
        except Exception:
            pass
    return stats


def verify(dbname: str, *, channel: str = CHANNEL) -> None:
    with _connect(dbname, autocommit=True) as conn:
        total, with_body = conn.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE "
            "COALESCE(NULLIF(TRIM(payload_json::jsonb->>'body'), ''), '') <> '') "
            "FROM events WHERE channel=%s",
            (channel,),
        ).fetchone()
        pct = (with_body / total) if total else 0
        print(f"{channel}: {with_body:,}/{total:,} events have a body ({pct:.2%})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="elevate_cli.apple_messages_body_backfill",
        description="Restore iMessage bodies lost to the attributedBody ingest gap.",
    )
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--verify", action="store_true", help="report body coverage and exit")
    ap.add_argument("--database", default=None, help="operational DB name (default: active account)")
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--limit", type=int, default=None, help="stop after N rows (canary runs)")
    ap.add_argument("--backup-file", type=Path, default=None)
    ap.add_argument("--no-resume", action="store_true", help="ignore saved cursor")
    args = ap.parse_args(argv)

    dbname = _database_name(args.database)
    if args.verify:
        verify(dbname, channel=args.channel)
        return 0
    run(
        apply=args.apply,
        dbname=dbname,
        channel=args.channel,
        batch=args.batch,
        limit=args.limit,
        backup_path=args.backup_file,
        resume=not args.no_resume,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
