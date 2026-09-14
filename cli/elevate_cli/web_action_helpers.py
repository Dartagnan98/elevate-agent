from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


def spawn_elevate_action(
    subcommand: List[str],
    name: str,
    *,
    action_log_files: Dict[str, str],
    action_log_dir: Path,
    action_procs: Dict[str, subprocess.Popen],
    project_root: Path,
) -> subprocess.Popen:
    """Spawn ``elevate <subcommand>`` detached and record the Popen handle."""
    log_file_name = action_log_files[name]
    action_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = action_log_dir / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "elevate_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(project_root),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "ELEVATE_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    action_procs[name] = proc
    return proc


def tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``."""
    if not path.exists():
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


def session_reveal_target(session_id: str, *, elevate_home: Path) -> Path:
    sessions_dir = elevate_home / "sessions"
    transcript = sessions_dir / f"{session_id}.jsonl"
    if transcript.exists():
        return transcript
    return sessions_dir


def open_in_file_manager(path: Path) -> None:
    path = path.expanduser().resolve()
    if sys.platform == "darwin":
        cmd = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
    elif sys.platform == "win32":
        selector = f"/select,{path}" if path.is_file() else str(path)
        cmd = ["explorer", selector]
    else:
        cmd = ["xdg-open", str(path if path.is_dir() else path.parent)]

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
