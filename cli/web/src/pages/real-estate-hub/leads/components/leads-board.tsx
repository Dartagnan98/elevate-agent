import { useState, useMemo, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Clock,
  Plus,
  ChevronDown,
  Sparkles,
  AlertTriangle,
  Refresh,
} from "../../admin/icons";
import {
  LEADS_SOURCES as DEFAULT_SOURCES,
  LEADS_CHANNELS as DEFAULT_CHANNELS,
  LEADS_SCHEDULES as DEFAULT_SCHEDULES,
  LEADS_AVAILABLE as DEFAULT_AVAILABLE,
  LEADS_DRAFTS as DEFAULT_DRAFTS,
  LEADS_PIPELINE as DEFAULT_PIPELINE,
  LEADS_ACTIVITY as DEFAULT_ACTIVITY,
  LEADS_PROFILES as DEFAULT_PROFILES,
  LEADS_TEMPLATES as DEFAULT_TEMPLATES,
  LEADS_SENT as DEFAULT_SENT,
  type LeadsSource,
  type LeadsChannel,
  type LeadsSchedule,
  type LeadsAvailable,
  type LeadsDraft,
  type LeadsPipeline,
  type LeadsHotEntry,
  type LeadsSkippedEntry,
  type LeadsActivityEntry,
  type LeadsProfile,
  type LeadsTemplateLane,
  type LeadsTemplateItem,
  type LeadsSentMessage,
  type LeadsDraftAction,
} from "../leads-data";
import { api } from "@/lib/api";
import type { ThreadContextResponse } from "@/lib/api-types";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ListSkeleton } from "@/components/ui/skeleton";

export function matchesLeadsSourceFilter(
  item: { source?: string; sourceId?: string },
  sourceFilter: string,
): boolean {
  if (!sourceFilter || sourceFilter === "all") return true;
  if (item.sourceId === sourceFilter) return true;
  const source = (item.source || "").toLowerCase();
  if (sourceFilter === "lofty") return source === "lofty crm";
  if (sourceFilter === "composio-insta") return source.includes("composio") || source.includes("instagram");
  return false;
}

export function nextDraftQueueSelection(
  current: ReadonlySet<string>,
  drafts: Array<Pick<LeadsDraft, "id">>,
): Set<string> {
  const ids = drafts.map((draft) => draft.id).filter(Boolean);
  const allSelected = ids.length > 0 && ids.every((id) => current.has(id));
  const next = new Set(current);
  for (const id of ids) {
    if (allSelected) next.delete(id);
    else next.add(id);
  }
  return next;
}

// ─────────────────────────────────────────────────────────────────
// Activity ticker
// ─────────────────────────────────────────────────────────────────
function ActivityTicker({ activity }: { activity: LeadsActivityEntry[] }) {
  const [idx, setIdx] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open) return;
    if (activity.length <= 1) return;
    const t = setInterval(() => {
      setIdx(i => (i + 1) % activity.length);
    }, 4200);
    return () => clearInterval(t);
  }, [activity.length, open]);

  if (activity.length === 0) return null;
  const a = activity[idx];

  return (
    <div className="lb-ticker-wrap">
      <button
        type="button"
        className="lb-ticker"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <Clock />
        <span className="lb-ticker-label mono">Last run</span>
        <span key={a.id} className="lb-ticker-item">
          <span className="lb-ticker-title">{a.title}</span>
          <span className="lb-ticker-dot">·</span>
          <span className="lb-ticker-age mono">{a.age}</span>
        </span>
        <span className={"lb-ticker-chev" + (open ? " open" : "")}>▾</span>
      </button>

      {open && (
        <div className="lb-ticker-drawer">
          <header className="lb-ticker-drawer-head">
            <span className="lb-ticker-drawer-title">Recent agent activity</span>
            <span className="lb-ticker-drawer-sub mono">{activity.length} runs</span>
          </header>
          <div className="lb-ticker-drawer-list">
            {activity.map(it => (
              <div key={it.id} className="lb-ticker-drawer-row">
                <span className="lb-ticker-drawer-dot"></span>
                <div className="lb-ticker-drawer-body">
                  <div className="lb-ticker-drawer-row-title">{it.title}</div>
                  <div className="lb-ticker-drawer-row-meta mono">{it.kind} · {it.age} · {it.messages} messages</div>
                </div>
                <span className="lb-ticker-drawer-tools mono">{it.tools} tools</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Sources health pill
// ─────────────────────────────────────────────────────────────────
function SourcesHealthPill({
  channels, schedules, available,
}: {
  channels: LeadsChannel[];
  schedules: LeadsSchedule[];
  available: LeadsAvailable[];
}) {
  const [open, setOpen] = useState(false);
  const all = [...channels, ...schedules];
  const broken = all.filter(s => s.status === "error" || s.status === "blocked");
  const live = all.filter(s => s.status === "live");

  return (
    <div className="lb-health-wrap">
      <button type="button" className={"lb-health" + (broken.length > 0 ? " has-broken" : "")} onClick={() => setOpen(o => !o)}>
        {broken.length > 0 && <span className="lb-health-pulse"></span>}
        <span className="lb-health-text">
          <strong>{live.length}</strong> live
          {broken.length > 0 && <span className="lb-health-warn"> · {broken.length} need attention</span>}
        </span>
        <span className={"lb-health-chev" + (open ? " open" : "")}>▾</span>
      </button>

      {open && (
        <div className="lb-health-drawer">
          <SourcesDrawerSection title="Channels" items={channels} kind="channel" />
          <SourcesDrawerSection title="Schedules" items={schedules} kind="schedule" />
          <div className="lb-health-available">
            <div className="lb-health-available-label mono">Connect more</div>
            <div className="lb-health-available-chips">
              {available.map(a => (
                <Link key={a.id} to="/config#connectors" className="lb-avail-chip">
                  <span>+</span><span>{a.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SourcesDrawerSection({
  title, items, kind,
}: {
  title: string;
  items: Array<LeadsChannel | LeadsSchedule>;
  kind: "channel" | "schedule";
}) {
  return (
    <div className="lb-health-section" data-kind={kind}>
      <div className="lb-health-section-label mono">{title}</div>
      {items.map(it => {
        const isBroken = it.status === "error" || it.status === "blocked";
        const sched = (it as LeadsSchedule).schedule;
        return (
          <div key={it.id} className="lb-health-row" data-status={it.status}>
            {isBroken && <span className="lb-source-pulse" data-tone={it.status === "error" ? "error" : "warn"}></span>}
            {!isBroken && <span className="lb-health-ok-dot"></span>}
            <span className="lb-health-name">{it.name}</span>
            {sched && <span className="lb-health-sched mono">{sched}</span>}
            <span className={"lb-source-tag " + it.status}>
              {it.status === "live" ? "Live" : it.status === "error" ? "Error" : it.status === "blocked" ? "Blocked" : it.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Tabs
// ─────────────────────────────────────────────────────────────────
type LeadsTab = "action" | "profiles" | "templates" | "sent";

function LeadsTabs({ tab, onChange }: { tab: LeadsTab; onChange: (t: LeadsTab) => void }) {
  const tabs: Array<{ id: LeadsTab; label: string }> = [
    { id: "action", label: "Action board" },
    { id: "profiles", label: "Profiles" },
    { id: "templates", label: "Templates" },
    { id: "sent", label: "Sent" },
  ];
  return (
    <div className="lb-tabs">
      {tabs.map(t => (
        <button
          key={t.id}
          type="button"
          className={"lb-tab" + (tab === t.id ? " active" : "")}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// KPI tile
// ─────────────────────────────────────────────────────────────────
interface LbKpiProps {
  label: string;
  value: string | number;
  breakdown?: string;
  delta?: string;
  deltaTone?: "up" | "down" | "warn" | "";
}
function LbKpi({ label, value, breakdown, delta, deltaTone }: LbKpiProps) {
  return (
    <div className="ab-kpi">
      <div className="ab-kpi-label mono">{label}</div>
      <div className="ab-kpi-value">{value}</div>
      {breakdown && <div className="ab-kpi-breakdown">{breakdown}</div>}
      {delta && (
        <div className={"ab-kpi-delta" + (deltaTone ? " " + deltaTone : "")}>
          {delta}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Source alert
// ─────────────────────────────────────────────────────────────────
// macOS deep-link straight to System Settings → Privacy & Security → Full Disk
// Access. Electron's setWindowOpenHandler shell.openExternal's any non-backend
// URL, so window.open(this) opens the real pane. The legacy
// `com.apple.preference.security?Privacy_AllFiles` anchor only worked on the old
// System Preferences (≤ Monterey); System Settings (Ventura+) uses the
// PrivacySecurity.extension pane id below, which actually scrolls to the section.
const FDA_SETTINGS_URL =
  "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles";

function LbSourceAlert({ blocked }: { blocked: LeadsChannel[] }) {
  if (blocked.length === 0) return null;
  const top = blocked[0];
  const isFda = top.kind === "imessage" || /full disk access/i.test(top.note || "");
  return (
    <div className="lb-alert">
      <span className="lb-alert-icon"><AlertTriangle /></span>
      <span className="lb-alert-label">
        {isFda ? "Apple Messages needs Full Disk Access." : "A lead source needs access."}
      </span>
      <span className="lb-alert-detail">
        {isFda
          ? "Open System Settings → Privacy & Security → Full Disk Access, turn ON Elevate (click + to add it if it's not listed), then quit and reopen Elevate."
          : <><strong>{top.name}:</strong> {top.note}</>}
      </span>
      {isFda ? (
        <button
          type="button"
          className="lb-alert-action"
          onClick={() => window.open(FDA_SETTINGS_URL, "_blank", "noopener,noreferrer")}
        >
          Open Full Disk Access
        </button>
      ) : (
        <Link to="/config#connectors" className="lb-alert-action">Open Settings</Link>
      )}
    </div>
  );
}

// Apple Messages inbound/outbound toggles. Inbound = read chat.db as a lead
// source (needs Full Disk Access — this is what drives the access banner).
// Outbound = send approved texts through Messages (no FDA needed). They are
// independent: you can send outreach without importing your message history.
function LbToggle({
  on, label, hint, onClick, disabled = false,
}: { on: boolean; label: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={hint}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        border: "1px solid var(--border, #2a2a2e)", borderRadius: 8,
        background: "transparent", color: "inherit", padding: "6px 10px",
        cursor: disabled ? "not-allowed" : "pointer", font: "inherit", opacity: disabled ? 0.65 : 1,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 30, height: 18, borderRadius: 999, position: "relative",
          background: on ? "var(--accent-good, #4c9a6a)" : "var(--border, #3a3a3e)",
          transition: "background .15s",
        }}
      >
        <span style={{
          position: "absolute", top: 2, left: on ? 14 : 2, width: 14, height: 14,
          borderRadius: 999, background: "#fff", transition: "left .15s",
        }} />
      </span>
      <span style={{ display: "inline-flex", flexDirection: "column", lineHeight: 1.15, textAlign: "left" }}>
        <span style={{ fontWeight: 600, fontSize: 12 }}>{label}</span>
        <span style={{ opacity: 0.6, fontSize: 11 }}>{on ? "on" : "off"}</span>
      </span>
    </button>
  );
}

function AppleMessagesToggleBar({
  appleMessages, onToggle,
}: {
  appleMessages?: { inbound: boolean; outbound: boolean; blocked?: boolean; note?: string };
  onToggle?: (dir: "inbound" | "outbound", value: boolean) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState<"inbound" | "outbound" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!appleMessages || !onToggle) return null;
  const runToggle = async (dir: "inbound" | "outbound", value: boolean) => {
    setBusy(dir);
    setError(null);
    try {
      await onToggle(dir, value);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update Apple Messages.");
    } finally {
      setBusy(null);
    }
  };
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      padding: "8px 0", marginBottom: 4,
    }}>
      <span style={{ fontWeight: 600, fontSize: 12, opacity: 0.8 }}>Apple Messages</span>
      <LbToggle
        on={appleMessages.inbound}
        label="Inbound (read replies)"
        hint="Read your Mac Messages as a lead source. Needs Full Disk Access for Elevate."
        onClick={() => void runToggle("inbound", !appleMessages.inbound)}
        disabled={busy !== null}
      />
      <LbToggle
        on={appleMessages.outbound}
        label="Outbound (send texts)"
        hint="Send approved texts through Messages. No Full Disk Access required."
        onClick={() => void runToggle("outbound", !appleMessages.outbound)}
        disabled={busy !== null}
      />
      {error && <span style={{ color: "var(--accent-warn, #e0a44c)", fontSize: 12 }}>{error}</span>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// DraftRow
// ─────────────────────────────────────────────────────────────────
function DraftRow({
  draft, selected, expanded, onToggle, onExpand, onAction, busy, onEditTemplate,
}: {
  draft: LeadsDraft;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onAction?: (action: LeadsDraftAction, draft: LeadsDraft) => void;
  busy?: boolean;
  onEditTemplate?: () => void;
}) {
  const [editText, setEditText] = useState(draft.body);
  useEffect(() => { setEditText(draft.body); }, [draft.id, draft.body]);
  const dirty = editText.trim() !== draft.body.trim();
  // Always act on the CURRENT edited text — approving with the original body was
  // dropping every edit. Saving persists the edit (action "edit") without sending.
  const editedDraft = { ...draft, body: editText };
  return (
    <div className={"lb-draft" + (selected ? " selected" : "") + (expanded ? " expanded" : "")}>
      <button type="button" className="lb-draft-check" onClick={onToggle} aria-label="Select draft">
        <span className={"lb-checkbox" + (selected ? " checked" : "")}>
          {selected && <span className="lb-check">✓</span>}
        </span>
      </button>
      <div className="lb-draft-body">
        <button type="button" className="lb-draft-summary" onClick={onExpand}>
          <div className="lb-draft-head">
            <span className="lb-draft-name">{draft.name}</span>
            <span className="lb-draft-meta mono">{draft.source} · {draft.channel}</span>
            {draft.heat === "hot" && <span className="lb-heat">Hot</span>}
            <span className="lb-draft-age">{draft.age} ago</span>
          </div>
          {!expanded && <p className="lb-draft-text">{draft.body}</p>}
        </button>
        {expanded ? (
          <div className="lb-draft-expand">
            <div className="lb-draft-recipient mono">To · {draft.name} · {draft.source}</div>
            <textarea
              className="lb-draft-edit"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={Math.max(3, Math.ceil(editText.length / 70))}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => { e.stopPropagation(); if (dirty && onAction) onAction("edit", editedDraft); }}
            />
            <div className="lb-draft-expand-foot">
              <span className="lb-draft-template-link">
                Generated from <strong>Warm intro</strong> template · <button type="button" className="lb-link" onClick={(e) => { e.stopPropagation(); onEditTemplate?.(); }}>edit template</button>
              </span>
              {dirty && (
                <button
                  type="button"
                  className="lb-btn ghost sm lb-draft-save"
                  disabled={busy || !onAction}
                  onClick={(e) => { e.stopPropagation(); onAction?.("edit", editedDraft); }}
                >
                  {busy ? "…" : "Save"}
                </button>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <div className="lb-draft-actions">
        <button
          type="button"
          className="lb-btn ghost sm"
          disabled={busy || !onAction}
          onClick={(e) => { e.stopPropagation(); onAction?.("skip", draft); }}
        >
          {busy ? "…" : "Skip"}
        </button>
        <button
          type="button"
          className="lb-btn primary sm"
          disabled={busy || !onAction}
          onClick={(e) => { e.stopPropagation(); onAction?.("approve", editedDraft); }}
        >
          {busy ? "…" : "Approve"}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// ActionQueue
// ─────────────────────────────────────────────────────────────────
type QueueTab = "approve" | "hot" | "followups" | "skipped";

function ActionQueue({
  drafts, pipeline, sourceFilter, onDraftAction, onEditTemplate, onOpenHotLead,
}: {
  drafts: LeadsDraft[];
  pipeline: LeadsPipeline;
  sourceFilter: string;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft) => void | Promise<void>;
  onEditTemplate?: () => void;
  onOpenHotLead?: (entry: LeadsHotEntry) => void;
}) {
  const [tab, setTab] = useState<QueueTab>("approve");
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const PAGE = 5;

  const handleDraftAction = async (action: LeadsDraftAction, draft: LeadsDraft) => {
    if (!onDraftAction) return;
    setActionError(null);
    setBusy((b) => { const n = new Set(b); n.add(draft.id); return n; });
    try {
      await onDraftAction(action, draft);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Could not ${action} draft.`);
    } finally {
      setBusy((b) => { const n = new Set(b); n.delete(draft.id); return n; });
    }
  };

  const handleBulkAction = async (action: LeadsDraftAction) => {
    if (!onDraftAction) return;
    const targets = filteredDrafts.filter((d) => selected.has(d.id));
    setSelected(new Set());
    for (const draft of targets) {
      await handleDraftAction(action, draft);
    }
  };

  useEffect(() => { setPage(0); setSelected(new Set()); setExpanded(null); }, [tab, sourceFilter]);

  const filteredDrafts = useMemo(() => {
    return drafts.filter((draft) => matchesLeadsSourceFilter(draft, sourceFilter));
  }, [drafts, sourceFilter]);

  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const allowed = new Set(filteredDrafts.map((draft) => draft.id));
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (allowed.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [filteredDrafts]);

  const tabs: Array<{ id: QueueTab; label: string; count: number; urgent: boolean }> = [
    { id: "approve", label: "Approve", count: filteredDrafts.length, urgent: filteredDrafts.length > 0 },
    { id: "hot", label: "Hot leads", count: pipeline.hot.length, urgent: false },
    { id: "followups", label: "Follow-ups", count: pipeline.followups.length, urgent: false },
    { id: "skipped", label: "Skipped", count: pipeline.skipped.length, urgent: false },
  ];

  const activeList: Array<LeadsDraft | LeadsHotEntry | LeadsSkippedEntry> =
    tab === "approve" ? filteredDrafts :
    tab === "hot" ? pipeline.hot :
    tab === "followups" ? pipeline.followups :
    tab === "skipped" ? pipeline.skipped : [];

  const totalPages = Math.max(1, Math.ceil(activeList.length / PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = showAll ? activeList : activeList.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const rangeStart = activeList.length === 0 ? 0 : safePage * PAGE + 1;
  const rangeEnd = Math.min(activeList.length, safePage * PAGE + PAGE);

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAllDrafts() {
    setSelected(prev => nextDraftQueueSelection(prev, filteredDrafts));
  }

  return (
    <section className="ab-card lb-queue">
      <header className="lb-queue-head">
        <div className="lb-queue-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              type="button"
              className={"lb-queue-tab" + (tab === t.id ? " active" : "")}
              onClick={() => setTab(t.id)}
            >
              {t.urgent && t.count > 0 && <span className="lb-queue-pulse"></span>}
              <span>{t.label}</span>
              <span className="lb-queue-tab-count mono">{t.count}</span>
            </button>
          ))}
        </div>

        {tab === "approve" && filteredDrafts.length > 0 && (
          <div className="lb-queue-actions">
            {selected.size > 0 ? (
              <>
                <span className="lb-replies-selected mono">{selected.size} selected</span>
                <button type="button" className="lb-btn ghost sm" onClick={() => setSelected(new Set())}>Clear</button>
                <button type="button" className="lb-btn ghost sm" disabled={!onDraftAction} onClick={() => void handleBulkAction("skip")}>Skip</button>
                <button type="button" className="lb-btn primary sm" disabled={!onDraftAction} onClick={() => void handleBulkAction("approve")}>Approve {selected.size}</button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="lb-replies-selectall"
                  onClick={toggleAllDrafts}
                  aria-label={`Select all ${filteredDrafts.length} drafts`}
                >
                  <span className="lb-checkbox" aria-hidden="true"></span>
                  <span>Select all {filteredDrafts.length}</span>
                </button>
                <span className="lb-replies-hint">Nothing sends until you click Approve.</span>
              </>
            )}
          </div>
        )}
      </header>

      {actionError && (
        <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{actionError}</div>
      )}

      <div className="lb-queue-list">
        {tab === "approve" && (
          visible.length === 0
            ? <div className="lb-replies-empty">Inbox zero on drafts. Next outreach run lands in ~1h.</div>
            : (visible as LeadsDraft[]).map(d => (
                <DraftRow
                  key={d.id}
                  draft={d}
                  selected={selected.has(d.id)}
                  expanded={expanded === d.id}
                  onToggle={() => toggle(d.id)}
                  onExpand={() => setExpanded(e => e === d.id ? null : d.id)}
                  onAction={onDraftAction ? handleDraftAction : undefined}
                  busy={busy.has(d.id)}
                  onEditTemplate={onEditTemplate}
                />
              ))
        )}
        {tab === "hot" && (
          visible.length === 0
            ? <div className="lb-replies-empty">No hot leads right now.</div>
            : (visible as LeadsHotEntry[]).map(p => (
                <div key={p.id} className="lb-q-row">
                  <span className="lb-heat-dot"></span>
                  <div className="lb-q-body">
                    <div className="lb-q-name">{p.name}</div>
                    <div className="lb-q-meta">{p.signal} · {p.age}</div>
                  </div>
                  <button type="button" className="lb-btn ghost sm" disabled={!onOpenHotLead} onClick={() => onOpenHotLead?.(p)}>Draft reply</button>
                  <button type="button" className="lb-btn ghost sm" disabled={!onOpenHotLead} onClick={() => onOpenHotLead?.(p)}>Open thread</button>
                </div>
              ))
        )}
        {tab === "followups" && (
          <div className="lb-replies-empty">
            No follow-ups queued.<br />
            <span className="lb-replies-hint-2">Threads that go cold 7+ days re-enter this queue automatically.</span>
          </div>
        )}
        {tab === "skipped" && (
          visible.length === 0
            ? <div className="lb-replies-empty">Nothing skipped recently.</div>
            : (visible as LeadsSkippedEntry[]).map(p => (
                <div key={p.id} className="lb-q-row">
                  <span className="lb-q-mute-dot"></span>
                  <div className="lb-q-body">
                    <div className="lb-q-name">{p.name}</div>
                    <div className="lb-q-meta">{p.reason}</div>
                  </div>
                  <button
                    type="button"
                    className="lb-btn ghost sm"
                    disabled={busy.has(p.id) || !onDraftAction || !p.sourceId || !p.taskId}
                    onClick={() => void handleDraftAction("restore", {
                      id: p.id,
                      name: p.name,
                      source: "",
                      channel: "",
                      age: "",
                      body: "",
                      heat: "warm",
                      sourceId: p.sourceId,
                      taskId: p.taskId,
                    })}
                  >
                    {busy.has(p.id) ? "…" : "Undo"}
                  </button>
                </div>
              ))
        )}
      </div>

      {activeList.length > PAGE && (
        <footer className="ab-inbox-foot">
          <span className="ab-inbox-range mono">
            {showAll ? `Showing all ${activeList.length}` : `${rangeStart}–${rangeEnd} of ${activeList.length}`}
          </span>
          <div className="ab-inbox-pager">
            {!showAll && (
              <>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  aria-label="Previous"
                >‹</button>
                <span className="ab-inbox-page-num mono">{safePage + 1} / {totalPages}</span>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage === totalPages - 1}
                  aria-label="Next"
                >›</button>
              </>
            )}
            <button
              type="button"
              className="ab-inbox-page-toggle"
              onClick={() => { setShowAll(s => !s); setPage(0); }}
            >
              {showAll ? "Paginate" : "Show all"}
            </button>
          </div>
        </footer>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// StatusPill
// ─────────────────────────────────────────────────────────────────
const PROFILE_STATUS_OPTIONS = [
  "No status", "New Lead", "Follow Up", "Ghosting", "Dead", "Closed Buyer", "Closed Seller",
];
const PROFILE_STATUS_CLASS: Record<string, string> = {
  "New Lead": "new",
  "Follow Up": "buyer",
  "Ghosting": "potential",
  "Dead": "",
  "Closed Buyer": "active",
  "Closed Seller": "seller",
  "Closed Sell…": "active",
  "Active lead": "active",
  "New leads": "new",
  "Buyer track": "buyer",
  "Seller CMA": "seller",
  "Potential": "potential",
};

function StatusPill({
  status, onChange, className,
}: {
  status: string;
  onChange: (s: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDocClick); window.removeEventListener("keydown", onKey); };
  }, [open]);
  const display = status || "No status";
  const cls = PROFILE_STATUS_CLASS[display] || "";
  return (
    <div className="lb-status-wrap" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={"lb-profile-status " + cls + (className ? " " + className : "")}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
      >
        <span>{display}</span>
        <ChevronDown className="lb-profile-status-caret" />
      </button>
      {open && (
        <div className="lb-status-menu" role="listbox">
          {PROFILE_STATUS_OPTIONS.map(s => {
            const sCls = PROFILE_STATUS_CLASS[s] || "";
            const selected = s === display;
            return (
              <button
                key={s}
                type="button"
                role="option"
                aria-selected={selected}
                className="lb-status-menu-row"
                onClick={() => { onChange(s); setOpen(false); }}
              >
                <span className={"lb-status-menu-dot " + sCls} aria-hidden="true" />
                <span>{s}</span>
                <svg className="lb-status-menu-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M5 12l4 4 10-10" />
                </svg>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// ProfileRow
// ─────────────────────────────────────────────────────────────────
function ProfileRow({
  profile, onOpen, onStatusChange, onFavoriteChange, favoriteBusy,
}: {
  profile: LeadsProfile;
  onOpen?: (p: LeadsProfile) => void;
  onStatusChange?: (profile: LeadsProfile, value: string) => void;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  favoriteBusy?: boolean;
}) {
  const heatTone = profile.heat >= 80 ? "hot" : profile.heat >= 50 ? "warm" : "cool";
  const initials = profile.name
    .split(/\s+/)
    .map(w => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen?.(profile);
    }
  };
  const isFavorite = Boolean(profile.favorite);
  return (
    <div
      role="button"
      tabIndex={0}
      className={"lb-profile-row" + (isFavorite ? " favorite" : "")}
      onClick={() => onOpen?.(profile)}
      onKeyDown={handleKeyDown}
    >
      <div className="lb-profile-favorite-cell" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className={"lb-profile-star" + (isFavorite ? " active" : "")}
          aria-label={isFavorite ? `Remove ${profile.name} from favorites` : `Add ${profile.name} to favorites`}
          aria-pressed={isFavorite}
          title={isFavorite ? "Remove favorite" : "Add favorite"}
          disabled={favoriteBusy || !onFavoriteChange}
          onClick={(e) => {
            e.stopPropagation();
            void onFavoriteChange?.(profile, !isFavorite);
          }}
        >
          {isFavorite ? "★" : "☆"}
        </button>
      </div>
      <div className="lb-profile-avatar" data-tone={heatTone}>{initials}</div>
      <div className="lb-profile-name-cell">
        <span className="lb-profile-name">{profile.name}</span>
        {profile.verified && <span className="lb-profile-verified-dot" title="Verified">✓</span>}
      </div>
      <div className="lb-profile-email mono">{profile.email}</div>
      <div className="lb-profile-phone mono">{profile.phone || "—"}</div>
      <div className={"lb-profile-heat-cell " + heatTone}>
        <span className="lb-profile-heat-num mono">{profile.heat}</span>
        <span className="lb-profile-heat-label">{heatTone}</span>
      </div>
      <div className="lb-profile-status-cell" onClick={(e) => e.stopPropagation()}>
        <StatusPill
          status={profile.status}
          onChange={(v) => onStatusChange && onStatusChange(profile, v)}
        />
      </div>
      <div className="lb-profile-source-cell">
        <div className="lb-profile-source-name">{profile.source}</div>
        <div className="lb-profile-source-sub mono">{profile.contact}</div>
      </div>
      <div className="lb-profile-preview">{profile.lastMsg || "—"}</div>
      <div className="lb-profile-touch-cell mono">{profile.lastTouch || profile.age}</div>
      <div className="lb-profile-actions">
        <span className="lb-profile-chev" aria-hidden="true">›</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// ProfilesList
// ─────────────────────────────────────────────────────────────────
function ProfilesList({
  profiles: profilesProp, sourceFilter, onOpen, statusOverrides, onStatusChange, onFavoriteChange,
}: {
  profiles: LeadsProfile[];
  sourceFilter: string;
  onOpen: (p: LeadsProfile) => void;
  statusOverrides: Record<string, string>;
  onStatusChange: (profile: LeadsProfile, value: string) => void;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
}) {
  const [statusFilter, setStatusFilter] = useState<"all" | "verified" | "unverified" | "potential" | "favorites">("all");
  const [favoriteBusy, setFavoriteBusy] = useState<Record<string, boolean>>({});
  const [favoriteError, setFavoriteError] = useState<string | null>(null);

  const profiles = useMemo(() => (
    profilesProp.map(p => (statusOverrides && statusOverrides[p.id]) ? { ...p, status: statusOverrides[p.id] } : p)
  ), [profilesProp, statusOverrides]);

  const filtered = useMemo(() => {
    let list = profiles;
    list = list.filter((profile) => matchesLeadsSourceFilter(profile, sourceFilter));
    if (statusFilter === "verified") list = list.filter(p => p.verified);
    if (statusFilter === "unverified") list = list.filter(p => !p.verified);
    if (statusFilter === "potential") list = list.filter(p => !p.verified);
    if (statusFilter === "favorites") list = list.filter(p => Boolean(p.favorite));
    return [...list].sort((a, b) => Number(Boolean(b.favorite)) - Number(Boolean(a.favorite)));
  }, [profiles, sourceFilter, statusFilter]);

  const grouped = useMemo(() => {
    const g: Record<"active" | "verified" | "unverified", LeadsProfile[]> = { active: [], verified: [], unverified: [] };
    for (const p of filtered) g[p.group].push(p);
    return g;
  }, [filtered]);

  const verifiedCount = profiles.filter(p => p.verified).length;
  const potentialCount = profiles.filter(p => !p.verified).length;
  const favoriteCount = profiles.filter(p => Boolean(p.favorite)).length;
  const handleFavoriteChange = async (profile: LeadsProfile, favorite: boolean) => {
    if (!onFavoriteChange) return;
    setFavoriteError(null);
    setFavoriteBusy((state) => ({ ...state, [profile.id]: true }));
    try {
      await onFavoriteChange(profile, favorite);
    } catch (err) {
      setFavoriteError(err instanceof Error ? err.message : "Could not update favorite.");
    } finally {
      setFavoriteBusy((state) => ({ ...state, [profile.id]: false }));
    }
  };

  const sections: Array<{ id: "active" | "verified" | "unverified"; label: string; desc: string }> = [
    { id: "active", label: "Active conversations", desc: "People they are actively messaging stay first, sorted by the newest conversation activity." },
    { id: "verified", label: "Verified — ready to queue", desc: "Verified profiles waiting on buyer workflow or seller CMA before Admin handoff." },
    { id: "unverified", label: "Unverified — needs review", desc: "Recent inbound that hasn't been verified yet." },
  ];

  return (
    <section className="ab-card lb-profiles">
      <header className="lb-profiles-head">
        <div className="lb-profiles-title-block">
          <h2 className="lb-profiles-title">Profile list</h2>
          <p className="lb-profiles-desc">
            Active conversations stay at the top, then verified profiles queue buyer workflows or seller CMA before Admin handoff.
          </p>
        </div>
        <div className="lb-profiles-badges">
          <button
            type="button"
            className={"lb-pbadge" + (statusFilter === "all" ? " active" : "")}
            onClick={() => setStatusFilter("all")}
          >
            <span className="lb-pbadge-num mono">{profiles.length}</span>
            <span>total</span>
          </button>
          <button
            type="button"
            className={"lb-pbadge favorite" + (statusFilter === "favorites" ? " active" : "")}
            onClick={() => setStatusFilter(s => s === "favorites" ? "all" : "favorites")}
          >
            <span className="lb-pbadge-num mono">{favoriteCount}</span>
            <span>favorites</span>
          </button>
          <button
            type="button"
            className={"lb-pbadge verified" + (statusFilter === "verified" ? " active" : "")}
            onClick={() => setStatusFilter(s => s === "verified" ? "all" : "verified")}
          >
            <span className="lb-pbadge-num mono">{verifiedCount}</span>
            <span>verified</span>
          </button>
          <button
            type="button"
            className={"lb-pbadge potential" + (statusFilter === "potential" ? " active" : "")}
            onClick={() => setStatusFilter(s => s === "potential" ? "all" : "potential")}
          >
            <span className="lb-pbadge-num mono">{potentialCount}</span>
            <span>potential leads</span>
          </button>
        </div>
      </header>

      {favoriteError && (
        <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{favoriteError}</div>
      )}

      {sections.map(sec => {
        const items = grouped[sec.id] || [];
        if (items.length === 0) return null;
        return (
          <div key={sec.id} className="lb-profiles-section">
            <div className="lb-profiles-section-head">
              <span className="lb-profiles-section-label mono">{sec.label}</span>
              <span className="lb-profiles-section-count mono">{items.length}</span>
            </div>
            <div className="lb-profiles-colhead">
              <span className="mono">Fav</span>
              <span></span>
              <span className="mono">Name</span>
              <span className="mono">Email</span>
              <span className="mono">Phone</span>
              <span className="mono">Heat</span>
              <span className="mono">Status</span>
              <span className="mono">Source</span>
              <span className="mono">Last communication</span>
              <span className="mono lb-profile-touch-col">Last contact</span>
              <span></span>
            </div>
            <div className="lb-profiles-list">
              {items.map(p => (
                <ProfileRow
                  key={p.id}
                  profile={p}
                  onOpen={onOpen}
                  onStatusChange={onStatusChange}
                  onFavoriteChange={handleFavoriteChange}
                  favoriteBusy={Boolean(favoriteBusy[p.id])}
                />
              ))}
            </div>
          </div>
        );
      })}

      {filtered.length === 0 && (
        <div className="lb-replies-empty">No profiles match this filter.</div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// TemplatesView
// ─────────────────────────────────────────────────────────────────
export interface TemplateMutations {
  // Create a template in a lane. Returns once the list is refreshed.
  onCreate: (laneId: string, name: string, body: string) => Promise<void>;
  // Save name/body edits to an existing template.
  onSave: (id: string, name: string, body: string) => Promise<void>;
  // Toggle a template's active flag (Pause / Resume).
  onTogglePause: (id: string, active: boolean) => Promise<void>;
  // Delete a template.
  onDelete: (id: string) => Promise<void>;
  // Ask the backend for a suggested variant for a lane. Resolves to the
  // suggested name/body so the caller can open a prefilled editor.
  onSuggest: (laneId: string) => Promise<{ name: string; body: string }>;
}

type TplEditor =
  | { mode: "create"; laneId: string; name: string; body: string }
  | { mode: "edit"; id: string; laneId: string; name: string; body: string };

function TemplateEditorRow({
  editor, onChange, onSave, onCancel, busy,
}: {
  editor: TplEditor;
  onChange: (patch: Partial<{ name: string; body: string }>) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="lb-tpl-row lb-tpl-editor">
      <div className="lb-tpl-row-body">
        <input
          type="text"
          className="lb-tpl-edit-name"
          value={editor.name}
          placeholder="Template name"
          onChange={(e) => onChange({ name: e.target.value })}
          disabled={busy}
        />
        <textarea
          className="lb-draft-edit"
          value={editor.body}
          placeholder="Body. Use {first_name}, {area}, {topic}, etc."
          rows={4}
          onChange={(e) => onChange({ body: e.target.value })}
          disabled={busy}
        />
      </div>
      <div className="lb-tpl-row-actions">
        <button type="button" className="lb-btn ghost sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className="lb-btn primary sm" onClick={onSave} disabled={busy}>
          {busy ? "…" : editor.mode === "create" ? "Add" : "Save"}
        </button>
      </div>
    </div>
  );
}

function TemplateRow({
  template, onPause, onEdit, onDelete, busy,
}: {
  template: LeadsTemplateItem;
  onPause?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  busy?: boolean;
}) {
  return (
    <div className={"lb-tpl-row" + (template.active ? "" : " paused")}>
      <div className="lb-tpl-row-body">
        <div className="lb-tpl-row-name">{template.name}</div>
        <div className="lb-tpl-row-text">{template.body}</div>
        <div className="lb-tpl-row-meta mono">
          <span>Used {template.used}×</span>
          <span className="lb-tpl-meta-sep">·</span>
          <span>{template.replies} replies</span>
          {template.replyRate != null && (
            <>
              <span className="lb-tpl-meta-sep">·</span>
              <span>{template.replyRate}% reply rate</span>
            </>
          )}
          {!template.active && (
            <>
              <span className="lb-tpl-meta-sep">·</span>
              <span>paused</span>
            </>
          )}
        </div>
      </div>
      <div className="lb-tpl-row-actions">
        <button type="button" className="lb-tpl-icon-btn" aria-label={template.active ? "Pause" : "Resume"} title={template.active ? "Pause" : "Resume"} disabled={busy || !onPause} onClick={onPause}>{template.active ? "‖" : "▸"}</button>
        <button type="button" className="lb-tpl-icon-btn" aria-label="Edit" disabled={busy || !onEdit} onClick={onEdit}>✎</button>
        <button type="button" className="lb-tpl-icon-btn danger" aria-label="Delete" disabled={busy || !onDelete} onClick={onDelete}>🗑</button>
      </div>
    </div>
  );
}

function TemplatesView({ groups, mutations }: { groups: LeadsTemplateLane[]; mutations?: TemplateMutations }) {
  const total = groups.reduce((n, g) => n + g.templates.length, 0);
  const active = groups.reduce((n, g) => n + g.active, 0);

  const [editor, setEditor] = useState<TplEditor | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LeadsTemplateItem | null>(null);

  const openCreate = (laneId: string) => {
    setError(null);
    setEditor({ mode: "create", laneId, name: "", body: "" });
  };
  const openEdit = (laneId: string, t: LeadsTemplateItem) => {
    setError(null);
    setEditor({ mode: "edit", id: t.id, laneId, name: t.name, body: t.body });
  };
  const closeEditor = () => { setEditor(null); setError(null); };

  const saveEditor = async () => {
    if (!editor || !mutations) return;
    const name = editor.name.trim();
    const body = editor.body.trim();
    if (!name || !body) { setError("Name and body are both required."); return; }
    setBusy(true);
    setError(null);
    try {
      if (editor.mode === "create") await mutations.onCreate(editor.laneId, name, body);
      else await mutations.onSave(editor.id, name, body);
      setEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save template.");
    } finally {
      setBusy(false);
    }
  };

  const suggest = async (laneId: string) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      const variant = await mutations.onSuggest(laneId);
      setEditor({ mode: "create", laneId, name: variant.name, body: variant.body });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not suggest a variant.");
    } finally {
      setBusy(false);
    }
  };

  const togglePause = async (t: LeadsTemplateItem) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      await mutations.onTogglePause(t.id, !t.active);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update template.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: LeadsTemplateItem) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      await mutations.onDelete(t.id);
      setDeleteTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete template.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lb-templates">
      <section className="ab-card lb-tpl-overview">
        <header className="lb-tpl-overview-head">
          <div>
            <h2 className="lb-profiles-title">Templates overview</h2>
            <p className="lb-profiles-desc">
              What's working, what's not, and fresh variants for approval. Best/worst rank after 5+ sends. Drift flags templates whose 30-day reply rate dropped 30%+ vs all-time.
            </p>
          </div>
          <span className="lb-tpl-overview-total mono">{total} total · {active} active</span>
        </header>

        {error && <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{error}</div>}

        <div className="lb-tpl-summary">
          {groups.map(g => (
            <div key={g.lane} className="lb-tpl-summary-card">
              <div className="lb-tpl-summary-head">
                <span className="lb-tpl-summary-icon" aria-hidden="true">{g.icon}</span>
                <span className="lb-tpl-summary-name">{g.lane}</span>
                <button type="button" className="lb-btn ghost sm" disabled={busy || !mutations} onClick={() => void suggest(g.laneId)}>✦ Suggest variant</button>
              </div>
              <div className="lb-tpl-summary-stats">
                <span><strong className="mono">{g.active}</strong> <span className="lb-tpl-stat-label">active</span></span>
                <span className="lb-tpl-stat-sep">·</span>
                <span><strong className="mono">{g.sent}</strong> <span className="lb-tpl-stat-label">sent</span></span>
                <span className="lb-tpl-stat-sep">·</span>
                <span><strong className="mono">{g.replyRate}%</strong> <span className="lb-tpl-stat-label">reply</span></span>
              </div>
              <div className="lb-tpl-summary-foot">{g.needMore}</div>
            </div>
          ))}
        </div>
      </section>

      {groups.map(g => (
        <section key={g.lane} className="ab-card lb-tpl-group">
          <header className="lb-tpl-group-head">
            <span className="lb-tpl-group-icon" aria-hidden="true">{g.icon}</span>
            <span className="lb-tpl-group-name">{g.lane}</span>
            <span className="lb-tpl-group-count mono">{g.templates.length} templates</span>
            <button type="button" className="lb-btn ghost sm" style={{ marginLeft: "auto" }} disabled={busy || !mutations} onClick={() => openCreate(g.laneId)}>+ New template</button>
          </header>
          <div className="lb-tpl-list">
            {g.templates.map(t => (
              editor?.mode === "edit" && editor.id === t.id ? (
                <TemplateEditorRow
                  key={t.id}
                  editor={editor}
                  onChange={(patch) => setEditor((prev) => (prev ? { ...prev, ...patch } : prev))}
                  onSave={saveEditor}
                  onCancel={closeEditor}
                  busy={busy}
                />
              ) : (
                <TemplateRow
                  key={t.id}
                  template={t}
                  onPause={mutations ? () => void togglePause(t) : undefined}
                  onEdit={mutations ? () => openEdit(g.laneId, t) : undefined}
                  onDelete={mutations ? () => setDeleteTarget(t) : undefined}
                  busy={busy}
                />
              )
            ))}
            {editor?.mode === "create" && editor.laneId === g.laneId && (
              <TemplateEditorRow
                editor={editor}
                onChange={(patch) => setEditor((prev) => (prev ? { ...prev, ...patch } : prev))}
                onSave={saveEditor}
                onCancel={closeEditor}
                busy={busy}
              />
            )}
          </div>
        </section>
      ))}
      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Delete "${deleteTarget?.name ?? "this template"}"?`}
        description="This removes the outreach template from this lane. This action cannot be undone here."
        confirmLabel="Delete"
        destructive
        loading={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) void remove(deleteTarget);
        }}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// SentView
// ─────────────────────────────────────────────────────────────────
function SentView({
  messages, onRefresh,
}: {
  messages: LeadsSentMessage[];
  // Refetch sent messages. includePending=true asks the gateway for queued /
  // retrying / failed rows too. Returns once the parent has the new list.
  onRefresh?: (includePending: boolean) => Promise<void>;
}) {
  const [includeQueued, setIncludeQueued] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = async (includePending: boolean) => {
    if (!onRefresh) return;
    setBusy(true);
    try {
      await onRefresh(includePending);
    } finally {
      setBusy(false);
    }
  };

  const toggleQueued = () => {
    const next = !includeQueued;
    setIncludeQueued(next);
    // Refetch with the new flag so the list reflects the toggle. If the parent
    // didn't pass onRefresh (static demo data) we fall back to client-side
    // filtering below.
    void refresh(next);
  };

  // Client-side fallback filter for when no refetch is wired: hide non-sent rows
  // unless "include queued" is on.
  const visible = onRefresh || includeQueued ? messages : messages.filter(m => m.status === "sent");

  return (
    <section className="ab-card lb-sent">
      <header className="lb-sent-head">
        <div>
          <h2 className="lb-profiles-title">Sent messages</h2>
          <p className="lb-profiles-desc">
            Outbound history. Every message you approved on the Action Board lands here.
          </p>
        </div>
        <div className="lb-sent-controls">
          <span className="lb-sent-count mono">{visible.length} messages</span>
          <label className="lb-sent-toggle">
            <span className={"lb-checkbox" + (includeQueued ? " checked" : "")} onClick={toggleQueued}>
              {includeQueued && <span className="lb-check">✓</span>}
            </span>
            <span>Include queued / retrying / failed</span>
          </label>
          <button type="button" className="lb-btn ghost sm" disabled={busy || !onRefresh} onClick={() => void refresh(includeQueued)}>
            {busy ? "…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="lb-sent-table">
        <div className="lb-sent-row lb-sent-header-row">
          <span className="lb-sent-h mono">When</span>
          <span className="lb-sent-h mono">Recipient</span>
          <span className="lb-sent-h mono">Source · Transport</span>
          <span className="lb-sent-h mono">Message</span>
          <span className="lb-sent-h mono">Status</span>
        </div>
        {visible.map(m => (
          <div key={m.id} className="lb-sent-row">
            <span className="lb-sent-when mono">{m.when}</span>
            <span className="lb-sent-recipient">{m.recipient}</span>
            <span className="lb-sent-source">
              <div>{m.source}</div>
              <div className="lb-sent-transport mono">{m.transport}</div>
            </span>
            <span className="lb-sent-msg">
              <div>{m.message}</div>
              <div className="lb-sent-msg-id mono">id: {m.msgId}</div>
            </span>
            <span className={"lb-sent-status " + (m.status === "sent" ? "sent" : m.status === "failed" ? "failed" : "queued")}>{(m.status || "sent").toUpperCase()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// ProfileDrawer
// ─────────────────────────────────────────────────────────────────
function ProfileDrawer({
  profile, onClose, onStatusChange,
}: {
  profile: LeadsProfile;
  onClose: () => void;
  onStatusChange?: (profile: LeadsProfile, value: string) => void;
}) {
  const handleStatusChange = (v: string) => {
    onStatusChange?.(profile, v);
  };
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loadingCtx, setLoadingCtx] = useState(false);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const sourceId = profile.sourceId || "";
  const threadId = profile.threadId || "";
  useEffect(() => {
    if (!sourceId || !threadId) {
      setContext(null);
      return;
    }
    let cancelled = false;
    setLoadingCtx(true);
    setCtxError(null);
    api
      .getThreadContext(sourceId, threadId)
      .then((res: ThreadContextResponse) => {
        if (!cancelled) setContext(res);
      })
      .catch((err: { message?: string }) => {
        if (!cancelled) setCtxError(err?.message || "Failed to load thread");
      })
      .finally(() => {
        if (!cancelled) setLoadingCtx(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId, threadId]);

  if (!profile) return null;

  const heatTone = profile.heat >= 80 ? "hot" : profile.heat >= 50 ? "warm" : "cool";

  const fmtTime = (iso?: string | null) => {
    if (!iso) return "";
    const t = new Date(iso);
    if (!isFinite(t.getTime())) return "";
    return t.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  };

  const activity = (context?.activity || []).map((a) => ({
    id: a.id,
    kind: (a.type || "activity").replace(/_/g, " "),
    time: fmtTime(a.timestamp),
    title: a.title,
    summary: a.summary,
  }));

  const messages = (context?.messages || []).map((m) => ({
    id: m.id,
    direction: m.direction === "outbound" ? "out" : "in",
    from: m.direction === "outbound" ? "You" : (m.sender || profile.name),
    text: m.text || "",
    time: fmtTime(m.timestamp),
  }));

  const notes = context?.notes || [];
  const tasks = context?.tasks || [];

  const sendHistory = (context?.sends || []).map((h, idx) => ({
    id: h.id || String(idx),
    transport: (h.channel || "EMAIL").toUpperCase(),
    status: h.status || "sent",
    time: fmtTime(h.createdAt),
    text: (h.payload && (h.payload.text || h.payload.body)) || "",
  }));

  return (
    <div className="lb-drawer-backdrop" onClick={onClose}>
      <aside className="lb-drawer" role="dialog" aria-modal="true" aria-label={"Profile: " + profile.name} onClick={(e) => e.stopPropagation()}>
        <header className="lb-drawer-head">
          <div className="lb-drawer-head-title">
            <h2 className="lb-drawer-name">{profile.name}</h2>
            <div className="lb-drawer-tags">
              <span className="lb-drawer-source mono">{profile.source.toLowerCase().replace(" crm", "")}</span>
              <span className="lb-drawer-tag mono">Outreach</span>
              <span className="lb-drawer-msg-count mono">{messages.length} messages</span>
            </div>
          </div>
          <div className="lb-drawer-head-actions">
            <StatusPill status={profile.status} onChange={handleStatusChange} />
            <button type="button" className="lb-drawer-close" onClick={onClose} aria-label="Close">×</button>
          </div>
        </header>

        <div className="lb-drawer-body">
          <div className="lb-drawer-thread">
            {loadingCtx ? (
              <ListSkeleton rows={4} />
            ) : ctxError ? (
              <div className="lb-drawer-empty">{ctxError}</div>
            ) : messages.length === 0 ? (
              <div className="lb-drawer-empty">No messages on file yet.</div>
            ) : (
              messages.map(m => (
                <div key={m.id} className={"lb-drawer-msg " + m.direction}>
                  <div className="lb-drawer-msg-head mono">{m.from} · {m.time}</div>
                  <div className="lb-drawer-msg-text">{m.text}</div>
                </div>
              ))
            )}
          </div>

          <aside className="lb-drawer-side">
            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Lead score</div>
              <div className={"lb-drawer-score " + heatTone}>
                <span className="lb-drawer-score-num">{profile.heat}</span>
                <span className="lb-drawer-score-label">{heatTone}</span>
              </div>
              <div className="lb-drawer-kv">
                <span className="lb-drawer-kv-label mono">Source</span>
                <span className="lb-drawer-kv-val">{profile.source}</span>
              </div>
              <div className="lb-drawer-kv">
                <span className="lb-drawer-kv-label mono">Owner</span>
                <span className="lb-drawer-kv-val">Demo Agent</span>
              </div>
              <div className="lb-drawer-pills">
                {profile.tags.map(t => (
                  <span key={t} className="lb-drawer-pill mono">{t.toLowerCase()}</span>
                ))}
              </div>
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Contact</div>
              <div className="lb-drawer-contact">{profile.email}</div>
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">▤ Notes <span className="lb-drawer-section-count">{notes.length}</span></div>
              {notes.length === 0 ? (
                <div className="lb-drawer-empty-small">No notes yet.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {notes.map(n => (
                    <div key={n.id} className="lb-drawer-activity-row" title={n.summary || n.title || ""}>
                      <span className="lb-drawer-activity-kind">{n.title || n.summary || "Note"}</span>
                      <span className="lb-drawer-activity-time mono">{fmtTime(n.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">▦ Tasks <span className="lb-drawer-section-count">{tasks.length}</span></div>
              {tasks.length === 0 ? (
                <div className="lb-drawer-empty-small">No tasks.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {tasks.map(t => (
                    <div key={t.id} className="lb-drawer-activity-row" title={t.summary || t.title || ""}>
                      <span className="lb-drawer-activity-kind">{t.title || "Task"}</span>
                      <span className="lb-drawer-activity-time mono">{fmtTime(t.dueAt || t.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">∿ Property activity <span className="lb-drawer-section-count">{activity.length}</span></div>
              {activity.length === 0 ? (
                <div className="lb-drawer-empty-small">No activity recorded.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {activity.map(a => (
                    <div key={a.id} className="lb-drawer-activity-row" title={a.summary || a.title || ""}>
                      <span className="lb-drawer-activity-kind mono">{a.kind}</span>
                      <span className="lb-drawer-activity-time mono">{a.time}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Send history <span className="lb-drawer-section-count">{sendHistory.length}</span></div>
              {sendHistory.length === 0 ? (
                <div className="lb-drawer-empty-small">No outbound sends yet.</div>
              ) : (
                sendHistory.map(h => (
                  <div key={h.id} className="lb-drawer-send">
                    <div className="lb-drawer-send-head">
                      <span className="lb-drawer-send-transport mono">{h.transport}</span>
                      <span className="lb-drawer-send-status mono">{h.status}</span>
                    </div>
                    <div className="lb-drawer-send-text">{h.text}</div>
                    <div className="lb-drawer-send-time mono">{h.time}</div>
                  </div>
                ))
              )}
            </section>
          </aside>
        </div>
      </aside>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// LeadsBoard root
// ─────────────────────────────────────────────────────────────────
export interface LeadsBoardProps {
  sources?: LeadsSource[];
  channels?: LeadsChannel[];
  schedules?: LeadsSchedule[];
  available?: LeadsAvailable[];
  drafts?: LeadsDraft[];
  pipeline?: LeadsPipeline;
  activity?: LeadsActivityEntry[];
  profiles?: LeadsProfile[];
  templates?: LeadsTemplateLane[];
  sent?: LeadsSentMessage[];
  kpis?: {
    drafts?: number;
    hot?: number;
    avgFirstTouch?: string;
    avgDaysSinceTouch?: string;
    replyRate?: string;
    newLeads7d?: string | number;
    medianWait?: string;
    nextRun?: string;
  };
  onRefresh?: () => void;
  loading?: boolean;
  error?: string | null;
  debugNote?: string | null;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft) => void | Promise<void>;
  onProfileFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onProfileStatusChange?: (profile: LeadsProfile, status: string) => void | Promise<void>;
  onReRunOnboarding?: () => void;
  templateMutations?: TemplateMutations;
  onSentRefresh?: (includePending: boolean) => Promise<void>;
  appleMessages?: { inbound: boolean; outbound: boolean; blocked?: boolean; note?: string };
  onToggleDirection?: (dir: "inbound" | "outbound", value: boolean) => void | Promise<void>;
}

export function LeadsBoard(props: LeadsBoardProps) {
  const [tab, setTab] = useState<LeadsTab>("action");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [activeProfile, setActiveProfile] = useState<LeadsProfile | null>(null);
  const [statusOverrides, setStatusOverrides] = useState<Record<string, string>>({});
  const [profileStatusError, setProfileStatusError] = useState<string | null>(null);

  const handleStatusChange = async (profile: LeadsProfile, value: string) => {
    setProfileStatusError(null);
    if (props.onProfileStatusChange) {
      try {
        await props.onProfileStatusChange(profile, value);
      } catch (err) {
        setProfileStatusError(err instanceof Error ? err.message : "Could not update lead status.");
        return;
      }
    }
    setStatusOverrides(o => ({ ...o, [profile.id]: value }));
    setActiveProfile(p => (p?.id === profile.id ? { ...p, status: value } : p));
  };
  const activeProfileStatus = activeProfile
    ? (statusOverrides[activeProfile.id] || activeProfile.status)
    : null;

  const sources = props.sources ?? DEFAULT_SOURCES;
  const drafts = props.drafts ?? DEFAULT_DRAFTS;
  const channels = props.channels ?? DEFAULT_CHANNELS;
  const schedules = props.schedules ?? DEFAULT_SCHEDULES;
  const available = props.available ?? DEFAULT_AVAILABLE;
  const pipeline = props.pipeline ?? DEFAULT_PIPELINE;
  const activity = props.activity ?? DEFAULT_ACTIVITY;
  const profiles = props.profiles ?? DEFAULT_PROFILES;
  const profilesWithFavoriteOverrides = profiles;

  // Open the profile drawer for a hot-lead queue entry. Prefer a real profile
  // match (carries full thread context); otherwise synthesize a minimal one
  // from the entry's sourceId/threadId so the drawer can still load the thread.
  const openHotLead = (entry: LeadsHotEntry) => {
    const match = profiles.find((p) => p.name === entry.name);
    if (match) {
      setActiveProfile(match);
      return;
    }
    setActiveProfile({
      id: entry.id,
      name: entry.name,
      heat: 80,
      group: "active",
      verified: false,
      status: "",
      source: entry.sourceId || "—",
      email: "",
      phone: "",
      contact: "",
      threads: 1,
      age: entry.age,
      tags: [],
      sub: entry.signal,
      lastMsg: entry.signal,
      lastTouch: entry.age,
      sourceId: entry.sourceId,
      threadId: entry.threadId,
    });
  };
  const templates = props.templates ?? DEFAULT_TEMPLATES;
  const sent = props.sent ?? DEFAULT_SENT;
  const blocked = channels.filter(c => c.status === "blocked");

  const k = {
    drafts: props.kpis?.drafts ?? drafts.length,
    hot: props.kpis?.hot ?? pipeline.hot.length,
    avgFirstTouch: props.kpis?.avgFirstTouch ?? "—",
    avgDaysSinceTouch: props.kpis?.avgDaysSinceTouch ?? "—",
    replyRate: props.kpis?.replyRate ?? "—",
    newLeads7d: props.kpis?.newLeads7d ?? "—",
    medianWait: props.kpis?.medianWait ?? "—",
    nextRun: props.kpis?.nextRun ?? "—",
  };

  return (
    <main className="admin-board">
      <header className="ab-top">
        <div className="ab-crumb">
          <span className="crumb">Lead desk</span>
          <span className="sep">·</span>
          <span className="ab-live"><span className="ab-live-dot"></span>Local gateway online</span>
          {props.loading && <span className="sep">·</span>}
          {props.loading && <span className="ab-live mono">loading…</span>}
          {props.error && <span className="sep">·</span>}
          {props.error && <span className="ab-live mono" style={{ color: "var(--accent-warn, #e0a44c)" }}>{props.error}</span>}
          {!props.error && props.debugNote && <span className="sep">·</span>}
          {!props.error && props.debugNote && <span className="ab-live mono">{props.debugNote}</span>}
        </div>
        <div className="ab-top-actions">
          <SourcesHealthPill channels={channels} schedules={schedules} available={available} />
          <button className="ab-btn ghost" type="button" onClick={props.onRefresh}><Refresh /><span>Refresh</span></button>
          <button className="ab-btn ghost" type="button" onClick={props.onReRunOnboarding}><Sparkles /><span>Re-run onboarding</span></button>
          <Link className="ab-btn primary" to="/config#connectors"><Plus /><span>New lead</span></Link>
        </div>
      </header>

      <div className="ab-scroll">
        <div className="lb-tabs-wrap">
          <LeadsTabs tab={tab} onChange={setTab} />
          <ActivityTicker activity={activity} />
          <div className="lb-source-filters">
            {sources.map(s => (
              <button
                key={s.id}
                type="button"
                className={"lb-source-chip" + (sourceFilter === s.id ? " active" : "")}
                onClick={() => setSourceFilter(s.id)}
              >
                <span>{s.label}</span>
                <span className="lb-source-chip-count mono">{s.count}</span>
              </button>
            ))}
          </div>
        </div>

        {profileStatusError && (
          <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{profileStatusError}</div>
        )}

        {tab === "action" && (
          <>
            <section className="ab-kpis">
              <LbKpi label="Drafts to approve" value={k.drafts} breakdown="approval-gated" delta={k.drafts > 0 ? "review queue" : "inbox zero"} deltaTone={k.drafts > 0 ? "warn" : ""} />
              <LbKpi label="Hot leads" value={k.hot} breakdown="replies + repeats" delta={pipeline.hot[0] ? `next: ${pipeline.hot[0].name.split(" ")[0]} ${pipeline.hot[0].name.split(" ")[1]?.[0] ?? ""}.` : "none queued"} deltaTone="" />
              <LbKpi label="Avg first touch" value={k.avgFirstTouch} breakdown="lead lands → reply" delta="" deltaTone="" />
              <LbKpi label="Avg days since touch" value={k.avgDaysSinceTouch} breakdown="across all leads" delta="" deltaTone="warn" />
              <LbKpi label="Reply rate" value={k.replyRate} breakdown="last 7 days" delta="" deltaTone="" />
              <LbKpi label="New leads (7d)" value={k.newLeads7d} breakdown="across all sources" delta="" deltaTone="" />
              <LbKpi label="Median wait" value={k.medianWait} breakdown="reply latency" delta="" deltaTone="" />
              <LbKpi label="Next agent run" value={k.nextRun} breakdown="Hot Leads Watcher" delta="" deltaTone="" />
            </section>

            <AppleMessagesToggleBar
              appleMessages={props.appleMessages}
              onToggle={props.onToggleDirection}
            />
            {props.appleMessages
              ? (props.appleMessages.blocked ? (
                  <LbSourceAlert
                    blocked={[{
                      id: "imessage",
                      name: "Apple Messages",
                      kind: "imessage",
                      status: "blocked",
                      uncontacted: 0,
                      contacted: 0,
                      records: 0,
                      note: props.appleMessages.note
                        || "Open System Settings → Privacy & Security → Full Disk Access, turn ON Elevate, then quit and reopen Elevate.",
                    }]}
                  />
                ) : null)
              : <LbSourceAlert blocked={blocked} />}
            <ActionQueue
              drafts={drafts}
              pipeline={pipeline}
              sourceFilter={sourceFilter}
              onDraftAction={props.onDraftAction}
              onEditTemplate={() => setTab("templates")}
              onOpenHotLead={openHotLead}
            />
          </>
        )}

        {tab === "profiles" && (
          <ProfilesList
            profiles={profilesWithFavoriteOverrides}
            sourceFilter={sourceFilter}
            onOpen={setActiveProfile}
            statusOverrides={statusOverrides}
            onStatusChange={handleStatusChange}
            onFavoriteChange={props.onProfileFavoriteChange}
          />
        )}

        {tab === "templates" && (
          <TemplatesView groups={templates} mutations={props.templateMutations} />
        )}

        {tab === "sent" && (
          <SentView messages={sent} onRefresh={props.onSentRefresh} />
        )}
      </div>

      {activeProfile && (
        <ProfileDrawer
          profile={{ ...activeProfile, status: activeProfileStatus ?? activeProfile.status }}
          onClose={() => setActiveProfile(null)}
          onStatusChange={handleStatusChange}
        />
      )}
    </main>
  );
}

export default LeadsBoard;
