#!/usr/bin/env python3
"""Effect-declaration and hidden-effect tests for the file read/search tools.

``read_file`` and ``search_files`` declare an exact ``read:files``. The read is
performed over the SAME shared local-execution substrate as the already-declared
``terminal`` READ lane (``_get_file_ops`` -> ``_create_environment`` -> the
identical ``_active_environments`` machinery). That substrate — env provisioning
(which idempotently ensures ELEVATE_HOME exactly as ``terminal``'s ``ls``/``cat``
reads do) plus foreground read-only subprocesses — is accepted for a READ
declaration by the terminal precedent, so it is NOT a per-tool effect. These
tests therefore pin the two things that ARE ``read_file``-specific:

1. ``read_file`` no longer actively materializes iCloud placeholders. The old
   path called ``materialize_if_dataless`` (a ``brctl download`` subprocess + an
   active iCloud residency change) which is unclassifiable from args. The
   repaired path calls ``require_resident`` — a pure ``stat`` — and refuses a
   dataless placeholder with a typed ``file_not_resident`` error.
   Materialization stays an explicit, UNKNOWN-effect opt-in helper used by
   effect-bearing tools. ``search_files`` never had an active materializer.
2. ``read_file``'s size guard (``_get_max_read_chars``) reads config via the
   bootstrap-free ``read_raw_config`` instead of ``load_config`` — a scoped
   hardening that stops THAT single-value lookup from mkdir-seeding the profile
   tree. The other config reads on the path (pagination limits via
   ``get_tool_output_limits``, terminal-env session init) still go through
   ``load_config`` exactly as ``terminal``'s declared ``ls``/``cat`` reads do,
   so the end-to-end read is NOT asserted bootstrap-free — that is the shared
   terminal-parity substrate, not a read_file-specific effect.

``write_file`` and ``patch`` mutate the filesystem and stay UNKNOWN (undeclared
→ fail closed).

Run with:  python -m pytest tests/tools/test_file_tools_effects.py -q
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

from tools import file_materialize as fm
from tools import file_tools
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.file_tools import read_file_tool, _read_tracker
from tools.registry import registry

READ_FILES = frozenset({Effect.parse("read:files")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})

READ_TOOLS = ["read_file", "search_files"]
WRITE_TOOLS = ["write_file", "patch"]


def _read_only():
    return ExecutionPolicy.for_mode("turn-file-tools-read", ExecutionPolicyMode.READ_ONLY)


@pytest.fixture(autouse=True)
def _clean_tracker():
    _read_tracker.clear()
    file_tools._max_read_chars_cached = None
    yield
    _read_tracker.clear()
    file_tools._max_read_chars_cached = None


class _FakeReadResult:
    def __init__(self, content="alpha\nbravo\n", total_lines=2, file_size=12):
        self.content = content
        self._total_lines = total_lines
        self._file_size = file_size

    def to_dict(self):
        return {
            "content": self.content,
            "total_lines": self._total_lines,
            "file_size": self._file_size,
        }


def _fake_ops(content="alpha\nbravo\n"):
    fake = MagicMock()
    fake.read_file = lambda path, offset=1, limit=500: _FakeReadResult(content=content)
    return fake


# ── declaration / resolution ──────────────────────────────────────────────


@pytest.mark.parametrize("name", READ_TOOLS)
def test_read_tools_declare_read_files(name):
    entry = registry.get_entry(name)
    assert entry is not None
    meta = registry.get_effect_metadata(name)
    assert meta["declared"] is True
    # Static declaration — no per-arg resolver needed (every branch is a read).
    assert meta["has_resolver"] is False
    assert registry.resolve_effects(name, {"path": "x", "pattern": "y"}) == READ_FILES


@pytest.mark.parametrize("name", READ_TOOLS)
def test_read_tools_allowed_under_read_only(name):
    resolved = registry.resolve_effects(name, {"path": "x", "pattern": "y"})
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_write_tools_stay_unknown_and_denied(name):
    meta = registry.get_effect_metadata(name)
    assert meta["declared"] is False
    resolved = registry.resolve_effects(name, {"path": "x"})
    assert resolved == UNKNOWN
    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


# ── materialize repair: read_file refuses dataless without downloading ─────


def test_read_file_refuses_dataless_without_subprocess(monkeypatch, tmp_path):
    """A dataless placeholder yields a typed file_not_resident error and the
    read never shells out to brctl or reaches the file-ops read."""
    target = tmp_path / "offloaded.txt"
    target.write_text("cloud only\n")

    # Force the residency check to see a placeholder.
    monkeypatch.setattr(fm, "is_dataless", lambda p: True)

    # brctl must never run on the declared-read path.
    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("read_file materialized via a subprocess")

    monkeypatch.setattr(fm.subprocess, "run", _boom)

    # The read must never reach file-ops either.
    def _no_ops(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("read_file reached file-ops on a dataless file")

    monkeypatch.setattr(file_tools, "_get_file_ops", _no_ops)

    result = json.loads(read_file_tool(str(target), task_id="dataless"))
    assert result.get("error_code") == "file_not_resident"
    assert "iCloud" in result["error"]


def test_read_file_resident_read_never_materializes(monkeypatch, tmp_path):
    """A resident file is read purely — no brctl subprocess is invoked."""
    target = tmp_path / "resident.txt"
    target.write_text("alpha\nbravo\n")

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("resident read shelled out to brctl")

    monkeypatch.setattr(fm.subprocess, "run", _boom)
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda *a, **k: _fake_ops())

    result = json.loads(read_file_tool(str(target), task_id="resident"))
    assert "error" not in result
    assert result.get("content") == "alpha\nbravo\n"


def test_search_never_actively_materializes(monkeypatch, tmp_path):
    """search_files performs no ACTIVE residency change.

    Unlike the old read_file, search never called ``materialize_if_dataless``.
    It has no brctl subprocess of its own — any iCloud fault-in is the passive
    OS behaviour of reading bytes, identical to ``terminal``'s ``grep``/``cat``
    declared reads. This pins that no active materializer creeps into search.
    """
    from tools.file_tools import search_tool

    fake = MagicMock()
    fake.search = lambda **kw: MagicMock(to_dict=lambda: {"matches": [], "truncated": False})
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda *a, **k: fake)

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("search_files shelled out to brctl (active materialize)")

    monkeypatch.setattr(fm.subprocess, "run", _boom)

    result = json.loads(search_tool(pattern="alpha", path=str(tmp_path), task_id="search"))
    assert "error" not in result


# ── live pure read through the real LocalEnvironment ───────────────────────


def test_live_read_returns_bytes_and_mutates_nothing(monkeypatch, tmp_path):
    """Drive read_file over a REAL local read of a REAL resident file and prove
    it returns the bytes while leaving the directory unchanged and never
    triggering materialization."""
    from tools.environments.local import LocalEnvironment
    from tools.file_operations import ShellFileOperations

    target = tmp_path / "live.txt"
    target.write_text("alpha\nbravo\ncharlie\n")

    before = sorted(os.listdir(tmp_path))

    real_ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path), timeout=15))
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda *a, **k: real_ops)

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("live read materialized via a subprocess")

    monkeypatch.setattr(fm.subprocess, "run", _boom)

    result = json.loads(read_file_tool(str(target), task_id="live"))
    assert "error" not in result
    assert "alpha" in result["content"]
    assert "charlie" in result["content"]

    # No temp/marker files created by the read.
    assert sorted(os.listdir(tmp_path)) == before


# ── cold-home declaration-rot guard (house pattern) ────────────────────────


def test_size_guard_uses_bootstrap_free_reader(monkeypatch, tmp_path):
    """_get_max_read_chars must read config without ensure_elevate_home().

    A direct guard against reintroducing load_config(): we point ELEVATE_HOME at
    a cold dir, invoke the size-guard reader, and assert the home tree is never
    created while a user override is still honoured.
    """
    cold_home = tmp_path / "cold-home"
    monkeypatch.setenv("ELEVATE_HOME", str(cold_home))
    file_tools._max_read_chars_cached = None

    # No config file at all -> falls back to the built-in default, no mkdir.
    assert file_tools._get_max_read_chars() == file_tools._DEFAULT_MAX_READ_CHARS
    assert not cold_home.exists()

    # A user override in a real (but hand-created) config file is still read,
    # and reading it must not seed the rest of the profile tree.
    file_tools._max_read_chars_cached = None
    cold_home.mkdir(parents=True)
    (cold_home / "config.yaml").write_text("file_read_max_chars: 4242\n")
    seeded_before = sorted(os.listdir(cold_home))
    assert file_tools._get_max_read_chars() == 4242
    # Reading the value did not seed additional profile files/dirs.
    assert sorted(os.listdir(cold_home)) == seeded_before


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
