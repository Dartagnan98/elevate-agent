// CMA address front door — mockup screen 1. Type an address, everything pulls.
//
// Two suggestion groups, in this order on purpose:
//   "Your deals"        an evaluation already open on this property. Picking one
//                       OPENS it. It must never create a second card for the same
//                       address; duplicate CMA cards on one property is a known
//                       painful failure on this pipeline.
//   "BC address lookup" the province's public geocoder, so a new property gets a
//                       real, correctly spelled address instead of whatever was
//                       typed at 11pm.
//
// Seller name is optional and is only a label on the new deal. Nothing here
// starts a search or sends anything; picking a row opens the wizard, and the
// wizard's own Subject step runs the pull.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";

const NAVY = "#182848", INK = "#1D2433", INK3 = "#6B7488", LINE = "#DDE2EA",
      LINE2 = "#EAEEF4", BLUE = "#5E8AD0", TERRA = "#C46340",
      WARN = "#B26B12", WARNBG = "#FDF3E4";

type DealHit = { dealId: string; address: string; side?: string | null; stage?: number | null; status?: string | null; title?: string | null };
type GeoHit = { address: string; locality?: string | null; score?: number | null; matchPrecision?: string | null };
type Row = { kind: "deal"; deal: DealHit } | { kind: "geo"; geo: GeoHit };

const STAGE_LABEL: Record<number, string> = {
  0: "CMA / Prospect", 1: "Listing initiated", 2: "Documents signed", 3: "Photos ready",
  4: "MLS entry", 5: "Listing live", 6: "Accepted offer", 7: "Subject removal",
  8: "Closing", 9: "Closed",
};

export default function CmaAddressIntake({ onOpenDeal }: { onOpenDeal: (dealId: string) => void }) {
  const isMobile = useIsMobile();
  const [q, setQ] = useState("");
  const [seller, setSeller] = useState("");
  const [deals, setDeals] = useState<DealHit[]>([]);
  const [geocoded, setGeocoded] = useState<GeoHit[]>([]);
  const [geocoderOk, setGeocoderOk] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [looking, setLooking] = useState(false);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState("");
  // Guards an out-of-order response overwriting a newer one: the user keeps
  // typing, an earlier slower request lands last, and the list reverts to
  // suggestions for a prefix they already moved past.
  const seqRef = useRef(0);

  const rows: Row[] = [
    ...deals.map((d) => ({ kind: "deal" as const, deal: d })),
    ...geocoded.map((g) => ({ kind: "geo" as const, geo: g })),
  ];

  useEffect(() => {
    const term = q.trim();
    if (term.length < 3) { setDeals([]); setGeocoded([]); setGeocoderOk(true); setLooking(false); return; }
    setLooking(true);
    const mine = ++seqRef.current;
    const t = setTimeout(() => {
      api.getCmaAddressSuggest(term)
        .then((r) => {
          if (mine !== seqRef.current) return;
          setDeals(r.deals || []); setGeocoded(r.geocoded || []);
          setGeocoderOk(r.geocoderOk !== false); setCursor(0);
        })
        .catch(() => { if (mine === seqRef.current) { setDeals([]); setGeocoded([]); } })
        .finally(() => { if (mine === seqRef.current) setLooking(false); });
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const choose = useCallback(async (row: Row | undefined) => {
    if (!row || creating) return;
    setErr("");
    if (row.kind === "deal") { onOpenDeal(row.deal.dealId); return; }
    setCreating(true);
    try {
      const title = seller.trim() ? `${row.geo.address} (${seller.trim()})` : row.geo.address;
      const deal = await api.createAdminDeal({
        title,
        side: "listing",
        listingAddress: row.geo.address,
        // Stage 0 = CMA / Prospect. Card auto-advance is never wanted, so this
        // opens where an evaluation belongs and stays there until she moves it.
        currentStage: 0,
      });
      const id = deal?.id;
      if (!id) throw new Error("the deal was created but came back without an id");
      onOpenDeal(id);
    } catch (e) {
      setErr(`Could not start that evaluation: ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }, [creating, seller, onOpenDeal]);

  const onKey = (e: React.KeyboardEvent) => {
    if (!rows.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(rows.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); void choose(rows[cursor]); }
    else if (e.key === "Escape") { setQ(""); }
  };

  const group = (label: string) => (
    <div key={`h-${label}`} style={{ padding: "6px 14px", background: "#F7F9FC", fontSize: 10.5, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: INK3, borderBottom: `1px solid ${LINE2}` }}>
      {label}
    </div>
  );

  const rowEl = (row: Row, idx: number) => {
    const on = idx === cursor;
    const isDeal = row.kind === "deal";
    const primary = isDeal ? row.deal.address : row.geo.address;
    const secondary = isDeal
      ? [row.deal.title && row.deal.title !== row.deal.address ? row.deal.title : null,
         row.deal.stage != null ? (STAGE_LABEL[row.deal.stage] ?? `Stage ${row.deal.stage}`) : null,
         row.deal.status && row.deal.status !== "active" ? row.deal.status : null].filter(Boolean).join(" · ")
      : [row.geo.locality, "BC"].filter(Boolean).join(", ");
    return (
      <div
        key={`${row.kind}-${idx}-${primary}`}
        role="option"
        aria-selected={on}
        onMouseEnter={() => setCursor(idx)}
        onClick={() => void choose(row)}
        style={{
          display: "flex", alignItems: isMobile ? "flex-start" : "center", gap: 11,
          flexDirection: isMobile ? "column" : "row",
          padding: "10px 14px", borderBottom: `1px solid ${LINE2}`, fontSize: 13.5,
          background: on ? "#F3F7FF" : "transparent", cursor: creating ? "wait" : "pointer",
        }}
      >
        <span style={{ fontWeight: 700, color: NAVY, flex: 1 }}>{primary}</span>
        {secondary && <span style={{ color: INK3, fontSize: 12 }}>{secondary}</span>}
        <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: isDeal ? TERRA : INK3 }}>
          {isDeal ? "Deal card" : "Geocoder"}
        </span>
      </div>
    );
  };

  const showList = q.trim().length >= 3 && (rows.length > 0 || !looking);

  return (
    <div style={{ padding: isMobile ? "28px 14px 32px" : "44px 20px 40px", maxWidth: 620, margin: "0 auto" }}>
      <h3 style={{ margin: "0 0 14px", fontSize: 19, fontWeight: 700, color: NAVY }}>What's the address?</h3>

      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKey}
        placeholder="Start typing a street address"
        aria-label="Property address"
        style={{
          width: "100%", boxSizing: "border-box", background: "#fff",
          border: `1.5px solid ${BLUE}`, borderRadius: 11, padding: "13px 15px",
          fontSize: 17, fontWeight: 600, color: INK, outline: "none",
          boxShadow: "0 0 0 3px rgba(94,138,208,.16)",
        }}
      />

      {showList && (
        <div role="listbox" style={{ background: "#fff", border: `1px solid ${LINE}`, borderRadius: 11, marginTop: 7, overflow: "hidden", boxShadow: "0 6px 20px rgba(24,40,72,.12)" }}>
          {deals.length > 0 && group("Your deals")}
          {deals.map((_, i) => rowEl(rows[i], i))}
          {geocoded.length > 0 && group("BC address lookup")}
          {geocoded.map((_, i) => rowEl(rows[deals.length + i], deals.length + i))}
          {rows.length === 0 && (
            <div style={{ padding: "12px 14px", fontSize: 13, color: INK3 }}>
              {/* An unreachable geocoder is NOT the same as an unknown address, and
                  saying "no match" when the lookup never ran would be a lie. */}
              {geocoderOk
                ? "No match yet. Keep typing, or add the number and street."
                : "The BC address lookup is not reachable right now. You can still type the full address and carry on."}
            </div>
          )}
        </div>
      )}

      {!geocoderOk && rows.length > 0 && (
        <div style={{ marginTop: 8, padding: "8px 12px", background: WARNBG, color: WARN, borderRadius: 8, fontSize: 12 }}>
          BC address lookup is unreachable, so only your own deals are listed.
        </div>
      )}

      <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, color: INK3 }}>Seller</span>
        <input
          value={seller}
          onChange={(e) => setSeller(e.target.value)}
          placeholder="Optional"
          aria-label="Seller name (optional)"
          style={{ border: "1px solid #C9D1DE", background: "#fff", borderRadius: 7, padding: "5px 9px", fontSize: 13, fontWeight: 600, color: INK, minWidth: 160, outline: "none" }}
        />
      </div>

      {err && <div style={{ marginTop: 14, color: "#8B1A1A", fontSize: 13 }}>{err}</div>}

      <div style={{ marginTop: 22, fontSize: 12, color: INK3 }}>
        {creating ? "Starting the evaluation..."
          : looking ? "Looking..."
          : rows.length ? "Press Enter to start, or arrow keys to pick a different one."
          : "Press Enter to start."}
      </div>
    </div>
  );
}
