"""Prompt renderers for source connector run sessions."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


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
