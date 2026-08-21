// Positioned — mockup screen 8, on the Pricing step.
//
// The question this answers is "where does her home sit", and position is a
// relationship, not three groups. So it is one ladder ordered by price with the
// subject placed INTO it, rather than a Better card stack above a Comparable
// card stack above a Worse one. You read the answer by finding the highlighted
// row and seeing what is above and below it.
//
// Tapping a comp reveals why it sits there. That sentence is the pricing
// engine's own, and the seller's PDF prints the same one, so what she reads here
// is what the seller reads.
//
// The expired band is deliberately last and visually quieter: those homes are
// ceiling evidence, never comps, and repeat attempts are the argument.
import { useState } from "react";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", INK2 = "#4A5468", MUTED = "#6B7488", LINE = "#e3e7ef",
      TERRA = "#C46340", TERRA_TINT = "#FDF3E4", GREEN = "#2f7a4d", BLUE = "#5E8AD0";

export type TierComp = {
  address: string; mls?: string | null; price?: string | number | null;
  beds?: string | number | null; baths?: string | number | null;
  sqft?: number | null; lotSqft?: number | null; dom?: number | null;
  soldDate?: string | null; narrative?: string | null; classification?: string | null;
};
export type Freshness = {
  tierComps?: number; currentComps?: number; matched?: number;
  stale?: boolean; partial?: boolean;
};
export type ExpiredBand = {
  available?: boolean; addressCount?: number; repeatCount?: number;
  monthsBack?: number | null;
  top?: { address: string; attempts: number; listings?: { listPrice?: string | null }[] }[];
};

const toNum = (v: unknown) => {
  const n = Number(String(v ?? "").replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : 0;
};
const money = (n: number) => "$" + Math.round(n).toLocaleString("en-CA");

type Band = "over" | "with" | "under";
const BAND: Record<Band, { label: string; ink: string; tint: string }> = {
  // Named from the SUBJECT's point of view, which is the question being asked.
  over:  { label: "Sold above yours", ink: GREEN, tint: "#EAF4EA" },
  with:  { label: "Sold with yours",  ink: BLUE,  tint: "#EAF0F9" },
  under: { label: "Sold under yours", ink: MUTED, tint: "#EFF1F5" },
};

export default function CmaPositioned({
  recommended,
  range,
  better,
  comparable,
  worse,
  expired,
  freshness,
}: {
  recommended?: string | null;
  range?: string | null;
  better?: TierComp[];
  comparable?: TierComp[];
  worse?: TierComp[];
  expired?: ExpiredBand | null;
  freshness?: Freshness | null;
}) {
  const isMobile = useIsMobile();
  const [open, setOpen] = useState<string | null>(null);
  const [showExpired, setShowExpired] = useState(false);

  const rows = [
    ...(better || []).map((c) => ({ c, band: "over" as Band })),
    ...(comparable || []).map((c) => ({ c, band: "with" as Band })),
    ...(worse || []).map((c) => ({ c, band: "under" as Band })),
  ]
    .filter((r) => r.c && r.c.address)
    .sort((a, b) => toNum(b.c.price) - toNum(a.c.price));

  if (!rows.length) return null;

  // REFUSE to draw a confident ladder from a comp set that no longer exists.
  // A re-pull resets the pricing phase but leaves the old sandwich file on disk,
  // so this view would otherwise rank her home against comps she has replaced.
  if (freshness?.stale) {
    return (
      <section style={{ marginTop: 12 }}>
        <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY }}>
          Where your home sits
        </h3>
        <div style={{ marginTop: 8, padding: "12px 13px", background: TERRA_TINT, border: "1px solid #EBD2A8", borderRadius: 12, fontSize: 14, lineHeight: 1.55, color: "#7A3E1D", maxWidth: "68ch" }}>
          This pricing was worked out from a different set of comps than the ones
          you have now, so the ranking below would be wrong. Run the pricing step
          again to rebuild it against your current {freshness.currentComps || ""} comps.
        </div>
      </section>
    );
  }

  const rec = toNum(recommended);
  // Where the subject sits in the ladder: above every comp it out-prices.
  const subjectAt = rec ? rows.findIndex((r) => toNum(r.c.price) < rec) : -1;
  const subjectIdx = rec ? (subjectAt === -1 ? rows.length : subjectAt) : -1;

  const spec = (c: TierComp) => [
    c.beds != null && c.baths != null ? `${c.beds} bed, ${c.baths} bath` : null,
    c.sqft ? `${c.sqft.toLocaleString("en-CA")} sqft` : null,
    c.lotSqft ? `${c.lotSqft.toLocaleString("en-CA")} sqft lot` : null,
    c.dom ? `${c.dom} days on market` : null,
  ].filter(Boolean).join(" · ");

  const compRow = (c: TierComp, band: Band, i: number) => {
    const id = String(c.mls || c.address || i);
    const isOpen = open === id;
    const b = BAND[band];
    const detail = spec(c);
    return (
      <div key={id} style={{ borderTop: `1px solid ${LINE}` }}>
        <button
          type="button"
          onClick={() => setOpen(isOpen ? null : id)}
          aria-expanded={isOpen}
          style={{
            width: "100%", textAlign: "left", background: "transparent", border: "none",
            // 44pt minimum touch target.
            minHeight: 44, padding: isMobile ? "11px 12px" : "10px 14px",
            display: "flex", alignItems: "center", gap: 12, cursor: c.narrative ? "pointer" : "default",
            font: "inherit",
          }}
        >
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontSize: isMobile ? 15 : 14, fontWeight: 600, color: NAVY, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {c.address}
            </span>
            <span style={{ display: "block", fontSize: 13, color: MUTED, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {detail || (c.soldDate ? `Sold ${c.soldDate}` : "")}
            </span>
          </span>
          <span style={{ flexShrink: 0, textAlign: "right" }}>
            <span style={{ display: "block", fontSize: isMobile ? 15 : 14, fontWeight: 700, color: NAVY, fontVariantNumeric: "tabular-nums" }}>
              {money(toNum(c.price))}
            </span>
            <span style={{ display: "block", fontSize: 12, fontWeight: 600, color: b.ink, marginTop: 2 }}>
              {isMobile ? b.label.replace("Sold ", "") : b.label}
            </span>
          </span>
        </button>
        {isOpen && c.narrative && (
          <p style={{
            margin: 0, padding: isMobile ? "0 12px 13px" : "0 14px 13px",
            fontSize: 14, lineHeight: 1.55, color: INK2, maxWidth: "68ch",
          }}>
            {c.narrative}
          </p>
        )}
      </div>
    );
  };

  const subjectRow = (
    <div
      key="subject"
      style={{
        borderTop: `1px solid ${TERRA}`, borderBottom: `1px solid ${TERRA}`,
        background: TERRA_TINT, minHeight: 44,
        padding: isMobile ? "12px" : "12px 14px",
        display: "flex", alignItems: "center", gap: 12,
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontSize: isMobile ? 16 : 15, fontWeight: 800, color: "#7A3E1D" }}>
          Your home
        </span>
        {range && (
          <span style={{ display: "block", fontSize: 13, color: "#8A5A38", marginTop: 2 }}>
            {range}
          </span>
        )}
      </span>
      <span style={{ flexShrink: 0, fontSize: isMobile ? 17 : 16, fontWeight: 800, color: "#7A3E1D", fontVariantNumeric: "tabular-nums" }}>
        {recommended || ""}
      </span>
    </div>
  );

  const ladder: React.ReactNode[] = [];
  rows.forEach((r, i) => {
    if (i === subjectIdx) ladder.push(subjectRow);
    ladder.push(compRow(r.c, r.band, i));
  });
  if (subjectIdx === rows.length) ladder.push(subjectRow);

  const exp = expired || {};
  const repeats = (exp.top || []).filter((g) => (g.attempts || 0) > 1);

  return (
    <section style={{ marginTop: 12 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
        Where your home sits
        <CmaInfo label="About this ranking">
          Every comp by what it sold for, with your home placed in. Tap one for why.
        </CmaInfo>
      </h3>

      {freshness?.partial && (
        <div style={{ margin: "0 0 10px", padding: "10px 12px", background: TERRA_TINT, border: "1px solid #EBD2A8", borderRadius: 10, fontSize: 13.5, lineHeight: 1.5, color: "#7A3E1D", maxWidth: "68ch" }}>
          Only {freshness.matched} of these {freshness.tierComps} were in your latest pull.
          Run the pricing step again to rebuild it against the current set.
        </div>
      )}

      <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
        {ladder}
      </div>

      {exp.available && (exp.addressCount || 0) > 0 && (
        <div style={{ marginTop: 14 }}>
          <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY }}>
            Tried and did not sell
          </h3>
          <p style={{ margin: "0 0 10px", fontSize: 14, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
            {exp.addressCount} nearby {exp.addressCount === 1 ? "home" : "homes"} came off the market without selling
            {exp.monthsBack ? ` in the last ${exp.monthsBack} months` : ""}
            {repeats.length ? `, and ${repeats.length} of them tried more than once.` : "."}
            {" "}They set the ceiling. They are never counted as comps.
          </p>
          {!!repeats.length && (
            <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
              {(showExpired ? repeats : repeats.slice(0, 3)).map((g, i) => (
                <div key={g.address} style={{
                  borderTop: i ? `1px solid ${LINE}` : "none", minHeight: 44,
                  padding: isMobile ? "11px 12px" : "10px 14px",
                  display: "flex", alignItems: "center", gap: 12,
                }}>
                  <span style={{ flex: 1, minWidth: 0, fontSize: isMobile ? 15 : 14, fontWeight: 600, color: NAVY, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {g.address}
                  </span>
                  <span style={{ flexShrink: 0, fontSize: 13, fontWeight: 700, color: TERRA }}>
                    tried {g.attempts} times
                  </span>
                </div>
              ))}
              {repeats.length > 3 && !showExpired && (
                <button type="button" onClick={() => setShowExpired(true)}
                  style={{ width: "100%", minHeight: 44, border: "none", borderTop: `1px solid ${LINE}`, background: "transparent", font: "inherit", fontSize: 14, fontWeight: 600, color: BLUE, cursor: "pointer" }}>
                  Show all {repeats.length}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
