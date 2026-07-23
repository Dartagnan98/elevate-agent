import { useMemo, useState } from "react";

import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "../leads-data";
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
      <div className="lb-profile-contact-cell">
        <span className="lb-profile-email mono">{profile.email || "—"}</span>
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
  searchQuery = "",
  loading = false,
  onOpen,
  onStatusChange,
  onFavoriteChange,
  onDraftAction,
  onDraftActionComplete,
  onEditTemplate,
}: {
  profiles: LeadsProfile[];
  drafts?: LeadsDraft[];
  sourceFilter: string;
  pipelineFilter?: string;
  temperatureFilter?: CrmTemperature;
  tagFilters?: string[];
  searchQuery?: string;
  loading?: boolean;
  onOpen: (p: LeadsProfile) => void;
  onStatusChange: (profile: LeadsProfile, value: string) => void;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  onEditTemplate?: () => void;
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
      searchQuery,
    }));
    if (audienceFilter === "verified") list = list.filter((profile) => profile.verified);
    if (audienceFilter === "potential") list = list.filter((profile) => !profile.verified);
    if (audienceFilter === "favorites") list = list.filter((profile) => Boolean(profile.favorite));
    return [...list].sort((a, b) => {
      const favoriteDelta = Number(Boolean(b.favorite)) - Number(Boolean(a.favorite));
      return favoriteDelta || b.heat - a.heat || a.name.localeCompare(b.name);
    });
  }, [profiles, sourceFilter, pipelineFilter, temperatureFilter, tagFilters, searchQuery, audienceFilter]);

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
                {[
                  "New Lead", "Attempted Contact", "Prospect", "Client", "Pending Deal",
                  "Closed", "Referred", "Realtor Contact", "Trash",
                ].map((stage) => <option key={stage} value={stage}>{stage}</option>)}
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
            <span className="lb-bulkbar-soon mono" title="Mass Email, Mass Text, Assign to agent, and Send to Dialer are on the build list — they are not wired to the send engine yet.">
              Mass Email / Text · soon
            </span>
            <button type="button" className="lb-bulkbar-select-page" onClick={selectVisible}>Select page</button>
            <button type="button" className="lb-bulkbar-clear" onClick={clearSelection}>Clear</button>
          </div>
        )}
        {bulkNotice && <div className="lb-bulkbar-notice" role="status">{bulkNotice}</div>}
      </div>

      <div className="lb-profiles-colhead" aria-hidden="true">
        <span></span>
        <span>Fav</span>
        <span></span>
        <span>Lead</span>
        <span>Contact</span>
        <span>Pipeline</span>
        <span>Temp</span>
        <span>Source</span>
        <span>Next / AI</span>
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
    </section>
  );
}
