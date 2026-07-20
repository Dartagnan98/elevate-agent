"""Effect and hidden-write tests for the composio introspection tool.

``composio`` exposes three actions -- ``status``, ``accounts``, ``toolkits``
(and a ``status`` default) -- each a credentialed HTTP GET against the Composio
API. It declares a static ``{read:composio, credential_access:composio}``: a
truthful credentialed read, not a read-only approval. These tests pin that the
declaration is exact, that the credential effect is denied under a read-only
policy but allowed by default, and -- adversarially -- that no action writes
the ``.env`` (``_get_or_create_user_id`` / ``save_env_value``), reaches the
write-capable ``execute_tool``, or issues any non-GET request.
"""

from __future__ import annotations

import json

import pytest

from elevate_cli import composio_client
from tools.approval import (
    Effect,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.composio_tool import composio_tool
from tools.registry import registry

EXPECTED = frozenset(
    {Effect.parse("read:composio"), Effect.parse("credential_access:composio")}
)
READ_ACTIONS = ("status", "accounts", "toolkits", "")  # "" -> handler default status


def test_composio_declares_exact_static_effects():
    entry = registry.get_entry("composio")
    assert entry is not None
    assert entry.effects == EXPECTED
    assert entry.effect_resolver is None
    assert registry.get_effect_metadata("composio") == {
        "declared": True,
        "effects": EXPECTED,
        "has_resolver": False,
    }
    # Static: identical for every argument shape, including unknown actions.
    for args in ({"action": "status"}, {"action": "toolkits"}, {}, {"action": "x"}):
        assert registry.resolve_effects("composio", args) == EXPECTED


def test_composio_is_denied_without_credential_capability():
    read_only = ExecutionPolicy.for_mode(
        "turn-composio-read", ExecutionPolicyMode.READ_ONLY
    )
    decision = authorize_effects(read_only, registry.resolve_effects("composio", {}))
    assert decision.allowed is False
    assert decision.denied_effects == frozenset(
        {Effect.parse("credential_access:composio")}
    )
    assert decision.reason == "effect_not_allowed"


def test_composio_is_allowed_by_default_policy():
    default = ExecutionPolicy.for_mode(
        "turn-composio-default", ExecutionPolicyMode.DEFAULT
    )
    decision = authorize_effects(default, registry.resolve_effects("composio", {}))
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.fixture
def fake_composio_http(monkeypatch):
    """Record every HTTP attempt and fail closed on any credential-writing call."""
    calls: list[tuple[str, str]] = []

    def fake_attempt(method, url, api_key, params, json_body):
        calls.append((method, url))
        # A single generic page: exhausts pagination and satisfies every reader.
        return {
            "ok": True,
            "data": {"items": [], "next_cursor": None},
            "status": 200,
        }

    def _forbidden(name):
        def _raise(*_a, **_k):
            raise AssertionError(f"read action must never call {name}")

        return _raise

    monkeypatch.setattr(composio_client, "_read_api_key", lambda: "fake-key")
    monkeypatch.setattr(composio_client, "_attempt_request", fake_attempt)
    monkeypatch.setattr(
        composio_client, "save_env_value", _forbidden("save_env_value")
    )
    monkeypatch.setattr(
        composio_client,
        "_get_or_create_user_id",
        _forbidden("_get_or_create_user_id"),
    )
    monkeypatch.setattr(composio_client, "execute_tool", _forbidden("execute_tool"))
    monkeypatch.setattr(composio_client, "set_api_key", _forbidden("set_api_key"))
    return calls


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_read_actions_issue_get_requests_only(fake_composio_http, action):
    out = json.loads(composio_tool(action=action or None))
    assert isinstance(out, dict)
    assert fake_composio_http, "expected at least one HTTP GET"
    assert all(method == "GET" for method, _url in fake_composio_http)


def test_accounts_action_never_creates_a_user_id(fake_composio_http):
    # `accounts` is the branch that, in execute_tool, would need a user id.
    # The read tool must not go anywhere near that write.
    out = json.loads(composio_tool(action="accounts"))
    assert out["action"] == "accounts"
    assert all(method == "GET" for method, _url in fake_composio_http)


def test_toolkit_search_is_get_only(fake_composio_http):
    out = json.loads(composio_tool(action="toolkits", search="gmail"))
    assert out["action"] == "toolkits"
    assert fake_composio_http == [("GET", composio_client.COMPOSIO_BASE_URL.rstrip("/") + "/api/v3/toolkits")]


def test_unknown_action_is_a_no_network_error(fake_composio_http):
    out = json.loads(composio_tool(action="delete-everything"))
    assert "error" in out
    # An unrecognized action returns the guidance error without any HTTP call.
    assert fake_composio_http == []
