import threading

from run_agent import AIAgent


def _agent_stub() -> AIAgent:
    agent = object.__new__(AIAgent)
    agent.quiet_mode = True
    agent.log_prefix = ""
    agent._pending_soft_interrupts = []
    agent._pending_soft_interrupts_lock = threading.Lock()
    return agent


def test_soft_interrupt_injects_into_recent_tool_result():
    agent = _agent_stub()
    assert agent.queue_soft_interrupt("also check the photos")

    messages = [
        {"role": "user", "content": "run the CMA"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "collected MLS data"},
    ]

    assert agent._apply_pending_soft_interrupts_to_tool_results(messages, 1) is True
    assert "User follow-up received" in messages[-1]["content"]
    assert "also check the photos" in messages[-1]["content"]
    assert agent._drain_pending_soft_interrupts() == []


def test_soft_interrupt_waits_when_no_current_tool_result():
    agent = _agent_stub()
    assert agent.queue_soft_interrupt("wait for approval")

    messages = [{"role": "user", "content": "start"}]

    assert agent._apply_pending_soft_interrupts_to_tool_results(messages, None) is False
    pending = agent._drain_pending_soft_interrupts()
    assert pending[0]["content"] == "wait for approval"


def test_soft_interrupt_display_text_strips_internal_wrapper():
    items = [
        {"content": "focus on seller objections", "source": "dashboard_steer"},
        {"content": "ignore generic marketing advice", "source": "dashboard_steer"},
    ]

    model_text = AIAgent._soft_interrupt_text(items)
    display_text = AIAgent._soft_interrupt_display_text(items)

    assert "User follow-up received" in model_text
    assert display_text == (
        "focus on seller objections\n\nignore generic marketing advice"
    )


def test_steer_display_content_persists_user_text_only():
    class FakeDB:
        def __init__(self):
            self.rows = []

        def ensure_session(self, *args, **kwargs):
            return None

        def append_message(self, **kwargs):
            self.rows.append(kwargs)

    agent = _agent_stub()
    agent.persist_session = True
    agent._session_db = FakeDB()
    agent.session_id = "child-1"
    agent.platform = "test"
    agent.model = "gpt-test"
    agent._last_flushed_db_idx = 0
    agent._persist_user_message_idx = None
    agent._persist_user_message_override = None
    messages = [
        {
            "role": "user",
            "content": "User follow-up received while you were already working:\n"
            "- focus on seller objections\n"
            "Fold this into the current task before continuing.",
            "client_message_id": "steer.abc123",
            "_display_content": "focus on seller objections",
        }
    ]

    agent._flush_messages_to_session_db(messages)

    assert agent._session_db.rows[0]["client_message_id"] == "steer.abc123"
    assert agent._session_db.rows[0]["content"] == "focus on seller objections"
