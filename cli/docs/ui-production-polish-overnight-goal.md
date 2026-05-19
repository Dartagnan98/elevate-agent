# Elevate UI Production Polish Overnight Goal

## Mission

Make the Elevate desktop app feel production-ready at the small-detail level, not just generally cleaner.

This is an autonomous overnight polish pass. Do not ask the user questions. Make strong product, UX, and engineering decisions; implement them; verify them; commit stable slices locally; and continue.

The app should feel like a coherent operating system for a realtor: compact, intentional, action-oriented, and easy to scan. Every tab, card, value, badge, queue, modal, dropdown, form, button, kanban card, and state should help the user understand what is happening and what to do next.

## Non-Negotiables

- Do not ask the user questions.
- Do not push to GitHub.
- Do not revert unrelated changes.
- Do not make broad rewrites when a focused UI/data-shape improvement will solve the issue.
- Do not stop at page-level impressions. Inspect component by component.
- Do not leave vague labels like `Next unknown`, unexplained backend counts, or duplicated concepts when a user-facing explanation is possible.
- Do not add decorative blobs, giant hero layouts, marketing sections, or empty visual drama.
- Do not create nested-card clutter.
- Do not hide important actions behind unclear dropdowns or technical labels.
- Do not mark work complete without checking the actual changed UI.

## Working Style

1. Start with an exhaustive audit.
2. Record the audit in `cli/docs/ui-production-polish-plan.md`.
3. Group findings by route, component type, severity, and proposed fix.
4. Implement in small, stable slices.
5. Verify each slice with relevant tests, typecheck/build, and browser/screenshot checks where useful.
6. Commit each stable slice locally with a clear message.
7. Continue until all routes and component types below have either been improved or explicitly marked as remaining work.

If blocked, write the blocker in `cli/docs/ui-production-polish-blockers.md` with:

- route/component
- observed issue
- why it is blocked
- what needs to happen next
- whether the UI has a temporary safe fallback

Then continue to the next highest-impact item.

## Definition Of Done

The pass is done only when:

- Every listed tab/surface has been inspected at component level.
- `cli/docs/ui-production-polish-plan.md` includes a page-by-page and component-by-component checklist with status.
- Cards are compact, scan-friendly, and action-oriented.
- Card values are useful to a realtor and not random backend counters.
- Kanban columns and cards explain workflow state, blocker, next action, owner/agent, dates, and evidence.
- Tasks and approvals feel like a real operating queue, not a vague mixed list.
- Handoffs explain attention needed and what happens next.
- Telegram setup cards clearly show readiness, missing requirements, and the fix action.
- Scheduled jobs, outreach lanes, wake loops, handoffs, automations, and tasks feel connected where they represent related work.
- Modals, popups, drawers, dropdowns, forms, hover states, loading states, empty states, error states, and disabled states have been reviewed.
- Layouts are responsive, no text overlaps, and buttons/labels fit.
- Stable local commits exist for completed slices.

## Product Standard

For every visible UI element, ask:

1. What is this?
2. Why does it matter to a realtor?
3. What status or value does it communicate?
4. What should the user do next?
5. Is it grouped with the right related information?
6. Is the label human-readable?
7. Is the value useful or just technical noise?
8. Is the primary action obvious?
9. Is secondary information quieter?
10. Does this component still make sense on smaller screens?

If the answer is weak, fix it by removing, relabeling, regrouping, redesigning, or changing the data presentation.

## Severity Model

Use this severity model in the audit table:

- P0: Broken workflow, broken navigation, data hidden/misleading, actions impossible, layout overlap, save/config impossible.
- P1: Core realtor workflow is confusing, duplicated, too technical, or not action-oriented.
- P2: Spacing, hierarchy, label, state, or grouping makes the page feel unpolished.
- P3: Small polish, microcopy, icon, hover, focus, animation, or consistency improvement.

## Required Audit Table Format

Add or maintain a table in `cli/docs/ui-production-polish-plan.md`:

| Status | Severity | Route | Component | Issue | Fix | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| todo/in-progress/done/blocked | P0-P3 | `/route` | Card/modal/etc | Specific observed issue | Specific change | Test/browser/screenshot |

Do not use vague findings like "needs polish." Every finding must name the exact component and the specific issue.

## Routes And Surfaces To Inspect

Inspect every reachable visible route, including but not limited to:

- Left sidebar and navigation.
- Chat page.
- Chat session list.
- Message composer.
- Chat message cards and attachments.
- PDF/local file viewer.
- Agent Hub.
- Agent configuration cards.
- Telegram lane configuration.
- Agent handoffs.
- Wake loop, heartbeat, worker status.
- Tasks.
- Approval queues.
- Admin task board.
- Admin action runs.
- Timed tasks.
- Recent sessions.
- Leads.
- Leads overview.
- Profiles list.
- Active conversations.
- Skipped leads.
- Buyer searches.
- Hot leads.
- Follow-ups.
- Outreach lanes.
- Lead scheduled jobs.
- Lead templates.
- Admin.
- Admin kanban.
- Admin deal cards.
- Admin side panel/drawer.
- Deal checklist.
- Deal artifacts.
- Deal runs/prior runs.
- Admin automations.
- Cron/Automations.
- Social Media.
- Social approval queue.
- Social metrics/snapshots.
- Setup/onboarding.
- Skills/cloud skills.
- Settings/config.
- Memory.
- Project.
- Logs/analytics/keys/documentation if visible in the sidebar.

If a route is gated or empty, still inspect the empty/locked state.

## Component Types To Inspect Everywhere

### Cards

For every card:

- Title must be clear and human-readable.
- Subtitle must explain context, not repeat the title.
- Metrics must help a user decide what to do.
- Remove repeated metrics such as sessions/active if they do not matter in that card.
- Use compact spacing and aligned labels.
- Primary action must be visually obvious.
- Secondary actions must be quiet but discoverable.
- Status must be legible and consistent.
- Missing setup must say what is missing and how to fix it.
- Empty cards must explain what will appear there.
- Cards should not contain other cards unless there is a strong reason.

### Card Values And Metrics

For every value:

- Replace backend names with human language.
- Prefer "Needs approval", "Blocked by Gmail", "Ready to run", "No due date yet" over raw enum labels.
- Hide unknown values if they add no information.
- Replace `Next unknown` with a useful fallback such as `No next run scheduled`, `Waiting for setup`, or `Manual trigger only`.
- If a count is shown, explain what the count is counting.
- If a count is stale or fake, remove it or label it as a setup/sample state.

### Badges

For every badge:

- Make colors consistent across the app.
- Use clear states: Ready, Running, Needs approval, Blocked, Missing setup, Paused, Scheduled, Drafted, Synced, Failed.
- Avoid mixing technical and human labels for the same state.
- Keep badge text short and readable.
- Ensure badges do not collide with card actions or dates.

### Buttons And Actions

For every action:

- There should be one clear primary action per component.
- Use icon buttons where the action is familiar and space is tight.
- Text buttons should use direct verbs: Configure, Review, Approve, Run, Pause, Resume, Sync, Open.
- Dangerous/destructive actions need clear confirmation.
- Disabled buttons need a reason nearby or a tooltip/title.
- Avoid "Run" if the action will only create a draft or queue a task.

### Lists And Tables

For every list/table:

- Rows should be scan-friendly and consistent height.
- The left side should identify the item.
- The right side should show status or next action.
- Important dates should be visible.
- Empty states should say why empty and how items get there.
- Long lists should have grouping, filters, or sensible ordering.

### Kanban Boards

For every kanban:

- Columns must match real workflow phases.
- Column labels must be human-readable.
- Cards must show phase, next action, blocker, owner/agent, date signal, approval state, and evidence/artifact indicators when relevant.
- Drag/drop/manual moves must not imply automation finished unless the source-of-truth state supports it.
- Waiting-human items should be visually distinct.
- Blocked items should explain exactly what is missing.
- Cards should be compact enough to scan several at once.

### Tasks And Approvals

Tasks should not be one mixed pile.

Separate or clearly group:

- Needs approval.
- Blocked/missing setup.
- Running/in progress.
- Scheduled/upcoming.
- Ready to run.
- Recently completed.
- Failed/retry needed.

Approval tasks should feel like a board or queue with:

- What needs approving.
- Why it matters.
- Source deal/profile/thread.
- Owner/agent.
- Required fields or decision.
- Primary approve/reject/review action.
- Link to evidence/artifact.

### Modals, Popovers, Drawers

For every modal/drawer/popover:

- It must have one clear purpose.
- Header must explain the object being edited/reviewed.
- Close, cancel, save, approve, and destructive actions must be clear.
- It must not cover unrelated content awkwardly when a split layout would work better.
- Form fields should be grouped logically.
- Long content should scroll inside the modal/drawer, not the page behind it.
- Avoid huge blank modal areas.
- Make escape/close behavior safe.

### Dropdowns And Menus

For every dropdown/menu:

- Label must make the category clear.
- Selected value must be visible.
- Options should be grouped if there are more than a few.
- Technical provider names need human helper text if unclear.
- Empty or unavailable options need explanation.
- Do not use dropdowns for actions that should be explicit buttons.

### Forms

For every form:

- Labels must be explicit.
- Placeholder text cannot be the only label.
- Helper text should explain format, source, or consequence.
- Save state must show saving/saved/error.
- Validation errors must be specific.
- Secrets/tokens must be masked and clearly saved to env/config.
- Required fields must be obvious.
- Group related fields.

### Loading, Empty, Error, Disabled

Every page and major component needs intentional states:

- Loading should not cause layout jump.
- Empty should explain what would appear and how to create/connect it.
- Error should explain what failed and what to try next.
- Blocked should explain missing setup.
- Disabled should explain why disabled.

### Responsive Layout

Check at least:

- Wide desktop.
- Laptop width.
- Tablet-ish width.
- Mobile/narrow if the app supports it.

Verify:

- No text overlap.
- Buttons fit.
- Sidebar does not crush content.
- Cards stack sensibly.
- Drawers/modals remain usable.
- Tables/lists do not overflow incoherently.

## Page-Specific Expectations

### Left Sidebar

Audit:

- Logo placement.
- New chat/search.
- Section labels.
- Chat row spacing.
- Active chat state.
- Timestamp/age alignment.
- Three-dot/menu collision.
- Long chat title truncation.
- Pinned vs chats grouping.
- Tool links and bottom settings.

Fix:

- Keep compact spacing.
- Make chat names readable.
- Ensure row click works.
- Ensure hover/actions do not overlap age labels.
- Avoid excessive vertical gaps.

### Chat Page And PDF Viewer

Audit:

- Chat history load speed perception.
- Composer layout.
- Agent selector.
- Model selector.
- Full access badge.
- Voice/send controls.
- Attachment cards.
- Local file cards.
- PDF viewer layout.
- Split-view behavior.
- Popover vs side panel.

Fix:

- PDF/local file viewer should feel like part of the chat workspace, not an overlapping nuisance.
- If a file is open, give chat and preview balanced space.
- Keep composer accessible and non-overlapping.
- Attachment actions should be clear: Open, Copy, maybe Reveal.

### Agent Hub

Audit:

- Agent cards.
- Executive/Admin/Outreach/Ads/Social/Marketing cards.
- Repeated session counts.
- Active counts.
- Skill/tool counts.
- Telegram lane readiness.
- Configure actions.
- Online/Ready/Needs Telegram labels.
- Handoff worker card.
- Wake loop/heartbeat.
- Harness/memory/access sections.

Fix:

- Agent cards should answer: what this agent owns, is it reachable, what is missing, what is the next setup/action?
- Remove or demote metrics that do not help the user.
- Make Telegram readiness obvious.
- Make "configured but not working" distinguishable from "not configured".
- Handoffs should show attention-needed first, not just counts.

### Tasks

Audit:

- Workflow strip.
- Agent handoffs card.
- Worker card.
- Admin deal tasks.
- Admin action runs.
- Timed tasks.
- Recent sessions.
- Empty and blocked states.

Fix:

- Turn approvals/waiting-human into a real queue or kanban-like board.
- Separate approvals, blocked, running, scheduled, and completed/recent.
- Make each task show source, owner, next action, due/date, and why it matters.
- Do not mix scheduled jobs and approval tasks without explaining relationship.

### Leads

Audit:

- Overview cards.
- Profiles list.
- Active conversations.
- Buyer searches.
- Hot leads.
- Follow-ups.
- Skipped.
- Templates.
- Outreach lanes.
- Scheduled jobs.
- Thread drawer.

Fix:

- Active conversations should stay at the top.
- Profiles should be organized by action, not random inventory.
- Skipped items should show immediately and explain why skipped.
- Buyer searches and hot leads should be visible if backend data exists.
- Outreach lanes and their scheduled jobs should feel connected.
- Draft approvals should clearly say draft vs sent.

### Admin

Audit:

- Kanban columns.
- Deal cards.
- Phase/stage names.
- Checklist progress.
- Important dates.
- Human intervention prompts.
- Artifacts/evidence.
- Side panel.
- Add/edit co-contact.
- Attach document.
- Prior runs.
- Condition flags.
- Approval tasks.

Fix:

- Admin board should feel like transaction files with a kanban view.
- Cards must show next action, blocker, owner/agent, due date, approval state, and evidence.
- Manual moves should not hide automation requirements.
- Human prompts should be visible and actionable.
- Side panel should be source-of-truth, not a disconnected detail blob.

### Automations And Cron

Audit:

- Scheduled job labels.
- Cron expressions.
- Next run display.
- Blocked states.
- Paused states.
- Lane ownership.
- Relationship to tasks/agent hub.

Fix:

- Replace raw cron with friendlier cadence where possible.
- Explain blocked job setup requirements.
- Show what each job creates or updates.
- Group jobs by workflow: leads, admin, social, memory/system.
- Make manual run vs scheduled run distinct.

### Social Media

Audit:

- Approval queue.
- Ideas/cards.
- Metrics.
- Connected accounts.
- Empty state.
- Scheduled posts.
- Draft vs published state.

Fix:

- Ideas need hook, platform, reason, source signal, and approval action.
- Never imply auto-publishing.
- Missing connector states should say which account to connect.
- Metrics should be useful and not overwhelming.

### Setup, Skills, Settings

Audit:

- Unlock/paid pack states.
- Cloud skills sync.
- Provider setup.
- Env/secrets fields.
- Telegram tokens/chat IDs.
- Province/region setup.
- Browser-use/composio/account connectors.

Fix:

- Make setup feel guided and sequential.
- Make unlocked pack status celebratory but professional.
- Make "what account do I connect next?" obvious.
- Explain where secrets are saved without exposing them.
- Skills should explain what they unlock in dashboards.

### Memory And Project

Audit:

- Memory visualization and graph cards.
- Project files/artifacts.
- Empty/loading/error states.
- Whether information helps the user decide what to do.

Fix:

- Keep memory/task/project state readable and operational.
- Avoid visual clutter.
- Prioritize recent useful activity and next action.

## Implementation Guidance

Prefer targeted component improvements:

- Rename labels.
- Reorder sections.
- Add compact status summaries.
- Collapse repeated metrics.
- Improve card grids.
- Split mixed queues.
- Add grouped filters.
- Improve empty/error/blocked copy.
- Improve primary action placement.
- Improve responsive constraints.
- Add subtle transition/micro-interaction if it clarifies state.

Avoid:

- Big rewrites unrelated to observed issues.
- New design systems unless required.
- Huge CSS churn.
- Data model changes unless the UI cannot be made honest without them.

## Verification

After each stable slice:

- Run the relevant typecheck/build/test command.
- Use browser or screenshot checks for changed UI.
- Check at least one wide desktop viewport and one narrower viewport when layout changed.
- Manually inspect changed cards/modals/dropdowns/kanban states.
- Verify no text overlap.
- Verify no primary action disappeared.
- Verify empty/loading/error states still render.

Suggested commands, adapted to repo reality:

```bash
npm --prefix cli/web run build
npm --prefix backend exec -- tsc --noEmit
pytest cli/tests/elevate_cli -q
```

Use the subset that matches the files changed.

## Commit Protocol

Commit stable slices locally. Do not push.

Good commit examples:

- `Polish task approval board`
- `Clarify agent hub readiness cards`
- `Tighten leads workflow cards`
- `Improve admin kanban card hierarchy`
- `Clean up cron job status layout`

Before committing:

- `git status --short`
- Stage only files related to the slice.
- Do not stage unrelated dirty files.

## Final Report

When the pass stops, update `cli/docs/ui-production-polish-plan.md` with:

- completed slices
- commits created
- verification run
- pages still needing work
- blockers
- next recommended pass

Then respond with a concise summary.
