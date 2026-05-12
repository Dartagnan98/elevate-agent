"""Elevate AI action harness.

Small, durable primitives for supervised browser automation, source capture,
checkpointed jobs, and approval-gated actions.
"""

from __future__ import annotations


import importlib.util
from pathlib import Path

from .browser_cdp import BrowserCDPWorker, BrowserTab, BrowserWorkerError
from .browser_use_harness import BrowserUseHarness, BrowserUseHarnessError
from .models import HarnessEvent, HarnessRun, SourceSnapshot, new_id, utc_now_iso
from .store import HarnessStore


def _load_status_harness_module():
    """Load the legacy ``elevate_cli/harness.py`` status helpers.

    The browser-use harness package intentionally owns the public
    ``elevate_cli.harness`` package name now, but older CLI tests and commands
    still import ``build_harness_snapshot`` and ``format_harness_snapshot`` from
    that same namespace.  Loading the sibling module under a private alias keeps
    both APIs available without reintroducing ambiguous imports.
    """
    module_path = Path(__file__).resolve().parent.parent / "harness.py"
    spec = importlib.util.spec_from_file_location(
        "elevate_cli._harness_status", module_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Cannot load harness status helpers from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_status_harness = _load_status_harness_module()
build_harness_snapshot = _status_harness.build_harness_snapshot
format_harness_snapshot = _status_harness.format_harness_snapshot

__all__ = [
    "BrowserCDPWorker",
    "BrowserTab",
    "BrowserUseHarness",
    "BrowserUseHarnessError",
    "BrowserWorkerError",
    "build_harness_snapshot",
    "format_harness_snapshot",
    "HarnessEvent",
    "HarnessRun",
    "HarnessStore",
    "SourceSnapshot",
    "new_id",
    "utc_now_iso",
]
