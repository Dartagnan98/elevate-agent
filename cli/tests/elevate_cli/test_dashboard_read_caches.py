"""Caches added so dashboard polls stop re-reading unchanged files.

- Agent Hub JSONL tail reads (memory events, context pressure) are cached on
  the file's (mtime_ns, size) and refreshed when the file changes.
- ``cron.jobs.load_jobs`` is cached the same way and invalidated by
  ``save_jobs`` so a write in-process is visible on the very next read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cron import jobs as cron_jobs
from elevate_cli import agent_hub


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def test_jsonl_tail_cache_reuses_parse_until_file_changes(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, [{"agent": "admin", "fact": "one"}, {"agent": "admin", "fact": "two"}])

    first = agent_hub._read_jsonl_tail_records(path, 5000)
    assert [r["fact"] for r in first] == ["one", "two"]

    calls = {"n": 0}
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self == path:
            calls["n"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    again = agent_hub._read_jsonl_tail_records(path, 5000)
    assert again is first
    assert calls["n"] == 0, "unchanged file must be served from cache"

    # Append a record: size changes, so the next read re-parses.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "admin", "fact": "three"}) + "\n")
    third = agent_hub._read_jsonl_tail_records(path, 5000)
    assert calls["n"] == 1
    assert [r["fact"] for r in third] == ["one", "two", "three"]

    # Malformed lines are skipped, tail limit still applies.
    path.write_text("not json\n" + json.dumps({"agent": "a", "fact": "x"}) + "\n", encoding="utf-8")
    os.utime(path, None)
    assert [r["fact"] for r in agent_hub._read_jsonl_tail_records(path, 1)] == ["x"]


def test_load_jobs_cache_invalidated_by_save_and_external_write(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_jobs, "_account_scoping_enabled", False)
    monkeypatch.setattr(cron_jobs, "CRON_DIR", tmp_path)
    monkeypatch.setattr(cron_jobs, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cron_jobs, "JOBS_FILE", tmp_path / "jobs.json")
    cron_jobs._invalidate_jobs_cache()

    assert cron_jobs.load_jobs() == []

    cron_jobs.save_jobs([{"id": "a", "name": "first"}])
    assert [j["id"] for j in cron_jobs.load_jobs()] == ["a"]

    # Callers get their own copy: mutating it must not poison the cache.
    rows = cron_jobs.load_jobs()
    rows[0]["name"] = "mutated"
    assert cron_jobs.load_jobs()[0]["name"] == "first"

    # An external writer (another process) replaces the file: mtime/size
    # differ, so the cache misses without any in-process invalidation.
    (tmp_path / "jobs.json").write_text(
        json.dumps({"jobs": [{"id": "b", "name": "external"}]}), encoding="utf-8"
    )
    assert [j["id"] for j in cron_jobs.load_jobs()] == ["b"]
