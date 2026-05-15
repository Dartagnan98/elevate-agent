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
                    draft.imessageEnabled
                  }
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
                  <SlackTestButton
                    webhookUrl={draft.slackWebhookUrl}
                    channel={draft.slackChannel}
                  />
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

// Inline Composio account connector — mirrors the connect-account flow in
// ConfigPage's ComposioPanel but trimmed to fit inside a wizard step.
// Lists already-connected toolkits and offers a search + connect for new
// ones. Opens Composio's OAuth URL in a new tab; refreshes on focus.
function ComposioConnectionsInline({ keyPresent }: { keyPresent: boolean }) {
  const [status, setStatus] = useState<{ valid: boolean; error?: string | null } | null>(null);
  const [connections, setConnections] = useState<
    Array<{ id: string; toolkit?: { slug?: string | null; name?: string | null } | null; status?: string | null }>
  >([]);
  const [toolkits, setToolkits] = useState<
    Array<{ slug?: string | null; name?: string | null; logo_url?: string | null }>
  >([]);
  const [loading, setLoading] = useState(false);
  const [connectingSlug, setConnectingSlug] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!keyPresent) {
      setStatus(null);
      setConnections([]);
      setToolkits([]);
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    // Fire all three calls in parallel from the jump. The previous flow
    // awaited /status before kicking off /connections + /toolkits — a
    // 1+1 round-trip serial chain that put the wizard's slowest call on
    // the critical path. Each toolkit/connection fetch hits Composio's
    // API which can take 2-4s on cold cache; serializing it doubled the
    // wait for no reason since an invalid key just gives 401s on the
    // dependent calls that we ignore anyway.
    const [statusRes, connsRes, toolkitsRes] = await Promise.allSettled([
      api.getComposioStatus(),
      api.getComposioConnections(),
      api.getComposioToolkits(),
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
    if (statusValid && toolkitsRes.status === "fulfilled") {
      const tkData =
        (toolkitsRes.value.data as { items?: typeof toolkits } | typeof toolkits) ?? [];
      setToolkits(Array.isArray(tkData) ? tkData : tkData.items ?? []);
    } else {
      setToolkits([]);
    }
    setLoading(false);
  }, [keyPresent]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onFocus = () => {
      if (status?.valid) void refresh();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh, status?.valid]);

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

  if (!keyPresent) {
    return (
      <p className="text-[11.5px] leading-5 text-muted-foreground/80">
        Paste a Composio key above to connect Gmail, Calendar, Slack, GitHub, Notion, and 100+ more.
      </p>
    );
  }

  if (loading && status === null) {
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

  const lowered = query.trim().toLowerCase();
  const visibleToolkits = (lowered
    ? toolkits.filter(
        (t) =>
          (t.name ?? "").toLowerCase().includes(lowered) ||
          (t.slug ?? "").toLowerCase().includes(lowered),
      )
    : toolkits
  ).slice(0, 12);

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
            {connections.map((c) => (
              <span
                key={c.id}
                className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-foreground"
              >
                <CheckCircle2 className="h-3 w-3 text-primary" />
                {c.toolkit?.name ?? c.toolkit?.slug ?? c.id}
              </span>
            ))}
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
          {visibleToolkits.map((t) => {
            const slug = (t.slug ?? "").toLowerCase();
            const connected = connectedSlugs.has(slug);
            const busy = connectingSlug === slug;
            return (
              <button
                key={slug || t.name}
                type="button"
                onClick={() => slug && !connected && !busy && connect(slug)}
                disabled={!slug || connected || busy}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-md border border-border bg-card/60 px-3 py-1.5 text-left text-[12px] transition-colors",
                  !connected && !busy && "hover:border-primary/40 hover:bg-primary/5",
                  connected && "opacity-60",
                )}
              >
                <span className="truncate">{t.name ?? slug}</span>
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
          {visibleToolkits.length === 0 && (
            <span className="col-span-full text-[11.5px] text-muted-foreground/80">
              No toolkits match "{query}". Try another term.
            </span>
          )}
        </div>
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
