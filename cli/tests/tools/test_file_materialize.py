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
