// Buyer demand per price bracket — mockup screen 9, "Buyers searching at each price".
//
// This is the number Skyleigh actually shows a seller: how many buyers with a
// saved search would NEWLY match the home at each price. The Xposure capture has
// been writing prospecting-brackets.json the whole time and nothing served it.
//
// Form: single-series magnitude across an ordered (descending) price scale, so a
// horizontal bar list, values direct-labelled. One series means no legend box —
// the heading names it. The cliff is an ANNOTATION, not a second series, so the
// bars stay one hue and only the callout carries the accent.
//
// Palette validated with the dataviz validator against a light surface:
// #5E8AD0 + #C46340 pass lightness band, chroma floor, CVD separation
// (worst adjacent dE 21.0 protan), normal-vision floor (dE 23.7) and contrast.
import { useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", INK3 = "#6B7488", LINE2 = "#EAEEF4",
      BLUE = "#5E8AD0", TERRA = "#C46340", TERRABG = "#FDF3E4";

type Bracket = { price: number; newSearches: number };
type Cliff = { price: number; gain: number; costFromPrice: number; costDollars: number };

const money = (n: number | null | undefined) =>
  n == null ? "" : "$" + Math.round(n).toLocaleString("en-CA");

export default function CmaBuyerDemand({ dealId }: { dealId: string }) {
  const isMobile = useIsMobile();
  const [rows, setRows] = useState<Bracket[]>([]);
  const [cliff, setCliff] = useState<Cliff | null>(null);
  const [base, setBase] = useState(0);
  const [meta, setMeta] = useState<{ anchorMls?: string | null; anchorAddress?: string | null; capturedAt?: string | null }>({});
  const [state, setState] = useState<"loading" | "none" | "ready">("loading");
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    api.getCmaProspecting(dealId)
      .then((r) => {
        if (!live) return;
        if (!r.available || !(r.brackets || []).length) { setState("none"); return; }
        setRows(r.brackets); setCliff(r.cliff || null);
        // The buyers already matching at the anchor price. Every bracket's
        // `newSearches` is the number ADDED on top of this, so a bar drawn from
        // newSearches alone shows a fraction of the real audience.
        setBase(Number(r.currentMatched || 0));
        setMeta({ anchorMls: r.anchorMls, anchorAddress: r.anchorAddress, capturedAt: r.capturedAt });
        setState("ready");
      })
      .catch(() => { if (live) setState("none"); });
    return () => { live = false; };
  }, [dealId]);

  // Nothing captured yet is a normal state, not an error. Say so plainly and
  // take up almost no room, rather than rendering an empty chart frame.
  if (state === "none") {
    return (
      <div style={{ fontSize: 12, color: INK3, marginTop: 10 }}>
No buyer-demand capture yet.
      </div>
    );
  }
  if (state === "loading") {
    return <div style={{ fontSize: 12, color: INK3, marginTop: 10 }}>Loading buyer demand...</div>;
  }

  // Bars are the TOTAL audience at each price, not the increment. Showing only
  // the increment said "284 buyers" at $339,900 when 2,776 would actually be
  // searching, because it silently dropped the pool that already matched.
  const total = (r: Bracket) => base + (r.newSearches || 0);
  const max = Math.max(...rows.map(total), 1);
  const captured = meta.capturedAt
    ? new Date(meta.capturedAt).toLocaleString("en-CA", { hour: "numeric", minute: "2-digit", month: "short", day: "numeric" })
    : null;

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <h4 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
          Buyers at each price
          <CmaInfo label="About buyer demand">
            Buyers with a saved search that would newly match at that price.
          </CmaInfo>
        </h4>
        {meta.anchorMls && (
          <span style={{ fontSize: 11.5, color: INK3 }}>
            Run against MLS {meta.anchorMls}
            {meta.anchorAddress ? ` · ${meta.anchorAddress}` : ""}
            {captured ? ` · pulled ${captured}` : ""}
          </span>
        )}
      </div>

      <div style={{ marginTop: 10 }} role="table" aria-label="Buyers newly matching at each price">
        {rows.map((r, i) => {
          const isCliff = cliff && r.price === cliff.price;
          const pct = (total(r) / max) * 100;
          const on = hover === i;
          return (
            <div key={r.price}>
              {/* The cliff is the argument, so it gets a band above the row it
                  belongs to rather than a differently coloured bar (which would
                  read as a second series). */}
              {isCliff && cliff && (
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, margin: "8px 0 5px",
                  padding: "5px 9px", background: TERRABG, border: `1px solid #EBD2A8`,
                  borderRadius: 8, fontSize: 11.5, fontWeight: 700, color: TERRA,
                }}>
                  Crossing under {money(cliff.costFromPrice)} adds {cliff.gain.toLocaleString("en-CA")} buyers
                  <span style={{ fontWeight: 500, color: INK3 }}>
                    for {money(cliff.costDollars)}
                  </span>
                </div>
              )}
              <div
                role="row"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                title={`${money(r.price)}: ${total(r).toLocaleString("en-CA")} buyers searching${r.newSearches ? `, ${r.newSearches.toLocaleString("en-CA")} of them added by this price` : ""}`}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  // 2px surface gap between adjacent bars.
                  padding: "1px 0", marginBottom: 2, cursor: "default",
                  background: on ? "#F3F7FF" : "transparent", borderRadius: 3,
                }}
              >
                <span style={{ width: isMobile ? 62 : 74, flexShrink: 0, textAlign: "right", fontSize: isMobile ? 11.5 : 12, color: isCliff ? NAVY : INK3, fontWeight: isCliff ? 700 : 500 }}>
                  {money(r.price)}
                </span>
                <span style={{ flex: 1, minWidth: 0, height: 14, background: LINE2, borderRadius: 3, overflow: "hidden" }}>
                  <span style={{
                    display: "block", height: "100%", width: `${Math.max(pct, total(r) > 0 ? 1.5 : 0)}%`,
                    background: BLUE,
                    // 4px rounded data-end, anchored square to the baseline.
                    borderRadius: "0 4px 4px 0",
                    // Deliberately NO width transition. The width is set once from
                    // the loaded brackets and never changes (hover only tints the
                    // row), so an animation here would never play, and animating
                    // width is a layout-thrash pattern regardless.
                  }} />
                </span>
                <span style={{ width: isMobile ? 62 : 76, flexShrink: 0, textAlign: "right" }}>
                  <span style={{ fontSize: isMobile ? 11.5 : 12, fontWeight: 700, color: NAVY, fontVariantNumeric: "tabular-nums" }}>
                    {total(r).toLocaleString("en-CA")}
                  </span>
                  {!!r.newSearches && (
                    <span style={{ display: "block", fontSize: 10, color: INK3, fontVariantNumeric: "tabular-nums" }}>
                      +{r.newSearches.toLocaleString("en-CA")}
                    </span>
                  )}
                </span>
              </div>
            </div>
          );
        })}
      </div>


    </div>
  );
}
