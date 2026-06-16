"""Skill-execution nudge: the "lists the skill steps then stops" fix.

When a skill is activated for a turn but the model narrates a plan in plain
text WITHOUT executing any tool, the loop used to treat "no tool calls" as
"turn complete" and end the turn (run_agent.py no-tool-call branch). The new
`_active_skill_stalled_before_acting` detector catches that, provider-agnostic,
so the gate nudges the model to continue instead of breaking.

These are pure-logic tests on the detector. They borrow the real method +
marker tuple from AIAgent onto a tiny stub so no full agent / network / config
is constructed.
"""

from run_agent import AIAgent


class _Stub:
    """Minimal carrier for the detector under test."""

    valid_tool_names = ["read_file", "write_file"]
    _SKILL_ACTIVATION_MARKERS = AIAgent._SKILL_ACTIVATION_MARKERS
    _active_skill_stalled_before_acting = (
        AIAgent._active_skill_stalled_before_acting
    )

    def _strip_think_blocks(self, text):
        # The real impl strips <think>...</think>; for these tests a passthrough
        # is enough (we never feed think blocks).
        return text or ""


def _stub(valid_tools=True):
    s = _Stub()
    if not valid_tools:
        s.valid_tool_names = []
    return s


# --- marker variants (all three activation paths) -------------------------

INVOKE = '[SYSTEM: The user has invoked the "cma" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]'
PRELOAD = '[SYSTEM: The user launched this CLI session with the "cma" skill preloaded. Treat its instructions as active guidance.]'
AUTOLOAD = '[SYSTEM: The "cma" skill is auto-loaded. Follow its instructions for this session.]'

PLAN = "Here's what I need to do: pull the active and sold comps, analyze the photos, then price and render the CMA report."


def _msgs(*, skill_marker=INVOKE, after=None):
    msgs = [{"role": "user", "content": skill_marker + "\n\nDo a CMA for 123 Test St."}]
    for m in after or []:
        msgs.append(m)
    return msgs


def test_fires_when_skill_active_and_no_tool_ran():
    """Skill activated, model planned in text, no tool ran -> nudge."""
    s = _stub()
    assert s._active_skill_stalled_before_acting(PLAN, _msgs()) is True


def test_fires_for_all_three_activation_markers():
    s = _stub()
    for marker in (INVOKE, PRELOAD, AUTOLOAD):
        assert (
            s._active_skill_stalled_before_acting(PLAN, _msgs(skill_marker=marker))
            is True
        ), marker


def test_no_fire_when_tool_ran_after_skill():
    """Once the skill is actually executing tools, do NOT nudge."""
    s = _stub()
    after = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "comps: ..."},
    ]
    assert s._active_skill_stalled_before_acting(PLAN, _msgs(after=after)) is False


def test_no_fire_when_no_skill_active():
    """No skill marker anywhere -> never a skill stall."""
    s = _stub()
    msgs = [{"role": "user", "content": "What's the weather like?"}]
    assert s._active_skill_stalled_before_acting(PLAN, msgs) is False


def test_no_fire_when_asking_user_a_question():
    """Trailing '?' means the model needs input — a valid place to stop."""
    s = _stub()
    q = "Which neighborhood should I pull comps from — Sahali or Aberdeen?"
    assert s._active_skill_stalled_before_acting(q, _msgs()) is False


def test_no_fire_on_empty_text():
    s = _stub()
    assert s._active_skill_stalled_before_acting("   ", _msgs()) is False
    assert s._active_skill_stalled_before_acting("", _msgs()) is False


def test_no_fire_without_tools_available():
    """No tools to execute -> nudging to 'run tool calls' is pointless."""
    s = _stub(valid_tools=False)
    assert s._active_skill_stalled_before_acting(PLAN, _msgs()) is False


def test_fires_again_on_a_later_stall_if_still_no_tools():
    """A second planning message (still no tool) is also a stall; the loop's
    own counter caps how many times the nudge actually fires."""
    s = _stub()
    after = [
        {"role": "assistant", "content": PLAN},
        {"role": "user", "content": "[System: Continue now. Execute the required tool calls...]"},
    ]
    # Still no tool role since the skill marker -> still a stall.
    assert s._active_skill_stalled_before_acting(PLAN, _msgs(after=after)) is True


def test_most_recent_skill_marker_wins():
    """A tool ran for an EARLIER skill, but a NEW skill just activated with no
    tool yet -> stall on the new one."""
    s = _stub()
    msgs = [
        {"role": "user", "content": AUTOLOAD.replace("cma", "outreach") + "\nrun outreach"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "done"},
        {"role": "user", "content": INVOKE + "\nnow do a CMA"},
    ]
    assert s._active_skill_stalled_before_acting(PLAN, msgs) is True


def test_non_string_content_is_skipped_safely():
    s = _stub()
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "multimodal"}]},
        {"role": "user", "content": INVOKE + "\ndo a CMA"},
    ]
    assert s._active_skill_stalled_before_acting(PLAN, msgs) is True
