import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Plus,
  Sparkles,
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
import { ActionQueue } from "./action-queue";
import {
  ActivityTicker,
  AppleMessagesToggleBar,
  LeadsTabs,
  LbKpi,
  LbSourceAlert,
  SourcesHealthPill,
  type LeadsTab,
} from "./lead-shell";
import { ProfilesList, StatusPill } from "./profiles-list";

export { matchesLeadsSourceFilter, nextDraftQueueSelection } from "./action-queue";

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
