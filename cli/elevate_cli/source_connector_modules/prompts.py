"""Prompt renderers for source connector run sessions."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Callable

from elevate_cli.source_connector_modules.connector_state import _blueprint
from elevate_cli.source_connector_modules.source_catalog import (
    AGENT_SESSION_SOURCE_IDS,
    COMPOSIO_SOCIAL_CONTRACT,
    CONNECTION_CONTRACT,
    OWNER_BY_SOURCE,
    UI_BY_SOURCE,
)


def _local_python_prefix() -> str:
    cli_root = Path(__file__).resolve().parents[2]
    # Dev checkout ships a virtualenv next to the CLI package. The packaged
    # desktop app does NOT — its interpreter is the bundled runtime python
    # (Contents/Resources/runtime/python/bin/python3.12), which is exactly the
    # process running this code. Fall back to sys.executable so the rendered
    # command works on a real install instead of pointing at a missing .venv.
    python = cli_root / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    return (
        f"PYTHONPATH={shlex.quote(str(cli_root))} "
        f"ELEVATE_PYTHON_SRC_ROOT={shlex.quote(str(cli_root))} "
        f"{shlex.quote(str(python))}"
    )


def _local_sync_command(source_id: str) -> str:
    return f"{_local_python_prefix()} -m elevate_cli.main sync {shlex.quote(source_id)} --json"


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
        "        print(f\"{label}={row['n'] if row else 0}\")",
        "PY",
    ])
    return "\n".join(lines)


def _source_file_count_commands(source_id: str) -> str:
    from elevate_cli.source_connectors import JSONL_FILES, _source_dir, get_source_root_info

    source_root = Path(get_source_root_info()["sourceRoot"])
    source_dir = _source_dir(source_root, source_id)
    files = " ".join(shlex.quote(str(source_dir / name)) for name in JSONL_FILES)
    return (
        f"ls -la {shlex.quote(str(source_dir))}\n"
        f"wc -l {files} 2>/dev/null || true\n"
        f"cat {shlex.quote(str(source_dir / 'status.json'))} 2>/dev/null || true\n"
        f"cat {shlex.quote(str(source_dir / 'source.json'))} 2>/dev/null || true"
    )


def _render_apple_messages_agent_prompt() -> str:
    sync_cmd = _local_sync_command("apple-messages")
    file_cmd = _source_file_count_commands("apple-messages")
    counts_cmd = _local_counts_command({
        "contacts": "SELECT COUNT(*) AS n FROM contacts",
        "conversations": "SELECT COUNT(*) AS n FROM conversations",
        "apple_events": (
            "SELECT COUNT(*) AS n FROM events "
            "WHERE source_id = 'apple-messages' OR channel = 'apple-messages'"
        ),
        "identities": "SELECT COUNT(*) AS n FROM identities",
        "identity_conflicts_pending": (
            "SELECT COUNT(*) AS n FROM identity_conflicts WHERE resolved_at IS NULL"
        ),
    })
    return (
        "TASK\n"
        "Run the Apple Messages connector as a visible local session. This is a\n"
        "read-only Mac Messages + AddressBook import; do not send or draft replies.\n\n"
        "DO THIS\n"
        f"1. Run the local sync command:\n   `{sync_cmd}`\n"
        "2. If macOS blocks chat.db or AddressBook access, stop and report the exact\n"
        "   Full Disk Access / Contacts permission error shown in status.json.\n"
        "3. Verify source files and status with bash:\n"
        "   ```bash\n"
        f"{file_cmd}\n"
        "   ```\n"
        "4. Verify the operational Postgres writethrough with bash:\n"
        "   ```bash\n"
        f"{counts_cmd}\n"
        "   ```\n"
        "5. Final reply exactly:\n"
        "   `DONE contacts=<contacts_db> conversations=<conversations_db> apple_events=<apple_events_db> identity_conflicts_pending=<pending_count>`\n"
        "   If blocked, reply `FAILED <one-line reason>`.\n\n"
        "CONSTRAINTS\n"
        "- Local read/import only. Never send a message.\n"
        "- Do not use deprecated ~/.elevate/data/operational.db for verification.\n"
        "- Keep all output in the session so the operator can watch the run."
    )


def _render_social_agent_prompt() -> str:
    from elevate_cli.source_connectors import get_source_root_info

    sync_cmd = _local_sync_command("social")
    source_root = Path(get_source_root_info()["sourceRoot"])
    counts_cmd = _local_counts_command({
        "contacts": "SELECT COUNT(*) AS n FROM contacts",
        "conversations": "SELECT COUNT(*) AS n FROM conversations",
        "lead_events": "SELECT COUNT(*) AS n FROM events WHERE source_id LIKE 'composio-%%' OR source_id = 'social'",
    })
    source_root_q = shlex.quote(str(source_root))
    return (
        "TASK\n"
        "Run the Composio social-account connector as a visible local session.\n"
        "Composio is the account hub; do not ask for raw social passwords.\n\n"
        "DO THIS\n"
        f"1. Run the local sync command:\n   `{sync_cmd}`\n"
        "2. If COMPOSIO_MCP_SERVER/config is missing, surface the exact setup error\n"
        "   and stop. If some toolkits are not connected, report them but continue\n"
        "   with connected toolkits.\n"
        "3. Verify per-toolkit source folders and status with bash:\n"
        "   ```bash\n"
        f"find {source_root_q} -maxdepth 1 -type d \\( -name 'composio-*' -o -name 'social' \\) -print\n"
        f"find {source_root_q} -maxdepth 2 \\( -name status.json -o -name source.json \\) -path '*composio-*' -print -exec cat {{}} \\;\n"
        "   ```\n"
        "4. Verify operational Postgres rows with bash:\n"
        "   ```bash\n"
        f"{counts_cmd}\n"
        "   ```\n"
        "5. Final reply exactly:\n"
        "   `DONE social_toolkits=<N> lead_events=<lead_events_db> conversations=<conversations_db> contacts=<contacts_db>`\n"
        "   If the Composio hub is not configured, reply `FAILED <one-line reason>`.\n\n"
        "CONSTRAINTS\n"
        "- Never post, reply, DM, or modify social content from this connector run.\n"
        "- Pull inbound/metrics only and leave outbound replies approval-gated.\n"
        "- Keep all output in the visible session."
    )


def _render_buyer_brief_agent_prompt() -> str:
    sync_cmd = _local_sync_command("buyer-brief")
    counts_cmd = _local_counts_command({
        "pcs_buyers": "SELECT COUNT(*) AS n FROM pcs_buyers",
        "contacts_with_brief": (
            "SELECT COUNT(*) AS n FROM contacts "
            "WHERE COALESCE(enrichment_brief, '') <> ''"
        ),
        "warm_buyers": (
            "SELECT COUNT(*) AS n FROM contacts WHERE activity_tier = 'warm'"
        ),
        "active_buyers": (
            "SELECT COUNT(*) AS n FROM contacts WHERE activity_tier = 'active'"
        ),
    })
    return (
        "TASK\n"
        "Run buyer-brief enrichment as a visible local session. This reads the\n"
        "already-imported pcs_buyers rows and writes human-readable buyer context\n"
        "and activity tiers back onto contacts. No browser and no external API.\n\n"
        "DO THIS\n"
        f"1. Run the local sync command:\n   `{sync_cmd}`\n"
        "2. Verify Postgres enrichment counts with bash:\n"
        "   ```bash\n"
        f"{counts_cmd}\n"
        "   ```\n"
        "3. Spot-check two enriched contacts without printing private emails:\n"
        "   ```bash\n"
        f"{_local_python_prefix()} - <<'PY'\n"
        "from elevate_cli.data import connect\n"
        "with connect() as conn:\n"
        "    rows = conn.execute(\"\"\"\n"
        "        SELECT display_name, activity_tier, LEFT(enrichment_brief, 180) AS brief\n"
        "        FROM contacts\n"
        "        WHERE COALESCE(enrichment_brief, '') <> ''\n"
        "        ORDER BY updated_at DESC\n"
        "        LIMIT 2\n"
        "    \"\"\").fetchall()\n"
        "    for row in rows:\n"
        "        print(dict(row))\n"
        "PY\n"
        "   ```\n"
        "4. Final reply exactly:\n"
        "   `DONE pcs_buyers=<pcs_buyers> contacts_with_brief=<contacts_with_brief> active=<active_buyers> warm=<warm_buyers>`\n"
        "   If enrichment fails, reply `FAILED <one-line reason>`.\n\n"
        "CONSTRAINTS\n"
        "- No browser, no outbound messages, no external enrichment calls.\n"
        "- Run after MLS Buyer Searches finishes; do not run concurrently with\n"
        "  xposure-pcs or xposure-pcs-views because those touch the same buyer rows.\n"
        "- Do not print private buyer emails in the final reply."
    )


def _render_xposure_pcs_agent_prompt() -> str:
    from elevate_cli.xposure_pcs_connector import build_agent_session_prompt

    return build_agent_session_prompt()


def _render_xposure_pcs_views_agent_prompt() -> str:
    from elevate_cli.xposure_pcs_views import build_agent_session_prompt

    return build_agent_session_prompt()


# ─── Per-source operational prompts ────────────────────────────────────
#
# Each prompt describes the EXACT code path that runs when the operator
# clicks "Run prompt" for that source. For wired sources (apple-messages,
# crm, social) it's a deterministic shell call; for not-yet-built sources
# it's the canonical contract an agent should follow to build it.
#
# Update these whenever the implementation changes — they are the
# operator/agent-facing source of truth for what this connector does.


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


PromptRenderer = Callable[[], str]


_WIRED_SOURCE_PROMPTS: dict[str, str | PromptRenderer] = {
    "apple-messages": _render_apple_messages_agent_prompt,

    "crm": "__CRM_DYNAMIC__",  # rendered at runtime by _render_crm_prompt()

    "social": _render_social_agent_prompt,

    "xposure-pcs": _render_xposure_pcs_agent_prompt,

    "buyer-brief": _render_buyer_brief_agent_prompt,

    "xposure-pcs-views": _render_xposure_pcs_views_agent_prompt,
}


def _render_crm_prompt() -> str:
    """Build a task-first CRM prompt with live state baked in.

    Resolves the configured provider (admin profile → config fallback) and
    peeks at last sync + contact count. The job is always the same: run
    `elevate sync crm` to backfill the operator's CRM into operational Postgres.
    Provider + credential are read from disk by the CLI — don't ask the user.
    """
    source_connectors = _source_connectors()
    config = source_connectors.load_config()
    provider, _api_key, crm, _env = source_connectors._resolve_crm_context(config)
    provider_label = source_connectors._provider_label(provider) if provider else "CRM"

    last_sync = None
    contact_count = 0
    try:
        info = source_connectors.get_source_root_info(config)
        source_root = Path(info["sourceRoot"])
        source_dir = source_connectors._source_dir(source_root, "crm")
        source_meta = source_connectors._read_json(source_dir / "source.json")
        if isinstance(source_meta, dict):
            last_sync = source_meta.get("last_sync_at")
        contact_count = source_connectors._count_jsonl(source_dir / "contacts.jsonl")
    except Exception:
        pass

    sync_cmd = _local_sync_command("crm")
    file_cmd = _source_file_count_commands("crm")
    counts_cmd = _local_counts_command({
        "contacts": "SELECT COUNT(*) AS n FROM contacts",
        "lifecycle_events": (
            "SELECT COUNT(*) AS n FROM events WHERE kind = 'lifecycle_change'"
        ),
        "conversations": "SELECT COUNT(*) AS n FROM conversations",
        "identities": "SELECT COUNT(*) AS n FROM identities",
        "identity_conflicts_pending": (
            "SELECT COUNT(*) AS n FROM identity_conflicts WHERE resolved_at IS NULL"
        ),
    })

    return (
        "TASK\n"
        f"Backfill the operator's {provider_label} CRM into Elevate's operational Postgres DB,\n"
        f"then VERIFY the sync actually succeeded end-to-end. Don't trust the CLI's\n"
        f"exit code alone — check the resulting data with your own eyes. Do not ask\n"
        f"the operator for the API key; the CLI reads it from ~/.elevate/.env. If\n"
        f"the CLI raises a missing-key error, surface that error verbatim and stop.\n\n"
        "CURRENT STATE (snapshot at render time — verify against live values)\n"
        f"  provider:       {provider_label} ({provider or 'unset'})\n"
        f"  contacts in source snapshot: {contact_count}\n"
        f"  last sync:      {last_sync or 'never'}\n\n"
        "DO THIS (every step. Don't skip the verification steps.)\n"
        f"1. Run the local sync command:\n   `{sync_cmd}`\n"
        "2. Wait for it to finish (paginated full backfill — may take a few minutes).\n"
        "   Watch stderr for HTTP 4xx/5xx, rate-limit, or auth errors. Do not silently\n"
        "   ignore non-zero exit codes.\n"
        "3. VERIFY the source files were written (jsonl, fresh timestamps):\n"
        "   ```bash\n"
        f"{file_cmd}\n"
        "   ```\n"
        "   Note: jsonl line counts may be lower than source.json record_counts because\n"
        "   the jsonl is the latest snapshot (may be incremental), while record_counts\n"
        "   is cumulative across all syncs. Use record_counts for the totals.\n"
        "4. VERIFY the walker wrote rows into the operational Postgres DB (real schema —\n"
        "   these are the only tables the walker actually populates):\n"
        "   ```bash\n"
        f"{counts_cmd}\n"
        "   ```\n"
        "   Counts should be > 0 and roughly match source.json record_counts. If DB\n"
        "   is empty but jsonl is populated, the writethrough is broken — flag it loudly.\n"
        "   NOTE: there is no `tasks` table by design — tasks live as JSONL only\n"
        "   (see reads.py). Don't query it. There is no `lead_events` table either —\n"
        "   lead lifecycle changes are stored in `events` with kind='lifecycle_change'.\n"
        "   DO NOT touch ~/.elevate/data/operational.db — that SQLite file is deprecated.\n"
        "5. Spot-check 2 real rows are coherent (use REAL column names):\n"
        "   ```bash\n"
        f"{_local_python_prefix()} - <<'PY'\n"
        "from elevate_cli.data import connect\n"
        "with connect() as conn:\n"
        "    rows = conn.execute(\"\"\"\n"
        "        SELECT id, display_name, primary_phone, primary_email\n"
        "        FROM contacts\n"
        "        ORDER BY updated_at DESC\n"
        "        LIMIT 2\n"
        "    \"\"\").fetchall()\n"
        "    for row in rows:\n"
        "        print(dict(row))\n"
        "PY\n"
        "   ```\n"
        "   Both rows should have a real display_name plus primary_phone OR primary_email.\n"
        "   If they're empty strings or duplicates, the adapter mapping is broken — flag it.\n"
        "6. Report back with a CSV-style summary (use REAL table/column names):\n"
        "     contacts_jsonl=N, conversations_jsonl=N, lead_events_jsonl=N, tasks_jsonl=N,\n"
        "     contacts_db=N, lifecycle_events_db=N, conversations_db=N, identities_db=N,\n"
        "     identity_conflicts_pending=N, last_sync_at=<iso>, record_counts_total=N,\n"
        "     errors=<count or 'none'>\n"
        "   Plus a one-line verdict: HEALTHY / DEGRADED / FAILED and what the operator\n"
        "   should look at next (e.g. 'review N identity_conflicts before merging').\n\n"
        "OUTCOME\n"
        "  Success = both the source jsonl files and operational Postgres tables hold the\n"
        "  same row counts (within rounding), the dashboard's /leads, /admin, /today\n"
        "  surfaces show live data, and any cross-CRM duplicates land in\n"
        "  identity_conflicts for human merge (NEVER auto-merge —\n"
        "  merge_contacts requires actor.startswith(\"human\"))."
    )


def source_prompt_for(source_id: str) -> str:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return ""
    surfaces = ", ".join(UI_BY_SOURCE.get(source_id, ["Settings"]))
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")

    wired = _WIRED_SOURCE_PROMPTS.get(source_id)
    if wired:
        # CRM is rendered live so the agent gets current provider + credential
        # state, not a generic stub.
        if source_id == "crm":
            wired_text = _render_crm_prompt()
        elif callable(wired):
            wired_text = wired()
        else:
            wired_text = wired

        if source_id in AGENT_SESSION_SOURCE_IDS:
            return (
                f"{blueprint['source']} — owner_agent={owner}, surfaces: {surfaces}\n\n"
                f"{wired_text}"
            )

        # Live inline source — describe exactly what runs. Append the canonical
        # contract so the agent / operator still sees the universal storage
        # layout and identity rules.
        return (
            f"{blueprint['source']} — owner_agent={owner}, surfaces: {surfaces}\n\n"
            f"{wired_text}\n\n"
            f"Canonical contract (applies to every Elevate source):\n{CONNECTION_CONTRACT}\n"
        )

    # Not-yet-wired source — emit the agent build brief that follows the
    # canonical pattern, with apple-messages / crm / social pointed at as
    # working reference implementations.
    extra_contract = f"\n\n{COMPOSIO_SOCIAL_CONTRACT}" if source_id == "social" else ""
    return (
        f"You are wiring {blueprint['source']} into Elevate Agent.\n"
        f"source_id={source_id}, owner_agent={owner}, target UI surfaces: {surfaces}\n\n"
        "STATUS: No live pull code exists for this source yet. This prompt creates a\n"
        "tasks.jsonl entry with `task_type=connector_setup` and `agent_prompt` embedded.\n"
        "An agent (Jimmy via dispatch-bridge, or the operator) reads this prompt and\n"
        "builds the real connector following the canonical contract below.\n\n"
        f"Information Elevate needs:\n{blueprint['informationNeeded']}\n\n"
        "Reference implementations to mirror:\n"
        "- Local-file source (chat.db / AddressBook): see `initialize_apple_messages_source`\n"
        "  in `elevate_cli/source_connectors.py` + `elevate_cli/apple_contacts.py`.\n"
        "- API source with pagination + enrichment: see `sync_lofty_crm_source` and the\n"
        "  generic adapter pattern in `elevate_cli/crm_adapters/`.\n"
        "- Messages-only source needing synthesized contacts/conversations: see\n"
        "  `elevate_cli/composio_inbound.py:synthesize_canonical_files`.\n\n"
        f"{CONNECTION_CONTRACT}{extra_contract}\n\n"
        "When the connector is built:\n"
        f"- If the source is deterministic, add a tuple to `elevate_cli/sync_scheduler.py:_JOBS`\n"
        f"  so `elevate db init` installs the recurring launchd plist on every fresh install.\n"
        f"  If it launches an AI/browser agent, register it in app Automations instead.\n"
        f"- Add `{source_id}` to the routing block in\n"
        f"  `elevate_cli/web_server.py:update_source_connector` so the UI Run button fires it.\n"
        f"- Add the relevant identity kind to the `_SOURCE_TO_HANDLE_KIND`,\n"
        f"  `_CRM_PROVIDER_TO_IDENTITY_KIND`, or `_TOOLKIT_TO_HANDLE_KIND` registry —\n"
        f"  do NOT branch in walker code.\n\n"
        f"Done when:\n{blueprint['successSignal']}\n"
        "- And: clicking Run on the connector card pulls live records into\n"
        "  the operational Postgres DB on a fresh install with no manual steps beyond providing\n"
        "  the operator's credential / file path.\n"
    )
