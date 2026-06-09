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
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { useCachedResource } from "@/hooks/useCachedResource";
import { Link } from "react-router-dom";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { FullWindowAurora } from "@/components/FullWindowAurora";
import type {
  AgentHandoff,
  AgentHubAgent,
  AgentHubSnapshot,
  CronJob,
  EnvVarInfo,
  HarnessSnapshot,
  HeartbeatSurface,
  InstallableDefault,
  SurfaceApproval,
  SurfaceTask,
} from "@/lib/api";
import type { TelegramPendingEntry } from "@/lib/api-types";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";
import { AgentLoops } from "@/components/agent/agent-loops";
import { AgentHubSkeleton } from "@/components/agent-hub/AgentHubSkeleton";
import { ListSkeleton } from "@/components/ui/skeleton";
import {
  AgentTelegramLaneEditor,
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

const EMPTY_AGENT_QUEUE_SUMMARY = {
  total: 0,
  queued: 0,
  running: 0,
  waitingHuman: 0,
  completed: 0,
  failed: 0,
  staleRecovered: 0,
  lastWorkerTickAt: null,
} satisfies AgentHubAgent["queueSummary"];

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

// Always-accessible channel pairing approver. Lists pending codes from the bot
// and lets you paste/approve a code directly — no onboarding wizard needed.
function PairingApprovalBlock() {
  const [pending, setPending] = useState<TelegramPendingEntry[]>([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await api.listTelegramPairings();
      setPending(resp.pending ?? []);
    } catch {
      /* gateway may be down — leave list empty */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const approve = useCallback(
    async (raw: string) => {
      const value = raw.trim();
      if (!value || busy) return;
      setBusy(true);
      setNote(null);
      try {
        await api.approveTelegramPairing(value);
        setNote(`Approved ${value}`);
        setCode("");
        await refresh();
      } catch (e) {
        setNote((e as Error)?.message ?? "Could not approve that code");
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh],
  );

  return (
    <div className="hub-block">
      <div className="hub-block-head">
        <div className="hub-block-title">
          Pair a channel
          {pending.length > 0 ? (
            <span className="hub-block-meta mono"> · {pending.length} waiting</span>
          ) : null}
        </div>
        <Link to="/agent-onboarding?run=1" className="hub-link">Setup wizard</Link>
      </div>

      {pending.length > 0 ? (
        <div className="hub-runway" style={{ marginBottom: 10 }}>
          {pending.map((p) => (
            <div key={p.code} className="hub-runway-tile" style={{ cursor: "default" }}>
              <div className="hub-runway-top">
                <span className="hub-runway-label">{p.user_name || "Unknown user"}</span>
              </div>
              <div className="hub-runway-detail mono">{p.platform} · {p.code}</div>
              <button
                type="button"
                className="hub-btn sm"
                style={{ marginTop: 8 }}
                disabled={busy}
                onClick={() => void approve(p.code)}
              >
                Approve
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="hub-runway-detail" style={{ marginBottom: 8 }}>
          No codes waiting. DM <span className="mono">/start</span> to your bot, then
          paste the code it replies with below.
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void approve(code); }}
          placeholder="Paste pairing code"
          spellCheck={false}
          className="mono"
          style={{
            flex: 1,
            minWidth: 0,
            padding: "8px 10px",
            borderRadius: 8,
            background: "var(--bg-2)",
            border: "1px solid var(--border)",
            color: "var(--fg)",
            outline: "none",
            fontSize: "13px",
          }}
        />
        <button
          type="button"
          className="hub-btn"
          disabled={busy || !code.trim()}
          onClick={() => void approve(code)}
        >
          {busy ? "Approving…" : "Approve code"}
        </button>
      </div>
      {note ? <div className="hub-runway-detail mono" style={{ marginTop: 6 }}>{note}</div> : null}
    </div>
  );
}

type AgentDetailTab =
  | "profile"
  | "tasks"
  | "automations"
  | "memory"
  | "activity"
  | "goals"
  | "settings";

const AGENT_DETAIL_TABS: Array<{ id: AgentDetailTab; label: string }> = [
  { id: "profile", label: "Profile" },
  { id: "tasks", label: "Tasks" },
  { id: "automations", label: "Workflows" },
  { id: "memory", label: "Memory" },
  { id: "activity", label: "Logs/Activity" },
  { id: "goals", label: "Goals" },
  { id: "settings", label: "Rules/Settings" },
];

const AGENT_SURFACE_MAP: Record<string, string> = { outreach: "leads" };
const surfaceKeyForAgent = (agentId: string) => AGENT_SURFACE_MAP[agentId] ?? agentId;

type ActivityItem = {
  kind: string;
  agent: string;
  ts: string;
  title: string;
  detail?: string | null;
  status?: string;
};

type AgentDetailData = {
  tasks: SurfaceTask[];
  handoffs: AgentHandoff[];
  incomingHandoffs: AgentHandoff[];
  outgoingHandoffs: AgentHandoff[];
  cronJobs: CronJob[];
  heartbeat?: HeartbeatSurface;
  activity: ActivityItem[];
  approvals: SurfaceApproval[];
};

function uniqueById<T extends { id: string }>(items: T[]): T[] {
  const out: T[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (!item.id || seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }
  return out;
}

function shortText(value: string | null | undefined, fallback = "Untitled") {
  const clean = String(value || "").trim();
  return clean || fallback;
}

const numberToText = (value?: number | null) => (value == null ? "" : String(value));
const textToOptionalInt = (value: string, { allowZero = false }: { allowZero?: boolean } = {}) => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed)) return null;
  if (allowZero ? parsed < 0 : parsed <= 0) return null;
  return parsed;
};
const listToText = (values?: string[]) => (values ?? []).join(", ");
const textToList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
const TIME_RE = /^\d{2}:\d{2}$/;
const APPROVAL_CATEGORIES = ["external-comms", "financial", "deployment", "data-deletion"] as const;
const APPROVAL_CATEGORY_LABELS: Record<(typeof APPROVAL_CATEGORIES)[number], string> = {
  "external-comms": "External comms",
  financial: "Financial",
  deployment: "Deployment",
  "data-deletion": "Data deletion",
};
const isKnownApprovalCategory = (value: string): value is (typeof APPROVAL_CATEGORIES)[number] =>
  (APPROVAL_CATEGORIES as readonly string[]).includes(value);

function DetailEmpty({ children }: { children: ReactNode }) {
  return <div className="hub-detail-empty">{children}</div>;
}

function DetailPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" | "ok" | "bad" }) {
  return <span className={`hub-detail-pill ${tone}`}>{children}</span>;
}

function useAgentDetailData(agentId: string) {
  const surfaceKey = surfaceKeyForAgent(agentId);
  const [data, setData] = useState<AgentDetailData>({
    tasks: [],
    handoffs: [],
    incomingHandoffs: [],
    outgoingHandoffs: [],
    cronJobs: [],
    activity: [],
    approvals: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [
        agentTasks,
        surfaceTasks,
        incoming,
        outgoing,
        cronJobs,
        heartbeat,
        activity,
        approvals,
        surfaceApprovals,
      ] = await Promise.all([
        api.listSurfaceTasks({ assignee: agentId }).catch(() => ({ tasks: [] as SurfaceTask[] })),
        surfaceKey !== agentId
          ? api.listSurfaceTasks({ assignee: surfaceKey }).catch(() => ({ tasks: [] as SurfaceTask[] }))
          : Promise.resolve({ tasks: [] as SurfaceTask[] }),
        api.getAgentHandoffs({ toAgentId: agentId, limit: 24 }).catch(() => ({ items: [] as AgentHandoff[], count: 0 })),
        api.getAgentHandoffs({ fromAgentId: agentId, limit: 24 }).catch(() => ({ items: [] as AgentHandoff[], count: 0 })),
        api.getCronJobs({ refresh: true }).catch(() => [] as CronJob[]),
        api.getHeartbeatSurfaces({ refresh: true }).catch(() => ({ surfaces: [] as HeartbeatSurface[] })),
        api.getActivity({ agent: agentId, limit: 10 }).catch(() => ({ items: [] as ActivityItem[] })),
        api.listSurfaceApprovals({ status: "pending", surface: agentId }).catch(() => ({ approvals: [] as SurfaceApproval[] })),
        surfaceKey !== agentId
          ? api.listSurfaceApprovals({ status: "pending", surface: surfaceKey }).catch(() => ({ approvals: [] as SurfaceApproval[] }))
          : Promise.resolve({ approvals: [] as SurfaceApproval[] }),
      ]);
      const incomingItems = incoming.items || [];
      const outgoingItems = outgoing.items || [];
      const agentKeys = new Set([agentId, surfaceKey]);
      setData({
        tasks: uniqueById([...(agentTasks.tasks || []), ...(surfaceTasks.tasks || [])]),
        incomingHandoffs: incomingItems,
        outgoingHandoffs: outgoingItems,
        handoffs: uniqueById([...incomingItems, ...outgoingItems]),
        cronJobs: (cronJobs || []).filter((job) => agentKeys.has(String(job.agent || ""))),
        heartbeat: (heartbeat.surfaces || []).find((surface) => surface.surface === surfaceKey),
        activity: activity.items || [],
        approvals: uniqueById([...(approvals.approvals || []), ...(surfaceApprovals.approvals || [])]),
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent detail failed");
    } finally {
      setLoading(false);
    }
  }, [agentId, surfaceKey]);

  useEffect(() => {
    load();
  }, [load]);
  useRefreshOnAgentTurn(() => void load());

  return { data, error, loading, refresh: load, surfaceKey };
}

function FactLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="hub-agent-detail-line">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AgentProfileForm({
  agent,
  saving,
  onSave,
}: {
  agent: AgentHubAgent;
  saving: boolean;
  onSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const [role, setRole] = useState(agent.role ?? "");
  const [description, setDescription] = useState(agent.description ?? "");
  const [emoji, setEmoji] = useState(agent.identity?.emoji ?? "");
  const [vibe, setVibe] = useState(agent.identity?.vibe ?? "");
  const [workStyle, setWorkStyle] = useState(agent.identity?.work_style ?? "");
  const [autonomyRules, setAutonomyRules] = useState(agent.soul?.autonomy_rules ?? "");
  const [communicationStyle, setCommunicationStyle] = useState(agent.soul?.communication_style ?? "");
  const [dayMode, setDayMode] = useState(agent.soul?.day_mode ?? "");
  const [nightMode, setNightMode] = useState(agent.soul?.night_mode ?? "");
  const [coreTruths, setCoreTruths] = useState(agent.soul?.core_truths ?? "");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRole(agent.role ?? "");
    setDescription(agent.description ?? "");
    setEmoji(agent.identity?.emoji ?? "");
    setVibe(agent.identity?.vibe ?? "");
    setWorkStyle(agent.identity?.work_style ?? "");
    setAutonomyRules(agent.soul?.autonomy_rules ?? "");
    setCommunicationStyle(agent.soul?.communication_style ?? "");
    setDayMode(agent.soul?.day_mode ?? "");
    setNightMode(agent.soul?.night_mode ?? "");
    setCoreTruths(agent.soul?.core_truths ?? "");
    setSaved(false);
    setError(null);
  }, [agent.id, agent.role, agent.description, agent.identity, agent.soul]);

  const baseline = JSON.stringify({
    role: agent.role ?? "",
    description: agent.description ?? "",
    emoji: agent.identity?.emoji ?? "",
    vibe: agent.identity?.vibe ?? "",
    workStyle: agent.identity?.work_style ?? "",
    autonomyRules: agent.soul?.autonomy_rules ?? "",
    communicationStyle: agent.soul?.communication_style ?? "",
    dayMode: agent.soul?.day_mode ?? "",
    nightMode: agent.soul?.night_mode ?? "",
    coreTruths: agent.soul?.core_truths ?? "",
  });
  const current = JSON.stringify({
    role,
    description,
    emoji,
    vibe,
    workStyle,
    autonomyRules,
    communicationStyle,
    dayMode,
    nightMode,
    coreTruths,
  });
  const dirty = baseline !== current;

  const save = async () => {
    setError(null);
    try {
      await onSave({
        role: role.trim(),
        description: description.trim(),
        identity: {
          emoji: emoji.trim(),
          vibe: vibe.trim(),
          work_style: workStyle.trim(),
        },
        soul: {
          autonomy_rules: autonomyRules.trim(),
          communication_style: communicationStyle.trim(),
          day_mode: dayMode.trim(),
          night_mode: nightMode.trim(),
          core_truths: coreTruths.trim(),
        },
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profile save failed");
    }
  };

  return (
    <div className="hub-profile-form">
      {saved && <div className="hub-save-note">Saved. Identity and soul fields are updated.</div>}
      {error && <div className="hub-import-error">{error}</div>}

      <section className="hub-profile-section">
        <div className="hub-profile-section-head">
          <span>Identity</span>
          <small>What the agent is and how it presents itself.</small>
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Role</span>
            <input className="hub-input" value={role} onChange={(event) => { setRole(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Emoji</span>
            <input className="hub-input" value={emoji} onChange={(event) => { setEmoji(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Description</span>
            <textarea className="hub-textarea" rows={2} value={description} onChange={(event) => { setDescription(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Vibe</span>
            <textarea className="hub-textarea" rows={2} value={vibe} onChange={(event) => { setVibe(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Work style</span>
            <textarea className="hub-textarea" rows={2} value={workStyle} onChange={(event) => { setWorkStyle(event.target.value); setSaved(false); }} />
          </label>
        </div>
      </section>

      <section className="hub-profile-section">
        <div className="hub-profile-section-head">
          <span>Soul</span>
          <small>Cortext-style behavior, autonomy, and day/night posture.</small>
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Autonomy rules</span>
            <textarea className="hub-textarea" rows={3} value={autonomyRules} onChange={(event) => { setAutonomyRules(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Communication style</span>
            <textarea className="hub-textarea" rows={3} value={communicationStyle} onChange={(event) => { setCommunicationStyle(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Day mode</span>
            <textarea className="hub-textarea" rows={2} value={dayMode} onChange={(event) => { setDayMode(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Night mode</span>
            <textarea className="hub-textarea" rows={2} value={nightMode} onChange={(event) => { setNightMode(event.target.value); setSaved(false); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Core truths</span>
            <textarea className="hub-textarea" rows={3} value={coreTruths} onChange={(event) => { setCoreTruths(event.target.value); setSaved(false); }} />
          </label>
        </div>
      </section>

      <div className="hub-profile-actions">
        <button type="button" className="hub-btn primary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? <Ico.refresh width="13" height="13" className="spin" /> : <Ico.save width="13" height="13" />}
          Save profile
        </button>
      </div>
    </div>
  );
}

function AgentCortextSetupPanel({
  agent,
  saving,
  onSave,
}: {
  agent: AgentHubAgent;
  saving: boolean;
  onSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const [runtimeType, setRuntimeType] = useState(agent.runtime?.runtime_type ?? "");
  const [model, setModel] = useState(agent.runtime?.model ?? "");
  const [provider, setProvider] = useState(agent.runtime?.provider ?? "");
  const [workdir, setWorkdir] = useState(agent.runtime?.workdir ?? "");
  const [timezone, setTimezone] = useState(agent.runtime?.timezone ?? "");
  const [codexContextCap, setCodexContextCap] = useState(numberToText(agent.runtime?.codex_context_cap));
  const [contextWarning, setContextWarning] = useState(numberToText(agent.runtime?.context_warning_threshold));
  const [contextHandoff, setContextHandoff] = useState(numberToText(agent.runtime?.context_handoff_threshold));
  const [dayModeStart, setDayModeStart] = useState(agent.soul?.day_mode_start ?? "");
  const [dayModeEnd, setDayModeEnd] = useState(agent.soul?.day_mode_end ?? "");
  const [communicationStyle, setCommunicationStyle] = useState(agent.soul?.communication_style ?? "");
  const [approvalMode, setApprovalMode] = useState(agent.safety?.approval_mode ?? "confirm_external_send");
  const [alwaysAsk, setAlwaysAsk] = useState<string[]>(agent.safety?.always_ask ?? []);
  const [neverAsk, setNeverAsk] = useState<string[]>(agent.safety?.never_ask ?? []);
  const [dangerouslySkipPermissions, setDangerouslySkipPermissions] = useState(Boolean(agent.safety?.dangerously_skip_permissions));
  const [startupDelay, setStartupDelay] = useState(numberToText(agent.lifecycle?.startup_delay));
  const [maxSessionSeconds, setMaxSessionSeconds] = useState(numberToText(agent.lifecycle?.max_session_seconds));
  const [maxCrashesPerDay, setMaxCrashesPerDay] = useState(numberToText(agent.lifecycle?.max_crashes_per_day));
  const [crashWindowSeconds, setCrashWindowSeconds] = useState(numberToText(agent.lifecycle?.crash_window_seconds));
  const [crashWindowMax, setCrashWindowMax] = useState(numberToText(agent.lifecycle?.crash_window_max));
  const [telegramPolling, setTelegramPolling] = useState(agent.lifecycle?.telegram_polling ?? null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRuntimeType(agent.runtime?.runtime_type ?? "");
    setModel(agent.runtime?.model ?? "");
    setProvider(agent.runtime?.provider ?? "");
    setWorkdir(agent.runtime?.workdir ?? "");
    setTimezone(agent.runtime?.timezone ?? "");
    setCodexContextCap(numberToText(agent.runtime?.codex_context_cap));
    setContextWarning(numberToText(agent.runtime?.context_warning_threshold));
    setContextHandoff(numberToText(agent.runtime?.context_handoff_threshold));
    setDayModeStart(agent.soul?.day_mode_start ?? "");
    setDayModeEnd(agent.soul?.day_mode_end ?? "");
    setCommunicationStyle(agent.soul?.communication_style ?? "");
    setApprovalMode(agent.safety?.approval_mode ?? "confirm_external_send");
    setAlwaysAsk(agent.safety?.always_ask ?? []);
    setNeverAsk(agent.safety?.never_ask ?? []);
    setDangerouslySkipPermissions(Boolean(agent.safety?.dangerously_skip_permissions));
    setStartupDelay(numberToText(agent.lifecycle?.startup_delay));
    setMaxSessionSeconds(numberToText(agent.lifecycle?.max_session_seconds));
    setMaxCrashesPerDay(numberToText(agent.lifecycle?.max_crashes_per_day));
    setCrashWindowSeconds(numberToText(agent.lifecycle?.crash_window_seconds));
    setCrashWindowMax(numberToText(agent.lifecycle?.crash_window_max));
    setTelegramPolling(agent.lifecycle?.telegram_polling ?? null);
    setSaved(false);
    setError(null);
  }, [agent.id, agent.runtime, agent.soul, agent.safety, agent.lifecycle]);

  const baseline = JSON.stringify({
    runtimeType: agent.runtime?.runtime_type ?? "",
    model: agent.runtime?.model ?? "",
    provider: agent.runtime?.provider ?? "",
    workdir: agent.runtime?.workdir ?? "",
    timezone: agent.runtime?.timezone ?? "",
    codexContextCap: numberToText(agent.runtime?.codex_context_cap),
    contextWarning: numberToText(agent.runtime?.context_warning_threshold),
    contextHandoff: numberToText(agent.runtime?.context_handoff_threshold),
    dayModeStart: agent.soul?.day_mode_start ?? "",
    dayModeEnd: agent.soul?.day_mode_end ?? "",
    communicationStyle: agent.soul?.communication_style ?? "",
    approvalMode: agent.safety?.approval_mode ?? "confirm_external_send",
    alwaysAsk: agent.safety?.always_ask ?? [],
    neverAsk: agent.safety?.never_ask ?? [],
    dangerouslySkipPermissions: Boolean(agent.safety?.dangerously_skip_permissions),
    startupDelay: numberToText(agent.lifecycle?.startup_delay),
    maxSessionSeconds: numberToText(agent.lifecycle?.max_session_seconds),
    maxCrashesPerDay: numberToText(agent.lifecycle?.max_crashes_per_day),
    crashWindowSeconds: numberToText(agent.lifecycle?.crash_window_seconds),
    crashWindowMax: numberToText(agent.lifecycle?.crash_window_max),
    telegramPolling: agent.lifecycle?.telegram_polling ?? null,
  });
  const current = JSON.stringify({
    runtimeType,
    model,
    provider,
    workdir,
    timezone,
    codexContextCap,
    contextWarning,
    contextHandoff,
    dayModeStart,
    dayModeEnd,
    communicationStyle,
    approvalMode,
    alwaysAsk,
    neverAsk,
    dangerouslySkipPermissions,
    startupDelay,
    maxSessionSeconds,
    maxCrashesPerDay,
    crashWindowSeconds,
    crashWindowMax,
    telegramPolling,
  });
  const dirty = baseline !== current;

  const resetSaved = () => {
    setSaved(false);
    setError(null);
  };

  const toggleApproval = (bucket: "always" | "never", category: string) => {
    resetSaved();
    if (bucket === "always") {
      const isOn = alwaysAsk.includes(category);
      setAlwaysAsk((prev) => (isOn ? prev.filter((item) => item !== category) : [...prev, category]));
      if (!isOn) setNeverAsk((prev) => prev.filter((item) => item !== category));
      return;
    }
    const isOn = neverAsk.includes(category);
    setNeverAsk((prev) => (isOn ? prev.filter((item) => item !== category) : [...prev, category]));
    if (!isOn) setAlwaysAsk((prev) => prev.filter((item) => item !== category));
  };

  const setCustomApproval = (bucket: "always" | "never", value: string) => {
    resetSaved();
    const custom = textToList(value).filter((item) => !isKnownApprovalCategory(item));
    if (bucket === "always") {
      const known = alwaysAsk.filter(isKnownApprovalCategory);
      setAlwaysAsk([...known, ...custom]);
      setNeverAsk((prev) => prev.filter((item) => !custom.includes(item)));
      return;
    }
    const known = neverAsk.filter(isKnownApprovalCategory);
    setNeverAsk([...known, ...custom]);
    setAlwaysAsk((prev) => prev.filter((item) => !custom.includes(item)));
  };

  const customAlwaysAsk = alwaysAsk.filter((item) => !isKnownApprovalCategory(item));
  const customNeverAsk = neverAsk.filter((item) => !isKnownApprovalCategory(item));
  const lifecycleSummary = agent.lifecycleSummary ?? {};

  const invalidNumber = (label: string, value: string, allowZero = false) => {
    if (!value.trim()) return null;
    return textToOptionalInt(value, { allowZero }) == null ? `${label} must be a whole ${allowZero ? "non-negative" : "positive"} number.` : null;
  };

  const save = async () => {
    setError(null);
    for (const [label, value, allowZero] of [
      ["Context cap", codexContextCap, false],
      ["Warning %", contextWarning, false],
      ["Handoff %", contextHandoff, false],
      ["Startup delay", startupDelay, true],
      ["Max session seconds", maxSessionSeconds, false],
      ["Max crashes/day", maxCrashesPerDay, false],
      ["Crash window seconds", crashWindowSeconds, false],
      ["Crash window max", crashWindowMax, false],
    ] as const) {
      const message = invalidNumber(label, value, allowZero);
      if (message) {
        setError(message);
        return;
      }
    }
    if (dayModeStart.trim() && !TIME_RE.test(dayModeStart.trim())) {
      setError("Day mode start must use HH:MM 24-hour time.");
      return;
    }
    if (dayModeEnd.trim() && !TIME_RE.test(dayModeEnd.trim())) {
      setError("Day mode end must use HH:MM 24-hour time.");
      return;
    }
    const warning = textToOptionalInt(contextWarning);
    const handoff = textToOptionalInt(contextHandoff);
    if (warning != null && (warning < 1 || warning > 100)) {
      setError("Warning % must be between 1 and 100.");
      return;
    }
    if (handoff != null && (handoff < 1 || handoff > 100)) {
      setError("Handoff % must be between 1 and 100.");
      return;
    }
    if (warning != null && handoff != null && warning >= handoff) {
      setError("Warning % must be lower than Handoff %.");
      return;
    }
    try {
      await onSave({
        runtime: {
          runtime_type: runtimeType.trim(),
          model: model.trim(),
          provider: provider.trim(),
          workdir: workdir.trim(),
          timezone: timezone.trim(),
          codex_context_cap: textToOptionalInt(codexContextCap),
          context_warning_threshold: warning,
          context_handoff_threshold: handoff,
        },
        soul: {
          communication_style: communicationStyle.trim(),
          day_mode_start: dayModeStart.trim(),
          day_mode_end: dayModeEnd.trim(),
        },
        safety: {
          approval_mode: approvalMode.trim() || "confirm_external_send",
          always_ask: alwaysAsk,
          never_ask: neverAsk,
          dangerously_skip_permissions: dangerouslySkipPermissions,
        },
        lifecycle: {
          startup_delay: textToOptionalInt(startupDelay, { allowZero: true }) ?? 0,
          max_session_seconds: textToOptionalInt(maxSessionSeconds),
          max_crashes_per_day: textToOptionalInt(maxCrashesPerDay),
          crash_window_seconds: textToOptionalInt(crashWindowSeconds),
          crash_window_max: textToOptionalInt(crashWindowMax),
          telegram_polling: telegramPolling,
        },
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Settings save failed");
    }
  };

  return (
    <div className="hub-setup-panel">
      {saved && <div className="hub-save-note">Saved. Future Elevate-native runs use these agent defaults; active work is not rewritten.</div>}
      {error && <div className="hub-import-error">{error}</div>}

      <section className="hub-setup-section">
        <div className="hub-profile-section-head">
          <span>Operational Config</span>
          <small>Matches CortextOS setup, mapped into Elevate Agent Hub.</small>
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Timezone</span>
            <input className="hub-input" value={timezone} placeholder="America/New_York" onChange={(event) => { resetSaved(); setTimezone(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Communication style</span>
            <input className="hub-input" value={communicationStyle} placeholder="casual, brief, proactive" onChange={(event) => { resetSaved(); setCommunicationStyle(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Day mode start</span>
            <input className="hub-input mono" value={dayModeStart} placeholder="08:00" onChange={(event) => { resetSaved(); setDayModeStart(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Day mode end</span>
            <input className="hub-input mono" value={dayModeEnd} placeholder="00:00" onChange={(event) => { resetSaved(); setDayModeEnd(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Telegram polling</span>
            <select
              className="hub-input"
              value={telegramPolling === null ? "inherit" : telegramPolling ? "enabled" : "disabled"}
              onChange={(event) => {
                resetSaved();
                const next = event.target.value;
                setTelegramPolling(next === "inherit" ? null : next === "enabled");
              }}
            >
              <option value="inherit">Inherited</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
        </div>
      </section>

      <section className="hub-setup-section">
        <div className="hub-profile-section-head">
          <span>Runtime & Context</span>
          <small>Hard values for model defaults and context-pressure behavior.</small>
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Runtime type</span>
            <select className="hub-input" value={runtimeType} onChange={(event) => { resetSaved(); setRuntimeType(event.target.value); }}>
              <option value="">Inherited / native</option>
              <option value="native">native</option>
              <option value="codex-app-server">codex-app-server</option>
              <option value="claude-code">claude-code compat</option>
              <option value="hermes">hermes</option>
            </select>
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Model</span>
            <input className="hub-input" value={model} placeholder="Inherited" onChange={(event) => { resetSaved(); setModel(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Provider</span>
            <input className="hub-input" value={provider} placeholder="Inherited" onChange={(event) => { resetSaved(); setProvider(event.target.value); }} />
          </label>
          <label className="hub-acc-field span-2">
            <span className="hub-acc-k">Working directory</span>
            <input className="hub-input mono" value={workdir} placeholder="Inherited" onChange={(event) => { resetSaved(); setWorkdir(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Codex context cap</span>
            <input type="number" min="1" className="hub-input mono" value={codexContextCap} placeholder="256000" onChange={(event) => { resetSaved(); setCodexContextCap(event.target.value); }} />
            <small className="hub-field-help">Token cap fallback when model context is unknown.</small>
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Warning %</span>
            <input type="number" min="1" max="100" className="hub-input mono" value={contextWarning} placeholder="70" onChange={(event) => { resetSaved(); setContextWarning(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Handoff %</span>
            <input type="number" min="1" max="100" className="hub-input mono" value={contextHandoff} placeholder="80" onChange={(event) => { resetSaved(); setContextHandoff(event.target.value); }} />
          </label>
        </div>
      </section>

      <section className="hub-setup-section">
        <div className="hub-profile-section-head">
          <span>Lifecycle Limits</span>
          <small>CortextOS daemon limits translated to Elevate scheduling and worker policy.</small>
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Startup delay seconds</span>
            <input type="number" min="0" className="hub-input mono" value={startupDelay} placeholder="0" onChange={(event) => { resetSaved(); setStartupDelay(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Max session seconds</span>
            <input type="number" min="1" className="hub-input mono" value={maxSessionSeconds} placeholder="255600" onChange={(event) => { resetSaved(); setMaxSessionSeconds(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Max crashes/day</span>
            <input type="number" min="1" className="hub-input mono" value={maxCrashesPerDay} placeholder="10" onChange={(event) => { resetSaved(); setMaxCrashesPerDay(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Crash window seconds</span>
            <input type="number" min="1" className="hub-input mono" value={crashWindowSeconds} placeholder="60" onChange={(event) => { resetSaved(); setCrashWindowSeconds(event.target.value); }} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Crash window max</span>
            <input type="number" min="1" className="hub-input mono" value={crashWindowMax} placeholder="3" onChange={(event) => { resetSaved(); setCrashWindowMax(event.target.value); }} />
          </label>
          <div className="hub-setup-status">
            <span>Lifecycle state</span>
            <strong>{lifecycleSummary.suspended ? `paused: ${lifecycleSummary.reason}` : "clear"}</strong>
          </div>
        </div>
      </section>

      <section className="hub-setup-section">
        <div className="hub-profile-section-head">
          <span>Approval Rules</span>
          <small>Checkbox policy like CortextOS, enforced through Elevate approvals/waiting-human gates.</small>
        </div>
        <label className="hub-acc-field">
          <span className="hub-acc-k">Approval mode</span>
          <select className="hub-input" value={approvalMode} onChange={(event) => { resetSaved(); setApprovalMode(event.target.value); }}>
            <option value="confirm_external_send">confirm_external_send</option>
            <option value="always_ask">always_ask</option>
            <option value="never_ask">never_ask</option>
            <option value="manual">manual</option>
          </select>
        </label>
        <div className="hub-approval-grid">
          {APPROVAL_CATEGORIES.map((category) => (
            <div className="hub-approval-row" key={category}>
              <span>{APPROVAL_CATEGORY_LABELS[category]}</span>
              <label>
                <input type="checkbox" checked={alwaysAsk.includes(category)} onChange={() => toggleApproval("always", category)} />
                Always ask
              </label>
              <label>
                <input type="checkbox" checked={neverAsk.includes(category)} onChange={() => toggleApproval("never", category)} />
                Never ask
              </label>
            </div>
          ))}
        </div>
        <div className="hub-profile-grid">
          <label className="hub-acc-field">
            <span className="hub-acc-k">Custom always ask</span>
            <input className="hub-input" value={listToText(customAlwaysAsk)} placeholder="custom-category, another-rule" onChange={(event) => setCustomApproval("always", event.target.value)} />
          </label>
          <label className="hub-acc-field">
            <span className="hub-acc-k">Custom never ask</span>
            <input className="hub-input" value={listToText(customNeverAsk)} placeholder="safe-category" onChange={(event) => setCustomApproval("never", event.target.value)} />
          </label>
        </div>
        <label className="hub-toggle-row">
          <span>
            <strong>Preserve dangerously_skip_permissions</strong>
            <small>Stored for Cortext compatibility. Elevate still applies safety gates.</small>
          </span>
          <input type="checkbox" checked={dangerouslySkipPermissions} onChange={(event) => { resetSaved(); setDangerouslySkipPermissions(event.target.checked); }} />
        </label>
      </section>

      <div className="hub-profile-actions">
        <button type="button" className="hub-btn primary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? <Ico.refresh width="13" height="13" className="spin" /> : <Ico.save width="13" height="13" />}
          Save setup
        </button>
      </div>
    </div>
  );
}

type HeartbeatGoalDraft = { id?: string; title: string; progress: number; order?: number };

function isMissingHeartbeatSurfaceError(err: unknown) {
  const message = err instanceof Error ? err.message : String(err || "");
  return /No heartbeat surface/i.test(message) || /404 Not Found on \/api\/heartbeats\/surfaces\/[^/]+\/goals/i.test(message);
}

function AgentGoalsPanel({
  agent,
  routing,
}: {
  agent: AgentHubAgent;
  routing: AgentHubAgent["routing"];
}) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [bottleneck, setBottleneck] = useState("");
  const [dailyFocus, setDailyFocus] = useState("");
  const [goals, setGoals] = useState<HeartbeatGoalDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadGoals = useCallback(() => {
    setBusy(true);
    setError(null);
    api
      .getHeartbeatSurfaceGoals(agent.id)
      .then((response) => {
        setAvailable(true);
        setBottleneck(response.bottleneck || "");
        setDailyFocus(response.daily_focus || "");
        setGoals((response.goals || []).map((goal, index) => ({
          id: goal.id,
          title: goal.title,
          progress: goal.progress ?? 0,
          order: goal.order ?? index,
        })));
      })
      .catch((err) => {
        setAvailable(false);
        setError(isMissingHeartbeatSurfaceError(err) ? null : err instanceof Error ? err.message : "Goals unavailable");
      })
      .finally(() => setBusy(false));
  }, [agent.id]);

  useEffect(() => {
    loadGoals();
  }, [loadGoals]);

  const saveGoals = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.patchHeartbeatSurfaceGoals(agent.id, {
        bottleneck,
        daily_focus: dailyFocus,
        goals: goals
          .map((goal, index) => ({
            id: goal.id,
            title: goal.title.trim(),
            progress: Math.max(0, Math.min(100, Number(goal.progress) || 0)),
            order: index,
          }))
          .filter((goal) => goal.title),
      });
      setAvailable(true);
      setBottleneck(String(response.bottleneck || ""));
      setDailyFocus(String(response.daily_focus || ""));
      setGoals(((response.goals as HeartbeatGoalDraft[]) || []).map((goal, index) => ({
        id: goal.id,
        title: goal.title,
        progress: goal.progress ?? 0,
        order: goal.order ?? index,
      })));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const createGoalsSurface = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.createHeartbeatSurface({
        surface: agent.id,
        title: agent.name,
        name: agent.name,
        goal: agent.description || agent.role || "Agent work loop",
      });
      setAvailable(true);
      loadGoals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create surface failed");
      setBusy(false);
    }
  };

  if (available === false) {
    return (
      <div className="hub-agent-detail-grid">
        <FactLine label="Owned areas" value={routing?.owns?.length ? routing.owns.join(", ") : "none"} />
        <FactLine label="Escalation" value={routing?.escalation_target || "none"} />
        <FactLine label="Handoff targets" value={routing?.handoff_targets?.length ? routing.handoff_targets.join(", ") : "open"} />
        <FactLine label="Default priority" value={routing?.default_priority || "normal"} />
        {error && <div className="hub-import-error">{error}</div>}
        <button type="button" className="hub-btn primary sm" onClick={createGoalsSurface} disabled={busy}>
          {busy ? <Ico.refresh width="13" height="13" className="spin" /> : <Ico.plus width="13" height="13" />}
          Create heartbeat surface
        </button>
        <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>
          Open Heartbeat
        </Link>
      </div>
    );
  }

  return (
    <div className="hub-agent-goals">
      <div className="hub-agent-detail-grid">
        <label className="hub-acc-field">
          <span className="hub-acc-k">Daily focus</span>
          <input className="hub-input" value={dailyFocus} onChange={(event) => setDailyFocus(event.target.value)} />
        </label>
        <label className="hub-acc-field">
          <span className="hub-acc-k">Bottleneck</span>
          <input className="hub-input" value={bottleneck} onChange={(event) => setBottleneck(event.target.value)} />
        </label>
        <FactLine label="Owned areas" value={routing?.owns?.length ? routing.owns.join(", ") : "none"} />
        <FactLine label="Default priority" value={routing?.default_priority || "normal"} />
      </div>
      <div className="hub-agent-goal-list">
        {goals.map((goal, index) => (
          <div className="hub-agent-goal-row" key={goal.id || index}>
            <input
              className="hub-input"
              value={goal.title}
              onChange={(event) => setGoals((items) => items.map((item, i) => (i === index ? { ...item, title: event.target.value } : item)))}
            />
            <input
              className="hub-input goal-progress"
              type="number"
              min={0}
              max={100}
              value={goal.progress}
              onChange={(event) => setGoals((items) => items.map((item, i) => (i === index ? { ...item, progress: Number(event.target.value) || 0 } : item)))}
            />
            <button
              type="button"
              className="hub-icon-btn"
              aria-label="Remove goal"
              onClick={() => setGoals((items) => items.filter((_, i) => i !== index))}
            >
              <Ico.x width="13" height="13" />
            </button>
          </div>
        ))}
        {!goals.length && <div className="hub-handoff-empty">No goals yet</div>}
      </div>
      {error && <div className="hub-import-error">{error}</div>}
      <div className="hub-agent-goal-actions">
        <button
          type="button"
          className="hub-btn ghost sm"
          onClick={() => setGoals((items) => [...items, { title: "", progress: 0, order: items.length }])}
        >
          <Ico.plus width="13" height="13" />
          Add goal
        </button>
        <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>
          Open Heartbeat
        </Link>
        <button type="button" className="hub-btn primary sm" onClick={saveGoals} disabled={busy}>
          {busy ? <Ico.refresh width="13" height="13" className="spin" /> : null}
          Save goals
        </button>
      </div>
    </div>
  );
}

function AgentTasksPanel({
  agent,
  data,
  loading,
}: {
  agent: AgentHubAgent;
  data: AgentDetailData;
  loading: boolean;
}) {
  const openHandoffs = data.handoffs
    .filter((handoff) => !["completed", "failed", "cancelled"].includes(String(handoff.status)))
    .slice(0, 6);
  const recentTasks = data.tasks.slice(0, 6);
  return (
    <div className="hub-detail-stack">
      <div className="hub-mini3">
        <MiniMetric label="Tasks" value={data.tasks.length} />
        <MiniMetric label="Incoming" value={data.incomingHandoffs.length} />
        <MiniMetric label="Outgoing" value={data.outgoingHandoffs.length} />
      </div>
      {loading ? (
        <ListSkeleton rows={3} />
      ) : (
        <>
          <div className="hub-detail-split">
            <div className="hub-detail-list">
              <div className="hub-detail-list-title">Assigned tasks</div>
              {recentTasks.length ? recentTasks.map((task) => (
                <div className="hub-detail-row" key={task.id}>
                  <div className="hub-detail-row-main">
                    <span>{task.title}</span>
                    <small>{task.project || task.assignee || agent.id}</small>
                  </div>
                  <DetailPill tone={task.status === "blocked" ? "warn" : task.status === "completed" ? "ok" : "neutral"}>
                    {task.status.replace("_", " ")}
                  </DetailPill>
                </div>
              )) : <DetailEmpty>No tasks assigned to this agent.</DetailEmpty>}
            </div>
            <div className="hub-detail-list">
              <div className="hub-detail-list-title">Agent handoffs</div>
              {openHandoffs.length ? openHandoffs.map((handoff) => (
                <Link
                  className="hub-detail-row link"
                  key={handoff.id}
                  to={`/comms?agent=${encodeURIComponent(handoff.toAgentId)}`}
                >
                  <div className="hub-detail-row-main">
                    <span>{handoff.title}</span>
                    <small>{handoff.fromAgentId} → {handoff.toAgentId}</small>
                  </div>
                  <DetailPill tone={handoff.status === "waiting_human" ? "warn" : "neutral"}>
                    {String(handoff.status).replace("_", " ")}
                  </DetailPill>
                </Link>
              )) : <DetailEmpty>No open handoffs.</DetailEmpty>}
            </div>
          </div>
          <div className="hub-detail-actions">
            <Link className="hub-btn ghost sm" to={`/tasks?agent=${encodeURIComponent(agent.id)}`}>Open Tasks</Link>
            <Link className="hub-btn ghost sm" to={`/comms?agent=${encodeURIComponent(agent.id)}`}>Open Comms</Link>
          </div>
        </>
      )}
    </div>
  );
}

function AgentAutomationsPanel({
  agent,
  data,
  loading,
  refresh,
  surfaceKey,
}: {
  agent: AgentHubAgent;
  data: AgentDetailData;
  loading: boolean;
  refresh: () => Promise<void>;
  surfaceKey: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const runCron = async (job: CronJob) => {
    setBusy(job.id);
    try {
      await api.triggerCronJob(job.id);
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const toggleCron = async (job: CronJob) => {
    setBusy(job.id);
    try {
      if (job.enabled) await api.pauseCronJob(job.id);
      else await api.resumeCronJob(job.id);
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const createHeartbeat = async () => {
    setBusy("heartbeat");
    try {
      await api.createHeartbeatSurface({ surface: surfaceKey, title: agent.name, name: agent.name });
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="hub-detail-stack">
      <div className="hub-agent-detail-grid">
        <FactLine label="Heartbeat" value={data.heartbeat ? (data.heartbeat.config?.enabled ? "enabled" : "paused") : "not created"} />
        <FactLine label="Heartbeat runs" value={data.heartbeat?.runCount ?? 0} />
        <FactLine label="Last run" value={data.heartbeat?.lastRun?.ran_at ? isoTimeAgo(String(data.heartbeat.lastRun.ran_at)) : "never"} />
        <FactLine label="Cron jobs" value={data.cronJobs.length} />
      </div>
      {data.heartbeat?.lastRun?.summary && (
        <div className="hub-detail-note">
          <span>Last heartbeat</span>
          <p>{String(data.heartbeat.lastRun.summary)}</p>
        </div>
      )}
      {loading ? (
        <ListSkeleton rows={3} />
      ) : (
        <div className="hub-detail-list">
          <div className="hub-detail-list-title">Assigned cron jobs</div>
          {data.cronJobs.length ? data.cronJobs.slice(0, 8).map((job) => (
            <div className="hub-detail-row" key={job.id}>
              <div className="hub-detail-row-main">
                <span>{job.name || job.prompt.slice(0, 56) || job.id}</span>
                <small>{job.schedule_display || job.schedule?.display || "manual"} · {job.last_run_at ? `last ${isoTimeAgo(job.last_run_at)}` : "never run"}</small>
              </div>
              <div className="hub-detail-row-actions">
                {job.last_error && <DetailPill tone="bad">error</DetailPill>}
                <button type="button" className="hub-btn ghost sm" disabled={busy === job.id} onClick={() => void toggleCron(job)}>
                  {job.enabled ? "Pause" : "Resume"}
                </button>
                <button type="button" className="hub-btn ghost sm" disabled={busy === job.id} onClick={() => void runCron(job)}>
                  Run
                </button>
              </div>
            </div>
          )) : <DetailEmpty>No cron jobs assigned to this agent.</DetailEmpty>}
        </div>
      )}
      <div className="hub-detail-actions">
        {!data.heartbeat && (
          <button type="button" className="hub-btn primary sm" disabled={busy === "heartbeat"} onClick={() => void createHeartbeat()}>
            <Ico.plus width="13" height="13" />Create heartbeat
          </button>
        )}
        <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>Open Heartbeat</Link>
        <Link className="hub-btn ghost sm" to={`/cron?agent=${encodeURIComponent(agent.id)}`}>Open Cron</Link>
      </div>
    </div>
  );
}

function AgentMemoryPanel({
  agent,
  data,
  memory,
}: {
  agent: AgentHubAgent;
  data: AgentDetailData;
  memory: AgentHubAgent["memorySummary"];
}) {
  const cfg = agent.memory ?? { scopes: [], sources: [] };
  return (
    <div className="hub-detail-stack">
      <div className="hub-agent-detail-grid">
        <FactLine label="Mode" value={memory?.mode || cfg.mode || "shared_scoped"} />
        <FactLine label="Scopes" value={(memory?.scopes ?? cfg.scopes ?? []).join(", ") || "shared"} />
        <FactLine label="Sources" value={(memory?.sources ?? cfg.sources ?? []).join(", ") || "default"} />
        <FactLine label="Recall" value={memory?.recallPolicy || cfg.recall_policy || "agent_scoped_recent"} />
        <FactLine label="Write" value={memory?.writePolicy || cfg.write_policy || "append_events"} />
        <FactLine label="Handoff" value={memory?.handoffPolicy || cfg.handoff_policy || "summary_only"} />
        <FactLine label="Facts" value={memory?.nativeFactsCapped ? `${memory.nativeFacts ?? 0}+` : memory?.nativeFacts ?? 0} />
        <FactLine label="Last write" value={memory?.lastMemoryAt ? isoTimeAgo(memory.lastMemoryAt) : "none"} />
      </div>
      <div className="hub-detail-list">
        <div className="hub-detail-list-title">Recent memory</div>
        {memory?.recentFacts?.length ? memory.recentFacts.map((item, index) => {
          const fact = shortText(item.fact, "Memory fact");
          const label = fact.length > 120 ? `${fact.slice(0, 117)}...` : fact;
          return (
            <div className="hub-detail-row" key={`${item.id || item.ts || "memory"}-${index}`}>
              <div className="hub-detail-row-main">
                <span>{label}</span>
                <small>{item.source || "memory"} · {item.ts ? isoTimeAgo(item.ts) : "unknown"}</small>
              </div>
            </div>
          );
        }) : <DetailEmpty>No native memory facts recorded yet.</DetailEmpty>}
      </div>
      <div className="hub-detail-note">
        <span>Heartbeat learnings</span>
        {data.heartbeat?.learnings?.trim() ? (
          <p>{data.heartbeat.learnings}</p>
        ) : (
          <p>No heartbeat learnings recorded yet.</p>
        )}
      </div>
      <div className="hub-detail-actions">
        <Link className="hub-btn ghost sm" to="/memory">Open Memory</Link>
        <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>Open Heartbeat Memory</Link>
      </div>
    </div>
  );
}

function AgentActivityPanel({
  agent,
  data,
  context,
  obs,
  loading,
}: {
  agent: AgentHubAgent;
  data: AgentDetailData;
  context: AgentHubAgent["contextPressure"];
  obs: AgentHubAgent["observability"];
  loading: boolean;
}) {
  return (
    <div className="hub-detail-stack">
      <div className="hub-agent-detail-grid">
        <FactLine label="Last scoped tick" value={obs?.lastScopedTickAt ? isoTimeAgo(obs.lastScopedTickAt) : "none"} />
        <FactLine label="Last wake" value={obs?.lastWakeAt ? isoTimeAgo(obs.lastWakeAt) : "none"} />
        <FactLine label="Approval blockers" value={data.approvals.length || obs?.approvalBlockers || 0} />
        <FactLine label="Context pressure" value={context?.percent != null ? `${context.percent}%` : "no event"} />
        <FactLine label="Context event" value={context?.lastEventAt ? `${context.kind} · ${isoTimeAgo(context.lastEventAt)}` : "none"} />
        <FactLine label="Activity rows" value={data.activity.length} />
      </div>
      <div className="hub-detail-split">
        <div className="hub-detail-list">
          <div className="hub-detail-list-title">Recent activity</div>
          {loading ? <ListSkeleton rows={3} /> : data.activity.length ? data.activity.map((item, index) => (
            <div className="hub-detail-row" key={`${item.ts}-${item.kind}-${index}`}>
              <div className="hub-detail-row-main">
                <span>{shortText(item.title, item.kind)}</span>
                <small>{item.detail || item.kind} · {item.ts ? isoTimeAgo(item.ts) : "unknown"}</small>
              </div>
              {item.status && <DetailPill>{item.status}</DetailPill>}
            </div>
          )) : <DetailEmpty>No recent activity for this agent.</DetailEmpty>}
        </div>
        <div className="hub-detail-list">
          <div className="hub-detail-list-title">Pending approvals</div>
          {data.approvals.length ? data.approvals.slice(0, 6).map((approval) => (
            <Link className="hub-detail-row link" key={approval.id} to="/approvals">
              <div className="hub-detail-row-main">
                <span>{approval.title}</span>
                <small>{approval.category} · {approval.createdAt ? isoTimeAgo(approval.createdAt) : "pending"}</small>
              </div>
              <DetailPill tone="warn">{approval.status}</DetailPill>
            </Link>
          )) : <DetailEmpty>No pending approvals.</DetailEmpty>}
        </div>
      </div>
      <div className="hub-detail-actions">
        <Link className="hub-btn ghost sm" to={`/activity?agent=${encodeURIComponent(agent.id)}`}>Open Activity</Link>
        <Link className="hub-btn ghost sm" to="/approvals">Open Approvals</Link>
      </div>
    </div>
  );
}

function AgentDetailWorkspace({
  agent,
  activeTab,
  onTabChange,
  savingConfig,
  onConfigSave,
}: {
  agent: AgentHubAgent;
  activeTab: AgentDetailTab;
  onTabChange: (tab: AgentDetailTab) => void;
  savingConfig: boolean;
  onConfigSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const routing = agent.routing ?? { owns: [], handoff_targets: [] };
  const memory = agent.memorySummary ?? {
    scopes: agent.memory?.scopes ?? [],
    sources: agent.memory?.sources ?? [],
  };
  const context = agent.contextPressure;
  const obs = agent.observability;
  const detail = useAgentDetailData(agent.id);

  return (
    <div className="hub-agent-detail">
      <div className="hub-agent-tabs" role="tablist" aria-label={`${agent.name} detail`}>
        {AGENT_DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={"hub-agent-tab" + (activeTab === tab.id ? " active" : "")}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="hub-agent-detail-body">
        {activeTab === "profile" && (
          <AgentProfileForm agent={agent} saving={savingConfig} onSave={onConfigSave} />
        )}
        {activeTab === "tasks" && (
          <AgentTasksPanel agent={agent} data={detail.data} loading={detail.loading} />
        )}
        {activeTab === "automations" && (
          <AgentAutomationsPanel
            agent={agent}
            data={detail.data}
            loading={detail.loading}
            refresh={detail.refresh}
            surfaceKey={detail.surfaceKey}
          />
        )}
        {activeTab === "memory" && (
          <AgentMemoryPanel agent={agent} data={detail.data} memory={memory} />
        )}
        {activeTab === "activity" && (
          <AgentActivityPanel agent={agent} data={detail.data} context={context} obs={obs} loading={detail.loading} />
        )}
        {activeTab === "goals" && (
          <AgentGoalsPanel agent={agent} routing={routing} />
        )}
        {detail.error && <div className="hub-import-error">{detail.error}</div>}
        {activeTab === "settings" && (
          <AgentCortextSetupPanel agent={agent} saving={savingConfig} onSave={onConfigSave} />
        )}
      </div>
    </div>
  );
}

type AgentCardProps = {
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
  workerBusy: boolean;
  onRunQueuedWork: (agentId: string) => void;
  onWakeAgent: (agentId: string) => void;
  onDeleteAgent: (agent: AgentHubAgent) => void;
};

type AgentWorkspaceTab = "overview" | "telegram" | "loops";

function AgentEnabledToggle({
  agent,
  saving,
  onChange,
}: {
  agent: AgentHubAgent;
  saving: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const label = agent.enabled ? "On" : "Off";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={agent.enabled}
      aria-label={`${agent.enabled ? "Suspend" : "Enable"} ${agent.name}`}
      className={"hub-power-toggle" + (agent.enabled ? " on" : "")}
      disabled={saving}
      onClick={() => onChange(!agent.enabled)}
    >
      <span>{label}</span>
      <span className={"hub-switch" + (agent.enabled ? " on" : "")} aria-hidden="true">
        <span className="hub-switch-knob" />
      </span>
    </button>
  );
}

// ── agent card (scan-first page card; details live in the workspace modal) ──
function AgentCard({
  agent,
  isPrimary,
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
  workerBusy,
  onRunQueuedWork,
  onWakeAgent,
  onDeleteAgent,
}: AgentCardProps) {
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<AgentDetailTab>("profile");
  const active = agent.status === "active" || agent.status === "online" || agent.status === "ready";
  const np = agent.platforms.length;
  const nt = agent.toolsets.length;
  const ns = agent.skills.length;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const queue = agent.queueSummary ?? EMPTY_AGENT_QUEUE_SUMMARY;
  const runtime = agent.runtime ?? {};
  const safety = agent.safety ?? { always_ask: [], never_ask: [] };
  const identity = agent.identity ?? {};
  const soul = agent.soul ?? {};
  const openQueue = queue.queued + queue.running + queue.waitingHuman;
  const avatar = identity.emoji || agent.name.trim().slice(0, 1).toUpperCase() || "A";
  const dayWindow =
    soul.day_mode_start || soul.day_mode_end
      ? `${soul.day_mode_start || "--"}-${soul.day_mode_end || "--"}`
      : "day/night inherited";
  const telegramStatus = agent.telegramLane?.error
    ? "Telegram needs attention"
    : agent.telegramLane?.tokenConfigured && agent.telegramLane?.targetConfigured
      ? "Telegram ready"
      : agent.telegramLane?.usesSharedBot && agent.telegramLane?.targetConfigured
        ? "Shared bot ready"
        : "Telegram not configured";
  const telegramTone = agent.telegramLane?.error
    ? "bad"
      : agent.telegramLane?.targetConfigured
        ? "ok"
        : "warn";
  return (
    <div className={"hub-agent" + (!agent.enabled ? " is-disabled" : "")}>
      <div className="hub-agent-head">
        <div className="hub-agent-identity">
          <div className="hub-agent-avatar" aria-hidden="true">{avatar}</div>
          <div className="hub-agent-titleblock">
            <div className="hub-agent-name">
              {agent.name}
              {isPrimary && <span className="hub-agent-badge mono">Main agent</span>}
            </div>
            <div className="hub-agent-roleline">
              <span>{agent.role || "support"}</span>
              <span>{runtime.runtime_type || "native"}</span>
              <span>{dayWindow}</span>
            </div>
          </div>
        </div>
        <div className="hub-agent-head-right">
          <span className={"hub-agent-status " + (active ? "ok" : "warn")}>
            <span className="hub-agent-status-dot" />
            {STATUS_COPY[agent.status] ?? agent.status}
          </span>
          <AgentEnabledToggle
            agent={agent}
            saving={savingConfig}
            onChange={(enabled) => void onConfigSave({ enabled })}
          />
        </div>
      </div>
      <div className="hub-agent-desc">{agent.description || agent.role}</div>
      <div className="hub-agent-meta mono">
        {agent.active_session_count > 0 && <span className="active">{agent.active_session_count} active</span>}
        {agent.session_count > 0 && <span>{plural(agent.session_count, "session")}</span>}
        <span>{plural(np, "platform")}</span>
        <span>{nt ? plural(nt, "tool") : "global tools"}</span>
        <span>{plural(ns, "skill")}</span>
      </div>
      <div className="hub-agent-glance mono">
        <span>{runtime.model || "inherited model"}</span>
        <span className={telegramTone}>{telegramStatus}</span>
        <span>{openQueue ? `${openQueue} queue` : "queue clear"}</span>
        <span>{safety.approval_mode || "confirm_external_send"}</span>
      </div>
      <div className="hub-agent-actions">
        <button
          type="button"
          className="hub-btn primary sm"
          disabled={savingConfig}
          onClick={() => setWorkspaceOpen(true)}
        >
          <Ico.gear width="13" height="13" />Open agent
        </button>
        <button
          type="button"
          className="hub-btn ghost sm"
          disabled={workerBusy}
          onClick={() => onRunQueuedWork(agent.id)}
        >
          <Ico.refresh width="13" height="13" className={workerBusy ? "spin" : ""} />Run queued work
        </button>
        <button
          type="button"
          className="hub-btn ghost sm"
          disabled={workerBusy}
          onClick={() => onWakeAgent(agent.id)}
        >
          <Ico.play width="12" height="12" />Wake agent
        </button>
        <Link className="hub-btn ghost sm" to={`/comms?agent=${encodeURIComponent(agent.id)}`}>
          <Ico.chat width="13" height="13" />Comms
        </Link>
      </div>
      {workspaceOpen && (
        <AgentWorkspaceModal
          agent={agent}
          isPrimary={isPrimary}
          savingConfig={savingConfig}
          onConfigSave={onConfigSave}
          telegramBotTokenPlaceholder={telegramBotTokenPlaceholder}
          telegramBotTokenValue={telegramBotTokenValue}
          telegramLanePlaceholder={telegramLanePlaceholder}
          telegramLaneValue={telegramLaneValue}
          onTelegramBotTokenChange={onTelegramBotTokenChange}
          onTelegramLaneChange={onTelegramLaneChange}
          onTelegramLaneSave={onTelegramLaneSave}
          savingTelegram={savingTelegram}
          workerBusy={workerBusy}
          onRunQueuedWork={onRunQueuedWork}
          onWakeAgent={onWakeAgent}
          onDeleteAgent={onDeleteAgent}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          onClose={() => setWorkspaceOpen(false)}
        />
      )}
    </div>
  );
}

function AgentWorkspaceModal({
  agent,
  isPrimary,
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
  workerBusy,
  onRunQueuedWork,
  onWakeAgent,
  onDeleteAgent,
  activeTab,
  onTabChange,
  onClose,
}: Omit<AgentCardProps, "availableSkills" | "availableToolsets" | "availablePlatforms"> & {
  activeTab: AgentDetailTab;
  onTabChange: (tab: AgentDetailTab) => void;
  onClose: () => void;
}) {
  const [workspaceTab, setWorkspaceTab] = useState<AgentWorkspaceTab>("overview");
  const active = agent.status === "active" || agent.status === "online" || agent.status === "ready";
  const identity = agent.identity ?? {};
  const avatar = identity.emoji || agent.name.trim().slice(0, 1).toUpperCase() || "A";

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
      aria-labelledby={`hub-agent-modal-title-${agent.id}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="hub-modal hub-agent-modal">
        <button type="button" className="hub-modal-close" aria-label="Close" onClick={onClose}>
          <Ico.x width="16" height="16" />
        </button>
        <div className="hub-modal-head">
          <div className="hub-modal-crumb mono">
            Agent Hub <span className="sep">/</span> {isPrimary ? "Main agent" : "Team agent"}
          </div>
          <div className="hub-agent-modal-titleline">
            <div className="hub-agent-avatar lg" aria-hidden="true">{avatar}</div>
            <div>
              <h2 id={`hub-agent-modal-title-${agent.id}`} className="hub-modal-title">{agent.name}</h2>
              <div className="hub-modal-sub">{agent.description || agent.role || "Agent configuration workspace"}</div>
            </div>
            <span className={"hub-agent-status " + (active ? "ok" : "warn")}>
              <span className="hub-agent-status-dot" />
              {STATUS_COPY[agent.status] ?? agent.status}
            </span>
          </div>
          <div className="hub-agent-modal-actions">
            <AgentEnabledToggle
              agent={agent}
              saving={savingConfig}
              onChange={(enabled) => void onConfigSave({ enabled })}
            />
            <button
              type="button"
              className="hub-btn ghost sm"
              disabled={workerBusy}
              onClick={() => onRunQueuedWork(agent.id)}
            >
              <Ico.refresh width="13" height="13" className={workerBusy ? "spin" : ""} />Run queued work
            </button>
            <button
              type="button"
              className="hub-btn ghost sm"
              disabled={workerBusy}
              onClick={() => onWakeAgent(agent.id)}
            >
              <Ico.play width="12" height="12" />Wake agent
            </button>
            <Link className="hub-btn ghost sm" to={`/comms?agent=${encodeURIComponent(agent.id)}`}>
              <Ico.chat width="13" height="13" />Comms
            </Link>
            <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>Heartbeat</Link>
            {agent.canDelete ? (
              <button
                type="button"
                className="hub-btn ghost sm danger"
                disabled={savingConfig}
                onClick={() => onDeleteAgent(agent)}
              >
                Delete
              </button>
            ) : null}
          </div>
          <div className="hub-modal-tabs" role="tablist" aria-label={`${agent.name} workspace`}>
            {[
              ["overview", "Overview"],
              ["telegram", "Telegram"],
              ["loops", "Loops"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={workspaceTab === id}
                className={"hub-modal-tab" + (workspaceTab === id ? " active" : "")}
                onClick={() => setWorkspaceTab(id as AgentWorkspaceTab)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="hub-modal-body">
          {workspaceTab === "overview" && (
            <AgentDetailWorkspace
              agent={agent}
              activeTab={activeTab}
              onTabChange={onTabChange}
              savingConfig={savingConfig}
              onConfigSave={onConfigSave}
            />
          )}
          {workspaceTab === "telegram" && (
            <div className="hub-detail-stack">
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
                defaultOpen
              />
              <div className="hub-detail-actions">
                <Link className="hub-btn ghost sm" to={`/comms?agent=${encodeURIComponent(agent.id)}`}>Open Comms</Link>
                <Link className="hub-btn ghost sm" to="/config">Open Gateway Settings</Link>
              </div>
            </div>
          )}
          {workspaceTab === "loops" && (
            <div className="hub-detail-stack">
              <AgentLoops agentId={agent.id} agentName={agent.name} defaultOpen />
              <div className="hub-detail-actions">
                <Link className="hub-btn ghost sm" to={`/heartbeat?agent=${encodeURIComponent(agent.id)}`}>Open Heartbeat</Link>
                <Link className="hub-btn ghost sm" to={`/cron?agent=${encodeURIComponent(agent.id)}`}>Open Cron</Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
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

type AgentCreatePayload = {
  [key: string]: unknown;
  id?: string;
  name: string;
  description?: string;
  role?: string;
  enabled?: boolean;
  platforms?: string[];
  session_sources?: string[];
  prompt?: string;
  skills?: string[];
  toolsets?: string[];
  metadata?: Record<string, unknown>;
  heartbeatGoalsSeed?: {
    bottleneck?: string;
    daily_focus?: string;
    goals?: HeartbeatGoalDraft[];
  };
  heartbeatSurfaceSeed?: {
    schedule?: string;
    goal?: string;
    experiment?: Record<string, unknown>;
    config?: Record<string, unknown>;
  };
  cronSeeds?: Array<{
    name: string;
    prompt: string;
    schedule: string;
    deliver?: string;
    agent?: string;
    model?: string | null;
    provider?: string | null;
    base_url?: string | null;
    workdir?: string | null;
    enabled?: boolean;
    origin?: { type?: string; source?: string; [k: string]: unknown } | null;
  }>;
  onboardingTaskSeed?: {
    title: string;
    description: string;
  };
  memorySeed?: {
    content: string;
    source?: string;
    scopes?: string[];
  };
};

type CortextAgentPack = {
  id: string;
  name: string;
  role: string;
  description: string;
  sourcePath: string;
  sourceExists: boolean;
  includes: string[];
  automationCount: number;
  payload: AgentCreatePayload;
};

function stripCortextImportSecrets(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripCortextImportSecrets);
  if (!value || typeof value !== "object") return value;
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    const lower = key.toLowerCase().replace(/-/g, "_");
    if (
      (lower.includes("token") && !lower.endsWith("_env")) ||
      lower.includes("secret") ||
      lower.includes("api_key") ||
      lower.includes("apikey") ||
      lower.includes("password") ||
      lower === "pm2" ||
      lower === "daemon" ||
      lower === "ipc" ||
      lower === "pty" ||
      lower === "file_inbox" ||
      lower === "fileinbox" ||
      lower === "fast_checker" ||
      lower.startsWith("daemon_") ||
      lower.startsWith("pm2_") ||
      lower.startsWith("ipc_") ||
      lower.startsWith("pty_")
    ) {
      continue;
    }
    out[key] = stripCortextImportSecrets(item);
  }
  return out;
}

const CORTEXT_IMPORT_IGNORED_FILES = new Set(["claude.md"]);

const CORTEXT_NATIVE_REPLACEMENTS = [
  "daemon -> Elevate desktop backend + agent worker",
  "IPC -> dashboard HTTP/WebSocket APIs",
  "PM2 -> desktop process + heartbeat/cron schedulers",
  "PTY injection -> prompt/tool contracts",
  "file inbox -> Comms, handoffs, Tasks, Activity",
];

const AGENT_ADD_TEMPLATES: Array<{
  id: string;
  label: string;
  defaultName: string;
  description: string;
  payload: Partial<AgentCreatePayload>;
}> = [
  {
    id: "operator",
    label: "Admin Operator",
    defaultName: "Operations Agent",
    description: "Owns queue work, handoffs, task hygiene, and approval-ready admin follow-through.",
    payload: {
      role: "admin",
      enabled: true,
      platforms: ["local", "telegram"],
      session_sources: ["cli", "cron", "telegram"],
      skills: ["admin-agent", "deal-matcher", "admin-result-writer", "surface-heartbeat"],
      toolsets: ["agent_bus", "agent_handoff", "memory", "todo", "deals_overview", "elevate_db", "admin_deal"],
      runtime: {
        runtime_type: "native",
        timezone: "America/Vancouver",
        context_warning_threshold: 70,
        context_handoff_threshold: 88,
        codex_context_cap: 160000,
      },
      routing: {
        owns: ["admin-operations", "tasks", "calendar", "deal-files", "approvals-support"],
        handoff_targets: ["executive-assistant"],
        escalation_target: "executive-assistant",
        default_priority: "normal",
      },
      safety: {
        approval_mode: "confirm_external_send",
        always_ask: ["external_send", "destructive_action", "financial", "legal", "data_deletion", "credential_change"],
        never_ask: ["local_read", "status_check", "summarize", "draft_only"],
      },
      identity: {
        emoji: "O",
        vibe: "Calm, practical operator",
        work_style: "Turn ambiguous admin work into visible tasks, evidence, and concise handoff results.",
      },
      soul: {
        autonomy_rules: "Drafting, local organization, status checks, and evidence gathering are allowed. External sends, deletion, financial/legal work, deployments, and credential changes require approval.",
        communication_style: "Blocker-first, concise, and operational.",
        day_mode: "Review task queues, deadline risks, waiting-human items, and active operational blockers.",
        night_mode: "Process safe queued work, prepare summaries, and avoid external sends unless approved.",
        day_mode_start: "08:00",
        day_mode_end: "18:00",
        core_truths: "Use Elevate-native Tasks, Comms, Activity, Approvals, memory, heartbeats, and handoffs. Never rely on daemon, IPC, PM2, PTY injection, or file inbox behavior.",
      },
      lifecycle: {
        startup_delay: 0,
        max_session_seconds: 5400,
        max_crashes_per_day: 3,
        crash_window_seconds: 86400,
        crash_window_max: 3,
        telegram_polling: true,
      },
      ecosystem: {
        local_version_control: false,
        upstream_sync: false,
        catalog_browse: false,
        community_publish: false,
      },
      memory: {
        mode: "agent_scoped",
        scopes: ["admin", "operations", "tasks", "approvals"],
        sources: ["agent-hub-template", "elevate-native"],
        recall_policy: "agent_scoped_recent",
        write_policy: "append_events",
        handoff_policy: "summary_only",
      },
      heartbeatGoalsSeed: {
        bottleneck: "No heartbeat history yet.",
        daily_focus: "Keep admin queues, handoffs, and blockers visible.",
        goals: [
          { title: "Review waiting-human blockers", progress: 0 },
          { title: "Return concise handoff results", progress: 0 },
          { title: "Keep tasks clean", progress: 0 },
        ],
      },
      heartbeatSurfaceSeed: {
        schedule: "0 */4 * * *",
        goal: "Run a native Admin Operator loop for task hygiene, blockers, and handoff closeout.",
      },
      onboardingTaskSeed: {
        title: "Onboard Operations Agent",
        description: "Confirm routing, safety rules, Telegram lane, and first heartbeat goals before assigning live work.",
      },
    },
  },
  {
    id: "research",
    label: "Analyst",
    defaultName: "Analyst",
    description: "Tracks findings, system signals, repo/catalog updates, and native task summaries.",
    payload: {
      role: "analyst",
      enabled: true,
      platforms: ["local"],
      session_sources: ["cli", "cron"],
      skills: ["autoresearch", "catalog-browse", "system-diagnostics", "theta-wave", "surface-heartbeat"],
      toolsets: ["agent_bus", "agent_handoff", "memory", "skills", "todo"],
      runtime: {
        runtime_type: "native",
        timezone: "America/Vancouver",
        context_warning_threshold: 72,
        context_handoff_threshold: 90,
        codex_context_cap: 160000,
      },
      routing: {
        owns: ["system-health", "metrics", "research", "catalog-review"],
        handoff_targets: ["executive-assistant", "theta-wave"],
        escalation_target: "executive-assistant",
        default_priority: "normal",
      },
      safety: {
        approval_mode: "confirm_external_send",
        always_ask: ["external_send", "deployment", "credential_change", "data_deletion"],
        never_ask: ["local_read", "status_check", "summarize", "draft_only"],
      },
      identity: {
        emoji: "A",
        vibe: "Curious systems analyst",
        work_style: "Inspect evidence, summarize the important signal, and hand off only actionable deltas.",
      },
      soul: {
        autonomy_rules: "May inspect local/native system state and summarize. Must ask before external sends, deployments, deletion, or credential work.",
        communication_style: "Evidence first, terse, with uncertainty called out.",
        day_mode: "Review signals, task queues, upstream/catalg changes, and system health.",
        night_mode: "Prepare summaries and low-risk research notes.",
        day_mode_start: "08:00",
        day_mode_end: "18:00",
        core_truths: "Analyst improves visibility. It does not operate daemon sessions or create duplicate stores.",
      },
      lifecycle: {
        startup_delay: 0,
        max_session_seconds: 5400,
        max_crashes_per_day: 3,
        crash_window_seconds: 86400,
        crash_window_max: 3,
        telegram_polling: false,
      },
      ecosystem: {
        local_version_control: true,
        upstream_sync: false,
        catalog_browse: true,
        community_publish: false,
      },
      memory: {
        mode: "agent_scoped",
        scopes: ["analyst", "system-health", "catalog", "research"],
        sources: ["agent-hub-template", "elevate-native"],
        recall_policy: "agent_scoped_recent",
        write_policy: "append_events",
        handoff_policy: "facts_only",
      },
      heartbeatGoalsSeed: {
        bottleneck: "No analysis loop has run yet.",
        daily_focus: "Find useful deltas and hand off only what needs action.",
        goals: [
          { title: "Review native system signals", progress: 0 },
          { title: "Summarize actionable deltas", progress: 0 },
          { title: "Feed Theta Wave when needed", progress: 0 },
        ],
      },
      heartbeatSurfaceSeed: {
        schedule: "0 */4 * * *",
        goal: "Run a native Analyst loop for system signals, catalog review, and actionable deltas.",
      },
      onboardingTaskSeed: {
        title: "Onboard Analyst",
        description: "Confirm analysis scope, native tools, memory scopes, and escalation targets.",
      },
    },
  },
  {
    id: "theta-wave",
    label: "Theta Wave",
    defaultName: "Theta Wave",
    description: "Challenges weak loops, stale assumptions, and system regressions without owning daemon processes.",
    payload: {
      role: "system-review",
      enabled: true,
      platforms: ["local"],
      session_sources: ["cli", "cron"],
      skills: ["theta-wave", "surface-heartbeat", "system-diagnostics"],
      toolsets: ["agent_bus", "agent_handoff", "memory", "todo"],
      runtime: {
        runtime_type: "native",
        timezone: "America/Vancouver",
        context_warning_threshold: 72,
        context_handoff_threshold: 90,
        codex_context_cap: 160000,
      },
      routing: {
        owns: ["theta-wave", "system-review", "experiments", "fleet-improvement"],
        handoff_targets: ["executive-assistant", "analyst"],
        escalation_target: "executive-assistant",
        default_priority: "high",
      },
      safety: {
        approval_mode: "confirm_external_send",
        always_ask: ["external_send", "deployment", "destructive_action", "data_deletion"],
        never_ask: ["local_read", "status_check", "summarize", "draft_only"],
      },
      identity: {
        emoji: "Θ",
        vibe: "Contrarian reviewer",
        work_style: "Challenge assumptions, classify weak loops, and propose concrete native fixes.",
      },
      soul: {
        autonomy_rules: "May review, classify, and propose. Must ask before modifying live workflows, deleting data, deploying, or sending externally.",
        communication_style: "Direct, specific, and improvement-oriented.",
        day_mode: "Review agent loops, failures, stale goals, and missed handoffs.",
        night_mode: "Prepare challenge notes and safe improvement proposals.",
        day_mode_start: "08:00",
        day_mode_end: "18:00",
        core_truths: "Theta Wave improves the fleet through Elevate-native loops, not daemon restarts or PM2 sessions.",
      },
      lifecycle: {
        startup_delay: 0,
        max_session_seconds: 5400,
        max_crashes_per_day: 3,
        crash_window_seconds: 86400,
        crash_window_max: 3,
        telegram_polling: false,
      },
      ecosystem: {
        local_version_control: true,
        upstream_sync: false,
        catalog_browse: true,
        community_publish: false,
      },
      memory: {
        mode: "agent_scoped",
        scopes: ["theta-wave", "system-review", "experiments", "fleet-improvement"],
        sources: ["agent-hub-template", "elevate-native"],
        recall_policy: "agent_scoped_recent",
        write_policy: "append_events",
        handoff_policy: "summary_only",
      },
      heartbeatGoalsSeed: {
        bottleneck: "No challenge loop has run yet.",
        daily_focus: "Find stale, weak, or unsafe loops and propose native fixes.",
        goals: [
          { title: "Classify fleet health", progress: 0 },
          { title: "Challenge weak assumptions", progress: 0 },
          { title: "Propose native improvements", progress: 0 },
        ],
      },
      heartbeatSurfaceSeed: {
        schedule: "0 */4 * * *",
        goal: "Run a native Theta Wave review loop for fleet quality and lifecycle risk.",
      },
      onboardingTaskSeed: {
        title: "Onboard Theta Wave",
        description: "Confirm challenge-review scope, lifecycle rules, and escalation routing.",
      },
    },
  },
  {
    id: "comms",
    label: "Comms",
    defaultName: "Comms Agent",
    description: "Prepares messages, keeps channels visible, and routes human approvals.",
    payload: {
      role: "comms",
      enabled: true,
      platforms: ["local", "telegram"],
      session_sources: ["cli", "telegram", "cron"],
      skills: ["surface-heartbeat"],
      toolsets: ["agent_bus", "agent_handoff", "memory", "messaging", "todo"],
      runtime: {
        runtime_type: "native",
        timezone: "America/Vancouver",
        context_warning_threshold: 70,
        context_handoff_threshold: 88,
      },
      routing: {
        owns: ["comms", "drafts", "approvals", "channel-triage"],
        handoff_targets: ["executive-assistant", "admin"],
        escalation_target: "executive-assistant",
        default_priority: "high",
      },
      safety: {
        approval_mode: "always_confirm",
        always_ask: ["external_send", "legal", "financial", "credential_change"],
        never_ask: ["local_read", "status_check", "summarize", "draft_only"],
      },
      identity: {
        emoji: "C",
        vibe: "Careful channel operator",
        work_style: "Draft clearly, keep context attached, and never send externally without approval.",
      },
      soul: {
        autonomy_rules: "Drafts and summaries are allowed. External sends always require approval.",
        communication_style: "Clean, human, and context-aware.",
        day_mode: "Review Comms, drafts, approvals, and handoff threads.",
        night_mode: "Prepare drafts and summaries only.",
        day_mode_start: "08:00",
        day_mode_end: "18:00",
        core_truths: "Comms owns visibility and draft quality. Delivery stays in Elevate-native channels and approval gates.",
      },
      lifecycle: {
        startup_delay: 0,
        max_session_seconds: 3600,
        max_crashes_per_day: 3,
        crash_window_seconds: 86400,
        crash_window_max: 3,
        telegram_polling: true,
      },
      ecosystem: {
        local_version_control: false,
        upstream_sync: false,
        catalog_browse: false,
        community_publish: false,
      },
      memory: {
        mode: "agent_scoped",
        scopes: ["comms", "drafts", "approvals"],
        sources: ["agent-hub-template", "elevate-native"],
        recall_policy: "agent_scoped_recent",
        write_policy: "append_events",
        handoff_policy: "summary_only",
      },
      heartbeatGoalsSeed: {
        bottleneck: "No Comms loop has run yet.",
        daily_focus: "Keep drafts, approvals, and channel context clean.",
        goals: [
          { title: "Review pending drafts", progress: 0 },
          { title: "Summarize channel blockers", progress: 0 },
          { title: "Protect external delivery", progress: 0 },
        ],
      },
      heartbeatSurfaceSeed: {
        schedule: "0 */4 * * *",
        goal: "Run a native Comms loop for drafts, approvals, and channel hygiene.",
      },
      onboardingTaskSeed: {
        title: "Onboard Comms Agent",
        description: "Confirm Telegram lane, external-send approvals, and handoff routing.",
      },
    },
  },
  {
    id: "blank",
    label: "Blank",
    defaultName: "Custom Agent",
    description: "A lightweight native agent shell you can shape from scratch.",
    payload: {
      role: "support",
      enabled: true,
      platforms: ["local"],
      session_sources: ["cli", "cron"],
      toolsets: ["agent_bus", "agent_handoff"],
    },
  },
];

function firstMarkdownParagraph(text: string) {
  return text
    .split(/\n{2,}/)
    .map((part) => part.replace(/^#+\s*/gm, "").trim())
    .find(Boolean) ?? "";
}

function mergeUniqueStrings(...groups: Array<unknown>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    const values = Array.isArray(group) ? group : typeof group === "string" ? group.split(/[,\n]/) : [];
    for (const value of values) {
      const clean = String(value || "").trim();
      if (!clean || seen.has(clean)) continue;
      seen.add(clean);
      out.push(clean);
    }
  }
  return out;
}

function markdownSection(text: string, heading: string): string {
  const lines = text.split(/\r?\n/);
  const target = heading.toLowerCase();
  const start = lines.findIndex((line) => line.replace(/^#+\s*/, "").trim().toLowerCase() === target);
  if (start < 0) return "";
  const body: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (/^#{1,6}\s+\S/.test(line)) break;
    body.push(line);
  }
  return body.join("\n").trim();
}

function markdownBullets(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim().match(/^(?:[-*+]|\d+[.)])\s+(.+)$/)?.[1]?.replace(/^\[[ xX]\]\s*/, "").trim() || "")
    .filter(Boolean);
}

function extractCortextSkillRefs(...texts: string[]): string[] {
  const refs: string[] = [];
  for (const text of texts) {
    for (const match of text.matchAll(/(?:^|[/"\s])skills\/([a-z0-9._-]+)\/SKILL\.md/gi)) {
      refs.push(match[1]);
    }
    for (const match of text.matchAll(/\.claude\/skills\/([a-z0-9._-]+)\/SKILL\.md/gi)) {
      refs.push(match[1]);
    }
  }
  return mergeUniqueStrings(refs);
}

function extractCortextToolsets(toolsText: string, config: Record<string, unknown>): string[] {
  const configured = mergeUniqueStrings(config.toolsets, config.tool_sets, config.enabled_toolsets);
  const inferred: string[] = [];
  const lower = toolsText.toLowerCase();
  if (/\b(agent_handoff|handoff|send-message|check-inbox)\b/.test(lower)) {
    inferred.push("agent_handoff");
  }
  if (/\b(create-task|update-task|complete-task|list-tasks|create-approval|list-approvals|post-activity|log-event|heartbeat|update-heartbeat|read-all-heartbeats|create-experiment|run-experiment|evaluate-experiment|list-experiments|browse-catalog|list-skills)\b/.test(lower)) {
    inferred.push("agent_bus");
  }
  if (/\b(kb-query|memory|knowledge-base|knowledge base)\b/.test(lower)) {
    inferred.push("memory");
  }
  return mergeUniqueStrings(configured, inferred);
}

function cortextCronSchedule(cron: Record<string, unknown>): string {
  const rawCron = String(cron.cron || "").trim();
  if (rawCron) return rawCron;
  const interval = String(cron.interval || "").trim();
  return interval ? `every ${interval}` : "";
}

function cortextRuntimeConfig(config: Record<string, unknown>): Record<string, unknown> {
  const runtime: Record<string, unknown> = {
    runtime_type: String(config.runtime || config.runtime_type || "native"),
    timezone: String(config.timezone || "America/Vancouver"),
  };
  for (const [source, target] of [
    ["model", "model"],
    ["provider", "provider"],
    ["base_url", "base_url"],
    ["working_directory", "workdir"],
    ["workdir", "workdir"],
    ["ctx_warning_threshold", "context_warning_threshold"],
    ["context_warning_threshold", "context_warning_threshold"],
    ["ctx_handoff_threshold", "context_handoff_threshold"],
    ["context_handoff_threshold", "context_handoff_threshold"],
    ["codex_context_cap", "codex_context_cap"],
  ] as const) {
    const value = config[source];
    if (value !== undefined && value !== null && value !== "") runtime[target] = value;
  }
  return runtime;
}

function cortextCronSeeds(config: Record<string, unknown>, agentName: string): AgentCreatePayload["cronSeeds"] {
  const crons = Array.isArray(config.crons) ? config.crons : [];
  const runtime = cortextRuntimeConfig(config);
  const seeds: NonNullable<AgentCreatePayload["cronSeeds"]> = [];
  for (const item of crons) {
    if (!item || typeof item !== "object") continue;
    const cron = item as Record<string, unknown>;
    const name = String(cron.name || "").trim();
    if (!name || name.toLowerCase() === "heartbeat") continue;
    const schedule = cortextCronSchedule(cron);
    const prompt = String(cron.prompt || "").trim();
    if (!schedule || !prompt) continue;
    seeds.push({
      name: `${agentName} - ${name}`,
      schedule,
      prompt,
      deliver: "local",
      model: (runtime.model as string | undefined) || null,
      provider: (runtime.provider as string | undefined) || null,
      base_url: (runtime.base_url as string | undefined) || null,
      workdir: (runtime.workdir as string | undefined) || null,
      enabled: false,
      origin: {
        type: "cortext-cron",
        source: "cortext-import",
        cortext_name: name,
      },
    });
  }
  return seeds;
}

function parseCortextGoalsJson(text: string): AgentCreatePayload["heartbeatGoalsSeed"] | undefined {
  if (!text.trim()) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return undefined;
  }
  const raw = Array.isArray(parsed) ? { goals: parsed } : parsed;
  if (!raw || typeof raw !== "object") return undefined;
  const obj = raw as Record<string, unknown>;
  const rawGoals = Array.isArray(obj.goals) ? obj.goals : Array.isArray(obj.items) ? obj.items : [];
  const goals: HeartbeatGoalDraft[] = [];
  rawGoals.forEach((item, index) => {
    if (typeof item === "string") {
      goals.push({ title: item, progress: 0, order: index });
      return;
    }
    if (!item || typeof item !== "object") return;
    const rec = item as Record<string, unknown>;
    const title = String(rec.title || rec.name || rec.goal || rec.text || "").trim();
    if (!title) return;
    const rawProgress = Number(rec.progress ?? rec.percent ?? rec.completion ?? 0);
    const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(100, rawProgress)) : 0;
    goals.push({ title, progress, order: Number(rec.order ?? index) });
  });
  const bottleneck = String(obj.bottleneck || obj.blocker || "").trim();
  const dailyFocus = String(obj.daily_focus || obj.dailyFocus || obj.focus || "").trim();
  if (!bottleneck && !dailyFocus && !goals.length) return undefined;
  return { bottleneck, daily_focus: dailyFocus, goals };
}

function mergeHeartbeatSeeds(
  primary?: AgentCreatePayload["heartbeatGoalsSeed"],
  fallback?: AgentCreatePayload["heartbeatGoalsSeed"],
): AgentCreatePayload["heartbeatGoalsSeed"] | undefined {
  if (!primary) return fallback;
  if (!fallback) return primary;
  const goalTitles = mergeUniqueStrings(
    (primary.goals || []).map((goal) => goal.title),
    (fallback.goals || []).map((goal) => goal.title),
  );
  return {
    bottleneck: primary.bottleneck || fallback.bottleneck,
    daily_focus: primary.daily_focus || fallback.daily_focus,
    goals: goalTitles.map((title, index) => {
      const existing = [...(primary.goals || []), ...(fallback.goals || [])].find((goal) => goal.title === title);
      return { title, progress: existing?.progress ?? 0, order: index };
    }),
  };
}

function parseCortextGoalsMarkdown(text: string): AgentCreatePayload["heartbeatGoalsSeed"] | undefined {
  const lines = text.split(/\r?\n/);
  let bottleneck = "";
  let dailyFocus = "";
  const goals: HeartbeatGoalDraft[] = [];

  for (const line of lines) {
    const clean = line.trim();
    if (!clean) continue;
    const daily = clean.match(/^daily[_\s-]*focus\s*:\s*(.+)$/i);
    if (daily) {
      dailyFocus = daily[1].trim();
      continue;
    }
    const blocker = clean.match(/^bottleneck\s*:\s*(.+)$/i);
    if (blocker) {
      bottleneck = blocker[1].trim();
      continue;
    }
    const bullet = clean.match(/^(?:[-*+]|\d+[.)])\s+(.+)$/);
    if (!bullet) continue;
    let title = bullet[1].replace(/^\[[ xX]\]\s*/, "").trim();
    const progressMatch = title.match(/(?:^|\s)(\d{1,3})%\s*$/);
    const progress = progressMatch ? Math.max(0, Math.min(100, Number(progressMatch[1]))) : 0;
    if (progressMatch) title = title.slice(0, progressMatch.index).trim();
    if (title && !/^daily[_\s-]*focus|^bottleneck/i.test(title)) {
      goals.push({ title, progress, order: goals.length });
    }
  }

  if (!bottleneck && !dailyFocus && !goals.length) return undefined;
  return { bottleneck, daily_focus: dailyFocus, goals };
}

async function buildCortextImportPayload(files: FileList): Promise<AgentCreatePayload> {
  const byName = new Map<string, string>();
  const ignoredFiles: string[] = [];
  await Promise.all(
    Array.from(files).map(async (file) => {
      const fileName = file.name.toLowerCase();
      if (CORTEXT_IMPORT_IGNORED_FILES.has(fileName)) {
        ignoredFiles.push(fileName);
        return;
      }
      byName.set(fileName, await file.text());
    }),
  );
  const rawConfig = byName.get("config.json");
  const parsed = rawConfig ? JSON.parse(rawConfig) : {};
  const config = stripCortextImportSecrets(parsed) as Record<string, unknown>;
  const agents = byName.get("agents.md") ?? "";
  const identity = byName.get("identity.md") ?? "";
  const soul = byName.get("soul.md") ?? "";
  const system = byName.get("system.md") ?? "";
  const user = byName.get("user.md") ?? "";
  const tools = byName.get("tools.md") ?? "";
  const guardrails = byName.get("guardrails.md") ?? "";
  const onboarding = byName.get("onboarding.md") ?? "";
  const heartbeat = byName.get("heartbeat.md") ?? "";
  const goals = byName.get("goals.md") ?? "";
  const goalsJson = byName.get("goals.json") ?? "";
  const memory = byName.get("memory.md") ?? "";
  const heartbeatGoalsSeed = mergeHeartbeatSeeds(
    mergeHeartbeatSeeds(parseCortextGoalsJson(goalsJson), parseCortextGoalsMarkdown(goals)),
    parseCortextGoalsMarkdown(heartbeat),
  );
  const name = String(config.name || config.id || config.slug || "Imported Agent");
  const rawCrons = Array.isArray(config.crons) ? config.crons.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [];
  const heartbeatCron = rawCrons.find((cron) => String(cron.name || "").trim().toLowerCase() === "heartbeat");
  const runtimeConfig = cortextRuntimeConfig(config);
  const communicationStyle = markdownSection(soul, "Communication Style") || markdownSection(identity, "Communication Style");
  const autonomyRules = markdownSection(soul, "Autonomy Rules") || markdownSection(guardrails, "Autonomy Rules");
  const dayMode = markdownSection(soul, "Day Mode");
  const nightMode = markdownSection(soul, "Night Mode");
  const guardrailRules = markdownBullets(guardrails);
  const importedFileNames = Array.from(byName.keys()).sort();
  const skills = mergeUniqueStrings(
    config.skills,
    extractCortextSkillRefs(agents, tools, guardrails, onboarding, heartbeat),
  );
  const toolsets = extractCortextToolsets(tools, config);
  const promptParts = [
    system && `# Imported SYSTEM\n${system}`,
    user && `# Imported USER\n${user}`,
    agents && `# Imported AGENTS\n${agents}`,
    identity && `# Imported IDENTITY\n${identity}`,
    soul && `# Imported SOUL\n${soul}`,
    tools && `# Imported TOOLS\n${tools}`,
    guardrails && `# Imported GUARDRAILS\n${guardrails}`,
    onboarding && `# Imported ONBOARDING\n${onboarding}`,
    heartbeat && `# Imported HEARTBEAT\n${heartbeat}`,
    goals && `# Imported GOALS\n${goals}`,
    rawCrons.length && `# Imported AUTOMATION RULES\n${rawCrons.map((cron) => {
      const title = String(cron.name || "automation").trim();
      return `## ${title}\nSchedule: ${cortextCronSchedule(cron) || "manual"}\n${String(cron.prompt || "").trim()}`;
    }).join("\n\n")}`,
  ].filter(Boolean);
  return {
    ...config,
    name,
    description: String(config.description || firstMarkdownParagraph(identity) || "Imported Cortext agent"),
    role: String(config.role || "support"),
    enabled: config.enabled == null ? true : Boolean(config.enabled),
    platforms: Array.isArray(config.platforms) ? (config.platforms as string[]) : ["local"],
    session_sources: Array.isArray(config.session_sources)
      ? (config.session_sources as string[])
      : ["cli", "cron"],
    skills,
    toolsets,
    prompt: promptParts.join("\n\n"),
    runtime: runtimeConfig,
    lifecycle: {
      ...((config.lifecycle as Record<string, unknown>) || {}),
      startup_delay: config.startup_delay ?? (config.lifecycle as Record<string, unknown> | undefined)?.startup_delay,
      max_session_seconds: config.max_session_seconds ?? (config.lifecycle as Record<string, unknown> | undefined)?.max_session_seconds,
      max_crashes_per_day: config.max_crashes_per_day ?? (config.lifecycle as Record<string, unknown> | undefined)?.max_crashes_per_day,
      telegram_polling: config.telegram_polling ?? (config.lifecycle as Record<string, unknown> | undefined)?.telegram_polling,
      crash_window: config.crash_window,
    },
    identity: {
      ...((config.identity as Record<string, unknown>) || {}),
      vibe: firstMarkdownParagraph(identity),
      work_style: markdownSection(identity, "Work Style") || markdownSection(agents, "Work Style"),
    },
    soul: {
      ...((config.soul as Record<string, unknown>) || {}),
      autonomy_rules: autonomyRules,
      communication_style: communicationStyle,
      day_mode: dayMode,
      night_mode: nightMode,
      core_truths: soul,
    },
    safety: {
      ...((config.safety as Record<string, unknown>) || {}),
      always_ask: mergeUniqueStrings(
        (config.safety as Record<string, unknown> | undefined)?.always_ask,
        (config.approval_rules as Record<string, unknown> | undefined)?.always_ask,
        guardrails ? ["external_send", "destructive_action", "deployment", "financial", "legal", "data_deletion"] : [],
      ),
      approval_mode: String(
        (config.safety as Record<string, unknown> | undefined)?.approval_mode
        || (config.approval_rules as Record<string, unknown> | undefined)?.approval_mode
        || (guardrails ? "always_confirm" : "confirm_external_send"),
      ),
    },
    memory: {
      ...((config.memory as Record<string, unknown>) || {}),
      sources: mergeUniqueStrings((config.memory as Record<string, unknown> | undefined)?.sources, ["cortext-import"]),
    },
    metadata: {
      ...((config.metadata as Record<string, unknown>) || {}),
      cortext_import: {
        source_files: importedFileNames,
        ignored_files: ignoredFiles.sort(),
        native_replacements: CORTEXT_NATIVE_REPLACEMENTS,
        guardrail_count: guardrailRules.length,
        onboarding_preview: onboarding.slice(0, 2000),
        heartbeat_preview: heartbeat.slice(0, 2000),
        tools_preview: tools.slice(0, 2000),
        goals_json_imported: Boolean(goalsJson.trim()),
        automation_rules: rawCrons.map((cron) => ({
          name: String(cron.name || "").trim(),
          type: String(cron.type || "recurring").trim(),
          interval: String(cron.interval || "").trim(),
          cron: String(cron.cron || "").trim(),
          prompt: String(cron.prompt || "").trim(),
          native_schedule: cortextCronSchedule(cron),
          native_store: String(cron.name || "").trim().toLowerCase() === "heartbeat" ? "heartbeat" : "cron",
        })),
        automation_store: "Elevate heartbeat/crons/tasks; no per-agent cron config store",
        claude_md_imported: false,
      },
    },
    heartbeatSurfaceSeed: {
      schedule: heartbeatCron ? cortextCronSchedule(heartbeatCron) : undefined,
      goal: heartbeatCron ? String(heartbeatCron.prompt || "").trim() : String(config.description || firstMarkdownParagraph(identity) || "Imported Cortext goals"),
      config: {
        runtime: runtimeConfig.runtime_type,
        model: runtimeConfig.model,
        provider: runtimeConfig.provider,
        base_url: runtimeConfig.base_url,
        workdir: runtimeConfig.workdir,
        timezone: runtimeConfig.timezone,
        day_mode_start: config.day_mode_start,
        day_mode_end: config.day_mode_end,
        communication_style: config.communication_style || communicationStyle,
        approval_rules: config.approval_rules || {},
        startup_delay: config.startup_delay,
        max_session_seconds: config.max_session_seconds,
        max_crashes_per_day: config.max_crashes_per_day,
        telegram_polling: config.telegram_polling,
      },
    },
    cronSeeds: cortextCronSeeds(config, name),
    heartbeatGoalsSeed,
    onboardingTaskSeed: onboarding.trim()
      ? {
          title: `Onboard ${name}`,
          description: onboarding.slice(0, 4000),
        }
      : undefined,
    memorySeed: memory.trim()
      ? {
          content: memory.slice(0, 40000),
          source: "cortext-import",
        }
      : undefined,
  };
}

// ── add-agent modal
function AddAgentModal({
  onAdd,
  onClose,
}: {
  onAdd: (payload: AgentCreatePayload) => Promise<void>;
  onClose: () => void;
}) {
  const defaultTemplate = AGENT_ADD_TEMPLATES.find((template) => template.id === "operator") ?? AGENT_ADD_TEMPLATES[0];
  const [name, setName] = useState(defaultTemplate.defaultName);
  const [description, setDescription] = useState(defaultTemplate.description);
  const [nameEdited, setNameEdited] = useState(false);
  const [descriptionEdited, setDescriptionEdited] = useState(false);
  const [mode, setMode] = useState<"manual" | "import">("manual");
  const [templateId, setTemplateId] = useState(defaultTemplate.id);
  const [importPayload, setImportPayload] = useState<AgentCreatePayload | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selectedTemplate = AGENT_ADD_TEMPLATES.find((template) => template.id === templateId) ?? AGENT_ADD_TEMPLATES[0];
  const templateRuntime = (selectedTemplate.payload.runtime as Record<string, unknown> | undefined) ?? {};
  const templateRouting = (selectedTemplate.payload.routing as Record<string, unknown> | undefined) ?? {};
  const templateSafety = (selectedTemplate.payload.safety as Record<string, unknown> | undefined) ?? {};
  const templateSoul = (selectedTemplate.payload.soul as Record<string, unknown> | undefined) ?? {};
  const templateTools = Array.isArray(selectedTemplate.payload.toolsets) ? selectedTemplate.payload.toolsets : [];
  const templateSkills = Array.isArray(selectedTemplate.payload.skills) ? selectedTemplate.payload.skills : [];
  const templatePlatforms = Array.isArray(selectedTemplate.payload.platforms) ? selectedTemplate.payload.platforms : [];
  const templateOwns = Array.isArray(templateRouting.owns) ? templateRouting.owns : [];

  useEffect(() => {
    if (!nameEdited) {
      setName(selectedTemplate.defaultName);
    }
    if (!descriptionEdited) {
      setDescription(selectedTemplate.description);
    }
  }, [descriptionEdited, nameEdited, selectedTemplate]);

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
          <div className="hub-agent-tabs" style={{ marginBottom: 12 }}>
            <button
              type="button"
              className={"hub-agent-tab" + (mode === "manual" ? " active" : "")}
              onClick={() => setMode("manual")}
            >
              Custom
            </button>
            <button
              type="button"
              className={"hub-agent-tab" + (mode === "import" ? " active" : "")}
              onClick={() => setMode("import")}
            >
              Import Cortext agent
            </button>
          </div>
          {mode === "manual" ? (
            <>
              <label className="hub-acc-field">
                <span className="hub-acc-k">Template</span>
                <select className="hub-input" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                  {AGENT_ADD_TEMPLATES.map((template) => (
                    <option key={template.id} value={template.id}>{template.label}</option>
                  ))}
                </select>
              </label>
              <div className="hub-template-preview">
                <div className="hub-template-preview-top">
                  <div>
                    <div className="hub-template-name">{selectedTemplate.defaultName}</div>
                    <div className="hub-template-desc">{selectedTemplate.description}</div>
                  </div>
                  <span className={"hub-template-state " + (selectedTemplate.payload.enabled === false ? "off" : "on")}>
                    {selectedTemplate.payload.enabled === false ? "Off" : "On"}
                  </span>
                </div>
                <div className="hub-template-grid mono">
                  <span><b>Role</b>{String(selectedTemplate.payload.role || "support")}</span>
                  <span><b>Runtime</b>{String(templateRuntime.runtime_type || "native")}</span>
                  <span><b>Day</b>{String(templateSoul.day_mode_start || "--")} to {String(templateSoul.day_mode_end || "--")}</span>
                  <span><b>Safety</b>{String(templateSafety.approval_mode || "confirm_external_send")}</span>
                </div>
                <div className="hub-template-chips mono">
                  {templatePlatforms.slice(0, 3).map((value) => <span key={`platform-${value}`}>{String(value)}</span>)}
                  {templateOwns.slice(0, 3).map((value) => <span key={`owns-${String(value)}`}>{String(value)}</span>)}
                  {templateTools.slice(0, 3).map((value) => <span key={`tool-${value}`}>{String(value)}</span>)}
                  {templateSkills.slice(0, 2).map((value) => <span key={`skill-${value}`}>{String(value)}</span>)}
                </div>
              </div>
              <label className="hub-acc-field">
                <span className="hub-acc-k">Agent name</span>
                <input
                  className="hub-input"
                  placeholder="e.g. Listings"
                  value={name}
                  onChange={(event) => {
                    setNameEdited(true);
                    setName(event.target.value);
                  }}
                />
              </label>
              <label className="hub-acc-field" style={{ marginTop: "12px" }}>
                <span className="hub-acc-k">Description</span>
                <input
                  className="hub-input"
                  placeholder="What does this agent handle?"
                  value={description}
                  onChange={(event) => {
                    setDescriptionEdited(true);
                    setDescription(event.target.value);
                  }}
                />
              </label>
            </>
          ) : (
            <div className="hub-import-panel">
              <label className="hub-acc-field">
                <span className="hub-acc-k">Cortext files</span>
                <input
                  className="hub-input"
                  type="file"
                  multiple
                  accept=".json,.md"
                  onChange={(event) => {
                    setImportError(null);
                    setImportPayload(null);
                    const files = event.currentTarget.files;
                    if (!files || files.length === 0) return;
                    void buildCortextImportPayload(files)
                      .then(setImportPayload)
                      .catch((error) => setImportError(error instanceof Error ? error.message : "Import parse failed"));
                  }}
                />
              </label>
              <div className="hub-runway-detail" style={{ marginTop: 8 }}>
                Select config.json plus AGENTS, IDENTITY, SOUL, SYSTEM, USER, TOOLS, GUARDRAILS, ONBOARDING, HEARTBEAT, GOALS, goals.json, and MEMORY files. CLAUDE.md is ignored.
              </div>
              {importError && <div className="hub-import-error">{importError}</div>}
              {importPayload && (
                <div className="hub-import-preview mono">
                  <div>{importPayload.name}</div>
                  <div>{importPayload.description}</div>
                  <div>Runtime: {String(importPayload.runtime_type || (importPayload.runtime as Record<string, unknown> | undefined)?.runtime_type || "inherited")}</div>
                </div>
              )}
            </div>
          )}
          <div className="hub-acc-actions" style={{ marginTop: "18px" }}>
            <button type="button" className="hub-btn ghost" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="hub-btn primary"
              disabled={(mode === "manual" ? !name.trim() : !importPayload) || creating}
              onClick={() => {
                setCreating(true);
                void (async () => {
	                  try {
	                    await onAdd(
	                      mode === "manual"
	                        ? {
	                            ...selectedTemplate.payload,
	                            name: name.trim(),
	                            description: description.trim() || selectedTemplate.description,
	                          }
	                        : importPayload!,
	                    );
                    setCreating(false);
                    onClose();
                  } catch {
                    setCreating(false);
                  }
                })();
              }}
            >
              {creating ? (
                <Ico.refresh width="13" height="13" className="spin" />
              ) : (
                <Ico.plus width="13" height="13" />
              )}
              Add agent
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

type AgentLibraryFilter = "all" | "active" | "inactive";

function CortextAgentPackCatalog({
  packs,
  agents,
  installableDefaults,
  loading,
  installingId,
  onInstall,
  onToggle,
}: {
  packs: CortextAgentPack[];
  agents: AgentHubAgent[];
  installableDefaults: InstallableDefault[];
  loading: boolean;
  installingId: string | null;
  onInstall: (pack: CortextAgentPack) => Promise<void>;
  onToggle: (agentId: string, enabled: boolean) => Promise<void>;
}) {
  const [filter, setFilter] = useState<AgentLibraryFilter>("all");
  const [busyId, setBusyId] = useState<string | null>(null);

  const installedIds = useMemo(
    () => new Set(agents.map((agent) => agent.id.toLowerCase())),
    [agents],
  );

  // Unified library: every installed agent + every installable native default +
  // every installable pack that isn't installed yet. Active = installed +
  // enabled; Inactive = installed-but-off OR not installed.
  type LibraryRow = {
    id: string;
    name: string;
    role: string;
    description: string;
    installed: boolean;
    active: boolean;
    native: boolean;
    pack?: CortextAgentPack;
  };
  const rows = useMemo<LibraryRow[]>(() => {
    const installedRows: LibraryRow[] = agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      role: String(agent.role ?? ""),
      description: String(agent.description ?? ""),
      installed: true,
      active: Boolean(agent.enabled),
      native: Boolean(agent.builtin),
    }));
    const defaultRows: LibraryRow[] = installableDefaults
      .filter((def) => !installedIds.has(def.id.toLowerCase()))
      .map((def) => ({
        id: def.id,
        name: def.name,
        role: String(def.role ?? ""),
        description: String(def.description ?? ""),
        installed: false,
        active: false,
        native: true,
      }));
    const packRows: LibraryRow[] = packs
      .filter((pack) => !installedIds.has(pack.id.toLowerCase()))
      .map((pack) => ({
        id: pack.id,
        name: pack.name,
        role: String(pack.role ?? ""),
        description: String(pack.description ?? ""),
        installed: false,
        active: false,
        native: false,
        pack,
      }));
    return [...installedRows, ...defaultRows, ...packRows].sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [agents, packs, installableDefaults, installedIds]);

  const counts = useMemo(
    () => ({
      all: rows.length,
      active: rows.filter((row) => row.active).length,
      inactive: rows.filter((row) => !row.active).length,
    }),
    [rows],
  );
  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        if (filter === "active") return row.active;
        if (filter === "inactive") return !row.active;
        return true;
      }),
    [rows, filter],
  );

  return (
    <div className="hub-block hub-pack-block">
      <div className="hub-block-head">
        <div>
          <div className="hub-block-title">
            Agent library <span className="hub-block-meta mono">· {counts.all} agents</span>
          </div>
          <div className="hub-pack-sub">
            Browse every agent — installed and available. Activate, deactivate, or install from here.
          </div>
        </div>
        <select
          className="hub-input sm mono"
          value={filter}
          onChange={(event) => setFilter(event.target.value as AgentLibraryFilter)}
          aria-label="Filter agents"
        >
          <option value="all">All agents ({counts.all})</option>
          <option value="active">Active ({counts.active})</option>
          <option value="inactive">Inactive ({counts.inactive})</option>
        </select>
      </div>

      {loading ? (
        <div className="hub-pack-grid">
          <ListSkeleton rows={3} className="hub-pack-skeleton" />
        </div>
      ) : filtered.length ? (
        <div className="hub-pack-grid">
          {filtered.map((row) => {
            const working = installingId === row.id || busyId === row.id;
            const stateLabel = row.active ? "active" : row.installed ? "inactive" : "not installed";
            return (
              <div className={"hub-pack-card" + (row.active ? " is-active" : "")} key={row.id}>
                <div className="hub-pack-top">
                  <div>
                    <div className="hub-pack-name">{row.name}</div>
                    <div className="hub-pack-role mono">{row.role}</div>
                  </div>
                  <span className={"hub-pack-source " + (row.active ? "ok" : "warn")}>{stateLabel}</span>
                </div>
                <p className="hub-pack-desc">{row.description}</p>
                {row.pack ? (
                  <div className="hub-pack-chips">
                    {row.pack.includes.slice(0, 6).map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                  </div>
                ) : null}
                <div className="hub-pack-foot">
                  <span className="mono">
                    {row.installed
                      ? row.active
                        ? "running"
                        : "installed · off"
                      : `${row.pack?.automationCount ?? 0} automation rule${row.pack?.automationCount === 1 ? "" : "s"}`}
                  </span>
                  {row.installed ? (
                    <button
                      type="button"
                      className={"hub-btn sm " + (row.active ? "ghost" : "primary")}
                      disabled={Boolean(busyId)}
                      onClick={async () => {
                        setBusyId(row.id);
                        try {
                          await onToggle(row.id, !row.active);
                        } finally {
                          setBusyId(null);
                        }
                      }}
                    >
                      {working ? <Ico.refresh width="13" height="13" className="spin" /> : null}
                      {row.active ? "Deactivate" : "Activate"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="hub-btn sm primary"
                      disabled={Boolean(installingId) || Boolean(busyId)}
                      onClick={async () => {
                        if (row.native) {
                          // Native default: re-add + enable it.
                          setBusyId(row.id);
                          try {
                            await onToggle(row.id, true);
                          } finally {
                            setBusyId(null);
                          }
                        } else if (row.pack) {
                          void onInstall(row.pack);
                        }
                      }}
                    >
                      {working ? (
                        <Ico.refresh width="13" height="13" className="spin" />
                      ) : (
                        <Ico.plus width="13" height="13" />
                      )}
                      {working ? "Installing" : "Install"}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="hub-pack-empty">No agents match this filter.</div>
      )}
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────
export default function AgentHubPage() {
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [savingTelegram, setSavingTelegram] = useState(false);
  const [savingAgentId, setSavingAgentId] = useState<string | null>(null);
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramHome, setTelegramHome] = useState("");
  const [telegramLanes, setTelegramLanes] = useState<Record<string, string>>({});
  const [telegramAgentTokens, setTelegramAgentTokens] = useState<Record<string, string>>({});
  const [addAgentOpen, setAddAgentOpen] = useState(false);
  const [installingPackId, setInstallingPackId] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Snapshot cached across tab switches (lite first paint, then enriched to
  // full in the background). Revisiting Agent Hub paints the last snapshot
  // instantly instead of re-fetching from scratch.
  const { data: snapshotData, loading, error: snapshotError, refresh: refreshSnapshot, mutate: mutateSnapshot } =
    useCachedResource(
      "agent-hub-snapshot",
      () => api.getAgentHub({ lite: true, includeMemoryGraph: false, includeSkills: false, includeToolsets: false }),
      { ttl: 5000 },
    );
  const snapshot = snapshotData ?? null;

  const { data: envVarsData, refresh: refreshEnvVars } = useCachedResource(
    "agent-hub-envvars",
    () => api.getEnvVars(),
    { ttl: 10000 },
  );
  const envVars = envVarsData ?? null;

  const { data: cortextPacksData, loading: loadingCortextPacks, refresh: refreshCortextPacks } = useCachedResource(
    "cortext-agent-packs",
    () => api.getCortextAgentPacks().then((catalog) => catalog.packs as CortextAgentPack[]).catch(() => [] as CortextAgentPack[]),
    { ttl: 30000 },
  );
  const cortextPacks = cortextPacksData ?? [];

  // Progressive hydration: once a lite snapshot lands, enrich it to the full
  // snapshot in the background. WeakSet guards against re-hydrating a snapshot
  // we already enriched (prevents a mutate -> effect -> mutate loop).
  const hydratedSnapshotsRef = useRef<WeakSet<object>>(new WeakSet());
  useEffect(() => {
    if (!snapshot || hydratedSnapshotsRef.current.has(snapshot)) return;
    hydratedSnapshotsRef.current.add(snapshot);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void api
        .getAgentHub({ includeMemoryGraph: true, includeSkills: true, includeToolsets: true })
        .then((fullSnapshot) => {
          if (cancelled) return;
          hydratedSnapshotsRef.current.add(fullSnapshot);
          mutateSnapshot(fullSnapshot);
        })
        .catch(() => null);
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [snapshot, mutateSnapshot]);

  useEffect(() => {
    if (snapshotError) {
      showToast(snapshotError instanceof Error ? snapshotError.message : "Agent Hub failed", "error");
    }
  }, [snapshotError, showToast]);

  const load = useCallback(async () => {
    await Promise.all([refreshSnapshot(), refreshEnvVars(), refreshCortextPacks()]);
  }, [refreshSnapshot, refreshEnvVars, refreshCortextPacks]);
  useRefreshOnAgentTurn(() => void load());

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
          ? `${pendingPairings} pairing code${pendingPairings === 1 ? "" : "s"} waiting — approve below`
          : `${configuredPlatforms} connector${configuredPlatforms === 1 ? "" : "s"} configured`,
        state: pendingPairings ? "review" : configuredPlatforms ? "ready" : "blank",
        to: "/hub",
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

  const runAgentWorker = async (agentId?: string) => {
    setHandoffBusy(true);
    try {
      const result = await api.runAgentWorkerTick(agentId ? { agentId } : {});
      const scoped = agentId ? `${agentId}: ` : "";
      showToast(
        `${scoped}worker launched ${result.drained.handoffs} handoff${result.drained.handoffs === 1 ? "" : "s"} and ${result.drained.adminRuns} admin run${result.drained.adminRuns === 1 ? "" : "s"}`,
        "success",
      );
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const wakeAgentWorker = async (agentId?: string) => {
    setHandoffBusy(true);
    try {
      await api.wakeAgentWorker(agentId ? { agentId } : {});
      showToast(
        agentId
          ? `${agentId}: worker wake queued. Gateway loop will drain it.`
          : "Worker wake queued. Gateway loop will drain it.",
        "success",
      );
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

  const handleAddAgent = useCallback(
    async (payload: AgentCreatePayload) => {
      const name = payload.name;
      const { heartbeatGoalsSeed, heartbeatSurfaceSeed, cronSeeds, onboardingTaskSeed, ...agentPayload } = payload;
      try {
        const created = await api.createAgent(agentPayload);
        const createdId = String(created.id || agentPayload.id || "").trim();
        if (createdId && onboardingTaskSeed?.description) {
          try {
            await api.createSurfaceTask({
              title: onboardingTaskSeed.title || `Onboard ${created.name || createdId}`,
              description: onboardingTaskSeed.description,
              assignee: createdId,
              priority: "normal",
              project: "agent-onboarding",
            });
          } catch (error) {
            showToast(error instanceof Error ? `Agent added, onboarding task failed: ${error.message}` : "Agent added, onboarding task failed", "error");
          }
        }
        if (createdId && (heartbeatSurfaceSeed || (heartbeatGoalsSeed && (
          heartbeatGoalsSeed.bottleneck ||
          heartbeatGoalsSeed.daily_focus ||
          heartbeatGoalsSeed.goals?.length
        )))) {
          try {
            await api.createHeartbeatSurface({
              surface: createdId,
              title: String(created.name || agentPayload.name || createdId),
              name: String(created.name || agentPayload.name || createdId),
              goal: String(heartbeatSurfaceSeed?.goal || agentPayload.description || agentPayload.role || "Imported Cortext goals"),
              schedule: heartbeatSurfaceSeed?.schedule,
              experiment: heartbeatSurfaceSeed?.experiment,
              config: heartbeatSurfaceSeed?.config,
            });
          } catch {
            // The surface may already exist; goals patch below is the source of truth.
          }
          if (heartbeatSurfaceSeed?.config) {
            try {
              await api.patchHeartbeatSurfaceConfig(createdId, heartbeatSurfaceSeed.config);
            } catch {
              // Older surfaces may not exist yet or may reject fields; Agent Hub remains authoritative.
            }
          }
        }
        if (createdId && heartbeatGoalsSeed && (
          heartbeatGoalsSeed.bottleneck ||
          heartbeatGoalsSeed.daily_focus ||
          heartbeatGoalsSeed.goals?.length
        )) {
          try {
            await api.patchHeartbeatSurfaceGoals(createdId, heartbeatGoalsSeed);
          } catch (error) {
            showToast(error instanceof Error ? `Agent added, goals import failed: ${error.message}` : "Agent added, goals import failed", "error");
          }
        }
        if (createdId && cronSeeds?.length) {
          const existingJobs = await api.getCronJobs({ compact: true, refresh: true }).catch(() => []);
          const existingNames = new Set(existingJobs.map((job) => String(job.name || "").trim().toLowerCase()));
          for (const seed of cronSeeds) {
            const cronName = String(seed.name || "").trim();
            if (!cronName || existingNames.has(cronName.toLowerCase())) continue;
            try {
              const job = await api.createCronJob({
                ...seed,
                name: cronName,
                agent: seed.agent || createdId,
                origin: { ...(seed.origin || {}), agent: createdId },
              });
              existingNames.add(cronName.toLowerCase());
              if (seed.enabled === false && job.id) {
                await api.pauseCronJob(job.id);
              }
            } catch (error) {
              showToast(error instanceof Error ? `Agent added, automation import failed: ${error.message}` : "Agent added, automation import failed", "error");
            }
          }
        }
        await load();
        showToast(`${name} added. Configure runtime, routing, and safety next.`, "success");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Agent creation failed", "error");
        throw error;
      }
    },
    [load, showToast],
  );

  const installCortextPack = useCallback(
    async (pack: CortextAgentPack) => {
      setInstallingPackId(pack.id);
      try {
        await handleAddAgent(pack.payload);
      } finally {
        setInstallingPackId(null);
      }
    },
    [handleAddAgent],
  );

  const deleteAgent = useCallback(
    async (agent: AgentHubAgent) => {
      if (!agent.canDelete) {
        showToast("Built-in agents can be suspended, not deleted.", "error");
        return;
      }
      const isCortextPreset = Boolean(
        (agent.metadata as Record<string, unknown> | undefined)?.cortext_preset,
      );
      const message = isCortextPreset
        ? `Delete ${agent.name}? This removes the custom Agent Hub config plus its imported heartbeat surface, onboarding task, and Cortext memory seed.`
        : `Delete ${agent.name}? This removes only the custom Agent Hub config entry.`;
      if (!window.confirm(message)) {
        return;
      }
      setSavingAgentId(agent.id);
      try {
        if (isCortextPreset) {
          await api.cleanupAgentInstallArtifacts(agent.id);
        } else {
          await api.deleteAgent(agent.id);
        }
        await load();
        showToast(`${agent.name} deleted.`, "success");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Agent delete failed", "error");
      } finally {
        setSavingAgentId(null);
      }
    },
    [load, showToast],
  );

  if (loading && !snapshot) {
    return <AgentHubSkeleton />;
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
                disabled={snapshot.gateway.running || busyAction !== null}
                aria-label={snapshot.gateway.running ? "Gateway already online" : "Start gateway"}
              >
                {busyAction === "start" ? (
                  <Ico.refresh width="13" height="13" className="spin" />
                ) : (
                  <Ico.play width="12" height="12" />
                )}
                {snapshot.gateway.running ? "Gateway online" : "Start gateway"}
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

          {/* Pairing approval — always-accessible approver for channel codes */}
          <PairingApprovalBlock />

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
                    workerBusy={handoffBusy}
                    onRunQueuedWork={(agentId) => void runAgentWorker(agentId)}
                    onWakeAgent={(agentId) => void wakeAgentWorker(agentId)}
                    onDeleteAgent={(targetAgent) => void deleteAgent(targetAgent)}
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

          <CortextAgentPackCatalog
            agents={snapshot.agents}
            installableDefaults={snapshot.installableDefaults ?? []}
            installingId={installingPackId}
            loading={loadingCortextPacks}
            onInstall={installCortextPack}
            packs={cortextPacks}
            onToggle={async (agentId, enabled) => {
              try {
                await api.updateAgent(agentId, { enabled });
                showToast(`${agentId} ${enabled ? "activated" : "deactivated"}`, "success");
                await load();
              } catch (error) {
                showToast(error instanceof Error ? error.message : "Failed to update agent", "error");
              }
            }}
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
