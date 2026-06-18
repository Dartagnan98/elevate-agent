#!/usr/bin/env python3
"""Summarize compaction events from Elevate logs for support triage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator


EVENT_RE = re.compile(
    r"\b(compaction\.(?:decision|started|completed|skipped|failed))\b"
)
KV_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


def default_log_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".elevate/logs/agent.log",
        home / ".elevate/logs/gateway.log",
        home / "Library/Logs/Elevate/main.log",
    ]


def parse_compaction_line(line: str, *, path: Path | None = None) -> dict | None:
    match = EVENT_RE.search(line)
    if not match:
        return None

    fields = {key: value.rstrip(",") for key, value in KV_RE.findall(line)}
    event = match.group(1)
    record = {
        "event": event,
        "path": str(path) if path is not None else "",
        "line": line.rstrip("\n"),
    }
    record.update(fields)
    return record


def iter_compaction_events(paths: Iterable[Path]) -> Iterator[dict]:
    for path in paths:
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                record = parse_compaction_line(line, path=path)
                if record is not None:
                    yield record


def summarize_compaction_events(
    events: Iterable[dict],
    *,
    session: str | None = None,
    limit: int = 20,
) -> dict:
    selected = []
    for event in events:
        if session and event.get("session") != session:
            continue
        selected.append(event)

    return {
        "total": len(selected),
        "by_event": dict(Counter(e.get("event", "") for e in selected)),
        "by_reason": dict(Counter(e.get("reason", "unknown") for e in selected)),
        "by_source": dict(Counter(e.get("source", "unknown") for e in selected)),
        "sessions": sorted({e.get("session", "") for e in selected if e.get("session")}),
        "recent": selected[-max(0, limit):],
    }


def _compact_recent_line(event: dict) -> str:
    fields = [
        event.get("event", ""),
        f"reason={event.get('reason', 'unknown')}",
        f"source={event.get('source', 'unknown')}",
        f"session={event.get('session', 'unknown')}",
    ]
    for key in (
        "raw_messages",
        "effective_messages",
        "tokens_before",
        "threshold_tokens",
        "context_limit",
        "cursor_before",
        "cursor_after",
        "summary_chars",
        "note",
        "error",
    ):
        value = event.get(key)
        if value is not None:
            fields.append(f"{key}={value}")
    return " ".join(fields)


def format_text_summary(summary: dict) -> str:
    lines = [f"Compaction events: {summary['total']}"]
    for label, key in (
        ("By event", "by_event"),
        ("By reason", "by_reason"),
        ("By source", "by_source"),
    ):
        values = summary.get(key) or {}
        if values:
            parts = ", ".join(f"{k}:{v}" for k, v in sorted(values.items()))
            lines.append(f"{label}: {parts}")
    sessions = summary.get("sessions") or []
    if sessions:
        lines.append(f"Sessions: {', '.join(sessions[:12])}")
        if len(sessions) > 12:
            lines[-1] += f" (+{len(sessions) - 12} more)"
    recent = summary.get("recent") or []
    if recent:
        lines.append("Recent:")
        lines.extend(f"- {_compact_recent_line(event)}" for event in recent)
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=default_log_paths())
    parser.add_argument("--session", help="Only include one session id.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    summary = summarize_compaction_events(
        iter_compaction_events(args.paths),
        session=args.session,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_text_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
