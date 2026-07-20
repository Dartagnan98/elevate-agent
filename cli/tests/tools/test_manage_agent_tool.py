"""Effect-resolver and hidden-bootstrap tests for the manage_agent tool.

``manage_agent`` is overwhelmingly a fleet-reconfiguration (write) tool. Only
its ``available``/``available_toolsets``/``catalog`` action is a genuine pure
read: it returns the valid toolset catalog from the static ``TOOLSETS`` map and
the in-process registry, touching no config file or filesystem. It resolves to
an exact ``read:agents``.

The deceptive part -- pinned here adversarially -- is ``list``/``get``: they
LOOK like reads but call ``load_config()`` -> ``ensure_elevate_home()``, which
mkdirs the profile and seeds ``SOUL.md`` on a cold home. That hidden bootstrap
keeps them (and every mutating/destructive/unknown action) unknown and denied
under a read-only policy.
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
from tools.manage_agent_tool import _manage_agent_effect_resolver, manage_agent
from tools.registry import registry

READ_AGENTS = frozenset({Effect.parse("read:agents")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

READ_ACTIONS = ["available", "available_toolsets", "catalog"]
# Deceptive "reads" that bootstrap, plus writes, destructive, and nonsense.
NON_READ_ACTIONS = [
    "list", "agents", "get", "show",
    "add_toolset", "add-toolset", "remove_toolset", "add_skill", "remove_skill",
    "set", "update", "configure", "create", "create_agent",
    "retire", "delete", "remove_agent",
    "", "frobnicate",
]


def _read_only():
    return ExecutionPolicy.for_mode(
        "turn-manage-agent-read", ExecutionPolicyMode.READ_ONLY
    )


def test_manage_agent_registers_a_resolver():
    entry = registry.get_entry("manage_agent")
    assert entry is not None
    assert entry.effects is None
    assert entry.effect_resolver is not None
    assert registry.get_effect_metadata("manage_agent") == {
        "declared": True,
        "effects": frozenset(),
        "has_resolver": True,
    }


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_catalog_actions_resolve_read_agents_and_are_allowed(action):
    resolved = registry.resolve_effects("manage_agent", {"action": action})
    assert resolved == READ_AGENTS
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.reason == "allowed"


@pytest.mark.parametrize("action", NON_READ_ACTIONS)
def test_non_read_actions_stay_unknown_and_denied(action):
    resolved = registry.resolve_effects("manage_agent", {"action": action})
    assert resolved == UNKNOWN
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_missing_and_none_args_are_unknown():
    assert registry.resolve_effects("manage_agent", {}) == UNKNOWN
    assert registry.resolve_effects("manage_agent", None) == UNKNOWN
    assert _manage_agent_effect_resolver(None) == {EffectKind.UNKNOWN}


def test_resolver_mirrors_handler_action_normalization():
    # The handler normalizes with .strip().lower().replace("-", "_"); the
    # resolver must classify the same normalized value, so alias/casing/dash
    # forms of the catalog read all resolve identically.
    for raw in ("available", "AVAILABLE", "  Catalog ", "available-toolsets"):
        assert _manage_agent_effect_resolver({"action": raw}) == {"read:agents"}
    # A dash/upper form of a WRITE action must still be unknown.
    for raw in ("ADD-TOOLSET", "Create", "  retire "):
        assert _manage_agent_effect_resolver({"action": raw}) == {EffectKind.UNKNOWN}


def test_available_is_a_pure_read_that_never_loads_config(monkeypatch):
    """`available` must classify AND behave as a pure read: no config load,
    hence no ensure_elevate_home bootstrap."""
    import elevate_cli.config as config_module

    calls = {"load_config": 0}

    def spy_load_config():
        calls["load_config"] += 1
        return {}

    monkeypatch.setattr(config_module, "load_config", spy_load_config)

    out = json.loads(manage_agent(action="available"))

    assert out["action"] == "available"
    assert isinstance(out["toolsets"], list)
    assert calls["load_config"] == 0


def test_list_reaches_the_config_bootstrap_path(monkeypatch):
    """Adversarial contrast: `list` LOOKS like a read but rides load_config
    (-> ensure_elevate_home mkdir + SOUL.md seed), which is exactly why the
    resolver leaves it unknown."""
    import elevate_cli.config as config_module

    calls = {"load_config": 0}

    def spy_load_config():
        calls["load_config"] += 1
        return {"agents": []}

    monkeypatch.setattr(config_module, "load_config", spy_load_config)

    manage_agent(action="list")

    # `list` rides load_config (>= 1 call) — the hidden ensure_elevate_home
    # bootstrap that disqualifies it as a pure read.
    assert calls["load_config"] >= 1
    # And the resolver correctly refuses to declare that path a read.
    assert registry.resolve_effects("manage_agent", {"action": "list"}) == UNKNOWN
