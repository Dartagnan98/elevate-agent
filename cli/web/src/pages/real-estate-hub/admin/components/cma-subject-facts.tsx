// Confirm the property — mockup screens 2-3, the square-footage conflict gate.
//
// WHY THIS EXISTS. Every comp filter keys off the subject's own numbers, and the
// MLS record can be decades old. 2520 Young reads 2,016 sqft and 4 bedrooms off
// a 1999 court-ordered sale; that produced a 1,613-2,419 size window which
// structurally EXCLUDED the 2,224-3,000 sqft comps Skyleigh actually used, and
// the result looked perfectly credible on the way out. A wrong subject number
// does not skew the comps slightly, it puts them in the wrong price bracket.
//
// The search side compensates by widening to +/-40% when the record is old. That
// is a guess. This is the answer: let her type the real figure, and then filter
// tightly around it (the runner drops the stale widening once a value is
// confirmed).
//
// Blank clears a field, so there is always a way back to what the MLS says.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import type { CmaSubjectField } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", WARN = "#B26B12", WARNBG = "#FDF3E4";

type Facts = {
  available: boolean;
  recordAgeYears?: number | null;
  recordStale?: boolean;
  recordDate?: string | null;
  sqft: CmaSubjectField; lot: CmaSubjectField; beds: CmaSubjectField; baths: CmaSubjectField;
};

const ROWS: { key: "sqft" | "lot" | "beds" | "baths"; label: string; unit?: string }[] = [
  { key: "sqft", label: "Finished area", unit: "sqft" },
  { key: "lot", label: "Lot", unit: "sqft" },
  { key: "beds", label: "Bedrooms" },
  { key: "baths", label: "Bathrooms" },
];

export default function CmaSubjectFacts({
  dealId,
  onChanged,
}: {
  dealId: string;
  onChanged?: () => void;
}) {
  const isMobile = useIsMobile();
  const [facts, setFacts] = useState<Facts | null>(null);
  const [state, setState] = useState<"loading" | "none" | "ready">("loading");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api.getCmaSubject(dealId)
      .then((r) => {
        if (!r.available) { setState("none"); return; }
        setFacts(r as Facts); setState("ready");
      })
      .catch(() => setState("none"));
  }, [dealId]);
  useEffect(() => { load(); }, [load]);

  // Nothing pulled yet is a normal state: the facts arrive with the pull.
  if (state !== "ready" || !facts) return null;

  const dirty = Object.keys(draft).length > 0;
  const nf = (n?: number | null) => (n == null ? "" : n.toLocaleString("en-CA"));

  const save = async () => {
    setSaving(true); setErr("");
    try {
      const r = await api.setCmaSubject(dealId, draft);
      if (!r.ok) { setErr(r.error || "Could not save that."); return; }
      setDraft({}); load(); onChanged?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save that.");
    } finally { setSaving(false); }
  };

  return (
    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", marginBottom: 12, background: "#fff" }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
        Confirm the property
        <CmaInfo label="About these numbers">
          Every comp filter keys off these. Correcting one uses your figure exactly.
          Clear a box to go back to the MLS record.
        </CmaInfo>
      </div>

      {/* The warning is the whole reason this screen exists, so it leads. */}
      {facts.recordStale && (
        <div style={{ display: "flex", gap: 8, padding: "8px 10px", background: WARNBG, border: "1px solid #EBD2A8", borderRadius: 8, fontSize: 12, color: WARN, lineHeight: 1.5, marginBottom: 10 }}>
          <span>
            {facts.recordAgeYears != null
              ? <>The last MLS record is about {facts.recordAgeYears} years old{facts.recordDate ? ` (${facts.recordDate})` : ""}. </>
              : <>The last MLS record has no readable date. </>}
          </span>
        </div>
      )}

      <div>
        {ROWS.map((row) => {
          const f = facts[row.key] || {};
          const edited = draft[row.key] !== undefined;
          const shown = edited ? draft[row.key] : (f.value == null ? "" : String(f.value));
          return (
            <div key={row.key} style={{
              display: "flex", alignItems: isMobile ? "flex-start" : "center",
              flexDirection: isMobile ? "column" : "row",
              gap: isMobile ? 4 : 10, padding: "7px 0", borderBottom: `1px solid #F1F4F8`,
            }}>
              <span style={{ flex: 1, fontSize: 12.5, color: MUTED, minWidth: 0 }}>
                {row.label}
                {f.source === "skyleigh" && (
                  <span style={{ color: GREEN, fontWeight: 700, marginLeft: 7, fontSize: 11.5 }}>
                    you set this{f.recordValue != null ? `, record said ${nf(f.recordValue)}` : ""}
                  </span>
                )}
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, width: isMobile ? "100%" : "auto" }}>
                <input
                  value={shown}
                  inputMode="numeric"
                  onChange={(e) => setDraft((d) => ({ ...d, [row.key]: e.target.value.replace(/[^0-9]/g, "") }))}
                  aria-label={row.label}
                  style={{
                    width: isMobile ? "100%" : 110, boxSizing: "border-box",
                    border: `1px solid ${edited ? "#9db4dd" : "#dde3ee"}`,
                    background: edited ? "#F3F7FF" : "#fff",
                    borderRadius: 7, padding: "7px 9px", fontSize: 13.5, fontWeight: 700,
                    color: NAVY, fontFamily: "inherit", textAlign: isMobile ? "left" : "right",
                  }}
                />
                {row.unit && <span style={{ fontSize: 11.5, color: MUTED }}>{row.unit}</span>}
              </span>
            </div>
          );
        })}
      </div>

      {err && <div style={{ fontSize: 12, color: "#8B1A1A", marginTop: 8 }}>{err}</div>}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
        <button
          onClick={() => void save()}
          disabled={!dirty || saving}
          style={{
            background: (!dirty || saving) ? "#d7dce6" : NAVY,
            color: (!dirty || saving) ? "#8a93a6" : "#fff",
            border: "none", borderRadius: 8, padding: "9px 16px",
            fontSize: 13, fontWeight: 700, cursor: saving ? "wait" : dirty ? "pointer" : "default",
          }}
        >
          {saving ? "Saving…" : "Save these numbers"}
        </button>
        {dirty && (
          <button onClick={() => { setDraft({}); setErr(""); }}
            style={{ background: "none", border: "none", padding: 0, fontSize: 12, fontWeight: 600, color: MUTED, cursor: "pointer" }}>
            Undo my changes
          </button>
        )}

      </div>
    </div>
  );
}
