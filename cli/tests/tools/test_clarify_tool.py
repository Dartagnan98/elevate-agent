"""Tests for tools/clarify_tool.py - Interactive clarifying questions."""

import json
from typing import List, Optional

import pytest

from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.clarify_tool import (
    clarify_tool,
    check_clarify_requirements,
    dispatch_clarify_via_registry,
    MAX_CHOICES,
    CLARIFY_SCHEMA,
)
from tools.registry import registry


class TestClarifyToolBasics:
    """Basic functionality tests for clarify_tool."""

    def test_simple_question_with_callback(self):
        """Should return user response for simple question."""
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            assert question == "What color?"
            assert choices is None
            return "blue"

        result = json.loads(clarify_tool("What color?", callback=mock_callback))
        assert result["question"] == "What color?"
        assert result["choices_offered"] is None
        assert result["user_response"] == "blue"

    def test_question_with_choices(self):
        """Should pass choices to callback and return response."""
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            assert question == "Pick a number"
            assert choices == ["1", "2", "3"]
            return "2"

        result = json.loads(clarify_tool(
            "Pick a number",
            choices=["1", "2", "3"],
            callback=mock_callback
        ))
        assert result["question"] == "Pick a number"
        assert result["choices_offered"] == ["1", "2", "3"]
        assert result["user_response"] == "2"

    def test_empty_question_returns_error(self):
        """Should return error for empty question."""
        result = json.loads(clarify_tool("", callback=lambda q, c: "ignored"))
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_whitespace_only_question_returns_error(self):
        """Should return error for whitespace-only question."""
        result = json.loads(clarify_tool("   \n\t  ", callback=lambda q, c: "ignored"))
        assert "error" in result

    def test_no_callback_returns_error(self):
        """Should return error when no callback is provided."""
        result = json.loads(clarify_tool("What do you want?"))
        assert "error" in result
        assert "not available" in result["error"].lower()


class TestClarifyToolChoicesValidation:
    """Tests for choices parameter validation."""

    def test_choices_trimmed_to_max(self):
        """Should trim choices to MAX_CHOICES."""
        choices_passed = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_passed.extend(choices or [])
            return "picked"

        many_choices = ["a", "b", "c", "d", "e", "f", "g"]
        clarify_tool("Pick one", choices=many_choices, callback=mock_callback)

        assert len(choices_passed) == MAX_CHOICES

    def test_empty_choices_become_none(self):
        """Empty choices list should become None (open-ended)."""
        choices_received = ["marker"]

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.clear()
            if choices is not None:
                choices_received.extend(choices)
            return "answer"

        clarify_tool("Open question?", choices=[], callback=mock_callback)
        assert choices_received == []  # Was cleared, nothing added

    def test_choices_with_only_whitespace_stripped(self):
        """Whitespace-only choices should be stripped out."""
        choices_received = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.extend(choices or [])
            return "answer"

        clarify_tool("Pick", choices=["valid", "  ", "", "also valid"], callback=mock_callback)
        assert choices_received == ["valid", "also valid"]

    def test_invalid_choices_type_returns_error(self):
        """Non-list choices should return error."""
        result = json.loads(clarify_tool(
            "Question?",
            choices="not a list",  # type: ignore
            callback=lambda q, c: "ignored"
        ))
        assert "error" in result
        assert "list" in result["error"].lower()

    def test_choices_converted_to_strings(self):
        """Non-string choices should be converted to strings."""
        choices_received = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.extend(choices or [])
            return "answer"

        clarify_tool("Pick", choices=[1, 2, 3], callback=mock_callback)  # type: ignore
        assert choices_received == ["1", "2", "3"]


class TestClarifyToolCallbackHandling:
    """Tests for callback error handling."""

    def test_callback_exception_returns_error(self):
        """Should return error if callback raises exception."""
        def failing_callback(question: str, choices: Optional[List[str]]) -> str:
            raise RuntimeError("User cancelled")

        result = json.loads(clarify_tool("Question?", callback=failing_callback))
        assert "error" in result
        assert "Failed to get user input" in result["error"]
        assert "User cancelled" in result["error"]

    def test_callback_receives_stripped_question(self):
        """Callback should receive trimmed question."""
        received_question = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            received_question.append(question)
            return "answer"

        clarify_tool("  Question with spaces  \n", callback=mock_callback)
        assert received_question[0] == "Question with spaces"

    def test_user_response_stripped(self):
        """User response should be stripped of whitespace."""
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            return "  response with spaces  \n"

        result = json.loads(clarify_tool("Q?", callback=mock_callback))
        assert result["user_response"] == "response with spaces"


class TestCheckClarifyRequirements:
    """Tests for the requirements check function."""

    def test_always_returns_true(self):
        """clarify tool has no external requirements."""
        assert check_clarify_requirements() is True


class _RecordingCallback:
    """Callback tripwire that records every invocation."""

    def __init__(self, answer: str = "routed-answer") -> None:
        self.calls: list = []
        self._answer = answer

    def __call__(self, question, choices):
        self.calls.append((question, choices))
        return self._answer


@pytest.fixture
def accepted_turn_policy():
    """Provide one Stable accepted-turn policy plus durable revision."""
    import model_tools  # noqa: F401 — ensures clarify is registered

    policy = ExecutionPolicy.for_mode("turn-clarify-routing", "read_only")
    token = set_current_execution_policy(policy, policy_revision=11)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class TestClarifyRegistryRouting:
    """ERB-406: every clarify path traverses the registry shadow boundary."""

    def test_registered_handler_refuses_without_bound_callback(self):
        import model_tools  # noqa: F401

        entry = registry.get_entry("clarify")
        assert entry is not None
        result = json.loads(entry.handler({"question": "Anyone there?"}))
        assert "not available" in result["error"].lower()

    def test_registered_handler_ignores_smuggled_callback_kwarg(self):
        """A callable smuggled through dispatch kwargs must never run."""
        import model_tools  # noqa: F401

        smuggled = _RecordingCallback()
        entry = registry.get_entry("clarify")
        result = json.loads(
            entry.handler({"question": "Q?"}, callback=smuggled)
        )
        assert "not available" in result["error"].lower()
        assert smuggled.calls == []

    def test_legacy_registry_dispatch_cannot_reach_a_callback(self):
        """Outside the routed binding the callback seam stays closed."""
        import model_tools  # noqa: F401

        result = json.loads(registry.dispatch("clarify", {"question": "Q?"}))
        assert "not available" in result["error"].lower()

    def test_routed_dispatch_without_identity_matches_legacy_behavior(self):
        """No accepted-turn policy: legacy dispatch result, callback once."""
        import model_tools  # noqa: F401

        callback = _RecordingCallback("blue")
        result = json.loads(
            dispatch_clarify_via_registry(
                {"question": "What color?"},
                callback=callback,
            )
        )
        assert result == {
            "question": "What color?",
            "choices_offered": None,
            "user_response": "blue",
        }
        assert callback.calls == [("What color?", None)]

    def test_routed_dispatch_traverses_atomic_boundary(
        self, monkeypatch, accepted_turn_policy
    ):
        """With durable identity the call is captured by execute_shadow."""
        callback = _RecordingCallback("2")
        captured = {}
        real_execute_shadow = registry.execute_shadow

        def spy(name, args, **kwargs):
            outcome = real_execute_shadow(name, args, **kwargs)
            captured["name"] = name
            captured["context"] = outcome.prepared.context
            captured["args_digest"] = outcome.prepared.args_digest
            captured["policy"] = outcome.prepared.execution_policy
            captured["started"] = outcome.started
            return outcome

        monkeypatch.setattr(registry, "execute_shadow", spy)
        result = json.loads(
            dispatch_clarify_via_registry(
                {"question": "Pick a number", "choices": ["1", "2"]},
                callback=callback,
                task_id="task-clarify",
                session_id="session-clarify",
                tool_call_id="call-clarify-1",
            )
        )

        assert result == {
            "question": "Pick a number",
            "choices_offered": ["1", "2"],
            "user_response": "2",
        }
        assert callback.calls == [("Pick a number", ["1", "2"])]
        assert captured["name"] == "clarify"
        assert captured["started"] is True
        assert captured["policy"] is accepted_turn_policy
        assert captured["context"].session_id == "session-clarify"
        assert captured["context"].invocation_id == "call-clarify-1"
        assert captured["context"].accepted_turn_id == "turn-clarify-routing"
        assert captured["context"].policy_revision == 11
        assert isinstance(captured["args_digest"], str)
        assert len(captured["args_digest"]) == 64

    def test_callback_binding_is_cleared_after_routed_dispatch(self):
        import model_tools  # noqa: F401

        callback = _RecordingCallback()
        dispatch_clarify_via_registry({"question": "Q?"}, callback=callback)
        assert len(callback.calls) == 1

        # The seam must be closed again once the routed dispatch returns.
        after = json.loads(registry.dispatch("clarify", {"question": "Q?"}))
        assert "not available" in after["error"].lower()
        assert len(callback.calls) == 1

    def test_stale_registration_fails_closed_without_callback(
        self, monkeypatch, accepted_turn_policy
    ):
        """A registration mutated between prepare and start never prompts."""
        callback = _RecordingCallback()
        entry = registry.get_entry("clarify")
        assert entry is not None
        real_prepare = registry.prepare_shadow

        def replace_after_preparation(name, args, **kwargs):
            prepared = real_prepare(name, args, **kwargs)
            if name == "clarify":
                # Same handler, new registration identity: the prepared
                # call's captured entry must be refused at start.
                registry.register(
                    name="clarify",
                    toolset=entry.toolset,
                    schema=entry.schema,
                    handler=entry.handler,
                    check_fn=entry.check_fn,
                    emoji=entry.emoji,
                )
            return prepared

        monkeypatch.setattr(registry, "prepare_shadow", replace_after_preparation)
        result = json.loads(
            dispatch_clarify_via_registry(
                {"question": "Should never prompt"},
                callback=callback,
                task_id="task-clarify",
                session_id="session-clarify",
                tool_call_id="call-clarify-stale",
            )
        )

        assert result["shadow_status"] == "stale_registration"
        assert callback.calls == []

    def test_exact_beta_denial_never_invokes_callback(
        self, monkeypatch, accepted_turn_policy
    ):
        """Undeclared clarify is refused before its callback in exact Beta."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        callback = _RecordingCallback()
        result = json.loads(
            dispatch_clarify_via_registry(
                {"question": "Should never prompt"},
                callback=callback,
                task_id="task-clarify",
                session_id="session-clarify",
                tool_call_id="call-clarify-beta",
            )
        )

        assert result["shadow_status"] == "effect_policy_block"
        assert callback.calls == []


class TestClarifySchema:
    """Tests for the OpenAI function-calling schema."""

    def test_schema_name(self):
        """Schema should have correct name."""
        assert CLARIFY_SCHEMA["name"] == "clarify"

    def test_schema_has_description(self):
        """Schema should have a description."""
        assert "description" in CLARIFY_SCHEMA
        assert len(CLARIFY_SCHEMA["description"]) > 50

    def test_schema_question_required(self):
        """Question parameter should be required."""
        assert "question" in CLARIFY_SCHEMA["parameters"]["required"]

    def test_schema_choices_optional(self):
        """Choices parameter should be optional."""
        assert "choices" not in CLARIFY_SCHEMA["parameters"]["required"]

    def test_schema_choices_max_items(self):
        """Schema should specify max items for choices."""
        choices_spec = CLARIFY_SCHEMA["parameters"]["properties"]["choices"]
        assert choices_spec.get("maxItems") == MAX_CHOICES

    def test_max_choices_is_four(self):
        """MAX_CHOICES constant should be 4."""
        assert MAX_CHOICES == 4
