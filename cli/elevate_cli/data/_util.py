"""Internal helpers shared by every table-level module.

Not exported from ``elevate_cli.data`` — call sites should import the
public per-table functions instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from elevate_cli.data.paths import payloads_root


# ─── Time + ids ────────────────────────────────────────────────────────


def now_iso() -> str:
    """UTC timestamp in ISO-8601 with explicit ``+00:00`` offset."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """UUIDv4 hex (32 chars, no dashes). Matches outreach.db's existing
    template/draft id format."""
    return uuid.uuid4().hex


# ─── Identifier normalization ──────────────────────────────────────────


_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
_PHONE_DIGITS_RE = re.compile(r"\D+")


def normalize_email(value: str | None) -> str | None:
    """Lowercase + strip. Returns ``None`` if blank or not email-shaped."""
    if not value:
        return None
    v = value.strip().lower()
    if not _EMAIL_RE.match(v):
        return None
    return v


def normalize_phone(value: str | None, *, default_country: str = "US") -> str | None:
    """Best-effort E.164 normalizer.

    We don't take a hard dependency on ``phonenumbers`` here — that'd
    pull a megabyte of metadata into every cron run. Strategy:

    * If the input already starts with ``+`` and has 8+ digits, keep
      digits-only and prepend ``+``.
    * If it has 10 digits, assume the default country (NANP for US/CA),
      prepend ``+1``.
    * If it has 11 digits and starts with ``1``, prepend ``+``.
    * Otherwise return ``None`` — caller treats that as "couldn't
      verify" and skips the deterministic auto-merge path.

    A future migration can swap this for ``phonenumbers`` without
    changing the data shape — call sites already trust the canonical
    form returned here.
    """
    if not value:
        return None
    raw = value.strip()
    has_plus = raw.startswith("+")
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if not digits:
        return None
    if has_plus and len(digits) >= 8:
        return f"+{digits}"
    if default_country.upper() in {"US", "CA"} and len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        # Best effort — caller can downgrade verified=0 in this case.
        return f"+{digits}"
    return None


def normalize_handle(value: str | None) -> str | None:
    """Strip leading ``@`` + lowercase. Used for IG/TikTok-style handles."""
    if not value:
        return None
    v = value.strip().lstrip("@").lower()
    return v or None


# ─── Hashing / event_hash ──────────────────────────────────────────────


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_event_hash(
    *,
    source_id: str,
    thread_key: str | None,
    ts: str,
    body: str | None,
) -> str:
    """Canonical formula from docs/source-keys.md.

    ``sha256(f"{source_id}|{thread_key}|{iso_ts}|{sha256(body or '')}")``

    For events without a natural thread (UI clicks, classification), the
    caller passes ``thread_key=None`` and a body string that uniquely
    identifies the action (e.g. ``f"classify:{contact_id}:{type}"``).
    """
    body_hash = sha256(body or "")
    payload = f"{source_id}|{thread_key or ''}|{ts}|{body_hash}"
    return sha256(payload)


# ─── Payload size policy ───────────────────────────────────────────────

_PAYLOAD_INLINE_LIMIT = 16 * 1024  # 16KB


def encode_payload(payload: Any) -> tuple[str | None, str | None]:
    """Return ``(payload_json, payload_ref)`` per the size policy.

    * ``None`` payload → ``(None, None)``.
    * ≤16KB → store inline as JSON, no spillover.
    * Larger → write to ``$ELEVATE_HOME/data/payloads/<hash>.json`` and
      return the relative path. ``payload_json`` then carries a small
      header stub so callers can still see what kind of thing landed.

    Files in ``payloads/`` are content-addressed by sha256 of the JSON
    body, so identical large payloads dedupe naturally.
    """
    if payload is None:
        return None, None
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) <= _PAYLOAD_INLINE_LIMIT:
        return encoded, None
    digest = sha256(encoded)
    rel = f"{digest[:2]}/{digest}.json"
    full = payloads_root() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    if not full.exists():
        full.write_text(encoded, encoding="utf-8")
    stub = json.dumps(
        {
            "_spilled": True,
            "size_bytes": len(encoded.encode("utf-8")),
            "sha256": digest,
        }
    )
    return stub, rel


def decode_payload(payload_json: str | None, payload_ref: str | None) -> Any:
    """Inverse of :func:`encode_payload`. Returns the original Python
    object, or ``None`` if neither slot is set."""
    if payload_ref:
        full = payloads_root() / payload_ref
        if full.exists():
            return json.loads(full.read_text(encoding="utf-8"))
        return None
    if payload_json is None:
        return None
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError:
        return payload_json
