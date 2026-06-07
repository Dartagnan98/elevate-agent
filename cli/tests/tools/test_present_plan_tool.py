"""Tests for present_plan preservation helpers."""

import json

from tools.present_plan_tool import (
    PLAN_INJECTION_HEADER,
    extract_latest_plan_from_messages,
    format_latest_plan_for_injection,
)


def test_extracts_latest_plan_by_tool_name():
    messages = [
        {
            "role": "tool",
            "tool_name": "present_plan",
            "content": json.dumps({"plan": "# Old"}),
        },
        {
            "role": "tool",
            "tool_name": "present_plan",
            "content": json.dumps({
                "plan": "# New\n\nDo the thing.",
                "title": "Current",
            }),
        },
    ]

    assert extract_latest_plan_from_messages(messages) == (
        "# New\n\nDo the thing.",
        "Current",
    )


def test_extracts_plan_by_tool_call_id_when_tool_name_missing():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_plan",
                    "type": "function",
                    "function": {"name": "present_plan", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_plan",
            "content": json.dumps({"plan": "# Persist me"}),
        },
    ]

    assert extract_latest_plan_from_messages(messages) == ("# Persist me", None)


def test_formats_and_reextracts_prior_injected_snapshot():
    snapshot = format_latest_plan_for_injection([
        {
            "role": "tool",
            "tool_name": "present_plan",
            "content": json.dumps({
                "plan": "# Plan\n\n1. Keep state.",
                "title": "State",
            }),
        }
    ])

    assert snapshot is not None
    assert snapshot.startswith(PLAN_INJECTION_HEADER)
    assert extract_latest_plan_from_messages([
        {"role": "user", "content": snapshot},
    ]) == (
        "# Plan\n\n1. Keep state.",
        "State",
    )
