import json
import os
import subprocess
import sys
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


def test_event_name_is_not_a_content_channel(recorder_home):
    assert recorder.record_session_event(
        "Please sell 123 Main Street to joe@example.com",
        session_id="s1",
    )

    event = _jsonl_events(recorder_home)[0]

    assert event["event"] == "diagnostics.event"
    assert "Main Street" not in json.dumps(event)
    assert "joe@example.com" not in json.dumps(event)


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


def test_write_failure_returns_false(tmp_path, monkeypatch):
    bad_home = tmp_path / "not-a-directory"
    bad_home.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("ELEVATE_HOME", str(bad_home))

    assert recorder.record_session_event("message.start", session_id="s1") is False


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
