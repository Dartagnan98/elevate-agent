"""Fail-closed identity for the code-bundled Realtor Beta skill corpus.

The exact lowercase ``beta`` channel must not derive its runtime skills from a
profile, cloud sync, or an environment override.  This module resolves the
skills tree beside the shipped CLI code, validates the complete Realtor skill
corpus granted by HQ plus the Realtor runtime surfaces, and binds it to the
province-routing code with a deterministic SHA-256 identity.

The loader intentionally has no auth or license dependencies.  Callers can
bind the returned identity into their own signed/durable activation state.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from elevate_constants import exact_realtor_beta_active


_HASH_DOMAIN: Final[bytes] = b"elevate-realtor-beta-skill-bundle-v2\x00"

# Mirrors backend/src/lib/skill-seeds.ts defaultSeedRoots(), plus the bundled
# real-estate runtime subtree used by the signed Beta agents and heartbeats.
# Keep these explicit: silently discovering every directory would let an
# unrelated bundled developer skill change the Realtor activation identity,
# while omitting one of these roots would leave an entitled Realtor surface
# outside the receipt's proof.
REALTOR_BETA_SKILL_ROOTS: Final[tuple[str, ...]] = (
    "real-estate",
    "real-estate-admin",
    "lead-scorer",
    "outreach-lanes",
    "social-content-engine",
    "cma",
)

REQUIRED_CRITICAL_FILES: Final[tuple[str, ...]] = (
    "real-estate-admin/ROUTING.md",
    "real-estate-admin/admin-agent/SKILL.md",
    "real-estate-admin/webforms/SKILL.md",
    "real-estate-admin/digisign/SKILL.md",
    "real-estate-admin/signing-package/SKILL.md",
    "real-estate-admin/buyer-cps/SKILL.md",
    "real-estate-admin/mlc/SKILL.md",
    "real-estate-admin/offer-review/SKILL.md",
    "real-estate-admin/subject-removal/SKILL.md",
    "real-estate/surface-heartbeat/SKILL.md",
    "lead-scorer/SKILL.md",
    "outreach-lanes/SKILL.md",
    "social-content-engine/SKILL.md",
    "cma/SKILL.md",
)

# These files select the jurisdiction package, import/serve the matching guide,
# and keep searchable guide memory isolated to the selected province.
DEFAULT_PROVINCE_CODE_PATHS: Final[tuple[str, ...]] = (
    "elevate_cli/admin_deal_flow.py",
    "elevate_cli/data/province_guides.py",
    "elevate_cli/data/province_guide_memory.py",
)

DEFAULT_MAX_FILE_BYTES: Final[int] = 1 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES: Final[int] = 16 * 1024 * 1024


class BetaSkillBundleError(RuntimeError):
    """The exact-Beta bundled corpus could not be trusted."""


@dataclass(frozen=True, slots=True)
class BetaSkillBundle:
    """Immutable result of validating the exact-Beta runtime skill bundle."""

    skills_root: Path
    sha256: str
    file_count: int
    total_bytes: int
    files: tuple[str, ...]

    @property
    def identity_hash(self) -> str:
        """Explicit alias for consumers that store a generic identity field."""
        return self.sha256


@dataclass(frozen=True, slots=True)
class _BundleFile:
    label: str
    content: bytes


def _absolute_without_resolving(path: Path | str) -> Path:
    # resolve() would hide a symlink at the injected or packaged root.
    return Path(os.path.abspath(os.fspath(path)))


def _require_plain_directory(path: Path, *, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise BetaSkillBundleError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise BetaSkillBundleError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise BetaSkillBundleError(f"{label} must be a directory")


def _relative_path(value: Path | str, *, label: str) -> PurePosixPath:
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        raise BetaSkillBundleError(f"{label} must be a non-empty relative path")
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise BetaSkillBundleError(f"{label} must stay within the code bundle")
    return candidate


def _require_plain_parent_chain(
    root: Path, relative: PurePosixPath, *, label: str
) -> None:
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        _require_plain_directory(current, label=f"{label} parent")


def _read_plain_file(path: Path, *, label: str, max_file_bytes: int) -> bytes:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise BetaSkillBundleError(
            f"required bundle file is unavailable: {label}"
        ) from exc
    if stat.S_ISLNK(before.st_mode):
        raise BetaSkillBundleError(f"bundle file must not be a symlink: {label}")
    if not stat.S_ISREG(before.st_mode):
        raise BetaSkillBundleError(f"bundle entry must be a regular file: {label}")
    if before.st_size <= 0:
        raise BetaSkillBundleError(f"bundle file must not be empty: {label}")
    if before.st_size > max_file_bytes:
        raise BetaSkillBundleError(f"bundle file exceeds the size cap: {label}")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BetaSkillBundleError(
            f"bundle file could not be opened safely: {label}"
        ) from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise BetaSkillBundleError(f"bundle entry must be a regular file: {label}")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise BetaSkillBundleError(f"bundle file changed while opening: {label}")
        if opened.st_size != before.st_size:
            raise BetaSkillBundleError(f"bundle file changed while opening: {label}")

        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise BetaSkillBundleError(
                    f"bundle file changed while reading: {label}"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise BetaSkillBundleError(f"bundle file changed while reading: {label}")

        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise BetaSkillBundleError(f"bundle file changed while reading: {label}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _walk_corpus(
    root: Path, relative_root: str, *, max_file_bytes: int
) -> list[_BundleFile]:
    corpus_root = root / relative_root
    _require_plain_directory(corpus_root, label=f"skill corpus {relative_root}")
    pending: list[tuple[Path, PurePosixPath]] = [
        (corpus_root, PurePosixPath(relative_root))
    ]
    files: list[_BundleFile] = []

    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda item: item.name)
        except OSError as exc:
            raise BetaSkillBundleError(
                f"skill corpus could not be enumerated: {relative_directory.as_posix()}"
            ) from exc

        for entry in entries:
            relative = relative_directory / entry.name
            label = f"skills/{relative.as_posix()}"
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise BetaSkillBundleError(
                    f"bundle entry is unavailable: {label}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise BetaSkillBundleError(
                    f"bundle entry must not be a symlink: {label}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                pending.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise BetaSkillBundleError(
                    f"bundle entry must be a regular file: {label}"
                )
            files.append(
                _BundleFile(
                    label=label,
                    content=_read_plain_file(
                        Path(entry.path),
                        label=label,
                        max_file_bytes=max_file_bytes,
                    ),
                )
            )
    return files


def _validate_limit(value: int, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BetaSkillBundleError(f"{label} must be a positive integer")
    return value


def _hash_files(files: Sequence[_BundleFile]) -> str:
    digest = hashlib.sha256(_HASH_DOMAIN)
    for item in files:
        encoded_label = item.label.encode("utf-8")
        digest.update(len(encoded_label).to_bytes(4, "big"))
        digest.update(encoded_label)
        digest.update(len(item.content).to_bytes(8, "big"))
        digest.update(item.content)
    return digest.hexdigest()


def load_exact_beta_skill_bundle(
    *,
    environ: Mapping[str, str] | None = None,
    code_root: Path | str | None = None,
    province_code_paths: Sequence[Path | str] = DEFAULT_PROVINCE_CODE_PATHS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> BetaSkillBundle:
    """Validate and identify the code-bundled Realtor/Admin runtime corpus.

    ``ELEVATE_RELEASE_CHANNEL`` must be exactly ``"beta"``.  In production the
    skills root is always ``<shipped cli code>/skills``; mutable skill-root
    environment overrides are deliberately ignored.  ``code_root`` and the
    relative ``province_code_paths`` are injectable only so tests and release
    tooling can validate an isolated candidate tree.
    """
    active_environ = os.environ if environ is None else environ
    if not exact_realtor_beta_active(dict(active_environ)):
        raise BetaSkillBundleError(
            "bundled skill identity is restricted to exact Realtor Beta"
        )

    max_file_bytes = _validate_limit(max_file_bytes, label="max_file_bytes")
    max_total_bytes = _validate_limit(max_total_bytes, label="max_total_bytes")
    if isinstance(province_code_paths, (str, bytes, os.PathLike)):
        raise BetaSkillBundleError("province_code_paths must be a sequence of paths")
    if not province_code_paths:
        raise BetaSkillBundleError("province_code_paths must not be empty")

    default_code_root = Path(__file__).parent.parent
    selected_code_root = _absolute_without_resolving(code_root or default_code_root)
    skills_root = selected_code_root / "skills"
    _require_plain_directory(selected_code_root, label="Beta code root")
    _require_plain_directory(skills_root, label="code-bundled skills root")

    bundle_files: list[_BundleFile] = []
    for relative_root in REALTOR_BETA_SKILL_ROOTS:
        bundle_files.extend(
            _walk_corpus(
                skills_root,
                relative_root,
                max_file_bytes=max_file_bytes,
            )
        )

    corpus_labels = {item.label.removeprefix("skills/") for item in bundle_files}
    missing = sorted(set(REQUIRED_CRITICAL_FILES) - corpus_labels)
    if missing:
        raise BetaSkillBundleError(
            "required critical skill files are missing: " + ", ".join(missing)
        )

    for index, value in enumerate(province_code_paths):
        relative = _relative_path(value, label=f"province_code_paths[{index}]")
        _require_plain_parent_chain(
            selected_code_root,
            relative,
            label=f"province routing code {relative.as_posix()}",
        )
        code_label = f"code/{relative.as_posix()}"
        bundle_files.append(
            _BundleFile(
                label=code_label,
                content=_read_plain_file(
                    selected_code_root.joinpath(*relative.parts),
                    label=code_label,
                    max_file_bytes=max_file_bytes,
                ),
            )
        )

    bundle_files.sort(key=lambda item: item.label)
    labels = tuple(item.label for item in bundle_files)
    if len(labels) != len(set(labels)):
        raise BetaSkillBundleError("bundle contains duplicate logical file paths")
    total_bytes = sum(len(item.content) for item in bundle_files)
    if total_bytes > max_total_bytes:
        raise BetaSkillBundleError("Beta skill bundle exceeds the total size cap")

    return BetaSkillBundle(
        skills_root=skills_root,
        sha256=_hash_files(bundle_files),
        file_count=len(bundle_files),
        total_bytes=total_bytes,
        files=labels,
    )


__all__ = [
    "BetaSkillBundle",
    "BetaSkillBundleError",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_PROVINCE_CODE_PATHS",
    "REALTOR_BETA_SKILL_ROOTS",
    "REQUIRED_CRITICAL_FILES",
    "load_exact_beta_skill_bundle",
]
