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
  Save,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubAgent,
  AgentSetupSnapshot,
  OAuthProvider,
  TelegramApprovedEntry,
  TelegramPendingEntry,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import {
  AgentConfigEditor,
  AgentTelegramLaneEditor,
  type AgentEditPatch,
  type SkillEntry,
  type ToolsetEntry,
} from "@/components/agent-hub/AgentConfigEditor";
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
  | "tts"
  | "terminal"
  | "agent_settings"
  | "memory"
  | "inbound"
  | "tools"
  | "skills"
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
    eyebrow: "Step 1 of 10",
    title: "Brain",
    subtitle:
      "Sign in to a model provider, then pick which one the agent thinks with. Same auth state as the CLI — if `elevate auth add anthropic` is done, you'll see Anthropic connected below.",
  },
  {
    id: "tts",
    eyebrow: "Step 2 of 10",
    title: "Voice (TTS)",
    subtitle:
      "Optional. Give the agent a voice for read-aloud, voice notes, and audio replies. Edge TTS is free; ElevenLabs / OpenAI TTS / Gemini sound the best.",
  },
  {
    id: "terminal",
    eyebrow: "Step 3 of 10",
    title: "Terminal backend",
    subtitle:
      "Where the agent runs shell commands. Local runs on this Mac. Pick Docker / Modal / SSH / Daytona / Singularity if you want the agent's shell isolated or remote.",
  },
  {
    id: "agent_settings",
    eyebrow: "Step 4 of 10",
    title: "Agent settings",
    subtitle:
      "Tune the runtime: max iterations per turn, tool progress verbosity, when to compress context, and when sessions auto-reset.",
  },
  {
    id: "memory",
    eyebrow: "Step 5 of 10",
    title: "Memory store",
    subtitle:
      "Where long-term memory lives. Local SQLite is zero-config and runs on this Mac. Pick Supabase later if you want memory shared across devices.",
  },
  {
    id: "inbound",
    eyebrow: "Step 6 of 10",
    title: "How the agent hears you",
    subtitle:
      "Pick every surface you want to reach the agent from — CLI is always on. Telegram and iMessage are the most common. 17 platforms supported — open \"More platforms\" for Signal, Matrix, Email, SMS, Feishu, WeCom, QQ Bot, BlueBubbles, and webhooks.",
  },
  {
    id: "tools",
    eyebrow: "Step 7 of 10",
    title: "APIs + tools",
    subtitle:
      "Optional. Image generation (Nano Banana) lights up /generate, /edit, /restore. Composio plugs in 100+ pre-wired tools — Gmail, Calendar, Slack, GitHub, Notion. Toolsets show what's installed and configured below.",
  },
  {
    id: "skills",
    eyebrow: "Step 8 of 10",
    title: "Skills",
    subtitle:
      "Reusable workflows the agent can run on command — research, follow-up, lead-pull, weekly report. Browse what's installed, see what each one does, flip them on/off. Disabled skills won't be picked by autopilot but you can still call them by name.",
  },
  {
    id: "outbound",
    eyebrow: "Step 9 of 10",
    title: "How the agent sends messages",
    subtitle:
      "Pick which channels the agent can write to. For bots and webhooks (Telegram, Discord, WhatsApp, Slack) the same credentials from Step 6 handle outbound — flip the channel off here to make the agent read-only on it. iMessage outbound uses Messages.app on this Mac.",
  },
  {
    id: "subagents",
    eyebrow: "Step 10 of 10",
    title: "Specialist agents",
    subtitle:
      "Pick which Agent Hub agents run alongside the main agent. Each one gets its own role, prompt, skills, toolsets, and (optional) Telegram lane — configure them inline below.",
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
      aria-label="Welcome to Elevation"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevation · Agent
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
                  title="Or paste API keys"
                  hint="For providers that don't have OAuth, or to override an OAuth login with a raw key. Writes to ~/.elevate/.env."
                >
                  <ApiKeysPanel
                    onError={(msg) => setError(msg)}
                    onSuccess={() => undefined}
                  />
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
                        {
                          value: "xai",
                          label: `xAI (Grok)${connectedProviderIds.has("xai-oauth") || connectedProviderIds.has("xai") ? " · connected" : ""}`,
                        },
                        {
                          value: "gemini",
                          label: `Google Gemini${connectedProviderIds.has("google-gemini-cli") || connectedProviderIds.has("gemini") ? " · connected" : ""}`,
                        },
                        {
                          value: "minimax",
                          label: `MiniMax${connectedProviderIds.has("minimax-oauth") || connectedProviderIds.has("minimax") ? " · connected" : ""}`,
                        },
                        { value: "deepseek", label: "DeepSeek (paste key in .env)" },
                        { value: "zai", label: "Z.AI / GLM (paste key in .env)" },
                        { value: "kimi-coding", label: "Kimi / Moonshot (paste key in .env)" },
                        { value: "nvidia", label: "NVIDIA NIM (paste key in .env)" },
                        { value: "huggingface", label: "Hugging Face (paste key in .env)" },
                        { value: "ollama-cloud", label: "Ollama Cloud (paste key in .env)" },
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
                        { value: "ollama", label: "Ollama (local server)" },
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

            {step.id === "tts" && (
              <WizardSection
                title="Text-to-Speech provider"
                hint="Optional. Edge TTS works without a key. ElevenLabs / OpenAI / Gemini sound natural — paste the matching key."
              >
                <TtsBrowser />
              </WizardSection>
            )}

            {step.id === "terminal" && (
              <WizardSection
                title="Terminal backend"
                hint="The shell environment your agent runs commands in. Local is fine for most operators. Remote backends let the agent run in a sandbox or on another machine."
              >
                <TerminalBrowser />
              </WizardSection>
            )}

            {step.id === "agent_settings" && (
              <WizardSection
                title="Runtime knobs"
                hint="Defaults are sensible — only change if you know why. 90 iterations, all tool progress, 50% compression threshold, daily reset at 4am local."
              >
                <AgentSettingsBrowser />
              </WizardSection>
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
                  On finish, Elevation creates the operational tables (contacts, conversations, deals, tasks) via migrations.
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

                <WizardSection
                  title="More messaging platforms"
                  hint="Signal, Matrix, Mattermost, Email, SMS, DingTalk, Feishu, WeCom (+ self-built callback), Weixin, QQ Bot, BlueBubbles, generic webhooks. Each one writes to the same env vars the CLI would."
                >
                  <ExtendedChannelsBrowser />
                </WizardSection>

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

                <WizardSection
                  title="Toolsets"
                  hint="Toolsets are bundles of tools the agent can call directly (web search, image generation, email reader, calendar, MCP servers). Each one shows whether it's enabled on the CLI runtime and whether its env keys are configured."
                >
                  <ToolsetsBrowser />
                </WizardSection>
              </>
            )}

            {step.id === "skills" && (
              <>
                <WizardSection
                  title="Installed skills"
                  hint="Skills are reusable workflows (research, follow-up, lead-pull, weekly report). Browse what's installed, see what each one does, flip them on/off. Disabled skills won't be picked by autopilot but you can still call them by name."
                >
                  <SkillsBrowser />
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
                title="Agent Hub roster"
                hint="Configure every Agent Hub agent inline: enable, skills, toolsets, platforms, system prompt, and per-agent Telegram bot. No /hub redirect — everything stays in setup."
              >
                <AgentHubRoster />
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

// Lists every Agent Hub agent that already has a Telegram bot wired up.
// Pulls /api/agent-hub (lite) and surfaces any agent whose telegramLane is
// configured. Shown inside TelegramPairingPanel so the operator sees every
// configured bot before pasting a new token.
type PeerRailRow = {
  key: string;
  name: string;
  role: string;
  tokenPreview: string;
};

function TelegramPeerRail() {
  const [rows, setRows] = useState<PeerRailRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getAgentHub({ lite: true })
      .then((resp) => {
        if (cancelled) return;
        const next: PeerRailRow[] = [];
        for (const a of resp.agents ?? []) {
          if (!a.telegramLane?.configured) continue;
          next.push({
            key: a.id,
            name: a.name || a.id,
            role: a.role || "",
            tokenPreview: a.telegramLane.tokenConfigured ? "configured" : "lane only",
          });
        }
        setRows(next);
      })
      .catch(() => {
        /* silent — rail is purely informational */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || rows.length === 0) return null;

  return (
    <section className="rounded-md border border-border bg-card/40 px-3 py-2.5">
      <header className="mb-1.5">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
          Agent Hub bots already configured
        </span>
      </header>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li
            key={r.key}
            className="flex items-center justify-between gap-3 text-[11.5px] leading-4"
          >
            <span className="min-w-0 truncate">
              <span className="text-foreground">{r.name}</span>
              {r.role && (
                <span className="text-muted-foreground/70"> · {r.role}</span>
              )}
            </span>
            <span className="shrink-0 font-mono-ui text-[10.5px] tracking-wide text-muted-foreground/80">
              {r.tokenPreview}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[10.5px] leading-4 text-muted-foreground/70">
        These bots are wired through Agent Hub. Paste a fresh BotFather token below to add a new one.
      </p>
    </section>
  );
}

// Surfaces the AI peers the operator has wired up alongside this elevate
// agent — signed-in model providers + the agents the operator has built in
// the Elevation Agent Hub. Read-only summary; deep config lives on /hub.
function ConnectedAgentsRail({
  oauthProviders,
}: {
  oauthProviders: OAuthProvider[];
}) {
  const [hubAgents, setHubAgents] = useState<HubAgentRow[]>([]);
  const [hubLoading, setHubLoading] = useState(true);
  const [hubError, setHubError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHubLoading(true);
    api
      .getAgentHub({ lite: true })
      .then((resp) => {
        if (cancelled) return;
        setHubAgents(
          (resp.agents ?? []).map((a) => ({
            id: a.id,
            name: a.name || a.id,
            role: a.role || "",
            description: a.description || "",
            enabled: Boolean(a.enabled),
            status: a.status || "ready",
          })),
        );
        setHubError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setHubAgents([]);
        setHubError(errorMessage(err, "Failed to load Agent Hub."));
      })
      .finally(() => {
        if (!cancelled) setHubLoading(false);
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
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[13.5px] font-semibold text-foreground">
            Already in your stack
          </h3>
          <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">
            Model providers signed in + agents you've built in the Agent Hub.
          </p>
        </div>
        <a
          href="/hub"
          className="shrink-0 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          Open Agent Hub →
        </a>
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
            Agent Hub agents
          </h4>
          {hubLoading ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">Loading…</p>
          ) : hubError ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">
              {hubError}
            </p>
          ) : hubAgents.length === 0 ? (
            <p className="mt-2 text-[12px] text-muted-foreground/80">
              No agents yet. Build one on{" "}
              <a href="/hub" className="text-primary underline-offset-2 hover:underline">
                /hub
              </a>
              .
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {hubAgents.map((agent) => (
                <AgentHubAgentRow
                  key={agent.id}
                  agent={agent}
                  onChange={(patch) =>
                    setHubAgents((prev) =>
                      prev.map((a) =>
                        a.id === agent.id ? { ...a, ...patch } : a,
                      ),
                    )
                  }
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

type HubAgentRow = {
  id: string;
  name: string;
  role: string;
  description: string;
  enabled: boolean;
  status: string;
};

// Per-row enable toggle + inline edit link. Toggle hits api.updateAgent so the
// operator can flip an agent on/off without leaving the wizard; deeper config
// (skills, toolsets, prompt) still lives on /hub.
function AgentHubAgentRow({
  agent,
  onChange,
}: {
  agent: HubAgentRow;
  onChange: (patch: Partial<HubAgentRow>) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleToggle = async (next: boolean) => {
    setSaving(true);
    setErr(null);
    const prev = agent.enabled;
    onChange({ enabled: next });
    try {
      await api.updateAgent(agent.id, { enabled: next });
    } catch (e) {
      onChange({ enabled: prev });
      setErr(errorMessage(e, "Toggle failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="rounded-md border border-border/50 bg-background/40 px-3 py-2 text-[12px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-foreground truncate">
          {agent.name}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em]",
              agent.enabled ? "text-primary" : "text-muted-foreground/60",
            )}
          >
            {agent.enabled ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <Circle className="h-3 w-3" />
            )}
            {agent.enabled ? agent.status : "disabled"}
          </span>
          <Switch
            checked={agent.enabled}
            disabled={saving}
            onCheckedChange={handleToggle}
          />
        </div>
      </div>
      {agent.role && (
        <p className="mt-0.5 text-[11px] text-muted-foreground/80 truncate">
          {agent.role}
        </p>
      )}
      {agent.description && (
        <p className="mt-0.5 text-[11px] text-muted-foreground/60 line-clamp-2">
          {agent.description}
        </p>
      )}
      {err && (
        <p className="mt-1 text-[11px] text-destructive">{err}</p>
      )}
    </li>
  );
}

// Full inline Agent Hub roster — Step 6 of the wizard. Lets the operator pick
// which agents run alongside the main one and configure each one (skills,
// toolsets, platforms, prompt, telegram lane) without ever leaving the wizard.
function AgentHubRoster() {
  const [agents, setAgents] = useState<AgentHubAgent[] | null>(null);
  const [skills, setSkills] = useState<SkillEntry[]>([]);
  const [toolsets, setToolsets] = useState<ToolsetEntry[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [envVars, setEnvVars] = useState<Record<string, { is_set: boolean; redacted_value: string | null }>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingConfigId, setSavingConfigId] = useState<string | null>(null);
  const [savingTelegramId, setSavingTelegramId] = useState<string | null>(null);
  const [tokenDrafts, setTokenDrafts] = useState<Record<string, string>>({});
  const [laneDrafts, setLaneDrafts] = useState<Record<string, string>>({});
  const [rowError, setRowError] = useState<Record<string, string | null>>({});
  const [rowToast, setRowToast] = useState<Record<string, string | null>>({});

  const refresh = useCallback(async () => {
    try {
      const [hub, skillsResp, toolsetsResp, envResp] = await Promise.all([
        api.getAgentHub({ includeSkills: true, includeToolsets: true }),
        api.getSkills(),
        api.getToolsets(),
        api.getEnvVars(),
      ]);
      setAgents(hub.agents ?? []);
      setPlatforms((hub.platforms ?? []).map((p) => p.name));
      setSkills(
        skillsResp.map((s) => ({
          name: s.name,
          category: s.category ?? "",
          description: s.description ?? "",
        })),
      );
      setToolsets(
        toolsetsResp.map((t) => ({
          name: t.name,
          label: t.label ?? t.name,
          description: t.description ?? "",
        })),
      );
      const envMap: Record<string, { is_set: boolean; redacted_value: string | null }> = {};
      for (const [key, info] of Object.entries(envResp)) {
        envMap[key] = {
          is_set: Boolean(info?.is_set),
          redacted_value: info?.redacted_value ?? null,
        };
      }
      setEnvVars(envMap);
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e, "Failed to load Agent Hub."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onConfigSave = async (agentId: string, patch: AgentEditPatch) => {
    setSavingConfigId(agentId);
    setRowError((prev) => ({ ...prev, [agentId]: null }));
    setRowToast((prev) => ({ ...prev, [agentId]: null }));
    try {
      await api.updateAgent(agentId, patch);
      setRowToast((prev) => ({ ...prev, [agentId]: "Saved" }));
      await refresh();
    } catch (e) {
      setRowError((prev) => ({
        ...prev,
        [agentId]: errorMessage(e, "Failed to save agent"),
      }));
    } finally {
      setSavingConfigId(null);
    }
  };

  const onTelegramLaneSave = async (agent: AgentHubAgent) => {
    const tokenValue = tokenDrafts[agent.id]?.trim() ?? "";
    const laneValue = laneDrafts[agent.id]?.trim() ?? "";
    const tokenEnv = agent.telegramLane?.tokenEnv;
    const targetEnv = agent.telegramLane?.targetEnv;
    if (!tokenEnv || !targetEnv) {
      setRowError((prev) => ({
        ...prev,
        [agent.id]: "Agent has no Telegram env keys configured.",
      }));
      return;
    }
    if (!tokenValue && !laneValue) return;
    setSavingTelegramId(agent.id);
    setRowError((prev) => ({ ...prev, [agent.id]: null }));
    setRowToast((prev) => ({ ...prev, [agent.id]: null }));
    try {
      if (tokenValue) await api.setEnvVar(tokenEnv, tokenValue);
      if (laneValue) await api.setEnvVar(targetEnv, laneValue);
      setTokenDrafts((prev) => ({ ...prev, [agent.id]: "" }));
      setLaneDrafts((prev) => ({ ...prev, [agent.id]: "" }));
      setRowToast((prev) => ({ ...prev, [agent.id]: "Telegram lane saved" }));
      await refresh();
    } catch (e) {
      setRowError((prev) => ({
        ...prev,
        [agent.id]: errorMessage(e, "Failed to save Telegram lane"),
      }));
    } finally {
      setSavingTelegramId(null);
    }
  };

  const placeholderFor = (key: string | undefined, fallback: string): string => {
    if (!key) return fallback;
    const info = envVars[key];
    if (info?.is_set && info.redacted_value) return info.redacted_value;
    return fallback;
  };

  if (loading && !agents) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-md border border-border/60 bg-card/30 px-3 py-4 text-[12px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>Loading Agent Hub roster…</span>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
        {loadError}
      </div>
    );
  }

  if (!agents || agents.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/40 px-3 py-4 text-[12px] text-muted-foreground">
        No Agent Hub agents yet. The main agent ships by default — you can build
        additional specialists from this section once setup finishes.
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {agents.map((agent) => {
        const lane = agent.telegramLane;
        const tokenPlaceholder = placeholderFor(
          lane?.tokenEnv,
          "BotFather token",
        );
        const lanePlaceholder = placeholderFor(
          lane?.targetEnv,
          "Chat ID or chat:topic",
        );
        const tokenValue = tokenDrafts[agent.id] ?? "";
        const laneValue = laneDrafts[agent.id] ?? "";
        const errMsg = rowError[agent.id];
        const toastMsg = rowToast[agent.id];
        return (
          <article
            key={agent.id}
            className="rounded-md border border-border/60 bg-background/40 px-3 py-3"
          >
            <header className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h4 className="text-[13px] font-semibold text-foreground truncate">
                    {agent.name || agent.id}
                  </h4>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em]",
                      agent.enabled
                        ? "text-primary"
                        : "text-muted-foreground/60",
                    )}
                  >
                    {agent.enabled ? (
                      <CheckCircle2 className="h-3 w-3" />
                    ) : (
                      <Circle className="h-3 w-3" />
                    )}
                    {agent.enabled ? agent.status : "disabled"}
                  </span>
                </div>
                {agent.role && (
                  <p className="mt-0.5 text-[11px] text-muted-foreground/80 truncate">
                    {agent.role}
                  </p>
                )}
                {agent.description && (
                  <p className="mt-0.5 text-[11px] text-muted-foreground/60 line-clamp-2">
                    {agent.description}
                  </p>
                )}
              </div>
            </header>
            <div className="mt-3 grid gap-2">
              <AgentConfigEditor
                agent={agent}
                availableSkills={skills}
                availableToolsets={toolsets}
                availablePlatforms={platforms}
                saving={savingConfigId === agent.id}
                onSave={(patch) => onConfigSave(agent.id, patch)}
              />
              {lane && (
                <AgentTelegramLaneEditor
                  agent={agent}
                  tokenValue={tokenValue}
                  laneValue={laneValue}
                  tokenPlaceholder={tokenPlaceholder}
                  lanePlaceholder={lanePlaceholder}
                  onTokenChange={(v) =>
                    setTokenDrafts((prev) => ({ ...prev, [agent.id]: v }))
                  }
                  onLaneChange={(v) =>
                    setLaneDrafts((prev) => ({ ...prev, [agent.id]: v }))
                  }
                  onSave={() => void onTelegramLaneSave(agent)}
                  saving={savingTelegramId === agent.id}
                />
              )}
            </div>
            {errMsg && (
              <p className="mt-2 text-[11px] text-destructive">{errMsg}</p>
            )}
            {!errMsg && toastMsg && (
              <p className="mt-2 text-[11px] text-primary">{toastMsg}</p>
            )}
          </article>
        );
      })}
    </div>
  );
}

type ApiKeyField = {
  envKey: string;
  label: string;
  description: string;
  docsUrl?: string;
  placeholder?: string;
};

const API_KEY_FIELDS: ApiKeyField[] = [
  {
    envKey: "OPENAI_API_KEY",
    label: "OpenAI",
    description: "GPT-4o, GPT-5, o1/o3, embeddings.",
    docsUrl: "https://platform.openai.com/api-keys",
    placeholder: "sk-...",
  },
  {
    envKey: "OPENROUTER_API_KEY",
    label: "OpenRouter",
    description: "One key, 100+ models. Falls back when others rate-limit.",
    docsUrl: "https://openrouter.ai/keys",
    placeholder: "sk-or-...",
  },
  {
    envKey: "ANTHROPIC_API_KEY",
    label: "Anthropic API",
    description: "Claude Opus/Sonnet/Haiku via raw API key (no subscription).",
    docsUrl: "https://console.anthropic.com/settings/keys",
    placeholder: "sk-ant-...",
  },
  {
    envKey: "AZURE_OPENAI_API_KEY",
    label: "Azure OpenAI",
    description: "Enterprise/region-locked OpenAI deployments.",
    docsUrl: "https://learn.microsoft.com/azure/ai-services/openai/",
    placeholder: "azure key",
  },
  {
    envKey: "AZURE_OPENAI_ENDPOINT",
    label: "Azure endpoint",
    description: "https://{resource}.openai.azure.com",
    placeholder: "https://your-resource.openai.azure.com",
  },
  {
    envKey: "VOYAGE_API_KEY",
    label: "Voyage AI",
    description: "Voyage embeddings — small + high-quality.",
    docsUrl: "https://docs.voyageai.com/docs/api-key-and-installation",
    placeholder: "pa-...",
  },
  {
    envKey: "COHERE_API_KEY",
    label: "Cohere",
    description: "Cohere embeddings + reranker.",
    docsUrl: "https://dashboard.cohere.com/api-keys",
    placeholder: "cohere key",
  },
  {
    envKey: "XAI_API_KEY",
    label: "xAI (Grok)",
    description: "Grok models via direct API key. (Subscription login is the xAI Grok card above.)",
    docsUrl: "https://console.x.ai/",
    placeholder: "xai-...",
  },
  {
    envKey: "GEMINI_API_KEY",
    label: "Google AI Studio (Gemini)",
    description: "Gemini models via direct API key. (Free OAuth login is the Google Gemini card above.)",
    docsUrl: "https://aistudio.google.com/apikey",
    placeholder: "AIza...",
  },
  {
    envKey: "DEEPSEEK_API_KEY",
    label: "DeepSeek",
    description: "DeepSeek-V3 / R1 / coder — direct API.",
    docsUrl: "https://platform.deepseek.com/api_keys",
    placeholder: "sk-...",
  },
  {
    envKey: "GLM_API_KEY",
    label: "Z.AI / GLM",
    description: "Zhipu GLM models — direct API.",
    docsUrl: "https://z.ai/manage-apikey/apikey-list",
    placeholder: "glm key",
  },
  {
    envKey: "KIMI_API_KEY",
    label: "Kimi / Moonshot",
    description: "Kimi Coding Plan (api.kimi.com) & Moonshot API.",
    docsUrl: "https://platform.moonshot.ai/console/api-keys",
    placeholder: "sk-...",
  },
  {
    envKey: "MINIMAX_API_KEY",
    label: "MiniMax",
    description: "MiniMax global direct API. (OAuth Coding Plan is the MiniMax card above.)",
    docsUrl: "https://www.minimax.io/platform/user-center/basic-information",
    placeholder: "minimax key",
  },
  {
    envKey: "NVIDIA_API_KEY",
    label: "NVIDIA NIM",
    description: "Nemotron models via build.nvidia.com.",
    docsUrl: "https://build.nvidia.com/",
    placeholder: "nvapi-...",
  },
  {
    envKey: "HF_TOKEN",
    label: "Hugging Face",
    description: "Inference Providers — 20+ open models.",
    docsUrl: "https://huggingface.co/settings/tokens",
    placeholder: "hf_...",
  },
];

// Password-style inputs for raw API keys. Shows "Already set — …last4 (paste to
// replace)" when ~/.elevate/.env already has the value, so the operator doesn't
// have to wonder whether their key is wired up.
function ApiKeysPanel({
  onError,
  onSuccess,
}: {
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}) {
  type EnvMap = Record<string, { is_set: boolean; redacted_value: string | null }>;
  const [envMap, setEnvMap] = useState<EnvMap>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getEnvVars();
      const next: EnvMap = {};
      for (const field of API_KEY_FIELDS) {
        const info = resp[field.envKey];
        next[field.envKey] = {
          is_set: Boolean(info?.is_set),
          redacted_value: info?.redacted_value ?? null,
        };
      }
      setEnvMap(next);
    } catch (e) {
      onError(errorMessage(e, "Could not load env keys"));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSave = async (field: ApiKeyField) => {
    const value = drafts[field.envKey]?.trim() ?? "";
    if (!value) {
      onError(`Paste a value for ${field.label} first.`);
      return;
    }
    setSaving(field.envKey);
    try {
      await api.setEnvVar(field.envKey, value);
      setDrafts((prev) => ({ ...prev, [field.envKey]: "" }));
      onSuccess(`${field.label} saved.`);
      await refresh();
    } catch (e) {
      onError(errorMessage(e, `Failed to save ${field.label}`));
    } finally {
      setSaving(null);
    }
  };

  const handleClear = async (field: ApiKeyField) => {
    if (!confirm(`Remove ${field.label} from ~/.elevate/.env?`)) return;
    setSaving(field.envKey);
    try {
      await api.deleteEnvVar(field.envKey);
      setDrafts((prev) => ({ ...prev, [field.envKey]: "" }));
      onSuccess(`${field.label} removed.`);
      await refresh();
    } catch (e) {
      onError(errorMessage(e, `Failed to clear ${field.label}`));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="space-y-2.5">
      {loading && Object.keys(envMap).length === 0 ? (
        <p className="text-[12px] text-muted-foreground/80">Loading…</p>
      ) : (
        API_KEY_FIELDS.map((field) => {
          const state = envMap[field.envKey];
          const draftVal = drafts[field.envKey] ?? "";
          const isSaving = saving === field.envKey;
          const last4 =
            state?.redacted_value
              ? state.redacted_value.replace(/^[•*]+/g, "").slice(-4)
              : "";
          return (
            <div
              key={field.envKey}
              className="rounded-md border border-border/60 bg-background/40 px-3 py-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">
                      {field.label}
                    </span>
                    {state?.is_set && (
                      <span className="inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-primary">
                        <CheckCircle2 className="h-3 w-3" />
                        set
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground/80">
                    {field.description}
                  </p>
                  {state?.is_set && last4 && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground/70">
                      Already set — <code className="font-mono-ui text-foreground/80">…{last4}</code>
                      <span className="opacity-80"> (paste below to replace)</span>
                    </p>
                  )}
                </div>
                {field.docsUrl && (
                  <a
                    href={field.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 inline-flex items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
                    title={`Get a ${field.label} key`}
                  >
                    Get key
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={field.placeholder || "paste key"}
                  value={draftVal}
                  onChange={(e) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [field.envKey]: e.target.value,
                    }))
                  }
                  className="flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 font-mono-ui text-[11.5px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <Button
                  size="sm"
                  variant="default"
                  disabled={isSaving || !draftVal.trim()}
                  onClick={() => handleSave(field)}
                  className="h-7 text-[11.5px]"
                >
                  {isSaving ? (
                    <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  ) : null}
                  Save
                </Button>
                {state?.is_set && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isSaving}
                    onClick={() => handleClear(field)}
                    className="h-7 text-[11.5px]"
                  >
                    Clear
                  </Button>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

// Full installed skills browser — groups by category, shows descriptions,
// surfaces the enable/disable toggle backed by ~/.elevate/config.yaml.
// Mirrors `elevate skills list` + `elevate skills toggle <name>`.
function SkillsBrowser() {
  const [skills, setSkills] = useState<
    Array<{ name: string; category: string; description: string; enabled: boolean }> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingName, setSavingName] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      const resp = await api.getSkills();
      setSkills(
        resp.map((s) => ({
          name: s.name,
          category: s.category || "uncategorized",
          description: s.description || "",
          enabled: s.enabled,
        })),
      );
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e, "Failed to load skills"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleToggle = async (name: string, next: boolean) => {
    setSavingName(name);
    const previous = skills;
    setSkills((prev) =>
      prev
        ? prev.map((s) => (s.name === name ? { ...s, enabled: next } : s))
        : prev,
    );
    try {
      await api.toggleSkill(name, next);
    } catch (e) {
      setSkills(previous);
      setLoadError(errorMessage(e, `Toggle ${name} failed`));
    } finally {
      setSavingName(null);
    }
  };

  const grouped = useMemo(() => {
    type Row = { name: string; category: string; description: string; enabled: boolean };
    if (!skills) return [] as Array<{ category: string; entries: Row[] }>;
    const needle = query.trim().toLowerCase();
    const filtered: Row[] = needle
      ? skills.filter(
          (s) =>
            s.name.toLowerCase().includes(needle) ||
            s.description.toLowerCase().includes(needle) ||
            s.category.toLowerCase().includes(needle),
        )
      : skills;
    const map = new Map<string, Row[]>();
    for (const s of filtered) {
      const key = s.category || "uncategorized";
      const arr = map.get(key) ?? [];
      arr.push(s);
      map.set(key, arr);
    }
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([category, entries]) => ({
        category,
        entries: entries.sort((x, y) => x.name.localeCompare(y.name)),
      }));
  }, [skills, query]);

  if (loading && !skills) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading installed skills…
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
        {loadError}
      </div>
    );
  }
  if (!skills || skills.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/40 px-3 py-4 text-[12px] text-muted-foreground">
        No skills installed. Run <code>elevate skills install</code> from the CLI to add one.
      </div>
    );
  }

  const enabledCount = skills.filter((s) => s.enabled).length;

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 text-[11.5px] text-muted-foreground">
          <span className="tabular-nums text-foreground">{enabledCount}</span>
          <span>of {skills.length} enabled</span>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter skills…"
          className="h-7 w-44 rounded-md border border-border bg-background px-2 text-[12px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
        />
      </div>
      <div className="grid gap-3">
        {grouped.map(({ category, entries }) => (
          <div key={category} className="grid gap-1">
            <h4 className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
              {category}
            </h4>
            <ul className="grid gap-1.5">
              {entries.map((skill) => (
                <li
                  key={skill.name}
                  className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-background/40 px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <code className="!bg-transparent !p-0 font-mono-ui text-[12px] font-medium text-foreground">
                        /{skill.name}
                      </code>
                      {!skill.enabled && (
                        <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/60">
                          disabled
                        </span>
                      )}
                    </div>
                    {skill.description && (
                      <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground/80">
                        {skill.description}
                      </p>
                    )}
                  </div>
                  <Switch
                    checked={skill.enabled}
                    disabled={savingName === skill.name}
                    onCheckedChange={(v) => void handleToggle(skill.name, v)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// Toolset registry browser. Mirrors `elevate setup tools` → toolset multi-select
// with the same labels + descriptions sourced from `_get_effective_configurable_toolsets`.
// Read-only for now: a toggle would need a backend write to
// `config.platform_toolsets[cli]` which doesn't have an endpoint yet.
function ToolsetsBrowser() {
  const [toolsets, setToolsets] = useState<
    Array<{
      name: string;
      label: string;
      description: string;
      enabled: boolean;
      configured: boolean;
      tools: string[];
    }> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      const resp = await api.getToolsets();
      setToolsets(
        resp.map((t) => ({
          name: t.name,
          label: t.label || t.name,
          description: t.description || "",
          enabled: t.enabled,
          configured: t.configured,
          tools: t.tools ?? [],
        })),
      );
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e, "Failed to load toolsets"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filtered = useMemo(() => {
    if (!toolsets) return [] as NonNullable<typeof toolsets>;
    const needle = query.trim().toLowerCase();
    if (!needle) return toolsets;
    return toolsets.filter(
      (t) =>
        t.name.toLowerCase().includes(needle) ||
        t.label.toLowerCase().includes(needle) ||
        t.description.toLowerCase().includes(needle) ||
        t.tools.some((tool) => tool.toLowerCase().includes(needle)),
    );
  }, [toolsets, query]);

  if (loading && !toolsets) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading toolsets…
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
        {loadError}
      </div>
    );
  }
  if (!toolsets || toolsets.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/40 px-3 py-4 text-[12px] text-muted-foreground">
        No toolsets registered.
      </div>
    );
  }

  const enabledCount = toolsets.filter((t) => t.enabled).length;
  const configuredCount = toolsets.filter((t) => t.configured).length;

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3 text-[11.5px] text-muted-foreground">
          <span>
            <span className="tabular-nums text-foreground">{enabledCount}</span>{" "}
            of {toolsets.length} enabled
          </span>
          <span>
            <span className="tabular-nums text-foreground">{configuredCount}</span>{" "}
            configured
          </span>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter toolsets…"
          className="h-7 w-44 rounded-md border border-border bg-background px-2 text-[12px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
        />
      </div>
      <ul className="grid gap-1.5">
        {filtered.map((t) => (
          <li
            key={t.name}
            className="rounded-md border border-border/60 bg-background/40 px-3 py-2"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12.5px] font-medium text-foreground">
                    {t.label}
                  </span>
                  <code className="!bg-transparent !p-0 font-mono-ui text-[10.5px] text-muted-foreground/70">
                    {t.name}
                  </code>
                  {t.enabled ? (
                    <span className="inline-flex items-center gap-1 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-primary">
                      <CheckCircle2 className="h-3 w-3" />
                      enabled
                    </span>
                  ) : (
                    <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/60">
                      disabled
                    </span>
                  )}
                  {!t.configured && t.enabled && (
                    <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-warning">
                      needs keys
                    </span>
                  )}
                </div>
                {t.description && (
                  <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground/80">
                    {t.description}
                  </p>
                )}
                {t.tools.length > 0 && (
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[10.5px] uppercase tracking-wide text-muted-foreground/60 hover:text-foreground">
                      {t.tools.length} tools
                    </summary>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {t.tools.map((tool) => (
                        <code
                          key={tool}
                          className="rounded-sm bg-muted/40 px-1.5 py-0.5 text-[10.5px] text-muted-foreground"
                        >
                          {tool}
                        </code>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[10.5px] leading-5 text-muted-foreground/60">
        Toolset enable/disable + per-toolset API key prompts ship in the next slice. For now, use <code>elevate setup tools</code> in the CLI.
      </p>
    </div>
  );
}

// =========================================================================
// TTS, Terminal, Agent settings, and extended-channel registries.
//
// Each one mirrors the matching `_setup_*` flow in cli/elevate_cli/setup.py
// (see web/docs/cli-setup-questionnaire.md for the exact prompt mapping).
// We avoid bloating the central AgentSetupDraft for these optional sections —
// they save inline via `api.saveConfig` (config.yaml) + `api.setEnvVar`
// (env vars) the same way the CLI prompts do.
// =========================================================================

type TtsProvider = {
  id: string;
  label: string;
  envVars: Array<{ key: string; prompt: string; password?: boolean }>;
  hint?: string;
};

const TTS_PROVIDERS: TtsProvider[] = [
  { id: "edge", label: "Edge TTS (free, local)", envVars: [], hint: "Microsoft Edge TTS — free, no key required. Decent quality, sounds robotic next to ElevenLabs." },
  { id: "elevenlabs", label: "ElevenLabs", envVars: [{ key: "ELEVENLABS_API_KEY", prompt: "ElevenLabs API key", password: true }], hint: "Best voice quality. Pay-per-character." },
  { id: "openai", label: "OpenAI TTS", envVars: [{ key: "VOICE_TOOLS_OPENAI_KEY", prompt: "OpenAI API key for TTS", password: true }], hint: "tts-1 / tts-1-hd. Same key plane as ChatGPT." },
  { id: "xai", label: "xAI", envVars: [{ key: "XAI_API_KEY", prompt: "xAI API key for TTS", password: true }] },
  { id: "minimax", label: "MiniMax", envVars: [{ key: "MINIMAX_API_KEY", prompt: "MiniMax API key for TTS", password: true }] },
  { id: "mistral", label: "Mistral Voxtral", envVars: [{ key: "MISTRAL_API_KEY", prompt: "Mistral API key for TTS", password: true }] },
  { id: "gemini", label: "Google Gemini", envVars: [{ key: "GEMINI_API_KEY", prompt: "Gemini API key for TTS", password: true }] },
  { id: "neutts", label: "NeuTTS (local)", envVars: [], hint: "Local model. Requires espeak-ng + NeuTTS deps — install via the CLI." },
  { id: "kittentts", label: "KittenTTS (local)", envVars: [], hint: "Local model. Install via the CLI first." },
];

// TTS provider picker + per-provider env vars. Mirrors `_setup_tts_provider`.
function TtsBrowser() {
  const [provider, setProvider] = useState<string>("");
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [envSet, setEnvSet] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getConfig(), api.getEnvVars()])
      .then(([config, envs]) => {
        if (cancelled) return;
        const tts = (config?.tts as Record<string, unknown>) ?? {};
        setProvider(String(tts.provider ?? ""));
        const setMap: Record<string, boolean> = {};
        for (const p of TTS_PROVIDERS) {
          for (const v of p.envVars) {
            setMap[v.key] = Boolean((envs as Record<string, { is_set?: boolean }>)[v.key]?.is_set);
          }
        }
        setEnvSet(setMap);
      })
      .catch((e) => !cancelled && setError(errorMessage(e, "Failed to load TTS config")));
    return () => { cancelled = true; };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const current = await api.getConfig();
      const ttsCfg = { ...(current.tts as Record<string, unknown> ?? {}), provider };
      await api.saveConfig({ ...current, tts: ttsCfg });
      for (const v of (TTS_PROVIDERS.find((p) => p.id === provider)?.envVars ?? [])) {
        const value = envValues[v.key]?.trim();
        if (value) {
          await api.setEnvVar(v.key, value);
          setEnvSet((m) => ({ ...m, [v.key]: true }));
        }
      }
      setEnvValues({});
      setToast("Saved.");
      setTimeout(() => setToast(null), 1800);
    } catch (e) {
      setError(errorMessage(e, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const active = TTS_PROVIDERS.find((p) => p.id === provider);

  return (
    <div className="grid gap-3">
      <WizardSelect
        label="TTS provider"
        value={provider}
        onChange={setProvider}
        options={[
          { value: "", label: "— skip (no voice) —" },
          ...TTS_PROVIDERS.map((p) => ({ value: p.id, label: p.label })),
        ]}
      />
      {active?.hint && (
        <p className="text-[11.5px] leading-5 text-muted-foreground/80">{active.hint}</p>
      )}
      {active && active.envVars.length > 0 && (
        <div className="grid gap-3">
          {active.envVars.map((v) => (
            <WizardField
              key={v.key}
              label={v.prompt}
              value={envValues[v.key] ?? ""}
              onChange={(val) => setEnvValues((m) => ({ ...m, [v.key]: val }))}
              placeholder={envSet[v.key] ? "Already set — paste to replace" : "Paste key"}
              type={v.password ? "password" : "text"}
              fullWidth
              hint={envSet[v.key] ? `Stored in ${v.key}. Leave blank to keep it.` : undefined}
            />
          ))}
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={handleSave} disabled={saving} className="h-8">
          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Save voice settings
        </Button>
        {toast && <span className="text-[11.5px] text-success">{toast}</span>}
        {error && <span className="text-[11.5px] text-destructive">{error}</span>}
      </div>
    </div>
  );
}

// =========================================================================
// Terminal backend picker. Mirrors `_setup_terminal_backend`.
// =========================================================================

const TERMINAL_BACKENDS = [
  { id: "local", label: "Local (this Mac)", hint: "Agent runs shell commands directly on this machine." },
  { id: "docker", label: "Docker", hint: "Isolated container per session." },
  { id: "modal", label: "Modal", hint: "Cloud-hosted ephemeral compute. Pay per second." },
  { id: "ssh", label: "SSH", hint: "Remote server. Bring your own host + key." },
  { id: "daytona", label: "Daytona", hint: "Managed dev environments." },
  { id: "singularity", label: "Singularity / Apptainer", hint: "Linux-only HPC containers." },
];

function TerminalBrowser() {
  const [backend, setBackend] = useState<string>("local");
  const [cwd, setCwd] = useState<string>("");
  const [dockerImage, setDockerImage] = useState<string>("");
  const [enableSudo, setEnableSudo] = useState<boolean>(false);
  const [sudoPassword, setSudoPassword] = useState<string>("");
  const [sshHost, setSshHost] = useState<string>("");
  const [sshUser, setSshUser] = useState<string>("");
  const [sshPort, setSshPort] = useState<string>("");
  const [sshKey, setSshKey] = useState<string>("");
  const [daytonaImage, setDaytonaImage] = useState<string>("");
  const [envSet, setEnvSet] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getConfig(), api.getEnvVars()])
      .then(([config, envs]) => {
        if (cancelled) return;
        const term = (config?.terminal as Record<string, unknown>) ?? {};
        setBackend(String(term.backend ?? "local"));
        setCwd(String(term.cwd ?? ""));
        setDockerImage(String(term.docker_image ?? ""));
        setDaytonaImage(String(term.daytona_image ?? ""));
        const keys = ["SUDO_PASSWORD", "TERMINAL_SSH_HOST", "TERMINAL_SSH_USER", "TERMINAL_SSH_PORT", "TERMINAL_SSH_KEY", "DAYTONA_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"];
        const setMap: Record<string, boolean> = {};
        for (const k of keys) setMap[k] = Boolean((envs as Record<string, { is_set?: boolean }>)[k]?.is_set);
        setEnvSet(setMap);
        setEnableSudo(Boolean(setMap.SUDO_PASSWORD));
      })
      .catch((e) => !cancelled && setError(errorMessage(e, "Failed to load terminal config")));
    return () => { cancelled = true; };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const current = await api.getConfig();
      const term: Record<string, unknown> = { ...(current.terminal as Record<string, unknown> ?? {}), backend };
      if (backend === "local" && cwd.trim()) term.cwd = cwd.trim();
      if (backend === "docker" && dockerImage.trim()) term.docker_image = dockerImage.trim();
      if (backend === "daytona" && daytonaImage.trim()) term.daytona_image = daytonaImage.trim();
      await api.saveConfig({ ...current, terminal: term });
      if (backend === "local" && enableSudo && sudoPassword.trim()) {
        await api.setEnvVar("SUDO_PASSWORD", sudoPassword.trim());
      }
      if (backend === "ssh") {
        if (sshHost.trim()) await api.setEnvVar("TERMINAL_SSH_HOST", sshHost.trim());
        if (sshUser.trim()) await api.setEnvVar("TERMINAL_SSH_USER", sshUser.trim());
        if (sshPort.trim() && sshPort.trim() !== "22") await api.setEnvVar("TERMINAL_SSH_PORT", sshPort.trim());
        if (sshKey.trim()) await api.setEnvVar("TERMINAL_SSH_KEY", sshKey.trim());
      }
      setToast("Saved.");
      setTimeout(() => setToast(null), 1800);
    } catch (e) {
      setError(errorMessage(e, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-3">
      <WizardSelect
        label="Backend"
        value={backend}
        onChange={setBackend}
        options={TERMINAL_BACKENDS.map((b) => ({ value: b.id, label: b.label }))}
      />
      {TERMINAL_BACKENDS.find((b) => b.id === backend)?.hint && (
        <p className="text-[11.5px] leading-5 text-muted-foreground/80">
          {TERMINAL_BACKENDS.find((b) => b.id === backend)?.hint}
        </p>
      )}
      {backend === "local" && (
        <>
          <WizardField label="Messaging working directory" value={cwd} onChange={setCwd} placeholder="/Users/you/projects" fullWidth />
          <label className="flex items-center gap-2 text-[12.5px] text-foreground">
            <input type="checkbox" checked={enableSudo} onChange={(e) => setEnableSudo(e.target.checked)} className="h-3.5 w-3.5 rounded border-border accent-primary" />
            Enable sudo support (stores password for apt install, etc.)
          </label>
          {enableSudo && (
            <WizardField
              label="Sudo password"
              value={sudoPassword}
              onChange={setSudoPassword}
              placeholder={envSet.SUDO_PASSWORD ? "Already set — paste to replace" : ""}
              type="password"
              fullWidth
              hint={envSet.SUDO_PASSWORD ? "Stored in SUDO_PASSWORD. Leave blank to keep it." : undefined}
            />
          )}
        </>
      )}
      {backend === "docker" && (
        <WizardField label="Docker image" value={dockerImage} onChange={setDockerImage} placeholder="elevate/runtime:latest" fullWidth />
      )}
      {backend === "ssh" && (
        <div className="grid gap-3 md:grid-cols-2">
          <WizardField label="SSH host" value={sshHost} onChange={setSshHost} placeholder="server.example.com" fullWidth hint={envSet.TERMINAL_SSH_HOST ? "Stored. Leave blank to keep it." : undefined} />
          <WizardField label="SSH user" value={sshUser} onChange={setSshUser} placeholder="elevate" fullWidth hint={envSet.TERMINAL_SSH_USER ? "Stored." : undefined} />
          <WizardField label="SSH port" value={sshPort} onChange={setSshPort} placeholder="22" fullWidth hint={envSet.TERMINAL_SSH_PORT ? "Stored." : undefined} />
          <WizardField label="SSH private key path" value={sshKey} onChange={setSshKey} placeholder="~/.ssh/id_ed25519" fullWidth hint={envSet.TERMINAL_SSH_KEY ? "Stored." : undefined} />
        </div>
      )}
      {backend === "daytona" && (
        <WizardField label="Sandbox image" value={daytonaImage} onChange={setDaytonaImage} placeholder="ubuntu:24.04" fullWidth />
      )}
      {(backend === "modal" || backend === "singularity") && (
        <p className="text-[11.5px] leading-5 text-muted-foreground/80">
          {backend === "modal"
            ? "Modal credentials (MODAL_TOKEN_ID + MODAL_TOKEN_SECRET) — run elevate setup terminal in the CLI for the secure prompt."
            : "Singularity / Apptainer (Linux only) — set the container image via elevate setup terminal."}
        </p>
      )}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={handleSave} disabled={saving} className="h-8">
          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Save terminal settings
        </Button>
        {toast && <span className="text-[11.5px] text-success">{toast}</span>}
        {error && <span className="text-[11.5px] text-destructive">{error}</span>}
      </div>
    </div>
  );
}

// =========================================================================
// Agent settings. Mirrors `_setup_agent_settings`.
// =========================================================================

function AgentSettingsBrowser() {
  const [maxTurns, setMaxTurns] = useState<string>("90");
  const [toolProgress, setToolProgress] = useState<string>("all");
  const [compressionThreshold, setCompressionThreshold] = useState<string>("0.50");
  const [sessionResetMode, setSessionResetMode] = useState<string>("both");
  const [idleMinutes, setIdleMinutes] = useState<string>("1440");
  const [atHour, setAtHour] = useState<string>("4");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getConfig().then((config) => {
      if (cancelled) return;
      const agent = (config?.agent as Record<string, unknown>) ?? {};
      const display = (config?.display as Record<string, unknown>) ?? {};
      const compression = (config?.compression as Record<string, unknown>) ?? {};
      const reset = (config?.session_reset as Record<string, unknown>) ?? {};
      setMaxTurns(String(agent.max_turns ?? "90"));
      setToolProgress(String(display.tool_progress ?? "all"));
      setCompressionThreshold(String(compression.threshold ?? "0.50"));
      setSessionResetMode(String(reset.mode ?? "both"));
      setIdleMinutes(String(reset.idle_minutes ?? "1440"));
      setAtHour(String(reset.at_hour ?? "4"));
      setLoaded(true);
    }).catch((e) => !cancelled && setError(errorMessage(e, "Failed to load")));
    return () => { cancelled = true; };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const current = await api.getConfig();
      const compressionThresholdNum = Number(compressionThreshold);
      const payload: Record<string, unknown> = {
        ...current,
        agent: { ...(current.agent as Record<string, unknown> ?? {}), max_turns: Number(maxTurns) || 90 },
        display: { ...(current.display as Record<string, unknown> ?? {}), tool_progress: toolProgress },
        compression: {
          ...(current.compression as Record<string, unknown> ?? {}),
          threshold: Number.isFinite(compressionThresholdNum) ? compressionThresholdNum : 0.5,
          enabled: true,
        },
        session_reset: {
          ...(current.session_reset as Record<string, unknown> ?? {}),
          mode: sessionResetMode,
          idle_minutes: Number(idleMinutes) || 1440,
          at_hour: Number(atHour) || 4,
        },
      };
      await api.saveConfig(payload);
      setToast("Saved.");
      setTimeout(() => setToast(null), 1800);
    } catch (e) {
      setError(errorMessage(e, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading agent settings…
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-2">
        <WizardField
          label="Max iterations per turn"
          value={maxTurns}
          onChange={setMaxTurns}
          placeholder="90"
          fullWidth
          hint="How many tool-use rounds the agent gets before stopping. 90 is the default."
        />
        <WizardSelect
          label="Tool progress mode"
          value={toolProgress}
          onChange={setToolProgress}
          options={[
            { value: "off", label: "off — silent" },
            { value: "new", label: "new — only first call" },
            { value: "all", label: "all — every call (default)" },
            { value: "verbose", label: "verbose — every call + payloads" },
          ]}
        />
        <WizardField
          label="Compression threshold (0.50-0.95)"
          value={compressionThreshold}
          onChange={setCompressionThreshold}
          placeholder="0.50"
          fullWidth
          hint="When context fills past this fraction, older messages compress automatically."
        />
        <WizardSelect
          label="Session reset mode"
          value={sessionResetMode}
          onChange={setSessionResetMode}
          options={[
            { value: "both", label: "Inactivity + daily (default)" },
            { value: "idle", label: "Inactivity only" },
            { value: "daily", label: "Daily only" },
            { value: "none", label: "Never auto-reset" },
          ]}
        />
        {(sessionResetMode === "both" || sessionResetMode === "idle") && (
          <WizardField label="Inactivity timeout (minutes)" value={idleMinutes} onChange={setIdleMinutes} placeholder="1440" fullWidth />
        )}
        {(sessionResetMode === "both" || sessionResetMode === "daily") && (
          <WizardField label="Daily reset hour (0-23, local time)" value={atHour} onChange={setAtHour} placeholder="4" fullWidth />
        )}
      </div>
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={handleSave} disabled={saving} className="h-8">
          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Save agent settings
        </Button>
        {toast && <span className="text-[11.5px] text-success">{toast}</span>}
        {error && <span className="text-[11.5px] text-destructive">{error}</span>}
      </div>
    </div>
  );
}

// =========================================================================
// Extended messaging platforms. Mirrors the 12 CLI `_setup_<platform>` flows
// that aren't covered by the dedicated Telegram / iMessage / Discord /
// WhatsApp / Slack panels above. Each entry lists exactly the env vars the
// CLI saves via `save_env_value`.
// =========================================================================

type ExtendedChannel = {
  id: string;
  label: string;
  hint: string;
  docs?: { href: string; label: string };
  envVars: Array<{ key: string; prompt: string; placeholder?: string; password?: boolean }>;
};

const EXTENDED_CHANNELS: ExtendedChannel[] = [
  {
    id: "signal",
    label: "Signal",
    hint: "Bridge via signal-cli running on this Mac (or a server). Start it with REST API on :8080.",
    docs: { href: "https://github.com/AsamK/signal-cli", label: "signal-cli docs" },
    envVars: [
      { key: "SIGNAL_HTTP_URL", prompt: "HTTP URL", placeholder: "http://127.0.0.1:8080" },
      { key: "SIGNAL_ACCOUNT", prompt: "Account number (E.164)", placeholder: "+15551234567" },
      { key: "SIGNAL_ALLOWED_USERS", prompt: "Allowed users (E.164, comma-separated)", placeholder: "+15555550100,+15555550101" },
      { key: "SIGNAL_GROUP_ALLOWED_USERS", prompt: "Allowed group IDs (or * for all)", placeholder: "*" },
    ],
  },
  {
    id: "matrix",
    label: "Matrix",
    hint: "Open standard. Self-host Synapse or use matrix.org. Optional E2EE.",
    docs: { href: "https://matrix.org/", label: "Matrix docs" },
    envVars: [
      { key: "MATRIX_HOMESERVER", prompt: "Homeserver URL", placeholder: "https://matrix.example.org" },
      { key: "MATRIX_ACCESS_TOKEN", prompt: "Access token (or leave blank for password)", password: true },
      { key: "MATRIX_USER_ID", prompt: "User ID", placeholder: "@bot:example.org" },
      { key: "MATRIX_PASSWORD", prompt: "Password (only if no access token)", password: true },
      { key: "MATRIX_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
      { key: "MATRIX_HOME_ROOM", prompt: "Home room ID" },
      { key: "MATRIX_ENCRYPTION", prompt: "Enable E2EE (true/false)", placeholder: "false" },
    ],
  },
  {
    id: "mattermost",
    label: "Mattermost",
    hint: "Slack-alternative for teams. Self-hosted or cloud.",
    docs: { href: "https://docs.mattermost.com/", label: "Mattermost docs" },
    envVars: [
      { key: "MATTERMOST_URL", prompt: "Server URL", placeholder: "https://mm.example.com" },
      { key: "MATTERMOST_TOKEN", prompt: "Bot token", password: true },
      { key: "MATTERMOST_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
      { key: "MATTERMOST_HOME_CHANNEL", prompt: "Home channel ID" },
    ],
  },
  {
    id: "email",
    label: "Email (IMAP + SMTP)",
    hint: "Inbound + outbound via IMAP/SMTP. Gmail: enable 2FA and create an App Password.",
    docs: { href: "https://support.google.com/accounts/answer/185833", label: "Gmail App Passwords" },
    envVars: [
      { key: "EMAIL_ADDRESS", prompt: "Email address", placeholder: "you@gmail.com" },
      { key: "EMAIL_PASSWORD", prompt: "Email password / App Password", password: true },
      { key: "EMAIL_IMAP_HOST", prompt: "IMAP host", placeholder: "imap.gmail.com" },
      { key: "EMAIL_SMTP_HOST", prompt: "SMTP host", placeholder: "smtp.gmail.com" },
      { key: "EMAIL_ALLOWED_USERS", prompt: "Allowed sender emails (comma-separated)" },
    ],
  },
  {
    id: "sms",
    label: "SMS (Twilio)",
    hint: "Inbound + outbound SMS via Twilio.",
    docs: { href: "https://console.twilio.com/", label: "Twilio Console" },
    envVars: [
      { key: "TWILIO_ACCOUNT_SID", prompt: "Twilio Account SID", placeholder: "AC…" },
      { key: "TWILIO_AUTH_TOKEN", prompt: "Twilio Auth Token", password: true },
      { key: "TWILIO_PHONE_NUMBER", prompt: "Twilio phone number (E.164)", placeholder: "+15551234567" },
      { key: "SMS_ALLOWED_USERS", prompt: "Allowed phone numbers (E.164, comma-separated)" },
      { key: "SMS_HOME_CHANNEL", prompt: "Home channel phone number" },
    ],
  },
  {
    id: "dingtalk",
    label: "DingTalk",
    hint: "Alibaba's enterprise messenger.",
    envVars: [
      { key: "DINGTALK_CLIENT_ID", prompt: "AppKey (Client ID)" },
      { key: "DINGTALK_CLIENT_SECRET", prompt: "AppSecret (Client Secret)", password: true },
    ],
  },
  {
    id: "feishu",
    label: "Feishu / Lark",
    hint: "ByteDance enterprise messenger.",
    docs: { href: "https://open.feishu.cn/app", label: "Feishu open platform" },
    envVars: [
      { key: "FEISHU_APP_ID", prompt: "App ID" },
      { key: "FEISHU_APP_SECRET", prompt: "App Secret", password: true },
      { key: "FEISHU_DOMAIN", prompt: "Domain (feishu or lark)", placeholder: "feishu" },
      { key: "FEISHU_CONNECTION_MODE", prompt: "Connection mode (websocket or webhook)", placeholder: "websocket" },
      { key: "FEISHU_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
      { key: "FEISHU_GROUP_POLICY", prompt: "Group policy (mention or disabled)", placeholder: "mention" },
      { key: "FEISHU_HOME_CHANNEL", prompt: "Home chat ID" },
    ],
  },
  {
    id: "wecom",
    label: "WeCom (Enterprise WeChat)",
    hint: "Tencent's enterprise messenger.",
    envVars: [
      { key: "WECOM_BOT_ID", prompt: "Bot ID" },
      { key: "WECOM_SECRET", prompt: "Secret", password: true },
      { key: "WECOM_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
      { key: "WECOM_HOME_CHANNEL", prompt: "Home chat ID" },
      { key: "WECOM_DM_POLICY", prompt: "DM policy (open / pairing / disabled)", placeholder: "pairing" },
    ],
  },
  {
    id: "wecom_callback",
    label: "WeCom Callback (self-built app)",
    hint: "WeCom self-built app with HTTP callback. Listens on its own port.",
    envVars: [
      { key: "WECOM_CALLBACK_CORP_ID", prompt: "Corp ID" },
      { key: "WECOM_CALLBACK_CORP_SECRET", prompt: "Corp Secret", password: true },
      { key: "WECOM_CALLBACK_AGENT_ID", prompt: "Agent ID" },
      { key: "WECOM_CALLBACK_TOKEN", prompt: "Callback Token", password: true },
      { key: "WECOM_CALLBACK_ENCODING_AES_KEY", prompt: "Encoding AES Key", password: true },
      { key: "WECOM_CALLBACK_PORT", prompt: "Callback server port", placeholder: "8645" },
      { key: "WECOM_CALLBACK_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
    ],
  },
  {
    id: "weixin",
    label: "Weixin / WeChat",
    hint: "Personal WeChat account. QR login in the CLI writes WEIXIN_ACCOUNT_ID + WEIXIN_TOKEN.",
    envVars: [
      { key: "WEIXIN_ACCOUNT_ID", prompt: "Account ID (from QR login)" },
      { key: "WEIXIN_TOKEN", prompt: "Token (from QR login)", password: true },
      { key: "WEIXIN_BASE_URL", prompt: "Base URL (optional)" },
      { key: "WEIXIN_ALLOWED_USERS", prompt: "Allowed user IDs (comma-separated)" },
      { key: "WEIXIN_DM_POLICY", prompt: "DM policy (pairing / open / allowlist / disabled)", placeholder: "pairing" },
      { key: "WEIXIN_GROUP_POLICY", prompt: "Group policy (disabled / open / listed)", placeholder: "disabled" },
      { key: "WEIXIN_GROUP_ALLOWED_USERS", prompt: "Allowed group chat IDs (comma-separated)" },
      { key: "WEIXIN_HOME_CHANNEL", prompt: "Home channel (user ID)" },
    ],
  },
  {
    id: "qqbot",
    label: "QQ Bot",
    hint: "QQ bot account. Use the QQ Open Platform to register.",
    docs: { href: "https://q.qq.com/", label: "QQ Open Platform" },
    envVars: [
      { key: "QQ_APP_ID", prompt: "App ID" },
      { key: "QQ_CLIENT_SECRET", prompt: "App Secret", password: true },
      { key: "QQ_ALLOWED_USERS", prompt: "Allowed user OpenIDs (comma-separated)" },
      { key: "QQBOT_HOME_CHANNEL", prompt: "Home channel OpenID" },
    ],
  },
  {
    id: "webhooks",
    label: "Generic webhooks",
    hint: "Inbound HTTP webhook listener with shared HMAC secret. Run the gateway to expose the endpoint.",
    envVars: [
      { key: "WEBHOOK_PORT", prompt: "Webhook listener port", placeholder: "8644" },
      { key: "WEBHOOK_SECRET", prompt: "Global HMAC secret", password: true },
      { key: "WEBHOOK_ENABLED", prompt: "Enabled (true/false)", placeholder: "true" },
    ],
  },
];

function ExtendedChannelsBrowser() {
  const [envState, setEnvState] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getEnvVars().then((envs) => {
      if (cancelled) return;
      const map: Record<string, boolean> = {};
      for (const c of EXTENDED_CHANNELS) {
        for (const v of c.envVars) {
          map[v.key] = Boolean((envs as Record<string, { is_set?: boolean }>)[v.key]?.is_set);
        }
      }
      setEnvState(map);
    }).catch((e) => !cancelled && setError(errorMessage(e, "Failed to load env vars")));
    return () => { cancelled = true; };
  }, []);

  const toggle = (id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const saveChannel = async (channel: ExtendedChannel) => {
    setSavingId(channel.id);
    setError(null);
    try {
      for (const v of channel.envVars) {
        const value = drafts[v.key]?.trim();
        if (value) {
          await api.setEnvVar(v.key, value);
          setEnvState((m) => ({ ...m, [v.key]: true }));
        }
      }
      setDrafts((prev) => {
        const next = { ...prev };
        for (const v of channel.envVars) delete next[v.key];
        return next;
      });
      setToast(`${channel.label} saved.`);
      setTimeout(() => setToast(null), 1800);
    } catch (e) {
      setError(errorMessage(e, `Save ${channel.label} failed`));
    } finally {
      setSavingId(null);
    }
  };

  const configuredCount = (c: ExtendedChannel) =>
    c.envVars.filter((v) => envState[v.key]).length;

  return (
    <div className="grid gap-2">
      <p className="text-[11.5px] leading-5 text-muted-foreground/80">
        12 more platforms supported by the CLI. Expand any one to paste credentials — saved directly to your <code>.env</code>.
      </p>
      <ul className="grid gap-1.5">
        {EXTENDED_CHANNELS.map((c) => {
          const isOpen = openIds.has(c.id);
          const set = configuredCount(c);
          const total = c.envVars.length;
          const isSaving = savingId === c.id;
          return (
            <li key={c.id} className="rounded-md border border-border/60 bg-background/40">
              <button
                type="button"
                onClick={() => toggle(c.id)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted/30"
              >
                <div className="flex flex-col">
                  <span className="text-[12.5px] font-medium text-foreground">{c.label}</span>
                  <span className="text-[11px] text-muted-foreground/80">{c.hint}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {set > 0 && (
                    <Badge variant={set === total ? "success" : "outline"} className="text-[10.5px]">
                      {set}/{total} set
                    </Badge>
                  )}
                  <span className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
                    {isOpen ? "hide" : "configure"}
                  </span>
                </div>
              </button>
              {isOpen && (
                <div className="border-t border-border/60 px-3 py-3 grid gap-3">
                  {c.docs && (
                    <a href={c.docs.href} target="_blank" rel="noreferrer noopener" className="inline-flex w-fit items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline">
                      {c.docs.label} <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                  {c.envVars.map((v) => (
                    <WizardField
                      key={v.key}
                      label={v.prompt}
                      value={drafts[v.key] ?? ""}
                      onChange={(val) => setDrafts((m) => ({ ...m, [v.key]: val }))}
                      placeholder={envState[v.key] ? "Already set — paste to replace" : (v.placeholder ?? "")}
                      type={v.password ? "password" : "text"}
                      fullWidth
                      hint={envState[v.key] ? `Stored in ${v.key}. Leave blank to keep it.` : undefined}
                    />
                  ))}
                  <div className="flex items-center gap-3">
                    <Button size="sm" onClick={() => saveChannel(c)} disabled={isSaving} className="h-8">
                      {isSaving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
                      Save {c.label}
                    </Button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {toast && <p className="text-[11.5px] text-success">{toast}</p>}
      {error && <p className="text-[11.5px] text-destructive">{error}</p>}
    </div>
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
                onClick={() => slug && !busy && connect(slug)}
                disabled={!slug || busy}
                aria-label={
                  connected
                    ? `Add another ${t.name ?? slug} connection`
                    : `Connect ${t.name ?? slug}`
                }
                className={cn(
                  "flex items-center justify-between gap-2 rounded-md border border-border bg-card/60 px-3 py-1.5 text-left text-[12px] transition-colors",
                  !busy && "hover:border-primary/40 hover:bg-primary/5",
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
                  {connected && (
                    <CheckCircle2 className="h-3 w-3 shrink-0 text-primary" />
                  )}
                </span>
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : connected ? (
                  <span className="text-[10.5px] uppercase tracking-wide text-primary">
                    add another
                  </span>
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
      <div className="space-y-3">
        <TelegramConnectedCard
          draft={draft}
          updateField={updateField}
          onSetupRefresh={onSetupRefresh}
        />
        <div className="rounded-md border border-primary/40 bg-card/60 px-3 py-3 text-[12px] text-foreground">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <span className="font-medium">Paired with {display}.</span>
          </div>
          <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
            The bot will deliver approvals and status messages here. Re-pair
            below if you switch bots.
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
      {draft.telegramSecretPresent && (
        <TelegramConnectedCard
          draft={draft}
          updateField={updateField}
          onSetupRefresh={onSetupRefresh}
        />
      )}
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
// Shows the live Telegram bot identity (via getMe) plus an inline form
// for the rest of _setup_telegram's prompts -- allowlist, home channel,
// unauthorized-DM behavior. Renders whenever a bot token is already in
// env so the operator sees "@gary_bot · Gary" + current access settings
// instead of an empty wizard form.
// ─────────────────────────────────────────────────────────────────────
function TelegramConnectedCard({
  draft,
  updateField,
  onSetupRefresh,
}: {
  draft: AgentSetupDraft;
  updateField: <K extends keyof AgentSetupDraft>(
    key: K,
    value: AgentSetupDraft[K],
  ) => void;
  onSetupRefresh: () => Promise<void> | void;
}) {
  type Status = {
    configured: boolean;
    tokenPreview: string;
    allowedUsers: string;
    homeChannel: string;
    dmBehavior: string;
    allowAllUsers: boolean;
    botId?: number;
    botUsername?: string;
    botName?: string;
    error?: string;
  };
  const [status, setStatus] = useState<Status | null>(null);
  const [editing, setEditing] = useState(false);
  const [allowedUsers, setAllowedUsers] = useState(draft.telegramAllowedUsers);
  // homeChannel and the legacy chatId both map to TELEGRAM_HOME_CHANNEL --
  // fall back to chatId so an older snapshot still pre-fills the input.
  const [homeChannel, setHomeChannel] = useState(
    draft.telegramHomeChannel || draft.telegramChatId,
  );
  const [dmBehavior, setDmBehavior] = useState<string>(draft.telegramDmBehavior || "pair");
  const [allowAll, setAllowAll] = useState(draft.telegramAllowAllUsers);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Snapshot can arrive after this card mounts (gateway restart + refetch).
  // Sync from draft when the input is still empty.
  useEffect(() => {
    if (draft.telegramAllowedUsers && !allowedUsers) {
      setAllowedUsers(draft.telegramAllowedUsers);
    }
    const draftHome = draft.telegramHomeChannel || draft.telegramChatId;
    if (draftHome && !homeChannel) {
      setHomeChannel(draftHome);
    }
    if (draft.telegramDmBehavior && (!dmBehavior || dmBehavior === "pair")) {
      setDmBehavior(draft.telegramDmBehavior);
    }
    if (draft.telegramAllowAllUsers && !allowAll) {
      setAllowAll(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    draft.telegramAllowedUsers,
    draft.telegramHomeChannel,
    draft.telegramChatId,
    draft.telegramDmBehavior,
    draft.telegramAllowAllUsers,
  ]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.getTelegramStatus();
        if (cancelled) return;
        setStatus(resp);
        setAllowedUsers(resp.allowedUsers || draft.telegramAllowedUsers);
        setHomeChannel(
          resp.homeChannel || draft.telegramHomeChannel || draft.telegramChatId,
        );
        setDmBehavior(resp.dmBehavior || draft.telegramDmBehavior || "pair");
        setAllowAll(resp.allowAllUsers || draft.telegramAllowAllUsers);
      } catch (e) {
        if (!cancelled) {
          const raw = errorMessage(e, "Could not fetch bot identity");
          // The new /api/channels/telegram/status route requires a server
          // restart. Before it lands, the SPA catchall returns index.html
          // which trips the JSON parser. Detect that and show a calmer
          // hint instead of "getMe failed".
          const looksLikeStaleServer =
            raw.includes("<!doctype") || raw.includes("Unexpected token '<'");
          setStatus({
            configured: true,
            tokenPreview: draft.telegramSecretPreview,
            allowedUsers: draft.telegramAllowedUsers,
            homeChannel: draft.telegramHomeChannel,
            dmBehavior: draft.telegramDmBehavior,
            allowAllUsers: draft.telegramAllowAllUsers,
            error: looksLikeStaleServer
              ? "Restart elevate web to load the live bot identity probe."
              : raw,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = useCallback(async () => {
    setBusy(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const resp = await api.configureTelegram({
        allowed_users: allowedUsers,
        home_channel: homeChannel,
        dm_behavior: (dmBehavior as "pair" | "ignore" | "open") || "",
        allow_all_users: allowAll,
      });
      setStatus((prev) => (prev ? { ...prev, ...resp } : { configured: true, ...resp }));
      updateField("telegramAllowedUsers", resp.allowedUsers);
      updateField("telegramHomeChannel", resp.homeChannel);
      updateField("telegramDmBehavior", resp.dmBehavior);
      updateField("telegramAllowAllUsers", resp.allowAllUsers);
      if (resp.homeChannel) {
        updateField("telegramChatId", resp.homeChannel);
      }
      setSuccessMsg("Access settings saved.");
      setEditing(false);
      await onSetupRefresh();
    } catch (e) {
      setErrorMsg(errorMessage(e, "Could not save Telegram access"));
    } finally {
      setBusy(false);
    }
  }, [allowedUsers, homeChannel, dmBehavior, allowAll, updateField, onSetupRefresh]);

  const botLabel = status?.botUsername
    ? `@${status.botUsername}${status.botName ? ` · ${status.botName}` : ""}`
    : status?.tokenPreview
      ? `Token ${status.tokenPreview}`
      : "Bot configured";
  const accessLabel = allowAll
    ? "Open access — any Telegram user"
    : allowedUsers
      ? `Allowlist: ${allowedUsers}`
      : dmBehavior === "pair"
        ? "DM pairing on first /start"
        : dmBehavior === "ignore"
          ? "Deny unknown users"
          : "No allowlist configured";

  return (
    <div className="rounded-md border border-primary/40 bg-card/60 px-3 py-3 text-[12px] text-foreground">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <span className="font-medium">Connected bot</span>
          </div>
          <div className="mt-1 font-mono text-[12.5px] text-foreground">
            {botLabel}
          </div>
          <div className="mt-0.5 text-[11.5px] text-muted-foreground">
            Home channel:{" "}
            <span className="font-mono">{homeChannel || "—"}</span>
          </div>
          <div className="text-[11.5px] text-muted-foreground">{accessLabel}</div>
          {status?.error && (
            <div className="mt-1 text-[11px] text-destructive/80">
              getMe failed: {status.error}
            </div>
          )}
        </div>
        <button
          type="button"
          className="shrink-0 text-[11.5px] text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => setEditing((v) => !v)}
        >
          {editing ? "Cancel" : "Edit access"}
        </button>
      </div>

      {editing && (
        <div className="mt-3 space-y-3 border-t border-border/60 pt-3">
          <WizardField
            label="Allowed user IDs"
            value={allowedUsers}
            onChange={setAllowedUsers}
            placeholder="123456789, 987654321"
            fullWidth
            hint="Comma-separated Telegram user IDs. DM @userinfobot to find yours. Leave empty to use DM pairing or open access."
          />
          <WizardField
            label="Home channel"
            value={homeChannel}
            onChange={setHomeChannel}
            placeholder="123456789"
            fullWidth
            hint="Where cron jobs + cross-platform notifications land. For DMs this is your user ID."
          />
          <div className="space-y-1.5">
            <div className="text-[11.5px] font-medium text-foreground">
              When an unknown user DMs the bot:
            </div>
            {[
              { value: "pair", label: "Mint a pairing code (recommended)" },
              { value: "ignore", label: "Ignore them" },
              { value: "open", label: "Allow anyone (also flips GATEWAY_ALLOW_ALL_USERS)" },
            ].map((opt) => (
              <label
                key={opt.value}
                className="flex items-center gap-2 text-[11.5px] text-muted-foreground"
              >
                <input
                  type="radio"
                  name="tg-dm-behavior"
                  checked={dmBehavior === opt.value && !(opt.value !== "open" && allowAll)}
                  onChange={() => {
                    setDmBehavior(opt.value);
                    setAllowAll(opt.value === "open");
                  }}
                />
                {opt.label}
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" onClick={save} disabled={busy} className="h-8">
              {busy ? "Saving…" : "Save access settings"}
            </Button>
            {successMsg && (
              <span className="text-[11.5px] text-muted-foreground">{successMsg}</span>
            )}
            {errorMsg && (
              <span className="text-[11.5px] text-destructive">{errorMsg}</span>
            )}
          </div>
        </div>
      )}
      {!editing && successMsg && (
        <p className="mt-2 text-[11.5px] text-muted-foreground">{successMsg}</p>
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
  // If BlueBubbles is already wired in env, default to that mode + pre-fill.
  const bbAlreadyWired =
    Boolean(draft.bluebubblesServerUrl) && draft.bluebubblesSecretPresent;
  const [mode, setMode] = useState<"local" | "bluebubbles">(
    bbAlreadyWired ? "bluebubbles" : "local",
  );
  const [serverUrl, setServerUrl] = useState(draft.bluebubblesServerUrl);
  const [password, setPassword] = useState("");
  const [allowedUsers, setAllowedUsers] = useState(draft.bluebubblesAllowedUsers);
  const [homeChannel, setHomeChannel] = useState(draft.bluebubblesHomeChannel);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(
    bbAlreadyWired
      ? `Connected via BlueBubbles. Password: ${draft.bluebubblesSecretPreview || "(set)"}`
      : null,
  );

  // The snapshot can arrive AFTER this panel mounted (e.g. user opened
  // the wizard, we then restarted the gateway, snapshot refreshed). Sync
  // state from the draft when the operator hasn't typed something
  // different -- prevents the inputs from looking empty even though the
  // env values are sitting right there in the draft.
  useEffect(() => {
    if (draft.bluebubblesServerUrl && !serverUrl) {
      setServerUrl(draft.bluebubblesServerUrl);
    }
    if (draft.bluebubblesAllowedUsers && !allowedUsers) {
      setAllowedUsers(draft.bluebubblesAllowedUsers);
    }
    if (draft.bluebubblesHomeChannel && !homeChannel) {
      setHomeChannel(draft.bluebubblesHomeChannel);
    }
    if (
      bbAlreadyWired &&
      mode === "local" &&
      !serverUrl &&
      !allowedUsers &&
      !homeChannel
    ) {
      setMode("bluebubbles");
    }
    if (bbAlreadyWired && !successMsg && !errorMsg && password === "") {
      setSuccessMsg(
        `Connected via BlueBubbles. Password: ${draft.bluebubblesSecretPreview || "(set)"}`,
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    draft.bluebubblesServerUrl,
    draft.bluebubblesAllowedUsers,
    draft.bluebubblesHomeChannel,
    draft.bluebubblesSecretPresent,
    draft.bluebubblesSecretPreview,
  ]);

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
            . Grant Full Disk Access to Terminal/Elevation (System Settings →
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
        WhatsApp bridge script not found. This Elevation install ships it at
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
