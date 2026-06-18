from pathlib import Path

from scripts.compaction_log_summary import (
    format_text_summary,
    iter_compaction_events,
    parse_compaction_line,
    summarize_compaction_events,
)


def test_parse_compaction_line_extracts_support_fields():
    line = (
        "INFO compaction.completed reason=full_compact source=compress_context "
        "session=sess-1 raw_messages=42 tokens_before=12345 "
        "cursor_before=0 cursor_after=30 summary_chars=99 aborted=false"
    )

    record = parse_compaction_line(line, path=Path("/tmp/agent.log"))

    assert record["event"] == "compaction.completed"
    assert record["reason"] == "full_compact"
    assert record["source"] == "compress_context"
    assert record["session"] == "sess-1"
    assert record["tokens_before"] == "12345"
    assert record["cursor_after"] == "30"
    assert record["path"] == "/tmp/agent.log"


def test_parse_ignores_non_compaction_lines():
    assert parse_compaction_line("INFO normal gateway line") is None


def test_iter_compaction_events_reads_existing_paths_only(tmp_path):
    log = tmp_path / "gateway.log"
    log.write_text(
        "\n".join(
            [
                "INFO inbound message",
                (
                    "INFO compaction.skipped reason=legacy_hygiene "
                    "source=estimated trigger=noop_guard session=sess-tg "
                    "raw_messages=450 effective_messages=450 tokens_before=100000 "
                    "cursor_before=0"
                ),
            ]
        ),
        encoding="utf-8",
    )

    events = list(iter_compaction_events([tmp_path / "missing.log", log]))

    assert len(events) == 1
    assert events[0]["event"] == "compaction.skipped"
    assert events[0]["reason"] == "legacy_hygiene"
    assert events[0]["trigger"] == "noop_guard"


def test_summarize_compaction_events_groups_paths_and_filters_session():
    events = [
        parse_compaction_line(
            "compaction.decision reason=full_compact source=real_count_projection "
            "session=sess-a raw_messages=20 effective_messages=12 "
            "tokens_before=181000 threshold_tokens=180000 context_limit=200000 "
            "cursor_before=0"
        ),
        parse_compaction_line(
            "compaction.decision reason=critical_compact source=effective_estimate "
            "session=sess-a raw_messages=25 effective_messages=15 "
            "tokens_before=191000 threshold_tokens=180000 context_limit=200000 "
            "cursor_before=0"
        ),
        parse_compaction_line(
            "compaction.completed reason=prune source=real_count_projection "
            "session=sess-b tokens_before=150000 threshold_tokens=180000 "
            "note=no_summary"
        ),
        parse_compaction_line(
            "compaction.failed reason=legacy_hygiene source=estimated "
            "trigger=message_count session=sess-a raw_messages=476 "
            "effective_messages=476 tokens_before=100000 cursor_before=0 "
            "retry_guard=recorded error=context"
        ),
    ]

    summary = summarize_compaction_events(events, session="sess-a", limit=2)

    assert summary["total"] == 3
    assert summary["by_event"] == {
        "compaction.decision": 2,
        "compaction.failed": 1,
    }
    assert summary["by_reason"] == {
        "critical_compact": 1,
        "full_compact": 1,
        "legacy_hygiene": 1,
    }
    assert summary["by_source"] == {
        "effective_estimate": 1,
        "estimated": 1,
        "real_count_projection": 1,
    }
    assert summary["sessions"] == ["sess-a"]
    assert [event["reason"] for event in summary["recent"]] == [
        "critical_compact",
        "legacy_hygiene",
    ]


def test_format_text_summary_is_support_readable():
    summary = summarize_compaction_events(
        [
            parse_compaction_line(
                "compaction.skipped reason=legacy_hygiene source=estimated "
                "session=sess-tg trigger=noop_guard raw_messages=450 "
                "effective_messages=450 tokens_before=100000 cursor_before=0"
            )
        ]
    )

    text = format_text_summary(summary)

    assert "Compaction events: 1" in text
    assert "By reason: legacy_hygiene:1" in text
    assert "session=sess-tg" in text
    assert "raw_messages=450" in text
    assert "effective_messages=450" in text
