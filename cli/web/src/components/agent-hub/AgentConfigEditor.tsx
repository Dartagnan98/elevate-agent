import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Loader2, Save, Settings, MessageSquare } from "lucide-react";
import type {
  AgentHubAgent,
  AgentEcosystemConfig,
  AgentIdentityConfig,
  AgentLifecycleConfig,
  AgentMemoryConfig,
  AgentRoutingConfig,
  AgentRuntimeConfig,
  AgentSafetyConfig,
  AgentSoulConfig,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ListSkeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

export type AgentEditPatch = {
  name?: string;
  enabled?: boolean;
  role?: string;
  prompt?: string;
  description?: string;
  skills?: string[];
  toolsets?: string[];
  platforms?: string[];
  session_sources?: string[];
  runtime?: AgentRuntimeConfig;
  routing?: AgentRoutingConfig;
  safety?: AgentSafetyConfig;
  identity?: AgentIdentityConfig;
  soul?: AgentSoulConfig;
  lifecycle?: AgentLifecycleConfig;
  ecosystem?: AgentEcosystemConfig;
  memory?: AgentMemoryConfig;
};

export type SkillEntry = { name: string; category: string; description: string };
export type ToolsetEntry = { name: string; label: string; description: string };

export function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const sortedA = [...a].sort();
  const sortedB = [...b].sort();
  return sortedA.every((value, index) => value === sortedB[index]);
}

export function MultiSelectGrid({
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
  empty: ReactNode;
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

const listToText = (values?: string[]) => (values ?? []).join(", ");
const textToList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
const numberToText = (value?: number | null) => (value == null ? "" : String(value));
const textToNumber = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

export function AgentConfigEditor({
  agent,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  defaultOpen = false,
  saving,
  onSave,
}: {
  agent: AgentHubAgent;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  defaultOpen?: boolean;
  saving: boolean;
  onSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(agent.enabled);
  const [role, setRole] = useState(agent.role ?? "support");
  const [description, setDescription] = useState(agent.description ?? "");
  const [prompt, setPrompt] = useState<string>("");
  const [promptLoaded, setPromptLoaded] = useState(false);
  const [skills, setSkills] = useState<string[]>(agent.skills);
  const [toolsets, setToolsets] = useState<string[]>(agent.toolsets);
  const [platforms, setPlatforms] = useState<string[]>(agent.platforms);
  const [sessionSourcesText, setSessionSourcesText] = useState(listToText(agent.session_sources));
  const [runtimeModel, setRuntimeModel] = useState(agent.runtime?.model ?? "");
  const [runtimeProvider, setRuntimeProvider] = useState(agent.runtime?.provider ?? "");
  const [runtimeWorkdir, setRuntimeWorkdir] = useState(agent.runtime?.workdir ?? "");
  const [runtimeTimezone, setRuntimeTimezone] = useState(agent.runtime?.timezone ?? "");
  const [runtimeType, setRuntimeType] = useState(agent.runtime?.runtime_type ?? "");
  const [codexContextCap, setCodexContextCap] = useState(
    numberToText(agent.runtime?.codex_context_cap),
  );
  const [contextWarning, setContextWarning] = useState(
    numberToText(agent.runtime?.context_warning_threshold),
  );
  const [contextHandoff, setContextHandoff] = useState(
    numberToText(agent.runtime?.context_handoff_threshold),
  );
  const [ownsText, setOwnsText] = useState(listToText(agent.routing?.owns));
  const [handoffTargetsText, setHandoffTargetsText] = useState(
    listToText(agent.routing?.handoff_targets),
  );
  const [escalationTarget, setEscalationTarget] = useState(
    agent.routing?.escalation_target ?? "",
  );
  const [defaultPriority, setDefaultPriority] = useState(
    agent.routing?.default_priority ?? "normal",
  );
  const [approvalMode, setApprovalMode] = useState(
    agent.safety?.approval_mode ?? "confirm_external_send",
  );
  const [alwaysAskText, setAlwaysAskText] = useState(listToText(agent.safety?.always_ask));
  const [neverAskText, setNeverAskText] = useState(listToText(agent.safety?.never_ask));
  const [dangerouslySkipPermissions, setDangerouslySkipPermissions] = useState(
    Boolean(agent.safety?.dangerously_skip_permissions),
  );
  const [identityEmoji, setIdentityEmoji] = useState(agent.identity?.emoji ?? "");
  const [identityVibe, setIdentityVibe] = useState(agent.identity?.vibe ?? "");
  const [identityWorkStyle, setIdentityWorkStyle] = useState(agent.identity?.work_style ?? "");
  const [soulAutonomyRules, setSoulAutonomyRules] = useState(agent.soul?.autonomy_rules ?? "");
  const [soulCommunicationStyle, setSoulCommunicationStyle] = useState(
    agent.soul?.communication_style ?? "",
  );
  const [soulDayMode, setSoulDayMode] = useState(agent.soul?.day_mode ?? "");
  const [soulNightMode, setSoulNightMode] = useState(agent.soul?.night_mode ?? "");
  const [soulDayModeStart, setSoulDayModeStart] = useState(agent.soul?.day_mode_start ?? "");
  const [soulDayModeEnd, setSoulDayModeEnd] = useState(agent.soul?.day_mode_end ?? "");
  const [soulCoreTruths, setSoulCoreTruths] = useState(agent.soul?.core_truths ?? "");
  const [startupDelay, setStartupDelay] = useState(numberToText(agent.lifecycle?.startup_delay));
  const [maxSessionSeconds, setMaxSessionSeconds] = useState(
    numberToText(agent.lifecycle?.max_session_seconds),
  );
  const [maxCrashesPerDay, setMaxCrashesPerDay] = useState(
    numberToText(agent.lifecycle?.max_crashes_per_day),
  );
  const [crashWindowSeconds, setCrashWindowSeconds] = useState(
    numberToText(agent.lifecycle?.crash_window_seconds),
  );
  const [crashWindowMax, setCrashWindowMax] = useState(
    numberToText(agent.lifecycle?.crash_window_max),
  );
  const [telegramPolling, setTelegramPolling] = useState(agent.lifecycle?.telegram_polling ?? null);
  const [localVersionControl, setLocalVersionControl] = useState(
    Boolean(agent.ecosystem?.local_version_control),
  );
  const [upstreamSync, setUpstreamSync] = useState(Boolean(agent.ecosystem?.upstream_sync));
  const [catalogBrowse, setCatalogBrowse] = useState(Boolean(agent.ecosystem?.catalog_browse));
  const [communityPublish, setCommunityPublish] = useState(
    Boolean(agent.ecosystem?.community_publish),
  );
  const [memoryMode, setMemoryMode] = useState(agent.memory?.mode ?? "shared_scoped");
  const [memoryScopesText, setMemoryScopesText] = useState(listToText(agent.memory?.scopes));
  const [memorySourcesText, setMemorySourcesText] = useState(listToText(agent.memory?.sources));
  const [memoryRecallPolicy, setMemoryRecallPolicy] = useState(
    agent.memory?.recall_policy ?? "agent_scoped_recent",
  );
  const [memoryWritePolicy, setMemoryWritePolicy] = useState(
    agent.memory?.write_policy ?? "append_events",
  );
  const [memoryHandoffPolicy, setMemoryHandoffPolicy] = useState(
    agent.memory?.handoff_policy ?? "summary_only",
  );

  useEffect(() => {
    setEnabled(agent.enabled);
    setRole(agent.role ?? "support");
    setDescription(agent.description ?? "");
    setSkills(agent.skills);
    setToolsets(agent.toolsets);
    setPlatforms(agent.platforms);
    setSessionSourcesText(listToText(agent.session_sources));
    setRuntimeModel(agent.runtime?.model ?? "");
    setRuntimeProvider(agent.runtime?.provider ?? "");
    setRuntimeWorkdir(agent.runtime?.workdir ?? "");
    setRuntimeTimezone(agent.runtime?.timezone ?? "");
    setRuntimeType(agent.runtime?.runtime_type ?? "");
    setCodexContextCap(numberToText(agent.runtime?.codex_context_cap));
    setContextWarning(numberToText(agent.runtime?.context_warning_threshold));
    setContextHandoff(numberToText(agent.runtime?.context_handoff_threshold));
    setOwnsText(listToText(agent.routing?.owns));
    setHandoffTargetsText(listToText(agent.routing?.handoff_targets));
    setEscalationTarget(agent.routing?.escalation_target ?? "");
    setDefaultPriority(agent.routing?.default_priority ?? "normal");
    setApprovalMode(agent.safety?.approval_mode ?? "confirm_external_send");
    setAlwaysAskText(listToText(agent.safety?.always_ask));
    setNeverAskText(listToText(agent.safety?.never_ask));
    setDangerouslySkipPermissions(Boolean(agent.safety?.dangerously_skip_permissions));
    setIdentityEmoji(agent.identity?.emoji ?? "");
    setIdentityVibe(agent.identity?.vibe ?? "");
    setIdentityWorkStyle(agent.identity?.work_style ?? "");
    setSoulAutonomyRules(agent.soul?.autonomy_rules ?? "");
    setSoulCommunicationStyle(agent.soul?.communication_style ?? "");
    setSoulDayMode(agent.soul?.day_mode ?? "");
    setSoulNightMode(agent.soul?.night_mode ?? "");
    setSoulDayModeStart(agent.soul?.day_mode_start ?? "");
    setSoulDayModeEnd(agent.soul?.day_mode_end ?? "");
    setSoulCoreTruths(agent.soul?.core_truths ?? "");
    setStartupDelay(numberToText(agent.lifecycle?.startup_delay));
    setMaxSessionSeconds(numberToText(agent.lifecycle?.max_session_seconds));
    setMaxCrashesPerDay(numberToText(agent.lifecycle?.max_crashes_per_day));
    setCrashWindowSeconds(numberToText(agent.lifecycle?.crash_window_seconds));
    setCrashWindowMax(numberToText(agent.lifecycle?.crash_window_max));
    setTelegramPolling(agent.lifecycle?.telegram_polling ?? null);
    setLocalVersionControl(Boolean(agent.ecosystem?.local_version_control));
    setUpstreamSync(Boolean(agent.ecosystem?.upstream_sync));
    setCatalogBrowse(Boolean(agent.ecosystem?.catalog_browse));
    setCommunityPublish(Boolean(agent.ecosystem?.community_publish));
    setMemoryMode(agent.memory?.mode ?? "shared_scoped");
    setMemoryScopesText(listToText(agent.memory?.scopes));
    setMemorySourcesText(listToText(agent.memory?.sources));
    setMemoryRecallPolicy(agent.memory?.recall_policy ?? "agent_scoped_recent");
    setMemoryWritePolicy(agent.memory?.write_policy ?? "append_events");
    setMemoryHandoffPolicy(agent.memory?.handoff_policy ?? "summary_only");
    setPromptLoaded(false);
    setPrompt("");
  }, [
    agent.id,
    agent.enabled,
    agent.role,
    agent.description,
    agent.skills,
    agent.toolsets,
    agent.platforms,
    agent.session_sources,
    agent.runtime,
    agent.routing,
    agent.safety,
    agent.identity,
    agent.soul,
    agent.lifecycle,
    agent.ecosystem,
    agent.memory,
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

  const runtimePatch: AgentRuntimeConfig = {
    model: runtimeModel.trim(),
    provider: runtimeProvider.trim(),
    workdir: runtimeWorkdir.trim(),
    timezone: runtimeTimezone.trim(),
    runtime_type: runtimeType.trim(),
    codex_context_cap: textToNumber(codexContextCap),
    context_warning_threshold: textToNumber(contextWarning),
    context_handoff_threshold: textToNumber(contextHandoff),
  };
  const routingPatch: AgentRoutingConfig = {
    owns: textToList(ownsText),
    handoff_targets: textToList(handoffTargetsText),
    escalation_target: escalationTarget.trim(),
    default_priority: defaultPriority.trim() || "normal",
  };
  const safetyPatch: AgentSafetyConfig = {
    approval_mode: approvalMode.trim() || "confirm_external_send",
    always_ask: textToList(alwaysAskText),
    never_ask: textToList(neverAskText),
    dangerously_skip_permissions: dangerouslySkipPermissions,
  };
  const identityPatch: AgentIdentityConfig = {
    emoji: identityEmoji.trim(),
    vibe: identityVibe.trim(),
    work_style: identityWorkStyle.trim(),
  };
  const soulPatch: AgentSoulConfig = {
    autonomy_rules: soulAutonomyRules.trim(),
    communication_style: soulCommunicationStyle.trim(),
    day_mode: soulDayMode.trim(),
    night_mode: soulNightMode.trim(),
    day_mode_start: soulDayModeStart.trim(),
    day_mode_end: soulDayModeEnd.trim(),
    core_truths: soulCoreTruths.trim(),
  };
  const lifecyclePatch: AgentLifecycleConfig = {
    startup_delay: textToNumber(startupDelay) ?? 0,
    max_session_seconds: textToNumber(maxSessionSeconds),
    max_crashes_per_day: textToNumber(maxCrashesPerDay),
    crash_window_seconds: textToNumber(crashWindowSeconds),
    crash_window_max: textToNumber(crashWindowMax),
    telegram_polling: telegramPolling,
  };
  const ecosystemPatch: AgentEcosystemConfig = {
    local_version_control: localVersionControl,
    upstream_sync: upstreamSync,
    catalog_browse: catalogBrowse,
    community_publish: communityPublish,
  };
  const memoryPatch: AgentMemoryConfig = {
    mode: memoryMode.trim() || "shared_scoped",
    scopes: textToList(memoryScopesText),
    sources: textToList(memorySourcesText),
    recall_policy: memoryRecallPolicy.trim() || "agent_scoped_recent",
    write_policy: memoryWritePolicy.trim() || "append_events",
    handoff_policy: memoryHandoffPolicy.trim() || "summary_only",
  };
  const sessionSources = textToList(sessionSourcesText);
  const runtimeDirty =
    runtimePatch.model !== (agent.runtime?.model ?? "") ||
    runtimePatch.provider !== (agent.runtime?.provider ?? "") ||
    runtimePatch.workdir !== (agent.runtime?.workdir ?? "") ||
    runtimePatch.timezone !== (agent.runtime?.timezone ?? "") ||
    runtimePatch.runtime_type !== (agent.runtime?.runtime_type ?? "") ||
    numberToText(runtimePatch.codex_context_cap) !==
      numberToText(agent.runtime?.codex_context_cap) ||
    numberToText(runtimePatch.context_warning_threshold) !==
      numberToText(agent.runtime?.context_warning_threshold) ||
    numberToText(runtimePatch.context_handoff_threshold) !==
      numberToText(agent.runtime?.context_handoff_threshold);
  const routingDirty =
    !arraysEqual(routingPatch.owns, agent.routing?.owns ?? []) ||
    !arraysEqual(routingPatch.handoff_targets, agent.routing?.handoff_targets ?? []) ||
    routingPatch.escalation_target !== (agent.routing?.escalation_target ?? "") ||
    routingPatch.default_priority !== (agent.routing?.default_priority ?? "normal");
  const safetyDirty =
    safetyPatch.approval_mode !== (agent.safety?.approval_mode ?? "confirm_external_send") ||
    !arraysEqual(safetyPatch.always_ask, agent.safety?.always_ask ?? []) ||
    !arraysEqual(safetyPatch.never_ask, agent.safety?.never_ask ?? []) ||
    safetyPatch.dangerously_skip_permissions !==
      Boolean(agent.safety?.dangerously_skip_permissions);
  const identityDirty =
    identityPatch.emoji !== (agent.identity?.emoji ?? "") ||
    identityPatch.vibe !== (agent.identity?.vibe ?? "") ||
    identityPatch.work_style !== (agent.identity?.work_style ?? "");
  const soulDirty =
    soulPatch.autonomy_rules !== (agent.soul?.autonomy_rules ?? "") ||
    soulPatch.communication_style !== (agent.soul?.communication_style ?? "") ||
    soulPatch.day_mode !== (agent.soul?.day_mode ?? "") ||
    soulPatch.night_mode !== (agent.soul?.night_mode ?? "") ||
    soulPatch.day_mode_start !== (agent.soul?.day_mode_start ?? "") ||
    soulPatch.day_mode_end !== (agent.soul?.day_mode_end ?? "") ||
    soulPatch.core_truths !== (agent.soul?.core_truths ?? "");
  const lifecycleDirty =
    numberToText(lifecyclePatch.startup_delay) !== numberToText(agent.lifecycle?.startup_delay) ||
    numberToText(lifecyclePatch.max_session_seconds) !== numberToText(agent.lifecycle?.max_session_seconds) ||
    numberToText(lifecyclePatch.max_crashes_per_day) !== numberToText(agent.lifecycle?.max_crashes_per_day) ||
    numberToText(lifecyclePatch.crash_window_seconds) !== numberToText(agent.lifecycle?.crash_window_seconds) ||
    numberToText(lifecyclePatch.crash_window_max) !== numberToText(agent.lifecycle?.crash_window_max) ||
    lifecyclePatch.telegram_polling !== (agent.lifecycle?.telegram_polling ?? null);
  const ecosystemDirty =
    ecosystemPatch.local_version_control !== Boolean(agent.ecosystem?.local_version_control) ||
    ecosystemPatch.upstream_sync !== Boolean(agent.ecosystem?.upstream_sync) ||
    ecosystemPatch.catalog_browse !== Boolean(agent.ecosystem?.catalog_browse) ||
    ecosystemPatch.community_publish !== Boolean(agent.ecosystem?.community_publish);
  const memoryDirty =
    memoryPatch.mode !== (agent.memory?.mode ?? "shared_scoped") ||
    !arraysEqual(memoryPatch.scopes, agent.memory?.scopes ?? []) ||
    !arraysEqual(memoryPatch.sources, agent.memory?.sources ?? []) ||
    memoryPatch.recall_policy !== (agent.memory?.recall_policy ?? "agent_scoped_recent") ||
    memoryPatch.write_policy !== (agent.memory?.write_policy ?? "append_events") ||
    memoryPatch.handoff_policy !== (agent.memory?.handoff_policy ?? "summary_only");

  const dirty =
    enabled !== agent.enabled ||
    role !== (agent.role ?? "support") ||
    description !== (agent.description ?? "") ||
    (promptLoaded && prompt !== "") ||
    !arraysEqual(skills, agent.skills) ||
    !arraysEqual(toolsets, agent.toolsets) ||
    !arraysEqual(platforms, agent.platforms) ||
    !arraysEqual(sessionSources, agent.session_sources) ||
    runtimeDirty ||
    routingDirty ||
    safetyDirty ||
    identityDirty ||
    soulDirty ||
    lifecycleDirty ||
    ecosystemDirty ||
    memoryDirty;

  const handleSave = () => {
    const patch: AgentEditPatch = {};
    if (enabled !== agent.enabled) patch.enabled = enabled;
    if (role !== (agent.role ?? "support")) patch.role = role;
    if (description !== (agent.description ?? "")) patch.description = description;
    if (promptLoaded && prompt.trim()) patch.prompt = prompt;
    if (!arraysEqual(skills, agent.skills)) patch.skills = skills;
    if (!arraysEqual(toolsets, agent.toolsets)) patch.toolsets = toolsets;
    if (!arraysEqual(platforms, agent.platforms)) patch.platforms = platforms;
    if (!arraysEqual(sessionSources, agent.session_sources)) {
      patch.session_sources = sessionSources;
    }
    if (runtimeDirty) patch.runtime = runtimePatch;
    if (routingDirty) patch.routing = routingPatch;
    if (safetyDirty) patch.safety = safetyPatch;
    if (identityDirty) patch.identity = identityPatch;
    if (soulDirty) patch.soul = soulPatch;
    if (lifecycleDirty) patch.lifecycle = lifecyclePatch;
    if (ecosystemDirty) patch.ecosystem = ecosystemPatch;
    if (memoryDirty) patch.memory = memoryPatch;
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
    <details className="group/config rounded-md border border-border/60 bg-background/40" open={defaultOpen}>
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
        <section className="grid gap-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Identity & Soul
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {enabled ? "Enabled" : "Suspended"}
              </span>
              <Switch
                checked={enabled}
                onCheckedChange={setEnabled}
                aria-label={enabled ? "Suspend agent identity" : "Enable agent identity"}
              />
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-[10rem_minmax(0,1fr)]">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Role</span>
              <Input value={role} onChange={(event) => setRole(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Description</span>
              <Input
                value={description}
                placeholder="One-line role description"
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
          </div>
          <label className="flex items-center justify-between gap-3 rounded-md border border-border/60 bg-background/40 px-2 py-1.5 text-xs text-muted-foreground">
            <span>Preserve dangerously_skip_permissions</span>
            <Switch
              checked={dangerouslySkipPermissions}
              onCheckedChange={setDangerouslySkipPermissions}
              aria-label="Preserve dangerously skip permissions"
            />
          </label>
        </section>

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

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Persona
          </span>
          <div className="grid gap-2 md:grid-cols-[5rem_minmax(0,1fr)]">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Emoji</span>
              <Input value={identityEmoji} onChange={(event) => setIdentityEmoji(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Vibe</span>
              <Input value={identityVibe} onChange={(event) => setIdentityVibe(event.target.value)} />
            </label>
          </div>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Work style</span>
            <textarea
              value={identityWorkStyle}
              onChange={(event) => setIdentityWorkStyle(event.target.value)}
              rows={2}
              className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
            />
          </label>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Autonomy rules</span>
              <textarea
                value={soulAutonomyRules}
                onChange={(event) => setSoulAutonomyRules(event.target.value)}
                rows={3}
                className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Communication style</span>
              <textarea
                value={soulCommunicationStyle}
                onChange={(event) => setSoulCommunicationStyle(event.target.value)}
                rows={3}
                className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
              />
            </label>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Day mode</span>
              <Input value={soulDayMode} onChange={(event) => setSoulDayMode(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Night mode</span>
              <Input value={soulNightMode} onChange={(event) => setSoulNightMode(event.target.value)} />
            </label>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Day mode start</span>
              <Input
                value={soulDayModeStart}
                placeholder="09:00"
                onChange={(event) => setSoulDayModeStart(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Day mode end</span>
              <Input
                value={soulDayModeEnd}
                placeholder="17:00"
                onChange={(event) => setSoulDayModeEnd(event.target.value)}
              />
            </label>
          </div>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Core truths</span>
            <textarea
              value={soulCoreTruths}
              onChange={(event) => setSoulCoreTruths(event.target.value)}
              rows={2}
              className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
            />
          </label>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Runtime
          </span>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Runtime type</span>
              <Input
                value={runtimeType}
                placeholder="codex"
                onChange={(event) => setRuntimeType(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Model</span>
              <Input
                value={runtimeModel}
                placeholder="Inherited"
                onChange={(event) => setRuntimeModel(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Provider</span>
              <Input
                value={runtimeProvider}
                placeholder="Inherited"
                onChange={(event) => setRuntimeProvider(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground md:col-span-2">
              <span>Workdir</span>
              <Input
                value={runtimeWorkdir}
                placeholder="Inherited"
                onChange={(event) => setRuntimeWorkdir(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Timezone</span>
              <Input
                value={runtimeTimezone}
                placeholder="Inherited"
                onChange={(event) => setRuntimeTimezone(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Codex context cap</span>
              <Input
                inputMode="numeric"
                value={codexContextCap}
                onChange={(event) => setCodexContextCap(event.target.value)}
              />
            </label>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1 text-xs font-medium text-muted-foreground">
                <span>Warning %</span>
                <Input
                  inputMode="numeric"
                  value={contextWarning}
                  onChange={(event) => setContextWarning(event.target.value)}
                />
              </label>
              <label className="grid gap-1 text-xs font-medium text-muted-foreground">
                <span>Handoff %</span>
                <Input
                  inputMode="numeric"
                  value={contextHandoff}
                  onChange={(event) => setContextHandoff(event.target.value)}
                />
              </label>
            </div>
          </div>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Lifecycle
          </span>
          <div className="grid gap-2 md:grid-cols-3">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Startup delay</span>
              <Input inputMode="numeric" value={startupDelay} onChange={(event) => setStartupDelay(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Max session seconds</span>
              <Input inputMode="numeric" value={maxSessionSeconds} onChange={(event) => setMaxSessionSeconds(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Max crashes/day</span>
              <Input inputMode="numeric" value={maxCrashesPerDay} onChange={(event) => setMaxCrashesPerDay(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Crash window seconds</span>
              <Input inputMode="numeric" value={crashWindowSeconds} onChange={(event) => setCrashWindowSeconds(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Crash window max</span>
              <Input inputMode="numeric" value={crashWindowMax} onChange={(event) => setCrashWindowMax(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Telegram polling</span>
              <select
                value={telegramPolling === null ? "inherit" : telegramPolling ? "enabled" : "disabled"}
                onChange={(event) => {
                  const next = event.target.value;
                  setTelegramPolling(next === "inherit" ? null : next === "enabled");
                }}
                className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
              >
                <option value="inherit">Inherited</option>
                <option value="enabled">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </label>
          </div>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Channels
          </span>
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
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Session sources</span>
            <Input
              value={sessionSourcesText}
              onChange={(event) => setSessionSourcesText(event.target.value)}
            />
          </label>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Work & Routing
          </span>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Owns</span>
            <Input value={ownsText} onChange={(event) => setOwnsText(event.target.value)} />
          </label>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Handoff targets</span>
            <Input
              value={handoffTargetsText}
              onChange={(event) => setHandoffTargetsText(event.target.value)}
            />
          </label>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Escalation target</span>
              <Input
                value={escalationTarget}
                onChange={(event) => setEscalationTarget(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Default priority</span>
              <Input
                value={defaultPriority}
                onChange={(event) => setDefaultPriority(event.target.value)}
              />
            </label>
          </div>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Safety
          </span>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Approval mode</span>
            <Input
              value={approvalMode}
              onChange={(event) => setApprovalMode(event.target.value)}
            />
          </label>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Always ask</span>
              <Input
                value={alwaysAskText}
                onChange={(event) => setAlwaysAskText(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Never ask</span>
              <Input
                value={neverAskText}
                onChange={(event) => setNeverAskText(event.target.value)}
              />
            </label>
          </div>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Ecosystem
          </span>
          <div className="grid gap-2 sm:grid-cols-2">
            {([
              ["local_version_control", "Local version control", localVersionControl, setLocalVersionControl],
              ["upstream_sync", "Upstream sync", upstreamSync, setUpstreamSync],
              ["catalog_browse", "Catalog browse", catalogBrowse, setCatalogBrowse],
              ["community_publish", "Community publish", communityPublish, setCommunityPublish],
            ] satisfies Array<[string, string, boolean, (next: boolean) => void]>).map(([key, label, checked, setChecked]) => (
              <label key={String(key)} className="flex items-center justify-between gap-3 rounded-md border border-border/60 bg-background/40 px-2 py-1.5 text-xs text-muted-foreground">
                <span>{String(label)}</span>
                <Switch
                  checked={checked}
                  onCheckedChange={setChecked}
                  aria-label={`${checked ? "Disable" : "Enable"} ${label}`}
                />
              </label>
            ))}
          </div>
        </section>

        <section className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Memory
          </span>
          <div className="grid gap-2 md:grid-cols-3">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Mode</span>
              <Input value={memoryMode} onChange={(event) => setMemoryMode(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Recall policy</span>
              <Input value={memoryRecallPolicy} onChange={(event) => setMemoryRecallPolicy(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Write policy</span>
              <Input value={memoryWritePolicy} onChange={(event) => setMemoryWritePolicy(event.target.value)} />
            </label>
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Scopes</span>
              <Input value={memoryScopesText} onChange={(event) => setMemoryScopesText(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Sources</span>
              <Input value={memorySourcesText} onChange={(event) => setMemorySourcesText(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-medium text-muted-foreground">
              <span>Handoff policy</span>
              <Input value={memoryHandoffPolicy} onChange={(event) => setMemoryHandoffPolicy(event.target.value)} />
            </label>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            Long-running memory content stays in Elevate memory; this only controls each agent's scope and recall/write behavior.
          </p>
        </section>

        <section className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Skills ({skills.length} of {availableSkills.length})
          </span>
          <MultiSelectGrid
            options={skillOptions}
            selected={skills}
            onToggle={toggleSkill}
            empty={
              availableSkills.length === 0
                ? <ListSkeleton rows={3} />
                : "No skills installed yet."
            }
            searchable
            getDescription={skillDescription}
            getCategory={skillCategory}
          />
        </section>

        <section className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Toolsets ({toolsets.length} of {availableToolsets.length})
          </span>
          <MultiSelectGrid
            options={toolsetOptions}
            selected={toolsets}
            onToggle={toggleToolset}
            empty={
              availableToolsets.length === 0
                ? <ListSkeleton rows={3} />
                : "No toolsets registered."
            }
            searchable
            getLabel={toolsetLabel}
            getDescription={toolsetDescription}
          />
        </section>

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

// Per-agent Telegram lane editor. Each Agent Hub agent can have its own bot
// token + chat target, completely separate from the primary Elevation bot.
export function AgentTelegramLaneEditor({
  agent,
  tokenValue,
  laneValue,
  tokenPlaceholder,
  lanePlaceholder,
  onTokenChange,
  onLaneChange,
  onSave,
  saving,
  defaultOpen = false,
}: {
  agent: AgentHubAgent;
  tokenValue: string;
  laneValue: string;
  tokenPlaceholder?: string;
  lanePlaceholder?: string;
  onTokenChange: (value: string) => void;
  onLaneChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
  defaultOpen?: boolean;
}) {
  const lane = agent.telegramLane;
  const ready = Boolean(lane?.configured);
  const changed = Boolean(tokenValue.trim() || laneValue.trim());
  const state = ready
    ? "Configured"
    : lane?.duplicateSharedBot
      ? "Duplicate bot token"
      : lane?.usesSharedBot
        ? "Needs own bot token"
        : lane?.tokenConfigured
          ? "Missing chat target"
          : lane?.targetConfigured
            ? "Missing bot token"
            : "Missing bot token and chat target";
  const detail = lane
    ? `${lane.tokenEnv || "agent token env"} + ${lane.targetEnv || "agent chat env"}`
    : "No Telegram lane required";

  return (
    <details className="group/telegram rounded-md border border-border/60 bg-background/40" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        <span className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5" />
          <span>Telegram lane</span>
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5",
            ready ? "text-muted-foreground" : "text-warning",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              ready ? "bg-success" : "bg-warning",
            )}
          />
          {state}
        </span>
      </summary>
      <div className="grid gap-2 px-2.5 pb-2.5 pt-1">
        {!ready && (
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
              value={tokenValue}
              placeholder={tokenPlaceholder ?? "BotFather token"}
              onChange={(event) => onTokenChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && changed) {
                  event.preventDefault();
                  onSave();
                }
              }}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Chat/topic ID</span>
            <Input
              value={laneValue}
              placeholder={lanePlaceholder ?? "Chat ID or chat:topic"}
              onChange={(event) => onLaneChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && changed) {
                  event.preventDefault();
                  onSave();
                }
              }}
            />
          </label>
          <Button
            size="sm"
            variant="outline"
            onClick={onSave}
            disabled={saving || !changed}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
        </div>
        {lane && (
          <div className="min-w-0 truncate text-xs text-muted-foreground">
            {detail}
          </div>
        )}
        {lane?.duplicateSharedBot && (
          <div className="text-xs leading-5 text-warning">
            This agent is using the Executive bot token. Create a separate BotFather token for this agent.
          </div>
        )}
      </div>
    </details>
  );
}
