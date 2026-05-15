"""Importing this module populates the adapter registry with every
implementation currently shipped. The base module imports this lazily
so :func:`elevate_cli.crm_adapters.get_adapter` can resolve any
provider without forcing every adapter into memory at app startup.

Each adapter module is responsible for calling
:func:`register_adapter` at module scope.

Order doesn't matter — the registry is a flat dict keyed on provider
slug.
"""

from __future__ import annotations

# Adapters self-register at import time. Failures in one provider's
# import (e.g. missing optional dep) must not break the others, so each
# import is guarded.
def _safe_import(module: str) -> None:
    try:
        __import__(module)
    except Exception:  # noqa: BLE001
        # Surface in logs, never crash the cron. Operators see "CRM
        # not supported" rather than an opaque ImportError.
        import logging

        logging.getLogger(__name__).exception("Failed to load adapter %s", module)


# Each line below is a TODO until the matching adapter file lands.
# Uncomment as adapters are ported in.
# _safe_import("elevate_cli.crm_adapters.lofty")
# _safe_import("elevate_cli.crm_adapters.fub")
# _safe_import("elevate_cli.crm_adapters.sierra")
# _safe_import("elevate_cli.crm_adapters.brivity")
# _safe_import("elevate_cli.crm_adapters.boldtrail")
