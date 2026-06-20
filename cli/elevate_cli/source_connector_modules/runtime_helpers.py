from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    """Replay a JSONL snapshot through the operational Postgres walker."""
    from elevate_cli.data import connect as _data_connect
    from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

    stats = BackfillStats()
    with _data_connect() as conn:
        walk_jsonl_source(source_dir, conn=conn, stats=stats, dry_run=False)
    return stats.to_dict()
