import { useEffect, useMemo, useRef, useState } from "react";

import type { LeadsDraft, LeadsDraftAction, LeadsProfile, LeadsTemperature } from "../leads-data";
import { PIPELINE_STAGES, resolvePipelineStage } from "../pipeline-stages";
import { DraftRow } from "./draft-row";
import "./leads-redesign.css";

// ── constants ────────────────────────────────────────────────────────────
const PAGE = 50;
const TEMPS: Array<{ id: LeadsTemperature; label: string }> = [
  { id: "hot", label: "Hot" },
  { id: "warm", label: "Warm" },
  { id: "lukewarm", label: "Lukewarm" },
  { id: "cool", label: "Cool" },
  { id: "soi", label: "SOI" },
  { id: "nurture", label: "Nurture" },
];
const TEMP_VAR: Record<LeadsTemperature, string> = {
  hot: "var(--hot)", warm: "var(--warm)", lukewarm: "var(--lukewarm)",
  cool: "var(--cool)", soi: "var(--soi)", nurture: "var(--nurture)",
};

function initials(name: string): string {
  return name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "?";
}
function normName(s: string): string {
  return (s || "").trim().toLowerCase();
}

export interface LeadsTableProps {
  profiles: LeadsProfile[];
  drafts: LeadsDraft[];
  kpis: {
    drafts: number; hot: number; avgFirstTouch: string; replyRate: string;
    newLeads7d: string | number;
  };
  onOpen: (p: LeadsProfile) => void;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onBulkUpdate?: (
    profiles: LeadsProfile[],
    action: "tags" | "segments" | "pipeline",
    value: unknown,
    mode?: "add" | "replace" | "remove",
  ) => Promise<{ updated: number; failed: Array<{ contactId: string; error: string }> }>;
}

// Close-on-outside-click helper for the several popovers on this view.
function useClickAway(onAway: () => void) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onAway();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onAway]);
  return ref;
}

export function LeadsTable(props: LeadsTableProps) {
  const { profiles, drafts, kpis } = props;

  const [query, setQuery] = useState("");
  const [sourceF, setSourceF] = useState("all");
  const [stageF, setStageF] = useState("all");
  const [tempF, setTempF] = useState<"all" | LeadsTemperature>("all");
  const [tagsF, setTagsF] = useState<Set<string>>(new Set());
  const [openMenu, setOpenMenu] = useState<null | "source" | "stage" | "temp" | "filters" | "add" | "more" | "sort">(null);
  const [sortBy, setSortBy] = useState<"draft" | "activity" | "name">("draft");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  // Session-only custom filter options added via "Add New" (not yet persisted).
  const [customStages, setCustomStages] = useState<string[]>([]);
  const [customTags, setCustomTags] = useState<string[]>([]);
  const [modal, setModal] = useState<
    null | { title: string; placeholder: string; onConfirm: (v: string) => void }
  >(null);
  const [modalVal, setModalVal] = useState("");

  const closeAll = () => setOpenMenu(null);
  const sourceRef = useClickAway(() => setOpenMenu((m) => (m === "source" ? null : m)));
  const stageRef = useClickAway(() => setOpenMenu((m) => (m === "stage" ? null : m)));
  const tempRef = useClickAway(() => setOpenMenu((m) => (m === "temp" ? null : m)));
  const filtersRef = useClickAway(() => setOpenMenu((m) => (m === "filters" ? null : m)));
  const addRef = useClickAway(() => setOpenMenu((m) => (m === "add" ? null : m)));
  const moreRef = useClickAway(() => setOpenMenu((m) => (m === "more" ? null : m)));
  const sortRef = useClickAway(() => setOpenMenu((m) => (m === "sort" ? null : m)));

  function showToast(msg: string, err = false) {
    setToast({ msg, err });
    window.setTimeout(() => setToast(null), 2800);
  }

  // ── draft index: match a pending draft to a profile by name ──────────────
  const draftByName = useMemo(() => {
    const m = new Map<string, LeadsDraft>();
    for (const d of drafts) {
      const key = normName(d.name);
      if (key && !m.has(key)) m.set(key, d);
    }
    return m;
  }, [drafts]);

  // ── distinct dimension values + counts (over the full loaded set) ────────
  const sourceOpts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of profiles) {
      const s = (p.source || "—").trim() || "—";
      counts.set(s, (counts.get(s) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [profiles]);

  // Skyleigh's 9 stages are the fixed canonical Pipeline filter, always shown
  // in pipeline order (not just stages present on the current page). Legacy
  // AI values map into her stages via resolvePipelineStage, so a follow_up lead
  // tallies under "Attempted", dead under "Trash", etc.
  const stageOpts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of PIPELINE_STAGES) counts.set(s.label, 0);
    for (const p of profiles) {
      const label = resolvePipelineStage(p.status).label;
      if (counts.has(label)) counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    for (const c of customStages) if (!counts.has(c)) counts.set(c, 0);
    return Array.from(counts.entries());
  }, [profiles, customStages]);

  const tempCounts = useMemo(() => {
    const counts = new Map<LeadsTemperature, number>();
    for (const p of profiles) {
      const t = (p.temperature ?? "nurture") as LeadsTemperature;
      counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return counts;
  }, [profiles]);

  const tagOpts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of profiles) for (const t of p.tags || []) counts.set(t, (counts.get(t) ?? 0) + 1);
    for (const c of customTags) if (!counts.has(c)) counts.set(c, 0);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [profiles, customTags]);

  // ── filtering (AND across dims, OR within tags) ──────────────────────────
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return profiles.filter((p) => {
      if (sourceF !== "all" && ((p.source || "—").trim() || "—") !== sourceF) return false;
      if (stageF !== "all" && resolvePipelineStage(p.status).label !== stageF) return false;
      if (tempF !== "all" && (p.temperature ?? "nurture") !== tempF) return false;
      if (tagsF.size > 0 && !(p.tags || []).some((t) => tagsF.has(t))) return false;
      if (q && !p.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [profiles, sourceF, stageF, tempF, tagsF, query]);

  // Sort the filtered set. "draft" floats leads with a ready-to-send draft to
  // the top (then most-recent), so the approve-and-send work is right there.
  const sorted = useMemo(() => {
    const hasDraft = (p: LeadsProfile) => draftByName.has(normName(p.name));
    const arr = filtered.slice();
    if (sortBy === "draft") {
      arr.sort((a, b) => {
        const d = (hasDraft(b) ? 1 : 0) - (hasDraft(a) ? 1 : 0);
        if (d !== 0) return d;
        return (b.latestAtIso || "").localeCompare(a.latestAtIso || "");
      });
    } else if (sortBy === "activity") {
      arr.sort((a, b) => (b.latestAtIso || "").localeCompare(a.latestAtIso || ""));
    } else if (sortBy === "name") {
      arr.sort((a, b) => a.name.localeCompare(b.name));
    }
    return arr;
  }, [filtered, sortBy, draftByName]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = sorted.slice(safePage * PAGE, safePage * PAGE + PAGE);

  useEffect(() => { setPage(0); }, [sourceF, stageF, tempF, tagsF, query, sortBy]);

  const activeFilterCount =
    (sourceF !== "all" ? 1 : 0) + (stageF !== "all" ? 1 : 0) + (tempF !== "all" ? 1 : 0) + tagsF.size;

  // ── selection ────────────────────────────────────────────────────────────
  const toggleSel = (id: string) =>
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allVisibleChecked = visible.length > 0 && visible.every((p) => selected.has(p.id));
  const toggleAll = () =>
    setSelected((s) => {
      const n = new Set(s);
      if (allVisibleChecked) visible.forEach((p) => n.delete(p.id));
      else visible.forEach((p) => n.add(p.id));
      return n;
    });
  const selectedProfiles = useMemo(
    () => profiles.filter((p) => selected.has(p.id)),
    [profiles, selected],
  );
  const clearSel = () => setSelected(new Set());

  // ── bulk actions ─────────────────────────────────────────────────────────
  async function runBulk(action: "tags" | "segments" | "pipeline", value: string, mode: "add" | "replace" = "add") {
    if (!props.onBulkUpdate) { showToast("Bulk update is not available.", true); return; }
    setBusy(true);
    try {
      const res = await props.onBulkUpdate(selectedProfiles, action, value, mode);
      const failed = res.failed?.length ?? 0;
      showToast(
        `${res.updated} updated${failed ? ` · ${failed} skipped` : ""}`,
        failed > 0 && res.updated === 0,
      );
      if (res.updated > 0) clearSel();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Bulk update failed.", true);
    } finally {
      setBusy(false);
      setOpenMenu(null);
    }
  }
  function bulkStub(label: string) {
    setOpenMenu(null);
    showToast(`${selected.size} selected — ${label} (not wired yet)`);
  }
  function promptBulk(action: "tags" | "segments" | "pipeline", title: string, placeholder: string) {
    setOpenMenu(null);
    setModalVal("");
    setModal({ title, placeholder, onConfirm: (v) => void runBulk(action, v) });
  }

  // ── add-new ──────────────────────────────────────────────────────────────
  function addNew(kind: "lead" | "pipeline" | "segment" | "tag") {
    setOpenMenu(null);
    if (kind === "lead") { showToast("New lead — use Config › Connectors to add a source lead."); return; }
    setModalVal("");
    if (kind === "pipeline")
      setModal({ title: "New pipeline stage", placeholder: "e.g. Under Contract", onConfirm: (v) => { setCustomStages((s) => [...s, v]); showToast(`Added pipeline stage “${v}” (this session)`); } });
    else if (kind === "segment")
      setModal({ title: "New segment", placeholder: "e.g. This-week hot", onConfirm: (v) => { showToast(`Added segment “${v}” (this session)`); } });
    else
      setModal({ title: "New tag", placeholder: "e.g. Pre-approved", onConfirm: (v) => { setCustomTags((t) => [...t, v]); showToast(`Added tag “${v}” (this session)`); } });
  }

  const draftsWaiting = kpis.drafts;
  const hasAvgFirstTouch = kpis.avgFirstTouch && kpis.avgFirstTouch !== "—";
  const hasReplyRate = kpis.replyRate && kpis.replyRate !== "—";

  const sourceLabel = sourceF === "all" ? "All" : sourceF;
  const stageLabel = stageF === "all" ? "All" : stageF;
  const tempLabel = tempF === "all" ? "All" : (TEMPS.find((t) => t.id === tempF)?.label ?? "All");

  return (
    <div className="leadsx">
      {/* masthead */}
      <div className="leadsx-masthead">
        <div>
          <h1 className="leadsx-title">Leads</h1>
          <div className="leadsx-sub">Your pipeline, sources, and follow-up cadence in one board</div>
        </div>
        <div className="leadsx-mright">
          <div className="leadsx-filterswrap" ref={filtersRef}>
            <button className="leadsx-filterbtn" onClick={() => setOpenMenu((m) => (m === "filters" ? null : "filters"))}>
              Filters {activeFilterCount > 0 && <span className="leadsx-fbadge">{activeFilterCount}</span>}
            </button>
            {openMenu === "filters" && (
              <div className="leadsx-pop">
                <div className="leadsx-pop-head">
                  <b>Filter by</b>
                  <button className="leadsx-pop-clear" onClick={() => { setSourceF("all"); setStageF("all"); setTempF("all"); setTagsF(new Set()); }}>Clear all</button>
                </div>
                <div className="leadsx-pop-sec">
                  <div className="leadsx-pop-lab">Tags</div>
                  <div className="leadsx-pop-chips">
                    {tagOpts.length === 0 && <span className="leadsx-pop-empty">No tags on the loaded leads yet.</span>}
                    {tagOpts.map(([t, c]) => (
                      <button
                        key={t}
                        className={"chip sm" + (tagsF.has(t) ? " on" : "")}
                        onClick={() => setTagsF((s) => { const n = new Set(s); n.has(t) ? n.delete(t) : n.add(t); return n; })}
                      >
                        {t} <span className="c">{c}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="leadsx-filterswrap" ref={addRef}>
            <button className="leadsx-addbtn" onClick={() => setOpenMenu((m) => (m === "add" ? null : "add"))}>+ Add New ▾</button>
            {openMenu === "add" && (
              <div className="leadsx-menu">
                <button onClick={() => addNew("lead")}><span className="ic">👤</span>New lead</button>
                <div className="sep" />
                <button onClick={() => addNew("pipeline")}><span className="ic">⛁</span>New pipeline stage</button>
                <button onClick={() => addNew("segment")}><span className="ic">🌡</span>New segment</button>
                <button onClick={() => addNew("tag")}><span className="ic">🏷</span>New tag</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* KPI strip — only render KPIs we actually have data for */}
      <div className="leadsx-kpis">
        <div className="leadsx-kpi"><div className="n">{kpis.newLeads7d}</div><div className="l"><b>New</b> in the last 7 days</div></div>
        <div className="leadsx-kpi"><div className="n">{kpis.hot}</div><div className="l"><b>Hot</b> drafts (0.7+ score)</div></div>
        <div className="leadsx-kpi accent"><div className="pin">approve</div><div className="n">{draftsWaiting}</div><div className="l"><b>Drafts</b> waiting on you</div></div>
        {hasAvgFirstTouch && <div className="leadsx-kpi"><div className="n">{kpis.avgFirstTouch}</div><div className="l">Avg <b>first touch</b></div></div>}
        {hasReplyRate && <div className="leadsx-kpi"><div className="n">{kpis.replyRate}</div><div className="l"><b>Reply rate</b></div></div>}
      </div>

      {/* search */}
      <div className="leadsx-search">
        <span className="s-ic">🔍</span>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search a lead by name…" autoComplete="off" />
      </div>

      {/* quick filters */}
      <div className="leadsx-quick">
        <div className={"leadsx-qf" + (sourceF !== "all" ? " active" : "")} ref={sourceRef}>
          <button className="leadsx-qf-btn" onClick={() => setOpenMenu((m) => (m === "source" ? null : "source"))}>
            <span className="leadsx-qf-lab">Source</span><b className="leadsx-qf-val">{sourceLabel}</b><span className="leadsx-qf-car">▾</span>
          </button>
          {openMenu === "source" && (
            <div className="leadsx-qf-menu">
              <button className={"chip" + (sourceF === "all" ? " on" : "")} onClick={() => { setSourceF("all"); closeAll(); }}>All <span className="c">{profiles.length}</span></button>
              {sourceOpts.map(([s, c]) => (
                <button key={s} className={"chip" + (sourceF === s ? " on" : "")} onClick={() => { setSourceF(s); closeAll(); }}>
                  <span className="tdot" style={{ background: "var(--navy-3)" }} />{s} <span className="c">{c}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className={"leadsx-qf" + (stageF !== "all" ? " active" : "")} ref={stageRef}>
          <button className="leadsx-qf-btn" onClick={() => setOpenMenu((m) => (m === "stage" ? null : "stage"))}>
            <span className="leadsx-qf-lab">Pipeline</span><b className="leadsx-qf-val">{stageLabel}</b><span className="leadsx-qf-car">▾</span>
          </button>
          {openMenu === "stage" && (
            <div className="leadsx-qf-menu">
              <button className={"chip" + (stageF === "all" ? " on" : "")} onClick={() => { setStageF("all"); closeAll(); }}>All <span className="c">{profiles.length}</span></button>
              {stageOpts.map(([s, c]) => (
                <button key={s} className={"chip" + (stageF === s ? " on" : "")} onClick={() => { setStageF(s); closeAll(); }}>
                  <span className="tdot" style={{ background: "var(--navy-3)" }} />{s} <span className="c">{c}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className={"leadsx-qf" + (tempF !== "all" ? " active" : "")} ref={tempRef}>
          <button className="leadsx-qf-btn" onClick={() => setOpenMenu((m) => (m === "temp" ? null : "temp"))}>
            <span className="leadsx-qf-lab">Temp</span><b className="leadsx-qf-val">{tempLabel}</b><span className="leadsx-qf-car">▾</span>
          </button>
          {openMenu === "temp" && (
            <div className="leadsx-qf-menu">
              <button className={"chip" + (tempF === "all" ? " on" : "")} onClick={() => { setTempF("all"); closeAll(); }}>All</button>
              {TEMPS.map((t) => (
                <button key={t.id} className={"chip" + (tempF === t.id ? " on" : "")} onClick={() => { setTempF(t.id); closeAll(); }}>
                  <span className="tdot" style={{ background: TEMP_VAR[t.id] }} />{t.label} <span className="c">{tempCounts.get(t.id) ?? 0}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="leadsx-qf" ref={sortRef}>
          <button className="leadsx-qf-btn" onClick={() => setOpenMenu((m) => (m === "sort" ? null : "sort"))}>
            <span className="leadsx-qf-lab">Sort</span>
            <b className="leadsx-qf-val">{sortBy === "draft" ? "Draft ready" : sortBy === "activity" ? "Recent activity" : "Name"}</b>
            <span className="leadsx-qf-car">▾</span>
          </button>
          {openMenu === "sort" && (
            <div className="leadsx-qf-menu">
              <button className={"chip" + (sortBy === "draft" ? " on" : "")} onClick={() => { setSortBy("draft"); closeAll(); }}>Draft ready first</button>
              <button className={"chip" + (sortBy === "activity" ? " on" : "")} onClick={() => { setSortBy("activity"); closeAll(); }}>Recent activity</button>
              <button className={"chip" + (sortBy === "name" ? " on" : "")} onClick={() => { setSortBy("name"); closeAll(); }}>Name (A-Z)</button>
            </div>
          )}
        </div>
      </div>

      {/* selection bar */}
      {selected.size > 0 && (
        <div className="leadsx-selbar">
          <span className="cnt"><b>{selected.size}</b> selected</span>
          <button className="leadsx-sb-btn leadsx-sb-primary" disabled={busy} onClick={() => bulkStub("Mass Email")}>✉ Mass Email</button>
          <button className="leadsx-sb-btn" disabled={busy} onClick={() => bulkStub("Mass Text")}>💬 Mass Text</button>
          <button className="leadsx-sb-btn" disabled={busy} onClick={() => bulkStub("Assign to agent")}>Assign to agent</button>
          <div className="leadsx-sb-more" ref={moreRef}>
            <button className="leadsx-sb-btn" disabled={busy} onClick={() => setOpenMenu((m) => (m === "more" ? null : "more"))}>More ▾</button>
            {openMenu === "more" && (
              <div className="leadsx-moremenu">
                <button onClick={() => bulkStub("Send to Dialer")}><span className="ic">📞</span>Send to Dialer</button>
                <div className="sep" />
                <button onClick={() => promptBulk("pipeline", "Change pipeline stage", "e.g. Prospect")}><span className="ic">⛁</span>Change Pipeline</button>
                <button onClick={() => promptBulk("segments", "Add a segment", "e.g. SOI")}><span className="ic">🌡</span>Change Segments</button>
                <button onClick={() => promptBulk("tags", "Add a tag", "e.g. Pre-approved")}><span className="ic">🏷</span>Change Tags</button>
                <div className="sep" />
                <button className="soon"><span className="ic">✉</span>Send Postcards<span className="tagsoon">soon</span></button>
                <button className="soon"><span className="ic">📄</span>Send Letters<span className="tagsoon">soon</span></button>
              </div>
            )}
          </div>
          <button className="leadsx-sb-btn leadsx-sb-clear" onClick={clearSel}>Clear</button>
        </div>
      )}

      {/* table */}
      <div className="leadsx-tablewrap">
        <div className="leadsx-tscroll">
          <div className="leadsx-thead">
            <div className="leadsx-th"><span className={"leadsx-cbox" + (allVisibleChecked ? " checked" : "")} onClick={toggleAll} /></div>
            <div className="leadsx-th">Name</div>
            <div className="leadsx-th">Pipeline stage</div>
            <div className="leadsx-th">Contact</div>
            <div className="leadsx-th">Source</div>
            <div className="leadsx-th">Next / AI</div>
            <div className="leadsx-th">Activity</div>
            <div className="leadsx-th" />
          </div>

          {visible.length === 0 && <div className="leadsx-empty">No leads match these filters.</div>}

          {visible.map((p) => {
            const heat = (p.temperature ?? "nurture") as LeadsTemperature;
            const draft = draftByName.get(normName(p.name));
            const stage = resolvePipelineStage(p.status).label;
            const isOpen = expandedId === p.id;
            return (
              <div key={p.id} className={"leadsx-group" + (isOpen ? " open" : "")}>
                <div
                  className="leadsx-trow"
                  role="button"
                  tabIndex={0}
                  onClick={() => props.onOpen(p)}
                  onKeyDown={(e) => { if (e.key === "Enter") props.onOpen(p); }}
                >
                  <div onClick={(e) => e.stopPropagation()}>
                    <span className={"leadsx-cbox" + (selected.has(p.id) ? " checked" : "")} onClick={() => toggleSel(p.id)} />
                  </div>
                  <div className="leadsx-namecell">
                    <button
                      className={"leadsx-star" + (p.favorite ? " on" : "")}
                      disabled={!props.onFavoriteChange}
                      aria-label={p.favorite ? "Remove favorite" : "Add favorite"}
                      onClick={(e) => { e.stopPropagation(); void props.onFavoriteChange?.(p, !p.favorite); }}
                    >
                      {p.favorite ? "★" : "☆"}
                    </button>
                    <div className="leadsx-avatar" data-heat={heat}>{initials(p.name)}</div>
                    <div className="leadsx-nm">
                      <div className="n">{p.name}{p.verified && <span className="verified" title="Verified">✓</span>}</div>
                      <div className="t"><span className={"leadsx-tpill " + heat}>{TEMPS.find((t) => t.id === heat)?.label ?? heat}</span>{p.sub || ""}</div>
                    </div>
                  </div>
                  <div><span className="leadsx-stage"><span className="dot" /><span className="txt">{stage}</span></span></div>
                  <div className="leadsx-contact">
                    <div className="e">{p.email || "—"}</div>
                    <div className="p">{p.phone || "—"}</div>
                  </div>
                  <div className="leadsx-src">{p.source || "—"}</div>
                  <div onClick={(e) => e.stopPropagation()}>
                    {draft ? (
                      <button className="leadsx-ai-draft" onClick={() => setExpandedId((id) => (id === p.id ? null : p.id))}>
                        ✦ Reply drafted
                      </button>
                    ) : (
                      <span className="leadsx-ai-muted">—</span>
                    )}
                  </div>
                  <div className="leadsx-activity">{p.lastTouch || p.age || "—"}</div>
                  <div className="leadsx-chev-cell">›</div>
                </div>
                {isOpen && draft && (
                  <div className="leadsx-draftpanel" onClick={(e) => e.stopPropagation()}>
                    <DraftRow
                      draft={draft}
                      selected={false}
                      expanded
                      onToggle={() => {}}
                      onExpand={() => {}}
                      busy={busy}
                      onAction={async (action, d, scheduledAt) => {
                        setBusy(true);
                        try {
                          await props.onDraftAction?.(action, d, scheduledAt);
                          await props.onDraftActionComplete?.(action);
                          if (action !== "edit") setExpandedId(null);
                        } catch (err) {
                          showToast(err instanceof Error ? err.message : "Draft action failed.", true);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* pager */}
      {filtered.length > PAGE && (
        <div className="leadsx-pager">
          <span className="rng">{safePage * PAGE + 1}–{Math.min(filtered.length, safePage * PAGE + PAGE)} of {filtered.length}</span>
          <div className="nums">
            <button disabled={safePage === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>‹</button>
            <button className="on">{safePage + 1}</button>
            <span style={{ color: "var(--faint)", fontFamily: "var(--lx-mono)", fontSize: 12 }}>of {totalPages}</span>
            <button disabled={safePage >= totalPages - 1} onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}>›</button>
          </div>
        </div>
      )}

      <div className="leadsx-callout">
        <b>Three ways to slice it, all stacking:</b> Source (where they came from), Pipeline (their stage), and Temp (your follow-up cadence). Check any rows for the bulk bar: Mass Email / Mass Text, Send to Dialer, Assign to agent, and More for Change Pipeline / Segments / Tags. Click a row to open the contact card, or the drafted chip to review and approve inline.
      </div>

      {/* name-it modal */}
      {modal && (
        <div className="leadsx-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setModal(null); }}>
          <div className="leadsx-modal">
            <h3>{modal.title}</h3>
            <input
              autoFocus
              value={modalVal}
              placeholder={modal.placeholder}
              onChange={(e) => setModalVal(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && modalVal.trim()) { modal.onConfirm(modalVal.trim()); setModal(null); } }}
            />
            <div className="leadsx-modal-actions">
              <button className="leadsx-modal-cancel" onClick={() => setModal(null)}>Cancel</button>
              <button className="leadsx-modal-add" disabled={!modalVal.trim()} onClick={() => { modal.onConfirm(modalVal.trim()); setModal(null); }}>Add</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className={"leadsx-toast" + (toast.err ? " leadsx-err" : "")}>{toast.msg}</div>}
    </div>
  );
}

export default LeadsTable;
