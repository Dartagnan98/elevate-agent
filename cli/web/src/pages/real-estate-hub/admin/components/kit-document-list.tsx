// One document list, shared by every paperwork surface on the deal card:
// the buyer Transaction Kit, the listing-side Listing Kit, and Client
// Onboarding. Built 2026-07-28 from the Transaction Kit redesign so the three
// cannot drift apart again — before this, the same idea existed three times in
// three shapes, with three different sets of buttons.
//
// The shape it enforces, from the Apple HIG pass:
//   · a document is ONE row carrying its whole state
//   · exactly one button per row, labelled with what it does to that document
//     (Draft / Review / Redraft) — no unlabeled overflow menus
//   · opening a row shows page 1 rendered inline beside its editable fields,
//     because this shell has no PDF plugin and a tab comes up blank
//   · fields pre-populate from the deal and say so
//   · status is plain words, and "Drafted" is only ever said about a PDF that
//     actually exists
import React, { useState, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";

const NAVY = "var(--ds-navy-surface)";
const ORANGE = "var(--ds-terracotta)";
const GREEN = "var(--ds-done)";
const BLUE = "var(--ds-blue)";
const INK = "var(--ds-ink)";
const MUTED = "var(--ds-muted)";
const BORDER = "var(--ds-border)";
const BORDER_STRONG = "var(--ds-border-strong)";

export type KitDocState = "excluded" | "unbuilt" | "building" | "stale" | "ready";

export type KitRow = {
  id: string;
  name: string;
  required?: boolean;
  state: KitDocState;
  /** Overrides the default status line for this state. */
  statusText?: string;
  generatedAt?: string;
  /** Values stored on the document; the resolved fetch layers over these. */
  fields?: Record<string, string>;
  /** Per-row field set, when documents on one surface take different fields. */
  fieldDefs?: KitFieldDef[];
};

export type KitFieldDef = {
  key: string; label: string; multiline?: boolean;
  /** Page of the document this field sits on. */
  page?: number;
  type?: "text" | "checkbox";
  /** Export states for a multi-option checkbox group ("1", "2", ...). */
  options?: string[];
  /** What each export state MEANS, from forms/checkbox-labels.json. A PDF
   *  checkbox carries a state and nothing that says what it stands for, so
   *  without this a compliance group can only read "Option 1 / Option 2".
   *  Absent = not labelled yet, and the generic wording is used. */
  optionLabels?: Record<string, string>;
  /** The option the BLANK template already has selected (the DORTS ships with
   *  "representing you as my client" ticked). Shown as a prefill so the card
   *  agrees with the PDF it is previewing. */
  default?: string;
  /** This document is not complete until something here is ticked. */
  mustTick?: boolean;
  /** Required only once another group sits on one of these states — e.g. "is
   *  the copy attached" only matters after you say the agreement exists. */
  mustTickWhen?: { key: string; in: string[] };
  /** known = the deal fills it · extra = the form asks, we do not guess ·
   *  standard = your own identity, same on every document. */
  tier?: "known" | "extra" | "standard";
};

export default function KitDocumentList({
  rows,
  fieldDefs,
  previewUrl,
  fieldsUrl,
  resolveLocal,
  onDraft,
  onOpen,
  onSaveField,
  onExclude,
  excludeLabel = "Leave out of this kit",
  isMobile = false,
  isNarrow = false,
  footNote,
}: {
  rows: KitRow[];
  fieldDefs: KitFieldDef[];
  /** Absolute path to the page-image endpoint for a document. */
  previewUrl: (docId: string, page: number, dpi: number) => string;
  /** Absolute path to the resolved-fields endpoint. Omit to skip resolution. */
  fieldsUrl?: (docId: string) => string;
  /** For surfaces that resolve defaults client-side instead of over HTTP. */
  resolveLocal?: (docId: string) => { fields: Record<string, string>; derived: string[]; defs?: KitFieldDef[] };
  onDraft: (docId: string, name: string) => void;
  onOpen: (docId: string, download?: boolean) => void;
  onSaveField: (docId: string, key: string, value: string) => void;
  /** Omit to hide the "leave out" action (e.g. a required form). */
  onExclude?: (docId: string) => void;
  excludeLabel?: string;
  isMobile?: boolean;
  isNarrow?: boolean;
  footNote?: string;
}) {
  const tap = isMobile ? 44 : undefined;
  const tok = () => (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";

  const [expanded, setExpanded] = useState<string | null>(null);
  // Your own name / brokerage / office is on nearly every form and identical
  // every time. Present, but folded away so it cannot bury what varies.
  const [showStd, setShowStd] = useState<Record<string, boolean>>({});

  // ── page-1 previews ───────────────────────────────────────────────────────
  type Preview = { state: "loading" | "ok" | "error"; url?: string; pages?: number; msg?: string };
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const previewsRef = React.useRef(previews);
  previewsRef.current = previews;
  const dropPreview = useCallback((docId: string) => {
    setPreviews((p) => {
      const cur = p[docId];
      if (cur?.url) URL.revokeObjectURL(cur.url);
      const next = { ...p };
      delete next[docId];
      return next;
    });
  }, []);
  const loadPreview = useCallback(async (docId: string) => {
    setPreviews((p) => ({ ...p, [docId]: { state: "loading" } }));
    try {
      const r = await fetch(previewUrl(docId, 1, 105), { headers: { Authorization: `Bearer ${tok()}` } });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        setPreviews((p) => ({ ...p, [docId]: { state: "error", msg: (e && e.detail) || `error ${r.status}` } }));
        return;
      }
      const pages = Number(r.headers.get("X-Page-Count") || "1") || 1;
      const url = URL.createObjectURL(await r.blob());
      setPreviews((p) => {
        const old = p[docId]?.url;
        if (old) URL.revokeObjectURL(old);
        return { ...p, [docId]: { state: "ok", url, pages } };
      });
    } catch {
      setPreviews((p) => ({ ...p, [docId]: { state: "error", msg: "could not load the preview" } }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewUrl]);
  useEffect(() => () => {
    Object.values(previewsRef.current).forEach((p) => { if (p.url) URL.revokeObjectURL(p.url); });
  }, []);

  // ── resolved field values ─────────────────────────────────────────────────
  // `defs` is what this document ACTUALLY has, read off its own template
  // server-side. Falls back to the surface's list until the fetch lands.
  type Resolved = { fields: Record<string, string>; derived: string[]; defs?: KitFieldDef[] };
  const [resolved, setResolved] = useState<Record<string, Resolved>>({});
  const loadFields = useCallback(async (docId: string) => {
    if (!fieldsUrl) return;
    try {
      const r = await fetch(fieldsUrl(docId), { headers: { Authorization: `Bearer ${tok()}` } });
      if (!r.ok) return;
      const body = await r.json().catch(() => null);
      if (body && body.fields) {
        setResolved((p) => ({ ...p, [docId]: {
          fields: body.fields, derived: body.derived || [],
          // [] means "this form has no fillable fields"; the key being absent
          // means we could not read a template, so keep the generic list.
          defs: Array.isArray(body.defs) ? body.defs : undefined,
        } }));
      }
    } catch { /* falls back to the stored fields */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldsUrl]);

  const openRow = useCallback((docId: string | null) => {
    setExpanded(docId);
    if (!docId) return;
    const row = rows.find((r) => r.id === docId);
    const built = row && (row.state === "ready" || row.state === "stale");
    if (built && !previewsRef.current[docId]) void loadPreview(docId);
    void loadFields(docId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, loadPreview, loadFields]);

  // Re-fetch a preview whose PDF was just rebuilt underneath it.
  const prevStates = React.useRef<Record<string, KitDocState>>({});
  useEffect(() => {
    for (const r of rows) {
      const was = prevStates.current[r.id];
      if (was === "building" && r.state === "ready") {
        dropPreview(r.id);
        if (expanded === r.id) void loadPreview(r.id);
        void loadFields(r.id);
      }
      prevStates.current[r.id] = r.state;
    }
  }, [rows, expanded, dropPreview, loadPreview, loadFields]);

  // ── full-size viewer ──────────────────────────────────────────────────────
  type Zoom = { docId: string; name: string; page: number; pages: number; url?: string; loading: boolean; msg?: string };
  const [zoom, setZoom] = useState<Zoom | null>(null);
  const zoomUrlRef = React.useRef<string | undefined>(undefined);
  const showPage = useCallback(async (docId: string, name: string, page: number, pages: number) => {
    setZoom({ docId, name, page, pages, loading: true });
    try {
      const r = await fetch(previewUrl(docId, page, 150), { headers: { Authorization: `Bearer ${tok()}` } });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        setZoom((z) => (z && z.docId === docId ? { ...z, loading: false, msg: (e && e.detail) || `error ${r.status}` } : z));
        return;
      }
      const total = Number(r.headers.get("X-Page-Count") || pages) || pages;
      const url = URL.createObjectURL(await r.blob());
      if (zoomUrlRef.current) URL.revokeObjectURL(zoomUrlRef.current);
      zoomUrlRef.current = url;
      setZoom((z) => (z && z.docId === docId ? { ...z, page, pages: total, url, loading: false, msg: undefined } : z));
    } catch {
      setZoom((z) => (z && z.docId === docId ? { ...z, loading: false, msg: "could not render this page" } : z));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewUrl]);
  const closeZoom = useCallback(() => {
    if (zoomUrlRef.current) { URL.revokeObjectURL(zoomUrlRef.current); zoomUrlRef.current = undefined; }
    setZoom(null);
  }, []);
  // Capture phase + stopPropagation: the deal card also closes on Escape, so a
  // bubble-phase handler would dismiss the viewer AND the card underneath it.
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeZoom(); return; }
      if (e.key === "ArrowRight" && zoom.page < zoom.pages) {
        e.preventDefault(); e.stopPropagation();
        void showPage(zoom.docId, zoom.name, zoom.page + 1, zoom.pages);
      }
      if (e.key === "ArrowLeft" && zoom.page > 1) {
        e.preventDefault(); e.stopPropagation();
        void showPage(zoom.docId, zoom.name, zoom.page - 1, zoom.pages);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [zoom, showPage, closeZoom]);

  // ── styles ────────────────────────────────────────────────────────────────
  const btn: React.CSSProperties = { fontSize: 12, padding: "5px 13px", borderRadius: 7, border: `1px solid ${BORDER_STRONG}`, background: "#fff", color: INK, cursor: "pointer", fontWeight: 600, minHeight: tap };
  const input: React.CSSProperties = { width: "100%", boxSizing: "border-box", fontSize: 13, padding: "7px 9px", borderRadius: 6, border: `1px solid ${BORDER_STRONG}`, color: INK, fontFamily: "inherit", minHeight: tap };
  const previewBox: React.CSSProperties = { width: "100%", aspectRatio: "8.5 / 11", borderRadius: 8, overflow: "hidden", boxShadow: "0 2px 10px rgba(24,40,72,.08)", boxSizing: "border-box" };
  const link: React.CSSProperties = { background: "none", border: "none", padding: 0, color: BLUE, fontWeight: 700, fontSize: 12.5, cursor: "pointer", font: "inherit", display: "inline-flex", alignItems: "center", minHeight: tap };

  const defaultStatus = (r: KitRow) =>
    r.state === "building" ? "Drafting…"
    : r.state === "excluded" ? "Not included"
    : r.state === "unbuilt" ? "Not drafted yet"
    : r.state === "stale" ? "Edited — redrafts when you send"
    : `Drafted${r.generatedAt ? " " + shortTime(r.generatedAt) : ""}`;

  return (
    <>
      {rows.map((r) => {
        const isOpen = expanded === r.id;
        const built = r.state === "ready" || r.state === "stale";
        const status = r.statusText || defaultStatus(r);
        const tone = r.state === "ready" ? GREEN : r.state === "stale" ? ORANGE : r.state === "building" ? BLUE : MUTED;
        const dot = r.state === "ready" ? GREEN : r.state === "stale" ? ORANGE : r.state === "building" ? BLUE : "#c9ced6";
        const pv = previews[r.id];
        const res = resolveLocal ? resolveLocal(r.id) : resolved[r.id];

        // One button, and it names what happens to THIS document.
        // Colour carries FUNCTION, never state:
        //   navy       = produce this document (Draft / Redraft)
        //   pale blue  = read this document (Review)
        //   terracotta = reserved for the one action that reaches a client (Send)
        // Redraft used to be terracotta, which made the same job look like two
        // different jobs depending on which state a section happened to be in,
        // and diluted terracotta so it no longer meant "this leaves the office".
        // The row's status line already says a document was edited, in orange —
        // the button does not need to repeat it.
        const action = r.state === "building"
          ? <button type="button" disabled style={{ ...btn, opacity: 0.6, cursor: "default" }}>Drafting…</button>
          : r.state === "stale"
            ? <button type="button" onClick={() => onDraft(r.id, r.name)} style={{ ...btn, background: NAVY, borderColor: "transparent", color: "#fff" }}>Redraft</button>
            : r.state === "ready"
              ? <button type="button" onClick={() => openRow(isOpen ? null : r.id)} style={{ ...btn, background: "#eef2f9", borderColor: "transparent", color: "#2f5da8" }}>Review</button>
              : <button type="button" onClick={() => onDraft(r.id, r.name)} style={{ ...btn, background: NAVY, borderColor: "transparent", color: "#fff" }}>Draft</button>;

        return (
          <div key={r.id} style={{ borderTop: "1px solid #eef0f3" }}>
            <div style={{
              display: "flex", gap: 10, borderRadius: 8, paddingRight: isNarrow ? 0 : 4,
              background: isOpen ? "#f5f7fb" : "transparent",
              flexDirection: isNarrow ? "column" : "row",
              alignItems: isNarrow ? "flex-start" : "center",
            }}>
              <button
                type="button"
                onClick={() => openRow(isOpen ? null : r.id)}
                aria-expanded={isOpen}
                style={{ flex: 1, minWidth: 0, width: isNarrow ? "100%" : "auto", display: "flex", alignItems: "center", gap: 11, background: "none", border: "none", padding: "13px 4px", textAlign: "left", cursor: "pointer", font: "inherit", borderRadius: 8 }}
              >
                <span aria-hidden="true" style={{ color: "#9aa0a6", fontSize: 10, width: 11, flexShrink: 0, display: "inline-block", transform: isOpen ? "rotate(90deg)" : "none", transition: "transform .2s ease" }}>▶</span>
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 14, fontWeight: 600, color: INK }}>
                    {r.name}
                    {r.required && <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.4, color: "#9aa0a6", background: "#eef1f6", borderRadius: 5, padding: "2px 7px" }}>REQUIRED</span>}
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, marginTop: 2, color: tone }}>
                    <span style={{ width: 7, height: 7, borderRadius: 999, background: dot, flexShrink: 0 }} />
                    {status}
                  </span>
                </span>
              </button>
              <div style={{ flexShrink: 0, paddingBottom: isNarrow ? 12 : 0, paddingLeft: isNarrow ? 26 : 0 }}>{action}</div>
            </div>

            {isOpen && (
              <div style={{ display: "grid", gridTemplateColumns: isNarrow ? "1fr" : "196px 1fr", gap: 18, padding: "4px 4px 18px 26px" }}>
                <div>
                  {!built ? (
                    <div style={{ ...previewBox, border: `1px dashed ${BORDER}`, background: "#f7f8fa", color: "#9aa0a6", fontSize: 11.5, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
                      The preview appears here once this document is drafted.
                    </div>
                  ) : pv?.state === "ok" && pv.url ? (
                    <>
                      <button type="button" onClick={() => void showPage(r.id, r.name, 1, pv.pages || 1)} title="Open it full size"
                        style={{ display: "block", width: "100%", padding: 0, border: "none", background: "none", cursor: "zoom-in" }}>
                        <img src={pv.url} alt={`First page of ${r.name}`} style={{ ...previewBox, objectFit: "contain", background: "#fff", display: "block" }} />
                      </button>
                      <div style={{ fontSize: 11, color: BLUE, marginTop: 5, textAlign: "center", fontWeight: 700 }}>
                        page 1 of {pv.pages || 1} · click to read it
                      </div>
                    </>
                  ) : pv?.state === "error" ? (
                    <div style={{ ...previewBox, border: `1px solid ${BORDER}`, background: "#fdf0e9", color: ORANGE, fontSize: 11.5, padding: 14, display: "flex", flexDirection: "column", gap: 8, alignItems: "center", justifyContent: "center", textAlign: "center" }}>
                      <span>Couldn&apos;t render the preview — {pv.msg}</span>
                      <button type="button" onClick={() => void loadPreview(r.id)} style={btn}>Try again</button>
                    </div>
                  ) : (
                    <div style={{ ...previewBox, border: `1px solid ${BORDER}`, background: "#f7f8fa", color: "#9aa0a6", fontSize: 11.5, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      Rendering page 1…
                    </div>
                  )}
                </div>

                <div>
                  {(() => {
                    const all = res?.defs || r.fieldDefs || fieldDefs;
                    const val = (k: string) => (res ? (res.fields[k] ?? "") : ((r.fields || {})[k] || ""));
                    // Tier on the axis she cares about — "what still needs me" —
                    // not on what the code happens to recognise. A field the form
                    // asks for and we refuse to guess is the MOST important thing
                    // on the row, not the least.
                    const needs = all.filter((f) => (f.tier === "extra" || f.tier === "known") && !val(f.key));
                    const filled = all.filter((f) => (f.tier === "extra" || f.tier === "known") && val(f.key));
                    const standard = all.filter((f) => f.tier === "standard");
                    const field = (fd: KitFieldDef) => {
                      const value = val(fd.key);
                      const derivedHere = !!res && res.derived.includes(fd.key) && !!value;
                      // A tick that came off the blank template is not "from the
                      // deal" — it is what the form already says. Saying so is
                      // the difference between a prefill she can trust and one
                      // she has to go open the PDF to check.
                      const fromForm = derivedHere && fd.type === "checkbox" && value === fd.default;
                      const fromDeal = derivedHere && !fromForm;
                      const label = (
                        <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3, fontWeight: 700 }}>
                          {fd.label}
                          {fd.page ? <span style={{ color: "#c2c8d4", fontWeight: 700 }}>p{fd.page}</span> : null}
                          {fromDeal && <span title="Filled in from the deal — type to override" style={{ color: BLUE, letterSpacing: 0.3 }}>from the deal</span>}
                          {fromForm && <span title="Already selected on the blank form — tap to change it" style={{ color: BLUE, letterSpacing: 0.3 }}>already on the form</span>}
                        </span>
                      );
                      if (fd.type === "checkbox") {
                        const opts = fd.options && fd.options.length ? fd.options : ["1"];
                        const named = fd.optionLabels || {};
                        const anyNamed = opts.some((o) => named[o]);
                        // Named options are sentences, not words ("My associate is
                        // buying, and I am providing them trading services"). Side
                        // by side they wrap into an unreadable hedge; one per line
                        // reads as the list of choices the form actually offers.
                        const stack = opts.some((o) => (named[o] || "").length > 24);
                        // On a disclosure the tick IS the disclosure, so an empty
                        // required group is called out here as well as before send.
                        const dep = fd.mustTickWhen;
                        const needed = !!fd.mustTick || (!!dep && dep.in.includes(val(dep.key)));
                        return (
                          <div key={fd.key} style={{ gridColumn: "1 / -1" }}>
                            {label}
                            {/* flex-start, not stretch: a full-width option reads
                                as a text input, which is what the row above it
                                actually is. Each choice hugs its own words. */}
                            <div style={{ display: "flex", gap: stack ? 5 : 8, flexWrap: "wrap", flexDirection: stack ? "column" : "row", alignItems: stack ? "flex-start" : "center" }}>
                              {opts.map((o) => {
                                const on = value === o;
                                return (
                                  <button key={o} type="button" role="checkbox" aria-checked={on}
                                    onClick={() => onSaveField(r.id, fd.key, on ? "" : o)}
                                    style={{ ...btn, minHeight: tap, display: "flex", alignItems: "center", gap: 8,
                                      textAlign: "left", fontWeight: on ? 700 : 500, lineHeight: 1.35,
                                      background: on ? NAVY : "#fff", color: on ? "#fff" : INK,
                                      borderColor: on ? "transparent" : BORDER_STRONG }}>
                                    <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: 4, flexShrink: 0, background: on ? "#fff" : "transparent", border: `1.5px solid ${on ? "#fff" : "#c9ced6"}`, color: NAVY, fontSize: 11, fontWeight: 900, lineHeight: "12px", textAlign: "center" }}>{on ? "✓" : ""}</span>
                                    {named[o] || (opts.length > 1 ? `Option ${o}` : "Tick")}
                                  </button>
                                );
                              })}
                              {!anyNamed && opts.length > 1 && (
                                <span style={{ fontSize: 11.5, color: MUTED, alignSelf: "center" }}>
                                  open the document to read which is which
                                </span>
                              )}
                            </div>
                            {needed && !value && (
                              <div style={{ fontSize: 11.5, color: ORANGE, marginTop: 5, fontWeight: 600 }}>
                                Nothing ticked — on this form the tick is the disclosure.
                              </div>
                            )}
                          </div>
                        );
                      }
                      return (
                        <label key={fd.key} style={{ display: "block", gridColumn: fd.multiline ? "1 / -1" : undefined }}>
                          {label}
                          {fd.multiline
                            ? <textarea key={value} defaultValue={value} rows={2}
                                onBlur={(e) => { if (e.target.value !== value) onSaveField(r.id, fd.key, e.target.value); }}
                                style={input} />
                            : <input key={value} defaultValue={value}
                                onBlur={(e) => { if (e.target.value !== value) onSaveField(r.id, fd.key, e.target.value); }}
                                style={input} />}
                        </label>
                      );
                    };
                    const grid = (list: KitFieldDef[]) => (
                      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: "10px 12px" }}>
                        {list.map(field)}
                      </div>
                    );
                    const head = (t: string) => (
                      <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 0.5, textTransform: "uppercase", color: MUTED, margin: "14px 0 6px" }}>{t}</div>
                    );
                    return (
                      <>
                        {needs.length > 0 && <>{head(`Needs your input · ${needs.length}`)}{grid(needs)}</>}
                        {filled.length > 0 && <>{head("Filled from the deal")}{grid(filled)}</>}
                        {standard.length > 0 && (
                          <>
                            <button type="button" onClick={() => setShowStd((p) => ({ ...p, [r.id]: !p[r.id] }))}
                              style={{ ...link, marginTop: 14 }}>
                              {showStd[r.id] ? "Hide" : "Show"} your details on this form ({standard.length})
                            </button>
                            {showStd[r.id] && grid(standard)}
                          </>
                        )}
                      </>
                    );
                  })()}
                  {(res?.defs || r.fieldDefs || fieldDefs).length === 0 && (
                    <div style={{ fontSize: 12.5, color: MUTED, padding: "2px 0 4px" }}>
                      Nothing on this form is filled from the deal — it is signed as-is.
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginTop: 12, paddingTop: 11, borderTop: `1px solid ${BORDER}` }}>
                    {built && <button type="button" onClick={() => onOpen(r.id)} style={link}>Open the full PDF</button>}
                    {built && <button type="button" onClick={() => onOpen(r.id, true)} style={link}>Download</button>}
                    {onExclude && !r.required && (
                      <button type="button" onClick={() => onExclude(r.id)} style={{ ...link, color: "#c0392b" }}>{excludeLabel}</button>
                    )}
                    <span style={{ fontSize: 12, color: "#9aa0a6" }}>
                      {footNote || "Edits save as you type. Anything you change is redrafted when you send."}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Portalled to document.body: the deal card's backdrop sets
          backdrop-filter, which makes it the containing block for any
          position:fixed descendant, and the modal itself is overflow-y:auto.
          Rendered in place, this overlay is positioned and clipped by the
          scrolling card and the page hides above the top edge. */}
      {zoom && createPortal(
        <div
          onClick={(e) => { if (e.target === e.currentTarget) closeZoom(); }}
          role="dialog"
          aria-modal="true"
          aria-label={`${zoom.name}, page ${zoom.page} of ${zoom.pages}`}
          style={{ position: "fixed", inset: 0, background: "rgba(15,20,32,.72)", zIndex: 9000, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: isMobile ? 10 : 26, gap: 12 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, color: "#fff", width: "100%", maxWidth: 900, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: 14, flex: 1, minWidth: 0 }}>{zoom.name}</span>
            <button type="button" onClick={() => onOpen(zoom.docId)} style={{ background: "transparent", border: "1px solid #ffffff55", color: "#fff", borderRadius: 8, padding: "7px 13px", fontWeight: 700, fontSize: 12.5, cursor: "pointer", minHeight: tap }}>Open the full PDF</button>
            <button type="button" onClick={closeZoom} aria-label="Close the viewer" style={{ background: "#fff", border: "none", color: INK, borderRadius: 8, padding: "7px 15px", fontWeight: 700, fontSize: 12.5, cursor: "pointer", minHeight: tap }}>Close</button>
          </div>
          <div style={{ flex: 1, minHeight: 0, width: "100%", overflow: "auto", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "2px 0" }}>
            {zoom.loading && !zoom.url ? (
              <span style={{ color: "#dfe5f0", fontSize: 13, margin: "auto" }}>Rendering page {zoom.page}…</span>
            ) : zoom.msg ? (
              <span style={{ color: "#ffd7c7", fontSize: 13, margin: "auto" }}>{zoom.msg}</span>
            ) : zoom.url ? (
              <img src={zoom.url} alt={`Page ${zoom.page} of ${zoom.name}`}
                style={{ width: "auto", maxWidth: "100%", height: "auto", display: "block", background: "#fff", borderRadius: 6, boxShadow: "0 18px 60px rgba(0,0,0,.45)", opacity: zoom.loading ? 0.55 : 1, transition: "opacity .15s ease" }} />
            ) : null}
          </div>
          {zoom.pages > 1 && (
            <div style={{ display: "flex", alignItems: "center", gap: 12, color: "#fff" }}>
              <button type="button" disabled={zoom.page <= 1} onClick={() => void showPage(zoom.docId, zoom.name, zoom.page - 1, zoom.pages)}
                style={{ background: "transparent", border: "1px solid #ffffff55", color: "#fff", borderRadius: 8, padding: "7px 15px", fontWeight: 700, fontSize: 13, cursor: zoom.page <= 1 ? "default" : "pointer", opacity: zoom.page <= 1 ? 0.4 : 1, minHeight: tap }}>← Back</button>
              <span style={{ fontSize: 13, fontWeight: 700, minWidth: 92, textAlign: "center" }}>page {zoom.page} of {zoom.pages}</span>
              <button type="button" disabled={zoom.page >= zoom.pages} onClick={() => void showPage(zoom.docId, zoom.name, zoom.page + 1, zoom.pages)}
                style={{ background: "transparent", border: "1px solid #ffffff55", color: "#fff", borderRadius: 8, padding: "7px 15px", fontWeight: 700, fontSize: 13, cursor: zoom.page >= zoom.pages ? "default" : "pointer", opacity: zoom.page >= zoom.pages ? 0.4 : 1, minHeight: tap }}>Next →</button>
            </div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}

// ── pre-send check ──────────────────────────────────────────────────────────
// A disclosure with nothing ticked looks finished from the outside: every text
// field is full, the PDF renders, the row says "Drafted". But a DORTS with
// neither "representing you" nor "not representing you" ticked discloses
// nothing, and that is the one thing on the form that had to be said. The last
// moment anyone looks at these documents is the send sheet, so the check lives
// there.
//
// Advisory, never blocking. There are legitimate reasons to send a form the
// client ticks themselves; the wrong failure mode here is a warning that stops
// a real send, not one that gets read and dismissed.
export type SendGap = { id: string; name: string; groups: { label: string; page?: number }[] };

const sessionToken = () =>
  (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";

export function useSendCheck(
  dealId: string,
  side: "buyer" | "listing" | "onboarding",
  docIds: string[],
  active: boolean,
): SendGap[] {
  const [gaps, setGaps] = useState<SendGap[]>([]);
  // A stable string, so the effect keys on the CONTENTS of the selection rather
  // than the array identity a parent re-render hands it.
  const key = docIds.slice().sort().join(" ");
  useEffect(() => {
    if (!active || !key) { setGaps([]); return; }
    let dropped = false;
    void (async () => {
      try {
        const r = await fetch(`/api/admin/deals/${dealId}/kit-send-check`, {
          method: "POST",
          headers: { Authorization: `Bearer ${sessionToken()}`, "Content-Type": "application/json" },
          body: JSON.stringify({ side, docIds: key.split(" ") }),
        });
        if (!r.ok) return;
        const body = await r.json().catch(() => null);
        if (!dropped && body && Array.isArray(body.documents)) setGaps(body.documents);
      } catch { /* advisory — a failed check never blocks the send sheet */ }
    })();
    return () => { dropped = true; };
  }, [dealId, side, key, active]);
  return gaps;
}

export function SendGapWarning({ gaps, nameOf }: {
  gaps: SendGap[];
  /** The name the send sheet is already showing for this document. The stored
   *  record often has no `name` and falls back to its id ("interest-in-trade"),
   *  which would make the warning describe a different-looking document than
   *  the row directly above it. */
  nameOf?: (id: string) => string | undefined;
}) {
  if (!gaps.length) return null;
  const n = gaps.reduce((a, g) => a + g.groups.length, 0);
  return (
    <div role="status" style={{ margin: "12px 0 2px", padding: "11px 13px", borderRadius: 9, background: "#fdf3ec", border: "1px solid #f0d3c1" }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#8a4a24" }}>
        {n === 1 ? "One question is unanswered" : `${n} questions are unanswered`}
      </div>
      <div style={{ fontSize: 12.5, color: "#8a4a24", marginTop: 5, lineHeight: 1.5 }}>
        {gaps.map((g) => (
          <div key={g.id} style={{ marginTop: 3 }}>
            <b>{(nameOf && nameOf(g.id)) || g.name}</b> — {g.groups.map((q) => q.label).join(" · ")}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12, color: "#9a6844", marginTop: 7 }}>
        On these forms the tick is the disclosure. Open the document to answer, or send as-is if the client fills it in.
      </div>
    </div>
  );
}

export function shortTime(iso: string): string {
  const t = new Date(iso);
  return isNaN(t.getTime()) ? "" : t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
