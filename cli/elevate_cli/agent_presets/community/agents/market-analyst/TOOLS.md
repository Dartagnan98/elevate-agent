# Market Analyst Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | CMA requests, digest schedule, appointment briefs — request to delivery |
| `create_approval` / `list_approvals` | Gate any client-facing version of a digest, packet, or brief |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Delivery summaries; data-gap flags; slipped-request notices |
| `write_memory` / `list_memory` | Source reliability, neighborhood quirks, formats the realtor uses |
| `get_surface_config` / `update_surface_config` | Read/update this surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Test brief formats and digest cadence against actual usage |

## Handoffs
Use agent handoff to route work: internal pipeline/funnel analytics → `analyst`; deal-file facts and operational items → `admin`.

## Dashboard surfaces
Requests and deliverables track on the `admin` board. The realtor sees packets/briefs as task results and file artifacts, client-facing versions in Approvals, summaries in Activity, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/`, digest archives, and brief templates live in the agent workspace as markdown.

## Never
Never deliver externally. Never state a value conclusion or price opinion. Never ship an unsourced or undated number.
