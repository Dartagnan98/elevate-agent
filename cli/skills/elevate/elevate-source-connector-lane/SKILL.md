---
name: elevate-source-connector-lane
description: Add or modify a local Elevate source connector lane/tab for a dashboard source section. Use when a user wants a new dashboard source button/import lane like Paid Ads, Website Leads, or Referral Sources, feeding sections such as Leads, Outreach, Today, or Approvals.
---

# Elevate source connector lane

Use this when adding a reusable dashboard source/import lane. Example: adding a **Paid Ads** button to the Leads dashboard that can receive imported leads without mixing them into Lofty CRM, Apple Messages, Gmail/Composio, or other existing sources.

## Key model

- Source buttons on `/leads` are generated from the source inbox response, not hardcoded per label in the frontend.
- Connector metadata is registered in `elevate_cli/source_connectors.py`:
  - `SOURCE_CONNECTION_BLUEPRINTS`
  - `SOURCE_CATEGORIES`
  - `OWNER_BY_SOURCE`
  - `UI_BY_SOURCE`
- Runtime source data lives under:
  - `~/.elevate/tools/data/sources/<source-id>/`
- Required source files are usually:
  - `source.json`
  - `status.json`
  - `contacts.jsonl`
  - `conversations.jsonl`
  - `messages.jsonl`
  - `message-days.jsonl`
  - `lead-events.jsonl`
  - `tasks.jsonl`
  - `artifacts/`

## Steps

1. **Locate the active runtime override**
   - In local app development, `~/Elevation/elevate_cli/__init__.py` (or the tenant's equivalent local override root) extends the package path back to the signed app bundle, so a local file such as `~/Elevation/elevate_cli/source_connectors.py` can override the packaged module.
   - Check the dashboard process cwd with `ps` or `lsof`; if it is running from that local override root, local overrides are likely active.
   - Do not edit the signed app bundle unless there is no local override path and the user explicitly wants that risk.

2. **Add the source blueprint**
   - Add a new item to `SOURCE_CONNECTION_BLUEPRINTS`.
   - Use a stable lowercase id such as `paid-ads`, `website-leads`, or `referrals`.
   - Set a clear operator-facing label in `source`, for example `Paid Ads`.
   - Pick a category. If needed, add a new `SOURCE_CATEGORIES` entry such as:
     - `id: leads`
     - `label: Lead sources`
   - Write descriptions in operator terms, not client-facing copy.

3. **Map ownership and surfaces**
   - Add the source id to `OWNER_BY_SOURCE`, usually `Outreach` for lead sources.
   - Add the source id to `UI_BY_SOURCE`, for example:
     - `['Leads', 'Outreach', 'Today', 'Approvals']`
   - Keep sends approval-gated. A source lane should not imply automatic sending.

4. **Create the local source directory**
   - Create `~/.elevate/tools/data/sources/<source-id>/`.
   - Write `source.json` with fields like:
     - `source_id`
     - `provider`
     - `account_label`
     - `connection_type`
     - `auth_status`
     - `sync_mode`
     - `owner_agent`
     - `enabled_ui_surfaces`
     - `setup_status`
     - `setup_notes`
   - Write `status.json` with:
     - `connected: true`
     - `import_only: true` for manual/import-only lanes
     - `blocked: false`
     - `next_operator_step`
     - `last_checked_at`
     - `counts`
   - Create empty canonical JSONL files and an `artifacts/` directory.

5. **Optional: add a safe import helper**
   - For CSV/import lanes, add a script under `artifacts/`, for example `import_paid_ads_csv.py`.
   - The helper should write normalized JSONL records only. It should not send, approve, queue, or auto-release outreach.
   - Include a template CSV in `artifacts/` with expected columns.
   - For lead sources, preserve campaign/platform metadata in internal fields, but do not generate client-facing draft language such as “came through Google” or “came through Paid Ads.”

6. **Verify without using online/browser tools**
   - Use the app runtime Python if dependencies like `psycopg` are needed:
     - `/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12`
   - Compile modified Python:
     - `python3.12 -m py_compile elevate_cli/source_connectors.py <import-helper>.py`
   - Verify the source appears in Python response builders:
     ```python
     from elevate_cli.source_connectors import build_source_inbox_response, build_source_connectors_response
     r = build_source_inbox_response(limit=1)
     [s for s in r['sources'] if s['id'] == '<source-id>']
     ```
   - Also verify connector metadata:
     ```python
     cr = build_source_connectors_response(include_prompts=False)
     [s for s in cr['connectors'] if s['id'] == '<source-id>']
     ```

## Pitfalls

- `/api/source-inbox` may prefer `db_source_inbox_response()` and only fall back to JSONL. Connector metadata still comes from `SOURCE_CONNECTION_BLUEPRINTS` and `connector_view()`, so source registration and local `source.json/status.json` matter even for DB-primary dashboards.
- The frontend source buttons are generated from `sources`, drafts, and profile/thread source IDs. A connected/import-only source with zero records can still appear as a source button, depending on the UI filter logic.
- System `python3` may lack runtime dependencies. Prefer the bundled app Python for Elevate internals.
- Do not expose raw internal source labels in outreach drafts. For paid ads or Making It Rain style leads, client-facing copy should use natural wording like website/home-search/contact-cleanup language.
- Do not create tasks that auto-send. Source import lanes should create records and, if needed, approval-gated draft tasks only.

## Example outcome

For a `paid-ads` lane:

- `SOURCE_CONNECTION_BLUEPRINTS` includes `id: paid-ads`, `source: Paid Ads`, `category: leads`.
- `OWNER_BY_SOURCE['paid-ads'] = 'Outreach'`.
- `UI_BY_SOURCE['paid-ads'] = ['Leads', 'Outreach', 'Today', 'Approvals']`.
- `~/.elevate/tools/data/sources/paid-ads/` contains the canonical JSONL files, `source.json`, `status.json`, and import artifacts.
- Verification returns a `Paid Ads` connector with `connected: true`, `importOnly: true`, and the expected `sourceDir`.
