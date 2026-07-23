import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { CrmColumn } from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "../leads-data";
import { BulkComposeModal } from "./bulk-compose-modal";
import {
  crmTemperatureForProfile,
  draftMatchesProfile,
  matchesCrmProfile,
  type CrmTemperature,
} from "./crm-profile-helpers";
import { DraftRow } from "./draft-row";
import { StatusPill } from "./profile-status";

export { StatusPill } from "./profile-status";

const PROFILE_PAGE = 50;

const BUILT_IN_STAGES = [
  "New Lead", "Attempted Contact", "Prospect", "Client", "Pending Deal",
  "Closed", "Referred", "Realtor Contact", "Trash",
];

function ProfileRow({
  profile,
  draft,
  draftExpanded,
  onToggleDraft,
  onOpen,
  onStatusChange,
  onFavoriteChange,
  favoriteBusy,
  selected,
  onToggleSelect,
  customColumns = [],
}: {
  profile: LeadsProfile;
  draft?: LeadsDraft;
  draftExpanded: boolean;
  onToggleDraft: () => void;
  onOpen?: (p: LeadsProfile) => void;
  onStatusChange?: (profile: LeadsProfile, value: string) => void;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  favoriteBusy?: boolean;
  selected?: boolean;
  onToggleSelect?: (profile: LeadsProfile) => void;
  customColumns?: CrmColumn[];
}) {
  const heatTone = crmTemperatureForProfile(profile);
  const initials = profile.name
    .split(/\s+/)
    .map((word) => word[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const isFavorite = Boolean(profile.favorite);

  return (
    <div
      className={"lb-profile-row" + (isFavorite ? " favorite" : "") + (selected ? " selected" : "")}
      onClick={() => onOpen?.(profile)}
    >
      <div className="lb-profile-select-cell" onClick={(event) => event.stopPropagation()}>
        <input
          type="checkbox"
          className="lb-profile-select"
          checked={Boolean(selected)}
          aria-label={selected ? `Deselect ${profile.name}` : `Select ${profile.name}`}
          onChange={() => onToggleSelect?.(profile)}
        />
      </div>
      <div className="lb-profile-favorite-cell" onClick={(event) => event.stopPropagation()}>
        <button
          type="button"
          className={"lb-profile-star" + (isFavorite ? " active" : "")}
          aria-label={isFavorite ? `Remove ${profile.name} from favorites` : `Add ${profile.name} to favorites`}
          aria-pressed={isFavorite}
          title={!onFavoriteChange ? "Favorite updates are unavailable for this contact." : isFavorite ? "Remove favorite" : "Add favorite"}
          disabled={favoriteBusy || !onFavoriteChange}
          onClick={() => void onFavoriteChange?.(profile, !isFavorite)}
        >
          {isFavorite ? "★" : "☆"}
        </button>
      </div>
      <div className="lb-profile-avatar" data-tone={heatTone} aria-hidden="true">{initials}</div>
      <button type="button" className="lb-profile-open" onClick={(event) => { event.stopPropagation(); onOpen?.(profile); }}>
        <span className="lb-profile-name-cell">
          <span className="lb-profile-name">{profile.name}</span>
          {profile.verified && <span className="lb-profile-verified-dot" title="Verified" aria-label="Verified">✓</span>}
        </span>
        <span className="lb-profile-contact-preview">{profile.email || profile.phone || "No contact details"}</span>
      </button>
      <div className="lb-profile-email-cell">
        <span className="lb-profile-email mono">{profile.email || "—"}</span>
      </div>
      <div className="lb-profile-phone-cell">
        <span className="lb-profile-phone mono">{profile.phone || "—"}</span>
      </div>
      <div className="lb-profile-status-cell" onClick={(event) => event.stopPropagation()}>
        <StatusPill
          status={profile.status}
          onChange={(value) => onStatusChange?.(profile, value)}
        />
      </div>
      <div className={"lb-profile-heat-cell " + heatTone}>
        <span className="lb-profile-heat-label">{heatTone}</span>
        <span className="lb-profile-heat-num mono">{profile.heat}</span>
      </div>
      <div className="lb-profile-source-cell">
        <div className="lb-profile-source-name">{profile.source}</div>
        <div className="lb-profile-source-sub mono">{profile.contact}</div>
      </div>
      <div className="lb-profile-next-cell" onClick={(event) => event.stopPropagation()}>
        {draft ? (
          <button
            type="button"
            className={"lb-profile-draft-chip" + (draftExpanded ? " active" : "")}
            aria-expanded={draftExpanded}
            onClick={onToggleDraft}
          >
            <span aria-hidden="true">✦</span>
            <span>Draft ready</span>
          </button>
        ) : (
          <span className="lb-profile-preview">{profile.lastMsg || "No next action recorded"}</span>
        )}
      </div>
      {customColumns.map((column) => {
        const value = profile.customFields?.[column.key] || "";
        return (
          <div key={column.key} className={"crm-custom-col-cell" + (value ? "" : " empty")}>
            {value || "—"}
          </div>
        );
      })}
      <div className="lb-profile-touch-cell mono">{profile.lastTouch || profile.age}</div>
      <button
        type="button"
        className="lb-profile-actions"
        aria-label={`Open ${profile.name}`}
        onClick={(event) => { event.stopPropagation(); onOpen?.(profile); }}
      >
        <span className="lb-profile-chev" aria-hidden="true">›</span>
      </button>
    </div>
  );
}

export function ProfilesList({
  profiles: profilesProp,
  drafts = [],
  sourceFilter,
  pipelineFilter = "all",
  temperatureFilter = "all",
  tagFilters = [],
  listFilter = "all",
  searchQuery = "",
  customColumns = [],
  pipelineOptions,
  loading = false,
  onOpen,
  onStatusChange,
  onFavoriteChange,
  onDraftAction,
  onDraftActionComplete,
  onEditTemplate,
  onBulkActionComplete,
}: {
  profiles: LeadsProfile[];
  drafts?: LeadsDraft[];
  sourceFilter: string;
  pipelineFilter?: string;
  temperatureFilter?: CrmTemperature;
  tagFilters?: string[];
  /** Configured list key, or "all" (migration 0038 named lead lists). */
  listFilter?: string;
  searchQuery?: string;
  customColumns?: CrmColumn[];
  /** Stage choices for the bulk Change Pipeline select (built-ins + custom). */
  pipelineOptions?: string[];
  loading?: boolean;
  onOpen: (p: LeadsProfile) => void;
  onStatusChange: (profile: LeadsProfile, value: string) => void;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  onEditTemplate?: () => void;
  /** Called after a bulk compose/assign lands so the parent can refresh. */
  onBulkActionComplete?: () => void;
}) {
  const [audienceFilter, setAudienceFilter] = useState<"all" | "verified" | "potential" | "favorites">("all");
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState<Record<string, boolean>>({});
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [expandedDraftId, setExpandedDraftId] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState<Record<string, boolean>>({});
  const [draftError, setDraftError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStage, setBulkStage] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const [composeChannel, setComposeChannel] = useState<"sms" | "email" | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignName, setAssignName] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  useEffect(() => {
    if (!assignOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !assignBusy) setAssignOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [assignOpen, assignBusy]);

  const profiles = profilesProp;

  const draftsByProfileId = useMemo(() => {
    const byProfileId = new Map<string, LeadsDraft>();
    for (const profile of profiles) {
      const draft = drafts.find((candidate) => draftMatchesProfile(candidate, profile));
      if (draft) byProfileId.set(profile.id, draft);
    }
    return byProfileId;
  }, [drafts, profiles]);

  const filtered = useMemo(() => {
    let list = profiles.filter((profile) => matchesCrmProfile(profile, {
      sourceFilter,
      pipelineFilter,
      temperatureFilter,
      tagFilters,
      listFilter,
      searchQuery,
    }));
    if (audienceFilter === "verified") list = list.filter((profile) => profile.verified);
    if (audienceFilter === "potential") list = list.filter((profile) => !profile.verified);
    if (audienceFilter === "favorites") list = list.filter((profile) => Boolean(profile.favorite));
    return [...list].sort((a, b) => {
      const favoriteDelta = Number(Boolean(b.favorite)) - Number(Boolean(a.favorite));
      return favoriteDelta || b.heat - a.heat || a.name.localeCompare(b.name);
    });
  }, [profiles, sourceFilter, pipelineFilter, temperatureFilter, tagFilters, listFilter, searchQuery, audienceFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PROFILE_PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visibleProfiles = showAll ? filtered : filtered.slice(safePage * PROFILE_PAGE, safePage * PROFILE_PAGE + PROFILE_PAGE);
  const rangeStart = filtered.length === 0 ? 0 : safePage * PROFILE_PAGE + 1;
  const rangeEnd = Math.min(filtered.length, safePage * PROFILE_PAGE + PROFILE_PAGE);

  const verifiedCount = profiles.filter((profile) => profile.verified).length;
  const potentialCount = profiles.filter((profile) => !profile.verified).length;
  const favoriteCount = profiles.filter((profile) => Boolean(profile.favorite)).length;

  const handleFavoriteChange = async (profile: LeadsProfile, favorite: boolean) => {
    if (!onFavoriteChange) return;
    setFavoriteError(null);
    setFavoriteBusy((state) => ({ ...state, [profile.id]: true }));
    try {
      await onFavoriteChange(profile, favorite);
    } catch (error) {
      setFavoriteError(error instanceof Error ? error.message : "Could not update favorite.");
    } finally {
      setFavoriteBusy((state) => ({ ...state, [profile.id]: false }));
    }
  };

  const handleDraftAction = async (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => {
    if (!onDraftAction) return;
    setDraftError(null);
    setDraftBusy((state) => ({ ...state, [draft.id]: true }));
    try {
      await onDraftAction(action, draft, scheduledAt);
      await onDraftActionComplete?.(action);
      if (action !== "edit") setExpandedDraftId(null);
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : `Could not ${action} draft.`);
    } finally {
      setDraftBusy((state) => ({ ...state, [draft.id]: false }));
    }
  };

  const setAudience = (value: typeof audienceFilter) => {
    setAudienceFilter((current) => current === value && value !== "all" ? "all" : value);
    setPage(0);
    setShowAll(false);
  };

  const toggleSelect = (profile: LeadsProfile) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(profile.id)) next.delete(profile.id); else next.add(profile.id);
      return next;
    });
  };
  const selectVisible = () => setSelectedIds(new Set(visibleProfiles.map((profile) => profile.id)));
  const clearSelection = () => { setSelectedIds(new Set()); setBulkStage(""); setBulkNotice(null); };
  const selectedProfiles = filtered.filter((profile) => selectedIds.has(profile.id));

  const applyBulkStage = async () => {
    if (!bulkStage || selectedProfiles.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    setBulkNotice(null);
    let applied = 0;
    let failed = 0;
    for (const profile of selectedProfiles) {
      try {
        // Same per-row path as the pill dropdown; sequential so one failure
        // doesn't hide behind a wall of parallel errors.
        await Promise.resolve(onStatusChange(profile, bulkStage));
        applied += 1;
      } catch {
        failed += 1;
      }
    }
    setBulkBusy(false);
    setBulkNotice(
      failed === 0
        ? `Pipeline set to “${bulkStage}” on ${applied} lead${applied === 1 ? "" : "s"}.`
        : `Set ${applied}, failed ${failed} — check the board error above.`,
    );
  };

  const finishBulkAction = (notice: string) => {
    setSelectedIds(new Set());
    setBulkStage("");
    setBulkNotice(notice);
    onBulkActionComplete?.();
  };

  const handleComposeDone = (summary: string) => {
    setComposeChannel(null);
    finishBulkAction(summary);
  };

  const runAssign = async () => {
    if (assignBusy) return;
    const assignee = assignName.trim();
    const withContact = selectedProfiles.filter((profile) => (profile.contactIds?.[0] || "").trim());
    const skippedNoContact = selectedProfiles.length - withContact.length;
    if (withContact.length === 0) {
      setAssignError("None of the selected leads have a linked contact record.");
      return;
    }
    setAssignBusy(true);
    setAssignError(null);
    let done = 0;
    const failures: string[] = [];
    for (const profile of withContact) {
      try {
        // Sequential on purpose — one failure surfaces by name instead of
        // hiding behind a burst of parallel errors.
        await api.assignSourceInboxContact(profile.contactIds![0], assignee || null);
        done += 1;
      } catch (error) {
        failures.push(`${profile.name}: ${error instanceof Error ? error.message : "assign failed"}`);
      }
    }
    setAssignBusy(false);
    if (failures.length > 0) {
      setAssignError(`Assigned ${done} of ${withContact.length}. Failed — ${failures.join("; ")}`);
      return;
    }
    setAssignOpen(false);
    setAssignName("");
    const skippedNote = skippedNoContact > 0
      ? ` ${skippedNoContact} skipped (no linked contact).`
      : "";
    finishBulkAction(
      assignee
        ? `Assigned ${done} lead${done === 1 ? "" : "s"} to ${assignee}.${skippedNote}`
        : `Cleared the assigned agent on ${done} lead${done === 1 ? "" : "s"}.${skippedNote}`,
    );
  };

  return (
    <section className="ab-card lb-profiles" aria-labelledby="leads-list-title">
      <header className="lb-profiles-head">
        <div className="lb-profiles-title-block">
          <h2 className="lb-profiles-title" id="leads-list-title">Conversation leads</h2>
          <p className="lb-profiles-desc">Open a profile for its selected conversation, notes, tasks, and source CRM details.</p>
        </div>
        <div className="lb-profiles-badges" aria-label="Lead subsets">
          {[
            { id: "all" as const, label: "all", count: profiles.length, tone: "" },
            { id: "favorites" as const, label: "favorites", count: favoriteCount, tone: " favorite" },
            { id: "verified" as const, label: "verified", count: verifiedCount, tone: " verified" },
            { id: "potential" as const, label: "needs review", count: potentialCount, tone: " potential" },
          ].map((item) => (
            <button
              key={item.id}
              type="button"
              className={`lb-pbadge${item.tone}${audienceFilter === item.id ? " active" : ""}`}
              aria-pressed={audienceFilter === item.id}
              onClick={() => setAudience(item.id)}
            >
              <span className="lb-pbadge-num mono">{item.count}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      </header>

      {(favoriteError || draftError) && (
        <div className="lb-replies-empty lb-crm-error" role="alert">{favoriteError || draftError}</div>
      )}

      <div className="lb-bulkbar-anchor" aria-live="polite">
        {selectedIds.size > 0 && (
          <div className="lb-bulkbar" role="toolbar" aria-label="Bulk actions">
            <span className="lb-bulkbar-count"><strong className="mono">{selectedIds.size}</strong> selected</span>
            <label className="lb-bulkbar-stage">
              <span className="sr-only">Change pipeline stage for selected leads</span>
              <select value={bulkStage} onChange={(event) => setBulkStage(event.target.value)} disabled={bulkBusy}>
                <option value="">Change pipeline…</option>
                {(pipelineOptions ?? BUILT_IN_STAGES).map((stage) => (
                  <option key={stage} value={stage}>{stage}</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="lb-bulkbar-apply"
              onClick={() => void applyBulkStage()}
              disabled={!bulkStage || bulkBusy}
            >
              {bulkBusy ? "Applying…" : "Apply"}
            </button>
            <button
              type="button"
              className="lb-bulkbar-select-page"
              title="Draft the same text to every selected lead — each lands in the approval queue."
              onClick={() => setComposeChannel("sms")}
              disabled={bulkBusy}
            >
              Mass Text
            </button>
            <button
              type="button"
              className="lb-bulkbar-select-page"
              title="Draft the same email to every selected lead — each lands in the approval queue."
              onClick={() => setComposeChannel("email")}
              disabled={bulkBusy}
            >
              Mass Email
            </button>
            <button
              type="button"
              className="lb-bulkbar-select-page"
              title="Set the assigned agent on each selected lead's contact record."
              onClick={() => { setAssignError(null); setAssignOpen(true); }}
              disabled={bulkBusy}
            >
              Assign to agent
            </button>
            <button type="button" className="lb-bulkbar-select-page" onClick={selectVisible}>Select page</button>
            <button type="button" className="lb-bulkbar-clear" onClick={clearSelection}>Clear</button>
          </div>
        )}
        {bulkNotice && <div className="lb-bulkbar-notice" role="status">{bulkNotice}</div>}
      </div>

      <div className="lb-table-scroll">
      <div className="lb-profiles-colhead" aria-hidden="true">
        <span></span>
        <span>Fav</span>
        <span></span>
        <span>Lead</span>
        <span>Email</span>
        <span>Phone</span>
        <span>Pipeline</span>
        <span>Temp</span>
        <span>Source</span>
        <span>Next / AI</span>
        {customColumns.map((column) => (
          <span key={column.key} className="crm-custom-col-head">{column.label}</span>
        ))}
        <span className="lb-profile-touch-col">Last touch</span>
        <span></span>
      </div>

      <div className="lb-profiles-list">
        {visibleProfiles.map((profile) => {
          const draft = draftsByProfileId.get(profile.id);
          const draftExpanded = Boolean(draft && expandedDraftId === draft.id);
          return (
            <div key={profile.id} className="lb-profile-group">
              <ProfileRow
                profile={profile}
                draft={draft}
                draftExpanded={draftExpanded}
                onToggleDraft={() => setExpandedDraftId((current) => current === draft?.id ? null : draft?.id ?? null)}
                onOpen={onOpen}
                onStatusChange={onStatusChange}
                onFavoriteChange={handleFavoriteChange}
                favoriteBusy={Boolean(favoriteBusy[profile.id])}
                selected={selectedIds.has(profile.id)}
                onToggleSelect={toggleSelect}
                customColumns={customColumns}
              />
              {draft && draftExpanded && (
                <div className="lb-profile-inline-draft">
                  <DraftRow
                    draft={draft}
                    selected={false}
                    expanded
                    onExpand={() => setExpandedDraftId(null)}
                    onAction={onDraftAction ? (action, nextDraft, scheduledAt) => void handleDraftAction(action, nextDraft, scheduledAt) : undefined}
                    busy={Boolean(draftBusy[draft.id])}
                    onEditTemplate={onEditTemplate}
                    hideSelection
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
      </div>

      {loading && profiles.length === 0 && (
        <div className="lb-crm-empty" role="status">
          <strong>Loading conversation leads…</strong>
          <span>Reading the connected source window.</span>
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="lb-crm-empty">
          <strong>{profiles.length === 0 ? "No conversation leads are available." : "No leads match these filters."}</strong>
          <span>{profiles.length === 0 ? "Connect or refresh a live source to load profiles from open conversations." : "Clear or adjust a filter to widen the list."}</span>
        </div>
      )}

      {filtered.length > PROFILE_PAGE && (
        <footer className="ab-inbox-foot">
          <span className="ab-inbox-range mono">
            {showAll ? `Showing all ${filtered.length}` : `${rangeStart}–${rangeEnd} of ${filtered.length}`}
          </span>
          <div className="ab-inbox-pager">
            {!showAll && (
              <>
                <button type="button" className="ab-inbox-page-btn" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={safePage === 0} aria-label="Previous leads">‹</button>
                <span className="ab-inbox-page-num mono">{safePage + 1} / {totalPages}</span>
                <button type="button" className="ab-inbox-page-btn" onClick={() => setPage((value) => Math.min(totalPages - 1, value + 1))} disabled={safePage === totalPages - 1} aria-label="Next leads">›</button>
              </>
            )}
            <button type="button" className="ab-inbox-page-toggle" onClick={() => { setShowAll((value) => !value); setPage(0); }}>
              {showAll ? "Paginate" : "Show all"}
            </button>
          </div>
        </footer>
      )}

      {assignOpen && (
        <div
          className="crm-tagpicker-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !assignBusy) setAssignOpen(false);
          }}
        >
          <div
            className="crm-tagpicker crm-add-lead-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Assign selected leads to an agent"
          >
            <div className="crm-tagpicker-head">
              <h3>Assign to agent</h3>
              <button type="button" aria-label="Close assign form" disabled={assignBusy} onClick={() => setAssignOpen(false)}>×</button>
            </div>
            <p className="crm-tagpicker-sub">
              Sets the assigned agent on <strong className="mono">{selectedProfiles.length}</strong> selected
              lead{selectedProfiles.length === 1 ? "" : "s"}. Leave the name empty to clear the assignment.
            </p>
            {assignError && <div className="crm-contact-error" role="alert">{assignError}</div>}
            <label className="crm-criteria-field">
              <span>Agent name</span>
              <input
                type="text"
                value={assignName}
                placeholder="e.g. Skyleigh"
                autoFocus
                onChange={(event) => setAssignName(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") void runAssign(); }}
              />
            </label>
            <div className="crm-tagpicker-foot">
              <button type="button" disabled={assignBusy} onClick={() => void runAssign()}>
                {assignBusy ? "Assigning…" : assignName.trim() ? "Assign leads" : "Clear assignment"}
              </button>
            </div>
          </div>
        </div>
      )}

      {composeChannel && (
        <BulkComposeModal
          channel={composeChannel}
          profiles={selectedProfiles}
          onClose={() => setComposeChannel(null)}
          onDone={handleComposeDone}
        />
      )}
    </section>
  );
}
