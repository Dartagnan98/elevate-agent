"""Scale invariant: the compaction PAYLOAD stays bounded over a long session.

The cursor model never rewrites the transcript, so the stored/in-memory message
list grows without bound across a long session. The property that actually
matters for cost/latency/context-fit is that the model PAYLOAD (what
messages_for_api emits each turn) does NOT grow with session length — it
plateaus at summary + recent tail regardless of how many compactions have run.

This drives the real compress_context + messages_for_api through 10 compactions
on an ever-growing transcript (summary LLM mocked) and pins:
  - the cursor advances monotonically every compaction
  - the payload plateaus (it does not scale with transcript length)
  - the payload is a small fraction of the full transcript (the trim is real)
  - the iterative summary stays under the token ceiling
  - the transcript itself keeps growing (the documented tradeoff)
"""

import types
from unittest.mock import MagicMock, patch

from agent.context_compressor import (
    ContextCompressor,
    _SUMMARY_TOKENS_CEILING,
)
from agent.conversation_compression import compress_context
from agent.model_metadata import estimate_messages_tokens_rough
from run_agent import AIAgent


def _summary_response():
    # A realistic ~6K-char structured summary (the compressor clips/caps it).
    body = (
        "## Active Task\nContinue the audit.\n## Completed Actions\n"
        + "\n".join(f"{i}. did thing {i} [tool: x]" for i in range(1, 90))
        + "\n## Critical Context\n"
        + ("detail " * 400)
    )
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = body
    return r


def _make_compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=200000
    ):
        c = ContextCompressor(
            model="test/model",
            protect_first_n=3,
            protect_last_n=20,
            quiet_mode=True,
        )
    c.context_length = 200000
    c.threshold_tokens = 64000
    c.tail_token_budget = 12800  # 20% of threshold — recent tail kept verbatim
    return c


def _fake_agent(compressor):
    a = types.SimpleNamespace(
        session_id="scale-1", model="test/model", tools=None, _session_db=None,
        context_compressor=compressor, compaction_cursor=0, compaction_summary=None,
        _memory_manager=None, _compression_feasibility_checked=True,
        _cached_system_prompt="SYSTEM" * 200, _usage_projector=None, log_prefix="",
        status_callback=lambda *a, **k: None,
    )
    a._emit_status = lambda m: None
    a._emit_warning = lambda m: None
    a._touch_activity = lambda d: None
    a._vprint = lambda *a, **k: None
    a._build_system_prompt = lambda sm: "SYSTEM" * 200
    a.commit_memory_session = lambda m: None
    return a


def _add_turn(messages, n=24):
    base = len(messages)
    messages.append({"role": "user", "content": f"user turn at {base} " * 8})
    for i in range(n):
        messages.append({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": f"c{base}_{i}", "function": {"name": "read_file", "arguments": "{}"}}],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"c{base}_{i}", "content": ("filedata " * 300),
        })


def _payload_tokens(agent, messages):
    # mirror run_agent: api copy = system + transcript, then messages_for_api trims
    api = [{"role": "system", "content": agent._cached_system_prompt}] + [dict(m) for m in messages]
    trimmed = AIAgent.messages_for_api(agent, api, 1)
    return estimate_messages_tokens_rough(trimmed)


def test_payload_bounded_over_long_session():
    compressor = _make_compressor()
    agent = _fake_agent(compressor)
    messages = []
    cursors, payloads, summary_toks, rows = [], [], [], []

    N_COMPACTIONS = 10
    with patch(
        "agent.context_compressor.call_llm", side_effect=lambda *a, **k: _summary_response()
    ):
        for _ in range(N_COMPACTIONS):
            # grow the session until the trimmed payload crosses the threshold,
            # then compact (bounded inner loop as a safety net)
            for _guard in range(50):
                _add_turn(messages)
                if _payload_tokens(agent, messages) >= compressor.threshold_tokens:
                    break
            summary, _sp = compress_context(agent, messages, "SYSTEM")
            assert summary is not None  # each pass compacts
            cursors.append(agent.compaction_cursor)
            payloads.append(_payload_tokens(agent, messages))
            summary_toks.append(len(agent.compaction_summary or "") // 4)
            rows.append(len(messages))

    # 1. cursor advances monotonically every compaction
    assert all(cursors[i] < cursors[i + 1] for i in range(len(cursors) - 1)), cursors

    # 2. payload PLATEAUS — it does not scale with session length. Compare the
    #    settled region (after warmup) — spread must be tiny relative to the
    #    transcript growth over the same span.
    settled = payloads[2:]
    assert max(settled) - min(settled) < 5000, payloads
    # last payload is not meaningfully larger than the first settled one
    assert payloads[-1] <= payloads[2] * 1.25, payloads

    # 3. the trim is real: payload is a small fraction of the full transcript
    full = estimate_messages_tokens_rough(messages)
    assert payloads[-1] < full / 4, (payloads[-1], full)
    assert payloads[-1] < compressor.threshold_tokens  # stays under the trigger

    # 4. iterative summary stays under the token ceiling across all folds
    assert all(t <= _SUMMARY_TOKENS_CEILING for t in summary_toks), summary_toks

    # 5. the transcript itself grows (the documented tradeoff), never shrinks
    assert all(rows[i] < rows[i + 1] for i in range(len(rows) - 1)), rows
    assert rows[-1] > rows[0] * 5
