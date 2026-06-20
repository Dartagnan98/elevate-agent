import { api } from "@/lib/api";
import type {
  AdminSetupItemStatus,
  LeadsSetupItemUpdate,
  LeadsSetupSnapshot,
  OutreachTemplate,
  SourceConnectorStatus,
} from "@/lib/api-types";

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

const LEADS_SETUP_STORAGE_KEY = "elevate.leadsSetup.v1";
const LEADS_SETUP_FRESH_MS = 60_000;
const LEADS_SETUP_STORAGE_MAX_AGE_MS = 10 * 60_000;

type CachedLeadsSetup = {
  cachedAt: number;
  setup: LeadsSetupSnapshot;
};

let cachedLeadsSetup: CachedLeadsSetup | null = null;
let leadsSetupInflight: Promise<LeadsSetupSnapshot> | null = null;

function normalizeCachedLeadsSetup(value: unknown): CachedLeadsSetup | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<CachedLeadsSetup>;
  if (!record.setup || typeof record.cachedAt !== "number") return null;
  if (Date.now() - record.cachedAt > LEADS_SETUP_STORAGE_MAX_AGE_MS) return null;
  return {
    cachedAt: record.cachedAt,
    setup: record.setup,
  };
}

export function readCachedLeadsSetup(): CachedLeadsSetup | null {
  if (cachedLeadsSetup) return cachedLeadsSetup;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LEADS_SETUP_STORAGE_KEY);
    if (!raw) return null;
    const cached = normalizeCachedLeadsSetup(JSON.parse(raw));
    if (!cached) {
      window.localStorage.removeItem(LEADS_SETUP_STORAGE_KEY);
      return null;
    }
    cachedLeadsSetup = cached;
    return cached;
  } catch {
    return null;
  }
}

export function writeCachedLeadsSetup(setup: LeadsSetupSnapshot): LeadsSetupSnapshot {
  const next = { cachedAt: Date.now(), setup };
  cachedLeadsSetup = next;
  if (typeof window !== "undefined") {
    window.setTimeout(() => {
      try {
        window.localStorage.setItem(LEADS_SETUP_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Best-effort only; the in-memory cache still prevents route flicker.
      }
    }, 0);
  }
  return setup;
}

export async function loadLeadsSetup(force = false): Promise<LeadsSetupSnapshot> {
  const cached = readCachedLeadsSetup();
  if (!force && cached && Date.now() - cached.cachedAt < LEADS_SETUP_FRESH_MS) {
    return cached.setup;
  }
  if (leadsSetupInflight) return leadsSetupInflight;
  leadsSetupInflight = api
    .getLeadsSetup({ refresh: force })
    .then(writeCachedLeadsSetup)
    .finally(() => {
      leadsSetupInflight = null;
    });
  return leadsSetupInflight;
}

export async function preloadLeadsSetup(): Promise<void> {
  await loadLeadsSetup().catch(() => undefined);
}

export const DEFAULT_AUTO_REPLY_TEMPLATE =
  "Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?";

export type LeadsSetupDraft = {
  metaMcpEndpoint: string;
  metaMcpToken: string;
  googleDeveloperToken: string;
  webhookUrl: string;
  webhookSecret: string;
  autoReplyEnabled: boolean;
  autoReplyTemplate: string;
  followUpCadenceDays: string;
};

export function leadsDraftFromSnapshot(snapshot: LeadsSetupSnapshot): LeadsSetupDraft {
  const byKey = new Map(snapshot.items.map((item) => [item.key, item]));
  const metaVal = (byKey.get("meta_lead_ads")?.value ?? {}) as Record<string, unknown>;
  const googleVal = (byKey.get("google_lead_forms")?.value ?? {}) as Record<string, unknown>;
  const webhookVal = (byKey.get("website_form_webhook")?.value ?? {}) as Record<string, unknown>;
  const policyVal = (byKey.get("auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
  return {
    metaMcpEndpoint: String(metaVal.mcpEndpoint ?? "https://mcp.pipeboard.co/meta-ads-mcp"),
    metaMcpToken: String(metaVal.mcpToken ?? ""),
    googleDeveloperToken: String(googleVal.developerToken ?? ""),
    webhookUrl: String(webhookVal.url ?? ""),
    webhookSecret: String(webhookVal.secret ?? ""),
    autoReplyEnabled: Boolean(policyVal.enabled ?? false),
    autoReplyTemplate: String(policyVal.initialMessageTemplate ?? DEFAULT_AUTO_REPLY_TEMPLATE),
    followUpCadenceDays: String(policyVal.followUpCadenceDays ?? "2"),
  };
}

export function buildItemUpdates(draft: LeadsSetupDraft): LeadsSetupItemUpdate[] {
  const metaReady = Boolean(draft.metaMcpEndpoint.trim() && draft.metaMcpToken.trim());
  const googleReady = Boolean(draft.googleDeveloperToken.trim());
  const webhookReady = draft.webhookUrl.trim();
  const policyReady = Boolean(draft.autoReplyTemplate.trim()) || !draft.autoReplyEnabled;
  return [
    {
      key: "meta_lead_ads",
      status: (metaReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: metaReady ? "meta_ads_mcp" : null,
      value: {
        authMethod: "mcp",
        mcpEndpoint: draft.metaMcpEndpoint.trim(),
        mcpToken: draft.metaMcpToken,
      },
    },
    {
      key: "google_lead_forms",
      status: (googleReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: googleReady ? "google_ads" : null,
      value: {
        developerToken: draft.googleDeveloperToken,
      },
    },
    {
      key: "website_form_webhook",
      status: (webhookReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: webhookReady ? "webhook" : null,
      value: {
        url: draft.webhookUrl.trim(),
        secret: draft.webhookSecret,
      },
    },
    {
      key: "auto_reply_policy",
      status: (policyReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.autoReplyEnabled ? "elevate" : "off",
      value: {
        enabled: draft.autoReplyEnabled,
        initialMessageTemplate: draft.autoReplyTemplate.trim(),
        followUpCadenceDays: Number(draft.followUpCadenceDays) || 2,
      },
    },
  ];
}

export const OUTREACH_CONNECTOR_IDS = ["crm", "apple-messages", "sms-provider", "android-device", "rcs"] as const;

export const LEADS_TEMPLATE_LANES: { id: string; label: string; hint: string }[] = [
  { id: "new-outreach", label: "First touch", hint: "lead just landed — pick the opener" },
  { id: "hot-leads-watcher", label: "Hot signals", hint: "live intent — open house, just-listed match, alert reply" },
  { id: "follow-ups", label: "Follow-ups", hint: "re-engagement, GIF nudge, market update, breakup, referral" },
];

export function connectorStateLabel(state: SourceConnectorStatus["state"]): string {
  return state.replace(/_/g, " ");
}

export function connectorStateClasses(state: SourceConnectorStatus["state"]): string {
  if (state === "connected" || state === "import_only") {
    return "bg-success/15 text-success";
  }
  if (state === "blocked" || state === "error" || state === "needs_operator") {
    return "border border-warning/40 bg-warning/10 text-warning";
  }
  return "border border-border/60 bg-muted/40 text-muted-foreground";
}

export function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

export function connectorSetupCopy(connector: SourceConnectorStatus): string {
  if (connector.initializeBehavior === "local_messages_import") {
    return connector.sourceExists
      ? "Live sync runs every 10 min via launchd. Click Re-import to force a full rebuild."
      : "Reads the synced Mac Messages database and builds a local Elevation message index for lead context.";
  }
  if (connector.initializeBehavior === "composio_social_setup") {
    return connector.sourceExists
      ? "Refreshes the local Composio social setup record and next operator step."
      : "Sets up Composio as the social account hub.";
  }
  return connector.sourceExists
    ? "Refreshes the local agent setup task and prompt for building the real connector."
    : "Creates a local setup task for the agent/operator to build the webhook, poller, import command, or bridge.";
}

export function isBrandNewLeadsSetup(setup: LeadsSetupSnapshot): boolean {
  if (setup.completionPct && setup.completionPct > 0) return false;
  if (setup.complete) return false;
  for (const item of setup.items) {
    if (item.status && item.status !== "missing") return false;
    if (item.provider && item.provider.trim()) return false;
    const value = item.value as Record<string, unknown> | null | undefined;
    if (value && Object.values(value).some((v) => v != null && String(v).trim() !== "")) return false;
  }
  return true;
}

export function firstTouchTemplates(templates: OutreachTemplate[]): OutreachTemplate[] {
  return templates.filter((tpl) => tpl.lane === "new-outreach");
}
