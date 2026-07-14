"""Kanban LLM writes require a complete terminal provider response."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _unoffered_tool_call() -> SimpleNamespace:
    return SimpleNamespace(
        function=SimpleNamespace(name="not_offered", arguments="{}"),
    )


def _response(
    *,
    finish_reason: object,
    content: str,
    tool_calls: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
            )
        ]
    )


def _triage_task() -> SimpleNamespace:
    return SimpleNamespace(
        id="task-1",
        status="triage",
        title="Prepare the deal",
        body="Use the correct provincial forms.",
        assignee=None,
    )


def _run_decompose(response, *, graph_result=None):
    from elevate_cli import kanban_decompose as mod

    client = MagicMock()
    client.chat.completions.create.return_value = response
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as specify_mutation,
        patch.object(mod.kb, "decompose_triage_task") as graph_mutation,
        patch.object(mod, "_load_config", return_value={}),
        patch.object(mod, "_resolve_orchestrator_profile", return_value="main"),
        patch.object(mod, "_resolve_default_assignee", return_value="main"),
        patch.object(
            mod,
            "_build_roster",
            return_value=(
                [
                    {
                        "name": "main",
                        "description": "orchestrator",
                        "has_description": True,
                    }
                ],
                {"main"},
            ),
        ),
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        if graph_result is not None:
            graph_mutation.return_value = graph_result
        outcome = mod.decompose_task("task-1", author="tester")

    return outcome, specify_mutation, graph_mutation


def test_specify_length_response_never_mutates_board():
    from elevate_cli import kanban_specify as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="length",
        content='{"title":"Changed","body":"Looks parseable but truncated"}',
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as mutate,
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.specify_task("task-1")

    assert outcome.ok is False
    assert "incomplete (length)" in outcome.reason
    mutate.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        "I cannot specify this task because the required context is missing.",
        '{"title":"Changed","body":"unterminated}',
    ],
)
def test_specify_refusal_or_malformed_json_never_promotes_task(content):
    from elevate_cli import kanban_specify as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="stop",
        content=content,
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as mutate,
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.specify_task("task-1")

    assert outcome.ok is False
    assert "malformed JSON" in outcome.reason
    mutate.assert_not_called()


def test_specify_valid_structured_json_still_promotes_task():
    from elevate_cli import kanban_specify as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="stop",
        content=(
            '{"title":"Prepare the BC deal package",'
            '"body":"**Goal** Prepare the forms.\\n\\n**Approach** Verify the deal.\\n\\n'
            '**Acceptance criteria** All required forms are present."}'
        ),
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task", return_value=True) as mutate,
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.specify_task("task-1", author="tester")

    assert outcome.ok is True
    assert outcome.reason == "specified"
    mutate.assert_called_once()
    assert mutate.call_args.kwargs == {
        "title": "Prepare the BC deal package",
        "body": (
            "**Goal** Prepare the forms.\n\n**Approach** Verify the deal.\n\n"
            "**Acceptance criteria** All required forms are present."
        ),
        "author": "tester",
    }


def test_specify_unoffered_tool_call_never_mutates_board():
    from elevate_cli import kanban_specify as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="stop",
        content='{"title":"Unsafe change","body":"Looks valid"}',
        tool_calls=[_unoffered_tool_call()],
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as mutate,
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.specify_task("task-1")

    assert outcome.ok is False
    assert "unexpected tool call" in outcome.reason
    mutate.assert_not_called()


def test_decompose_length_response_never_mutates_board():
    from elevate_cli import kanban_decompose as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="length",
        content=(
            '{"fanout":true,"tasks":['
            '{"title":"Unsafe child","body":"Partial","parents":[]}'
            "]}"
        ),
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as specify_mutation,
        patch.object(mod.kb, "decompose_triage_task") as graph_mutation,
        patch.object(mod, "_load_config", return_value={}),
        patch.object(mod, "_resolve_orchestrator_profile", return_value="main"),
        patch.object(mod, "_resolve_default_assignee", return_value="main"),
        patch.object(
            mod,
            "_build_roster",
            return_value=(
                [
                    {
                        "name": "main",
                        "description": "orchestrator",
                        "has_description": True,
                    }
                ],
                {"main"},
            ),
        ),
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.decompose_task("task-1")

    assert outcome.ok is False
    assert "incomplete (length)" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


def test_decompose_unoffered_tool_call_never_mutates_board():
    from elevate_cli import kanban_decompose as mod

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        finish_reason="stop",
        content=(
            '{"fanout":true,"tasks":['
            '{"title":"Unsafe child","body":"Valid body","parents":[]}'
            "]}"
        ),
        tool_calls=[_unoffered_tool_call()],
    )
    connection = MagicMock()
    connection.__enter__.return_value = MagicMock()

    with (
        patch.object(mod.kb, "connect", return_value=connection),
        patch.object(mod.kb, "get_task", return_value=_triage_task()),
        patch.object(mod.kb, "specify_triage_task") as specify_mutation,
        patch.object(mod.kb, "decompose_triage_task") as graph_mutation,
        patch.object(mod, "_load_config", return_value={}),
        patch.object(mod, "_resolve_orchestrator_profile", return_value="main"),
        patch.object(mod, "_resolve_default_assignee", return_value="main"),
        patch.object(
            mod,
            "_build_roster",
            return_value=(
                [
                    {
                        "name": "main",
                        "description": "orchestrator",
                        "has_description": True,
                    }
                ],
                {"main"},
            ),
        ),
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.decompose_task("task-1")

    assert outcome.ok is False
    assert "unexpected tool call" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


def test_decompose_prose_wrapped_json_never_mutates_board():
    payload = {
        "fanout": False,
        "rationale": "One worker is enough.",
        "title": "Prepare the deal package",
        "body": "Prepare and verify all required forms.",
        "assignee": None,
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(
            finish_reason="stop",
            content="Here is the result:\n" + json.dumps(payload),
        )
    )

    assert outcome.ok is False
    assert "malformed JSON" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


def test_decompose_string_fanout_never_mutates_board():
    payload = {
        "fanout": "false",
        "rationale": "One worker is enough.",
        "title": "Prepare the deal package",
        "body": "Prepare and verify all required forms.",
        "assignee": None,
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(finish_reason="stop", content=json.dumps(payload))
    )

    assert outcome.ok is False
    assert "fanout must be a boolean" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


def test_decompose_empty_child_body_never_mutates_board():
    payload = {
        "fanout": True,
        "rationale": "Split the work.",
        "tasks": [
            {
                "title": "Prepare forms",
                "body": "",
                "assignee": None,
                "parents": [],
            },
            {
                "title": "Review forms",
                "body": "Review the prepared forms.",
                "assignee": None,
                "parents": [],
            },
        ],
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(finish_reason="stop", content=json.dumps(payload))
    )

    assert outcome.ok is False
    assert "body is missing or empty" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


@pytest.mark.parametrize("task_count", [1, 7])
def test_decompose_fanout_cardinality_never_mutates_board(task_count):
    payload = {
        "fanout": True,
        "rationale": "Split the work.",
        "tasks": [
            {
                "title": f"Task {index}",
                "body": f"Complete work item {index}.",
                "assignee": None,
                "parents": [],
            }
            for index in range(task_count)
        ],
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(finish_reason="stop", content=json.dumps(payload))
    )

    assert outcome.ok is False
    assert "between 2 and 6 tasks" in outcome.reason
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


@pytest.mark.parametrize("parents", [[True], ["0"], [9]])
def test_decompose_invalid_parent_indices_never_mutate_board(parents):
    payload = {
        "fanout": True,
        "rationale": "Split the work.",
        "tasks": [
            {
                "title": "Prepare forms",
                "body": "Prepare the required forms.",
                "assignee": None,
                "parents": parents,
            },
            {
                "title": "Review forms",
                "body": "Review the prepared forms.",
                "assignee": "main",
                "parents": [],
            },
        ],
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(finish_reason="stop", content=json.dumps(payload))
    )

    assert outcome.ok is False
    specify_mutation.assert_not_called()
    graph_mutation.assert_not_called()


def test_decompose_valid_graph_preserves_assignee_fallback_and_mutates_once():
    payload = {
        "fanout": True,
        "rationale": "Preparation and review can be routed explicitly.",
        "tasks": [
            {
                "title": "Prepare forms",
                "body": "Prepare the required provincial forms.",
                "assignee": None,
                "parents": [],
            },
            {
                "title": "Review forms",
                "body": "Review the prepared forms for compliance.",
                "assignee": "unknown-profile",
                "parents": [0],
            },
        ],
    }
    outcome, specify_mutation, graph_mutation = _run_decompose(
        _response(finish_reason="stop", content=json.dumps(payload)),
        graph_result=["child-1", "child-2"],
    )

    assert outcome.ok is True
    assert outcome.fanout is True
    assert outcome.child_ids == ["child-1", "child-2"]
    specify_mutation.assert_not_called()
    graph_mutation.assert_called_once()
    assert graph_mutation.call_args.kwargs["children"] == [
        {
            "title": "Prepare forms",
            "body": "Prepare the required provincial forms.",
            "assignee": "main",
            "parents": [],
        },
        {
            "title": "Review forms",
            "body": "Review the prepared forms for compliance.",
            "assignee": "main",
            "parents": [0],
        },
    ]
