"""Message Loop endpoint — GET /api/leads/message-loop.

Returns the daily conversation loop-closure report read from iMessage:
  - waiting_on_you  : they texted last with real content, no reply from Skyleigh
  - waiting_on_them : Skyleigh sent a real message, no reply yet (left hanging)
  - full_circle     : the thread closed naturally (ack / sign-off / reaction)

Read-only. Shells to the engine at ~/skyleigh-tools/scripts/message-loop-check.py
(reads ~/skyleigh-tools/data/messages.db). Powers the "Message Loop" button on
the /leads board.
"""
import json
import logging
import os
import subprocess

from fastapi import APIRouter

ENGINE = os.path.expanduser("~/skyleigh-tools/scripts/message-loop-check.py")
PYBIN = "/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3"

_EMPTY = {"waiting_on_you": [], "waiting_on_them": [], "full_circle": [],
          "counts": {"waiting_on_you": 0, "waiting_on_them": 0, "full_circle": 0}}


def create_message_loop_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/leads/message-loop")
    def get_message_loop(days: int = 2):
        try:
            out = subprocess.run(
                [PYBIN, ENGINE, "--days", str(int(days)), "--json"],
                capture_output=True, text=True, timeout=60,
            )
            line = (out.stdout or "").strip().splitlines()[-1] if out.stdout.strip() else "{}"
            data = json.loads(line)
            return {"ok": True, **data}
        except Exception as exc:  # never 500 the board — return an empty, ok=False shape
            _log.exception("message-loop: engine failed")
            return {"ok": False, "error": str(exc), **_EMPTY}

    return router
