import json
import os
import stat
from pathlib import Path

import pytest

from elevate_cli import refresh_pending


FIXTURE = Path(__file__).parents[1] / "fixtures" / "beta-refresh-pending-v1.json"
A = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE"


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / ".elevate-beta"
    root.mkdir(mode=0o700)
    return root


def test_shared_fixture_schema_and_atomic_round_trip(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    marker = root / refresh_pending.MARKER_NAME
    marker.write_bytes(FIXTURE.read_bytes())
    marker.chmod(0o600)

    expected = json.loads(FIXTURE.read_text())
    assert refresh_pending.read_pending(root) == refresh_pending.PendingRefresh(**expected)

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
