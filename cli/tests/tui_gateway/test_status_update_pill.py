"""Regression tests for FIX 1.2: the compaction pill must ride the
``status.update`` event channel, not a bare ``status`` event.

Root cause: ``tui_gateway/server.py:_run_direct_compress_slash`` (manual
``/compress``) used to fire ``_emit("status", ...)``. The frontend only
subscribes to ``status.update`` (no ``gw.on("status")`` listener), so the
"Compacting context" pill never rendered — the chat sat silent through the
~24-36s summary call until the result card popped.

The fix routes every pill through the module-level ``_status_update(sid, kind,
text)`` helper, which emits an event of type EXACTLY ``status.update`` with
``payload = {"kind": ..., "text": ...}``.

These tests prove, deterministically and with no network / LLM / real
``~/.elevate`` access:

  1. (unit) ``_status_update(sid, "compacting_context", "Compacting context")``
     calls ``_emit`` with event type EXACTLY ``"status.update"`` and text
     EXACTLY ``"Compacting context"``.
  2. (source) ``_run_direct_compress_slash`` contains NO bare
     ``_emit("status", ...)`` and routes its pills through ``_status_update``.
  3. (end-to-end) invoking ``_run_direct_compress_slash`` with a light fake
     session/agent (no network) emits the compacting + compacted pills on the
     ``status.update`` channel and emits NO bare ``status`` event.
"""

import importlib
import inspect

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def server():
    """Import tui_gateway.server with its heavy boot-time deps stubbed.

    Mirrors tests/tui_gateway/test_protocol.py so import does not touch the
    real elevate home, env loader, or state db.
    """
    with patch.dict("sys.modules", {
        "elevate_constants": MagicMock(
            get_elevate_home=MagicMock(return_value="/tmp/elevate_test")
        ),
        "elevate_cli.env_loader": MagicMock(),
        "elevate_cli.banner": MagicMock(),
        "elevate_state": MagicMock(),
    }):
        mod = importlib.import_module("tui_gateway.server")
        yield mod
        mod._sessions.clear()
        importlib.reload(mod)


# ──────────────────────────────────────────────────────────────────────
# 1. Unit: _status_update emits on the status.update channel
# ──────────────────────────────────────────────────────────────────────
def test_status_update_emits_status_update_event(server, monkeypatch):
    calls = []
    monkeypatch.setattr(
        server, "_emit", lambda event, sid, payload=None: calls.append((event, sid, payload))
    )

    server._status_update("sess-1", "compacting_context", "Compacting context")

    assert len(calls) == 1, f"expected exactly one _emit, got {calls!r}"
    event, sid, payload = calls[0]
    # Event type must be EXACTLY status.update — not bare "status".
    assert event == "status.update"
    assert event != "status"
    assert sid == "sess-1"
    assert payload == {"kind": "compacting_context", "text": "Compacting context"}
    # Text the frontend maps to setCompacting(true) must survive verbatim.
    assert payload["text"] == "Compacting context"


def test_status_update_release_pill_event(server, monkeypatch):
    """The release pill ('Session compacted') also rides status.update."""
    calls = []
    monkeypatch.setattr(
        server, "_emit", lambda event, sid, payload=None: calls.append((event, sid, payload))
    )

    server._status_update("sess-9", "session_compacted", "Session compacted")

    assert calls == [
        ("status.update", "sess-9", {"kind": "session_compacted", "text": "Session compacted"})
    ]


def test_status_update_blank_body_noops(server, monkeypatch):
    """Empty/whitespace body must not emit anything (guards stray pills)."""
    calls = []
    monkeypatch.setattr(
        server, "_emit", lambda *a, **k: calls.append(a)
    )
    server._status_update("sess-1", "compacting_context", "   ")
    assert calls == []


# ──────────────────────────────────────────────────────────────────────
# 2. Source-level: no bare _emit("status", ...) in the compress handler
# ──────────────────────────────────────────────────────────────────────
def test_compress_slash_routes_pill_through_status_update(server):
    src = inspect.getsource(server._run_direct_compress_slash)

    # No bare "status" event anywhere in the handler (single or double quotes).
    assert '_emit("status"' not in src
    assert "_emit('status'" not in src

    # Both pill texts are emitted via _status_update.
    assert '_status_update(sid, "compacting_context", "Compacting context")' in src
    assert '_status_update(sid, "session_compacted", "Session compacted")' in src

    # _status_update is actually used (sanity vs. the grep above being vacuous).
    assert "_status_update(" in src

    # Every _emit call left in the handler targets a non-"status" channel
    # (session.identity / session.info), confirming the only status-channel
    # path is _status_update.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("_emit("):
            assert not stripped.startswith('_emit("status"'), stripped
            assert not stripped.startswith("_emit('status'"), stripped


# ──────────────────────────────────────────────────────────────────────
# 3. End-to-end: drive _run_direct_compress_slash with a fake session/agent
# ──────────────────────────────────────────────────────────────────────
class _FakeAgent:
    """Minimal agent stub — no network, no LLM, no real state.db."""

    compression_enabled = True
    model = "fake-model"
    tools = []
    session_id = "sess-e2e"  # == session["session_key"] → skips the _get_db branch
    _cached_system_prompt = "sys"

    def _compress_context(self, history, system_prompt, approx_tokens=0, focus_topic=None):
        # Drop one message so summarize_manual_compression reports a real change.
        return list(history[:-1]), None

    def _persist_session(self, compressed, _):
        # Persisting is a no-op in the harness (no DB).
        return None


def test_run_direct_compress_slash_emits_pill_on_status_update_channel(server, monkeypatch):
    calls = []
    monkeypatch.setattr(
        server, "_emit", lambda event, sid, payload=None: calls.append((event, payload))
    )
    # _session_info pulls usage/version/skills — keep it cheap and deterministic.
    monkeypatch.setattr(server, "_session_info", lambda agent: {"model": "fake-model"})

    import threading

    agent = _FakeAgent()
    session = {
        "agent": agent,
        "running": False,
        "session_key": "sess-e2e",
        "history_lock": threading.RLock(),
        "history": [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
            {"role": "assistant", "content": "four"},
        ],
        "history_version": 0,
    }

    out = server._run_direct_compress_slash("sess-e2e", session, "")

    events = [e for (e, _p) in calls]
    # No bare "status" event ever reaches the wire.
    assert "status" not in events, f"bare status event leaked: {events!r}"

    # The compacting + compacted pills both rode status.update with exact text.
    status_payloads = [p for (e, p) in calls if e == "status.update"]
    texts = [p["text"] for p in status_payloads]
    assert "Compacting context" in texts
    assert "Session compacted" in texts
    # "Compacting context" (setCompacting true) must precede the release.
    assert texts.index("Compacting context") < texts.index("Session compacted")

    # Sanity: the handler actually ran the compress and returned a summary card.
    assert "Compressed:" in out
    assert session["history_version"] == 1
    assert len(session["history"]) == 3
