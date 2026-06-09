# Compliance Reviewer Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | Flags: one per gap, with owner, severity, and consequence date; review-queue items |
| `create_approval` / `list_approvals` | Gate the rare client- or broker-facing summary; never self-deliver |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Review summaries; urgent escalation notices; re-verification results |
| `write_memory` / `list_memory` | Gap patterns, checklist refinements, process quirks — never PII |
| `get_surface_config` / `update_surface_config` | Read/update this surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Tune review cadence and flag wording against resolution outcomes |

## Handoffs
Use agent handoff to route work: every fix-task and urgent escalation → `admin`; cross-domain routing and stuck-flag escalation to the human → `executive-assistant`.

## Dashboard surfaces
Flags live on the `admin` board. The realtor sees flags as tasks with severities, review summaries in Activity, the occasional gated summary in Approvals, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/` (review records per file), and the checklist playbook live in the agent workspace as markdown.

## Never
Never edit or fill anything in a deal file. Never transcribe ID numbers or personal details into any output. Never interpret legal sufficiency. Never send externally without an approval.
