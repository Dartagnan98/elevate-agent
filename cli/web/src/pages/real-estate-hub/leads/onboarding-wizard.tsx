import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { OutreachTemplate, SourceConnectorStatus } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  playOnboardingClick,
  playOnboardingSwell,
} from "@/lib/onboarding-sounds";
import type { LeadsSetupDraft } from "./onboarding-data";
import { LeadsConnectorSetupStep } from "./onboarding-connector-step";
import { LeadsPolicyStep } from "./onboarding-policy-step";
import {
  WizardField,
} from "./onboarding-form-parts";

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

export function LeadsOnboardingWizard({
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
              <LeadsConnectorSetupStep
                connectors={outreachSourceConnectors}
                loading={sourceConnectorsLoading}
                runningPromptId={runningPromptId}
                copyStatus={copyStatus}
                onRefresh={() => void refreshSourceConnectors()}
                onRunPrompt={(connector) => void runPrompt(connector)}
                onCopyPrompt={(connector) => void copyPrompt(connector)}
              />
            )}

            {step.id === "policy" && (
              <LeadsPolicyStep
                draft={draft}
                updateField={updateField}
                firstTouchTemplates={firstTouchTemplates}
                refreshTemplates={refreshTemplates}
              />
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
    </div>,
    document.body,
  );
}
