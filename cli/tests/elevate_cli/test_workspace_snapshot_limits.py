"""Chat status must not snapshot large artifact folders or change the user's index."""
import subprocess
from unittest.mock import patch

import pytest

from elevate_cli.web_routes import workspace


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    (root / "tracked.txt").write_text("one\n")
    git(root, "add", "tracked.txt")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")
    return root


@pytest.mark.parametrize("large_kind", ["count", "bytes"])
def test_large_workspace_uses_repo_counts_without_snapshot(repo, monkeypatch, large_kind):
    (repo / "artifact.bin").write_bytes(b"data")
    if large_kind == "count":
        monkeypatch.setattr(workspace, "_SESSION_SNAPSHOT_MAX_FILES", 0)
    else:
        monkeypatch.setattr(workspace, "_SESSION_SNAPSHOT_MAX_BYTES", 1)
    before = (repo / ".git/index").read_bytes()
    with patch.object(workspace, "_git_worktree_tree", side_effect=AssertionError("must not snapshot")):
        result = workspace._workspace_git_status_payload(workspace_root=repo, session_id="large")
    assert result["ok"]
    assert result["diff_scope"] == "repo"
    assert result["repo_dirty"] and result["untracked"] == 1
    assert result["session_snapshot_skipped"]
    assert not workspace._session_git_baseline_path("large").exists()
    assert (repo / ".git/index").read_bytes() == before


def test_small_workspace_session_diff_captures_edits_additions_and_deletions(repo):
    result = workspace._workspace_git_status_payload(workspace_root=repo, session_id="small")
    assert result["baseline_created"] and result["changed_files"] == 0
    (repo / "tracked.txt").write_text("one\ntwo\n")
    (repo / "new.txt").write_text("new\n")
    staged_before = git(repo, "diff", "--cached")
    result = workspace._workspace_git_status_payload(workspace_root=repo, session_id="small")
    assert result["diff_scope"] == "session"
    assert result["changed_files"] == 2 and result["insertions"] == 2
    assert result["session_snapshot_skipped"] is None
    (repo / "tracked.txt").unlink()
    result = workspace._workspace_git_status_payload(workspace_root=repo, session_id="small")
    assert result["deletions"] == 1 and result["changed_files"] == 2
    assert git(repo, "diff", "--cached") == staged_before
