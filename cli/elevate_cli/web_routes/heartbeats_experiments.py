"""Experiment summary helpers for heartbeat routes."""

from typing import Any, Dict, List


def experiment_stats(experiments: List[Dict[str, Any]]) -> Dict[str, int]:
    """Per-surface experiment stats, computed at read time."""
    running = sum(1 for e in experiments if e.get("status") == "running")
    proposed = sum(1 for e in experiments if e.get("status") == "proposed")
    completed = sum(1 for e in experiments if e.get("status") == "completed")
    kept = sum(1 for e in experiments if e.get("decision") == "keep")
    discarded = sum(1 for e in experiments if e.get("decision") == "discard")
    decided = kept + discarded
    return {
        "total": len(experiments),
        "running": running,
        "proposed": proposed,
        "completed": completed,
        "kept": kept,
        "discarded": discarded,
        "keepRate": round((kept / decided) * 100) if decided else 0,
    }


def experiment_summary(surfaces: List[Dict[str, Any]]) -> Dict[str, int]:
    """Fleet-wide rollup across all surfaces."""
    kept = sum(s["stats"]["kept"] for s in surfaces)
    discarded = sum(s["stats"]["discarded"] for s in surfaces)
    decided = kept + discarded
    return {
        "surfaces": len(surfaces),
        "cycles": sum(len(s["cycles"]) for s in surfaces),
        "total": sum(s["stats"]["total"] for s in surfaces),
        "running": sum(s["stats"]["running"] for s in surfaces),
        "completed": sum(s["stats"]["completed"] for s in surfaces),
        "kept": kept,
        "discarded": discarded,
        "keepRate": round((kept / decided) * 100) if decided else 0,
    }
