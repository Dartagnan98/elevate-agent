"""Tests for the gateway status-heartbeat throttle.

``_emit_status`` fans every per-API-call ``⏳ Sending request…`` to
``status_callback``.  An agentic turn loops one API call per tool round,
so a long task pushes one heartbeat per iteration.  In the CLI/TUI that
is a status pill that overwrites itself in place (the repetition is
invisible); piped to a gateway with no overwrite (Telegram) each one
lands as its own message — a flood.

``agent.status_heartbeat_min_interval`` (env
``ELEVATE_STATUS_HEARTBEAT_INTERVAL``) throttles same-category repeats on
the ``status_callback`` path only.  Distinct state changes still pass
immediately, and the CLI ``_vprint`` path is never throttled.
"""
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_agent(status_heartbeat_min_interval=None):
    cfg = {"agent": {}}
    if status_heartbeat_min_interval is not None:
        cfg["agent"]["status_heartbeat_min_interval"] = status_heartbeat_min_interval

    with patch("run_agent.OpenAI"), \
         patch("elevate_cli.config.load_config", return_value=cfg):
        return AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )


# ── Config surface (mirrors test_api_turn_deadline_config.py) ────────────

def test_default_interval_is_30s(monkeypatch):
    monkeypatch.delenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", raising=False)
    assert _make_agent()._status_throttle_s == 30.0


def test_config_override(monkeypatch):
    monkeypatch.delenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", raising=False)
    assert _make_agent(status_heartbeat_min_interval=10)._status_throttle_s == 10.0
    assert _make_agent(status_heartbeat_min_interval="5")._status_throttle_s == 5.0


def test_zero_or_negative_disables(monkeypatch):
    monkeypatch.delenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", raising=False)
    assert _make_agent(status_heartbeat_min_interval=0)._status_throttle_s == 0.0
    assert _make_agent(status_heartbeat_min_interval=-9)._status_throttle_s == 0.0


def test_env_override_when_no_config(monkeypatch):
    monkeypatch.setenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", "15")
    assert _make_agent()._status_throttle_s == 15.0


def test_config_beats_env(monkeypatch):
    monkeypatch.setenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", "15")
    assert _make_agent(status_heartbeat_min_interval=45)._status_throttle_s == 45.0


def test_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("ELEVATE_STATUS_HEARTBEAT_INTERVAL", raising=False)
    assert _make_agent(status_heartbeat_min_interval="nope")._status_throttle_s == 30.0


# ── Category normalizer ─────────────────────────────────────────────────

def test_category_key_collapses_recurring_heartbeats():
    k = AIAgent._status_category_key
    assert k("⏳ Sending request…") == "sending request"
    # Differing per-occurrence counters collapse to one key.
    assert k("⏳ Retrying in 4.0s (attempt 2/3)...") == k(
        "⏳ Retrying in 1.5s (attempt 3/3)..."
    )
    assert k("⏳ Still working... (10 min elapsed — iteration 46/150)") == (
        "still working"
    )


def test_category_key_distinguishes_real_state_changes():
    k = AIAgent._status_category_key
    assert k("⏳ Sending request…") != k("🔐 Codex auth refreshed after 401")
    assert k("⏳ Sending request…") != k("⏳ Retrying in 2s (attempt 1/3)...")


# ── Throttle behavior on the status_callback path ───────────────────────

def _agent_with_clock(interval=30.0):
    agent = _make_agent(status_heartbeat_min_interval=interval)
    cb = MagicMock()
    agent.status_callback = cb
    agent.quiet_mode = True  # keep the _vprint path silent for these
    return agent, cb


def test_repeated_sending_request_collapses_to_one_within_window():
    """The exact bug: many ``⏳ Sending request…`` in a tool loop must
    reach the gateway once per window, not once per iteration."""
    agent, cb = _agent_with_clock(interval=30.0)
    fake = {"t": 1000.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        for _ in range(46):  # the user's 46-iteration turn
            agent._emit_status("⏳ Sending request…")
            fake["t"] += 1.0  # ~1s between API calls
    # 46 emits over 45s with a 30s window → 2 reach the gateway, not 46.
    assert cb.call_count == 2
    assert all(c.args == ("lifecycle", "⏳ Sending request…") for c in cb.call_args_list)


def test_same_category_different_detail_is_throttled():
    agent, cb = _agent_with_clock(interval=30.0)
    fake = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        agent._emit_status("⏳ Retrying in 4.0s (attempt 1/3)...")
        fake["t"] += 5.0
        agent._emit_status("⏳ Retrying in 8.0s (attempt 2/3)...")  # same cat
        fake["t"] += 5.0
        agent._emit_status("⏳ Retrying in 16.0s (attempt 3/3)...")  # same cat
    assert cb.call_count == 1  # only the first within the 30s window


def test_distinct_category_passes_immediately():
    """A genuine state change is never throttled, and an interleaved
    distinct category resets the dedupe so a following same-category emit
    passes again.  This is the intended contract: throttle kills a
    *consecutive* flood, not a transition back to normal.  ``A B A`` is
    three messages (not spam — it is: working → event → back to working);
    only ``A A A`` collapses."""
    agent, cb = _agent_with_clock(interval=30.0)
    fake = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        agent._emit_status("⏳ Sending request…")                       # A
        fake["t"] += 1.0
        agent._emit_status("🔐 Codex auth refreshed after 401. Retrying...")  # B
        fake["t"] += 1.0
        agent._emit_status("⏳ Sending request…")                       # A again
    assert cb.call_count == 3
    emitted = [c.args[1] for c in cb.call_args_list]
    assert "Sending request" in emitted[0]
    assert "Codex auth refreshed" in emitted[1]
    assert "Sending request" in emitted[2]


def test_only_consecutive_repeats_collapse_not_interleaved():
    """Lock the design: dedupe is against the *single last* category, so
    ``A A A`` → 1 but ``A B A B`` → 4.  In the real agentic loop the
    happy path emits only the ``Sending request`` heartbeat per
    iteration (every other _emit_status call site is an error/recovery
    path), so the flood is always consecutive and always collapses."""
    agent_aaa, cb_aaa = _agent_with_clock(interval=30.0)
    fake = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        for _ in range(3):
            agent_aaa._emit_status("⏳ Sending request…")
            fake["t"] += 1.0
    assert cb_aaa.call_count == 1  # A A A → 1

    agent_abab, cb_abab = _agent_with_clock(interval=30.0)
    fake2 = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake2["t"]):
        for _ in range(2):
            agent_abab._emit_status("⏳ Sending request…")
            fake2["t"] += 1.0
            agent_abab._emit_status("🗜️ Compressing context (1/3)...")
            fake2["t"] += 1.0
    assert cb_abab.call_count == 4  # A B A B → 4 (each differs from the last)


def test_same_category_passes_again_after_window():
    agent, cb = _agent_with_clock(interval=30.0)
    fake = {"t": 100.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        agent._emit_status("⏳ Sending request…")
        fake["t"] += 31.0  # window elapsed
        agent._emit_status("⏳ Sending request…")
    assert cb.call_count == 2  # liveness preserved: one beat per window


def test_throttle_disabled_emits_everything():
    agent, cb = _agent_with_clock(interval=0)  # disabled → legacy behavior
    fake = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]):
        for _ in range(5):
            agent._emit_status("⏳ Sending request…")
    assert cb.call_count == 5


def test_cli_vprint_path_is_never_throttled():
    """Throttle is gateway-only.  The CLI status pill overwrites in place,
    so it must keep receiving every heartbeat even while the callback is
    being collapsed."""
    agent, cb = _agent_with_clock(interval=30.0)
    agent.quiet_mode = False  # make the _vprint fan-out active
    fake = {"t": 0.0}
    with patch("run_agent.time.monotonic", lambda: fake["t"]), \
         patch.object(agent, "_vprint") as vp:
        for _ in range(4):
            agent._emit_status("⏳ Sending request…")
            fake["t"] += 1.0
    assert vp.call_count == 4          # CLI sees every one
    assert cb.call_count == 1          # gateway sees one within the window


def test_throttle_failure_never_swallows_a_status():
    """If anything in the throttle bookkeeping raises, the status must
    still reach the gateway (it must not be silenced by its own guard)."""
    agent, cb = _agent_with_clock(interval=30.0)
    with patch.object(
        AIAgent, "_status_category_key", side_effect=RuntimeError("boom")
    ):
        agent._emit_status("⏳ Sending request…")
    assert cb.call_count == 1


def test_callback_exception_is_swallowed():
    agent, cb = _agent_with_clock(interval=30.0)
    cb.side_effect = RuntimeError("gateway down")
    # Must not propagate — _emit_status never raises.
    agent._emit_status("⏳ Sending request…")
    assert cb.call_count == 1
