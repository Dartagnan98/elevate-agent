from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path

from fastapi import HTTPException, Request


# The CMA PDF download route accepts the session token via ?token= because
# window.open() can't attach an Authorization header. Scoped to this path only.
_CMA_PDF_PATH_RE = re.compile(r"^/api/(?:admin/)?deals/[^/]+/cma-pdf/?$")
_DRAFT_PDF_PATH_RE = re.compile(r"^/api/(?:admin/)?deals/[^/]+/run-draft-pdf/[^/]+/?$")


def load_session_token() -> str:
    env = os.environ.get("ELEVATE_DASHBOARD_SESSION_TOKEN")
    if env:
        return env.strip()
    try:
        path = os.path.join(os.path.expanduser("~"), ".elevate", "dashboard-session-token")
        if os.path.exists(path):
            existing = open(path, encoding="utf-8").read().strip()
            if existing:
                return existing
        token = secrets.token_urlsafe(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.chmod(path, 0o600)
        return token
    except Exception:
        return secrets.token_urlsafe(32)


def license_signed_in(*, license_path: Path) -> bool:
    """Return True iff a license.json with an unexpired access token exists."""
    try:
        with license_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False

    token = data.get("access_token")
    expires_at = data.get("expires_at")
    if not token or not isinstance(expires_at, (int, float)):
        return False
    return float(expires_at) > (time.time() + 30)


def has_valid_session_token(
    request: Request,
    *,
    session_header_name: str,
    session_token: str,
) -> bool:
    """True if the request carries a valid dashboard session token."""
    session_header = request.headers.get(session_header_name, "")
    if session_header and hmac.compare_digest(
        session_header.encode(),
        session_token.encode(),
    ):
        return True

    cookie_tok = request.cookies.get("elevate_session", "")
    if cookie_tok and hmac.compare_digest(
        cookie_tok.encode(),
        session_token.encode(),
    ):
        return True

    auth = request.headers.get("authorization", "")
    expected = f"Bearer {session_token}"
    if hmac.compare_digest(auth.encode(), expected.encode()):
        return True

    # New-tab opens (window.open) of a file download can't send headers, so
    # the CMA PDF route also accepts the same session token as a ?token= query
    # param. Scoped to that one read-only download path only — everything else
    # stays header/cookie-only.
    if _CMA_PDF_PATH_RE.match(request.url.path) or _DRAFT_PDF_PATH_RE.match(request.url.path):
        query_tok = request.query_params.get("token", "")
        if query_tok and hmac.compare_digest(
            query_tok.encode(),
            session_token.encode(),
        ):
            return True

    return False


def has_valid_run_token(
    request: Request,
    *,
    run_result_path_re: re.Pattern,
    run_token_header_name: str,
) -> bool:
    match = run_result_path_re.match(request.url.path)
    if not match:
        return False
    deal_id, run_id = match.groups()
    token = request.headers.get(run_token_header_name, "").strip()
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return False
    try:
        from elevate_cli.data import connect, verify_action_run_token

        with connect() as conn:
            return verify_action_run_token(
                conn,
                deal_id=deal_id,
                run_id=run_id,
                token=token,
            )
    except Exception:
        return False


def require_session_token(request: Request, *, has_valid_session_token_func) -> None:
    """Validate the ephemeral session token. Raises 401 on mismatch."""
    if not has_valid_session_token_func(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})


def is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to."""
    if not host_header:
        return False
    h = host_header.strip()
    if h.startswith("["):
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    if bound_host in ("0.0.0.0", "::"):
        return True

    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES

    return host_only == bound_lc


def safe_log_token(value: object, *, max_len: int = 96, log_token_re: re.Pattern) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return log_token_re.sub("_", text)[:max_len] or "-"


def request_id_for_log(
    request: Request,
    *,
    request_id_header_name: str,
    safe_log_token_func,
) -> str:
    incoming = safe_log_token_func(request.headers.get(request_id_header_name), max_len=96)
    return incoming if incoming != "-" else secrets.token_hex(8)


def session_id_for_log(
    request: Request,
    *,
    session_id_header_names: tuple[str, ...],
    request_session_path_re: re.Pattern,
    safe_log_token_func,
) -> str:
    for header in session_id_header_names:
        candidate = safe_log_token_func(request.headers.get(header), max_len=140)
        if candidate != "-":
            return candidate
    match = request_session_path_re.match(request.url.path)
    if match:
        return safe_log_token_func(urllib.parse.unquote(match.group(1)), max_len=140)
    return "-"
