import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import type { CrmColumn } from "@/lib/api-types";
import { Plus, Refresh, Sparkles } from "../../admin/icons";
import type {
  LeadsActivityEntry,
  LeadsAvailable,
  LeadsChannel,
  LeadsDraft,
  LeadsDraftAction,
  LeadsHotEntry,
  LeadsPipeline,
  LeadsProfile,
  LeadsSchedule,
  LeadsSentMessage,
  LeadsSource,
  LeadsTemplateLane,
} from "../leads-data";
import { ActionQueue } from "./action-queue";
import {
  AppleMessagesToggleBar,
  LeadsTabs,
  LbKpi,
  LbSourceAlert,
  type LeadsTab,
} from "./lead-shell";
import { NotSentView } from "./not-sent-view";
import { ProfileDrawer } from "./profile-drawer";
import { draftMatchesProfile, type CrmTemperature } from "./crm-profile-helpers";
import type { DraftSendLifecycleNotice } from "../draft-send-lifecycle";
import { ProfilesList } from "./profiles-list";
import { SentView } from "./sent-view";
import { TemplatesView, type TemplateMutations } from "./templates-view";

export type { TemplateMutations } from "./templates-view";

const EMPTY_PIPELINE: LeadsPipeline = { hot: [], followups: [], buyers: 0, skipped: [] };
const EMPTY_SOURCES: LeadsSource[] = [];
const EMPTY_CHANNELS: LeadsChannel[] = [];
const EMPTY_DRAFTS: LeadsDraft[] = [];
const EMPTY_PROFILES: LeadsProfile[] = [];
const EMPTY_TEMPLATES: LeadsTemplateLane[] = [];
const EMPTY_SENT: LeadsSentMessage[] = [];

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
  draftSendNotices?: DraftSendLifecycleNotice[];
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
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  onProfileFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onProfileTop25Change?: (profile: LeadsProfile, top25: boolean) => void | Promise<void>;
  onProfileTagsChange?: (profile: LeadsProfile, tags: string[]) => void | Promise<void>;
  onProfileStatusChange?: (profile: LeadsProfile, status: string) => void | Promise<void>;
  onReRunOnboarding?: () => void;
  templateMutations?: TemplateMutations;
  templatesState?: { loading: boolean; error: string | null };
  onSentRefresh?: (includePending: boolean) => Promise<void>;
  sentState?: { loading: boolean; error: string | null; partial: boolean; limit: number };
  appleMessages?: { inbound: boolean; outbound: boolean; blocked?: boolean; note?: string };
  onToggleDirection?: (dir: "inbound" | "outbound", value: boolean) => void | Promise<void>;
}

export function LeadsBoard(props: LeadsBoardProps) {
  const [tab, setTab] = useState<LeadsTab>("leads");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [pipelineFilter, setPipelineFilter] = useState("all");
  const [temperatureFilter, setTemperatureFilter] = useState<CrmTemperature>("all");
  const [tagFilters, setTagFilters] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeProfile, setActiveProfile] = useState<LeadsProfile | null>(null);
  const [profileStatusError, setProfileStatusError] = useState<string | null>(null);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [addLeadOpen, setAddLeadOpen] = useState(false);
  const [addLead, setAddLead] = useState({ name: "", email: "", phone: "", type: "buyer" });
  const [addLeadBusy, setAddLeadBusy] = useState(false);
  const [addLeadError, setAddLeadError] = useState<string | null>(null);
  const [addColumnOpen, setAddColumnOpen] = useState(false);
  const [addColumnLabel, setAddColumnLabel] = useState("");
  const [columnBusy, setColumnBusy] = useState(false);
  const [columnError, setColumnError] = useState<string | null>(null);
  const [customColumns, setCustomColumns] = useState<CrmColumn[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.getCrmColumns()
      .then((result) => { if (!cancelled) setCustomColumns(result.columns || []); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const handleAddLead = async () => {
    const { name, email, phone, type } = addLead;
    if (!name.trim() && !email.trim() && !phone.trim()) {
      setAddLeadError("Give the lead at least a name, email, or phone.");
      return;
    }
    setAddLeadBusy(true);
    setAddLeadError(null);
    try {
      await api.createSourceInboxLead({
        name: name.trim(),
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        type,
      });
      setAddLeadOpen(false);
      setAddLead({ name: "", email: "", phone: "", type: "buyer" });
      props.onRefresh?.();
    } catch (error) {
      setAddLeadError(error instanceof Error ? error.message : "Could not create the lead.");
    } finally {
      setAddLeadBusy(false);
    }
  };

  const handleAddColumn = async () => {
    const label = addColumnLabel.trim();
    if (!label) return;
    setColumnBusy(true);
    setColumnError(null);
    try {
      const result = await api.putCrmColumns([...customColumns, { key: "", label }]);
      setCustomColumns(result.columns);
      setAddColumnOpen(false);
      setAddColumnLabel("");
    } catch (error) {
      setColumnError(error instanceof Error ? error.message : "Could not add the column.");
    } finally {
      setColumnBusy(false);
    }
  };

  const handleRemoveColumn = async (key: string) => {
    setColumnBusy(true);
    setColumnError(null);
    try {
      const result = await api.putCrmColumns(customColumns.filter((column) => column.key !== key));
      setCustomColumns(result.columns);
    } catch (error) {
      setColumnError(error instanceof Error ? error.message : "Could not remove the column.");
    } finally {
      setColumnBusy(false);
    }
  };

  // Rendering an empty inbox must stay empty. Demo constants still support
  // isolated design fixtures, but are never a fallback for the live CRM.
  const sources = props.sources ?? EMPTY_SOURCES;
  const channels = props.channels ?? EMPTY_CHANNELS;
  const drafts = props.drafts ?? EMPTY_DRAFTS;
  const pipeline = props.pipeline ?? EMPTY_PIPELINE;
  const profiles = props.profiles ?? EMPTY_PROFILES;
  const templates = props.templates ?? EMPTY_TEMPLATES;
  const sent = props.sent ?? EMPTY_SENT;
  const draftSendNotices = props.draftSendNotices ?? [];
  const blocked = channels.filter((channel) => channel.status === "blocked");

  const pipelineOptions = useMemo(() => {
    const stages = [
      "New Lead", "Attempted Contact", "Prospect", "Client", "Pending Deal",
      "Closed", "Referred", "Realtor Contact", "Trash",
    ];
    const known = new Set(stages.map((stage) => stage.toLowerCase()));
    const extras = [...new Set(profiles.map((profile) => profile.status).filter(Boolean))]
      .filter((status) => !known.has(status.toLowerCase()))
      .sort((a, b) => a.localeCompare(b));
    return [...stages, ...extras];
  }, [profiles]);
  const tagOptions = useMemo(() => (
    [...new Set(profiles.flatMap((profile) => profile.tags).map((tag) => tag.trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b))
  ), [profiles]);
  const unmatchedDrafts = useMemo(
    () => drafts.filter((draft) => !profiles.some((profile) => draftMatchesProfile(draft, profile))),
    [drafts, profiles],
  );

  const activeProfileFromLive = activeProfile
    ? profiles.find((profile) => profile.id === activeProfile.id) ?? activeProfile
    : null;
  const activeDraft = activeProfileFromLive
    ? drafts.find((draft) => draftMatchesProfile(draft, activeProfileFromLive))
    : undefined;

  const updateStatus = async (profile: LeadsProfile, value: string) => {
    setProfileStatusError(null);
    if (props.onProfileStatusChange) {
      try {
        await props.onProfileStatusChange(profile, value);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not update lead status.";
        setProfileStatusError(message);
        throw new Error(message, { cause: error });
      }
    }
  };
  const handleListStatusChange = (profile: LeadsProfile, value: string) => {
    void updateStatus(profile, value).catch(() => undefined);
  };

  const handleFavoriteChange = async (profile: LeadsProfile, favorite: boolean) => {
    if (!props.onProfileFavoriteChange) return;
    await props.onProfileFavoriteChange(profile, favorite);
    setActiveProfile((current) => current?.id === profile.id ? { ...current, favorite } : current);
  };

  const profileForHotLead = (entry: LeadsHotEntry) => profiles.find((profile) => (
      entry.sourceId
      && entry.threadId
      && profile.sourceId === entry.sourceId
      && profile.threadId === entry.threadId
  ));
  const openHotLead = (entry: LeadsHotEntry) => {
    const match = profileForHotLead(entry);
    if (match) setActiveProfile(match);
  };

  const toggleTag = (tag: string) => {
    setTagFilters((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  };
  const resetFilters = () => {
    setSourceFilter("all");
    setPipelineFilter("all");
    setTemperatureFilter("all");
    setTagFilters([]);
    setSearchQuery("");
  };
  const activeFilterCount = Number(sourceFilter !== "all")
    + Number(pipelineFilter !== "all")
    + Number(temperatureFilter !== "all")
    + tagFilters.length
    + Number(Boolean(searchQuery.trim()));

  const kpis = {
    newLeads7d: props.kpis?.newLeads7d ?? "—",
    replyRate: props.kpis?.replyRate ?? "—",
  };
  const queueCount = unmatchedDrafts.length + pipeline.hot.length + pipeline.followups.length + pipeline.skipped.length;
  const sourceInboxLoaded = props.sources !== undefined || props.drafts !== undefined || props.profiles !== undefined;
  const sourceInboxState = props.error
    ? { label: "Source refresh failed", tone: "error" }
    : props.loading
      ? { label: "Refreshing source inbox", tone: "warn" }
      : sourceInboxLoaded
        ? { label: "Source inbox ready", tone: "done" }
        : { label: "Source inbox not loaded", tone: "warn" };

  return (
    <main
      className="admin-board crm-board"
      data-custom-cols={customColumns.length > 0 ? customColumns.length : undefined}
      style={customColumns.length > 0
        ? ({ "--crm-custom-cols": `repeat(${customColumns.length}, minmax(100px, 0.7fr))` } as React.CSSProperties)
        : undefined}
    >
      <header className="ab-top crm-masthead">
        <div className="crm-title-block">
          <span className="crm-eyebrow">Elevation CRM</span>
          <div className="crm-title-row">
            <h1>Leads</h1>
            <span className="crm-live-state" style={{ color: `var(--status-${sourceInboxState.tone})` }}>
              <span className={`dot ${sourceInboxState.tone}`} aria-hidden="true" />
              {sourceInboxState.label}
            </span>
          </div>
          {(props.loading || props.error || props.debugNote) && (
            <div className="crm-data-note mono" role={props.error ? "alert" : "status"}>
              {props.error || (props.loading ? "Refreshing live lead data…" : props.debugNote)}
            </div>
          )}
        </div>
        <div className="ab-top-actions">
          <button className="ab-btn ghost" type="button" onClick={props.onRefresh} disabled={!props.onRefresh || props.loading}>
            <Refresh /><span>{props.loading ? "Refreshing…" : "Refresh"}</span>
          </button>
          <button className="ab-btn ghost" type="button" onClick={props.onReRunOnboarding} disabled={!props.onReRunOnboarding}>
            <Sparkles /><span>Source setup</span>
          </button>
          <Link className="ab-btn ghost" to="/config#connectors"><span>Connect source</span></Link>
          <div className="crm-addwrap">
            <button
              className="ab-btn primary"
              type="button"
              aria-expanded={addMenuOpen}
              onClick={() => setAddMenuOpen((open) => !open)}
            >
              <Plus /><span>Add New</span>
            </button>
            {addMenuOpen && (
              <div className="crm-addmenu" role="menu">
                <button type="button" role="menuitem" onClick={() => { setAddMenuOpen(false); setAddLeadOpen(true); }}>
                  New lead
                </button>
                <button type="button" role="menuitem" onClick={() => { setAddMenuOpen(false); setAddColumnOpen(true); }}>
                  New column
                </button>
                {customColumns.length > 0 && <div className="crm-addmenu-sep" aria-hidden="true" />}
                {customColumns.map((column) => (
                  <button
                    key={column.key}
                    type="button"
                    role="menuitem"
                    className="crm-addmenu-remove"
                    disabled={columnBusy}
                    onClick={() => void handleRemoveColumn(column.key)}
                  >
                    Remove column “{column.label}”
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>

      {addLeadOpen && (
        <div
          className="crm-tagpicker-backdrop"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setAddLeadOpen(false); }}
        >
          <div className="crm-tagpicker crm-add-lead-modal" role="dialog" aria-modal="true" aria-label="Add a new lead">
            <div className="crm-tagpicker-head">
              <h3>New lead</h3>
              <button type="button" aria-label="Close new lead form" onClick={() => setAddLeadOpen(false)}>×</button>
            </div>
            {addLeadError && <div className="crm-contact-error" role="alert">{addLeadError}</div>}
            <label className="crm-criteria-field">
              <span>Name</span>
              <input type="text" value={addLead.name} placeholder="e.g. Shannon Hogan" onChange={(event) => setAddLead((c) => ({ ...c, name: event.target.value }))} />
            </label>
            <label className="crm-criteria-field">
              <span>Email</span>
              <input type="email" value={addLead.email} placeholder="name@example.com" onChange={(event) => setAddLead((c) => ({ ...c, email: event.target.value }))} />
            </label>
            <label className="crm-criteria-field">
              <span>Phone</span>
              <input type="tel" value={addLead.phone} placeholder="+1 250-555-0100" onChange={(event) => setAddLead((c) => ({ ...c, phone: event.target.value }))} />
            </label>
            <label className="crm-criteria-field">
              <span>Lead type</span>
              <select value={addLead.type} onChange={(event) => setAddLead((c) => ({ ...c, type: event.target.value }))}>
                <option value="buyer">Buyer</option>
                <option value="listing">Seller</option>
                <option value="other">Other</option>
                <option value="unclassified">Unclassified</option>
              </select>
            </label>
            <div className="crm-tagpicker-foot">
              <button type="button" disabled={addLeadBusy} onClick={() => void handleAddLead()}>
                {addLeadBusy ? "Adding…" : "Add lead"}
              </button>
            </div>
          </div>
        </div>
      )}

      {addColumnOpen && (
        <div
          className="crm-tagpicker-backdrop"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setAddColumnOpen(false); }}
        >
          <div className="crm-tagpicker crm-add-lead-modal" role="dialog" aria-modal="true" aria-label="Add a custom column">
            <div className="crm-tagpicker-head">
              <h3>New column</h3>
              <button type="button" aria-label="Close new column form" onClick={() => setAddColumnOpen(false)}>×</button>
            </div>
            <p className="crm-tagpicker-sub">
              Adds a custom information column to the leads list. Fill each lead's value from their card under Edit details.
            </p>
            {columnError && <div className="crm-contact-error" role="alert">{columnError}</div>}
            <label className="crm-criteria-field">
              <span>Column name</span>
              <input
                type="text"
                value={addColumnLabel}
                placeholder="e.g. Lender, Anniversary, Referral fee"
                onChange={(event) => setAddColumnLabel(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") void handleAddColumn(); }}
              />
            </label>
            <div className="crm-tagpicker-foot">
              <button type="button" disabled={columnBusy || !addColumnLabel.trim()} onClick={() => void handleAddColumn()}>
                {columnBusy ? "Adding…" : "Add column"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="ab-scroll crm-scroll">
        <div className="crm-viewbar">
          <LeadsTabs tab={tab} onChange={setTab} />
          <span className="crm-record-count mono">{profiles.length.toLocaleString()} conversation {profiles.length === 1 ? "profile" : "profiles"} loaded</span>
        </div>

        {tab === "leads" && (
          <div className="crm-coverage-note" role="note">
            Full directory: every contact on record is listed — conversation leads first, plus CRM-only and manually added contacts that have no thread yet.
          </div>
        )}

        {profileStatusError && <div className="lb-replies-empty lb-crm-error" role="alert">{profileStatusError}</div>}

        {draftSendNotices.length > 0 && (
          <section aria-label="Approved draft send status" aria-live="polite">
            {draftSendNotices.map((notice) => {
              const needsAttention = notice.phase === "failed" || notice.phase === "timeout" || notice.phase === "unknown";
              return (
                <div
                  key={notice.draftId}
                  className={`lb-replies-empty${needsAttention ? " lb-crm-error" : ""}`}
                  role={needsAttention ? "alert" : "status"}
                >
                  <strong>{notice.draftName}</strong> · {notice.message}
                </div>
              );
            })}
          </section>
        )}

        {tab === "leads" && (
          <div className="crm-tab-panel" role="tabpanel" id="crm-panel-leads" aria-labelledby="crm-tab-leads">
            <section className="crm-kpis" aria-label="Lead overview">
              <LbKpi label="Profiles loaded" value={profiles.length} breakdown="from open conversations" delta="" deltaTone="" />
              <LbKpi label="Drafts loaded" value={drafts.length} breakdown="nothing sends without approval" delta={drafts.length ? "review needed" : "inbox zero"} deltaTone={drafts.length ? "warn" : ""} />
              <LbKpi label="Hot queue shown" value={pipeline.hot.length} breakdown="up to 8 prioritized conversations" delta="" deltaTone="" />
              <LbKpi label="Touched (7d)" value={kpis.newLeads7d} breakdown="status or conversation activity" delta="" deltaTone="" />
              <LbKpi label="Reply rate" value={kpis.replyRate} breakdown="last 7 days" delta="" deltaTone="" />
            </section>

            <section className="crm-filterbar" aria-label="Filter leads">
              <label className="crm-search">
                <span className="sr-only">Search leads</span>
                <span aria-hidden="true">⌕</span>
                <input
                  type="search"
                  value={searchQuery}
                  placeholder="Search name, email, or phone"
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              </label>
              <label className="crm-quick-filter">
                <span>Source</span>
                <select value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); }}>
                  {(sources.some((source) => source.id === "all") ? sources : [{ id: "all", label: "All sources", count: profiles.length, isAll: true }, ...sources]).map((source) => (
                    <option key={source.id} value={source.id}>{source.label}</option>
                  ))}
                </select>
              </label>
              <label className="crm-quick-filter">
                <span>Pipeline</span>
                <select value={pipelineFilter} onChange={(event) => setPipelineFilter(event.target.value)}>
                  <option value="all">All stages</option>
                  {pipelineOptions.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <label className="crm-quick-filter">
                <span>Temp</span>
                <select value={temperatureFilter} onChange={(event) => setTemperatureFilter(event.target.value as CrmTemperature)}>
                  <option value="all">All segments</option>
                  <option value="hot">Hot · 0–30d</option>
                  <option value="warm">Warm · 30–90d</option>
                  <option value="lukewarm">Lukewarm · 90–180d</option>
                  <option value="cool">Cool · 180–365d</option>
                  <option value="soi">SOI · past clients</option>
                  <option value="nurture">Nurture · 365d+</option>
                </select>
              </label>
              <details className="crm-tags-filter">
                <summary>Tags{tagFilters.length ? ` · ${tagFilters.length}` : ""}</summary>
                <div className="crm-tags-popover">
                  <div className="crm-tags-popover-head">
                    <strong>Filter by tags</strong>
                    <button type="button" onClick={() => setTagFilters([])} disabled={tagFilters.length === 0}>Clear</button>
                  </div>
                  {tagOptions.length === 0 ? (
                    <p>No tags on loaded conversation profiles.</p>
                  ) : (
                    <fieldset>
                      <legend className="sr-only">Contact tags</legend>
                      {tagOptions.map((tag) => (
                        <label key={tag}>
                          <input type="checkbox" checked={tagFilters.includes(tag)} onChange={() => toggleTag(tag)} />
                          <span>{tag}</span>
                        </label>
                      ))}
                    </fieldset>
                  )}
                </div>
              </details>
              {activeFilterCount > 0 && <button type="button" className="crm-clear-filters" onClick={resetFilters}>Clear {activeFilterCount}</button>}
            </section>

            <AppleMessagesToggleBar appleMessages={props.appleMessages} onToggle={props.onToggleDirection} />
            {props.appleMessages?.blocked && (
              <LbSourceAlert blocked={[{
                id: "imessage",
                name: "Apple Messages",
                kind: "imessage",
                status: "blocked",
                uncontacted: 0,
                contacted: 0,
                records: 0,
                note: props.appleMessages.note || "Open System Settings → Privacy & Security → Full Disk Access, turn ON Elevate, then quit and reopen Elevate.",
              }]} />
            )}
            {!props.appleMessages && blocked.length > 0 && <LbSourceAlert blocked={blocked} />}

            <ProfilesList
              profiles={profiles}
              drafts={drafts}
              sourceFilter={sourceFilter}
              pipelineFilter={pipelineFilter}
              temperatureFilter={temperatureFilter}
              tagFilters={tagFilters}
              searchQuery={searchQuery}
              customColumns={customColumns}
              loading={Boolean(props.loading)}
              onOpen={setActiveProfile}
              onStatusChange={handleListStatusChange}
              onFavoriteChange={props.onProfileFavoriteChange ? handleFavoriteChange : undefined}
              onDraftAction={props.onDraftAction}
              onDraftActionComplete={props.onDraftActionComplete}
              onEditTemplate={() => setTab("templates")}
            />

            {queueCount > 0 && (
              <details className="crm-work-queue" open={unmatchedDrafts.length > 0}>
                <summary>
                  <span>Additional follow-up work</span>
                  <span className="mono">{queueCount}</span>
                </summary>
                <ActionQueue
                  drafts={unmatchedDrafts}
                  pipeline={pipeline}
                  sourceFilter={sourceFilter}
                  onDraftAction={props.onDraftAction}
                  onDraftActionComplete={props.onDraftActionComplete}
                  onEditTemplate={() => setTab("templates")}
                  onOpenHotLead={openHotLead}
                  canOpenHotLead={(entry) => Boolean(profileForHotLead(entry))}
                />
              </details>
            )}
          </div>
        )}

        {tab === "templates" && (
          <div className="crm-tab-panel" role="tabpanel" id="crm-panel-templates" aria-labelledby="crm-tab-templates">
            <TemplatesView
              groups={templates}
              mutations={props.templateMutations}
              loading={props.templatesState?.loading}
              loadError={props.templatesState?.error}
            />
          </div>
        )}
        {tab === "sent" && (
          <div className="crm-tab-panel" role="tabpanel" id="crm-panel-sent" aria-labelledby="crm-tab-sent">
            <SentView
              messages={sent}
              onRefresh={props.onSentRefresh}
              loading={props.sentState?.loading}
              error={props.sentState?.error}
              partial={props.sentState?.partial}
              limit={props.sentState?.limit}
            />
          </div>
        )}
        {tab === "didnt-send" && (
          <div className="crm-tab-panel" role="tabpanel" id="crm-panel-didnt-send" aria-labelledby="crm-tab-didnt-send">
            <NotSentView />
          </div>
        )}
      </div>

      {activeProfileFromLive && (
        <ProfileDrawer
          key={`${activeProfileFromLive.id}:${activeProfileFromLive.sourceId || ""}:${activeProfileFromLive.threadId || ""}`}
          profile={activeProfileFromLive}
          draft={activeDraft}
          onClose={() => setActiveProfile(null)}
          onStatusChange={updateStatus}
          onFavoriteChange={props.onProfileFavoriteChange ? handleFavoriteChange : undefined}
          onTop25Change={props.onProfileTop25Change}
          onTagsChange={props.onProfileTagsChange}
          customColumns={customColumns}
          onContactSaved={props.onRefresh}
          onDraftAction={props.onDraftAction}
          onDraftActionComplete={props.onDraftActionComplete}
          draftSendNotices={draftSendNotices}
          onEditTemplate={() => { setActiveProfile(null); setTab("templates"); }}
        />
      )}
    </main>
  );
}

export default LeadsBoard;
