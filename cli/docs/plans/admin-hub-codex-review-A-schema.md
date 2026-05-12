## 1. Schema fit

The Admin Hub deal model fits the existing operational store, but the proposed storage location is wrong. The plan correctly says the `elevate-agent` repo owns "the SQLite store + `/api/admin/*` REST + dispatcher + registry schema" for the Admin Hub (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:15`), but then contradicts itself by putting runtime state in "the new `data/operational.db` SQLite store" (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:17`) and by defining primitive B as "`~/.elevate/data/operational.db` + `~/.elevate/data/deal-events.jsonl`" (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:120`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:122`). Existing code says the opposite: `elevate_cli.data` "Lives at `$ELEVATE_HOME/data/operational.db`" and owns every read/write, with call sites importing data functions instead of raw `sqlite3.connect` (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:1`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:5`).

The database path is already centralized: the layout documents `$ELEVATE_HOME/data/operational.db` as the central SQLite store (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/paths.py:7`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/paths.py:15`), and `operational_db_path()` returns `data_root() / "operational.db"` (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/paths.py:33`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/paths.py:35`). The first migration is explicitly "Initial schema for `$ELEVATE_HOME/data/operational.db`" (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:1`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:2`), and the connection helper opens `operational_db_path()`, applies migrations, commits on success, and rolls back on error (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/connection.py:65`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/connection.py:86`). A separate `client-specific.db` would bypass that migration runner, PRAGMA setup, rollback behavior, and test isolation.

The model itself belongs as new operational tables. Existing `contacts` already gives a natural optional FK target for the card's person or client (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:31`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:52`), while the plan requires persisted phase moves and emitted `deal_events` (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:127`). The plan's schema detail is also incomplete: it claims "Toggle set on each deal (24 fields)" but only names 7 enum fields and 12 yes/no fields (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:145`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:147`). The first migration should not invent the missing five; it should model the named fields and leave a clear extension point or defer the unnamed columns.

The Python module should mirror `templates.py`, not create a parallel DB layer. `templates.py` takes an already-open `sqlite3.Connection`, normalizes rows through `_row_to_template`, and returns API-shaped dictionaries (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:46`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:82`). Its reads accept `conn` and query the operational tables directly (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:88`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:125`), and its lifecycle writes generate ids/timestamps, insert or update, then return the normalized row (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:131`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:192`). Admin endpoints already follow that pattern by importing helpers from `elevate_cli.data` inside the route and wrapping work in `with connect() as conn` (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/web_server.py:3163`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/web_server.py:3170`).

## 2. Migration design

The next migration number is `0003` because the existing directory contains `0001_init.sql` and `0002_identity_conflicts_unique.sql`; `0002` is already a numbered SQL migration (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0002_identity_conflicts_unique.sql:1`). This should be an append-only DDL file because the initial migration says shipped schema edits become numbered `0002_*.sql` migrations, not rewrites (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:9`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0001_init.sql:12`), and the migration runner validates `NNNN_name.sql` filenames, discovers SQL files, and applies them in sorted order (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations.py:34`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations.py:84`).

Smallest workable first migration:

```sql
-- 0003_admin_hub_deals.sql
-- Admin Hub deal workflow state for $ELEVATE_HOME/data/operational.db.

CREATE TABLE IF NOT EXISTS deals (
    id                       TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    side                     TEXT NOT NULL
                                 CHECK (side IN ('listing','buyer')),
    current_stage            INTEGER NOT NULL DEFAULT 0
                                 CHECK (current_stage BETWEEN 0 AND 9),
    status                   TEXT NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active','closed','archived')),
    province                 TEXT NOT NULL DEFAULT 'BC',
    primary_contact_id       TEXT,
    lofty_contact_id         TEXT,
    listing_address          TEXT,

    -- Named enum/toggle fields from the plan. Keep enum values as TEXT in
    -- 0003 because the plan names fields but not allowed enum values.
    signing_authority        TEXT,
    fintrac_form_type        TEXT,
    listing_track            TEXT,
    property_subtype         TEXT,
    estate_status            TEXT,
    transaction_type         TEXT,
    listing_type             TEXT,

    pep                      INTEGER CHECK (pep IN (0,1)),
    tenanted                 INTEGER CHECK (tenanted IN (0,1)),
    poa_signing              INTEGER CHECK (poa_signing IN (0,1)),
    corporate                INTEGER CHECK (corporate IN (0,1)),
    has_suite                INTEGER CHECK (has_suite IN (0,1)),
    multiple_offers          INTEGER CHECK (multiple_offers IN (0,1)),
    family_member            INTEGER CHECK (family_member IN (0,1)),
    dual_rep                 INTEGER CHECK (dual_rep IN (0,1)),
    unrepresented_other_side INTEGER CHECK (unrepresented_other_side IN (0,1)),
    lockbox                  INTEGER CHECK (lockbox IN (0,1)),
    delayed_offer            INTEGER CHECK (delayed_offer IN (0,1)),
    sale_of_buyers_property  INTEGER CHECK (sale_of_buyers_property IN (0,1)),

    extra_toggles_json       TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    stage_entered_at         TEXT NOT NULL,
    closed_at                TEXT,

    FOREIGN KEY(primary_contact_id) REFERENCES contacts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_side_stage_status
    ON deals(side, current_stage, status);
CREATE INDEX IF NOT EXISTS idx_deals_contact
    ON deals(primary_contact_id) WHERE primary_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deals_updated_at
    ON deals(updated_at);

CREATE TABLE IF NOT EXISTS deal_events (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL,
    kind            TEXT NOT NULL
                        CHECK (kind IN ('created','stage_transition','toggle_change')),
    actor           TEXT NOT NULL,
    from_stage      INTEGER CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage        INTEGER CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    field_name      TEXT,
    old_value_json  TEXT,
    new_value_json  TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,

    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE CASCADE,
    CHECK (kind != 'stage_transition' OR to_stage IS NOT NULL),
    CHECK (kind != 'toggle_change' OR field_name IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_deal_events_deal_created
    ON deal_events(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_kind_created
    ON deal_events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_field_created
    ON deal_events(field_name, created_at)
    WHERE field_name IS NOT NULL;
```

Indexes are intentionally limited to the first API shapes: kanban grouping by `side/current_stage/status`, contact drill-in, recent updates, and event-log reads by deal/kind/field. The first migration should defer `pending_items` and `conditional_docs`, which the plan attaches to later toggle-driven dispatch (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:149`), dispatcher run ids and action execution wiring (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:180`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:188`), Outputs-tab artifact linkage (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:202`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:206`), province guide/reference tables (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:165`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:170`), and SkySlope read/write adapter state (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:224`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:225`). Phase A's exit criteria are just persisted card moves across browsers and province-swapped checklist content (`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:157`-`/Users/dartagnanpatricio/elevate/cli/docs/plans/admin-hub-agentic-workflow-plan.md:173`), so stricter enum value checks can also wait until the source values are named.

## 3. Module shape

`elevate_cli/data/deals.py` should look like a sibling of `templates.py`: row conversion first, read helpers next, then lifecycle writes. That mirrors the visible "Reads" and "Lifecycle" split in `templates.py` (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:85`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:131`), the explicit `conn: sqlite3.Connection` signatures (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:88`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:104`), and the write methods that validate, update, and return the normalized row (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:131`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/templates.py:192`). It should also be re-exported from `elevate_cli.data`, as templates are imported and exposed there (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:99`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:113`, `/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:152`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py:157`).

```python
from __future__ import annotations

import sqlite3
from typing import Any, Mapping


def _row_to_deal(row: sqlite3.Row) -> dict[str, Any]:
    """Normalize one deals row into the Admin Hub API shape."""
    ...


def _row_to_deal_event(row: sqlite3.Row) -> dict[str, Any]:
    """Normalize one deal_events row and decode JSON value fields."""
    ...


def get_deal(conn: sqlite3.Connection, deal_id: str) -> dict[str, Any] | None:
    """Return one deal by id, or None when it does not exist."""
    ...


def list_deals(
    conn: sqlite3.Connection,
    *,
    side: str | None = None,
    current_stage: int | None = None,
    status: str | None = "active",
    primary_contact_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List deals for kanban columns and admin filters."""
    ...


def create_deal(
    conn: sqlite3.Connection,
    *,
    title: str,
    side: str,
    actor: str,
    province: str = "BC",
    current_stage: int = 0,
    primary_contact_id: str | None = None,
    lofty_contact_id: str | None = None,
    listing_address: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a deal, apply initial field values, and append a created event."""
    ...


def move_deal_stage(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    to_stage: int,
    actor: str,
) -> dict[str, Any]:
    """Move a deal to a 0-9 stage and append a stage_transition event."""
    ...


def set_deal_toggle(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    field: str,
    value: Any,
    actor: str,
) -> dict[str, Any]:
    """Update one named toggle or enum field and append a toggle_change event."""
    ...


def list_deal_events(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the newest stage/toggle events for one deal."""
    ...
```

The first endpoint should follow the existing admin-template route shape, not open its own database. The current endpoint file imports data helpers inside route handlers, calls `connect()`, and maps `ValueError`/`LookupError`/`PermissionError` to HTTP errors (`/Users/dartagnanpatricio/elevate/cli/elevate_cli/web_server.py:3142`-`/Users/dartagnanpatricio/elevate/cli/elevate_cli/web_server.py:3210`). The endpoint tests already use `TestClient` with the session header (`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:33`-`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:40`), data helpers that write through `connect()` (`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:43`-`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:58`), and an auth-gating sanity test for `/api/admin/templates` (`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:237`-`/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_templates_endpoints.py:243`).

## 4. First-PR punch list

1. `/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/migrations/0003_admin_hub_deals.sql` - add `deals` and `deal_events` to `operational.db` with stage, side, named toggle fields, FKs, and indexes.
2. `/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/deals.py` - implement connection-accepting read/lifecycle helpers and append `deal_events` inside move/toggle writes.
3. `/Users/dartagnanpatricio/elevate/cli/elevate_cli/data/__init__.py` - re-export the deals helpers so web routes import from `elevate_cli.data` like the template endpoints.
4. `/Users/dartagnanpatricio/elevate/cli/elevate_cli/web_server.py` - add the first `/api/admin/deals` list/create route using `with connect() as conn` and the same HTTP error mapping as `/api/admin/templates`.
5. `/Users/dartagnanpatricio/elevate/cli/tests/elevate_cli/test_admin_deals_endpoints.py` - add hermetic FastAPI tests for create/list plus unauthenticated rejection, mirroring the admin-template endpoint test shape.
