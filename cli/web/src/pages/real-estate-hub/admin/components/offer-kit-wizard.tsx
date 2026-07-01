// Offer Kit wizard (buyer side) — replaces the old OfferPrepPanel + kit list with
// a 4-step flow: Property -> Terms -> Subjects -> Build & Preview. Step 1 here;
// later steps land incrementally. Selections persist to deals.extra_toggles_json
// via setAdminDealToggle (bare keys), so the existing backend reads them as-is.
import { useState, useCallback, useEffect } from "react";
import { api } from "../../../../lib/api";
import { clauseLibrary } from "../cps/cps-libraries";
import ClausePickerModal from "./clause-picker-modal";

type AnyObj = Record<string, any>;

// Clause selection (Step 3) — ported from OfferPrepPanel so the wizard reads the
// same per-umbrella clause library + saves the same keys (cpsClauses, cpsVars,
// cpsCustomClauses) that the CPS assembler consumes.
const UNIVERSAL = new Set(["common-subject", "buyer-specific", "standard-clause"]);
const VAR_LABELS: Record<string, string> = {
  pds_date: "PDS date", inspection_cap: "Inspection cap $", park_name: "Park name",
  monthly_strata_fee: "Monthly strata fee $", pad_rental_amount: "Pad rent $",
  municipality: "Municipality", buyer_property_address: "Buyer's property address",
  buyer_sale_date: "Buyer's sale date", additional_buyer_name: "Additional buyer name",
  meet_greet_date: "Meet & greet date", tenant_name: "Tenant name", monthly_rent: "Monthly rent $",
  security_deposit: "Security deposit $", strata_minutes_start_date: "Minutes from",
  strata_minutes_end_date: "Minutes to", radius_km: "Force-majeure radius (km)",
  prior_offer_collapse_date: "Prior offer collapse-by date",
};
const VAR_DEFAULTS: Record<string, string> = { inspection_cap: "1,000" };
const VAR_SKIP = new Set(["subject_removal_date"]);
function clauseVisible(clause: AnyObj, umbrella: string, udef: AnyObj): boolean {
  const id = clause.id, sec = clause.section;
  if ((udef.default_clauses || []).includes(id)) return true;
  if ((udef.available_extra || []).includes(id)) return true;
  if (UNIVERSAL.has(sec)) return true;
  if (sec === "rural") return umbrella === "residential" || umbrella === "rural" || umbrella === "lot";
  if (sec === "new-construction") return umbrella === "pre-con";
  if (sec === "strata") return umbrella === "strata" || umbrella === "bare-land-strata";
  if (sec === "manufactured") return umbrella === "mobile";
  return false;
}

const NAVY = "#21314f";
const ORANGE = "#C46340";
const GREEN = "#2f8a5b";
const BLUE = "#5E8AD0";
const INK = "#182848";
const MUTED = "#6b7280";
const BORDER = "#e3e6eb";

const STEPS = ["Property", "Terms", "Subjects", "Build & Preview"];

const PROPERTY_TYPES: { id: string; label: string }[] = [
  { id: "residential", label: "Residential (Freehold)" },
  { id: "strata", label: "Strata" },
  { id: "mobile", label: "Mobile / Manufactured" },
  { id: "rural", label: "Rural / Acreage" },
  { id: "lot", label: "Vacant Lot" },
  { id: "bare-land-strata", label: "Bareland Strata" },
  { id: "pre-con", label: "New Construction" },
];

// The forms the kit can build (Step 4). cps-residential is always included.
const KIT_FORMS: { id: string; label: string; required?: boolean }[] = [
  { id: "cps-residential", label: "CPS — Contract of Purchase & Sale", required: true },
  { id: "cps-addendum", label: "CPS — Addendum / Amendment" },
  { id: "bcfsa-disclosure", label: "DORTS — Disclosure of Representation" },
  { id: "privacy-notice", label: "PNC — Privacy Notice & Consent" },
  { id: "disclosure-remuneration", label: "Disclosure of Remuneration" },
  { id: "condition-waiver", label: "Notice of Condition Waiver" },
];
const KIT_FORM_DEFAULTS: Record<string, boolean> = {
  "cps-residential": true, "cps-addendum": true, "bcfsa-disclosure": true,
  "privacy-notice": true, "disclosure-remuneration": false, "condition-waiver": true,
};

export default function OfferKitWizard({
  dealId,
  extra,
  address,
  buyerName,
  currentStage,
  onUpdate,
}: {
  dealId: string;
  extra: AnyObj;
  address?: string;
  buyerName?: string;
  currentStage?: number;
  onUpdate?: () => void;
}) {
  const [step, setStep] = useState(1);
  const [umbrella, setUmbrella] = useState<string>((extra.cpsUmbrella as string) || "residential");
  // Offer Prep (stage 0) shows the full wizard. Once the offer is accepted
  // (stage >= 1) it minimizes to a slim bar — the kit's built, no need for the
  // wizard open. Click the bar to reopen it anytime.
  // Derive collapsed from the stage every render (so it reacts when ctx loads
  // late), unless the operator has manually toggled it — then honor their choice.
  // Pipeline: 0 Client Onboarding · 1 Offer Prep · 2 Accepted · 3+ later.
  // Open only at Offer Prep (stage 1); minimized during Onboarding and after.
  // Expand with the ▾ arrow anytime. Manual toggle wins, derived every render.
  const accepted = (currentStage ?? 0) >= 2;
  const [manualCollapse, setManualCollapse] = useState<boolean | null>(null);
  const collapsed = manualCollapse !== null ? manualCollapse : (currentStage ?? 0) !== 1;
  const setCollapsed = setManualCollapse;

  // ── clause selection (Step 3) ──
  const allClauses: AnyObj[] = (clauseLibrary.clauses as AnyObj[]) || [];
  const defaultsFor = (u: string): string[] => ((clauseLibrary.umbrellas as AnyObj)?.[u]?.default_clauses as string[]) || [];
  const savedClauses: string[] = Array.isArray(extra.cpsClauses) ? (extra.cpsClauses as string[]) : [];
  const savedCustom: AnyObj[] = Array.isArray(extra.cpsCustomClauses) ? (extra.cpsCustomClauses as AnyObj[]) : [];
  const [selectedClauses, setSelectedClauses] = useState<Set<string>>(
    () => new Set(savedClauses.length ? savedClauses : defaultsFor((extra.cpsUmbrella as string) || "residential")),
  );
  const [customClauses, setCustomClauses] = useState<AnyObj[]>(savedCustom);
  const [cpsVars, setCpsVars] = useState<AnyObj>((extra.cpsVars as AnyObj) || {});
  const [showMoreClauses, setShowMoreClauses] = useState(false);
  const [newClause, setNewClause] = useState("");
  const persistClauses = useCallback((sel: Set<string>, custom: AnyObj[]) => {
    api.setAdminDealToggle(dealId, "cpsClauses", Array.from(sel) as any).catch(() => {});
    api.setAdminDealToggle(dealId, "cpsCustomClauses", custom as any).catch(() => {});
  }, [dealId]);
  const toggleClause = (id: string) => {
    setSelectedClauses((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      persistClauses(next, customClauses);
      return next;
    });
  };
  const saveVar = (key: string, value: string) => {
    setCpsVars((prev) => { const next = { ...prev, [key]: value }; api.setAdminDealToggle(dealId, "cpsVars", next as any).catch(() => {}); return next; });
  };
  const addCustomClause = () => {
    const t = newClause.trim(); if (!t) return;
    const next = [...customClauses, { id: "custom-" + Date.now(), title: "Custom clause", wording: t }];
    setCustomClauses(next); setNewClause(""); persistClauses(selectedClauses, next);
  };
  // Persist the pre-checked defaults on first open so cpsClauses reflects the UI
  // (the assembler reads cpsClauses, not the in-memory pre-checks).
  useEffect(() => {
    if (!savedClauses.length && selectedClauses.size) persistClauses(selectedClauses, customClauses);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // "Insert Clauses" popup — browse the whole library by folder. System = the
  // curated/BCREA-scraped library; Office/Personal fill in as they're added.
  const [clausePickerOpen, setClausePickerOpen] = useState(false);
  // Pull the scraped WEBForms library (Personal/Office/System) for the popup.
  const [wfFolders, setWfFolders] = useState<{ key: string; label: string; clauses: AnyObj[] }[] | null>(null);
  useEffect(() => {
    const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    fetch("/api/admin/clause-library", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((d) => {
        const f = (d && d.folders) || {};
        setWfFolders([
          { key: "personal", label: "Personal Clauses", clauses: f.personal || [] },
          { key: "office", label: "Office Clauses", clauses: f.office || [] },
          { key: "system", label: "System Clauses", clauses: f.system || [] },
        ]);
      })
      .catch(() => {});
  }, []);
  const clauseFolders = wfFolders || [
    { key: "personal", label: "Personal Clauses", clauses: [] },
    { key: "office", label: "Office Clauses", clauses: [] },
    { key: "system", label: "System Clauses", clauses: allClauses },
  ];
  // A clause in the curated library (assembler knows its id) is added by id; a
  // scraped clause rides along as a custom clause carrying its own wording.
  const insertClauses = (clauses: AnyObj[]) => {
    const libIds = new Set((allClauses as AnyObj[]).map((c) => c.id));
    setSelectedClauses((prev) => {
      const nextSel = new Set(prev);
      const nextCustom = [...customClauses];
      for (const c of clauses) {
        if (libIds.has(c.id)) nextSel.add(c.id);
        else if (!nextCustom.some((x) => x.id === c.id)) nextCustom.push({ id: c.id, title: c.title, wording: c.primary_wording || c.wording || "" });
      }
      setCustomClauses(nextCustom);
      persistClauses(nextSel, nextCustom);
      return nextSel;
    });
  };

  // ── build (Step 4) ──
  const [kitForms, setKitForms] = useState<Record<string, boolean>>(
    () => (extra.cpsKitForms as Record<string, boolean>) || { ...KIT_FORM_DEFAULTS },
  );
  const toggleKitForm = (id: string) => {
    if (id === "cps-residential") return; // always included
    setKitForms((p) => { const next = { ...p, [id]: !(p[id] ?? KIT_FORM_DEFAULTS[id] ?? true) }; api.setAdminDealToggle(dealId, "cpsKitForms", next as any).catch(() => {}); return next; });
  };
  const [building, setBuilding] = useState(false);
  const [builtMsg, setBuiltMsg] = useState("");
  const buildKit = useCallback(async () => {
    const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    setBuilding(true); setBuiltMsg("");
    try {
      // Make sure the current subject selection is saved before we assemble it.
      await api.setAdminDealToggle(dealId, "cpsClauses", Array.from(selectedClauses) as any).catch(() => {});
      await api.setAdminDealToggle(dealId, "cpsCustomClauses", customClauses as any).catch(() => {});
      await fetch(`/api/admin/deals/${dealId}/offer-kit/build`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
      const enabled = KIT_FORMS.filter((f) => f.required || (kitForms[f.id] ?? KIT_FORM_DEFAULTS[f.id] ?? true)).map((f) => f.id);
      for (const id of enabled) {
        await fetch(`/api/admin/deals/${dealId}/kit-doc/${id}/generate`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }).catch(() => {});
      }
      setBuiltMsg(`✓ Built ${enabled.length} documents into the kit`);
      onUpdate?.();
    } finally { setBuilding(false); }
  }, [dealId, kitForms, onUpdate, selectedClauses, customClauses]);

  // ── built kit documents (Step 4, post-build) ─────────────────────────────
  // Folded in from the old standalone "Transaction Kit" card so build + open +
  // edit + approve all live inside the wizard. Self-contained handlers (same
  // endpoints the card used) so deal-modal no longer renders a second surface.
  type KitDoc = { id: string; name: string; status?: string; ready?: boolean; fields?: Record<string, string> };
  const builtDocs: KitDoc[] = ((extra as unknown as { offerKit?: { documents?: KitDoc[] } }).offerKit?.documents) || [];
  const [expandedKit, setExpandedKit] = useState<string | null>(null);
  const [generatingKit, setGeneratingKit] = useState<string | null>(null);
  const tok = () => (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
  const openKitDoc = useCallback((docId: string, download = false) => {
    const origin = window.location.origin;
    const externalOrigin = origin.includes("127.0.0.1") ? origin.replace("127.0.0.1", "localhost") : origin.replace("localhost", "127.0.0.1");
    window.open(`${externalOrigin}/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}?token=${encodeURIComponent(tok())}&v=${Date.now()}${download ? "&download=1" : ""}`, "_blank", "noopener,noreferrer");
  }, [dealId]);
  const approveKitDoc = useCallback(async (docId: string, status: string) => {
    await fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}/approve`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ status }) }).catch(() => {});
    onUpdate?.();
  }, [dealId, onUpdate]);
  const saveKitField = useCallback((docId: string, key: string, value: string) => {
    fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}/field`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ key, value }) }).catch(() => {});
  }, [dealId]);
  const generateKitDoc = useCallback(async (docId: string) => {
    setGeneratingKit(docId);
    try {
      await fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } });
      onUpdate?.();
    } finally { setGeneratingKit(null); }
  }, [dealId, onUpdate]);

  // ── Add a form (#6): upload a PDF, or pick from the wired-template catalog ──
  const [addFormOpen, setAddFormOpen] = useState(false);
  const [addingForm, setAddingForm] = useState(false);
  // Forms that have a fillable template wired backend-side but aren't in the
  // default 6. Grows as more templates are wired; upload covers everything else.
  const builtIds = new Set(builtDocs.map((d) => d.id));
  const FORM_CATALOG: { id: string; label: string }[] = [
    { id: "subject-removal", label: "Subject Removal / Notice of Fulfillment" },
  ].filter((f) => !builtIds.has(f.id));
  const addCatalogForm = useCallback(async (templateId: string, name: string) => {
    setAddingForm(true);
    try {
      await fetch(`/api/admin/deals/${dealId}/kit-doc/add`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ templateId, name }) });
      onUpdate?.();
    } finally { setAddingForm(false); setAddFormOpen(false); }
  }, [dealId, onUpdate]);
  const uploadForm = useCallback(async (file: File) => {
    setAddingForm(true);
    try {
      const buf = await file.arrayBuffer();
      let bin = "";
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      const contentB64 = btoa(bin);
      await fetch(`/api/admin/deals/${dealId}/kit-doc/add`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, contentB64 }) });
      onUpdate?.();
    } finally { setAddingForm(false); setAddFormOpen(false); }
  }, [dealId, onUpdate]);

  const mls = (extra.mlsNumber as string) || (extra.mls as string) || "";
  const pid = (extra.pid as string) || "";
  const legal = (extra.legalDescription as string) || (extra.legal as string) || "";
  const docsPulled = !!(pid || legal);

  const saveUmbrella = useCallback(
    (u: string) => {
      setUmbrella(u);
      // Reset the subject set to the new property type's defaults.
      const defs = new Set(defaultsFor(u));
      setSelectedClauses(defs);
      persistClauses(defs, customClauses);
      api.setAdminDealToggle(dealId, "cpsUmbrella", u).then(() => onUpdate?.()).catch(() => {});
    },
    [dealId, onUpdate, customClauses, persistClauses],
  );

  const postal = (extra.postalCode as string) || (extra.postal as string) || "";
  const pullStatus = (extra.listingPullStatus as string) || "";
  const [mlsInput, setMlsInput] = useState<string>(mls);
  const [pulling, setPulling] = useState(false);
  const pullDocuments = useCallback(async () => {
    const num = mlsInput.trim();
    if (!num) return;
    const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    setPulling(true);
    await api.setAdminDealToggle(dealId, "mlsNumber", num).catch(() => {});
    await fetch(`/api/admin/deals/${dealId}/pull-listing`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ mls: num }),
    }).catch(() => {});
    // The pull is a browser scrape (a few minutes). Poll the deal so the fields
    // fill in when it finishes, then stop.
    let ticks = 0;
    const poll = setInterval(() => {
      ticks += 1;
      onUpdate?.();
      if (ticks > 40) { clearInterval(poll); setPulling(false); }
    }, 6000);
  }, [dealId, mlsInput, onUpdate]);
  const busy = pulling || pullStatus === "pulling";

  // Save any term to the deal (bare key — same keys the CPS/assembler read).
  const saveField = useCallback(
    (key: string, value: string) => {
      api.setAdminDealToggle(dealId, key, value.trim() || null).catch(() => {});
    },
    [dealId],
  );

  // ── header ──────────────────────────────────────────────────────────────
  const Header = (
    <div style={{ background: NAVY, color: "#fff", padding: "18px 22px", borderRadius: "12px 12px 0 0", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 19 }}>{(buyerName || "Buyer").trim()} — Transaction Kit</div>
        <div style={{ fontSize: 13, color: "#aeb8cc", marginTop: 3 }}>
          {address || "Property"}{mls ? ` · MLS ${mls}` : ""}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <span style={{ background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 12, letterSpacing: 0.5, padding: "5px 12px", borderRadius: 999, whiteSpace: "nowrap" }}>OFFER PREP</span>
        <button type="button" onClick={() => setCollapsed(true)} title="Minimize" style={{ background: "transparent", border: "1px solid #ffffff44", color: "#fff", borderRadius: 7, padding: "4px 11px", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>▴</button>
      </div>
    </div>
  );

  if (collapsed) {
    return (
      <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, overflow: "hidden" }}>
        <button type="button" onClick={() => setCollapsed(false)} style={{ width: "100%", background: NAVY, color: "#fff", border: "none", padding: "13px 22px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", textAlign: "left" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{(buyerName || "Buyer").trim()} — Transaction Kit</div>
            <div style={{ fontSize: 12, color: "#aeb8cc", marginTop: 2 }}>{accepted ? "Offer accepted · kit on file" : (address || "property")}</div>
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#cdd5e4", whiteSpace: "nowrap" }}>▾</span>
        </button>
      </section>
    );
  }

  // ── step indicator ──────────────────────────────────────────────────────
  const Stepper = (
    <div style={{ display: "flex", alignItems: "center", margin: "4px 0 18px" }}>
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const active = n === step;
        const circleBg = done ? GREEN : active ? ORANGE : "#e7eaef";
        const circleColor = done || active ? "#fff" : "#9aa0a6";
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : "0 0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <div style={{ width: 30, height: 30, borderRadius: 999, background: circleBg, color: circleColor, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14, boxShadow: active ? `0 0 0 4px ${ORANGE}22` : "none", flexShrink: 0 }}>
                {done ? "✓" : n}
              </div>
              <span style={{ fontWeight: 700, fontSize: 14, color: done ? GREEN : active ? INK : "#9aa0a6", whiteSpace: "nowrap" }}>{label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ flex: 1, height: 2, background: n < step ? GREEN : "#e7eaef", margin: "0 12px" }} />
            )}
          </div>
        );
      })}
    </div>
  );

  const panel: React.CSSProperties = { border: `1px solid ${BORDER}`, borderRadius: 12, padding: "18px 20px", marginTop: 14 };
  const FromTag = ({ t }: { t: string }) => (
    <span style={{ color: BLUE, fontWeight: 700, fontSize: 11, letterSpacing: 0.4 }}>{t}</span>
  );
  const factBox: React.CSSProperties = { background: "#f7f8fa", border: `1px solid ${BORDER}`, borderRadius: 8, padding: "10px 12px" };

  // ── Step 1: Property ──────────────────────────────────────────────────────
  const Step1 = (
    <>
      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Property type &amp; template</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 14px" }}>
          Auto-detected from the MLS listing — tap another if it&apos;s different. This sets which CPS gets filled and which subjects apply.
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {PROPERTY_TYPES.map((t) => {
            const sel = umbrella === t.id;
            return (
              <button key={t.id} type="button" onClick={() => saveUmbrella(t.id)} style={{ padding: "10px 16px", borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: "pointer", border: `1px solid ${sel ? ORANGE : BORDER}`, background: sel ? ORANGE : "#fff", color: sel ? "#fff" : INK }}>
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      <div style={panel}>
        <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Listing documents</div>
        <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 12px" }}>
          Enter the MLS # of the property the buyer is writing on, then pull. This logs into Xposure, grabs every document on the listing&apos;s Docs tab + the title, and reads the legal description, PID &amp; postal code.
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
          <div>
            <label style={{ display: "block", fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 4 }}>MLS #</label>
            <input value={mlsInput} onChange={(e) => setMlsInput(e.target.value)} placeholder="e.g. 10391498" style={{ fontSize: 15, padding: "9px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK, width: 200 }} />
          </div>
          <button type="button" onClick={pullDocuments} disabled={busy || !mlsInput.trim()} style={{ padding: "10px 18px", borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: busy ? "default" : "pointer", border: "none", background: busy ? "#9aa6bd" : NAVY, color: "#fff" }}>
            {busy ? "Pulling…" : "Pull listing documents"}
          </button>
        </div>
        <div style={{ display: "inline-block", background: busy ? "#eef2f9" : docsPulled ? "#e7f4ec" : "#fdf0e9", color: busy ? NAVY : docsPulled ? GREEN : ORANGE, fontWeight: 700, fontSize: 13, padding: "8px 14px", borderRadius: 8, marginBottom: 12 }}>
          {busy ? "Pulling from Xposure + title… this takes a few minutes" : docsPulled ? "✓ Package prepped · title + documents pulled" : pullStatus === "failed" ? "Pull failed — check the MLS # and try again" : "Not pulled yet — enter the MLS # above and pull"}
        </div>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={factBox}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4 }}>PROPERTY ADDRESS</span><FromTag t="FROM MLS" /></div>
            <div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{address || "—"}</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            <div style={factBox}>
              <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4 }}>PID</span><FromTag t="TITLE / LISTING" /></div>
              <div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{pid || "—"}</div>
            </div>
            <div style={factBox}>
              <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4 }}>POSTAL CODE</span><FromTag t="FROM MLS" /></div>
              <div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{postal || "—"}</div>
            </div>
            <div style={factBox}>
              <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4 }}>MLS #</span><FromTag t="FROM MLS" /></div>
              <div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{mls || "—"}</div>
            </div>
          </div>
          <div style={factBox}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4 }}>LEGAL DESCRIPTION</span><FromTag t="TITLE / LISTING" /></div>
            <div style={{ fontWeight: 700, color: INK, marginTop: 3 }}>{legal || "—"}</div>
          </div>
        </div>
      </div>
    </>
  );

  // ── Step 2: Terms ─────────────────────────────────────────────────────────
  const fieldLabel: React.CSSProperties = { display: "block", fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 5 };
  const termsInput: React.CSSProperties = { width: "100%", boxSizing: "border-box", fontSize: 15, padding: "10px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK, fontFamily: "inherit" };
  const cell = (label: string, key: string, ph: string) => (
    <div key={key}>
      <label style={fieldLabel}>{label}</label>
      <input defaultValue={(extra[key] as string) || ""} placeholder={ph} onBlur={(e) => saveField(key, e.target.value)} style={termsInput} />
    </div>
  );
  const Step2 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Deal terms</div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 16px" }}>
        Buyer &amp; seller names pull from the card; PID and legal from the title. Just the offer numbers here — everything saves as you type.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        {cell("PURCHASE PRICE", "cpsPurchasePrice", "$630,000")}
        {cell("DEPOSIT", "cpsDeposit", "$10,000")}
        {cell("DEPOSIT DUE", "cpsDepositTerms", "on subject removal")}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        {cell("SUBJECT REMOVAL", "subjectRemovalDate", "Jul 14")}
        {cell("COMPLETION", "completionDate", "Aug 12")}
        {cell("POSSESSION", "possessionDate", "Aug 14")}
        {cell("ADJUSTMENT", "adjustmentDate", "Aug 12")}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        {cell("INCLUDED ITEMS", "cpsInclusions", "all appliances, window coverings…")}
        {cell("EXCLUDED ITEMS", "cpsExclusions", "staging furniture…")}
        {cell("DESIGNATED AGENCY", "designatedAgency", "Skyleigh McCallum")}
      </div>
    </div>
  );

  // ── Step 3: Subjects & clauses ────────────────────────────────────────────
  const udefU: AnyObj = (clauseLibrary.umbrellas as AnyObj)?.[umbrella] || {};
  const defsSet = new Set(defaultsFor(umbrella));
  const visibleClauses = allClauses.filter((c) => clauseVisible(c, umbrella, udefU));
  const mainClauses = visibleClauses.filter((c) => defsSet.has(c.id) || selectedClauses.has(c.id));
  const moreClauses = visibleClauses.filter((c) => !defsSet.has(c.id) && !selectedClauses.has(c.id));
  const typeLabel = PROPERTY_TYPES.find((t) => t.id === umbrella)?.label || umbrella;
  const clauseRow = (c: AnyObj) => {
    const checked = selectedClauses.has(c.id);
    const cvars: AnyObj[] = (c.variables || []).filter((v: AnyObj) => v && v.key && !VAR_SKIP.has(v.key));
    const w = String(c.primary_wording || "");
    return (
      <div key={c.id} style={{ padding: "12px 0", borderTop: "1px solid #eef0f3" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", cursor: "pointer" }} onClick={() => toggleClause(c.id)}>
          <div style={{ width: 24, height: 24, borderRadius: 6, flexShrink: 0, marginTop: 1, background: checked ? GREEN : "#fff", border: `1px solid ${checked ? GREEN : "#c9ced6"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14 }}>{checked ? "✓" : ""}</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>{c.title}</div>
            <div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{w.slice(0, 95)}{w.length > 95 ? "…" : ""}</div>
          </div>
        </div>
        {checked && cvars.length > 0 && (
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8, marginLeft: 36 }}>
            {cvars.map((v) => (
              <div key={v.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12, color: MUTED, fontWeight: 600 }}>{VAR_LABELS[v.key] || v.key}</span>
                <input defaultValue={cpsVars[v.key] || VAR_DEFAULTS[v.key] || ""} onBlur={(e) => saveVar(v.key, e.target.value)} style={{ width: 140, fontSize: 13, padding: "6px 9px", borderRadius: 7, border: `1px solid ${BORDER}`, color: INK }} />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };
  const Step3 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Subjects &amp; clauses · {typeLabel}</div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 4px" }}>
        For the Buyer&apos;s benefit, removed on or before <b style={{ color: INK }}>{(extra.subjectRemovalDate as string) || "[date]"}</b>. The standard set for this property type is pre-checked — fill the blanks or add your own.
      </div>
      <div>
        {mainClauses.map(clauseRow)}
        {customClauses.map((c) => (
          <div key={c.id} style={{ padding: "12px 0", borderTop: "1px solid #eef0f3", display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, flexShrink: 0, background: GREEN, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 14 }}>✓</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>Custom clause</div>
              <div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{c.wording}</div>
            </div>
            <button type="button" onClick={() => { const next = customClauses.filter((x) => x.id !== c.id); setCustomClauses(next); persistClauses(selectedClauses, next); }} style={{ background: "none", border: "none", color: "#9aa0a6", cursor: "pointer", fontSize: 18, fontWeight: 700 }}>×</button>
          </div>
        ))}
      </div>
      {moreClauses.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #eef0f3" }}>
          <button type="button" onClick={() => setShowMoreClauses((s) => !s)} style={{ background: "none", border: "none", color: ORANGE, fontWeight: 700, fontSize: 14, cursor: "pointer", padding: 0 }}>
            {showMoreClauses ? "Hide extra clauses ▴" : `Add more clauses ▾ (${moreClauses.length} more for ${typeLabel})`}
          </button>
          {showMoreClauses && <div>{moreClauses.map(clauseRow)}</div>}
        </div>
      )}
      <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${BORDER}` }}>
        <button type="button" onClick={() => setClausePickerOpen(true)} style={{ display: "flex", alignItems: "center", gap: 8, background: "#fff", border: `1px solid ${NAVY}`, color: NAVY, borderRadius: 8, padding: "9px 16px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}>
          📁 Browse all clauses (Personal / Office / System)
        </button>
      </div>
      <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${BORDER}` }}>
        <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 8 }}>+ ADD YOUR OWN CLAUSE</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={newClause} onChange={(e) => setNewClause(e.target.value)} placeholder="Type a one-off clause for this deal…" style={{ flex: 1, fontSize: 14, padding: "9px 12px", borderRadius: 8, border: `1px solid ${BORDER}`, color: INK }} />
          <button type="button" onClick={addCustomClause} style={{ padding: "9px 18px", borderRadius: 8, fontWeight: 700, border: `1px solid ${ORANGE}`, background: "#fff", color: ORANGE, cursor: "pointer" }}>Add</button>
        </div>
      </div>
    </div>
  );

  // ── Step 4: Build & Preview ───────────────────────────────────────────────
  // Fields editable per built doc (mirrors the canonical CPS context keys).
  const KIT_DOC_FIELDS: { key: string; label: string; multiline?: boolean }[] = [
    { key: "buyer1", label: "Buyer 1" }, { key: "buyer2", label: "Buyer 2" },
    { key: "property", label: "Property address" }, { key: "price", label: "Purchase price ($)" },
    { key: "priceWords", label: "Price in words" }, { key: "deposit", label: "Deposit ($)" },
    { key: "depositHolder", label: "Deposit held by" }, { key: "completionDate", label: "Completion date" },
    { key: "possessionDate", label: "Possession date" }, { key: "adjustmentDate", label: "Adjustment date" },
    { key: "included", label: "Included items", multiline: true }, { key: "excluded", label: "Excluded items", multiline: true },
    { key: "conditions", label: "Subject conditions / clauses", multiline: true },
  ];
  const kitBtn: React.CSSProperties = { fontSize: 12, padding: "5px 13px", borderRadius: 7, border: `1px solid #d4d8de`, background: "#fff", color: INK, cursor: "pointer", fontWeight: 600 };
  const kitInput: React.CSSProperties = { width: "100%", boxSizing: "border-box", fontSize: 13, padding: "7px 9px", borderRadius: 6, border: `1px solid #d4d8de`, color: INK, fontFamily: "inherit" };
  const readyCount = builtDocs.filter((d) => d.ready).length;
  const Step4 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>Documents in the kit</div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 14px" }}>
        Toggle which forms get built into this buyer&apos;s package. Add your own for anything outside the standard set.
      </div>
      <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 4 }}>STANDARD FORMS</div>
      <div>
        {KIT_FORMS.map((f) => {
          const on = !!f.required || (kitForms[f.id] ?? KIT_FORM_DEFAULTS[f.id] ?? true);
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

      {/* Add a form (#6) — upload a PDF or pick a wired template */}
      <div style={{ marginTop: 14, border: `1.5px dashed ${BORDER}`, borderRadius: 10, padding: addFormOpen ? "16px 18px" : 0 }}>
        {!addFormOpen ? (
          <button type="button" onClick={() => setAddFormOpen(true)} style={{ width: "100%", padding: "16px 18px", display: "flex", alignItems: "center", gap: 14, color: MUTED, background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
            <div style={{ width: 40, height: 40, borderRadius: 8, background: NAVY, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 700, flexShrink: 0 }}>+</div>
            <div>
              <div style={{ fontWeight: 700, color: INK, fontSize: 14 }}>Add a form</div>
              <div style={{ fontSize: 13 }}>Upload a PDF or pick from the form catalog — builds right into the kit.</div>
            </div>
          </button>
        ) : (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontWeight: 700, color: INK, fontSize: 14 }}>Add a form</span>
              <button type="button" onClick={() => setAddFormOpen(false)} style={{ background: "none", border: "none", color: MUTED, cursor: "pointer", fontSize: 18 }}>×</button>
            </div>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: addingForm ? "default" : "pointer", border: `1px solid ${NAVY}`, color: NAVY, borderRadius: 8, padding: "9px 16px", fontWeight: 700, fontSize: 14, marginBottom: 14 }}>
              {addingForm ? "Adding…" : "⬆ Upload a PDF"}
              <input type="file" accept="application/pdf" disabled={addingForm} onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadForm(f); }} style={{ display: "none" }} />
            </label>
            {FORM_CATALOG.length > 0 && (
              <>
                <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, margin: "4px 0 6px" }}>OR PICK FROM THE CATALOG</div>
                {FORM_CATALOG.map((f) => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
                    <span style={{ fontSize: 14, color: INK, fontWeight: 600 }}>{f.label}</span>
                    <button type="button" disabled={addingForm} onClick={() => void addCatalogForm(f.id, f.label)} style={kitBtn}>Add</button>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Built documents (#7) — folded in from the old standalone Transaction Kit card */}
      {builtDocs.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, marginBottom: 2 }}>BUILT DOCUMENTS</div>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 6 }}>{readyCount} of {builtDocs.length} populated · open, edit, or approve each document</div>
          {builtDocs.map((d) => {
            const approved = d.status === "approved";
            const isOpen = expandedKit === d.id;
            const fields = d.fields || {};
            return (
              <div key={d.id} style={{ borderTop: "1px solid #eef0f3" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "11px 0", opacity: d.ready ? 1 : 0.6 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, color: INK, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.name}</div>
                    <div style={{ fontSize: 11, color: approved ? BLUE : d.ready ? ORANGE : "#9aa0a6", marginTop: 2, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{approved ? "Approved" : d.ready ? "Draft ready" : "Awaiting template"}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    {Object.keys(fields).length > 0 && <button type="button" onClick={() => setExpandedKit(isOpen ? null : d.id)} style={{ ...kitBtn, ...(isOpen ? { background: "#eef2f9" } : {}) }}>{isOpen ? "Close" : "Edit fields"}</button>}
                    <button type="button" onClick={() => generateKitDoc(d.id)} disabled={generatingKit === d.id} style={kitBtn} title="Re-fill from the deal data">{generatingKit === d.id ? "…" : "Generate"}</button>
                    <button type="button" onClick={() => openKitDoc(d.id)} style={kitBtn} title="View the PDF">Open</button>
                    <button type="button" onClick={() => openKitDoc(d.id, true)} style={kitBtn} title="Download editable PDF">Download</button>
                    <button type="button" onClick={() => approveKitDoc(d.id, approved ? "draft" : "approved")} style={{ ...kitBtn, background: approved ? BLUE : NAVY, color: "#fff", borderColor: "transparent" }}>{approved ? "Approved ✓" : "Approve"}</button>
                  </div>
                </div>
                {isOpen && (
                  <div style={{ padding: "2px 0 16px" }}>
                    {KIT_DOC_FIELDS.map((fd) => (
                      <div key={fd.key} style={{ marginBottom: 8 }}>
                        <label style={{ display: "block", fontSize: 10, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>{fd.label}</label>
                        {fd.multiline
                          ? <textarea defaultValue={fields[fd.key] || ""} onBlur={(e) => saveKitField(d.id, fd.key, e.target.value)} rows={2} style={kitInput} />
                          : <input defaultValue={fields[fd.key] || ""} onBlur={(e) => saveKitField(d.id, fd.key, e.target.value)} style={kitInput} />}
                      </div>
                    ))}
                    <button type="button" onClick={() => generateKitDoc(d.id)} disabled={generatingKit === d.id} style={{ ...kitBtn, background: ORANGE, color: "#fff", borderColor: "transparent" }}>{generatingKit === d.id ? "Generating…" : "Generate PDF"}</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {builtMsg && <div style={{ marginTop: 12, color: GREEN, fontWeight: 700, fontSize: 14 }}>{builtMsg}</div>}
    </div>
  );

  const Placeholder = (
    <div style={{ ...panel, color: MUTED, fontSize: 14 }}>This step lands next.</div>
  );

  const navBtn: React.CSSProperties = { padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 15, cursor: "pointer", border: "none" };

  return (
    <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, background: "#fff" }}>
      {Header}
      <div style={{ padding: "18px 22px 20px" }}>
        <div style={{ fontWeight: 800, fontSize: 13, letterSpacing: 0.6, color: INK }}>BUILD OFFER KIT · STEP {step} OF 4</div>
        <div style={{ marginTop: 12 }}>{Stepper}</div>
        {step === 1 ? Step1 : step === 2 ? Step2 : step === 3 ? Step3 : step === 4 ? Step4 : Placeholder}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18 }}>
          {step > 1 ? (
            <button type="button" onClick={() => setStep((s) => s - 1)} style={{ ...navBtn, background: "#fff", color: INK, border: `1px solid ${BORDER}` }}>← Back</button>
          ) : <span />}
          <button type="button" disabled={building} onClick={() => { if (step === 4) buildKit(); else setStep((s) => Math.min(4, s + 1)); }} style={{ ...navBtn, background: step === 4 ? GREEN : NAVY, color: "#fff", opacity: building ? 0.7 : 1 }}>
            {step === 1 ? "Continue to Terms →" : step === 2 ? "Continue to Subjects →" : step === 3 ? "Continue to Build →" : building ? "Building…" : "Build Transaction Kit"}
          </button>
        </div>
      </div>
      <ClausePickerModal
        open={clausePickerOpen}
        onClose={() => setClausePickerOpen(false)}
        onInsert={insertClauses}
        folders={clauseFolders as unknown as { key: string; label: string; clauses: { id: string }[] }[]}
        preselected={selectedClauses}
      />
    </section>
  );
}
