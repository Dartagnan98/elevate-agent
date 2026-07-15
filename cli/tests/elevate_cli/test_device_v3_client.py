import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from elevate_cli import entitlement_assertion as assertion_mod
from elevate_cli import license as license_mod
from elevate_cli import refresh_pending


_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
_PUBLIC_KEY = base64.b64encode(
    _PRIVATE_KEY.public_key().public_bytes(
        Encoding.DER,
        PublicFormat.SubjectPublicKeyInfo,
    )
).decode("ascii")


def _token(byte: bytes) -> str:
    return base64.urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")


DEVICE_D = _token(b"D")
REFRESH_B = _token(b"B")
REFRESH_C = _token(b"C")
ATTEMPT_I = _token(b"I")
WINNER_E = _token(b"E")
THIRD_F = _token(b"F")
THIRD_G = _token(b"G")
THIRD_H = _token(b"H")
THIRD_J = _token(b"J")


class Response:
    def __init__(
        self,
        status_code: int,
        payload: object | None = None,
        *,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def _signed_payload(
    refresh_token: str,
    *,
    access_token: str = "device-access",
    license_id: str = "license-device",
    email: str = "agent@example.test",
    entitlements: list[str] | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    expiry = int(time.time()) + 3600 if expires_at is None else expires_at
    granted = sorted(set(entitlements or []))
    header = {
        "alg": "EdDSA",
        "typ": assertion_mod.ENTITLEMENT_ASSERTION_TYPE,
        "kid": assertion_mod.ENTITLEMENT_ASSERTION_KID,
    }
    claims = {
        "iss": assertion_mod.ENTITLEMENT_ASSERTION_ISSUER,
        "aud": assertion_mod.ENTITLEMENT_ASSERTION_AUDIENCE,
        "schema": assertion_mod.ENTITLEMENT_ASSERTION_SCHEMA,
        "sub": f"user-{license_id}",
        "license_id": license_id,
        "email": email,
        "tier": "pro",
        "entitlements": granted,
        "iat": expiry - 3600,
        "nbf": expiry - 3600,
        "exp": expiry,
        "jti": f"assertion-{license_id}-{refresh_token}",
        "ath": assertion_mod.token_binding_hash(access_token),
        "rth": assertion_mod.token_binding_hash(refresh_token),
    }
    protected = _b64json(header)
    payload = _b64json(claims)
    signature = (
        base64.urlsafe_b64encode(
            _PRIVATE_KEY.sign(f"{protected}.{payload}".encode("ascii"))
        )
        .decode("ascii")
        .rstrip("=")
    )
    assertion = f"{protected}.{payload}.{signature}"
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "license_id": license_id,
        "tier": "pro",
        "email": email,
        "expires_at": expiry,
        "expires_in": 3600,
        "entitlements": granted,
        "entitlement_assertion": assertion,
    }


def _b64json(value: object) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )


def _license(refresh_token: str, **kwargs: Any) -> license_mod.License:
    return license_mod._beta_license_from_mapping(
        _signed_payload(refresh_token, **kwargs)
    )


@pytest.fixture(autouse=True)
def beta_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".elevate-beta"
    root.mkdir()
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(root))
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: root)
    monkeypatch.setattr(license_mod, "LICENSE_PATH", root / "license.json")
    monkeypatch.setattr(
        license_mod,
        "LICENSE_FAIL_PATH",
        root / ".license_refresh_failures",
    )
    monkeypatch.setattr(license_mod.time, "sleep", lambda _seconds: None)
    keys = {assertion_mod.ENTITLEMENT_ASSERTION_KID: _PUBLIC_KEY}
    monkeypatch.setattr(assertion_mod, "ENTITLEMENT_ASSERTION_PUBLIC_KEYS", keys)
    monkeypatch.setattr(
        assertion_mod,
        "ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS",
        tuple(keys),
    )
    monkeypatch.setattr(
        assertion_mod,
        "ENTITLEMENT_ASSERTION_KEYSET_SHA256",
        assertion_mod.entitlement_assertion_keyset_sha256(keys),
    )
    return root


def _pending(root: Path, *, created_at: int | None = None) -> Any:
    with refresh_pending.refresh_lock(root):
        return refresh_pending.write_device_pending(
            root,
            device_code=DEVICE_D,
            initial_refresh_token=REFRESH_B,
            recovery_refresh_token=REFRESH_C,
            recovery_attempt_id=ATTEMPT_I,
            created_at=created_at,
        )


def _install(lic: license_mod.License) -> None:
    license_mod._atomic_beta_replace(
        json.dumps(lic.to_dict(), separators=(",", ":")).encode("utf-8")
    )


def _start(payload: dict[str, Any]) -> Response:
    user_code = "ABCD-EFGH"
    return Response(
        200,
        {
            "protocol_version": 3,
            "device_code": payload["device_code"],
            "user_code": user_code,
            "verification_uri": f"{license_mod.DEFAULT_BACKEND}/link",
            "verification_uri_complete": (
                f"{license_mod.DEFAULT_BACKEND}/link?code={user_code}"
            ),
            "expires_in": 600,
            "interval": 5,
        },
    )


def _resume() -> Response:
    return Response(
        200,
        {
            "protocol_version": 3,
            "status": "resume_poll",
            "grant_status": "claimed",
            "interval": 5,
        },
    )


def _approved(refresh_token: str) -> Response:
    return Response(
        200,
        {
            "status": "approved",
            "protocol_version": 2,
            **_signed_payload(refresh_token),
        },
    )


def _set_responder(
    monkeypatch: pytest.MonkeyPatch,
    responder: Callable[[str, str, dict[str, Any]], Response],
) -> None:
    monkeypatch.setattr(license_mod, "_post_beta_device", responder)


def test_fresh_v3_persists_marker_before_network_and_converges_on_exact_c(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    observed_pending: Any | None = None

    def responder(base: str, path: str, payload: dict[str, Any]) -> Response:
        nonlocal observed_pending
        assert base == license_mod.DEFAULT_BACKEND
        # Every request must run after the shared local credential lock exits.
        with refresh_pending.refresh_lock(beta_profile, timeout_seconds=0):
            pass
        pending = refresh_pending.read_device_pending(beta_profile)
        assert pending is not None
        observed_pending = pending
        calls.append((path, dict(payload)))
        if path == "/api/device/start":
            assert payload == {
                "protocol_version": 3,
                "device_code": pending.device_code,
                "device_label": "Realtor Mac",
                "proposed_refresh_token_hash": hashlib.sha256(
                    pending.initial_refresh_token.encode("ascii")
                ).hexdigest(),
            }
            return _start(payload)
        if path == "/api/device/poll":
            assert payload == {
                "device_code": pending.device_code,
                "refresh_token": pending.initial_refresh_token,
            }
            return _approved(pending.initial_refresh_token)
        assert path == "/api/license/refresh"
        assert payload == {
            "refresh_token": pending.initial_refresh_token,
            "next_refresh_token": pending.recovery_refresh_token,
            "refresh_attempt_id": pending.recovery_attempt_id,
        }
        return Response(200, _signed_payload(pending.recovery_refresh_token))

    _set_responder(monkeypatch, responder)
    result = license_mod.link_device("Realtor Mac", interval_override=1)

    assert observed_pending is not None
    assert result.refresh_token == observed_pending.recovery_refresh_token
    assert [path for path, _payload in calls] == [
        "/api/device/start",
        "/api/device/poll",
        "/api/license/refresh",
    ]
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True) == result
    )


def test_discarded_start_response_reuses_exact_d_and_b(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_request: dict[str, Any] = {}

    def lost_start(_base: str, path: str, payload: dict[str, Any]) -> Response:
        assert path == "/api/device/start"
        first_request.update(payload)
        raise license_mod.LicenseError(
            "HQ was unavailable; recovery remains saved.",
            code="beta_device_link_upstream_unavailable",
        )

    _set_responder(monkeypatch, lost_start)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)
    assert caught.value.code == "beta_device_link_upstream_unavailable"
    retained = refresh_pending.read_device_pending(beta_profile)
    assert retained is not None

    second_start: dict[str, Any] = {}

    def replay(_base: str, path: str, payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            second_start.update(payload)
            return _start(payload)
        if path == "/api/device/poll":
            return _approved(retained.initial_refresh_token)
        return Response(200, _signed_payload(retained.recovery_refresh_token))

    _set_responder(monkeypatch, replay)
    result = license_mod.link_device("Realtor Mac", interval_override=1)
    assert result.refresh_token == retained.recovery_refresh_token
    assert second_start["device_code"] == first_request["device_code"]
    assert (
        second_start["proposed_refresh_token_hash"]
        == first_request["proposed_refresh_token_hash"]
    )


def test_restart_resumes_existing_marker_and_claims_b(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    calls: list[tuple[str, dict[str, Any]]] = []

    def responder(_base: str, path: str, payload: dict[str, Any]) -> Response:
        calls.append((path, dict(payload)))
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return _approved(REFRESH_B)
        return Response(200, _signed_payload(REFRESH_C))

    _set_responder(monkeypatch, responder)
    result = license_mod.link_device("Realtor Mac", interval_override=1)

    assert result.refresh_token == REFRESH_C
    assert calls[0][1]["device_code"] == pending.device_code
    assert calls[1][1] == {
        "device_code": DEVICE_D,
        "refresh_token": REFRESH_B,
    }
    assert calls[2][1] == {
        "refresh_token": REFRESH_B,
        "next_refresh_token": REFRESH_C,
        "refresh_attempt_id": ATTEMPT_I,
    }
    assert refresh_pending.read_device_pending(beta_profile) is None


def test_unchanged_signed_predecessor_is_captured_and_replaced_by_exact_b(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = _license(
        WINNER_E,
        access_token="predecessor-access",
        license_id="predecessor-license",
    )
    _install(predecessor)
    captured_marker: Any | None = None

    def responder(_base: str, path: str, payload: dict[str, Any]) -> Response:
        nonlocal captured_marker
        captured_marker = refresh_pending.read_device_pending(beta_profile)
        assert captured_marker is not None
        if path == "/api/device/start":
            return _start(payload)
        if path == "/api/device/poll":
            return _approved(captured_marker.initial_refresh_token)
        return Response(
            200,
            _signed_payload(captured_marker.recovery_refresh_token),
        )

    _set_responder(monkeypatch, responder)
    result = license_mod.link_device("Realtor Mac", interval_override=1)

    assert captured_marker is not None
    assert result.refresh_token == captured_marker.recovery_refresh_token
    assert result != predecessor
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True) == result
    )


def test_changed_signed_predecessor_loses_even_when_marker_bytes_do_not_change(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = _license(
        WINNER_E,
        access_token="predecessor-access",
        license_id="predecessor-license",
    )
    winner = _license(
        THIRD_F,
        access_token="winner-access",
        license_id="winner-license",
    )
    _install(predecessor)
    captured_marker: Any | None = None

    def responder(_base: str, path: str, payload: dict[str, Any]) -> Response:
        nonlocal captured_marker
        pending = refresh_pending.read_device_pending(beta_profile)
        assert pending is not None
        if captured_marker is None:
            captured_marker = pending
        else:
            assert pending == captured_marker
        if path == "/api/device/start":
            return _start(payload)
        _install(winner)
        assert refresh_pending.read_device_pending(beta_profile) == captured_marker
        return _approved(captured_marker.initial_refresh_token)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_auth_superseded"
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True) == winner
    )
    assert refresh_pending.read_device_pending(beta_profile) == captured_marker


def test_restart_with_unverifiable_corrupt_predecessor_fails_closed(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    corrupt = b'{"access_token":"partial-device-write"}\n'
    license_mod.LICENSE_PATH.write_bytes(corrupt)
    license_mod.LICENSE_PATH.chmod(0o600)
    monkeypatch.setattr(
        license_mod,
        "_post_beta_device",
        lambda *_args, **_kwargs: pytest.fail(
            "unverifiable state must not use network"
        ),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_predecessor_unverifiable"
    assert license_mod.LICENSE_PATH.read_bytes() == corrupt
    assert refresh_pending.read_device_pending(beta_profile) == pending


def test_restart_with_unrelated_signed_predecessor_fails_closed(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = _license(
        WINNER_E,
        access_token="predecessor-access",
        license_id="predecessor-license",
    )
    _install(predecessor)
    pending = _pending(beta_profile)
    monkeypatch.setattr(
        license_mod,
        "_post_beta_device",
        lambda *_args, **_kwargs: pytest.fail("ambiguous predecessor must not use network"),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_predecessor_unverifiable"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == predecessor
    assert refresh_pending.read_device_pending(beta_profile) == pending


@pytest.mark.parametrize(
    "body",
    [
        {
            "protocol_version": 3,
            "status": "resume_poll",
            "grant_status": "pending",
            "interval": 5,
        },
        {
            "protocol_version": 3,
            "status": "resume_poll",
            "grant_status": "claimed",
        },
        {
            "protocol_version": 3,
            "status": "resume_poll",
            "grant_status": "claimed",
            "interval": 5,
            "device_code": DEVICE_D,
        },
        {
            "protocol_version": 3,
            "status": "resume_poll",
            "grant_status": "claimed",
            "interval": True,
        },
    ],
    ids=["bad-grant-status", "missing-interval", "credential-field", "bool-interval"],
)
def test_resume_response_is_strict_and_retains_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
) -> None:
    pending = _pending(beta_profile)
    _set_responder(
        monkeypatch,
        lambda _base, _path, _payload: Response(200, body),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_protocol_invalid"
    assert refresh_pending.read_device_pending(beta_profile) == pending


@pytest.mark.parametrize(
    "poll_response",
    [
        Response(410, {"error": "claim_retry_expired", "status": "claimed"}),
        Response(401, {"error": "invalid_grant"}),
    ],
    ids=["claim-window-expired", "restart-stale-b"],
)
def test_claim_recovery_replays_exact_b_c_i(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    poll_response: Response,
) -> None:
    pending = _pending(beta_profile)
    recovery_body: dict[str, Any] = {}

    def responder(_base: str, path: str, payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return poll_response
        assert path == "/api/license/refresh"
        recovery_body.update(payload)
        return Response(200, _signed_payload(REFRESH_C))

    _set_responder(monkeypatch, responder)
    result = license_mod.link_device("Realtor Mac", interval_override=1)

    assert result.refresh_token == REFRESH_C
    assert recovery_body == {
        "refresh_token": pending.initial_refresh_token,
        "next_refresh_token": pending.recovery_refresh_token,
        "refresh_attempt_id": pending.recovery_attempt_id,
    }
    assert refresh_pending.read_device_pending(beta_profile) is None


def test_recovery_c_can_replace_exact_historical_b_predecessor(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pending(beta_profile)
    historical_b = license_mod._beta_license_from_mapping(
        _signed_payload(
            REFRESH_B,
            access_token="expired-b-access",
            expires_at=int(time.time()) - 60,
        ),
        require_current=False,
    )
    _install(historical_b)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return Response(401, {"error": "invalid_grant"})
        return Response(200, _signed_payload(REFRESH_C))

    _set_responder(monkeypatch, responder)
    recovered = license_mod.link_device("Realtor Mac", interval_override=1)

    assert recovered.refresh_token == REFRESH_C
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True)
        == recovered
    )


def test_recovery_c_can_refresh_exact_historical_c_predecessor(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    historical_c = license_mod._beta_license_from_mapping(
        _signed_payload(
            REFRESH_C,
            access_token="expired-c-access",
            expires_at=int(time.time()) - 60,
        ),
        require_current=False,
    )
    _install(historical_c)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return Response(401, {"error": "invalid_grant"})
        return Response(
            200,
            _signed_payload(REFRESH_C, access_token="fresh-c-access"),
        )

    _set_responder(monkeypatch, responder)
    recovered = license_mod.link_device("Realtor Mac", interval_override=1)

    assert recovered.refresh_token == pending.recovery_refresh_token
    assert recovered.access_token == "fresh-c-access"
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == recovered


def test_concurrent_fresh_c_repairs_historical_c_after_attempt_prepared(
    beta_profile: Path,
) -> None:
    pending = _pending(beta_profile)
    attempt = license_mod._BetaDeviceAttempt(
        pending=pending,
        starting_snapshot=None,
    )
    historical_c = license_mod._beta_license_from_mapping(
        _signed_payload(
            REFRESH_C,
            access_token="concurrent-expired-c-access",
            expires_at=int(time.time()) - 60,
        ),
        require_current=False,
    )
    _install(historical_c)
    fresh_c = _license(REFRESH_C, access_token="concurrent-fresh-c-access")

    repaired = license_mod._commit_beta_device_license(
        attempt,
        fresh_c,
        expected_refresh_token=REFRESH_C,
        final=True,
    )

    assert repaired == fresh_c
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == fresh_c


def test_concurrent_server_c_converges_when_local_b_commits_first(
    beta_profile: Path,
) -> None:
    pending = _pending(beta_profile)
    first = license_mod._BetaDeviceAttempt(pending=pending, starting_snapshot=None)
    second = license_mod._BetaDeviceAttempt(pending=pending, starting_snapshot=None)
    signed_b = _license(REFRESH_B, access_token="poll-b-access")
    signed_c = _license(REFRESH_C, access_token="recovery-c-access")

    interim = license_mod._commit_beta_device_license(
        first,
        signed_b,
        expected_refresh_token=REFRESH_B,
        final=False,
    )
    assert interim.refresh_token == REFRESH_B
    assert refresh_pending.read_device_pending(beta_profile) == pending

    final = license_mod._commit_beta_device_license(
        second,
        signed_c,
        expected_refresh_token=REFRESH_C,
        final=True,
    )
    assert final.refresh_token == REFRESH_C
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == final


def test_late_local_b_preserves_already_durable_server_c(
    beta_profile: Path,
) -> None:
    pending = _pending(beta_profile)
    recovering = license_mod._BetaDeviceAttempt(
        pending=pending,
        starting_snapshot=None,
    )
    late_poll = license_mod._BetaDeviceAttempt(
        pending=pending,
        starting_snapshot=None,
    )
    signed_c = _license(REFRESH_C, access_token="recovery-c-access")
    late_b = _license(REFRESH_B, access_token="late-poll-b-access")

    final = license_mod._commit_beta_device_license(
        recovering,
        signed_c,
        expected_refresh_token=REFRESH_C,
        final=True,
    )
    preserved = license_mod._commit_beta_device_license(
        late_poll,
        late_b,
        expected_refresh_token=REFRESH_B,
        final=False,
    )

    assert preserved == final
    assert preserved.refresh_token == REFRESH_C
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == final


@pytest.mark.parametrize(
    ("refresh_token", "final"),
    [(REFRESH_B, False), (REFRESH_C, True)],
    ids=["late-b", "late-c"],
)
def test_late_old_result_cannot_claim_success_over_newer_device_marker(
    beta_profile: Path,
    refresh_token: str,
    final: bool,
) -> None:
    original = _pending(beta_profile)
    old_attempt = license_mod._BetaDeviceAttempt(
        pending=original,
        starting_snapshot=None,
    )
    signed_c = _license(REFRESH_C, access_token="old-final-c-access")
    license_mod._commit_beta_device_license(
        old_attempt,
        signed_c,
        expected_refresh_token=REFRESH_C,
        final=True,
    )
    with refresh_pending.refresh_lock(beta_profile):
        newer = refresh_pending.write_device_pending(
            beta_profile,
            device_code=THIRD_F,
            initial_refresh_token=THIRD_G,
            recovery_refresh_token=THIRD_H,
            recovery_attempt_id=THIRD_J,
        )
    late = (
        _license(REFRESH_B, access_token="late-old-b-access")
        if not final
        else _license(REFRESH_C, access_token="late-old-c-access")
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod._commit_beta_device_license(
            old_attempt,
            late,
            expected_refresh_token=refresh_token,
            final=final,
        )

    assert caught.value.code == "beta_auth_superseded"
    assert refresh_pending.read_device_pending(beta_profile) == newer
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == signed_c


def test_recovery_c_rejects_cross_identity_rotation_from_local_b(
    beta_profile: Path,
) -> None:
    pending = _pending(beta_profile)
    attempt = license_mod._BetaDeviceAttempt(pending=pending, starting_snapshot=None)
    signed_b = _license(
        REFRESH_B,
        access_token="poll-b-access",
        license_id="device-license",
    )
    wrong_c = _license(
        REFRESH_C,
        access_token="wrong-c-access",
        license_id="different-license",
        email="different@example.test",
    )
    license_mod._commit_beta_device_license(
        attempt,
        signed_b,
        expected_refresh_token=REFRESH_B,
        final=False,
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod._commit_beta_device_license(
            attempt,
            wrong_c,
            expected_refresh_token=REFRESH_C,
            final=True,
        )

    assert caught.value.code == "beta_entitlement_response_mismatch"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == signed_b


def test_fresh_b_rejects_cross_identity_repair_of_historical_b(
    beta_profile: Path,
) -> None:
    pending = _pending(beta_profile)
    attempt = license_mod._BetaDeviceAttempt(
        pending=pending,
        starting_snapshot=None,
    )
    historical_b = license_mod._beta_license_from_mapping(
        _signed_payload(
            REFRESH_B,
            access_token="expired-original-b-access",
            license_id="original-license",
            expires_at=int(time.time()) - 60,
        ),
        require_current=False,
    )
    _install(historical_b)
    wrong_b = _license(
        REFRESH_B,
        access_token="wrong-fresh-b-access",
        license_id="different-license",
        email="different@example.test",
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod._commit_beta_device_license(
            attempt,
            wrong_b,
            expected_refresh_token=REFRESH_B,
            final=False,
        )

    assert caught.value.code == "beta_entitlement_response_mismatch"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=False
    ) == historical_b


@pytest.mark.parametrize(
    "terminal",
    [
        Response(403, {"error": "access_denied", "status": "denied"}),
        Response(410, {"error": "expired_token", "status": "expired"}),
    ],
)
def test_terminal_poll_retains_marker_for_historical_signed_b(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: Response,
) -> None:
    pending = _pending(beta_profile)
    historical_b = license_mod._beta_license_from_mapping(
        _signed_payload(
            REFRESH_B,
            access_token="expired-b-access",
            expires_at=int(time.time()) - 60,
        ),
        require_current=False,
    )
    _install(historical_b)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        return _resume() if path == "/api/device/start" else terminal

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_completion_incomplete"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=False)
        == historical_b
    )


@pytest.mark.parametrize(
    ("terminal_stage", "terminal"),
    [
        ("start", Response(403, {"error": "authorization_denied"})),
        ("start", Response(410, {"error": "expired_token"})),
        (
            "poll",
            Response(403, {"error": "access_denied", "status": "denied"}),
        ),
        (
            "poll",
            Response(410, {"error": "expired_token", "status": "expired"}),
        ),
    ],
    ids=["start-denied", "start-expired", "poll-denied", "poll-expired"],
)
def test_terminal_start_or_poll_retains_marker_for_current_signed_b(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_stage: str,
    terminal: Response,
) -> None:
    pending = _pending(beta_profile)
    signed_b = _license(REFRESH_B, access_token="current-b-access")
    _install(signed_b)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return terminal if terminal_stage == "start" else _resume()
        return terminal

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_completion_incomplete"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == signed_b


@pytest.mark.parametrize("terminal_stage", ["start", "poll"])
def test_late_terminal_response_cannot_claim_c_over_newer_device_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_stage: str,
) -> None:
    original = _pending(beta_profile)
    signed_c = _license(REFRESH_C, access_token="old-completed-c-access")
    newer: Any | None = None

    def install_newer_attempt() -> None:
        nonlocal newer
        if newer is not None:
            return
        _install(signed_c)
        with refresh_pending.refresh_lock(beta_profile):
            assert refresh_pending.remove_device_pending(beta_profile, original)
            newer = refresh_pending.write_device_pending(
                beta_profile,
                device_code=THIRD_F,
                initial_refresh_token=THIRD_G,
                recovery_refresh_token=THIRD_H,
                recovery_attempt_id=THIRD_J,
            )

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start" and terminal_stage == "poll":
            return _resume()
        install_newer_attempt()
        if terminal_stage == "start":
            return Response(403, {"error": "authorization_denied"})
        return Response(403, {"error": "access_denied", "status": "denied"})

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_auth_superseded"
    assert newer is not None
    assert refresh_pending.read_device_pending(beta_profile) == newer
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == signed_c


@pytest.mark.parametrize(
    ("path", "response", "expected_code"),
    [
        (
            "start",
            Response(403, {"error": "authorization_denied"}),
            "beta_device_link_denied",
        ),
        (
            "start",
            Response(410, {"error": "expired_token"}),
            "beta_device_link_expired",
        ),
        (
            "poll",
            Response(403, {"error": "access_denied", "status": "denied"}),
            "beta_device_link_denied",
        ),
        (
            "poll",
            Response(410, {"error": "expired_token", "status": "expired"}),
            "beta_device_link_expired",
        ),
    ],
)
def test_only_definitive_denial_or_expiry_clears_exact_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    response: Response,
    expected_code: str,
) -> None:
    pending = _pending(beta_profile)

    def responder(_base: str, request_path: str, payload: dict[str, Any]) -> Response:
        if request_path == "/api/device/start":
            return response if path == "start" else _start(payload)
        return response

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == expected_code
    assert refresh_pending.read_device_pending(beta_profile) is None
    assert pending.initial_refresh_token not in str(caught.value)


@pytest.mark.parametrize(
    ("poll_response", "recovery_response", "expected_code"),
    [
        (
            Response(500, {"error": "device poll unavailable"}),
            None,
            "beta_device_link_upstream_failed",
        ),
        (
            Response(403, {"error": "license_revoked"}),
            None,
            "beta_device_link_protocol_rejected",
        ),
        (
            Response(402, {"error": "subscription inactive"}),
            None,
            "beta_device_link_protocol_rejected",
        ),
        (
            Response(200, None, json_error=ValueError("not json")),
            None,
            "beta_device_protocol_invalid",
        ),
        (
            Response(200, None, json_error=RecursionError("too deeply nested")),
            None,
            "beta_device_protocol_invalid",
        ),
        (
            Response(401, {"error": "invalid_grant"}),
            Response(401, {"error": "invalid or revoked refresh token"}),
            "beta_device_recovery_rejected",
        ),
        (
            Response(410, {"error": "claim_retry_expired", "status": "claimed"}),
            Response(503, {"error": "license refresh unavailable"}),
            "beta_device_link_upstream_failed",
        ),
    ],
)
def test_ambiguous_poll_and_recovery_failures_retain_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    poll_response: Response,
    recovery_response: Response | None,
    expected_code: str,
) -> None:
    pending = _pending(beta_profile)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return poll_response
        assert recovery_response is not None
        return recovery_response

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == expected_code
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert REFRESH_B not in str(caught.value)
    assert REFRESH_C not in str(caught.value)


@pytest.mark.parametrize("interval", [0, True, 61])
def test_pending_poll_rejects_invalid_interval_and_retains_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    interval: object,
) -> None:
    pending = _pending(beta_profile)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        return Response(200, {"status": "pending", "interval": interval})

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_protocol_invalid"
    assert refresh_pending.read_device_pending(beta_profile) == pending


def test_pending_poll_timeout_retains_resumable_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile, created_at=0)
    clock = iter([1_000.0, 1_000.0, 1_003.0])
    monkeypatch.setattr(license_mod.time, "time", lambda: next(clock))

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        return Response(200, {"status": "pending", "interval": 5})

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_link_timeout"
    assert refresh_pending.read_device_pending(beta_profile) == pending


def test_malformed_signed_approval_retains_marker_and_local_predecessor(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = _license(
        WINNER_E,
        access_token="predecessor-access",
        license_id="predecessor-license",
    )
    _install(predecessor)
    captured_marker: Any | None = None

    def responder(_base: str, path: str, payload: dict[str, Any]) -> Response:
        nonlocal captured_marker
        captured_marker = refresh_pending.read_device_pending(beta_profile)
        assert captured_marker is not None
        if path == "/api/device/start":
            return _start(payload)
        return Response(
            200,
            {
                "status": "approved",
                "protocol_version": 2,
                "access_token": "unsigned-access",
                "refresh_token": captured_marker.initial_refresh_token,
            },
        )

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_entitlement_assertion_missing"
    assert refresh_pending.read_device_pending(beta_profile) == captured_marker
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True)
        == predecessor
    )


def test_transport_failure_retains_marker_without_secret_in_error(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        def __enter__(self) -> "FailingClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> Response:
            assert refresh_pending.read_device_pending(beta_profile) is not None
            raise httpx.ConnectError("wire failed")

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: FailingClient())
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    pending = refresh_pending.read_device_pending(beta_profile)
    assert pending is not None
    assert caught.value.code == "beta_device_link_upstream_unavailable"
    assert caught.value.__cause__ is None
    for secret in (
        pending.device_code,
        pending.initial_refresh_token,
        pending.recovery_refresh_token,
        pending.recovery_attempt_id,
    ):
        assert secret not in str(caught.value)


def test_marker_cas_loss_preserves_third_device_winner(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _pending(beta_profile)
    third: Any | None = None

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        nonlocal third
        if path == "/api/device/start":
            return _resume()
        with refresh_pending.refresh_lock(beta_profile):
            assert refresh_pending.remove_device_pending(beta_profile, original)
            third = refresh_pending.write_device_pending(
                beta_profile,
                device_code=THIRD_F,
                initial_refresh_token=THIRD_G,
                recovery_refresh_token=THIRD_H,
                recovery_attempt_id=THIRD_J,
            )
        return _approved(REFRESH_B)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_auth_superseded"
    assert refresh_pending.read_device_pending(beta_profile) == third
    assert not license_mod.LICENSE_PATH.exists()


def test_byte_identical_marker_cannot_authorize_after_signed_predecessor_changes(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    winner = _license(
        WINNER_E,
        access_token="explicit-winner-access",
        license_id="explicit-winner",
    )

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        # Model a signed local winner landing while a non-cooperating/failed
        # cleanup path leaves the exact marker bytes untouched.
        _install(winner)
        assert refresh_pending.read_device_pending(beta_profile) == pending
        return _approved(REFRESH_B)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_auth_superseded"
    assert (
        license_mod.read_verified_beta_license_snapshot(require_current=True) == winner
    )
    assert refresh_pending.read_device_pending(beta_profile) == pending


def test_signed_b_mismatch_retains_marker_and_changes_no_local_state(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        return _resume() if path == "/api/device/start" else _approved(WINNER_E)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_refresh_token_mismatch"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    assert not license_mod.LICENSE_PATH.exists()


def test_mirror_failure_retains_signed_b_and_restart_recovers_exact_c(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    original_verify = license_mod._verify_beta_entitlement_mirror
    calls = 0

    def fail_once(lic: license_mod.License, *, require_current: bool) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise license_mod.LicenseError(
                "The local mirror was not durable.",
                code="beta_entitlement_persistence_mismatch",
            )
        original_verify(lic, require_current=require_current)

    monkeypatch.setattr(license_mod, "_verify_beta_entitlement_mirror", fail_once)

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        return _resume() if path == "/api/device/start" else _approved(REFRESH_B)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_entitlement_persistence_mismatch"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    durable = license_mod.read_verified_beta_license_snapshot(require_current=True)
    assert durable.refresh_token == REFRESH_B

    def resume_recovery(
        _base: str,
        path: str,
        _payload: dict[str, Any],
    ) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return Response(401, {"error": "invalid_grant"})
        return Response(200, _signed_payload(REFRESH_C))

    _set_responder(monkeypatch, resume_recovery)
    recovered = license_mod.link_device("Realtor Mac", interval_override=1)
    assert recovered.refresh_token == REFRESH_C
    assert recovered != durable
    assert refresh_pending.read_device_pending(beta_profile) is None


def test_marker_cleanup_response_loss_reconciles_durable_c_on_restart(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    original_remove = refresh_pending.remove_device_pending
    removals = 0

    def lose_first_cleanup(root: Path, expected: Any) -> bool:
        nonlocal removals
        removals += 1
        if removals == 1:
            raise refresh_pending.RefreshPendingError(
                "beta_device_persistence_failed",
                "Device completion cleanup acknowledgement was lost.",
            )
        return original_remove(root, expected)

    monkeypatch.setattr(
        refresh_pending,
        "remove_device_pending",
        lose_first_cleanup,
    )

    def responder(_base: str, path: str, _payload: dict[str, Any]) -> Response:
        if path == "/api/device/start":
            return _resume()
        if path == "/api/device/poll":
            return _approved(REFRESH_B)
        return Response(200, _signed_payload(REFRESH_C))

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_persistence_failed"
    assert refresh_pending.read_device_pending(beta_profile) == pending
    durable = license_mod.read_verified_beta_license_snapshot(require_current=True)
    assert durable.refresh_token == REFRESH_C

    monkeypatch.setattr(
        license_mod,
        "_post_beta_device",
        lambda *_args, **_kwargs: pytest.fail("restart must reconcile durable C"),
    )
    recovered = license_mod.link_device("Realtor Mac", interval_override=1)
    assert recovered == durable
    assert refresh_pending.read_device_pending(beta_profile) is None


def test_keyboard_interrupt_retains_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending(beta_profile)
    _set_responder(
        monkeypatch,
        lambda _base, path, _payload: (
            _resume()
            if path == "/api/device/start"
            else pytest.fail("poll must not run")
        ),
    )
    monkeypatch.setattr(
        license_mod.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        license_mod.link_device("Realtor Mac", interval_override=1)
    assert refresh_pending.read_device_pending(beta_profile) == pending


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.__setitem__("protocol_version", "3"),
        lambda body: body.__setitem__("protocol_version", True),
        lambda body: body.__setitem__("device_code", THIRD_F),
        lambda body: body.__setitem__("user_code", "ABCL-EFGH"),
        lambda body: body.__setitem__("verification_uri", "http://example.test/link"),
        lambda body: body.__setitem__(
            "verification_uri_complete", "https://evil.test/link"
        ),
        lambda body: body.__setitem__("expires_in", True),
        lambda body: body.__setitem__("expires_in", 601),
        lambda body: body.__setitem__("interval", 0),
        lambda body: body.__setitem__("extra", "field"),
    ],
    ids=[
        "string-protocol",
        "boolean-protocol",
        "wrong-device",
        "ambiguous-user-code",
        "http-origin",
        "unpinned-complete-link",
        "boolean-expiry",
        "long-expiry",
        "zero-interval",
        "unknown-field",
    ],
)
def test_start_response_is_strict_and_retains_marker(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    pending = _pending(beta_profile)

    def responder(_base: str, _path: str, payload: dict[str, Any]) -> Response:
        response = _start(payload)
        body = dict(response.json())
        mutate(body)
        return Response(200, body)

    _set_responder(monkeypatch, responder)
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_device_protocol_invalid"
    assert refresh_pending.read_device_pending(beta_profile) == pending


def test_stable_keeps_legacy_v1_request_and_response_behavior(
    beta_profile: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del beta_profile
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    calls: list[tuple[str, dict[str, Any]]] = []
    responses = [
        Response(
            200,
            {
                "device_code": "legacy-device",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://legacy.example.test/link",
                "expires_in": 60,
                "interval": 1,
            },
        ),
        Response(
            200,
            {
                "status": "approved",
                "access_token": "legacy-access",
                "refresh_token": "legacy-refresh",
                "license_id": "legacy-license",
                "tier": "pro",
                "email": "agent@example.test",
                "entitlements": [],
            },
        ),
    ]

    class Client:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, json: dict[str, Any]) -> Response:
            calls.append((url, dict(json)))
            return responses.pop(0)

    monkeypatch.setattr(license_mod.httpx, "Client", Client)
    result = license_mod.link_device("Stable Mac", interval_override=1)

    assert result.refresh_token == "legacy-refresh"
    assert calls == [
        (
            f"{license_mod.BACKEND_URL}/api/device/start",
            {"device_label": "Stable Mac"},
        ),
        (
            f"{license_mod.BACKEND_URL}/api/device/poll",
            {"device_code": "legacy-device"},
        ),
    ]
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None
