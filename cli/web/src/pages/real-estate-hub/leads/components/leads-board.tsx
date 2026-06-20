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
  type LeadsSentMessage,
  type LeadsDraftAction,
} from "../leads-data";
import { api } from "@/lib/api";
import type { ThreadContextResponse } from "@/lib/api-types";
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
import { SentView } from "./sent-view";
import { TemplatesView, type TemplateMutations } from "./templates-view";

export { matchesLeadsSourceFilter, nextDraftQueueSelection } from "./action-queue";
export type { TemplateMutations } from "./templates-view";

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
