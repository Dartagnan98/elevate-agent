// Listing Kit wizard (listing/seller side) — the listing-side twin of the buyer
// Offer Kit wizard. 4 steps: Property & Records -> Listing Terms & Schedule A ->
// Forms -> Build & Sign. Selections persist to deals.extra_toggles_json via
// setAdminDealToggle (bare keys), and Build/Generate/Send hit the listing-kit
// backend endpoints (mirrors the offer-kit endpoints). Self-contained: uses raw
// fetch for the kit endpoints so it doesn't depend on api.ts additions (which
// keeps it deployable independently). Render from deal-modal for listing deals.
import { useState, useCallback } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import KitDocumentList, { type KitDocState, type KitFieldDef, useSendCheck, SendGapWarning } from "./kit-document-list";

type AnyObj = Record<string, any>;

// These hexes were the app's de-facto design reference: Skyleigh reviewed this
// wizard on 2026-07-27 and approved its colours, so the global tokens in
// src/elevate-design-system.css were derived FROM them. Now pointed back at
// those tokens so the wizard and the rest of the dashboard cannot drift apart
// again (and so this surface picks up dark theme, which hardcoding blocked).
const NAVY = "var(--ds-navy-surface)";
const ORANGE = "var(--ds-terracotta)";
const GREEN = "var(--ds-done)";
const BLUE = "var(--ds-blue)";
const INK = "var(--ds-ink)";
const MUTED = "var(--ds-muted)";
const BORDER = "var(--ds-border)";

// Fields editable per listing document, mirroring the MLC / Schedule-A context.
const LISTING_DOC_FIELDS: KitFieldDef[] = [
  { key: "seller1", label: "Seller 1" }, { key: "seller2", label: "Seller 2" },
  { key: "property", label: "Property address" }, { key: "listPrice", label: "List price ($)" },
  { key: "listPriceWords", label: "Price in words" }, { key: "listingCommission", label: "Listing commission" },
  { key: "buyerAgencyComp", label: "Buyer agency compensation" }, { key: "listingDate", label: "Listing date" },
  { key: "expiryDate", label: "Expiry date" }, { key: "designatedAgency", label: "Designated agency" },
  { key: "pid", label: "PID" }, { key: "zoning", label: "Zoning" },
  { key: "legal", label: "Legal description", multiline: true },
];

// Intake paths write the sellers' names to different keys. Reading only one is
// how the buyer side ended up saying "the buyer(s)" on live deals — same fix.
function resolveSellerNames(extra: AnyObj, passed?: string, dealTitle?: string): string {
  const clean = (v: unknown) => String(v ?? "").trim();
  const flatten = (v: unknown): string => {
    if (Array.isArray(v)) return v.map((x) => clean(typeof x === "string" ? x : (x as AnyObj)?.name)).filter(Boolean).join(" & ");
    if (v && typeof v === "object") return clean((v as AnyObj).name);
    // Several keys store "A; B" rather than a list.
    return clean(v).split(";").map((x) => x.trim()).filter(Boolean).join(" & ");
  };
  for (const c of [passed, extra.sellerNames, extra.sellerPreferredNames, extra["seller.preferredNames"],
                   extra.sellerLegalNames, extra["seller.legalNames"], extra.skyslopeSellerNames,
                   extra.skyslopeSellerNamesRaw, extra.registeredOwner, extra.profileDisplayName]) {
    const v = flatten(c);
    if (v) return v;
  }
  return clean(dealTitle).replace(/^listing:\s*/i, "").replace(/,.*$/, "").trim();
}

const STEPS = ["Property", "Listing Terms", "Forms", "Documents"];

const LISTING_TYPES: { id: string; label: string }[] = [
  { id: "residential", label: "Residential (Freehold)" },
  { id: "strata", label: "Strata" },
  { id: "mobile", label: "Mobile / Manufactured" },
  { id: "rural", label: "Rural / Acreage" },
  { id: "lot", label: "Vacant Lot" },
  { id: "bare-land-strata", label: "Bareland Strata" },
];

// Schedule A clauses — each agent's standard listing terms that print into
// Schedule A of the MLC. Default set; the picker also pulls saved clauses.
const SCHEDULE_A_CLAUSES: { id: string; title: string; wording: string; default?: boolean }[] = [
  { id: "collapsed-sale", title: "Commission earned on a collapsed / fallen-through sale", wording: "Commission is earned if an accepted offer collapses due to seller default.", default: true },
  { id: "marketing", title: "Marketing & advertising authorization", wording: "Authorizes signage, MLS, social, and online marketing of the property.", default: true },
  { id: "lockbox", title: "Lockbox & showing access", wording: "Seller consents to a lockbox and reasonable showing access.", default: true },
  { id: "measurement", title: "Measurement & square-footage disclaimer", wording: "Measurements are approximate; buyer to verify if important.", default: true },
  { id: "media-ownership", title: "Photography & listing-media ownership", wording: "Listing photos & media remain the property of the brokerage." },
  { id: "dual-agency-ack", title: "Designated agency acknowledgement", wording: "Seller acknowledges the designated agency relationship and its limits." },
];

// Forms the listing package can build (Step 4). MLC is always included.
const LISTING_FORMS: { id: string; label: string; required?: boolean }[] = [
  { id: "mlc", label: "MLC — Multiple Listing Contract", required: true },
  { id: "dorts", label: "DORTS — Disclosure of Representation" },
  { id: "pnc", label: "PNC — Privacy Notice & Consent" },
  // The PDS variant is chosen automatically from the listing sub-type above
  // (residential / strata / bare-land strata / rural / lot). Mobile uses the
  // Residential PDS — BCREA publishes no manufactured-specific one.
  { id: "pds", label: "PDS — Property Disclosure Statement" },
  { id: "pds-rural-addendum", label: "PDS — Rural Premises Addendum" },
  { id: "pds-no-disclosure", label: "Property NO-Disclosure Statement" },
  // No MLS Data Input Sheet (AIR/Matrix board form, not BCREA) and no Subject
  // Removal (Skyleigh uses the Notice of Condition Waiver instead) — 2026-07-27.
  // Anything else goes through Add a form below.
];
// No FINTRAC: Skyleigh does not do FINTRAC on a form any more (2026-07-27).
const LISTING_FORM_DEFAULTS: Record<string, boolean> = {
  mlc: true, dorts: true, pnc: true, pds: true,
  "pds-rural-addendum": false, "pds-no-disclosure": false,
};

// Forms (Step 3) required by property type — pre-checked, with conditional notes.
const formsFor = (umbrella: string): { id: string; title: string; sub: string; on: boolean; cond?: string }[] => [
  { id: "pds", title: "Property Disclosure Statement (PDS)", sub: "Seller's disclosure of the property's condition.", on: true },
  { id: "dorts", title: "DORTS — Disclosure of Representation in Trading Services", sub: "Given to the sellers before providing services.", on: true },
  { id: "pnc", title: "PNC — Privacy Notice & Consent", sub: "Seller privacy consent.", on: true },
  // No FINTRAC row: identity verification still happens, but it is not a form
  // Skyleigh fills or sends any more (2026-07-27).
  { id: "csa", title: "Manufactured Home — CSA / Registry disclosure", sub: "Pad rental, registration #, CSA label.", on: umbrella === "mobile", cond: "SUB-TYPE: MOBILE" },
  { id: "strata", title: "Strata Form B + bylaws + Form J", sub: "Strata documents.", on: umbrella === "strata" || umbrella === "bare-land-strata", cond: "SUB-TYPE: STRATA" },
];

export default function ListingKitWizard({
  dealId, extra, address, sellerName, dealTitle, currentStage, onUpdate,
}: {
  dealId: string; extra: AnyObj; address?: string; sellerName?: string; dealTitle?: string;
  currentStage?: number; onUpdate?: () => void;
}) {
  const isMobile = useIsMobile();
  // Fixed multi-column field grids collapse to one column on a phone (CSS media
  // queries can't reach these inline styles).
  const cols = (n: number) => (isMobile ? "1fr" : Array(n).fill("1fr").join(" "));
  const [step, setStep] = useState(1);
  const [umbrella, setUmbrella] = useState<string>((extra.listingUmbrella as string) || "residential");
  const accepted = (currentStage ?? 0) >= 5; // listing live / accepted offer -> minimize
  const [manualCollapse, setManualCollapse] = useState<boolean | null>(null);
  const collapsed = manualCollapse !== null ? manualCollapse : (currentStage ?? 0) >= 5;
  const setCollapsed = setManualCollapse;
  const tok = () => (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";

  // ── Schedule A clause selection (Step 2) ──
  const savedClauses: string[] = Array.isArray(extra.scheduleAClauses) ? (extra.scheduleAClauses as string[]) : [];
  const savedCustom: AnyObj[] = Array.isArray(extra.scheduleACustomClauses) ? (extra.scheduleACustomClauses as AnyObj[]) : [];
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(savedClauses.length ? savedClauses : SCHEDULE_A_CLAUSES.filter((c) => c.default).map((c) => c.id)),
  );
  const [custom, setCustom] = useState<AnyObj[]>(savedCustom);
  const [newClause, setNewClause] = useState("");
  const persistClauses = useCallback((sel: Set<string>, cust: AnyObj[]) => {
    api.setAdminDealToggle(dealId, "scheduleAClauses", Array.from(sel) as any).catch(() => {});
    api.setAdminDealToggle(dealId, "scheduleACustomClauses", cust as any).catch(() => {});
  }, [dealId]);
  const toggleClause = (id: string) => setSelected((prev) => {
    const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); persistClauses(next, custom); return next;
  });
  const addCustom = () => {
    const t = newClause.trim(); if (!t) return;
    const next = [...custom, { id: "sa-custom-" + Date.now(), title: "Custom clause", wording: t }];
    setCustom(next); setNewClause(""); persistClauses(selected, next);
  };

  // ── property type ──
  const saveUmbrella = useCallback((u: string) => {
    setUmbrella(u);
    api.setAdminDealToggle(dealId, "listingUmbrella", u).then(() => onUpdate?.()).catch(() => {});
  }, [dealId, onUpdate]);

  // ── record pull (Step 1) ──
  const [pulling, setPulling] = useState(false);
  const recordsPulled = !!(extra.pid || extra.legalDescription || extra.legal);
  const pullStatus = (extra.recordsPullStatus as string) || "";
  const pullRecords = useCallback(async () => {
    setPulling(true);
    await fetch(`/api/admin/deals/${dealId}/listing-pull-records`, {
      method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" },
    }).catch(() => {});
    let n = 0;
    const poll = setInterval(() => { n += 1; onUpdate?.(); if (n > 30) { clearInterval(poll); setPulling(false); } }, 6000);
  }, [dealId, onUpdate]);
  const busy = pulling || pullStatus === "pulling";

  // ── terms (Step 2) — save any term to a bare key the MLC/Schedule-A fill read ──
  const saveField = useCallback((key: string, value: string) => {
    api.setAdminDealToggle(dealId, key, value.trim() || null).catch(() => {});
  }, [dealId]);

  // ── build (Step 4) ──
  const [kitForms, setKitForms] = useState<Record<string, boolean>>(
    () => (extra.listingKitForms as Record<string, boolean>) || { ...LISTING_FORM_DEFAULTS },
  );
  const toggleKitForm = (id: string) => {
    if (id === "mlc") return;
    setKitForms((p) => { const next = { ...p, [id]: !(p[id] ?? LISTING_FORM_DEFAULTS[id] ?? true) }; api.setAdminDealToggle(dealId, "listingKitForms", next as any).catch(() => {}); return next; });
  };
  const [building, setBuilding] = useState(false);
  const [builtMsg, setBuiltMsg] = useState("");
  const builtDocs: AnyObj[] = ((extra as AnyObj).listingKit?.documents) || [];
  const [genBusy, setGenBusy] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [showExcluded, setShowExcluded] = useState(false);
  const isNarrow = useIsMobile(900);
  const tap = isMobile ? 44 : undefined;
  const sellerLabel = resolveSellerNames(extra, sellerName, dealTitle) || "the sellers";

  // A doc is stale when its fields were edited after the PDF was drafted.
  const docIsStale = (d?: AnyObj) => !!d?.editedAt && (!d.generatedAt || d.editedAt > d.generatedAt);
  const kitIncluded = (id: string) => {
    const std = LISTING_FORMS.find((f) => f.id === id);
    if (!std) return true;              // anything added or uploaded is in by existing
    if (std.required) return true;
    return kitForms[id] ?? LISTING_FORM_DEFAULTS[id] ?? true;
  };
  const rowStateOf = (id: string): KitDocState => {
    const d = builtDocs.find((x) => x.id === id);
    if (genBusy === id || (building && !d?.filePath)) return "building";
    if (!kitIncluded(id)) return "excluded";
    if (!d || !d.filePath) return "unbuilt";
    return docIsStale(d) ? "stale" : "ready";
  };
  const allRows: { id: string; name: string; required?: boolean }[] = [
    ...LISTING_FORMS.map((f) => ({ id: f.id, name: f.label, required: f.required })),
    ...builtDocs
      .filter((d) => !LISTING_FORMS.some((f) => f.id === d.id))
      .map((d) => ({ id: d.id as string, name: (d.name as string) || (d.id as string) })),
  ];
  const includedRows = allRows.filter((r) => kitIncluded(r.id));
  const excludedRows = allRows.filter((r) => !kitIncluded(r.id));
  const needsDraft = includedRows.filter((r) => ["unbuilt", "stale"].includes(rowStateOf(r.id)));
  const sendable = includedRows.filter((r) => rowStateOf(r.id) === "ready");
  // Seller-side twin of the buyer kit's pre-send check: which of these would go
  // out with a disclosure question unanswered. Above the `if (collapsed)`
  // early-return, or the hook count changes between renders.
  const sendGaps = useSendCheck(dealId, "listing", sendable.map((r) => r.id), sendOpen);
  const saveKitField = useCallback((docId: string, key: string, value: string) => {
    fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}/field`, {
      method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }).catch(() => {});
  }, [dealId]);
  const linkBtn: React.CSSProperties = { background: "none", border: "none", padding: 0, color: BLUE, fontWeight: 700, fontSize: 12.5, cursor: "pointer", font: "inherit", minHeight: tap };

  const buildKit = useCallback(async () => {
    setBuilding(true); setBuiltMsg("");
    try {
      await api.setAdminDealToggle(dealId, "scheduleAClauses", Array.from(selected) as any).catch(() => {});
      await api.setAdminDealToggle(dealId, "scheduleACustomClauses", custom as any).catch(() => {});
      const buildRes = await fetch(`/api/admin/deals/${dealId}/listing-kit/build`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }).catch(() => null);
      if (!buildRes || !buildRes.ok) {
        const detail = buildRes ? await buildRes.text().catch(() => "") : "no response";
        setBuiltMsg(`✗ Build failed — ${String(detail).slice(0, 160) || "could not seed the listing kit"}`);
        return;
      }
      const enabled = LISTING_FORMS.filter((f) => f.required || (kitForms[f.id] ?? LISTING_FORM_DEFAULTS[f.id] ?? true)).map((f) => f.id);
      // Record the ACTUAL result per form. This used to report "✓ Built N documents"
      // unconditionally while every call 404'd, so a build that did nothing looked
      // like a success. Forms with no filler wired yet are counted separately from
      // real failures.
      const failed: string[] = [];
      const notWired: string[] = [];
      const warns: string[] = [];
      for (const id of enabled) {
        const r = await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${id}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }).catch(() => null);
        if (!r) { failed.push(id); continue; }
        if (r.status === 400) { notWired.push(id); continue; }
        if (!r.ok) { failed.push(id); continue; }
        const body = await r.json().catch(() => ({} as any));
        if (Array.isArray(body?.warnings) && body.warnings.length) {
          warns.push(...body.warnings.map((w: string) => `${id}: ${w}`));
        }
      }
      const ok = enabled.length - failed.length - notWired.length;
      const bits: string[] = [];
      if (notWired.length) bits.push(`${notWired.length} not wired yet (${notWired.join(", ")})`);
      if (warns.length) bits.push(`${warns.length} blank to complete: ${warns.join("; ")}`);
      if (failed.length) {
        setBuiltMsg(`⚠ Built ${ok} of ${enabled.length} — ${failed.length} failed (${failed.join(", ")})${bits.length ? ". " + bits.join(". ") : ""}`);
      } else if (bits.length) {
        // A checkmark on zero built documents reads as success. It is not.
        setBuiltMsg(`${ok > 0 ? "✓" : "⚠"} Built ${ok} of ${enabled.length} — ${bits.join(". ")}`);
      } else {
        setBuiltMsg(`✓ Built ${ok} documents into the listing package`);
      }
      onUpdate?.();
    } finally { setBuilding(false); }
  }, [dealId, kitForms, onUpdate, selected, custom]);

  const openKitDoc = useCallback((docId: string, download = false) => {
    const o = window.location.origin;
    const ext = o.includes("127.0.0.1") ? o.replace("127.0.0.1", "localhost") : o.replace("localhost", "127.0.0.1");
    window.open(`${ext}/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}?token=${encodeURIComponent(tok())}&v=${Date.now()}${download ? "&download=1" : ""}`, "_blank");
  }, [dealId]);
  const generateKitDoc = useCallback(async (docId: string) => {
    setGenBusy(docId);
    try { await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }); onUpdate?.(); }
    finally { setGenBusy(null); }
  }, [dealId, onUpdate]);
  // ── Add a form (Step 4) — catalog + upload, mirrors the offer kit ──
  const [addFormOpen, setAddFormOpen] = useState(false);
  const [addingForm, setAddingForm] = useState(false);
  const [addMsg, setAddMsg] = useState("");
  type CatForm = { id: string; label: string; available: boolean; reason?: string };
  const [catalog, setCatalog] = useState<CatForm[]>([]);
  const loadCatalog = useCallback(async () => {
    const r = await fetch(`/api/admin/deals/${dealId}/listing-kit/catalog`, { headers: { Authorization: `Bearer ${tok()}` } }).catch(() => null);
    if (!r || !r.ok) return;
    const b = await r.json().catch(() => null);
    if (b?.forms) setCatalog(b.forms as CatForm[]);
  }, [dealId]);
  const addCatalogForm = useCallback(async (templateId: string, name: string) => {
    setAddingForm(true); setAddMsg("");
    try {
      const r = await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/add`, {
        method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" },
        body: JSON.stringify({ templateId, name }),
      }).catch(() => null);
      if (r?.ok) { setAddMsg(`✓ Added ${name}. Hit Generate on it to fill it.`); onUpdate?.(); }
      else {
        const e = r ? await r.json().catch(() => null) : null;
        setAddMsg((e && e.detail) || "Couldn't add that form.");
      }
    } finally { setAddingForm(false); }
  }, [dealId, onUpdate]);
  const uploadForm = useCallback(async (file: File) => {
    setAddingForm(true); setAddMsg("");
    try {
      const b64 = await new Promise<string>((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result).split(",")[1] || "");
        fr.onerror = rej;
        fr.readAsDataURL(file);
      });
      const r = await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/add`, {
        method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, contentB64: b64 }),
      }).catch(() => null);
      if (r?.ok) { setAddMsg(`✓ Added ${file.name}.`); setAddFormOpen(false); onUpdate?.(); }
      else {
        const e = r ? await r.json().catch(() => null) : null;
        setAddMsg((e && e.detail) || "Couldn't upload that file.");
      }
    } finally { setAddingForm(false); }
  }, [dealId, onUpdate]);

  // Draft-first send to sellers (mirrors onboarding-sign on the buyer side).
  const [sendMsg, setSendMsg] = useState("");
  const [sending, setSending] = useState(false);
  const sendForSign = useCallback(async () => {
    setSending(true); setSendMsg("");
    try {
      const r = await fetch(`/api/admin/deals/${dealId}/listing-sign`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } });
      setSendMsg(r.ok ? "Listing package dispatched — you'll get a Review & approve card with the Preview before anything sends to the sellers." : "Could not dispatch. Try again.");
      onUpdate?.();
    } catch { setSendMsg("Could not dispatch. Try again."); } finally { setSending(false); }
  }, [dealId, onUpdate]);

  const mls = (extra.mlsNumber as string) || "";
  const fv = (k: string) => (extra[k] as string) || "";

  // ── styles ──
  const panel: React.CSSProperties = { border: `1px solid ${BORDER}`, borderRadius: 12, padding: "18px 20px", marginTop: 14 };
  const fieldLabel: React.CSSProperties = { display: "block", fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 5 };
  const ci: React.CSSProperties = { width: "100%", boxSizing: "border-box", fontSize: 15, padding: "10px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK, fontFamily: "inherit" };
  const factBox: React.CSSProperties = { background: "#f7f8fa", border: `1px solid ${BORDER}`, borderRadius: 8, padding: "10px 12px" };
  const FromTag = ({ t }: { t: string }) => <span style={{ color: BLUE, fontWeight: 700, fontSize: 11, letterSpacing: 0.4 }}>{t}</span>;
  const cell = (label: string, key: string, ph: string) => (
    <div key={key}><label style={fieldLabel}>{label}</label>
      <input defaultValue={fv(key)} placeholder={ph} onBlur={(e) => saveField(key, e.target.value)} style={ci} /></div>
  );

  const Header = (
    <div style={{ background: NAVY, color: "#fff", padding: "18px 22px", borderRadius: "12px 12px 0 0", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 19 }}>{address || "Property"} — Listing Kit</div>
        <div style={{ fontSize: 13, color: "#aeb8cc", marginTop: 3 }}>{LISTING_TYPES.find((t) => t.id === umbrella)?.label}{mls ? ` · MLS ${mls}` : ""}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <span style={{ background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 12, letterSpacing: 0.5, padding: "5px 12px", borderRadius: 999, whiteSpace: "nowrap" }}>LISTING INTAKE</span>
        <button type="button" onClick={() => setCollapsed(true)} title="Minimize" style={{ background: "transparent", border: "1px solid #ffffff44", color: "#fff", borderRadius: 7, padding: "4px 11px", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>▴</button>
      </div>
    </div>
  );

  if (collapsed) {
    return (
      <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, overflow: "hidden" }}>
        <button type="button" onClick={() => setCollapsed(false)} style={{ width: "100%", background: NAVY, color: "#fff", border: "none", padding: "13px 22px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", textAlign: "left" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{address || "Property"} — Listing Kit</div>
            <div style={{ fontSize: 12, color: "#aeb8cc", marginTop: 2 }}>{accepted ? "Listing live · package on file" : (address || "property")}</div>
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#cdd5e4" }}>▾</span>
        </button>
      </section>
    );
  }

  // Breadcrumb, not four equal circles — completed steps recede and the deal
  // card's sticky header can no longer slice the rail in half on scroll.
  const stepComplete = (n: number) =>
    n === 1 ? recordsPulled
    : n === 2 ? !!(fv("listPrice") && fv("listingDate"))
    : n === 3 ? true
    : false;
  const Stepper = (
    <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", margin: "0 0 16px" }}>
      {STEPS.map((label, i) => {
        const n = i + 1, active = n === step, done = stepComplete(n) && !active;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button type="button" onClick={() => setStep(n)} aria-current={active ? "step" : undefined}
              title={`Go to step ${n}: ${label}`}
              style={{ display: "flex", alignItems: "center", gap: 6, border: "none", cursor: "pointer", font: "inherit",
                padding: "6px 10px", borderRadius: 7, minHeight: tap ? 40 : undefined,
                background: active ? "#fff" : "transparent",
                boxShadow: active ? "0 1px 2px rgba(24,40,72,.09)" : "none",
                color: active ? INK : MUTED, fontWeight: active ? 800 : 600, fontSize: 13, whiteSpace: "nowrap" }}>
              {done && <span style={{ color: GREEN, fontWeight: 800 }}>✓</span>}
              {label}
            </button>
            {i < STEPS.length - 1 && <span style={{ color: "#c9ced6", fontSize: 11 }}>›</span>}
          </div>
        );
      })}
    </div>
  );

  // ── Step 1: Property & Records ──
  const Step1 = (
    <>
      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Property type &amp; template</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 14px" }}>Sets which listing contract gets filled and which forms apply to this listing.</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {LISTING_TYPES.map((t) => {
            const sel = umbrella === t.id;
            return <button key={t.id} type="button" onClick={() => saveUmbrella(t.id)} style={{ padding: "10px 16px", borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: "pointer", border: `1px solid ${sel ? ORANGE : BORDER}`, background: sel ? ORANGE : "#fff", color: sel ? "#fff" : INK }}>{t.label}</button>;
          })}
        </div>
      </div>
      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Pull property records</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 12px" }}>One pull grabs the LTSA title (PID + legal), BC Assessment value &amp; lot size, and zoning — so the MLC and MLS sheet fill themselves.</div>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
          <div style={{ flex: isMobile ? "1 1 100%" : "0 1 auto", minWidth: 0 }}><label style={{ display: "block", fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 4 }}>PROPERTY ADDRESS</label>
            <input defaultValue={address || ""} style={{ fontSize: 15, padding: "9px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK, width: isMobile ? "100%" : 340, maxWidth: "100%", boxSizing: "border-box" }} /></div>
          <button type="button" onClick={pullRecords} disabled={busy} style={{ padding: "10px 18px", borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: busy ? "default" : "pointer", border: "none", background: busy ? "#9aa6bd" : NAVY, color: "#fff" }}>{busy ? "Pulling…" : "Pull title, assessment & zoning"}</button>
        </div>
        <div style={{ display: "inline-block", background: busy ? "#eef2f9" : recordsPulled ? "#e7f4ec" : "#fdf0e9", color: busy ? NAVY : recordsPulled ? GREEN : ORANGE, fontWeight: 700, fontSize: 13, padding: "8px 14px", borderRadius: 8, marginBottom: 12 }}>
          {busy ? "Pulling from LTSA + BC Assessment + CityMap…" : recordsPulled ? "✓ Pulled · LTSA title + BC Assessment + CityMap zoning" : "Not pulled yet — pull above"}
        </div>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 10 }}>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>PID</span><FromTag t="TITLE / LTSA" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("pid") || "—"}</div></div>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>LOT SIZE</span><FromTag t="BC ASSESSMENT" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("lotSize") || "—"}</div></div>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>ASSESSMENT</span><FromTag t="BC ASSESSMENT" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("assessmentValue") || "—"}</div></div>
          </div>
          <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>LEGAL DESCRIPTION</span><FromTag t="TITLE / LTSA" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("legalDescription") || fv("legal") || "—"}</div></div>
          <div style={{ display: "grid", gridTemplateColumns: cols(2), gap: 10 }}>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>ZONING</span><FromTag t="CITYMAP" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("zoning") || "—"}</div></div>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>REGISTERED OWNER</span><FromTag t="TITLE / LTSA" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("registeredOwner") || sellerName || "—"}</div></div>
          </div>
        </div>
      </div>
    </>
  );

  // ── Step 2: Listing Terms & Schedule A ──
  const Step2 = (
    <>
      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Listing terms</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 16px" }}>Seller names pull from the card; PID &amp; legal from the title. Just the listing numbers here — everything saves as you type.</div>
        <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14, marginBottom: 14 }}>
          {cell("LIST PRICE", "listPrice", "$539,900")}
          {cell("LISTING COMMISSION", "listingCommission", "3.5% / 1.5%")}
          {cell("BUYER AGENCY COMP", "buyerAgencyComp", "3.255% / 1.1625%")}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14 }}>
          {cell("LISTING DATE", "listingDate", "Jul 2")}
          {cell("EXPIRY DATE", "expiryDate", "Oct 2")}
          {cell("DESIGNATED AGENCY", "designatedAgency", "Skyleigh McCallum")}
        </div>
      </div>
      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Schedule A — your terms &amp; conditions</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 4px" }}>The big clause section on the MLC. Your standard listing clauses are pre-checked — tick what applies, write your own, or pull from saved clauses. These print into Schedule A of the contract.</div>
        <div>
          {SCHEDULE_A_CLAUSES.map((c) => {
            const checked = selected.has(c.id);
            return (
              <div key={c.id} style={{ padding: "12px 0", borderTop: "1px solid #eef0f3", display: "flex", gap: 12, alignItems: "flex-start", cursor: "pointer" }} onClick={() => toggleClause(c.id)}>
                <div style={{ width: 24, height: 24, borderRadius: 6, flexShrink: 0, marginTop: 1, background: checked ? GREEN : "#fff", border: `1px solid ${checked ? GREEN : "#c9ced6"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14 }}>{checked ? "✓" : ""}</div>
                <div style={{ minWidth: 0 }}><div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>{c.title}</div><div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{c.wording}</div></div>
              </div>
            );
          })}
          {custom.map((c) => (
            <div key={c.id} style={{ padding: "12px 0", borderTop: "1px solid #eef0f3", display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{ width: 24, height: 24, borderRadius: 6, flexShrink: 0, background: GREEN, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14 }}>✓</div>
              <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>Custom clause</div><div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{c.wording}</div></div>
              <button type="button" onClick={() => { const next = custom.filter((x) => x.id !== c.id); setCustom(next); persistClauses(selected, next); }} style={{ background: "none", border: "none", color: "#9aa0a6", cursor: "pointer", fontSize: 18, fontWeight: 700 }}>×</button>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${BORDER}` }}>
          <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 8 }}>+ ADD YOUR OWN CLAUSE</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={newClause} onChange={(e) => setNewClause(e.target.value)} placeholder="Type a clause to add to Schedule A…" style={{ flex: 1, fontSize: 14, padding: "9px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK }} />
            <button type="button" onClick={addCustom} style={{ padding: "9px 18px", borderRadius: 8, fontWeight: 700, border: `1px solid ${ORANGE}`, background: "#fff", color: ORANGE, cursor: "pointer" }}>Add</button>
          </div>
        </div>
      </div>
    </>
  );

  // ── Step 3: Forms ──
  const Step3 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Forms for this listing · {LISTING_TYPES.find((t) => t.id === umbrella)?.label}</div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 4px" }}>The standard forms for this property type are pre-checked. Untick anything that doesn't apply, or add your own.</div>
      <div>
        {formsFor(umbrella).map((f) => (
          <div key={f.id} style={{ padding: "12px 0", borderTop: "1px solid #eef0f3", display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, flexShrink: 0, background: f.on ? GREEN : "#fff", border: `1px solid ${f.on ? GREEN : "#c9ced6"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14 }}>{f.on ? "✓" : ""}</div>
            <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>{f.title}</div><div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{f.sub}</div></div>
            {f.cond && f.on && <span style={{ fontSize: 10.5, fontWeight: 800, color: ORANGE, background: "#fdf1e9", borderRadius: 5, padding: "2px 8px" }}>{f.cond}</span>}
          </div>
        ))}
      </div>
    </div>
  );

  // ── Step 4: Build & Sign ──
  const kitBtn: React.CSSProperties = { fontSize: 12, padding: "5px 13px", borderRadius: 7, border: `1px solid #d4d8de`, background: "#fff", color: INK, cursor: "pointer", fontWeight: 600 };
  const Step4 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>
        Documents{sellerLabel ? ` for ${sellerLabel}` : " in the listing package"}
      </div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 10px" }}>
        {building || genBusy
          ? "Drafting…"
          : needsDraft.length === 0 && sendable.length > 0
            ? `All ${sendable.length} drafted and ready to send.`
            : `${sendable.length} drafted. ${needsDraft.length} still to draft.`}
      </div>

      <KitDocumentList
        rows={includedRows.map((r) => ({
          id: r.id,
          name: r.name,
          required: r.required,
          state: rowStateOf(r.id),
          generatedAt: builtDocs.find((d) => d.id === r.id)?.generatedAt,
          fields: builtDocs.find((d) => d.id === r.id)?.fields,
        }))}
        fieldDefs={LISTING_DOC_FIELDS}
        previewUrl={(id, page, dpi) =>
          `/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(id)}/preview?page=${page}&dpi=${dpi}&v=${Date.now()}`}
        fieldsUrl={(id) => `/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(id)}/fields?v=${Date.now()}`}
        onDraft={(id) => void generateKitDoc(id)}
        onOpen={(id, download) => openKitDoc(id, download)}
        onSaveField={saveKitField}
        onExclude={(id) => toggleKitForm(id)}
        isMobile={isMobile}
        isNarrow={isNarrow}
      />

      {/* Not in this package: one line, not a row each. */}
      {excludedRows.length > 0 && (
        <div style={{ borderTop: "1px solid #eef0f3", padding: "12px 4px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 13, color: MUTED }}>
              {excludedRows.length} form{excludedRows.length === 1 ? "" : "s"} not in this package
            </span>
            <button type="button" onClick={() => setShowExcluded((v) => !v)} style={linkBtn}>
              {showExcluded ? "Hide" : "Show"}
            </button>
          </div>
          {showExcluded && excludedRows.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
              <span style={{ fontSize: 13.5, color: "#9aa0a6" }}>{r.name}</span>
              <button type="button" onClick={() => toggleKitForm(r.id)} style={kitBtn}>Add to the package</button>
            </div>
          ))}
        </div>
      )}

      {/* Add a form */}
      <div style={{ borderTop: "1px solid #eef0f3" }}>
        {!addFormOpen ? (
          <button type="button" onClick={() => { setAddFormOpen(true); void loadCatalog(); }} style={{ width: "100%", padding: "13px 0", display: "flex", alignItems: "center", gap: 13, color: MUTED, background: "none", border: "none", cursor: "pointer", textAlign: "left", minHeight: tap }}>
            <span style={{ width: 21, height: 21, borderRadius: 6, background: NAVY, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700, flexShrink: 0 }}>+</span>
            <span>
              <span style={{ display: "block", fontSize: 14, fontWeight: 600, color: INK }}>Add a form</span>
              <span style={{ display: "block", fontSize: 12.5, marginTop: 2 }}>Amendments, seller disclosures, or upload your own PDF</span>
            </span>
          </button>
        ) : (
          <div style={{ padding: "14px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontWeight: 700, color: INK, fontSize: 14 }}>Add a form</span>
              <button type="button" onClick={() => setAddFormOpen(false)} aria-label="Close" style={{ background: "none", border: "none", color: MUTED, cursor: "pointer", fontSize: 18, minHeight: tap, minWidth: tap }}>×</button>
            </div>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: addingForm ? "default" : "pointer", border: `1px solid ${NAVY}`, color: NAVY, borderRadius: 8, padding: "9px 16px", fontWeight: 700, fontSize: 14, marginBottom: 14, minHeight: tap }}>
              {addingForm ? "Adding…" : "⬆ Upload a PDF"}
              <input type="file" accept="application/pdf" disabled={addingForm} onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadForm(f); }} style={{ display: "none" }} />
            </label>
            {catalog.length > 0 && (
              <>
                <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, margin: "4px 0 6px" }}>OR PICK FROM THE CATALOG</div>
                {catalog.filter((f) => !builtDocs.some((d) => d.id === f.id)).map((f) => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
                    <span style={{ fontSize: 14, color: f.available ? INK : "#9aa0a6", fontWeight: 600 }}>{f.label}</span>
                    {f.available
                      ? <button type="button" disabled={addingForm} onClick={() => void addCatalogForm(f.id, f.label)} style={kitBtn}>Add</button>
                      : <span title={f.reason} style={{ fontSize: 11, color: ORANGE, fontWeight: 700, whiteSpace: "nowrap" }}>NO TEMPLATE YET</span>}
                  </div>
                ))}
              </>
            )}
            {addMsg && <div style={{ marginTop: 10, fontSize: 13, color: addMsg.startsWith("✓") ? GREEN : ORANGE, fontWeight: 600 }}>{addMsg}</div>}
          </div>
        )}
      </div>

      {/* Two actions, permanently distinct. */}
      {!sendOpen && (
        <div style={{ display: "flex", gap: 11, flexWrap: "wrap", alignItems: "center", marginTop: 18, paddingTop: 16, borderTop: `1px solid ${BORDER}` }}>
          {needsDraft.length > 0 && (
            <button type="button" disabled={building} onClick={() => void buildKit()}
              style={{ padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 14.5, border: `1px solid ${BORDER}`, background: "#fff", color: INK, cursor: building ? "default" : "pointer", opacity: building ? 0.65 : 1, minHeight: tap }}>
              {building ? "Drafting…" : `Draft the ${needsDraft.length} remaining`}
            </button>
          )}
          <button type="button" disabled={building || sendable.length === 0} onClick={() => setSendOpen(true)}
            style={{ padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 14.5, border: "none", color: "#fff", cursor: sendable.length === 0 ? "default" : "pointer", minHeight: tap,
              background: sendable.length === 0 || building ? "#9aa6bd" : ORANGE }}>
            {sendable.length ? `Send ${sendable.length} for signature` : "Send for signature"}
          </button>
          <div style={{ flexBasis: "100%", fontSize: 12.5, color: MUTED }}>
            One DigiSign envelope for {sellerLabel}. You review the filled preview before anything sends.
          </div>
        </div>
      )}

      {sendOpen && (
        <div style={{ marginTop: 16, border: `1px solid ${BORDER}`, borderRadius: 11, background: "#fbfcfe", padding: "16px 18px" }}>
          <div style={{ fontSize: 14.5, fontWeight: 700, color: INK }}>Send to {sellerLabel}?</div>
          <div style={{ fontSize: 13, color: MUTED, margin: "4px 0 11px" }}>
            One DigiSign envelope for {address || "this listing"}. Everything drafted is listed below.
          </div>
          {sendable.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: GREEN, flexShrink: 0 }} />
              <span style={{ fontSize: 14, fontWeight: 600, color: INK }}>{r.name}</span>
            </div>
          ))}
          <SendGapWarning gaps={sendGaps} nameOf={(id) => sendable.find((r) => r.id === id)?.name} />
          <div style={{ display: "flex", gap: 9, marginTop: 14, alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" onClick={() => setSendOpen(false)} style={kitBtn}>Cancel</button>
            <button type="button" disabled={sending} onClick={() => { setSendOpen(false); void sendForSign(); }}
              style={{ ...kitBtn, background: ORANGE, borderColor: "transparent", color: "#fff", padding: "9px 16px", fontSize: 13.5 }}>
              {sending ? "Dispatching…" : `Send ${sendable.length} to ${sellerLabel}`}
            </button>
            <span style={{ fontSize: 12.5, color: MUTED }}>Nothing sends — it lands as a review card first.</span>
          </div>
        </div>
      )}

      {builtMsg && <div style={{ marginTop: 12, color: builtMsg.startsWith("\u2713") ? GREEN : ORANGE, fontWeight: 700, fontSize: 14 }}>{builtMsg}</div>}
      {sendMsg && <div style={{ marginTop: 10, fontSize: 13, color: GREEN, fontWeight: 600 }}>{sendMsg}</div>}
    </div>
  );

  const navBtn: React.CSSProperties = { padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 15, cursor: "pointer", border: "none" };
  return (
    <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, background: "#fff" }}>
      {Header}
      <div style={{ padding: "18px 22px 20px" }}>
        <div>{Stepper}</div>
        {step === 1 ? Step1 : step === 2 ? Step2 : step === 3 ? Step3 : Step4}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18 }}>
          {step > 1 ? <button type="button" onClick={() => setStep((s) => s - 1)} style={{ ...navBtn, background: "#fff", color: INK, border: `1px solid ${BORDER}` }}>← Back</button> : <span />}
          {step < 4 && (
            <button type="button" onClick={() => setStep((s) => Math.min(4, s + 1))} style={{ ...navBtn, background: NAVY, color: "#fff" }}>
              {step === 1 ? "Continue to Listing Terms →" : step === 2 ? "Continue to Forms →" : "Continue to Documents →"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
