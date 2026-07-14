"""Regression tests for the Discord /model picker.

Uses the shared discord mock from tests/gateway/conftest.py (installed
at collection time via _ensure_discord_mock()). Previously this file
installed its own mock at module-import time and clobbered sys.modules,
breaking other gateway tests under pytest-xdist.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from elevate_cli.beta_provider_policy import BetaProviderPolicyError
from gateway.platforms.discord import ModelPickerView


def _providers() -> list[dict]:
    return [
        {
            "slug": "openai-codex",
            "name": "OpenAI Codex",
            "models": ["gpt-5.5"],
            "total_models": 1,
            "is_current": True,
        }
    ]


def _view(on_model_selected) -> ModelPickerView:
    view = ModelPickerView(
        providers=_providers(),
        current_model="gpt-5.4",
        current_provider="openai-codex",
        session_key="session-beta",
        on_model_selected=on_model_selected,
        allowed_user_ids=set(),
    )
    view._selected_provider = "openai-codex"
    return view


def _interaction() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=123),
        channel_id=456,
        data={"values": ["gpt-5.5"]},
        response=SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
        ),
        edit_original_response=AsyncMock(),
    )


def _view_state(view: ModelPickerView) -> dict:
    def fingerprint(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return ("value", value)
        return ("identity", id(value))

    return {
        "dict_keys": tuple(sorted(view.__dict__)),
        "providers_id": id(view.providers),
        "providers": [dict(provider) for provider in view.providers],
        "current_model": view.current_model,
        "current_provider": view.current_provider,
        "session_key": view.session_key,
        "callback_id": id(view.on_model_selected),
        "allowed_user_ids": set(view.allowed_user_ids),
        "allowed_role_ids": set(view.allowed_role_ids),
        "resolved": view.resolved,
        "selected_provider": view._selected_provider,
        "children_list_id": id(view.children),
        "children": tuple(
            (
                id(child),
                tuple(
                    sorted(
                        (key, fingerprint(value))
                        for key, value in vars(child).items()
                    )
                ),
            )
            for child in view.children
        ),
    }


@pytest.mark.asyncio
async def test_model_picker_clears_controls_before_running_switch_callback(
    monkeypatch,
):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    events: list[object] = []

    async def on_model_selected(chat_id: str, model_id: str, provider_slug: str) -> str:
        events.append(("switch", chat_id, model_id, provider_slug))
        return "Model switched"

    async def edit_message(**kwargs):
        events.append(
            (
                "initial-edit",
                kwargs["embed"].title,
                kwargs["embed"].description,
                kwargs["view"],
            )
        )

    async def edit_original_response(**kwargs):
        events.append((
            "final-edit",
            kwargs["embed"].title,
            kwargs["embed"].description,
            kwargs["view"],
        ))

    view = ModelPickerView(
        providers=[
            {
                "slug": "copilot",
                "name": "GitHub Copilot",
                "models": ["gpt-5.4"],
                "total_models": 1,
                "is_current": True,
            }
        ],
        current_model="gpt-5-mini",
        current_provider="copilot",
        session_key="session-1",
        on_model_selected=on_model_selected,
        allowed_user_ids=set(),
    )
    view._selected_provider = "copilot"

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        channel_id=456,
        data={"values": ["gpt-5.4"]},
        response=SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
            edit_message=AsyncMock(side_effect=edit_message),
        ),
        edit_original_response=AsyncMock(side_effect=edit_original_response),
    )

    await view._on_model_selected(interaction)

    assert events == [
        ("initial-edit", "⚙ Switching Model", "Switching to `gpt-5.4`...", None),
        ("switch", "456", "gpt-5.4", "copilot"),
        ("final-edit", "⚙ Model Switched", "Model switched", None),
    ]
    interaction.response.edit_message.assert_awaited_once()
    interaction.response.defer.assert_not_called()
    interaction.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_beta_policy_failure_is_typed_and_preserves_exact_view_state(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    calls: list[tuple[str, str, str]] = []

    async def blocked(chat_id: str, model_id: str, provider_slug: str) -> str:
        calls.append((chat_id, model_id, provider_slug))
        raise BetaProviderPolicyError(
            "OpenAI Codex auth is required in this Beta profile.",
            code="beta_codex_auth_required",
        )

    view = _view(blocked)
    interaction = _interaction()
    before = _view_state(view)

    await view._on_model_selected(interaction)

    assert calls == [("456", "gpt-5.5", "openai-codex")]
    assert _view_state(view) == before
    interaction.response.defer.assert_awaited_once_with()
    interaction.response.send_message.assert_not_awaited()
    interaction.response.edit_message.assert_not_awaited()
    interaction.edit_original_response.assert_awaited_once()
    final = interaction.edit_original_response.await_args.kwargs
    assert final["embed"].title == "⚙ Model Switch Blocked"
    assert "[beta_codex_auth_required]" in final["embed"].description
    assert final["view"] is view


@pytest.mark.asyncio
async def test_beta_duplicate_click_during_failed_switch_runs_callback_once(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocked(_chat_id: str, _model_id: str, _provider_slug: str) -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        raise BetaProviderPolicyError(
            "Hostile provider state appeared during the switch.",
            code="beta_provider_not_allowed",
        )

    view = _view(blocked)
    first = _interaction()
    second = _interaction()
    before = _view_state(view)

    first_task = asyncio.create_task(view._on_model_selected(first))
    await started.wait()
    await view._on_model_selected(second)
    release.set()
    await first_task

    assert calls == 1
    second.response.send_message.assert_awaited_once_with(
        "Model switch already in progress~", ephemeral=True
    )
    second.response.defer.assert_not_awaited()
    second.edit_original_response.assert_not_awaited()
    assert _view_state(view) == before
    assert "[beta_provider_not_allowed]" in (
        first.edit_original_response.await_args.kwargs["embed"].description
    )


@pytest.mark.asyncio
async def test_beta_success_resolves_only_after_callback(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    events: list[str] = []

    async def switched(_chat_id: str, _model_id: str, _provider_slug: str) -> str:
        assert view.resolved is False
        assert view.children
        events.append("callback")
        return "Model switched"

    view = _view(switched)
    interaction = _interaction()
    interaction.response.defer.side_effect = lambda: events.append("defer")

    async def final_edit(**_kwargs):
        events.append("final")

    interaction.edit_original_response.side_effect = final_edit

    await view._on_model_selected(interaction)

    assert events == ["defer", "callback", "final"]
    assert view.resolved is True
    assert view.children == []
    assert "_beta_model_switch_in_flight" not in view.__dict__
    interaction.response.edit_message.assert_not_awaited()
    final = interaction.edit_original_response.await_args.kwargs
    assert final["embed"].title == "⚙ Model Switched"
    assert final["view"] is None


@pytest.mark.asyncio
async def test_non_exact_beta_keeps_stable_failure_behavior(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")

    async def stable_failure(_chat_id: str, _model_id: str, _provider_slug: str) -> str:
        raise ValueError("stable boom")

    view = _view(stable_failure)
    interaction = _interaction()

    await view._on_model_selected(interaction)

    assert view.resolved is True
    assert view.children == []
    interaction.response.defer.assert_not_awaited()
    initial = interaction.response.edit_message.await_args.kwargs
    assert initial["embed"].title == "⚙ Switching Model"
    assert initial["view"] is None
    final = interaction.edit_original_response.await_args.kwargs
    assert final["embed"].title == "⚙ Model Switched"
    assert final["embed"].description == "Error switching model: stable boom"
    assert final["view"] is None
