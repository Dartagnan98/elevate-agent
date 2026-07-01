import { useState } from "react";
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
import { ActionQueue } from "./action-queue";
import { matchesLeadsSourceFilter } from "./action-queue-helpers";
import {
  ActivityTicker,
  AppleMessagesToggleBar,
  LeadsTabs,
  LbKpi,
  LbSourceAlert,
  SourcesHealthPill,
  type LeadsTab,
} from "./lead-shell";
import { ProfileDrawer } from "./profile-drawer";
import { ProfilesList } from "./profiles-list";
import { SentView } from "./sent-view";
import { NotSentView } from "./not-sent-view";
import { TemplatesView, type TemplateMutations } from "./templates-view";

export type { TemplateMutations } from "./templates-view";

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
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
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
  // The Paid Ads tab is the Action board scoped to the paid-ad lead source.
  const paidAdsSourceId = sources.find((s) => /paid\s*ads/i.test(s.label))?.id ?? "";
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
              onDraftActionComplete={props.onDraftActionComplete}
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
        {tab === "didnt-send" && <NotSentView />}
        {tab === "paid-ads" && (
          <ActionQueue
            drafts={drafts}
            pipeline={{
              ...pipeline,
              hot: pipeline.hot.filter((l) => matchesLeadsSourceFilter(l, paidAdsSourceId)),
              followups: pipeline.followups.filter((l) => matchesLeadsSourceFilter(l, paidAdsSourceId)),
              skipped: pipeline.skipped.filter((l) => matchesLeadsSourceFilter(l, paidAdsSourceId)),
            }}
            sourceFilter={paidAdsSourceId}
            onDraftAction={props.onDraftAction}
            onDraftActionComplete={props.onDraftActionComplete}
            onEditTemplate={() => setTab("templates")}
            onOpenHotLead={openHotLead}
          />
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
