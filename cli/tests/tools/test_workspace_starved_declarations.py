"""Declarations that were truthful all along and simply had no ceiling.

Three surfaces were declared correctly by earlier packages and then starved:
nothing in any ceiling admitted the effect they declared, so they resolved,
authorized, and were denied — every time, silently, in normal operation.

* ``skill_view`` was UNDECLARED, so it resolved to UNKNOWN and no skill could
  ever be opened by the model. ``skills_list`` returns names and descriptions
  only, so a skill-driven request produced an empty template instead of work.
* memory retrieval declares ``{read:memory, write_local:memory}`` because
  provider reads persist retrieval telemetry, and ``write_local:memory`` was in
  no ceiling. Admitting it was NECESSARY but is NOT SUFFICIENT — see the
  memory section below, which pins what is still blocked and why.
* ``composio`` declares ``{read:composio, credential_access:composio}`` for a
  pure credentialed GET. ``credential_access:composio`` was in no ceiling, so
  the entitled connector catalog was unreachable.

These tests pin that each is now admitted under the workspace ceiling, that
each declaration is still honest about what it does, and that admitting them
did not drag in the outbound half of the same surfaces.
"""

from __future__ import annotations

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry

import tools.composio_tool  # noqa: F401  (registration side effect)
import tools.discord_tool  # noqa: F401
import tools.feishu_doc_tool  # noqa: F401
import tools.homeassistant_tool  # noqa: F401
import tools.memory_tool  # noqa: F401
import tools.skills_tool  # noqa: F401
import tools.todo_tool  # noqa: F401


def _workspace() -> ExecutionPolicy:
    return ExecutionPolicy.for_mode("turn-starved", ExecutionPolicyMode.WORKSPACE)


# ---------------------------------------------------------------------------
# skill_view — the model can open a skill again
# ---------------------------------------------------------------------------


def test_skill_view_is_declared_at_all():
    """Undeclared meant UNKNOWN meant denied under every ceiling."""
    entry = registry.get_entry("skill_view")
    assert entry is not None
    meta = registry.get_effect_metadata("skill_view")
    assert meta["declared"] is True


def test_skill_view_declares_the_read_and_the_usage_ledger_write():
    resolved = registry.resolve_effects("skill_view", {"name": "some-skill"})
    assert resolved == frozenset({
        Effect.parse("read:skills"),
        Effect.parse("read:files"),
        Effect.parse("write_local:skill_usage"),
    })


def test_skill_view_is_allowed_under_the_workspace_ceiling():
    decision = authorize_effects(
        _workspace(), registry.resolve_effects("skill_view", {"name": "s"})
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_skill_view_is_still_denied_under_read_only():
    """The usage-ledger write is a real write and read-only still refuses it."""
    decision = authorize_effects(
        ExecutionPolicy.for_mode("t", ExecutionPolicyMode.READ_ONLY),
        registry.resolve_effects("skill_view", {"name": "s"}),
    )
    assert decision.allowed is False
    assert decision.reason == "effect_not_allowed"


def test_skill_view_does_not_declare_execution_because_it_cannot_execute():
    """Inline-shell expansion is gated twice; if either gate goes, so does this.

    ``agent/skill_preprocessing.py`` requires BOTH the ``skills.inline_shell``
    config opt-in (default False) and ``not exact_realtor_beta_active()``, and
    ``run_inline_shell`` re-checks the channel itself. Pin both gates here so
    relaxing either one fails a test rather than silently granting the agent
    arbitrary shell execution through skill text.
    """
    import inspect

    from agent import skill_preprocessing

    source = inspect.getsource(skill_preprocessing.preprocess_skill_content)
    assert 'cfg.get("inline_shell", False)' in source
    assert "not exact_realtor_beta_active()" in source

    runner = inspect.getsource(skill_preprocessing.run_inline_shell)
    assert "if exact_realtor_beta_active():" in runner

    kinds = {
        effect.kind
        for effect in registry.resolve_effects("skill_view", {"name": "s"})
    }
    assert EffectKind.SPAWN not in kinds


def test_inline_shell_is_refused_under_beta_regardless_of_config(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    from agent.skill_preprocessing import preprocess_skill_content, run_inline_shell

    assert run_inline_shell("echo pwned", None, 5) == (
        "[inline-shell disabled in Realtor Beta]"
    )
    rendered = preprocess_skill_content(
        "before !`echo pwned` after",
        None,
        skills_cfg={"inline_shell": True, "template_vars": False},
    )
    assert rendered == "before !`echo pwned` after"


# ---------------------------------------------------------------------------
# memory — the agent can remember what it learned
# ---------------------------------------------------------------------------


MEMORY_READ_ACTIONS = ["search", "recall", "probe"]


def _memory_effects(tool: str, action: str):
    from agent.memory_manager import _beta_memory_tool_effects

    return _beta_memory_tool_effects(tool, {"action": action})


def test_memory_retrieval_is_still_declared_as_a_mixed_read_and_write():
    """Retrieval persists telemetry; the declaration must keep saying so."""
    for action in MEMORY_READ_ACTIONS:
        effects = _memory_effects("fact_store", action)
        if effects == {"unknown"}:  # action not in this build's read set
            continue
        assert "read:memory" in effects
        assert "write_local:memory" in effects


def test_memory_retrieval_is_now_reachable_under_the_workspace_ceiling():
    policy = _workspace()
    assert authorize_effects(policy, {"read:memory", "write_local:memory"}).allowed
    assert authorize_effects(policy, {"write_local:memory"}).allowed


def test_memory_was_genuinely_unreachable_under_the_old_ceilings():
    """Regression anchor: this is the bug that hid 319 stored facts."""
    for mode in (
        ExecutionPolicyMode.READ_ONLY,
        ExecutionPolicyMode.PLAN,
        ExecutionPolicyMode.DRAFT_ONLY,
    ):
        decision = authorize_effects(
            ExecutionPolicy.for_mode("t", mode),
            {"read:memory", "write_local:memory"},
        )
        assert decision.allowed is False


def test_memory_writes_stay_scoped_and_never_leave_the_machine():
    policy = _workspace()
    for outward in ("write_external:memory", "message_external", "spawn"):
        assert authorize_effects(policy, {outward}).allowed is False


def test_the_builtin_memory_tool_is_STILL_BLOCKED_and_here_is_why():
    """Honest pin on the limit of this change: memory recall is NOT restored.

    Two different surfaces are called "memory":

    * the memory-PROVIDER lane (``fact_store``/``fact_feedback``), which is
      inert under exact Beta regardless of any ceiling
      (``MemoryManager.has_tool`` returns False), and
    * the built-in ``memory`` tool, which is the one actually in every realtor
      profile's toolsets — and it is still UNDECLARED, so it resolves to
      UNKNOWN and is denied even under the workspace ceiling.

    Its declaration is blocked for a real reason, not an oversight:
    ``memory``'s add/replace path fires ``MemoryManager.on_memory_write``,
    which forwards to arbitrary external providers (honcho / mem0 / …) whose
    effect surface is unproven and may be remote. The write floor cannot be
    honestly bounded, so ERB-404 doctrine leaves it UNKNOWN.

    The repair is the same shape as the CRM mirror severance in this change:
    cut ``on_memory_write`` on ``write_external`` capability, then the built-in
    tool's effects ARE bounded to local memory files and it can declare
    ``write_local:memory`` truthfully. That is deliberately NOT done here —
    it is its own change with its own review.

    This test exists so nobody reads ``write_local:memory`` sitting in the
    ceiling and concludes the agent can remember things again. When the
    repair lands, this test fails and must be rewritten to assert the new,
    truthful declaration.
    """
    entry = registry.get_entry("memory")
    assert entry is not None
    assert entry.effects is None
    assert entry.effect_resolver is None

    resolved = registry.resolve_effects("memory", {"action": "add", "content": "x"})
    assert resolved == frozenset({Effect(EffectKind.UNKNOWN)})

    decision = authorize_effects(_workspace(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


def test_the_external_memory_bridge_is_inert_under_beta(monkeypatch):
    """The premise the future repair rests on, pinned now.

    ``on_memory_write`` short-circuits on the release channel before it
    reaches any provider, so under exact Beta the built-in memory tool's
    only reachable effect really is a local file write.
    """
    import inspect

    from agent.memory_manager import MemoryManager

    source = inspect.getsource(MemoryManager.on_memory_write)
    assert "if _exact_beta_memory_policy_active():" in source
    assert source.index("_exact_beta_memory_policy_active") < source.index(
        "for provider in self._providers"
    ), "the channel gate must precede every provider call"


# ---------------------------------------------------------------------------
# composio — the operator's own entitled connector catalog
# ---------------------------------------------------------------------------


def test_composio_declares_a_credentialed_read():
    entry = registry.get_entry("composio")
    assert entry is not None
    assert entry.effects == frozenset({
        Effect.parse("read:composio"),
        Effect.parse("credential_access:composio"),
    })


def test_composio_is_allowed_under_the_workspace_ceiling():
    decision = authorize_effects(
        _workspace(), registry.resolve_effects("composio", {"action": "accounts"})
    )
    assert decision.allowed is True


def test_only_composio_credentials_are_admitted():
    """Narrow on purpose: no evidence the Beta cohort needs the others, and
    each one widens the credential blast radius."""
    policy = _workspace()
    for other in (
        "credential_access:discord",
        "credential_access:feishu",
        "credential_access:homeassistant",
        "credential_access",
    ):
        assert authorize_effects(policy, {other}).allowed is False, other


@pytest.mark.parametrize(
    "tool",
    [
        "discord",
        "discord_admin",
        "ha_list_entities",
        "ha_get_state",
        "ha_list_services",
        "ha_call_service",
        "feishu_doc_read",
    ],
)
def test_other_credentialed_connectors_stay_refused(tool):
    entry = registry.get_entry(tool)
    assert entry is not None, f"{tool} is no longer registered — update this pin"
    resolved = registry.resolve_effects(tool, {"action": "list"})
    assert authorize_effects(_workspace(), resolved).allowed is False


# ---------------------------------------------------------------------------
# todo — a plan the realtor's DEFAULT mode can actually keep
# ---------------------------------------------------------------------------


def test_todo_plan_write_is_allowed_under_the_workspace_ceiling():
    resolved = registry.resolve_effects(
        "todo", {"todos": [{"id": "1", "content": "Call Dana", "status": "pending"}]}
    )
    assert resolved == frozenset({Effect.parse("write_local:session_plan")})
    assert authorize_effects(_workspace(), resolved).allowed is True


def test_todo_read_needs_no_write_capability():
    resolved = registry.resolve_effects("todo", {})
    assert resolved == frozenset({Effect.parse("read:session_plan")})
    assert authorize_effects(
        ExecutionPolicy.for_mode("t", ExecutionPolicyMode.READ_ONLY), resolved
    ).allowed is True


def test_the_realtor_default_mode_admits_the_plan_write(monkeypatch):
    """A ceiling that only worked in a non-default mode is not a fix."""
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    from tools.approval import execution_policy_for_permission_mode

    policy = execution_policy_for_permission_mode("turn-default", "default")
    resolved = registry.resolve_effects("todo", {"todos": []})
    assert authorize_effects(policy, resolved).allowed is True
