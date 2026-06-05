/*
 * Default premium lead/admin automation kit — the backend source of truth that
 * mirrors cli/cron/jobs.py's SURFACE_HEARTBEAT_DEFAULTS + SURFACE_AUTOMATION_DEFAULTS.
 *
 * The CLI fetches these from GET /api/automations/list (entitlement-gated) and
 * seeds each PAUSED per account. Keep prompts/goals/schedules in lockstep with the
 * CLI constants so the bundled fallback and the backend kit stay identical.
 *
 * Gating: leads-surface items require the `real_estate_sales` entitlement, admin
 * items require `real_estate_admin`. tier_required is 'pro' (the base paid tier).
 */

export type SeedAutomation = {
  name: string;
  surface: string;
  kind: "heartbeat" | "automation";
  schedule: string;
  skill: string;
  prompt: string;
  deliver: string;
  spec: Record<string, unknown>;
  tier_required: "pro" | "builder";
  manifest: Record<string, unknown>;
  version: number;
};

const SURFACE_HEARTBEAT_SKILL = "real-estate/surface-heartbeat";

export function defaultAutomations(): SeedAutomation[] {
  return [
    // ── Heartbeats (kind=heartbeat; goal + experiment live in spec) ──────────
    {
      name: "Leads Heartbeat",
      surface: "leads",
      kind: "heartbeat",
      schedule: "0 8,15 * * *",
      skill: SURFACE_HEARTBEAT_SKILL,
      prompt: "",
      deliver: "local",
      spec: {
        goal:
          "Each run: check new/changed leads since the last run; surface the hot ones " +
          "with a one-line why; list overdue follow-ups and today's showings; draft " +
          "(never send) the next-touch for anyone gone quiet. End with one tight summary; " +
          "say 'all quiet' if nothing changed.",
        experiment: {
          every_n_runs: 7,
          metric: "next_touch_reply_rate",
          metric_type: "qualitative",
          direction: "higher",
          window: "7d",
          measurement:
            "Self-score 1-10 the quality/likely-conversion of the next-touch drafts vs the prior cycle, with justification, until a real reply-rate metric is wired.",
          approval_required: false,
        },
      },
      tier_required: "pro",
      manifest: { entitlement: "real_estate_sales" },
      version: 1,
    },
    {
      name: "Admin Heartbeat",
      surface: "admin",
      kind: "heartbeat",
      schedule: "30 7 * * *",
      skill: SURFACE_HEARTBEAT_SKILL,
      prompt: "",
      deliver: "local",
      spec: {
        goal:
          "Each run: scan the calendar and tasks; flag deadlines, conflicts, and anything " +
          "needing the realtor's decision; reconcile today's agenda. End with one tight " +
          "summary; say 'all quiet' if nothing needs attention.",
        experiment: {
          every_n_runs: 7,
          metric: "tasks_slipped",
          metric_type: "qualitative",
          direction: "lower",
          window: "7d",
          measurement:
            "Self-score 1-10 how well the agenda/flagging kept anything from slipping vs the prior cycle, with justification, until a real slipped-task metric is wired.",
          approval_required: false,
        },
      },
      tier_required: "pro",
      manifest: { entitlement: "real_estate_admin" },
      version: 1,
    },

    // ── Automations (kind=automation; prompt + skill) ────────────────────────
    {
      name: "New Outreach",
      surface: "leads",
      kind: "automation",
      schedule: "0 8 * * *",
      skill: "local/outreach-lanes",
      prompt:
        "Run the outreach skill. Pull fresh leads from every connected source " +
        "(CRM, SMS, email, social via Composio) that have not yet received a " +
        "first-touch in the last 14 days. For each one: enrich from CRM + " +
        "property-lookup, draft a personalized first message on the channel they " +
        "came in from, and write the draft to the source inbox for approval. Do " +
        "not send. Mark each lead as touched only after the human approves.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_sales" },
      version: 1,
    },
    {
      name: "Hot Leads Watcher",
      surface: "leads",
      kind: "automation",
      schedule: "15 8 * * *",
      skill: "local/outreach-lanes",
      prompt:
        "Run the outreach skill in monitor mode. Scan every connected source " +
        "(CRM, Messages, email, SMS, social via Composio) for hot signals since " +
        "the last run: inbound replies, viewing requests, repeat opens, CRM stage " +
        "moves, listing alerts. Re-score heat across the inbox and surface the top " +
        "10 hottest leads. For any lead with a brand-new inbound message that needs " +
        "a reply, draft a same-channel response and queue it for approval. Do not send.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_sales" },
      version: 1,
    },
    {
      name: "Follow-ups",
      surface: "leads",
      kind: "automation",
      schedule: "0 10,15 * * *",
      skill: "local/outreach-lanes",
      prompt:
        "Run the outreach skill in nurture mode. For every lead with an open thread " +
        "whose last outbound was 3+ days ago without a reply (or whose CRM stage is " +
        "in nurture), draft a context-aware follow-up on the same channel they were " +
        "last contacted. Use the relationship history, last touch, and CRM stage to " +
        "pick the angle. Queue every draft for approval. Do not send.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_sales" },
      version: 1,
    },
    {
      name: "Gmail Doc Router",
      surface: "admin",
      kind: "automation",
      schedule: "0 9 * * 1",
      skill: "real-estate-admin/gmail-doc-router",
      prompt:
        "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, " +
        "match listing documents to active Elevate deals with deal-matcher, file " +
        "documents to the correct Drive folder, and write artifacts/checklist " +
        "evidence back to the deal with admin-result-writer. Do not send messages.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_admin" },
      version: 1,
    },
    {
      name: "Seller Update",
      surface: "admin",
      kind: "automation",
      schedule: "0 16 * * 1-5",
      skill: "real-estate-admin/seller-update",
      prompt:
        "Run the seller-update skill. Pull ShowingTime feedback/activity for active " +
        "listings, match each listing to an Elevate deal, write the digest back to " +
        "the operational deal store, and create Gmail seller-update drafts. Never " +
        "send directly.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_admin" },
      version: 1,
    },
    {
      name: "Social Content Engine",
      surface: "marketing",
      kind: "automation",
      schedule: "20 7 * * 1",
      skill: "local/social-content-engine",
      prompt:
        "Run the social-content-engine skill (weekly content engine for the connected real estate agent).\n\n" +
        "Steps:\n" +
        "1. Pull last-30-day post metrics from every connected social platform (Instagram, TikTok, YouTube, Facebook, LinkedIn) using the bundled native fetchers.\n" +
        "2. Aggregate + rank with scripts/aggregate.py.\n" +
        "3. Research current real-estate content trends in the agent's market via the last30days skill.\n" +
        "4. Read inbox + CRM signals with scripts/read_signals.py to ground ideas in real client questions.\n" +
        "5. Generate 5-10 content ideas. Each one MUST cite at least one of metric / trend / signal.\n" +
        "6. Queue each idea with scripts/queue_idea.py — ideas land in /social-media for human approval.\n" +
        "7. Append a run summary to social-runs.jsonl.\n\n" +
        "Never publish. Never invent metrics. Real-estate scope only. The human approves on /social-media.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_marketing" },
      version: 1,
    },
    {
      name: "Market Stats Watcher",
      surface: "marketing",
      kind: "automation",
      schedule: "0 7 * * 1",
      skill: "real-estate/market-stats-watcher",
      prompt:
        "Run the market-stats-watcher skill. Pull fresh market-stat emails and route " +
        "useful market context into the real estate knowledge/admin workflow. Do not send messages.",
      deliver: "local",
      spec: {},
      tier_required: "pro",
      manifest: { entitlement: "real_estate_marketing" },
      version: 1,
    },
  ];
}
