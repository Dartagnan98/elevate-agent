# Sphere Farming Tools

## agent_bus actions

| Action | Use |
|--------|-----|
| `create_task` / `list_tasks` / `claim_task` / `update_task` / `complete_task` / `block_task` | Touch calendar entries (date + reason), farm-sequence steps, "needs detail" asks |
| `create_approval` / `list_approvals` | Gate every touch draft; watch date-tied drafts for staleness |
| `update_heartbeat` | First call of every cycle |
| `post_activity` / `log_event` | Program-health summaries; late-touch and stale-approval flags |
| `write_memory` / `list_memory` | Contact history detail, touch angles that work, farm response patterns |
| `get_surface_config` / `update_surface_config` | Read/update this surface's DB-backed config |
| `get_goals` / `update_goals` | Read and progress the starter goals |
| `list_cycles` / `create_cycle` / `modify_cycle` / `remove_cycle` | Experiment cycles on this surface |
| `create_experiment` / `run_experiment` / `evaluate_experiment` / `list_experiments` | Test touch angles, farm cadence, and ask timing against replies and referrals |

## Handoffs
Use agent handoff to route work: replies and live buying/selling/referral intent → `outreach`; creative templates, brand campaigns, and email infrastructure → `marketing`.

## Dashboard surfaces
Relationship programs track on the `leads` board; operational items on `admin`. The realtor sees touch drafts in Approvals, program health in Activity, the touch calendar as tasks, and the Heartbeat page.

## File artifacts
`learnings.md`, `history/`, and program playbooks (touch cadences, farm sequences) live in the agent workspace as markdown.

## Never
Never send to a contact. Never state a specific home's value. Never cold-ask for referrals. Never touch an opted-out contact.
