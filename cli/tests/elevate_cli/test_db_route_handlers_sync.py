"""G2 — DB-bound dashboard routes must not block the event loop.

FastAPI runs `async def` handlers inline on the event loop and only offloads
plain `def` handlers to its worker threadpool. A handler that opens the
synchronous `connect()` from inside `async def` freezes the entire dashboard
(and the status poller / SSE streams) for the duration of the query. Every
route that touches the operational DB must therefore be a plain `def`.

This invariant test also guards against regressions: add a new `async def`
DB handler and this fails.
"""

from __future__ import annotations

import inspect

from elevate_cli import web_server


def test_db_bound_route_handlers_do_not_block_event_loop():
    offenders = []
    sync_db_handlers = 0
    for route in web_server.app.routes:
        ep = getattr(route, "endpoint", None)
        if ep is None:
            continue
        src_file = inspect.getsourcefile(ep) or ""
        # Routes migrated from the web_server.py monolith into web_routes/
        # modules over time; matching only web_server.py left this guard
        # counting zero handlers (a vacuous pass on the offenders check).
        if not (
            "web_server.py" in src_file
            or "/web_routes/" in src_file
            or "web_agent_admin_routes.py" in src_file
        ):
            continue
        try:
            body = inspect.getsource(ep)
        except OSError:
            continue
        if "connect()" not in body:
            continue
        if inspect.iscoroutinefunction(ep):
            # An async DB handler is only safe if it actually awaits (i.e.
            # offloads the blocking work itself). A pure-sync body under
            # `async def` is the bug.
            if "await" not in body:
                offenders.append(getattr(route, "path", ep.__name__))
        else:
            sync_db_handlers += 1

    assert not offenders, f"async DB handlers block the event loop: {offenders}"
    # Guard against a vacuous pass if the route shape ever changes.
    assert sync_db_handlers >= 40, f"only found {sync_db_handlers} sync DB handlers"
