"""Verification for backend-signed Realtor Beta entitlement assertions.

The assertion is the sole authority for paid identity and entitlement fields in
the exact Realtor Beta release.  Access and refresh tokens are deliberately
bound into the signed claims so an assertion cannot be replayed with a
different local session.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key


ENTITLEMENT_ASSERTION_SCHEMA = 1
ENTITLEMENT_ASSERTION_TYPE = "elevate-entitlement+jwt"
ENTITLEMENT_ASSERTION_ISSUER = "https://api.elevationrealestatehq.com"
ENTITLEMENT_ASSERTION_AUDIENCE = "elevate-realtor-beta"
# The backend remains on A until the dual-key Beta has passed its adoption
# gate.  This value is retained for fixture/signing compatibility; verifiers
# trust the complete key ring below.
ENTITLEMENT_ASSERTION_KID = "ent-2026-07-a"
ENTITLEMENT_ASSERTION_PUBLIC_KEYS: dict[str, str] = {
    ENTITLEMENT_ASSERTION_KID: (
        "MCowBQYDK2VwAyEAexzoft6MmOXSkKHVJH4hBLgss5LN51wWaQ7bfUom1CQ="
    ),
    "ent-2026-07-b": (
        "MCowBQYDK2VwAyEA6ohPc76/T+8U0Wi+pK704Sc9a+dBBS77egvXHe8wYiA="
    ),
}
ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS = tuple(
    sorted(ENTITLEMENT_ASSERTION_PUBLIC_KEYS)
)
ENTITLEMENT_ASSERTION_KEYSET_SHA256 = (
    "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c"
)

_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TIER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CLAIM_KEYS = frozenset({
    "ath",
    "aud",
    "email",
    "entitlements",
    "exp",
    "iat",
    "iss",
    "jti",
    "license_id",
    "nbf",
    "rth",
    "schema",
    "sub",
    "tier",
})
_MAX_ASSERTION_BYTES = 128 * 1024
_CLOCK_SKEW_SECONDS = 30


class EntitlementAssertionError(ValueError):
    """A signed entitlement assertion was absent, malformed, or untrusted."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EntitlementAssertionClaims:
    subject: str
    license_id: str
    email: str
    tier: str
    entitlements: tuple[str, ...]
    issued_at: int
    not_before: int
    expires_at: int
    assertion_id: str
    access_token_hash: str
    refresh_token_hash: str


def token_binding_hash(token: str) -> str:
    """Return the assertion's unpadded base64url SHA-256 token binding."""
    if not isinstance(token, str) or not token:
        raise EntitlementAssertionError(
            "The entitlement assertion is not bound to a complete token pair.",
            code="beta_entitlement_token_missing",
        )
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _decode_base64url(segment: str, *, label: str) -> bytes:
    if not isinstance(segment, str) or not _BASE64URL_RE.fullmatch(segment):
        raise EntitlementAssertionError(
            f"The entitlement assertion {label} is not canonical base64url.",
            code="beta_entitlement_assertion_malformed",
        )
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, binascii.Error) as exc:
        raise EntitlementAssertionError(
            f"The entitlement assertion {label} is invalid.",
            code="beta_entitlement_assertion_malformed",
        ) from exc
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if not hmac.compare_digest(canonical, segment):
        raise EntitlementAssertionError(
            f"The entitlement assertion {label} is not canonical base64url.",
            code="beta_entitlement_assertion_malformed",
        )
    return decoded


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EntitlementAssertionError(
                    f"The entitlement assertion {label} repeats {key!r}.",
                    code="beta_entitlement_assertion_malformed",
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {value}")
            ),
        )
    except EntitlementAssertionError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise EntitlementAssertionError(
            f"The entitlement assertion {label} is not valid JSON.",
            code="beta_entitlement_assertion_malformed",
        ) from exc
    if not isinstance(value, dict):
        raise EntitlementAssertionError(
            f"The entitlement assertion {label} is not a JSON object.",
            code="beta_entitlement_assertion_malformed",
        )
    return value


def _required_text(
    claims: Mapping[str, Any],
    name: str,
    *,
    max_length: int = 256,
) -> str:
    value = claims.get(name)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(ord(char) < 0x20 for char in value)
    ):
        raise EntitlementAssertionError(
            f"The entitlement assertion has an invalid {name} claim.",
            code="beta_entitlement_claim_invalid",
        )
    return value


def _required_time(claims: Mapping[str, Any], name: str) -> int:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EntitlementAssertionError(
            f"The entitlement assertion has an invalid {name} claim.",
            code="beta_entitlement_claim_invalid",
        )
    return value


def _load_public_key(spki_der_base64: str) -> Ed25519PublicKey:
    try:
        der = base64.b64decode(spki_der_base64, validate=True)
        key = load_der_public_key(der)
    except Exception as exc:
        raise EntitlementAssertionError(
            "The Realtor Beta entitlement verifier is unavailable.",
            code="beta_entitlement_verifier_unavailable",
        ) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise EntitlementAssertionError(
            "The Realtor Beta entitlement verifier has an invalid key type.",
            code="beta_entitlement_verifier_unavailable",
        )
    return key


def entitlement_assertion_keyset_sha256(public_keys: Mapping[str, str]) -> str:
    """Fingerprint a canonical kid-to-SPKI entitlement verification ring."""
    digest = hashlib.sha256()
    digest.update(b"elevate-entitlement-keyset-v1\0")
    key_ids = list(public_keys)
    if any(not isinstance(kid, str) for kid in key_ids):
        raise EntitlementAssertionError(
            "The Realtor Beta entitlement verifier has an invalid key ring.",
            code="beta_entitlement_verifier_unavailable",
        )
    for kid in sorted(key_ids):
        spki_der_base64 = public_keys[kid]
        if (
            not isinstance(kid, str)
            or not kid
            or len(kid) > 128
            or any(ord(char) < 0x20 for char in kid)
            or not isinstance(spki_der_base64, str)
        ):
            raise EntitlementAssertionError(
                "The Realtor Beta entitlement verifier has an invalid key ring.",
                code="beta_entitlement_verifier_unavailable",
            )
        try:
            der = base64.b64decode(spki_der_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise EntitlementAssertionError(
                "The Realtor Beta entitlement verifier has an invalid key ring.",
                code="beta_entitlement_verifier_unavailable",
            ) from exc
        canonical = base64.b64encode(der).decode("ascii")
        if not hmac.compare_digest(canonical, spki_der_base64):
            raise EntitlementAssertionError(
                "The Realtor Beta entitlement verifier has a noncanonical key ring.",
                code="beta_entitlement_verifier_unavailable",
            )
        digest.update(kid.encode("utf-8"))
        digest.update(b"\0")
        digest.update(canonical.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def verifier_ready() -> bool:
    """Return whether the exact compiled production key ring initializes."""
    try:
        if tuple(sorted(ENTITLEMENT_ASSERTION_PUBLIC_KEYS)) != (
            ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS
        ):
            return False
        if not hmac.compare_digest(
            entitlement_assertion_keyset_sha256(ENTITLEMENT_ASSERTION_PUBLIC_KEYS),
            ENTITLEMENT_ASSERTION_KEYSET_SHA256,
        ):
            return False
        for spki_der_base64 in ENTITLEMENT_ASSERTION_PUBLIC_KEYS.values():
            _load_public_key(spki_der_base64)
    except (EntitlementAssertionError, TypeError):
        return False
    return True


def verify_entitlement_assertion(
    assertion: str,
    *,
    access_token: str,
    refresh_token: str,
    now: int | None = None,
    trusted_keys: Mapping[str, str] | None = None,
    require_current: bool = True,
) -> EntitlementAssertionClaims:
    """Verify and return one strict EdDSA compact entitlement assertion."""
    if (
        not isinstance(assertion, str)
        or not assertion
        or len(assertion.encode("utf-8")) > _MAX_ASSERTION_BYTES
    ):
        raise EntitlementAssertionError(
            "The entitlement assertion is missing or too large.",
            code="beta_entitlement_assertion_missing",
        )
    segments = assertion.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        raise EntitlementAssertionError(
            "The entitlement assertion is not compact JWS.",
            code="beta_entitlement_assertion_malformed",
        )
    header_segment, payload_segment, signature_segment = segments
    header = _json_object(
        _decode_base64url(header_segment, label="header"),
        label="header",
    )
    if set(header) != {"alg", "typ", "kid"}:
        raise EntitlementAssertionError(
            "The entitlement assertion has unsupported protected headers.",
            code="beta_entitlement_header_invalid",
        )
    if header.get("alg") != "EdDSA":
        raise EntitlementAssertionError(
            "The entitlement assertion algorithm is not EdDSA.",
            code="beta_entitlement_algorithm_invalid",
        )
    if header.get("typ") != ENTITLEMENT_ASSERTION_TYPE:
        raise EntitlementAssertionError(
            "The entitlement assertion type is invalid.",
            code="beta_entitlement_header_invalid",
        )
    kid = header.get("kid")
    keys = ENTITLEMENT_ASSERTION_PUBLIC_KEYS if trusted_keys is None else trusted_keys
    if trusted_keys is None and not verifier_ready():
        raise EntitlementAssertionError(
            "The Realtor Beta entitlement verifier has no trusted production ring.",
            code="beta_entitlement_verifier_unavailable",
        )
    if not isinstance(kid, str) or kid not in keys:
        raise EntitlementAssertionError(
            "The entitlement assertion key is not trusted.",
            code="beta_entitlement_key_unknown",
        )
    signature = _decode_base64url(signature_segment, label="signature")
    if len(signature) != 64:
        raise EntitlementAssertionError(
            "The entitlement assertion signature has an invalid length.",
            code="beta_entitlement_signature_invalid",
        )
    key = _load_public_key(keys[kid])
    try:
        key.verify(
            signature,
            f"{header_segment}.{payload_segment}".encode("ascii"),
        )
    except Exception as exc:
        raise EntitlementAssertionError(
            "The entitlement assertion signature is invalid.",
            code="beta_entitlement_signature_invalid",
        ) from exc

    claims = _json_object(
        _decode_base64url(payload_segment, label="payload"),
        label="payload",
    )
    if set(claims) != _CLAIM_KEYS:
        raise EntitlementAssertionError(
            "The entitlement assertion has unsupported schema 1 claims.",
            code="beta_entitlement_claim_invalid",
        )
    if claims.get("schema") != ENTITLEMENT_ASSERTION_SCHEMA or isinstance(
        claims.get("schema"), bool
    ):
        raise EntitlementAssertionError(
            "The entitlement assertion schema is unsupported.",
            code="beta_entitlement_schema_invalid",
        )
    if claims.get("iss") != ENTITLEMENT_ASSERTION_ISSUER:
        raise EntitlementAssertionError(
            "The entitlement assertion issuer is invalid.",
            code="beta_entitlement_issuer_invalid",
        )
    if claims.get("aud") != ENTITLEMENT_ASSERTION_AUDIENCE:
        raise EntitlementAssertionError(
            "The entitlement assertion audience is invalid.",
            code="beta_entitlement_audience_invalid",
        )

    subject = _required_text(claims, "sub")
    license_id = _required_text(claims, "license_id")
    assertion_id = _required_text(claims, "jti")
    email = _required_text(claims, "email", max_length=320)
    if email != email.lower():
        raise EntitlementAssertionError(
            "The entitlement assertion email is not normalized.",
            code="beta_entitlement_claim_invalid",
        )
    tier = _required_text(claims, "tier", max_length=64)
    if not _TIER_RE.fullmatch(tier) or tier not in {"pro", "builder"}:
        raise EntitlementAssertionError(
            "The entitlement assertion tier is not normalized.",
            code="beta_entitlement_claim_invalid",
        )

    raw_entitlements = claims.get("entitlements")
    if not isinstance(raw_entitlements, list) or any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(ord(char) < 0x20 for char in value)
        for value in raw_entitlements
    ):
        raise EntitlementAssertionError(
            "The entitlement assertion entitlements claim is invalid.",
            code="beta_entitlement_claim_invalid",
        )
    if raw_entitlements != sorted(set(raw_entitlements)):
        raise EntitlementAssertionError(
            "The entitlement assertion entitlements are not sorted and unique.",
            code="beta_entitlement_claim_invalid",
        )

    issued_at = _required_time(claims, "iat")
    not_before = _required_time(claims, "nbf")
    expires_at = _required_time(claims, "exp")
    current = int(time.time()) if now is None else int(now)
    if (
        not_before != issued_at
        or expires_at <= issued_at
        or expires_at - issued_at > 3600
    ):
        raise EntitlementAssertionError(
            "The entitlement assertion validity window is not schema 1 canonical.",
            code="beta_entitlement_claim_invalid",
        )
    if issued_at > current + _CLOCK_SKEW_SECONDS:
        raise EntitlementAssertionError(
            "The entitlement assertion was issued in the future.",
            code="beta_entitlement_assertion_not_current",
        )
    if not_before > current + _CLOCK_SKEW_SECONDS:
        raise EntitlementAssertionError(
            "The entitlement assertion is not active yet.",
            code="beta_entitlement_assertion_not_current",
        )
    if require_current and expires_at <= current - _CLOCK_SKEW_SECONDS:
        raise EntitlementAssertionError(
            "The entitlement assertion has expired.",
            code="beta_entitlement_assertion_not_current",
        )

    access_hash = _required_text(claims, "ath", max_length=64)
    refresh_hash = _required_text(claims, "rth", max_length=64)
    if not hmac.compare_digest(access_hash, token_binding_hash(access_token)):
        raise EntitlementAssertionError(
            "The entitlement assertion does not match the access token.",
            code="beta_entitlement_token_mismatch",
        )
    if not hmac.compare_digest(refresh_hash, token_binding_hash(refresh_token)):
        raise EntitlementAssertionError(
            "The entitlement assertion does not match the refresh token.",
            code="beta_entitlement_token_mismatch",
        )

    return EntitlementAssertionClaims(
        subject=subject,
        license_id=license_id,
        email=email,
        tier=tier,
        entitlements=tuple(raw_entitlements),
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        assertion_id=assertion_id,
        access_token_hash=access_hash,
        refresh_token_hash=refresh_hash,
    )
