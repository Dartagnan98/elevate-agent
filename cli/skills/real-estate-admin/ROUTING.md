# Elevate Agent Routing

Shared routing reference for every Elevate agent (Admin, Leads, Sales).
Read this instead of inspecting source code. It is the standard answer to
"where does this data live" and "what do I start up".

## Databases — where to route a question

All stores are local SQLite under `~/.elevate/`. Route by intent:

| Need | Database | Path |
| --- | --- | --- |
| Setup / onboarding state, deal files, CRM contacts, conversations, province guide source rows, admin actions | **operational.db** | `~/.elevate/data/operational.db` |
| Searchable recall — facts, source documents, province guide corpus, past knowledge | **memory_store.db** | `~/.elevate/memory_store.db` |
| Session + message history, per-turn token usage | **state.db** | `~/.elevate/state.db` |
| Cron / scheduled agent runs and their events | **orchestration.db** | `~/.elevate/orchestration.db` |
| Outreach templates and lane configs | **outreach.db** | `~/.elevate/tools/data/outreach/outreach.db` |
| Cached model responses | **response_store.db** | `~/.elevate/response_store.db` |
| Token usage ledger | **usage_ledger.sqlite** | `~/.elevate/usage_ledger.sqlite` |

### operational.db — source of truth
The migrated operational store. Treat its rows as authoritative; never guess
a value that lives here.
- `admin_setup_items` / `admin_setup_profile` — Admin onboarding + provider config
- `leads_setup_items` — Leads onboarding (lead sources, outreach channels, policy)
- `agent_setup_items` — agent runtime config (models, memory, channels)
- `pack_onboarding_items` / `pack_onboarding_profiles` — per-pack setup contracts
- `province_reference_pages` / `province_checklists` / `province_forms` — the
  province admin guide corpus (the searchable copy lives in memory_store.db)
- `admin_action_registry` / `admin_action_runs` — Admin board actions and runs
- deal, contact, conversation, and event tables — deal-file working data

### memory_store.db — searchable recall
The holographic memory store. This is what `fact_store` (search, probe,
document_search) and durable recall read. Source documents carry a
`source_type`; `province_guide` holds the full provincial admin guide,
ingested by `province_guide_memory.sync_province_guide_to_memory`. To recall
guide material, `document_search` with `source_type='province_guide'` — do
not re-read the operational.db rows for that.

## Services — what is already running, what NOT to start

Services are launchd-managed on macOS. They are `KeepAlive`. The agent runs
*inside* the gateway — it does not own the process lifecycle.

- **Do NOT** start, stop, restart, or `kill` any of these. Do not run
  `elevate gateway`, `npm run`, or relaunch the app to "fix" something.
- `ai.elevate.gateway` — the agent gateway. Always up via launchd.
- `ai.elevate.debugchrome` — visible debug Chrome for browser-use. Auto-
  provisions on first browser-tool use; do not launch Chrome manually.
- Connector sync jobs (`apple-messages` / `crm` / `social`) — launchd timers
  that pull into operational.db on their own schedule.

If a service is genuinely down, that is a `waiting_human` condition: report
it with the exact symptom. Do not try to repair infrastructure mid-task.

## Default posture
- Read state from the database above that owns it; do not parse code to learn
  schema or behaviour.
- Treat operational.db as truth, memory_store.db as recall.
- Never manage processes. Never start services.
