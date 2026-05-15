import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
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
import type { AgentSetupSnapshot, OAuthProvider } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
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
      "Sign in to a model provider, then pick which one the agent thinks with. Same auth state as the CLI — if `elevate auth add anthropic` is done, you'll see Anthropic connected below.",
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
      "Opt-in. Spin up the specialist PTY agents (Executive Assistant + Admin + Outreach + Ads + Marketing + Social Media) so the council runs alongside the main agent. Off by default for solo runtimes.",
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
  const [oauthProviders, setOauthProviders] = useState<OAuthProvider[] | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  useEffect(() => {
    setDraft(draftFromSnapshot(setup));
  }, [setup]);

  // Pull real CLI auth state so the Brain step reflects what's actually
  // signed in (anthropic via PKCE, claude-code subscription, etc) — NOT
  // just what's in ~/.elevate/.env. Refreshes when the user lands on or
  // returns to step 1.
  useEffect(() => {
    let cancelled = false;
    const fetchProviders = () => {
      api
        .getOAuthProviders()
        .then((resp) => {
          if (cancelled) return;
          setOauthProviders(resp.providers);
          // Auto-default primaryProvider when nothing is picked yet but
          // a CLI provider is signed in. Saves the user a click when they
          // already authed via `elevate auth add anthropic`.
          const current = draftRef.current.primaryProvider;
          if (!current.trim()) {
            const live = resp.providers.find(
              (p) => p.status.logged_in && p.id !== "claude-code",
            );
            const fallback = resp.providers.find((p) => p.status.logged_in);
            const pick = live ?? fallback;
            if (pick) {
              setDraft((prev) =>
                prev.primaryProvider.trim()
                  ? prev
                  : { ...prev, primaryProvider: pick.id === "claude-code" ? "anthropic" : pick.id },
              );
            }
          }
        })
        .catch(() => {
          if (!cancelled) setOauthProviders([]);
        });
    };
    if (AGENT_WIZARD_STEPS[stepIdx]?.id === "models") {
      fetchProviders();
    }
    return () => {
      cancelled = true;
    };
  }, [stepIdx]);

  const connectedProviderIds = useMemo(() => {
    if (!oauthProviders) return new Set<string>();
    return new Set(oauthProviders.filter((p) => p.status.logged_in).map((p) => p.id));
  }, [oauthProviders]);
  const anyProviderConnected = connectedProviderIds.size > 0;

  // Channels marked "configured" on the backend (env-detected or
  // wizard-confirmed). The toggle in the UI mirrors this so env-set creds
  // light up On instead of looking dead. User feedback: "these say off but
  // they are on?".
  const configuredChannelKeys = useMemo(() => {
    const out = new Set<string>();
    for (const item of setup.items ?? []) {
      if (
        item.key?.startsWith("operator_channel_") &&
        item.status === "configured"
      ) {
        out.add(item.key);
      }
    }
    return out;
  }, [setup.items]);

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
      // A provider is "available" if either: the user signed in via CLI/wizard
      // OAuth (real auth store), OR a key is detected in ~/.elevate/.env, OR
      // the user pasted one in this session.
      const providerConnected =
        connectedProviderIds.has(draft.primaryProvider) ||
        // claude-code subscription credentials count as anthropic access
        (draft.primaryProvider === "anthropic" && connectedProviderIds.has("claude-code"));
      const primaryHasKey =
        providerConnected ||
        Boolean(draft.primaryApiKey.trim()) ||
        draft.primarySecretPresent;
      if (!anyProviderConnected && !primaryHasKey) {
        return "Connect a model provider below before continuing.";
      }
      if (!draft.primaryProvider.trim() || !draft.primaryModel.trim() || !primaryHasKey) {
        return "Pick a provider and model the agent should think with.";
      }
      if (!draft.embeddingProvider.trim() || !draft.embeddingModel.trim()) {
        return "Pick an embedding provider and model — memory recall needs it.";
      }
      const embeddingHasKey =
        Boolean(draft.embeddingApiKey.trim()) || draft.embeddingSecretPresent;
      if (!draft.embeddingShareKey && !embeddingHasKey) {
        return "Paste an embedding API key, or check 'share the primary key.'";
      }
    }
    if (step.id === "memory") {
      if (draft.memoryProvider === "supabase") {
        const memoryHasKey =
          Boolean(draft.memorySupabaseKey.trim()) || draft.memorySecretPresent;
        if (!draft.memorySupabaseUrl.trim() || !memoryHasKey) {
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
                <WizardSection
                  title="Sign in to a model provider"
                  hint="Real CLI auth state. Sign in here once and the agent, the CLI, and every cron all share the same credential."
                >
                  <div className="-mx-1">
                    <OAuthProvidersCard
                      onError={(msg) => setError(msg)}
                      onSuccess={() => {
                        // Re-pull so the wizard picks up the new auth state.
                        api.getOAuthProviders().then((resp) => setOauthProviders(resp.providers)).catch(() => {});
                      }}
                    />
                  </div>
                </WizardSection>

                <WizardSection
                  title="Pick the brain"
                  hint="Which connected provider + which model id the agent should use as its primary."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    <WizardSelect
                      label="Provider"
                      value={draft.primaryProvider}
                      onChange={(v) => updateField("primaryProvider", v)}
                      options={[
                        { value: "", label: anyProviderConnected ? "— pick one —" : "— connect a provider above first —" },
                        {
                          value: "anthropic",
                          label: `Anthropic (Claude)${connectedProviderIds.has("anthropic") || connectedProviderIds.has("claude-code") ? " · connected" : ""}`,
                        },
                        {
                          value: "openai",
                          label: `OpenAI${connectedProviderIds.has("openai-codex") ? " · connected via Codex" : ""}`,
                        },
                        { value: "nous", label: `Nous Portal${connectedProviderIds.has("nous") ? " · connected" : ""}` },
                        { value: "qwen", label: `Qwen${connectedProviderIds.has("qwen-oauth") ? " · connected" : ""}` },
                        { value: "openrouter", label: "OpenRouter (paste key in .env)" },
                        { value: "azure_openai", label: "Azure OpenAI (paste key in .env)" },
                      ]}
                    />
                    <WizardField
                      label="Model ID"
                      value={draft.primaryModel}
                      onChange={(v) => updateField("primaryModel", v)}
                      placeholder={
                        draft.primaryProvider === "anthropic"
                          ? "claude-opus-4-7  or  claude-sonnet-4-6"
                          : draft.primaryProvider === "openai"
                            ? "gpt-4-turbo  or  o4-mini"
                            : "model id"
                      }
                    />
                  </div>
                  <p className="mt-3 text-[11.5px] leading-5 text-muted-foreground/80">
                    Don't see your provider connected? Hit "Sign in" on a card above, or paste the key in <code className="rounded bg-muted px-1 py-0.5 text-[10.5px]">~/.elevate/.env</code> and reload.
                  </p>
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
                        placeholder={
                          draft.embeddingSecretPresent && !draft.embeddingApiKey
                            ? `Already set — ${draft.embeddingSecretPreview} (paste to replace)`
                            : "sk-…"
                        }
                        type="password"
                        fullWidth
                        hint={
                          draft.embeddingSecretPresent && !draft.embeddingApiKey
                            ? "Detected from environment. Leave blank to keep using it."
                            : undefined
                        }
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
                      placeholder={
                        draft.memorySecretPresent && !draft.memorySupabaseKey
                          ? `Already set — ${draft.memorySecretPreview} (paste to replace)`
                          : "eyJhbGc…"
                      }
                      type="password"
                      fullWidth
                      hint={
                        draft.memorySecretPresent && !draft.memorySupabaseKey
                          ? "Detected from environment. Leave blank to keep using it."
                          : undefined
                      }
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
                  enabled={
                    configuredChannelKeys.has("operator_channel_telegram") ||
                    Boolean(
                      (draft.telegramBotToken || draft.telegramSecretPresent) &&
                        draft.telegramChatId,
                    )
                  }
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
                      placeholder={
                        draft.telegramSecretPresent && !draft.telegramBotToken
                          ? `Already set — ${draft.telegramSecretPreview} (paste to replace)`
                          : "123456789:ABC…"
                      }
                      type="password"
                      hint={
                        draft.telegramSecretPresent && !draft.telegramBotToken
                          ? "Detected from environment. Leave blank to keep using it."
                          : undefined
                      }
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
                  enabled={
                    configuredChannelKeys.has("operator_channel_discord") ||
                    Boolean(draft.discordBotToken && draft.discordChannelId)
                  }
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
                  enabled={
                    configuredChannelKeys.has("operator_channel_whatsapp") ||
                    Boolean(draft.whatsappProvider && draft.whatsappToken)
                  }
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
                  enabled={
                    configuredChannelKeys.has("operator_channel_slack") ||
                    Boolean(draft.slackWebhookUrl)
                  }
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
                        draft.imageSecretPresent && !draft.imageApiKey
                          ? `Already set — ${draft.imageSecretPreview} (paste to replace)`
                          : draft.imageProvider === "nano_banana"
                            ? "AIzaSy…"
                            : "sk-…"
                      }
                      type="password"
                      hint={
                        draft.imageSecretPresent && !draft.imageApiKey
                          ? "Detected from environment. Leave blank to keep using it."
                          : undefined
                      }
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
                      placeholder={
                        draft.composioSecretPresent && !draft.composioApiKey
                          ? `Already set — ${draft.composioSecretPreview} (paste to replace)`
                          : "csk_…"
                      }
                      type="password"
                      fullWidth
                      hint={
                        draft.composioSecretPresent && !draft.composioApiKey
                          ? "Detected from environment. Leave blank to keep using it."
                          : undefined
                      }
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
                hint="Optional. Specialist PTY agents (Executive Assistant coordinates; Admin runs deal files; Outreach handles follow-up; Ads runs paid; Marketing owns listings + email; Social Media owns organic) run alongside the main agent for parallel work."
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
                        { value: "cortextos_default", label: "Default council (Executive Assistant + 5 specialists)" },
                        { value: "cortextos_minimal", label: "Minimal (Executive Assistant only)" },
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
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
  hint?: string;
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
      {hint && (
        <span className="mt-1.5 block text-[11px] leading-4 text-muted-foreground/80">{hint}</span>
      )}
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
