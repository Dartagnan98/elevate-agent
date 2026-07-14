"""Profile metadata is written only from a complete provider response."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _describe_with_response(
    tmp_path,
    *,
    finish_reason,
    content,
    tool_calls=None,
):
    from elevate_cli import profile_describer as mod

    profile_dir = tmp_path / "profiles" / "realtor"
    profile_dir.mkdir(parents=True, exist_ok=True)
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls,
                ),
            )
        ]
    )

    with (
        patch.object(
            mod.profiles_mod,
            "normalize_profile_name",
            return_value="realtor",
        ),
        patch.object(mod.profiles_mod, "profile_exists", return_value=True),
        patch.object(
            mod.profiles_mod,
            "get_profile_dir",
            return_value=profile_dir,
        ),
        patch.object(mod.profiles_mod, "read_profile_meta", return_value={}),
        patch.object(
            mod.profiles_mod,
            "_read_config_model",
            return_value=("test-model", "test-provider"),
        ),
        patch.object(mod, "_collect_skills", return_value=[]),
        patch.object(mod.profiles_mod, "write_profile_meta") as persist,
        patch(
            "agent.auxiliary_client.get_text_auxiliary_client",
            return_value=(client, "test-model"),
        ),
        patch(
            "agent.auxiliary_client.get_auxiliary_extra_body",
            return_value=None,
        ),
    ):
        outcome = mod.describe_profile("realtor")

    return outcome, persist, profile_dir


def test_length_response_never_persists_profile_description(tmp_path):
    outcome, persist, _ = _describe_with_response(
        tmp_path,
        finish_reason="length",
        content='{"description":"Parseable but truncated metadata"}',
    )

    assert outcome.ok is False
    assert "incomplete (length)" in outcome.reason
    persist.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        "I cannot determine this profile's capabilities from the supplied data.",
        '{"description":"unterminated}',
        'Here is the result: {"description":"Python specialist"}',
        '{"description":"Python specialist","confidence":0.8}',
    ],
)
def test_refusal_or_malformed_description_never_writes_profile_metadata(
    tmp_path,
    content,
):
    outcome, persist, _ = _describe_with_response(
        tmp_path,
        finish_reason="stop",
        content=content,
    )

    assert outcome.ok is False
    persist.assert_not_called()


def test_valid_structured_description_writes_auto_metadata(tmp_path):
    description = (
        "Prepares Canadian real-estate transaction documents and verifies "
        "province-specific compliance requirements."
    )
    outcome, persist, profile_dir = _describe_with_response(
        tmp_path,
        finish_reason="stop",
        content=json.dumps({"description": description}),
    )

    assert outcome.ok is True
    assert outcome.description == description
    persist.assert_called_once_with(
        profile_dir,
        description=description,
        description_auto=True,
    )


def test_unoffered_tool_call_never_writes_profile_metadata(tmp_path):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="not_offered", arguments="{}"),
    )
    outcome, persist, _ = _describe_with_response(
        tmp_path,
        finish_reason="stop",
        content=json.dumps({"description": "Looks structurally valid."}),
        tool_calls=[tool_call],
    )

    assert outcome.ok is False
    assert "unexpected tool call" in outcome.reason
    persist.assert_not_called()
