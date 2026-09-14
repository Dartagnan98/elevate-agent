"""Step 2 of the compaction redesign — the payload-build seam.

``AIAgent.messages_for_api(api_messages, sys_offset)`` is the ONE place the
compaction cursor + synthetic summary touch the wire.  These tests pin its
shape:

  payload = system/prefill leaders + [summary?] + transcript[cursor:]

and prove the invariants the redesign depends on:
  - cursor 0 / no summary is a pure pass-through (legacy / no-compaction)
  - the input ``api_messages`` list is never mutated (transcript is sacred)
  - the synthetic summary is exactly ONE user message carrying SUMMARY_PREFIX
  - tool pairs are never split: an orphan tool result at the cut is repaired
"""

import types

from run_agent import AIAgent
from agent.context_compressor import SUMMARY_PREFIX


def _agent(cursor, summary, prefill=None):
    """Minimal stand-in carrying just the attrs messages_for_api reads."""
    agent = types.SimpleNamespace(
        compaction_cursor=cursor,
        compaction_summary=summary,
        ephemeral_system_prompt=None,
        prefill_messages=prefill or [],
        _plan_mode_suffix=lambda: "",
    )
    agent.messages_for_api = types.MethodType(AIAgent.messages_for_api, agent)
    return agent


def _call(self_obj, api_messages, sys_offset):
    # Bind the unbound instance method to the stand-in self.
    return AIAgent.messages_for_api(self_obj, api_messages, sys_offset)


def _transcript(n):
    """n alternating user/assistant transcript messages."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"m{i}"})
    return out


# ---------------------------------------------------------------------------
# Sentinel / pass-through
# ---------------------------------------------------------------------------

def test_cursor_zero_is_passthrough():
    sys = {"role": "system", "content": "S"}
    api = [sys] + _transcript(6)
    out = _call(_agent(0, "anything"), list(api), sys_offset=1)
    assert out == api  # untouched


def test_no_summary_is_passthrough():
    sys = {"role": "system", "content": "S"}
    api = [sys] + _transcript(6)
    out = _call(_agent(3, None), list(api), sys_offset=1)
    assert out == api


# ---------------------------------------------------------------------------
# Core shape: system + summary + tail
# ---------------------------------------------------------------------------

def test_payload_is_system_summary_tail():
    sys = {"role": "system", "content": "S"}
    transcript = _transcript(8)  # m0..m7
    api = [sys] + list(transcript)
    out = _call(_agent(4, "EARLIER WORK"), api, sys_offset=1)

    # leader preserved
    assert out[0] == sys
    # exactly one synthetic summary, role=user, carrying the prefix
    assert out[1]["role"] == "user"
    assert out[1]["content"].startswith(SUMMARY_PREFIX)
    assert "EARLIER WORK" in out[1]["content"]
    assert "END OF CONTEXT SUMMARY" in out[1]["content"]
    # tail is transcript[4:] verbatim
    assert out[2:] == transcript[4:]
    # total = 1 system + 1 summary + 4 tail
    assert len(out) == 6


def test_pressure_payload_is_system_summary_tail_without_mutating():
    transcript = _transcript(8)
    transcript[5]["reasoning"] = "hidden chain"
    snapshot = [dict(m) for m in transcript]
    agent = _agent(4, "EARLIER WORK")

    out = AIAgent._messages_for_compression_pressure(agent, transcript, "S")

    assert transcript == snapshot
    assert [m["role"] for m in out].count("system") == 1
    assert out[0] == {"role": "system", "content": "S"}
    assert out[1]["role"] == "user"
    assert out[1]["content"].startswith(SUMMARY_PREFIX)
    assert "EARLIER WORK" in out[1]["content"]
    assert out[2:] == [
        {
            k: v
            for k, v in msg.items()
            if k not in {"reasoning", "finish_reason", "_thinking_prefill"}
        }
        for msg in transcript[4:]
    ]


def test_transcript_input_is_not_mutated():
    sys = {"role": "system", "content": "S"}
    transcript = _transcript(8)
    api = [sys] + list(transcript)
    snapshot = [dict(m) for m in api]
    _call(_agent(4, "summary"), api, sys_offset=1)
    # The caller's list object is read, not rewritten in place.
    assert api == snapshot


def test_summary_prefix_not_double_wrapped():
    sys = {"role": "system", "content": "S"}
    api = [sys] + _transcript(6)
    pre_wrapped = f"{SUMMARY_PREFIX}\nalready wrapped"
    out = _call(_agent(2, pre_wrapped), api, sys_offset=1)
    # Prefix appears exactly once at the start.
    assert out[1]["content"].count(SUMMARY_PREFIX) == 1


# ---------------------------------------------------------------------------
# sys_offset accounts for prefill leaders
# ---------------------------------------------------------------------------

def test_sys_offset_counts_prefill():
    sys = {"role": "system", "content": "S"}
    prefill = {"role": "user", "content": "PREFILL"}
    transcript = _transcript(8)
    # system + prefill + transcript, sys_offset = 2
    api = [sys, prefill] + list(transcript)
    out = _call(_agent(3, "summary"), api, sys_offset=2)
    assert out[0] == sys
    assert out[1] == prefill
    assert out[2]["role"] == "user" and out[2]["content"].startswith(SUMMARY_PREFIX)
    # tail starts at transcript[3]
    assert out[3:] == transcript[3:]


# ---------------------------------------------------------------------------
# Tool-pair safety: never ship an orphan tool result
# ---------------------------------------------------------------------------

def test_orphan_tool_result_at_cut_is_repaired():
    sys = {"role": "system", "content": "S"}
    # transcript: u, a(tool_call), tool, a, u, a  — if cursor lands on the
    # `tool` message its parent assistant was skipped → orphan. The guard must
    # walk the cut back so the kept window has no orphan tool result.
    transcript = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a2"},
    ]
    api = [sys] + list(transcript)
    # cursor=2 would put the cut at transcript[2] = the orphan tool result.
    out = _call(_agent(2, "summary"), api, sys_offset=1)
    # First kept transcript message after the summary must NOT be a bare tool
    # result (no preceding assistant tool_call in the kept window).
    kept = out[2:]
    assert kept[0]["role"] != "tool", f"shipped orphan: {kept[0]}"


def test_cursor_at_or_past_end_does_not_drop_everything():
    sys = {"role": "system", "content": "S"}
    transcript = _transcript(4)
    api = [sys] + list(transcript)
    # cursor == len(transcript) would skip the whole tail; clamp keeps >=1 msg.
    out = _call(_agent(4, "summary"), api, sys_offset=1)
    # Either a pass-through or a clamped trim, but never system+summary only.
    tail = [m for m in out if m.get("content", "").startswith("m")]
    assert len(tail) >= 1
