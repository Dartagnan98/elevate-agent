"""Effect-resolver and hidden-bootstrap tests for the discord tools.

``discord`` (core) and ``discord_admin`` share one dispatcher, one shared
credential (``DISCORD_BOT_TOKEN``), and one shared effect resolver. Their
GET-only actions read Discord over the REST API with the bot token, so the
truthful declaration is a credentialed read: ``read:discord`` +
``credential_access:discord`` (the ha_*/feishu_* precedent). Every write
action (pin/unpin/delete/create_thread/role changes) and any unrecognized
action stays ``UNKNOWN`` and fails closed.

The reads are only truthful after the repair that moved
``_load_allowed_actions_config`` off ``load_config`` (which calls
``ensure_elevate_home`` — a mkdir + SOUL.md seed on every action) onto the
bootstrap-free ``read_raw_config``. These tests pin BOTH the declaration and
that bootstrap-free property, including a cold-``ELEVATE_HOME``
declaration-rot guard: if anyone reroutes the allowlist read back through the
bootstrapping loader, the credentialed-read declaration silently becomes a lie.
"""

from __future__ import annotations

import json

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools import discord_tool
from tools.discord_tool import (
    _READ_ONLY_ACTIONS,
    _discord_effect_resolver,
    discord_admin_handler,
    discord_core,
)
from tools.registry import registry

READ_EFFECTS = frozenset(
    {Effect.parse("read:discord"), Effect.parse("credential_access:discord")}
)
READ_EFFECT_STRINGS = {"read:discord", "credential_access:discord"}
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

# GET-only reads (must match _READ_ONLY_ACTIONS exactly).
READ_ACTIONS = sorted(_READ_ONLY_ACTIONS)
# Mutating REST verbs + unroutable/odd-cased forms the handler never dispatches.
WRITE_ACTIONS = [
    "pin_message",
    "unpin_message",
    "delete_message",
    "create_thread",
    "add_role",
    "remove_role",
]
NON_READ_ACTIONS = WRITE_ACTIONS + [
    "",
    "frobnicate",
    "Fetch_Messages",  # exact-case: handler dict-lookup misses it, so must be UNKNOWN
    "FETCH_MESSAGES",
    " fetch_messages ",  # handler never strips, so this is not a known action
]


def _read_only():
    return ExecutionPolicy.for_mode("turn-discord-read", ExecutionPolicyMode.READ_ONLY)


def _default():
    return ExecutionPolicy.for_mode("turn-discord-default", ExecutionPolicyMode.DEFAULT)


# ── declaration / resolver ────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name", ["discord", "discord_admin"])
def test_both_tools_register_the_shared_resolver(tool_name):
    entry = registry.get_entry(tool_name)
    assert entry is not None
    assert entry.effect_resolver is _discord_effect_resolver
    meta = registry.get_effect_metadata(tool_name)
    assert meta["declared"] is True
    assert meta["has_resolver"] is True


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_read_actions_resolve_to_credentialed_read(action):
    assert _discord_effect_resolver({"action": action}) == READ_EFFECT_STRINGS


@pytest.mark.parametrize("action", NON_READ_ACTIONS)
def test_non_read_actions_stay_unknown(action):
    assert _discord_effect_resolver({"action": action}) == {EffectKind.UNKNOWN}


def test_missing_and_none_args_are_unknown():
    assert _discord_effect_resolver({}) == {EffectKind.UNKNOWN}
    assert _discord_effect_resolver(None) == {EffectKind.UNKNOWN}
    assert registry.resolve_effects("discord", {}) == UNKNOWN
    assert registry.resolve_effects("discord_admin", None) == UNKNOWN


def test_registry_resolves_core_and_admin_reads():
    # A core read (exposed by ``discord``) and an admin read (exposed by
    # ``discord_admin``) both resolve to the same credentialed read.
    assert registry.resolve_effects("discord", {"action": "fetch_messages"}) == READ_EFFECTS
    assert registry.resolve_effects("discord_admin", {"action": "list_guilds"}) == READ_EFFECTS


# ── authorization: credentialed read is DEFAULT-only ──────────────────────


@pytest.mark.parametrize(
    ("tool_name", "action"),
    [("discord", "fetch_messages"), ("discord_admin", "list_guilds")],
)
def test_read_is_denied_under_read_only(tool_name, action):
    resolved = registry.resolve_effects(tool_name, {"action": action})
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    # READ_ONLY's ceiling is a bare ``read`` — the credential effect is what
    # trips it, exactly like composio.
    assert decision.denied_effects == frozenset(
        {Effect.parse("credential_access:discord")}
    )
    assert decision.reason == "effect_not_allowed"


@pytest.mark.parametrize(
    ("tool_name", "action"),
    [("discord", "search_members"), ("discord_admin", "channel_info")],
)
def test_read_is_allowed_under_default(tool_name, action):
    resolved = registry.resolve_effects(tool_name, {"action": action})
    decision = authorize_effects(_default(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize(
    ("tool_name", "action"),
    [("discord", "create_thread"), ("discord_admin", "delete_message"), ("discord_admin", "add_role")],
)
def test_write_actions_are_unknown_and_denied_everywhere(tool_name, action):
    resolved = registry.resolve_effects(tool_name, {"action": action})
    assert resolved == UNKNOWN
    for policy in (_read_only(), _default()):
        decision = authorize_effects(policy, resolved)
        assert decision.allowed is False
        assert decision.reason == "unknown_effect"


# ── bootstrap-free proof (declaration-rot guards) ─────────────────────────


def _canned_discord_request():
    """Record (method, path) and return an empty GET payload."""
    calls: list[tuple[str, str]] = []

    def _fake(method, path, token, params=None, body=None, timeout=15):
        calls.append((method, path))
        # /messages returns a list; other GETs a dict — both empty is fine here.
        return [] if path.endswith("/messages") else {}

    _fake.calls = calls
    return _fake


def test_read_action_never_bootstraps_a_cold_home(monkeypatch, tmp_path):
    """A full read action on a cold ELEVATE_HOME must not materialize it.

    The declared read rides ``_load_allowed_actions_config`` ->
    ``read_raw_config`` (no ``ensure_elevate_home``). If a future edit reroutes
    it back through ``load_config``, running any GET action would mkdir the
    profile tree + seed SOUL.md — a hidden filesystem write under a declared
    read. This pins the bootstrap-free property empirically at the tool
    boundary.
    """
    cold_home = tmp_path / "cold-elevate-home"
    assert not cold_home.exists()
    monkeypatch.setenv("ELEVATE_HOME", str(cold_home))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")

    fake = _canned_discord_request()
    monkeypatch.setattr(discord_tool, "_discord_request", fake)

    result = json.loads(discord_core("fetch_messages", channel_id="123"))

    assert "error" not in result
    assert result["messages"] == []
    # The credentialed read is a GET — matches the declared surface.
    assert fake.calls and all(method == "GET" for method, _ in fake.calls)
    assert not cold_home.exists(), (
        "discord read bootstrapped ELEVATE_HOME via the allowlist config read"
    )


def test_read_path_never_calls_bootstrapping_load_config(monkeypatch):
    """The allowlist read must stay on ``read_raw_config``, never ``load_config``.

    ``load_config`` is the only config loader that calls ``ensure_elevate_home``.
    Detonating it and then running a full GET on both tools proves the read
    dispatch never touches the bootstrapping loader.
    """
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")

    def _explode():
        raise AssertionError(
            "discord read path called load_config (would ensure_elevate_home)"
        )

    monkeypatch.setattr("elevate_cli.config.load_config", _explode)
    fake = _canned_discord_request()
    monkeypatch.setattr(discord_tool, "_discord_request", fake)

    core = json.loads(discord_core("search_members", guild_id="g", query="a"))
    admin = json.loads(discord_admin_handler(action="list_guilds"))

    assert "error" not in core
    assert "error" not in admin
    assert fake.calls and all(method == "GET" for method, _ in fake.calls)
