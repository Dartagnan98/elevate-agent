"""Dashboard server startup helpers."""

import logging
import threading
import time
from typing import Any


def run_dashboard_server(
    app: Any,
    *,
    host: str,
    port: int,
    open_browser: bool,
    allow_public: bool,
    log: logging.Logger,
) -> None:
    import uvicorn

    localhost = ("127.0.0.1", "localhost", "::1")
    if host not in localhost and not allow_public:
        raise SystemExit(
            f"Refusing to bind to {host} — the dashboard exposes API keys "
            f"and config without robust authentication.\n"
            f"Use --insecure to override (NOT recommended on untrusted networks)."
        )
    if host not in localhost:
        log.warning(
            "Binding to %s with --insecure — the dashboard has no robust "
            "authentication. Only use on trusted networks.",
            host,
        )

    # Host and port feed the Host-header guard and embedded PTY websocket URL.
    app.state.bound_host = host
    app.state.bound_port = port

    if open_browser:
        import webbrowser

        def _open():
            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
