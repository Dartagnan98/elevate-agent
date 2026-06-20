import { useMemo, useState, type KeyboardEvent } from "react";

import type { LeadsProfile } from "../leads-data";
import { matchesLeadsSourceFilter } from "./action-queue";
import { StatusPill } from "./profile-status";

export { StatusPill } from "./profile-status";

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
  const handleKeyDown = (e: KeyboardEvent) => {
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

export function ProfilesList({
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
