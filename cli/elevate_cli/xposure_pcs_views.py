"""xposure-pcs-views source connector.

Per-listing engagement scrape. Depends on the ``xposure-pcs`` connector
having populated ``pcs_buyers`` first. For each buyer with a recent
search activity, drives the Playwright scraper to drill into their
Xposure profile and capture every matched listing along with view count,
last viewed date, and engagement state ("viewed" / "new" / "pc" / "older").

Pipeline:

  1. Pick scrape targets: contacts with ``activity_tier`` in ('active','warm')
     OR ``last_search_at`` within the last 90 days. Limit per-run via
     ``ELEVATE_PCS_VIEWS_BATCH`` (default 80) to keep wall-clock under
     ~30 minutes.
  2. Drive the scrape via the Elevate oneshot agent using the built-in
     ``browser_use`` + ``bash`` toolsets. The agent prompt walks Xposure
     dynamically (contact-detail-link → ManageClients → manageResults
     (searchId, '1') → Client View) and appends one JSONL line per
     (buyer, search) pair. A Gmail MFA poller thread (shared with the
     xposure-pcs connector) writes the 6-digit code to ``/tmp/xposure-mfa.txt``
     for the agent to read.
  3. Read the resulting JSONL at
     ``~/.elevate/snapshots/pcs-listing-views.jsonl`` and upsert into
     ``pcs_listing_views``. Also patch the parent ``pcs_buyers`` row with
     summary counts (results/favorites/removed/queue) and
     ``last_client_access``, and store ``contacts.xposure_contact_id`` so
     subsequent runs can re-locate the buyer without an email search.

The upsert key is (contact_id, search_id, mls_id). Each scrape OVERWRITES
the row for that key — we don't keep a history table here. Diff lives in
the JSONL snapshot (append-only) so the activity flagger cron can compare
the latest scrape against the previous one and fire outreach triggers.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.data.connection import connect

logger = logging.getLogger(__name__)

SOURCE_ID = "xposure-pcs-views"

_DEFAULT_LOOKBACK_DAYS = 90
_DEFAULT_BATCH = int(os.getenv("ELEVATE_PCS_VIEWS_BATCH", "80") or "80")
_SNAPSHOT = Path(os.path.expanduser(
    "~/.elevate/snapshots/pcs-listing-views.jsonl"
))

# Side-channel file the Gmail MFA poller writes into. Shared with the
# xposure-pcs connector so a single MFA round-trip can satisfy both
# scrapers if they run back-to-back.
_MFA_FILE = "/tmp/xposure-mfa.txt"


def _write_target_email_file(emails: list[str]) -> Path:
    target_dir = Path(os.path.expanduser("~/.elevate/tmp/xposure-pcs-views"))
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"target-emails-{stamp}.txt"
    clean = [email.strip().lower() for email in emails if email.strip()]
    path.write_text("\n".join(clean) + ("\n" if clean else ""), encoding="utf-8")
    return path


def _local_cdp_writer_command(target_file: Path) -> str:
    from elevate_cli.xposure_pcs_connector import _local_python_prefix

    return (
        f"{_local_python_prefix()} -m elevate_cli.xposure_pcs_views_cdp_writer "
        f"--emails-file {shlex.quote(str(target_file))} "
        f"--snapshot {shlex.quote(str(_SNAPSHOT))}"
    )


# ─── Target selection ────────────────────────────────────────────────


def _select_targets(conn, limit: int, lookback_days: int) -> list[dict[str, Any]]:
    """Pick buyers whose listing views are worth (re-)scraping.

    Ordering:
      1. ``activity_tier='active'`` first (recent + high volume),
      2. ``activity_tier='warm'`` next,
      3. then anyone else with ``last_search_at`` inside the lookback.

    Within each tier we age-rank by ``views_scraped_at`` ASC NULLS FIRST
    so the freshest buyers re-scrape last and a new buyer always scrapes
    first. Stop at ``limit``.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = conn.execute(
        """
        SELECT c.id,
               c.primary_email,
               c.display_name,
               c.activity_tier,
               c.last_search_at,
               c.xposure_contact_id,
               p.views_scraped_at
          FROM contacts c
          JOIN pcs_buyers p ON p.contact_id = c.id
         WHERE c.primary_email IS NOT NULL
           AND c.primary_email <> ''
           AND (
                 c.activity_tier IN ('active', 'warm')
              OR c.last_search_at >= ?
           )
         ORDER BY
           CASE c.activity_tier
             WHEN 'active' THEN 0
             WHEN 'warm'   THEN 1
             ELSE 2
           END,
           p.views_scraped_at ASC NULLS FIRST,
           c.last_search_at DESC NULLS LAST
         LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Scraper invocation ──────────────────────────────────────────────


_AGENT_PROMPT_TEMPLATE = """\
You are an automation agent driving the AOIR Xposure realtor portal via \
the browser_use toolset. Your job is to walk a list of buyer emails, open \
each buyer's Client View one-way mirror per saved search, and append a \
JSONL record per buyer-per-search to disk.

CREDENTIALS (already in your environment)
- Login URL: https://iam.interiorbc.ca/idp/login
- Username env: MLS_USERNAME = "{username}"
- Password env: MLS_PASSWORD = "{password}"

BUYER EMAILS TO SCRAPE (one per line)
{email_list}

OUTPUT
- Append-only JSONL file: {snapshot_path}
- Target email file for the local CDP writer: {target_file}
- DO NOT TRUNCATE this file. Append one line per (buyer_email, search_id) pair.
- Each line shape (NDJSON):
  {{"scraped_at": "<ISO8601>", "buyer_email": "<lowercase>",
   "xposure_contact_id": "<digits>", "search_id": "<digits>",
   "summary": {{"results": <int|null>, "favorites": <int|null>,
                "removed": <int|null>, "queue": <int|null>,
                "total_found": <int|null>, "last_access": "<ISO|null>"}},
   "listings": [
     {{"mls_id": "<digits>", "address": "<str>",
       "major_area": "<str|null>", "minor_area": "<str|null>",
       "list_price_cents": <int|null>, "status": "<str|null>",
       "beds": <int|null>, "baths": <int|null>, "year_built": <int|null>,
       "style": "<str|null>", "property_type": "<str|null>",
       "dom_days": <int|null>, "view_count": <int>,
       "last_viewed_at": "<ISO|null>",
       "view_state": "new|pc|older|viewed|favorite|removed"}}
   ]}}

STEPS
1. browser_navigate to https://iam.interiorbc.ca/idp/login.
2. Use browser_snapshot to get refs, then browser_type the username and \
   password into the matching fields and browser_click the login button.
3. If an MFA / "verification code" prompt appears:
   a. Click the "Email" option if offered.
   b. Poll the file {mfa_file} for up to 120 seconds via \
      `bash: cat {mfa_file}` — a background process writes the 6-digit \
      code there.
   c. Type the code into the OTP input and submit.
4. Wait until URL contains members.interiorbc.ca, then click the \
   "AOIR Xposure" app tile (text matches /aoir xposure|^xposure$/i). \
   If the SAML hop stalls, browser_navigate directly to \
   https://xposureapp.com.
5. After AOIR Xposure opens, go to the Clients / Contacts page so the visible \
   browser shows the `#pcs-contacts-table` DataTable. You may use a tiny \
   browser_console check to confirm the table exists, but DO NOT return the \
   full buyer/search/listing records through browser_console or browser_cdp.
6. Run this exact local CDP writer command with bash:
   `{writer_command}`
   This command attaches to the same visible browser on CDP port 9222, reads \
   the Xposure DataTables model directly, fetches each Client View with \
   `POST https://interiorrealtors.xposureapp.com/pcs/air/DoLogin`, parses the \
   HTML with `DOMParser`, iterates `.listing-container` cards, and appends the \
   JSONL records directly to `{snapshot_path}`.
7. Watch the command stdout. It prints compact JSON with `records_appended`, \
   `contacts_matched`, `searches_seen`, and `listings_seen`. If it says the \
   contacts table is not ready, navigate back to \
   https://interiorrealtors.xposureapp.com/portal/air/Contacts, wait until \
   the table renders, and run the same command once more.
8. DO NOT create `/tmp/xposure_append_server.py`; DO NOT start a localhost \
   append server; DO NOT fetch `127.0.0.1` or `localhost` from the Xposure \
   page; DO NOT fetch `/static/responsive/js/pcs-contacts.js`; DO NOT dump \
   full Client View HTML or full listing JSON into the chat.
9. If this prompt includes a VISIBLE SESSION CONTINUATION section below, follow \
   that section after appending the JSONL. Otherwise, when ALL buyers have \
   been processed, reply with EXACTLY: `DONE rows=<N>` where N is the number \
   of JSONL lines you appended on this run.

CONSTRAINTS
- Never truncate the snapshot file. Only append.
- Use the local CDP writer command for heavy DOM extraction and JSONL writes; \
  do not pipe bulk records through the model/chat transcript.
- Prefer the deterministic DataTables + POST + DOMParser path above. If it \
  works for one buyer, continue with it for the whole batch instead of \
  inspecting scripts or trying alternate navigation paths.
- If a buyer is missing from the Clients table, skip them and move on.
- If a search opens to an empty Client View, still write a record with \
  `listings: []` and whatever summary you can extract.
- Dismiss modals via JS (`$('.modal-backdrop').remove(); $('.btn-close').click();`).
- If login fails or MFA never arrives, reply `FAILED <one-line reason>`.
- DO NOT publish anything, modify listings, or push leads anywhere. \
  Read-only scrape of buyer engagement state.
"""


def _candidate_emails_for_prompt(config: dict[str, Any] | None = None) -> list[str]:
    cfg = config or {}
    batch = int(cfg.get("batch") or _DEFAULT_BATCH)
    lookback = int(cfg.get("lookback_days") or _DEFAULT_LOOKBACK_DAYS)
    try:
        with connect() as conn:
            targets = _select_targets(conn, limit=batch, lookback_days=lookback)
    except Exception as exc:
        logger.warning("xposure-pcs-views: could not select prompt targets: %s", exc)
        return []
    return [str(t["primary_email"]).strip() for t in targets if t.get("primary_email")]


def build_agent_session_prompt(
    config: dict[str, Any] | None = None,
    *,
    target_emails: list[str] | None = None,
) -> str:
    """Render the executable prompt used by visible dashboard chat runs."""
    from elevate_cli.xposure_pcs_connector import (
        _load_premium_env,
        _local_counts_command,
        _local_sync_command,
    )

    _load_premium_env()
    emails = [
        str(email).strip()
        for email in (target_emails if target_emails is not None else _candidate_emails_for_prompt(config))
        if str(email).strip()
    ]
    email_list = "\n".join(emails) if emails else (
        "NO_ELIGIBLE_BUYERS_FOUND\n"
        "If this is the only line, stop and reply `FAILED no eligible buyers; "
        "run MLS Buyer Searches first or widen the xposure_pcs_views batch/lookback`."
    )
    target_file = _write_target_email_file(emails)
    writer_command = _local_cdp_writer_command(target_file)
    scraper_prompt = _AGENT_PROMPT_TEMPLATE.format(
        username=os.environ.get("MLS_USERNAME", "").strip() or "<missing MLS_USERNAME>",
        password=os.environ.get("MLS_PASSWORD", "").strip() or "<missing MLS_PASSWORD>",
        email_list=email_list,
        snapshot_path=str(_SNAPSHOT),
        target_file=str(target_file),
        writer_command=writer_command,
        mfa_file=_MFA_FILE,
    )
    sync_cmd = _local_sync_command(
        "xposure-pcs-views",
        env_flag="ELEVATE_XPOSURE_VIEWS_SKIP_SCRAPER",
    )
    verify_cmd = _local_counts_command({
        "pcs_listing_views": "SELECT COUNT(*) AS n FROM pcs_listing_views",
        "buyers_enriched": (
            "SELECT COUNT(*) AS n FROM pcs_buyers "
            "WHERE views_scraped_at IS NOT NULL"
        ),
        "contacts_with_xposure_contact_id": (
            "SELECT COUNT(*) AS n FROM contacts "
            "WHERE xposure_contact_id IS NOT NULL"
        ),
    })
    return (
        f"{scraper_prompt}\n"
        "VISIBLE SESSION CONTINUATION\n"
        "10. After appending the per-search Client View JSONL, run this local import command with bash:\n"
        f"   `{sync_cmd}`\n"
        "   This must NOT open the browser again. It reuses the snapshot you just wrote\n"
        "   and imports per-listing views, favorites, removed counts, last client access,\n"
        "   and Xposure contact ids into operational Postgres.\n"
        "11. Verify the Postgres enrichment with bash:\n"
        "   ```bash\n"
        f"{verify_cmd}\n"
        "   ```\n"
        "12. Final reply exactly:\n"
        "   `DONE rows=<appended_rows> listing_views=<pcs_listing_views_count> buyers_enriched=<buyers_with_views_count> xposure_contact_ids=<contacts_with_xposure_contact_id_count>`\n"
        "   If either scrape or import fails, reply `FAILED <one-line reason>`.\n"
        "13. Run this after MLS Buyer Searches and buyer-brief have completed. Do not\n"
        "   run it in parallel with xposure-pcs; both import paths update pcs_buyers.\n"
    )


def _run_scraper(emails: list[str], *, skip: bool, headless: bool = False) -> dict[str, Any]:
    """Drive the per-listing engagement scrape via the Elevate oneshot \
    agent with the browser_use + bash toolsets.

    The previous implementation shelled out to a 500-line Node+Playwright \
    script (``pcs-listing-views-scraper.cjs``). This version delegates to \
    the agent's own browser-use model, sharing the MFA poller side-channel \
    with the xposure-pcs connector.

    Signature kept identical (``emails, skip, headless``) so the rest of \
    the module + tests don't move. Returns \
    ``{ok, skipped, snapshot_count, stdout_tail, stderr_tail}``.

    ``snapshot_count`` is the number of *new* JSONL lines appended to \
    ``_SNAPSHOT`` during this run (computed by diffing pre/post line count).
    """
    if skip:
        return {"ok": True, "skipped": True, "snapshot_count": _count_jsonl_lines(_SNAPSHOT),
                "stdout_tail": "", "stderr_tail": ""}

    if not emails:
        return {"ok": True, "skipped": False, "snapshot_count": 0,
                "stdout_tail": "no emails to scrape", "stderr_tail": ""}

    # Reuse the env loader + MFA poller from the xposure-pcs connector so
    # both scrapers share creds + the same Gmail polling logic.
    from elevate_cli.xposure_pcs_connector import (
        _load_premium_env,
        _start_mfa_poller,
    )

    _load_premium_env()
    username = os.environ.get("MLS_USERNAME", "").strip()
    password = os.environ.get("MLS_PASSWORD", "").strip()
    if not username or not password:
        return {
            "ok": False, "skipped": False,
            "error": "MLS_USERNAME / MLS_PASSWORD must be set",
            "snapshot_count": 0, "stdout_tail": "", "stderr_tail": "",
        }

    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    pre_lines = _count_jsonl_lines(_SNAPSHOT)

    target_file = _write_target_email_file(emails)
    prompt = _AGENT_PROMPT_TEMPLATE.format(
        username=username,
        password=password,
        email_list="\n".join(emails),
        snapshot_path=str(_SNAPSHOT),
        target_file=str(target_file),
        writer_command=_local_cdp_writer_command(target_file),
        mfa_file=_MFA_FILE,
    )

    # Cap MFA polling inside the agent run window. Per-buyer wall-clock is
    # ~30s warm, so 80 buyers ~40min — give the poller 18min, matching the
    # xposure-pcs connector's window.
    poller_deadline = time.time() + 60 * 18
    stop_poller = _start_mfa_poller(poller_deadline)

    try:
        from elevate_cli.oneshot import _run_agent
    except Exception as exc:  # pragma: no cover (import time only)
        stop_poller.set()
        return {
            "ok": False, "skipped": False,
            "error": f"could not import oneshot agent runner: {exc}",
            "snapshot_count": 0, "stdout_tail": "", "stderr_tail": "",
        }

    response = ""
    error: str | None = None
    try:
        response = _run_agent(
            prompt,
            toolsets=["browser", "bash"],
            use_config_toolsets=False,
        )
    except Exception as exc:
        error = f"oneshot agent raised: {exc}"
    finally:
        stop_poller.set()

    post_lines = _count_jsonl_lines(_SNAPSHOT)
    snapshot_count = max(0, post_lines - pre_lines)
    response_tail = (response or "")[-1000:]

    if error:
        return {
            "ok": False, "skipped": False, "error": error,
            "snapshot_count": snapshot_count,
            "stdout_tail": response_tail, "stderr_tail": "",
        }

    if response_tail.strip().startswith("FAILED"):
        return {
            "ok": False, "skipped": False,
            "error": response_tail.strip()[:300],
            "snapshot_count": snapshot_count,
            "stdout_tail": response_tail, "stderr_tail": "",
        }

    return {
        "ok": snapshot_count > 0 or response_tail.strip().startswith("DONE"),
        "skipped": False,
        "returncode": 0,
        "snapshot_count": snapshot_count,
        "stdout_tail": response_tail,
        "stderr_tail": "",
    }


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open() as fh:
        return sum(1 for _ in fh)


# ─── Snapshot ingest ─────────────────────────────────────────────────


def _read_recent_records(snapshot: Path, since_count: int) -> list[dict[str, Any]]:
    """Return the JSONL records appended on this run (last N lines)."""
    if not snapshot.exists() or since_count <= 0:
        return []
    with snapshot.open() as fh:
        all_lines = fh.readlines()
    tail = all_lines[-since_count:]
    out: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _resolve_contact_id(conn, email: str | None) -> str | None:
    if not email:
        return None
    row = conn.execute(
        "SELECT id FROM contacts WHERE LOWER(primary_email) = LOWER(?) LIMIT 1",
        (email,),
    ).fetchone()
    return row["id"] if row else None


def _upsert_listing_views(conn, contact_id: str, search_id: str,
                          listings: list[dict[str, Any]]) -> int:
    """Replace this buyer's listing-view rows for the given search.

    Snapshot semantics: each scrape is treated as the new truth for
    (contact_id, search_id). Listings not in the new payload are aged
    out by setting view_state='stale'. (We don't delete — preserves a
    soft history for the activity flagger.)
    """
    if not listings:
        return 0
    incoming_mls = {L.get("mls_id") for L in listings if L.get("mls_id")}
    if incoming_mls:
        # Mark anything we no longer see as 'stale'
        conn.execute(
            f"""
            UPDATE pcs_listing_views
               SET view_state = 'stale',
                   snapshot_at = NOW()
             WHERE contact_id = ?
               AND search_id  = ?
               AND mls_id NOT IN ({','.join(['?'] * len(incoming_mls))})
            """,
            (contact_id, search_id, *list(incoming_mls)),
        )

    written = 0
    for L in listings:
        mls_id = L.get("mls_id")
        if not mls_id:
            continue
        conn.execute(
            """
            INSERT INTO pcs_listing_views (
                contact_id, search_id, mls_id,
                address, major_area, minor_area,
                list_price_cents, status,
                beds, baths, year_built, style, property_type, dom_days,
                view_count, last_viewed_at, view_state, snapshot_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
            ON CONFLICT (contact_id, search_id, mls_id) DO UPDATE SET
                address          = excluded.address,
                major_area       = excluded.major_area,
                minor_area       = excluded.minor_area,
                list_price_cents = excluded.list_price_cents,
                status           = excluded.status,
                beds             = excluded.beds,
                baths            = excluded.baths,
                year_built       = excluded.year_built,
                style            = excluded.style,
                property_type    = excluded.property_type,
                dom_days         = excluded.dom_days,
                view_count       = excluded.view_count,
                last_viewed_at   = excluded.last_viewed_at,
                view_state       = excluded.view_state,
                snapshot_at      = NOW()
            """,
            (
                contact_id, search_id, mls_id,
                L.get("address"), L.get("major_area"), L.get("minor_area"),
                L.get("list_price_cents"), L.get("status"),
                L.get("beds"), L.get("baths"), L.get("year_built"),
                L.get("style"), L.get("property_type"), L.get("dom_days"),
                L.get("view_count") or 0, L.get("last_viewed_at"),
                L.get("view_state") or "older",
            ),
        )
        written += 1
    return written


def _update_buyer_summary(conn, contact_id: str, *,
                          summary: dict[str, Any] | None,
                          xposure_contact_id: str | None) -> None:
    """Patch the parent pcs_buyers row + contacts.xposure_contact_id.

    Only writes machine fields; never touches operator-edited columns.
    """
    if xposure_contact_id:
        conn.execute(
            """
            UPDATE contacts
               SET xposure_contact_id = ?,
                   updated_at         = NOW()
             WHERE id = ?
               AND (xposure_contact_id IS NULL OR xposure_contact_id <> ?)
            """,
            (xposure_contact_id, contact_id, xposure_contact_id),
        )
    if not summary:
        return
    conn.execute(
        """
        UPDATE pcs_buyers
           SET results_count      = COALESCE(?, results_count),
               favorites_count    = COALESCE(?, favorites_count),
               removed_count      = COALESCE(?, removed_count),
               queue_count        = COALESCE(?, queue_count),
               last_client_access = COALESCE(?, last_client_access),
               views_scraped_at   = NOW()
         WHERE contact_id = ?
        """,
        (
            summary.get("total_found") if summary.get("total_found") is not None
            else summary.get("results"),
            summary.get("favorites"),
            summary.get("removed"),
            summary.get("queue"),
            summary.get("last_access"),
            contact_id,
        ),
    )


def _ingest_records(records: list[dict[str, Any]]) -> dict[str, int]:
    """Apply all records from one scraper run."""
    counts = {"records": 0, "buyers_touched": 0, "listings_upserted": 0,
              "buyers_missing": 0}
    seen_buyers: set[str] = set()
    with connect() as conn:
        for rec in records:
            counts["records"] += 1
            email = rec.get("buyer_email")
            contact_id = _resolve_contact_id(conn, email)
            if not contact_id:
                counts["buyers_missing"] += 1
                logger.warning("xposure-pcs-views: no contact for %s", email)
                continue
            search_id = rec.get("search_id")
            if not search_id:
                continue
            written = _upsert_listing_views(
                conn, contact_id, str(search_id), rec.get("listings") or []
            )
            counts["listings_upserted"] += written
            _update_buyer_summary(
                conn, contact_id,
                summary=rec.get("summary"),
                xposure_contact_id=rec.get("xposure_contact_id"),
            )
            if contact_id not in seen_buyers:
                seen_buyers.add(contact_id)
                counts["buyers_touched"] += 1
    return counts


# ─── Entry point ─────────────────────────────────────────────────────


def run_views_sync(
    config: dict[str, Any] | None = None,
    *,
    skip_scraper: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one full xposure-pcs-views sync.

    config keys (all optional):
      - ``batch``         max buyers to scrape this run (default 80)
      - ``lookback_days`` how recent ``last_search_at`` must be (default 90)
      - ``headless``      run scraper headless (default false — MFA needs
                          visible window for now)
    """
    cfg = config or {}
    batch = int(cfg.get("batch") or _DEFAULT_BATCH)
    lookback = int(cfg.get("lookback_days") or _DEFAULT_LOOKBACK_DAYS)
    headless = bool(cfg.get("headless"))

    started = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        targets = _select_targets(conn, limit=batch, lookback_days=lookback)

    emails = [t["primary_email"] for t in targets if t.get("primary_email")]
    if not emails:
        return {
            "ok": True,
            "source": SOURCE_ID,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "targets": 0,
            "snapshot_count": 0,
            "ingested": {"records": 0, "buyers_touched": 0,
                         "listings_upserted": 0, "buyers_missing": 0},
            "note": "no eligible buyers (none with activity_tier in active/warm "
                    "and no last_search_at inside lookback)",
        }

    scraper = _run_scraper(emails, skip=skip_scraper, headless=headless)
    if not scraper.get("ok"):
        return {
            "ok": False,
            "source": SOURCE_ID,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "targets": len(emails),
            "scraper": scraper,
        }

    new_records = _read_recent_records(_SNAPSHOT, scraper["snapshot_count"])
    if dry_run:
        return {
            "ok": True,
            "source": SOURCE_ID,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "targets": len(emails),
            "snapshot_count": scraper["snapshot_count"],
            "dry_run": True,
            "records_preview": new_records[:3],
        }

    ingested = _ingest_records(new_records)
    return {
        "ok": True,
        "source": SOURCE_ID,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "targets": len(emails),
        "snapshot_count": scraper["snapshot_count"],
        "ingested": ingested,
    }
