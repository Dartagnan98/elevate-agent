// Comp review — the screen that replaces "log into Xposure to check a comp".
//
// Master-detail: the candidate rail on the left stays put while the pane on the
// right carries everything Xposure holds for the selected listing (all photos,
// the facts against the subject's, the status). Skyleigh keeps her place across
// 50+ candidates and never loses the list to a modal.
//
// Four groups, because the useful question is not just "which comps did it pick"
// but "what did it see and not pick":
//   Included     the selected comp set
//   Worth a look in-band solds that missed selection (where her local knowledge counts)
//   Did not sell expired/cancelled/withdrawn — ceiling evidence, NEVER comps
//   Out of range everything dropped, each with its reason, collapsed
//
// Photo indices are NOT a range. Comps are numbered from 1, actives and the
// subject from 0, so we always iterate the `indices` the API returns.
import { useCallback, useEffect, useRef, useState } from "react";
import CmaInfo from "./cma-info";
import { api } from "../../../../lib/api";
import CmaFinishGrid from "./cma-finish-grid";
import CmaExpiredReview from "./cma-expired-review";
import type { CmaCandidate, CmaFacts } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#dde2ea", BLUE = "#5E8AD0",
  GREEN = "#2E7D32", TERRA = "#C46340";

type NoteRec = { mls: string; kind: string; num?: number; address?: string;
                 raw?: string; voiced?: string; savedAt?: string;
                 position?: string | null };

// Skyleigh's method, in her words: "we just move the property to be better or
// worse than other properties could've sold." This is that control. It is the
// pricing model -- the cheapest comp above the home is the ceiling, the dearest
// below it is the floor -- so nothing here computes a price from square footage
// or averages.
const POSITIONS: { key: string; short: string; long: string }[] = [
  { key: "subject_leads", short: "more", long: "Yours sells for more than this one" },
  { key: "on_par", short: "about the same", long: "Yours competes closely with this one" },
  { key: "comp_leads", short: "less", long: "This one sells for more than yours" },
];

type CompFeed = {
  mls: string; address: string; price: string | number; compNum?: number;
  excluded?: boolean; beds?: number; baths?: number; year?: number;
  soldDate?: string | null; status?: string; carriedOver?: boolean;
  subArea?: string | null; listPrice?: string | number | null; dom?: number | null;
};

type Group = "included" | "active" | "worth" | "expired" | "out";

type Row = CmaCandidate & { _group: Group; _num?: number; _attempts?: number; _tries?: string;
  carriedOver?: boolean; subArea?: string | null; listPrice?: string | number | null; dom?: number | null };

const money = (v: unknown) => {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(String(v).replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(n) || n === 0) return String(v);
  return n >= 1000 ? `${Math.round(n / 1000)}k` : `$${n}`;
};

export default function CmaCompReview({
  dealId,
  soldComps,
  activeComps,
  yours,
  onToggle,
}: {
  dealId: string;
  // The selected comps from /cma/comps — they carry compNum, which is what the
  // photo endpoints key on. The candidates feed has no compNum.
  soldComps: CompFeed[];
  activeComps?: CompFeed[];
  // Her own specs, pinned above the comps. Passed in rather than fetched: the
  // comps call already carries them, and a second round-trip put a nine-second
  // "Loading the comp review" in front of the list.
  yours?: CmaFacts | null;
  onToggle: (mls: string, kind: "sold" | "active") => void;
}) {
  const isMobile = useIsMobile();
  // Names the seller's own home in the lightbox, so "this comp" and "your home"
  // are never ambiguous when two photos sit side by side.
  const subjectAddress = (yours?.address || "").toString().trim();
  // Which SET the selected row belongs to. Photos and detail sheets are numbered
  // per set -- comp-2 and active-2 are different properties -- so every call that
  // takes a number must also carry the kind. Hardcoding "comp" here meant
  // selecting an active listing showed the sold comp holding the same number:
  // 9199 Knouff Lake (active 2) rendered 1860 Agate Bay Road (comp 2).
  const kindOf = (g?: string): "comp" | "active" => (g === "active" ? "active" : "comp");
  // Her notes, keyed "<kind>:<mls>". Loaded once with the comps so clicking
  // between properties does not re-fetch on every selection.
  const [notes, setNotes] = useState<Record<string, NoteRec>>({});
  useEffect(() => {
    let live = true;
    api.getCmaNotes(dealId)
      .then((r) => { if (live && r?.ok) setNotes(r.notes || {}); })
      .catch(() => { /* the field still works, it just starts empty */ });
    return () => { live = false; };
  }, [dealId]);
  const [rows, setRows] = useState<Row[]>([]);
  const [sel, setSel] = useState<string>("");
  const [note, setNote] = useState("");
  const [photos, setPhotos] = useState<{ indices: number[]; count: number; labels?: Record<string, string>; rooms?: Record<string, number> } | null>(null);
  const [lightbox, setLightbox] = useState<number | null>(null);
  // Her own photos, so the lightbox can put her kitchen beside theirs. Fetched
  // once per deal: they do not change as she moves down the rail.
  const [subjPhotos, setSubjPhotos] = useState<number[]>([]);
  const [subjRooms, setSubjRooms] = useState<Record<string, number>>({});
  const [subjLabels, setSubjLabels] = useState<Record<string, string>>({});
  // True when the pane on the right was chosen by matching the room, not by her.
  const [matched, setMatched] = useState<string | null>(null);
  const [subjAt, setSubjAt] = useState(0);
  const [showOut, setShowOut] = useState(false);
  const [loading, setLoading] = useState(true);

  // Build the rail from three sources. Selected comps come from /cma/comps so we
  // keep compNum (needed for photos); the rest come from the candidate grid.
  const build = useCallback(async () => {
    const out: Row[] = [];
    for (const c of soldComps) {
      out.push({
        mls: c.mls, address: c.address, price: c.price, soldDate: c.soldDate,
        beds: c.beds, baths: c.baths, year: c.year, excluded: c.excluded,
        carriedOver: c.carriedOver,
        subArea: c.subArea, listPrice: c.listPrice, dom: c.dom,
        _group: "included", _num: c.compNum,
      });
    }
    // Actives, in the same shape and the same list.
    for (const c of activeComps || []) {
      out.push({
        mls: c.mls, address: c.address, price: c.price, status: c.status,
        beds: c.beds, baths: c.baths, year: c.year, excluded: c.excluded,
        subArea: c.subArea, listPrice: c.listPrice, dom: c.dom,
        _group: "active", _num: c.compNum,
      });
    }
    const seen = new Set(out.map((r) => String(r.mls)));

    try {
      const cand = await api.getCmaCandidates(dealId);
      if (cand.available) {
        for (const c of cand.worthALook || []) {
          if (!seen.has(String(c.mls))) { out.push({ ...c, _group: "worth" }); seen.add(String(c.mls)); }
        }
        for (const c of cand.outOfRange || []) {
          if (!seen.has(String(c.mls))) { out.push({ ...c, _group: "out" }); seen.add(String(c.mls)); }
        }
        setNote("");
      } else {
        setNote(cand.reason || "Search again to see every property the tool found.");
      }
    } catch { setNote("Could not load the candidate list."); }

    try {
      const exp = await api.getCmaExpired(dealId);
      if (exp.available) {
        for (const g of exp.byAddress || []) {
          const first = g.listings?.[0] || {};
          out.push({
            mls: String(first.mlsNumber || g.address),
            address: g.address,
            price: first.listPrice ?? null,
            status: first.status,
            beds: first.bedrooms, baths: first.bathrooms, year: first.yearBuilt,
            _group: "expired",
            _attempts: g.attempts,
            _tries: (g.listings || []).map((l) => money(l.listPrice)).filter(Boolean).join(", "),
          });
        }
      }
    } catch { /* expired is additive; never block the review on it */ }

    setRows(out);
    setLoading(false);
    if (!sel && out.length) setSel(String(out[0].mls));
  }, [dealId, soldComps, activeComps]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void build(); }, [build]);


  useEffect(() => {
    let live = true;
    api.listCmaCompPhotos(dealId, 0, "subject")
      .then((r) => {
        if (!live) return;
        setSubjPhotos(r.indices || []);
        setSubjRooms(r.rooms || {}); setSubjLabels(r.labels || {});
      })
      .catch(() => { if (live) setSubjPhotos([]); });
    return () => { live = false; };
  }, [dealId]);

  const current = rows.find((r) => String(r.mls) === sel) || null;

  // ROOM MATCHING. Both photo sets are labelled by the scoring pass ("Kitchen -
  // white shaker cabinets..."), so the first word is a usable key. When she
  // opens their kitchen, show hers. No label on either side means no match is
  // claimed: her pane just stays where it was, and the badge does not appear.
  const roomOf = (label?: string) =>
    (label || "").trim().split(/[ ,-]/)[0].toLowerCase();
  useEffect(() => {
    if (lightbox === null || !photos?.labels) { setMatched(null); return; }
    const room = roomOf(photos.labels[String(lightbox)]);
    const hers = room ? subjRooms[room] : undefined;
    if (hers === undefined) { setMatched(null); return; }
    const at = subjPhotos.indexOf(hers);
    if (at >= 0) { setSubjAt(at); setMatched(room); }
  }, [lightbox, photos, subjRooms, subjPhotos]);

  // Photos only exist for listings we actually opened, which is the selected set.
  useEffect(() => {
    setPhotos(null); setLightbox(null);
    if (!current || current._num === undefined) return;
    let cancelled = false;
    api.listCmaCompPhotos(dealId, current._num, kindOf(current._group))
      .then((r) => { if (!cancelled) setPhotos({ indices: r.indices || [], count: r.count || 0, labels: r.labels, rooms: r.rooms }); })
      .catch(() => { if (!cancelled) setPhotos({ indices: [], count: 0 }); });
    return () => { cancelled = true; };
    // _group is a dependency, not decoration: moving from sold comp 2 to active
    // comp 2 keeps the same number, so without it the effect never re-runs and
    // the previous set's photos stay on screen.
  }, [dealId, current?._num, current?._group]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard triage. j/k move, i/x toggle, space opens photos, esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      const visible = rows.filter((r) => r._group !== "out" || showOut);
      const i = visible.findIndex((r) => String(r.mls) === sel);
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); if (i < visible.length - 1) setSel(String(visible[i + 1].mls)); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); if (i > 0) setSel(String(visible[i - 1].mls)); }
      else if ((e.key === "i" || e.key === "x") && current && current._group === "included") { onToggle(current.mls, "sold"); }
      else if (e.key === " " && photos?.indices.length) { e.preventDefault(); setLightbox(photos.indices[0]); }
      else if (e.key === "Escape") setLightbox(null);
      else if ((e.key === "s" || e.key === "S") && lightbox !== null && subjPhotos.length > 1) {
        // Hers and theirs move independently: the two sets are not paired, so
        // advancing both together would be a guess. S goes forward, Shift+S
        // back, mirroring the two arrows now under each photo -- the keyboard
        // had the same missing-direction gap the buttons did.
        e.preventDefault();
        const step = e.shiftKey ? -1 : 1;
        setSubjAt((i) => (i + step + subjPhotos.length) % subjPhotos.length);
        setMatched(null);
      }
      else if (lightbox !== null && photos?.indices.length) {
        const pi = photos.indices.indexOf(lightbox);
        if (e.key === "ArrowRight" && pi < photos.indices.length - 1) setLightbox(photos.indices[pi + 1]);
        if (e.key === "ArrowLeft" && pi > 0) setLightbox(photos.indices[pi - 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, sel, current, photos, lightbox, showOut, onToggle, subjPhotos]);

  // Every group renders the SAME way (Skyleigh 2026-08-17: "I want the actives
  // and the expired options to be the same format as the solds. That way I can
  // see everything and make the decision to keep it or not"). No second-class
  // rendering: she decides, so she sees the same facts for each.
  const kept = rows.filter((r) => (r._group === "included" || r._group === "active") && !r.excluded).length;
  const dropped = rows.filter((r) => (r._group === "included" || r._group === "active") && r.excluded).length;
  const looking = rows.filter((r) => r._group === "worth").length;

  // The label says the OUTCOME; the reasoning sits behind the (i). "Worth a
  // look" and "Out of range" both described a feeling about a property without
  // saying whether it was in or out of the evaluation, which is the only thing
  // the label needs to answer at a glance.
  const groups: { key: Group; label: string; hint?: React.ReactNode }[] = [
    { key: "included", label: "Sold comps",
      hint: "The properties this evaluation is built from. Untick one to drop it." },
    { key: "active", label: "On the market now",
      hint: "What your seller is competing against today. Competition, not evidence of value, so these never set the price." },
    { key: "worth", label: "Close, but not used",
      hint: "These matched on most things but fell outside the search band, so the tool left them out. Tick one to bring it in." },
    { key: "expired", label: "Didn't sell",
      hint: "Came off the market without an offer the sellers could take. Never counted as comps. They set the ceiling." },
    { key: "out", label: "Too far off to compare",
      hint: "Dropped because a figure sat too far from your seller's home to be a fair comparison. Each one shows the reason." },
  ];

  const railRow = (r: Row) => {
    const on = String(r.mls) === sel;
    const gone = !!r.excluded;
    // The checkbox IS the include/exclude control. She asked for the actives
    // list's pattern rather than a button buried in the detail pane, and it also
    // means the decision is visible for every row at once instead of one at a time.
    const kind: "sold" | "active" = r._group === "active" ? "active" : "sold";
    const selectable = r._group === "included" || r._group === "active";
    return (
      <div key={r.mls + r.address} onClick={() => setSel(String(r.mls))}
        style={{
          display: "flex", alignItems: "flex-start", gap: 9, padding: isMobile ? "9px 11px" : "8px 12px",
          cursor: "pointer", minHeight: 44,
          borderLeft: `2.5px solid ${on ? BLUE : "transparent"}`,
          background: on ? "#fff" : "transparent",
        }}>
        {selectable ? (
          <input
            type="checkbox"
            checked={!gone}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onToggle(r.mls, kind)}
            aria-label={`Include ${r.address}`}
            style={{ width: 20, height: 20, flexShrink: 0, marginTop: 1, cursor: "pointer", accentColor: GREEN }}
          />
        ) : (
          <span aria-hidden style={{ width: 20, flexShrink: 0, textAlign: "center", color: MUTED, fontWeight: 800, marginTop: 1 }}>
            {r._group === "expired" ? "◇" : "?"}
          </span>
        )}
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", fontSize: isMobile ? 14 : 13, fontWeight: on ? 700 : 600, color: gone ? MUTED : NAVY, textDecoration: gone ? "line-through" : "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.address}
          </span>
          {/* Where it is. The first thing she asks of any comp. */}
          <span style={{ display: "block", fontSize: 12, color: MUTED, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.subArea || "area not on file"}
            {r._attempts ? ` · tried ${r._attempts}x` : ""}
          </span>
        </span>
        <span style={{ flexShrink: 0, textAlign: "right" }}>
          <span style={{ display: "block", fontSize: isMobile ? 14 : 13, fontWeight: 700, color: gone ? MUTED : NAVY, fontVariantNumeric: "tabular-nums" }}>
            {money(r.price)}
          </span>
          {/* Listed vs sold, so a reduction is visible without opening anything. */}
          {r.listPrice && money(r.listPrice) !== money(r.price) && (
            <span style={{ display: "block", fontSize: 11.5, color: MUTED, fontVariantNumeric: "tabular-nums" }}>
              asked {money(r.listPrice)}
            </span>
          )}
        </span>
      </div>
    );
  };

  if (loading) return <div style={{ fontSize: 12.5, color: MUTED, padding: "10px 2px" }}>Loading comparables…</div>;

  return (
    <div style={{ marginTop: 12, border: `1px solid ${LINE}`, borderRadius: 10, overflow: "hidden", background: "#fff" }}>
      {note && (
        <div style={{ background: "#FDF3E4", borderBottom: `1px solid #EBD2A8`, color: "#6E4409", fontSize: 12, padding: "8px 13px" }}>
          {note}
        </div>
      )}
      {/* Master-detail is a desktop shape. On a phone the 250px rail beside the
          pane leaves nothing for either, so stack: list on top, detail beneath. */}
      {/* YOURS. Pinned so every comparison below has something to compare to. */}
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap", padding: isMobile ? "8px 11px 0" : "8px 14px 0", fontSize: 13, color: MUTED }}>
        <b style={{ color: NAVY }}>{kept} in</b>
        {dropped > 0 && <span>{dropped} dropped</span>}
        {looking > 0 && <span>{looking} to look at</span>}
      </div>

      {yours && (
        <div style={{ display: "flex", gap: isMobile ? 8 : 14, flexWrap: "wrap", alignItems: "baseline", padding: isMobile ? "9px 11px" : "9px 14px", background: NAVY, color: "#fff", fontSize: 13 }}>
          <span style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".08em", color: "#aeb9d4" }}>YOURS</span>
          {yours.sqft != null && <span><b>{yours.sqft.toLocaleString("en-CA")}</b> sqft</span>}
          {yours.beds != null && yours.baths != null && <span><b>{yours.beds}</b> bed, <b>{yours.baths}</b> bath</span>}
          {yours.lotSqft != null && <span>lot <b>{yours.lotSqft.toLocaleString("en-CA")}</b></span>}
          {yours.yearBuilt != null && <span>built <b>{yours.yearBuilt}</b></span>}
          {yours.basement && <span style={{ color: "#c8d2e8" }}>{yours.basement}</span>}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: isMobile ? "column" : "row", alignItems: "stretch", minHeight: isMobile ? 0 : 420 }}>
        {/* rail */}
        <div style={{ width: isMobile ? "100%" : 250, flexShrink: 0, background: "#F0F3F8", borderRight: isMobile ? "none" : `1px solid ${LINE}`, borderBottom: isMobile ? `1px solid ${LINE}` : "none", padding: "8px 0 12px", maxHeight: isMobile ? 260 : 620, overflowY: "auto" }}>
          {groups.map((g) => {
            const rs = rows.filter((r) => r._group === g.key);
            if (!rs.length) return null;
            const collapsed = g.key === "out" && !showOut;
            return (
              <div key={g.key}>
                <div onClick={() => g.key === "out" && setShowOut((v) => !v)}
                  style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".08em", textTransform: "uppercase", color: MUTED, padding: "9px 13px 5px", display: "flex", gap: 6, cursor: g.key === "out" ? "pointer" : "default" }}>
                  {g.label} <span style={{ color: "#4A5468" }}>{rs.length}</span>
                  {g.hint && <CmaInfo label={`What "${g.label}" means`}>{g.hint}</CmaInfo>}
                  {g.key === "out" && <span style={{ marginLeft: "auto" }}>{collapsed ? "▸" : "▾"}</span>}
                </div>
                {!collapsed && rs.map(railRow)}
              </div>
            );
          })}
        </div>

        {/* detail pane */}
        <div style={{ flex: 1, padding: isMobile ? "12px 13px" : "13px 16px", minWidth: 0 }}>
          {!current ? (
            <div style={{ fontSize: 12.5, color: MUTED }}>Choose a property to see how it compares</div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <span style={{ fontSize: 16, fontWeight: 800, color: NAVY }}>{current.address}</span>
                <span style={{ marginLeft: "auto", fontSize: 16, fontWeight: 800, color: NAVY, fontVariantNumeric: "tabular-nums" }}>
                  {current.price ? String(current.price) : ""}
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: MUTED, marginTop: 3, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {current.soldDate && <span>{current.status || "Sold"} {current.soldDate}</span>}
                {current.mls && <span>MLS {current.mls}</span>}
                {current.beds != null && <span>{current.beds}bd</span>}
                {current.baths != null && <span>{current.baths}ba</span>}
                {current.year != null && <span>built {current.year}</span>}
                {current.searchPass && (
                  <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: ".05em", textTransform: "uppercase", padding: "2px 7px", borderRadius: 4, background: /cross|districtWide/i.test(String(current.searchPass)) ? "#FDF3E4" : "#EAF0F9", color: /cross|districtWide/i.test(String(current.searchPass)) ? "#6E4409" : "#33538A" }}>
                    {/* Strips both the original `passN-` prefix and the relax-ladder
                        `rungN-` prefix, so a rung row reads "nearby-noLot" and not
                        "rung3-nearby-noLot". District-wide gets the same warning
                        tint as cross-area: both mean "not near the subject". */}
                    {String(current.searchPass).replace(/^(pass|rung)\d+-/, "")}
                  </span>
                )}
              </div>

              {/* expired: the repeat-listing story */}
              {current._group === "expired" && (
                <div style={{ marginTop: 12, border: `1px solid ${LINE}`, borderRadius: 9, padding: "11px 13px", fontSize: 12.5, color: "#4A5468", lineHeight: 1.6 }}>
                  {current._attempts && current._attempts > 1 ? (
                    <>
                      <b style={{ color: TERRA }}>Listed {current._attempts} times without selling.</b>{" "}
                      Asked {current._tries}. The market did not respond at any of those numbers.
                    </>
                  ) : (
                    <>Came off the market without an offer the sellers could take.</>
                  )}
                  <div style={{ marginTop: 6, fontSize: 11.5, color: MUTED }}>
                    Ceiling evidence only. Expired listings never enter the comp set or the price.
                  </div>
                </div>
              )}

              {/* why it was not used */}
              {current.reason && (
                <div style={{ marginTop: 12, fontSize: 12.5, color: "#6E4409", background: "#FDF3E4", border: "1px solid #EBD2A8", borderRadius: 9, padding: "9px 12px" }}>
                  Not used: {current.reason}
                </div>
              )}

              {current.carriedOver && (
                <div style={{ marginTop: 10, padding: "8px 10px", background: "#EAF0F9", border: "1px solid #C7D6EC", borderRadius: 8, fontSize: 12, color: "#2C4A7C", lineHeight: 1.45 }}>
                  The latest pull did not surface this one again, so these details are carried over from the earlier pull.
                </div>
              )}

              {/* Theirs vs yours. The whole point of the review screen: answer
                  "how does this compare to mine" without opening Xposure. */}
              {current._num !== undefined && <CompDeltas dealId={dealId} num={current._num} kind={kindOf(current._group)} />}

              {/* Her own sentence about this comp. Only on comps that are IN the
                  evaluation: there is nothing to say to a seller about one she
                  dropped. What she approves replaces the automatic "taking the
                  lot, size and finishings together..." line for this comp. */}
              {!current.excluded && current._group !== "expired" && (
                <CompNote
                  key={`${current._group}:${current.mls}`}
                  dealId={dealId}
                  mls={String(current.mls)}
                  kind={current._group === "active" ? "active" : "sold"}
                  address={String(current.address || "")}
                  saved={notes[`${current._group === "active" ? "active" : "sold"}:${current.mls}`]}
                  // MERGE, do not replace: the autosave reports only `raw`, and a
                  // replace here would wipe voiced/position off the parent's copy.
                  onSaved={(k, v) => setNotes((m) => ({ ...m, [k]: { ...(m[k] || {}), ...v } }))}
                />
              )}

              {/* photos */}
              {current._num !== undefined && (
                <div style={{ marginTop: 13 }}>
                  {photos === null ? (
                    <div style={{ fontSize: 12, color: MUTED }}>Loading photos…</div>
                  ) : photos.indices.length === 0 ? (
                    <div style={{ fontSize: 12, color: MUTED }}>This listing has no photos on the MLS.</div>
                  ) : (
                    <>
                      <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                        {photos.indices.slice(0, 8).map((i) => (
                          <img key={i} src={api.cmaCompPhotoUrl(dealId, current._num as number, i, kindOf(current._group))} alt=""
                            onClick={() => setLightbox(i)}
                            // boxSizing is load-bearing here: the 1px border is OUTSIDE the width
                            // under the default content-box, so two "50% - 4px" thumbs came to
                            // 353px in a 350px row and wrapped to one per row on a phone.
                            style={{ width: isMobile ? "calc(50% - 4px)" : 104, height: 78, boxSizing: "border-box", objectFit: "cover", borderRadius: 6, border: `1px solid ${LINE}`, cursor: "zoom-in", background: "#eef1f6" }} />
                        ))}
                        {photos.indices.length > 8 && (
                          <div onClick={() => setLightbox(photos.indices[8])}
                            style={{ width: isMobile ? "calc(50% - 4px)" : 104, height: 78, boxSizing: "border-box", borderRadius: 6, background: "#EDF0F5", color: "#4A5468", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
                            +{photos.indices.length - 8}
                          </div>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: MUTED, marginTop: 6 }}>
                        {photos.count} photo{photos.count === 1 ? "" : "s"} captured. Click any to enlarge, then use the arrow keys.
                      </div>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* lightbox */}
      {lightbox !== null && current?._num !== undefined && photos && (
        <div onClick={() => setLightbox(null)} role="dialog" aria-modal="true"
          aria-label={`Photos for ${current.address}`}
          // Above the CMA surface (1100), or the photo opens behind it.
          // MOBILE: this was centred with no overflow, so the stack (header + two
          // 32vh images + two captions + the match chip + Done) ran past the
          // viewport and the ends were simply unreachable -- Skyleigh 2026-08-31:
          // "on mobile when I bring up the photo comparisons it's not all visible."
          // Centring is right when it fits and wrong when it does not, so on a
          // phone it starts at the top and scrolls instead.
          style={{ position: "fixed", inset: 0, background: "rgba(13,20,33,.93)", zIndex: 1250, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: isMobile ? "flex-start" : "center", overflowY: isMobile ? "auto" : "hidden", WebkitOverflowScrolling: "touch", gap: 12, padding: 12, paddingBottom: "max(12px, env(safe-area-inset-bottom))" }}>

          {/* The room leads, because the room is what she is comparing. The
              addresses sit on each photo where they disambiguate "theirs" and
              "yours" without a legend. */}
          <div style={{ color: "#CBD6E8", fontSize: 13, display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", justifyContent: "center", textAlign: "center" }}>
            <b style={{ color: "#fff" }}>{photos?.labels?.[String(lightbox)] || "Photos"}</b>
            {!isMobile && <span>← → this comp · S / shift S your home · Esc close</span>}
          </div>

          {/* Theirs beside yours: comparing finishes is the judgement this screen
              exists for, and it cannot be made from one photo at a time. Stacked
              on a phone, because two images side by side on a 390px screen are
              too small to judge a kitchen from.

              Each photo owns its own back/next bar directly underneath it. This
              used to be one row of two buttons BOTH labelled "Theirs" plus a
              lone "Next" tucked in the subject's caption with no way back, so
              the two halves of the same job lived in different places and one
              direction was simply missing. */}
          <div onClick={(e) => e.stopPropagation()}
            style={{ display: "flex", flexDirection: isMobile ? "column" : "row", gap: 10, alignItems: "flex-start", justifyContent: "center", maxWidth: "96vw" }}>

            <figure style={{ margin: 0, display: "flex", flexDirection: "column", gap: 6, alignItems: "center", width: isMobile ? "92vw" : "46vw" }}>
              <img src={api.cmaCompPhotoUrl(dealId, current._num, lightbox, kindOf(current._group))} alt={`${current.address} photo`}
                style={{ maxWidth: "100%", maxHeight: isMobile ? "32vh" : "62vh", objectFit: "contain", borderRadius: 8, background: "#0d1421" }} />
              <figcaption style={{ color: "#CBD6E8", fontSize: 13, fontWeight: 600, textAlign: "center", maxWidth: "100%" }}>
                {current.address}
                <span style={{ display: "block", fontWeight: 400, color: "#93A2BE", fontSize: 11.5, marginTop: 2 }}>
                  This comp{photos?.labels?.[String(lightbox)] ? ` · ${photos.labels[String(lightbox)]}` : ""}
                </span>
              </figcaption>
              <PhotoNav
                at={photos.indices.indexOf(lightbox)}
                count={photos.indices.length}
                label={`${current.address} photos`}
                onPrev={() => { const i = photos.indices.indexOf(lightbox); if (i > 0) setLightbox(photos.indices[i - 1]); }}
                onNext={() => { const i = photos.indices.indexOf(lightbox); if (i < photos.indices.length - 1) setLightbox(photos.indices[i + 1]); }}
              />
            </figure>

            <figure style={{ margin: 0, display: "flex", flexDirection: "column", gap: 6, alignItems: "center", width: isMobile ? "92vw" : "46vw" }}>
              {subjPhotos.length ? (
                <img src={api.cmaCompPhotoUrl(dealId, 0, subjPhotos[subjAt % subjPhotos.length], "subject")}
                  alt="Your listing photo"
                  style={{ maxWidth: "100%", maxHeight: isMobile ? "32vh" : "62vh", objectFit: "contain", borderRadius: 8, background: "#0d1421" }} />
              ) : (
                <div style={{ width: "100%", minHeight: isMobile ? 110 : 200, borderRadius: 8, background: "#151d2e", border: "1px solid #2a3550", display: "flex", alignItems: "center", justifyContent: "center", padding: 20, textAlign: "center" }}>
                  <span style={{ color: "#9FB0CC", fontSize: 14, lineHeight: 1.5, maxWidth: "40ch" }}>
                    No photos of this home yet. Add them on the Property step and they show here beside every comp.
                  </span>
                </div>
              )}
              <figcaption style={{ color: "#CBD6E8", fontSize: 13, fontWeight: 600, textAlign: "center", maxWidth: "100%" }}>
                {subjectAddress || "Your home"}
                <span style={{ display: "block", fontWeight: 400, color: "#93A2BE", fontSize: 11.5, marginTop: 2 }}>
                  Your home{subjPhotos.length && subjLabels[String(subjPhotos[subjAt % subjPhotos.length])] ? ` · ${subjLabels[String(subjPhotos[subjAt % subjPhotos.length])]}` : ""}
                </span>
              </figcaption>
              {subjPhotos.length > 0 && (
                <PhotoNav
                  at={subjAt % subjPhotos.length}
                  count={subjPhotos.length}
                  label="Your photos"
                  onPrev={() => { setSubjAt((i) => (i - 1 + subjPhotos.length) % subjPhotos.length); setMatched(null); }}
                  onNext={() => { setSubjAt((i) => (i + 1) % subjPhotos.length); setMatched(null); }}
                />
              )}
            </figure>
          </div>

          {/* Stated, never forced: the two sides move independently and this only
              reports when they happen to land on the same room. */}
          {matched && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "#1E3A2C", color: "#8FCB9B", border: "1px solid #2F5741", borderRadius: 20, padding: "4px 11px", fontSize: 12, fontWeight: 700 }}>
              Both showing the {matched}
            </span>
          )}

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }} onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setLightbox(null)}
              style={{ minHeight: 44, background: "transparent", color: "#CBD6E8", border: "1px solid #2a3550", borderRadius: 8, padding: "10px 20px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Done</button>
          </div>
        </div>
      )}
      {/* Her finish calls, on the Comparables step, feeding straight into the report. */}
      <CmaFinishGrid dealId={dealId} />

      {/* The expired band is curated HERE, beside the sold and active comps,
          because it is the same decision: which properties does this seller see. */}
      <CmaExpiredReview dealId={dealId} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   CompNote — Skyleigh's own sentence about one comparable.

   The report has always been able to print her words instead of the automatic
   "taking the lot, size and finishings together..." verdict: generate-cma-pdf-v2
   reads `_verdict` off the comp and prints it first. Until now there was nowhere
   to write it, so the ability sat unused.

   The flow is deliberately two steps. She types shorthand, the rewrite comes
   back written for the report, and NOTHING is saved until she presses Add to
   report. A tool
   that published its own draft into a client document would be the wrong kind
   of automatic, and the same rule governs every other send in this system.

   If the rewrite fails she still gets to keep her own words, because the
   failure returns her original text rather than nothing.
   ───────────────────────────────────────────────────────────────── */
function CompNote({ dealId, mls, kind, address, saved, onSaved }: {
  dealId: string; mls: string; kind: "sold" | "active"; address: string;
  saved?: NoteRec; onSaved: (key: string, rec: NoteRec) => void;
}) {
  const [raw, setRaw] = useState(saved?.raw || "");
  const [draft, setDraft] = useState("");
  // Edit focuses the drafted paragraph rather than re-running the writer: she
  // fixes the word she wants changed instead of re-rolling and hoping.
  const draftRef = useRef<HTMLTextAreaElement | null>(null);
  const [pos, setPos] = useState<string | null>(saved?.position ?? null);
  const [posSource, setPosSource] = useState<"yours" | "tool" | null>(saved?.position ? "yours" : null);

  const savePosition = async (next: string | null) => {
    const prev = pos;
    posTouched.current = true;  // her tap outranks any late-arriving fetch
    setPos(next); setPosSource(next ? "yours" : null);   // optimistic: the control must not lag a tap
    try {
      const r = await api.setCmaPosition(dealId, mls, kind, next);
      if (!r?.ok) { setPos(prev); setErr(r?.error || "Could not save that."); }
    } catch { setPos(prev); setErr("Could not save that."); }
  };
  const [busy, setBusy] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  // Non-empty when the autosave could NOT land her words. This must be loud:
  // a silent failed autosave under a "Saving…" line is the fourth way to lose
  // the same note.
  const [saveErr, setSaveErr] = useState("");

  // She has typed in THIS mounted box. While true, nothing arriving from the
  // parent (the late first notes fetch, any refetch) may replace her words --
  // the reset effect below used to setRaw(saved?.raw) whenever the parent's
  // copy changed, so a fetch that resolved mid-typing clobbered the textarea
  // with the older disk copy while her newer words were still in the debounce.
  const dirty = useRef(false);
  const posTouched = useRef(false);
  // Mirrors `raw` for the pagehide flush, which runs outside React's lifecycle.
  const rawRef = useRef(raw);
  rawRef.current = raw;

  // AUTOSAVE THE TYPED TEXT.
  //
  // Skyleigh 2026-08-31: "I just wrote notes on Gleneagles 696 and it doesn't
  // look like it saved." It had not -- onChange only set React state, so her
  // words were in the browser and nowhere else until she pressed the rewrite
  // button, while the Better/Worse toggle beside it saved on tap. Two controls an
  // inch apart behaving differently, with nothing on screen to say which was safe.
  //
  // Debounced so a fast typist is not one request per keystroke, flushed on blur
  // so leaving the field commits immediately, flushed on unmount/comp-switch so
  // navigating away cannot outrun the timer, and flushed with `keepalive` on
  // pagehide so closing the tab cannot either.
  //
  // SINGLE-FLIGHT, CONFIRMED, RETRIED. The first version fired saves in
  // parallel and marked "Saved" as soon as any response arrived -- so two
  // saves could land out of order (older text winning on disk), and a response
  // of {ok:false} or {} (the runner crashing) still showed "Saved. Your words
  // are kept" over words that were nowhere. Now: one request at a time, newest
  // text always wins, "Saved" only after the server said ok, failures retried
  // and, if they keep failing, said out loud.
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingDraft = useRef<string | null>(null);
  const draftFor = useRef<string>("");
  const inFlight = useRef(false);
  const retries = useRef(0);
  // The last text the SERVER confirmed. "Saved" is only honest while the box
  // matches this.
  const confirmedRaw = useRef<string | null>(null);
  const sendDraft = useCallback((mlsKey: string, kindKey: "sold" | "active", text: string): Promise<void> => {
    inFlight.current = true;
    return api.cmaSaveNoteDraft(dealId, mlsKey, kindKey, text)
      .then((r) => {
        if (!r?.ok) throw new Error(r?.error || "The save did not go through.");
        confirmedRaw.current = text;
        retries.current = 0;
        setSaveErr("");
        setDraftSaved(rawRef.current.trim() === text.trim());
        // Keep the parent's copy in step with the disk, so switching to another
        // comp and back shows her words instead of an empty box over a safe file.
        onSaved(`${kindKey}:${mlsKey}`, { mls: mlsKey, kind: kindKey, raw: text });
      })
      .catch(() => {
        setDraftSaved(false);
        retries.current += 1;
        setSaveErr(retries.current >= 5
          ? "Your words are NOT saved yet. Keep this page open — still retrying."
          : "Not saved yet — retrying…");
        // Re-queue this text unless she has already typed something newer.
        if (pendingDraft.current === null) {
          pendingDraft.current = text;
          draftFor.current = `${kindKey}:${mlsKey}`;
        }
        if (retryTimer.current) clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(() => { drainDraft(); }, 3000);
      })
      .finally(() => {
        inFlight.current = false;
        // Newer text queued while this one was in flight: send it now.
        if (pendingDraft.current !== null && !draftTimer.current && !retryTimer.current) drainDraft();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);
  const drainDraft = () => {
    if (retryTimer.current) { clearTimeout(retryTimer.current); retryTimer.current = null; }
    if (inFlight.current) return;
    const t = pendingDraft.current;
    if (t === null) return;
    pendingDraft.current = null;
    const [k, m] = (draftFor.current || `${kind}:${mls}`).split(":");
    void sendDraft(m, (k as "sold" | "active"), t);
  };
  const queueDraftSave = (text: string) => {
    dirty.current = true;
    setDraftSaved(false);
    retries.current = 0;
    pendingDraft.current = text;
    draftFor.current = `${kind}:${mls}`;
    if (draftTimer.current) clearTimeout(draftTimer.current);
    draftTimer.current = setTimeout(() => { draftTimer.current = null; drainDraft(); }, 800);
  };
  const flushDraftSave = () => {
    if (draftTimer.current) { clearTimeout(draftTimer.current); draftTimer.current = null; }
    drainDraft();
  };
  useEffect(() => () => {
    flushDraftSave();
    if (retryTimer.current) clearTimeout(retryTimer.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // CLOSING THE TAB. React never unmounts on tab close, the debounce timer dies
  // with the page, and an ordinary fetch already in flight is aborted -- so up
  // to 800ms of typing (plus anything unconfirmed) evaporated. `keepalive`
  // survives the page teardown. visibilitychange->hidden covers the phone case
  // (Safari does not reliably fire pagehide when the app is swiped away).
  useEffect(() => {
    const flush = () => {
      if (!dirty.current) return;
      const t = rawRef.current;
      if (t === confirmedRaw.current) return;
      try { void api.cmaSaveNoteDraft(dealId, mls, kind, t, { keepalive: true }); } catch { /* page is going away */ }
    };
    const onVis = () => { if (document.visibilityState === "hidden") flush(); };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [dealId, mls, kind]);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(false);
  // True while this instance is mounted. The rewrite poll below outlives a comp
  // switch (the component remounts via the key prop); local state writes from a
  // stale poll must become no-ops, while onSaved still delivers the finished
  // wording into the parent's map under the ORIGINAL key.
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  // Sync the box from the parent's copy -- but ONLY while she has not typed.
  // Remount (key prop) handles comp switches, so within one mounted instance the
  // only thing this effect ever receives is a parent-side update: the first
  // notes fetch resolving late, or our own onSaved echoing back. Before the
  // dirty guard, a fetch that resolved after she started typing clobbered the
  // textarea with the older disk copy (and wiped an in-progress draft edit via
  // setDraft("")). Her typing outranks anything the parent has: the autosave
  // owns the disk from her first keystroke.
  // It must also NOT clear busy: our own save-first onSaved fires while the
  // rewrite poll is still running, and resetting busy here re-enabled the
  // button mid-rewrite.
  useEffect(() => {
    if (!dirty.current) {
      setRaw(saved?.raw || ""); setDraft(""); setErr(""); setEditing(false);
      // What arrived IS the saved copy -- reflect that honestly in the status line.
      confirmedRaw.current = saved?.raw || "";
      setDraftSaved(!!(saved?.raw || "").trim());
    }
    if (!posTouched.current) {
      setPos(saved?.position ?? null);
      setPosSource(saved?.position ? "yours" : null);
    }
  }, [mls, saved?.raw, saved?.position]);

  const published = (saved?.voiced || "").trim();
  const key = `${kind}:${mls}`;
  const short = address.split(",")[0];

  // SAVE FIRST, then rewrite in the background.
  //
  // Skyleigh 2026-08-30: "when I typed the notes in the comp section it deletes it
  // if I leave the page before it's fully done re writing it." It was not deleting
  // anything -- it had never saved. The old call rewrote synchronously (up to two
  // minutes), saved NOTHING, and only persisted when she clicked save afterwards,
  // so her words lived in this component's state and nowhere else. Now the raw text
  // is on disk before the rewriter starts and she is free to leave immediately.
  const rewrite = async () => {
    if (!raw.trim() || busy) return;
    setBusy(true); setErr("");
    const mine = raw.trim();
    try {
      const r = await api.cmaRewriteNote(dealId, mls, kind, mine, pos);
      if (!r?.ok) { setErr(r?.error || "Could not save that note."); setBusy(false); return; }
      // Keep the previously published sentence visible while the new one is
      // prepared -- the backend now preserves it on disk for the same reason.
      onSaved(key, { mls, kind, address, raw: mine, voiced: saved?.voiced || "", position: pos });
      setErr("");
      // Poll for the voiced version. Her note is already safe either way, so a
      // failed or abandoned poll costs the wording, never the words.
      let tries = 0;
      const tick = async () => {
        tries += 1;
        try {
          const st = await api.cmaRewriteStatus(dealId, mls, kind);
          if (st?.rewrite === "done" && st.voiced) {
            onSaved(key, { mls, kind, address, raw: mine, voiced: st.voiced, position: pos });
            if (alive.current) { setDraft(st.voiced); setEditing(true); setBusy(false); }
            return;
          }
          if (st?.rewrite === "failed") {
            if (alive.current) {
              setDraft(st.raw || mine); setEditing(true); setBusy(false);
              setErr(st.voiced
                ? "The rewrite did not finish. Your note is saved; the report keeps the earlier wording until you save a new one."
                : "The wording could not be prepared. This is your own text, saved as you typed it.");
            }
            return;
          }
        } catch { /* keep polling; the note is already saved */ }
        if (tries > 60) {                       // ~3 min, then stop nagging
          if (alive.current) {
            setBusy(false);
            setErr("Still rewriting in the background. Your note is saved and you can carry on.");
          }
          return;
        }
        setTimeout(tick, 3000);
      };
      setTimeout(tick, 3000);
    } catch {
      setErr("Could not save that note.");
      setBusy(false);
    }
  };

  const save = async (text: string) => {
    setBusy(true); setErr("");
    try {
      const r = await api.setCmaNote(dealId, mls, kind, raw.trim(), text.trim(), pos);
      if (r?.ok) { onSaved(key, { mls, kind, address, raw: raw.trim(), voiced: text.trim(), position: pos }); setDraft(""); setEditing(false); }
      else setErr(r?.error || "Could not save that note.");
    } catch { setErr("Could not save that note."); }
    finally { setBusy(false); }
  };

  const box: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", font: "inherit", fontSize: 13, lineHeight: 1.5,
    color: NAVY, background: "#FBFCFD", border: `1px solid ${LINE}`, borderRadius: 7,
    padding: "9px 11px", minHeight: 66, resize: "vertical",
  };
  // One filled primary, one outlined secondary, and the dismissive action as
  // plain text set apart from them. Three equally weighted buttons is the thing
  // Apple's guidance warns against, and it was what this row used to be.
  const btn = (kind: "primary" | "secondary" | "quiet"): React.CSSProperties => ({
    minHeight: 44, borderRadius: 7,
    padding: kind === "quiet" ? "10px 4px" : "10px 16px",
    fontSize: 13, fontWeight: kind === "quiet" ? 600 : 800,
    cursor: busy ? "default" : "pointer", font: "inherit",
    border: kind === "secondary" ? `1px solid #C7D6EC` : "none",
    background: kind === "primary" ? (busy ? "#D8B7A6" : TERRA) : "transparent",
    color: kind === "primary" ? "#fff" : kind === "secondary" ? BLUE : MUTED,
  });

  return (
    <div style={{ marginTop: 13, border: `1px solid ${LINE}`, borderRadius: 9, overflow: "hidden", background: "#fff" }}>
      <div style={{ padding: "10px 12px 0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 800, color: NAVY }}>
          Yours sells for
          <CmaInfo label="About positioning">
            This is what sets the price. The cheapest comp that beats this home is the ceiling,
            the dearest one it beats is the floor, and the launch price sits between them. Your
            note sets this for you and you can flip it here.
          </CmaInfo>
        </div>
        <div role="group" aria-label={`Where ${short} sits`}
          style={{ display: "flex", gap: 6, marginTop: 7, flexWrap: "wrap" }}>
          {POSITIONS.map((o) => {
            const on = pos === o.key;
            return (
              <button key={o.key} type="button" title={o.long} aria-pressed={on}
                disabled={busy}
                onClick={() => void savePosition(on ? null : o.key)}
                style={{
                  minHeight: 44, padding: "9px 14px", borderRadius: 7, font: "inherit",
                  fontSize: 12.5, fontWeight: on ? 800 : 600, cursor: busy ? "default" : "pointer",
                  border: `1px solid ${on ? NAVY : "#C7D6EC"}`,
                  background: on ? NAVY : "transparent",
                  color: on ? "#fff" : BLUE,
                }}>{o.short}</button>
            );
          })}
          <span style={{ alignSelf: "center", fontSize: 11.5, color: MUTED }}>
            {pos ? (posSource === "yours" ? "from your note" : "the tool's read, change it if it is wrong")
                 : "not set yet"}
          </span>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "12px 12px 0", fontSize: 12.5, fontWeight: 800, color: NAVY }}>
        Your notes on {short}
        <CmaInfo label="About your notes">
          Write it however you like. It gets written up for the report, you approve it, and it
          prints under this property in place of the automatic wording. Leave it blank and this
          comparable keeps the automatic wording.
        </CmaInfo>
      </div>

      {published && !editing && !draft ? (
        <>
          <div style={{ margin: "8px 12px 0", padding: "10px 12px", borderRadius: 8, background: "#FBF1EC", border: "1px solid #E9CDBF", fontSize: 13, lineHeight: 1.6, color: NAVY }}>
            <span style={{ display: "block", fontSize: 10, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase", color: TERRA, marginBottom: 5 }}>
              In the report
            </span>
            {published}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 12px 12px", flexWrap: "wrap" }}>
            <button type="button" style={btn("secondary")} onClick={() => { setDraft(published); setEditing(true); }}>Edit</button>
            <button type="button" style={btn("quiet")} disabled={busy} onClick={() => { setRaw(""); save(""); }}>
              Remove
            </button>
          </div>
        </>
      ) : (
        <>
          <div style={{ padding: "8px 12px 0" }}>
            <textarea value={raw} onChange={(e) => { setRaw(e.target.value); queueDraftSave(e.target.value); }}
              onBlur={() => flushDraftSave()} style={box}
              aria-label={`Your notes on ${short}`}
              placeholder="Rough notes are fine. Nothing is added to the report until you approve it." />
            {/* She could not tell whether typing had saved, because it had not.
                Now it autosaves and SAYS so -- an invisible save is the same
                problem as no save. */}
            <div style={{ fontSize: 11.5, color: saveErr ? "#B3261E" : draftSaved ? GREEN : MUTED, marginTop: 4, fontWeight: saveErr ? 700 : 400 }}>
              {saveErr
                ? saveErr
                : raw.trim()
                  ? (draftSaved ? "Saved. Your words are kept even if you leave this page."
                                : "Saving as you type…")
                  : "Saved as you type."}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 12px 12px", flexWrap: "wrap" }}>
            <button type="button" style={btn("primary")} onClick={rewrite} disabled={busy || !raw.trim()}>
              {busy ? "Writing…" : "Write for the report"}
            </button>
            {editing && (
              <button type="button" style={btn("quiet")} onClick={() => { setEditing(false); setDraft(""); setRaw(saved?.raw || ""); }}>
                Cancel
              </button>
            )}
            <span style={{ fontSize: 11.5, color: MUTED }}>Takes about ten seconds.</span>
          </div>
        </>
      )}

      {draft && (
        <div style={{ padding: "0 12px 12px" }}>
          <div style={{ padding: "10px 12px", borderRadius: 8, background: "#FBF1EC", border: "1px solid #E9CDBF" }}>
            <span style={{ display: "block", fontSize: 10, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase", color: TERRA, marginBottom: 5 }}>
              For the report
            </span>
            <textarea ref={draftRef} value={draft} onChange={(e) => setDraft(e.target.value)}
              aria-label="Wording for the report"
              style={{ ...box, background: "transparent", border: "none", padding: 0, minHeight: 58 }} />
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
            <button type="button" style={btn("primary")} disabled={busy} onClick={() => save(draft)}>
              {busy ? "Saving…" : "Add to report"}
            </button>
            <button type="button" style={btn("secondary")} disabled={busy}
              onClick={() => {
                const el = draftRef.current;
                if (!el) return;
                el.focus();
                el.setSelectionRange(el.value.length, el.value.length);
              }}>Edit</button>
            <button type="button" style={btn("quiet")} disabled={busy}
              onClick={() => { setDraft(""); setEditing(false); }}>Discard</button>
          </div>
        </div>
      )}

      {err && (
        <div style={{ padding: "0 12px 12px", fontSize: 12, color: "#9B3B2E", lineHeight: 1.45 }}>{err}</div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   PhotoNav — back / position / next for ONE image.

   Both sides of the lightbox mount the same component, so the controls are
   identical and mirrored and neither side can end up missing a direction. The
   arrows are chevrons rather than words: the previous version labelled both
   buttons "Theirs", which named the subject instead of the action and gave two
   different controls the same name.

   A control at the end of its range is dimmed AND disabled AND marked
   aria-disabled, so the state does not rest on colour alone.
   ───────────────────────────────────────────────────────────────── */
function PhotoNav({ at, count, label, onPrev, onNext }: {
  at: number; count: number; label: string; onPrev: () => void; onNext: () => void;
}) {
  const atStart = at <= 0, atEnd = at >= count - 1;
  const btn = (off: boolean): React.CSSProperties => ({
    minWidth: 44, minHeight: 44, borderRadius: 7, border: "none",
    background: off ? "#1B2334" : "#26324E",
    color: off ? "#55617D" : "#fff",
    fontSize: 17, fontWeight: 700, lineHeight: 1,
    cursor: off ? "default" : "pointer",
    display: "inline-flex", alignItems: "center", justifyContent: "center",
  });
  return (
    <div role="group" aria-label={label}
      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, width: "100%", maxWidth: 320, marginTop: 2, background: "#182238", border: "1px solid #2A3550", borderRadius: 9, padding: 5 }}>
      <button type="button" onClick={onPrev} disabled={atStart} aria-disabled={atStart}
        aria-label="Previous photo" style={btn(atStart)}>‹</button>
      <span style={{ color: "#CBD6E8", fontSize: 12, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
        {count ? at + 1 : 0} of {count}
      </span>
      <button type="button" onClick={onNext} disabled={atEnd} aria-disabled={atEnd}
        aria-label="Next photo" style={btn(atEnd)}>›</button>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   CompDeltas — "theirs vs yours" for the selected comp.

   The rail feed carries 11 fields; the detail sheet on disk carries ~283 and
   every one was being discarded, so answering "is this bigger than mine" meant
   opening Xposure. This is that answer.

   Two rules it must not break:
   - NO dollar figure tied to the subject ever appears beside a comp (the reader
     strips subject price fields; nothing here re-adds them).
   - Direction is stated as fact, never as a verdict. "3,000 sqft larger lot",
     never "worse than yours". Skyleigh's clients read this language.
   ───────────────────────────────────────────────────────────────── */

function CompDeltas({ dealId, num, kind }: { dealId: string; num: number; kind: "comp" | "active" }) {
  const isMobile = useIsMobile();
  type Sheet = { title: string; rows: { label: string; value: string }[] }[];
  const [d, setD] = useState<{ comp?: CmaFacts & { publicRemarks?: string | null; sheet?: Sheet }; subject?: CmaFacts } | null>(null);
  const [state, setState] = useState<"loading" | "none" | "ready">("loading");
  const [showRemarks, setShowRemarks] = useState(false);
  const [showSheet, setShowSheet] = useState(false);

  useEffect(() => {
    let live = true;
    setState("loading"); setD(null); setShowRemarks(false); setShowSheet(false);
    api.getCmaCompDetail(dealId, num, kind)
      .then((r) => {
        if (!live) return;
        if (!r.available || !r.comp) { setState("none"); return; }
        setD({ comp: r.comp, subject: r.subject }); setState("ready");
      })
      .catch(() => { if (live) setState("none"); });
    return () => { live = false; };
  }, [dealId, num, kind]);

  if (state !== "ready" || !d?.comp) return null;

  const c = d.comp, s = d.subject || {};
  const nf = (n: number) => Math.round(n).toLocaleString("en-CA");

  // A row renders only when the comp has the value. The subject column and the
  // delta each degrade independently, because a missing subject figure (a stale
  // sheet with no year built) must not hide the comp's.
  const rows: { label: string; comp: string; subj: string; delta: string | null }[] = [];
  // `plain` skips the thousands separator. A year is not a quantity: without this
  // "Year built" rendered as "1,965".
  const numRow = (label: string, cv?: number | null, sv?: number | null, unit = "", biggerWord = "larger", smallerWord = "smaller", plain = false) => {
    if (cv == null) return;
    const fmt = (n: number) => (plain ? String(Math.round(n)) : nf(n));
    let delta: string | null = null;
    if (sv != null && sv !== 0) {
      const diff = Math.round(cv - sv);
      // Within 2% reads as the same; a 20 sqft difference is noise, not a fact
      // worth putting in front of a seller. Years are compared exactly, since a
      // 2% band would swallow a 30-year gap.
      if (!plain && Math.abs(diff) / sv < 0.02) delta = "about the same";
      else if (diff === 0) delta = "the same";
      else delta = `${plain ? Math.abs(diff) : nf(Math.abs(diff))}${plain ? " years" : unit} ${diff > 0 ? biggerWord : smallerWord}`;
    }
    rows.push({ label, comp: fmt(cv) + unit, subj: sv != null ? fmt(sv) + unit : "", delta });
  };
  const txtRow = (label: string, cv?: string | null, sv?: string | null) => {
    if (!cv) return;
    rows.push({ label, comp: cv, subj: sv || "", delta: null });
  };

  numRow("Finished area", c.sqft, s.sqft, " sqft");
  numRow("Lot", c.lotSqft, s.lotSqft, " sqft");
  numRow("Bedrooms", c.beds, s.beds, "", "more", "fewer");
  numRow("Bathrooms", c.baths, s.baths, "", "more", "fewer");
  numRow("Year built", c.yearBuilt, s.yearBuilt, "", "newer", "older", true);
  txtRow("Basement", c.basement, s.basement);
  txtRow("Suite potential", c.suitePotential, s.suitePotential);
  txtRow("Parking", c.parking, s.parking);
  if (c.dom != null) {
    rows.push({ label: "Days on market", comp: `${nf(c.dom)}${c.cdom != null && c.cdom !== c.dom ? ` (${nf(c.cdom)} cumulative)` : ""}`, subj: "", delta: null });
  }
  if (!rows.length) return null;

  return (
    <div style={{ marginTop: 13, border: `1px solid ${LINE}`, borderRadius: 9, overflow: "hidden" }}>
      <div style={{ display: "flex", gap: 8, padding: "6px 12px", background: "#F7F9FC", borderBottom: `1px solid ${LINE}`, fontSize: 10.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: MUTED }}>
        <span style={{ flex: 1 }}>How it compares</span>
        <span style={{ width: isMobile ? 82 : 120, textAlign: "right" }}>This comp</span>
        <span style={{ width: isMobile ? 72 : 96, textAlign: "right" }}>Yours</span>
      </div>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "6px 12px", borderBottom: `1px solid #F1F4F8`, fontSize: 13 }}>
          <span style={{ flex: 1, color: MUTED, minWidth: 0 }}>
            {r.label}
            {r.delta && <span style={{ color: NAVY, fontWeight: 600, marginLeft: isMobile ? 0 : 7, fontSize: 11.5, display: isMobile ? "block" : "inline" }}>{r.delta}</span>}
          </span>
          <span style={{ width: isMobile ? 82 : 120, textAlign: "right", fontWeight: 700, color: NAVY, wordBreak: "break-word" }}>{r.comp}</span>
          <span style={{ width: isMobile ? 72 : 96, textAlign: "right", color: r.subj ? "#4A5468" : "#B6BDC9", wordBreak: "break-word" }}>{r.subj || "not on file"}</span>
        </div>
      ))}
      {/* The MLS sheet. Skyleigh 2026-08-17: "Whatever the MLS sheet says should
          be included on the CMA wizard." Not a curated subset -- she decides
          from it, so she gets it. */}
      {!!(c.sheet || []).length && (
        <div style={{ borderTop: `1px solid ${LINE}` }}>
          <button type="button" onClick={() => setShowSheet((v) => !v)}
            aria-expanded={showSheet}
            style={{ width: "100%", textAlign: "left", font: "inherit", background: "#FCFDFE", border: "none", minHeight: 44, padding: "10px 12px", fontSize: 13, fontWeight: 700, color: BLUE, cursor: "pointer" }}>
            {showSheet ? "Hide full MLS sheet" : "Full MLS sheet"}
          </button>
          {showSheet && (
            <div style={{ padding: "0 12px 10px" }}>
              {(c.sheet || []).map((g) => (
                <div key={g.title} style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", color: MUTED, marginBottom: 4 }}>
                    {g.title}
                  </div>
                  {g.rows.map((r) => (
                    <div key={r.label} style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "4px 0", borderBottom: "1px solid #F4F6FA", fontSize: 13 }}>
                      <span style={{ flex: 1, color: MUTED, minWidth: 0 }}>{r.label}</span>
                      <span style={{ flexShrink: 0, maxWidth: "58%", textAlign: "right", fontWeight: 600, color: NAVY, wordBreak: "break-word" }}>{r.value}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {c.publicRemarks && (
        <div style={{ padding: "8px 12px", background: "#FCFDFE" }}>
          <button type="button" onClick={() => setShowRemarks((v) => !v)}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 11.5, fontWeight: 700, color: BLUE }}>
            {showRemarks ? "Hide listing description" : "Listing description"}
          </button>
          {showRemarks && (
            <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.55, color: "#384256" }}>{c.publicRemarks}</p>
          )}
        </div>
      )}
    </div>
  );
}
