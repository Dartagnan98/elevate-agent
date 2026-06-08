import os
import shutil

from agent.cwd import safe_getcwd, safe_realpath
from agent.file_safety import is_write_denied
from agent.lsp.workspace import resolve_workspace_for_file
from tools.file_tools import _resolve_path_for_task


def test_deleted_process_cwd_falls_back_to_terminal_cwd(tmp_path, monkeypatch):
    original = os.getcwd()
    dead = tmp_path / "dead-cwd"
    fallback = tmp_path / "fallback-cwd"
    dead.mkdir()
    fallback.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", str(fallback))

    os.chdir(dead)
    shutil.rmtree(dead)
    try:
        assert safe_getcwd() == str(fallback)
        assert safe_realpath("notes.md") == str(fallback / "notes.md")
        assert is_write_denied("notes.md") is False
        assert resolve_workspace_for_file("notes.md") == (None, False)
        assert _resolve_path_for_task("notes.md") == fallback / "notes.md"
    finally:
        os.chdir(original)
