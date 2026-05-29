import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type SVGProps,
} from "react";
import { Link } from "react-router-dom";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { FullWindowAurora } from "@/components/FullWindowAurora";
import type {
  AgentHubAgent,
  AgentHubSnapshot,
  EnvVarInfo,
  HarnessSnapshot,
} from "@/lib/api";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";
import {
  type AgentEditPatch,
  type SkillEntry,
  type ToolsetEntry,
} from "@/components/agent-hub/AgentConfigEditor";
import "./agent-hub.css";

// ── status copy ──────────────────────────────────────────────────────
const STATUS_COPY: Record<string, string> = {
  online: "Online",
  ready: "Ready",
  offline: "Offline",
  disabled: "Disabled",
  needs_model: "Needs model",
  needs_telegram: "Needs Telegram",
};

// ── icons (verbatim from the design prototype) ───────────────────────
type IconProps = SVGProps<SVGSVGElement>;
const Ico = {
  refresh: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M3 21v-5h5" /></svg>
  ),
  play: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M8 5v14l11-7z" /></svg>
  ),
  key: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="m10.5 12.5 8-8" /><path d="m16 5 3 3" /><path d="m19 8 2-2" /></svg>
  ),
  terminal: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m6 8 4 4-4 4" /><path d="M12 16h6" /></svg>
  ),
  people: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
  ),
  memory: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" /></svg>
  ),
  gear: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
  ),
  chat: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
  ),
  save: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><path d="M17 21v-8H7v8M7 3v5h8" /></svg>
  ),
  wrench: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M14.7 6.3a4 4 0 0 0-5.6 5.6l-6.4 6.4a1.5 1.5 0 0 0 2.1 2.1l6.4-6.4a4 4 0 0 0 5.6-5.6l-2.5 2.5-2.1-2.1z" /></svg>
  ),
  sparkles: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" /></svg>
  ),
  chevDown: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m6 9 6 6 6-6" /></svg>
  ),
  search: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
  ),
  x: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M18 6 6 18M6 6l12 12" /></svg>
  ),
  plus: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 5v14M5 12h14" /></svg>
  ),
  rotate: (p: IconProps) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>
  ),
};

type RunwayIconKey = "key" | "terminal" | "people" | "memory";
const RUNWAY_ICON: Record<RunwayIconKey, (p: IconProps) => ReactNode> = {
  key: Ico.key,
  terminal: Ico.terminal,
  people: Ico.people,
  memory: Ico.memory,
};

// ── env helpers (preserved from the live page) ───────────────────────
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

// ── primitives (design markup) ───────────────────────────────────────
function MiniMetric({
  label,
  value,
  big,
}: {
  label: string;
  value: string | number;
  big?: boolean;
}) {
  return (
    <div className="hub-kpi">
      <div className="hub-kpi-label">{label}</div>
      <div className={"hub-kpi-value" + (big ? " big" : "")} title={String(value)}>
        {value}
      </div>
    </div>
  );
}

function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      className={"hub-switch" + (checked ? " on" : "")}
      aria-pressed={checked}
      onClick={(event) => {
        event.preventDefault();
        onChange(!checked);
      }}
    >
      <span className="hub-switch-knob" />
    </button>
  );
}

function StateBadge({ state }: { state: string }) {
  const ok = state === "ready" || state === "online";
  const warn = state === "review" || state === "needs setup" || state === "starting";
  const cls = ok ? "ok" : warn ? "warn" : "idle";
  const label = state === "online" ? "online" : state === "starting" ? "starting…" : state;
  return (
    <span className={"hub-state " + cls}>
      <span className="hub-state-dot" />
      {label}
    </span>
  );
}

type RunwayItem = {
  id: string;
  icon: RunwayIconKey;
  label: string;
  detail: string;
  state: string;
  to?: string;
  action?: () => void;
};

function RunwayTile({
  item,
  busy,
}: {
  item: RunwayItem;
  busy: boolean;
}) {
  const Icon = RUNWAY_ICON[item.icon];
  const inner = (
    <>
      <div className="hub-runway-top">
        <span className="hub-runway-icon"><Icon width="15" height="15" /></span>
        <span className="hub-runway-label">{item.label}</span>
        <StateBadge state={item.state} />
      </div>
      <div className="hub-runway-detail mono">{item.detail}</div>
    </>
  );
  if (item.action) {
    return (
      <button type="button" className="hub-runway-tile" onClick={item.action} disabled={busy}>
        {inner}
      </button>
    );
  }
  return (
    <Link to={item.to ?? "/config"} className="hub-runway-tile">
      {inner}
    </Link>
  );
}

function ChipRow({
  icon: Icon,
  items,
  empty,
}: {
  icon: (p: IconProps) => ReactNode;
  items: string[];
  empty: string;
}) {
  const list = (items && items.length ? items : [empty]).slice(0, 7);
  return (
    <div className="hub-chiprow">
      <Icon width="12" height="12" className="hub-chiprow-ico" />
      {list.map((x) => (
        <span className="hub-chip-flat" key={x}>{x}</span>
      ))}
    </div>
  );
}

// ── MultiSelectGrid — toggleable option chips (design markup) ────────
function MultiSelectGrid({
  options,
  selected,
  onToggle,
  empty,
  searchable,
  getLabel,
  getDescription,
}: {
  options: Array<{ name: string }>;
  selected: string[];
  onToggle: (name: string) => void;
  empty: string;
  searchable?: boolean;
  getLabel?: (name: string) => string;
  getDescription?: (name: string) => string;
}) {
  const [query, setQuery] = useState("");
  if (!options.length) return <div className="hub-ms-empty">{empty}</div>;
  const filtered =
    searchable && query
      ? options.filter((o) =>
          (getLabel ? getLabel(o.name) : o.name).toLowerCase().includes(query.toLowerCase()),
        )
      : options;
  return (
    <div className="hub-ms">
      {searchable && (
        <div className="hub-ms-search">
          <Ico.search width="12" height="12" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search…" />
        </div>
      )}
      <div className="hub-ms-grid">
        {filtered.map((o) => {
          const on = selected.includes(o.name);
          const label = getLabel ? getLabel(o.name) : o.name;
          const desc = getDescription ? getDescription(o.name) : "";
          return (
            <button
              type="button"
              key={o.name}
              className={"hub-ms-chip" + (on ? " on" : "")}
              title={desc}
              onClick={(event) => {
                event.preventDefault();
                onToggle(o.name);
              }}
            >
              <span className="hub-ms-check">{on ? "✓" : ""}</span>
              <span className="hub-ms-name">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── inline Configure editor (design markup, real onSave -> updateAgent)
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
  const [promptOpen, setPromptOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [skills, setSkills] = useState<string[]>(agent.skills);
  const [toolsets, setToolsets] = useState<string[]>(agent.toolsets);
  const [platforms, setPlatforms] = useState<string[]>(agent.platforms);

  useEffect(() => {
    setEnabled(agent.enabled);
    setDescription(agent.description ?? "");
    setSkills(agent.skills);
    setToolsets(agent.toolsets);
    setPlatforms(agent.platforms);
    setPromptOpen(false);
    setPrompt("");
  }, [agent.id, agent.enabled, agent.description, agent.skills, agent.toolsets, agent.platforms]);

  const toggle =
    (set: React.Dispatch<React.SetStateAction<string[]>>) => (name: string) =>
      set((prev) => (prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]));
  const eq = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
  const dirty =
    enabled !== agent.enabled ||
    description !== (agent.description ?? "") ||
    (promptOpen && Boolean(prompt.trim())) ||
    !eq(skills, agent.skills) ||
    !eq(toolsets, agent.toolsets) ||
    !eq(platforms, agent.platforms);

  const skillOpts = availableSkills.map((s) => ({ name: s.name }));
  const toolOpts = availableToolsets.map((t) => ({ name: t.name }));
  const platOpts = availablePlatforms.map((name) => ({ name }));
  const skillDesc = (n: string) => availableSkills.find((s) => s.name === n)?.description ?? "";
  const toolLabel = (n: string) => availableToolsets.find((t) => t.name === n)?.label ?? n;
  const toolDesc = (n: string) => availableToolsets.find((t) => t.name === n)?.description ?? "";

  function handleSave() {
    const patch: AgentEditPatch = {};
    if (enabled !== agent.enabled) patch.enabled = enabled;
    if (description !== (agent.description ?? "")) patch.description = description;
    if (promptOpen && prompt.trim()) patch.prompt = prompt;
    if (!eq(skills, agent.skills)) patch.skills = skills;
    if (!eq(toolsets, agent.toolsets)) patch.toolsets = toolsets;
    if (!eq(platforms, agent.platforms)) patch.platforms = platforms;
    if (Object.keys(patch).length === 0) return;
    void onSave(patch);
  }

  return (
    <details className="hub-acc">
      <summary className="hub-acc-sum">
        <span className="hub-acc-sum-l"><Ico.gear width="13" height="13" /><span>Configure</span></span>
        <span className="hub-acc-sum-meta mono">{agent.skills.length} skills · {agent.toolsets.length} tools</span>
        <Ico.chevDown width="13" height="13" className="hub-acc-chev" />
      </summary>
      <div className="hub-acc-body">
        <div className="hub-acc-switchrow">
          <div>
            <div className="hub-acc-k">Enabled</div>
            <div className="hub-acc-hint">Disabled agents won't take work or handoffs.</div>
          </div>
          <Switch checked={enabled} onChange={setEnabled} />
        </div>

        <label className="hub-acc-field">
          <span className="hub-acc-k">Description</span>
          <input
            className="hub-input"
            value={description}
            placeholder="One-line role description"
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>

        <div className="hub-acc-field">
          <div className="hub-acc-fieldhead">
            <span className="hub-acc-k">System prompt / rules</span>
            <span className="hub-acc-hint">{agent.has_prompt ? "Custom prompt set" : "Using default"}</span>
          </div>
          {promptOpen ? (
            <textarea
              className="hub-textarea"
              rows={4}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Define this agent's responsibilities, voice, and handoff rules…"
            />
          ) : (
            <button
              type="button"
              className="hub-btn ghost sm"
              onClick={(event) => {
                event.preventDefault();
                setPromptOpen(true);
              }}
            >
              Edit prompt
            </button>
          )}
        </div>

        <div className="hub-acc-field">
          <span className="hub-acc-k">Platforms ({platforms.length})</span>
          <MultiSelectGrid options={platOpts} selected={platforms} onToggle={toggle(setPlatforms)} empty="No platforms available" />
        </div>
        <div className="hub-acc-field">
          <span className="hub-acc-k">Skills ({skills.length} of {availableSkills.length})</span>
          <MultiSelectGrid options={skillOpts} selected={skills} onToggle={toggle(setSkills)} empty="No skills installed yet." searchable getDescription={skillDesc} />
        </div>
        <div className="hub-acc-field">
          <span className="hub-acc-k">Toolsets ({toolsets.length} of {availableToolsets.length})</span>
          <MultiSelectGrid options={toolOpts} selected={toolsets} onToggle={toggle(setToolsets)} empty="No toolsets registered." searchable getLabel={toolLabel} getDescription={toolDesc} />
        </div>

        <div className="hub-acc-actions">
          <button className="hub-btn primary" disabled={!dirty || saving} onClick={handleSave}>
            {saving ? (
              <><Ico.refresh width="13" height="13" className="spin" />Saving</>
            ) : (
              <><Ico.save width="13" height="13" />Save changes</>
            )}
          </button>
        </div>
      </div>
    </details>
  );
}

// ── inline Telegram lane editor (design markup, real onSave) ─────────
function AgentTelegramLaneEditor({
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

  const saveOnEnter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && changed) {
      event.preventDefault();
      onSave();
    }
  };

  return (
    <details className="hub-acc">
      <summary className="hub-acc-sum">
        <span className="hub-acc-sum-l"><Ico.chat width="13" height="13" /><span>Telegram lane</span></span>
        <span className={"hub-lane-status " + (ready ? "ok" : "warn")}><span className="hub-lane-dot" />{state}</span>
        <Ico.chevDown width="13" height="13" className="hub-acc-chev" />
      </summary>
      <div className="hub-acc-body">
        {!ready && (
          <p className="hub-acc-note">Both fields required. Get a bot token from @BotFather, then paste your chat ID (or chat:topic) from the agent's Telegram conversation.</p>
        )}
        <div className="hub-lane-form">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Bot token</span>
            <input
              className="hub-input mono"
              autoComplete="new-password"
              type="password"
              value={tokenValue}
              placeholder={tokenPlaceholder ?? "BotFather token"}
              onChange={(event) => onTokenChange(event.target.value)}
              onKeyDown={saveOnEnter}
            />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Chat/topic ID</span>
            <input
              className="hub-input mono"
              value={laneValue}
              placeholder={lanePlaceholder ?? "Chat ID or chat:topic"}
              onChange={(event) => onLaneChange(event.target.value)}
              onKeyDown={saveOnEnter}
            />
          </label>
          <button className="hub-btn ghost" disabled={!changed || saving} onClick={onSave}>
            {saving ? (
              <><Ico.refresh width="13" height="13" className="spin" />Saving</>
            ) : (
              <><Ico.save width="13" height="13" />Save</>
            )}
          </button>
        </div>
        <div className="hub-lane-detail mono">{detail}</div>
        {lane?.duplicateSharedBot && (
          <p className="hub-acc-note" style={{ color: "var(--status-warn)" }}>
            This agent is using the Executive bot token. Create a separate BotFather token for this agent.
          </p>
        )}
      </div>
    </details>
  );
}

// ── agent card (design markup) ───────────────────────────────────────
function AgentCard({
  agent,
  isPrimary,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  savingConfig,
  onConfigSave,
  telegramBotTokenPlaceholder,
  telegramBotTokenValue,
  telegramLanePlaceholder,
  telegramLaneValue,
  onTelegramBotTokenChange,
  onTelegramLaneChange,
  onTelegramLaneSave,
  savingTelegram,
}: {
  agent: AgentHubAgent;
  isPrimary: boolean;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  savingConfig: boolean;
  onConfigSave: (patch: AgentEditPatch) => Promise<void>;
  telegramBotTokenPlaceholder?: string;
  telegramBotTokenValue: string;
  telegramLanePlaceholder?: string;
  telegramLaneValue: string;
  onTelegramBotTokenChange: (value: string) => void;
  onTelegramLaneChange: (value: string) => void;
  onTelegramLaneSave: () => void;
  savingTelegram: boolean;
}) {
  const active = agent.status === "active" || agent.status === "online" || agent.status === "ready";
  const np = agent.platforms.length;
  const nt = agent.toolsets.length;
  const ns = agent.skills.length;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return (
    <div className="hub-agent">
      <div className="hub-agent-head">
        <div className="hub-agent-name">
          {agent.name}
          {isPrimary && <span className="hub-agent-badge mono">Main agent</span>}
        </div>
        <span className={"hub-agent-status " + (active ? "ok" : "warn")}>
          <span className="hub-agent-status-dot" />
          {STATUS_COPY[agent.status] ?? agent.status}
        </span>
      </div>
      <div className="hub-agent-desc">{agent.description || agent.role}</div>
      <div className="hub-agent-meta mono">
        {agent.active_session_count > 0 && <span className="active">{agent.active_session_count} active</span>}
        {agent.session_count > 0 && <span>{plural(agent.session_count, "session")}</span>}
        <span>{plural(np, "platform")}</span>
        <span>{nt ? plural(nt, "tool") : "global tools"}</span>
        <span>{plural(ns, "skill")}</span>
      </div>
      <ChipRow icon={Ico.terminal} items={agent.platforms} empty="No platforms" />
      <ChipRow icon={Ico.wrench} items={agent.toolsets} empty="Global tools" />
      {agent.skills.length > 0 && <ChipRow icon={Ico.sparkles} items={agent.skills} empty="No skills" />}
      <div className="hub-agent-config">
        <AgentConfigEditor
          agent={agent}
          availableSkills={availableSkills}
          availableToolsets={availableToolsets}
          availablePlatforms={availablePlatforms}
          saving={savingConfig}
          onSave={onConfigSave}
        />
        <AgentTelegramLaneEditor
          agent={agent}
          tokenValue={telegramBotTokenValue}
          laneValue={telegramLaneValue}
          tokenPlaceholder={telegramBotTokenPlaceholder}
          lanePlaceholder={telegramLanePlaceholder}
          onTokenChange={onTelegramBotTokenChange}
          onLaneChange={onTelegramLaneChange}
          onSave={onTelegramLaneSave}
          saving={savingTelegram}
        />
      </div>
    </div>
  );
}

// ── executive telegram controls (design markup) ─────────────────────
function ExecutiveTelegramControls({
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
  const saveOnEnter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && hasChanges) {
      event.preventDefault();
      onSave();
    }
  };
  return (
    <div className="hub-exectel">
      <div className="hub-exectel-head">
        <span className="hub-exectel-title">Executive Telegram</span>
        <span className="hub-exectel-sep">·</span>
        <span className={"hub-exectel-tag" + (tokenConfigured ? "" : " warn")}>
          {tokenConfigured ? "configured" : "needs token"}
        </span>
      </div>
      <div className="hub-exectel-form">
        <div className="hub-exectel-field">
          <span className="hub-input-label">Executive bot token</span>
          <input
            className="hub-input mono"
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
        <div className="hub-exectel-field">
          <span className="hub-input-label">Executive chat/topic</span>
          <input
            className="hub-input mono"
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
        <div className="hub-exectel-actions">
          <button className="hub-btn primary" onClick={onSave} disabled={saving || !hasChanges}>
            {saving ? <><Ico.refresh width="13" height="13" className="spin" />Save</> : <><Ico.save width="13" height="13" />Save</>}
          </button>
          <button className="hub-btn ghost" onClick={onRestart}>
            <Ico.rotate width="13" height="13" />Restart
          </button>
        </div>
      </div>
    </div>
  );
}

// ── handoff bus (design markup, real worker/handoff data) ────────────
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
  const workerHealthy =
    worker.enabled && worker.state !== "error" && worker.state !== "disabled" && loopRunning;
  const busyAgents = handoffs.byAgent.filter((a) => a.queued > 0 || a.running > 0).slice(0, 8);

  return (
    <div className="hub-section">
      <div className="hub-handoff-head">
        <div>
          <div className="hub-block-title">
            Agent handoffs <span className="hub-block-meta mono">· {active} open</span>
          </div>
          <div className="hub-handoff-meta mono">
            <span>Worker {worker.enabled ? worker.state : "disabled"}</span><span className="sep">·</span>
            <span>Loop {loopRunning ? "running" : "stopped"}</span>
            {worker.lastTickAt && (<><span className="sep">·</span><span>Tick {isoTimeAgo(worker.lastTickAt)}</span></>)}
            {heartbeat?.lastBeatAt && (<><span className="sep">·</span><span>Heartbeat {isoTimeAgo(heartbeat.lastBeatAt)}</span></>)}
            {wake?.lastWakeAt && (<><span className="sep">·</span><span>Wake {isoTimeAgo(wake.lastWakeAt)}</span></>)}
            {worker.lastError && <span className="warn">{worker.lastError}</span>}
          </div>
          {handoffs.error && <div className="hub-handoff-meta mono"><span className="warn">{handoffs.error}</span></div>}
        </div>
        <div className="hub-handoff-actions">
          <button className="hub-btn primary" disabled={busy} onClick={onRunWorker}>
            <Ico.refresh width="13" height="13" className={busy ? "spin" : ""} />Run worker
          </button>
          <button className="hub-btn ghost" disabled={busy} onClick={onWakeWorker}>
            <Ico.play width="12" height="12" />Wake loop
          </button>
        </div>
      </div>

      {(handoffs.queued > 0 || handoffs.running > 0) && (
        <div className="hub-mini3">
          <MiniMetric label="Queued" value={handoffs.queued} />
          <MiniMetric label="Running" value={handoffs.running} />
          <MiniMetric label="Human" value={handoffs.waitingHuman} />
        </div>
      )}

      <div className="hub-handoff-flags mono">
        <span><span className={"hub-flagdot " + (workerHealthy ? "ok" : "warn")} />{worker.enabled ? "auto-drain on" : "auto-drain off"}</span>
        <span><span className={"hub-flagdot " + (loopRunning ? "ok" : "warn")} />wake loop {loopRunning ? "on" : "off"}</span>
        <span><span className={"hub-flagdot " + (heartbeat?.enabled ? "ok" : "warn")} />heartbeat {heartbeat?.intervalSeconds ?? "off"}s</span>
        {wake?.pending && <span className="warn">wake pending</span>}
      </div>

      {busyAgents.length > 0 && (
        <div className="hub-handoff-byagent mono">
          {busyAgents.map((a) => (
            <span key={a.agentId}>{a.agentId} {a.queued + a.running}/{a.total}</span>
          ))}
        </div>
      )}

      <div className="hub-handoff-list">
        {handoffs.recent.slice(0, 5).map((h) => (
          <div className="hub-handoff-row" key={h.id}>
            <div className="hub-handoff-row-top">
              <span className="hub-handoff-title">{h.title}</span>
              <span className="hub-handoff-status">{h.status.replace("_", " ")}</span>
            </div>
            <div className="hub-handoff-route mono">{h.fromAgentId} → {h.toAgentId} · {isoTimeAgo(h.updatedAt)}</div>
          </div>
        ))}
        {!handoffs.recent.length && <div className="hub-handoff-empty">No handoffs yet</div>}
      </div>
    </div>
  );
}

// ── harness / system status (design markup, real harness data) ──────
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
      <div className="hub-section">
        <div className="hub-block-title" style={{ marginBottom: "12px" }}>Harness</div>
        <div className="hub-harness-unavailable">Harness snapshot unavailable</div>
      </div>
    );
  }

  const best = harness.performance.best_profile;
  const worst = harness.performance.worst_profile;
  const connectedClients = harness.server.clients.filter((client) => client.connected);
  const memoryEvents = harness.memory.pipeline.recent_events ?? [];

  return (
    <div className="hub-section">
      <div className="hub-block-title" style={{ marginBottom: "12px" }}>
        Harness <span className="hub-block-meta mono">· {harness.server.pattern}</span>
      </div>
      <div className="hub-mini3">
        <MiniMetric label="Ready" value={harness.orchestration.plan_graph.ready_runs} />
        <MiniMetric label="Blocked" value={harness.orchestration.plan_graph.blocked_runs} />
        <MiniMetric label="Safety" value={harness.safety.external_actions_policy} />
      </div>
      {harness.performance.available && (
        <div className="hub-harness-perf mono">
          <div><span className="dim">Baseline</span><span>{(harness.performance.baseline_request_tokens ?? 0).toLocaleString()} tokens</span></div>
          <div><span className="dim">Best profile</span><span>{best?.name ?? "-"} / {formatSavings(best?.savings_pct)}</span></div>
          <div><span className="dim">Weakest profile</span><span>{worst?.name ?? "-"} / {formatSavings(worst?.savings_pct)}</span></div>
          <div><span className="dim">Clients</span><span>{connectedClients.length}/{harness.server.clients.length}</span></div>
          <div><span className="dim">Routed runs</span><span>{harness.orchestration.route_labeled_runs}</span></div>
          <div><span className="dim">Memory flow</span><span>{harness.memory.pipeline.state}</span></div>
        </div>
      )}
      {memoryEvents.length > 0 && (
        <div className="hub-harness-memact mono">
          <div className="lbl">Memory activity</div>
          {memoryEvents.slice(0, 3).map((event, index) => (
            <div className="row" key={`${event.timestamp ?? "event"}-${index}`}>
              {event.kind ?? "memory"}{event.status ? ` / ${event.status}` : ""}{event.message ? `: ${event.message}` : ""}
            </div>
          ))}
        </div>
      )}
      {harness.recommendations.length > 0 && (
        <div className="hub-harness-recs">
          {harness.recommendations.slice(0, 2).map((r) => <div key={r}>- {r}</div>)}
        </div>
      )}
      <details className="hub-harness-detail mono">
        <summary>Show technical detail</summary>
        <div className="hub-harness-detail-body">
          <div className="hub-harness-detail-row"><span>Recent events</span><span>{harness.orchestration.recent_events}</span></div>
          {harness.orchestration.lifecycle_states.length > 0 && (
            <div className="hub-harness-states">
              {harness.orchestration.lifecycle_states.slice(0, 7).map((state) => <span key={state}>{state}</span>)}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

// ── access (design markup, real entitlements) ───────────────────────
function AccessRow({ snapshot }: { snapshot: AgentHubSnapshot }) {
  return (
    <div className="hub-section hub-access">
      <div className="hub-block-title" style={{ marginBottom: "10px" }}>
        Access <span className="hub-block-meta mono">· {snapshot.access.label}</span>
      </div>
      <div className="hub-access-ents mono">
        {Object.entries(snapshot.access.entitlements).map(([name, entitlement]) => (
          <span key={name}>
            <span className={"hub-flagdot " + (entitlement.status === "active" ? "ok" : "off")} />
            {name}
          </span>
        ))}
      </div>
      <div className="hub-access-path mono">{snapshot.config_path}</div>
      <div className="hub-snapshot mono">Snapshot {timeAgo(snapshot.generated_at)} / {snapshot.elevate_home}</div>
    </div>
  );
}

// ── add-agent modal (design markup; no createAgent endpoint -> honest error)
function AddAgentModal({
  onAdd,
  onClose,
}: {
  onAdd: (name: string, description: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return createPortal(
    <div
      className="hub-modal-back"
      role="dialog"
      aria-modal="true"
      aria-labelledby="hub-add-agent-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="hub-modal sm">
        <button type="button" className="hub-modal-close" aria-label="Close" onClick={onClose}>
          <Ico.x width="16" height="16" />
        </button>
        <div className="hub-modal-head">
          <div className="hub-modal-crumb mono">Agent orchestration <span className="sep">/</span> New agent</div>
          <h2 id="hub-add-agent-title" className="hub-modal-title">Add an agent</h2>
          <div className="hub-modal-sub">Spin up a new orchestrated agent in your team.</div>
        </div>
        <div className="hub-modal-body">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Agent name</span>
            <input className="hub-input" placeholder="e.g. Listings" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="hub-acc-field" style={{ marginTop: "12px" }}>
            <span className="hub-acc-k">Description</span>
            <input className="hub-input" placeholder="What does this agent handle?" value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <div className="hub-acc-actions" style={{ marginTop: "18px" }}>
            <button type="button" className="hub-btn ghost" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="hub-btn primary"
              disabled={!name.trim()}
              onClick={() => {
                onAdd(name.trim(), description.trim());
                onClose();
              }}
            >
              <Ico.plus width="13" height="13" />Add agent
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ── page ─────────────────────────────────────────────────────────────
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
  const [addAgentOpen, setAddAgentOpen] = useState(false);
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
      <button type="button" className="hub-btn ghost sm" onClick={load} disabled={loading}>
        <Ico.refresh width="13" height="13" className={loading ? "spin" : ""} />
        Refresh
      </button>,
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

  const runAction = useCallback(
    async (name: "start" | "restart") => {
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
    },
    [load, showToast],
  );

  const runwayItems = useMemo<RunwayItem[]>(() => {
    if (!snapshot) return [];
    const pendingPairings = snapshot.platforms.reduce(
      (total, platform) => total + platform.pending_pairings.length,
      0,
    );
    const configuredPlatforms = snapshot.platforms.filter((platform) => platform.configured).length;
    return [
      {
        id: "model",
        icon: "key",
        label: "Model auth",
        detail: snapshot.model.configured ? `${snapshot.model.provider} / ${snapshot.model.model}` : "Connect OpenAI Codex",
        state: snapshot.model.configured ? "ready" : "needs setup",
        to: "/env",
      },
      {
        id: "gateway",
        icon: "terminal",
        label: "Gateway",
        detail: snapshot.gateway.running
          ? `Running${snapshot.gateway.pid ? ` as ${snapshot.gateway.pid}` : ""}`
          : busyAction === "start" || busyAction === "restart"
            ? "Booting service…"
            : "Start the local service",
        state: snapshot.gateway.running ? "online" : busyAction ? "starting" : "offline",
        action: snapshot.gateway.running ? () => void runAction("restart") : () => void runAction("start"),
      },
      {
        id: "messaging",
        icon: "people",
        label: "Messaging",
        detail: pendingPairings
          ? `${pendingPairings} pairing code${pendingPairings === 1 ? "" : "s"} waiting`
          : `${configuredPlatforms} connector${configuredPlatforms === 1 ? "" : "s"} configured`,
        state: pendingPairings ? "review" : configuredPlatforms ? "ready" : "blank",
        to: "/today",
      },
      {
        id: "memory",
        icon: "memory",
        label: "Memory",
        detail: snapshot.memory.embedding.enabled
          ? `${snapshot.memory.embedding.provider}:${snapshot.memory.embedding.model}`
          : "Turn on embeddings",
        state: snapshot.memory.embedding.enabled ? "ready" : "optional",
        to: "/memory",
      },
    ];
  }, [snapshot, busyAction, runAction]);

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

  // TODO: no createAgent endpoint exists yet (api only exposes updateAgent).
  // Wire this to api.createAgent once the backend lands; for now we surface a
  // toast so the affordance is honest rather than silently failing.
  const handleAddAgent = useCallback(
    (name: string, _description: string) => {
      void _description;
      showToast(`Agent creation isn't wired yet — "${name}" was not created.`, "error");
    },
    [showToast],
  );

  if (loading && !snapshot) {
    return (
      <div role="status" aria-live="polite" className="min-h-[20rem] w-full">
        <span className="sr-only">Loading Agent Hub</span>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <FullWindowAurora
        label="Agent Hub"
        title="Agent Hub unavailable"
        subtitle="The local gateway didn't respond. Check the system panel in the sidebar and try Restart Gateway."
      />
    );
  }

  return (
    <div className="hub-root">
      <Toast toast={toast} />
      <div className="hub">
        <div className="hub-inner">
          {/* Title/status/Refresh live in the app page header (usePageHeader),
              matching the Admin/Leads single-top-bar pattern — no in-page
              duplicate top bar here. */}
          {/* hero */}
          <div className="hub-hero">
            <div>
              <div className="hub-hero-label">Main agent</div>
              <h1 className="hub-hero-title">{executiveAgent?.name ?? "Executive Assistant"}</h1>
              <p className="hub-hero-sub">
                {executiveAgent?.description ||
                  executiveAgent?.role ||
                  "Primary operator and orchestration agent for the local Elevation workspace."}
              </p>
            </div>
            <div className="hub-hero-actions">
              <button
                type="button"
                className="hub-btn primary"
                onClick={() => void runAction("start")}
                disabled={busyAction !== null}
                aria-label={snapshot.gateway.running ? "Restart gateway" : "Start gateway"}
              >
                {busyAction === "start" ? <Ico.refresh width="13" height="13" className="spin" /> : <Ico.play width="12" height="12" />}
                Start gateway
              </button>
              <button
                type="button"
                className="hub-btn ghost"
                onClick={() => void runAction("restart")}
                disabled={busyAction !== null}
                aria-label="Restart gateway"
              >
                {busyAction === "restart" ? <Ico.refresh width="13" height="13" className="spin" /> : <Ico.rotate width="13" height="13" />}
                Restart
              </button>
            </div>
          </div>

          {/* kpis */}
          <div className="hub-kpis">
            <MiniMetric label="Agent team" value={activeAgents.length} big />
            <MiniMetric label="Live chats" value={liveSessions.length} big />
            <MiniMetric label="Open handoffs" value={snapshot.handoffs.open} big />
            <MiniMetric label="Skills" value={`${snapshot.skills.enabled}/${snapshot.skills.total}`} big />
          </div>

          {/* setup runway */}
          <div className="hub-block">
            <div className="hub-block-head">
              <div className="hub-block-title">Setup runway</div>
              <Link to="/config" className="hub-link">Full settings</Link>
            </div>
            <div className="hub-runway">
              {runwayItems.map((item) => (
                <RunwayTile key={item.id} item={item} busy={busyAction !== null} />
              ))}
            </div>
          </div>

          {/* agent orchestration */}
          <div className="hub-block">
            <div className="hub-block-head">
              <div className="hub-block-title">
                Agent orchestration <span className="hub-block-meta mono">· {activeAgents.length} enabled</span>
              </div>
              <button type="button" className="hub-btn ghost sm" onClick={() => setAddAgentOpen(true)}>
                <Ico.plus width="13" height="13" />Add an agent
              </button>
            </div>

            <ExecutiveTelegramControls
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

            <div className="hub-agents">
              {snapshot.agents.map((agent) => {
                const telegramField = telegramFieldForAgent(agent.id, agent.name);
                return (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    isPrimary={executiveAgent?.id === agent.id}
                    availableSkills={availableSkills}
                    availableToolsets={availableToolsets}
                    availablePlatforms={availablePlatforms}
                    savingConfig={savingAgentId === agent.id}
                    onConfigSave={(patch) => saveAgentConfig(agent.id, patch)}
                    telegramBotTokenPlaceholder={envPlaceholder(envVars, telegramField.tokenKey, `${agent.name} bot token`)}
                    telegramBotTokenValue={telegramAgentTokens[telegramField.tokenKey] ?? ""}
                    telegramLanePlaceholder={envPlaceholder(envVars, telegramField.key, "Chat ID or topic ID")}
                    telegramLaneValue={telegramLanes[telegramField.key] ?? ""}
                    onTelegramBotTokenChange={(value) =>
                      setTelegramAgentTokens((prev) => ({ ...prev, [telegramField.tokenKey]: value }))
                    }
                    onTelegramLaneChange={(value) =>
                      setTelegramLanes((prev) => ({ ...prev, [telegramField.key]: value }))
                    }
                    onTelegramLaneSave={() => void saveTelegramConfig()}
                    savingTelegram={savingTelegram}
                  />
                );
              })}
              <button type="button" className="hub-agent-add" onClick={() => setAddAgentOpen(true)}>
                <span className="hub-agent-add-ico"><Ico.plus width="18" height="18" /></span>
                <span className="hub-agent-add-label">Add an agent</span>
                <span className="hub-agent-add-sub">Spin up a new orchestrated agent</span>
              </button>
            </div>
          </div>

          {/* handoff bus */}
          <HandoffBusCard
            busy={handoffBusy}
            handoffs={snapshot.handoffs}
            onRunWorker={() => void runAgentWorker()}
            onWakeWorker={() => void wakeAgentWorker()}
            worker={snapshot.agentWorker}
          />

          {/* system status (harness) */}
          <details className="hub-sysstatus">
            <summary className="hub-sysstatus-toggle">
              System status <span className="hub-sysstatus-hint">· show</span>
            </summary>
            <HarnessCard harness={snapshot.harness} />
          </details>

          {/* access */}
          <AccessRow snapshot={snapshot} />
        </div>
      </div>

      {addAgentOpen && (
        <AddAgentModal onAdd={handleAddAgent} onClose={() => setAddAgentOpen(false)} />
      )}
    </div>
  );
}
