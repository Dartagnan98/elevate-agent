"""Small benchmark harness for Elevate holographic memory recall.

This is intentionally local and read-only. It exercises the same provider/store
paths used by fact_store so we can measure recall latency, duplicate injection
risk, and hit counts without mutating ad/Supabase/business systems.
"""

from __future__ import annotations

import json
from typing import Any


def run_holographic_memory_benchmark(
    *,
    config: dict | None = None,
    queries: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Run the local holographic memory benchmark and return JSON-safe stats."""
    if isinstance(config, dict):
        runtime_config = config
    else:
        try:
            from elevate_cli.config import load_config

            loaded = load_config()
            runtime_config = loaded if isinstance(loaded, dict) else {}
        except Exception:
            runtime_config = {}
    plugins = runtime_config.get("plugins") if isinstance(runtime_config, dict) else {}
    plugin_config = {}
    if isinstance(plugins, dict):
        plugin_config = plugins.get("elevate-memory-store") or {}
    if not isinstance(plugin_config, dict):
        plugin_config = {}
    plugin_config = dict(plugin_config)
    if not plugin_config.get("db_path"):
        plugin_config["db_path"] = "~/.elevate/memory_store.db"

    from plugins.memory.holographic import HolographicMemoryProvider

    provider = HolographicMemoryProvider(config=plugin_config)
    provider.initialize("memory-benchmark")
    try:
        store = provider._store
        result = store.memory_benchmark(queries=queries, limit=limit)
        result["ran"] = True
        return result
    finally:
        provider.shutdown()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run Elevate holographic memory benchmark")
    parser.add_argument("queries", nargs="*", help="Queries to benchmark. Defaults to built-in smoke queries.")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_holographic_memory_benchmark(queries=args.queries, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
