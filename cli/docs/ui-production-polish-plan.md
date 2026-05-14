# Elevate UI production polish plan

Started 2026-05-13. Goal: ship-ready realtor UI through small, verifiable slices.
Working out of `cli/web/src/`. Build verified after every slice (`npx tsc -b && npm run build`).

## Method

- Touch one surface per slice. tsc + vite must both stay green.
- Stage by file name, never `git add -A`.
- Each slice ends in a local commit, message scoped to the surface.
- ChatPage.tsx and PageHeaderProvider.tsx are dirty user work — do not touch.
- Audit findings are recorded here; "DONE" lines below mark verified ship.

## Already shipped this session (pre-goal context)

- `/today` redesigned (pulse strip, priority queue, day shape, running strip).
- `/today` lazy-loaded into its own chunk.
- Draft rows on `/leads` clean up RFC822 envelopes; provenance deduped; terracotta stripe killed.
- Lane sections on `/leads` compacted (title + count only, empty-state collapses to one line).

## Audit by page

### P0 — must fix before this counts as production

1. **Tasks page** lists six surfaces (handoffs, worker, deal tasks, action runs, timed tasks, sessions×2) but **no approval queue**.
   The page name promises action; the content is a status dump. → Restructure around "what needs me right now": waiting-human handoffs and pending deal tasks become the headline, everything else moves below.
2. **Agent Hub** handoff card shows counts + worker state but the "next action" is buried.
   When the worker is unhealthy the user shouldn't have to read six chips to find the fix. → Surface the single most-important call to action as a primary affordance.
3. **Outreach lanes vs Automations vs Tasks** — same operational concept (timed jobs) rendered three different ways. → Make the relationship visible: the lanes block on `/leads` already lists the cron jobs, but the styling makes it look like a different system. Reuse the same row UI, label both as "Automations" sub-views.
4. **Cron page row width**: schedule, last, next all crammed on one line; with long names the row overflows on tablet. → Stack schedule on its own line under the title on `<lg`.

### P1 — visible polish

5. **AgentHubPage AgentCard** — `MiniMetric` shows "Sessions / Active" with no context; for a realtor this is meaningless. Either retitle to "Last 24h" / "Live now" or drop and show last run timestamp.
6. **AgentHubPage Telegram lane card** — state strings ("Missing bot token", "Duplicate bot token") are correct but the action ("paste from BotFather here") isn't obvious. The Save button doesn't enable until both fields have values; the form should say so.
7. **Memory page WorkflowStrip** — six counters of backend table sizes (facts, entities, documents, chunks, communities, relations) — none of these help a realtor decide anything. → Replace strip with two meaningful tiles (pipeline health + most-recently-ingested session) and drop the rest.
8. **Social media page** — `summaryStats` four tiles always render even when zero. Heavy `py-12` empty state in the idea queue. → Collapse summary to one line until there is data, tighten the empty state.
9. **Memory page graph card** — `min-h-[38rem]` even when there are zero nodes. → Set a max-height fallback and an inline empty state for the empty graph.
10. **Sidebar Automations section** — uses its own custom collapse button while the other section labels use the shared `SidebarSectionLabel`. → Unify to one component so visual rhythm holds.

### P2 — quality cleanup

11. **Tasks WorkflowStrip** repeats "Task errors" and "Memory queue" which appear nowhere else on the page — they belong on Memory and Cron respectively.
12. **Today page** uses `Home` icon. Hub title is "Elevate Agent · Today" — drop the "Elevate Agent" prefix (every page already lives inside Elevate; redundant).
13. **HubShell hero copy** on Tasks, Memory, Social — long marketing-style sentences. Strip or shorten to 1 short clause.
14. **Cron form** — "New job" card is full-width above the list. Most users come to this page to look at existing jobs. → Collapse create form behind a button until they need it.
15. **Social media `refresh from platforms` button** — uppercase mono, 44px min height. Way too loud. → Standard small button.

## Implementation slices

| # | Slice | Files | Verify |
|---|---|---|---|
| S1 | **Lane cleanup baseline commit** (already done in editor; commit it) | `_shared/index.ts`, `_shared/parse-identity.ts`, `_shared/use-hub-data.tsx`, `today/*`, `RealEstateHubPages.tsx`, `App.tsx` (today lazy) | tsc + vite |
| S2 | **Tasks page restructure** (P0 #1, P2 #11, #13) — reorder around what's waiting on the user. | `real-estate-hub/tasks/index.tsx` | tsc + vite |
| S3 | **Agent Hub handoff card** (P0 #2, P1 #5, #6) — surface single primary action; tighten metrics; clarify Telegram form. | `AgentHubPage.tsx` | tsc + vite |
| S4 | **Memory page WorkflowStrip rewrite** (P1 #7, #9, P2 #13) | `real-estate-hub/memory/index.tsx` | tsc + vite |
| S5 | **Social page summary + idea queue empty state** (P1 #8, P2 #15) | `real-estate-hub/social/index.tsx` | tsc + vite |
| S6 | **Cron page row layout + collapse create form** (P0 #4, P2 #14) | `CronPage.tsx` | tsc + vite |
| S7 | **Sidebar unify section collapse** (P1 #10) | `App.tsx` | tsc + vite |
| S8 | **Today header trim** (P2 #12) + hub-shell hero strip | `today/index.tsx`, possibly `_shared/hub-shell.tsx` | tsc + vite |

## Change log

(filled as slices ship)
