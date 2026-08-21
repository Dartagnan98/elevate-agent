// Brand — the kits everything generated is dressed in.
//
// A BRAND KIT is whose a document is: colours, two typefaces, logos, the signature
// block, and the brand's own rules. A THEME is how a page is built. They are kept
// apart on purpose, so one kit dresses the CMA, the listing graphics, the emails
// and the ads instead of each of those carrying its own copy of the palette.
//
// This page is for LOOKING, not configuring. Skyleigh asked for somewhere "people
// can visually see their brand guides and brand kits", so the palette is shown at a
// size you can actually judge, the typefaces are set in themselves, and each brand's
// own rules are printed as rules rather than buried in a document nobody opens.
// That last part matters: Elevation's guide says NO GREEN, and a guide that is not
// in front of you when you work is a guide that gets broken.
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useIsMobile } from "../hooks/useIsMobile";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#e3e7ef",
      TERRA = "#C46340", INK2 = "#4A5468";

type Swatch = { hex: string; label: string; use?: string };
type FontDef = { family: string; google?: string; use?: string };
type Kit = {
  id: string; name: string; tagline?: string;
  colors: Record<string, Swatch>;
  fonts: Record<string, FontDef>;
  assets?: Record<string, string>;
  assetsPresent?: Record<string, boolean>;
  contact?: Record<string, string>;
  rules?: string[];
};

// Load each kit's own faces so the specimens are set in the real typeface rather
// than described in words. Idempotent: a face already requested is not re-added.
function useKitFonts(kits: Kit[]) {
  useEffect(() => {
    const families = new Set<string>();
    for (const k of kits) {
      for (const f of Object.values(k.fonts || {})) if (f.google) families.add(f.google);
    }
    for (const fam of families) {
      const id = `kitfont-${fam.replace(/[^a-z0-9]/gi, "")}`;
      if (document.getElementById(id)) continue;
      const link = document.createElement("link");
      link.id = id;
      link.rel = "stylesheet";
      link.href = `https://fonts.googleapis.com/css2?family=${fam}&display=swap`;
      document.head.appendChild(link);
    }
  }, [kits]);
}

export default function BrandPage() {
  const isMobile = useIsMobile();
  const [kits, setKits] = useState<Kit[]>([]);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "none">("loading");

  const load = useCallback(async () => {
    try {
      const r = await api.getBrandKits();
      if (!r?.ok || !(r.kits || []).length) { setState("none"); return; }
      setKits(r.kits as Kit[]); setActive(r.active || ""); setState("ready");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load your brand kits.");
      setState("none");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useKitFonts(kits);

  const activate = async (id: string) => {
    setBusy(id); setErr("");
    try {
      const r = await api.activateBrandKit(id);
      if (r?.ok) setActive(r.active || id);
      else setErr(r?.error || "Could not switch kits.");
    } catch { setErr("Could not switch kits."); }
    finally { setBusy(""); }
  };

  if (state === "loading") {
    return <div style={{ padding: 24, fontSize: 13, color: MUTED }}>Loading your brand…</div>;
  }
  if (state === "none") {
    return (
      <div style={{ padding: 24, maxWidth: 620 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: NAVY, margin: "0 0 8px" }}>Brand</h1>
        <p style={{ fontSize: 14, color: MUTED, lineHeight: 1.6 }}>
          No brand kits yet. A kit holds your colours, your two typefaces, your logo and
          signature, and the rules your brand follows. Everything generated reads from it.
        </p>
        {err && <div style={{ marginTop: 10, fontSize: 13, color: "#9B3B2E" }}>{err}</div>}
      </div>
    );
  }

  const USES = ["CMA reports", "Listing graphics", "Just Listed / Open House", "Seller update emails",
                "Newsletters", "Paid ad creative", "Landing pages", "Email signature", "Feature sheets"];

  return (
    <div style={{ padding: isMobile ? "18px 14px 60px" : "26px 28px 80px", maxWidth: 1080 }}>
      <h1 style={{ fontSize: isMobile ? 22 : 26, fontWeight: 700, color: NAVY, margin: "0 0 6px" }}>Brand</h1>
      <p style={{ fontSize: 14.5, color: MUTED, lineHeight: 1.6, maxWidth: "68ch", margin: "0 0 8px" }}>
        Your brand kits. The one in use dresses everything generated from here: reports,
        graphics, emails, ads. Switch it once and they all follow.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 26 }}>
        {USES.map((u) => (
          <span key={u} style={{ fontSize: 11.5, color: INK2, background: "#F5F7FA",
                                 border: `1px solid ${LINE}`, borderRadius: 99, padding: "3px 10px" }}>{u}</span>
        ))}
      </div>

      {err && <div style={{ marginBottom: 14, fontSize: 13, color: "#9B3B2E" }}>{err}</div>}

      <div style={{ display: "grid", gap: 20 }}>
        {kits.map((k) => {
          const on = k.id === active;
          const display = k.fonts?.display, body = k.fonts?.body;
          const primary = k.colors?.primary?.hex || NAVY;
          const accent = k.colors?.accent?.hex || TERRA;
          return (
            <section key={k.id}
              style={{ border: `1px solid ${on ? accent : LINE}`, borderRadius: 14, overflow: "hidden",
                       background: "#fff", boxShadow: on ? `0 0 0 2px ${accent}22` : "none" }}>

              {/* the brand speaking in its own voice, not a form row */}
              <header style={{ background: primary, color: "#fff", padding: isMobile ? "18px 16px" : "22px 24px",
                               display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontFamily: display?.family ? `'${display.family}', Georgia, serif` : "inherit",
                                fontSize: isMobile ? 24 : 30, lineHeight: 1.1 }}>{k.name}</div>
                  {k.tagline && (
                    <div style={{ fontSize: 12.5, opacity: .82, marginTop: 5, letterSpacing: ".01em" }}>{k.tagline}</div>
                  )}
                </div>
                {on ? (
                  <span style={{ fontSize: 10.5, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase",
                                 background: accent, color: "#fff", borderRadius: 99, padding: "5px 12px" }}>In use</span>
                ) : (
                  <button type="button" onClick={() => void activate(k.id)} disabled={!!busy}
                    style={{ minHeight: 40, borderRadius: 8, border: "1px solid rgba(255,255,255,.5)",
                             background: "transparent", color: "#fff", font: "inherit", fontSize: 12.5,
                             fontWeight: 700, padding: "9px 16px", cursor: busy ? "default" : "pointer" }}>
                    {busy === k.id ? "Switching…" : "Use this kit"}
                  </button>
                )}
              </header>

              <div style={{ padding: isMobile ? 16 : 22, display: "grid", gap: 22 }}>

                {/* Palette, at a size you can judge. Each swatch says what it is FOR,
                    because "primary" means nothing when you are choosing a rule colour. */}
                <div>
                  <Label>Palette</Label>
                  <div style={{ display: "grid", gap: 10,
                                gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? 140 : 168}px, 1fr))` }}>
                    {Object.entries(k.colors || {}).map(([key, sw]) => (
                      <div key={key} style={{ border: `1px solid ${LINE}`, borderRadius: 9, overflow: "hidden" }}>
                        <div style={{ height: 52, background: sw.hex }} />
                        <div style={{ padding: "8px 10px" }}>
                          <div style={{ fontSize: 12.5, fontWeight: 700, color: NAVY }}>{sw.label}</div>
                          <div style={{ fontSize: 11, color: MUTED, fontVariantNumeric: "tabular-nums",
                                        textTransform: "uppercase", letterSpacing: ".04em" }}>{sw.hex}</div>
                          {sw.use && <div style={{ fontSize: 11, color: INK2, marginTop: 4, lineHeight: 1.4 }}>{sw.use}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Typefaces set in themselves. A font named in a list tells you nothing. */}
                <div>
                  <Label>Typefaces</Label>
                  <div style={{ display: "grid", gap: 12, gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
                    {[display, body].filter(Boolean).map((f, i) => (
                      <div key={i} style={{ border: `1px solid ${LINE}`, borderRadius: 9, padding: "13px 15px" }}>
                        <div style={{ fontFamily: `'${f!.family}', ${i === 0 ? "Georgia, serif" : "system-ui, sans-serif"}`,
                                      fontSize: i === 0 ? 30 : 21, color: NAVY, lineHeight: 1.15,
                                      fontWeight: i === 0 ? 600 : 700 }}>
                          9171 Knouff Lake Road
                        </div>
                        <div style={{ fontFamily: `'${f!.family}', ${i === 0 ? "Georgia, serif" : "system-ui, sans-serif"}`,
                                      fontSize: 13, color: INK2, marginTop: 6, lineHeight: 1.6 }}>
                          Prepared for you, with everything I know about your market in front of you.
                        </div>
                        <div style={{ fontSize: 11.5, color: MUTED, marginTop: 9 }}>
                          <b style={{ color: NAVY }}>{f!.family}</b>{f!.use ? ` · ${f!.use}` : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* The brand's own rules, in front of you. Elevation's says NO GREEN. */}
                {!!(k.rules || []).length && (
                  <div>
                    <Label>Rules</Label>
                    <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
                      {k.rules!.map((r, i) => (
                        <li key={i} style={{ fontSize: 13, lineHeight: 1.55, color: INK2 }}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div style={{ display: "grid", gap: 18, gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
                  {!!Object.keys(k.assets || {}).length && (
                    <div>
                      <Label>Assets</Label>
                      <div style={{ display: "grid", gap: 8 }}>
                        {Object.entries(k.assets || {}).map(([name, rel]) => {
                          const there = k.assetsPresent?.[name];
                          const isImg = /\.(png|jpe?g|svg|webp)$/i.test(rel);
                          return (
                            <div key={name} style={{ border: `1px solid ${LINE}`, borderRadius: 9, padding: 10,
                                                     display: "flex", gap: 11, alignItems: "center" }}>
                              {there && isImg ? (
                                <img src={api.brandAssetUrl(rel)} alt={name}
                                     style={{ width: 74, height: 44, objectFit: "contain",
                                              background: primary, borderRadius: 5, padding: 4 }} />
                              ) : (
                                <div style={{ width: 74, height: 44, borderRadius: 5, background: "#F5F7FA",
                                              border: `1px dashed ${LINE}`, display: "flex", alignItems: "center",
                                              justifyContent: "center", fontSize: 10, color: MUTED }}>
                                  {there ? "file" : "missing"}
                                </div>
                              )}
                              <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700, color: NAVY }}>{name}</div>
                                <div style={{ fontSize: 11, color: there ? MUTED : "#9B3B2E",
                                              wordBreak: "break-all", lineHeight: 1.4 }}>
                                  {there ? rel : `${rel} — not on disk`}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {!!Object.keys(k.contact || {}).length && (
                    <div>
                      <Label>Signature block</Label>
                      <div style={{ border: `1px solid ${LINE}`, borderRadius: 9, padding: "13px 15px" }}>
                        <div style={{ fontFamily: display?.family ? `'${display.family}', Georgia, serif` : "inherit",
                                      fontSize: 21, color: primary }}>{k.contact!.name}</div>
                        {k.contact!.title && (
                          <div style={{ fontSize: 11, letterSpacing: ".08em", textTransform: "uppercase",
                                        color: accent, marginTop: 3, fontWeight: 700 }}>{k.contact!.title}</div>
                        )}
                        <div style={{ fontSize: 12.5, color: INK2, marginTop: 8, lineHeight: 1.7 }}>
                          {[k.contact!.phone, k.contact!.email, k.contact!.website].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>

      <NewKit onSaved={() => void load()} isMobile={isMobile} />

      <p style={{ marginTop: 26, fontSize: 12.5, color: MUTED, lineHeight: 1.6, maxWidth: "66ch" }}>
        Kits live beside your brand assets in <code>knowledge/brand/kits/</code>, so the guide
        and the machine-readable version stay together.
      </p>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10.5, fontWeight: 900, letterSpacing: ".09em", textTransform: "uppercase",
                  color: MUTED, marginBottom: 10 }}>{children}</div>
  );
}


/* ─────────────────────────────────────────────────────────────────
   NewKit — add a brand by handing over a design.

   The honest version of what Skyleigh expected when she first dropped a PDF into
   the CMA wizard. The file is READ, never executed: colours are measured off the
   pixels, typefaces come from the PDF's own embedded font list, and everything
   lands in fields she can correct before anything is saved.

   Two things it tells the truth about rather than papering over:
   a design exported as flat images (a Canva or InDesign flatten, which is what
   hers is) carries no fonts to read, and the accent is the one genuinely
   interpretive guess, because a strong colour inside a photograph looks exactly
   like a brand colour to a pixel counter.
   ───────────────────────────────────────────────────────────────── */
function NewKit({ onSaved, isMobile }: { onSaved: () => void; isMobile: boolean }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"" | "reading" | "saving">("");
  const [err, setErr] = useState("");
  const [kit, setKit] = useState<Kit | null>(null);
  const [read, setRead] = useState<{ pages: number; textIsImages: boolean; note: string } | null>(null);

  const onFile = async (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) { setErr("Give it a PDF of the design."); return; }
    setBusy("reading"); setErr(""); setKit(null); setRead(null);
    try {
      const b64: string = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result || "").split(",")[1] || "");
        r.onerror = () => rej(new Error("Could not read that file"));
        r.readAsDataURL(f);
      });
      const r = await api.extractBrandKit(f.name, b64);
      if (r?.ok && r.proposed) {
        setKit(r.proposed as Kit);
        if (r.readFrom) setRead({ pages: r.readFrom.pages, textIsImages: r.readFrom.textIsImages, note: r.readFrom.note });
      } else setErr(r?.error || "Could not read that design.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read that design.");
    } finally { setBusy(""); }
  };

  const setColor = (key: string, hex: string) =>
    setKit((k) => k ? { ...k, colors: { ...k.colors, [key]: { ...k.colors[key], hex } } } : k);
  const setFont = (role: string, family: string) =>
    setKit((k) => k ? { ...k, fonts: { ...k.fonts, [role]: {
      ...(k.fonts[role] || {}), family,
      google: family.trim().replace(/\s+/g, "+") + (role === "display" ? ":wght@500;600" : ":wght@400;700"),
    } } } : k);

  const save = async () => {
    if (!kit) return;
    setBusy("saving"); setErr("");
    try {
      const r = await api.saveBrandKit(kit as never);
      if (r?.ok) { setKit(null); setRead(null); setOpen(false); onSaved(); }
      else setErr(r?.error || "Could not save that kit.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save that kit.");
    } finally { setBusy(""); }
  };

  const field: React.CSSProperties = {
    font: "inherit", fontSize: 13, padding: "8px 10px", borderRadius: 7,
    border: `1px solid ${LINE}`, background: "#fff", color: NAVY, width: "100%", boxSizing: "border-box",
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        style={{ marginTop: 20, width: "100%", textAlign: "left", font: "inherit",
                 border: `1px dashed ${LINE}`, borderRadius: 14, background: "#fff",
                 padding: "20px 22px", cursor: "pointer" }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: NAVY }}>Add a brand</div>
        <div style={{ fontSize: 13, color: MUTED, marginTop: 4, lineHeight: 1.55, maxWidth: "60ch" }}>
          Upload a design and it reads the colours and typefaces back for you to confirm.
        </div>
      </button>
    );
  }

  return (
    <section style={{ marginTop: 20, border: `1px solid ${LINE}`, borderRadius: 14, background: "#fff", overflow: "hidden" }}>
      <header style={{ padding: "14px 18px", borderBottom: `1px solid ${LINE}`, background: "#F5F7FA",
                       display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1, fontSize: 14.5, fontWeight: 700, color: NAVY }}>Add a brand</div>
        <button type="button" onClick={() => { setOpen(false); setKit(null); setErr(""); }}
          style={{ font: "inherit", fontSize: 12.5, fontWeight: 600, color: MUTED,
                   background: "none", border: "none", cursor: "pointer", minHeight: 40 }}>Cancel</button>
      </header>

      <div style={{ padding: isMobile ? 16 : 20, display: "grid", gap: 18 }}>
        {!kit && (
          <div>
            <label style={{ display: "inline-block", cursor: busy ? "default" : "pointer" }}>
              <input type="file" accept="application/pdf" disabled={!!busy}
                onChange={(e) => void onFile(e.target.files)} style={{ display: "none" }} />
              <span style={{ display: "inline-flex", alignItems: "center", minHeight: 44, padding: "11px 18px",
                             borderRadius: 8, background: busy ? "#D8B7A6" : TERRA, color: "#fff",
                             fontSize: 13, fontWeight: 800 }}>
                {busy === "reading" ? "Reading the design…" : "Choose a design PDF"}
              </span>
            </label>
            <div style={{ fontSize: 12.5, color: MUTED, marginTop: 10, lineHeight: 1.6, maxWidth: "62ch" }}>
              Any PDF of the brand: a report, a one-pager, a brand guide. The colours are
              measured off the pages and the typefaces are read from the file itself. Nothing
              is saved until you have looked at it.
            </div>
          </div>
        )}

        {kit && (
          <>
            {read && (
              <div style={{ background: read.textIsImages ? "#FDF6EC" : "#EAF0F9",
                            border: `1px solid ${read.textIsImages ? "#EBD2A8" : "#C7D6EC"}`,
                            borderRadius: 9, padding: "11px 13px", fontSize: 12.5,
                            lineHeight: 1.55, color: read.textIsImages ? "#6E4409" : "#2C4A7C" }}>
                Read {read.pages} page{read.pages === 1 ? "" : "s"}. {read.note}
              </div>
            )}

            <div style={{ display: "grid", gap: 12, gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
              <label><Label>Name</Label>
                <input value={kit.name} style={field}
                  onChange={(e) => setKit({ ...kit, name: e.target.value })} /></label>
              <label><Label>Short id</Label>
                <input value={kit.id} style={field}
                  onChange={(e) => setKit({ ...kit, id: e.target.value })} /></label>
            </div>

            <div>
              <Label>Colours it found</Label>
              <div style={{ display: "grid", gap: 10,
                            gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? 150 : 180}px, 1fr))` }}>
                {Object.entries(kit.colors || {}).map(([key, sw]) => (
                  <div key={key} style={{ border: `1px solid ${LINE}`, borderRadius: 9, overflow: "hidden" }}>
                    <div style={{ height: 44, background: sw.hex }} />
                    <div style={{ padding: "8px 10px" }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: NAVY }}>{sw.label}</div>
                      <input value={sw.hex} onChange={(e) => setColor(key, e.target.value)}
                        aria-label={`${sw.label} colour`}
                        style={{ ...field, marginTop: 5, fontSize: 12, textTransform: "uppercase",
                                 fontVariantNumeric: "tabular-nums" }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <Label>Typefaces</Label>
              <div style={{ display: "grid", gap: 12, gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
                {(["display", "body"] as const).map((role) => (
                  <label key={role}>
                    <div style={{ fontSize: 12, color: MUTED, marginBottom: 5 }}>
                      {role === "display" ? "Display, for names and headings" : "Body, for everything else"}
                    </div>
                    <input value={kit.fonts?.[role]?.family || ""} placeholder="e.g. Cormorant Garamond"
                      onChange={(e) => setFont(role, e.target.value)} style={field} />
                  </label>
                ))}
              </div>
              {read?.textIsImages && (
                <div style={{ fontSize: 12, color: MUTED, marginTop: 8, lineHeight: 1.5 }}>
                  This design has no readable text, so type the two typefaces in yourself.
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <button type="button" onClick={() => void save()} disabled={!!busy}
                style={{ minHeight: 44, border: "none", borderRadius: 8, padding: "11px 20px",
                         font: "inherit", fontSize: 13, fontWeight: 800,
                         background: busy ? "#D8B7A6" : TERRA, color: "#fff",
                         cursor: busy ? "default" : "pointer" }}>
                {busy === "saving" ? "Saving…" : "Save this kit"}
              </button>
              <button type="button" onClick={() => { setKit(null); setRead(null); }} disabled={!!busy}
                style={{ minHeight: 44, border: `1px solid #C7D6EC`, borderRadius: 8, padding: "11px 16px",
                         font: "inherit", fontSize: 13, fontWeight: 700, background: "transparent",
                         color: "#3F6BB8", cursor: "pointer" }}>
                Try another design
              </button>
            </div>
          </>
        )}

        {err && <div style={{ fontSize: 12.5, color: "#9B3B2E", lineHeight: 1.5 }}>{err}</div>}
      </div>
    </section>
  );
}
