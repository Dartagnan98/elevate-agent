import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, CheckCircle2, Circle, AlertTriangle, ExternalLink, Sparkles, Link as LinkIcon, Play, Copy, RefreshCw, Plus, Pencil, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  LeadsSetupItem,
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
} from "@/lib/onboarding-sounds";
import {
  buildItemUpdates,
  connectorRecordTotal,
  connectorSetupCopy,
  connectorStateClasses,
  connectorStateLabel,
  DEFAULT_AUTO_REPLY_TEMPLATE,
  errorMessage,
  isBrandNewLeadsSetup,
  LEADS_TEMPLATE_LANES,
  leadsDraftFromSnapshot,
  loadLeadsSetup,
  OUTREACH_CONNECTOR_IDS,
  readCachedLeadsSetup,
  writeCachedLeadsSetup,
  type LeadsSetupDraft,
} from "./onboarding-data";
import {
  FieldRow,
  ItemCard,
  OUTREACH_HINTS,
  OutreachConnectorsCard,
  TemplateEditorCard,
  type TemplateEditorState,
  WizardField,
} from "./onboarding-form-parts";
import { LeadsOnboardingGate, LeadsOnboardingWelcome } from "./onboarding-shell";

export { preloadLeadsSetup } from "./onboarding-data";

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
  const [copyStatus, setCopyStatus] = useState<Record<string, { kind: "success" | "error"; message: string }>>({});

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
      const prompt = await promptForConnector(connector);
      await navigator.clipboard.writeText(prompt);
      setCopyStatus((prev) => ({
        ...prev,
        [connector.id]: { kind: "success", message: "Prompt copied." },
      }));
    } catch (err) {
      setCopyStatus((prev) => ({
        ...prev,
        [connector.id]: {
          kind: "error",
          message: err instanceof Error ? err.message : "Could not copy prompt.",
        },
      }));
    }
  }, [promptForConnector]);

  const [templateEditor, setTemplateEditor] = useState<TemplateEditorState | null>(null);
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
                        {copyStatus[connector.id] && (
                          <p
                            className={cn(
                              "mt-2 text-[11.5px]",
                              copyStatus[connector.id].kind === "error"
                                ? "text-destructive"
                                : "text-muted-foreground",
                            )}
                          >
                            {copyStatus[connector.id].message}
                          </p>
                        )}
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
