import json
import os
import signal
import sys
import time
import traceback
import re
import uuid
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from tui_gateway import server
from tui_gateway.server import _CRASH_LOG, dispatch, resolve_skin, write_json
from tui_gateway.transport import TeeTransport


def _install_sidecar_publisher() -> None:
    """Mirror every dispatcher emit to the dashboard sidebar via WS.

    Activated by `ELEVATE_TUI_SIDECAR_URL`, set by the dashboard's
    ``/api/pty`` endpoint when a chat tab passes a ``channel`` query param.
    Best-effort: connect failure or runtime drop falls back to stdio-only.
    """
    url = os.environ.get("ELEVATE_TUI_SIDECAR_URL")

    from elevate_constants import exact_realtor_beta_active

    exact_beta = exact_realtor_beta_active()
    if not url:
        if exact_beta:
            raise RuntimeError(
                "Realtor Beta terminal sessions must be launched from the Elevate app"
            )
        return

    from tui_gateway.event_publisher import WsPublisherTransport

    instance_values = parse_qs(urlsplit(url).query).get("instance", [])
    instance_id = instance_values[0] if len(instance_values) == 1 else ""
    if not re.fullmatch(r"[a-f0-9]{32}", instance_id):
        if exact_beta:
            raise RuntimeError(
                "dashboard sidecar instance identity is missing or invalid"
            )
        # Stable keeps supporting older/custom sidecar URLs that predate PTY
        # repair identity. Upgrade the URL locally without changing its event
        # semantics.
        instance_id = uuid.uuid4().hex
        parsed = urlsplit(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("instance", instance_id))
        url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    publisher = WsPublisherTransport(
        url,
        instance_id=instance_id,
        control_handler=server.handle_exact_beta_runtime_control,
        require_registration_ack=exact_beta,
    )
    if exact_beta and not publisher.connected:
        publisher.close()
        raise RuntimeError(
            "Realtor Beta terminal could not register with the Elevate app"
        )
    if exact_beta:
        server.install_exact_beta_sidecar_registration_check(
            lambda: publisher.connected
        )
    server._stdio_transport = TeeTransport(server._stdio_transport, publisher)


def _log_signal(signum: int, frame) -> None:
    """Capture WHICH thread and WHERE a termination signal hit us.

    SIG_DFL for SIGPIPE kills the process silently the instant any
    background thread (TTS playback, beep, voice status emitter, etc.)
    writes to a stdout the TUI has stopped reading.  Without this
    handler the gateway-exited banner in the TUI has no trace — the
    crash log never sees a Python exception because the kernel reaps
    the process before the interpreter runs anything.
    """
    name = {
        signal.SIGPIPE: "SIGPIPE",
        signal.SIGTERM: "SIGTERM",
        signal.SIGHUP: "SIGHUP",
    }.get(signum, f"signal {signum}")
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== {name} received · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            if frame is not None:
                f.write("main-thread stack at signal delivery:\n")
                traceback.print_stack(frame, file=f)
            # All live threads — signal may have been triggered by a
            # background thread (write to broken stdout from TTS, etc.).
            import threading as _threading
            for tid, th in _threading._active.items():
                f.write(f"\n--- thread {th.name} (id={tid}) ---\n")
                f.write("".join(traceback.format_stack(sys._current_frames().get(tid))))
    except Exception:
        pass
    print(f"[gateway-signal] {name}", file=sys.stderr, flush=True)
    sys.exit(0)


# SIGPIPE: ignore, don't exit. The old SIG_DFL killed the process
# silently whenever a *background* thread (TTS playback chain, voice
# debug stderr emitter, beep thread) wrote to a pipe the TUI had gone
# quiet on — even though the main thread was perfectly fine waiting on
# stdin.  Ignoring the signal lets Python raise BrokenPipeError on the
# offending write (write_json already handles that with a clean
# sys.exit(0) + _log_exit), which keeps the gateway alive as long as
# the main command pipe is still readable.  Terminal signals still
# route through _log_signal so kills and hangups are diagnosable.
signal.signal(signal.SIGPIPE, signal.SIG_IGN)
signal.signal(signal.SIGTERM, _log_signal)
signal.signal(signal.SIGHUP, _log_signal)
signal.signal(signal.SIGINT, signal.SIG_IGN)


def _log_exit(reason: str) -> None:
    """Record why the gateway subprocess is shutting down.

    Three exit paths (startup write fail, parse-error-response write fail,
    dispatch-response write fail, stdin EOF) all collapse into a silent
    sys.exit(0) here.  Without this trail the TUI shows "gateway exited"
    with no actionable clue about WHICH broken pipe or WHICH message
    triggered it — the main reason voice-mode turns look like phantom
    crashes when the real story is "TUI read pipe closed on this event".
    """
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== gateway exit · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· reason={reason} ===\n"
            )
    except Exception:
        pass
    print(f"[gateway-exit] {reason}", file=sys.stderr, flush=True)


def _warm_slash_completions():
    """Pre-scan skill commands in the background at startup.

    The first ``complete.slash`` RPC lazily triggers ``scan_skill_commands``;
    keeping that work off the request path prevents visible lag between
    typing ``/`` and seeing the command popover.
    """
    import threading

    def _scan():
        try:
            from agent.skill_commands import get_skill_commands

            get_skill_commands()
        except Exception:
            pass

    threading.Thread(target=_scan, daemon=True, name="warm-slash").start()


def main():
    # Persistent agent runtime (dashboard/TUI): post-turn scorecard inference
    # stays async so the UI stays snappy. One-shot runs (chat -q, cron) don't
    # mark themselves, so they drain the tick inline before exit.
    try:
        from agent.turn_attribution import mark_persistent_process

        mark_persistent_process()
    except Exception:
        pass
    _install_sidecar_publisher()

    if not write_json({
        "jsonrpc": "2.0",
        "method": "event",
        "params": {"type": "gateway.ready", "payload": {"skin": resolve_skin()}},
    }):
        _log_exit("startup write failed (broken stdout pipe before first event)")
        sys.exit(0)

    _warm_slash_completions()

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            if not write_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None}):
                _log_exit("parse-error-response write failed (broken stdout pipe)")
                sys.exit(0)
            continue

        method = req.get("method") if isinstance(req, dict) else None
        resp = dispatch(req)
        if resp is not None:
            if not write_json(resp):
                _log_exit(f"response write failed for method={method!r} (broken stdout pipe)")
                sys.exit(0)

    _log_exit("stdin EOF (TUI closed the command pipe)")


if __name__ == "__main__":
    main()
