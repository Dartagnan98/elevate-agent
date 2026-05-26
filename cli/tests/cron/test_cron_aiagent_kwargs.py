"""Lock the cron AIAgent() call site to AIAgent.__init__'s real signature.

Why this test exists
--------------------
2026-05-25: two cron jobs (Memory smoke, Social Content Engine) failed at
02:00 and 07:00 with::

    TypeError: AIAgent.__init__() got an unexpected keyword argument
    'load_soul_identity'

The kwarg had been added to ``cron/scheduler.py``'s AIAgent() call but the
constructor signature didn't accept it. The existing
``test_cron_workdir.py`` did not catch this because its FakeAgent uses
``**kwargs`` and silently absorbs unknown args.

This test does NOT stub AIAgent. It parses the real AIAgent() call site in
``cron/scheduler.py``, inspects the real ``AIAgent.__init__.__signature__``,
and asserts every kwarg the scheduler passes is accepted by the
constructor. Adding a kwarg on one side without the other now fails CI.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest


CLI_ROOT = Path(__file__).resolve().parents[2]


def _scheduler_path() -> Path:
    return CLI_ROOT / "cron" / "scheduler.py"


def _agent_cbs_path() -> Path:
    return CLI_ROOT / "tui_gateway" / "server.py"


# Splatted dicts the scheduler passes to AIAgent. Each entry names a
# function in the codebase whose return-dict contributes kwargs through
# ``**splat``. The test statically resolves them so the kwarg coverage
# stays accurate without losing the strict-no-unknown-kwarg lock.
KNOWN_SPLAT_SOURCES = {
    # ``**_tg_cron_callbacks`` at the AIAgent() call binds the dict
    # returned by ``tui_gateway.server._agent_cbs(sid)``.
    "_tg_cron_callbacks": ("tui_gateway/server.py", "_agent_cbs"),
}


def _kwarg_names_of_returned_dict(file_path: Path, func_name: str) -> list[str]:
    """Statically inspect a function and return the keys of its ``return dict(...)``.

    Only resolves the simple ``return dict(k=v, k2=v2, ...)`` shape used by
    ``tui_gateway.server._agent_cbs``. If the shape changes, the test
    surfaces a clear error so the static lock can be updated.
    """
    tree = ast.parse(file_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                    call = sub.value
                    if isinstance(call.func, ast.Name) and call.func.id == "dict":
                        names: list[str] = []
                        for kw in call.keywords:
                            if kw.arg is None:
                                raise AssertionError(
                                    f"{file_path.name}:{func_name} uses **kwargs "
                                    f"in its return dict(...); update this test."
                                )
                            names.append(kw.arg)
                        return names
            raise AssertionError(
                f"{file_path.name}:{func_name} return shape changed; "
                f"expected ``return dict(k=v, ...)``."
            )
    raise AssertionError(f"{func_name} not found in {file_path}")


def _find_aiagent_call_kwargs() -> list[str]:
    """Parse cron/scheduler.py and return every kwarg name passed to AIAgent().

    Handles both explicit kwargs and known ``**splat`` dicts whose
    contents are resolvable from KNOWN_SPLAT_SOURCES.
    """
    source = _scheduler_path().read_text()
    tree = ast.parse(source)

    call_kwargs: list[str] = []
    found_any = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "AIAgent":
            found_any = True
            for kw in node.keywords:
                if kw.arg is not None:
                    call_kwargs.append(kw.arg)
                    continue
                # ``**splat`` — try to resolve against KNOWN_SPLAT_SOURCES.
                if not isinstance(kw.value, ast.Name):
                    raise AssertionError(
                        "cron/scheduler.py: AIAgent() **splat is not a "
                        "simple Name; update KNOWN_SPLAT_SOURCES."
                    )
                splat_name = kw.value.id
                if splat_name not in KNOWN_SPLAT_SOURCES:
                    raise AssertionError(
                        f"cron/scheduler.py: AIAgent() splats **{splat_name} "
                        f"but it isn't in KNOWN_SPLAT_SOURCES — add an entry "
                        f"so this lock can resolve it."
                    )
                rel_path, fn_name = KNOWN_SPLAT_SOURCES[splat_name]
                call_kwargs.extend(
                    _kwarg_names_of_returned_dict(CLI_ROOT / rel_path, fn_name)
                )

    if not found_any:
        raise AssertionError(
            "Expected at least one AIAgent(...) call in cron/scheduler.py "
            "but found none. If construction moved, update this test."
        )
    return call_kwargs


def test_every_cron_kwarg_is_accepted_by_aiagent_init():
    """Every kwarg cron passes must appear in AIAgent.__init__'s signature.

    Catches the kwarg-drift bug class — the next time someone adds a
    kwarg to the cron AIAgent() call without adding it to
    ``AIAgent.__init__``, this test fails instead of a 2am job.
    """
    from run_agent import AIAgent

    sig = inspect.signature(AIAgent.__init__)
    accepted = set(sig.parameters.keys())
    # If AIAgent.__init__ ever grows a ``**kwargs`` catch-all, this lock
    # becomes a no-op. Detect that and fail with a clear message.
    for name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            pytest.fail(
                "AIAgent.__init__ now accepts **kwargs — this kwarg lock "
                "no longer protects against drift. Either remove the "
                "**kwargs catch-all or replace this test with a stricter "
                "schema check."
            )

    passed = _find_aiagent_call_kwargs()
    missing = sorted(set(passed) - accepted)
    assert not missing, (
        f"cron/scheduler.py passes kwargs to AIAgent() that are NOT in "
        f"AIAgent.__init__'s signature: {missing}. "
        f"Either add them to AIAgent.__init__ or remove them from the "
        f"scheduler. Drift like this caused the 2026-05-25 cron outage."
    )


def test_aiagent_init_can_bind_a_full_cron_kwarg_set():
    """Sanity-check: AIAgent.__init__ can be bound with the cron kwargs.

    Doesn't actually construct the agent (that would hit the network and
    file system). Uses inspect.Signature.bind_partial which raises
    TypeError on the first unknown kwarg, mirroring the runtime crash.
    """
    from run_agent import AIAgent

    sig = inspect.signature(AIAgent.__init__)
    passed = _find_aiagent_call_kwargs()
    # Build a dict of kwarg_name -> sentinel value. We don't care about
    # type correctness here — just that the *names* are accepted.
    sentinel = object()
    fake_kwargs = {name: sentinel for name in passed}
    try:
        sig.bind_partial(None, **fake_kwargs)  # ``None`` stands in for ``self``
    except TypeError as exc:
        pytest.fail(f"AIAgent.__init__ rejected a cron kwarg: {exc}")
