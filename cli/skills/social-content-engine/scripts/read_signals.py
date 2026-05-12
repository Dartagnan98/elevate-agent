"""Pull recent inbox + CRM signals as fuel for the idea generator.

The skill workflow runs this BEFORE asking the LLM to compose ideas. The LLM
gets back: (a) the most-asked questions in the agent's inbox over the last
30 days, (b) recent lead events with context (new lead, stage change, hot
score), and (c) account-level signals (follower spikes, follow drops).

The point: ideas should answer real client questions, not invented ones.

Output (JSON to stdout):
{
  "lookback_days": 30,
  "inbound_questions": [
    {"text": "...", "channel": "sms|email|social", "from": "Anon", "ts": "..."}
  ],
  "lead_events": [
    {"type": "...", "summary": "...", "ts": "...", "score": 12}
  ],
  "hot_topics": ["first-time buyer", "condo docs", "rate hold"],
  "sources_scanned": ["sms", "social", "crm", ...]
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_CLI = Path(__file__).resolve().parents[3]
if str(_REPO_CLI) not in sys.path:
    sys.path.insert(0, str(_REPO_CLI))

try:
    from elevate_cli.source_connectors import _is_automated_sender_record  # type: ignore
except Exception:  # pragma: no cover — fallback for when module import fails
    def _is_automated_sender_record(record):  # type: ignore
        return False


def _resolve_source_root() -> Path:
    try:
        from elevate_cli.source_connectors import get_source_root_info  # type: ignore
        info = get_source_root_info()
        root = Path(info.get("sourceRoot") or "")
        if root.parts:
            return root
    except Exception:
        pass
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    client_tools = elevate_home / "tmp" / "client-tools" / "data" / "sources"
    if client_tools.exists():
        return client_tools
    return elevate_home / "tools" / "data" / "sources"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# Real-estate keyword universe for hot-topic extraction. Intentionally narrow —
# the goal is "what's the audience asking about" not full topic modeling.
TOPIC_PATTERNS = {
    "first-time-buyer": r"\b(first[- ]time|new buyer|never bought)\b",
    "pre-approval": r"\b(pre[- ]approval|preapproval|pre[- ]qualified|mortgage application)\b",
    "rate-hold": r"\b(rate hold|interest rate|fixed rate|variable rate|prime|bank rate)\b",
    "condo-docs": r"\b(condo (document|doc|fee|reserve|estoppel)|strata)\b",
    "inspection": r"\b(home inspection|inspector|inspection clause)\b",
    "downpayment": r"\b(down payment|downpayment|deposit|5%|10%|20%)\b",
    "closing-costs": r"\b(closing cost|land transfer|legal fee|adjustment)\b",
    "investment-property": r"\b(rental property|investment|cap rate|cash flow|airbnb)\b",
    "selling-tips": r"\b(stage|staging|list price|sale price|sell my home|when to sell)\b",
    "market-trends": r"\b(market (update|trend|forecast)|housing market|home prices?)\b",
    "showing-request": r"\b(viewing|book a tour|showing|see the (house|home|listing|property))\b",
    "mortgage-renewal": r"\b(renewal|renew(ing)? my mortgage|switch lender)\b",
    "new-construction": r"\b(new build|new construction|presale|preconstruction)\b",
    "neighbourhood": r"\b(neighbourhood|neighborhood|school district|safe area)\b",
}


def _extract_topics(text: str) -> list[str]:
    text_l = (text or "").lower()
    hits = []
    for topic, pattern in TOPIC_PATTERNS.items():
        if re.search(pattern, text_l):
            hits.append(topic)
    return hits


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    if re.match(r"^(how|what|when|where|why|can|could|would|do you|is it|are there|should i|what's|how's|when's)\b", t.lower()):
        return True
    return False


def collect(*, lookback_days: int = 30, max_questions: int = 30, max_events: int = 50) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    source_root = _resolve_source_root()

    inbound_questions: list[dict[str, Any]] = []
    lead_events: list[dict[str, Any]] = []
    topic_counter: Counter[str] = Counter()
    sources_scanned: list[str] = []

    if not source_root.exists():
        return {
            "lookback_days": lookback_days,
            "inbound_questions": [],
            "lead_events": [],
            "hot_topics": [],
            "sources_scanned": [],
            "note": f"No source root at {source_root}",
        }

    for source_dir in sorted(source_root.iterdir()):
        if not source_dir.is_dir():
            continue
        sources_scanned.append(source_dir.name)

        # Messages — pull inbound, score for question-shape, collect topics.
        # Skip automated/marketing senders so the LLM sees real client questions.
        msg_path = source_dir / "messages.jsonl"
        for row in _read_jsonl(msg_path):
            ts = _parse_iso(row.get("timestamp") or row.get("ts"))
            if not ts or ts < cutoff:
                continue
            direction = (row.get("direction") or "").lower()
            if direction not in ("inbound", "in", "incoming", ""):
                # If direction unknown, only include if outbound flag false
                if row.get("is_outbound") or row.get("outbound"):
                    continue
            if _is_automated_sender_record(row):
                continue
            text = (row.get("text") or row.get("body") or row.get("summary") or "").strip()
            if not text:
                continue
            topics = _extract_topics(text)
            for t in topics:
                topic_counter[t] += 1
            if _looks_like_question(text):
                inbound_questions.append({
                    "text": text[:300],
                    "channel": source_dir.name,
                    "from": row.get("display_name") or row.get("from") or "unknown",
                    "ts": ts.isoformat(timespec="seconds"),
                    "topics": topics,
                })

        # Lead events — pull all in window
        events_path = source_dir / "lead-events.jsonl"
        for row in _read_jsonl(events_path):
            ts = _parse_iso(row.get("timestamp") or row.get("ts"))
            if not ts or ts < cutoff:
                continue
            text = (row.get("title") or row.get("summary") or row.get("text") or "").strip()
            for t in _extract_topics(text):
                topic_counter[t] += 1
            lead_events.append({
                "type": row.get("type") or "lead_event",
                "summary": text[:240],
                "channel": source_dir.name,
                "ts": ts.isoformat(timespec="seconds"),
                "score": row.get("heat_score") or row.get("score"),
            })

    # Newest first, capped
    inbound_questions.sort(key=lambda x: x["ts"], reverse=True)
    lead_events.sort(key=lambda x: x["ts"], reverse=True)

    return {
        "lookback_days": lookback_days,
        "inbound_questions": inbound_questions[:max_questions],
        "lead_events": lead_events[:max_events],
        "hot_topics": [t for t, _ in topic_counter.most_common(8)],
        "topic_counts": dict(topic_counter.most_common(20)),
        "sources_scanned": sources_scanned,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--max-questions", type=int, default=30)
    parser.add_argument("--max-events", type=int, default=50)
    args = parser.parse_args(argv)

    payload = collect(
        lookback_days=args.lookback,
        max_questions=args.max_questions,
        max_events=args.max_events,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
