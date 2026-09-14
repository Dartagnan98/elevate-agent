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
import type { CmaPricePageQuads } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";
import CmaExpiredReview from "./cma-expired-review";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#e3e7ef",
      GREEN = "#2f7a4d", BLUE = "#5E8AD0", TERRA = "#C46340";

type Section = { key: string; label: string; blurb?: string; locked?: boolean; on: boolean };

export default function CmaReportBuild({ dealId, reportVersion = "", revision = 0 }: { dealId: string; reportVersion?: string; revision?: number }) {
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
  }, [dealId, reportVersion, revision]);
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

  // NO early return here. The expired picker, the price page and the overview
  // are hers to fill in BEFORE a report exists, and getCmaSections swallows its
  // own errors above, so a bad toggles fetch used to blank this whole step --
  // the same silent-absence she hit on 2026-09-06 with the expired picker.
  // Every block below carries its own guard.

  const FIRST = isMobile ? 6 : 12;
  const shown = Array.from({ length: showAll ? pages : Math.min(FIRST, pages) }, (_, i) => i + 1);

  return (
    <section style={{ marginTop: 12 }}>
      {/* Her closing paragraph, written last because that is the order she
          thinks in: read the comps, then say where she lands. It replaces the
          standing copy in the report's closing block. */}
      {/* ALSO HERE, not only on the Comparables step. Skyleigh 2026-09-06, after
          the first build: "It's still not letting me select which expired listings
          I want to include." It was mounted, on a step she was not on. Deciding
          which expired homes a seller sees is a REPORT decision and she makes it
          on the Report step, next to the section switches, so the control belongs
          on both screens. They share server state, and only one step renders at a
          time, so there is nothing to keep in sync. */}
      <CmaExpiredReview dealId={dealId} />

      <PricePage dealId={dealId} isMobile={isMobile} />

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
                <img src={(api.cmaReportPageUrl(dealId, n) + "?v=" + encodeURIComponent(reportVersion))} alt="" loading="lazy" style={{ width: "100%", display: "block" }} />
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
          <img src={(api.cmaReportPageUrl(dealId, viewing) + "?v=" + encodeURIComponent(reportVersion))} alt={`Report page ${viewing}`}
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
   PricePage — "How We Got to the Price", the four-box page of the approved
   design, written from her own material.

   This page is IN the approved template and cma-visual-qa.py hard-fails A7
   without it. The renderer has always been able to print it: it reads
   pricingStrategy / valueDrivers / buyerQuestions / prepNextSteps off
   _strategy.json. NOTHING EVER WROTE THOSE FOUR KEYS. Since the wizard rebuild
   the only writer stamped the address and the price, so the page returned an
   empty string on every CMA and the report failed its own design check in
   silence, while this very step listed the section as "Always in".

   Skyleigh 2026-09-06, asked where the words should come from: "From your notes,
   you approve." So it is the same two-step everything else here uses: a draft off
   her notes, her positioning, the buyer-demand number and her walkthrough read,
   editable, and nothing in the report until she presses the button.
   ───────────────────────────────────────────────────────────────── */

const PRICE_BOXES: { key: keyof CmaPricePageQuads; label: string; blurb: string }[] = [
  { key: "pricingStrategy", label: "Pricing strategy", blurb: "Why the launch price is where it is." },
  { key: "valueDrivers", label: "Value drivers to lead with", blurb: "What this home has that its competition does not." },
  { key: "buyerQuestions", label: "Likely buyer questions", blurb: "What a buyer or their agent will push back on." },
  { key: "prepNextSteps", label: "Prep, timing and next steps", blurb: "What happens now, and what is worth doing first." },
];

const asLines = (q?: string[]) => (q || []).join("\n");
const asBullets = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);

function PricePage({ dealId, isMobile }: { dealId: string; isMobile: boolean }) {
  const [saved, setSaved] = useState<CmaPricePageQuads>({});
  const [inReport, setInReport] = useState(false);
  const [sources, setSources] = useState<string[]>([]);
  // Non-null while she has a draft or an edit open. Null means "show what is saved".
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState<"" | "writing" | "saving">("");
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api.getCmaPricePage(dealId)
      .then((r) => {
        if (!r?.ok) return;
        setSaved(r.quads || {});
        setInReport(!!r.inReport);
        setSources(r.sources || []);
      })
      .catch(() => { /* the step still works without it */ });
  }, [dealId]);
  useEffect(() => { load(); }, [load]);

  const write = async () => {
    setBusy("writing"); setErr("");
    try {
      // The server side of this runs a headless writer for up to five minutes.
      // On a phone, locking the screen or switching apps can suspend the fetch
      // so it never settles, and then "writing" never clears and the button
      // stays dead with nothing to tap. Race it against a clock so the UI can
      // always come back, even when the request cannot.
      const r = await Promise.race([
        api.draftCmaPricePage(dealId),
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error("That took longer than five minutes, so I stopped waiting. Tap it again and leave this screen open.")), 305000)),
      ]);
      if (r?.ok && r.quads) {
        const d: Record<string, string> = {};
        PRICE_BOXES.forEach((b) => { d[b.key as string] = asLines(r.quads[b.key]); });
        setDraft(d);
      } else setErr(r?.error || "The page could not be written.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The page could not be written.");
    } finally { setBusy(""); }
  };

  const save = async (d: Record<string, string> | null) => {
    setBusy("saving"); setErr("");
    const quads: CmaPricePageQuads = {};
    PRICE_BOXES.forEach((b) => { quads[b.key] = d ? asBullets(d[b.key as string] || "") : []; });
    try {
      const r = await api.setCmaPricePage(dealId, quads);
      if (r?.ok) { setSaved(r.quads || quads); setInReport(!!r.inReport); setDraft(null); }
      else setErr(r?.error || "Could not save that.");
    } catch { setErr("Could not save that."); }
    finally { setBusy(""); }
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
  const box: React.CSSProperties = {
    // 16px on phones is not a taste call: iOS Safari auto-zooms any focused
    // field under 16px, and this app ships no maximum-scale, so a smaller box
    // leaves her zoomed and panned sideways after every tap.
    width: "100%", boxSizing: "border-box", font: "inherit", fontSize: isMobile ? 16 : 13.5, lineHeight: 1.6,
    color: NAVY, background: "transparent", border: "none", padding: 0,
    minHeight: 96, resize: "vertical",
  };

  const showing = draft || (inReport
    ? Object.fromEntries(PRICE_BOXES.map((b) => [b.key as string, asLines(saved[b.key])]))
    : null);

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
        How we got to the price
        <CmaInfo label="About this page">
          Four boxes in the approved design, written from your notes on the comparables,
          your bracket, the buyer-demand number and your read on the home. Edit every word.
          Nothing reaches the report until you save it.
        </CmaInfo>
      </h3>
      <p style={{ margin: "0 0 10px", fontSize: 13.5, color: MUTED, lineHeight: 1.5, maxWidth: "66ch" }}>
        Sits right after Key Strengths, the way the approved design has it.
      </p>

      {!showing ? (
        <div style={{ border: "1px solid #E9CDBF", borderRadius: 12, background: "#FBF1EC", padding: "16px 18px" }}>
          {/* Said out loud, because this is exactly what has been going wrong: the
              page was listed as included and was not in the PDF. */}
          <div style={{ fontSize: 13.5, fontWeight: 800, color: "#9B3B2E", marginBottom: 8, lineHeight: 1.5 }}>
            This page is not in the report yet. Write and approve it if you want to include it.
          </div>
          <button type="button" style={btn("primary")} onClick={() => void write()} disabled={!!busy}>
            {busy === "writing" ? "Writing…" : "Write it from my notes"}
          </button>
          <div style={{ fontSize: 12, color: MUTED, marginTop: 9, lineHeight: 1.5, maxWidth: "62ch" }}>
            {sources.length
              ? `Uses ${sources.join(", ")}. Takes a couple of minutes, and you can edit every word after.`
              : "Finish the comparables and pricing steps first, then this can be written."}
          </div>
        </div>
      ) : (
        <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, background: "#fff", overflow: "hidden" }}>
          <div style={{ display: "grid", gap: 10, padding: 12,
                        gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
            {PRICE_BOXES.map((b) => (
              <div key={b.key as string} style={{ padding: "12px 14px", borderRadius: 8, background: "#FBF1EC", border: "1px solid #E9CDBF" }}>
                <span style={{ display: "block", fontSize: 10, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase", color: TERRA, marginBottom: 2 }}>
                  {b.label}
                </span>
                <span style={{ display: "block", fontSize: 11.5, color: MUTED, marginBottom: 7, lineHeight: 1.4 }}>
                  {b.blurb}
                </span>
                <textarea
                  value={showing[b.key as string] || ""}
                  onChange={(e) => setDraft({ ...(showing as Record<string, string>), [b.key as string]: e.target.value })}
                  aria-label={b.label} style={box}
                  placeholder="One line per bullet." />
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "0 12px 13px", flexWrap: "wrap" }}>
            {draft ? (
              <>
                <button type="button" style={btn("primary")} disabled={!!busy} onClick={() => void save(draft)}>
                  {busy === "saving" ? "Saving…" : "Add to report"}
                </button>
                <button type="button" style={btn("quiet")} disabled={!!busy} onClick={() => { setDraft(null); setErr(""); }}>Discard</button>
              </>
            ) : (
              <>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: GREEN }}>In the report</span>
                <button type="button" style={btn("secondary")} disabled={!!busy} onClick={() => void write()}>
                  {busy === "writing" ? "Writing…" : "Write it again from my notes"}
                </button>
                <button type="button" style={btn("quiet")} disabled={!!busy} onClick={() => void save(null)}>Remove</button>
              </>
            )}
          </div>
        </div>
      )}

      {err && <div style={{ marginTop: 8, fontSize: 12.5, color: "#9B3B2E", lineHeight: 1.45 }}>{err}</div>}
    </div>
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
