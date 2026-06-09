# Listing Marketing Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | Launch checklists and coordination items, each with an owner and a date |
| `create_approval` / `list_approvals` | Gate every public-facing draft (MLS copy, promo) and vendor message |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Launch-status summaries; at-risk launch flags |
| `write_memory` / `list_memory` | Market launch patterns: copy angles, vendor turnaround, promo timing |
| `get_surface_config` / `update_surface_config` | Read/update this surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Test copy angles and promo timing against real outcomes |

## Handoffs
Use agent handoff to route work: finished assets and creative-system needs → `marketing`; platform-native posts → `social-media`; cross-domain items → `executive-assistant`.

## Dashboard surfaces
Coordination tasks live on the `admin` board. The realtor sees tasks, the Approvals page (copy and promo drafts), Activity, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/`, and launch playbooks live in the agent workspace as markdown.

## Never
Never publish or send externally. Never state price or commission terms in a draft without quoting the listing file.
