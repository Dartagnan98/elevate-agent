import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentSetupSnapshot } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  playOnboardingChime,
  playOnboardingClick,
  playOnboardingSwell,
  playOnboardingWhoosh,
} from "@/lib/onboarding-sounds";
import {
  buildItemUpdates,
  draftFromSnapshot,
  type AgentSetupDraft,
} from "./index";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

type AgentWizardStepId =
  | "models"
  | "memory"
  | "inbound"
  | "tools"
  | "outbound"
  | "subagents";

type AgentWizardStep = {
  id: AgentWizardStepId;
  eyebrow: string;
  title: string;
  subtitle: string;
};

const AGENT_WIZARD_STEPS: AgentWizardStep[] = [
  {
    id: "models",
    eyebrow: "Step 1 of 6",
    title: "Brain",
    subtitle:
      "The model the agent thinks with, plus an embedding model for memory recall. You can paste one API key for both — Anthropic and OpenAI both work.",
  },
  {
    id: "memory",
    eyebrow: "Step 2 of 6",
    title: "Memory store",
    subtitle:
      "Where long-term memory lives. Local SQLite is zero-config and runs on this Mac. Pick Supabase later if you want memory shared across devices.",
  },
  {
    id: "inbound",
    eyebrow: "Step 3 of 6",
    title: "How the agent hears you",
    subtitle:
      "Pick every surface you want to reach the agent from — CLI is always on. Telegram and iMessage are the most common. Skip anything you don't use.",
  },
  {
    id: "tools",
    eyebrow: "Step 4 of 6",
    title: "APIs + tools",
    subtitle:
      "Optional. Image generation (Nano Banana) lights up /generate, /edit, /restore. Composio plugs in 100+ pre-wired tools — Gmail, Calendar, Slack, GitHub, Notion.",
  },
  {
    id: "outbound",
    eyebrow: "Step 5 of 6",
    title: "How the agent sends messages",
    subtitle:
      "Outbound iMessage uses the Messages.app on this Mac. Anything you wire here lets the agent write back to leads, clients, or yourself.",
  },
  {
    id: "subagents",
    eyebrow: "Step 6 of 6",
    title: "Sub-agents",
    subtitle:
      "Opt-in. Spin up the cortextos PTY specialists (Jimmy + Gary + Nina + Ricky + QC) so the agent has a council. Off by default for solo runtimes.",
  },
];

export function AgentOnboardingWelcome({ onContinue }: { onContinue: () => void }) {
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
      aria-label="Welcome to Elevate"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevate · Agent
        </div>
        <h1 className="onboarding-rise-delay-1 mt-4 text-[52px] font-medium leading-[1.02] tracking-tight text-foreground">
          Bring the agent online.
        </h1>
        <p className="onboarding-rise-delay-2 mt-4 max-w-lg text-[15px] leading-7 text-muted-foreground">
          Pick a model, give it a memory store, and tell it which channels to listen on. Same form you'd find buried in Settings — guided.
        </p>
        <Button
          size="lg"
          onClick={handleStart}
          disabled={exiting}
          className="onboarding-rise-delay-3 mt-9 h-12 min-w-[240px] px-7 text-[14px]"
        >
          Start onboarding
        </Button>
      </div>
    </div>,
    document.body,
  );
}

export function AgentOnboardingWizard({
  setup,
  onSetupUpdated,
  onFinish,
}: {
  setup: AgentSetupSnapshot;
  onSetupUpdated: (next: AgentSetupSnapshot) => void;
  onFinish: () => void;
}) {
  const [draft, setDraft] = useState<AgentSetupDraft>(() => draftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showMissing, setShowMissing] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);

  useEffect(() => {
    setDraft(draftFromSnapshot(setup));
  }, [setup]);

  const step = AGENT_WIZARD_STEPS[stepIdx];
  const isLast = stepIdx === AGENT_WIZARD_STEPS.length - 1;
  const isFirst = stepIdx === 0;
  const busy = saving || completing;

  const updateField = useCallback(
    <K extends keyof AgentSetupDraft>(key: K, value: AgentSetupDraft[K]) => {
      setDraft((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const missingMessage = useMemo(() => {
    if (step.id === "models") {
      if (!draft.primaryProvider.trim() || !draft.primaryModel.trim() || !draft.primaryApiKey.trim()) {
        return "Pick a provider, model, and paste an API key before continuing.";
      }
      if (!draft.embeddingProvider.trim() || !draft.embeddingModel.trim()) {
        return "Pick an embedding provider and model — memory recall needs it.";
      }
      if (!draft.embeddingShareKey && !draft.embeddingApiKey.trim()) {
        return "Paste an embedding API key, or check 'share the primary key.'";
      }
    }
    if (step.id === "memory") {
      if (draft.memoryProvider === "supabase") {
        if (!draft.memorySupabaseUrl.trim() || !draft.memorySupabaseKey.trim()) {
          return "Paste your Supabase URL and service-role key, or switch back to local SQLite.";
        }
      } else if (!draft.memoryProvider.trim()) {
        return "Pick a memory store.";
      }
    }
    return null;
  }, [step.id, draft]);

  const canAdvance = missingMessage == null;

  useEffect(() => {
    setShowMissing(false);
  }, [stepIdx]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateAgentSetup(buildItemUpdates(draft));
      onSetupUpdated(updated);
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
      throw err;
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const handleFinish = useCallback(async () => {
    setError(null);
    setCompleting(true);
    try {
      await api.updateAgentSetup(buildItemUpdates(draft));
      const completed = await api.completeAgentSetup();
      onSetupUpdated(completed);
    } catch (err) {
      setError(errorMessage(err, "Could not complete onboarding"));
      setCompleting(false);
      return;
    }
    playOnboardingChime();
    setCompleting(false);
    onFinish();
  }, [draft, onSetupUpdated, onFinish]);

  const handleNext = useCallback(async () => {
    if (busy) return;
    if (!canAdvance) {
      setShowMissing(true);
      return;
    }
    playOnboardingClick();
    try {
      await save();
    } catch {
      return;
    }
    if (isLast) {
      await handleFinish();
      return;
    }
    setStepIdx((idx) => Math.min(idx + 1, AGENT_WIZARD_STEPS.length - 1));
  }, [busy, canAdvance, isLast, save, handleFinish]);

  const handleBack = useCallback(() => {
    if (busy) return;
    playOnboardingClick();
    setStepIdx((idx) => Math.max(idx - 1, 0));
  }, [busy]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Agent onboarding wizard"
      className="onboarding-overlay fixed inset-0 z-[100] overflow-y-auto"
    >
      <div className="onboarding-aurora-bg pointer-events-none fixed inset-0" aria-hidden />
      <div className="relative flex min-h-full items-center justify-center px-6 py-10">
       <div className="relative flex w-full max-w-3xl flex-col">
        <div className="mb-7 flex items-center gap-1.5">
          {AGENT_WIZARD_STEPS.map((s, idx) => (
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

          <div className="onboarding-rise-delay-3 mt-8 flex flex-col gap-5">
            {step.id === "models" && (
              <>
                <WizardSection title="Primary LLM" hint="The model the agent thinks with.">
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardSelect
                      label="Provider"
                      value={draft.primaryProvider}
                      onChange={(v) => updateField("primaryProvider", v)}
                      options={[
                        { value: "", label: "— pick one —" },
                        { value: "anthropic", label: "Anthropic (Claude)" },
                        { value: "openai", label: "OpenAI" },
                        { value: "openrouter", label: "OpenRouter" },
                        { value: "azure_openai", label: "Azure OpenAI" },
                      ]}
                    />
                    <WizardField
                      label="Model ID"
                      value={draft.primaryModel}
                      onChange={(v) => updateField("primaryModel", v)}
                      placeholder="claude-opus-4-7  or  gpt-4-turbo"
                    />
                    <WizardField
                      label="API key"
                      value={draft.primaryApiKey}
                      onChange={(v) => updateField("primaryApiKey", v)}
                      placeholder="sk-ant-…  or  sk-…"
                      type="password"
                      fullWidth
                    />
                  </div>
                </WizardSection>

                <WizardSection title="Embedding model" hint="Powers memory recall + semantic search.">
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardSelect
                      label="Provider"
                      value={draft.embeddingProvider}
                      onChange={(v) => updateField("embeddingProvider", v)}
                      options={[
                        { value: "", label: "— pick one —" },
                        { value: "openai", label: "OpenAI" },
                        { value: "voyage", label: "Voyage AI" },
                        { value: "cohere", label: "Cohere" },
                        { value: "local", label: "Local (sentence-transformers)" },
                      ]}
                    />
                    <WizardField
                      label="Model ID"
                      value={draft.embeddingModel}
                      onChange={(v) => updateField("embeddingModel", v)}
                      placeholder="text-embedding-3-large  or  voyage-3"
                    />
                  </div>
                  <label className="mt-3 flex items-center gap-2 text-[12.5px] text-foreground">
                    <input
                      type="checkbox"
                      checked={draft.embeddingShareKey}
                      onChange={(e) => updateField("embeddingShareKey", e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-border accent-primary"
                    />
                    Share the primary LLM key
                  </label>
                  {!draft.embeddingShareKey && (
                    <div className="mt-3">
                      <WizardField
                        label="Embedding API key"
                        value={draft.embeddingApiKey}
                        onChange={(v) => updateField("embeddingApiKey", v)}
                        placeholder="sk-…"
                        type="password"
                        fullWidth
                      />
                    </div>
                  )}
                </WizardSection>
              </>
            )}

            {step.id === "memory" && (
              <WizardSection
                title="Where memory lives"
                hint="Local is the safe default. Switch to Supabase when you want shared memory."
              >
                <WizardSelect
                  label="Provider"
                  value={draft.memoryProvider}
                  onChange={(v) => updateField("memoryProvider", v)}
                  options={[
                    { value: "sqlite_local", label: "Local SQLite (recommended)" },
                    { value: "supabase", label: "Supabase (shared across devices)" },
                  ]}
                />
                {draft.memoryProvider === "supabase" && (
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <WizardField
                      label="Supabase project URL"
                      value={draft.memorySupabaseUrl}
                      onChange={(v) => updateField("memorySupabaseUrl", v)}
                      placeholder="https://xxx.supabase.co"
                      fullWidth
                    />
                    <WizardField
                      label="Service-role key"
                      value={draft.memorySupabaseKey}
                      onChange={(v) => updateField("memorySupabaseKey", v)}
                      placeholder="eyJhbGc…"
                      type="password"
                      fullWidth
                    />
                  </div>
                )}
                <p className="mt-3 text-[11.5px] leading-5 text-muted-foreground/80">
                  On finish, Elevate creates the operational tables (contacts, conversations, deals, tasks) via migrations.
                </p>
              </WizardSection>
            )}

            {step.id === "inbound" && (
              <>
                <ChannelToggle
                  enabled={draft.cliEnabled}
                  onToggle={(v) => updateField("cliEnabled", v)}
                  title="CLI"
                  hint="Talk to the agent inside your terminal with `elevate`. Always available — keep on."
                />

                <ChannelToggle
                  enabled={Boolean(draft.telegramBotToken && draft.telegramChatId)}
                  onToggle={(v) => {
                    if (!v) {
                      updateField("telegramBotToken", "");
                      updateField("telegramChatId", "");
                    }
                  }}
                  title="Telegram"
                  hint="Bot token from @BotFather + your chat id. Push approvals and status messages arrive in Telegram."
                  link={{ href: "https://t.me/BotFather", label: "Open @BotFather" }}
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardField
                      label="Bot token"
                      value={draft.telegramBotToken}
                      onChange={(v) => updateField("telegramBotToken", v)}
                      placeholder="123456789:ABC…"
                      type="password"
                    />
                    <WizardField
                      label="Chat id"
                      value={draft.telegramChatId}
                      onChange={(v) => updateField("telegramChatId", v)}
                      placeholder="-1001234567890  or  987654321"
                    />
                  </div>
                </ChannelToggle>

                <ChannelToggle
                  enabled={draft.imessageEnabled}
                  onToggle={(v) => updateField("imessageEnabled", v)}
                  title="iMessage"
                  hint="Read inbound iMessage threads from the local Messages database on this Mac. Requires Full Disk Access for Terminal/Elevate."
                >
                  <WizardField
                    label="Your iMessage handle (optional)"
                    value={draft.imessageHandle}
                    onChange={(v) => updateField("imessageHandle", v)}
                    placeholder="+15551234567  or  you@icloud.com"
                    fullWidth
                  />
                </ChannelToggle>

                <ChannelToggle
                  enabled={Boolean(draft.discordBotToken && draft.discordChannelId)}
                  onToggle={(v) => {
                    if (!v) {
                      updateField("discordBotToken", "");
                      updateField("discordChannelId", "");
                    }
                  }}
                  title="Discord"
                  hint="Bot token + channel id. DMs and channel pings route to the agent."
                  link={{
                    href: "https://discord.com/developers/applications",
                    label: "Discord developer portal",
                  }}
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardField
                      label="Bot token"
                      value={draft.discordBotToken}
                      onChange={(v) => updateField("discordBotToken", v)}
                      placeholder="MTI…"
                      type="password"
                    />
                    <WizardField
                      label="Channel id"
                      value={draft.discordChannelId}
                      onChange={(v) => updateField("discordChannelId", v)}
                      placeholder="123456789012345678"
                    />
                  </div>
                </ChannelToggle>

                <ChannelToggle
                  enabled={Boolean(draft.whatsappProvider && draft.whatsappToken)}
                  onToggle={(v) => {
                    if (!v) {
                      updateField("whatsappProvider", "");
                      updateField("whatsappToken", "");
                      updateField("whatsappPhoneId", "");
                    }
                  }}
                  title="WhatsApp"
                  hint="WhatsApp Business API or a Composio-managed gateway."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardSelect
                      label="Gateway"
                      value={draft.whatsappProvider}
                      onChange={(v) => updateField("whatsappProvider", v)}
                      options={[
                        { value: "", label: "— pick one —" },
                        { value: "meta_cloud_api", label: "Meta Cloud API" },
                        { value: "composio", label: "Composio managed gateway" },
                        { value: "twilio", label: "Twilio WhatsApp Business" },
                      ]}
                    />
                    <WizardField
                      label="Access token"
                      value={draft.whatsappToken}
                      onChange={(v) => updateField("whatsappToken", v)}
                      placeholder="EAA…  or  csk_…"
                      type="password"
                    />
                    <WizardField
                      label="Phone number id (Cloud API)"
                      value={draft.whatsappPhoneId}
                      onChange={(v) => updateField("whatsappPhoneId", v)}
                      placeholder="1234567890"
                      fullWidth
                    />
                  </div>
                </ChannelToggle>

                <ChannelToggle
                  enabled={Boolean(draft.slackWebhookUrl)}
                  onToggle={(v) => {
                    if (!v) {
                      updateField("slackWebhookUrl", "");
                      updateField("slackChannel", "");
                    }
                  }}
                  title="Slack"
                  hint="Incoming webhook URL + optional target channel."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardField
                      label="Incoming webhook URL"
                      value={draft.slackWebhookUrl}
                      onChange={(v) => updateField("slackWebhookUrl", v)}
                      placeholder="https://hooks.slack.com/services/T…/B…/…"
                      fullWidth
                    />
                    <WizardField
                      label="Channel (optional)"
                      value={draft.slackChannel}
                      onChange={(v) => updateField("slackChannel", v)}
                      placeholder="#elevate-ops"
                      fullWidth
                    />
                  </div>
                </ChannelToggle>
              </>
            )}

            {step.id === "tools" && (
              <>
                <WizardSection
                  title="Image generation"
                  hint="Optional. Nano Banana Gemini-CLI ships preinstalled — paste a Gemini API key and /generate, /edit, /restore, /icon, /pattern, /story, /diagram light up."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardSelect
                      label="Provider"
                      value={draft.imageProvider}
                      onChange={(v) => updateField("imageProvider", v)}
                      options={[
                        { value: "", label: "— skip —" },
                        { value: "nano_banana", label: "Nano Banana (Gemini CLI)" },
                        { value: "openai_images", label: "OpenAI Images (DALL-E)" },
                        { value: "replicate", label: "Replicate" },
                      ]}
                    />
                    <WizardField
                      label={
                        draft.imageProvider === "nano_banana"
                          ? "Gemini API key"
                          : "API key"
                      }
                      value={draft.imageApiKey}
                      onChange={(v) => updateField("imageApiKey", v)}
                      placeholder={
                        draft.imageProvider === "nano_banana" ? "AIzaSy…" : "sk-…"
                      }
                      type="password"
                    />
                  </div>
                  {draft.imageProvider === "nano_banana" && (
                    <a
                      href="https://aistudio.google.com/apikey"
                      target="_blank"
                      rel="noreferrer noopener"
                      className="mt-3 inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
                    >
                      Get a Gemini API key from AI Studio <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </WizardSection>

                <WizardSection
                  title="Composio (100+ pre-wired tools)"
                  hint="Optional. Gmail, Calendar, Slack, GitHub, Notion, Linear, HubSpot — Composio handles the OAuth for all of them. Connect accounts inside the Composio dashboard after pasting a key."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardField
                      label="Composio API key"
                      value={draft.composioApiKey}
                      onChange={(v) => updateField("composioApiKey", v)}
                      placeholder="csk_…"
                      type="password"
                      fullWidth
                    />
                    <WizardField
                      label="Workspace"
                      value={draft.composioWorkspace}
                      onChange={(v) => updateField("composioWorkspace", v)}
                      placeholder="default"
                    />
                  </div>
                  <a
                    href="https://app.composio.dev/"
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-3 inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
                  >
                    Open Composio dashboard <ExternalLink className="h-3 w-3" />
                  </a>
                </WizardSection>
              </>
            )}

            {step.id === "outbound" && (
              <ChannelToggle
                enabled={draft.outboundImessageEnabled}
                onToggle={(v) => updateField("outboundImessageEnabled", v)}
                title="Outbound iMessage"
                hint="Let the agent send messages from Messages.app on this Mac. Requires the local Messages bridge + Accessibility permission. Replies go from whichever Apple ID you're signed in as."
              >
                <WizardField
                  label="Sender handle (optional override)"
                  value={draft.outboundImessageSenderHandle}
                  onChange={(v) => updateField("outboundImessageSenderHandle", v)}
                  placeholder="+15551234567  or  you@icloud.com"
                  fullWidth
                />
              </ChannelToggle>
            )}

            {step.id === "subagents" && (
              <WizardSection
                title="cortextos sub-agents"
                hint="Optional. Specialist PTY agents (Jimmy = orchestrator, Gary = ads, Nina = analyst, Ricky = copy, QC = reviewer) run alongside the main agent for parallel work."
              >
                <label className="flex items-center gap-2 text-[13px] text-foreground">
                  <input
                    type="checkbox"
                    checked={draft.subagentsEnabled}
                    onChange={(e) => updateField("subagentsEnabled", e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-border accent-primary"
                  />
                  Enable sub-agents
                </label>
                {draft.subagentsEnabled && (
                  <div className="mt-3">
                    <WizardSelect
                      label="Pack"
                      value={draft.subagentsPack}
                      onChange={(v) => updateField("subagentsPack", v)}
                      options={[
                        { value: "cortextos_default", label: "cortextos default (Jimmy + 4 specialists)" },
                        { value: "cortextos_minimal", label: "cortextos minimal (Jimmy only)" },
                      ]}
                    />
                  </div>
                )}
              </WizardSection>
            )}
          </div>

          {error && (
            <div className="mt-6 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
              <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
              {error}
            </div>
          )}
        </div>

        <div className="mt-9 flex items-center justify-between gap-3 border-t border-border/60 pt-5">
          <div className="min-h-[18px] flex-1 text-[12px] leading-5 text-muted-foreground/80">
            {showMissing && missingMessage && (
              <span className="text-destructive">{missingMessage}</span>
            )}
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

function WizardSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card/60 px-4 py-4 backdrop-blur-sm">
      <header className="mb-3">
        <h3 className="text-[13.5px] font-semibold text-foreground">{title}</h3>
        {hint && <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">{hint}</p>}
      </header>
      {children}
    </section>
  );
}

function ChannelToggle({
  enabled,
  onToggle,
  title,
  hint,
  link,
  children,
}: {
  enabled: boolean;
  onToggle: (v: boolean) => void;
  title: string;
  hint?: string;
  link?: { href: string; label: string };
  children?: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-md border bg-card/60 px-4 py-3 backdrop-blur-sm transition-colors",
        enabled ? "border-primary/40" : "border-border",
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[13.5px] font-semibold text-foreground">{title}</h3>
          {hint && <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">{hint}</p>}
          {link && (
            <a
              href={link.href}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
            >
              {link.label} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
        <label className="inline-flex shrink-0 cursor-pointer items-center gap-2 text-[11.5px] font-medium uppercase tracking-wide">
          <span className={cn("text-muted-foreground", enabled && "text-primary")}>
            {enabled ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <Circle className="h-4 w-4" />
            )}
          </span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggle(e.target.checked)}
            className="sr-only"
          />
          <span className="text-muted-foreground">{enabled ? "On" : "Off"}</span>
        </label>
      </header>
      {enabled && children && <div className="mt-3">{children}</div>}
    </section>
  );
}

function WizardField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  fullWidth = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
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
    </label>
  );
}

function WizardSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors focus:border-primary focus:ring-1 focus:ring-primary/30"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
