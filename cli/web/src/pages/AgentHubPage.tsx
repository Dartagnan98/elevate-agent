import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  Brain,
  KeyRound,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  RotateCw,
  Save,
  Settings,
  Sparkles,
  Terminal,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubAgent,
  AgentHubSnapshot,
  EnvVarInfo,
  HarnessSnapshot,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

const STATUS_COPY: Record<string, string> = {
  online: "Online",
  ready: "Ready",
  offline: "Offline",
  disabled: "Disabled",
  needs_model: "Needs model",
  needs_telegram: "Needs Telegram",
};

function envPlaceholder(
  envVars: Record<string, EnvVarInfo> | null,
  key: string,
  fallback: string,
) {
  const info = envVars?.[key];
  return info?.is_set && info.redacted_value ? info.redacted_value : fallback;
}

function agentTelegramEnvSegment(agentId: string) {
  const segment = agentId.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return segment || "AGENT";
}

function telegramFieldForAgent(agentId: string, label?: string) {
  const segment = agentTelegramEnvSegment(agentId);
  return {
    agentId,
    tokenKey: `ELEVATE_AGENT_${segment}_TELEGRAM_BOT_TOKEN`,
    key: `ELEVATE_AGENT_${segment}_TELEGRAM_CHANNEL`,
    label: label || agentId,
  };
}

const EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN";
const EXECUTIVE_TELEGRAM_CHANNEL_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL";

function looksLikeTelegramBotToken(value: string) {
  const text = value.trim().replace(/^telegram:/i, "");
  return /^\d{6,}:[A-Za-z0-9_-]{20,}$/.test(text);
}

type AgentEditPatch = {
  enabled?: boolean;
  prompt?: string;
  description?: string;
  skills?: string[];
  toolsets?: string[];
  platforms?: string[];
};

type SkillEntry = { name: string; category: string; description: string };
type ToolsetEntry = { name: string; label: string; description: string };

function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const sortedA = [...a].sort();
  const sortedB = [...b].sort();
  return sortedA.every((value, index) => value === sortedB[index]);
}

function MultiSelectGrid({
  options,
  selected,
  onToggle,
  empty,
  searchable = false,
  getLabel,
  getDescription,
  getCategory,
}: {
  options: Array<{ name: string }>;
  selected: string[];
  onToggle: (name: string) => void;
  empty: string;
  searchable?: boolean;
  getLabel?: (name: string) => string;
  getDescription?: (name: string) => string;
  getCategory?: (name: string) => string;
}) {
  const [query, setQuery] = useState("");
  const selectedSet = new Set(selected);

  const annotated = useMemo(
    () =>
      options.map((option) => ({
        name: option.name,
        label: getLabel?.(option.name) ?? option.name,
        description: getDescription?.(option.name) ?? "",
        category: getCategory?.(option.name) ?? "",
      })),
    [options, getLabel, getDescription, getCategory],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return annotated;
    return annotated.filter(
      (entry) =>
        entry.name.toLowerCase().includes(needle) ||
        entry.label.toLowerCase().includes(needle) ||
        entry.description.toLowerCase().includes(needle) ||
        entry.category.toLowerCase().includes(needle),
    );
  }, [annotated, query]);

  if (options.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/40 px-2.5 py-3 text-xs text-muted-foreground">
        {empty}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {searchable && options.length > 6 && (
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`Search ${options.length} options`}
          className="h-7 text-xs"
        />
      )}
      <div className="grid max-h-56 gap-1 overflow-y-auto pr-1 sm:grid-cols-2">
        {filtered.length === 0 ? (
          <div className="col-span-full px-1 py-2 text-xs text-muted-foreground">
            No matches for "{query}"
          </div>
        ) : (
          filtered.map((entry) => {
            const isOn = selectedSet.has(entry.name);
            return (
              <label
                key={entry.name}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md border px-2 py-1.5 text-xs transition-colors",
                  isOn
                    ? "border-primary/40 bg-primary/5 text-foreground"
                    : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground",
                )}
                title={entry.description || entry.label}
              >
                <input
                  type="checkbox"
                  checked={isOn}
                  onChange={() => onToggle(entry.name)}
                  className="mt-0.5 h-3 w-3 cursor-pointer accent-[--color-primary]"
                />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-medium">{entry.label}</span>
                  {entry.category && (
                    <span className="truncate text-[0.65rem] uppercase tracking-wide text-muted-foreground/70">
                      {entry.category}
                    </span>
                  )}
                </span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

function AgentConfigEditor({
  agent,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  saving,
  onSave,
}: {
  agent: AgentHubAgent;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  saving: boolean;
  onSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(agent.enabled);
  const [description, setDescription] = useState(agent.description ?? "");
  const [prompt, setPrompt] = useState<string>("");
  const [promptLoaded, setPromptLoaded] = useState(false);
  const [skills, setSkills] = useState<string[]>(agent.skills);
  const [toolsets, setToolsets] = useState<string[]>(agent.toolsets);
  const [platforms, setPlatforms] = useState<string[]>(agent.platforms);

  useEffect(() => {
    setEnabled(agent.enabled);
    setDescription(agent.description ?? "");
    setSkills(agent.skills);
    setToolsets(agent.toolsets);
    setPlatforms(agent.platforms);
    setPromptLoaded(false);
    setPrompt("");
  }, [
    agent.id,
    agent.enabled,
    agent.description,
    agent.skills,
    agent.toolsets,
    agent.platforms,
  ]);

  const togglePlatform = (name: string) =>
    setPlatforms((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  const toggleSkill = (name: string) =>
    setSkills((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  const toggleToolset = (name: string) =>
    setToolsets((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );

  const dirty =
    enabled !== agent.enabled ||
    description !== (agent.description ?? "") ||
    (promptLoaded && prompt !== "") ||
    !arraysEqual(skills, agent.skills) ||
    !arraysEqual(toolsets, agent.toolsets) ||
    !arraysEqual(platforms, agent.platforms);

  const handleSave = () => {
    const patch: AgentEditPatch = {};
    if (enabled !== agent.enabled) patch.enabled = enabled;
    if (description !== (agent.description ?? "")) patch.description = description;
    if (promptLoaded && prompt.trim()) patch.prompt = prompt;
    if (!arraysEqual(skills, agent.skills)) patch.skills = skills;
    if (!arraysEqual(toolsets, agent.toolsets)) patch.toolsets = toolsets;
    if (!arraysEqual(platforms, agent.platforms)) patch.platforms = platforms;
    if (Object.keys(patch).length === 0) return;
    void onSave(patch);
  };

  const skillOptions = useMemo(() => availableSkills.map((s) => ({ name: s.name })), [availableSkills]);
  const toolsetOptions = useMemo(
    () => availableToolsets.map((t) => ({ name: t.name })),
    [availableToolsets],
  );
  const platformOptions = useMemo(
    () => availablePlatforms.map((name) => ({ name })),
    [availablePlatforms],
  );

  const skillDescription = (name: string) =>
    availableSkills.find((s) => s.name === name)?.description ?? "";
  const skillCategory = (name: string) =>
    availableSkills.find((s) => s.name === name)?.category ?? "";
  const toolsetLabel = (name: string) =>
    availableToolsets.find((t) => t.name === name)?.label ?? name;
  const toolsetDescription = (name: string) =>
    availableToolsets.find((t) => t.name === name)?.description ?? "";

  return (
    <details className="group/config rounded-md border border-border/60 bg-background/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        <span className="flex items-center gap-2">
          <Settings className="h-3.5 w-3.5" />
          <span>Configure</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {agent.skills.length} skills · {agent.toolsets.length} tools
        </span>
      </summary>
      <div className="grid gap-3 px-2.5 pb-3 pt-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col">
            <span className="text-xs font-medium text-foreground">Enabled</span>
            <span className="text-xs text-muted-foreground">
              Disabled agents won't take work or handoffs.
            </span>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          <span>Description</span>
          <Input
            value={description}
            placeholder="One-line role description"
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>

        <div className="grid gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">System prompt / rules</span>
            <span className="text-xs text-muted-foreground">
              {agent.has_prompt ? "Custom prompt set" : "Using default"}
            </span>
          </div>
          {promptLoaded ? (
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={5}
              className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
              placeholder="Define this agent's responsibilities, voice, and handoff rules…"
            />
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setPromptLoaded(true);
                setPrompt("");
              }}
            >
              Edit prompt
            </Button>
          )}
          {promptLoaded && (
            <span className="text-xs text-muted-foreground">
              Leave empty to keep the existing prompt. Anything typed here replaces it.
            </span>
          )}
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Platforms ({platforms.length})
          </span>
          <MultiSelectGrid
            options={platformOptions}
            selected={platforms}
            onToggle={togglePlatform}
            empty="No platforms available"
          />
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Skills ({skills.length} of {availableSkills.length})
          </span>
          <MultiSelectGrid
            options={skillOptions}
            selected={skills}
            onToggle={toggleSkill}
            empty={
              availableSkills.length === 0
                ? "Loading installed skills…"
                : "No skills installed yet."
            }
            searchable
            getDescription={skillDescription}
            getCategory={skillCategory}
          />
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Toolsets ({toolsets.length} of {availableToolsets.length})
          </span>
          <MultiSelectGrid
            options={toolsetOptions}
            selected={toolsets}
            onToggle={toggleToolset}
            empty={
              availableToolsets.length === 0
                ? "Loading toolsets…"
                : "No toolsets registered."
            }
            searchable
            getLabel={toolsetLabel}
            getDescription={toolsetDescription}
          />
        </div>

        <div className="flex justify-end">
          <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save changes
          </Button>
        </div>
      </div>
    </details>
  );
}

function AgentCard({
  agent,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  savingConfig,
  onConfigSave,
  telegramBotTokenPlaceholder,
  telegramBotTokenValue,
  telegramLanePlaceholder,
  telegramLaneValue,
  onTelegramLaneSave,
  onTelegramBotTokenChange,
  onTelegramLaneChange,
  savingTelegram,
}: {
  agent: AgentHubAgent;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  savingConfig: boolean;
  onConfigSave: (patch: AgentEditPatch) => Promise<void>;
  telegramBotTokenPlaceholder?: string;
  telegramBotTokenValue?: string;
  telegramLanePlaceholder?: string;
  telegramLaneValue?: string;
  onTelegramLaneSave?: () => void;
  onTelegramBotTokenChange?: (value: string) => void;
  onTelegramLaneChange?: (value: string) => void;
  savingTelegram?: boolean;
}) {
  const agentTelegramChanged = Boolean(
    telegramBotTokenValue?.trim() || telegramLaneValue?.trim(),
  );
  const telegramLane = agent.telegramLane;
  const telegramLaneReady = Boolean(telegramLane?.configured);
  const telegramLaneState = telegramLaneReady
    ? "Configured"
    : telegramLane?.duplicateSharedBot
      ? "Duplicate bot token"
      : telegramLane?.usesSharedBot
        ? "Needs own bot token"
      : telegramLane?.tokenConfigured
        ? "Missing chat target"
        : telegramLane?.targetConfigured
          ? "Missing bot token"
          : "Missing bot token and chat target";
  const telegramLaneDetail = telegramLane
    ? `${telegramLane.tokenEnv || "agent token env"} + ${telegramLane.targetEnv || "agent chat env"}`
    : "No Telegram lane required";

  return (
    <div className="rounded-md p-2 hover:bg-muted">
      <div className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{agent.name}</span>
          </div>
          <span className={cn(
            "inline-flex items-center gap-1.5 text-xs",
            agent.status === "active" ? "text-muted-foreground" : "text-warning"
          )}>
            <span className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              agent.status === "active" ? "bg-success" : "bg-warning"
            )} />
            {STATUS_COPY[agent.status] ?? agent.status}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">{agent.description || agent.role}</div>
      </div>
      <div className="mt-2 space-y-3">
        {(agent.active_session_count > 0 || agent.session_count > 0) && (
          <div className="flex items-baseline gap-3 text-xs text-muted-foreground">
            {agent.active_session_count > 0 && (
              <span className="inline-flex items-baseline gap-1 text-success">
                <span className="font-medium tabular-nums">{agent.active_session_count}</span>
                <span>active now</span>
              </span>
            )}
            {agent.session_count > 0 && (
              <span className="inline-flex items-baseline gap-1">
                <span className="tabular-nums">{agent.session_count}</span>
                <span>{agent.session_count === 1 ? "session" : "sessions"} total</span>
              </span>
            )}
          </div>
        )}
        <ChipRow icon={Terminal} items={agent.platforms} empty="No platforms" />
        <ChipRow icon={Wrench} items={agent.toolsets} empty="Global tools" />
        {agent.skills.length > 0 && (
          <ChipRow icon={Sparkles} items={agent.skills} empty="No skills" />
        )}
        <AgentConfigEditor
          agent={agent}
          availableSkills={availableSkills}
          availableToolsets={availableToolsets}
          availablePlatforms={availablePlatforms}
          saving={savingConfig}
          onSave={onConfigSave}
        />
        {onTelegramLaneChange && (
          <details className="group/telegram rounded-md border border-border/60 bg-background/40">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
              <span className="flex items-center gap-2">
                <MessageSquare className="h-3.5 w-3.5" />
                <span>Telegram lane</span>
              </span>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5",
                  telegramLaneReady ? "text-muted-foreground" : "text-warning",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    telegramLaneReady ? "bg-success" : "bg-warning",
                  )}
                />
                {telegramLaneState}
              </span>
            </summary>
            <div className="grid gap-2 px-2.5 pb-2.5 pt-1">
              {!telegramLaneReady && (
                <p className="text-[0.72rem] leading-5 text-muted-foreground">
                  Both fields required. Get a bot token from @BotFather, then paste your chat ID (or chat:topic) from the agent's Telegram conversation.
                </p>
              )}
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
                <label className="grid gap-1 text-xs font-medium text-muted-foreground">
                  <span>Bot token</span>
                  <Input
                    autoComplete="new-password"
                    type="password"
                    value={telegramBotTokenValue ?? ""}
                    placeholder={telegramBotTokenPlaceholder ?? "BotFather token"}
                    onChange={(event) => onTelegramBotTokenChange?.(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && agentTelegramChanged && onTelegramLaneSave) {
                        event.preventDefault();
                        onTelegramLaneSave();
                      }
                    }}
                  />
                </label>
                <label className="grid gap-1 text-xs font-medium text-muted-foreground">
                  <span>Chat/topic ID</span>
                  <Input
                    value={telegramLaneValue ?? ""}
                    placeholder={telegramLanePlaceholder ?? "Chat ID or chat:topic"}
                    onChange={(event) => onTelegramLaneChange(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && agentTelegramChanged && onTelegramLaneSave) {
                        event.preventDefault();
                        onTelegramLaneSave();
                      }
                    }}
                  />
                </label>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={onTelegramLaneSave}
                  disabled={savingTelegram || !agentTelegramChanged}
                >
                  {savingTelegram ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Save
                </Button>
              </div>
              {telegramLane && (
                <div className="min-w-0 truncate text-xs text-muted-foreground">
                  {telegramLaneDetail}
                </div>
              )}
              {telegramLane?.duplicateSharedBot && (
                <div className="text-xs leading-5 text-warning">
                  This agent is using the Executive bot token. Create a separate BotFather token for this agent.
                </div>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-0 py-1">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-sm font-medium" title={String(value)}>
        {value}
      </div>
    </div>
  );
}

function ChipRow({
  items,
  empty,
}: {
  icon: typeof Terminal;
  items: string[];
  empty: string;
}) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
      {(items.length ? items : [empty]).slice(0, 7).map((item) => (
        <span key={item} className="max-w-full truncate">
          {item}
        </span>
      ))}
    </div>
  );
}

function TelegramGatewayControls({
  envVars,
  hasChanges,
  home,
  onHomeChange,
  onRestart,
  onSave,
  onTokenChange,
  saving,
  token,
  tokenConfigured,
}: {
  envVars: Record<string, EnvVarInfo> | null;
  hasChanges: boolean;
  home: string;
  onHomeChange: (value: string) => void;
  onRestart: () => void;
  onSave: () => void;
  onTokenChange: (value: string) => void;
  saving: boolean;
  token: string;
  tokenConfigured: boolean;
}) {
  const saveOnEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && hasChanges) {
      event.preventDefault();
      onSave();
    }
  };

  return (
    <div className="py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-foreground">Executive Telegram</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className={cn("text-xs", tokenConfigured ? "text-muted-foreground" : "text-warning")}>
            {tokenConfigured ? "configured" : "needs token"}
          </span>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <div className="grid gap-1">
          <div className="text-xs font-medium text-muted-foreground">Executive bot token</div>
          <Input
            autoComplete="new-password"
            type="password"
            value={token}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY,
              envPlaceholder(envVars, "TELEGRAM_BOT_TOKEN", "Executive BotFather token"),
            )}
            onChange={(event) => onTokenChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="grid gap-1">
          <div className="text-xs font-medium text-muted-foreground">Executive chat/topic</div>
          <Input
            value={home}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_CHANNEL_KEY,
              envPlaceholder(envVars, "TELEGRAM_HOME_CHANNEL", "Executive chat ID"),
            )}
            onChange={(event) => onHomeChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="flex gap-2 md:justify-end">
          <Button
            size="sm"
            onClick={onSave}
            disabled={saving || !hasChanges}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={onRestart}>
            <RotateCw className="h-3.5 w-3.5" />
            Restart
          </Button>
        </div>
      </div>
    </div>
  );
}

function isHarnessSnapshot(value: AgentHubSnapshot["harness"]): value is HarnessSnapshot {
  return Boolean(value && "server" in value && "orchestration" in value);
}

function formatSavings(value: number | null | undefined) {
  if (typeof value !== "number") return "-";
  return `${value.toFixed(1)}%`;
}

function HarnessCard({ harness }: { harness?: AgentHubSnapshot["harness"] }) {
  if (!isHarnessSnapshot(harness)) {
    return (
      <div className="px-1">
        <div className="mb-2 text-sm font-medium">Harness</div>
        <div className="text-sm text-muted-foreground">
          Harness snapshot unavailable
        </div>
      </div>
    );
  }

  const best = harness.performance.best_profile;
  const worst = harness.performance.worst_profile;
  const connectedClients = harness.server.clients.filter((client) => client.connected);

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 px-1">
        <span className="text-sm font-medium">Harness</span>
        <span className="text-xs text-muted-foreground">· {harness.server.pattern}</span>
      </div>
      <div className="space-y-3 px-1">
        <div className="grid grid-cols-3 gap-2">
          <MiniMetric label="Ready" value={harness.orchestration.plan_graph.ready_runs} />
          <MiniMetric label="Blocked" value={harness.orchestration.plan_graph.blocked_runs} />
          <MiniMetric label="Safety" value={harness.safety.external_actions_policy} />
        </div>
        {harness.performance.available && (
          <div className="text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Baseline</span>
              <span>{harness.performance.baseline_request_tokens ?? 0} tokens</span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Best profile</span>
              <span>
                {best?.name ?? "-"} / {formatSavings(best?.savings_pct)}
              </span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Weakest profile</span>
              <span>
                {worst?.name ?? "-"} / {formatSavings(worst?.savings_pct)}
              </span>
            </div>
          </div>
        )}
        <details className="group text-xs">
          <summary className="cursor-pointer list-none text-muted-foreground hover:text-foreground">
            <span className="group-open:hidden">Show technical detail</span>
            <span className="hidden group-open:inline">Hide technical detail</span>
          </summary>
          <div className="mt-2 space-y-1.5">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Clients</span>
              <span>{connectedClients.length}/{harness.server.clients.length}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Routed runs</span>
              <span>{harness.orchestration.route_labeled_runs}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Recent events</span>
              <span>{harness.orchestration.recent_events}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Memory flow</span>
              <span>{harness.memory.pipeline.state}</span>
            </div>
            {harness.orchestration.lifecycle_states.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-muted-foreground">
                {harness.orchestration.lifecycle_states.slice(0, 7).map((state) => (
                  <span key={state}>{state}</span>
                ))}
              </div>
            )}
          </div>
        </details>
        {harness.memory.pipeline.recent_events?.length ? (
          <div className="text-xs">
            <div className="mb-1 text-muted-foreground">Memory activity</div>
            {harness.memory.pipeline.recent_events.slice(0, 3).map((event, index) => (
              <div key={`${event.timestamp ?? "event"}-${index}`} className="truncate">
                {event.kind ?? "memory"}{event.status ? ` / ${event.status}` : ""}
                {event.message ? `: ${event.message}` : ""}
              </div>
            ))}
          </div>
        ) : null}
        {harness.recommendations.length > 0 && (
          <div className="space-y-1 text-xs text-muted-foreground">
            {harness.recommendations.slice(0, 2).map((item) => (
              <div key={item}>- {item}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function HandoffBusCard({
  busy,
  handoffs,
  onRunWorker,
  onWakeWorker,
  worker,
}: {
  busy: boolean;
  handoffs: AgentHubSnapshot["handoffs"];
  onRunWorker: () => void;
  onWakeWorker: () => void;
  worker: AgentHubSnapshot["agentWorker"];
}) {
  const active = handoffs.queued + handoffs.running + handoffs.waitingHuman;
  const loopRunning = worker.loop?.running ?? false;
  const heartbeat = worker.heartbeat;
  const wake = worker.wake;
  const workerHealthy = worker.enabled && worker.state !== "error" && worker.state !== "disabled" && loopRunning;

  const primaryAction: { label: string; onClick: () => void } = (() => {
    if (!worker.enabled || worker.state === "disabled") {
      return { label: "Run worker", onClick: onRunWorker };
    }
    if (!loopRunning) {
      return { label: "Wake loop", onClick: onWakeWorker };
    }
    if (handoffs.queued > 0 || handoffs.waitingHuman > 0) {
      return { label: "Run worker now", onClick: onRunWorker };
    }
    return { label: "Run worker", onClick: onRunWorker };
  })();
  const secondaryAction =
    primaryAction.label === "Wake loop"
      ? { label: "Run worker", onClick: onRunWorker }
      : { label: "Wake loop", onClick: onWakeWorker };

  return (
    <div className="px-1">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Agent handoffs</span>
            <span className="text-xs text-muted-foreground">· {active} open</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Worker {worker.enabled ? worker.state : "disabled"}</span>
            <span>·</span>
            <span>Loop {loopRunning ? "running" : "stopped"}</span>
            {worker.lastTickAt && (<><span>·</span><span>Tick {isoTimeAgo(worker.lastTickAt)}</span></>)}
            {heartbeat?.lastBeatAt && (<><span>·</span><span>Heartbeat {isoTimeAgo(heartbeat.lastBeatAt)}</span></>)}
            {wake?.lastWakeAt && (<><span>·</span><span>Wake {isoTimeAgo(wake.lastWakeAt)}</span></>)}
            {worker.lastError && <span className="text-warning">{worker.lastError}</span>}
          </div>
          {handoffs.error && (
            <div className="mt-1 text-xs text-warning">{handoffs.error}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
            <Button
              size="sm"
              onClick={primaryAction.onClick}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : primaryAction.label === "Wake loop" ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {primaryAction.label}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={secondaryAction.onClick}
              disabled={busy}
            >
              {secondaryAction.label === "Wake loop" ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {secondaryAction.label}
            </Button>
          </div>
        </div>
      <div className="space-y-3">
        {(handoffs.queued > 0 || handoffs.running > 0) && (
          <div className="grid grid-cols-3 gap-2">
            <MiniMetric label="Queued" value={handoffs.queued} />
            <MiniMetric label="Running" value={handoffs.running} />
            <MiniMetric label="Human" value={handoffs.waitingHuman} />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", workerHealthy ? "bg-success" : "bg-warning")} />
            {worker.enabled ? "auto-drain on" : "auto-drain off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", loopRunning ? "bg-success" : "bg-warning")} />
            wake loop {loopRunning ? "on" : "off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", heartbeat?.enabled ? "bg-success" : "bg-warning")} />
            heartbeat {heartbeat?.intervalSeconds ?? "off"}s
          </span>
          {wake?.pending && <span className="text-warning">wake pending</span>}
        </div>
        <details className="group text-xs">
          <summary className="cursor-pointer list-none text-muted-foreground hover:text-foreground">
            <span className="group-open:hidden">Show drain history</span>
            <span className="hidden group-open:inline">Hide drain history</span>
          </summary>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
            <span>Last handoffs {worker.drained.handoffs}</span>
            <span>·</span>
            <span>Last admin {worker.drained.adminRuns}</span>
            <span>·</span>
            <span>Wakes {wake?.count ?? 0}</span>
            <span>·</span>
            <span>Handoff cap {worker.limits.handoffs}</span>
            <span>·</span>
            <span>Admin cap {worker.limits.adminRuns}</span>
          </div>
        </details>
        {handoffs.byAgent.some((a) => a.queued > 0 || a.running > 0) && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {handoffs.byAgent
              .filter((a) => a.queued > 0 || a.running > 0)
              .slice(0, 8)
              .map((agent) => (
                <span key={agent.agentId} className="text-warning">
                  {agent.agentId} {agent.queued + agent.running}/{agent.total}
                </span>
              ))}
          </div>
        )}
        <div className="space-y-0.5">
          {handoffs.recent.slice(0, 5).map((handoff) => (
            <div
              key={handoff.id}
              className="rounded-md px-1 py-1.5 hover:bg-muted"
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 truncate text-sm font-medium">
                  {handoff.title}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {handoff.status.replace("_", " ")}
                </span>
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                {handoff.fromAgentId} → {handoff.toAgentId} · {isoTimeAgo(handoff.updatedAt)}
              </div>
            </div>
          ))}
          {!handoffs.recent.length && (
            <div className="py-1 text-xs text-muted-foreground/80">No handoffs yet</div>
          )}
        </div>
      </div>
    </div>
  );
}

function SetupRunway({
  busyAction,
  onRestart,
  onStart,
  snapshot,
}: {
  busyAction: string | null;
  onRestart: () => void;
  onStart: () => void;
  snapshot: AgentHubSnapshot;
}) {
  const pendingPairings = snapshot.platforms.reduce(
    (total, platform) => total + platform.pending_pairings.length,
    0,
  );
  const configuredPlatforms = snapshot.platforms.filter((platform) => platform.configured).length;

  const items = [
    {
      icon: KeyRound,
      label: "Model auth",
      detail: snapshot.model.configured ? `${snapshot.model.provider} / ${snapshot.model.model}` : "Connect OpenAI Codex",
      state: snapshot.model.configured ? "ready" : "needs setup",
      to: "/env",
    },
    {
      icon: Terminal,
      label: "Gateway",
      detail: snapshot.gateway.running ? `Running${snapshot.gateway.pid ? ` as ${snapshot.gateway.pid}` : ""}` : "Start the local service",
      state: snapshot.gateway.running ? "online" : "offline",
      action: snapshot.gateway.running ? onRestart : onStart,
    },
    {
      icon: Users,
      label: "Messaging",
      detail: pendingPairings ? `${pendingPairings} pairing code${pendingPairings === 1 ? "" : "s"} waiting` : `${configuredPlatforms} connector${configuredPlatforms === 1 ? "" : "s"} configured`,
      state: pendingPairings ? "review" : configuredPlatforms ? "ready" : "blank",
      to: "/today",
    },
    {
      icon: Brain,
      label: "Memory",
      detail: snapshot.memory.embedding.enabled
        ? `${snapshot.memory.embedding.provider}:${snapshot.memory.embedding.model}`
        : "Turn on embeddings",
      state: snapshot.memory.embedding.enabled ? "ready" : "optional",
      to: "/memory",
    },
  ];

  return (
    <div className="px-1">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-sm font-medium">Setup runway</span>
        <Link
          to="/config"
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          Full settings
        </Link>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => {
          const Icon = item.icon;
          const content = (
            <>
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate text-sm font-semibold text-foreground">{item.label}</span>
                </div>
                <span className={cn(
                  "inline-flex items-center gap-1.5 text-xs",
                  item.state === "ready" || item.state === "online"
                    ? "text-muted-foreground"
                    : item.state === "review" || item.state === "needs setup"
                      ? "text-warning"
                      : "text-muted-foreground"
                )}>
                  <span className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    item.state === "ready" || item.state === "online"
                      ? "bg-success"
                      : item.state === "review" || item.state === "needs setup"
                        ? "bg-warning"
                        : "bg-border"
                  )} />
                  {item.state}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
            </>
          );

          if (item.action) {
            return (
              <button
                key={item.label}
                type="button"
                onClick={item.action}
                disabled={busyAction !== null}
                className="p-2 text-left transition-colors hover:bg-muted disabled:opacity-60 rounded-md"
              >
                {content}
              </button>
            );
          }

          return (
            <Link
              key={item.label}
              to={item.to ?? "/config"}
              className="p-2 transition-colors hover:bg-muted rounded-md"
            >
              {content}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function AgentHubPage() {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [envVars, setEnvVars] = useState<Record<string, EnvVarInfo> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [savingTelegram, setSavingTelegram] = useState(false);
  const [savingAgentId, setSavingAgentId] = useState<string | null>(null);
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramHome, setTelegramHome] = useState("");
  const [telegramLanes, setTelegramLanes] = useState<Record<string, string>>({});
  const [telegramAgentTokens, setTelegramAgentTokens] = useState<Record<string, string>>({});
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();
  const hydrationTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    if (hydrationTimerRef.current) {
      window.clearTimeout(hydrationTimerRef.current);
      hydrationTimerRef.current = null;
    }
    const envVarsPromise = api
      .getEnvVars()
      .then((nextEnvVars) => {
        if (mountedRef.current) setEnvVars(nextEnvVars);
      })
      .catch(() => null);
    try {
      const nextSnapshot = await api.getAgentHub({
        lite: true,
        includeSkills: true,
        includeToolsets: true,
      });
      if (mountedRef.current) {
        setSnapshot(nextSnapshot);
        hydrationTimerRef.current = window.setTimeout(() => {
          void api
            .getAgentHub({ includeMemoryGraph: true })
            .then((fullSnapshot) => {
              if (mountedRef.current) setSnapshot(fullSnapshot);
            })
            .catch(() => null);
        }, 900);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent Hub failed", "error");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
    void envVarsPromise;
  }, [showToast]);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => {
      mountedRef.current = false;
      if (hydrationTimerRef.current) {
        window.clearTimeout(hydrationTimerRef.current);
        hydrationTimerRef.current = null;
      }
    };
  }, [load]);

  useLayoutEffect(() => {
    setAfterTitle(
      snapshot ? (
        <span className="text-xs text-muted-foreground">
          {snapshot.gateway.running ? "Gateway online" : "Gateway offline"}
        </span>
      ) : null,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={load} disabled={loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, setAfterTitle, setEnd, snapshot]);

  const executiveAgent = useMemo(
    () =>
      snapshot?.agents.find((agent) => agent.id === "executive-assistant") ??
      snapshot?.agents[0] ??
      null,
    [snapshot],
  );
  const activeAgents = snapshot?.agents.filter((agent) => agent.enabled) ?? [];
  const liveSessions = snapshot?.sessions.recent.filter((session) => session.is_active) ?? [];
  const availableSkills = useMemo<SkillEntry[]>(
    () => snapshot?.skills.available ?? [],
    [snapshot?.skills.available],
  );
  const availableToolsets = useMemo<ToolsetEntry[]>(
    () =>
      (snapshot?.toolsets.known ?? []).map((toolset) => ({
        name: toolset.name,
        label: toolset.label,
        description: toolset.description,
      })),
    [snapshot?.toolsets.known],
  );
  const availablePlatforms = useMemo<string[]>(
    () => snapshot?.platforms.map((platform) => platform.name) ?? [],
    [snapshot?.platforms],
  );
  const telegramPlatform = snapshot?.platforms.find(
    (platform) => platform.name.toLowerCase() === "telegram",
  );
  const telegramTokenConfigured = Boolean(
    telegramPlatform?.token_configured ||
      envVars?.TELEGRAM_BOT_TOKEN?.is_set ||
      envVars?.[EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY]?.is_set,
  );
  const telegramHasChanges = Boolean(
    telegramToken.trim() ||
      telegramHome.trim() ||
      (snapshot?.agents ?? []).some((agent) => {
        const field = telegramFieldForAgent(agent.id, agent.name);
        return Boolean((telegramAgentTokens[field.tokenKey] ?? "").trim() || (telegramLanes[field.key] ?? "").trim());
      }),
  );

  const runAction = async (name: "start" | "restart") => {
    setBusyAction(name);
    try {
      const result = name === "start" ? await api.startGateway() : await api.restartGateway();
      showToast(`${result.name} started as PID ${result.pid}`, "success");
      setTimeout(load, 1200);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Gateway action failed", "error");
    } finally {
      setBusyAction(null);
    }
  };

  const runAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      const result = await api.runAgentWorkerTick();
      showToast(
        `Worker launched ${result.drained.handoffs} handoff${result.drained.handoffs === 1 ? "" : "s"} and ${result.drained.adminRuns} admin run${result.drained.adminRuns === 1 ? "" : "s"}`,
        "success",
      );
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const wakeAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      await api.wakeAgentWorker();
      showToast("Worker wake queued. Gateway loop will drain it.", "success");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker wake failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const saveTelegramConfig = async () => {
    const entries = new Map<string, string>();
    const executiveField = telegramFieldForAgent("executive-assistant", "Executive Assistant");
    const telegramTokenValue = telegramToken.trim();
    const telegramHomeValue = telegramHome.trim();
    const typedExecutiveToken = (telegramAgentTokens[executiveField.tokenKey] ?? "").trim();
    const typedExecutiveHome = (telegramLanes[executiveField.key] ?? "").trim();
    const executiveTokenCandidate = typedExecutiveToken || telegramTokenValue;
    for (const agent of snapshot?.agents ?? []) {
      if (agent.id === "executive-assistant") continue;
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (
        tokenValue &&
        ((telegramTokenValue && tokenValue === telegramTokenValue) ||
          (executiveTokenCandidate && tokenValue === executiveTokenCandidate))
      ) {
        showToast(`${agent.name} needs its own BotFather token; it cannot reuse Executive.`, "error");
        return;
      }
    }
    if (telegramTokenValue) {
      entries.set("TELEGRAM_BOT_TOKEN", telegramTokenValue);
      if (!typedExecutiveToken) {
        entries.set(EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY, telegramTokenValue);
      }
    }
    if (telegramHomeValue) {
      if (looksLikeTelegramBotToken(telegramHomeValue)) {
        showToast("Home channel expects a chat/topic ID, not a bot token.", "error");
        return;
      }
      entries.set("TELEGRAM_HOME_CHANNEL", telegramHomeValue);
      if (!typedExecutiveHome) {
        entries.set(EXECUTIVE_TELEGRAM_CHANNEL_KEY, telegramHomeValue);
      }
    }
    for (const agent of snapshot?.agents ?? []) {
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (tokenValue) {
        entries.set(field.tokenKey, tokenValue);
      }
      const value = (telegramLanes[field.key] ?? "").trim();
      if (value) {
        if (looksLikeTelegramBotToken(value)) {
          showToast(`${agent.name}: paste the bot token into Bot token, not Chat/topic ID.`, "error");
          return;
        }
        entries.set(field.key, value);
      }
    }
    if (!entries.size) return;

    setSavingTelegram(true);
    try {
      for (const [key, value] of entries.entries()) {
        await api.setEnvVar(key, value);
      }
      setTelegramToken("");
      setTelegramHome("");
      setTelegramLanes({});
      setTelegramAgentTokens({});
      await load();
      showToast("Telegram settings saved. Restart gateway to apply.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Telegram save failed", "error");
    } finally {
      setSavingTelegram(false);
    }
  };

  const saveAgentConfig = useCallback(
    async (agentId: string, patch: AgentEditPatch) => {
      setSavingAgentId(agentId);
      try {
        await api.updateAgent(agentId, patch);
        await load();
        showToast("Agent saved. Restart gateway to apply changes.", "success");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Agent save failed", "error");
      } finally {
        setSavingAgentId(null);
      }
    },
    [load, showToast],
  );

  if (loading && !snapshot) {
    return (
      <div className="onboarding-overlay relative -mx-6 -my-6 flex min-h-[calc(100vh-9rem)] items-center justify-center overflow-hidden px-6 py-10">
        <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative flex flex-col items-center text-center">
          <div className="onboarding-rise flex items-center gap-3">
            <span
              aria-hidden
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-card text-[15px] font-semibold tracking-tight text-foreground"
            >
              E
            </span>
            <span className="text-[17px] font-medium tracking-tight text-foreground">Elevate</span>
          </div>
          <div className="onboarding-rise-delay-1 mt-7 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Agent Hub · loading
          </div>
          <h2 className="onboarding-rise-delay-2 mt-2 text-[26px] font-medium leading-[1.1] tracking-tight text-foreground">
            Spinning up your agents
          </h2>
          <p className="onboarding-rise-delay-3 mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground">
            Pulling agent configs, memory snapshots, and connector status.
          </p>
          <Loader2 className="onboarding-rise-delay-3 mt-6 h-4 w-4 animate-spin text-muted-foreground/70" />
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="onboarding-overlay relative -mx-6 -my-6 flex min-h-[calc(100vh-9rem)] items-center justify-center overflow-hidden px-6 py-10">
        <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative flex flex-col items-center text-center">
          <div className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Agent Hub
          </div>
          <h2 className="mt-2 text-[22px] font-medium leading-[1.1] tracking-tight text-foreground">
            Agent Hub unavailable
          </h2>
          <p className="mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground">
            The local gateway didn't respond. Check the system panel in the sidebar and try Restart Gateway.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="px-1">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="min-w-0">
              <div className="text-xs font-medium text-muted-foreground">Main agent</div>
              <h1 className="mt-1 truncate text-2xl font-semibold leading-tight text-foreground sm:text-3xl">
                {executiveAgent?.name ?? "Executive Assistant"}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                {executiveAgent?.description ||
                  executiveAgent?.role ||
                  "Primary operator and orchestration agent for the local Elevate workspace."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => runAction("start")}
                disabled={busyAction !== null}
                aria-label={snapshot.gateway.running ? "Restart gateway" : "Start gateway"}
              >
                {busyAction === "start" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                Start gateway
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => runAction("restart")}
                disabled={busyAction !== null}
                aria-label="Restart gateway"
              >
                {busyAction === "restart" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCw className="h-3.5 w-3.5" />
                )}
                Restart
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniMetric label="Agent team" value={activeAgents.length} />
            <MiniMetric label="Live chats" value={liveSessions.length} />
            <MiniMetric label="Open handoffs" value={snapshot.handoffs.open} />
            <MiniMetric label="Skills" value={`${snapshot.skills.enabled}/${snapshot.skills.total}`} />
          </div>
        </div>
      </section>

      <SetupRunway
        busyAction={busyAction}
        onRestart={() => void runAction("restart")}
        onStart={() => void runAction("start")}
        snapshot={snapshot}
      />

      <div className="flex flex-col gap-6">
        <div>
          <div className="mb-3 flex items-center gap-2 px-1">
            <span className="text-sm font-medium">Agent orchestration</span>
            <span aria-hidden="true" className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{activeAgents.length} enabled</span>
          </div>
            <div className="space-y-3">
              <TelegramGatewayControls
                envVars={envVars}
                hasChanges={telegramHasChanges}
                home={telegramHome}
                onHomeChange={setTelegramHome}
                onRestart={() => void runAction("restart")}
                onSave={() => void saveTelegramConfig()}
                onTokenChange={setTelegramToken}
                saving={savingTelegram}
                token={telegramToken}
                tokenConfigured={telegramTokenConfigured}
              />
              <div className="grid gap-3 md:grid-cols-2">
                {snapshot.agents.map((agent) => {
                  const telegramField = telegramFieldForAgent(agent.id, agent.name);
                  return (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      availableSkills={availableSkills}
                      availableToolsets={availableToolsets}
                      availablePlatforms={availablePlatforms}
                      savingConfig={savingAgentId === agent.id}
                      onConfigSave={(patch) => saveAgentConfig(agent.id, patch)}
                      telegramBotTokenPlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.tokenKey, `${agent.name} bot token`)
                          : undefined
                      }
                      telegramBotTokenValue={
                        telegramField ? (telegramAgentTokens[telegramField.tokenKey] ?? "") : undefined
                      }
                      telegramLanePlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.key, "Chat ID or topic ID")
                          : undefined
                      }
                      telegramLaneValue={telegramField ? (telegramLanes[telegramField.key] ?? "") : undefined}
                      onTelegramBotTokenChange={
                        telegramField
                          ? (value) =>
                              setTelegramAgentTokens((prev) => ({
                                ...prev,
                                [telegramField.tokenKey]: value,
                              }))
                          : undefined
                      }
                      onTelegramLaneChange={
                        telegramField
                          ? (value) =>
                              setTelegramLanes((prev) => ({ ...prev, [telegramField.key]: value }))
                          : undefined
                      }
                      onTelegramLaneSave={() => void saveTelegramConfig()}
                      savingTelegram={savingTelegram}
                    />
                  );
                })}
              </div>
            </div>
          </div>

        <HandoffBusCard
          busy={handoffBusy}
          handoffs={snapshot.handoffs}
          onRunWorker={() => void runAgentWorker()}
          onWakeWorker={() => void wakeAgentWorker()}
          worker={snapshot.agentWorker}
        />

        <details className="group px-1">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <span className="font-medium">System status</span>
            <span className="text-xs text-muted-foreground/80 group-open:hidden">
              · show
            </span>
            <span className="hidden text-xs text-muted-foreground/80 group-open:inline">
              · hide
            </span>
          </summary>
          <div className="mt-3">
            <HarnessCard harness={snapshot.harness} />
          </div>
        </details>

        <div className="px-1">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-sm font-medium">Access</span>
            <span aria-hidden="true" className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{snapshot.access.label}</span>
          </div>
          <div className="flex items-center gap-x-3 overflow-x-auto whitespace-nowrap text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {Object.entries(snapshot.access.entitlements).map(([name, entitlement]) => (
              <span key={name} className="inline-flex shrink-0 items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    entitlement.status === "active" ? "bg-success" : "bg-border",
                  )}
                />
                <span className="text-muted-foreground">{name}</span>
              </span>
            ))}
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{snapshot.config_path}</div>
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        Snapshot {timeAgo(snapshot.generated_at)} / {snapshot.elevate_home}
      </div>
    </div>
  );
}
