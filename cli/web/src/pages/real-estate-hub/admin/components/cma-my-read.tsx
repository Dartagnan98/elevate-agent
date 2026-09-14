// Your read on the home — the Property step.
//
// Skyleigh 2026-08-17: "If I can give photos that's great and have a space to
// give my feedback and adjust.. if not then I'll manually weigh it." So this is
// ONE control with two entry states, not two features:
//
//   photos scored -> the chips show what the scoring found and she adjusts it
//   no photos     -> the chips ARE the assessment; she has walked the property
//
// Why it exists at all: the comps always have 20+ MLS photos and can always be
// scored honestly. Her home often has none. That asymmetry used to collapse the
// whole finish comparison into neutral scores, which the report then presented
// as analysis. Her walkthrough is the missing half, and it is a STRONGER source
// than the comps' side: their agents only ever had photos.
//
// Four questions, three chips each. Fable's warning, and it is right: more than
// four and she taps past the whole thing to get on with the CMA.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", BLUE = "#5E8AD0";

type Axis = {
  key: string; label: string; picked?: string | null; scored?: number | null;
  chips: { id: string; label: string }[];
};

export default function CmaMyRead({ dealId, onSaved }: { dealId: string; onSaved?: () => void }) {
  const isMobile = useIsMobile();
  const [axes, setAxes] = useState<Axis[]>([]);
  const [hasPhotos, setHasPhotos] = useState(false);
  const [hasMine, setHasMine] = useState(false);
  const [notes, setNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api.getCmaAssessment(dealId)
      .then((r) => {
        setAxes(r.axes || []); setHasPhotos(!!r.hasPhotos); setHasMine(!!r.hasMine);
        if (!notesDirty) setNotes(r.notes || "");
      })
      .catch(() => setAxes([]));
  }, [dealId, notesDirty]);
  useEffect(() => { load(); }, [dealId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!axes.length) return null;

  const pick = async (axis: Axis, chipId: string) => {
    const next = axis.picked === chipId ? "" : chipId;   // tapping again clears it
    setBusy(axis.key); setErr("");
    setAxes((xs) => xs.map((a) => (a.key === axis.key ? { ...a, picked: next || null } : a)));
    try {
      const r = await api.setCmaAssessment(dealId, { picks: { [axis.key]: next } });
      if (!r.ok) { setErr(r.error || "That did not save."); load(); return; }
      if (r.axes) { setAxes(r.axes); setHasMine(!!r.hasMine); }
      onSaved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save."); load();
    } finally { setBusy(""); }
  };

  const saveNotes = async () => {
    setBusy("notes"); setErr("");
    try {
      const r = await api.setCmaAssessment(dealId, { notes });
      if (!r.ok) { setErr(r.error || "That did not save."); return; }
      setNotesDirty(false); setHasMine(!!r.hasMine); onSaved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
    } finally { setBusy(""); }
  };

  return (
    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", marginBottom: 12, background: "#fff" }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
        Your read on the home
      </div>
      <p style={{ margin: "0 0 11px", fontSize: 14, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
        {hasPhotos
          ? "The photos have been scored. Change anything that does not match what you saw."
          : "There are no photos to score, so this is what the comparison uses. You have been inside; the comps are only ever judged from their listing photos."}
      </p>

      {axes.map((a) => (
        <div key={a.key} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: NAVY, marginBottom: 6, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            {a.label}
            {a.picked && a.scored != null && (
              <span style={{ fontSize: 12, fontWeight: 600, color: GREEN }}>you set this</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {a.chips.map((c) => {
              const on = a.picked === c.id;
              return (
                <button key={c.id} type="button"
                  onClick={() => void pick(a, c.id)}
                  disabled={busy === a.key}
                  aria-pressed={on}
                  style={{
                    // 44pt targets: she taps these standing in someone's kitchen.
                    minHeight: 44, padding: isMobile ? "10px 14px" : "9px 13px",
                    borderRadius: 9, fontSize: 14, fontWeight: on ? 700 : 600,
                    border: `1.5px solid ${on ? BLUE : "#C9D1DE"}`,
                    background: on ? "#EAF0F9" : "#fff",
                    color: on ? "#2C4A7C" : "#4A5468",
                    cursor: busy === a.key ? "wait" : "pointer",
                    flex: isMobile ? "1 1 auto" : "0 0 auto",
                  }}>
                  {c.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <label style={{ display: "block", fontSize: 13.5, fontWeight: 600, color: NAVY, marginBottom: 6 }}>
        Anything else worth knowing?
      </label>
      <textarea
        value={notes}
        onChange={(e) => { setNotes(e.target.value); setNotesDirty(true); }}
        rows={3}
        placeholder="Kitchen was redone a couple of years ago. Yard is the best on the street."
        style={{
          width: "100%", boxSizing: "border-box", border: `1px solid #dde3ee`, borderRadius: 8,
          padding: "10px 11px", fontSize: 15, lineHeight: 1.5, color: NAVY,
          fontFamily: "inherit", resize: "vertical",
        }}
      />

      {err && <div style={{ fontSize: 13, color: "#8B1A1A", marginTop: 8 }}>{err}</div>}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 9, flexWrap: "wrap" }}>
        <button
          onClick={() => void saveNotes()}
          disabled={!notesDirty || busy === "notes"}
          style={{
            minHeight: 44, background: (!notesDirty || busy === "notes") ? "#d7dce6" : NAVY,
            color: (!notesDirty || busy === "notes") ? "#8a93a6" : "#fff",
            border: "none", borderRadius: 8, padding: "10px 17px", fontSize: 14, fontWeight: 700,
            cursor: busy === "notes" ? "wait" : notesDirty ? "pointer" : "default",
          }}>
          {busy === "notes" ? "Saving…" : "Save my notes"}
        </button>
        {hasMine && !notesDirty && (
          <span style={{ fontSize: 13, color: GREEN, fontWeight: 600 }}>Saved</span>
        )}
        <span style={{ fontSize: 13, color: MUTED }}>
          Tap a chip again to clear it.
        </span>
      </div>
    </div>
  );
}
