"""Wire message ids (Phase 2 of plans/chat-transcript-refactor.md).

The gateway mints a stable id per message and carries it on every
message.start/delta/complete event, the session.resume transcript, and the
prompt.submit ack — so the dashboard reconciles transcripts by identity
instead of content fingerprints.
"""

from types import SimpleNamespace
from unittest.mock import patch

from tui_gateway import server


class TestWireMessageId:
    def test_valid_client_id_passes_through(self):
        assert server._wire_message_id("abc-123_X.z") == "abc-123_X.z"

    def test_invalid_or_missing_mints_uuid_hex(self):
        for bad in (None, "", "has spaces", "x" * 65, 42, "emoji🙂"):
            minted = server._wire_message_id(bad)
            assert isinstance(minted, str) and len(minted) == 32
            assert server._WIRE_MESSAGE_ID_RE.match(minted)

    def test_mints_are_unique(self):
        assert server._wire_message_id() != server._wire_message_id()


class TestHistoryToMessages:
    def test_copies_client_message_id_to_wire(self):
        history = [
            {"role": "user", "content": "q", "client_message_id": "u-1"},
            {"role": "assistant", "content": "a", "client_message_id": "a-1"},
        ]
        out = server._history_to_messages(history)
        assert [m.get("message_id") for m in out] == ["u-1", "a-1"]

    def test_never_leaks_platform_message_id(self):
        """msg['message_id'] in HISTORY dicts is the external platform id
        (telegram/yuanbao). It must NOT become the wire transcript id."""
        history = [
            {"role": "user", "content": "from tg", "message_id": "tg-999"},
        ]
        out = server._history_to_messages(history)
        assert out[0].get("message_id") is None or "message_id" not in out[0]

    def test_client_id_wins_when_both_present(self):
        history = [
            {
                "role": "user",
                "content": "x",
                "message_id": "tg-1",
                "client_message_id": "ours-1",
            },
        ]
        out = server._history_to_messages(history)
        assert out[0]["message_id"] == "ours-1"

    def test_tool_messages_carry_ids(self):
        history = [
            {
                "role": "tool",
                "tool_call_id": "tc1",
                "tool_name": "web_search",
                "content": "result",
                "client_message_id": "t-1",
            },
        ]
        out = server._history_to_messages(history)
        assert out[0]["role"] == "tool"
        assert out[0]["message_id"] == "t-1"

    def test_idless_legacy_dicts_omit_the_field(self):
        out = server._history_to_messages([{"role": "user", "content": "old"}])
        assert "message_id" not in out[0]


class TestSignInNagStamping:
    def test_same_id_across_start_delta_complete(self):
        events = []
        with patch.object(server, "_emit", lambda *a: events.append(a)):
            server._emit_sign_in_nag("sid1")
        kinds = [e[0] for e in events]
        assert kinds == ["message.start", "message.delta", "message.complete"]
        ids = {e[2]["message_id"] for e in events}
        assert len(ids) == 1 and all(ids)


class TestAgentStamping:
    def _stamp(self, messages, turn_aid="turn-A"):
        from run_agent import AIAgent

        holder = SimpleNamespace(_turn_assistant_message_id=turn_aid)
        AIAgent._ensure_client_message_ids(holder, messages)
        return messages

    def test_final_content_assistant_gets_turn_id(self):
        msgs = [
            {"role": "user", "content": "q", "client_message_id": "u-1"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]},
            {"role": "tool", "tool_call_id": "t", "content": "out"},
            {"role": "assistant", "content": "final answer"},
        ]
        self._stamp(msgs)
        assert msgs[3]["client_message_id"] == "turn-A"
        # Intermediates minted, distinct, present.
        assert msgs[1]["client_message_id"] and msgs[2]["client_message_id"]
        assert msgs[1]["client_message_id"] != "turn-A"

    def test_idempotent_across_repeated_flushes(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "final"},
        ]
        self._stamp(msgs)
        first = [m["client_message_id"] for m in msgs]
        self._stamp(msgs)
        assert [m["client_message_id"] for m in msgs] == first

    def test_turn_id_applied_at_most_once(self):
        msgs = [
            {"role": "assistant", "content": "old final", "client_message_id": "turn-A"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "new final"},
        ]
        self._stamp(msgs)
        # turn-A already taken by the earlier message — the new final must NOT
        # duplicate it.
        assert msgs[2]["client_message_id"] != "turn-A"

    def test_interrupted_turn_no_content_assistant(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]},
        ]
        self._stamp(msgs)
        # No content-bearing final — turn id unused, but everything still ids.
        assert all(m.get("client_message_id") for m in msgs)
        assert all(m.get("client_message_id") != "turn-A" for m in msgs)
