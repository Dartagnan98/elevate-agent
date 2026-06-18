import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from elevate_cli.diagnostics import session_recorder as recorder


@pytest.fixture()
def recorder_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.delenv("ELEVATE_SESSION_RECORDER", raising=False)
    return home


def _jsonl_files(home: Path) -> list[Path]:
    return sorted((home / "logs" / "session-events").glob("*.jsonl"))


def _jsonl_events(home: Path) -> list[dict]:
    events = []
    for path in _jsonl_files(home):
        with open(path, encoding="utf-8") as f:
            for line in f:
                events.append(json.loads(line))
    return events


def test_append_and_collect_event(recorder_home):
    assert recorder.record_session_event(
        "message.complete",
        session_id="s1",
        payload={"status": "ok", "output_tokens": 12},
    )

    result = recorder.collect_session_events("s1", since_seconds=60)

    assert result["report"]["events_written"] == 1
    event = result["events"][0]
    assert event["event"] == "message.complete"
    assert event["session_id"] == "s1"
    assert event["payload"] == {"status": "ok", "output_tokens": 12}


def test_sanitizer_drops_forbidden_and_unknown_keys(recorder_home):
    assert recorder.record_session_event(
        "gateway.error",
        session_id="s1",
        payload={
            "content": "raw prompt content",
            "prompt": "sell my house",
            "customer_name": "Private Client",
            "error_message": (
                "email joe@example.com phone +16045551212 "
                "token=sk-1234567890abcdef password=hunter2 "
                "/Users/dartagnanpatricio/private/report.pdf"
            ),
            "output_tokens": 3,
        },
        severity="error",
    )

    raw = "\n".join(path.read_text(encoding="utf-8") for path in _jsonl_files(recorder_home))
    event = _jsonl_events(recorder_home)[0]
    payload = event["payload"]
    redaction = event["redaction"]

    assert "content" not in payload
    assert "prompt" not in payload
    assert "customer_name" not in payload
    assert redaction["forbidden_keys_dropped"] == 2
    assert redaction["unknown_keys_dropped"] == 1
    assert redaction["strings_redacted"] > 0
    assert payload["output_tokens"] == 3
    assert "joe@example.com" not in raw
    assert "+16045551212" not in raw
    assert "hunter2" not in raw
    assert "/Users/dartagnanpatricio" not in raw
    assert "report.pdf" in raw


def test_sanitizer_rejects_type_abuse_content_channels(recorder_home):
    assert recorder.record_session_event(
        "gateway.error",
        session_id="s1",
        payload={
            "output_tokens": "raw prompt text",
            "success": "raw answer text",
            "status": {"content": "raw nested content"},
            "prompt_hash": {"content": "raw nested hash"},
            "retry_count": 2,
            "failed": False,
        },
    )

    raw = "\n".join(path.read_text(encoding="utf-8") for path in _jsonl_files(recorder_home))
    event = _jsonl_events(recorder_home)[0]

    assert event["payload"] == {"retry_count": 2, "failed": False}
    assert "raw prompt text" not in raw
    assert "raw answer text" not in raw
    assert "raw nested content" not in raw
    assert "raw nested hash" not in raw
    assert event["redaction"]["unknown_keys_dropped"] == 4


def test_friction_metric_allowlist_keeps_safe_types():
    payload, report = recorder.sanitize_payload(
        "browser.friction_detected",
        {
            "attempt_count": 2,
            "correction_count": 1,
            "friction_count": 3,
            "critical_ratio_bps": 999,
            "critical_item_count": 2,
            "context_tokens": 120,
            "context_limit": 1200,
            "compaction_saved_tokens": 42,
            "compaction_removed_messages": 8,
            "low_yield_count": 0,
            "tool_name": "browser_navigate",
            "stage": "navigate",
            "friction_kind": "blocked",
            "outcome": "failed",
            "recovered": False,
            "abandoned": True,
        },
    )

    assert payload == {
        "attempt_count": 2,
        "correction_count": 1,
        "friction_count": 3,
        "critical_ratio_bps": 999,
        "critical_item_count": 2,
        "context_tokens": 120,
        "context_limit": 1200,
        "compaction_saved_tokens": 42,
        "compaction_removed_messages": 8,
        "low_yield_count": 0,
        "tool_name": "browser_navigate",
        "stage": "navigate",
        "friction_kind": "blocked",
        "outcome": "failed",
        "recovered": False,
        "abandoned": True,
    }
    assert report["unknown_keys_dropped"] == 0


def test_friction_metric_allowlist_drops_wrong_types_and_raw_browser_text():
    payload, report = recorder.sanitize_payload(
        "browser.friction_detected",
        {
            "attempt_count": "2",
            "critical_ratio_bps": "1250",
            "recovered": "false",
            "abandoned": 1,
            "tool_name": {"content": "browser_navigate"},
            "url": "https://example.com/private?token=secret",
            "browser_snapshot": "secret page snapshot",
            "raw": "raw browser result",
            "text": "page text",
            "stack": "stack trace",
        },
    )

    assert payload == {}
    assert report["unknown_keys_dropped"] == 7
    assert report["forbidden_keys_dropped"] == 3


def test_event_name_is_not_a_content_channel(recorder_home):
    assert recorder.record_session_event(
        "Please sell 123 Main Street to joe@example.com",
        session_id="s1",
    )

    event = _jsonl_events(recorder_home)[0]

    assert event["event"] == "diagnostics.event"
    assert "Main Street" not in json.dumps(event)
    assert "joe@example.com" not in json.dumps(event)


def test_envelope_strings_are_redacted(recorder_home):
    assert recorder.record_session_event(
        "gateway.error",
        session_id="s1",
        source="joe@example.com",
        component="/Users/dartagnanpatricio/private/report.pdf",
        app_version="https://user:pass@example.com/callback?token=abc123&ok=1",
    )

    raw = "\n".join(path.read_text(encoding="utf-8") for path in _jsonl_files(recorder_home))
    event = _jsonl_events(recorder_home)[0]

    assert event["source"] == "[redacted-email]"
    assert event["component"] == "[path:report.pdf]"
    assert "joe@example.com" not in raw
    assert "/Users/dartagnanpatricio" not in raw
    assert "pass@example.com" not in raw
    assert "token=abc123" not in raw


def test_collect_skips_malformed_lines(recorder_home):
    assert recorder.record_session_event("message.start", session_id="s1")
    path = _jsonl_files(recorder_home)[0]
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not-json}\n")

    result = recorder.collect_session_events("s1", since_seconds=60)

    assert len(result["events"]) == 1
    assert result["report"]["malformed_lines"] == 1


def test_collect_matches_child_and_task_ids(recorder_home):
    assert recorder.record_session_event(
        "subagent.complete",
        session_id="parent",
        child_session_id="child-1",
        task_id="task-1",
        payload={"status": "completed", "api_calls": 2},
    )
    assert recorder.record_session_event(
        "subagent.complete",
        session_id="other",
        child_session_id="child-2",
        task_id="task-2",
        payload={"status": "completed", "api_calls": 1},
    )

    by_child = recorder.collect_session_events(child_session_id="child-1", since_seconds=60)
    by_task = recorder.collect_session_events(task_id="task-2", since_seconds=60)

    assert [event["child_session_id"] for event in by_child["events"]] == ["child-1"]
    assert [event["task_id"] for event in by_task["events"]] == ["task-2"]


def test_kill_switch_prevents_file_creation(recorder_home, monkeypatch):
    monkeypatch.setenv("ELEVATE_SESSION_RECORDER", "off")

    assert recorder.record_session_event("message.start", session_id="s1") is False
    assert not (recorder_home / "logs" / "session-events").exists()


def test_successful_write_enqueues_cloud_upload(recorder_home, monkeypatch):
    from elevate_cli.diagnostics import session_uploader

    queued = []
    monkeypatch.setattr(
        session_uploader,
        "queue_session_event",
        lambda event: queued.append(event),
    )

    assert recorder.record_session_event("message.start", session_id="s1")

    assert len(queued) == 1
    assert queued[0]["event"] == "message.start"
    assert queued[0]["session_id"] == "s1"


def test_uploader_skips_when_no_license(monkeypatch):
    from elevate_cli import license as elevate_license
    from elevate_cli.diagnostics import session_uploader

    started = []
    monkeypatch.setenv("ELEVATE_SESSION_RECORDER_UPLOAD", "1")
    monkeypatch.setattr(elevate_license, "load", lambda: None)
    monkeypatch.setattr(session_uploader, "_ensure_worker", lambda: started.append(True))

    session_uploader.queue_session_event({"event_id": "e1", "event": "message.start"})

    assert started == []


def test_uploader_is_opt_in_by_default(monkeypatch):
    from elevate_cli.diagnostics import session_uploader

    monkeypatch.delenv("ELEVATE_SESSION_RECORDER_UPLOAD", raising=False)

    assert session_uploader.uploader_enabled() is False


def test_write_failure_returns_false(tmp_path, monkeypatch):
    bad_home = tmp_path / "not-a-directory"
    bad_home.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("ELEVATE_HOME", str(bad_home))

    assert recorder.record_session_event("message.start", session_id="s1") is False


def test_retention_prunes_old_jsonl(recorder_home):
    base_dir = recorder_home / "logs" / "session-events"
    base_dir.mkdir(parents=True)
    old = base_dir / "2000-01-01.jsonl"
    old.write_text('{"ts":1}\n', encoding="utf-8")
    os.utime(old, (0, 0))

    assert recorder.record_session_event("message.start", session_id="s1")

    assert not old.exists()


def test_directory_size_cap_prunes_existing_jsonl(recorder_home, monkeypatch):
    base_dir = recorder_home / "logs" / "session-events"
    base_dir.mkdir(parents=True)
    now = time.time()
    old_files = []
    for idx in range(2):
        path = base_dir / f"old-{idx}.jsonl"
        path.write_text("x" * 100, encoding="utf-8")
        os.utime(path, (now - idx, now - idx))
        old_files.append(path)
    monkeypatch.setattr(recorder, "DEFAULT_MAX_DIR_SIZE_BYTES", 50)

    assert recorder.record_session_event("message.start", session_id="s1")

    assert all(not path.exists() for path in old_files)


def test_oversize_payload_is_truncated_before_write(recorder_home, monkeypatch):
    monkeypatch.setattr(recorder, "DEFAULT_MAX_EVENT_BYTES", 600)

    assert recorder.record_session_event(
        "gateway.error",
        session_id="s1",
        payload={"error_message": "x" * 2000},
    )

    raw = "\n".join(path.read_text(encoding="utf-8") for path in _jsonl_files(recorder_home))
    event = _jsonl_events(recorder_home)[0]

    assert event["payload"] == {"payload_truncated": True}
    assert event["redaction"]["oversize_payloads_truncated"] == 1
    assert "x" * 100 not in raw


def test_rotation_keeps_parseable_jsonl(recorder_home, monkeypatch):
    monkeypatch.setattr(recorder, "DEFAULT_MAX_FILE_SIZE_BYTES", 350)

    for idx in range(5):
        assert recorder.record_session_event(
            "gateway.error",
            session_id="s1",
            payload={"error_message": "x" * 120, "retry_count": idx},
        )

    files = _jsonl_files(recorder_home)
    assert len(files) >= 2
    assert len(_jsonl_events(recorder_home)) == 5


def test_concurrent_thread_writers_produce_parseable_jsonl(recorder_home):
    def write(idx: int) -> bool:
        return recorder.record_session_event(
            "message.complete",
            session_id="threaded",
            payload={"retry_count": idx},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(40)))

    assert any(results)
    events = _jsonl_events(recorder_home)
    assert events
    assert all(event["session_id"] == "threaded" for event in events)


def test_memory_critical_sample_below_threshold_only_writes_sample(recorder_home):
    ratio = recorder.record_memory_critical_sample(
        "s1",
        critical_chars=100,
        critical_item_count=1,
        context_budget_chars=2000,
    )

    events = _jsonl_events(recorder_home)
    assert ratio == 500
    assert [event["event"] for event in events] == ["memory.critical_budget_sample"]
    assert events[0]["payload"]["critical_ratio_bps"] == 500
    assert "critical_chars" not in json.dumps(events)


def test_memory_critical_sample_above_threshold_writes_exceeded(recorder_home):
    ratio = recorder.record_memory_critical_sample(
        "s1",
        critical_chars=250,
        critical_item_count=2,
        context_budget_chars=2000,
    )

    events = _jsonl_events(recorder_home)
    assert ratio == 1250
    assert [event["event"] for event in events] == [
        "memory.critical_budget_sample",
        "memory.critical_budget_exceeded",
    ]
    assert events[1]["severity"] == "warning"


def test_concurrent_process_writers_produce_parseable_jsonl(recorder_home):
    script = """
from elevate_cli.diagnostics.session_recorder import record_session_event
for i in range(10):
    record_session_event("message.complete", session_id="process", payload={"retry_count": i})
"""
    env = os.environ.copy()
    env["ELEVATE_HOME"] = str(recorder_home)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    procs = [
        subprocess.Popen([sys.executable, "-c", script], cwd=env["PYTHONPATH"], env=env)
        for _ in range(4)
    ]
    for proc in procs:
        assert proc.wait(timeout=10) == 0

    events = _jsonl_events(recorder_home)
    assert events
    assert all(event["session_id"] == "process" for event in events)
