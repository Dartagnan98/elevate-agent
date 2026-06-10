# Elevate Agent Routing

Shared routing reference for every Elevate agent (Admin, Leads, Sales).
Read this instead of inspecting source code. It is the standard answer to
"where does this data live" and "what do I start up".

## The operational store — where to route a question

All agent-facing state lives in ONE per-account embedded Postgres database
(`elevate_op_<account_key>`), managed by the app. The old per-domain SQLite
files (`operational.db`, `outreach.db`, `orchestration.db`, `state.db`,
`response_store.db`, `memory_store.db`, `usage_ledger.sqlite`) were imported
one-shot and are now frozen archives — never open them, and never run raw
`sqlite3`/`psql`. Route by intent, tools first:

| Need | Use |
| --- | --- |
| Deal files, checklists, stages, run closure | **`admin_deal`** tool (+ `deals_overview`); close runs per `admin-result-writer` |
| CRM contacts, conversations, source threads, drafts | source-inbox / connector tools (+ `leads_overview`) |
| Searchable recall — facts, source documents, province guide corpus, past knowledge | **`fact_store`** (search, probe, document_search) |
| Surface state — config, goals, cycles, experiments, run index, activity, heartbeats | **`agent_bus`** (get/update_surface_config, get/update_goals, list_cycles + cycle CRUD, experiments, log_run/run_count, post_activity/list_activity, update_heartbeat) |
| Tasks and approvals | **`agent_bus`** (create/list/claim/complete tasks, create/list approvals) or dashboard `/api/surface-tasks` + `/api/surface-approvals` |
| Outreach templates and lane configs | **`outreach_templates(...)`** tool; dashboard `/api/outreach/templates*` + `/api/lanes*` |
| Ad-hoc reads/writes no tool covers | **`elevate_db`** (SQL through the Elevate data layer) — last resort, never raw `sqlite3`/`psql` |
| Session history, cron run events, cached model responses, token ledger | runtime-owned tables; not agent source-of-truth — leave them alone unless explicitly asked |

### Operational store — source of truth
Treat its rows as authoritative; never guess a value that lives here.
- `admin_setup_items` / `admin_setup_profile` — Admin onboarding + provider config
- `leads_setup_items` — Leads onboarding (lead sources, outreach channels, policy)
- `agent_setup_items` — agent runtime config (models, memory, channels)
- `pack_onboarding_items` / `pack_onboarding_profiles` — per-pack setup contracts
- `province_reference_pages` / `province_checklists` / `province_forms` — the
  province admin guide corpus (the searchable copy lives in the memory tables)
- `admin_action_registry` / `admin_action_runs` — Admin board actions and runs
- deal, contact, conversation, and event tables — deal-file working data

### Memory — searchable recall
The holographic memory store lives in the same database (`memory_facts`,
source documents, embeddings). This is what `fact_store` (search, probe,
document_search) and durable recall read. Source documents carry a
`source_type`; `province_guide` holds the full provincial admin guide,
ingested by `province_guide_memory.sync_province_guide_to_memory`. To recall
guide material, `document_search` with `source_type='province_guide'` — do
not re-read the operational deal/reference rows for that.

### What legitimately stays file-based
Markdown artifacts only: surface workspace `learnings.md`, `history/` run
records, playbooks, `experiments/results.tsv`; session `*.jsonl` transcripts;
cron job definitions under `accounts/<key>/cron/`. JSON state files that used
to live in `heartbeats/<surface>/` (`config.json`, `goals.json`,
`heartbeat.json`, `experiments/*.json`, `agent_activity.jsonl`) are frozen
archives — read/write that state through `agent_bus` instead.

## Services — what is already running, what NOT to start

Services are launchd-managed on macOS. They are `KeepAlive`. The agent runs
*inside* the gateway — it does not own the process lifecycle.

- **Do NOT** start, stop, restart, or `kill` any of these. Do not run
  `elevate gateway`, `npm run`, or relaunch the app to "fix" something.
- `ai.elevate.gateway` — the agent gateway. Always up via launchd.
- `ai.elevate.debugchrome` — visible debug Chrome for browser-use. Auto-
  provisions on first browser-tool use; do not launch Chrome manually.
- Connector sync jobs (`apple-messages` / `crm` / `social`) — launchd timers
  that pull into the operational store on their own schedule.

If a service is genuinely down, that is a `waiting_human` condition: report
it with the exact symptom. Do not try to repair infrastructure mid-task.

## Default posture
- Read state from the tool/table above that owns it; do not parse code to learn
  schema or behaviour.
- Treat the operational store as truth, `fact_store` memory as recall.
- Never manage processes. Never start services.
