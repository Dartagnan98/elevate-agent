"""Hostile and cross-runtime tests for the Beta entitlement assertion."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from elevate_cli.entitlement_assertion import (
    ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
    ENTITLEMENT_ASSERTION_KID,
    ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
    EntitlementAssertionError,
    entitlement_assertion_keyset_sha256,
    token_binding_hash,
    verifier_ready,
    verify_entitlement_assertion,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "test"
    / "fixtures"
    / "entitlement-assertion-v1.json"
)
KEYSET_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "entitlement-keyset-v1.json"
)
TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
TEST_B_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))


def _public_spki(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        private_key.public_key().public_bytes(
            Encoding.DER,
            PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")


TEST_PUBLIC_KEY = _public_spki(TEST_PRIVATE_KEY)
TEST_B_PUBLIC_KEY = _public_spki(TEST_B_PRIVATE_KEY)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _signed_assertion(
    *,
    private_key: Ed25519PrivateKey = TEST_PRIVATE_KEY,
    access_token: str = "access-token",
    refresh_token: str = "refresh-token",
    now: int = 2_000_000_000,
    header_overrides: dict | None = None,
    protected_header_json: bytes | None = None,
    claim_overrides: dict | None = None,
) -> str:
    header = {
        "alg": "EdDSA",
        "typ": "elevate-entitlement+jwt",
        "kid": ENTITLEMENT_ASSERTION_KID,
    }
    header.update(header_overrides or {})
    claims = {
        "iss": "https://api.elevationrealestatehq.com",
        "aud": "elevate-realtor-beta",
        "schema": 1,
        "sub": "user-1",
        "license_id": "license-1",
        "email": "agent@example.test",
        "tier": "pro",
        "entitlements": ["real_estate_admin", "real_estate_sales"],
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "jti": "assertion-1",
        "ath": token_binding_hash(access_token),
        "rth": token_binding_hash(refresh_token),
    }
    claims.update(claim_overrides or {})
    protected = _b64url(
        protected_header_json
        if protected_header_json is not None
        else json.dumps(header, separators=(",", ":")).encode()
    )
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{protected}.{payload}".encode("ascii")
    return f"{protected}.{payload}.{_b64url(private_key.sign(signing_input))}"


def _verify(
    assertion: str,
    *,
    now: int = 2_000_000_100,
    trusted_keys: dict[str, str] | None = None,
):
    return verify_entitlement_assertion(
        assertion,
        access_token="access-token",
        refresh_token="refresh-token",
        now=now,
        trusted_keys=(
            {ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY}
            if trusted_keys is None
            else trusted_keys
        ),
    )


def test_backend_golden_fixture_verifies_cross_runtime() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    claims = verify_entitlement_assertion(
        fixture["compact_jws"],
        access_token=fixture["access_token"],
        refresh_token=fixture["refresh_token"],
        now=fixture["payload"]["iat"] + 1,
        trusted_keys={
            fixture["header"]["kid"]: fixture["test_public_key_spki_der_b64"]
        },
    )

    assert claims.license_id == fixture["payload"]["license_id"]
    assert list(claims.entitlements) == fixture["payload"]["entitlements"]
    assert (
        ENTITLEMENT_ASSERTION_PUBLIC_KEYS[ENTITLEMENT_ASSERTION_KID]
        == fixture["production_public_key_spki_der_b64"]
    )
    assert verifier_ready() is True


def test_production_key_ring_matches_cross_runtime_fixture() -> None:
    fixture = json.loads(KEYSET_FIXTURE_PATH.read_text(encoding="utf-8"))

    assert list(ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS) == fixture[
        "accepted_key_ids"
    ]
    assert ENTITLEMENT_ASSERTION_PUBLIC_KEYS == fixture[
        "public_keys_spki_der_b64"
    ]
    assert ENTITLEMENT_ASSERTION_KEYSET_SHA256 == fixture["keyset_sha256"]
    assert (
        entitlement_assertion_keyset_sha256(ENTITLEMENT_ASSERTION_PUBLIC_KEYS)
        == fixture["keyset_sha256"]
    )


def test_verifier_requires_the_complete_pinned_production_ring(monkeypatch) -> None:
    import elevate_cli.entitlement_assertion as assertion_module

    monkeypatch.setattr(
        assertion_module,
        "ENTITLEMENT_ASSERTION_PUBLIC_KEYS",
        {ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY},
    )

    assert verifier_ready() is False


def test_verifier_rejects_malformed_and_non_ed25519_production_keys(
    monkeypatch,
) -> None:
    import elevate_cli.entitlement_assertion as assertion_module

    kid_a, kid_b = ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS
    ec_public_key = base64.b64encode(
        ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            Encoding.DER,
            PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")
    non_ed_ring = {kid_a: TEST_PUBLIC_KEY, kid_b: ec_public_key}
    monkeypatch.setattr(
        assertion_module,
        "ENTITLEMENT_ASSERTION_PUBLIC_KEYS",
        non_ed_ring,
    )
    monkeypatch.setattr(
        assertion_module,
        "ENTITLEMENT_ASSERTION_KEYSET_SHA256",
        entitlement_assertion_keyset_sha256(non_ed_ring),
    )
    assert verifier_ready() is False

    malformed_ring = {kid_a: TEST_PUBLIC_KEY, kid_b: "not-base64"}
    monkeypatch.setattr(
        assertion_module,
        "ENTITLEMENT_ASSERTION_PUBLIC_KEYS",
        malformed_ring,
    )
    assert verifier_ready() is False


def test_missing_production_key_is_typed_verifier_unavailable(monkeypatch) -> None:
    import elevate_cli.entitlement_assertion as assertion_module

    monkeypatch.setattr(assertion_module, "ENTITLEMENT_ASSERTION_PUBLIC_KEYS", {})

    with pytest.raises(EntitlementAssertionError) as exc_info:
        verify_entitlement_assertion(
            _signed_assertion(),
            access_token="access-token",
            refresh_token="refresh-token",
            now=2_000_000_100,
        )

    assert exc_info.value.code == "beta_entitlement_verifier_unavailable"


@pytest.mark.parametrize(
    ("header_overrides", "expected_code"),
    [
        ({"kid": "attacker-key"}, "beta_entitlement_key_unknown"),
        ({"alg": "HS256"}, "beta_entitlement_algorithm_invalid"),
        ({"alg": "none"}, "beta_entitlement_algorithm_invalid"),
        ({"typ": "JWT"}, "beta_entitlement_header_invalid"),
        ({"jwk": {"kty": "OKP"}}, "beta_entitlement_header_invalid"),
    ],
)
def test_rejects_unknown_keys_and_algorithm_confusion(
    header_overrides: dict,
    expected_code: str,
) -> None:
    with pytest.raises(EntitlementAssertionError) as exc_info:
        _verify(_signed_assertion(header_overrides=header_overrides))

    assert exc_info.value.code == expected_code


def test_routes_b_by_kid_and_rejects_cross_key_signatures() -> None:
    kid_b = ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS[1]
    trusted_keys = {
        ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY,
        kid_b: TEST_B_PUBLIC_KEY,
    }
    assertion_b = _signed_assertion(
        private_key=TEST_B_PRIVATE_KEY,
        header_overrides={"kid": kid_b},
    )

    assert _verify(assertion_b, trusted_keys=trusted_keys).license_id == "license-1"

    mislabeled = _signed_assertion(header_overrides={"kid": kid_b})
    with pytest.raises(EntitlementAssertionError) as exc_info:
        _verify(mislabeled, trusted_keys=trusted_keys)
    assert exc_info.value.code == "beta_entitlement_signature_invalid"


def test_rejects_escaped_duplicate_protected_header_kid() -> None:
    duplicate_header = (
        b'{"alg":"EdDSA","typ":"elevate-entitlement+jwt",'
        b'"kid":"ent-2026-07-a","k\\u0069d":"ent-2026-07-b"}'
    )

    with pytest.raises(EntitlementAssertionError) as exc_info:
        _verify(_signed_assertion(protected_header_json=duplicate_header))

    assert exc_info.value.code == "beta_entitlement_assertion_malformed"


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"schema": 2},
        {"iss": "https://attacker.example.test"},
        {"aud": "elevate-stable"},
        {"email": "Agent@Example.test"},
        {"tier": "Pro"},
        {"tier": "enterprise"},
        {"entitlements": ["real_estate_sales", "real_estate_admin"]},
        {"entitlements": ["real_estate_admin", "real_estate_admin"]},
        {"nbf": 2_000_000_001},
        {"exp": 2_000_007_200},
        {"unsupported": "claim"},
        {"sub": ""},
        {"license_id": ""},
        {"jti": ""},
    ],
)
def test_rejects_wrong_or_noncanonical_required_claims(claim_overrides: dict) -> None:
    with pytest.raises(EntitlementAssertionError):
        _verify(_signed_assertion(claim_overrides=claim_overrides))


@pytest.mark.parametrize(
    ("claim_overrides", "now"),
    [
        ({"iat": 2_000_000_500, "nbf": 2_000_000_500}, 2_000_000_100),
        ({"exp": 2_000_000_050}, 2_000_000_100),
    ],
)
def test_rejects_expired_and_future_assertions(
    claim_overrides: dict,
    now: int,
) -> None:
    with pytest.raises(EntitlementAssertionError) as exc_info:
        _verify(_signed_assertion(claim_overrides=claim_overrides), now=now)

    assert exc_info.value.code == "beta_entitlement_assertion_not_current"


def test_historical_mode_accepts_expired_signature_but_never_future_assertion() -> None:
    expired = _signed_assertion(now=2_000_000_000)
    claims = verify_entitlement_assertion(
        expired,
        access_token="access-token",
        refresh_token="refresh-token",
        now=2_000_007_200,
        trusted_keys={ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY},
        require_current=False,
    )

    assert claims.expires_at == 2_000_003_600
    with pytest.raises(EntitlementAssertionError) as exc_info:
        verify_entitlement_assertion(
            _signed_assertion(now=2_000_008_000),
            access_token="access-token",
            refresh_token="refresh-token",
            now=2_000_007_200,
            trusted_keys={ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY},
            require_current=False,
        )
    assert exc_info.value.code == "beta_entitlement_assertion_not_current"


def test_rejects_bad_signature_payload_tampering_and_token_mismatch() -> None:
    valid = _signed_assertion()
    head, payload, signature = valid.split(".")
    bad_signature = f"{head}.{payload}.{signature[:-1]}A"
    tampered_payload = f"{head}.{_b64url(b'{}')}.{signature}"

    for assertion in (bad_signature, tampered_payload):
        with pytest.raises(EntitlementAssertionError) as exc_info:
            _verify(assertion)
        assert exc_info.value.code == "beta_entitlement_signature_invalid"

    with pytest.raises(EntitlementAssertionError) as exc_info:
        verify_entitlement_assertion(
            valid,
            access_token="different-access-token",
            refresh_token="refresh-token",
            now=2_000_000_100,
            trusted_keys={ENTITLEMENT_ASSERTION_KID: TEST_PUBLIC_KEY},
        )
    assert exc_info.value.code == "beta_entitlement_token_mismatch"


@pytest.mark.parametrize(
    "assertion",
    ["", "one.two", "one.two.three.four", "a=.b.c", "a.b.c"],
)
def test_rejects_noncanonical_compact_jws(assertion: str) -> None:
    with pytest.raises(EntitlementAssertionError):
        _verify(assertion)
