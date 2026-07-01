// "Insert Clauses" popup — browse the full clause library by folder
// (Personal / Office / System) with search + a basket, modelled on WEBForms.
// System = the curated/BCREA-scraped library; Office = brokerage; Personal =
// the agent's saved clauses. OK inserts the basket into the deal's selection.
import { useMemo, useState } from "react";

const BLUE = "#5E8AD0";
const INK = "#182848";
const MUTED = "#6b7280";
const BORDER = "#e3e6eb";

type Clause = { id: string; title?: string; primary_wording?: string; wording?: string; category?: string };

export default function ClausePickerModal({
  open,
  onClose,
  onInsert,
  folders,
  preselected,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (clauses: Clause[]) => void;
  folders: { key: string; label: string; clauses: Clause[] }[];
  preselected?: Set<string>;
}) {
  const [search, setSearch] = useState("");
  const [openFolder, setOpenFolder] = useState<string | null>("system");
  const [basket, setBasket] = useState<Set<string>>(() => new Set(preselected || []));
  const [showBasket, setShowBasket] = useState(false);

  const allById = useMemo(() => {
    const m: Record<string, Clause> = {};
    for (const f of folders) for (const c of f.clauses) m[c.id] = c;
    return m;
  }, [folders]);

  if (!open) return null;

  const q = search.trim().toLowerCase();
  const match = (c: Clause) =>
    !q || (c.title || "").toLowerCase().includes(q) || (c.primary_wording || c.wording || "").toLowerCase().includes(q);
  const toggle = (id: string) =>
    setBasket((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const wording = (c: Clause) => c.primary_wording || c.wording || "";

  const clauseRow = (c: Clause) => {
    const on = basket.has(c.id);
    return (
      <div key={c.id} onClick={() => toggle(c.id)} style={{ display: "flex", gap: 11, padding: "10px 0 10px 30px", borderTop: `1px solid #f0f1f4`, cursor: "pointer" }}>
        <div style={{ width: 20, height: 20, borderRadius: 5, flexShrink: 0, marginTop: 1, background: on ? BLUE : "#fff", border: `1px solid ${on ? BLUE : "#c9ced6"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 12 }}>{on ? "✓" : ""}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, color: INK, fontSize: 13.5 }}>{c.title || "Clause"}</div>
          <div style={{ fontSize: 12.5, color: MUTED, marginTop: 1 }}>{wording(c).slice(0, 110)}{wording(c).length > 110 ? "…" : ""}</div>
        </div>
      </div>
    );
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "#0008", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", borderRadius: 12, width: "min(820px, 100%)", maxHeight: "88vh", display: "flex", flexDirection: "column", boxShadow: "0 20px 60px #0006" }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 18px", borderBottom: `1px solid ${BORDER}` }}>
          <button type="button" onClick={onClose} style={{ background: "#c0392b", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontWeight: 700, fontSize: 15, cursor: "pointer" }}>Close</button>
          <div style={{ fontWeight: 700, fontSize: 18, color: INK }}>Insert Clauses</div>
          <button type="button" onClick={() => { onInsert(Array.from(basket).map((id) => allById[id]).filter(Boolean)); onClose(); }} style={{ background: BLUE, color: "#fff", border: "none", borderRadius: 8, padding: "9px 22px", fontWeight: 700, fontSize: 15, cursor: "pointer" }}>OK</button>
        </div>
        {/* search + basket */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", borderBottom: `1px solid ${BORDER}`, justifyContent: "flex-end" }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search" style={{ width: 320, fontSize: 15, padding: "9px 13px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK }} />
          <button type="button" onClick={() => setShowBasket((s) => !s)} title="Selected clauses" style={{ background: "none", border: "none", cursor: "pointer", position: "relative", fontSize: 24 }}>
            🧺
            {basket.size > 0 && <span style={{ position: "absolute", top: -4, right: -6, background: BLUE, color: "#fff", fontSize: 11, fontWeight: 700, borderRadius: 999, minWidth: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 4px" }}>{basket.size}</span>}
          </button>
        </div>
        {/* body */}
        <div style={{ overflowY: "auto", padding: "6px 18px 18px" }}>
          {showBasket ? (
            <div>
              <div style={{ fontWeight: 700, color: INK, fontSize: 14, margin: "12px 0 6px" }}>Selected ({basket.size})</div>
              {basket.size === 0 && <div style={{ color: MUTED, fontSize: 13, padding: "8px 0" }}>Nothing selected yet — tick clauses from the folders.</div>}
              {Array.from(basket).map((id) => allById[id]).filter(Boolean).map(clauseRow)}
            </div>
          ) : (
            folders.map((f) => {
              const items = f.clauses.filter(match);
              const expanded = openFolder === f.key || !!q;
              return (
                <div key={f.key} style={{ borderBottom: `1px solid ${BORDER}` }}>
                  <button type="button" onClick={() => setOpenFolder(openFolder === f.key ? null : f.key)} style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", background: "none", border: "none", padding: "16px 0", cursor: "pointer", textAlign: "left" }}>
                    <span style={{ fontSize: 22, color: BLUE }}>{expanded ? "📂" : "📁"}</span>
                    <span style={{ fontSize: 17, color: BLUE, fontWeight: 500 }}>{f.label}</span>
                    <span style={{ fontSize: 13, color: MUTED, marginLeft: 4 }}>({f.clauses.length})</span>
                  </button>
                  {expanded && (
                    <div style={{ paddingBottom: 8 }}>
                      {items.length === 0 ? <div style={{ color: MUTED, fontSize: 13, padding: "4px 0 10px 30px" }}>No clauses{q ? " match the search" : " yet"}.</div> : items.map(clauseRow)}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
