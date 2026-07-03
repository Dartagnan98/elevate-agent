"""Sync-backup directories must be invisible to every skill scanner.

Corrective restores leave ``<skill>.stale-bak/`` beside the live skill,
merge-updates leaves ``.bak-premerge``, snapshots use ``.tmp`` — each holding
a full SKILL.md with the SAME frontmatter name as the real skill. If a scanner
reads them, the routing index can be served the stale pre-restore description
again, resurrecting exactly the confusion the restore fixed (Skyleigh wipe,
2026-07: 185 such backups in one skills tree).
"""
import pathlib

from agent.skill_utils import is_excluded_skill_path, iter_skill_index_files


def test_backup_suffixed_dirs_are_excluded():
    assert is_excluded_skill_path("skills/agent-ops/approvals.stale-bak/SKILL.md")
    assert is_excluded_skill_path(pathlib.Path("skills/x/y.bak-premerge/SKILL.md"))
    assert is_excluded_skill_path("skills/.bundled-base/foo.tmp/SKILL.md")
    # real skills stay visible — including dotted names that merely CONTAIN a
    # suffix-like fragment mid-name
    assert not is_excluded_skill_path("skills/agent-ops/approvals/SKILL.md")
    assert not is_excluded_skill_path("skills/creative/creative-ideation/SKILL.md")


def test_iter_skill_index_files_skips_backups(tmp_path):
    live = tmp_path / "agent-ops" / "approvals"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text("---\nname: approvals\ndescription: new\n---\n")
    bak = tmp_path / "agent-ops" / "approvals.stale-bak"
    bak.mkdir()
    (bak / "SKILL.md").write_text("---\nname: approvals\ndescription: STALE\n---\n")
    merge = tmp_path / "agent-ops" / "tasks.bak-premerge"
    merge.mkdir()
    (merge / "SKILL.md").write_text("---\nname: tasks\ndescription: STALE\n---\n")

    found = [str(p) for p in iter_skill_index_files(tmp_path, "SKILL.md")]
    assert len(found) == 1
    assert found[0].endswith("agent-ops/approvals/SKILL.md")
    assert not any(".stale-bak" in p or ".bak-premerge" in p for p in found)
