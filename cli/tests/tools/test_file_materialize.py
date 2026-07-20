"""Tests for the iCloud dataless-file materialization guard."""
import errno
import os
import tempfile

import pytest

from tools import file_materialize as fm


@pytest.fixture()
def tmp_file():
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    f.write(b"hello world")
    f.close()
    yield f.name
    try:
        os.unlink(f.name)
    except OSError:
        pass


def test_is_dataless_false_for_normal_file(tmp_file):
    assert fm.is_dataless(tmp_file) is False


def test_is_dataless_false_for_missing_file():
    assert fm.is_dataless("/no/such/path/xyz.bin") is False


def test_materialize_noop_on_resident_file(tmp_file):
    # Already-resident files short-circuit to True without shelling out.
    assert fm.materialize_if_dataless(tmp_file) is True


def test_read_bytes_resilient_reads_normal_file(tmp_file):
    assert fm.read_bytes_resilient(tmp_file) == b"hello world"


def test_dataless_detection_uses_sf_dataless_bit(monkeypatch, tmp_file):
    """is_dataless must key off the SF_DATALESS (0x40000000) st_flags bit."""
    monkeypatch.setattr(fm, "_IS_MACOS", True)

    real_stat = os.stat(tmp_file)

    class _Flagged:
        st_flags = real_stat.st_flags | fm.SF_DATALESS

    monkeypatch.setattr(fm.os, "stat", lambda *a, **k: _Flagged())
    assert fm.is_dataless(tmp_file) is True


def test_materialize_raises_when_stays_dataless(monkeypatch, tmp_file):
    """If the file never materializes, we raise FileNotReadyError (errno EDEADLK)."""
    monkeypatch.setattr(fm, "_IS_MACOS", True)
    monkeypatch.setattr(fm, "is_dataless", lambda p: True)  # never clears
    # Skip the brctl subprocess and the real wait.
    monkeypatch.setattr(fm.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(fm.time, "monotonic", _fake_clock())
    monkeypatch.setattr(fm.time, "sleep", lambda s: None)

    with pytest.raises(fm.FileNotReadyError) as ei:
        fm.materialize_if_dataless(tmp_file, timeout=1.0, poll=0.1)
    assert ei.value.errno == errno.EDEADLK


def _fake_clock():
    """Monotonic clock that advances 0.5s per call so timeout loops terminate."""
    state = {"t": 0.0}

    def _clock():
        state["t"] += 0.5
        return state["t"]

    return _clock


# ── require_resident: the pure (non-materializing) declared-read guard ─────


def test_require_resident_noop_on_resident_file(tmp_file):
    """A resident file passes the guard and returns None."""
    assert fm.require_resident(tmp_file) is None


def test_require_resident_noop_on_missing_file():
    """A missing file is not dataless, so the guard is a no-op."""
    assert fm.require_resident("/no/such/path/xyz.bin") is None


def test_require_resident_refuses_dataless_without_subprocess(monkeypatch, tmp_file):
    """A dataless placeholder is refused WITHOUT any brctl download.

    This is the core repair: the declared-read lane must never run the
    materialization subprocess or change iCloud residency. If it did, the
    read effect would be unclassifiable from args and read_file could not
    truthfully declare read:files.
    """
    monkeypatch.setattr(fm, "is_dataless", lambda p: True)

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("require_resident shelled out to a subprocess")

    monkeypatch.setattr(fm.subprocess, "run", _boom)

    with pytest.raises(fm.FileNotResidentError):
        fm.require_resident(tmp_file)


def test_file_not_resident_is_distinct_from_not_ready():
    """The two typed errors are distinct classes (both OSError)."""
    assert fm.FileNotResidentError is not fm.FileNotReadyError
    assert issubclass(fm.FileNotResidentError, OSError)
    assert issubclass(fm.FileNotReadyError, OSError)
