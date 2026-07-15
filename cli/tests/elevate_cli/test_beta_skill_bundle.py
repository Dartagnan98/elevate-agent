from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

import pytest

from elevate_cli.beta_skill_bundle import (
    DEFAULT_PROVINCE_CODE_PATHS,
    REALTOR_BETA_SKILL_ROOTS,
    REQUIRED_CRITICAL_FILES,
    BetaSkillBundleError,
    load_exact_beta_skill_bundle,
)


def _write(path: Path, content: bytes = b"signed bundle content\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _candidate_tree(tmp_path: Path) -> Path:
    code_root = tmp_path / "candidate-cli"
    for relative in REQUIRED_CRITICAL_FILES:
        _write(code_root / "skills" / relative, f"{relative}\n".encode())
    _write(
        code_root / "skills" / "real-estate-admin" / "buyer-cps" / "lessons.md",
        b"lessons are part of the runtime corpus\n",
    )
    _write(
        code_root
        / "skills"
        / "real-estate-admin"
        / "outreach"
        / "references"
        / "voice-and-drafting.md",
        b"nested references are part of the runtime corpus\n",
    )
    _write(
        code_root / "skills" / "real-estate" / "theta-wave" / "SKILL.md",
        b"realtor runtime agent skill\n",
    )
    _write(
        code_root / "skills" / "social-content-engine" / "scripts" / "aggregate.py",
        b"# marketing runtime helper\n",
    )
    for relative in DEFAULT_PROVINCE_CODE_PATHS:
        _write(code_root / relative, f"# {relative}\n".encode())
    return code_root


def _load(code_root: Path, **kwargs):
    return load_exact_beta_skill_bundle(
        environ={
            "ELEVATE_RELEASE_CHANNEL": "beta",
            "ELEVATE_BUNDLED_SKILLS": "/tmp/untrusted-override",
        },
        code_root=code_root,
        **kwargs,
    )


def test_identity_covers_complete_corpus_and_province_code_and_is_immutable(
    tmp_path: Path,
) -> None:
    code_root = _candidate_tree(tmp_path)

    bundle = _load(code_root)

    assert REALTOR_BETA_SKILL_ROOTS == (
        "real-estate",
        "real-estate-admin",
        "lead-scorer",
        "outreach-lanes",
        "social-content-engine",
        "cma",
    )
    assert bundle.skills_root == code_root / "skills"
    assert bundle.file_count == len(REQUIRED_CRITICAL_FILES) + 4 + len(
        DEFAULT_PROVINCE_CODE_PATHS
    )
    assert bundle.files == tuple(sorted(bundle.files))
    assert "skills/real-estate-admin/buyer-cps/lessons.md" in bundle.files
    assert (
        "skills/real-estate-admin/outreach/references/voice-and-drafting.md"
        in bundle.files
    )
    assert "skills/real-estate/theta-wave/SKILL.md" in bundle.files
    assert "skills/social-content-engine/scripts/aggregate.py" in bundle.files
    assert all(f"code/{path}" in bundle.files for path in DEFAULT_PROVINCE_CODE_PATHS)
    assert re.fullmatch(r"[0-9a-f]{64}", bundle.sha256)
    assert bundle.identity_hash == bundle.sha256
    assert bundle.total_bytes > 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.file_count = 0  # type: ignore[misc]


def test_identity_is_path_independent_and_changes_with_included_content(
    tmp_path: Path,
) -> None:
    first_root = _candidate_tree(tmp_path / "first")
    second_root = _candidate_tree(tmp_path / "second")
    first = _load(first_root)
    second = _load(second_root)
    assert first.sha256 == second.sha256

    _write(
        second_root / "skills" / "real-estate-admin" / "buyer-cps" / "lessons.md",
        b"changed lessons\n",
    )
    changed = _load(second_root)
    assert changed.sha256 != first.sha256
    assert changed.file_count == first.file_count


@pytest.mark.parametrize("root", REALTOR_BETA_SKILL_ROOTS)
def test_every_authoritative_realtor_root_is_required(
    root: str,
    tmp_path: Path,
) -> None:
    code_root = _candidate_tree(tmp_path)
    corpus_root = code_root / "skills" / root
    for path in sorted(corpus_root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    corpus_root.rmdir()

    with pytest.raises(BetaSkillBundleError, match=f"skill corpus {re.escape(root)}"):
        _load(code_root)


@pytest.mark.parametrize("channel", [None, "", "Beta", "stable", "beta "])
def test_only_exact_lowercase_beta_can_load(
    channel: str | None, tmp_path: Path
) -> None:
    code_root = _candidate_tree(tmp_path)
    environ = {} if channel is None else {"ELEVATE_RELEASE_CHANNEL": channel}

    with pytest.raises(BetaSkillBundleError, match="restricted to exact Realtor Beta"):
        load_exact_beta_skill_bundle(environ=environ, code_root=code_root)


def test_missing_critical_file_fails_closed(tmp_path: Path) -> None:
    code_root = _candidate_tree(tmp_path)
    missing = code_root / "skills" / "real-estate-admin" / "mlc" / "SKILL.md"
    missing.unlink()

    with pytest.raises(BetaSkillBundleError, match="required critical.*mlc/SKILL.md"):
        _load(code_root)


@pytest.mark.parametrize(
    "relative",
    [
        "skills/real-estate-admin/admin-agent/SKILL.md",
        "elevate_cli/admin_deal_flow.py",
    ],
)
def test_empty_skill_or_province_code_file_fails_closed(
    relative: str,
    tmp_path: Path,
) -> None:
    code_root = _candidate_tree(tmp_path)
    (code_root / relative).write_bytes(b"")

    with pytest.raises(BetaSkillBundleError, match="must not be empty"):
        _load(code_root)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_symlinks_anywhere_in_skill_corpus_fail_closed(
    kind: str, tmp_path: Path
) -> None:
    code_root = _candidate_tree(tmp_path)
    outside = tmp_path / "outside"
    if kind == "file":
        _write(outside, b"outside instructions\n")
        (code_root / "skills" / "real-estate-admin" / "linked.md").symlink_to(outside)
    else:
        _write(outside / "SKILL.md", b"outside instructions\n")
        (code_root / "skills" / "real-estate-admin" / "linked").symlink_to(
            outside,
            target_is_directory=True,
        )

    with pytest.raises(BetaSkillBundleError, match="must not be a symlink"):
        _load(code_root)


def test_symlinked_province_code_parent_fails_closed(tmp_path: Path) -> None:
    code_root = _candidate_tree(tmp_path)
    outside = tmp_path / "outside-code"
    _write(outside / "route.py", b"outside routing\n")
    (code_root / "linked-code").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BetaSkillBundleError, match="parent must not be a symlink"):
        _load(code_root, province_code_paths=("linked-code/route.py",))


def test_nonregular_corpus_entry_fails_closed(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    code_root = _candidate_tree(tmp_path)
    os.mkfifo(code_root / "skills" / "real-estate-admin" / "not-a-file")

    with pytest.raises(BetaSkillBundleError, match="must be a regular file"):
        _load(code_root)


def test_individual_and_total_size_caps_fail_closed(tmp_path: Path) -> None:
    code_root = _candidate_tree(tmp_path)
    largest = max(
        path.stat().st_size
        for path in (code_root / "skills" / "real-estate-admin").rglob("*")
        if path.is_file()
    )
    with pytest.raises(BetaSkillBundleError, match="exceeds the size cap"):
        _load(code_root, max_file_bytes=largest - 1)

    valid = _load(code_root)
    with pytest.raises(BetaSkillBundleError, match="exceeds the total size cap"):
        _load(code_root, max_total_bytes=valid.total_bytes - 1)


@pytest.mark.parametrize("bad_path", ["../outside.py", "/absolute/route.py"])
def test_injected_code_paths_cannot_escape_code_root(
    bad_path: str,
    tmp_path: Path,
) -> None:
    code_root = _candidate_tree(tmp_path)

    with pytest.raises(BetaSkillBundleError, match="must stay within the code bundle"):
        _load(code_root, province_code_paths=(bad_path,))


def test_province_code_identity_cannot_be_omitted(tmp_path: Path) -> None:
    code_root = _candidate_tree(tmp_path)

    with pytest.raises(BetaSkillBundleError, match="must not be empty"):
        _load(code_root, province_code_paths=())


def test_real_candidate_tree_passes_with_every_required_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_cli = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BUNDLED_SKILLS", "/tmp/untrusted-override")

    bundle = load_exact_beta_skill_bundle(code_root=repo_cli)

    assert bundle.skills_root == repo_cli / "skills"
    assert bundle.file_count >= 100
    assert bundle.total_bytes < 16 * 1024 * 1024
    assert all(
        f"skills/{relative}" in bundle.files for relative in REQUIRED_CRITICAL_FILES
    )
