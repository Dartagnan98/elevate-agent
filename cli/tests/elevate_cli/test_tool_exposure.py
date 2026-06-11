"""Guard: tools that exist must actually reach the model.

The tool-exposure pipeline has multiple filter layers, and three separate
incidents came from the same class of gap — a tool defined and entitled but
silently stripped before the model saw it:

  1. data toolsets had no TOOLSETS entry -> resolve_toolset() returned [] ->
     platform subset-inference never enabled them (fixed b15723172);
  2. the TUI gateway's per-prompt tool profiles stripped the data tools from
     conversational turns (fixed 4a06c2253);
  3. the same profiles stripped delegation/agent_handoff, so the EA could
     neither query NOR hand off to a specialist (fixed 527818547).

These tests pin every layer so a regression fails the build instead of
shipping as "the agent says it can't query the database."
"""

from __future__ import annotations

import pytest


def _resolve(toolset: str) -> set[str]:
    # Import inside the test so tool modules register first via model_tools.
    import model_tools  # noqa: F401  (imports populate the registry)
    from toolsets import resolve_toolset

    return set(resolve_toolset(toolset))


def test_every_agent_loadout_toolset_resolves():
    """A toolset declared in an agent's loadout must resolve to >=1 tool,
    otherwise the specialist silently loses that capability at run time."""
    from elevate_cli.agent_hub import DEFAULT_AGENT_DEFS

    bad: dict[str, list[str]] = {}
    for agent in DEFAULT_AGENT_DEFS:
        missing = [ts for ts in (agent.get("toolsets") or []) if not _resolve(ts)]
        if missing:
            bad[str(agent.get("id"))] = missing
    assert not bad, f"agent loadout toolsets resolve to no tools: {bad}"


def test_every_configurable_toolset_resolves():
    """CONFIGURABLE_TOOLSETS keys must resolve; an empty resolution breaks the
    platform subset-inference that enables them (incident #1)."""
    from elevate_cli.tools_config import CONFIGURABLE_TOOLSETS

    empty = [key for key, _, _ in CONFIGURABLE_TOOLSETS if not _resolve(key)]
    # 'computer' / 'video' / plugin-style keys may be gated by optional deps;
    # only hard-fail on the ones that have no excuse to be empty.
    hard_fail = [k for k in empty if k not in {"computer", "video", "moa", "rl", "homeassistant", "spotify"}]
    assert not hard_fail, f"configurable toolsets resolve to no tools: {hard_fail}"


# The EA's contract: SEE the pipeline (read tools) and DELEGATE scoped work
# (delegation + handoff). Both must survive the gateway's per-prompt profile
# filter on every conversational profile, or the EA can only apologize.
_EA_REQUIRED_TOOLSETS = (
    "leads_overview",
    "deals_overview",
    "lead_status",
    "delegation",
    "agent_handoff",
)
_CONVERSATIONAL_PROFILES = ("gateway-followup", "skill-runner")


@pytest.mark.parametrize("profile", _CONVERSATIONAL_PROFILES)
def test_conversational_profiles_keep_ea_contract(profile):
    import tui_gateway.server as server

    keys = set(server._TUI_TOOL_PROFILES[profile])
    missing = [ts for ts in _EA_REQUIRED_TOOLSETS if ts not in keys]
    assert not missing, (
        f"TUI profile {profile!r} strips {missing} — the EA loses pipeline "
        "visibility/delegation in conversation (incidents #2/#3). Add them "
        "back to _TUI_TOOL_PROFILES."
    )


@pytest.mark.parametrize("profile", _CONVERSATIONAL_PROFILES)
def test_model_actually_sees_ea_tools(profile):
    """End-to-end: the model's final tool list (get_tool_definitions) must
    contain the EA tools under each conversational profile."""
    import tui_gateway.server as server
    from model_tools import get_tool_definitions

    toolsets = sorted(set(server._TUI_TOOL_PROFILES[profile]))
    defs = get_tool_definitions(enabled_toolsets=toolsets)
    names = {(d.get("function") or {}).get("name") or d.get("name", "") for d in defs}
    expected = {"leads_overview", "deals_overview", "lead_status", "delegate_task", "agent_handoff"}
    missing = sorted(expected - names)
    assert not missing, (
        f"model tool list under profile {profile!r} is missing {missing} "
        f"(got {sorted(n for n in names if n)})"
    )


def test_specialist_boundary_holds():
    """elevate_db (raw SQL) and admin_deal (writes) must NOT leak into the
    conversational profiles — they're the Admin specialist's tools, reached
    via delegation only."""
    import tui_gateway.server as server

    for profile in _CONVERSATIONAL_PROFILES:
        keys = set(server._TUI_TOOL_PROFILES[profile])
        leaked = keys & {"elevate_db", "admin_deal"}
        assert not leaked, f"specialist-only toolsets leaked into {profile!r}: {leaked}"
