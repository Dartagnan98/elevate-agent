// Address input with BC lookup, for correcting the address on an evaluation
// that already exists.
//
// The board's "New evaluation" front door (cma-address-intake.tsx) does the same
// lookup but its job is to CREATE or OPEN a deal. Here the property is already
// decided and we are only fixing what it is called, so the two differ in one
// important way: a match against another deal is NOT something to pick, it is a
// warning. Silently pointing this deal at an address that already has its own
// evaluation is how you end up with two cards fighting over one property.
//
// Mobile: single column, wrapping button row, suggestions capped in height.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";

const NAVY = "#182848", INK3 = "#6B7488", LINE = "#DDE2EA", LINE2 = "#EAEEF4",
      WARN = "#B26B12", WARNBG = "#FDF3E4";

type Geo = { address: string; locality?: string | null };

export default function CmaAddressField({
  dealId,
  initial,
  busy,
  onSave,
  onCancel,
}: {
  dealId: string;
  initial: string;
  busy: boolean;
  onSave: (address: string) => void | Promise<void>;
  onCancel: () => void;
}) {
  const isMobile = useIsMobile();
  const [q, setQ] = useState(initial || "");
  const [geo, setGeo] = useState<Geo[]>([]);
  const [clash, setClash] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const [open, setOpen] = useState(false);
  const seqRef = useRef(0);
  // Suppresses the lookup for one cycle after a pick, so choosing a suggestion
  // doesn't immediately reopen the list with that same address.
  const skipRef = useRef(false);

  useEffect(() => {
    const term = q.trim();
    if (skipRef.current) { skipRef.current = false; return; }
    if (term.length < 3) { setGeo([]); setClash([]); setOpen(false); return; }
    const mine = ++seqRef.current;
    const t = setTimeout(() => {
      api.getCmaAddressSuggest(term)
        .then((r) => {
          if (mine !== seqRef.current) return;
          setGeo((r.geocoded || []).slice(0, 5));
          // Only OTHER deals are a clash. This deal matching itself is expected.
          setClash((r.deals || []).filter((d) => d.dealId !== dealId).map((d) => d.address));
          setCursor(-1);
          setOpen(true);
        })
        .catch(() => { if (mine === seqRef.current) { setGeo([]); setClash([]); } });
    }, 300);
    return () => clearTimeout(t);
  }, [q, dealId]);

  const pick = useCallback((address: string) => {
    skipRef.current = true;
    setQ(address); setOpen(false); setCursor(-1);
  }, []);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { if (open) { setOpen(false); } else { onCancel(); } return; }
    if (e.key === "Enter") {
      e.preventDefault();
      if (open && cursor >= 0 && geo[cursor]) pick(geo[cursor].address);
      else if (q.trim()) void onSave(q.trim());
      return;
    }
    if (!open || !geo.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(geo.length - 1, c + 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(-1, c - 1)); }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          value={q}
          autoFocus
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="2520 Young Ave"
          aria-label="Property address"
          style={{
            flex: 1, minWidth: isMobile ? "100%" : 180, border: `1px solid #dde3ee`,
            borderRadius: 8, padding: "9px 11px", fontSize: 14, fontWeight: 600,
            color: NAVY, fontFamily: "inherit", boxSizing: "border-box",
          }}
        />
        <button
          onClick={() => q.trim() && void onSave(q.trim())}
          disabled={!q.trim() || busy}
          style={{
            background: (!q.trim() || busy) ? "#d7dce6" : NAVY,
            color: (!q.trim() || busy) ? "#8a93a6" : "#fff",
            border: "none", borderRadius: 8, padding: "9px 16px",
            fontSize: 13, fontWeight: 700, cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onCancel}
          style={{ background: "#fff", border: `1px solid ${LINE}`, borderRadius: 8, padding: "9px 13px", fontSize: 13, fontWeight: 600, color: INK3, cursor: "pointer" }}
        >
          Cancel
        </button>
      </div>

      {open && geo.length > 0 && (
        <div role="listbox" style={{ marginTop: 6, border: `1px solid ${LINE}`, borderRadius: 9, overflow: "hidden", background: "#fff", maxHeight: 210, overflowY: "auto" }}>
          <div style={{ padding: "5px 11px", background: "#F7F9FC", fontSize: 10, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", color: INK3, borderBottom: `1px solid ${LINE2}` }}>
            BC address lookup
          </div>
          {geo.map((g, i) => (
            <div
              key={g.address}
              role="option"
              aria-selected={i === cursor}
              onMouseEnter={() => setCursor(i)}
              onClick={() => pick(g.address)}
              style={{
                display: "flex", alignItems: "baseline", gap: 8, padding: "9px 11px",
                borderBottom: `1px solid ${LINE2}`, fontSize: 13, cursor: "pointer",
                background: i === cursor ? "#F3F7FF" : "transparent",
              }}
            >
              <span style={{ flex: 1, fontWeight: 700, color: NAVY, minWidth: 0 }}>{g.address}</span>
              {g.locality && !isMobile && <span style={{ fontSize: 11.5, color: INK3 }}>{g.locality}</span>}
            </div>
          ))}
        </div>
      )}

      {clash.length > 0 && (
        <div style={{ marginTop: 7, padding: "7px 10px", background: WARNBG, border: "1px solid #EBD2A8", borderRadius: 8, fontSize: 12, color: WARN, lineHeight: 1.45 }}>
          {clash[0]} already has its own evaluation on the board. Pointing this one at the same address leaves you with two.
        </div>
      )}
    </div>
  );
}
