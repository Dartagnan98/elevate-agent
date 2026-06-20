"""Source connector JSON/JSONL file helpers and UI state."""

from __future__ import annotations

import contextlib
import fcntl
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JsonRecord = dict[str, Any]

_JSONL_COUNT_CACHE: dict[str, tuple[int, int, int]] = {}
_JSONL_RECORD_CACHE: dict[tuple[str, int, bool], tuple[int, int, list[JsonRecord]]] = {}


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _now() -> str:
    return _source_connectors()._now()


def _source_dir(source_root: Path, source_id: str) -> Path:
    return source_root / source_id


def _read_json(path: Path) -> JsonRecord | None:
    try:
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_json(path: Path, value: JsonRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _count_jsonl(path: Path) -> int:
    try:
        stat = path.stat()
        cache_key = str(path)
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = _JSONL_COUNT_CACHE.get(cache_key)
        if cached and cached[:2] == signature:
            return cached[2]
        with path.open("r", encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.strip())
        _JSONL_COUNT_CACHE[cache_key] = (signature[0], signature[1], count)
        return count
    except FileNotFoundError:
        return 0
    except Exception:
        try:
            _JSONL_COUNT_CACHE.pop(str(path), None)
        except Exception:
            pass
        return 0


def _record_timestamp(record: JsonRecord) -> str:
    for key in ("timestamp", "last_message_at", "last_seen_at", "last_sync_at", "day"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _read_jsonl_records(path: Path, *, limit: int = 12, tail: bool = False) -> list[JsonRecord]:
    # No upper clamp here — callers explicitly pass small limits (UI preview reads ~12-100)
    # or large limits (rewrite-preserve operations need 5000+). Earlier 100-row ceiling
    # silently dropped preserved tasks/drafts past row 100 on every CRM sync.
    safe_limit = max(1, int(limit or 12))
    try:
        stat = path.stat()
    except FileNotFoundError:
        return []
    except Exception:
        return []
    cache_key = (str(path), safe_limit, bool(tail))
    cached = _JSONL_RECORD_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return [dict(record) for record in cached[2]]

    raw_lines: list[str]
    try:
        if tail:
            recent: deque[str] = deque(maxlen=safe_limit)
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        recent.append(line)
            raw_lines = list(recent)
        else:
            raw_lines = []
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    raw_lines.append(line)
                    if len(raw_lines) >= safe_limit:
                        break
    except Exception:
        return []

    records: list[JsonRecord] = []
    for line in raw_lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            records.append(value)
    records = sorted(records, key=_record_timestamp, reverse=True)
    _JSONL_RECORD_CACHE[cache_key] = (
        stat.st_mtime_ns,
        stat.st_size,
        [dict(record) for record in records],
    )
    return records


def _find_jsonl_record_by_id(
    path: Path,
    target_id: str,
    *,
    id_keys: tuple[str, ...] = ("id", "contact_id", "source_record_id"),
) -> JsonRecord | None:
    """Stream a JSONL file and return the last row whose id matches ``target_id``.

    Unbounded by file size and uses constant memory — designed for the thread
    drawer's contact/lead lookup, which previously used a 2000-row preview read
    and silently dropped any record past that mark. Returns the LAST matching
    row so an updated record (re-synced contact) wins over a stale earlier one.
    """
    target = (target_id or "").strip()
    if not target or not path.exists():
        return None
    match: JsonRecord | None = None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if not isinstance(value, dict):
                    continue
                for key in id_keys:
                    candidate = value.get(key)
                    if candidate is None:
                        continue
                    if str(candidate).strip() == target:
                        match = value
                        break
    except OSError:
        return match
    return match


def _stream_jsonl_records_by_id(
    path: Path,
    target_id: str,
    *,
    id_keys: tuple[str, ...] = ("contact_id", "conversation_id"),
) -> list[JsonRecord]:
    """Stream a JSONL file and return every row whose id matches ``target_id``.

    Unlike :func:`_find_jsonl_record_by_id` (which returns a single contact
    row), this returns the full event list for a given conversation — used by
    the thread drawer for notes/tasks/activity. Streams the whole file so it
    doesn't drop events for older leads on long-running CRMs (the prior
    `tail=True, limit=4000` read silently dropped activity for any contact
    whose events were ingested earlier than the last 4000 rows; with 2474
    Lofty leads and 15455 lifetime events, every contact past line 11455 had
    an empty Property Activity panel).
    """
    target = (target_id or "").strip()
    matches: list[JsonRecord] = []
    if not target or not path.exists():
        return matches
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if not isinstance(value, dict):
                    continue
                for key in id_keys:
                    candidate = value.get(key)
                    if candidate is None:
                        continue
                    if str(candidate).strip() == target:
                        matches.append(value)
                        break
    except OSError:
        return matches
    return matches


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _parse_record_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        number = int(raw)
        if number > 10_000_000_000:
            number = number // 1000
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except Exception:
            return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _tag_text(value: Any) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.extend(str(v) for v in item.values() if isinstance(v, (str, int, float)))
            else:
                parts.append(str(item))
        return " ".join(parts).lower()
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float))).lower()
    return str(value or "").lower()


def _source_ui_state_path(source_dir: Path) -> Path:
    return source_dir / "ui-state.json"


def _read_source_ui_state(source_dir: Path) -> JsonRecord:
    state = _read_json(_source_ui_state_path(source_dir))
    if not state:
        return {"threads": {}}
    threads = state.get("threads")
    if not isinstance(threads, dict):
        state["threads"] = {}
    return state


def _write_source_ui_state(source_dir: Path, state: JsonRecord) -> None:
    state["updated_at"] = _now()
    _write_json(_source_ui_state_path(source_dir), state)


# Profile-level statuses set by the operator from the /leads UI. These
# describe where the lead is in the pipeline so cron-pulled queues can
# skip cold/closed people. Distinct from thread-level status which only
# tracks open/done/archived.
PROFILE_STATUS_VALUES: tuple[str, ...] = (
    "new_lead",
    "follow_up",
    "ghosting",
    "dead",
    "closed_seller",
    "closed_buyer",
)


def _profile_state_path(source_root: Path) -> Path:
    return source_root / "profile-state.json"


def _read_profile_state(source_root: Path) -> JsonRecord:
    state = _read_json(_profile_state_path(source_root))
    if not isinstance(state, dict):
        return {"profiles": {}}
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        state["profiles"] = {}
    return state


def _write_profile_state(source_root: Path, state: JsonRecord) -> None:
    state["updated_at"] = _now()
    _write_json(_profile_state_path(source_root), state)


def _replace_jsonl(path: Path, records: list[JsonRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_path.replace(path)
    path_key = str(path)
    for cache_key in list(_JSONL_RECORD_CACHE):
        if cache_key[0] == path_key:
            _JSONL_RECORD_CACHE.pop(cache_key, None)
    _JSONL_COUNT_CACHE.pop(path_key, None)


# ─── Snapshot lock (cross-file consistency) ───────────────────────────────
#
# A CRM sync rewrites four files (contacts.jsonl, conversations.jsonl,
# lead-events.jsonl, tasks.jsonl) and a leads request reads all four. Per
# Codex audit P1 (2026-05-05) the per-file ``Path.replace`` is atomic
# alone but readers can still see torn snapshots between renames. The
# shared lock below brackets the writer's full multi-file rewrite and
# any reader that needs cross-file consistency. Best-effort — fcntl is
# advisory; nothing crashes if a caller forgets to use it.

@contextlib.contextmanager
def _snapshot_writer_lock(source_dir: Path):
    """Exclusive lock for a multi-file CRM snapshot rewrite. Wrap the
    full block of ``_replace_jsonl`` calls that should land together."""
    source_dir.mkdir(parents=True, exist_ok=True)
    lock_path = source_dir / ".snapshot.lock"
    lock_path.touch(exist_ok=True)
    fh = lock_path.open("a+")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # Best-effort: never block sync on lock failure.
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


@contextlib.contextmanager
def _snapshot_reader_lock(source_dir: Path):
    """Shared lock for cross-file reads. Wrap the block where a request
    reads multiple JSONL files that must agree (e.g. ``_read_source_inbox``)."""
    if not source_dir.exists():
        # Nothing written yet — no torn-snapshot risk.
        yield
        return
    lock_path = source_dir / ".snapshot.lock"
    if not lock_path.exists():
        # Writer hasn't run yet, nothing to coordinate with.
        yield
        return
    fh = lock_path.open("r")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        except OSError:
            pass
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()
