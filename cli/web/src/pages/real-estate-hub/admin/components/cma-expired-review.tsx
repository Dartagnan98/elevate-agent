// "What was tried and didn't sell" -- choosing which ones the seller sees.
//
// Skyleigh 2026-09-06: "on the tried but didn't sell section and the expired for
// the comparables. I'm not able to select which ones I want included. There are
// actually a number of them that are outside the range for the pricing so it
// doesn't make sense to include them, but I can't seem to delete them."
//
// She was right: sold and active comps have had a set-aside since the review
// screen was built, and the expired band never got one. Every address the search
// returned went into the report. On 426 Gleneagles that put a home asking up to
// $1,388,000 in front of a seller whose bracket is $865,000 to $915,000.
//
// Two things this screen refuses to do:
//   1. It never hides a row. Everything the pull found is listed, in price order,
//      with her choice on each.
//   2. It never drops a row for her. "Outside your bracket" is printed as a note,
//      not acted on. The tool overruling her curation is a mistake this codebase
//      has already made once, on a comp she had explicitly ticked.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import type { CmaExpiredRow } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", TERRA = "#C46340";

const money = (n?: number | null) =>
  n ? "$" + Math.round(n).toLocaleString("en-US") : "n/a";

export default function CmaExpiredReview({ dealId }: { dealId: string }) {
  const isMobile = useIsMobile();
  const [rows, setRows] = useState<CmaExpiredRow[]>([]);
  const [cap, setCap] = useState(6);
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(() => {
    api.getCmaExpiredSelect(dealId)
      .then((r) => {
        if (!r?.ok) return;
        setAvailable(!!r.available);
        setRows(r.expired || []);
        setCap(r.shownCap || 6);
      })
      .catch(() => { /* the step still works without it */ });
  }, [dealId]);
  useEffect(() => { load(); }, [load]);

  const toggle = async (row: CmaExpiredRow) => {
    setBusy(row.key); setErr("");
    // Optimistic on the row she tapped, but inReport comes back from the server:
    // excluding one promotes another into the six, and guessing which would put a
    // wrong "in the report" badge on screen.
    setRows((xs) => xs.map((x) => (x.key === row.key ? { ...x, excluded: !x.excluded } : x)));
    try {
      const r = await api.toggleCmaExpired(dealId, row.key);
      if (r?.ok && r.expired) { setRows(r.expired); setCap(r.shownCap || 6); }
      else { setErr("That did not save."); load(); }
    } catch {
      setErr("That did not save."); load();
    } finally { setBusy(null); }
  };

  // NEVER RETURN NULL SILENTLY. An absent control and a broken one look identical
  // on screen, which is how this whole feature read as "still not letting me
  // select" when it was in fact mounted on a step she was not on. If there is
  // nothing to curate, say so.
  if (!available || !rows.length) {
    return (
      <div style={{ marginTop: 22 }}>
        <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY }}>
          What was tried and didn't sell
        </h3>
        <p style={{ margin: 0, fontSize: 13.5, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
          {err || "No expired listings have been pulled for this property yet, so there is nothing to choose from. This fills in when the comps are pulled."}
        </p>
      </div>
    );
  }

  const inCount = rows.filter((r) => r.inReport).length;
  const keptCount = rows.filter((r) => !r.excluded).length;
  const visible = showAll ? rows : rows.slice(0, 8);

  return (
    <div style={{ marginTop: 22 }}>
      <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
        What was tried and didn't sell
        <CmaInfo label="About the expired band">
          Homes near you that went to market and came off without selling. They never
          set your price, the solds do that. They show the asking prices buyers walked
          away from. Untick anything that does not belong in front of this seller.
        </CmaInfo>
      </h3>
      <p style={{ margin: "0 0 10px", fontSize: 13.5, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
        {rows.length} found, {keptCount} kept, and the report shows the first {cap} of those.
        {inCount < keptCount ? ` ${keptCount - inCount} more are kept but sit past the ${cap} the report has room for.` : ""}
      </p>

      <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
        {visible.map((r, i) => (
          <button key={r.key} type="button" onClick={() => void toggle(r)} disabled={busy === r.key}
            aria-pressed={!r.excluded}
            style={{
              width: "100%", textAlign: "left", font: "inherit", background: "transparent",
              border: "none", borderTop: i ? `1px solid ${LINE}` : "none", minHeight: 44,
              padding: isMobile ? "11px 12px" : "10px 14px", display: "flex", alignItems: "center",
              gap: 12, cursor: "pointer", opacity: busy === r.key ? 0.6 : 1,
            }}>
            <span aria-hidden style={{
              flexShrink: 0, width: 22, height: 22, borderRadius: 6,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: r.excluded ? "#fff" : "#EAF4EA",
              border: `1.5px solid ${r.excluded ? "#C9D1DE" : "#A9CDAB"}`,
              color: r.excluded ? "transparent" : GREEN, fontSize: 13, fontWeight: 800, lineHeight: 1,
            }}>✓</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: "block", fontSize: isMobile ? 15 : 14, fontWeight: 600, color: r.excluded ? MUTED : NAVY }}>
                {r.address}
              </span>
              <span style={{ display: "block", fontSize: 12.5, color: MUTED, marginTop: 2, lineHeight: 1.45 }}>
                asked up to {money(r.topAsk)}
                {r.attempts > 1 ? ` · ${r.attempts} attempts` : ""}
                {r.minorArea ? ` · ${r.minorArea}` : ""}
                {r.outsideBracket ? (
                  <span style={{ color: TERRA, fontWeight: 700 }}> · {r.outsideBracket}</span>
                ) : null}
              </span>
            </span>
            {r.inReport && !r.excluded && (
              <span style={{ flexShrink: 0, fontSize: 11, fontWeight: 800, color: GREEN,
                             background: "#EAF4EA", borderRadius: 10, padding: "3px 9px" }}>
                In the report
              </span>
            )}
          </button>
        ))}
      </div>

      {rows.length > 8 && (
        <button type="button" onClick={() => setShowAll((v) => !v)}
          style={{ marginTop: 9, minHeight: 44, font: "inherit", fontSize: 13, fontWeight: 700,
                   color: "#5E8AD0", background: "none", border: "none", cursor: "pointer", padding: "10px 2px" }}>
          {showAll ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
      {err && <div style={{ fontSize: 13, color: "#8B1A1A", marginTop: 8 }}>{err}</div>}
    </div>
  );
}
