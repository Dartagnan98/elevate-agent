# ISA Lead Nurture Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | Cadence touches with next-touch dates; lane work items |
| `create_approval` / `list_approvals` | Gate every lead-facing draft; watch for time-sensitive approvals going stale |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Lane-health summaries; hot-lead flags; opt-out notices |
| `write_memory` / `list_memory` | Reply patterns, angle learnings, source quality, voice notes |
| `get_surface_config` / `update_surface_config` | Read/update the leads surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Test touch angles, timing, and cadence spacing against reply outcomes |

## Handoffs
Use agent handoff to route work: responding/qualified leads and anything pricing/legal/emotional → `outreach`; cross-domain items → `executive-assistant`.

## Dashboard surfaces
Operates on the `leads` board and its lanes (new outreach, hot leads, follow-ups). The realtor sees drafts in Approvals, lane summaries in Activity, tasks, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/`, and cadence playbooks live in the agent workspace as markdown.

## Never
Never send to a lead. Never contact an opted-out lead. Never promise pricing, terms, or availability in a draft.
