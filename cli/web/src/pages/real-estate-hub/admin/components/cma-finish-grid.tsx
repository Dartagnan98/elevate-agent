// The finish flip-table, on the Comparables step.
//
// Skyleigh 2026-08-30: "On the report section at the end I have a spot that says
// if certain finishings are better in the comparable house or the subject house.
// We should add that to the comparable section on the CMA wizard so that it goes
// directly from the wizard to the report."
//
// It already existed as a CLI gate that PRINTED a table and asked her to reply in
// prose ("comp 2 kitchen on par"). This is the same table, tappable, saving as she
// goes.
//
// Two rules this component exists to honour:
//
//  1. A flip is a PRESENTATION overlay. It never moves the underlying finish
//     score, because that score also feeds the pricing adjustment -- the old
//     --apply path expressed a flip by shoving the comp's score +/-2 and silently
//     changed a pricing input as a side effect of an editorial call.
//  2. Her call is stored in its own file, so re-running normalize cannot wipe it.
//     Anything written into sandwich-comparison.json is regenerated away.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", TERRA = "#C46340";

type Cell = {
  key: string; label: string;
  auto: string | null; override: string | null; value: string | null; edited: boolean;
};
type Row = { compNum: number; mls: string; address: string; suite?: string | null; cells: Cell[] };

// Tapping cycles through her three answers and back to the computed one. "Auto"
// has to stay reachable or there is no way to undo a mistap.
const CYCLE = ["your home", "on par", "this comp", ""] as const;
const SHORT: Record<string, string> = {
  "your home": "Yours", "on par": "On par", "this comp": "This comp",
};

export default function CmaFinishGrid({ dealId }: { dealId: string }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    api.cmaFinishGrid(dealId)
      .then((r) => { setRows(r?.rows || []); setLoaded(true); })
      .catch(() => { setRows([]); setLoaded(true); });
  }, [dealId]);
  useEffect(() => { load(); }, [load]);

  // Nothing to show until the photos have been scored. Rendering an empty grid
  // would read as "no differences found", which is a claim we have not earned.
  // But returning null MID-RESCORE made the whole table vanish from under her,
  // which reads as lost work. Say which it is.
  if (!loaded) return null;
  if (!rows.length) {
    return (
      <div style={{ borderTop: `1px solid ${LINE}`, padding: "12px 13px", background: "#fff",
                    fontSize: 12, color: MUTED }}>
        <div style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
          How the finishes compare
        </div>
        The finish comparison appears once the photos have been scored. Your comps,
        your exclusions and your notes are all saved and unaffected.
      </div>
    );
  }

  const flip = async (row: Row, cell: Cell) => {
    const at = CYCLE.indexOf((cell.override || "") as typeof CYCLE[number]);
    const next = CYCLE[(at + 1) % CYCLE.length];
    const id = `${row.mls}:${cell.key}`;
    setBusy(id); setErr("");
    // Optimistic, so the cell does not lag a tap.
    setRows((xs) => xs.map((r) => r.mls !== row.mls ? r : {
      ...r,
      cells: r.cells.map((c) => c.key !== cell.key ? c : {
        ...c, override: next || null, value: next || c.auto, edited: !!next && next !== c.auto,
      }),
    }));
    try {
      const res = await api.cmaSetFinishFlip(dealId, row.mls, cell.key, next);
      if (!res?.ok) { setErr(res?.error || "That did not save."); load(); }
      else if (res.rows) setRows(res.rows as Row[]);
    } catch {
      setErr("That did not save."); load();
    } finally { setBusy(""); }
  };

  return (
    <div style={{ borderTop: `1px solid ${LINE}`, padding: "12px 13px", background: "#fff" }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2 }}>
        How the finishes compare
      </div>
      <div style={{ fontSize: 12, color: MUTED, marginBottom: 9 }}>
        Room against the same room. Tap any cell to overrule what the photos scored.
        This is what prints in the report.
      </div>
      {err && <div style={{ fontSize: 12, color: TERRA, marginBottom: 7 }}>{err}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%", minWidth: 560 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "5px 8px 7px 0", color: MUTED, fontWeight: 700, whiteSpace: "nowrap" }}>Comparable</th>
              {rows[0].cells.map((c) => (
                <th key={c.key} style={{ padding: "5px 6px 7px", color: MUTED, fontWeight: 700, whiteSpace: "nowrap" }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.mls} style={{ borderTop: `1px solid ${LINE}` }}>
                <td style={{ padding: "7px 8px 7px 0", color: NAVY, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {(r.address || "").split(",")[0]}
                  {r.suite === "Yes" && (
                    <span style={{ marginLeft: 6, fontSize: 10.5, color: GREEN, fontWeight: 700 }}>SUITE</span>
                  )}
                </td>
                {r.cells.map((c) => {
                  const id = `${r.mls}:${c.key}`;
                  const v = c.value || "";
                  return (
                    <td key={c.key} style={{ padding: "4px 4px", textAlign: "center" }}>
                      <button
                        onClick={() => flip(r, c)}
                        disabled={busy === id}
                        title={c.edited ? `Your call. The photos scored this "${SHORT[c.auto || ""] || "not rated"}". Tap to cycle.` : "Scored from the photos. Tap to overrule."}
                        style={{
                          width: "100%", minWidth: 74, cursor: "pointer", borderRadius: 6,
                          padding: "5px 6px", fontSize: 11.5, fontWeight: c.edited ? 800 : 600,
                          // Her call is outlined, the computed one is flat. She has to be
                          // able to see at a glance which cells are hers.
                          border: c.edited ? `1.5px solid ${NAVY}` : `1px solid ${LINE}`,
                          background: c.edited ? "#EEF2FA" : "#fff",
                          color: v ? NAVY : MUTED,
                          opacity: busy === id ? 0.55 : 1,
                        }}
                      >
                        {SHORT[v] || "not rated"}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11.5, color: MUTED, marginTop: 8 }}>
        Outlined cells are yours. Tapping cycles Yours, On par, This comp, then back to the scored value.
      </div>
    </div>
  );
}
