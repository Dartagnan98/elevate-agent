from run_agent import AIAgent


class _FakeAgent:
    _emit_warning = AIAgent._emit_warning
    _emit_status = AIAgent._emit_status
    _status_category_key = staticmethod(AIAgent._status_category_key)

    def __init__(self):
        self.calls = []
        self.quiet_mode = True
        self.log_prefix = ""
        self.status_callback = lambda kind, message: self.calls.append((kind, message))
        self._status_throttle_s = 0.0

    def _should_start_quiet_spinner(self):
        return False

    def _vprint(self, *_args, **_kwargs):
        raise AssertionError("quiet embedded warnings should not print")


def test_emit_warning_routes_to_lifecycle_status_without_raising():
    agent = _FakeAgent()

    agent._emit_warning("Compression aborted")

    assert agent.calls == [("lifecycle", "Compression aborted")]
