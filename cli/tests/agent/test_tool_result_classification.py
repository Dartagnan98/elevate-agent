import json

import pytest

from agent.tool_result_classification import classify_tool_failure


@pytest.mark.parametrize("failed_count", [0, 3])
def test_nested_failure_fields_do_not_fail_a_successful_tool(failed_count):
    result = json.dumps(
        {
            "success": True,
            "overview": {
                "failed": failed_count,
                "recentSends": [{"error": "one historical send failed"}],
            },
        }
    )

    assert classify_tool_failure("leads_overview", result) == (False, "")


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False},
        {"error": "provider unavailable"},
        {"status": "error"},
        {"status": "failed"},
        {"status": "cancelled"},
        {"status": "canceled"},
        {"status": "interrupted"},
    ],
)
def test_top_level_failure_fields_fail_the_tool(payload):
    assert classify_tool_failure("example", json.dumps(payload)) == (
        True,
        " [error]",
    )


def test_plain_error_result_remains_a_failure():
    assert classify_tool_failure("example", "Error: provider unavailable") == (
        True,
        " [error]",
    )


@pytest.mark.parametrize(
    "result",
    [
        "error: provider unavailable",
        "[Tool execution cancelled — interrupted]",
        "[Tool execution skipped — not started]",
        "Tool execution failed: worker crashed",
    ],
)
def test_known_plain_failure_prefixes_are_case_insensitive(result):
    assert classify_tool_failure("example", result) == (True, " [error]")


def test_terminal_top_level_error_without_exit_code_is_a_failure():
    assert classify_tool_failure(
        "terminal",
        json.dumps({"status": "error", "error": "foreground command timed out"}),
    ) == (True, " [error]")


def test_terminal_nonzero_exit_preserves_exit_code_suffix():
    assert classify_tool_failure(
        "terminal",
        json.dumps({"exit_code": 2, "error": "command failed"}),
    ) == (True, " [exit 2]")
