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
import type {
  AgentSetupSnapshot,
  OAuthProvider,
  TelegramApprovedEntry,
  TelegramPendingEntry,
} from "@/lib/api-types";
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

// Static fallback catalogs. Mirrors `_PROVIDER_MODELS` + `DEFAULT_CODEX_MODELS`
// from cli/elevate_cli/models.py — only consulted when the live /api/models/by-provider
// endpoint returns empty (older dashboard build, offline provider, broken OAuth).
// Source of truth is the backend; this is just so the picker is never empty.
const STATIC_PROVIDER_MODELS: Record<string, string[]> = {
  "openai-codex": [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
  ],
  openai: [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-4.1",
    "gpt-4o",
    "gpt-4o-mini",
    "o3-mini",
  ],
  anthropic: [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
  ],
  "claude-code": [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
  ],
};

function staticModelsFor(providerId: string): string[] {
  return STATIC_PROVIDER_MODELS[providerId] ?? [];
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
      "Pick which channels the agent can write to. For bots and webhooks (Telegram, Discord, WhatsApp, Slack) the same credentials from Step 3 handle outbound — flip the channel off here to make the agent read-only on it. iMessage outbound uses Messages.app on this Mac.",
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

  // Map the wizard's grouped provider value to the concrete provider id the
  // backend catalog endpoint understands. "openai" routes to "openai-codex"
  // when Codex is the signed-in flow; "qwen" routes to "qwen-oauth"; etc.
  const catalogProviderId = useMemo(() => {
    const p = draft.primaryProvider;
    if (!p) return "";
    if (p === "openai") {
      return connectedProviderIds.has("openai-codex") ? "openai-codex" : "openai";
    }
    if (p === "anthropic") {
      if (connectedProviderIds.has("anthropic")) return "anthropic";
      if (connectedProviderIds.has("claude-code")) return "claude-code";
      return "anthropic";
    }
    if (p === "qwen") {
      return connectedProviderIds.has("qwen-oauth") ? "qwen-oauth" : "qwen";
    }
    return p;
  }, [draft.primaryProvider, connectedProviderIds]);

  // Live model catalog for the chosen provider. Refetches whenever the
  // resolved provider id changes so the dropdown stays in sync with auth
  // state (e.g. signing in to Codex unlocks the live gpt-5 list).
  const [primaryModelCatalog, setPrimaryModelCatalog] = useState<string[]>([]);
  const [primaryModelLoading, setPrimaryModelLoading] = useState(false);

  // Local "user wants to configure this channel" intent. ChannelToggle gates
  // its inputs on `enabled`, so without this map the WhatsApp/Slack/Discord
  // toggles look on-click-broken — the boolean is derived from field
  // presence, and the fields are empty, so the toggle visually moves but
  // nothing expands. This map lets the toggle expand on intent.
  const [expandedChannels, setExpandedChannels] = useState<Record<string, boolean>>({});
  const setChannelExpanded = useCallback((key: string, value: boolean) => {
    setExpandedChannels((prev) => ({ ...prev, [key]: value }));
  }, []);

  useEffect(() => {
    if (!catalogProviderId) {
      setPrimaryModelCatalog([]);
      setPrimaryModelLoading(false);
      return;
    }
    let cancelled = false;
    setPrimaryModelLoading(true);
    // Seed with the static fallback immediately so the picker is never empty,
    // then upgrade to the live catalog when the backend responds. This also
    // protects against older dashboard builds that don't have the
    // /api/models/by-provider endpoint registered (it 404s -> we'd otherwise
    // strand the user on whatever stale draft.primaryModel was carrying).
    setPrimaryModelCatalog(staticModelsFor(catalogProviderId));
    api
      .getProviderModels(catalogProviderId)
      .then((resp) => {
        if (cancelled) return;
        const live = resp.models ?? [];
        setPrimaryModelCatalog(live.length > 0 ? live : staticModelsFor(catalogProviderId));
      })
      .catch(() => {
        if (cancelled) return;
        setPrimaryModelCatalog(staticModelsFor(catalogProviderId));
      })
      .finally(() => {
        if (!cancelled) setPrimaryModelLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [catalogProviderId]);

  // Auto-clear primaryModel when the user switches providers and the carried
  // value isn't in the new catalog. Prevents stale Anthropic ids surfacing
  // when the resolved provider becomes openai-codex, etc.
  useEffect(() => {
    if (!catalogProviderId) return;
    if (primaryModelLoading) return;
    if (primaryModelCatalog.length === 0) return;
    const current = draftRef.current.primaryModel.trim();
    if (!current) return;
    if (primaryModelCatalog.includes(current)) return;
    // Best-effort cross-provider check: if the current model looks like it
    // belongs to a different family (e.g. "claude-" while we're on OpenAI),
    // wipe it so the picker doesn't parade it as the "1 model available".
    const looksAnthropic = current.toLowerCase().startsWith("claude");
    const looksOpenAI = current.toLowerCase().startsWith("gpt") || current.toLowerCase().startsWith("o");
    const familyMismatch =
      (catalogProviderId.startsWith("openai") && looksAnthropic) ||
      (catalogProviderId.startsWith("anthropic") && looksOpenAI) ||
      (catalogProviderId === "claude-code" && looksOpenAI);
    if (familyMismatch) {
      setDraft((prev) => ({ ...prev, primaryModel: primaryModelCatalog[0] ?? "" }));
    }
  }, [catalogProviderId, primaryModelCatalog, primaryModelLoading]);

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
                    <WizardModelPicker
                      label="Model ID"
                      value={draft.primaryModel}
                      onChange={(v) => updateField("primaryModel", v)}
                      models={primaryModelCatalog}
                      loading={primaryModelLoading}
                      disabled={!draft.primaryProvider}
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
                  enabled={true}
                  onToggle={() => {}}
                  locked
                  title="CLI"
                  hint="Talk to the agent inside your terminal with `elevate`. Always available — keep on."
                />

                <ChannelToggle
                  enabled={
                    configuredChannelKeys.has("operator_channel_telegram") ||
                    Boolean(draft.telegramBotToken || draft.telegramSecretPresent)
                  }
                  onToggle={(v) => {
                    if (!v) {
                      updateField("telegramBotToken", "");
                      updateField("telegramChatId", "");
                    }
                  }}
                  title="Telegram"
                  hint="Paste your BotFather token, then DM /start to your bot. The bot replies with a pairing code that lights up here."
                  link={{ href: "https://t.me/BotFather", label: "Open @BotFather" }}
                >
                  <TelegramPairingPanel
                    draft={draft}
                    updateField={updateField}
                    alreadyConfigured={configuredChannelKeys.has(
                      "operator_channel_telegram",
                    )}
                    onSetupRefresh={async () => {
                      try {
                        const next = await api.getAgentSetup();
                        onSetupUpdated(next);
                      } catch {
                        /* swallow — surfaced inside the panel */
                      }
                    }}
                  />
                </ChannelToggle>

                <ChannelToggle
                  enabled={
                    configuredChannelKeys.has("operator_channel_imessage") ||
                    draft.imessageEnabled ||
                    expandedChannels.imessage === true
                  }
                  onToggle={(v) => {
                    setChannelExpanded("imessage", v);
                    updateField("imessageEnabled", v);
                  }}
                  title="iMessage"
                  hint="Local Mac Messages.db, or BlueBubbles to bridge from another Mac. Pick one."
                >
                  <IMessageSetupPanel draft={draft} updateField={updateField} />
                </ChannelToggle>

                <ChannelToggle
                  enabled={
                    configuredChannelKeys.has("operator_channel_discord") ||
                    Boolean(draft.discordBotToken && draft.discordChannelId) ||
                    expandedChannels.discord === true
                  }
                  onToggle={(v) => {
                    setChannelExpanded("discord", v);
                    if (!v) {
                      updateField("discordBotToken", "");
                      updateField("discordChannelId", "");
                    }
                  }}
                  title="Discord"
                  hint="Bot token + allowlist + home channel. Mirrors `elevate gateway setup discord`."
                  link={{
                    href: "https://discord.com/developers/applications",
                    label: "Discord developer portal",
                  }}
                >
                  <DiscordSetupPanel draft={draft} updateField={updateField} />
                </ChannelToggle>

                <ChannelToggle
                  enabled={
                    configuredChannelKeys.has("operator_channel_whatsapp") ||
                    Boolean(draft.whatsappProvider && draft.whatsappToken) ||
                    expandedChannels.whatsapp === true
                  }
                  onToggle={(v) => {
                    setChannelExpanded("whatsapp", v);
                    if (!v) {
                      updateField("whatsappProvider", "");
                      updateField("whatsappToken", "");
                      updateField("whatsappPhoneId", "");
                    }
                  }}
                  title="WhatsApp"
                  hint="Free local bridge with QR pairing (recommended), or a paid cloud API."
                >
                  <WhatsAppSetupPanel draft={draft} updateField={updateField} />
                </ChannelToggle>

                <ChannelToggle
                  enabled={
                    configuredChannelKeys.has("operator_channel_slack") ||
                    Boolean(draft.slackWebhookUrl) ||
                    expandedChannels.slack === true
                  }
                  onToggle={(v) => {
                    setChannelExpanded("slack", v);
                    if (!v) {
                      updateField("slackWebhookUrl", "");
                      updateField("slackChannel", "");
                    }
                  }}
                  title="Slack"
                  hint="Socket Mode app (recommended) for full inbound + outbound, or a one-way webhook for posting only."
                  link={{
                    href: "https://api.slack.com/apps",
                    label: "Slack app dashboard",
                  }}
                >
                  <SlackSetupPanel draft={draft} updateField={updateField} />
                </ChannelToggle>

                <ConnectedAgentsRail oauthProviders={oauthProviders ?? []} />
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
                  hint="Optional. Gmail, Calendar, Slack, GitHub, Notion, Linear, HubSpot — Composio brokers OAuth for all of them. Paste your key, then connect accounts inline."
                >
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
                  <div className="mt-3">
                    <ComposioConnectionsInline
                      keyPresent={draft.composioSecretPresent || Boolean(draft.composioApiKey.trim())}
                    />
                  </div>
                </WizardSection>
              </>
            )}

            {step.id === "outbound" && (
              <>
                <OutboundMirrorToggle
                  channel="telegram"
                  enabled={draft.outboundTelegramEnabled}
                  inboundReady={
                    configuredChannelKeys.has("operator_channel_telegram") ||
                    Boolean(
                      (draft.telegramBotToken.trim() || draft.telegramSecretPresent) &&
                        draft.telegramChatId.trim(),
                    )
                  }
                  onToggle={(v) => updateField("outboundTelegramEnabled", v)}
                />
                <OutboundMirrorToggle
                  channel="discord"
                  enabled={draft.outboundDiscordEnabled}
                  inboundReady={
                    configuredChannelKeys.has("operator_channel_discord") ||
                    Boolean(draft.discordBotToken && draft.discordChannelId)
                  }
                  onToggle={(v) => updateField("outboundDiscordEnabled", v)}
                />
                <OutboundMirrorToggle
                  channel="whatsapp"
                  enabled={draft.outboundWhatsappEnabled}
                  inboundReady={
                    configuredChannelKeys.has("operator_channel_whatsapp") ||
                    Boolean(draft.whatsappProvider && draft.whatsappToken)
                  }
                  onToggle={(v) => updateField("outboundWhatsappEnabled", v)}
                />
                <OutboundMirrorToggle
                  channel="slack"
                  enabled={draft.outboundSlackEnabled}
                  inboundReady={
                    configuredChannelKeys.has("operator_channel_slack") ||
                    Boolean(draft.slackWebhookUrl)
                  }
                  onToggle={(v) => updateField("outboundSlackEnabled", v)}
                />
                <ChannelToggle
                  enabled={draft.outboundImessageEnabled}
                  onToggle={(v) => updateField("outboundImessageEnabled", v)}
                  title="iMessage"
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
              </>
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

// Slack test button — fires /api/channels/slack/test so the operator can
// verify the webhook is live before saving. Reuses env-detected webhook
// when the wizard field is blank (backend handles that fallback).
function SlackTestButton({
  webhookUrl,
  channel,
}: {
  webhookUrl: string;
  channel: string;
}) {
  const [status, setStatus] = useState<
    { kind: "idle" } | { kind: "loading" } | { kind: "ok"; detail: string } | { kind: "err"; detail: string }
  >({ kind: "idle" });

  const onClick = useCallback(async () => {
    setStatus({ kind: "loading" });
    try {
      const resp = await api.testSlackWebhook({
        webhook_url: webhookUrl,
        channel: channel || undefined,
        text: "elevate · onboarding test message",
      });
      if (resp.ok) {
        setStatus({ kind: "ok", detail: `delivered (HTTP ${resp.status})` });
      } else {
        setStatus({
          kind: "err",
          detail: `HTTP ${resp.status} — ${resp.detail || "unknown error"}`,
        });
      }
    } catch (err) {
      setStatus({ kind: "err", detail: errorMessage(err, "Network error") });
    }
  }, [webhookUrl, channel]);

  return (
    <div className="mt-3 flex items-center gap-3 text-[11.5px]">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onClick}
        disabled={status.kind === "loading"}
        className="h-7 px-3 text-[11px]"
      >
        {status.kind === "loading" ? (
          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        ) : null}
        Send test message
      </Button>
      {status.kind === "ok" && (
        <span className="inline-flex items-center gap-1 text-primary">
          <CheckCircle2 className="h-3 w-3" />
          {status.detail}
        </span>
      )}
      {status.kind === "err" && (
        <span className="inline-flex items-center gap-1 text-destructive">
          <AlertTriangle className="h-3 w-3" />
          {status.detail}
        </span>
      )}
    </div>
  );
}

// Lists peer agents that already have a Telegram bot configured. Shown
// inside TelegramPairingPanel so the operator can see "@ctrl_gary_bot is
// already wired to gary" before pasting a new token — answers the question
// "which bots already have Telegram?" without leaving the wizard.
function TelegramPeerRail() {
  const [peers, setPeers] = useState<
    Array<{
      org: string;
      name: string;
      telegram?: {
        configured: boolean;
        botHandle: string;
        chatId: string;
        tokenPreview: string;
        source: string;
      };
    }>
  >([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getAgentPeers()
      .then((resp) => {
        if (cancelled) return;
        setPeers(resp.peers ?? []);
      })
      .catch(() => {
        /* silent — the rail is purely informational */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tgPeers = useMemo(
    () => peers.filter((p) => p.telegram?.configured),
    [peers],
  );

  if (loading || tgPeers.length === 0) return null;

  return (
    <section className="rounded-md border border-border bg-card/40 px-3 py-2.5">
      <header className="mb-1.5">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
          Bots already on this Mac
        </span>
      </header>
      <ul className="space-y-1">
        {tgPeers.map((p) => (
          <li
            key={`${p.org}/${p.name}`}
            className="flex items-center justify-between gap-3 text-[11.5px] leading-4"
          >
            <span className="min-w-0 truncate">
              <span className="text-foreground">{p.name}</span>
              <span className="text-muted-foreground/70"> · {p.org}</span>
              {p.telegram?.botHandle && (
                <span className="ml-1 text-muted-foreground">@{p.telegram.botHandle}</span>
              )}
            </span>
            <span className="shrink-0 font-mono-ui text-[10.5px] tracking-wide text-muted-foreground/80">
              {p.telegram?.tokenPreview || "configured"}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[10.5px] leading-4 text-muted-foreground/70">
        Reuse one of these tokens or paste a fresh BotFather token below.
      </p>
    </section>
  );
}

// Surfaces the AI peers the operator has wired up alongside this elevate
// agent — signed-in model providers + Cortex OS-style PTY specialists from
// $HOME/claudeclaw/orgs. Read-only. Lets the wizard answer "who else is in
// the room" without forcing the operator into a separate config page.
function ConnectedAgentsRail({
  oauthProviders,
}: {
  oauthProviders: OAuthProvider[];
}) {
  const [peers, setPeers] = useState<
    Array<{
      org: string;
      name: string;
      enabled: boolean;
      workingDirectory: string;
      communicationStyle: string;
      cronCount: number;
      roleHint: string;
    }>
  >([]);
  const [peersLoading, setPeersLoading] = useState(true);
  const [peersError, setPeersError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPeersLoading(true);
    api
      .getAgentPeers()
      .then((resp) => {
        if (cancelled) return;
        setPeers(resp.peers ?? []);
        setPeersError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setPeers([]);
        setPeersError(errorMessage(err, "Failed to load Cortex OS peers."));
      })
      .finally(() => {
        if (!cancelled) setPeersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const connectedProviders = useMemo(
    () => oauthProviders.filter((p) => p.status?.logged_in),
    [oauthProviders],
  );

  return (
    <section className="rounded-md border border-border bg-card/40 px-4 py-3 backdrop-blur-sm">
      <header className="mb-3">
        <h3 className="text-[13.5px] font-semibold text-foreground">
          Agents already connected
        </h3>
        <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">
          Other AI surfaces wired up on this Mac. Read-only — manage them from the CLI or their own config files.
        </p>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            Model providers signed in
          </h4>
          {connectedProviders.length === 0 ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">
              Nothing yet. Sign in to a provider on Step 1.
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {connectedProviders.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center justify-between rounded-md border border-border/50 bg-background/40 px-3 py-2 text-[12px]"
                >
                  <span className="font-medium text-foreground">{p.name || p.id}</span>
                  <span className="inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-primary">
                    <CheckCircle2 className="h-3 w-3" />
                    connected
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            Cortex OS specialists
          </h4>
          {peersLoading ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">Loading…</p>
          ) : peersError ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">
              {peersError}
            </p>
          ) : peers.length === 0 ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">
              No peers found under <code>~/claudeclaw/orgs</code>. Set <code>ELEVATE_PEERS_ROOT</code> to point at a different orgs directory.
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {peers.map((peer) => (
                <li
                  key={`${peer.org}/${peer.name}`}
                  className="rounded-md border border-border/50 bg-background/40 px-3 py-2 text-[12px]"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground">
                      {peer.name}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em]",
                        peer.enabled ? "text-primary" : "text-muted-foreground/60",
                      )}
                    >
                      {peer.enabled ? (
                        <CheckCircle2 className="h-3 w-3" />
                      ) : (
                        <Circle className="h-3 w-3" />
                      )}
                      {peer.enabled ? "enabled" : "disabled"}
                    </span>
                  </div>
                  {peer.roleHint && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground/80">
                      {peer.roleHint}
                    </p>
                  )}
                  <p className="mt-0.5 font-mono-ui text-[10px] uppercase tracking-[0.16em] text-muted-foreground/60">
                    {peer.org} · {peer.cronCount} cron{peer.cronCount === 1 ? "" : "s"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
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

// Compact toggle for the outbound step. The matching inbound channel already
// carries the credentials — this toggle just gates "agent is allowed to send
// on this surface". When inbound isn't wired we render a muted row instead
// of a clickable toggle so users know they need to go back to Step 3 first.
const OUTBOUND_CHANNEL_LABELS: Record<string, { title: string; hint: string }> = {
  telegram: {
    title: "Telegram",
    hint: "Same BotFather token writes outbound. Off = agent reads but never replies.",
  },
  discord: {
    title: "Discord",
    hint: "Bot token from Step 3 writes outbound. Off = agent is read-only in the channel.",
  },
  whatsapp: {
    title: "WhatsApp",
    hint: "Meta Cloud API / Twilio / Composio session can send back. Off = inbound-only.",
  },
  slack: {
    title: "Slack",
    hint: "Webhook URL is outbound-by-design. Off = the agent doesn't post into the channel.",
  },
};

function OutboundMirrorToggle({
  channel,
  enabled,
  inboundReady,
  onToggle,
}: {
  channel: "telegram" | "discord" | "whatsapp" | "slack";
  enabled: boolean;
  inboundReady: boolean;
  onToggle: (v: boolean) => void;
}) {
  const meta = OUTBOUND_CHANNEL_LABELS[channel];
  if (!inboundReady) {
    return (
      <section className="rounded-md border border-border bg-card/30 px-4 py-3">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[13.5px] font-semibold text-muted-foreground">{meta.title}</h3>
            <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground/80">
              Wire {meta.title} inbound in Step 3 to enable outbound here.
            </p>
          </div>
          <span className="inline-flex shrink-0 items-center gap-2 rounded-md border border-border bg-muted/40 px-2 py-1 text-[10.5px] font-medium uppercase tracking-wide text-muted-foreground">
            Not connected
          </span>
        </header>
      </section>
    );
  }
  return (
    <ChannelToggle
      enabled={enabled}
      onToggle={onToggle}
      title={meta.title}
      hint={meta.hint}
    />
  );
}

function ChannelToggle({
  enabled,
  onToggle,
  title,
  hint,
  link,
  locked,
  lockedLabel,
  children,
}: {
  enabled: boolean;
  onToggle: (v: boolean) => void;
  title: string;
  hint?: string;
  link?: { href: string; label: string };
  // Locked = state is reality, not preference. CLI is always on; renders
  // an "Always on" badge instead of a clickable toggle.
  locked?: boolean;
  lockedLabel?: string;
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
        {locked ? (
          <span className="inline-flex shrink-0 items-center gap-2 rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[10.5px] font-medium uppercase tracking-wide text-primary">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {lockedLabel ?? "Always on"}
          </span>
        ) : (
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
        )}
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

// Provider-aware model picker. When the live catalog has entries, renders
// a native <select> the user can scroll through. If the user typed a value
// not in the catalog (e.g. an unreleased preview model), preserves it as
// the first option so we never silently drop it. Includes a "Custom…" tail
// option that swaps in a text input for one-off model ids. Falls back to a
// plain text input when no catalog is loaded yet.
function WizardModelPicker({
  label,
  value,
  onChange,
  models,
  loading,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  models: string[];
  loading: boolean;
  disabled?: boolean;
}) {
  const [customMode, setCustomMode] = useState(false);

  const optionList = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    if (value && !models.includes(value)) {
      out.push(value);
      seen.add(value);
    }
    for (const m of models) {
      if (seen.has(m)) continue;
      seen.add(m);
      out.push(m);
    }
    return out;
  }, [value, models]);

  const showCustom = customMode || (!loading && optionList.length === 0);

  return (
    <label className="block min-w-0">
      <span className="mb-1.5 flex items-center justify-between text-[12px] font-medium text-muted-foreground">
        <span>{label}</span>
        {loading && (
          <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            loading…
          </span>
        )}
        {!loading && optionList.length > 0 && (
          <button
            type="button"
            onClick={() => setCustomMode((m) => !m)}
            className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70 hover:text-foreground"
          >
            {customMode ? "pick from list" : "custom…"}
          </button>
        )}
      </span>
      {showCustom ? (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="paste any model id"
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60"
        />
      ) : (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled || loading}
          size={1}
          className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors focus:border-primary focus:ring-1 focus:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {!value && (
            <option value="">
              {disabled
                ? "— pick a provider first —"
                : loading
                  ? "loading models…"
                  : "— pick a model —"}
            </option>
          )}
          {optionList.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      )}
      <span className="mt-1.5 block text-[11px] leading-4 text-muted-foreground/70">
        {disabled
          ? "Pick a provider first."
          : loading
            ? "Pulling live model list from the provider…"
            : optionList.length > 0
              ? `${optionList.length} model${optionList.length === 1 ? "" : "s"} available · scroll the list`
              : "No catalog yet for this provider. Paste a model id."}
      </span>
    </label>
  );
}

type ComposioToolkitRow = {
  slug?: string | null;
  name?: string | null;
  logo?: string | null;
  meta?: { logo?: string | null } | null;
};

const TOOLKIT_PAGE_SIZE = 30;

// Pull the toolkit logo from either ``meta.logo`` (newer responses) or
// ``logo`` (older). Composio mixes the two depending on endpoint.
function toolkitLogo(t: ComposioToolkitRow): string | null {
  return t.meta?.logo || t.logo || null;
}

// Step-by-step walkthrough rendered when there's no Composio key yet. The
// previous panel just said "paste a key" — that's not enough for a brand-
// new operator who has never opened composio.dev. Deep links go straight
// to the page that produces the next required value.
function ComposioWalkthrough() {
  return (
    <div className="space-y-2.5 rounded-md border border-border bg-card/50 px-4 py-3">
      <div className="text-[11.5px] leading-5 text-foreground">
        Composio brokers OAuth for Gmail, Calendar, Slack, GitHub, Notion, and
        100+ other tools. Free tier is generous — paste an API key here and
        every connector lights up.
      </div>
      <ol className="space-y-1.5 text-[11.5px] leading-5">
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-primary/40 text-[10px] font-semibold text-primary">
            1
          </span>
          <span className="text-muted-foreground">
            Create your account at{" "}
            <a
              href="https://app.composio.dev/signup"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-primary underline-offset-2 hover:underline"
            >
              app.composio.dev/signup
              <ExternalLink className="h-3 w-3" />
            </a>
            . Google sign-in works.
          </span>
        </li>
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-primary/40 text-[10px] font-semibold text-primary">
            2
          </span>
          <span className="text-muted-foreground">
            Open the{" "}
            <a
              href="https://app.composio.dev/developers"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-primary underline-offset-2 hover:underline"
            >
              Developer dashboard
              <ExternalLink className="h-3 w-3" />
            </a>
            {" "}— pick (or create) the project that should own this agent.
          </span>
        </li>
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-primary/40 text-[10px] font-semibold text-primary">
            3
          </span>
          <span className="text-muted-foreground">
            Generate an API key on the{" "}
            <a
              href="https://app.composio.dev/developers/api-keys"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-primary underline-offset-2 hover:underline"
            >
              API keys page
              <ExternalLink className="h-3 w-3" />
            </a>
            , then paste it into the Composio field above. Tool catalog
            appears here as soon as the key validates.
          </span>
        </li>
      </ol>
    </div>
  );
}

// Inline Composio account connector — mirrors the connect-account flow in
// ConfigPage's ComposioPanel but trimmed to fit inside a wizard step.
// First paint loads a single 30-item page (no full catalog walk); search
// queries Composio's index server-side; Prev/Next pages via cursor. Logos
// render inline so the user actually recognizes each tool.
function ComposioConnectionsInline({ keyPresent }: { keyPresent: boolean }) {
  const [status, setStatus] = useState<{ valid: boolean; error?: string | null } | null>(null);
  const [connections, setConnections] = useState<
    Array<{
      id: string;
      toolkit?: { slug?: string | null; name?: string | null; logo?: string | null; meta?: { logo?: string | null } | null } | null;
      status?: string | null;
    }>
  >([]);
  const [toolkits, setToolkits] = useState<ComposioToolkitRow[]>([]);
  const [statusLoading, setStatusLoading] = useState(false);
  const [toolkitsLoading, setToolkitsLoading] = useState(false);
  const [connectingSlug, setConnectingSlug] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Pagination state — cursorStack[n] is the cursor that produced the
  // current page n. Reset on every new search.
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const pageIdx = cursorStack.length - 1;

  // Debounce keystrokes so we don't fire a Composio search per character.
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => clearTimeout(handle);
  }, [query]);

  // Reset to page 1 whenever search term changes.
  useEffect(() => {
    setCursorStack([undefined]);
  }, [debouncedQuery]);

  // Status + connections are cheap; fire both in parallel up front so the
  // user sees "Connected accounts" without waiting on the toolkit page.
  const refreshStatusAndConns = useCallback(async () => {
    if (!keyPresent) {
      setStatus(null);
      setConnections([]);
      return;
    }
    setStatusLoading(true);
    setErrorMsg(null);
    const [statusRes, connsRes] = await Promise.allSettled([
      api.getComposioStatus(),
      api.getComposioConnections(),
    ]);
    if (statusRes.status === "fulfilled") {
      setStatus(statusRes.value);
    } else {
      setStatus(null);
      setErrorMsg(
        statusRes.reason instanceof Error
          ? statusRes.reason.message
          : String(statusRes.reason),
      );
    }
    const statusValid = statusRes.status === "fulfilled" && statusRes.value.valid;
    if (statusValid && connsRes.status === "fulfilled") {
      const conData =
        (connsRes.value.data as { items?: typeof connections } | typeof connections) ?? [];
      setConnections(Array.isArray(conData) ? conData : conData.items ?? []);
    } else {
      setConnections([]);
    }
    setStatusLoading(false);
  }, [keyPresent]);

  // Toolkit page loads independently; doesn't block the rest of the panel.
  const loadToolkitPage = useCallback(
    async (cursor: string | undefined, search: string) => {
      if (!keyPresent) {
        setToolkits([]);
        setNextCursor(null);
        return;
      }
      setToolkitsLoading(true);
      try {
        const resp = await api.getComposioToolkitsPage({
          cursor,
          search: search || undefined,
          limit: TOOLKIT_PAGE_SIZE,
        });
        const raw =
          (resp.data as
            | { items?: ComposioToolkitRow[]; next_cursor?: string | null; nextCursor?: string | null }
            | ComposioToolkitRow[]
            | undefined) ?? [];
        if (Array.isArray(raw)) {
          setToolkits(raw);
          setNextCursor(null);
        } else {
          setToolkits(raw.items ?? []);
          setNextCursor(raw.next_cursor ?? raw.nextCursor ?? null);
        }
      } catch (err) {
        setToolkits([]);
        setNextCursor(null);
        setErrorMsg(err instanceof Error ? err.message : String(err));
      } finally {
        setToolkitsLoading(false);
      }
    },
    [keyPresent],
  );

  useEffect(() => {
    void refreshStatusAndConns();
  }, [refreshStatusAndConns]);

  // Whenever the cursor or search changes (and status is valid), load the
  // current page. We don't depend on status itself becoming valid in this
  // hook because the first paint of /status validates the key — if status
  // is invalid, /toolkits will 401 anyway and we handle the error.
  useEffect(() => {
    if (!keyPresent) return;
    if (status === null) return;
    if (!status.valid) return;
    void loadToolkitPage(cursorStack[cursorStack.length - 1], debouncedQuery);
  }, [keyPresent, status, cursorStack, debouncedQuery, loadToolkitPage]);

  useEffect(() => {
    const onFocus = () => {
      if (status?.valid) void refreshStatusAndConns();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refreshStatusAndConns, status?.valid]);

  const connect = useCallback(async (slug: string) => {
    setConnectingSlug(slug);
    setErrorMsg(null);
    try {
      const result = await api.initiateComposioConnection({ toolkitSlug: slug });
      const url = result.data?.redirect_url ?? result.data?.redirect_uri;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }
      setErrorMsg(
        result.error ||
          "This toolkit needs custom credentials. Open Settings → Composio to paste them.",
      );
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setConnectingSlug(null);
    }
  }, []);

  const goNextPage = useCallback(() => {
    if (!nextCursor) return;
    setCursorStack((prev) => [...prev, nextCursor]);
  }, [nextCursor]);

  const goPrevPage = useCallback(() => {
    setCursorStack((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev));
  }, []);

  if (!keyPresent) return <ComposioWalkthrough />;

  if (statusLoading && status === null) {
    return (
      <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Checking your Composio account…
      </div>
    );
  }

  if (status && !status.valid) {
    return (
      <p className="text-[11.5px] leading-5 text-destructive">
        {status.error ?? "Composio rejected the key. Double-check it and save again."}
      </p>
    );
  }

  const connectedSlugs = new Set(
    connections.map((c) => (c.toolkit?.slug ?? "").toLowerCase()).filter(Boolean),
  );

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Connected accounts
        </div>
        {connections.length === 0 ? (
          <p className="text-[11.5px] leading-5 text-muted-foreground/80">
            None yet. Pick a tool below to connect — Composio opens an OAuth tab for that toolkit.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {connections.map((c) => {
              const logo = c.toolkit?.meta?.logo ?? c.toolkit?.logo;
              return (
                <span
                  key={c.id}
                  className="inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-foreground"
                >
                  {logo ? (
                    <img
                      src={logo}
                      alt=""
                      className="h-3.5 w-3.5 rounded-sm object-contain"
                    />
                  ) : (
                    <CheckCircle2 className="h-3 w-3 text-primary" />
                  )}
                  {c.toolkit?.name ?? c.toolkit?.slug ?? c.id}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Add a tool
          </span>
          <a
            href="/config#composio"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
          >
            Open full Composio manager <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Gmail, Slack, Notion, Linear, GitHub…"
          className="mb-2 h-8 w-full rounded-md border border-border bg-card/60 px-3 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        />
        <div className="grid gap-1.5 md:grid-cols-2">
          {toolkits.map((t) => {
            const slug = (t.slug ?? "").toLowerCase();
            const connected = connectedSlugs.has(slug);
            const busy = connectingSlug === slug;
            const logo = toolkitLogo(t);
            return (
              <button
                key={slug || t.name || Math.random()}
                type="button"
                onClick={() => slug && !connected && !busy && connect(slug)}
                disabled={!slug || connected || busy}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-md border border-border bg-card/60 px-3 py-1.5 text-left text-[12px] transition-colors",
                  !connected && !busy && "hover:border-primary/40 hover:bg-primary/5",
                  connected && "opacity-60",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  {logo ? (
                    <img
                      src={logo}
                      alt=""
                      className="h-4 w-4 shrink-0 rounded-sm object-contain"
                      loading="lazy"
                    />
                  ) : (
                    <span className="h-4 w-4 shrink-0 rounded-sm bg-muted/40" />
                  )}
                  <span className="truncate">{t.name ?? slug}</span>
                </span>
                {connected ? (
                  <span className="text-[10.5px] uppercase tracking-wide text-primary">connected</span>
                ) : busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : (
                  <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                    connect
                  </span>
                )}
              </button>
            );
          })}
          {toolkitsLoading && toolkits.length === 0 && (
            <span className="col-span-full inline-flex items-center gap-2 text-[11.5px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading toolkits…
            </span>
          )}
          {!toolkitsLoading && toolkits.length === 0 && (
            <span className="col-span-full text-[11.5px] text-muted-foreground/80">
              {debouncedQuery
                ? `No toolkits match "${debouncedQuery}". Try another term.`
                : "Composio returned no toolkits. Check your key or try again."}
            </span>
          )}
        </div>

        {/* Prev / Next page controls. Only render when there's a reason to. */}
        {(pageIdx > 0 || nextCursor) && (
          <div className="mt-2 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={goPrevPage}
              disabled={pageIdx === 0 || toolkitsLoading}
              className={cn(
                "rounded-md border border-border bg-card/60 px-2.5 py-1 text-[11px] uppercase tracking-wide text-muted-foreground transition-colors",
                pageIdx === 0 ? "opacity-40" : "hover:border-primary/40 hover:text-foreground",
              )}
            >
              ← Prev
            </button>
            <span className="font-mono-ui text-[10.5px] uppercase tracking-[0.18em] text-muted-foreground/70">
              Page {pageIdx + 1}
            </span>
            <button
              type="button"
              onClick={goNextPage}
              disabled={!nextCursor || toolkitsLoading}
              className={cn(
                "rounded-md border border-border bg-card/60 px-2.5 py-1 text-[11px] uppercase tracking-wide text-muted-foreground transition-colors",
                !nextCursor ? "opacity-40" : "hover:border-primary/40 hover:text-foreground",
              )}
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {errorMsg && (
        <p className="text-[11.5px] leading-5 text-destructive">{errorMsg}</p>
      )}
    </div>
  );
}

// Mirrors the CLI's `elevate gateway setup` + `elevate pairing approve
// telegram <code>` ritual: paste the BotFather token, restart the gateway
// in pair mode, watch for the code the bot DMs back, approve it. The
// gateway-side PairingStore is the source of truth — we poll it.
function TelegramPairingPanel({
  draft,
  updateField,
  onSetupRefresh,
  alreadyConfigured,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
  onSetupRefresh: () => Promise<void> | void;
  alreadyConfigured: boolean;
}) {
  type Stage = "token" | "polling" | "paired";
  const [stage, setStage] = useState<Stage>(() =>
    alreadyConfigured ? "paired" : draft.telegramSecretPresent ? "polling" : "token",
  );
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pending, setPending] = useState<TelegramPendingEntry[]>([]);
  const [approved, setApproved] = useState<TelegramApprovedEntry[]>([]);
  const [statusNote, setStatusNote] = useState<string | null>(null);

  useEffect(() => {
    if (stage !== "polling") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const resp = await api.listTelegramPairings();
        if (cancelled) return;
        setPending(resp.pending);
        setApproved(resp.approved);
        if (resp.approved.length > 0 && resp.pending.length === 0) {
          setStage("paired");
          return;
        }
      } catch (e) {
        if (!cancelled) {
          setErrorMsg(errorMessage(e, "Couldn't read pairing state"));
        }
      }
      if (!cancelled) timer = setTimeout(tick, 3000);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [stage]);

  const startPairing = useCallback(async () => {
    const token = draft.telegramBotToken.trim();
    if (!token && !draft.telegramSecretPresent) {
      setErrorMsg("Paste your BotFather token first.");
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    if (!token && draft.telegramSecretPresent) {
      // Token already in env — skip the save+restart, just enter polling.
      setStage("polling");
      setStatusNote("Using the token already in your env. Send /start to the bot.");
      setBusy(false);
      return;
    }
    setStatusNote("Saving token + restarting the gateway…");
    try {
      await api.startTelegramPairing(token);
      updateField("telegramSecretPresent", true);
      updateField("telegramSecretPreview", "•••" + token.slice(-4));
      updateField("telegramBotToken", "");
      setStage("polling");
      setStatusNote(
        "Gateway is restarting. Open Telegram, find your bot, send /start.",
      );
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not start pairing"));
    } finally {
      setBusy(false);
    }
  }, [draft.telegramBotToken, draft.telegramSecretPresent, updateField]);

  const approveCode = useCallback(
    async (code: string) => {
      setBusy(true);
      setErrorMsg(null);
      setStatusNote(null);
      try {
        const resp = await api.approveTelegramPairing(code, true);
        setStage("paired");
        setStatusNote(
          resp.user_name
            ? `Paired with ${resp.user_name} (id ${resp.user_id}).`
            : `Paired with user ${resp.user_id}.`,
        );
        await onSetupRefresh();
      } catch (e) {
        setErrorMsg(errorMessage(e, "Approval failed"));
      } finally {
        setBusy(false);
      }
    },
    [onSetupRefresh],
  );

  if (stage === "paired") {
    const display = approved[0]?.user_name || approved[0]?.user_id || "you";
    return (
      <div className="space-y-2">
        <div className="rounded-md border border-primary/40 bg-card/60 px-3 py-3 text-[12px] text-foreground">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <span className="font-medium">Paired with {display}.</span>
          </div>
          <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
            The bot will deliver approvals and status messages here. Re-pair
            from Settings → Channels later if you switch accounts.
          </p>
          {statusNote && (
            <p className="mt-2 text-[11.5px] leading-5 text-muted-foreground">
              {statusNote}
            </p>
          )}
        </div>
        <button
          type="button"
          className="text-[11.5px] text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => {
            setStage("token");
            setStatusNote(null);
            setErrorMsg(null);
          }}
        >
          Pair a different bot
        </button>
      </div>
    );
  }

  if (stage === "polling") {
    const tgPending = pending.filter((p) => p.platform === "telegram");
    return (
      <div className="space-y-3">
        <div className="rounded-md border border-border bg-card/40 px-3 py-3 text-[12px] leading-5 text-foreground">
          <div className="flex items-center gap-2 text-[12.5px] font-medium">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            Waiting for your /start DM…
          </div>
          <p className="mt-1.5 text-[11.5px] leading-5 text-muted-foreground">
            Open Telegram, find your bot, and send <code>/start</code>. The bot
            replies with a pairing code that shows up here in a few seconds.
          </p>
        </div>

        {tgPending.length > 0 && (
          <ul className="space-y-2">
            {tgPending.map((row) => (
              <li
                key={row.code}
                className="flex items-center justify-between gap-3 rounded-md border border-primary/40 bg-card/60 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="font-mono text-[12.5px] font-semibold text-foreground">
                    {row.code}
                  </div>
                  <div className="text-[11px] leading-4 text-muted-foreground">
                    {row.user_name || `user ${row.user_id}`}
                    {row.age_minutes > 0 ? ` · ${row.age_minutes}m ago` : ""}
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={() => approveCode(row.code)}
                  disabled={busy}
                  className="h-8"
                >
                  {busy ? "Approving…" : "Approve"}
                </Button>
              </li>
            ))}
          </ul>
        )}

        {statusNote && (
          <p className="text-[11.5px] leading-5 text-muted-foreground">
            {statusNote}
          </p>
        )}
        {errorMsg && (
          <p className="text-[11.5px] leading-5 text-destructive">{errorMsg}</p>
        )}

        <div className="flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
          <button
            type="button"
            className="underline-offset-2 hover:underline"
            onClick={() => {
              setStage("token");
              setStatusNote(null);
              setErrorMsg(null);
            }}
          >
            Paste a different bot token
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <TelegramPeerRail />
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
        fullWidth
        hint={
          draft.telegramSecretPresent && !draft.telegramBotToken
            ? "Detected from env. Leave blank to keep using it, then continue below."
            : "Create the bot with @BotFather (/newbot) and paste the token here."
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          onClick={startPairing}
          disabled={
            busy ||
            (!draft.telegramBotToken.trim() && !draft.telegramSecretPresent)
          }
          className="h-8"
        >
          {busy ? "Starting…" : "Start pairing"}
        </Button>
        {draft.telegramSecretPresent && !draft.telegramBotToken.trim() && (
          <button
            type="button"
            className="text-[11.5px] text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => {
              setStage("polling");
              setStatusNote("Using the token already in your env.");
            }}
          >
            Skip — token already set, take me to /start →
          </button>
        )}
      </div>
      {statusNote && (
        <p className="text-[11.5px] leading-5 text-muted-foreground">
          {statusNote}
        </p>
      )}
      {errorMsg && (
        <p className="text-[11.5px] leading-5 text-destructive">{errorMsg}</p>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// Discord setup panel — mirrors setup._setup_discord. Saves
// DISCORD_BOT_TOKEN, DISCORD_ALLOWED_USERS, DISCORD_HOME_CHANNEL
// to the env file the gateway reads.
// ─────────────────────────────────────────────────────────────────────
function DiscordSetupPanel({
  draft,
  updateField,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
}) {
  const [allowedUsers, setAllowedUsers] = useState("");
  const [homeChannel, setHomeChannel] = useState(draft.discordChannelId);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const save = useCallback(async () => {
    const token = draft.discordBotToken.trim();
    if (!token) {
      setErrorMsg("Paste your Discord bot token first.");
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const resp = await api.configureDiscord({
        bot_token: token,
        allowed_users: allowedUsers.trim() || undefined,
        home_channel: homeChannel.trim() || undefined,
      });
      // Stash the home channel back into the draft so item state survives.
      updateField("discordChannelId", homeChannel.trim());
      updateField("discordBotToken", ""); // clear plaintext from memory
      setSuccessMsg(`Saved. Token: ${resp.tokenPreview || "(set)"}.`);
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not save Discord config"));
    } finally {
      setBusy(false);
    }
  }, [draft.discordBotToken, allowedUsers, homeChannel, updateField]);

  return (
    <div className="space-y-3">
      <ol className="ml-4 list-decimal space-y-1 text-[11.5px] leading-5 text-muted-foreground">
        <li>
          Open the{" "}
          <a
            href="https://discord.com/developers/applications"
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline-offset-2 hover:underline"
          >
            Discord developer portal
          </a>
          , create an application, then in the Bot tab click <em>Reset Token</em>.
        </li>
        <li>
          To find a user or channel ID: Discord → Settings → Advanced → enable
          Developer Mode → right-click name/channel → Copy ID.
        </li>
        <li>
          Invite the bot to your server with{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
            applications.commands
          </code>{" "}
          +{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">bot</code>{" "}
          scopes.
        </li>
      </ol>

      <div className="grid gap-3 md:grid-cols-2">
        <WizardField
          label="Bot token"
          value={draft.discordBotToken}
          onChange={(v) => updateField("discordBotToken", v)}
          placeholder="MTI…"
          type="password"
          fullWidth
        />
        <WizardField
          label="Allowed user IDs (comma-separated)"
          value={allowedUsers}
          onChange={setAllowedUsers}
          placeholder="123456789012345678,987…"
          hint="Empty = anyone in shared servers can DM the bot."
        />
        <WizardField
          label="Home channel ID (optional)"
          value={homeChannel}
          onChange={setHomeChannel}
          placeholder="123456789012345678"
          hint="Cron + cross-platform notifications land here. Set later with /set-home in Discord."
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={save} disabled={busy} size="sm">
          {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          Save Discord config
        </Button>
        {successMsg && (
          <span className="text-[11.5px] text-success">{successMsg}</span>
        )}
        {errorMsg && (
          <span className="text-[11.5px] text-destructive">{errorMsg}</span>
        )}
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// Slack setup panel — Socket Mode (recommended) for full bidirectional,
// or one-way incoming webhook for posting only. Mirrors setup._setup_slack.
// ─────────────────────────────────────────────────────────────────────
function SlackSetupPanel({
  draft,
  updateField,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
}) {
  const [mode, setMode] = useState<"socket" | "webhook">("socket");
  const [botToken, setBotToken] = useState("");
  const [appToken, setAppToken] = useState("");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const save = useCallback(async () => {
    if (mode === "webhook") {
      // Webhook is one-way; nothing to save server-side beyond the existing
      // draft fields. Leave the user a clear message.
      setSuccessMsg(
        "Webhook URL stored in draft — saved when you finish the wizard. (Socket Mode is required for inbound.)",
      );
      return;
    }
    if (!botToken.trim()) {
      setErrorMsg("Slack bot token (xoxb-…) is required.");
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const resp = await api.configureSlackBot({
        bot_token: botToken.trim(),
        app_token: appToken.trim() || undefined,
        allowed_users: allowedUsers.trim() || undefined,
      });
      setBotToken("");
      setAppToken("");
      setSuccessMsg(
        `Saved. Bot token: ${resp.botTokenPreview || "(set)"}${
          resp.appTokenPreview ? `, app token: ${resp.appTokenPreview}` : ""
        }.`,
      );
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not save Slack config"));
    } finally {
      setBusy(false);
    }
  }, [mode, botToken, appToken, allowedUsers]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-[11.5px]">
        <button
          type="button"
          onClick={() => setMode("socket")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "socket"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          Socket Mode (recommended)
        </button>
        <button
          type="button"
          onClick={() => setMode("webhook")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "webhook"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          Incoming webhook (one-way post)
        </button>
      </div>

      {mode === "socket" ? (
        <>
          <ol className="ml-4 list-decimal space-y-1 text-[11.5px] leading-5 text-muted-foreground">
            <li>
              <a
                href="https://api.slack.com/apps"
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline-offset-2 hover:underline"
              >
                api.slack.com/apps
              </a>{" "}
              → Create New App (From scratch).
            </li>
            <li>
              Settings → Socket Mode → enable, create an App-Level Token with{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                connections:write
              </code>
              .
            </li>
            <li>
              Features → OAuth & Permissions → add Bot Token Scopes:{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                chat:write
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                app_mentions:read
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                channels:history
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                channels:read
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                im:history
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                im:read
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                im:write
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                users:read
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                files:read
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                files:write
              </code>
              .
            </li>
            <li>
              Event Subscriptions → enable → subscribe to{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                message.im
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                message.channels
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                app_mention
              </code>
              .
            </li>
            <li>
              Install to Workspace, then{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                /invite @YourBot
              </code>{" "}
              in any channel.
            </li>
          </ol>

          <div className="grid gap-3 md:grid-cols-2">
            <WizardField
              label="Bot token (xoxb-…)"
              value={botToken}
              onChange={setBotToken}
              placeholder="xoxb-…"
              type="password"
            />
            <WizardField
              label="App token (xapp-…)"
              value={appToken}
              onChange={setAppToken}
              placeholder="xapp-…"
              type="password"
            />
            <WizardField
              label="Allowed Slack member IDs (comma-separated, optional)"
              value={allowedUsers}
              onChange={setAllowedUsers}
              placeholder="U01ABC…,U02DEF…"
              hint="Empty = unpaired users denied by default."
              fullWidth
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={save} disabled={busy} size="sm">
              {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Save Slack config
            </Button>
            {successMsg && (
              <span className="text-[11.5px] text-success">{successMsg}</span>
            )}
            {errorMsg && (
              <span className="text-[11.5px] text-destructive">{errorMsg}</span>
            )}
          </div>
        </>
      ) : (
        <>
          <p className="text-[11.5px] leading-5 text-muted-foreground">
            One-way webhook. The agent can post to Slack but cannot receive
            DMs or mentions. For full bidirectional flow, pick Socket Mode.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
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
          <SlackTestButton
            webhookUrl={draft.slackWebhookUrl}
            channel={draft.slackChannel}
          />
        </>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// iMessage panel — local Messages.app (default) or BlueBubbles bridge.
// Local mode just flips the draft flag (gateway reads from chat.db).
// BlueBubbles mirrors setup._setup_bluebubbles.
// ─────────────────────────────────────────────────────────────────────
function IMessageSetupPanel({
  draft,
  updateField,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
}) {
  const [mode, setMode] = useState<"local" | "bluebubbles">("local");
  const [serverUrl, setServerUrl] = useState("");
  const [password, setPassword] = useState("");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [homeChannel, setHomeChannel] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const saveBlueBubbles = useCallback(async () => {
    if (!serverUrl.trim() || !password.trim()) {
      setErrorMsg("BlueBubbles server URL + password are required.");
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const resp = await api.configureBlueBubbles({
        server_url: serverUrl.trim(),
        password: password.trim(),
        allowed_users: allowedUsers.trim() || undefined,
        home_channel: homeChannel.trim() || undefined,
      });
      setPassword("");
      updateField("imessageEnabled", true);
      setSuccessMsg(`Saved. Server: ${resp.serverUrl}.`);
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not save BlueBubbles config"));
    } finally {
      setBusy(false);
    }
  }, [serverUrl, password, allowedUsers, homeChannel, updateField]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-[11.5px]">
        <button
          type="button"
          onClick={() => setMode("local")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "local"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          Local Mac (Messages.app)
        </button>
        <button
          type="button"
          onClick={() => setMode("bluebubbles")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "bluebubbles"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          BlueBubbles (remote bridge)
        </button>
      </div>

      {mode === "local" ? (
        <div className="space-y-2 text-[11.5px] leading-5 text-muted-foreground">
          <p>
            Reads inbound iMessage from this Mac's{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
              ~/Library/Messages/chat.db
            </code>
            . Grant Full Disk Access to Terminal/Elevate (System Settings →
            Privacy & Security).
          </p>
          <WizardField
            label="Your iMessage handle (optional)"
            value={draft.imessageHandle}
            onChange={(v) => updateField("imessageHandle", v)}
            placeholder="+15551234567 or you@icloud.com"
            fullWidth
          />
          <div className="text-[11px] text-muted-foreground/80">
            Toggle stays on — local-Mac mode needs no save action.
          </div>
        </div>
      ) : (
        <>
          <ol className="ml-4 list-decimal space-y-1 text-[11.5px] leading-5 text-muted-foreground">
            <li>
              Install{" "}
              <a
                href="https://bluebubbles.app/"
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline-offset-2 hover:underline"
              >
                BlueBubbles Server
              </a>{" "}
              on a Mac (v1.0.0+).
            </li>
            <li>BlueBubbles Server → Settings → API → note Server URL + Password.</li>
            <li>
              Optional: install the{" "}
              <a
                href="https://docs.bluebubbles.app/helper-bundle/installation"
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline-offset-2 hover:underline"
              >
                Private API helper
              </a>{" "}
              for typing indicators + tapbacks.
            </li>
          </ol>
          <div className="grid gap-3 md:grid-cols-2">
            <WizardField
              label="Server URL"
              value={serverUrl}
              onChange={setServerUrl}
              placeholder="http://192.168.1.10:1234"
              fullWidth
            />
            <WizardField
              label="Server password"
              value={password}
              onChange={setPassword}
              placeholder="…"
              type="password"
            />
            <WizardField
              label="Allowed iMessage addresses (comma-separated)"
              value={allowedUsers}
              onChange={setAllowedUsers}
              placeholder="you@icloud.com,+15551234567"
              hint="Empty = anyone who can iMessage the host Mac can use the bot."
            />
            <WizardField
              label="Home channel (optional)"
              value={homeChannel}
              onChange={setHomeChannel}
              placeholder="+15551234567 or you@icloud.com"
              hint="Where cron + notifications go. Set later with /set-home."
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={saveBlueBubbles} disabled={busy} size="sm">
              {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Save BlueBubbles config
            </Button>
            {successMsg && (
              <span className="text-[11.5px] text-success">{successMsg}</span>
            )}
            {errorMsg && (
              <span className="text-[11.5px] text-destructive">{errorMsg}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// WhatsApp setup panel — free local Baileys bridge with live QR pair,
// or paid cloud API. Local mode mirrors cmd_whatsapp.
// ─────────────────────────────────────────────────────────────────────
function WhatsAppSetupPanel({
  draft,
  updateField,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
}) {
  const [mode, setMode] = useState<"local" | "cloud">("local");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-[11.5px]">
        <button
          type="button"
          onClick={() => setMode("local")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "local"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          Local bridge (QR pair, free)
        </button>
        <button
          type="button"
          onClick={() => setMode("cloud")}
          className={cn(
            "rounded-md border px-2 py-1 transition-colors",
            mode === "cloud"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          Cloud API (Meta / Composio / Twilio)
        </button>
      </div>

      {mode === "local" ? (
        <WhatsAppLocalPanel />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
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
            placeholder="EAA… or csk_…"
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
      )}
    </div>
  );
}


type WAPairStatus = {
  bridgePresent: boolean;
  bridgeInstalled: boolean;
  mode: string;
  enabled: boolean;
  paired: boolean;
  allowedUsers: string;
};

function WhatsAppLocalPanel() {
  const [status, setStatus] = useState<WAPairStatus | null>(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [waMode, setWaMode] = useState<"bot" | "self-chat">("bot");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [installing, setInstalling] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [pairMessage, setPairMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.getWhatsAppStatus();
      setStatus(next);
      if (next.mode === "bot" || next.mode === "self-chat") setWaMode(next.mode);
      if (next.allowedUsers) setAllowedUsers(next.allowedUsers);
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not read WhatsApp status"));
    } finally {
      setStatusLoaded(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, [refresh]);

  const install = useCallback(async () => {
    setInstalling(true);
    setErrorMsg(null);
    try {
      await api.installWhatsAppBridge();
      await refresh();
    } catch (e) {
      setErrorMsg(errorMessage(e, "npm install failed"));
    } finally {
      setInstalling(false);
    }
  }, [refresh]);

  const saveConfig = useCallback(async () => {
    setSavingConfig(true);
    setErrorMsg(null);
    try {
      await api.configureWhatsApp({
        mode: waMode,
        allowed_users: allowedUsers.trim() || undefined,
      });
      await refresh();
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not save WhatsApp config"));
    } finally {
      setSavingConfig(false);
    }
  }, [waMode, allowedUsers, refresh]);

  const startPairing = useCallback(() => {
    setPairing(true);
    setQrDataUrl(null);
    setPairMessage("Starting bridge…");
    setErrorMsg(null);

    const url = "/api/channels/whatsapp/pair/stream";
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "qr") {
          if (payload.dataUrl) setQrDataUrl(payload.dataUrl);
          setPairMessage(
            waMode === "bot"
              ? "Open WhatsApp (or WhatsApp Business) on the bot's phone → Settings → Linked Devices → Link a Device. Scan this QR."
              : "Open WhatsApp on your phone → Settings → Linked Devices → Link a Device. Scan this QR.",
          );
        } else if (payload.event === "connected") {
          setPairMessage("Connected. Waiting for credentials to flush…");
        } else if (payload.event === "paired") {
          setPairMessage("Paired. WhatsApp session saved.");
          setQrDataUrl(null);
        } else if (payload.event === "exit") {
          setPairing(false);
          es.close();
          eventSourceRef.current = null;
          refresh();
        }
      } catch {
        // ignore malformed
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setPairing(false);
      if (!qrDataUrl) {
        setErrorMsg("Pairing stream closed. If you weren't quick enough, click 'Start pairing' again.");
      }
    };
  }, [waMode, refresh, qrDataUrl]);

  if (!statusLoaded) {
    return (
      <p className="text-[11.5px] text-muted-foreground">
        <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> Loading WhatsApp status…
      </p>
    );
  }
  if (!status?.bridgePresent) {
    return (
      <p className="text-[11.5px] text-warning">
        WhatsApp bridge script not found. This Elevate install ships it at
        scripts/whatsapp-bridge/bridge.js — try running `elevate update`.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <ol className="ml-4 list-decimal space-y-1 text-[11.5px] leading-5 text-muted-foreground">
        <li>
          Pick a mode. <strong>Separate bot number</strong> is cleaner — the
          bot has its own WhatsApp number (e.g. WhatsApp Business on the same
          phone with a 2nd line, or a cheap prepaid SIM). <strong>Self-chat</strong>{" "}
          uses your own number; you DM yourself to talk to the agent.
        </li>
        <li>
          Add allowed phone numbers (e.g. <code className="rounded bg-muted px-1 py-0.5 text-[11px]">15551234567</code>).
          Empty means anyone can message the bot.
        </li>
        <li>Install bridge deps (one-time npm install).</li>
        <li>Pair via QR — opens Linked Devices → scan the code below.</li>
      </ol>

      <div className="grid gap-3 md:grid-cols-2">
        <WizardSelect
          label="WhatsApp mode"
          value={waMode}
          onChange={(v) => setWaMode(v as "bot" | "self-chat")}
          options={[
            { value: "bot", label: "Separate bot number (recommended)" },
            { value: "self-chat", label: "Personal number (self-chat)" },
          ]}
        />
        <WizardField
          label="Allowed phone numbers (comma-separated, or * for any)"
          value={allowedUsers}
          onChange={setAllowedUsers}
          placeholder="15551234567,15559876543"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={saveConfig} disabled={savingConfig}>
          {savingConfig && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          Save mode + allowlist
        </Button>
        {!status.bridgeInstalled && (
          <Button size="sm" variant="outline" onClick={install} disabled={installing}>
            {installing && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Install bridge deps (npm install)
          </Button>
        )}
        <Button
          size="sm"
          onClick={startPairing}
          disabled={pairing || !status.bridgeInstalled || !status.mode}
        >
          {pairing && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {status.paired ? "Re-pair" : "Start pairing"}
        </Button>
        {status.paired && !pairing && (
          <span className="inline-flex items-center gap-1 text-[11.5px] text-success">
            <CheckCircle2 className="h-3.5 w-3.5" /> Session paired
          </span>
        )}
      </div>

      {qrDataUrl && (
        <div className="flex flex-col items-start gap-2 rounded-md border border-border bg-card/60 p-3">
          <img
            src={qrDataUrl}
            alt="WhatsApp pairing QR code"
            className="h-56 w-56 rounded-sm bg-white p-2"
          />
          {pairMessage && (
            <p className="text-[11.5px] leading-5 text-muted-foreground">{pairMessage}</p>
          )}
        </div>
      )}
      {!qrDataUrl && pairMessage && (
        <p className="text-[11.5px] leading-5 text-muted-foreground">{pairMessage}</p>
      )}
      {errorMsg && (
        <p className="text-[11.5px] leading-5 text-destructive">{errorMsg}</p>
      )}
    </div>
  );
}
