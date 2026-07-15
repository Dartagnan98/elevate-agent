"""Crash-safe shared pending state for exact-Beta credential transitions.

Python and the desktop runtime intentionally share the artifact names, JSON
schemas, and BSD ``flock`` lock.  The markers contain bearer credentials, so
every path is opened without following symlinks and must remain a private,
single-link file owned by the current account.  Refresh and pre-license Device
operations use separate markers but one lock, so callers can recover either
operation without allowing the credential transitions to overlap.
"""

from __future__ import annotations

import base64
import errno
import fcntl
import json
import os
import re
import secrets
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


LOCK_NAME = ".license-refresh.lock"
MARKER_NAME = ".license-refresh-pending.json"
DEVICE_MARKER_NAME = ".license-device-pending.json"
SCHEMA_KEYS = frozenset(
    {
        "schema",
        "operation",
        "license_id",
        "current_refresh_token",
        "successor_refresh_token",
        "attempt_id",
        "created_at",
    }
)
DEVICE_SCHEMA_KEYS = frozenset(
    {
        "schema",
        "operation",
        "device_code",
        "initial_refresh_token",
        "recovery_refresh_token",
        "recovery_attempt_id",
        "created_at",
    }
)
MAX_MARKER_BYTES = 16 * 1024


class RefreshPendingError(Exception):
    """Typed local-state failure surfaced by the license client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _SourceInteger(int):
    """A parsed JSON integer that retains its exact wire spelling."""

    source: str

    def __new__(cls, source: str) -> _SourceInteger:
        value = int.__new__(cls, source)
        value.source = source
        return value


@dataclass(frozen=True)
class PendingRefresh:
    schema: int
    operation: str
    license_id: str
    current_refresh_token: str
    successor_refresh_token: str
    attempt_id: str
    created_at: int

    def to_bytes(self) -> bytes:
        return (json.dumps(asdict(self), separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class PendingDevice:
    """Exact pre-license Device v3 recovery state shared by both clients."""

    schema: int
    operation: str
    device_code: str
    initial_refresh_token: str
    recovery_refresh_token: str
    recovery_attempt_id: str
    created_at: int

    def to_bytes(self) -> bytes:
        return (json.dumps(asdict(self), separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class RefreshLockGuard:
    """Proof that the named lock still resolves to the held inode."""

    dir_fd: int
    fd: int

    def assert_held(self) -> None:
        opened = _validate_private_file(self.fd, artifact="lock", empty=True)
        _verify_named_fd(self.dir_fd, LOCK_NAME, opened, artifact="lock")


def canonical_token32(value: object) -> bool:
    """Return whether *value* is canonical unpadded base64url for 32 bytes."""
    if not isinstance(value, str) or len(value) != 43:
        return False
    try:
        raw = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return False
    return (
        len(raw) == 32
        and base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") == value
    )


def generate_token32() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _error(
    code: str, message: str, cause: BaseException | None = None
) -> RefreshPendingError:
    error = RefreshPendingError(code, message)
    if cause is not None:
        error.__cause__ = cause
    return error


def _directory_fd(root: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(root, flags)


def _validate_private_file(
    fd: int,
    *,
    artifact: str,
    empty: bool = False,
    unsafe_code: str = "beta_refresh_state_unsafe",
    state_label: str = "refresh",
) -> os.stat_result:
    file_stat = os.fstat(fd)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) != 0o600
        or (hasattr(os, "getuid") and file_stat.st_uid != os.getuid())
        or (empty and file_stat.st_size != 0)
    ):
        raise _error(
            unsafe_code,
            f"Realtor Beta could not verify its private {state_label} {artifact}.",
        )
    return file_stat


def _verify_named_fd(
    dir_fd: int,
    name: str,
    opened: os.stat_result,
    *,
    artifact: str,
    unsafe_code: str = "beta_refresh_state_unsafe",
    state_label: str = "refresh",
) -> None:
    named = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(named.st_mode)
        or named.st_dev != opened.st_dev
        or named.st_ino != opened.st_ino
        or named.st_nlink != 1
    ):
        raise _error(
            unsafe_code,
            f"Realtor Beta could not verify its {state_label} {artifact} path.",
        )


def _open_lock(root: Path) -> tuple[int, int]:
    dir_fd = _directory_fd(root)
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        try:
            fd = os.open(
                LOCK_NAME,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            created = True
        except FileExistsError:
            fd = os.open(LOCK_NAME, flags, dir_fd=dir_fd)
        try:
            if created:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
                os.fsync(dir_fd)
            opened = _validate_private_file(fd, artifact="lock", empty=True)
            _verify_named_fd(dir_fd, LOCK_NAME, opened, artifact="lock")
            return dir_fd, fd
        except Exception:
            os.close(fd)
            raise
    except Exception:
        os.close(dir_fd)
        raise


@contextmanager
def refresh_lock(
    root: Path,
    *,
    timeout_seconds: float = 30.0,
) -> Iterator[RefreshLockGuard]:
    """Hold the shared BSD lock for one complete refresh transaction."""
    try:
        dir_fd, fd = _open_lock(root)
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_refresh_state_unsafe",
            "Realtor Beta could not open its protected refresh lock.",
            exc,
        )
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    acquired = False
    try:
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno == errno.EINTR:
                        continue
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    if time.monotonic() >= deadline:
                        raise _error(
                            "beta_refresh_lock_timeout",
                            "Another Realtor Beta process is still refreshing this account.",
                        ) from exc
                    time.sleep(0.05)
            opened = _validate_private_file(fd, artifact="lock", empty=True)
            _verify_named_fd(dir_fd, LOCK_NAME, opened, artifact="lock")
        except RefreshPendingError:
            raise
        except Exception as exc:
            raise _error(
                "beta_refresh_state_unsafe",
                "Realtor Beta could not safely coordinate account refresh.",
                exc,
            )
        # Exceptions raised by the refresh body must retain their own typed
        # meaning; the lock layer only translates acquisition failures.
        yield RefreshLockGuard(dir_fd=dir_fd, fd=fd)
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)
        os.close(dir_fd)


def _decode_marker_object(
    raw: bytes,
    *,
    corrupt_code: str,
    subject: str,
    capture_integer_sources: bool = False,
) -> dict[str, object]:
    if len(raw) > MAX_MARKER_BYTES:
        raise _error(
            corrupt_code,
            f"The Realtor Beta pending {subject} state is too large.",
        )
    try:

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"duplicate key: {key}")
                result[key] = item
            return result

        text = raw.decode("utf-8")
        if capture_integer_sources:
            value = json.loads(
                text,
                object_pairs_hook=reject_duplicate_keys,
                parse_int=_SourceInteger,
            )
        else:
            value = json.loads(
                text,
                object_pairs_hook=reject_duplicate_keys,
            )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _error(
            corrupt_code,
            f"The Realtor Beta pending {subject} state is unreadable.",
            exc,
        )
    if not isinstance(value, dict):
        raise _error(
            corrupt_code,
            f"The Realtor Beta pending {subject} state has an unknown format.",
        )
    return value


def _parse_marker(raw: bytes) -> PendingRefresh:
    value = _decode_marker_object(
        raw,
        corrupt_code="beta_refresh_state_corrupt",
        subject="refresh",
    )
    if not isinstance(value, dict) or frozenset(value) != SCHEMA_KEYS:
        raise _error(
            "beta_refresh_state_corrupt",
            "The Realtor Beta pending refresh state has an unknown format.",
        )
    if (
        value.get("schema") != 1
        or value.get("operation") != "refresh"
        or not isinstance(value.get("license_id"), str)
        or not value["license_id"]
        or not isinstance(value.get("created_at"), int)
        or isinstance(value.get("created_at"), bool)
        or value["created_at"] < 0
        or value["created_at"] > 2**53 - 1
        or not canonical_token32(value.get("current_refresh_token"))
        or not canonical_token32(value.get("successor_refresh_token"))
        or not canonical_token32(value.get("attempt_id"))
        or value["current_refresh_token"] == value["successor_refresh_token"]
    ):
        raise _error(
            "beta_refresh_state_corrupt",
            "The Realtor Beta pending refresh state failed validation.",
        )
    return PendingRefresh(**value)


def parse_device_pending(raw: bytes) -> PendingDevice:
    """Parse the exact Device v3 marker schema without filesystem access."""
    value = _decode_marker_object(
        raw,
        corrupt_code="beta_device_state_corrupt",
        subject="Device authorization",
        capture_integer_sources=True,
    )
    if frozenset(value) != DEVICE_SCHEMA_KEYS:
        raise _error(
            "beta_device_state_corrupt",
            "The Realtor Beta pending Device authorization state has an unknown format.",
        )
    schema = value.get("schema")
    created_at = value.get("created_at")
    tokens = (
        value.get("device_code"),
        value.get("initial_refresh_token"),
        value.get("recovery_refresh_token"),
        value.get("recovery_attempt_id"),
    )
    if (
        not isinstance(schema, _SourceInteger)
        or schema.source != "1"
        or value.get("operation") != "device"
        or not isinstance(created_at, _SourceInteger)
        or re.fullmatch(r"(?:0|[1-9][0-9]*)", created_at.source) is None
        or created_at > 2**53 - 1
        or not all(canonical_token32(token) for token in tokens)
        or len(set(tokens)) != len(tokens)
    ):
        raise _error(
            "beta_device_state_corrupt",
            "The Realtor Beta pending Device authorization state failed validation.",
        )
    return PendingDevice(
        schema=int(schema),
        operation=value["operation"],
        device_code=value["device_code"],
        initial_refresh_token=value["initial_refresh_token"],
        recovery_refresh_token=value["recovery_refresh_token"],
        recovery_attempt_id=value["recovery_attempt_id"],
        created_at=int(created_at),
    )


def _open_pending(
    dir_fd: int,
) -> tuple[int, os.stat_result, PendingRefresh] | None:
    """Open, authenticate, and parse the marker without releasing its inode."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(MARKER_NAME, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    try:
        opened = _validate_private_file(fd, artifact="marker")
        _verify_named_fd(dir_fd, MARKER_NAME, opened, artifact="marker")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(4096, MAX_MARKER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MARKER_BYTES:
                break
        return fd, opened, _parse_marker(b"".join(chunks))
    except Exception:
        os.close(fd)
        raise


def _open_device_pending(
    dir_fd: int,
) -> tuple[int, os.stat_result, PendingDevice] | None:
    """Open, authenticate, and parse the Device marker without closing it."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(DEVICE_MARKER_NAME, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    try:
        opened = _validate_private_file(
            fd,
            artifact="marker",
            unsafe_code="beta_device_state_unsafe",
            state_label="Device authorization",
        )
        _verify_named_fd(
            dir_fd,
            DEVICE_MARKER_NAME,
            opened,
            artifact="marker",
            unsafe_code="beta_device_state_unsafe",
            state_label="Device authorization",
        )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(4096, MAX_MARKER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MARKER_BYTES:
                break
        return fd, opened, parse_device_pending(b"".join(chunks))
    except Exception:
        os.close(fd)
        raise


def read_pending(root: Path) -> PendingRefresh | None:
    """Read a strictly protected pending marker while the caller holds the lock."""
    dir_fd = _directory_fd(root)
    opened_marker: tuple[int, os.stat_result, PendingRefresh] | None = None
    try:
        opened_marker = _open_pending(dir_fd)
        return None if opened_marker is None else opened_marker[2]
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_refresh_state_unsafe",
            "Realtor Beta could not safely read its pending refresh state.",
            exc,
        )
    finally:
        if opened_marker is not None:
            os.close(opened_marker[0])
        os.close(dir_fd)


def read_device_pending(root: Path) -> PendingDevice | None:
    """Read the protected Device v3 marker while the caller holds the lock."""
    dir_fd = _directory_fd(root)
    opened_marker: tuple[int, os.stat_result, PendingDevice] | None = None
    try:
        opened_marker = _open_device_pending(dir_fd)
        return None if opened_marker is None else opened_marker[2]
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_device_state_unsafe",
            "Realtor Beta could not safely read its pending Device authorization state.",
            exc,
        )
    finally:
        if opened_marker is not None:
            os.close(opened_marker[0])
        os.close(dir_fd)


def create_pending(
    root: Path,
    *,
    license_id: str,
    current_refresh_token: str,
    created_at: int | None = None,
) -> PendingRefresh:
    """Atomically create and durably publish one new A/B/I marker."""
    if (
        not isinstance(license_id, str)
        or not license_id
        or not canonical_token32(current_refresh_token)
    ):
        raise _error(
            "beta_refresh_token_invalid",
            "The Realtor Beta refresh token is not a canonical 256-bit token.",
        )
    if created_at is not None and (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or created_at < 0
        or created_at > 2**53 - 1
    ):
        raise _error(
            "beta_refresh_state_corrupt",
            "The Realtor Beta pending refresh timestamp is invalid.",
        )
    successor = generate_token32()
    while successor == current_refresh_token:
        successor = generate_token32()
    pending = PendingRefresh(
        schema=1,
        operation="refresh",
        license_id=license_id,
        current_refresh_token=current_refresh_token,
        successor_refresh_token=successor,
        attempt_id=generate_token32(),
        created_at=int(time.time()) if created_at is None else created_at,
    )
    payload = pending.to_bytes()
    dir_fd = _directory_fd(root)
    tmp_name = f".license-refresh-pending-{uuid.uuid4().hex}.tmp"
    try:
        if read_pending(root) is not None or read_device_pending(root) is not None:
            raise _error(
                "beta_refresh_state_conflict",
                "A Realtor Beta refresh attempt already exists.",
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("pending refresh write made no progress")
                offset += written
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_name, MARKER_NAME, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
        persisted = read_pending(root)
        if persisted != pending:
            raise _error(
                "beta_refresh_persistence_failed",
                "Realtor Beta could not verify its pending refresh state.",
            )
        return persisted
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_refresh_persistence_failed",
            "Realtor Beta could not durably save its pending refresh state.",
            exc,
        )
    finally:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        os.close(dir_fd)


def remove_pending(root: Path) -> None:
    """Remove and fsync a valid marker; unsafe markers are never unlinked."""
    dir_fd = _directory_fd(root)
    opened_marker: tuple[int, os.stat_result, PendingRefresh] | None = None
    try:
        opened_marker = _open_pending(dir_fd)
        if opened_marker is None:
            return
        # Keep the authenticated inode open and revalidate the named path at
        # the deletion boundary. A swapped symlink or different inode is
        # retained and reported instead of being unlinked on trust.
        _verify_named_fd(
            dir_fd,
            MARKER_NAME,
            opened_marker[1],
            artifact="marker",
        )
        os.unlink(MARKER_NAME, dir_fd=dir_fd)
        try:
            os.stat(MARKER_NAME, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OSError("pending refresh removal could not be verified")
        os.fsync(dir_fd)
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_refresh_persistence_failed",
            "Realtor Beta could not durably clear its pending refresh state.",
            exc,
        )
    finally:
        if opened_marker is not None:
            os.close(opened_marker[0])
        os.close(dir_fd)


def write_device_pending(
    root: Path,
    *,
    device_code: str,
    initial_refresh_token: str,
    recovery_refresh_token: str,
    recovery_attempt_id: str,
    created_at: int | None = None,
) -> PendingDevice:
    """Atomically publish one exact D/B/C/I Device v3 marker.

    The caller must hold :func:`refresh_lock`.  Existing refresh or Device
    state is retained and reported as a conflict; this function never replaces
    an in-flight credential transition.
    """
    pending = PendingDevice(
        schema=1,
        operation="device",
        device_code=device_code,
        initial_refresh_token=initial_refresh_token,
        recovery_refresh_token=recovery_refresh_token,
        recovery_attempt_id=recovery_attempt_id,
        created_at=int(time.time()) if created_at is None else created_at,
    )
    # Parse our own wire representation so write-time validation is exactly the
    # same as recovery-time validation in both clients.
    pending = parse_device_pending(pending.to_bytes())
    payload = pending.to_bytes()
    dir_fd = _directory_fd(root)
    tmp_name = f".license-device-pending-{uuid.uuid4().hex}.tmp"
    try:
        if read_device_pending(root) is not None or read_pending(root) is not None:
            raise _error(
                "beta_device_state_conflict",
                "A Realtor Beta credential transition already exists.",
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("pending Device write made no progress")
                offset += written
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_name, DEVICE_MARKER_NAME, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
        persisted = read_device_pending(root)
        if persisted != pending:
            raise _error(
                "beta_device_persistence_failed",
                "Realtor Beta could not verify its pending Device authorization state.",
            )
        return persisted
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_device_persistence_failed",
            "Realtor Beta could not durably save its pending Device authorization state.",
            exc,
        )
    finally:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        os.close(dir_fd)


def remove_device_pending(root: Path, expected: PendingDevice) -> bool:
    """CAS-remove the exact Device marker, retaining mismatches and unsafe paths."""
    if not isinstance(expected, PendingDevice):
        raise _error(
            "beta_device_state_corrupt",
            "The Realtor Beta expected Device authorization state is invalid.",
        )
    expected = parse_device_pending(expected.to_bytes())
    dir_fd = _directory_fd(root)
    opened_marker: tuple[int, os.stat_result, PendingDevice] | None = None
    try:
        opened_marker = _open_device_pending(dir_fd)
        if opened_marker is None or opened_marker[2] != expected:
            return False
        _verify_named_fd(
            dir_fd,
            DEVICE_MARKER_NAME,
            opened_marker[1],
            artifact="marker",
            unsafe_code="beta_device_state_unsafe",
            state_label="Device authorization",
        )
        os.unlink(DEVICE_MARKER_NAME, dir_fd=dir_fd)
        try:
            os.stat(DEVICE_MARKER_NAME, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OSError("pending Device removal could not be verified")
        os.fsync(dir_fd)
        return True
    except RefreshPendingError:
        raise
    except Exception as exc:
        raise _error(
            "beta_device_persistence_failed",
            "Realtor Beta could not durably clear its pending Device authorization state.",
            exc,
        )
    finally:
        if opened_marker is not None:
            os.close(opened_marker[0])
        os.close(dir_fd)
