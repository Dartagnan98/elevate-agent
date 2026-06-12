"""TUI per-message tool-profile narrowing is explicit opt-in ONLY.

The keyword classifier ("deals/transaction/mls" → skill-runner) used to run
by DEFAULT for dashboard chats — and skill-runner has terminal but no
browser, so "what deals are pending in webforms" produced a session that
truthfully had no browser tools and hand-rolled Selenium through the
terminal it did have. Worse, the mode reader fell back to
agent.gateway_tool_profile, where the platform fix writes "configured" —
which wasn't in the off-list and mapped straight back to auto.
"""

from __future__ import annotations

from unittest.mock import patch

import tui_gateway.server as srv


def _mode_with_cfg(cfg: dict) -> str:
    with patch.object(srv, "_load_cfg", return_value=cfg):
        return srv._load_tui_tool_profile_mode()


def test_default_is_full():
    assert _mode_with_cfg({}) == "full"
    assert _mode_with_cfg({"agent": {}}) == "full"


def test_gateway_tool_profile_configured_no_longer_maps_to_auto():
    # The 1.2.25 platform fix writes gateway_tool_profile: configured for
    # every install — that value must NOT re-enable TUI narrowing.
    assert _mode_with_cfg({"agent": {"gateway_tool_profile": "configured"}}) == "full"
    # Even an explicit platform-side auto stays a PLATFORM knob.
    assert _mode_with_cfg({"agent": {"gateway_tool_profile": "auto"}}) == "full"


def test_explicit_tui_auto_opts_in():
    assert _mode_with_cfg({"agent": {"tui_tool_profile": "auto"}}) == "auto"
    assert _mode_with_cfg({"display": {"tui_tool_profile": "auto"}}) == "auto"


def test_explicit_off_values_stay_full():
    for value in ("off", "full", "configured", "legacy", "nonsense"):
        assert _mode_with_cfg({"agent": {"tui_tool_profile": value}}) == "full"


class TestWidenToolsets:
    def _agent(self, toolsets, tools):
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent.enabled_toolsets = toolsets
        agent.disabled_toolsets = None
        agent.tools = tools
        agent.valid_tool_names = {
            t["function"]["name"] for t in tools if isinstance(t, dict)
        }
        return agent

    def test_none_toolsets_means_all_tools_no_widen(self):
        agent = self._agent(None, [])
        assert agent.widen_toolsets(["browser"]) is False

    def test_already_present_no_change(self):
        agent = self._agent(["web", "browser"], [])
        assert agent.widen_toolsets(["browser"]) is False

    def test_widen_rebuilds_surface_and_keeps_postinit_tools(self):
        plugin_tool = {"type": "function", "function": {"name": "my_plugin_tool"}}
        agent = self._agent(["todo"], [plugin_tool])
        rebuilt = [
            {"type": "function", "function": {"name": "todo"}},
            {"type": "function", "function": {"name": "browser_navigate"}},
        ]
        with patch("run_agent.get_tool_definitions", return_value=list(rebuilt)):
            assert agent.widen_toolsets(["browser"]) is True
        assert agent.enabled_toolsets == ["todo", "browser"]
        names = {t["function"]["name"] for t in agent.tools}
        # Rebuilt base AND the post-init plugin tool both survive.
        assert {"todo", "browser_navigate", "my_plugin_tool"} <= names
        assert "my_plugin_tool" in agent.valid_tool_names
