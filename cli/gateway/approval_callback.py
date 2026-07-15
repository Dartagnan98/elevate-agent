"""Opaque, provider-safe identities for interactive approval callbacks."""

from __future__ import annotations

import re
import secrets
from collections.abc import Container


# Telegram limits callback_data to 64 bytes.  A 12-byte urlsafe token is
# exactly 16 ASCII characters, leaving ample room for ``ea:<choice>:``.
_APPROVAL_CALLBACK_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
_MAX_MINT_ATTEMPTS = 16


def is_approval_callback_nonce(value: object) -> bool:
    """Return whether *value* is one of our fixed-size opaque nonces."""
    return isinstance(value, str) and bool(_APPROVAL_CALLBACK_NONCE_RE.fullmatch(value))


def mint_approval_callback_nonce(existing: Container[str]) -> str:
    """Mint a fresh callback nonce, rejecting even improbable live collisions."""
    for _ in range(_MAX_MINT_ATTEMPTS):
        nonce = secrets.token_urlsafe(12)
        if is_approval_callback_nonce(nonce) and nonce not in existing:
            return nonce
    raise RuntimeError("could not mint a unique approval callback identity")
