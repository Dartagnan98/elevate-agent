// The report, before it goes out — mockup screen 10, on the Report step.
//
// Two questions, in the order she asks them: what is in it, and what does it
// look like. So sections first, then the pages of the actual rendered PDF.
//
// The page images are of the REPORT SHE WOULD SEND, not a mockup of it. The
// Elevate shell has no PDF plugin, so an embedded PDF is a blank pane; images
// are the only way to look at the thing in the app before it leaves.
//
// Two sections are required and are shown as such rather than hidden: the visual
// QA gate hard-fails without buyer demand and the pricing section, so a switch
// that turned them off would only produce a report that cannot pass its own check.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", BLUE = "#5E8AD0", TERRA = "#C46340";

type Section = { key: string; label: string; blurb?: string; locked?: boolean; on: boolean };

export default function CmaReportBuild({ dealId }: { dealId: string }) {
  const isMobile = useIsMobile();
  const [sections, setSections] = useState<Section[]>([]);
  const [counts, setCounts] = useState({ on: 0, total: 0 });
  const [saving, setSaving] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [pages, setPages] = useState(0);
  const [viewing, setViewing] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(() => {
    api.getCmaSections(dealId)
      .then((r) => { setSections(r.sections || []); setCounts({ on: r.onCount, total: r.total }); })
      .catch(() => { /* the step still works without toggles */ });
    api.getCmaReportPages(dealId)
      .then((r) => setPages(r.available ? r.pages : 0))
      .catch(() => setPages(0));
  }, [dealId]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (viewing === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewing(null);
      if (e.key === "ArrowRight") setViewing((v) => Math.min(pages, (v || 1) + 1));
      if (e.key === "ArrowLeft") setViewing((v) => Math.max(1, (v || 1) - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewing, pages]);

  const toggle = async (s: Section) => {
    if (s.locked) return;
    setSaving(s.key); setErr("");
    // Optimistic: the switch should answer the tap, not the round trip.
    setSections((xs) => xs.map((x) => (x.key === s.key ? { ...x, on: !x.on } : x)));
    try {
      const r = await api.setCmaSections(dealId, { [s.key]: !s.on });
      if (!r.ok) { setErr(r.error || "That did not save."); load(); return; }
      if (r.sections) { setSections(r.sections); setCounts({ on: r.onCount || 0, total: r.total || 0 }); }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
      load();
    } finally { setSaving(null); }
  };

  if (!sections.length && !pages) return null;

  const FIRST = isMobile ? 6 : 12;
  const shown = Array.from({ length: showAll ? pages : Math.min(FIRST, pages) }, (_, i) => i + 1);

  return (
    <section style={{ marginTop: 12 }}>
      {/* Her closing paragraph, written last because that is the order she
          thinks in: read the comps, then say where she lands. It replaces the
          standing copy in the report's closing block. */}
      <Overview dealId={dealId} isMobile={isMobile} />

      {!!sections.length && (
        <>
          <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
            In the report
            <CmaInfo label="About report sections">
              Switch off anything this seller does not need. Two are required and
              cannot be turned off.
            </CmaInfo>
          </h3>
          <p style={{ margin: "0 0 10px", fontSize: 14, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
{counts.on} of {counts.total} sections.
          </p>

          <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
            {sections.map((s, i) => (
              <div key={s.key} style={{ borderTop: i ? `1px solid ${LINE}` : "none" }}>
                <button
                  type="button"
                  onClick={() => void toggle(s)}
                  disabled={!!s.locked || saving === s.key}
                  aria-pressed={s.on}
                  style={{
                    width: "100%", textAlign: "left", font: "inherit", background: "transparent",
                    border: "none", minHeight: 44, padding: isMobile ? "11px 12px" : "10px 14px",
                    display: "flex", alignItems: "center", gap: 12,
                    cursor: s.locked ? "default" : "pointer", opacity: saving === s.key ? 0.6 : 1,
                  }}
                >
                  {/* A checkmark reads as "included" at a glance; a switch reads as
                      a setting. This list answers "what is in it". */}
                  <span aria-hidden style={{
                    flexShrink: 0, width: 22, height: 22, borderRadius: 6,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: s.on ? (s.locked ? "#E7EDE8" : "#EAF4EA") : "#fff",
                    border: `1.5px solid ${s.on ? (s.locked ? "#B9CCBB" : "#A9CDAB") : "#C9D1DE"}`,
                    color: s.on ? (s.locked ? "#5C7A5F" : GREEN) : "transparent",
                    fontSize: 13, fontWeight: 800, lineHeight: 1,
                  }}>✓</span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: "block", fontSize: isMobile ? 15 : 14, fontWeight: 600, color: s.on ? NAVY : MUTED }}>
                      {s.label}
                    </span>
                    {s.blurb && (
                      <span style={{ display: "block", fontSize: 13, color: MUTED, marginTop: 2, lineHeight: 1.4 }}>
                        {s.blurb}
                      </span>
                    )}
                  </span>
                  {s.locked && (
                    <span style={{ flexShrink: 0, fontSize: 12, fontWeight: 700, color: MUTED }}>Always in</span>
                  )}
                </button>
              </div>
            ))}
          </div>
          {err && <div style={{ fontSize: 13, color: "#8B1A1A", marginTop: 8 }}>{err}</div>}
        </>
      )}

      {pages > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY }}>
            What the seller will see
          </h3>
          <p style={{ margin: "0 0 10px", fontSize: 14, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
{pages} {pages === 1 ? "page" : "pages"}.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${isMobile ? 3 : 6}, 1fr)`, gap: 7 }}>
            {shown.map((n) => (
              <button key={n} type="button" onClick={() => setViewing(n)}
                aria-label={`Report page ${n} of ${pages}`}
                style={{ padding: 0, border: `1px solid ${LINE}`, borderRadius: 5, background: "#f4f6fa", cursor: "zoom-in", overflow: "hidden", position: "relative", lineHeight: 0, minHeight: 44 }}>
                <img src={api.cmaReportPageUrl(dealId, n)} alt="" loading="lazy" style={{ width: "100%", display: "block" }} />
                <span style={{ position: "absolute", bottom: 2, right: 3, fontSize: 9, fontWeight: 700, color: "#fff", background: "rgba(24,40,72,.72)", borderRadius: 3, padding: "0 4px", lineHeight: "13px" }}>{n}</span>
              </button>
            ))}
          </div>
          {pages > shown.length && (
            <button type="button" onClick={() => setShowAll(true)}
              style={{ background: "none", border: "none", padding: "8px 0 0", fontSize: 14, fontWeight: 600, color: BLUE, cursor: "pointer", minHeight: 44 }}>
              Show all {pages} pages
            </button>
          )}
        </div>
      )}

      {viewing !== null && (
        <div onClick={() => setViewing(null)} role="dialog" aria-modal="true"
          aria-label={`Report page ${viewing}`}
          style={{ position: "fixed", inset: 0, background: "rgba(13,20,33,.93)", zIndex: 1250, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 12, paddingBottom: "max(12px, env(safe-area-inset-bottom))" }}>
          <div style={{ color: "#CBD6E8", fontSize: 13, display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", justifyContent: "center" }}>
            <b style={{ color: "#fff" }}>Your report</b>
            <span>page {viewing} of {pages}</span>
            <span>tap to close</span>
          </div>
          <img src={api.cmaReportPageUrl(dealId, viewing)} alt={`Report page ${viewing}`}
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: "94vw", maxHeight: "76vh", objectFit: "contain", borderRadius: 6, background: "#fff" }} />
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={(e) => { e.stopPropagation(); setViewing((v) => Math.max(1, (v || 1) - 1)); }}
              disabled={viewing <= 1}
              style={{ minHeight: 44, background: "#1d2942", color: viewing <= 1 ? "#5b6782" : "#fff", border: "none", borderRadius: 8, padding: "10px 18px", fontSize: 14, fontWeight: 700, cursor: viewing <= 1 ? "default" : "pointer" }}>← Back</button>
            <button onClick={(e) => { e.stopPropagation(); setViewing((v) => Math.min(pages, (v || 1) + 1)); }}
              disabled={viewing >= pages}
              style={{ minHeight: 44, background: "#1d2942", color: viewing >= pages ? "#5b6782" : "#fff", border: "none", borderRadius: 8, padding: "10px 18px", fontSize: 14, fontWeight: 700, cursor: viewing >= pages ? "default" : "pointer" }}>Next →</button>
          </div>
        </div>
      )}
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Overview — the closing summary, written FROM her notes.

   Skyleigh: "I don't want to have to write anything specific in that section. I
   would like that to actually be a summary section that is auto generated from
   all of the notes that I've made throughout the comparable. And make it so that
   there's an edit button so that I can edit it before it goes into the final PDF."

   So there is no empty box asking her to write the thing she has already written
   nine times. One button synthesises her comp notes into a closing paragraph, it
   comes back editable, and nothing reaches the report until she saves it.
   ───────────────────────────────────────────────────────────────── */
function Overview({ dealId, isMobile }: { dealId: string; isMobile: boolean }) {
  const [published, setPublished] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"" | "writing" | "saving">("");
  const [err, setErr] = useState("");
  const draftRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    let live = true;
    api.getCmaNotes(dealId)
      .then((r) => { if (live && r?.ok) setPublished((r.overview?.voiced || "").trim()); })
      .catch(() => { /* starts empty, still writable */ });
    return () => { live = false; };
  }, [dealId]);

  const write = async () => {
    setBusy("writing"); setErr("");
    try {
      const r = await api.summarizeCmaNotes(dealId);
      if (r?.ok && r.text) setDraft(r.text);
      else setErr(r?.error || "The summary could not be written.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The summary could not be written.");
    } finally { setBusy(""); }
  };

  const save = async (text: string) => {
    setBusy("saving"); setErr("");
    try {
      const r = await api.setCmaOverview(dealId, "", text.trim());
      if (r?.ok) { setPublished(text.trim()); setDraft(""); }
      else setErr(r?.error || "Could not save that.");
    } catch { setErr("Could not save that."); }
    finally { setBusy(""); }
  };

  const box: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", font: "inherit", fontSize: 14, lineHeight: 1.6,
    color: NAVY, background: "transparent", border: "none", padding: 0,
    minHeight: 120, resize: "vertical",
  };
  const btn = (kind: "primary" | "secondary" | "quiet"): React.CSSProperties => ({
    minHeight: 44, borderRadius: 7,
    padding: kind === "quiet" ? "10px 4px" : "10px 16px",
    fontSize: 13, fontWeight: kind === "quiet" ? 600 : 800,
    cursor: busy ? "default" : "pointer", font: "inherit",
    border: kind === "secondary" ? "1px solid #C7D6EC" : "none",
    background: kind === "primary" ? (busy ? "#D8B7A6" : TERRA) : "transparent",
    color: kind === "primary" ? "#fff" : kind === "secondary" ? BLUE : MUTED,
  });
  const focusDraft = () => {
    const el = draftRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  };
  const showing = draft || published;

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
        Where you land overall
        <CmaInfo label="About the summary">
          Written from the notes you left on the comparables, so you do not write it twice.
          Edit it however you like. Nothing reaches the report until you save it.
        </CmaInfo>
      </h3>
      <p style={{ margin: "0 0 10px", fontSize: 13.5, color: MUTED, lineHeight: 1.5, maxWidth: "66ch" }}>
        The last thing your sellers read, after all the comparables.
      </p>

      {!showing ? (
        <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, background: "#fff", padding: "16px 18px" }}>
          <button type="button" style={btn("primary")} onClick={() => void write()} disabled={!!busy}>
            {busy === "writing" ? "Writing…" : "Write it from my notes"}
          </button>
          <div style={{ fontSize: 12, color: MUTED, marginTop: 9, lineHeight: 1.5, maxWidth: "60ch" }}>
            Pulls together everything you wrote on the comparables. Takes about fifteen seconds,
            and you can edit every word of it after.
          </div>
        </div>
      ) : (
        <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, background: "#fff", overflow: "hidden" }}>
          <div style={{ margin: 12, padding: "13px 15px", borderRadius: 8, background: "#FBF1EC", border: "1px solid #E9CDBF" }}>
            <span style={{ display: "block", fontSize: 10, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase", color: TERRA, marginBottom: 6 }}>
              {draft ? "For the report" : "In the report"}
            </span>
            <textarea ref={draftRef} value={showing}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Closing summary for the report" style={box} />
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "0 12px 13px", flexWrap: "wrap" }}>
            {draft ? (
              <>
                <button type="button" style={btn("primary")} disabled={!!busy} onClick={() => void save(draft)}>
                  {busy === "saving" ? "Saving…" : "Add to report"}
                </button>
                <button type="button" style={btn("secondary")} disabled={!!busy} onClick={focusDraft}>Edit</button>
                <button type="button" style={btn("quiet")} disabled={!!busy} onClick={() => setDraft("")}>Discard</button>
              </>
            ) : (
              <>
                <button type="button" style={btn("secondary")} disabled={!!busy}
                  onClick={() => { setDraft(published); setTimeout(focusDraft, 0); }}>Edit</button>
                <button type="button" style={btn("secondary")} disabled={!!busy} onClick={() => void write()}>
                  {busy === "writing" ? "Writing…" : "Write it again from my notes"}
                </button>
                <button type="button" style={btn("quiet")} disabled={!!busy} onClick={() => void save("")}>Remove</button>
              </>
            )}
          </div>
        </div>
      )}

      {err && <div style={{ marginTop: 8, fontSize: 12.5, color: "#9B3B2E", lineHeight: 1.45 }}>{err}</div>}
    </div>
  );
}
