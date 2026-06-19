import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, CheckCircle2, Circle, AlertTriangle, ExternalLink, Sparkles, Link as LinkIcon, Play, Copy, RefreshCw, Plus, Pencil, Trash2, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminSetupItemStatus,
  LeadsSetupItem,
  LeadsSetupItemUpdate,
  LeadsSetupSnapshot,
  OutreachConnectorRef,
  OutreachTemplate,
  SourceConnectorStatus,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ListSkeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  playOnboardingChime,
  playOnboardingClick,
  playOnboardingSwell,
  playOnboardingWhoosh,
} from "@/lib/onboarding-sounds";

function errorMessage(err: unknown, fallback: string): string {
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

function readCachedLeadsSetup(): CachedLeadsSetup | null {
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

function writeCachedLeadsSetup(setup: LeadsSetupSnapshot): LeadsSetupSnapshot {
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

async function loadLeadsSetup(force = false): Promise<LeadsSetupSnapshot> {
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

const DEFAULT_AUTO_REPLY_TEMPLATE =
  "Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?";

type LeadsSetupDraft = {
  metaMcpEndpoint: string;
  metaMcpToken: string;
  googleDeveloperToken: string;
  webhookUrl: string;
  webhookSecret: string;
  autoReplyEnabled: boolean;
  autoReplyTemplate: string;
  followUpCadenceDays: string;
};

function leadsDraftFromSnapshot(snapshot: LeadsSetupSnapshot): LeadsSetupDraft {
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

function buildItemUpdates(draft: LeadsSetupDraft): LeadsSetupItemUpdate[] {
  // Meta: one Pipeboard token is enough — Pipeboard's MCP auto-discovers
  // ad accounts, pages, and lead forms.
  const metaReady = Boolean(draft.metaMcpEndpoint.trim() && draft.metaMcpToken.trim());
  // Google: developer token alone — the CLI auto-discovers customer ID
  // and campaign IDs via `google-ads-list-accessible-customers`.
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

function StatusBadge({ status }: { status: AdminSetupItemStatus }) {
  if (status === "connected" || status === "configured") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (status === "manual") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Manual
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        Skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Missing
    </span>
  );
}

const OUTREACH_CONNECTOR_IDS = ["crm", "apple-messages", "sms-provider", "android-device", "rcs"] as const;

const LEADS_TEMPLATE_LANES: { id: string; label: string; hint: string }[] = [
  { id: "new-outreach", label: "First touch", hint: "lead just landed — pick the opener" },
  { id: "hot-leads-watcher", label: "Hot signals", hint: "live intent — open house, just-listed match, alert reply" },
  { id: "follow-ups", label: "Follow-ups", hint: "re-engagement, GIF nudge, market update, breakup, referral" },
];

function connectorStateLabel(state: SourceConnectorStatus["state"]): string {
  return state.replace(/_/g, " ");
}

function connectorStateClasses(state: SourceConnectorStatus["state"]): string {
  if (state === "connected" || state === "import_only") {
    return "bg-success/15 text-success";
  }
  if (state === "blocked" || state === "error" || state === "needs_operator") {
    return "border border-warning/40 bg-warning/10 text-warning";
  }
  return "border border-border/60 bg-muted/40 text-muted-foreground";
}

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

function connectorSetupCopy(connector: SourceConnectorStatus): string {
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

function isBrandNewLeadsSetup(setup: LeadsSetupSnapshot): boolean {
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

function LeadsOnboardingGate({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <section className="onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-background px-6 py-10">
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-md flex-col items-center text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Leads · first run
        </div>
        <h1 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
          Wire up Elevation Leads
        </h1>
        <p className="onboarding-rise-delay-2 mt-3 max-w-sm text-[13.5px] leading-6 text-muted-foreground">
          A short guided run sets your lead sources, outreach channels, and auto-reply policy. Two minutes, end-to-end.
        </p>
        <Button
          size="lg"
          onClick={onStart}
          className="onboarding-rise-delay-3 mt-7 h-12 min-w-[220px] px-6 text-[14px]"
        >
          <Sparkles className="h-4 w-4" />
          Run onboarding
        </Button>
        <button
          type="button"
          onClick={onSkip}
          className="onboarding-rise-delay-3 mt-4 text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          or skip to the full setup form
        </button>
      </div>
    </section>
  );
}

function LeadsOnboardingWelcome({ onContinue }: { onContinue: () => void }) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    playOnboardingSwell();
  }, []);

  const handleStart = useCallback(() => {
    playOnboardingWhoosh();
    playOnboardingSwell();
    setExiting(true);
  }, []);

  const handleAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget) return;
      if (exiting) onContinue();
    },
    [exiting, onContinue],
  );

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to Elevation Leads"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevation · Leads
        </div>
        <h1 className="onboarding-rise-delay-1 mt-4 text-[52px] font-medium leading-[1.02] tracking-tight text-foreground">
          Welcome to Elevation Leads.
        </h1>
        <p className="onboarding-rise-delay-2 mt-4 max-w-lg text-[15px] leading-7 text-muted-foreground">
          A few quick questions and Leads starts catching, routing, and drafting replies the moment a lead lands.
        </p>
        <Button
          size="lg"
          onClick={handleStart}
          disabled={exiting}
          className="onboarding-rise-delay-3 mt-9 h-12 min-w-[240px] px-7 text-[14px]"
        >
          Let's get started
        </Button>
      </div>
    </div>,
    document.body,
  );
}

type LeadsWizardStepId = "meta" | "google" | "webhook" | "outreach" | "policy";

type LeadsWizardStep = {
  id: LeadsWizardStepId;
  eyebrow: string;
  title: string;
  subtitle: string;
};

const LEADS_WIZARD_STEPS: LeadsWizardStep[] = [
  {
    id: "meta",
    eyebrow: "Step 1 of 5",
    title: "Meta Lead Ads",
    subtitle:
      "Skip if you don't run Facebook / Instagram lead-form ads. Pipeboard MCP wraps Meta's Marketing API — one token, no Facebook App registration.",
  },
  {
    id: "google",
    eyebrow: "Step 2 of 5",
    title: "Google Lead Forms",
    subtitle:
      "Skip if you don't run Google Ads. One developer token is enough — Elevation's CLI auto-discovers your customer ID and campaigns.",
  },
  {
    id: "webhook",
    eyebrow: "Step 3 of 5",
    title: "Website form webhook",
    subtitle:
      "Optional catch-all POST endpoint for landing-page and contact-us forms. Wire any form provider that can POST JSON.",
  },
  {
    id: "policy",
    eyebrow: "Step 4 of 5",
    title: "Auto-reply policy",
    subtitle:
      "Tell Elevation how aggressive to be on the first touch. You can change the cadence per lane after onboarding.",
  },
  {
    id: "outreach",
    eyebrow: "Step 5 of 5",
    title: "CRM + outreach channels",
    subtitle:
      "CRM (Lofty / FUB), iMessage, SMS, and RCS live as Source Connectors. \"Run prompt\" opens a chat seeded with that connector's setup — finish onboarding first, then run these one by one.",
  },
];

function LeadsOnboardingWizard({
  draft,
  updateField,
  onAdvanceSave,
  onFinish,
  saving,
  completing,
  error,
  savedMessage,
  outreachSourceConnectors,
  refreshSourceConnectors,
  sourceConnectorsLoading,
  firstTouchTemplates,
  refreshTemplates,
}: {
  draft: LeadsSetupDraft;
  updateField: <K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => void;
  onAdvanceSave: () => Promise<void>;
  onFinish: () => Promise<void>;
  saving: boolean;
  completing: boolean;
  error: string | null;
  savedMessage: string | null;
  outreachSourceConnectors: SourceConnectorStatus[];
  refreshSourceConnectors: () => Promise<void>;
  sourceConnectorsLoading: boolean;
  firstTouchTemplates: OutreachTemplate[];
  refreshTemplates: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const [runningPromptId, setRunningPromptId] = useState<string | null>(null);

  const promptForConnector = useCallback(async (connector: SourceConnectorStatus) => {
    const existing = (connector.prompt || "").trim();
    if (existing) return existing;
    const resp = await api.getSourceConnectorPrompt(connector.id);
    return (resp.prompt || "").trim();
  }, []);

  const runPrompt = useCallback(
    async (connector: SourceConnectorStatus) => {
      setRunningPromptId(connector.id);
      try {
        const prompt = await promptForConnector(connector);
        if (!prompt) return;
        const ts = String(Date.now());
        const seedText = `Source connector: ${connector.label} (${connector.id})\n\n${prompt}`;
        try {
          window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText);
        } catch {
          // sessionStorage disabled — navigate anyway, user can paste manually.
        }
        navigate(`/chat?new=${ts}&seed=${ts}`);
      } finally {
        setRunningPromptId(null);
      }
    },
    [navigate, promptForConnector],
  );

  const copyPrompt = useCallback(async (connector: SourceConnectorStatus) => {
    try {
      await navigator.clipboard.writeText(await promptForConnector(connector));
    } catch {
      // clipboard unavailable — silent fail
    }
  }, [promptForConnector]);

  type TemplateEditor =
    | { mode: "create"; lane: string; name: string; body: string }
    | { mode: "edit"; id: string; lane: string; name: string; body: string };
  const [templateEditor, setTemplateEditor] = useState<TemplateEditor | null>(null);
  const [templateMutating, setTemplateMutating] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [deleteTemplateTarget, setDeleteTemplateTarget] = useState<OutreachTemplate | null>(null);

  const openCreateTemplate = useCallback((lane: string) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "create", lane, name: "", body: "" });
  }, []);

  const openEditTemplate = useCallback((tpl: OutreachTemplate) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "edit", id: tpl.id, lane: tpl.lane, name: tpl.name, body: tpl.body });
  }, []);

  const closeTemplateEditor = useCallback(() => {
    setTemplateEditor(null);
    setTemplateError(null);
  }, []);

  const saveTemplate = useCallback(async () => {
    if (!templateEditor) return;
    const name = templateEditor.name.trim();
    const body = templateEditor.body.trim();
    if (!name || !body) {
      setTemplateError("Name and body are both required.");
      return;
    }
    setTemplateMutating(true);
    setTemplateError(null);
    try {
      if (templateEditor.mode === "create") {
        await api.createOutreachTemplate({ lane: templateEditor.lane, name, body });
      } else {
        await api.updateOutreachTemplate(templateEditor.id, { name, body });
      }
      await refreshTemplates();
      setTemplateEditor(null);
    } catch (err) {
      setTemplateError(errorMessage(err, "Could not save template."));
    } finally {
      setTemplateMutating(false);
    }
  }, [templateEditor, refreshTemplates]);

  const deleteTemplate = useCallback(
    async (tpl: OutreachTemplate) => {
      setTemplateMutating(true);
      setTemplateError(null);
      try {
        await api.deleteOutreachTemplate(tpl.id);
        await refreshTemplates();
        setDeleteTemplateTarget(null);
      } catch (err) {
        setTemplateError(errorMessage(err, "Could not delete template."));
      } finally {
        setTemplateMutating(false);
      }
    },
    [refreshTemplates],
  );

  const [stepIdx, setStepIdx] = useState(0);
  const [showMissing, setShowMissing] = useState(false);
  const step = LEADS_WIZARD_STEPS[stepIdx];
  const isLast = stepIdx === LEADS_WIZARD_STEPS.length - 1;
  const isFirst = stepIdx === 0;
  const busy = saving || completing;

  const missingMessage = useMemo(() => {
    if (step.id !== "policy") return null;
    if (draft.autoReplyEnabled && !draft.autoReplyTemplate.trim()) {
      return 'Fill in "Initial reply template" before continuing — or turn auto-reply off.';
    }
    return null;
  }, [step.id, draft.autoReplyEnabled, draft.autoReplyTemplate]);
  const canAdvance = missingMessage == null;
  useEffect(() => {
    setShowMissing(false);
  }, [stepIdx]);

  const handleNext = useCallback(async () => {
    if (busy) return;
    if (!canAdvance) {
      setShowMissing(true);
      return;
    }
    playOnboardingClick();
    await onAdvanceSave();
    if (isLast) {
      playOnboardingSwell();
      await onFinish();
      return;
    }
    setStepIdx((idx) => Math.min(idx + 1, LEADS_WIZARD_STEPS.length - 1));
  }, [busy, canAdvance, isLast, onAdvanceSave, onFinish]);

  const handleBack = useCallback(() => {
    if (busy) return;
    playOnboardingClick();
    setStepIdx((idx) => Math.max(idx - 1, 0));
  }, [busy]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Leads onboarding wizard"
      className="onboarding-overlay fixed inset-0 z-[100] overflow-y-auto"
    >
      <div className="onboarding-aurora-bg pointer-events-none fixed inset-0" aria-hidden />
      <div className="relative flex min-h-full items-center justify-center px-6 py-10">
       <div className="relative flex w-full max-w-3xl flex-col">
        <div className="mb-7 flex items-center gap-1.5">
          {LEADS_WIZARD_STEPS.map((s, idx) => (
            <span
              key={s.id}
              aria-hidden
              className={cn(
                "h-1 flex-1 rounded-sm transition-colors duration-300",
                idx <= stepIdx ? "bg-primary" : "bg-border/60",
              )}
            />
          ))}
        </div>

        <div key={stepIdx} className="flex flex-col">
          <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            {step.eyebrow}
          </div>
          <h2 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
            {step.title}
          </h2>
          <p className="onboarding-rise-delay-2 mt-3 max-w-xl text-[14px] leading-7 text-muted-foreground">
            {step.subtitle}
          </p>

          <div className="onboarding-rise-delay-3 mt-8 flex flex-col gap-4">
            {step.id === "meta" && (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  <WizardField
                    label="MCP endpoint URL"
                    value={draft.metaMcpEndpoint}
                    onChange={(v) => updateField("metaMcpEndpoint", v)}
                    placeholder="https://mcp.pipeboard.co/meta-ads-mcp"
                    fullWidth
                    helper="Pre-filled with Pipeboard's hosted MCP. They handle the Facebook OAuth + Marketing API plumbing — you just paste a token."
                  />
                  <WizardField
                    label="Pipeboard API token"
                    value={draft.metaMcpToken}
                    onChange={(v) => updateField("metaMcpToken", v)}
                    placeholder="••••••••"
                    type="password"
                    fullWidth
                    helper={
                      <>
                        Get one at{" "}
                        <a
                          href="https://pipeboard.co/api-tokens"
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          pipeboard.co/api-tokens
                        </a>{" "}
                        (OAuth Facebook there once, copy token back). Ad accounts, pages, and lead forms are auto-discovered.
                      </>
                    }
                  />
                </div>
                <p className="text-[11.5px] text-muted-foreground/80">
                  Optional — skip Meta entirely if you don't run Facebook / Instagram lead-form ads.
                </p>
              </>
            )}

            {step.id === "google" && (
              <div className="grid gap-4 md:grid-cols-2">
                <WizardField
                  label="Developer token"
                  value={draft.googleDeveloperToken}
                  onChange={(v) => updateField("googleDeveloperToken", v)}
                  placeholder="abcDEF123-xyz"
                  type="password"
                  fullWidth
                  helper={
                    <>
                      Generate one at{" "}
                      <a
                        href="https://developers.google.com/google-ads/api/docs/get-started/dev-token"
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        Google Ads → Tools → API Center
                      </a>
                      . The CLI auto-discovers your customer ID and campaign IDs from this token.
                    </>
                  }
                />
                <p className="md:col-span-2 text-[11.5px] text-muted-foreground/80">
                  Optional — skip Google entirely if you don't run Google Ads lead-form extensions.
                </p>
              </div>
            )}

            {step.id === "webhook" && (
              <div className="grid gap-4 md:grid-cols-2">
                <WizardField
                  label="Webhook URL"
                  value={draft.webhookUrl}
                  onChange={(v) => updateField("webhookUrl", v)}
                  placeholder="https://elevate.yourdomain.com/api/leads/inbound"
                  fullWidth
                  helper="POST endpoint your form provider (Webflow, Framer, custom) hits when someone submits."
                />
                <WizardField
                  label="Shared secret"
                  value={draft.webhookSecret}
                  onChange={(v) => updateField("webhookSecret", v)}
                  placeholder="optional"
                  type="password"
                  fullWidth
                  helper="Optional. If set, Elevation verifies HMAC signature on each incoming submission."
                />
              </div>
            )}

            {step.id === "outreach" && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    to="/config#connectors"
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card/60 px-3 py-1.5 text-[12.5px] font-medium text-foreground backdrop-blur-sm hover:bg-muted"
                  >
                    <LinkIcon className="h-3.5 w-3.5" />
                    Open Source Connectors
                  </Link>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void refreshSourceConnectors()}
                    disabled={sourceConnectorsLoading}
                    className="h-8 gap-1 px-2 text-[11.5px]"
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5", sourceConnectorsLoading && "animate-spin")} />
                    Refresh
                  </Button>
                </div>

                <ul className="divide-y divide-border/40 overflow-hidden rounded-md border border-border/60 bg-card/40 backdrop-blur-sm">
                  {outreachSourceConnectors.length === 0 && !sourceConnectorsLoading && (
                    <li className="px-3 py-4 text-[12px] text-muted-foreground">
                      No outreach connectors found. Check that your install seeded `data/sources/`.
                    </li>
                  )}
                  {outreachSourceConnectors.length === 0 && sourceConnectorsLoading && (
                    <li className="px-3 py-4">
                      <ListSkeleton rows={3} />
                    </li>
                  )}
                  {outreachSourceConnectors.map((connector) => {
                    const total = connectorRecordTotal(connector);
                    const hint = OUTREACH_HINTS[connector.id as OutreachConnectorRef["id"]];
                    const setupCopy = connectorSetupCopy(connector);
                    return (
                      <li key={connector.id} className="px-3 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[13px] font-semibold text-foreground">{connector.label}</span>
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium",
                                  connectorStateClasses(connector.state),
                                )}
                              >
                                {connector.state === "connected" || connector.state === "import_only" ? (
                                  <CheckCircle2 className="h-3 w-3" />
                                ) : connector.state === "blocked" || connector.state === "error" ? (
                                  <AlertTriangle className="h-3 w-3" />
                                ) : (
                                  <Circle className="h-3 w-3" />
                                )}
                                {connectorStateLabel(connector.state)}
                              </span>
                              {total > 0 && (
                                <span className="text-[10.5px] text-muted-foreground">
                                  {total.toLocaleString()} records
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
                              {hint?.tagline || setupCopy}
                            </p>
                            {connector.nextOperatorStep && (
                              <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/80">
                                Next: {connector.nextOperatorStep}
                              </p>
                            )}
                            {connector.lastError && (
                              <p className="mt-1.5 text-[11px] leading-5 text-destructive/80">
                                {connector.lastError}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                            {connector.ownerAgent}
                          </span>
                          {connector.connectionType && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                              {connector.connectionType}
                            </span>
                          )}
                          <Button
                            size="sm"
                            variant="default"
                            className="ml-auto h-7 gap-1 px-2 text-[11.5px]"
                            disabled={runningPromptId === connector.id}
                            onClick={() => void runPrompt(connector)}
                            aria-label={`Run setup prompt for ${connector.label}`}
                          >
                            <Play className="h-3 w-3" />
                            {runningPromptId === connector.id ? "Opening chat…" : "Run prompt"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            onClick={() => void copyPrompt(connector)}
                            aria-label={`Copy setup prompt for ${connector.label}`}
                            title="Copy prompt text"
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      </li>
                    );
                  })}
                </ul>

                <p className="text-[11.5px] text-muted-foreground/80">
                  Run prompt opens a chat seeded with the connector's setup prompt — same flow as Config → Source connectors.
                  Elevation auto-routes by lead device: iPhone → iMessage, Android → SMS / RCS.
                </p>
              </div>
            )}

            {step.id === "policy" && (
              <div className="flex flex-col gap-4">
                <label className="flex items-start gap-3 rounded-md border border-border bg-card/60 px-4 py-3 backdrop-blur-sm">
                  <input
                    type="checkbox"
                    checked={draft.autoReplyEnabled}
                    onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-primary"
                  />
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-foreground">
                      Send an automated first reply when a lead lands
                    </div>
                    <p className="mt-0.5 text-[11.5px] text-muted-foreground">
                      Off by default — Elevation drafts and queues a reply for your approval instead.
                    </p>
                  </div>
                </label>
                <div className="flex flex-col gap-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[12.5px] font-medium text-foreground">
                        Template library
                      </span>
                      <span className="text-[11px] leading-[1.4] text-muted-foreground">
                        Elevation picks per situation — best-fit template is auto-attached by ID and tracked for reply rate. Click any card to pin it as the default first-touch.
                      </span>
                    </div>
                    <Link
                      to="/real-estate/templates"
                      className="shrink-0 text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Manage all
                    </Link>
                  </div>
                  {templateError && (
                    <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-[11.5px] text-destructive">
                      {templateError}
                    </div>
                  )}
                  {LEADS_TEMPLATE_LANES.map((lane) => {
                    const laneTemplates = firstTouchTemplates.filter((t) => t.lane === lane.id);
                    const editingThisLane =
                      templateEditor && templateEditor.lane === lane.id ? templateEditor : null;
                    return (
                      <div key={lane.id} className="flex flex-col gap-2">
                        <div className="flex items-baseline justify-between gap-2">
                          <div className="flex items-baseline gap-2">
                            <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                              {lane.label}
                            </span>
                            <span className="text-[10.5px] text-muted-foreground/70">
                              {laneTemplates.length} · {lane.hint}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => openCreateTemplate(lane.id)}
                            className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground transition hover:bg-muted hover:text-foreground"
                            disabled={templateMutating}
                          >
                            <Plus className="h-3 w-3" />
                            Add
                          </button>
                        </div>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {laneTemplates.map((tpl) => {
                            const isActive = draft.autoReplyTemplate.trim() === tpl.body.trim();
                            const hasGif = /\[\[gif:/i.test(tpl.body);
                            const isEditingThis =
                              editingThisLane?.mode === "edit" && editingThisLane.id === tpl.id;
                            if (isEditingThis) {
                              return (
                                <TemplateEditorCard
                                  key={tpl.id}
                                  editor={editingThisLane}
                                  onChange={(patch) =>
                                    setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                                  }
                                  onSave={saveTemplate}
                                  onCancel={closeTemplateEditor}
                                  busy={templateMutating}
                                />
                              );
                            }
                            return (
                              <div
                                key={tpl.id}
                                className={cn(
                                  "group relative flex flex-col gap-1 rounded-md border px-3 py-2.5 text-left backdrop-blur-sm transition",
                                  isActive
                                    ? "border-primary/60 bg-primary/10"
                                    : "border-border bg-card/60 hover:border-border/80 hover:bg-card",
                                )}
                              >
                                <button
                                  type="button"
                                  onClick={() => updateField("autoReplyTemplate", tpl.body)}
                                  className="flex flex-col gap-1 text-left"
                                >
                                  <div className="flex items-center justify-between gap-2 pr-12">
                                    <span className="text-[12.5px] font-medium text-foreground">{tpl.name}</span>
                                    <div className="flex items-center gap-1.5">
                                      {hasGif && (
                                        <span className="inline-flex items-center rounded-sm border border-border/70 bg-muted/50 px-1.5 py-px font-mono-ui text-[9px] uppercase tracking-wide text-muted-foreground">
                                          GIF
                                        </span>
                                      )}
                                      {isActive && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                                    </div>
                                  </div>
                                  <span className="line-clamp-2 text-[11.5px] leading-[1.4] text-muted-foreground">
                                    {tpl.body}
                                  </span>
                                  <span className="mt-0.5 font-mono-ui text-[9.5px] tracking-wide text-muted-foreground/60">
                                    id · {tpl.id.slice(0, 8)}
                                  </span>
                                </button>
                                <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      openEditTemplate(tpl);
                                    }}
                                    className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                                    title="Rename or edit body"
                                    disabled={templateMutating}
                                  >
                                    <Pencil className="h-3 w-3" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDeleteTemplateTarget(tpl);
                                    }}
                                    className="rounded-sm p-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                                    title="Delete template"
                                    disabled={templateMutating}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                          {editingThisLane?.mode === "create" && (
                            <TemplateEditorCard
                              editor={editingThisLane}
                              onChange={(patch) =>
                                setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                              }
                              onSave={saveTemplate}
                              onCancel={closeTemplateEditor}
                              busy={templateMutating}
                            />
                          )}
                          {laneTemplates.length === 0 && editingThisLane?.mode !== "create" && (
                            <button
                              type="button"
                              onClick={() => openCreateTemplate(lane.id)}
                              className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border/70 px-3 py-4 text-[11.5px] text-muted-foreground hover:border-border hover:text-foreground"
                              disabled={templateMutating}
                            >
                              <Plus className="h-3.5 w-3.5" />
                              Add the first {lane.label.toLowerCase()} template
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <label className="block">
                  <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
                    Initial reply template {draft.autoReplyEnabled && <span className="text-destructive">*</span>}
                  </span>
                  <textarea
                    value={draft.autoReplyTemplate}
                    onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
                    rows={4}
                    placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
                    className="min-h-28 w-full resize-y rounded-md border border-border bg-card/60 px-3 py-2 text-[13px] leading-5 text-foreground outline-none backdrop-blur-sm placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
                  />
                  <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">
                    {firstTouchTemplates.length > 0
                      ? "Pick one above to load it here — edit freely. Used both as the auto-send template (if enabled) and the default draft otherwise."
                      : "Used both as the auto-send template (if enabled) and the default draft otherwise."}
                  </span>
                </label>
                <WizardField
                  label="Follow-up cadence (days between nudges)"
                  value={draft.followUpCadenceDays}
                  onChange={(v) => updateField("followUpCadenceDays", v)}
                  placeholder="2"
                  type="number"
                />
              </div>
            )}
          </div>
        </div>

        {(error || savedMessage) && (
          <div
            className={cn(
              "mt-6 flex items-baseline gap-3 border-t py-3 text-[13px]",
              error ? "border-destructive" : "border-success",
            )}
          >
            <span
              className={cn(
                "shrink-0 font-mono-ui text-[10px] uppercase tracking-wider",
                error ? "text-destructive" : "text-success",
              )}
            >
              {error ? "Error" : "Saved"}
            </span>
            <span className="text-foreground">{error || savedMessage}</span>
          </div>
        )}

        <div className="mt-9 flex items-center justify-between gap-3 border-t border-border/60 pt-5">
          <div className="min-h-[18px] flex-1 text-[12px] leading-5 text-muted-foreground/80">
            {showMissing && missingMessage && <span className="text-destructive">{missingMessage}</span>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" onClick={handleBack} disabled={busy || isFirst}>
              Back
            </Button>
            <Button
              onClick={() => void handleNext()}
              disabled={busy || !canAdvance}
              className="min-w-[140px]"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {isLast ? "Finish setup" : "Continue"}
            </Button>
          </div>
        </div>
       </div>
      </div>
      <ConfirmDialog
        open={deleteTemplateTarget !== null}
        title={`Delete "${deleteTemplateTarget?.name ?? "this template"}"?`}
        description="This removes the outreach template from the wizard. This action cannot be undone here."
        confirmLabel="Delete"
        destructive
        loading={templateMutating}
        onCancel={() => setDeleteTemplateTarget(null)}
        onConfirm={() => {
          if (deleteTemplateTarget) void deleteTemplate(deleteTemplateTarget);
        }}
      />
    </div>,
    document.body,
  );
}

type TemplateEditorState =
  | { mode: "create"; lane: string; name: string; body: string }
  | { mode: "edit"; id: string; lane: string; name: string; body: string };

function TemplateEditorCard({
  editor,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  editor: TemplateEditorState;
  onChange: (patch: Partial<{ name: string; body: string }>) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-primary/40 bg-card/70 px-3 py-2.5 backdrop-blur-sm sm:col-span-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {editor.mode === "create" ? "New template" : "Edit template"}
        </span>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Cancel template edit"
          title="Cancel"
          className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          disabled={busy}
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      <input
        type="text"
        value={editor.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="Template name (e.g. Open house live)"
        className="w-full rounded-md border border-border bg-background/40 px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <textarea
        value={editor.body}
        onChange={(e) => onChange({ body: e.target.value })}
        rows={4}
        placeholder="Body. Use {first_name}, {area}, {topic}, etc. Add [[gif:keyword]] to attach a GIF."
        className="min-h-24 w-full resize-y rounded-md border border-border bg-background/40 px-3 py-2 text-[12.5px] leading-5 text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground hover:text-foreground"
          disabled={busy}
        >
          Cancel
        </button>
        <Button size="sm" onClick={onSave} disabled={busy} className="h-7 px-3 text-[11.5px]">
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          {editor.mode === "create" ? "Add template" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function WizardField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  fullWidth = false,
  helper,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
  helper?: React.ReactNode;
}) {
  return (
    <label className={cn("block min-w-0", fullWidth && "md:col-span-2")}>
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        spellCheck={type === "password" || type === "email" ? false : undefined}
        className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {helper && (
        <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">{helper}</span>
      )}
    </label>
  );
}

function ItemCard({
  title,
  description,
  status,
  children,
}: {
  title: string;
  description: string;
  status: AdminSetupItemStatus;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{description}</p>
        </div>
        <StatusBadge status={status} />
      </header>
      {children && <div className="mt-3 space-y-2">{children}</div>}
    </section>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </label>
  );
}

const OUTREACH_HINTS: Record<
  OutreachConnectorRef["id"],
  { tagline: string; routes: string }
> = {
  "apple-messages": {
    tagline: "iMessage from your Mac. Auto-picks blue-bubble route for iPhone leads.",
    routes: "Pairs with Messages.app via the existing local bridge — already syncing 237k+ records on this Mac.",
  },
  "sms-provider": {
    tagline: "Business SMS line (Twilio, Sinch, MessageBird, etc.) for non-iPhone leads.",
    routes: "Two-way SMS over a webhook/API. Use for green-bubble Android leads.",
  },
  "android-device": {
    tagline: "Personal Android device SMS via export or helper.",
    routes: "Backup/export route — does not claim live sync unless a helper is wired.",
  },
  "rcs": {
    tagline: "Rich messaging (read receipts, media, typing) for Android leads.",
    routes: "Business RCS provider or Twilio RCS. Personal-device RCS is import-only.",
  },
};

function ConnectorStatusBadge({ connector }: { connector: OutreachConnectorRef }) {
  if (connector.connected) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (connector.importOnly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Import only
      </span>
    );
  }
  if (connector.blocked) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-[10.5px] font-medium text-destructive">
        <AlertTriangle className="h-3 w-3" /> Blocked
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Not configured
    </span>
  );
}

function OutreachConnectorsCard({
  connectors,
  outreachReady,
  crmStatus,
  crmProvider,
}: {
  connectors: OutreachConnectorRef[];
  outreachReady: boolean;
  crmStatus: AdminSetupItemStatus;
  crmProvider: string;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">Outreach channels</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            iMessage, SMS, and RCS aren't configured here — they live as Source Connectors so the same wiring
            powers ingestion (read-only message index) and outbound. Elevation auto-routes: iPhone leads get
            iMessage, Android leads fall through to SMS / RCS.
          </p>
        </div>
        {outreachReady ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
            <CheckCircle2 className="h-3 w-3" /> Ready
            {crmStatus === "connected" && crmProvider ? ` (via ${crmProvider})` : ""}
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
            <Circle className="h-3 w-3" /> None active
          </span>
        )}
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link
          to="/config#connectors"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11.5px] font-medium text-foreground hover:bg-muted"
        >
          <LinkIcon className="h-3 w-3" />
          Open Source Connectors
        </Link>
        <span className="text-[10.5px] text-muted-foreground">
          Config → Source connectors. Each row below opens its setup task.
        </span>
      </div>

      <div className="space-y-1.5">
        {connectors.length === 0 ? (
          <ListSkeleton rows={3} />
        ) : (
          connectors.map((connector) => {
            const hint = OUTREACH_HINTS[connector.id];
            return (
              <div
                key={connector.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-muted/15 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">{connector.label}</span>
                    <ConnectorStatusBadge connector={connector} />
                    {connector.totalRecords > 0 && (
                      <span className="text-[10.5px] text-muted-foreground">
                        {connector.totalRecords.toLocaleString()} records
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint?.tagline}</p>
                  {connector.nextOperatorStep && !connector.connected && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                      Next: {connector.nextOperatorStep}
                    </p>
                  )}
                  {connector.lastError && (
                    <p className="mt-1 text-[10.5px] text-destructive/80">{connector.lastError}</p>
                  )}
                </div>
                <Link
                  to="/config#connectors"
                  className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
                >
                  Configure <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

export function LeadsSetupLaunch({
  setup,
  onSetupUpdated,
  forceOnboarding = false,
  onForceOnboardingDone,
}: {
  setup: LeadsSetupSnapshot;
  onSetupUpdated: (next: LeadsSetupSnapshot) => void;
  forceOnboarding?: boolean;
  onForceOnboardingDone?: () => void;
}) {
  const [draft, setDraft] = useState<LeadsSetupDraft>(() => leadsDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [phase, setPhase] = useState<"gate" | "welcome" | "wizard" | "form">(() =>
    forceOnboarding ? "welcome" : isBrandNewLeadsSetup(setup) ? "gate" : "form",
  );
  const [outreachSourceConnectors, setOutreachSourceConnectors] = useState<SourceConnectorStatus[]>([]);
  const [sourceConnectorsLoading, setSourceConnectorsLoading] = useState(true);
  const [firstTouchTemplates, setFirstTouchTemplates] = useState<OutreachTemplate[]>([]);

  const refreshSourceConnectors = useCallback(async () => {
    setSourceConnectorsLoading(true);
    try {
      const resp = await api.getSourceConnectors();
      const ids = new Set<string>(OUTREACH_CONNECTOR_IDS);
      setOutreachSourceConnectors(resp.connectors.filter((c) => ids.has(c.id)));
    } catch {
      // best-effort — leave previous list in place
    } finally {
      setSourceConnectorsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSourceConnectors();
  }, [refreshSourceConnectors]);

  const refreshTemplates = useCallback(async () => {
    try {
      const resp = await api.getOutreachTemplates();
      setFirstTouchTemplates(resp.templates.filter((t) => t.active));
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.getOutreachTemplates();
        if (cancelled) return;
        const actives = resp.templates.filter((t) => t.active);
        setFirstTouchTemplates(actives);
        const policyVal = (setup.items.find((i) => i.key === "auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
        const stored = String(policyVal.initialMessageTemplate ?? "").trim();
        const currentMatchesDefault = draft.autoReplyTemplate.trim() === DEFAULT_AUTO_REPLY_TEMPLATE.trim();
        const firstTouchDefault = actives.find((t) => t.lane === "new-outreach");
        if (firstTouchDefault && !stored && currentMatchesDefault) {
          setDraft((prev) => ({ ...prev, autoReplyTemplate: firstTouchDefault.body }));
        }
      } catch {
        // best-effort — empty list falls back to default opener
      }
    })();
    return () => {
      cancelled = true;
    };
    // intentional one-shot on mount — refetch is via refreshTemplates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (forceOnboarding && phase === "form") {
      onForceOnboardingDone?.();
    }
  }, [forceOnboarding, phase, onForceOnboardingDone]);

  useEffect(() => {
    setDraft(leadsDraftFromSnapshot(setup));
  }, [setup]);

  const byKey = useMemo(() => new Map(setup.items.map((item: LeadsSetupItem) => [item.key, item])), [setup.items]);
  const crmItem = byKey.get("crm");
  const metaItem = byKey.get("meta_lead_ads");
  const googleItem = byKey.get("google_lead_forms");
  const webhookItem = byKey.get("website_form_webhook");
  const policyItem = byKey.get("auto_reply_policy");

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateLeadsSetup(buildItemUpdates(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.complete
          ? "Saved. Everything required is in — hit 'Mark complete' to lift the gate."
          : `Saved. ${updated.missingRequiredKeys.length} item(s) still required.`,
      );
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const markComplete = useCallback(async () => {
    setCompleting(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
      const completed = await api.completeLeadsSetup();
      onSetupUpdated(completed);
      onForceOnboardingDone?.();
    } catch (err) {
      setError(errorMessage(err, "Could not complete setup"));
    } finally {
      setCompleting(false);
    }
  }, [draft, onSetupUpdated, onForceOnboardingDone]);

  const updateField = useCallback(<K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const pct = setup.completionPct ?? 0;
  const crmStatus = crmItem?.status ?? "missing";
  const crmProvider = (crmItem?.provider || "").trim();
  const leadSourcesReady = setup.leadSourcesReady;
  const outreachReady = setup.outreachReady;
  const outreachConnectors = setup.outreachConnectors ?? [];

  const handleWizardFinish = useCallback(async () => {
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
      return;
    }
    playOnboardingChime();
    setPhase("form");
  }, [draft]);

  if (phase === "gate") {
    return (
      <LeadsOnboardingGate
        onStart={() => setPhase("welcome")}
        onSkip={() => setPhase("form")}
      />
    );
  }

  if (phase === "welcome") {
    return <LeadsOnboardingWelcome onContinue={() => setPhase("wizard")} />;
  }

  if (phase === "wizard") {
    return (
      <LeadsOnboardingWizard
        draft={draft}
        updateField={updateField}
        onAdvanceSave={save}
        onFinish={handleWizardFinish}
        saving={saving}
        completing={completing}
        error={error}
        savedMessage={savedMessage}
        outreachSourceConnectors={outreachSourceConnectors}
        refreshSourceConnectors={refreshSourceConnectors}
        sourceConnectorsLoading={sourceConnectorsLoading}
        firstTouchTemplates={firstTouchTemplates}
        refreshTemplates={refreshTemplates}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Leads onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              CRM is inherited from Admin setup and already counts as an outreach lane. Wire at least one
              lead source (Meta / Google / Website webhook) and set your auto-reply policy. Texting channels
              (iMessage / SMS / RCS) are managed in Source Connectors below — Elevation auto-routes by lead device.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPhase("welcome")}
              className="h-7 gap-1 px-2 text-[11px]"
            >
              <Sparkles className="h-3 w-3" />
              Run guided onboarding
            </Button>
            <div className="flex flex-col items-end gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {setup.completedRequiredCount}/{setup.requiredCount} required
              </span>
              <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
              </div>
              <span className="text-[10.5px] text-muted-foreground">{pct}%</span>
            </div>
          </div>
        </div>
        {forceOnboarding && (
          <div className="mt-3 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[10.5px] text-muted-foreground">
            <Sparkles className="h-3 w-3" /> Re-running onboarding — existing state preserved
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
          {error}
        </div>
      )}
      {savedMessage && (
        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">
          {savedMessage}
        </div>
      )}

      <ItemCard
        title="CRM (inherited from Admin)"
        description={
          crmProvider
            ? `Reading from admin_setup_profile.crm_provider. Manage in Admin → Connectors.`
            : "No CRM set in Admin yet. Finish Admin onboarding first — Leads can't store contacts without a CRM."
        }
        status={crmStatus}
      >
        <div className="text-[12px] text-foreground">
          {crmProvider ? `Connected to ${crmProvider}.` : "Not configured."}
        </div>
      </ItemCard>

      <ItemCard
        title="Meta Lead Ads (optional)"
        description="Skip if you don't run Facebook / Instagram lead-form ads. One Pipeboard token — ad accounts, pages, and lead forms are auto-discovered."
        status={metaItem?.status ?? "missing"}
      >
        <FieldRow
          label="MCP endpoint URL"
          value={draft.metaMcpEndpoint}
          onChange={(v) => updateField("metaMcpEndpoint", v)}
          placeholder="https://mcp.pipeboard.co/meta-ads-mcp"
        />
        <FieldRow
          label="Pipeboard API token"
          value={draft.metaMcpToken}
          onChange={(v) => updateField("metaMcpToken", v)}
          placeholder="••••••••"
          type="password"
        />
        <div className="flex flex-wrap items-center gap-3 text-[11.5px]">
          <a
            href="https://pipeboard.co/api-tokens"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
          >
            Get Pipeboard token (OAuth Facebook) <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="https://github.com/pipeboard-co/meta-ads-mcp"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-muted-foreground underline-offset-2 hover:underline hover:text-foreground"
          >
            Install guide <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </ItemCard>

      <ItemCard
        title="Google Lead Form Ads (optional)"
        description="Skip if you don't run Google Ads. One developer token — Elevation's CLI auto-discovers your customer ID and campaigns."
        status={googleItem?.status ?? "missing"}
      >
        <FieldRow
          label="Developer token"
          value={draft.googleDeveloperToken}
          onChange={(v) => updateField("googleDeveloperToken", v)}
          placeholder="abcDEF123-xyz"
          type="password"
        />
        <a
          href="https://developers.google.com/google-ads/api/docs/get-started/dev-token"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          How to get a Google Ads developer token <ExternalLink className="h-3 w-3" />
        </a>
      </ItemCard>

      <ItemCard
        title="Website form webhook"
        description="Catch-all webhook URL for landing-page and contact-us form submissions."
        status={webhookItem?.status ?? "missing"}
      >
        <FieldRow
          label="Webhook URL (POST endpoint for your form provider)"
          value={draft.webhookUrl}
          onChange={(v) => updateField("webhookUrl", v)}
          placeholder="https://elevate.yourdomain.com/api/leads/inbound"
        />
        <FieldRow
          label="Shared secret (optional — for HMAC verification)"
          value={draft.webhookSecret}
          onChange={(v) => updateField("webhookSecret", v)}
          placeholder="optional"
          type="password"
        />
      </ItemCard>

      <OutreachConnectorsCard
        connectors={outreachConnectors}
        outreachReady={outreachReady}
        crmStatus={crmStatus}
        crmProvider={crmProvider}
      />

      <ItemCard
        title="Auto-reply policy"
        description="Initial-touch behaviour and follow-up cadence default."
        status={policyItem?.status ?? "missing"}
      >
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.autoReplyEnabled}
            onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Send an automated first reply when a lead lands
        </label>
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Initial reply template</span>
          <textarea
            value={draft.autoReplyTemplate}
            onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
            rows={3}
            placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
            className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] leading-5 text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          />
        </label>
        <FieldRow
          label="Follow-up cadence (days between nudges)"
          value={draft.followUpCadenceDays}
          onChange={(v) => updateField("followUpCadenceDays", v)}
          placeholder="2"
          type="number"
        />
      </ItemCard>

      <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card/95 px-3 py-2 backdrop-blur">
        <div className="text-[11.5px] text-muted-foreground">
          {leadSourcesReady
            ? "Lead source ready (CRM and/or ads connector)."
            : "Need at least one lead source connected — CRM, Meta, Google, or website webhook."}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void save()} disabled={saving || completing}>
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
          <Button
            size="sm"
            onClick={() => void markComplete()}
            disabled={completing || saving || setup.requiredCount === 0}
            className={cn(setup.complete ? "" : "opacity-95")}
          >
            {completing ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Mark complete
          </Button>
        </div>
      </div>
    </div>
  );
}

export function useLeadsSetup(): {
  loading: boolean;
  setup: LeadsSetupSnapshot | null;
  error: string | null;
  setSetup: (next: LeadsSetupSnapshot) => void;
  refresh: () => Promise<void>;
} {
  const initialCache = readCachedLeadsSetup();
  const [setup, setSetupState] = useState<LeadsSetupSnapshot | null>(() => initialCache?.setup ?? null);
  const [loading, setLoading] = useState(() => !initialCache);
  const [error, setError] = useState<string | null>(null);

  const setSetup = useCallback((next: LeadsSetupSnapshot) => {
    setSetupState(writeCachedLeadsSetup(next));
  }, []);

  const refresh = useCallback(async () => {
    if (!readCachedLeadsSetup()) setLoading(true);
    setError(null);
    try {
      const snap = await loadLeadsSetup();
      setSetupState(snap);
    } catch (err) {
      setError(errorMessage(err, "Could not load leads setup"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, setup, error, setSetup, refresh };
}
