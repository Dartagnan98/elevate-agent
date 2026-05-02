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
