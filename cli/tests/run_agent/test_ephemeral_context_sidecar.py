"""Cross-turn cache stability via `_ephemeral_context` sidecar.

The memory-prefetch + plugin pre_llm_call hooks both inject "context" into
the current turn's user message at API-call time.  Historically that
injection was applied only in the API build loop and never written back —
so the same user message looked different across turns (turn N: bytes
with memory_v1; turn N+1: bare bytes).  That broke the Anthropic
prompt-cache prefix at every breakpoint at or after the affected position.

Fix (in `run_conversation`, near the prefetch block): when the combined
injection is non-empty, stash it on the user message dict as
`_ephemeral_context`.  The API build loop now re-attaches `_ephemeral_context`
to *any* user message that has one, not just the latest.  That makes the
prefix bytes reproducible across turns.

These tests pin the contract:
- the combined injection is stashed on the current-turn user message
- the API build loop appends `_ephemeral_context` (when present) to any
  user message's content, current or historical
- the sidecar field never leaks to the API request
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


CLI_ROOT = Path(__file__).resolve().parents[2]
RUN_AGENT_SRC = (CLI_ROOT / "run_agent.py").read_text(encoding="utf-8")


class TestSidecarNeverLeaksToDisk:
    """The sidecar is in-memory-only.  Any place that serializes messages
    must strip `_ephemeral_context` from user dicts first.  Without these
    pins, the field silently leaks to ~/.elevate/sessions/session_*.json
    on every turn — bloating disk and duplicating recalled-memory bytes
    in a place the commit message says is in-memory only.
    """

    def test_save_session_log_strips_sidecar_from_user(self) -> None:
        # Verify the strip is present in _save_session_log's clean loop.
        # We look for the elif/pop pattern, not just a substring of the
        # field name — must be inside the build loop, not a comment.
        assert (
            'elif msg.get("role") == "user" and "_ephemeral_context" in msg:'
            in RUN_AGENT_SRC
        ), (
            "_save_session_log must strip _ephemeral_context from user "
            "messages — otherwise the sidecar bytes leak to "
            "~/.elevate/sessions/session_*.json on every turn"
        )
        assert 'msg.pop("_ephemeral_context", None)' in RUN_AGENT_SRC, (
            "the strip must actually pop the sidecar (defense in depth: "
            "this substring appears in both the api-loop and session-log "
            "branches; we require at least one)"
        )

    def test_session_log_pop_is_inside_save_session_log(self) -> None:
        # Tighter check: the session-log strip happens between the
        # _save_session_log signature and the next def.  Without this,
        # someone could delete the strip and the prior test still passes
        # because the api-loop pop still exists in the file.
        idx_def = RUN_AGENT_SRC.index("def _save_session_log(")
        # Find the next "def " at a lower indent.
        rest = RUN_AGENT_SRC[idx_def:]
        next_def_rel = rest.index("\n    def ", 1)
        body = rest[:next_def_rel]
        assert (
            'msg.pop("_ephemeral_context", None)' in body
            or '"_ephemeral_context" in msg' in body
        ), (
            "_save_session_log body must strip _ephemeral_context — "
            "if the strip moves out of this method, the on-disk JSON "
            "starts accumulating sidecar bytes again"
        )


class TestSidecarSourceContract:
    """Source-level checks so even non-instantiable refactors keep the wiring."""

    def test_sidecar_field_set_after_prefetch(self) -> None:
        # Sidecar attach happens after both _ext_prefetch_cache and
        # _plugin_user_context are computed.  Order matters: bail early
        # otherwise we'd stash an incomplete injection.
        # prefetch_all is now submitted to a budgeted executor; anchor on the
        # submit reference rather than the old inline assignment.
        idx_prefetch = RUN_AGENT_SRC.index("self._memory_manager.prefetch_all")
        idx_attach = RUN_AGENT_SRC.index('_u["_ephemeral_context"] = _ephemeral_injection')
        assert idx_attach > idx_prefetch, (
            "_ephemeral_context sidecar must be stashed AFTER prefetch_all() so "
            "memory_v1 is included in the persisted bytes"
        )

    def test_api_loop_reads_sidecar_on_every_user_message(self) -> None:
        # The build loop must accept the sidecar on any user message, not
        # only the current-turn one — that's the whole point of the fix.
        # Use raw substring (indentation in the source uses 16 spaces, inside
        # the per-message build loop).
        api_loop_snippet = (
            'if msg.get("role") == "user":\n'
            '                    _eph = msg.get("_ephemeral_context") or ""\n'
            '                    if _eph:'
        )
        assert api_loop_snippet in RUN_AGENT_SRC, (
            "API build loop must read _ephemeral_context from msg, not from "
            "the current-turn injection vars"
        )

    def test_sidecar_stripped_from_api_message(self) -> None:
        # The sidecar field is internal — must never go on the wire.
        assert 'api_msg.pop("_ephemeral_context", None)' in RUN_AGENT_SRC, (
            "_ephemeral_context must be stripped from api_msg before send"
        )

    def test_memory_block_built_inside_run_conversation(self) -> None:
        # We expect build_memory_context_block to be invoked once per turn,
        # in the prefetch block — NOT inside the per-iteration API loop.
        # Counting occurrences is a coarse but durable check.
        count = RUN_AGENT_SRC.count("build_memory_context_block(_ext_prefetch_cache)")
        assert count == 1, (
            f"build_memory_context_block(_ext_prefetch_cache) should appear once "
            f"(in the sidecar-attach block), found {count}.  More than one means "
            f"we're re-building the fenced block inside the API loop, defeating "
            f"the sidecar's purpose."
        )


class TestSidecarBehavior:
    """Pure-function behavioral checks on the api_msg build pattern."""

    def _apply_sidecar_to_api_msg(self, msg: dict) -> dict:
        """Mirror the API-loop logic from run_agent.py for unit testing.

        Keep this in sync with the loop in run_conversation.
        """
        api_msg = msg.copy()
        if msg.get("role") == "user":
            _eph = msg.get("_ephemeral_context") or ""
            if _eph:
                _base = api_msg.get("content", "")
                if isinstance(_base, str):
                    api_msg["content"] = (
                        _base + "\n\n" + _eph if _base else _eph
                    )
        if "_ephemeral_context" in api_msg:
            api_msg.pop("_ephemeral_context", None)
        return api_msg

    def test_sidecar_appended_to_user_content(self) -> None:
        msg = {
            "role": "user",
            "content": "hello there",
            "_ephemeral_context": "<memory-context>recalled stuff</memory-context>",
        }
        api_msg = self._apply_sidecar_to_api_msg(msg)
        assert api_msg["content"] == (
            "hello there\n\n<memory-context>recalled stuff</memory-context>"
        )
        assert "_ephemeral_context" not in api_msg
        # Original message dict is untouched (only api_msg mutated)
        assert msg["content"] == "hello there"
        assert "_ephemeral_context" in msg

    def test_no_sidecar_means_no_injection(self) -> None:
        msg = {"role": "user", "content": "plain message"}
        api_msg = self._apply_sidecar_to_api_msg(msg)
        assert api_msg == {"role": "user", "content": "plain message"}

    def test_empty_sidecar_does_nothing(self) -> None:
        msg = {"role": "user", "content": "x", "_ephemeral_context": ""}
        api_msg = self._apply_sidecar_to_api_msg(msg)
        assert api_msg == {"role": "user", "content": "x"}

    def test_sidecar_ignored_on_non_user_role(self) -> None:
        msg = {
            "role": "assistant",
            "content": "response",
            "_ephemeral_context": "should-not-appear",
        }
        api_msg = self._apply_sidecar_to_api_msg(msg)
        # Sidecar still gets stripped (defense in depth), but never injected.
        assert api_msg["content"] == "response"
        assert "_ephemeral_context" not in api_msg

    def test_empty_base_uses_sidecar_only(self) -> None:
        # Edge: user submits an empty message (rare, but valid).  Avoid the
        # double-newline weirdness — sidecar becomes the entire content.
        msg = {"role": "user", "content": "", "_ephemeral_context": "ctx-only"}
        api_msg = self._apply_sidecar_to_api_msg(msg)
        assert api_msg["content"] == "ctx-only"

    def test_list_content_skips_injection(self) -> None:
        # Multimodal content: don't try to inject memory text into a content
        # list.  Mirrors the old behavior (isinstance check on str).
        msg = {
            "role": "user",
            "content": [{"type": "image", "source": "..."}],
            "_ephemeral_context": "ignored",
        }
        api_msg = self._apply_sidecar_to_api_msg(msg)
        # Content unchanged, sidecar stripped.
        assert api_msg["content"] == [{"type": "image", "source": "..."}]
        assert "_ephemeral_context" not in api_msg


class TestCacheControlOrdering:
    """cache_control breakpoints must be applied AFTER all message mutations.

    If sanitize/normalize/strip runs after cache markers are placed, inserted
    stubs or byte changes shift the prefix hash and every turn cache-misses.
    """

    def test_cache_control_applied_after_sanitize(self) -> None:
        idx_sanitize = RUN_AGENT_SRC.index("self._sanitize_api_messages(api_messages)")
        idx_cache = RUN_AGENT_SRC.index("apply_anthropic_cache_control(")
        assert idx_cache > idx_sanitize, (
            "apply_anthropic_cache_control must run AFTER _sanitize_api_messages — "
            "sanitize can insert/remove messages which shifts cache breakpoints"
        )

    def test_cache_control_applied_after_whitespace_normalize(self) -> None:
        idx_strip = RUN_AGENT_SRC.index('am["content"] = am["content"].strip()')
        idx_cache = RUN_AGENT_SRC.index("apply_anthropic_cache_control(")
        assert idx_cache > idx_strip, (
            "apply_anthropic_cache_control must run AFTER whitespace normalize — "
            "stripping changes bytes in messages that would get cache markers"
        )

    def test_cache_control_applied_after_surrogate_strip(self) -> None:
        idx_surr = RUN_AGENT_SRC.index("_sanitize_messages_surrogates(api_messages)")
        idx_cache = RUN_AGENT_SRC.index("apply_anthropic_cache_control(")
        assert idx_cache > idx_surr, (
            "apply_anthropic_cache_control must run AFTER surrogate sanitize — "
            "surrogate replacement changes bytes that affect prefix hashing"
        )


class TestCrossTurnByteStability:
    """The actual property the sidecar exists to provide.

    Build two consecutive API requests with the SAME historical user msg
    that carries `_ephemeral_context`.  The bytes at that position must be
    identical across requests — that's what makes the Anthropic
    cache_control prefix hash stable cross-turn.
    """

    def _build_api_messages(self, messages: list[dict]) -> list[dict]:
        out = []
        for msg in messages:
            api_msg = msg.copy()
            if msg.get("role") == "user":
                _eph = msg.get("_ephemeral_context") or ""
                if _eph:
                    _base = api_msg.get("content", "")
                    if isinstance(_base, str):
                        api_msg["content"] = (
                            _base + "\n\n" + _eph if _base else _eph
                        )
            if "_ephemeral_context" in api_msg:
                api_msg.pop("_ephemeral_context", None)
            out.append(api_msg)
        return out

    def test_historical_user_bytes_match_across_turns(self) -> None:
        # Turn N: user_N submitted with memory_v1 injection sidecar.
        user_N = {
            "role": "user",
            "content": "what's the weather",
            "_ephemeral_context": "<memory-context>known city: SF</memory-context>",
        }
        assistant_N = {"role": "assistant", "content": "sunny"}

        # Turn N API request:
        turn_N_msgs = [user_N, assistant_N]
        turn_N_api = self._build_api_messages(turn_N_msgs)

        # Turn N+1: user_N+1 added.  user_N still carries the same sidecar.
        user_N1 = {
            "role": "user",
            "content": "how about tomorrow",
            "_ephemeral_context": "<memory-context>known city: SF, last query: weather</memory-context>",
        }
        turn_N1_msgs = [user_N, assistant_N, user_N1]
        turn_N1_api = self._build_api_messages(turn_N1_msgs)

        # The user_N entry in turn N+1's request must be byte-identical to
        # the user_N entry in turn N's request.  This is what enables the
        # Anthropic cache to hit on any breakpoint at or after user_N.
        assert turn_N1_api[0] == turn_N_api[0]
        assert turn_N1_api[1] == turn_N_api[1]
        # And the new user message reflects its own (different) sidecar.
        assert (
            turn_N1_api[2]["content"]
            == "how about tomorrow\n\n<memory-context>known city: SF, last query: weather</memory-context>"
        )
