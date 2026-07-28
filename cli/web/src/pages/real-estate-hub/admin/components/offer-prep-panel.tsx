// Offer Prep card panel (buyer side). Pick the CPS form (umbrella) + select clauses.
// Standard set is visible + pre-checked; everything else is behind "Add more clauses";
// a free-text box adds a one-off clause for this deal. Selections persist to
// deals.extra_toggles_json (bare keys cpsUmbrella, cpsClauses, cpsCustomClauses).
// Generation stays GATED until the forms + clause wording are confirmed.
import { useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formLibrary, clauseLibrary } from "../cps/cps-libraries";

const NAVY = "#182848";
const TERRA = "#C46340";
const BLUE = "#5E8AD0";
const LINE = "#e6e9f0";
const MUTED = "#7a8499";

const SECTION_LABELS: Record<string, string> = {
  "common-subject": "Common subjects",
  "buyer-specific": "Buyer-strategy clauses",
  rural: "Rural (well / septic / water)",
  "new-construction": "New construction",
  strata: "Strata-specific",
  manufactured: "Manufactured / mobile",
  "standard-clause": "Standard clauses",
  other: "Other",
};
const SECTION_ORDER = ["common-subject", "buyer-specific", "rural", "new-construction", "strata", "manufactured", "standard-clause", "other"];
const UNIVERSAL = new Set(["common-subject", "buyer-specific", "standard-clause"]);

// friendly labels + sensible defaults for the [blanks] inside clause wording.
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
// subject_removal_date is collected once in Deal Terms — don't show it per-clause.
const VAR_SKIP = new Set(["subject_removal_date"]);

type AnyObj = Record<string, any>;

function umbrellaForms(): AnyObj[] {
  return (formLibrary.forms || []).filter((f: AnyObj) => f.umbrella);
}

// Which clauses are offerable for a chosen umbrella.
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

export default function OfferPrepPanel({ dealId, extra, address, onGenerated }: { dealId: string; extra: AnyObj; address?: string; onGenerated?: () => void }) {
  const forms = umbrellaForms();
  const savedUmbrella: string = (extra.cpsUmbrella as string) || "residential";
  const savedClauses: string[] = Array.isArray(extra.cpsClauses) ? (extra.cpsClauses as string[]) : [];
  const savedCustom: AnyObj[] = Array.isArray(extra.cpsCustomClauses) ? (extra.cpsCustomClauses as AnyObj[]) : [];

  const defaultsFor = (u: string): string[] => (clauseLibrary.umbrellas?.[u]?.default_clauses as string[]) || [];

  const [umbrella, setUmbrella] = useState<string>(savedUmbrella);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(savedClauses.length ? savedClauses : defaultsFor(savedUmbrella))
  );
  const [customClauses, setCustomClauses] = useState<AnyObj[]>(savedCustom);
  const [showMore, setShowMore] = useState(false);
  const [newText, setNewText] = useState("");
  const [open, setOpen] = useState(true);
  const [saving, setSaving] = useState(false);

  // Deal terms that fill the CPS form (not clauses): inclusions/exclusions, the
  // three dates, and the Canadian-buyer declaration. Saved to extra under bare keys.
  const [terms, setTerms] = useState<AnyObj>({
    cpsPurchasePrice: (extra.cpsPurchasePrice as string) || "",
    cpsDeposit: (extra.cpsDeposit as string) || "",
    cpsDepositTerms: (extra.cpsDepositTerms as string) || "",
    cpsInclusions: (extra.cpsInclusions as string) || "",
    cpsExclusions: (extra.cpsExclusions as string) || "",
    subjectRemovalDate: (extra.subjectRemovalDate as string) || "",
    completionDate: (extra.completionDate as string) || "",
    possessionDate: (extra.possessionDate as string) || "",
    possessionTime: (extra.possessionTime as string) || "",
    adjustmentDate: (extra.adjustmentDate as string) || "",
    mhRegistration: (extra.mhRegistration as string) || "",
    mhSerial: (extra.mhSerial as string) || "",
    mhCsaLabel: (extra.mhCsaLabel as string) || "",
    buyerCanadian: extra.buyerCanadian === undefined ? true : extra.buyerCanadian === true || extra.buyerCanadian === "true",
  });
  // Persist every edit on a short debounce (in addition to onBlur), so partial
  // work is never lost if the card is closed mid-typing — you can come back and
  // generate later.
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const setTerm = (key: string, value: any) => {
    setTerms((t) => ({ ...t, [key]: value }));
    clearTimeout(saveTimers.current[key]);
    saveTimers.current[key] = setTimeout(() => { void saveTerm(key, value); }, 600);
  };
  const saveTerm = async (key: string, value: any) => {
    clearTimeout(saveTimers.current[key]);
    setSaving(true);
    try { await api.setAdminDealToggle(dealId, key, value === "" ? null : value); }
    finally { setSaving(false); }
  };

  // per-clause fill-in values (the [blanks] in clause wording). Optional —
  // anything left empty generates a blank line. subject_removal_date is handled
  // by Deal Terms, so it's not shown per-clause.
  const [cpsVars, setCpsVars] = useState<AnyObj>((extra.cpsVars as AnyObj) || {});
  const saveVar = (key: string, value: string) => {
    setCpsVars((prev) => {
      const next = { ...prev, [key]: value };
      void api.setAdminDealToggle(dealId, "cpsVars", next as any);
      return next;
    });
  };

  // gather docs + MLS sheet from Xposure into the buyer deal folder
  const [mlsInput, setMlsInput] = useState<string>((extra.targetMls as string) || "");
  const [gatherMsg, setGatherMsg] = useState<string>("");
  const [gathering, setGathering] = useState(false);
  const runGather = async () => {
    const mls = mlsInput.trim();
    if (!/^\d{6,9}$/.test(mls)) { setGatherMsg("Enter a valid MLS number."); return; }
    setGathering(true);
    setGatherMsg("Gathering from Xposure… docs + MLS sheet will land in the deal folder in ~1-2 min.");
    try {
      await api.setAdminDealToggle(dealId, "targetMls", mls);
      await api.gatherCpsPackage(mls, dealId);
      setGatherMsg("✓ Started. The MLS sheet and listing documents are being filed into this deal's folder.");
    } catch {
      setGatherMsg("Could not start the gather. Try again, or check the listing is on Xposure.");
    } finally {
      setGathering(false);
    }
  };

  // accessory forms that can ride along with the CPS in the package
  const OFFER_FORMS: { key: "pnc" | "dorts" | "disclosure-rem"; label: string; full: string }[] = [
    { key: "dorts", label: "DORTS", full: "Disclosure of Representation in Trading Services" },
    { key: "pnc", label: "PNC", full: "Privacy Notice and Consent" },
    { key: "disclosure-rem", label: "Disclosure of Remuneration", full: "Discloses the brokerage's remuneration on this purchase" },
  ];
  // which forms to include in the package (CPS is always included)
  const [pkgForms, setPkgForms] = useState<Record<string, boolean>>(
    (extra.cpsForms as Record<string, boolean>) || { dorts: true, pnc: true, "disclosure-rem": true });
  const toggleForm = (key: string) => {
    setPkgForms((p) => {
      const next = { ...p, [key]: !(p[key] ?? true) };
      void api.setAdminDealToggle(dealId, "cpsForms", next as any);
      return next;
    });
  };
  const [packageBusy, setPackageBusy] = useState(false);
  const [packageMsg, setPackageMsg] = useState("");
  const [packageUrl, setPackageUrl] = useState<string>((extra.cpsPackageUrl as string) || "");
  const runPackage = async () => {
    setPackageBusy(true);
    const chosen = OFFER_FORMS.filter((f) => pkgForms[f.key] ?? true);
    setPackageMsg(`Building the package (CPS${chosen.length ? " + " + chosen.map((f) => f.label).join(" + ") : ""})… ~30s`);
    try {
      const vars: Record<string, any> = { subject_removal_date: terms.subjectRemovalDate || "" };
      for (const c of (clauseLibrary.clauses || []) as AnyObj[]) {
        if (!selected.has(c.id)) continue;
        for (const v of (c.variables || []) as AnyObj[]) {
          if (v.key === "subject_removal_date") continue;
          vars[v.key] = cpsVars[v.key] ?? VAR_DEFAULTS[v.key] ?? "";
        }
      }
      const r = await api.buildOfferPackage({
        umbrella, clauses: Array.from(selected),
        customClauses: customClauses.map((c) => ({ wording: c.wording })),
        vars, address, dealId, forms: chosen.map((f) => f.key),
      });
      if (r.url) {
        setPackageUrl(r.url);
        await api.setAdminDealToggle(dealId, "cpsPackageUrl", r.url);
        onGenerated?.();  // light up the top "Open Offer Package" button
      }
      setPackageMsg(`✓ Package ready (${r.count} ${r.count === 1 ? "doc" : "docs"} in one PDF) — Open Package to preview, or edit above and build again.`);
    } catch {
      setPackageMsg("Package build failed — try again.");
    } finally {
      setPackageBusy(false);
    }
  };

  const udef = clauseLibrary.umbrellas?.[umbrella] || {};
  const allClauses: AnyObj[] = clauseLibrary.clauses || [];

  // visible clauses for this umbrella, split into the standard/active set vs the rest
  const { mainBySec, moreBySec, moreCount } = useMemo(() => {
    const defs = new Set(defaultsFor(umbrella));
    const main: Record<string, AnyObj[]> = {};
    const more: Record<string, AnyObj[]> = {};
    let mc = 0;
    for (const c of allClauses) {
      if (!clauseVisible(c, umbrella, udef)) continue;
      const isMain = defs.has(c.id) || selected.has(c.id);
      const bucket = isMain ? main : more;
      (bucket[c.section] = bucket[c.section] || []).push(c);
      if (!isMain) mc++;
    }
    return { mainBySec: main, moreBySec: more, moreCount: mc };
  }, [umbrella, selected]); // eslint-disable-line

  const persist = async (u: string, ids: string[], custom: AnyObj[]) => {
    setSaving(true);
    try {
      await api.setAdminDealToggle(dealId, "cpsUmbrella", u);
      await api.setAdminDealToggle(dealId, "cpsClauses", ids as any);
      await api.setAdminDealToggle(dealId, "cpsCustomClauses", custom as any);
    } finally {
      setSaving(false);
    }
  };

  const pickUmbrella = (u: string) => {
    const defs = defaultsFor(u);
    setUmbrella(u);
    setSelected(new Set(defs));
    setShowMore(false);
    void persist(u, defs, customClauses);
  };

  const toggleClause = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
    void persist(umbrella, Array.from(next), customClauses);
  };

  const addCustom = () => {
    const t = newText.trim();
    if (!t) return;
    const c = { id: "custom-" + Date.now(), title: "Custom clause", wording: t };
    const next = [...customClauses, c];
    setCustomClauses(next);
    setNewText("");
    void persist(umbrella, Array.from(selected), next);
  };

  const removeCustom = (id: string) => {
    const next = customClauses.filter((c) => c.id !== id);
    setCustomClauses(next);
    void persist(umbrella, Array.from(selected), next);
  };

  const selectedForm = forms.find((f) => f.umbrella === umbrella);
  const selCount = Array.from(selected).filter((id) => allClauses.some((c) => c.id === id)).length + customClauses.length;

  const checkbox = (on: boolean, onClick: () => void) => (
    <span
      onClick={(e) => { e.preventDefault(); onClick(); }}
      style={{ width: 18, height: 18, borderRadius: 5, flex: "0 0 auto", marginTop: 1,
        border: `2px solid ${on ? BLUE : "#cdd4e2"}`, background: on ? BLUE : "#fff", position: "relative", cursor: "pointer" }}
    >
      {on && <span style={{ position: "absolute", left: 5, top: 1, width: 4, height: 9, border: "solid #fff", borderWidth: "0 2px 2px 0", transform: "rotate(45deg)" }} />}
    </span>
  );

  const clauseRow = (c: AnyObj) => {
    const on = selected.has(c.id);
    const vkeys: string[] = (c.variables || []).map((v: AnyObj) => v.key).filter((k: string) => !VAR_SKIP.has(k));
    return (
      <div key={c.id} style={{ borderTop: "1px solid #f0f2f7" }}>
        <label style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "7px 4px", cursor: "pointer" }}>
          {checkbox(on, () => toggleClause(c.id))}
          <span style={{ flex: 1 }}>
            <span style={{ fontSize: 13.5, fontWeight: 600, color: "#2b2b2b" }}>{c.title}</span>
            <span style={{ fontSize: 10.5, fontWeight: 700, marginLeft: 7, padding: "1px 6px", borderRadius: 5,
              background: c.category === "subject" ? "#e7eefb" : "#f1ede9", color: c.category === "subject" ? "#3a5da8" : "#9a6a4d" }}>{c.category}</span>
            {c.needs_confirmation && <span style={{ fontSize: 10.5, color: TERRA, marginLeft: 6 }}>· wording to confirm</span>}
          </span>
        </label>
        {on && vkeys.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "0 4px 9px 30px" }}>
            {vkeys.map((k) => (
              <label key={k} style={{ fontSize: 10.5, color: MUTED, display: "flex", flexDirection: "column" }}>
                {VAR_LABELS[k] || k}
                <input value={cpsVars[k] ?? VAR_DEFAULTS[k] ?? ""} placeholder="(blank line if empty)"
                  onChange={(e) => { const v = e.target.value; setCpsVars((p) => ({ ...p, [k]: v })); clearTimeout(saveTimers.current["var:" + k]); saveTimers.current["var:" + k] = setTimeout(() => saveVar(k, v), 600); }}
                  onBlur={(e) => saveVar(k, e.target.value)}
                  style={{ marginTop: 2, border: `1px solid ${LINE}`, borderRadius: 6, padding: "5px 7px", fontSize: 12, width: k.includes("address") ? 220 : 130, fontFamily: "inherit" }} />
              </label>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderGroups = (bySec: Record<string, AnyObj[]>) =>
    SECTION_ORDER.filter((s) => bySec[s]?.length).map((sec) => (
      <div key={sec} style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>{SECTION_LABELS[sec] || sec}</div>
        {bySec[sec].map(clauseRow)}
      </div>
    ));

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", padding: "12px 16px", background: NAVY, color: "#fff" }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>
          Offer Prep — CPS Builder
          <span style={{ fontWeight: 400, fontSize: 12, color: "#b9c4dc", marginLeft: 8 }}>
            {selectedForm ? selectedForm.name : "Contract of Purchase & Sale"} · {selCount} clauses
          </span>
        </div>
        <span style={{ fontSize: 12, color: "#b9c4dc" }}>{saving ? "saving…" : open ? "▾" : "▸"}</span>
      </header>

      {open && (
        <div style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>Form</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginBottom: 14 }}>
            {forms.map((f) => {
              const on = f.umbrella === umbrella;
              return (
                <button key={f.umbrella} onClick={() => pickUmbrella(f.umbrella)}
                  style={{ fontSize: 12.5, fontWeight: on ? 700 : 500, padding: "7px 12px", borderRadius: 8,
                    border: `1px solid ${on ? TERRA : LINE}`, background: on ? TERRA : "#fff", color: on ? "#fff" : MUTED, cursor: "pointer" }}>
                  {clauseLibrary.umbrellas?.[f.umbrella]?.label || f.umbrella}
                </button>
              );
            })}
          </div>

          {/* gather docs + MLS sheet from the listing */}
          <div style={{ marginBottom: 14, paddingBottom: 12, borderBottom: `1px solid ${LINE}` }}>
            <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>Prep CPS Package</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input value={mlsInput} onChange={(e) => setMlsInput(e.target.value)} placeholder="Listing MLS #"
                style={{ width: 150, border: `1px solid ${LINE}`, borderRadius: 8, padding: "8px 10px", fontSize: 13, fontFamily: "inherit" }} />
              <button onClick={runGather} disabled={gathering || !mlsInput.trim()} title="CPS = Contract of Purchase and Sale. Pulls the title + MLS docs into the deal folder."
                style={{ fontSize: 13, fontWeight: 700, padding: "9px 14px", borderRadius: 8, border: "none",
                  background: gathering ? "#d7dce6" : NAVY, color: gathering ? "#8a93a6" : "#fff", cursor: gathering ? "wait" : "pointer" }}>
                {gathering ? "Starting…" : "Prep CPS Package →"}
              </button>
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 6 }}>
              Pulls the MLS sheet + every document on the listing's Docs tab into <b>2 - Deal Files / {"<address>"}</b>.
            </div>
            {gatherMsg && <div style={{ fontSize: 12, color: gatherMsg.startsWith("✓") ? "#2f7a4d" : TERRA, marginTop: 6 }}>{gatherMsg}</div>}
          </div>

          {/* deal terms that fill the CPS form */}
          <div style={{ marginBottom: 14, paddingBottom: 12, borderBottom: `1px solid ${LINE}` }}>
            <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 8 }}>Deal Terms</div>
            <div style={{ fontSize: 11, color: MUTED, marginBottom: 10 }}>
              Buyer &amp; seller names pull from the deal card&rsquo;s contacts; PID &amp; legal description pull from the title. Party mailing addresses are left blank to complete at signing.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2fr", gap: 9, marginBottom: 10 }}>
              <label style={{ display: "block" }}>
                <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>Purchase price</span>
                <input type="text" inputMode="decimal" value={terms.cpsPurchasePrice} placeholder="e.g. 499,900"
                  onChange={(e) => setTerm("cpsPurchasePrice", e.target.value)} onBlur={(e) => saveTerm("cpsPurchasePrice", e.target.value)}
                  style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
              </label>
              <label style={{ display: "block" }}>
                <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>Deposit amount</span>
                <input type="text" inputMode="decimal" value={terms.cpsDeposit} placeholder="e.g. 15,000"
                  onChange={(e) => setTerm("cpsDeposit", e.target.value)} onBlur={(e) => saveTerm("cpsDeposit", e.target.value)}
                  style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
              </label>
              <label style={{ display: "block" }}>
                <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>Deposit due (when it's paid)</span>
                <input type="text" value={terms.cpsDepositTerms} placeholder="within 24 hours of subject removal"
                  onChange={(e) => setTerm("cpsDepositTerms", e.target.value)} onBlur={(e) => saveTerm("cpsDepositTerms", e.target.value)}
                  style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
              </label>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 9, marginBottom: 10 }}>
              {([["subjectRemovalDate", "Subject Removal"], ["completionDate", "Completion"], ["possessionDate", "Possession"], ["adjustmentDate", "Adjustment"]] as [string, string][]).map(([k, lbl]) => (
                <label key={k} style={{ display: "block" }}>
                  <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>{lbl} date</span>
                  <input type="date" value={terms[k]} onChange={(e) => setTerm(k, e.target.value)} onBlur={(e) => saveTerm(k, e.target.value)}
                    style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
                </label>
              ))}
            </div>
            <label style={{ display: "block", marginBottom: 10, maxWidth: 200 }}>
              <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>Possession time (on possession date)</span>
              <input type="time" value={terms.possessionTime} onChange={(e) => setTerm("possessionTime", e.target.value)} onBlur={(e) => saveTerm("possessionTime", e.target.value)}
                style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
              {([["cpsInclusions", "Included items (stays with the property)"], ["cpsExclusions", "Excluded items"]] as [string, string][]).map(([k, lbl]) => (
                <label key={k} style={{ display: "block" }}>
                  <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>{lbl}</span>
                  <textarea value={terms[k]} rows={2} onChange={(e) => setTerm(k, e.target.value)} onBlur={(e) => saveTerm(k, e.target.value)}
                    placeholder={k === "cpsInclusions" ? "e.g. all appliances, window coverings, shed…" : "e.g. staging furniture, hot tub…"}
                    style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12, resize: "vertical", fontFamily: "inherit" }} />
                </label>
              ))}
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
              {checkbox(terms.buyerCanadian, () => { const v = !terms.buyerCanadian; setTerm("buyerCanadian", v); void saveTerm("buyerCanadian", v); })}
              <span style={{ fontSize: 13, color: "#2b2b2b" }}>Buyer is a Canadian citizen or permanent resident</span>
              {!terms.buyerCanadian && <span style={{ fontSize: 10.5, color: TERRA, fontWeight: 600 }}>· non-Canadian: foreign-buyer rules / extra PTT may apply</span>}
            </label>
          </div>

          {/* mobile-home property specs (for the score card) — only for mobile */}
          {umbrella === "mobile" && (
            <div style={{ marginBottom: 14, paddingBottom: 12, borderBottom: `1px solid ${LINE}` }}>
              <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 8 }}>Mobile Home Specs</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                {([["mhRegistration", "Registration #"], ["mhSerial", "Serial #"], ["mhCsaLabel", "CSA / Silver Label #"]] as [string, string][]).map(([k, lbl]) => (
                  <label key={k} style={{ display: "block" }}>
                    <span style={{ fontSize: 10.5, color: MUTED, fontWeight: 600 }}>{lbl}</span>
                    <input value={terms[k]} onChange={(e) => setTerm(k, e.target.value)} onBlur={(e) => saveTerm(k, e.target.value)}
                      style={{ width: "100%", marginTop: 3, border: `1px solid ${LINE}`, borderRadius: 7, padding: "6px 8px", fontSize: 12.5, fontFamily: "inherit" }} />
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* standard / active clauses */}
          {renderGroups(mainBySec)}

          {/* custom clauses for this deal */}
          {customClauses.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>Your custom clauses (this deal)</div>
              {customClauses.map((c) => (
                <div key={c.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "7px 4px", borderTop: "1px solid #f0f2f7" }}>
                  {checkbox(true, () => removeCustom(c.id))}
                  <span style={{ flex: 1, fontSize: 12.5, color: "#3a4257" }}>{c.wording}</span>
                  <span onClick={() => removeCustom(c.id)} style={{ color: MUTED, fontSize: 13, cursor: "pointer" }}>✕</span>
                </div>
              ))}
            </div>
          )}

          {/* add more clauses (collapsed) */}
          {moreCount > 0 && (
            <div style={{ marginTop: 4 }}>
              <button onClick={() => setShowMore((s) => !s)}
                style={{ display: "inline-flex", alignItems: "center", gap: 7, border: "none", background: "transparent", color: TERRA, fontWeight: 700, fontSize: 13, padding: "6px 0", cursor: "pointer" }}>
                {showMore ? "Hide extra clauses ▴" : `Add more clauses ▾ (${moreCount})`}
              </button>
              {showMore && <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px dashed ${LINE}` }}>{renderGroups(moreBySec)}</div>}
            </div>
          )}

          {/* add your own clause */}
          <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${LINE}` }}>
            <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>+ Add your own clause</div>
            <div style={{ display: "flex", gap: 8 }}>
              <textarea value={newText} onChange={(e) => setNewText(e.target.value)} rows={2}
                placeholder="Type a one-off clause for this deal…"
                style={{ flex: 1, border: `1px solid ${LINE}`, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, resize: "vertical", fontFamily: "inherit" }} />
              <button onClick={addCustom} disabled={!newText.trim()}
                style={{ alignSelf: "flex-start", fontSize: 13, fontWeight: 700, padding: "9px 14px", borderRadius: 8, border: `1.5px solid ${TERRA}`,
                  background: "#fff", color: newText.trim() ? TERRA : "#c7b3a8", cursor: newText.trim() ? "pointer" : "not-allowed" }}>Add</button>
            </div>
          </div>

          {/* build the offer package — one button, pick which forms ride along */}
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${LINE}` }}>
            <div style={{ fontSize: 11, letterSpacing: 0.6, color: MUTED, fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>Build offer package</div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14, marginBottom: 10, fontSize: 12.5 }}>
              <span style={{ color: MUTED }}>Include:</span>
              <label style={{ display: "flex", alignItems: "center", gap: 6, color: "#2b2b2b" }} title="Contract of Purchase and Sale — always included">
                <input type="checkbox" checked readOnly /> CPS
              </label>
              {OFFER_FORMS.map((f) => (
                <label key={f.key} style={{ display: "flex", alignItems: "center", gap: 6, color: "#2b2b2b", cursor: "pointer" }} title={f.full}>
                  <input type="checkbox" checked={pkgForms[f.key] ?? true} onChange={() => toggleForm(f.key)} /> {f.label}
                </label>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <button onClick={runPackage} disabled={packageBusy}
                style={{ flex: "0 0 auto", fontSize: 13, fontWeight: 700, padding: "9px 18px", borderRadius: 9, border: "none",
                  background: packageBusy ? "#d7dce6" : "#044B35", color: packageBusy ? "#8a93a6" : "#fff", cursor: packageBusy ? "wait" : "pointer" }}>
                {packageBusy ? "Building…" : "Build Offer Package →"}</button>
              {packageUrl && (
                <a href={packageUrl} target="_blank" rel="noreferrer"
                  style={{ fontSize: 13, fontWeight: 700, color: "#5E8AD0", textDecoration: "none" }}>Open Package ↗</a>
              )}
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 8 }}>Need a change? Edit a term, date, or clause above and Build again — the package regenerates with your edit.</div>
            {packageMsg && <div style={{ fontSize: 12, color: packageMsg.startsWith("✓") ? "#2f7a4d" : TERRA, marginTop: 6 }}>{packageMsg}</div>}
          </div>
        </div>
      )}
    </section>
  );
}
