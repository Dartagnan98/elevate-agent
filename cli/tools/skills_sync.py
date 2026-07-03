#!/usr/bin/env python3
"""
Skills Sync -- Manifest-based seeding and updating of bundled skills.

Copies bundled skills from the repo's skills/ directory into ~/.elevate/skills/
and uses a manifest to track which skills have been synced and their origin hash.

Manifest format (v2): each line is "skill_name:origin_hash" where origin_hash
is the MD5 of the bundled skill at the time it was last synced to the user dir.
Old v1 manifests (plain names without hashes) are auto-migrated.

Update logic:
  - NEW skills (not in manifest): copied to user dir, origin hash recorded.
  - EXISTING skills (in manifest, present in user dir):
      * If user copy matches origin hash: user hasn't modified it → safe to
        update from bundled if bundled changed. New origin hash recorded.
      * If user copy differs from origin hash: user customized it → SKIP.
  - DELETED by user (in manifest, absent from user dir): respected, not re-added.
  - REMOVED from bundled (in manifest, gone from repo): cleaned from manifest.

The manifest lives at ~/.elevate/skills/.bundled_manifest.
"""

import hashlib
import logging
import os
import shutil
from pathlib import Path
from elevate_constants import get_bundled_skills_dir, get_elevate_home
from agent.skill_utils import is_excluded_skill_path
from typing import Dict, List, Tuple
from utils import atomic_replace

logger = logging.getLogger(__name__)


ELEVATE_HOME = get_elevate_home()
SKILLS_DIR = ELEVATE_HOME / "skills"
MANIFEST_FILE = SKILLS_DIR / ".bundled_manifest"


def _get_bundled_dir() -> Path:
    """Locate the bundled skills/ directory.

    Checks ELEVATE_BUNDLED_SKILLS env var first (set by Nix wrapper),
    then a wheel-installed data dir, then falls back to the relative
    path from this source file.
    """
    return get_bundled_skills_dir(Path(__file__).parent.parent / "skills")


def _read_manifest() -> Dict[str, str]:
    """
    Read the manifest as a dict of {skill_name: origin_hash}.

    Handles both v1 (plain names) and v2 (name:hash) formats.
    v1 entries get an empty hash string which triggers migration on next sync.
    """
    if not MANIFEST_FILE.exists():
        return {}
    try:
        result = {}
        for line in MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                # v2 format: name:hash
                name, _, hash_val = line.partition(":")
                result[name.strip()] = hash_val.strip()
            else:
                # v1 format: plain name — empty hash triggers migration
                result[line] = ""
        return result
    except (OSError, IOError):
        return {}


def _write_manifest(entries: Dict[str, str]):
    """Write the manifest file atomically in v2 format (name:hash).

    Uses a temp file + os.replace() to avoid corruption if the process
    crashes or is interrupted mid-write.
    """
    import tempfile

    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = "\n".join(f"{name}:{hash_val}" for name, hash_val in sorted(entries.items())) + "\n"

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(MANIFEST_FILE.parent),
            prefix=".bundled_manifest_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            atomic_replace(tmp_path, MANIFEST_FILE)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to write skills manifest %s: %s", MANIFEST_FILE, e, exc_info=True)


def _read_skill_name(skill_md: Path, fallback: str) -> str:
    """Read the name field from SKILL.md YAML frontmatter, falling back to *fallback*."""
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return fallback
    in_frontmatter = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return fallback


def _discover_bundled_skills(bundled_dir: Path) -> List[Tuple[str, Path]]:
    """
    Find all SKILL.md files in the bundled directory.
    Returns list of (skill_name, skill_directory_path) tuples.
    """
    skills = []
    if not bundled_dir.exists():
        return skills

    for skill_md in bundled_dir.rglob("SKILL.md"):
        if is_excluded_skill_path(skill_md):
            continue
        skill_dir = skill_md.parent
        skill_name = _read_skill_name(skill_md, skill_dir.name)
        skills.append((skill_name, skill_dir))

    return skills


def _compute_relative_dest(skill_dir: Path, bundled_dir: Path) -> Path:
    """
    Compute the destination path in SKILLS_DIR preserving the category structure.
    e.g., bundled/skills/mlops/axolotl -> ~/.elevate/skills/mlops/axolotl
    """
    rel = skill_dir.relative_to(bundled_dir)
    return SKILLS_DIR / rel


def _dir_hash(directory: Path) -> str:
    """Compute a hash of all file contents in a directory for change detection."""
    hasher = hashlib.md5()
    try:
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file():
                rel = fpath.relative_to(directory)
                hasher.update(str(rel).encode("utf-8"))
                hasher.update(fpath.read_bytes())
    except (OSError, IOError):
        pass
    return hasher.hexdigest()


# ── Three-way update support ────────────────────────────────────────────
# Pristine copies of the bundled version each skill was last synced from live
# under SKILLS_DIR/.bundled-base/<manifest key>/. With that base on disk, a
# user-modified skill is no longer a dead end: per-file classification against
# (base, user, new-bundled) applies upstream changes the user never touched,
# keeps user edits upstream never touched, and queues genuine collisions under
# SKILLS_DIR/.pending-merges/ for the box's own agent to merge semantically
# (``elevate skills merge-updates``). Both dot-dirs are in
# EXCLUDED_SKILL_DIRS so skill scanners never read them as real skills.

def base_snapshot_root() -> Path:
    """Resolved at call time so tests/profile-seeding can patch SKILLS_DIR."""
    return SKILLS_DIR / ".bundled-base"


def pending_merges_root() -> Path:
    """Resolved at call time so tests/profile-seeding can patch SKILLS_DIR."""
    return SKILLS_DIR / ".pending-merges"


def _safe_key(skill_name: str) -> str:
    """Manifest keys are frontmatter names — sanitize for use as a dirname."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in skill_name)


def _base_dir_for(skill_name: str) -> Path:
    return base_snapshot_root() / _safe_key(skill_name)


def _write_base_snapshot(skill_name: str, src_dir: Path) -> None:
    """Record *src_dir* as the pristine base for *skill_name* (best-effort)."""
    dest = _base_dir_for(skill_name)
    try:
        tmp = dest.with_suffix(".tmp")
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, tmp)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(tmp), str(dest))
    except (OSError, IOError) as e:
        logger.debug("base snapshot for %s failed: %s", skill_name, e)


def _read_file_map(directory: Path) -> Dict[str, bytes]:
    """All files under *directory* as {relative posix path: content bytes}."""
    out: Dict[str, bytes] = {}
    try:
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file():
                out[fpath.relative_to(directory).as_posix()] = fpath.read_bytes()
    except (OSError, IOError):
        pass
    return out


def _three_way_classify(
    base_dir: Path, user_dir: Path, new_dir: Path
) -> Tuple[List[str], List[str]]:
    """Classify every file across base/user/new.

    Returns (updates, conflicts):
      updates   — rel paths where the user never diverged from base and the
                  bundled version changed → safe to apply mechanically
                  (copy new over, or delete when removed upstream).
      conflicts — rel paths where BOTH sides changed and disagree.
    Files only the user changed (or added/deleted) are silently kept.
    """
    base = _read_file_map(base_dir)
    user = _read_file_map(user_dir)
    new = _read_file_map(new_dir)

    updates: List[str] = []
    conflicts: List[str] = []
    for rel in sorted(set(base) | set(user) | set(new)):
        b, u, n = base.get(rel), user.get(rel), new.get(rel)
        if u == n:
            continue  # already identical (or both absent)
        if b == u:
            updates.append(rel)  # user untouched → take upstream
        elif b == n:
            continue  # upstream untouched → keep user's version
        else:
            conflicts.append(rel)  # three distinct versions
    return updates, conflicts


def _apply_file_updates(user_dir: Path, new_dir: Path, rels: List[str]) -> None:
    """Apply mechanical updates: copy each rel from new_dir, delete if absent."""
    for rel in rels:
        src = new_dir / rel
        dst = user_dir / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()


def _queue_agent_merge(
    skill_name: str,
    dest: Path,
    skill_src: Path,
    bundled_hash: str,
    conflicts: List[str],
    bootstrap: bool,
    quiet: bool,
) -> None:
    """Queue a skill whose update needs the agent (self-contained snapshot).

    Idempotent per bundled version: an existing entry for the same
    bundled_hash is left alone; a newer bundled version refreshes the entry.
    """
    import json as _json
    import time as _time

    key = _safe_key(skill_name)
    entry = pending_merges_root() / f"{key}.json"
    new_copy = pending_merges_root() / f"{key}.new"
    try:
        if entry.exists():
            try:
                if _json.loads(entry.read_text(encoding="utf-8")).get("bundled_hash") == bundled_hash:
                    return  # already queued for this exact upstream version
            except (ValueError, OSError):
                pass  # unreadable entry — rebuild it
        pending_merges_root().mkdir(parents=True, exist_ok=True)
        if new_copy.exists():
            shutil.rmtree(new_copy, ignore_errors=True)
        shutil.copytree(skill_src, new_copy)
        entry.write_text(
            _json.dumps(
                {
                    "skill": skill_name,
                    "dest": str(dest),
                    "new_copy": str(new_copy),
                    "base": str(_base_dir_for(skill_name)) if _base_dir_for(skill_name).exists() else None,
                    "bundled_hash": bundled_hash,
                    "conflicts": conflicts,
                    "bootstrap": bootstrap,
                    "queued_at": _time.time(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if not quiet:
            print(f"  ⇢ {skill_name} (update waiting — agent merge queued)")
    except (OSError, IOError) as e:
        logger.debug("could not queue agent merge for %s: %s", skill_name, e)


# ── Corrective resync ──────────────────────────────────────────────────
# Markers of the SQLite-era skill instructions that were rewritten for the
# per-account Postgres data layer (2026-06). A skill on disk still carrying
# any of these points an agent at a frozen archive and will misbehave. When
# the bundled version no longer carries the marker but the on-disk copy does,
# the on-disk "modification" IS the bug — so we force-replace it even past the
# normal user-modified guard. Self-clearing: once replaced the marker is gone
# and this never fires for that skill again. A genuine user customization would
# not contain these removed-store references, so real edits are never clobbered.
_STALE_CONTENT_MARKERS: tuple = (
    "operational.db",
    "memory_store.db",
    "orchestration.db",
    "response_store.db",
    "usage_ledger.sqlite",
    "Treat SQLite as source of truth",
    "so SQLite can update",
    "SQLite closure",
    "Deal source: SQLite",
    "Board rows persist in SQLite",
    # Hand-rolled browser automation baked in by the post-task skill review:
    # an agent that fought through a login with terminal-scripted Selenium /
    # raw CDP can "learn" that approach into its local copy of a bundled
    # skill, which then shadows the bundled fix that forbids it (the
    # user-modified guard sees a divergent hash and skips). These are CODE
    # strings only — the bundled prose forbids Selenium/chromedriver in
    # words, never in code, so the both-sides check at the call site stays
    # false for clean bundled copies.
    "from selenium",
    "webdriver.Chrome",
    "debuggerAddress",
    "remote-allow-origins",
)


def _skill_has_stale_content(skill_dir: Path) -> bool:
    """True if any markdown file under ``skill_dir`` contains a stale marker."""
    try:
        for md in skill_dir.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except (OSError, IOError):
                continue
            if any(marker in text for marker in _STALE_CONTENT_MARKERS):
                return True
    except (OSError, IOError):
        pass
    return False


def sync_skills(quiet: bool = False) -> dict:
    """
    Sync bundled skills into ~/.elevate/skills/ using the manifest.

    Returns:
        dict with keys: copied (list), updated (list), skipped (int),
                        user_modified (list), cleaned (list), total_bundled (int)
    """
    bundled_dir = _get_bundled_dir()
    if not bundled_dir.exists():
        return {
            "copied": [], "updated": [], "skipped": 0,
            "user_modified": [], "cleaned": [], "total_bundled": 0,
        }

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # One-time migration: the bundled `cortextos/` skill folder was renamed to
    # `agent-ops/`. The manifest is keyed by NAME, so the moved skills aren't
    # seen as removed — which would leave the OLD ~/.elevate/skills/cortextos/
    # copies on disk as stale duplicates (same names, pre-nativization bodies).
    # Remove the orphaned folder so only the new agent-ops/ copies remain.
    try:
        _orphan = SKILLS_DIR / "cortextos"
        if _orphan.is_dir():
            import shutil as _shutil

            _shutil.rmtree(_orphan, ignore_errors=True)
            logger.info("skills sync: removed orphaned legacy cortextos/ skill folder")
    except Exception:
        logger.debug("orphaned cortextos cleanup skipped", exc_info=True)

    # One-time follow-up to the rename migration above: it removed the orphaned
    # folder but LEFT the manifest entries, and the sync loop reads "in manifest
    # + absent from user dir" as a deliberate user deletion — so the renamed
    # agent-ops skills were never copied and every agent loadout referencing
    # them broke ("Skill(s) not found and skipped: tasks, comms, memory, …").
    # Drop those manifest entries once (sentinel-guarded so a user who later
    # genuinely deletes an agent-ops skill stays respected) and let the standard
    # loop re-copy them as new.
    try:
        _sentinel = SKILLS_DIR / ".agent-ops-resync-v1"
        if not _sentinel.exists():
            _m = _read_manifest()
            _agent_ops_src = bundled_dir / "agent-ops"
            _dropped = 0
            if _agent_ops_src.is_dir():
                for _p in _agent_ops_src.iterdir():
                    _n = _p.name
                    if (
                        _p.is_dir()
                        and _n in _m
                        and not (SKILLS_DIR / "agent-ops" / _n).exists()
                    ):
                        _m.pop(_n, None)
                        _dropped += 1
            if _dropped:
                _write_manifest(_m)
                logger.info(
                    "skills sync: re-queued %d agent-ops skills whose manifest "
                    "entries blocked the rename migration",
                    _dropped,
                )
            _sentinel.write_text("done\n")
    except Exception:
        logger.debug("agent-ops manifest resync skipped", exc_info=True)

    # One-time manifest key renames: when a bundled skill's frontmatter `name`
    # changes but its directory does not, the manifest (keyed by name) still
    # holds the OLD key, so the sync loop reads the renamed skill as brand-new,
    # sees the same-named directory already on disk, and prints the scary
    # "yours was kept" notice instead of updating it. Carry the origin hash to
    # the new key once (sentinel-guarded) so an unedited install updates
    # normally and a genuinely user-edited copy still reads as user-modified.
    _MANIFEST_KEY_RENAMES = {"ideation": "creative-ideation"}
    try:
        _rn_sentinel = SKILLS_DIR / ".manifest-key-renames-v1"
        if not _rn_sentinel.exists():
            _m = _read_manifest()
            _renamed = 0
            for _old, _new in _MANIFEST_KEY_RENAMES.items():
                if _old in _m and _new not in _m:
                    _m[_new] = _m.pop(_old)
                    _renamed += 1
            if _renamed:
                _write_manifest(_m)
                logger.info(
                    "skills sync: carried %d manifest entries across a skill "
                    "rename so unedited copies keep auto-updating",
                    _renamed,
                )
            _rn_sentinel.write_text("done\n")
    except Exception:
        logger.debug("manifest key rename migration skipped", exc_info=True)

    manifest = _read_manifest()
    bundled_skills = _discover_bundled_skills(bundled_dir)
    bundled_names = {name for name, _ in bundled_skills}

    copied = []
    updated = []
    user_modified = []
    merged = []
    queued_for_agent = []
    corrected = []
    skipped = 0

    # Corrective pass: force-replace on-disk skills still carrying removed-store
    # markers (SQLite-era instructions). Runs BEFORE the normal loop — it drops
    # the manifest entry and removes the stale copy so the loop re-copies the
    # fixed bundled version through the standard (safe) path. Only fires when the
    # bundled version is clean, so it can't reintroduce a marker, and never
    # touches a skill whose disk copy is already clean.
    for skill_name, skill_src in bundled_skills:
        dest = _compute_relative_dest(skill_src, bundled_dir)
        if not dest.exists():
            continue
        if _skill_has_stale_content(dest) and not _skill_has_stale_content(skill_src):
            try:
                backup = dest.with_suffix(".stale-bak")
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                shutil.move(str(dest), str(backup))
                manifest.pop(skill_name, None)
                corrected.append(skill_name)
                if not quiet:
                    print(f"  ⟳ {skill_name} (corrected: removed-store reference replaced)")
            except (OSError, IOError) as e:
                if not quiet:
                    print(f"  ! Failed to correct {skill_name}: {e}")

    for skill_name, skill_src in bundled_skills:
        dest = _compute_relative_dest(skill_src, bundled_dir)
        bundled_hash = _dir_hash(skill_src)

        if skill_name not in manifest:
            # ── New skill — never offered before ──
            try:
                if dest.exists():
                    # User already has a skill with the same name — don't overwrite.
                    # Only baseline in the manifest when the on-disk copy is
                    # byte-identical to bundled (e.g. a reset that re-syncs, or
                    # a coincidentally identical install); that case is harmless
                    # to track. If the copy differs (custom skill, hub-installed,
                    # or user-edited) skip the manifest write: recording
                    # bundled_hash there would poison update detection by making
                    # user_hash != origin_hash read as "user-modified" on every
                    # subsequent sync, permanently blocking bundled updates.
                    skipped += 1
                    if _dir_hash(dest) == bundled_hash:
                        manifest[skill_name] = bundled_hash
                    elif not quiet:
                        print(
                            f"  ⚠ {skill_name}: bundled version shipped but you "
                            f"already have a local skill by this name — yours "
                            f"was kept. Run `hermes skills reset {skill_name}` "
                            f"to replace it with the bundled version."
                        )
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(skill_src, dest)
                    copied.append(skill_name)
                    manifest[skill_name] = bundled_hash
                    _write_base_snapshot(skill_name, skill_src)
                    if not quiet:
                        print(f"  + {skill_name}")
            except (OSError, IOError) as e:
                if not quiet:
                    print(f"  ! Failed to copy {skill_name}: {e}")
                # Do NOT add to manifest — next sync should retry

        elif dest.exists():
            # ── Existing skill — in manifest AND on disk ──
            origin_hash = manifest.get(skill_name, "")
            user_hash = _dir_hash(dest)

            if not origin_hash:
                # v1 migration: no origin hash recorded. Set baseline from
                # user's current copy so future syncs can detect modifications.
                manifest[skill_name] = user_hash
                if user_hash == bundled_hash:
                    skipped += 1  # already in sync
                else:
                    # Can't tell if user modified or bundled changed — be safe
                    skipped += 1
                continue

            if user_hash != origin_hash:
                # User modified this skill. With a base snapshot on disk this
                # is no longer a dead end — merge what we safely can.
                base_dir = _base_dir_for(skill_name)
                if bundled_hash == origin_hash:
                    # No upstream change pending. The current bundled copy IS
                    # the base they diverged from — record it (exact) so a
                    # future upstream change can three-way merge.
                    if not base_dir.exists():
                        _write_base_snapshot(skill_name, skill_src)
                    user_modified.append(skill_name)
                    if not quiet:
                        print(f"  ~ {skill_name} (user-modified, no update pending)")
                    continue

                if base_dir.exists():
                    updates, conflicts = _three_way_classify(base_dir, dest, skill_src)
                    if not conflicts:
                        # Every changed file is one-sided → mechanical merge.
                        backup = dest.with_suffix(".bak-merge")
                        try:
                            if backup.exists():
                                shutil.rmtree(backup, ignore_errors=True)
                            shutil.copytree(dest, backup)
                            _apply_file_updates(dest, skill_src, updates)
                            _write_base_snapshot(skill_name, skill_src)
                            manifest[skill_name] = bundled_hash
                            merged.append(skill_name)
                            shutil.rmtree(backup, ignore_errors=True)
                            if not quiet:
                                print(
                                    f"  ⇡ {skill_name} (merged: {len(updates)} upstream "
                                    f"file(s), your edits kept)"
                                )
                        except (OSError, IOError) as e:
                            if backup.exists() and not dest.exists():
                                shutil.move(str(backup), str(dest))
                            if not quiet:
                                print(f"  ! Failed to merge {skill_name}: {e}")
                        continue
                    # Both sides touched the same file(s) → the box's agent
                    # merges semantically; nothing is overwritten meanwhile.
                    _queue_agent_merge(
                        skill_name, dest, skill_src, bundled_hash,
                        conflicts, bootstrap=False, quiet=quiet,
                    )
                    queued_for_agent.append(skill_name)
                    user_modified.append(skill_name)
                    continue

                # Diverged with an update pending but no base recorded (installs
                # that predate base snapshots): the true base is unknowable, so
                # never guess mechanically — hand the whole skill to the agent.
                _queue_agent_merge(
                    skill_name, dest, skill_src, bundled_hash,
                    conflicts=[], bootstrap=True, quiet=quiet,
                )
                queued_for_agent.append(skill_name)
                user_modified.append(skill_name)
                continue

            # User copy matches origin — check if bundled has a newer version
            if bundled_hash != origin_hash:
                try:
                    # Move old copy to a backup so we can restore on failure
                    backup = dest.with_suffix(".bak")
                    shutil.move(str(dest), str(backup))
                    try:
                        shutil.copytree(skill_src, dest)
                        manifest[skill_name] = bundled_hash
                        _write_base_snapshot(skill_name, skill_src)
                        updated.append(skill_name)
                        if not quiet:
                            print(f"  ↑ {skill_name} (updated)")
                        # Remove backup after successful copy
                        shutil.rmtree(backup, ignore_errors=True)
                    except (OSError, IOError):
                        # Restore from backup
                        if backup.exists() and not dest.exists():
                            shutil.move(str(backup), str(dest))
                        raise
                except (OSError, IOError) as e:
                    if not quiet:
                        print(f"  ! Failed to update {skill_name}: {e}")
            else:
                skipped += 1  # bundled unchanged, user unchanged
                if not _base_dir_for(skill_name).exists():
                    # Backfill the base snapshot while all three copies agree.
                    _write_base_snapshot(skill_name, skill_src)

        else:
            # ── In manifest but not on disk — user deleted it ──
            skipped += 1

    # Clean stale manifest entries (skills removed from bundled dir)
    cleaned = sorted(set(manifest.keys()) - bundled_names)
    for name in cleaned:
        del manifest[name]
        # Drop the matching base snapshot and any queued merge — the skill no
        # longer ships, so there is nothing to merge toward.
        shutil.rmtree(_base_dir_for(name), ignore_errors=True)
        _key = _safe_key(name)
        try:
            (pending_merges_root() / f"{_key}.json").unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(pending_merges_root() / f"{_key}.new", ignore_errors=True)

    # Also copy DESCRIPTION.md files for categories (if not already present)
    for desc_md in bundled_dir.rglob("DESCRIPTION.md"):
        rel = desc_md.relative_to(bundled_dir)
        dest_desc = SKILLS_DIR / rel
        if not dest_desc.exists():
            try:
                dest_desc.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(desc_md, dest_desc)
            except (OSError, IOError) as e:
                logger.debug("Could not copy %s: %s", desc_md, e)

    _write_manifest(manifest)

    return {
        "copied": copied,
        "updated": updated,
        "skipped": skipped,
        "user_modified": user_modified,
        "merged": merged,
        "queued_for_agent": queued_for_agent,
        "corrected": corrected,
        "cleaned": cleaned,
        "total_bundled": len(bundled_skills),
    }


def reset_bundled_skill(name: str, restore: bool = False) -> dict:
    """
    Reset a bundled skill's manifest tracking so future syncs work normally.

    When a user edits a bundled skill, subsequent syncs mark it as
    ``user_modified`` and skip it forever — even if the user later copies
    the bundled version back into place, because the manifest still holds
    the *old* origin hash. This function breaks that loop.

    Args:
        name: The skill name (matches the manifest key / skill frontmatter name).
        restore: If True, also delete the user's copy in SKILLS_DIR and let
                 the next sync re-copy the current bundled version. If False
                 (default), only clear the manifest entry — the user's
                 current copy is preserved but future updates work again.

    Returns:
        dict with keys:
          - ok: bool, whether the reset succeeded
          - action: one of "manifest_cleared", "restored", "not_in_manifest",
                    "bundled_missing"
          - message: human-readable description
          - synced: dict from sync_skills() if a sync was triggered, else None
    """
    manifest = _read_manifest()
    bundled_dir = _get_bundled_dir()
    bundled_skills = _discover_bundled_skills(bundled_dir)
    bundled_by_name = dict(bundled_skills)

    in_manifest = name in manifest
    is_bundled = name in bundled_by_name

    if not in_manifest and not is_bundled:
        return {
            "ok": False,
            "action": "not_in_manifest",
            "message": (
                f"'{name}' is not a tracked bundled skill. Nothing to reset. "
                f"(Hub-installed skills use `hermes skills uninstall`.)"
            ),
            "synced": None,
        }

    # Step 1: drop the manifest entry so next sync treats it as new
    if in_manifest:
        del manifest[name]
        _write_manifest(manifest)

    # Step 2 (optional): delete the user's copy so next sync re-copies bundled
    deleted_user_copy = False
    if restore:
        if not is_bundled:
            return {
                "ok": False,
                "action": "bundled_missing",
                "message": (
                    f"'{name}' has no bundled source — manifest entry cleared "
                    f"but cannot restore from bundled (skill was removed upstream)."
                ),
                "synced": None,
            }
        # The destination mirrors the bundled path relative to bundled_dir.
        dest = _compute_relative_dest(bundled_by_name[name], bundled_dir)
        if dest.exists():
            try:
                shutil.rmtree(dest)
                deleted_user_copy = True
            except (OSError, IOError) as e:
                return {
                    "ok": False,
                    "action": "manifest_cleared",
                    "message": (
                        f"Cleared manifest entry for '{name}' but could not "
                        f"delete user copy at {dest}: {e}"
                    ),
                    "synced": None,
                }

    # Step 3: run sync to re-baseline (or re-copy if we deleted)
    synced = sync_skills(quiet=True)

    if restore and deleted_user_copy:
        action = "restored"
        message = f"Restored '{name}' from bundled source."
    elif restore:
        # Nothing on disk to delete, but we re-synced — acts like a fresh install
        action = "restored"
        message = f"Restored '{name}' (no prior user copy, re-copied from bundled)."
    else:
        action = "manifest_cleared"
        message = (
            f"Cleared manifest entry for '{name}'. Future `hermes update` runs "
            f"will re-baseline against your current copy and accept upstream changes."
        )

    return {"ok": True, "action": action, "message": message, "synced": synced}


if __name__ == "__main__":
    print("Syncing bundled skills into ~/.elevate/skills/ ...")
    result = sync_skills(quiet=False)
    parts = [
        f"{len(result['copied'])} new",
        f"{len(result['updated'])} updated",
        f"{result['skipped']} unchanged",
    ]
    if result["user_modified"]:
        names = result["user_modified"]
        MAX_SHOW = 5
        shown = ", ".join(names[:MAX_SHOW])
        if len(names) > MAX_SHOW:
            shown += f", +{len(names) - MAX_SHOW} more"
        parts.append(f"{len(names)} user-modified (kept): {shown}")
    if result["cleaned"]:
        parts.append(f"{len(result['cleaned'])} cleaned from manifest")
    print(f"\nDone: {', '.join(parts)}. {result['total_bundled']} total bundled.")
