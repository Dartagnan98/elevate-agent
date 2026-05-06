from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

RunStatus = Literal["pending", "running", "paused", "blocked", "failed", "completed", "cancelled"]
HarnessMode = Literal["read_only", "read_download", "controlled_navigation", "action"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(slots=True)
class HarnessRun:
    id: str
    name: str
    run_type: str
    status: RunStatus
    account_context: str | None = None
    jurisdiction: str | None = None
    mode: HarnessMode = "read_only"
    allowed_domains: list[str] = field(default_factory=list)
    input: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    resume_cursor: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None


@dataclass(slots=True)
class HarnessEvent:
    run_id: str
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SourceSnapshot:
    id: str
    source_type: str
    source_uri: str
    content_hash: str
    captured_at: str
    run_id: str | None = None
    title: str | None = None
    account_context: str | None = None
    jurisdiction: str | None = None
    raw_text_path: str | None = None
    markdown_path: str | None = None
    json_path: str | None = None
    file_path: str | None = None
    trust_level: str = "source"
    metadata: dict[str, Any] = field(default_factory=dict)
