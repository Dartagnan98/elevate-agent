"""Exact-Beta containment for Leads-board outreach template inference."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli import template_suggester
from elevate_cli.beta_provider_policy import BetaProviderPolicyError
from elevate_cli.web_routes.outreach_templates import create_outreach_templates_router


def _response(text: str, *, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
                finish_reason=finish_reason,
            )
        ]
    )


@pytest.fixture
def beta_home(tmp_path, monkeypatch):
    home = tmp_path / "beta-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    (home / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai-codex": {
                        "tokens": {
                            "access_token": "profile-token",
                            "refresh_token": "profile-refresh",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic-key")
    for key in (
        "ELEVATE_INFERENCE_PROVIDER",
        "ELEVATE_MODEL",
        "ELEVATE_CODEX_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        template_suggester.outreach_db,
        "list_templates_grouped",
        lambda: {},
    )
    monkeypatch.setattr(template_suggester, "_voice_anchor", lambda: "Realtor voice")
    return home


def test_beta_suggestion_uses_canonical_auxiliary_boundary_not_anthropic(
    beta_home, monkeypatch
):
    import agent.auxiliary_client as auxiliary

    call = MagicMock(
        return_value=_response(
            '{"name":"Local Codex Variant","body":"Hi {first_name}, quick question?",'
            '"rationale":"Tests a direct question."}'
        )
    )
    monkeypatch.setattr(auxiliary, "call_llm", call)
    monkeypatch.setattr(
        template_suggester,
        "_call_anthropic",
        MagicMock(side_effect=AssertionError("Beta must not call Anthropic")),
    )
    monkeypatch.setattr(
        template_suggester.httpx,
        "Client",
        MagicMock(side_effect=AssertionError("Beta must not construct direct HTTP")),
    )
    persist = MagicMock(
        side_effect=lambda **candidate: {"id": "pending-1", **candidate}
    )
    monkeypatch.setattr(
        template_suggester.outreach_db, "create_pending_template", persist
    )

    candidate = template_suggester.suggest_and_save("new-outreach")

    assert candidate["id"] == "pending-1"
    assert candidate["name"] == "Local Codex Variant"
    assert candidate["body"] == "Hi {first_name}, quick question?"
    persist.assert_called_once_with(
        lane="new-outreach",
        name="Local Codex Variant",
        body="Hi {first_name}, quick question?",
        channel="any",
        rationale="Tests a direct question.",
    )
    assert call.call_args.kwargs["task"] == "outreach_template"
    assert call.call_args.kwargs["provider"] == "openai-codex"
    assert call.call_args.kwargs["messages"][0]["role"] == "system"
    assert call.call_args.kwargs["messages"][1]["role"] == "user"


@pytest.mark.parametrize(
    ("text", "finish_reason", "code"),
    [
        (
            '{"name":"Truncated","body":"Do not save"}',
            "length",
            "beta_outreach_generation_failed",
        ),
        ("", "stop", "beta_outreach_generation_failed"),
        ("not json", "stop", "beta_outreach_completion_invalid"),
    ],
)
def test_beta_requires_terminal_parseable_completion_before_persistence(
    beta_home, monkeypatch, text, finish_reason, code
):
    import agent.auxiliary_client as auxiliary

    monkeypatch.setattr(
        auxiliary,
        "call_llm",
        MagicMock(return_value=_response(text, finish_reason=finish_reason)),
    )
    persist = MagicMock()
    monkeypatch.setattr(
        template_suggester.outreach_db, "create_pending_template", persist
    )
    monkeypatch.setattr(
        template_suggester,
        "_call_anthropic",
        MagicMock(side_effect=AssertionError("Beta must not call Anthropic")),
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        template_suggester.suggest_and_save("new-outreach")

    assert exc.value.code == code
    persist.assert_not_called()


def test_beta_rejects_hostile_outreach_task_provider_before_client_or_persistence(
    beta_home, monkeypatch
):
    import agent.auxiliary_client as auxiliary

    (beta_home / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-codex\n"
        "  default: gpt-5.5\n"
        "auxiliary:\n"
        "  outreach_template:\n"
        "    provider: anthropic\n"
        "    base_url: https://attacker.invalid/v1\n"
        "    api_key: hostile-profile-key\n",
        encoding="utf-8",
    )
    persist = MagicMock()
    monkeypatch.setattr(
        template_suggester.outreach_db, "create_pending_template", persist
    )
    monkeypatch.setattr(
        template_suggester.httpx,
        "Client",
        MagicMock(side_effect=AssertionError("direct HTTP must not be constructed")),
    )
    monkeypatch.setattr(
        auxiliary,
        "OpenAI",
        MagicMock(side_effect=AssertionError("provider client must not be constructed")),
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        template_suggester.suggest_and_save("new-outreach")

    assert exc.value.code == "beta_provider_not_allowed"
    persist.assert_not_called()


def test_beta_route_exposes_typed_failure(monkeypatch):
    app = FastAPI()
    app.include_router(create_outreach_templates_router())
    monkeypatch.setattr(
        template_suggester,
        "suggest_and_save",
        MagicMock(
            side_effect=BetaProviderPolicyError(
                "Current-profile Codex did not complete; no template was saved.",
                code="beta_outreach_generation_failed",
            )
        ),
    )

    response = TestClient(app).post(
        "/api/outreach/templates/suggest",
        json={"lane": "new-outreach", "channel": "sms"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "beta_outreach_generation_failed"
    assert "no template was saved" in response.json()["detail"]["message"].lower()


def test_non_exact_beta_keeps_legacy_anthropic_or_heuristic_path(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setattr(
        template_suggester.outreach_db,
        "list_templates_grouped",
        lambda: {},
    )
    legacy = MagicMock(return_value=None)
    monkeypatch.setattr(template_suggester, "_call_anthropic", legacy)
    monkeypatch.setattr(
        template_suggester,
        "_call_beta_codex",
        MagicMock(side_effect=AssertionError("non-exact Beta must stay unchanged")),
    )

    candidate = template_suggester.suggest_variant("new-outreach")

    legacy.assert_called_once()
    assert candidate["rationale"].startswith("No Anthropic key configured")
