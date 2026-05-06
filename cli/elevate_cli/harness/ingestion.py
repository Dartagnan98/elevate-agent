from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import SourceSnapshot, new_id, utc_now_iso
from .redaction import sanitize_browser_snapshot
from .store import HarnessStore


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_browser_page(
    *,
    store: HarnessStore,
    run_id: str | None,
    page: dict[str, Any],
    output_root: str | Path,
    account_context: str | None = None,
    jurisdiction: str | None = None,
) -> SourceSnapshot:
    cleaned = sanitize_browser_snapshot(page)
    text = str(cleaned.get("text") or "")
    title = str(cleaned.get("title") or cleaned.get("url") or "Untitled")
    source_uri = str(cleaned.get("url") or cleaned.get("source_uri") or "")
    digest = content_hash(source_uri + "\n" + title + "\n" + text)
    snapshot_id = new_id("src")
    root = Path(output_root).expanduser() / snapshot_id
    root.mkdir(parents=True, exist_ok=True)

    raw_text_path = root / "raw.txt"
    markdown_path = root / "page.md"
    json_path = root / "metadata.json"

    raw_text_path.write_text(text, encoding="utf-8")
    markdown_path.write_text(
        f"# {title}\n\nSource: {source_uri}\nCaptured: {utc_now_iso()}\n\n{text}\n\n## Links\n"
        + "\n".join(
            f"- [{(link.get('text') or link.get('href') or '').replace(chr(10), ' ')[:180]}]({link.get('href', '')})"
            for link in cleaned.get("links", [])
            if isinstance(link, dict)
        )
        + "\n",
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = SourceSnapshot(
        id=snapshot_id,
        run_id=run_id,
        source_type="browser_page",
        source_uri=source_uri,
        title=title,
        account_context=account_context,
        jurisdiction=jurisdiction,
        raw_text_path=str(raw_text_path),
        markdown_path=str(markdown_path),
        json_path=str(json_path),
        content_hash=digest,
        captured_at=utc_now_iso(),
        metadata={"link_count": len(cleaned.get("links", [])), "text_length": len(text)},
    )
    store.insert_source_snapshot(snapshot)
    return snapshot
