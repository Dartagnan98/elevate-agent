from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .browser_cdp import BrowserCDPWorker
from .browser_use_harness import BrowserUseHarness
from .ingestion import ingest_browser_page
from .models import HarnessRun, new_id
from .store import HarnessStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight Elevate browser worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--allow", action="append", default=[], help="Allowed domain; can repeat")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tabs", help="List CDP tabs")
    sub.add_parser("page-info", help="Print upstream browser-use/browser-harness page_info()")

    extract = sub.add_parser("extract", help="Extract a current tab and optionally save a source snapshot")
    extract.add_argument("--url-contains", default=None)
    extract.add_argument("--state-db", default=None)
    extract.add_argument("--out", default=None)
    extract.add_argument("--account-context", default=None)
    extract.add_argument("--jurisdiction", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = BrowserCDPWorker(host=args.host, port=args.port, allowed_domains=args.allow)

    if args.command == "tabs":
        print(json.dumps([asdict(tab) for tab in worker.list_tabs()], indent=2))
        return 0

    if args.command == "page-info":
        harness = BrowserUseHarness(cdp_url=f"http://{args.host}:{args.port}")
        print(json.dumps(harness.page_info(), indent=2))
        return 0

    if args.command == "extract":
        tab = worker.select_tab(args.url_contains)
        if tab is None:
            raise SystemExit("No matching browser tab found")
        page = worker.extract_tab(tab)
        if args.state_db and args.out:
            store = HarnessStore(args.state_db)
            store.migrate()
            run = HarnessRun(id=new_id("run"), name="Browser extract", run_type="browser_extract", status="completed", allowed_domains=args.allow)
            store.upsert_run(run)
            snapshot = ingest_browser_page(
                store=store,
                run_id=run.id,
                page=page,
                output_root=Path(args.out),
                account_context=args.account_context,
                jurisdiction=args.jurisdiction,
            )
            print(json.dumps({"run_id": run.id, "snapshot_id": snapshot.id, "markdown_path": snapshot.markdown_path}, indent=2))
        else:
            print(json.dumps(page, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
