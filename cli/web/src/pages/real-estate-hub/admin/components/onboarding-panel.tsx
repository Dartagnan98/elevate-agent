// Client Onboarding section for the buyer card — one section, 3 collapsible
// sub-sections: 1) Client Information (multiple buyers via "+ Add buyer"),
// 2) Property Search Criteria, 3) Onboarding Documents (Agency/DORTS/PNC shared
// + one FINTRAC per buyer → Generate → Approve & send for signatures).
import { useState, useEffect, useRef } from "react";
import { api } from "../../../../lib/api";

type AnyObj = Record<string, any>;
type FieldDef = { key: string; label: string; kind?: string; options?: string[] };
type BuyerRow = { name: string; email: string; phone: string };
const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", BLUE = "#5E8AD0", GREEN = "#2f7a4d", TERRA = "#C46340";

// Per-buyer fields become rows; the rest of Client Info stays deal-level.
const PER_BUYER = { name: "buyer.clientNames", email: "buyer.emails", phone: "buyer.phones" };
const PER_BUYER_KEYS = new Set(Object.values(PER_BUYER));

// Shared onboarding docs (one form covers all buyers). FINTRAC is per-buyer.
const DOCS: { key: string; label: string; sub: string }[] = [
  { key: "agency", label: "Designated Buyer's Agency Agreement", sub: "Agreement to represent the buyer(s)" },
  { key: "dorts", label: "DORTS — Disclosure of Representation", sub: "Given before providing services" },
  { key: "pnc", label: "PNC — Privacy Notice & Consent", sub: "Privacy consent" },
];
const SIGNABLE = new Set(["agency", "dorts", "pnc"]);

export default function OnboardingPanel({
  dealId, extra, currentStage,
  clientFields = [], searchFields = [], fieldValue, saveField,
}: {
  dealId: string; extra: AnyObj; currentStage?: number;
  clientFields?: FieldDef[]; searchFields?: FieldDef[];
  fieldValue?: (key: string) => string; saveField?: (key: string, value: string) => void;
}) {
  const sv = (k: string) => (typeof extra[k] === "string" ? (extra[k] as string) : "");
  const [status, setStatus] = useState<Record<string, string>>(() =>
    Object.fromEntries(DOCS.map((it) => [it.key, sv("onboard_" + it.key)])));
  const [fintrac, setFintrac] = useState<Record<number, string>>(() => {
    const raw = (extra as AnyObj).onboardFintrac;
    return Array.isArray(raw) ? Object.fromEntries(raw.map((v: string, i: number) => [i, v || ""])) : {};
  });
  const [busy, setBusy] = useState("");
  const [pkgMsg, setPkgMsg] = useState("");
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const open = manualOpen !== null ? manualOpen : (currentStage ?? 0) === 0;
  const [subOpen, setSubOpen] = useState<Record<string, boolean>>({ client: true, search: true, docs: true });
  const toggleSub = (k: string) => setSubOpen((s) => ({ ...s, [k]: !s[k] }));

  // Deal-level field overrides (mailing, timeline, financing, lender).
  const [fvals, setFvals] = useState<Record<string, string>>({});
  const fval = (k: string) => (fvals[k] !== undefined ? fvals[k] : (fieldValue ? fieldValue(k) : ""));
  const saveFv = (key: string, v: string) => { setFvals((s) => ({ ...s, [key]: v })); saveField?.(key, v); };

  // Buyer rows. Seed from saved onboardingBuyers, else from the legacy single
  // name/email/phone fields once they load (handled in the effect below).
  const [buyers, setBuyers] = useState<BuyerRow[]>(() => {
    const raw = (extra as AnyObj).onboardingBuyers;
    return Array.isArray(raw) && raw.length
      ? raw.map((b: AnyObj) => ({ name: b.name || "", email: b.email || "", phone: b.phone || "" }))
      : [{ name: "", email: "", phone: "" }];
  });
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const raw = (extra as AnyObj).onboardingBuyers;
    if (Array.isArray(raw) && raw.length) { seeded.current = true; return; }
    const nm = fieldValue?.(PER_BUYER.name) || "";
    if (nm) {
      setBuyers([{ name: nm, email: fieldValue?.(PER_BUYER.email) || "", phone: fieldValue?.(PER_BUYER.phone) || "" }]);
      seeded.current = true;
    }
  }, [extra, fieldValue]);

  const persistBuyers = (rows: BuyerRow[]) => {
    void api.setAdminDealToggle(dealId, "onboardingBuyers", rows as any);
    void api.setAdminDealToggle(dealId, "buyerClientNames", rows.map((r) => r.name.trim()).filter(Boolean) as any);
  };
  const setBuyerField = (i: number, k: keyof BuyerRow, v: string) =>
    setBuyers((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const addBuyer = () => setBuyers((rows) => { const n = [...rows, { name: "", email: "", phone: "" }]; persistBuyers(n); return n; });
  const removeBuyer = (i: number) => setBuyers((rows) => { const n = rows.filter((_, j) => j !== i); persistBuyers(n.length ? n : [{ name: "", email: "", phone: "" }]); return n.length ? n : [{ name: "", email: "", phone: "" }]; });

  const setDocStatus = (key: string, val: string) => {
    setStatus((s) => ({ ...s, [key]: val }));
    void api.setAdminDealToggle(dealId, "onboard_" + key, val || null);
  };
  const setFintracStatus = (i: number, val: string) => {
    setFintrac((s) => { const n = { ...s, [i]: val }; void api.setAdminDealToggle(dealId, "onboardFintrac", buyers.map((_, j) => n[j] || "") as any); return n; });
  };
  const genOne = async (key: string) => {
    const r = await api.sendOnboardingDoc(dealId, key);
    if (r.url) { setUrls((u) => ({ ...u, [key]: r.url as string })); void api.setAdminDealToggle(dealId, "onboard_" + key + "_url", r.url); }
    setDocStatus(key, "sent");
  };
  const sendDoc = async (key: string) => { setBusy(key); try { await genOne(key); } finally { setBusy(""); } };
  const sendPackage = async () => {
    setBusy("pkg"); setPkgMsg("");
    try {
      for (const k of unsigned) await genOne(k);
      const r = await api.sendForSignatures(dealId);
      setPkgMsg(r && (r as { runId?: string }).runId
        ? "Signing run dispatched. The envelope is being drafted — you'll get it to review and approve before anything sends to the clients."
        : "Dispatched. You'll get the envelope to review before it sends.");
    } catch {
      setPkgMsg("Could not dispatch the signing run. Try again, or check the deal's runs.");
    } finally { setBusy(""); }
  };

  const unsigned = [...SIGNABLE].filter((k) => status[k] !== "signed");
  const fintracDone = buyers.filter((_, i) => fintrac[i] === "verified").length;
  const docsDone = DOCS.filter((it) => status[it.key] === "signed").length + fintracDone;
  const docsTotal = DOCS.length + buyers.length;
  const namedBuyers = buyers.filter((b) => b.name.trim()).length;
  const clientFilled = namedBuyers + clientFields.filter((f) => !PER_BUYER_KEYS.has(f.key) && (fval(f.key) || "").trim()).length;
  const clientTotal = 1 + clientFields.filter((f) => !PER_BUYER_KEYS.has(f.key)).length;
  const searchFilled = searchFields.filter((f) => (fval(f.key) || "").trim()).length;
  const dealClientFields = clientFields.filter((f) => !PER_BUYER_KEYS.has(f.key));

  const STATE: Record<string, [string, string, string]> = {
    signed: ["done", "Signed", "signed"], verified: ["done", "Verified", "signed"],
    sent: ["pend", "Awaiting", "await"], "": ["todo", "To do", "todo"],
  };
  const dotS = (cls: string) => ({ done: { background: GREEN, color: "#fff" }, pend: { background: "#fdf1e9", color: TERRA, border: `1.5px solid #f0cdb6` }, todo: { background: "#fff", border: `1.6px solid #cdd5e2`, color: "transparent" } } as AnyObj)[cls];
  const tagS = (cls: string) => ({ signed: { background: "#eaf5ee", color: GREEN }, await: { background: "#fdf1e9", color: TERRA }, todo: { background: "#eef1f6", color: MUTED } } as AnyObj)[cls];
  const inS: React.CSSProperties = { width: "100%", border: `1px solid #dde3ee`, borderRadius: 7, padding: "7px 9px", fontSize: 12.5, fontWeight: 600, color: "#1c2433", background: "#fbfcfe", fontFamily: "inherit" };
  const lblS: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: "#9aa4b8", textTransform: "uppercase", letterSpacing: 0.3, display: "block", marginBottom: 3 };

  const fieldGrid = (fields: FieldDef[]) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      {fields.map((f) => (
        <label key={f.key} style={{ display: "block" }}>
          <span style={lblS}>{f.label}</span>
          {f.kind === "select" && f.options ? (
            <select value={fval(f.key)} onChange={(e) => saveFv(f.key, e.target.value)} style={inS}>
              <option value="">Not set</option>{f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input value={fval(f.key)} placeholder="Not set" onChange={(e) => setFvals((s) => ({ ...s, [f.key]: e.target.value }))} onBlur={(e) => saveFv(f.key, e.target.value)} style={inS} />
          )}
        </label>
      ))}
    </div>
  );

  const subHead = (key: string, num: string, title: string, statusText: string, done: boolean) => (
    <div onClick={() => toggleSub(key)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "11px 14px", background: "#fbfcfe", borderBottom: subOpen[key] ? "1px solid #eef1f6" : "none", cursor: "pointer" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ width: 22, height: 22, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 800, background: done ? GREEN : "#eef4fc", color: done ? "#fff" : "#2c4a78" }}>{done ? "✓" : num}</span>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: NAVY }}>{num} · {title}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: done ? GREEN : "#b0894d" }}>{statusText}</span>
        <span style={{ fontSize: 12, color: "#9aa4b8" }}>{subOpen[key] ? "▾" : "▸"}</span>
      </div>
    </div>
  );
  const subWrap: React.CSSProperties = { border: `1px solid ${LINE}`, borderRadius: 11, overflow: "hidden", marginBottom: 12 };

  const docRow = (key: string, label: string, sub: string, st: string, onAct: () => void, actLabel: string, viewUrl?: string) => {
    const [dotCls, tagLabel, tagCls] = STATE[st] || STATE[""];
    return (
      <div key={key} style={{ display: "flex", alignItems: "center", gap: 13, padding: "12px 2px", borderTop: "1px solid #f3f5f9" }}>
        <span style={{ width: 22, height: 22, borderRadius: "50%", flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, ...dotS(dotCls) }}>{dotCls === "done" ? "✓" : dotCls === "pend" ? "…" : ""}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: NAVY }}>{label}</div>
          <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>{sub}</div>
        </div>
        <span style={{ fontSize: 10.5, fontWeight: 700, borderRadius: 6, padding: "3px 9px", ...tagS(tagCls) }}>{tagLabel}</span>
        {(st === "signed" || st === "verified")
          ? (viewUrl !== undefined
            ? <a href={viewUrl || "#"} target="_blank" rel="noreferrer" style={{ fontSize: 12.5, fontWeight: 700, color: BLUE, textDecoration: "none" }}>View ↗</a>
            : <span style={{ fontSize: 12.5, fontWeight: 700, color: GREEN }}>✓</span>)
          : <button onClick={onAct} disabled={!!busy} style={{ fontSize: 12.5, fontWeight: 700, color: NAVY, border: `1px solid #cdd5e2`, borderRadius: 7, padding: "6px 12px", background: "#fff", cursor: "pointer" }}>{busy === key ? "…" : actLabel}</button>}
      </div>
    );
  };

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setManualOpen(!open)} style={{ padding: "14px 18px", background: NAVY, color: "#fff", cursor: "pointer" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 14.5, fontWeight: 700 }}>Client Onboarding</span>
          <span style={{ fontSize: 11.5, fontWeight: 700, color: "#aeb9d4" }}>{open ? "▾" : "▸"}</span>
        </div>
        <div style={{ fontSize: 11.5, color: "#aeb9d4", marginTop: 4 }}>Gather info → pick documents → generate → send for signatures.</div>
      </header>
      {open && (
        <div style={{ padding: "14px 14px 4px" }}>
          {/* 1 · Client Information */}
          <div style={subWrap}>
            {subHead("client", "1", "Client Information", `${clientFilled} of ${clientTotal} filled`, namedBuyers > 0 && clientFilled === clientTotal)}
            {subOpen.client && (
              <div style={{ padding: "13px 14px" }}>
                {buyers.map((b, i) => (
                  <div key={i} style={{ marginBottom: 10, paddingBottom: 10, borderBottom: i < buyers.length - 1 ? "1px solid #f0f2f7" : "none" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.3 }}>Buyer {i + 1}</span>
                      {buyers.length > 1 && <span onClick={() => removeBuyer(i)} style={{ fontSize: 12, color: "#b7c0d0", cursor: "pointer" }}>✕ remove</span>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1.3fr 1fr", gap: 9 }}>
                      <label><span style={lblS}>Name</span><input value={b.name} placeholder="Full legal name" onChange={(e) => setBuyerField(i, "name", e.target.value)} onBlur={() => persistBuyers(buyers)} style={inS} /></label>
                      <label><span style={lblS}>Email</span><input value={b.email} placeholder="email" onChange={(e) => setBuyerField(i, "email", e.target.value)} onBlur={() => persistBuyers(buyers)} style={inS} /></label>
                      <label><span style={lblS}>Phone</span><input value={b.phone} placeholder="phone" onChange={(e) => setBuyerField(i, "phone", e.target.value)} onBlur={() => persistBuyers(buyers)} style={inS} /></label>
                    </div>
                  </div>
                ))}
                <button onClick={addBuyer} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: `1.5px dashed #c7d0e0`, background: "#fafbfd", color: NAVY, fontSize: 12.5, fontWeight: 700, padding: "7px 14px", borderRadius: 8, cursor: "pointer", marginBottom: 12 }}>+ Add buyer</button>
                {dealClientFields.length > 0 && fieldGrid(dealClientFields)}
              </div>
            )}
          </div>

          {/* 2 · Property Search Criteria */}
          <div style={subWrap}>
            {subHead("search", "2", "Property Search Criteria", `${searchFilled} of ${searchFields.length} filled`, searchFields.length > 0 && searchFilled >= Math.ceil(searchFields.length / 2))}
            {subOpen.search && <div style={{ padding: "13px 14px" }}>{fieldGrid(searchFields)}</div>}
          </div>

          {/* 3 · Onboarding Documents */}
          <div style={subWrap}>
            {subHead("docs", "3", "Onboarding Documents", `${docsDone} of ${docsTotal} complete`, docsDone === docsTotal)}
            {subOpen.docs && (
              <div style={{ padding: "6px 14px 12px" }}>
                <div style={{ fontSize: 10.5, fontWeight: 800, color: "#9aa4b8", textTransform: "uppercase", letterSpacing: 0.4, margin: "8px 0 0" }}>Shared (all buyers sign)</div>
                {DOCS.map((it) => docRow(it.key, it.label, it.sub, status[it.key] || "",
                  () => sendDoc(it.key), status[it.key] === "sent" ? "Resend" : "Generate",
                  urls[it.key] || sv("onboard_" + it.key + "_url")))}
                <div style={{ fontSize: 10.5, fontWeight: 800, color: "#9aa4b8", textTransform: "uppercase", letterSpacing: 0.4, margin: "14px 0 0" }}>FINTRAC ID — one per buyer</div>
                {buyers.map((b, i) => docRow(`fintrac-${i}`, `FINTRAC — ${b.name.trim() || `Buyer ${i + 1}`}`, "Individual identification record", fintrac[i] || "",
                  () => setFintracStatus(i, "verified"), "Mark verified"))}
                {unsigned.length > 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 14, paddingTop: 13, borderTop: "1px solid #eef1f6" }}>
                    <button onClick={sendPackage} disabled={!!busy} style={{ background: "#044B35", border: "none", color: "#fff", fontSize: 13, fontWeight: 700, padding: "11px 18px", borderRadius: 9, cursor: "pointer" }}>{busy === "pkg" ? "Dispatching…" : "Approve & send for signatures →"}</button>
                    <span style={{ fontSize: 11, color: MUTED }}>Bundles the agency, DORTS &amp; PNC (all buyers' names + signature lines) into one envelope.</span>
                  </div>
                )}
                {pkgMsg && (
                  <div style={{ marginTop: 10, fontSize: 12, fontWeight: 600, color: pkgMsg.startsWith("Could not") ? TERRA : GREEN, background: pkgMsg.startsWith("Could not") ? "#fdf1e9" : "#eaf5ee", borderRadius: 8, padding: "9px 12px" }}>{pkgMsg}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
