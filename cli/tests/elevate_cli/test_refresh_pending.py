import base64
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from elevate_cli import refresh_pending


FIXTURE = Path(__file__).parents[1] / "fixtures" / "beta-refresh-pending-v1.json"
DEVICE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "beta-device-pending-v1.json"
A = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE"
DEVICE_VALUE = json.loads(DEVICE_FIXTURE.read_text())
DEVICE_TOKEN_KEYS = (
    "device_code",
    "initial_refresh_token",
    "recovery_refresh_token",
    "recovery_attempt_id",
)


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / ".elevate-beta"
    root.mkdir(mode=0o700, parents=True)
    return root


def test_shared_fixture_schema_and_atomic_round_trip(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.MARKER_NAME
    marker.write_bytes(FIXTURE.read_bytes())
    marker.chmod(0o600)

    expected = json.loads(FIXTURE.read_text())
    assert refresh_pending.read_pending(root) == refresh_pending.PendingRefresh(
        **expected
    )

    marker.unlink()
    with refresh_pending.refresh_lock(root):
        created = refresh_pending.create_pending(
            root,
            license_id="license-fixture",
            current_refresh_token=A,
            created_at=1784080000,
        )
        assert created.current_refresh_token == A
        assert refresh_pending.canonical_token32(created.successor_refresh_token)
        assert refresh_pending.canonical_token32(created.attempt_id)
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert marker.stat().st_nlink == 1
        refresh_pending.remove_pending(root)

    lock = root / refresh_pending.LOCK_NAME
    assert lock.read_bytes() == b""
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    assert not marker.exists()


@pytest.mark.parametrize("auth_kind", ["login", "signup"])
def test_initial_auth_marker_is_scoped_by_email_and_kind(
    tmp_path: Path,
    auth_kind: str,
) -> None:
    root = private_root(tmp_path)
    other_kind = "signup" if auth_kind == "login" else "login"

    with refresh_pending.refresh_lock(root):
        pending = refresh_pending.create_initial_auth_pending(
            root,
            email=" Agent@Example.Test ",
            auth_kind=auth_kind,
            created_at=1784080000,
        )
        assert refresh_pending.is_initial_auth_pending(pending)
        assert refresh_pending.initial_auth_pending_matches(
            pending,
            "agent@example.test",
            auth_kind=auth_kind,
        )
        assert not refresh_pending.initial_auth_pending_matches(
            pending,
            "agent@example.test",
            auth_kind=other_kind,
        )
        assert not refresh_pending.initial_auth_pending_matches(
            pending,
            "different@example.test",
            auth_kind=auth_kind,
        )
        assert pending.license_id == refresh_pending.initial_auth_license_id(
            "AGENT@example.test",
            auth_kind=auth_kind,
        )
        assert re.fullmatch(
            rf"initial-auth-v1:{auth_kind}:[0-9a-f]{{64}}",
            pending.license_id,
        )
        refresh_pending.remove_pending(root)

    assert not (root / refresh_pending.MARKER_NAME).exists()


@pytest.mark.parametrize("artifact", ["lock", "marker"])
@pytest.mark.parametrize("attack", ["symlink", "hardlink", "public", "nonempty-lock"])
def test_refresh_artifacts_fail_closed(
    tmp_path: Path,
    artifact: str,
    attack: str,
) -> None:
    if artifact == "marker" and attack == "nonempty-lock":
        pytest.skip("lock-only invariant")
    root = private_root(tmp_path)
    target = root / (
        refresh_pending.LOCK_NAME if artifact == "lock" else refresh_pending.MARKER_NAME
    )
    outside = tmp_path / "outside"
    outside.write_bytes(b"x" if artifact == "lock" else FIXTURE.read_bytes())
    outside.chmod(0o600)
    if attack == "symlink":
        target.symlink_to(outside)
    elif attack == "hardlink":
        os.link(outside, target)
    elif attack == "public":
        target.write_bytes(b"" if artifact == "lock" else FIXTURE.read_bytes())
        target.chmod(0o644)
    else:
        target.write_bytes(b"corrupt")
        target.chmod(0o600)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        if artifact == "lock":
            with refresh_pending.refresh_lock(root, timeout_seconds=0):
                pass
        else:
            refresh_pending.read_pending(root)
    assert caught.value.code.startswith("beta_refresh_")


def test_malformed_marker_is_never_removed(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.MARKER_NAME
    marker.write_text('{"schema":1,"operation":"different"}')
    marker.chmod(0o600)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.remove_pending(root)

    assert caught.value.code == "beta_refresh_state_corrupt"
    assert marker.exists()


def test_remove_revalidates_the_open_marker_inode_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.MARKER_NAME
    backup = root / "authenticated-marker"
    outside = tmp_path / "outside-marker"
    marker.write_bytes(FIXTURE.read_bytes())
    marker.chmod(0o600)
    outside.write_bytes(b"outside-must-survive")
    outside.chmod(0o600)
    real_verify = refresh_pending._verify_named_fd
    marker_checks = 0

    def swap_before_delete(
        dir_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        artifact: str,
    ) -> None:
        nonlocal marker_checks
        if name == refresh_pending.MARKER_NAME:
            marker_checks += 1
            if marker_checks == 2:
                marker.rename(backup)
                marker.symlink_to(outside)
        real_verify(dir_fd, name, opened, artifact=artifact)

    monkeypatch.setattr(refresh_pending, "_verify_named_fd", swap_before_delete)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.remove_pending(root)

    assert caught.value.code == "beta_refresh_state_unsafe"
    assert marker_checks == 2
    assert marker.is_symlink()
    assert backup.read_bytes() == FIXTURE.read_bytes()
    assert outside.read_bytes() == b"outside-must-survive"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema":1,"schema":1,"operation":"refresh"}',
        b'{"schema":1,"operation":"refresh","license_id":"bad\xff"}',
    ],
)
def test_duplicate_keys_and_invalid_utf8_are_rejected(
    tmp_path: Path,
    payload: bytes,
) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.MARKER_NAME
    marker.write_bytes(payload)
    marker.chmod(0o600)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.read_pending(root)

    assert caught.value.code == "beta_refresh_state_corrupt"


@pytest.mark.parametrize("created_at", [True, -1, 1.5, 2**53])
def test_invalid_created_at_is_rejected_before_publish(
    tmp_path: Path,
    created_at: object,
) -> None:
    root = private_root(tmp_path)
    with refresh_pending.refresh_lock(root):
        with pytest.raises(refresh_pending.RefreshPendingError):
            refresh_pending.create_pending(
                root,
                license_id="license-fixture",
                current_refresh_token=A,
                created_at=created_at,  # type: ignore[arg-type]
            )
    assert not (root / refresh_pending.MARKER_NAME).exists()


def test_wrong_owner_identity_rejects_lock_and_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    lock = root / refresh_pending.LOCK_NAME
    lock.write_bytes(b"")
    lock.chmod(0o600)
    marker = root / refresh_pending.MARKER_NAME
    marker.write_bytes(FIXTURE.read_bytes())
    marker.chmod(0o600)
    actual_uid = os.getuid()
    monkeypatch.setattr(refresh_pending.os, "getuid", lambda: actual_uid + 1)

    with pytest.raises(refresh_pending.RefreshPendingError):
        with refresh_pending.refresh_lock(root, timeout_seconds=0):
            pass
    with pytest.raises(refresh_pending.RefreshPendingError):
        refresh_pending.read_pending(root)


def test_marker_publish_and_removal_fsync_file_and_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    real_fsync = os.fsync
    fsynced: list[str] = []

    def audited_fsync(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        fsynced.append("directory" if stat.S_ISDIR(mode) else "file")
        real_fsync(fd)

    monkeypatch.setattr(refresh_pending.os, "fsync", audited_fsync)
    with refresh_pending.refresh_lock(root):
        refresh_pending.create_pending(
            root,
            license_id="license-fixture",
            current_refresh_token=A,
        )
        refresh_pending.remove_pending(root)

    assert "file" in fsynced
    assert fsynced.count("directory") >= 3


def device_payload(value: dict[str, object]) -> bytes:
    return (json.dumps(value, separators=(",", ":")) + "\n").encode()


def deeply_nested_device_payload() -> bytes:
    nested = b"[" * 1100 + b"0" + b"]" * 1100
    original = b'"device_code":"' + str(DEVICE_VALUE["device_code"]).encode() + b'"'
    return DEVICE_FIXTURE.read_bytes().replace(
        original,
        b'"device_code":' + nested,
    )


def write_device_fixture(root: Path, payload: bytes | None = None) -> Path:
    marker = root / refresh_pending.DEVICE_MARKER_NAME
    marker.write_bytes(DEVICE_FIXTURE.read_bytes() if payload is None else payload)
    marker.chmod(0o600)
    return marker


def token32(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode().rstrip("=")


def replacement_device(seed: int = 0) -> refresh_pending.PendingDevice:
    first = 74 + seed * 4
    return refresh_pending.PendingDevice(
        schema=1,
        operation="device",
        device_code=token32(first),
        initial_refresh_token=token32(first + 1),
        recovery_refresh_token=token32(first + 2),
        recovery_attempt_id=token32(first + 3),
        created_at=1784080001 + seed,
    )


def test_device_shared_fixture_parse_read_write_and_exact_cas(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)

    assert refresh_pending.parse_device_pending(DEVICE_FIXTURE.read_bytes()) == expected
    assert refresh_pending.read_device_pending(root) == expected
    marker.unlink()

    with refresh_pending.refresh_lock(root):
        created = refresh_pending.write_device_pending(
            root,
            device_code=expected.device_code,
            initial_refresh_token=expected.initial_refresh_token,
            recovery_refresh_token=expected.recovery_refresh_token,
            recovery_attempt_id=expected.recovery_attempt_id,
            created_at=expected.created_at,
        )
        assert created == expected
        assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert marker.stat().st_nlink == 1

        assert not refresh_pending.remove_device_pending(
            root,
            replace(expected, created_at=expected.created_at + 1),
        )
        assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
        assert refresh_pending.remove_device_pending(root, expected)
        assert not refresh_pending.remove_device_pending(root, expected)

    assert not marker.exists()
    assert not list(root.glob(".license-device-pending-*.tmp"))
    assert root.joinpath(refresh_pending.LOCK_NAME).read_bytes() == b""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", 2),
        ("schema", True),
        ("schema", 1.0),
        ("operation", "refresh"),
        ("created_at", True),
        ("created_at", -1),
        ("created_at", 1.0),
        ("created_at", 1.5),
        ("created_at", 2**53),
    ],
)
def test_device_rejects_invalid_schema_and_timestamp(
    field: str,
    value: object,
) -> None:
    candidate = dict(DEVICE_VALUE)
    candidate[field] = value
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(device_payload(candidate))
    assert caught.value.code == "beta_device_state_corrupt"


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (b'"schema":1', b'"schema":1e0'),
        (b'"schema":1', b'"schema":01'),
        (b'"created_at":1784080000', b'"created_at":-0'),
        (b'"created_at":1784080000', b'"created_at":1784080000e0'),
        (b'"created_at":1784080000', b'"created_at":01784080000'),
    ],
)
def test_device_rejects_noncanonical_integer_wire_spellings(
    original: bytes,
    replacement: bytes,
) -> None:
    payload = DEVICE_FIXTURE.read_bytes().replace(original, replacement)
    assert payload != DEVICE_FIXTURE.read_bytes()

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(payload)

    assert caught.value.code == "beta_device_state_corrupt"


def test_refresh_parser_keeps_legacy_negative_zero_behavior() -> None:
    payload = FIXTURE.read_bytes().replace(
        b'"created_at":1784080000',
        b'"created_at":-0',
    )

    assert refresh_pending._parse_marker(payload).created_at == 0


def test_deeply_nested_same_bytes_are_typed_corrupt_in_parser_and_filesystem(
    tmp_path: Path,
) -> None:
    payload = deeply_nested_device_payload()
    assert len(payload) <= refresh_pending.MAX_MARKER_BYTES

    with pytest.raises(refresh_pending.RefreshPendingError) as parsed:
        refresh_pending.parse_device_pending(payload)
    assert parsed.value.code == "beta_device_state_corrupt"

    root = private_root(tmp_path)
    marker = write_device_fixture(root, payload)
    with pytest.raises(refresh_pending.RefreshPendingError) as loaded:
        refresh_pending.read_device_pending(root)
    assert loaded.value.code == "beta_device_state_corrupt"
    assert marker.read_bytes() == payload


def test_refresh_deep_nesting_is_also_typed_corrupt() -> None:
    nested = b"[" * 1100 + b"0" + b"]" * 1100
    payload = FIXTURE.read_bytes().replace(
        b'"license_id":"license-fixture"',
        b'"license_id":' + nested,
    )
    assert len(payload) <= refresh_pending.MAX_MARKER_BYTES

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending._parse_marker(payload)

    assert caught.value.code == "beta_refresh_state_corrupt"


@pytest.mark.parametrize("field", DEVICE_TOKEN_KEYS)
def test_device_rejects_each_noncanonical_token(field: str) -> None:
    candidate = dict(DEVICE_VALUE)
    candidate[field] = f"{candidate[field]}="
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(device_payload(candidate))
    assert caught.value.code == "beta_device_state_corrupt"


@pytest.mark.parametrize("left,right", combinations(DEVICE_TOKEN_KEYS, 2))
def test_device_rejects_every_equal_token_pair(left: str, right: str) -> None:
    candidate = dict(DEVICE_VALUE)
    candidate[right] = candidate[left]
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(device_payload(candidate))
    assert caught.value.code == "beta_device_state_corrupt"


@pytest.mark.parametrize("field", tuple(DEVICE_VALUE))
def test_device_rejects_every_duplicate_key(field: str) -> None:
    duplicate = json.dumps(DEVICE_VALUE[field], separators=(",", ":"))
    payload = (
        DEVICE_FIXTURE.read_bytes().rstrip()[:-1]
        + f',"{field}":{duplicate}}}\n'.encode()
    )
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(payload)
    assert caught.value.code == "beta_device_state_corrupt"


@pytest.mark.parametrize(
    "change", ["missing", "extra", "array", "invalid-utf8", "oversize"]
)
def test_device_rejects_unknown_encoding_and_size(change: str) -> None:
    candidate = dict(DEVICE_VALUE)
    if change == "missing":
        candidate.pop("device_code")
        payload = device_payload(candidate)
    elif change == "extra":
        candidate["future"] = True
        payload = device_payload(candidate)
    elif change == "array":
        payload = b"[]"
    elif change == "invalid-utf8":
        payload = b'{"schema":1,"device_code":"\xff"}'
    else:
        payload = b"{" + b" " * refresh_pending.MAX_MARKER_BYTES + b"}"
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.parse_device_pending(payload)
    assert caught.value.code == "beta_device_state_corrupt"


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "public", "directory"])
def test_device_marker_filesystem_attacks_fail_closed(
    tmp_path: Path,
    attack: str,
) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.DEVICE_MARKER_NAME
    outside = tmp_path / "outside-device"
    outside.write_bytes(DEVICE_FIXTURE.read_bytes())
    outside.chmod(0o600)
    if attack == "symlink":
        marker.symlink_to(outside)
    elif attack == "hardlink":
        os.link(outside, marker)
    elif attack == "public":
        marker.write_bytes(DEVICE_FIXTURE.read_bytes())
        marker.chmod(0o644)
    else:
        marker.mkdir(mode=0o700)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.read_device_pending(root)
    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.exists() or marker.is_symlink()


@pytest.mark.parametrize(
    ("marker_name", "reader", "expected_code"),
    [
        (
            refresh_pending.MARKER_NAME,
            "read_pending",
            "beta_refresh_state_unsafe",
        ),
        (
            refresh_pending.DEVICE_MARKER_NAME,
            "read_device_pending",
            "beta_device_state_unsafe",
        ),
    ],
)
def test_fifo_marker_fails_typed_without_blocking(
    tmp_path: Path,
    marker_name: str,
    reader: str,
    expected_code: str,
) -> None:
    root = private_root(tmp_path)
    marker = root / marker_name
    os.mkfifo(marker, 0o600)
    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from elevate_cli import refresh_pending as rp",
            "try:",
            "    getattr(rp, sys.argv[2])(Path(sys.argv[1]))",
            "except rp.RefreshPendingError as exc:",
            "    print(exc.code)",
            "    raise SystemExit(0)",
            "raise SystemExit(3)",
        ]
    )

    result = subprocess.run(
        [sys.executable, "-c", script, str(root), reader],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected_code
    assert stat.S_ISFIFO(marker.lstat().st_mode)
    marker.unlink()
    assert not marker.exists()


def test_device_marker_wrong_owner_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    actual_uid = os.getuid()
    monkeypatch.setattr(refresh_pending.os, "getuid", lambda: actual_uid + 1)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.read_device_pending(root)

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.exists()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema":1,"schema":1,"operation":"device"}',
        b"{" + b" " * refresh_pending.MAX_MARKER_BYTES + b"}",
    ],
)
def test_device_corrupt_marker_is_never_cas_removed(
    tmp_path: Path,
    payload: bytes,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root, payload)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)

    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.remove_device_pending(root, expected)

    assert caught.value.code == "beta_device_state_corrupt"
    assert marker.read_bytes() == payload


def test_refresh_and_device_markers_are_mutually_exclusive(tmp_path: Path) -> None:
    device_root = private_root(tmp_path / "device")
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    with refresh_pending.refresh_lock(device_root):
        refresh_pending.write_device_pending(
            device_root,
            device_code=expected.device_code,
            initial_refresh_token=expected.initial_refresh_token,
            recovery_refresh_token=expected.recovery_refresh_token,
            recovery_attempt_id=expected.recovery_attempt_id,
            created_at=expected.created_at,
        )
        with pytest.raises(refresh_pending.RefreshPendingError) as refresh_conflict:
            refresh_pending.create_pending(
                device_root,
                license_id="license-fixture",
                current_refresh_token=A,
            )
        assert refresh_conflict.value.code == "beta_refresh_state_conflict"

    refresh_root = private_root(tmp_path / "refresh")
    with refresh_pending.refresh_lock(refresh_root):
        refresh_pending.create_pending(
            refresh_root,
            license_id="license-fixture",
            current_refresh_token=A,
        )
        with pytest.raises(refresh_pending.RefreshPendingError) as device_conflict:
            refresh_pending.write_device_pending(
                refresh_root,
                device_code=expected.device_code,
                initial_refresh_token=expected.initial_refresh_token,
                recovery_refresh_token=expected.recovery_refresh_token,
                recovery_attempt_id=expected.recovery_attempt_id,
            )
        assert device_conflict.value.code == "beta_device_state_conflict"


def test_device_partial_writes_are_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    real_write = os.write
    partial_writes = 0

    def short_write(fd: int, payload: bytes) -> int:
        nonlocal partial_writes
        partial_writes += 1
        return real_write(fd, payload[: max(1, len(payload) // 2)])

    with refresh_pending.refresh_lock(root):
        monkeypatch.setattr(refresh_pending.os, "write", short_write)
        refresh_pending.write_device_pending(
            root,
            device_code=expected.device_code,
            initial_refresh_token=expected.initial_refresh_token,
            recovery_refresh_token=expected.recovery_refresh_token,
            recovery_attempt_id=expected.recovery_attempt_id,
            created_at=expected.created_at,
        )

    assert partial_writes > 1
    assert root.joinpath(refresh_pending.DEVICE_MARKER_NAME).read_bytes() == (
        DEVICE_FIXTURE.read_bytes()
    )


def test_device_post_publish_fsync_failure_retains_exact_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    real_fsync = os.fsync

    with refresh_pending.refresh_lock(root):

        def fail_directory_fsync(fd: int) -> None:
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory fsync failure")
            real_fsync(fd)

        monkeypatch.setattr(refresh_pending.os, "fsync", fail_directory_fsync)
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.write_device_pending(
                root,
                device_code=expected.device_code,
                initial_refresh_token=expected.initial_refresh_token,
                recovery_refresh_token=expected.recovery_refresh_token,
                recovery_attempt_id=expected.recovery_attempt_id,
                created_at=expected.created_at,
            )
        assert caught.value.code == "beta_device_persistence_failed"

    assert root.joinpath(refresh_pending.DEVICE_MARKER_NAME).read_bytes() == (
        DEVICE_FIXTURE.read_bytes()
    )


def test_device_readback_failure_retains_exact_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    real_read = refresh_pending.read_device_pending
    reads = 0

    def fail_second_read(target: Path) -> refresh_pending.PendingDevice | None:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise refresh_pending.RefreshPendingError(
                "beta_device_state_unsafe",
                "injected readback failure",
            )
        return real_read(target)

    with refresh_pending.refresh_lock(root):
        monkeypatch.setattr(refresh_pending, "read_device_pending", fail_second_read)
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.write_device_pending(
                root,
                device_code=expected.device_code,
                initial_refresh_token=expected.initial_refresh_token,
                recovery_refresh_token=expected.recovery_refresh_token,
                recovery_attempt_id=expected.recovery_attempt_id,
                created_at=expected.created_at,
            )
        assert caught.value.code == "beta_device_state_unsafe"

    assert root.joinpath(refresh_pending.DEVICE_MARKER_NAME).read_bytes() == (
        DEVICE_FIXTURE.read_bytes()
    )


def test_device_cas_revalidates_open_inode_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    backup = root / "authenticated-device-marker"
    outside = tmp_path / "outside-device-swap"
    outside.write_bytes(b"outside-must-survive")
    outside.chmod(0o600)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    real_verify = refresh_pending._verify_named_fd
    marker_checks = 0

    def swap_before_delete(
        dir_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        artifact: str,
        unsafe_code: str = "beta_refresh_state_unsafe",
        state_label: str = "refresh",
    ) -> None:
        nonlocal marker_checks
        if name == refresh_pending.DEVICE_MARKER_NAME:
            marker_checks += 1
            if marker_checks == 2:
                marker.rename(backup)
                marker.symlink_to(outside)
        real_verify(
            dir_fd,
            name,
            opened,
            artifact=artifact,
            unsafe_code=unsafe_code,
            state_label=state_label,
        )

    monkeypatch.setattr(refresh_pending, "_verify_named_fd", swap_before_delete)
    with pytest.raises(refresh_pending.RefreshPendingError) as caught:
        refresh_pending.remove_device_pending(root, expected)

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker_checks == 2
    assert marker.is_symlink()
    assert backup.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert outside.read_bytes() == b"outside-must-survive"


def test_device_replace_is_one_atomic_exact_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    replacement = replacement_device()
    real_replace = os.replace
    real_unlink = os.unlink
    transitions: list[str] = []

    def audited_replace(
        source: str,
        target: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert source.startswith(".license-device-pending-")
        assert target == refresh_pending.DEVICE_MARKER_NAME
        assert marker.read_bytes() == expected.to_bytes()
        transitions.append("old")
        real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        assert marker.read_bytes() == replacement.to_bytes()
        transitions.append("new")

    def reject_marker_unlink(
        target: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        assert target != refresh_pending.DEVICE_MARKER_NAME
        real_unlink(target, dir_fd=dir_fd)

    monkeypatch.setattr(refresh_pending.os, "replace", audited_replace)
    monkeypatch.setattr(refresh_pending.os, "unlink", reject_marker_unlink)
    with refresh_pending.refresh_lock(root) as guard:
        assert refresh_pending.replace_device_pending(
            root,
            expected,
            replacement,
            lock_guard=guard,
        )

    assert transitions == ["old", "new"]
    assert marker.read_bytes() == replacement.to_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))
    with refresh_pending.refresh_lock(root) as guard:
        assert not refresh_pending.replace_device_pending(
            root,
            expected,
            replacement_device(1),
            lock_guard=guard,
        )
    assert marker.read_bytes() == replacement.to_bytes()


def test_device_replace_missing_expected_is_a_clean_cas_miss(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    with refresh_pending.refresh_lock(root) as guard:
        assert not refresh_pending.replace_device_pending(
            root,
            expected,
            replacement_device(),
            lock_guard=guard,
        )
    assert not root.joinpath(refresh_pending.DEVICE_MARKER_NAME).exists()
    assert not list(root.glob(".license-device-pending-*.tmp"))


@pytest.mark.parametrize(
    ("which", "invalid"),
    [
        ("expected", object()),
        ("replacement", object()),
        ("replacement", replace(replacement_device(), schema=2)),
        ("replacement", replace(replacement_device(), created_at=True)),
        (
            "replacement",
            replace(
                replacement_device(),
                recovery_refresh_token=replacement_device().initial_refresh_token,
            ),
        ),
    ],
)
def test_device_replace_validates_both_exact_schemas_before_touching_disk(
    tmp_path: Path,
    which: str,
    invalid: object,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    expected: object = refresh_pending.PendingDevice(**DEVICE_VALUE)
    replacement: object = replacement_device()
    if which == "expected":
        expected = invalid
    else:
        replacement = invalid

    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                expected,  # type: ignore[arg-type]
                replacement,  # type: ignore[arg-type]
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_corrupt"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


@pytest.mark.parametrize(
    ("attack", "expected_code"),
    [
        ("symlink", "beta_device_state_unsafe"),
        ("hardlink", "beta_device_state_unsafe"),
        ("public", "beta_device_state_unsafe"),
        ("directory", "beta_device_state_unsafe"),
        ("fifo", "beta_device_state_unsafe"),
        ("invalid-utf8", "beta_device_state_corrupt"),
        ("duplicate", "beta_device_state_corrupt"),
        ("deep", "beta_device_state_corrupt"),
        ("oversize", "beta_device_state_corrupt"),
    ],
)
def test_device_replace_rejects_unsafe_or_corrupt_current_marker(
    tmp_path: Path,
    attack: str,
    expected_code: str,
) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.DEVICE_MARKER_NAME
    outside = tmp_path / "outside-replace"
    outside.write_bytes(DEVICE_FIXTURE.read_bytes())
    outside.chmod(0o600)
    if attack == "symlink":
        marker.symlink_to(outside)
    elif attack == "hardlink":
        os.link(outside, marker)
    elif attack == "public":
        marker.write_bytes(DEVICE_FIXTURE.read_bytes())
        marker.chmod(0o644)
    elif attack == "directory":
        marker.mkdir(mode=0o700)
    elif attack == "fifo":
        os.mkfifo(marker, 0o600)
    elif attack == "invalid-utf8":
        marker.write_bytes(b'{"schema":1,"device_code":"\xff"}')
        marker.chmod(0o600)
    elif attack == "duplicate":
        marker.write_bytes(b'{"schema":1,"schema":1,"operation":"device"}')
        marker.chmod(0o600)
    elif attack == "deep":
        marker.write_bytes(deeply_nested_device_payload())
        marker.chmod(0o600)
    else:
        marker.write_bytes(b"{" + b" " * refresh_pending.MAX_MARKER_BYTES + b"}")
        marker.chmod(0o600)
    before = marker.lstat()

    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    after = marker.lstat()
    assert caught.value.code == expected_code
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    assert outside.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_preserves_refresh_device_mutual_exclusion(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    device = write_device_fixture(root)
    refresh = root / refresh_pending.MARKER_NAME
    refresh.write_bytes(FIXTURE.read_bytes())
    refresh.chmod(0o600)

    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_conflict"
    assert device.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert refresh.read_bytes() == FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))

    refresh_only_root = private_root(tmp_path / "refresh-only")
    refresh_only = refresh_only_root / refresh_pending.MARKER_NAME
    refresh_only.write_bytes(FIXTURE.read_bytes())
    refresh_only.chmod(0o600)
    with refresh_pending.refresh_lock(refresh_only_root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as refresh_only_error:
            refresh_pending.replace_device_pending(
                refresh_only_root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )
    assert refresh_only_error.value.code == "beta_device_state_conflict"
    assert refresh_only.read_bytes() == FIXTURE.read_bytes()
    assert not refresh_only_root.joinpath(
        refresh_pending.DEVICE_MARKER_NAME
    ).exists()


def test_device_replace_detects_same_inode_expected_value_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    third_winner = replacement_device(2)
    real_read = refresh_pending._read_device_pending_fd
    reads = 0

    def mutate_before_boundary_read(fd: int) -> refresh_pending.PendingDevice:
        nonlocal reads
        reads += 1
        if reads == 2:
            payload = third_winner.to_bytes()
            writer = os.open(marker, os.O_WRONLY)
            try:
                assert os.write(writer, payload) == len(payload)
                os.ftruncate(writer, len(payload))
                os.fsync(writer)
            finally:
                os.close(writer)
        return real_read(fd)

    monkeypatch.setattr(
        refresh_pending,
        "_read_device_pending_fd",
        mutate_before_boundary_read,
    )
    with refresh_pending.refresh_lock(root) as guard:
        assert not refresh_pending.replace_device_pending(
            root,
            expected,
            replacement_device(),
            lock_guard=guard,
        )

    assert reads == 2
    assert marker.read_bytes() == third_winner.to_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_detects_same_inode_temp_payload_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    replacement = replacement_device()
    mutated_temp = replacement_device(1)
    assert len(mutated_temp.to_bytes()) == len(replacement.to_bytes())
    real_read = refresh_pending._read_bounded_fd
    marker_fd: int | None = None
    reads_by_fd: dict[int, int] = {}

    def mutate_second_temp_read(fd: int) -> bytes:
        nonlocal marker_fd
        if marker_fd is None:
            marker_fd = fd
        reads_by_fd[fd] = reads_by_fd.get(fd, 0) + 1
        if fd != marker_fd and reads_by_fd[fd] == 2:
            payload = mutated_temp.to_bytes()
            os.lseek(fd, 0, os.SEEK_SET)
            assert os.write(fd, payload) == len(payload)
            os.ftruncate(fd, len(payload))
            os.fsync(fd)
        return real_read(fd)

    monkeypatch.setattr(refresh_pending, "_read_bounded_fd", mutate_second_temp_read)
    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement,
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_persistence_failed"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_inode_swap_retains_competing_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    authenticated = root / "authenticated-device-replace"
    third_winner = replacement_device(2)
    real_verify = refresh_pending._verify_named_fd
    marker_checks = 0

    def swap_before_boundary_authentication(
        dir_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        artifact: str,
        unsafe_code: str = "beta_refresh_state_unsafe",
        state_label: str = "refresh",
    ) -> None:
        nonlocal marker_checks
        if name == refresh_pending.DEVICE_MARKER_NAME:
            marker_checks += 1
            if marker_checks == 2:
                marker.rename(authenticated)
                marker.write_bytes(third_winner.to_bytes())
                marker.chmod(0o600)
        real_verify(
            dir_fd,
            name,
            opened,
            artifact=artifact,
            unsafe_code=unsafe_code,
            state_label=state_label,
        )

    monkeypatch.setattr(
        refresh_pending,
        "_verify_named_fd",
        swap_before_boundary_authentication,
    )
    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker_checks == 2
    assert authenticated.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert marker.read_bytes() == third_winner.to_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_real_lock_loss_before_work_retains_old_marker(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    with refresh_pending.refresh_lock(root) as guard:
        refresh_pending.fcntl.flock(guard.fd, refresh_pending.fcntl.LOCK_UN)
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_real_lock_loss_at_boundary_retains_old_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    real_read = refresh_pending._read_bounded_fd
    reads = 0

    with refresh_pending.refresh_lock(root) as guard:

        def unlock_after_initial_guard(fd: int) -> bytes:
            nonlocal reads
            reads += 1
            if reads == 2:
                refresh_pending.fcntl.flock(
                    guard.fd,
                    refresh_pending.fcntl.LOCK_UN,
                )
            return real_read(fd)

        monkeypatch.setattr(
            refresh_pending,
            "_read_bounded_fd",
            unlock_after_initial_guard,
        )
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert reads == 2
    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_rejects_forged_live_same_root_guard(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    dir_fd, fd = refresh_pending._open_lock(root)
    forged = refresh_pending.RefreshLockGuard(dir_fd=dir_fd, fd=fd)
    try:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=forged,
            )
    finally:
        os.close(fd)
        os.close(dir_fd)

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_rejects_lock_guard_from_another_profile(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path / "target")
    other_root = private_root(tmp_path / "other")
    marker = write_device_fixture(root)

    with refresh_pending.refresh_lock(other_root) as wrong_guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=wrong_guard,
            )

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


@pytest.mark.parametrize(
    "phase",
    ["write-error", "write-no-progress", "file-fsync", "temp-readback", "replace"],
)
def test_device_replace_pre_rename_faults_retain_old_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    real_write = os.write
    real_fsync = os.fsync
    real_read = refresh_pending._read_bounded_fd
    reads = 0

    with refresh_pending.refresh_lock(root) as guard:
        if phase == "write-error":

            def fail_write(_fd: int, _payload: bytes) -> int:
                raise OSError("injected replacement write failure")

            monkeypatch.setattr(refresh_pending.os, "write", fail_write)
        elif phase == "write-no-progress":
            monkeypatch.setattr(refresh_pending.os, "write", lambda _fd, _data: 0)
        elif phase == "file-fsync":

            def fail_payload_fsync(fd: int) -> None:
                file_stat = os.fstat(fd)
                if stat.S_ISREG(file_stat.st_mode) and file_stat.st_size:
                    raise OSError("injected replacement fsync failure")
                real_fsync(fd)

            monkeypatch.setattr(refresh_pending.os, "fsync", fail_payload_fsync)
        elif phase == "temp-readback":

            def fail_temp_readback(fd: int) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 2:
                    raise OSError("injected replacement readback failure")
                return real_read(fd)

            monkeypatch.setattr(
                refresh_pending,
                "_read_bounded_fd",
                fail_temp_readback,
            )
        else:

            def fail_replace(*_args: object, **_kwargs: object) -> None:
                raise OSError("injected pre-rename failure")

            monkeypatch.setattr(refresh_pending.os, "replace", fail_replace)

        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_persistence_failed"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))
    monkeypatch.setattr(refresh_pending.os, "write", real_write)


@pytest.mark.parametrize("phase", ["replace-raised", "directory-fsync", "readback"])
def test_device_replace_post_rename_faults_retain_new_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    replacement = replacement_device()
    real_replace = os.replace
    real_fsync = os.fsync

    with refresh_pending.refresh_lock(root) as guard:
        if phase == "replace-raised":

            def replace_then_raise(
                source: str,
                target: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                real_replace(
                    source,
                    target,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
                raise OSError("injected error after rename")

            monkeypatch.setattr(refresh_pending.os, "replace", replace_then_raise)
        elif phase == "directory-fsync":

            def fail_post_rename_directory_fsync(fd: int) -> None:
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("injected post-rename directory fsync failure")
                real_fsync(fd)

            monkeypatch.setattr(
                refresh_pending.os,
                "fsync",
                fail_post_rename_directory_fsync,
            )
        else:

            def fail_post_rename_readback(
                _dir_fd: int,
            ) -> refresh_pending.PendingDevice | None:
                raise OSError("injected post-rename readback failure")

            monkeypatch.setattr(
                refresh_pending,
                "_read_device_pending_from_dir_fd",
                fail_post_rename_readback,
            )

        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement,
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_persistence_failed"
    assert marker.read_bytes() == replacement.to_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_post_rename_readback_retains_third_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    replacement = replacement_device()
    third_winner = replacement_device(2)
    real_reader = refresh_pending._read_device_pending_from_dir_fd
    real_replace = os.replace

    def install_third_winner(dir_fd: int) -> refresh_pending.PendingDevice | None:
        winner_temp = root / ".independent-device-winner.tmp"
        winner_temp.write_bytes(third_winner.to_bytes())
        winner_temp.chmod(0o600)
        real_replace(winner_temp, marker)
        return real_reader(dir_fd)

    monkeypatch.setattr(
        refresh_pending,
        "_read_device_pending_from_dir_fd",
        install_third_winner,
    )
    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement,
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_persistence_failed"
    assert marker.read_bytes() == third_winner.to_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


def test_device_replace_temp_path_swap_is_retained_and_never_cleaned_as_ours(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    outside = tmp_path / "outside-temp-winner"
    outside.write_bytes(b"outside-temp-must-survive")
    outside.chmod(0o600)
    authenticated_temp = root / "authenticated-device-temp"
    real_verify = refresh_pending._verify_named_fd
    temp_checks = 0
    swapped_name: str | None = None

    def swap_temp_path(
        dir_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        artifact: str,
        unsafe_code: str = "beta_refresh_state_unsafe",
        state_label: str = "refresh",
    ) -> None:
        nonlocal temp_checks, swapped_name
        if name.startswith(".license-device-pending-"):
            temp_checks += 1
            if temp_checks == 2:
                swapped_name = name
                temp_path = root / name
                temp_path.rename(authenticated_temp)
                temp_path.symlink_to(outside)
        real_verify(
            dir_fd,
            name,
            opened,
            artifact=artifact,
            unsafe_code=unsafe_code,
            state_label=state_label,
        )

    monkeypatch.setattr(refresh_pending, "_verify_named_fd", swap_temp_path)
    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_unsafe"
    assert temp_checks == 2
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert authenticated_temp.read_bytes() == replacement_device().to_bytes()
    assert swapped_name is not None
    assert root.joinpath(swapped_name).is_symlink()
    assert outside.read_bytes() == b"outside-temp-must-survive"


def test_device_replace_cleanup_unlink_failure_leaves_only_private_inert_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    replacement = replacement_device()
    real_unlink = os.unlink

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected pre-rename failure")

    def fail_temp_unlink(
        target: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if str(target).startswith(".license-device-pending-"):
            raise OSError("injected temp cleanup failure")
        real_unlink(target, dir_fd=dir_fd)

    with refresh_pending.refresh_lock(root) as guard:
        monkeypatch.setattr(refresh_pending.os, "replace", fail_replace)
        monkeypatch.setattr(refresh_pending.os, "unlink", fail_temp_unlink)
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement,
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_persistence_failed"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    temps = list(root.glob(".license-device-pending-*.tmp"))
    assert len(temps) == 1
    temp = temps[0]
    assert re.fullmatch(r"\.license-device-pending-[0-9a-f]{32}\.tmp", temp.name)
    temp_stat = temp.stat()
    assert stat.S_ISREG(temp_stat.st_mode)
    assert stat.S_IMODE(temp_stat.st_mode) == 0o600
    assert temp_stat.st_nlink == 1
    assert temp_stat.st_uid == os.getuid()
    assert temp.read_bytes() == replacement.to_bytes()
    real_unlink(temp)


def test_device_replace_owner_drift_fails_typed_before_marker_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    actual_uid = os.getuid()
    real_guard_check = refresh_pending._assert_device_lock_guard
    checks = 0

    def shift_identity_after_guard(
        guard: refresh_pending.RefreshLockGuard,
        dir_fd: int,
    ) -> None:
        nonlocal checks
        checks += 1
        real_guard_check(guard, dir_fd)
        if checks == 1:
            monkeypatch.setattr(refresh_pending.os, "getuid", lambda: actual_uid + 1)

    monkeypatch.setattr(
        refresh_pending,
        "_assert_device_lock_guard",
        shift_identity_after_guard,
    )
    with refresh_pending.refresh_lock(root) as guard:
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            refresh_pending.replace_device_pending(
                root,
                refresh_pending.PendingDevice(**DEVICE_VALUE),
                replacement_device(),
                lock_guard=guard,
            )

    assert caught.value.code == "beta_device_state_unsafe"
    assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    assert not list(root.glob(".license-device-pending-*.tmp"))


@pytest.mark.parametrize(("phase", "exit_code"), [("before", 73), ("after", 74)])
def test_device_replace_process_crash_linearizes_to_old_or_new(
    tmp_path: Path,
    phase: str,
    exit_code: int,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)
    replacement = replacement_device()
    script = "\n".join(
        [
            "import json, os, sys",
            "from pathlib import Path",
            "from elevate_cli import refresh_pending as rp",
            "phase = sys.argv[1]",
            "root = Path(sys.argv[2])",
            "expected = rp.PendingDevice(**json.loads(sys.argv[3]))",
            "replacement = rp.PendingDevice(**json.loads(sys.argv[4]))",
            "real_replace = rp.os.replace",
            "def crash_replace(source, target, *, src_dir_fd=None, dst_dir_fd=None):",
            "    if phase == 'before':",
            "        os._exit(73)",
            "    real_replace(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)",
            "    os._exit(74)",
            "rp.os.replace = crash_replace",
            "with rp.refresh_lock(root) as guard:",
            "    rp.replace_device_pending(root, expected, replacement, lock_guard=guard)",
            "raise SystemExit(3)",
        ]
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            phase,
            str(root),
            expected.to_bytes().decode(),
            replacement.to_bytes().decode(),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == exit_code, result.stderr
    temps = list(root.glob(".license-device-pending-*.tmp"))
    if phase == "before":
        assert marker.read_bytes() == expected.to_bytes()
        assert len(temps) == 1
        assert temps[0].read_bytes() == replacement.to_bytes()
        assert stat.S_IMODE(temps[0].stat().st_mode) == 0o600
        temps[0].unlink()
    else:
        assert marker.read_bytes() == replacement.to_bytes()
        assert not temps


def test_device_replace_shared_lock_blocks_another_process(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    marker = write_device_fixture(root)
    ready = tmp_path / "holder-ready"
    release = tmp_path / "holder-release"
    script = "\n".join(
        [
            "import sys, time",
            "from pathlib import Path",
            "from elevate_cli import refresh_pending as rp",
            "root, ready, release = map(Path, sys.argv[1:4])",
            "with rp.refresh_lock(root):",
            "    ready.write_text('ready')",
            "    deadline = time.monotonic() + 5",
            "    while not release.exists() and time.monotonic() < deadline:",
            "        time.sleep(0.01)",
            "    if not release.exists():",
            "        raise SystemExit(4)",
        ]
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(root), str(ready), str(release)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            if holder.poll() is not None:
                break
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(refresh_pending.RefreshPendingError) as caught:
            with refresh_pending.refresh_lock(root, timeout_seconds=0):
                pass
        assert caught.value.code == "beta_refresh_lock_timeout"

        dir_fd, fd = refresh_pending._open_lock(root)
        forged = refresh_pending.RefreshLockGuard(dir_fd=dir_fd, fd=fd)
        try:
            with pytest.raises(refresh_pending.RefreshPendingError) as forged_error:
                refresh_pending.replace_device_pending(
                    root,
                    refresh_pending.PendingDevice(**DEVICE_VALUE),
                    replacement_device(),
                    lock_guard=forged,
                )
        finally:
            os.close(fd)
            os.close(dir_fd)
        assert forged_error.value.code == "beta_device_state_unsafe"
        assert marker.read_bytes() == DEVICE_FIXTURE.read_bytes()
    finally:
        release.touch()
        stdout, stderr = holder.communicate(timeout=5)
    assert holder.returncode == 0, stdout + stderr

    with refresh_pending.refresh_lock(root) as guard:
        assert refresh_pending.replace_device_pending(
            root,
            refresh_pending.PendingDevice(**DEVICE_VALUE),
            replacement_device(),
            lock_guard=guard,
        )
    assert marker.read_bytes() == replacement_device().to_bytes()


def test_device_replace_repeated_two_process_race_has_one_exact_winner(
    tmp_path: Path,
) -> None:
    script = "\n".join(
        [
            "import json, sys, time",
            "from pathlib import Path",
            "from elevate_cli import refresh_pending as rp",
            "root, gate = Path(sys.argv[1]), Path(sys.argv[2])",
            "expected = rp.PendingDevice(**json.loads(sys.argv[3]))",
            "replacement = rp.PendingDevice(**json.loads(sys.argv[4]))",
            "deadline = time.monotonic() + 5",
            "while not gate.exists() and time.monotonic() < deadline:",
            "    time.sleep(0.001)",
            "if not gate.exists():",
            "    raise SystemExit(4)",
            "with rp.refresh_lock(root) as guard:",
            "    won = rp.replace_device_pending(root, expected, replacement, lock_guard=guard)",
            "print('1' if won else '0', flush=True)",
        ]
    )
    expected = refresh_pending.PendingDevice(**DEVICE_VALUE)

    for iteration in range(8):
        root = private_root(tmp_path / str(iteration))
        marker = write_device_fixture(root)
        gate = tmp_path / f"race-{iteration}-go"
        left = replacement_device(iteration * 2)
        right = replacement_device(iteration * 2 + 1)
        common = [
            sys.executable,
            "-c",
            script,
            str(root),
            str(gate),
            expected.to_bytes().decode(),
        ]
        contenders = [
            subprocess.Popen(
                [*common, candidate.to_bytes().decode()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for candidate in (left, right)
        ]
        gate.touch()
        results = [contender.communicate(timeout=5) for contender in contenders]
        assert [contender.returncode for contender in contenders] == [0, 0]
        assert sorted(stdout.strip() for stdout, _stderr in results) == ["0", "1"]
        assert all(not stderr for _stdout, stderr in results)
        assert marker.read_bytes() in {left.to_bytes(), right.to_bytes()}
        assert not list(root.glob(".license-device-pending-*.tmp"))
