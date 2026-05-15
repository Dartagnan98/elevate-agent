import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { FullWindowAurora } from "@/components/FullWindowAurora";
import type {
  AdminSetupItemStatus,
  AgentSetupItem,
  AgentSetupItemUpdate,
  AgentSetupSnapshot,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  AgentOnboardingWelcome,
  AgentOnboardingWizard,
} from "./wizard";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

export const SUBAGENT_KEYS = ["jimmy", "gary", "nina", "ricky", "qc"] as const;
export const SUBAGENT_LABELS: Record<string, { label: string; role: string }> = {
  jimmy: { label: "Jimmy", role: "Orchestrator" },
  gary: { label: "Gary", role: "Ads strategist" },
  nina: { label: "Nina", role: "Analyst / reporting" },
  ricky: { label: "Ricky", role: "Copywriter" },
  qc: { label: "QC", role: "Reviewer" },
};
export const AGENT_CHANNEL_TYPES = [
  { key: "telegram", label: "Telegram chat ids", placeholder: "-1001234567890" },
  { key: "imessage", label: "iMessage handles", placeholder: "+15551234567" },
  { key: "slack", label: "Slack channels", placeholder: "#ops" },
  { key: "discord", label: "Discord channel ids", placeholder: "987654321098765432" },
  { key: "whatsapp", label: "WhatsApp numbers", placeholder: "+15551234567" },
] as const;

function emptyAgentChannels(): Record<string, Record<string, string[]>> {
  const out: Record<string, Record<string, string[]>> = {};
  for (const agent of SUBAGENT_KEYS) {
    const slots: Record<string, string[]> = {};
    for (const ch of AGENT_CHANNEL_TYPES) slots[ch.key] = [];
    out[agent] = slots;
  }
  return out;
}

function parseAgentChannels(raw: unknown): Record<string, Record<string, string[]>> {
  const out = emptyAgentChannels();
  if (!raw || typeof raw !== "object") return out;
  const routing = (raw as { routing?: unknown }).routing;
  if (!routing || typeof routing !== "object") return out;
  for (const agent of SUBAGENT_KEYS) {
    const agentSlots = (routing as Record<string, unknown>)[agent];
    if (!agentSlots || typeof agentSlots !== "object") continue;
    for (const ch of AGENT_CHANNEL_TYPES) {
      const list = (agentSlots as Record<string, unknown>)[ch.key];
      if (Array.isArray(list)) {
        out[agent][ch.key] = list.map((v) => String(v ?? "").trim()).filter(Boolean);
      }
    }
  }
  return out;
}

function agentChannelsToValue(
  channels: Record<string, Record<string, string[]>>,
): { routing: Record<string, Record<string, string[]>> } {
  const routing: Record<string, Record<string, string[]>> = {};
  for (const agent of SUBAGENT_KEYS) {
    const slots: Record<string, string[]> = {};
    for (const ch of AGENT_CHANNEL_TYPES) {
      const list = channels[agent]?.[ch.key] ?? [];
      const cleaned = list.map((v) => v.trim()).filter(Boolean);
      if (cleaned.length) slots[ch.key] = cleaned;
    }
    if (Object.keys(slots).length) routing[agent] = slots;
  }
  return { routing };
}

function agentChannelsHasAny(channels: Record<string, Record<string, string[]>>): boolean {
  for (const agent of SUBAGENT_KEYS) {
    for (const ch of AGENT_CHANNEL_TYPES) {
      if ((channels[agent]?.[ch.key] ?? []).some((v) => v.trim())) return true;
    }
  }
  return false;
}

export type AgentSetupDraft = {
  primaryProvider: string;
  primaryModel: string;
  primaryApiKey: string;
  embeddingProvider: string;
  embeddingModel: string;
  embeddingApiKey: string;
  embeddingShareKey: boolean;
  imageProvider: string;
  imageApiKey: string;
  memoryProvider: string;
  memorySupabaseUrl: string;
  memorySupabaseKey: string;
  composioApiKey: string;
  composioWorkspace: string;
  cliEnabled: boolean;
  telegramBotToken: string;
  telegramChatId: string;
  imessageEnabled: boolean;
  imessageHandle: string;
  discordBotToken: string;
  discordChannelId: string;
  whatsappProvider: string;
  whatsappToken: string;
  whatsappPhoneId: string;
  slackWebhookUrl: string;
  slackChannel: string;
  outboundImessageEnabled: boolean;
  outboundImessageSenderHandle: string;
  subagentsEnabled: boolean;
  subagentsPack: string;
  agentChannels: Record<string, Record<string, string[]>>;
  primarySecretPresent: boolean;
  primarySecretPreview: string;
  embeddingSecretPresent: boolean;
  embeddingSecretPreview: string;
  imageSecretPresent: boolean;
  imageSecretPreview: string;
  memorySecretPresent: boolean;
  memorySecretPreview: string;
  composioSecretPresent: boolean;
  composioSecretPreview: string;
  telegramSecretPresent: boolean;
  telegramSecretPreview: string;
};

export function draftFromSnapshot(snapshot: AgentSetupSnapshot): AgentSetupDraft {
  const byKey = new Map(snapshot.items.map((it) => [it.key, it]));
  const primaryVal = (byKey.get("model_primary")?.value ?? {}) as Record<string, unknown>;
  const embeddingVal = (byKey.get("model_embedding")?.value ?? {}) as Record<string, unknown>;
  const imageVal = (byKey.get("model_image")?.value ?? {}) as Record<string, unknown>;
  const memoryVal = (byKey.get("memory_store")?.value ?? {}) as Record<string, unknown>;
  const composioVal = (byKey.get("composio_workspace")?.value ?? {}) as Record<string, unknown>;
  const cliItem = byKey.get("operator_channel_cli");
  const tgVal = (byKey.get("operator_channel_telegram")?.value ?? {}) as Record<string, unknown>;
  const imessageItem = byKey.get("operator_channel_imessage");
  const imessageVal = (imessageItem?.value ?? {}) as Record<string, unknown>;
  const discordVal = (byKey.get("operator_channel_discord")?.value ?? {}) as Record<string, unknown>;
  const whatsappVal = (byKey.get("operator_channel_whatsapp")?.value ?? {}) as Record<string, unknown>;
  const slackVal = (byKey.get("operator_channel_slack")?.value ?? {}) as Record<string, unknown>;
  const outImessageItem = byKey.get("outbound_imessage");
  const outImessageVal = (outImessageItem?.value ?? {}) as Record<string, unknown>;
  const subagentsItem = byKey.get("subagents_pack");
  const subagentsVal = (subagentsItem?.value ?? {}) as Record<string, unknown>;
  const agentChannelsItem = byKey.get("agent_channel_routing");
  return {
    primaryProvider: String(byKey.get("model_primary")?.provider ?? ""),
    primaryModel: String(primaryVal.model ?? ""),
    primaryApiKey: String(primaryVal.apiKey ?? ""),
    embeddingProvider: String(byKey.get("model_embedding")?.provider ?? ""),
    embeddingModel: String(embeddingVal.model ?? ""),
    embeddingApiKey: String(embeddingVal.apiKey ?? ""),
    embeddingShareKey: Boolean(embeddingVal.sharesPrimaryKey ?? true),
    imageProvider: String(byKey.get("model_image")?.provider ?? ""),
    imageApiKey: String(imageVal.apiKey ?? ""),
    memoryProvider: String(byKey.get("memory_store")?.provider ?? "sqlite_local"),
    memorySupabaseUrl: String(memoryVal.supabaseUrl ?? ""),
    memorySupabaseKey: String(memoryVal.supabaseKey ?? ""),
    composioApiKey: String(composioVal.apiKey ?? ""),
    composioWorkspace: String(composioVal.workspace ?? ""),
    cliEnabled: cliItem ? cliItem.status === "configured" : true,
    telegramBotToken: String(tgVal.botToken ?? ""),
    telegramChatId: String(tgVal.chatId ?? ""),
    imessageEnabled: imessageItem ? imessageItem.status === "configured" : false,
    imessageHandle: String(imessageVal.handle ?? ""),
    discordBotToken: String(discordVal.botToken ?? ""),
    discordChannelId: String(discordVal.channelId ?? ""),
    whatsappProvider: String(whatsappVal.provider ?? ""),
    whatsappToken: String(whatsappVal.token ?? ""),
    whatsappPhoneId: String(whatsappVal.phoneId ?? ""),
    slackWebhookUrl: String(slackVal.webhookUrl ?? ""),
    slackChannel: String(slackVal.channel ?? ""),
    outboundImessageEnabled: outImessageItem ? outImessageItem.status === "configured" : false,
    outboundImessageSenderHandle: String(outImessageVal.senderHandle ?? ""),
    subagentsEnabled: subagentsItem ? subagentsItem.status === "configured" : false,
    subagentsPack: String(subagentsVal.pack ?? "cortextos_default"),
    agentChannels: parseAgentChannels(agentChannelsItem?.value),
    primarySecretPresent: Boolean(primaryVal.secretPresent),
    primarySecretPreview: String(primaryVal.secretPreview ?? ""),
    embeddingSecretPresent: Boolean(embeddingVal.secretPresent),
    embeddingSecretPreview: String(embeddingVal.secretPreview ?? ""),
    imageSecretPresent: Boolean(imageVal.secretPresent),
    imageSecretPreview: String(imageVal.secretPreview ?? ""),
    memorySecretPresent: Boolean(memoryVal.secretPresent),
    memorySecretPreview: String(memoryVal.secretPreview ?? ""),
    composioSecretPresent: Boolean(composioVal.secretPresent),
    composioSecretPreview: String(composioVal.secretPreview ?? ""),
    telegramSecretPresent: Boolean(tgVal.secretPresent),
    telegramSecretPreview: String(tgVal.secretPreview ?? ""),
  };
}

export function buildItemUpdates(draft: AgentSetupDraft): AgentSetupItemUpdate[] {
  const primaryHasKey = Boolean(draft.primaryApiKey.trim()) || draft.primarySecretPresent;
  const primaryReady = Boolean(
    draft.primaryProvider.trim() && primaryHasKey && draft.primaryModel.trim(),
  );
  const embeddingHasKey = draft.embeddingShareKey
    ? primaryHasKey
    : Boolean(draft.embeddingApiKey.trim()) || draft.embeddingSecretPresent;
  const embeddingReady = Boolean(
    draft.embeddingProvider.trim() && draft.embeddingModel.trim() && embeddingHasKey,
  );
  const imageReady = Boolean(
    draft.imageProvider.trim() && (draft.imageApiKey.trim() || draft.imageSecretPresent),
  );
  const memoryReady = ((): boolean => {
    if (draft.memoryProvider === "supabase") {
      const hasKey = Boolean(draft.memorySupabaseKey.trim()) || draft.memorySecretPresent;
      return Boolean(draft.memorySupabaseUrl.trim() && hasKey);
    }
    return Boolean(draft.memoryProvider.trim());
  })();
  const composioReady = Boolean(draft.composioApiKey.trim()) || draft.composioSecretPresent;
  const telegramReady =
    (Boolean(draft.telegramBotToken.trim()) || draft.telegramSecretPresent) &&
    Boolean(draft.telegramChatId.trim());
  const imessageReady = draft.imessageEnabled;
  const discordReady = Boolean(draft.discordBotToken.trim() && draft.discordChannelId.trim());
  const whatsappReady = Boolean(
    draft.whatsappProvider.trim() && draft.whatsappToken.trim(),
  );
  const slackReady = Boolean(draft.slackWebhookUrl.trim());
  const outImessageReady = draft.outboundImessageEnabled;

  return [
    {
      key: "model_primary",
      status: (primaryReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.primaryProvider.trim() || null,
      value: {
        model: draft.primaryModel.trim(),
        apiKey: draft.primaryApiKey,
        usesEnvSecret: !draft.primaryApiKey.trim() && draft.primarySecretPresent,
      },
    },
    {
      key: "model_embedding",
      status: (embeddingReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.embeddingProvider.trim() || null,
      value: {
        model: draft.embeddingModel.trim(),
        apiKey: draft.embeddingShareKey ? "" : draft.embeddingApiKey,
        sharesPrimaryKey: draft.embeddingShareKey,
        usesEnvSecret:
          !draft.embeddingShareKey &&
          !draft.embeddingApiKey.trim() &&
          draft.embeddingSecretPresent,
      },
    },
    {
      key: "model_image",
      status: (imageReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.imageProvider.trim() || null,
      value: {
        apiKey: draft.imageApiKey,
        usesEnvSecret: !draft.imageApiKey.trim() && draft.imageSecretPresent,
      },
    },
    {
      key: "memory_store",
      status: (memoryReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.memoryProvider.trim() || null,
      value: {
        supabaseUrl: draft.memorySupabaseUrl.trim(),
        supabaseKey: draft.memorySupabaseKey,
        usesEnvSecret:
          draft.memoryProvider === "supabase" &&
          !draft.memorySupabaseKey.trim() &&
          draft.memorySecretPresent,
      },
    },
    {
      key: "composio_workspace",
      status: (composioReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: composioReady ? "composio" : null,
      value: {
        apiKey: draft.composioApiKey,
        workspace: draft.composioWorkspace.trim(),
        usesEnvSecret: !draft.composioApiKey.trim() && draft.composioSecretPresent,
      },
    },
    {
      key: "operator_channel_cli",
      status: (draft.cliEnabled ? "configured" : "skipped") as AdminSetupItemStatus,
      provider: draft.cliEnabled ? "elevate-cli" : null,
      value: { enabled: draft.cliEnabled },
    },
    {
      key: "operator_channel_telegram",
      status: (telegramReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: telegramReady ? "telegram" : null,
      value: {
        botToken: draft.telegramBotToken,
        chatId: draft.telegramChatId.trim(),
        usesEnvSecret: !draft.telegramBotToken.trim() && draft.telegramSecretPresent,
      },
    },
    {
      key: "operator_channel_imessage",
      status: (imessageReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: imessageReady ? "apple-messages" : null,
      value: {
        enabled: draft.imessageEnabled,
        handle: draft.imessageHandle.trim(),
      },
    },
    {
      key: "operator_channel_discord",
      status: (discordReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: discordReady ? "discord" : null,
      value: {
        botToken: draft.discordBotToken,
        channelId: draft.discordChannelId.trim(),
      },
    },
    {
      key: "operator_channel_whatsapp",
      status: (whatsappReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: whatsappReady ? draft.whatsappProvider.trim() : null,
      value: {
        provider: draft.whatsappProvider.trim(),
        token: draft.whatsappToken,
        phoneId: draft.whatsappPhoneId.trim(),
      },
    },
    {
      key: "operator_channel_slack",
      status: (slackReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: slackReady ? "slack" : null,
      value: {
        webhookUrl: draft.slackWebhookUrl.trim(),
        channel: draft.slackChannel.trim(),
      },
    },
    {
      key: "outbound_imessage",
      status: (outImessageReady ? "configured" : "skipped") as AdminSetupItemStatus,
      provider: outImessageReady ? "apple-messages" : null,
      value: {
        enabled: draft.outboundImessageEnabled,
        senderHandle: draft.outboundImessageSenderHandle.trim(),
      },
    },
    {
      key: "subagents_pack",
      status: (draft.subagentsEnabled ? "configured" : "skipped") as AdminSetupItemStatus,
      provider: draft.subagentsEnabled ? draft.subagentsPack || "cortextos_default" : null,
      value: {
        pack: draft.subagentsPack,
        enabled: draft.subagentsEnabled,
      },
    },
    {
      key: "agent_channel_routing",
      status: (agentChannelsHasAny(draft.agentChannels)
        ? "configured"
        : "skipped") as AdminSetupItemStatus,
      provider: agentChannelsHasAny(draft.agentChannels) ? "elevate" : null,
      value: agentChannelsToValue(draft.agentChannels),
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

function ItemCard({
  title,
  description,
  status,
  required,
  children,
}: {
  title: string;
  description: string;
  status: AdminSetupItemStatus;
  required?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">
            {title}
            {required && (
              <span className="ml-2 inline-flex items-center rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
                Required
              </span>
            )}
          </h3>
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
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  hint?: string;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        spellCheck={type === "password" ? false : undefined}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {hint && (
        <span className="mt-1 block text-[10.5px] leading-4 text-muted-foreground/80">{hint}</span>
      )}
    </label>
  );
}

function SelectRow({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      >
        <option value="">— pick one —</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AgentSetupLaunch({
  setup,
  onSetupUpdated,
  forceOnboarding = false,
  onForceOnboardingDone,
}: {
  setup: AgentSetupSnapshot;
  onSetupUpdated: (next: AgentSetupSnapshot) => void;
  forceOnboarding?: boolean;
  onForceOnboardingDone?: () => void;
}) {
  const [draft, setDraft] = useState<AgentSetupDraft>(() => draftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(draftFromSnapshot(setup));
  }, [setup]);

  const byKey = useMemo(
    () => new Map(setup.items.map((item: AgentSetupItem) => [item.key, item])),
    [setup.items],
  );
  const primaryItem = byKey.get("model_primary");
  const embeddingItem = byKey.get("model_embedding");
  const imageItem = byKey.get("model_image");
  const memoryItem = byKey.get("memory_store");
  const composioItem = byKey.get("composio_workspace");
  const telegramItem = byKey.get("operator_channel_telegram");
  const slackItem = byKey.get("operator_channel_slack");
  const subagentsItem = byKey.get("subagents_pack");
  const agentChannelRoutingItem = byKey.get("agent_channel_routing");

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateAgentSetup(buildItemUpdates(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.complete
          ? "Saved. Required items are all in — hit 'Mark complete' to lift the gate."
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
      await api.updateAgentSetup(buildItemUpdates(draft));
      const completed = await api.completeAgentSetup();
      onSetupUpdated(completed);
      onForceOnboardingDone?.();
    } catch (err) {
      setError(errorMessage(err, "Could not complete setup"));
    } finally {
      setCompleting(false);
    }
  }, [draft, onSetupUpdated, onForceOnboardingDone]);

  const updateField = useCallback(
    <K extends keyof AgentSetupDraft>(key: K, value: AgentSetupDraft[K]) => {
      setDraft((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const updateAgentChannel = useCallback(
    (agent: string, channel: string, list: string[]) => {
      setDraft((prev) => {
        const nextChannels: Record<string, Record<string, string[]>> = { ...prev.agentChannels };
        const agentSlots: Record<string, string[]> = { ...(nextChannels[agent] ?? {}) };
        agentSlots[channel] = list;
        nextChannels[agent] = agentSlots;
        return { ...prev, agentChannels: nextChannels };
      });
    },
    [],
  );

  const pct = setup.completionPct ?? 0;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Agent onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              Bring the runtime up. Required: primary LLM, embedding model, memory store. Everything
              else (image gen, Composio, operator channels, sub-agents) is opt-in and can be added
              later. The database schema is created automatically on completion; backend connectors
              backfill once you hit launch.
            </p>
          </div>
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
        title="Primary LLM"
        description="The model the agent thinks with. Anthropic Claude or OpenAI GPT are the proven defaults."
        status={primaryItem?.status ?? "missing"}
        required
      >
        <SelectRow
          label="Provider"
          value={draft.primaryProvider}
          onChange={(v) => updateField("primaryProvider", v)}
          options={[
            { value: "anthropic", label: "Anthropic (Claude)" },
            { value: "openai", label: "OpenAI" },
            { value: "openrouter", label: "OpenRouter" },
            { value: "azure_openai", label: "Azure OpenAI" },
          ]}
        />
        <FieldRow
          label="Model ID"
          value={draft.primaryModel}
          onChange={(v) => updateField("primaryModel", v)}
          placeholder="claude-opus-4-7  or  gpt-4-turbo"
        />
        <FieldRow
          label="API key"
          value={draft.primaryApiKey}
          onChange={(v) => updateField("primaryApiKey", v)}
          placeholder={
            draft.primarySecretPresent && !draft.primaryApiKey
              ? `Already set — ${draft.primarySecretPreview} (paste to replace)`
              : "sk-ant-…  or  sk-…"
          }
          type="password"
          hint={
            draft.primarySecretPresent && !draft.primaryApiKey
              ? "Detected from environment. Leave blank to keep using it."
              : undefined
          }
        />
      </ItemCard>

      <ItemCard
        title="Embedding model"
        description="Powers memory recall + semantic search. Usually the same provider as your primary LLM."
        status={embeddingItem?.status ?? "missing"}
        required
      >
        <SelectRow
          label="Provider"
          value={draft.embeddingProvider}
          onChange={(v) => updateField("embeddingProvider", v)}
          options={[
            { value: "openai", label: "OpenAI" },
            { value: "voyage", label: "Voyage AI" },
            { value: "cohere", label: "Cohere" },
            { value: "local", label: "Local (sentence-transformers)" },
          ]}
        />
        <FieldRow
          label="Model ID"
          value={draft.embeddingModel}
          onChange={(v) => updateField("embeddingModel", v)}
          placeholder="text-embedding-3-large  or  voyage-3"
        />
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.embeddingShareKey}
            onChange={(e) => updateField("embeddingShareKey", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Share the primary LLM key
        </label>
        {!draft.embeddingShareKey && (
          <FieldRow
            label="Embedding API key"
            value={draft.embeddingApiKey}
            onChange={(v) => updateField("embeddingApiKey", v)}
            placeholder={
              draft.embeddingSecretPresent && !draft.embeddingApiKey
                ? `Already set — ${draft.embeddingSecretPreview} (paste to replace)`
                : "sk-…"
            }
            type="password"
            hint={
              draft.embeddingSecretPresent && !draft.embeddingApiKey
                ? "Detected from environment. Leave blank to keep using it."
                : undefined
            }
          />
        )}
      </ItemCard>

      <ItemCard
        title="Memory store"
        description="Where long-term memory lives. Local SQLite is zero-config. Supabase if you want shared multi-device memory."
        status={memoryItem?.status ?? "missing"}
        required
      >
        <SelectRow
          label="Provider"
          value={draft.memoryProvider}
          onChange={(v) => updateField("memoryProvider", v)}
          options={[
            { value: "sqlite_local", label: "Local SQLite (recommended)" },
            { value: "supabase", label: "Supabase (shared)" },
          ]}
        />
        {draft.memoryProvider === "supabase" && (
          <>
            <FieldRow
              label="Supabase project URL"
              value={draft.memorySupabaseUrl}
              onChange={(v) => updateField("memorySupabaseUrl", v)}
              placeholder="https://xxx.supabase.co"
            />
            <FieldRow
              label="Supabase service-role key"
              value={draft.memorySupabaseKey}
              onChange={(v) => updateField("memorySupabaseKey", v)}
              placeholder={
                draft.memorySecretPresent && !draft.memorySupabaseKey
                  ? `Already set — ${draft.memorySecretPreview} (paste to replace)`
                  : "eyJhbGc…"
              }
              type="password"
              hint={
                draft.memorySecretPresent && !draft.memorySupabaseKey
                  ? "Detected from environment. Leave blank to keep using it."
                  : undefined
              }
            />
          </>
        )}
        <p className="text-[10.5px] text-muted-foreground">
          On Mark complete, Elevate creates the operational tables (contacts, conversations, deals,
          tasks, etc.) automatically via migrations.
        </p>
      </ItemCard>

      <ItemCard
        title="Image generation (Nano Banana)"
        description="Optional. The Nano Banana Gemini-CLI extension ships pre-installed — drop in a Gemini API key from AI Studio and /generate, /edit, /restore, /icon, /pattern, /story, /diagram light up. Other providers (OpenAI Images, Replicate) also supported."
        status={imageItem?.status ?? "missing"}
      >
        <SelectRow
          label="Provider"
          value={draft.imageProvider}
          onChange={(v) => updateField("imageProvider", v)}
          options={[
            { value: "nano_banana", label: "Nano Banana (Gemini CLI extension)" },
            { value: "openai_images", label: "OpenAI Images (DALL-E)" },
            { value: "replicate", label: "Replicate" },
          ]}
        />
        <FieldRow
          label={
            draft.imageProvider === "nano_banana"
              ? "Gemini API key (NANOBANANA_API_KEY)"
              : "API key"
          }
          value={draft.imageApiKey}
          onChange={(v) => updateField("imageApiKey", v)}
          placeholder={
            draft.imageSecretPresent && !draft.imageApiKey
              ? `Already set — ${draft.imageSecretPreview} (paste to replace)`
              : draft.imageProvider === "nano_banana"
                ? "AIzaSy…  (from AI Studio)"
                : "sk-…"
          }
          type="password"
          hint={
            draft.imageSecretPresent && !draft.imageApiKey
              ? "Detected from environment. Leave blank to keep using it."
              : undefined
          }
        />
        {draft.imageProvider === "nano_banana" && (
          <a
            href="https://aistudio.google.com/apikey"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
          >
            Get a Gemini API key from AI Studio <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </ItemCard>

      <ItemCard
        title="Composio workspace"
        description="Optional. Pre-wired toolkit for Gmail, Calendar, Slack, GitHub, Notion, 100+ more. Skip if you don't use Composio."
        status={composioItem?.status ?? "missing"}
      >
        <FieldRow
          label="Composio API key"
          value={draft.composioApiKey}
          onChange={(v) => updateField("composioApiKey", v)}
          placeholder={
            draft.composioSecretPresent && !draft.composioApiKey
              ? `Already set — ${draft.composioSecretPreview} (paste to replace)`
              : "csk_…"
          }
          type="password"
          hint={
            draft.composioSecretPresent && !draft.composioApiKey
              ? "Detected from environment. Leave blank to keep using it."
              : undefined
          }
        />
        <FieldRow
          label="Workspace (optional)"
          value={draft.composioWorkspace}
          onChange={(v) => updateField("composioWorkspace", v)}
          placeholder="default"
        />
        <a
          href="https://app.composio.dev/"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          Open Composio dashboard <ExternalLink className="h-3 w-3" />
        </a>
      </ItemCard>

      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-[11.5px] text-muted-foreground">
        <span className="font-medium text-foreground">Operator channels.</span> Where the agent
        pings you for approvals and status. Optional — pick one (or both) if you want push.
      </div>

      <ItemCard
        title="Telegram operator channel"
        description="Bot token + chat id. Push approvals + status arrive to your Telegram."
        status={telegramItem?.status ?? "missing"}
      >
        <FieldRow
          label="Bot token (from @BotFather)"
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
        <FieldRow
          label="Chat id"
          value={draft.telegramChatId}
          onChange={(v) => updateField("telegramChatId", v)}
          placeholder="-1001234567890  or  987654321"
        />
        <a
          href="https://t.me/BotFather"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          Open @BotFather <ExternalLink className="h-3 w-3" />
        </a>
      </ItemCard>

      <ItemCard
        title="Slack operator channel"
        description="Incoming webhook URL + target channel. Alternative to Telegram."
        status={slackItem?.status ?? "missing"}
      >
        <FieldRow
          label="Incoming webhook URL"
          value={draft.slackWebhookUrl}
          onChange={(v) => updateField("slackWebhookUrl", v)}
          placeholder="https://hooks.slack.com/services/T…/B…/…"
        />
        <FieldRow
          label="Channel (optional override)"
          value={draft.slackChannel}
          onChange={(v) => updateField("slackChannel", v)}
          placeholder="#elevate-ops"
        />
      </ItemCard>

      <ItemCard
        title="Sub-agents pack"
        description="Optional. Spin up the cortextos PTY specialists (Jimmy, Gary, Nina, Ricky, QC). Off by default — turn on if you want a council."
        status={subagentsItem?.status ?? "missing"}
      >
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.subagentsEnabled}
            onChange={(e) => updateField("subagentsEnabled", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Enable sub-agents
        </label>
        {draft.subagentsEnabled && (
          <SelectRow
            label="Pack"
            value={draft.subagentsPack}
            onChange={(v) => updateField("subagentsPack", v)}
            options={[
              { value: "cortextos_default", label: "cortextos default (Jimmy + 4 specialists)" },
              { value: "cortextos_minimal", label: "cortextos minimal (Jimmy only)" },
            ]}
          />
        )}
      </ItemCard>

      <ItemCard
        title="Per-agent channel routing"
        description="Optional. Wire each sub-agent to one or more channels. Multiple entries per slot are allowed and the same channels work for inbound and outbound. No fallback — an agent with nothing wired only acts when another agent hands work to it."
        status={agentChannelRoutingItem?.status ?? "missing"}
      >
        <div className="space-y-3">
          {SUBAGENT_KEYS.map((agent) => {
            const slots = draft.agentChannels[agent] ?? {};
            const meta = SUBAGENT_LABELS[agent];
            return (
              <div
                key={agent}
                className="rounded-md border border-border bg-background/40 p-3"
              >
                <header className="mb-2 flex items-baseline justify-between gap-2">
                  <div>
                    <h4 className="text-[12.5px] font-semibold text-foreground">
                      {meta?.label ?? agent}
                    </h4>
                    <p className="text-[10.5px] text-muted-foreground">
                      {meta?.role ?? ""}
                    </p>
                  </div>
                </header>
                <div className="space-y-2">
                  {AGENT_CHANNEL_TYPES.map((ch) => {
                    const list = slots[ch.key] ?? [];
                    return (
                      <div key={ch.key}>
                        <div className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground/80">
                          {ch.label}
                        </div>
                        <div className="space-y-1">
                          {list.map((entry, idx) => (
                            <div key={idx} className="flex items-center gap-1">
                              <input
                                type="text"
                                value={entry}
                                onChange={(e) => {
                                  const next = [...list];
                                  next[idx] = e.target.value;
                                  updateAgentChannel(agent, ch.key, next);
                                }}
                                placeholder={ch.placeholder}
                                className="w-full rounded-md border border-border bg-background px-2 py-1 text-[12px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                              />
                              <button
                                type="button"
                                aria-label="Remove entry"
                                onClick={() => {
                                  const next = list.filter((_, i) => i !== idx);
                                  updateAgentChannel(agent, ch.key, next);
                                }}
                                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:text-foreground"
                              >
                                ×
                              </button>
                            </div>
                          ))}
                          <button
                            type="button"
                            onClick={() => updateAgentChannel(agent, ch.key, [...list, ""])}
                            className="text-[11px] text-primary underline-offset-2 hover:underline"
                          >
                            + Add {ch.label.toLowerCase()}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </ItemCard>

      <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card/95 px-3 py-2 backdrop-blur">
        <div className="text-[11.5px] text-muted-foreground">
          {setup.complete
            ? "All required items connected."
            : `${setup.missingRequiredKeys.length} required item(s) outstanding.`}
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
            Mark complete & create databases
          </Button>
        </div>
      </div>
    </div>
  );
}

export function useAgentSetup(): {
  loading: boolean;
  setup: AgentSetupSnapshot | null;
  error: string | null;
  setSetup: (next: AgentSetupSnapshot) => void;
  refresh: () => Promise<void>;
} {
  const [setup, setSetup] = useState<AgentSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snap = await api.getAgentSetup();
      setSetup(snap);
    } catch (err) {
      setError(errorMessage(err, "Could not load agent setup"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, setup, error, setSetup, refresh };
}

type WizardPhase = "welcome" | "wizard" | "form";

export function AgentOnboardingPage() {
  const { loading, setup, error, setSetup, refresh } = useAgentSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const runFlag = searchParams.get("run") === "1";
  const [wizardPhase, setWizardPhase] = useState<WizardPhase>(
    runFlag ? "welcome" : "form",
  );

  useEffect(() => {
    if (runFlag && wizardPhase === "form") {
      setWizardPhase("welcome");
    }
  }, [runFlag, wizardPhase]);

  const clearRunFlag = useCallback(() => {
    if (!searchParams.has("run")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("run");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const onReset = useCallback(async () => {
    setResetting(true);
    setResetError(null);
    try {
      const reopened = await api.resetAgentSetup();
      setSetup(reopened);
      setForceOnboarding(true);
      setWizardPhase("welcome");
    } catch (err) {
      setResetError(errorMessage(err, "Could not re-open onboarding"));
    } finally {
      setResetting(false);
    }
  }, [setSetup]);

  if (loading) {
    return (
      <FullWindowAurora
        label="Agent · onboarding"
        title="Loading your setup"
        subtitle="Reading existing connectors, memory wiring, and outbound channels."
      />
    );
  }
  if (error) {
    return (
      <div className="m-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-[12px] text-warning">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
        {error}
        <Button variant="outline" size="sm" className="ml-3" onClick={() => void refresh()}>
          Retry
        </Button>
      </div>
    );
  }
  if (!setup) return null;

  const showOnboarding = !setup.complete || forceOnboarding;

  if (showOnboarding && wizardPhase === "welcome") {
    return (
      <AgentOnboardingWelcome onContinue={() => setWizardPhase("wizard")} />
    );
  }
  if (showOnboarding && wizardPhase === "wizard") {
    return (
      <AgentOnboardingWizard
        setup={setup}
        onSetupUpdated={setSetup}
        onFinish={() => {
          setWizardPhase("form");
          setForceOnboarding(false);
          clearRunFlag();
        }}
      />
    );
  }

  return (
    <div className="flex flex-col">
      <div className="border-b border-border bg-background/95 px-4 py-2 backdrop-blur">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2">
          <div className="text-[12px] text-muted-foreground">
            {setup.complete
              ? `Agent runtime up. Completed ${
                  setup.completedAt ? new Date(setup.completedAt).toLocaleString() : "earlier"
                }.`
              : `${setup.completedRequiredCount}/${setup.requiredCount} required items connected.`}
          </div>
          <div className="flex items-center gap-2">
            {setup.complete && !forceOnboarding && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setForceOnboarding(true);
                  setWizardPhase("welcome");
                }}
              >
                Re-run onboarding
              </Button>
            )}
            {(setup.complete || forceOnboarding) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void onReset()}
                disabled={resetting}
              >
                {resetting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                Re-open gate
              </Button>
            )}
          </div>
        </div>
        {resetError && (
          <div className="mx-auto mt-2 max-w-3xl rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-[11.5px] text-warning">
            <AlertTriangle className="mr-1 inline h-3 w-3" />
            {resetError}
          </div>
        )}
      </div>

      <AgentSetupLaunch
        setup={setup}
        onSetupUpdated={setSetup}
        forceOnboarding={forceOnboarding}
        onForceOnboardingDone={() => setForceOnboarding(false)}
      />

    </div>
  );
}

export default AgentOnboardingPage;
