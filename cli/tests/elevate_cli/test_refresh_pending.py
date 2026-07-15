import json
import os
import stat
import subprocess
import sys
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
