"""Direct database awareness for the AI over the operational PG store.

Three actions exposed as one tool:

* ``query``   — read-only SQL (SELECT / WITH only) against the operational
  store, filtered to tables the user is entitled to.
* ``describe`` — list the tables and columns the user can see, or dump one
  table's schema. Backed by ``information_schema`` since the cutover to
  embedded Postgres.
* ``call``    — invoke a curated write function from ``elevate_cli.data.*``
  by name with keyword args. The function name is checked against the
  per-pack allowlist and ``elevate_cli.data.__all__``; raw UPDATE/INSERT
  is NOT exposed.

Entitlement gating
------------------
Tables and write namespaces are bucketed per pack:

* ``elevate_core``       — always on. Contacts, identities, conversations,
  events, templates, ingest, agent setup, pack onboarding.
* ``real_estate_sales``  — Leads pack. ``lead_signals``, ``pcs_buyers``,
  ``lead_inquiries``, ``lead_properties``, ``leads_setup_*``, ``send_queue``,
  ``lane_config``.
* ``real_estate_admin``  — Admin pack. ``deals``, ``deal_*``,
  ``agent_handoffs``, ``admin_*``, ``province_*``, ``conditional_docs``.

If the caller asks about a table or write function gated by a pack they
don't own, the tool returns a structured ``requires_entitlement`` error
so the AI can tell the user which package would unlock it.

Concurrency note: this only became feasible after the SQLite → embedded
Postgres cutover. Under SQLite, an AI query during a sync could block on
the single writer lock; now it's a regular MVCC read.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from tools.registry import registry, tool_error, tool_result


# ─── Pack-to-table allowlist ────────────────────────────────────────────

CORE_TABLES: frozenset[str] = frozenset({
    "contacts",
    "identities",
    "identity_conflicts",
    "conversations",
    "events",
    "events_summary",
    "inbound_seen",
    "ingest_runs",
    "meta",
    "notes",
    "templates",
    "thread_meta",
    "agent_setup_items",
    "agent_setup_state",
    "pack_onboarding_items",
    "pack_onboarding_profiles",
    "data_parity_snapshots",
    "draft_attempts",
})

SALES_TABLES: frozenset[str] = frozenset({
    "lead_signals",
    "lead_inquiries",
    "lead_properties",
    "leads_setup_items",
    "leads_setup_state",
    "pcs_buyers",
    "send_queue",
    "lane_config",
})

ADMIN_TABLES: frozenset[str] = frozenset({
    "deals",
    "deal_attachments",
    "deal_contacts",
    "deal_events",
    "agent_handoffs",
    "agent_handoff_messages",
    "admin_action_registry",
    "admin_action_runs",
    "admin_date_trigger_firings",
    "admin_setup_items",
    "admin_setup_profile",
    "conditional_docs",
    "province_checklists",
    "province_forms",
    "province_reference_pages",
})

# Submodule path → required entitlement for any function exported from
# that module. Anything not listed falls under ``elevate_core``.
WRITE_NAMESPACE_PACKS: dict[str, str] = {
    "elevate_cli.data.deals":            "real_estate_admin",
    "elevate_cli.data.dispatch":         "real_estate_admin",
    "elevate_cli.data.agent_handoffs":   "real_estate_admin",
    "elevate_cli.data.admin_setup":      "real_estate_admin",
    "elevate_cli.data.province_guides":  "real_estate_admin",
    "elevate_cli.data.workflow_import":  "real_estate_admin",
    "elevate_cli.data.lead_signals":     "real_estate_sales",
    "elevate_cli.data.leads_setup":      "real_estate_sales",
    "elevate_cli.data.picker":           "real_estate_sales",
    # Working state is contact-default (core); deal-scoped writes are
    # additionally gated inside the helper / tool layer via
    # working_state._enforce_pack(), so elevate_core is the right floor.
    "elevate_cli.data.working_state":    "elevate_core",
}


# ─── Read-only SQL guard ────────────────────────────────────────────────

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|"
    r"copy|vacuum|analyze|reindex|cluster|comment|lock|set|reset|do|call)\b",
    re.IGNORECASE,
)

# Word-boundary table-name extraction. PG identifiers can be quoted, so we
# match either ``"table"`` or a bare ident.
_TABLE_REF = re.compile(
    r'\b(?:from|join)\s+(?:"([a-z_][a-z0-9_]*)"|([a-z_][a-z0-9_]*))',
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    """Drop ``--`` line comments and ``/* */`` block comments before guard."""
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _referenced_tables(sql: str) -> list[str]:
    out: list[str] = []
    for m in _TABLE_REF.finditer(sql):
        name = m.group(1) or m.group(2)
        if name and not name.lower().startswith(("information_schema", "pg_")):
            out.append(name.lower())
    return out


# ─── Entitlement helpers ────────────────────────────────────────────────

def _allowed_tables_for(access_cfg: dict[str, Any] | None) -> set[str]:
    from elevate_cli.access import (
        ENTITLEMENT_REAL_ESTATE_ADMIN,
        ENTITLEMENT_REAL_ESTATE_SALES,
        is_entitlement_active,
    )
    allowed: set[str] = set(CORE_TABLES)
    if is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, access_cfg):
        allowed |= SALES_TABLES
    if is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, access_cfg):
        allowed |= ADMIN_TABLES
    return allowed


def _table_pack(table: str) -> str:
    if table in CORE_TABLES:
        return "elevate_core"
    if table in SALES_TABLES:
        return "real_estate_sales"
    if table in ADMIN_TABLES:
        return "real_estate_admin"
    return "unknown"


def _resolve_data_callable(name: str) -> tuple[Any, str] | tuple[None, None]:
    """Look up ``name`` in ``elevate_cli.data`` and return (fn, source_module).

    Returns ``(None, None)`` if not found or not in ``__all__``.
    """
    from elevate_cli import data as data_pkg
    public = set(getattr(data_pkg, "__all__", []) or [])
    if name not in public:
        return None, None
    fn = getattr(data_pkg, name, None)
    if not callable(fn):
        return None, None
    module = getattr(fn, "__module__", "") or ""
    return fn, module


def _required_pack_for_callable(module: str) -> str:
    return WRITE_NAMESPACE_PACKS.get(module, "elevate_core")


# ─── Action handlers ────────────────────────────────────────────────────

def _action_query(args: dict[str, Any]) -> str:
    sql_raw = str(args.get("sql") or "").strip()
    if not sql_raw:
        return tool_error("missing 'sql'")
    limit = int(args.get("limit") or 200)
    limit = max(1, min(limit, 1000))

    sql = _strip_sql_comments(sql_raw)
    head = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    if head not in ("select", "with"):
        return tool_error("only SELECT / WITH queries are allowed via this tool")
    if _FORBIDDEN_SQL.search(sql):
        return tool_error(
            "query contains a forbidden keyword. Use action='call' for writes."
        )

    allowed = _allowed_tables_for(None)
    refs = _referenced_tables(sql)
    blocked = [t for t in refs if t not in allowed and _table_pack(t) != "unknown"]
    if blocked:
        # Pick the first one for the structured error
        t = blocked[0]
        return tool_result(
            success=False,
            error="requires_entitlement",
            table=t,
            required_pack=_table_pack(t),
            message=(
                f"Table '{t}' is part of the {_table_pack(t)} pack. "
                "User has not purchased it — surface upgrade prompt rather than retry."
            ),
        )
    unknown_refs = [t for t in refs if _table_pack(t) == "unknown"]
    if unknown_refs:
        return tool_error(f"unknown table(s): {', '.join(unknown_refs)}")

    # Append LIMIT if the query doesn't already cap itself.
    if not re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        sql_to_run = sql.rstrip().rstrip(";") + f" LIMIT {limit}"
    else:
        sql_to_run = sql.rstrip().rstrip(";")

    from elevate_cli.data.connection import connect
    with connect() as conn:
        cur = conn.execute(sql_to_run)
        rows = cur.fetchall()
        cols = [d.name for d in (cur.description or [])]
    serialized = [
        {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in dict(r).items()}
        for r in rows
    ]
    return tool_result(success=True, columns=cols, row_count=len(serialized), rows=serialized)


def _action_describe(args: dict[str, Any]) -> str:
    table = (args.get("table") or "").strip().lower() or None
    allowed = _allowed_tables_for(None)

    from elevate_cli.data.connection import connect
    if table is None:
        # Group by pack so the AI can see what's owned vs locked behind upgrades.
        from elevate_cli.access import (
            ENTITLEMENT_REAL_ESTATE_ADMIN,
            ENTITLEMENT_REAL_ESTATE_SALES,
            is_entitlement_active,
        )
        return tool_result(
            success=True,
            packs={
                "elevate_core": sorted(CORE_TABLES),
                "real_estate_sales": {
                    "tables": sorted(SALES_TABLES),
                    "active": is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, None),
                },
                "real_estate_admin": {
                    "tables": sorted(ADMIN_TABLES),
                    "active": is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None),
                },
            },
            visible_tables=sorted(allowed),
        )

    if table not in allowed:
        if _table_pack(table) == "unknown":
            return tool_error(f"unknown table: {table}")
        return tool_result(
            success=False,
            error="requires_entitlement",
            table=table,
            required_pack=_table_pack(table),
        )

    with connect() as conn:
        cols = conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s "
            "ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        if not cols:
            return tool_error(f"table not present in schema: {table}")
        fks = conn.execute(
            """
            SELECT kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_schema='public'
              AND tc.constraint_type='FOREIGN KEY'
              AND tc.table_name=%s
            """,
            (table,),
        ).fetchall()
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    return tool_result(
        success=True,
        table=table,
        pack=_table_pack(table),
        row_count=row_count,
        columns=[dict(c) for c in cols],
        foreign_keys=[dict(f) for f in fks],
    )


def _action_call(args: dict[str, Any]) -> str:
    fn_name = str(args.get("function") or "").strip()
    if not fn_name:
        return tool_error("missing 'function'")
    kwargs = args.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        return tool_error("'kwargs' must be an object")

    fn, module = _resolve_data_callable(fn_name)
    if fn is None:
        return tool_error(
            f"function '{fn_name}' is not part of the public elevate_cli.data API"
        )

    required_pack = _required_pack_for_callable(module)
    from elevate_cli.access import is_entitlement_active
    if required_pack != "elevate_core" and not is_entitlement_active(required_pack, None):
        return tool_result(
            success=False,
            error="requires_entitlement",
            function=fn_name,
            module=module,
            required_pack=required_pack,
            message=(
                f"Function '{fn_name}' belongs to the {required_pack} pack. "
                "User has not purchased it — surface upgrade prompt rather than retry."
            ),
        )

    from elevate_cli.data.connection import connect, transaction
    try:
        with connect() as conn:
            with transaction(conn):
                result = fn(conn, **kwargs)
    except TypeError as exc:
        # Bad kwargs — surface to the AI so it can correct itself.
        return tool_error(f"call to {fn_name} rejected: {exc}")
    except Exception as exc:
        return tool_error(f"{type(exc).__name__}: {exc}")

    # Normalize return for JSON serialization.
    if hasattr(result, "isoformat"):
        payload = result.isoformat()
    elif isinstance(result, (str, int, float, bool, type(None), list, dict)):
        payload = result
    else:
        try:
            payload = dict(result)  # dict-like (PgRow)
        except Exception:
            payload = repr(result)
    return tool_result(success=True, function=fn_name, module=module, result=payload)


# ─── Tool handler + schema ──────────────────────────────────────────────

_ACTIONS = {
    "query": _action_query,
    "describe": _action_describe,
    "call": _action_call,
}


def _elevate_db_handler(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "").strip().lower()
    handler = _ACTIONS.get(action)
    if handler is None:
        return tool_error(
            f"unknown action '{action}'. Use one of: query, describe, call."
        )
    try:
        return handler(args)
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")


ELEVATE_DB_SCHEMA = {
    "type": "function",
    "function": {
        "name": "elevate_db",
        "description": (
            "Direct, gated access to the operational source-of-truth database "
            "(embedded Postgres). Three actions:\n"
            "  • query    — read-only SELECT / WITH against owned tables\n"
            "  • describe — list owned tables and columns, or one table's schema\n"
            "  • call     — invoke a curated write function from elevate_cli.data "
            "(structured writes only; raw UPDATE/INSERT is not exposed)\n"
            "Tables and write functions are bucketed per purchased pack "
            "(elevate_core / real_estate_sales / real_estate_admin). Asking "
            "about an un-owned table returns a structured 'requires_entitlement' "
            "error — surface that as an upgrade prompt, do not retry. Use this "
            "whenever the user asks about contacts, leads, deals, conversations, "
            "templates, signals, or any other operational record."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query", "describe", "call"],
                    "description": "Which operation to perform.",
                },
                "sql": {
                    "type": "string",
                    "description": (
                        "(action=query) Read-only SELECT or WITH ... SELECT. "
                        "Will be LIMIT-capped if no LIMIT is present."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "(action=query) Row cap. Default 200, max 1000.",
                },
                "table": {
                    "type": "string",
                    "description": (
                        "(action=describe) Single table name. Omit to list all "
                        "tables grouped by pack."
                    ),
                },
                "function": {
                    "type": "string",
                    "description": (
                        "(action=call) Function name from elevate_cli.data "
                        "(e.g. 'upsert_contact', 'create_deal', "
                        "'record_inbound', 'set_pipeline_status')."
                    ),
                },
                "kwargs": {
                    "type": "object",
                    "description": (
                        "(action=call) Keyword arguments passed to the function "
                        "after the implicit `conn` first arg."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


registry.register(
    name="elevate_db",
    toolset="elevate_db",
    schema=ELEVATE_DB_SCHEMA,
    handler=_elevate_db_handler,
    description=(
        "Read/describe/write the operational PG store. Per-pack entitlement "
        "gated; structured writes only."
    ),
    emoji="",
)
