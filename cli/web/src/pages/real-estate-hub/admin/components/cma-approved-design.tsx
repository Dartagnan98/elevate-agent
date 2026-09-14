// The approved CMA design, on the Report step.
//
// Skyleigh 2026-08-17: she wanted a place to upload the approved design "so that
// it's easy for the agent to tell what template the final PDF is going to be
// rendered in". Until now the reference PDF's filename was hardcoded inside
// cma-visual-qa.py, so the approved design was invisible from the app and could
// only be changed by editing a script.
//
// This is NOT decoration. cma-visual-qa.py resolves the same pointer file, so
// whatever is uploaded here becomes what every future CMA is proofed against.
//
// Preview is a PNG, not an embedded PDF: the Elevate shell has no PDF plugin, so
// an <iframe> of a PDF renders as a blank pane.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef",
      WARN = "#B26B12", WARNBG = "#FDF3E4";

type Tpl = {
  available: boolean; file?: string; originalName?: string;
  uploadedAt?: string | null; legacy?: boolean; pages?: number | null;
  bytes?: number; hasPreview?: boolean; pageImages?: number;
};

export default function CmaApprovedDesign() {
  const isMobile = useIsMobile();
  const [tpl, setTpl] = useState<Tpl | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [bust, setBust] = useState(0);      // cache-buster for the page images
  const [viewing, setViewing] = useState<number | null>(null);   // full-screen page
  const [showAll, setShowAll] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(() => {
    api.getCmaApprovedTemplate()
      .then((r) => setTpl(r as Tpl))
      .catch(() => setTpl({ available: false }));
  }, []);
  useEffect(() => { load(); }, [load]);

  const upload = async (f: File | null | undefined) => {
    if (!f) return;
    if (!/pdf$/i.test(f.name)) { setErr("The approved design needs to be a PDF."); return; }
    setBusy(true); setErr("");
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(String(fr.result || ""));
        fr.onerror = () => reject(new Error("could not read that file"));
        fr.readAsDataURL(f);
      });
      const r = await api.uploadCmaApprovedTemplate(f.name, dataUrl);
      if (!r.ok) { setErr("That upload did not take."); return; }
      setBust((n) => n + 1);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That upload did not take.");
    } finally { setBusy(false); }
  };

  const pageCount = tpl?.pageImages || tpl?.pages || 0;
  // Show a first screenful, then let her open the rest. Fifteen full-width page
  // images loading at once on a phone is a lot to pay for a glance.
  const FIRST = isMobile ? 6 : 12;
  const shownPages = Array.from({ length: showAll ? pageCount : Math.min(FIRST, pageCount) }, (_, i) => i + 1);

  useEffect(() => {
    if (viewing === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewing(null);
      if (e.key === "ArrowRight") setViewing((v) => Math.min(pageCount, (v || 1) + 1));
      if (e.key === "ArrowLeft") setViewing((v) => Math.max(1, (v || 1) - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewing, pageCount]);

  if (!tpl) return null;

  const when = tpl.uploadedAt
    ? new Date(tpl.uploadedAt).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" })
    : null;

  return (
    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", marginTop: 12, background: "#fff" }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
        Approved design
        <CmaInfo label="About the approved design">
          Every CMA is rendered to match this, and the visual check at the end of
          this step proofs the finished PDF against it. Replacing it keeps the previous one.
        </CmaInfo>
      </div>

      {!tpl.available ? (
        <div style={{ display: "flex", gap: 8, padding: "8px 10px", background: WARNBG, border: "1px solid #EBD2A8", borderRadius: 8, fontSize: 12, color: WARN, lineHeight: 1.5, marginBottom: 10 }}>
          No approved design on file, so there is nothing to check the finished CMA against. Upload the PDF you want every report to match.
        </div>
      ) : (
        <div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 700, color: NAVY, wordBreak: "break-word" }}>
              {tpl.originalName || tpl.file}
            </div>
            <div style={{ fontSize: 11.5, color: MUTED, marginTop: 3, lineHeight: 1.5 }}>
              {tpl.pages ? `${tpl.pages} pages` : ""}
              {tpl.pages && (when || tpl.legacy) ? " · " : ""}
              {when ? `uploaded ${when}` : tpl.legacy ? "the long-standing house template" : ""}
            </div>

          </div>

          {/* EVERY page. The cover tells you almost nothing about the design;
              the comp and pricing pages are where the layout actually lives. */}
          {!!pageCount && (
            <div style={{ marginTop: 11 }}>
              <div style={{ display: "grid", gridTemplateColumns: `repeat(${isMobile ? 3 : 6}, 1fr)`, gap: 7 }}>
                {shownPages.map((n) => (
                  <button key={n} type="button" onClick={() => setViewing(n)}
                    title={`Page ${n} of ${pageCount}`}
                    style={{ padding: 0, border: `1px solid ${LINE}`, borderRadius: 5, background: "#f4f6fa", cursor: "zoom-in", overflow: "hidden", position: "relative", lineHeight: 0 }}>
                    <img src={`${api.cmaApprovedTemplatePageUrl(n)}?v=${bust}`} alt={`Approved design page ${n}`}
                      loading="lazy"
                      style={{ width: "100%", display: "block" }} />
                    <span style={{ position: "absolute", bottom: 2, right: 3, fontSize: 9, fontWeight: 700, color: "#fff", background: "rgba(24,40,72,.72)", borderRadius: 3, padding: "0 4px", lineHeight: "13px" }}>{n}</span>
                  </button>
                ))}
              </div>
              {pageCount > shownPages.length && (
                <button type="button" onClick={() => setShowAll(true)}
                  style={{ background: "none", border: "none", padding: "8px 0 0", fontSize: 12, fontWeight: 700, color: "#5E8AD0", cursor: "pointer" }}>
                  Show all {pageCount} pages
                </button>
              )}

            </div>
          )}
        </div>
      )}

      {viewing !== null && (
        <div onClick={() => setViewing(null)} role="dialog" aria-modal="true"
          aria-label={`Approved design page ${viewing}`}
          style={{ position: "fixed", inset: 0, background: "rgba(13,20,33,.93)", zIndex: 1250, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 12 }}>
          <div style={{ color: "#CBD6E8", fontSize: 12.5, display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", justifyContent: "center" }}>
            <b style={{ color: "#fff" }}>Approved design</b>
            <span>page {viewing} of {pageCount}</span>
            <span>tap to close</span>
          </div>
          <img src={`${api.cmaApprovedTemplatePageUrl(viewing)}?v=${bust}`} alt={`Approved design page ${viewing}`}
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: "94vw", maxHeight: "78vh", objectFit: "contain", borderRadius: 6, background: "#fff" }} />
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={(e) => { e.stopPropagation(); setViewing((v) => Math.max(1, (v || 1) - 1)); }}
              disabled={viewing <= 1}
              style={{ background: "#1d2942", color: viewing <= 1 ? "#5b6782" : "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, fontWeight: 700, cursor: viewing <= 1 ? "default" : "pointer" }}>← Back</button>
            <button onClick={(e) => { e.stopPropagation(); setViewing((v) => Math.min(pageCount, (v || 1) + 1)); }}
              disabled={viewing >= pageCount}
              style={{ background: "#1d2942", color: viewing >= pageCount ? "#5b6782" : "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, fontWeight: 700, cursor: viewing >= pageCount ? "default" : "pointer" }}>Next →</button>
          </div>
        </div>
      )}

      {err && <div style={{ fontSize: 12, color: "#8B1A1A", marginTop: 8 }}>{err}</div>}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 11, flexWrap: "wrap" }}>
        <label style={{
          fontSize: 12.5, fontWeight: 700, color: busy ? "#8a93a6" : NAVY,
          border: `1px solid ${LINE}`, borderRadius: 8,
          padding: isMobile ? "9px 14px" : "7px 13px",
          background: "#fff", cursor: busy ? "wait" : "pointer",
        }}>
          {busy ? "Uploading…" : tpl.available ? "Replace the approved design" : "Upload the approved design"}
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            onChange={(e) => { void upload(e.target.files?.[0]); e.currentTarget.value = ""; }}
            style={{ display: "none" }}
          />
        </label>

      </div>
    </div>
  );
}
