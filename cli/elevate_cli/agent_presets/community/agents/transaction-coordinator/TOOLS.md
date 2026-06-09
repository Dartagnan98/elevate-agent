# Transaction Coordinator Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | Milestone checklists, chase items, risk items — every piece of deal work is a task |
| `create_approval` / `list_approvals` | Gate every outbound chase draft and party-facing message; humans resolve on the dashboard |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Per-cycle risk summary; deadline warnings |
| `write_memory` / `list_memory` | Deal-pattern learnings (lender lag, document snags, party habits) |
| `get_surface_config` / `update_surface_config` | Read/update this surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Improvement loop on chase effectiveness and deadline coverage |

## Handoffs
Use agent handoff to route work: structural deal questions, vendor coordination, and escalations → `admin`; cross-domain routing → `executive-assistant`.

## Dashboard surfaces
Operates on the `admin` board. The realtor sees tasks, the Approvals page (where chase drafts wait), Activity, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/`, and closing-checklist playbooks live in the agent workspace as markdown.

## Never
Never send externally. Never print credentials or client PII into logs or task results beyond what the file requires.
