// Listing Kit wizard (listing/seller side) — the listing-side twin of the buyer
// Offer Kit wizard. 4 steps: Property & Records -> Listing Terms & Schedule A ->
// Forms -> Build & Sign. Selections persist to deals.extra_toggles_json via
// setAdminDealToggle (bare keys), and Build/Generate/Send hit the listing-kit
// backend endpoints (mirrors the offer-kit endpoints). Self-contained: uses raw
// fetch for the kit endpoints so it doesn't depend on api.ts additions (which
// keeps it deployable independently). Render from deal-modal for listing deals.
import { useState, useCallback } from "react";
import { api } from "../../../../lib/api";

type AnyObj = Record<string, any>;

const NAVY = "#21314f";
const ORANGE = "#C46340";
const GREEN = "#2f8a5b";
const BLUE = "#5E8AD0";
const INK = "#182848";
const MUTED = "#6b7280";
const BORDER = "#e3e6eb";

const STEPS = ["Property", "Listing Terms", "Forms", "Build & Sign"];

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
  { id: "schedule-a", label: "Schedule A — to the MLC" },
  { id: "dorts", label: "DORTS — Disclosure of Representation" },
  { id: "pnc", label: "PNC — Privacy Notice & Consent" },
  { id: "pds", label: "PDS — Property Disclosure Statement" },
  { id: "fintrac", label: "FINTRAC — Individual ID record" },
  { id: "mls-input", label: "MLS Data Input Sheet (AIR / Matrix)" },
];
const LISTING_FORM_DEFAULTS: Record<string, boolean> = {
  mlc: true, "schedule-a": true, dorts: true, pnc: true, pds: true, fintrac: true, "mls-input": false,
};

// Forms (Step 3) required by property type — pre-checked, with conditional notes.
const formsFor = (umbrella: string): { id: string; title: string; sub: string; on: boolean; cond?: string }[] => [
  { id: "pds", title: "Property Disclosure Statement (PDS)", sub: "Seller's disclosure of the property's condition.", on: true },
  { id: "dorts", title: "DORTS — Disclosure of Representation in Trading Services", sub: "Given to the sellers before providing services.", on: true },
  { id: "pnc", title: "PNC — Privacy Notice & Consent", sub: "Seller privacy consent.", on: true },
  { id: "fintrac", title: "FINTRAC — Individual ID (one per seller)", sub: "Identity verification record for each seller.", on: true },
  { id: "csa", title: "Manufactured Home — CSA / Registry disclosure", sub: "Pad rental, registration #, CSA label.", on: umbrella === "mobile", cond: "SUB-TYPE: MOBILE" },
  { id: "strata", title: "Strata Form B + bylaws + Form J", sub: "Strata documents.", on: umbrella === "strata" || umbrella === "bare-land-strata", cond: "SUB-TYPE: STRATA" },
];

export default function ListingKitWizard({
  dealId, extra, address, sellerName, currentStage, onUpdate,
}: {
  dealId: string; extra: AnyObj; address?: string; sellerName?: string;
  currentStage?: number; onUpdate?: () => void;
}) {
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
  const [expandedKit] = useState<string | null>(null);
  const [genBusy, setGenBusy] = useState<string | null>(null);

  const buildKit = useCallback(async () => {
    setBuilding(true); setBuiltMsg("");
    try {
      await api.setAdminDealToggle(dealId, "scheduleAClauses", Array.from(selected) as any).catch(() => {});
      await api.setAdminDealToggle(dealId, "scheduleACustomClauses", custom as any).catch(() => {});
      await fetch(`/api/admin/deals/${dealId}/listing-kit/build`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } });
      const enabled = LISTING_FORMS.filter((f) => f.required || (kitForms[f.id] ?? LISTING_FORM_DEFAULTS[f.id] ?? true)).map((f) => f.id);
      for (const id of enabled) {
        await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${id}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }).catch(() => {});
      }
      setBuiltMsg(`✓ Built ${enabled.length} documents into the listing package`);
      onUpdate?.();
    } finally { setBuilding(false); }
  }, [dealId, kitForms, onUpdate, selected, custom]);

  const openKitDoc = useCallback((docId: string, download = false) => {
    const o = window.location.origin;
    const ext = o.includes("127.0.0.1") ? o.replace("127.0.0.1", "localhost") : o.replace("localhost", "127.0.0.1");
    window.open(`${ext}/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}?token=${encodeURIComponent(tok())}&v=${Date.now()}${download ? "&download=1" : ""}`, "_blank", "noopener,noreferrer");
  }, [dealId]);
  const approveKitDoc = useCallback(async (docId: string, status: string) => {
    await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}/approve`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ status }) }).catch(() => {});
    onUpdate?.();
  }, [dealId, onUpdate]);
  const generateKitDoc = useCallback(async (docId: string) => {
    setGenBusy(docId);
    try { await fetch(`/api/admin/deals/${dealId}/listing-kit-doc/${encodeURIComponent(docId)}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }); onUpdate?.(); }
    finally { setGenBusy(null); }
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

  const Stepper = (
    <div style={{ display: "flex", alignItems: "center", margin: "4px 0 18px" }}>
      {STEPS.map((label, i) => {
        const n = i + 1, done = n < step, active = n === step;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : "0 0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <div style={{ width: 30, height: 30, borderRadius: 999, background: done ? GREEN : active ? ORANGE : "#e7eaef", color: done || active ? "#fff" : "#9aa0a6", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14, boxShadow: active ? `0 0 0 4px ${ORANGE}22` : "none", flexShrink: 0 }}>{done ? "✓" : n}</div>
              <span style={{ fontWeight: 700, fontSize: 14, color: done ? GREEN : active ? INK : "#9aa0a6", whiteSpace: "nowrap" }}>{label}</span>
            </div>
            {i < STEPS.length - 1 && <div style={{ flex: 1, height: 2, background: n < step ? GREEN : "#e7eaef", margin: "0 12px" }} />}
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
          <div><label style={{ display: "block", fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 4 }}>PROPERTY ADDRESS</label>
            <input defaultValue={address || ""} style={{ fontSize: 15, padding: "9px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK, width: 340 }} /></div>
          <button type="button" onClick={pullRecords} disabled={busy} style={{ padding: "10px 18px", borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: busy ? "default" : "pointer", border: "none", background: busy ? "#9aa6bd" : NAVY, color: "#fff" }}>{busy ? "Pulling…" : "Pull title, assessment & zoning"}</button>
        </div>
        <div style={{ display: "inline-block", background: busy ? "#eef2f9" : recordsPulled ? "#e7f4ec" : "#fdf0e9", color: busy ? NAVY : recordsPulled ? GREEN : ORANGE, fontWeight: 700, fontSize: 13, padding: "8px 14px", borderRadius: 8, marginBottom: 12 }}>
          {busy ? "Pulling from LTSA + BC Assessment + CityMap…" : recordsPulled ? "✓ Pulled · LTSA title + BC Assessment + CityMap zoning" : "Not pulled yet — pull above"}
        </div>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>PID</span><FromTag t="TITLE / LTSA" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("pid") || "—"}</div></div>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>LOT SIZE</span><FromTag t="BC ASSESSMENT" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("lotSize") || "—"}</div></div>
            <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>ASSESSMENT</span><FromTag t="BC ASSESSMENT" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("assessmentValue") || "—"}</div></div>
          </div>
          <div style={factBox}><div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700 }}>LEGAL DESCRIPTION</span><FromTag t="TITLE / LTSA" /></div><div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{fv("legalDescription") || fv("legal") || "—"}</div></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
          {cell("LIST PRICE", "listPrice", "$539,900")}
          {cell("LISTING COMMISSION", "listingCommission", "3.5% / 1.5%")}
          {cell("BUYER AGENCY COMP", "buyerAgencyComp", "3.255% / 1.1625%")}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
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
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Documents in the listing package</div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 14px" }}>Toggle which forms build. The MLC is always included. Add your own for anything outside the standard set.</div>
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 4 }}>STANDARD FORMS</div>
      <div>
        {LISTING_FORMS.map((f) => {
          const on = !!f.required || (kitForms[f.id] ?? LISTING_FORM_DEFAULTS[f.id] ?? true);
          return (
            <div key={f.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderTop: "1px solid #eef0f3" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <button type="button" onClick={() => toggleKitForm(f.id)} disabled={!!f.required} style={{ width: 44, height: 26, borderRadius: 999, border: "none", cursor: f.required ? "default" : "pointer", background: on ? BLUE : "#cdd2da", position: "relative", flexShrink: 0 }}>
                  <span style={{ position: "absolute", top: 3, left: on ? 21 : 3, width: 20, height: 20, borderRadius: 999, background: "#fff" }} />
                </button>
                <span style={{ fontWeight: 700, color: INK, fontSize: 14 }}>{f.label}</span>
              </div>
              {f.required && <span style={{ fontSize: 11, color: MUTED, fontWeight: 700, background: "#eef0f3", padding: "3px 9px", borderRadius: 6 }}>REQUIRED</span>}
            </div>
          );
        })}
      </div>

      {builtDocs.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 6 }}>BUILT DOCUMENTS · {builtDocs.filter((d) => d.ready).length} of {builtDocs.length} populated</div>
          {builtDocs.map((d) => {
            const approved = d.status === "approved", isOpen = expandedKit === d.id;
            return (
              <div key={d.id} style={{ borderTop: "1px solid #eef0f3" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "11px 0", opacity: d.ready ? 1 : 0.6 }}>
                  <div style={{ minWidth: 0 }}><div style={{ fontWeight: 600, color: INK, fontSize: 13 }}>{d.name}</div>
                    <div style={{ fontSize: 11, color: approved ? BLUE : d.ready ? ORANGE : "#9aa0a6", marginTop: 2, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{approved ? "Approved" : d.ready ? "Draft ready" : "Awaiting template"}</div></div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button type="button" onClick={() => generateKitDoc(d.id)} disabled={genBusy === d.id} style={kitBtn}>{genBusy === d.id ? "…" : "Generate"}</button>
                    <button type="button" onClick={() => openKitDoc(d.id)} style={kitBtn}>Open</button>
                    <button type="button" onClick={() => openKitDoc(d.id, true)} style={kitBtn}>Download</button>
                    <button type="button" onClick={() => approveKitDoc(d.id, approved ? "draft" : "approved")} style={{ ...kitBtn, background: approved ? BLUE : NAVY, color: "#fff", borderColor: "transparent" }}>{approved ? "Approved ✓" : "Approve"}</button>
                  </div>
                </div>
                {isOpen && <div />}
              </div>
            );
          })}
          <div style={{ marginTop: 16, background: "#f4f8f5", border: "1px solid #cfe6d8", borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ fontWeight: 700, color: "#1f5f3f", fontSize: 13.5 }}>Send to sellers for signature — review first</div>
            <div style={{ fontSize: 12.5, color: "#34684c", marginTop: 4 }}>Builds one DigiSign envelope (MLC + Schedule A + DORTS + PNC + PDS + FINTRAC) for {sellerName || "the sellers"}. You review the filled Preview before anything sends — same draft-first flow as the buyer side.</div>
            <div style={{ marginTop: 10 }}>
              <button type="button" onClick={sendForSign} disabled={sending} style={{ fontSize: 12.5, fontWeight: 700, color: "#fff", background: GREEN, border: "none", borderRadius: 7, padding: "8px 14px", cursor: "pointer" }}>{sending ? "Dispatching…" : "Approve & send for signatures →"}</button>
            </div>
            {sendMsg && <div style={{ marginTop: 8, fontSize: 12, color: "#1f5f3f", fontWeight: 600 }}>{sendMsg}</div>}
          </div>
        </div>
      )}
      {builtMsg && <div style={{ marginTop: 12, color: GREEN, fontWeight: 700, fontSize: 14 }}>{builtMsg}</div>}
    </div>
  );

  const navBtn: React.CSSProperties = { padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 15, cursor: "pointer", border: "none" };
  return (
    <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, background: "#fff" }}>
      {Header}
      <div style={{ padding: "18px 22px 20px" }}>
        <div style={{ fontWeight: 800, fontSize: 13, letterSpacing: 0.6, color: INK }}>BUILD LISTING KIT · STEP {step} OF 4</div>
        <div style={{ marginTop: 12 }}>{Stepper}</div>
        {step === 1 ? Step1 : step === 2 ? Step2 : step === 3 ? Step3 : Step4}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18 }}>
          {step > 1 ? <button type="button" onClick={() => setStep((s) => s - 1)} style={{ ...navBtn, background: "#fff", color: INK, border: `1px solid ${BORDER}` }}>← Back</button> : <span />}
          <button type="button" disabled={building} onClick={() => { if (step === 4) buildKit(); else setStep((s) => Math.min(4, s + 1)); }} style={{ ...navBtn, background: step === 4 ? GREEN : NAVY, color: "#fff", opacity: building ? 0.7 : 1 }}>
            {step === 1 ? "Continue to Listing Terms →" : step === 2 ? "Continue to Forms →" : step === 3 ? "Continue to Build →" : building ? "Building…" : "Build Listing Package"}
          </button>
        </div>
      </div>
    </section>
  );
}
