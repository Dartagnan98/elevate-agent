import { useEffect, useMemo, useState } from "react";
import { Loader2, Save, Settings, MessageSquare } from "lucide-react";
import type { AgentHubAgent } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

export type AgentEditPatch = {
  enabled?: boolean;
  prompt?: string;
  description?: string;
  skills?: string[];
  toolsets?: string[];
  platforms?: string[];
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

export function AgentConfigEditor({
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
    <details className="group/telegram rounded-md border border-border/60 bg-background/40">
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
