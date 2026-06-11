"""Persistent agent worker — one resident ``ElevateCLI`` per agent, holding WARM
context across turns (the native equivalent of a Elevate PTY agent).

Unlike :mod:`tui_gateway.slash_worker` (which only runs ``/slash`` commands via
``process_command``), this worker runs FREE-FORM agent turns via
``ElevateCLI.chat`` — so a heartbeat, handoff, or inbound event is delivered as a
message into a session that remembers everything it did before, instead of a cold
one-shot ``run_agent`` that reloads context from files every time.

Protocol (JSON lines, same framing as slash_worker):
    stdin  : {"id": <int>, "message": "<free-form prompt>"}
    stdout : {"id": <int>, "ok": true, "output": "<agent reply>"}
           | {"id": <int>, "ok": false, "error": "<message>"}

The session key (``--session-key``, e.g. ``agent:outreach``) is passed to
``ElevateCLI(resume=...)`` so the conversation persists for the life of the process
AND survives a restart (resume reloads it). Supervised by the gateway exactly like
the slash worker (liveness via ``proc.poll()``, restart on death).

This module is intentionally NOT wired into dispatch yet — it is the foundation the
agent-session supervisor (cron/agent_sessions.py) and the ``ELEVATE_PERSISTENT_AGENTS``
routing switch build on. See docs/persistent-agent-sessions.md.
"""

import argparse
import contextlib
import io
import json
import os
import sys

from cli import ElevateCLI


def _turn(cli: ElevateCLI, message: str) -> str:
    """Run one free-form agent turn against the warm session; return the reply text."""
    msg = (message or "").strip()
    if not msg:
        return ""
    out = cli.chat(msg)
    return (out or "").rstrip() if isinstance(out, str) else str(out or "").rstrip()


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--session-key", required=True)
    p.add_argument("--model", default="")
    args = p.parse_args()

    os.environ["ELEVATE_SESSION_KEY"] = args.session_key
    # Resident agent sessions are non-interactive workers, not a TTY chat. Leave
    # ELEVATE_INTERACTIVE unset so chat() runs headless.

    # Construct the warm CLI with output suppressed (the agent's reply comes back
    # over the protocol, not stdout).
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cli = ElevateCLI(
            model=args.model or None,
            compact=True,
            resume=args.session_key,
            verbose=False,
        )

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            # Suppress any incidental stdout/stderr from the turn so the protocol
            # line is the ONLY thing on stdout.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                out = _turn(cli, req.get("message", ""))
            sys.stdout.write(json.dumps({"id": rid, "ok": True, "output": out}) + "\n")
            sys.stdout.flush()
        except Exception as e:  # noqa: BLE001 — report every failure over the protocol
            sys.stdout.write(json.dumps({"id": rid, "ok": False, "error": str(e)}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
