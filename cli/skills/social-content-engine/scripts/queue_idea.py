"""Queue one social post idea into the approval queue.

The agent (running this skill weekly) calls this script once per idea after
composing the hook + outline. The script resolves the tools root the same way
the rest of Elevate does (env > config > detected skyleigh-tools > default)
and appends a task to ``data/sources/social/tasks.jsonl`` with shape that the
``/social-media`` page already understands.

Usage:

    queue_idea.py \\
      --platform instagram \\
      --format reel \\
      --hook "5 mistakes Calgary buyers make in 2026" \\
      --concept "Listicle reel walking through the 5 things..." \\
      --best-post-time "Tuesday 7pm Pacific" \\
      --grounded-in-metric "ig_post_3 engagement_rate=0.154" \\
      --grounded-in-trend "Buyer fatigue uptick in Alberta search trends" \\
      --grounded-in-signal "3 inbound DMs in last 7d asking about first-time buyer pitfalls" \\
      --reasoning "Top-performing reel format + live signal of buyer questions"

The task carries ``approval_required: true``. The user approves on
``/social-media`` to schedule via Ayrshare.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make the elevate_cli package importable so we can reuse the tools-root resolver
_REPO_CLI = Path(__file__).resolve().parents[3]
if str(_REPO_CLI) not in sys.path:
    sys.path.insert(0, str(_REPO_CLI))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_source_dir() -> Path:
    """Mirror source_connectors._candidate_tools_root, fail soft to ELEVATE_HOME."""
    try:
        from elevate_cli.source_connectors import get_source_root_info  # type: ignore
        info = get_source_root_info()
        source_root = Path(info.get("sourceRoot") or "")
        if source_root.parts:
            return source_root / "social"
    except Exception:
        pass
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    skyleigh = elevate_home / "tmp" / "skyleigh-tools" / "data" / "sources" / "social"
    if skyleigh.parent.parent.exists():
        return skyleigh
    return elevate_home / "tools" / "data" / "sources" / "social"


def queue(
    *,
    platform: str,
    format_: str,
    hook: str,
    concept: str,
    best_post_time: str | None,
    grounded_in_metric: str | None,
    grounded_in_trend: str | None,
    grounded_in_signal: str | None,
    reasoning: str | None,
    outline: list[str] | None = None,
    suggested_assets: list[str] | None = None,
    target_audience: str | None = None,
) -> dict[str, Any]:
    if not (grounded_in_metric or grounded_in_trend or grounded_in_signal):
        raise SystemExit(
            "queue_idea: every idea must cite at least one of metric / trend / signal "
            "(skill rule). Refusing to queue."
        )

    source_dir = _resolve_source_dir()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    now = _now_iso()
    record_id = f"social-idea:{platform}:{int(datetime.now(timezone.utc).timestamp())}:{abs(hash(hook)) % 100000}"

    grounded = {
        k: v for k, v in {
            "metric": grounded_in_metric,
            "trend": grounded_in_trend,
            "signal": grounded_in_signal,
        }.items() if v
    }

    draft_text = "\n\n".join(filter(None, [
        f"Hook: {hook}",
        f"Concept: {concept}",
        ("Outline:\n- " + "\n- ".join(outline)) if outline else None,
        f"Best post time: {best_post_time}" if best_post_time else None,
        f"Target audience: {target_audience}" if target_audience else None,
        f"Why now: {reasoning}" if reasoning else None,
    ]))

    record = {
        "source_id": "social",
        "source_record_id": record_id,
        "display_name": f"Idea: {hook[:80]}",
        "timestamp": now,
        "title": f"[{platform}/{format_.lower()}] {hook[:120]}",
        "status": "open",
        "task_type": "social_post_idea",
        "approval_required": True,
        "owner_agent": "Social Media",
        "summary": (concept or hook)[:500],
        "draft_text": draft_text,
        "platform": platform,
        "format": format_,
        "hook": hook,
        "concept": concept,
        "outline": outline or [],
        "best_post_time": best_post_time,
        "target_audience": target_audience,
        "grounded_in": grounded,
        "reasoning": reasoning,
        "suggested_assets": suggested_assets or [],
        "confidence": 0.85,
        "tags": ["social-idea", platform, format_.lower(), "real-estate"],
        "target_ui_surfaces": ["Social Media", "Approvals"],
    }

    tasks_path = source_dir / "tasks.jsonl"
    with tasks_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "queued": True,
        "tasks_path": str(tasks_path),
        "source_record_id": record_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue a social post idea for human approval.")
    parser.add_argument("--platform", required=True, choices=["instagram", "tiktok", "youtube", "facebook", "linkedin"])
    parser.add_argument("--format", required=True, dest="format_", choices=["reel", "short", "feed", "carousel", "story", "video", "text"])
    parser.add_argument("--hook", required=True, help="One-line opening hook (≤120 chars)")
    parser.add_argument("--concept", required=True, help="2-3 sentence summary of the post")
    parser.add_argument("--outline", nargs="*", default=None, help="Bullet points (optional)")
    parser.add_argument("--best-post-time", default=None, help="e.g. 'Tuesday 7pm Pacific'")
    parser.add_argument("--target-audience", default=None)
    parser.add_argument("--grounded-in-metric", default=None, help="Required if no trend/signal")
    parser.add_argument("--grounded-in-trend", default=None, help="Required if no metric/signal")
    parser.add_argument("--grounded-in-signal", default=None, help="Required if no metric/trend")
    parser.add_argument("--reasoning", default=None, help="Why this will land")
    parser.add_argument("--suggested-assets", nargs="*", default=None, help="Asset prompts/refs")
    args = parser.parse_args(argv)

    result = queue(
        platform=args.platform,
        format_=args.format_,
        hook=args.hook,
        concept=args.concept,
        best_post_time=args.best_post_time,
        grounded_in_metric=args.grounded_in_metric,
        grounded_in_trend=args.grounded_in_trend,
        grounded_in_signal=args.grounded_in_signal,
        reasoning=args.reasoning,
        outline=args.outline,
        suggested_assets=args.suggested_assets,
        target_audience=args.target_audience,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
