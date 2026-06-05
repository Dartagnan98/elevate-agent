"""xposure-pcs source connector.

Pulls MLS private-search (PCS) buyer data from the Xposure realtor portal,
converts it into Elevate's canonical JSONL shape, and runs the same
identity-first writethrough that Apple Messages and CRM already use.

Pipeline:

  1. Run the scraper (an Elevate oneshot agent driving the portal via the
     built-in ``browser_use`` toolset, with a parallel Gmail-polling thread
     surfacing the MFA code). It writes a snapshot to
     ``$ELEVATE_HOME/tmp/elevate-premium/data/sources/mls-private-search/
     buyers.jsonl``.
  2. Read that snapshot, normalize each row, and emit canonical JSONL
     into ``$ELEVATE_TOOLS_ROOT/data/sources/xposure-pcs/``:
       - ``contacts.jsonl``     one row per buyer
       - ``lead-events.jsonl``  one row per buyer-search event (so the
                                 walker creates ``events`` rows that the
                                 enrichment cron can later count)
       - ``pcs_buyers.jsonl``   source-specific extras (searches_json,
                                 matching_listings_json, score, tier).
                                 Not part of the canonical walker; this
                                 connector writes pcs_buyers directly.
  3. Call :func:`walk_jsonl_source` for identities + contacts + events.
  4. Upsert ``pcs_buyers`` rows keyed on contact_id (idempotent).

Why a dedicated module instead of a branch in ``source_connectors.py``:
``source_connectors.py`` is already 5,800 lines and groups several
connectors. The Apple Messages and Lofty CRM flows each live in their
own helpers there because they're tightly coupled to the prebuilt UI
contract. xposure-pcs is a clean greenfield connector — kept self-
contained so the scraper can be swapped (Xposure → some other portal)
without re-threading through the catch-all source_connectors module.

Idempotency contract:
- Re-running the connector NEVER inserts duplicate contacts. The walker
  resolves by identity (email/phone), then by ``source_key``. Both
  collapse to the same canonical ``contact_id``.
- ``pcs_buyers`` rows upsert on the ``contact_id`` PK (set by
  ``ON CONFLICT (contact_id) DO UPDATE``).
- Machine-only fields are touched: ``last_activity_at``,
  ``last_scraped_at``, ``score``, ``tier``, ``searches_json``,
  ``matching_listings_json``. Operator-edited fields on the parent
  ``contacts`` row (display_name, notes, tags) are NEVER overwritten —
  the walker's ``_better_display_name`` rule already enforces that for
  display_name, and we never write notes/tags from here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from elevate_cli.data import connect

_log = logging.getLogger(__name__)

SOURCE_ID = "xposure-pcs"

# Snapshot path the connector reads. The previous Node+Playwright scraper
# wrote here; the new LLM-driven scraper (an Elevate oneshot agent using
# the built-in browser_use toolset) writes the same path so the rest of
# the connector pipeline is unchanged.
_SCRAPER_OUTPUT_REL = "tmp/elevate-premium/data/sources/mls-private-search/buyers.jsonl"

# Side-channel file the Gmail MFA poller writes the 6-digit code into.
# Both the poller thread and the agent (via bash) reference this path.
_MFA_FILE = "/tmp/xposure-mfa.txt"

# The Xposure portal credentials (and Lofty / Gmail tokens) live in the
# elevate-premium project .env, not in the elevate CLI config. When this
# connector runs from launchd, the plist only sources HOME/PATH/ELEVATE_HOME
# — so we always best-effort load that .env into os.environ on entry.
_PREMIUM_ENV_PATH = Path.home() / "elevate-premium" / ".env"


def _load_premium_env() -> None:
    """Merge ~/elevate-premium/.env into os.environ if present. Idempotent:
    existing env vars win (so an explicit launchd / shell override is honoured)."""
    try:
        if not _PREMIUM_ENV_PATH.exists():
            return
        with _PREMIUM_ENV_PATH.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    continue
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val
    except Exception as exc:  # pragma: no cover (best-effort)
        _log.debug("could not load %s: %s", _PREMIUM_ENV_PATH, exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elevate_home() -> Path:
    from elevate_constants import get_elevate_home

    return get_elevate_home()


def _scraper_output_path() -> Path:
    return _elevate_home() / _SCRAPER_OUTPUT_REL


def _local_python_prefix() -> str:
    cli_root = Path(__file__).resolve().parents[1]
    # Dev checkout has a .venv next to the CLI package; the packaged desktop app
    # does not (its interpreter is the bundled runtime python running this code).
    # Fall back to sys.executable so the command works on a real install.
    python = cli_root / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    return (
        f"PYTHONPATH={shlex.quote(str(cli_root))} "
        f"ELEVATE_PYTHON_SRC_ROOT={shlex.quote(str(cli_root))} "
        f"{shlex.quote(str(python))}"
    )


def _local_sync_command(source_id: str, *, env_flag: str) -> str:
    return (
        f"{env_flag}=1 {_local_python_prefix()} "
        f"-m elevate_cli.main sync {shlex.quote(source_id)} --json"
    )


def _local_counts_command(queries: dict[str, str]) -> str:
    lines = [
        f"{_local_python_prefix()} - <<'PY'",
        "from elevate_cli.data import connect",
        "queries = {",
    ]
    for label, sql in queries.items():
        lines.append(f"    {label!r}: {sql!r},")
    lines.extend([
        "}",
        "with connect() as conn:",
        "    for label, sql in queries.items():",
        "        row = conn.execute(sql).fetchone()",
        "        print(f\"{label}={row['n']}\")",
        "PY",
    ])
    return "\n".join(lines)


def _source_workspace(config: dict[str, Any] | None) -> Path:
    """Return ``<tools_root>/data/sources/xposure-pcs/`` — the canonical
    workspace the walker reads."""
    from elevate_cli.source_connectors import (
        get_source_root_info,
        load_config,
    )

    cfg = config or load_config()
    info = get_source_root_info(cfg)
    source_root = Path(info["sourceRoot"])
    workspace = source_root / SOURCE_ID
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "artifacts").mkdir(parents=True, exist_ok=True)
    return workspace


# ─── Gmail MFA side-channel ───────────────────────────────────────────


_GWS_PATH = "PATH=/usr/local/bin:/opt/homebrew/bin:$PATH"


def _gmail_mfa_poll_once() -> str | None:
    """Look once at the inbox for a fresh 6-digit code. Returns the code
    or None. Matches the same sender/subject heuristics the Node scraper
    used, so behaviour stays identical."""
    try:
        list_raw = subprocess.check_output(
            f"{_GWS_PATH} gws gmail users messages list --params "
            "'{\"userId\":\"me\",\"q\":\"newer_than:3m subject:verification\","
            "\"maxResults\":5}'",
            shell=True,
            text=True,
            timeout=10,
        )
        listed = json.loads(list_raw or "{}")
    except Exception as exc:  # gws missing, network blip, malformed JSON
        _log.debug("gmail list failed: %s", exc)
        return None

    for msg in listed.get("messages") or []:
        mid = msg.get("id")
        if not mid:
            continue
        try:
            raw = subprocess.check_output(
                f"{_GWS_PATH} gws gmail users messages get --params "
                f"'{{\"userId\":\"me\",\"id\":\"{mid}\",\"format\":\"metadata\"}}'",
                shell=True,
                text=True,
                timeout=10,
            )
            body = json.loads(raw or "{}")
        except Exception:
            continue
        headers = {
            (h.get("name") or "").lower(): h.get("value") or ""
            for h in (body.get("payload") or {}).get("headers", [])
        }
        sender = headers.get("from", "").lower()
        subject = headers.get("subject", "").lower()
        snippet = body.get("snippet") or ""
        if not (
            "interior" in sender
            or "xposure" in sender
            or "realtor" in sender
            or "verification" in subject
            or "authentication" in subject
        ):
            continue
        m = re.search(r"\b(\d{6})\b", snippet)
        if m:
            return m.group(1)
    return None


def _start_mfa_poller(deadline_ts: float) -> threading.Event:
    """Spawn a daemon thread that polls Gmail every 3s until either it
    finds a code (writes it to ``_MFA_FILE``) or the deadline passes.

    Returns an Event the caller can set() to stop early once the agent
    confirms it submitted the code."""
    stop = threading.Event()

    def _loop() -> None:
        try:
            Path(_MFA_FILE).unlink(missing_ok=True)
        except Exception:
            pass
        while not stop.is_set() and time.time() < deadline_ts:
            code = _gmail_mfa_poll_once()
            if code:
                try:
                    Path(_MFA_FILE).write_text(code, encoding="utf-8")
                    _log.info("xposure MFA code received via gmail poller")
                except Exception as exc:  # pragma: no cover
                    _log.warning("failed to write MFA code: %s", exc)
                return
            stop.wait(3.0)

    t = threading.Thread(target=_loop, name="xposure-mfa-poller", daemon=True)
    t.start()
    return stop


# ─── Scraper invocation ───────────────────────────────────────────────


_AGENT_PROMPT_TEMPLATE = """\
You are an automation agent driving the AOIR Xposure MLS Private Client \
Services portal via the browser_use toolset. Your only job is to log in, \
open the Clients tab, and dump the full buyer table as JSONL to disk.

CREDENTIALS (already in your environment but quoted here for clarity)
- Login URL: {login_url}
- Username env: MLS_USERNAME = "{username}"
- Password env: MLS_PASSWORD = "{password}"

OUTPUT
- Append-only JSONL file: {output_path}
- One row per buyer. Required shape:
  {{"id": "stable Xposure row/client id or deterministic row key",
   "name": "...", "email": "...", "phone": "...", "searches": [...],
   "lastActivity": "...", "dateEntered": "...", "city": "...",
   "profileUrl": "{portal_base}/..."}}
- Truncate the file at the start of the run.

STEPS
1. browser_navigate to the login URL.
2. Use browser_snapshot to get refs, then browser_type the username into the \
   username field and the password into the password field. browser_click the \
   login button.
3. If the page now shows an MFA / "verification code" prompt:
   a. browser_click the "Email" option if one is offered (otherwise skip).
   b. Poll the file {mfa_file} for up to 120 seconds — a background process \
      writes the 6-digit code there. Read it with bash: `cat {mfa_file}`.
   c. Once you have the code, browser_type it into the OTP input and submit.
4. Complete the SSO hop. Some boards land on an intermediate members portal \
   ({members_url}) showing an "Xposure" app tile (text matches \
   /aoir xposure|^xposure$/i) — browser_click it. Others SSO straight into the \
   Xposure portal. Either way, end up on the Xposure portal at {portal_base}. \
   If the SSO hop stalls, browser_navigate directly to {contacts_url}.
5. Once inside the Xposure portal ({portal_base}), find and click the "Clients" \
   nav link if you are not already there. The URL should end up at /Contacts.
6. The clients table has id "pcs-contacts-table". Set its DataTables \
   length dropdown (select[name=\"pcs-contacts-table_length\"]) to "All" \
   using browser_console with a JavaScript expression. Wait ~10 seconds for \
   all rows to render.
7. Extract every row via browser_console. The columns (0-indexed) are:
   0 checkbox | 1 pcs-link (href is in cells[1] a) | 2 blank | 3 type | \
   4 Name | 5 Search Title | 6 Last Login | 7 Date Entered | 8 Consent | \
   9 DRTS | 10 City | 11 Address | 12 Home Phone | 13 Mobile Phone | \
   14 Email | 15 Tags
   Put a stable value in `id`: prefer the checkbox value, row data id,
   pcs-link href id, or client/search id from the DOM. If none exists,
   derive a deterministic key from lowercased email + name + search title +
   date entered.
8. Write one JSONL row per buyer to {output_path}. Skip rows where the \
   name cell is empty.
9. If this prompt includes a VISIBLE SESSION CONTINUATION section below, follow
   that section after writing the JSONL. Otherwise, when done, reply with
   exactly: `DONE rows=<N>` (no other text).

CONSTRAINTS
- Do not open Lofty, do not push any leads anywhere. Just write the JSONL.
- Use browser_console(expression=...) for any DOM extraction — much faster \
  than chasing refs row-by-row.
- If you hit a modal/backdrop, dismiss it via JS (remove .modal-backdrop, \
  click .btn-close).
- If login fails or MFA never arrives, reply `FAILED <one-line reason>`.
"""


def build_agent_session_prompt() -> str:
    """Render the executable prompt used by visible dashboard chat runs.

    The scraper-only prompt is enough for the old in-process runner because
    Python continues into the importer after ``_run_agent`` returns. A regular
    chat session has no such caller, so the visible-session prompt includes the
    local import command that turns the scraped buyer JSONL into contacts,
    lead events, and pcs_buyers rows.
    """
    _load_premium_env()
    from elevate_cli.xposure_board import board_config

    board = board_config()
    scraper_prompt = _AGENT_PROMPT_TEMPLATE.format(
        username=os.environ.get("MLS_USERNAME", "").strip() or "<missing MLS_USERNAME>",
        password=os.environ.get("MLS_PASSWORD", "").strip() or "<missing MLS_PASSWORD>",
        output_path=str(_scraper_output_path()),
        mfa_file=_MFA_FILE,
        login_url=board["login_url"],
        members_url=board["members_url"],
        portal_base=board["portal_base"],
        contacts_url=board["contacts_url"],
    )
    sync_cmd = _local_sync_command("xposure-pcs", env_flag="ELEVATE_XPOSURE_SKIP_SCRAPER")
    verify_cmd = _local_counts_command({
        "contacts": "SELECT COUNT(*) AS n FROM contacts",
        "pcs_buyers": "SELECT COUNT(*) AS n FROM pcs_buyers",
        "xposure_events": "SELECT COUNT(*) AS n FROM events WHERE source_id = 'xposure-pcs'",
        "xposure_identities": "SELECT COUNT(*) AS n FROM identities WHERE kind = 'xposure_pcs_id'",
    })
    return (
        f"{scraper_prompt}\n"
        "VISIBLE SESSION CONTINUATION\n"
        "10. After the buyer JSONL is written, run this local import command with bash:\n"
        f"    `{sync_cmd}`\n"
        "    This must NOT open the browser again. It reuses the file you just wrote\n"
        "    and imports people/emails/phones into operational Postgres: contacts,\n"
        "    events, identities, and pcs_buyers.\n"
        "11. Verify the Postgres import with bash:\n"
        "    ```bash\n"
        f"{verify_cmd}\n"
        "    ```\n"
        "12. Final reply exactly:\n"
        "    `DONE rows=<scraped_rows> imported_contacts=<contacts_count> pcs_buyers=<pcs_buyers_count> xposure_events=<xposure_events_count> xposure_identities=<xposure_identities_count>`\n"
        "    If either scrape or import fails, reply `FAILED <one-line reason>`.\n"
        "13. Run the MLS layers sequentially: finish this buyer-search import before\n"
        "    starting buyer-brief or xposure-pcs-views. They share contacts/pcs_buyers\n"
        "    rows and should not be imported in parallel.\n"
    )


def _run_scraper(*, skip: bool = False) -> dict[str, Any]:
    """Drive the Xposure PCS scrape via the Elevate oneshot agent with the \
    browser_use + bash toolsets.

    The previous implementation shelled out to a 550-line Node+Playwright \
    script. This version delegates to the agent's own browser-use model, \
    which interprets the steps prompt against the live portal. A parallel \
    Gmail polling thread surfaces the 6-digit MFA code via ``_MFA_FILE``.

    Returns ``{ok, skipped, returncode, stdout_tail, stderr_tail}`` — same \
    shape the rest of the connector expects.

    ``skip=True`` short-circuits everything and just reads whatever snapshot \
    is already on disk (used by tests and by manual re-imports after a \
    successful scrape)."""
    if skip:
        return {"ok": True, "skipped": True, "stdout_tail": "", "stderr_tail": ""}

    _load_premium_env()
    username = os.environ.get("MLS_USERNAME", "").strip()
    password = os.environ.get("MLS_PASSWORD", "").strip()
    if not username or not password:
        return {
            "ok": False,
            "skipped": False,
            "error": "MLS_USERNAME / MLS_PASSWORD must be set",
            "stdout_tail": "",
            "stderr_tail": "",
        }

    output_path = _scraper_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text("", encoding="utf-8")  # truncate
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "error": f"failed to truncate snapshot: {exc}",
            "stdout_tail": "",
            "stderr_tail": "",
        }

    prompt = _AGENT_PROMPT_TEMPLATE.format(
        username=username,
        password=password,
        output_path=str(output_path),
        mfa_file=_MFA_FILE,
    )

    poller_deadline = time.time() + 60 * 18  # cap MFA wait inside the 20-min run
    stop_poller = _start_mfa_poller(poller_deadline)

    try:
        from elevate_cli.oneshot import _run_agent
    except Exception as exc:  # pragma: no cover (import time only)
        stop_poller.set()
        return {
            "ok": False,
            "skipped": False,
            "error": f"could not import oneshot agent runner: {exc}",
            "stdout_tail": "",
            "stderr_tail": "",
        }

    response = ""
    error: str | None = None
    try:
        # Browser-use + bash give the agent everything it needs: navigate,
        # snapshot, click, type, JS eval, and shell access for the MFA file.
        response = _run_agent(
            prompt,
            toolsets=["browser", "bash"],
            use_config_toolsets=False,
        )
    except Exception as exc:  # network blow-up, agent crash, etc.
        error = f"oneshot agent raised: {exc}"
    finally:
        stop_poller.set()

    # The agent contract: "DONE rows=N" means success, "FAILED ..." means
    # the agent gave up on its own. Anything else we treat as ambiguous
    # and re-check the file.
    response_tail = (response or "")[-1000:]
    snapshot_lines = 0
    try:
        with output_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    snapshot_lines += 1
    except FileNotFoundError:
        snapshot_lines = 0

    if error:
        return {
            "ok": False,
            "skipped": False,
            "error": error,
            "stdout_tail": response_tail,
            "stderr_tail": "",
            "snapshot_rows": snapshot_lines,
        }

    if response_tail.strip().startswith("FAILED"):
        return {
            "ok": False,
            "skipped": False,
            "error": response_tail.strip()[:300],
            "stdout_tail": response_tail,
            "stderr_tail": "",
            "snapshot_rows": snapshot_lines,
        }

    return {
        "ok": snapshot_lines > 0,
        "skipped": False,
        "returncode": 0 if snapshot_lines > 0 else 1,
        "stdout_tail": response_tail,
        "stderr_tail": "",
        "snapshot_rows": snapshot_lines,
    }


# ─── Snapshot → canonical JSONL ───────────────────────────────────────


def _read_snapshot(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                _log.warning("skipping malformed snapshot row")
    return out


def _coerce_searches(raw: Any) -> list[str]:
    """Snapshot stores ``searches`` as a list of label strings (e.g.
    ['no title', 'Kamloops 3-bed']). Keep it as a flat list."""
    if isinstance(raw, list):
        return [str(s) for s in raw if s]
    if isinstance(raw, str):
        return [raw]
    return []


def _coerce_listings(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _snapshot_native_id(row: dict[str, Any]) -> str:
    """Return a stable native key for a scraped buyer row.

    Older scraper contracts forgot to include ``id`` even though the importer
    requires one for source identity. Keep those snapshots importable by
    deriving a deterministic key from the row's visible buyer/search fields.
    """
    for key in (
        "id",
        "source_record_id",
        "sourceRecordId",
        "clientId",
        "contactId",
        "pcsId",
        "xposureId",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value

    searches = _coerce_searches(row.get("searches"))
    parts = [
        str(row.get("email") or "").strip().lower(),
        str(row.get("name") or "").strip().lower(),
        "|".join(s.strip().lower() for s in searches if s.strip()),
        str(row.get("dateEntered") or "").strip().lower(),
        str(row.get("profileUrl") or "").strip().lower(),
    ]
    basis = "\x1f".join(part for part in parts if part)
    if not basis:
        return ""
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"derived:{digest}"


def _build_canonical_rows(
    snapshot: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert snapshot rows into (contacts, lead_events, pcs_extras).

    The contact and lead-event rows go through ``walk_jsonl_source`` so
    they pick up the identity-first writethrough. The pcs_extras list
    is consumed directly by :func:`_upsert_pcs_buyers`.
    """
    contacts: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []

    now = _now_iso()
    for row in snapshot:
        native = _snapshot_native_id(row)
        if not native:
            continue

        email = str(row.get("email") or "").strip() or None
        phone = str(row.get("phone") or "").strip() or None
        name = str(row.get("name") or "").strip() or None
        scraped_at = str(row.get("scrapedAt") or now)

        # Canonical contact row. The walker writes the contact, creates
        # email + phone identities, and (if a Lofty/Apple row already
        # owns either identity) collapses this scrape into that contact.
        contacts.append(
            {
                "source_record_id": native,
                "display_name": name,
                "email": email,
                "phone": phone,
                "identities": [
                    {"kind": "xposure_pcs_id", "value": native},
                ],
                "tags": list(row.get("tags") or []),
                "raw_profile_url": row.get("profileUrl"),
            }
        )

        # One lead-event per buyer per scrape. Provides the activity
        # signal the enrichment cron counts for tier bucketing.
        events.append(
            {
                "source_record_id": f"{native}:scrape:{scraped_at}",
                "contact_id": native,
                "timestamp": scraped_at,
                "legacyType": "pcs_scrape",
                "summary": f"MLS private-search scrape (tier={row.get('tier') or 'unknown'})",
                "lead_score": row.get("score"),
                "tier": row.get("tier"),
            }
        )

        extras.append(
            {
                "source_record_id": native,
                "score": row.get("score"),
                "tier": row.get("tier"),
                "days": row.get("days"),
                "searches": _coerce_searches(row.get("searches")),
                "matching_listings": _coerce_listings(row.get("matchingListings")),
                "profile_url": row.get("profileUrl"),
                "last_activity_label": row.get("lastActivity"),
                "scraped_at": scraped_at,
            }
        )

    return contacts, events, extras


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_source_json(workspace: Path, *, status: str, counts: dict[str, int]) -> None:
    payload = {
        "source_id": SOURCE_ID,
        "provider": "Xposure MLS",
        "account_label": "xposure-pcs scrape",
        "connection_type": "headless_scraper",
        "auth_status": "active",
        "sync_mode": "scrape",
        "owner_agent": "Outreach",
        "enabled_ui_surfaces": ["Leads", "Today", "Outreach", "Approvals"],
        "setup_status": status,
        "last_sync_at": _now_iso(),
        "setup_notes": (
            "MLS private-search scraper that pulls buyer criteria from the "
            "Lofty member-area portal. Runs through the canonical "
            "walk_jsonl_source writethrough so the same buyer collapses to "
            "one contact across xposure-pcs + Lofty + Apple Messages."
        ),
        "record_counts": counts,
    }
    (workspace / "source.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _write_status_json(
    workspace: Path,
    *,
    connected: bool,
    last_error: str | None,
    next_step: str | None,
) -> None:
    payload = {
        "connected": connected,
        "import_only": False,
        "blocked": False,
        "last_error": last_error,
        "next_operator_step": next_step,
        "last_checked_at": _now_iso(),
    }
    (workspace / "status.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ─── pcs_buyers upsert ────────────────────────────────────────────────


def _upsert_pcs_buyers(
    conn,
    *,
    extras: list[dict[str, Any]],
    contact_by_native: dict[str, str],
) -> int:
    """Idempotent upsert of pcs_buyers rows.

    PK is ``contact_id``. We never delete rows here — if the scraper
    stops seeing a buyer, the row stays put with its last-known state
    until the enrichment cron explicitly ages it out. This keeps drawer
    history visible even after a buyer drops off the active list.
    """
    if not extras:
        return 0

    now = _now_iso()
    written = 0
    for extra in extras:
        native = str(extra.get("source_record_id") or "")
        if not native:
            continue
        contact_id = contact_by_native.get(native)
        if not contact_id:
            # Walker decided not to upsert this row (no identifying
            # signal — empty email AND empty phone AND no native id).
            # Skip; the contact doesn't exist in PG, so the FK would
            # blow up anyway.
            continue

        # lead_signal_id is REQUIRED by the FK on pcs_buyers. Look up
        # any open lead_signal for this contact; if none, create a
        # bare one so the pcs_buyers row has a valid parent.
        sig_row = conn.execute(
            "SELECT id FROM lead_signals WHERE graduated_to_contact_id=? "
            "ORDER BY last_activity_at DESC NULLS LAST LIMIT 1",
            (contact_id,),
        ).fetchone()
        if sig_row:
            lead_signal_id = sig_row["id"]
        else:
            lead_signal_id = f"sig:{SOURCE_ID}:{native}"
            row = conn.execute(
                """
                INSERT INTO lead_signals (
                    id, source_id, source_native_id, payload_json,
                    last_activity_at, graduated_at, graduated_to_contact_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?)
                ON CONFLICT (source_id, source_native_id) DO UPDATE SET
                    last_activity_at = excluded.last_activity_at,
                    graduated_to_contact_id = excluded.graduated_to_contact_id,
                    updated_at = excluded.updated_at
                RETURNING id
                """,
                (
                    lead_signal_id,
                    SOURCE_ID,
                    native,
                    extra.get("scraped_at") or now,
                    now,
                    contact_id,
                    now,
                    now,
                ),
            ).fetchone()
            if row and row.get("id"):
                lead_signal_id = row["id"]

        conn.execute(
            """
            INSERT INTO pcs_buyers (
                contact_id, lead_signal_id, score, tier, days,
                searches_json, matching_listings_json,
                last_activity_at, last_scraped_at, profile_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (contact_id) DO UPDATE SET
                score                  = excluded.score,
                tier                   = excluded.tier,
                days                   = excluded.days,
                searches_json          = excluded.searches_json,
                matching_listings_json = excluded.matching_listings_json,
                last_activity_at       = excluded.last_activity_at,
                last_scraped_at        = excluded.last_scraped_at,
                profile_url            = excluded.profile_url
            """,
            (
                contact_id,
                lead_signal_id,
                extra.get("score"),
                extra.get("tier"),
                extra.get("days"),
                json.dumps(extra.get("searches") or [], ensure_ascii=False),
                json.dumps(extra.get("matching_listings") or [], ensure_ascii=False),
                extra.get("scraped_at") or now,
                now,
                extra.get("profile_url"),
            ),
        )
        written += 1
    return written


def _contact_map_by_native(
    conn,
    *,
    contacts: list[dict[str, Any]],
) -> dict[str, str]:
    """Return xposure native id -> canonical contact_id after the walker.

    A matched buyer may resolve into an existing CRM contact. In that case
    ``contacts.source_key`` remains the CRM source key by design, so looking up
    ``contacts.source_key LIKE 'xposure-pcs:%'`` misses the exact rows we care
    about. The connector emits an explicit ``xposure_pcs_id`` identity and maps
    through ``identities`` first, with the source_key query kept as a legacy
    fallback for pre-identity rows.
    """
    out: dict[str, str] = {}
    natives = [str(row.get("source_record_id") or "").strip() for row in contacts]
    for native in [n for n in natives if n]:
        row = conn.execute(
            "SELECT contact_id FROM identities WHERE kind=? AND value=?",
            ("xposure_pcs_id", native),
        ).fetchone()
        if row and row.get("contact_id"):
            out[native] = row["contact_id"]

    missing = [native for native in natives if native and native not in out]
    if missing:
        rows = conn.execute(
            "SELECT id, source_key FROM contacts WHERE source_key LIKE ?",
            (f"{SOURCE_ID}:%",),
        ).fetchall()
        for r in rows:
            source_key = r["source_key"] or ""
            if source_key.startswith(f"{SOURCE_ID}:"):
                native = source_key.split(":", 1)[1]
                if native in missing:
                    out[native] = r["id"]
    return out


# ─── Entry point ──────────────────────────────────────────────────────


def sync_xposure_pcs_source(
    config: dict[str, Any] | None = None,
    *,
    skip_scraper: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one full xposure-pcs sync.

    ``skip_scraper=True`` reuses the latest snapshot on disk — fast path
    for local testing or when the scraper just ran in another process.

    ``dry_run=True`` walks the snapshot, writes the canonical JSONL files,
    and reports what WOULD be upserted, but rolls back the DB transaction
    so no rows commit. The connector's source/status JSON DO get written
    because they're files, not DB state — operators want to see "ran but
    dry" reflected in the connector card status.
    """
    from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

    workspace = _source_workspace(config)
    scrape_result = _run_scraper(skip=skip_scraper)

    snapshot_path = _scraper_output_path()
    snapshot = _read_snapshot(snapshot_path)

    contacts, events, extras = _build_canonical_rows(snapshot)
    _write_jsonl(workspace / "contacts.jsonl", contacts)
    _write_jsonl(workspace / "lead-events.jsonl", events)
    # Apple Messages-shaped sources also write conversations/messages;
    # MLS scrapes don't have either, so we write empty placeholders so
    # the canonical 5-file layout exists and downstream readers don't
    # 404 on missing files.
    _write_jsonl(workspace / "conversations.jsonl", [])
    _write_jsonl(workspace / "messages.jsonl", [])
    _write_jsonl(workspace / "tasks.jsonl", [])

    stats = BackfillStats()
    with connect() as conn:
        # Disable autocommit so the walker + pcs_buyers upsert share
        # the same transaction. dry_run rolls everything back at the end.
        walk_jsonl_source(workspace, conn=conn, stats=stats, dry_run=dry_run)

        # Rebuild native → contact_id map from PG (the walker doesn't
        # return it). Use the xposure_pcs_id identity first so buyers that
        # merged into an existing CRM contact still get pcs_buyers detail.
        contact_by_native: dict[str, str] = {}
        if not dry_run and contacts:
            contact_by_native = _contact_map_by_native(conn, contacts=contacts)

        pcs_written = (
            _upsert_pcs_buyers(conn, extras=extras, contact_by_native=contact_by_native)
            if not dry_run
            else 0
        )

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    counts = {
        "snapshot_rows": len(snapshot),
        "contacts_seen": len(contacts),
        "events_seen": len(events),
        "pcs_buyers_upserted": pcs_written,
        "contacts_new": stats.contacts,
        "contacts_skipped": stats.contacts_skipped,
        "events_new": stats.lifecycle_events,
        "events_skipped": 0,
    }
    connected = scrape_result.get("ok", False) and bool(snapshot)
    last_error = None if scrape_result.get("ok") else (
        scrape_result.get("error") or scrape_result.get("stderr_tail")
    )
    next_step = (
        None
        if connected
        else "Re-run scraper or check Lofty member-area session token."
    )

    _write_source_json(
        workspace,
        status="connected" if connected else "needs_operator",
        counts=counts,
    )
    _write_status_json(
        workspace,
        connected=connected,
        last_error=last_error,
        next_step=next_step,
    )

    return {
        "id": SOURCE_ID,
        "label": "MLS Buyer Searches",
        "state": "connected" if connected else "needs_operator",
        "sourceExists": True,
        "sourceDir": str(workspace),
        "connectionType": "headless_scraper",
        "syncMode": "scrape",
        "authStatus": "active" if connected else "needs_operator",
        "connected": connected,
        "importOnly": False,
        "blocked": False,
        "lastError": last_error,
        "nextOperatorStep": next_step,
        "lastCheckedAt": _now_iso(),
        "recordCounts": counts,
        "scrapeResult": {
            k: v for k, v in scrape_result.items() if k not in ("stdout_tail",)
        },
        "dryRun": dry_run,
    }


__all__ = ["SOURCE_ID", "build_agent_session_prompt", "sync_xposure_pcs_source"]
