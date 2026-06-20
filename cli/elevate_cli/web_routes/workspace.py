"""Workspace git status and open routes for the dashboard."""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import APIRouter, Body, HTTPException

from elevate_cli.config import get_elevate_home


OpenInFileManager = Callable[[Path], None]
_GIT_UNAVAILABLE_WARNED = False


def git_value(
    repo_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 5,
) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def _parse_git_shortstat(raw: str) -> Dict[str, int]:
    stats = {"files": 0, "insertions": 0, "deletions": 0}
    for key, pattern in {
        "files": r"(\d+)\s+files?\s+changed",
        "insertions": r"(\d+)\s+insertions?\(\+\)",
        "deletions": r"(\d+)\s+deletions?\(-\)",
    }.items():
        match = re.search(pattern, raw)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _git_shortstat(repo_dir: Path) -> Dict[str, int]:
    raw = git_value(repo_dir, "diff", "--shortstat", "HEAD") or ""
    return _parse_git_shortstat(raw)


def _git_run_for_tree(
    repo_dir: Path,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _nul_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in raw.split("\0") if part]


def _git_worktree_changed_paths(repo_dir: Path) -> list[str]:
    tracked = git_value(
        repo_dir,
        "diff",
        "--name-only",
        "-z",
        "HEAD",
        "--",
        timeout=10,
    )
    untracked = git_value(
        repo_dir,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        timeout=10,
    )
    return sorted(set(_nul_paths(tracked) + _nul_paths(untracked)))


def _git_worktree_fingerprint(repo_dir: Path, changed_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in changed_paths:
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        path = repo_dir / rel
        try:
            st = path.lstat()
            h.update(f"{st.st_mtime_ns}:{st.st_size}:{st.st_mode}".encode("ascii"))
        except FileNotFoundError:
            h.update(b"missing")
        except OSError as exc:
            h.update(f"error:{type(exc).__name__}".encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def _git_worktree_tree(repo_dir: Path, changed_paths: list[str] | None = None) -> str:
    if changed_paths is None:
        changed_paths = _git_worktree_changed_paths(repo_dir)
    with tempfile.TemporaryDirectory(prefix="elevate-git-index-") as tmp:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")

        read = _git_run_for_tree(repo_dir, env, "read-tree", "HEAD")
        if read.returncode != 0:
            read = _git_run_for_tree(repo_dir, env, "read-tree", "--empty")
        if read.returncode != 0:
            raise RuntimeError((read.stderr or read.stdout or "git read-tree failed").strip())

        if changed_paths:
            add = subprocess.run(
                ["git", "update-index", "--add", "--remove", "-z", "--stdin"],
                cwd=repo_dir,
                env=env,
                input="\0".join(changed_paths) + "\0",
                capture_output=True,
                text=True,
                timeout=20,
            )
            if add.returncode != 0:
                raise RuntimeError((add.stderr or add.stdout or "git update-index failed").strip())

        tree = _git_run_for_tree(repo_dir, env, "write-tree")
        if tree.returncode != 0:
            raise RuntimeError((tree.stderr or tree.stdout or "git write-tree failed").strip())
        value = (tree.stdout or "").strip()
        if not value:
            raise RuntimeError("git write-tree returned no tree")
        return value


def _git_tree_exists(repo_dir: Path, tree: str | None) -> bool:
    if not tree:
        return False
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{tree}^{{tree}}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0


def _git_tree_shortstat(repo_dir: Path, baseline_tree: str, current_tree: str) -> Dict[str, int]:
    raw = git_value(
        repo_dir,
        "diff",
        "--shortstat",
        baseline_tree,
        current_tree,
        timeout=20,
    ) or ""
    return _parse_git_shortstat(raw)


def _session_git_baseline_path(session_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id).strip("._")[:140]
    if not safe_id:
        safe_id = "session"
    return get_elevate_home() / "session_git_baselines" / f"{safe_id}.json"


def _session_git_status_cache_path(session_id: str) -> Path:
    path = _session_git_baseline_path(session_id)
    return path.with_name(f"{path.stem}.status.json")


def _read_session_git_baseline(session_id: str, repo_dir: Path) -> Dict[str, Any] | None:
    try:
        path = _session_git_baseline_path(session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("repo_path") != str(repo_dir):
            return None
        tree = str(raw.get("tree") or "")
        if not _git_tree_exists(repo_dir, tree):
            return None
        return raw
    except Exception:
        return None


def _write_session_git_baseline(
    session_id: str,
    repo_dir: Path,
    *,
    branch: str | None,
    short_sha: str | None,
    tree: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "version": 1,
        "session_id": session_id,
        "repo_path": str(repo_dir),
        "repo_name": repo_dir.name,
        "branch": branch,
        "short_sha": short_sha,
        "tree": tree,
        "created_at": time.time(),
    }
    path = _session_git_baseline_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return payload


def _read_session_git_status_cache(
    session_id: str,
    repo_dir: Path,
    *,
    baseline_tree: str,
    fingerprint: str,
) -> Dict[str, Any] | None:
    try:
        path = _session_git_status_cache_path(session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("repo_path") != str(repo_dir):
            return None
        if raw.get("baseline_tree") != baseline_tree:
            return None
        if raw.get("fingerprint") != fingerprint:
            return None
        stats = raw.get("stats")
        if not isinstance(stats, dict):
            return None
        return raw
    except Exception:
        return None


def _write_session_git_status_cache(
    session_id: str,
    repo_dir: Path,
    *,
    baseline_tree: str,
    fingerprint: str,
    stats: Dict[str, int],
    changed_files: int,
) -> None:
    try:
        payload = {
            "version": 1,
            "session_id": session_id,
            "repo_path": str(repo_dir),
            "baseline_tree": baseline_tree,
            "fingerprint": fingerprint,
            "stats": stats,
            "changed_files": changed_files,
            "created_at": time.time(),
        }
        path = _session_git_status_cache_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _git_ahead_behind(repo_dir: Path) -> tuple[int, int]:
    raw = git_value(repo_dir, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if not raw:
        return 0, 0
    parts = raw.split()
    if len(parts) < 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def _github_repo_url(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    url = remote_url.strip()
    if url.startswith("git@github.com:"):
        path = url.split(":", 1)[1]
    elif "github.com/" in url:
        path = urllib.parse.urlparse(url).path.lstrip("/")
    else:
        return None
    if path.endswith(".git"):
        path = path[:-4]
    if path.count("/") < 1:
        return None
    return f"https://github.com/{path}"


def _github_compare_url(repo_url: str | None, branch: str | None, upstream: str | None) -> str | None:
    if not repo_url or not branch or branch in {"HEAD", "main", "master"}:
        return None
    base = "main"
    if upstream:
        upstream_branch = upstream.split("/", 1)[1] if "/" in upstream else upstream
        if upstream_branch and upstream_branch != branch:
            base = upstream_branch
    return (
        f"{repo_url}/compare/"
        f"{urllib.parse.quote(base, safe='')}..."
        f"{urllib.parse.quote(branch, safe='')}?expand=1"
    )


def _resolve_workspace_repo_dir(workspace_root: Path) -> Path | None:
    local_root = git_value(workspace_root, "rev-parse", "--show-toplevel")
    if local_root:
        return Path(local_root).resolve()
    return workspace_root


def _workspace_display_dir(
    *,
    workspace_root: Path,
    repo_dir: Path,
    working_directory: str | None = None,
) -> Path:
    fallback = repo_dir
    try:
        workspace_root.resolve().relative_to(repo_dir.resolve())
        fallback = workspace_root
    except Exception:
        fallback = repo_dir

    if working_directory:
        try:
            candidate = Path(working_directory).expanduser()
            if not candidate.is_absolute():
                candidate = (repo_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.exists():
                try:
                    candidate.relative_to(repo_dir.resolve())
                except Exception:
                    return fallback
                return candidate
        except Exception:
            pass
    return fallback


def _repo_relative_display(repo_dir: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(repo_dir.resolve())
    except Exception:
        return path.name or str(path)
    if str(rel) == ".":
        return repo_dir.name
    return f"{repo_dir.name}/{rel.as_posix()}"


def _empty_workspace_git_payload(error: str | None = None) -> Dict[str, Any]:
    return {
        "ok": error is None,
        "error": error,
        "path": None,
        "repo_path": None,
        "working_directory": None,
        "display_name": None,
        "repo_name": None,
        "branch": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "changed_files": 0,
        "insertions": 0,
        "deletions": 0,
        "untracked": 0,
        "dirty": False,
        "repo_changed_files": 0,
        "repo_insertions": 0,
        "repo_deletions": 0,
        "repo_untracked": 0,
        "repo_dirty": False,
        "diff_scope": "repo",
        "baseline_created": False,
        "baseline_at": None,
        "short_sha": None,
        "origin_url": None,
        "repo_url": None,
        "pr_url": None,
        "checked_at": time.time(),
    }


def _workspace_git_status_payload(
    *,
    workspace_root: Path,
    session_id: str | None = None,
    working_directory: str | None = None,
) -> Dict[str, Any]:
    repo_dir = _resolve_workspace_repo_dir(workspace_root)
    if repo_dir is None:
        return _empty_workspace_git_payload("not_git_install")

    display_dir = _workspace_display_dir(
        workspace_root=workspace_root,
        repo_dir=repo_dir,
        working_directory=working_directory,
    )
    branch = git_value(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = git_value(repo_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead, behind = _git_ahead_behind(repo_dir)
    porcelain = git_value(repo_dir, "status", "--porcelain=v1") or ""
    status_lines = [line for line in porcelain.splitlines() if line.strip()]
    untracked = sum(1 for line in status_lines if line.startswith("??"))
    repo_stats = _git_shortstat(repo_dir)
    origin_url = git_value(repo_dir, "remote", "get-url", "origin")
    repo_url = _github_repo_url(origin_url)
    short_sha = git_value(repo_dir, "rev-parse", "--short", "HEAD")
    diff_scope = "repo"
    baseline_created = False
    baseline_at: float | None = None
    display_stats = repo_stats
    display_changed_files = len(status_lines)
    display_untracked = untracked

    if session_id:
        changed_paths = _git_worktree_changed_paths(repo_dir)
        fingerprint = _git_worktree_fingerprint(repo_dir, changed_paths)
        baseline = _read_session_git_baseline(session_id, repo_dir)
        cache = (
            _read_session_git_status_cache(
                session_id,
                repo_dir,
                baseline_tree=str(baseline["tree"]),
                fingerprint=fingerprint,
            )
            if baseline
            else None
        )
        if cache:
            baseline_at = float(baseline.get("created_at") or 0) or None
            cached_stats = cache.get("stats") or {}
            display_stats = {
                "files": int(cached_stats.get("files") or 0),
                "insertions": int(cached_stats.get("insertions") or 0),
                "deletions": int(cached_stats.get("deletions") or 0),
            }
            display_changed_files = int(cache.get("changed_files") or display_stats["files"])
        else:
            current_tree = _git_worktree_tree(repo_dir, changed_paths=changed_paths)
            if not baseline:
                baseline = _write_session_git_baseline(
                    session_id,
                    repo_dir,
                    branch=branch,
                    short_sha=short_sha,
                    tree=current_tree,
                )
                baseline_created = True
            baseline_at = float(baseline.get("created_at") or 0) or None
            display_stats = _git_tree_shortstat(repo_dir, str(baseline["tree"]), current_tree)
            display_changed_files = display_stats["files"]
            _write_session_git_status_cache(
                session_id,
                repo_dir,
                baseline_tree=str(baseline["tree"]),
                fingerprint=fingerprint,
                stats=display_stats,
                changed_files=display_changed_files,
            )
        display_untracked = 0
        diff_scope = "session"

    return {
        "ok": True,
        "error": None,
        "path": str(repo_dir),
        "repo_path": str(repo_dir),
        "working_directory": str(display_dir),
        "display_name": _repo_relative_display(repo_dir, display_dir),
        "repo_name": repo_dir.name,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "changed_files": display_changed_files,
        "insertions": display_stats["insertions"],
        "deletions": display_stats["deletions"],
        "untracked": display_untracked,
        "dirty": bool(display_changed_files),
        "repo_changed_files": len(status_lines),
        "repo_insertions": repo_stats["insertions"],
        "repo_deletions": repo_stats["deletions"],
        "repo_untracked": untracked,
        "repo_dirty": bool(status_lines),
        "diff_scope": diff_scope,
        "baseline_created": baseline_created,
        "baseline_at": baseline_at,
        "short_sha": short_sha,
        "origin_url": origin_url,
        "repo_url": repo_url,
        "pr_url": _github_compare_url(repo_url, branch, upstream),
        "checked_at": time.time(),
    }


def _is_git_unavailable_error(msg: str) -> bool:
    low = (msg or "").lower()
    return (
        "no developer tools were found" in low
        or "xcode-select" in low
        or "git: command not found" in low
        or "git: not found" in low
        or "no such file or directory: 'git'" in low
    )


def create_workspace_router(
    *,
    workspace_root: Path,
    open_in_file_manager: OpenInFileManager,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build routes for workspace git status and opening the workspace."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/workspace/git/status")
    async def get_workspace_git_status(
        session_id: str | None = None,
        working_directory: str | None = None,
    ):
        try:
            return await asyncio.to_thread(
                _workspace_git_status_payload,
                workspace_root=workspace_root,
                session_id=session_id,
                working_directory=working_directory,
            )
        except Exception as exc:
            msg = str(exc)
            if _is_git_unavailable_error(msg):
                global _GIT_UNAVAILABLE_WARNED
                if not _GIT_UNAVAILABLE_WARNED:
                    _GIT_UNAVAILABLE_WARNED = True
                    _log.warning(
                        "workspace git status disabled: git is unavailable "
                        "(Xcode command line tools not installed?): %s",
                        msg.splitlines()[0] if msg else "git unavailable",
                    )
                return _empty_workspace_git_payload(msg)
            _log.exception("GET /api/workspace/git/status failed")
            return _empty_workspace_git_payload(msg)

    @router.post("/api/workspace/open")
    async def open_workspace(payload: dict[str, Any] | None = Body(default=None)):
        repo_dir = _resolve_workspace_repo_dir(workspace_root)
        if repo_dir is None:
            raise HTTPException(status_code=404, detail="Workspace repo not found")
        requested = str((payload or {}).get("path") or "").strip()
        target = _workspace_display_dir(
            workspace_root=workspace_root,
            repo_dir=repo_dir,
            working_directory=requested,
        )
        open_in_file_manager(target)
        return {"ok": True, "path": str(target)}

    return router
