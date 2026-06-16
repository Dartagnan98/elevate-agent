"""Run the social-content-engine fetchers under a capable interpreter.

The skill historically invoked these scripts with a bare ``python3``. On a
customer Mac that resolves to the system Python (no ``httpx``, no ``elevate_cli``
on the path), so every fetcher fell through ``find_composio_account``'s silent
``except: return None`` and reported the platform as ``not_configured`` — even
when the Composio key and all accounts were perfectly connected.

Importing this module FIRST makes a fetcher self-heal:
  1. put the cli root on ``sys.path`` so ``elevate_cli`` is importable, then
  2. if the current interpreter still can't load the HTTP deps, re-exec into the
     bundled app Python (``…/Resources/runtime/python``) — or the repo ``.venv``
     in development — so the script runs with everything it needs.

Only stdlib is imported here, so it is safe under any Python (incl. system 3.9).
"""
import glob
import os
import sys

_GUARD = "ELEVATE_SCE_BOOTSTRAPPED"


def _cli_root() -> str:
    # …/cli/skills/social-content-engine/scripts/_bootstrap.py -> …/cli
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _ensure_cli_on_path() -> None:
    root = _cli_root()
    if root not in sys.path:
        sys.path.insert(0, root)


def _is_capable() -> bool:
    # Test the REAL import chain the fetchers need (elevate_cli + httpx +
    # tenacity); a partial check let system Python — which happened to have
    # httpx but not tenacity — pass and never re-exec.
    try:
        from elevate_cli import composio_client  # noqa: F401
        return True
    except Exception:
        return False


def _candidate_interpreters() -> list[str]:
    cli = _cli_root()
    resources = os.path.dirname(cli)  # bundle layout: …/Resources/cli
    cands: list[str] = []
    # Bundled app runtime (production install).
    cands += sorted(glob.glob(os.path.join(resources, "runtime", "python", "bin", "python3*")))
    # Repo virtualenv (development).
    cands += [
        os.path.join(cli, ".venv", "bin", "python"),
        os.path.join(os.path.dirname(cli), ".venv", "bin", "python"),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in cands:
        if p and os.path.exists(p) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _reexec_if_needed() -> None:
    _ensure_cli_on_path()
    if _is_capable():
        return
    if os.environ.get(_GUARD):
        # Already re-exec'd once; don't loop. The fetcher's own diagnostics
        # (and find_composio_account) will surface a clear reason from here.
        return
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script:
        return
    for py in _candidate_interpreters():
        if os.path.realpath(py) == os.path.realpath(sys.executable):
            continue
        env = dict(os.environ)
        env[_GUARD] = "1"
        try:
            sys.stderr.write(
                f"[social-content-engine] re-exec into capable Python: {py}\n"
            )
            sys.stderr.flush()
            os.execve(py, [py, script, *sys.argv[1:]], env)
        except Exception:
            continue


_reexec_if_needed()
