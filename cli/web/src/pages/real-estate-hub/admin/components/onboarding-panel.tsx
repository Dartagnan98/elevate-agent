// Client Onboarding section — one section, 3 collapsible sub-sections, shown on
// BOTH the buyer card and the seller card. On a seller card it captures the
// same three things: who the client is, what they are doing NEXT (most sellers
// buy again, and the ones who leave town get referred out), and the DORTS +
// PNC every client signs regardless of side.
// Original buyer-card note:
// Client Onboarding section for the buyer card — one section, 3 collapsible
// sub-sections: 1) Client Information (multiple buyers via "+ Add buyer"),
// 2) Property Search Criteria, 3) Onboarding Documents (Agency/DORTS/PNC shared
// → Generate → Approve & send for signatures). No FINTRAC: Skyleigh does
// not do FINTRAC on a form (2026-07-27).
import { useState, useEffect, useRef } from "react";
import { api } from "../../../../lib/api";
import KitDocumentList, { type KitDocState, useSendCheck, SendGapWarning } from "./kit-document-list";
import { useIsMobile } from "../../../../hooks/useIsMobile";

type AnyObj = Record<string, any>;
type FieldDef = { key: string; label: string; kind?: string; options?: string[] };
type BuyerRow = { name: string; email: string; phone: string };
const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", GREEN = "#2f7a4d", TERRA = "#C46340";

// Per-client fields become rows; the rest of Client Info stays deal-level.
// The seller card writes the same three values onto the seller.* keys the
// Seller Information section, the MLC and the signing package already read, so
// there is one truth per deal rather than a second onboarding-only copy.
const PER_PARTY = {
  buyer:   { name: "buyer.clientNames",  email: "buyer.emails",  phone: "buyer.phones" },
  listing: { name: "seller.legalNames",  email: "seller.emails", phone: "seller.phones" },
};

// Shared onboarding docs (one form covers all buyers).
// `fields` are the values the operator can correct by hand on the card before
// re-drafting; they map onto the keys the fill scripts read off the deal.
type DocField = { key: string; label: string; placeholder?: string };
type DocDef = { key: string; label: string; fields: DocField[] };
const AGENCY_DOC: DocDef = {
  key: "agency", label: "Designated Buyer's Agency Agreement",
  fields: [
    { key: "buyers", label: "Client name(s)" },
    { key: "buyerAddress", label: "Client mailing address" },
    { key: "buyerPhone", label: "Client phone" },
    { key: "termMonths", label: "Term (months)" },
    { key: "commission", label: "Remuneration" },
  ],
};
const DOCS: DocDef[] = [
  AGENCY_DOC,
  {
    key: "dorts", label: "DORTS — Disclosure of Representation",
    // signingDate is read by offer-prep-forms.py before it fills anything, so it
    // sets every date slot on the form. Blank = today. She back-dates this one.
    fields: [
      { key: "buyers", label: "Client name(s)" },
      { key: "signingDate", label: "Date on the form", placeholder: "blank = today, e.g. 2026-06-15" },
    ],
  },
  {
    key: "pnc", label: "PNC — Privacy Notice & Consent",
    fields: [
      { key: "buyers", label: "Client name(s)" },
      { key: "signingDate", label: "Date on the form", placeholder: "blank = today, e.g. 2026-06-15" },
    ],
  },
];
// Seller card: DORTS + PNC always, because a seller signs exactly the same two
// disclosures a buyer does. The Buyer's Agency Agreement only joins them once
// the Next Move answer says this seller is buying again HERE -- a seller who is
// leaving the area gets referral paperwork instead, not an agency agreement.
const SELLER_BASE_DOCS: DocDef[] = DOCS.filter((d) => d.key !== "agency");
function docsForSide(isListing: boolean, buyingLocally: boolean): DocDef[] {
  if (!isListing) return DOCS;
  return buyingLocally ? [...SELLER_BASE_DOCS, AGENCY_DOC] : SELLER_BASE_DOCS;
}

export default function OnboardingPanel({
  dealId, extra, currentStage, side = "buyer",
  clientFields = [], searchFields = [], fieldValue, saveField,
}: {
  dealId: string; extra: AnyObj; currentStage?: number;
  side?: "buyer" | "listing";
  clientFields?: FieldDef[]; searchFields?: FieldDef[];
  fieldValue?: (key: string) => string; saveField?: (key: string, value: string) => void;
}) {
  const isMobile = useIsMobile();
  const isListing = side === "listing";
  const partyNoun = isListing ? "Seller" : "Buyer";
  const perParty = isListing ? PER_PARTY.listing : PER_PARTY.buyer;
  const perPartyKeys = new Set(Object.values(perParty));
  // Where the rows live on the deal. A deal is one side or the other, so these
  // never collide -- the separate key just keeps a seller card readable.
  const rowsKey = isListing ? "onboardingSellers" : "onboardingBuyers";
  const namesKey = isListing ? "sellerLegalNames" : "buyerClientNames";
  const sv = (k: string) => (typeof extra[k] === "string" ? (extra[k] as string) : "");
  // Status is DERIVED from the deal, not snapshotted at mount. The lazy
  // initializer that used to seed it ran on the first render, before the card's
  // context had loaded, so `extra` was still empty and every document read
  // "Not drafted yet" forever — even with the PDF sitting on disk. A local
  // override layers on top so a draft started here shows immediately.
  const [statusOverride, setStatusOverride] = useState<Record<string, string>>({});
  // Next Move drives which documents this seller actually needs. Read through
  // fieldValue so it reflects an edit made in section 2 without a card reload.
  const nextMove = (fieldValue ? fieldValue("seller.nextMove") : "") || sv("seller.nextMove");
  const buyingLocally = /buying locally/i.test(nextMove);
  const docs = docsForSide(isListing, buyingLocally);
  const signable = docs.map((d) => d.key);
  const status: Record<string, string> = Object.fromEntries(
    docs.map((it) => [it.key, statusOverride[it.key] ?? sv("onboard_" + it.key)]));
  const [busy, setBusy] = useState("");
  // Which documents go in the envelope. Signed docs are never included.
  const [sel, setSel] = useState<Set<string>>(() => new Set(docs.map((d) => d.key)));
  const toggleSel = (k: string) => setSel((prev) => {
    const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n;
  });
  // Choosing what goes in the envelope happens at the moment of sending, not as
  // a permanent control on every row (same as the Transaction Kit).
  const [sendOpen, setSendOpen] = useState(false);
  // Onboarding's DORTS carries the same "representing you / not representing
  // you" tick the kits do, so it gets the same pre-send check.
  const sendGaps = useSendCheck(dealId, "onboarding", Array.from(sel), sendOpen);
  const [pkgMsg, setPkgMsg] = useState("");
  // Which doc rows are mid-draft right now, which row has its Edit panel open,
  // and the per-doc manual overrides (seeded from what the last draft used).
  const [drafting, setDrafting] = useState<Record<string, boolean>>({});
  const [docFields, setDocFields] = useState<Record<string, Record<string, string>>>(() => {
    const saved = (extra as AnyObj).onboardingDocs;
    const out: Record<string, Record<string, string>> = {};
    if (saved && typeof saved === "object") {
      for (const [k, v] of Object.entries(saved as AnyObj)) {
        const f = (v as AnyObj)?.fields;
        if (f && typeof f === "object") {
          out[k] = Object.fromEntries(Object.entries(f).map(([a, b]) => [a, String(b ?? "")]));
        }
      }
    }
    // Edits saved on blur but not yet redrafted win over the last generated set.
    const pending = (extra as AnyObj).onboardingDocFields;
    if (pending && typeof pending === "object") {
      for (const [k, v] of Object.entries(pending as AnyObj)) {
        if (v && typeof v === "object") {
          out[k] = { ...(out[k] || {}), ...Object.fromEntries(Object.entries(v as AnyObj).map(([a, b]) => [a, String(b ?? "")])) };
        }
      }
    }
    return out;
  });
  const setDf = (doc: string, key: string, v: string) =>
    setDocFields((s) => ({ ...s, [doc]: { ...(s[doc] || {}), [key]: v } }));
  // Persist on blur so leaving the field keeps the edit even if the panel is
  // closed or the card reloaded. Draft/Redraft is still what rebuilds the PDF.
  const persistDf = (doc: string, key: string, v: string) => {
    const next = { ...docFields, [doc]: { ...(docFields[doc] || {}), [key]: v } };
    void api.setAdminDealToggle(dealId, "onboardingDocFields", next as any);
  };
  // Fields the LAST draft actually used. Compared against what the card shows
  // now, this tells us whether the PDF on disk is out of date.
  const draftedFields = (key: string): Record<string, string> => {
    const f = (((extra as AnyObj).onboardingDocs || {})[key] || {}).fields;
    return f && typeof f === "object"
      ? Object.fromEntries(Object.entries(f as AnyObj).map(([a, b]) => [a, String(b ?? "")]))
      : {};
  };
  // Compare EVERY value saved on this document against what the last draft
  // used — not just a fixed list of keys. The card now shows whatever fields
  // the document actually has, so a hardcoded comparison would miss an edit to
  // any of them and quietly send a PDF that disagrees with the card.
  const isStale = (key: string) => {
    const was = draftedFields(key);
    const now = docFields[key] || {};
    return Object.keys(now).some((k) => (was[k] ?? "") !== (now[k] ?? ""));
  };
  const draftedAt = (key: string) =>
    (((extra as AnyObj).onboardingDocs || {})[key] || {}).generatedAt || "";
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const [subOpen, setSubOpen] = useState<Record<string, boolean>>({ client: true, search: true, docs: true });
  const toggleSub = (k: string) => setSubOpen((s) => ({ ...s, [k]: !s[k] }));

  // Deal-level field overrides (mailing, timeline, financing, lender).
  const [fvals, setFvals] = useState<Record<string, string>>({});
  const fval = (k: string) => (fvals[k] !== undefined ? fvals[k] : (fieldValue ? fieldValue(k) : ""));
  const saveFv = (key: string, v: string) => { setFvals((s) => ({ ...s, [key]: v })); saveField?.(key, v); };

  // Client rows. Seed from the saved rows, else from the legacy single
  // name/email/phone fields once they load (handled in the effect below).
  const [buyers, setBuyers] = useState<BuyerRow[]>(() => {
    const raw = (extra as AnyObj)[rowsKey];
    return Array.isArray(raw) && raw.length
      ? raw.map((b: AnyObj) => ({ name: b.name || "", email: b.email || "", phone: b.phone || "" }))
      : [{ name: "", email: "", phone: "" }];
  });
  // Seed buyer rows ONLY from saved onboardingBuyers, never from the lossy
  // fallback getters (buyer.clientNames falls back to the deal title, buyer.emails
  // to every contact email on the deal incl. the lender). Seeding from those and
  // then persisting on blur is what wiped real client email/phone. Seed once when
  // the saved value arrives; until then leave the blank row and never auto-persist.
  const seeded = useRef(false);
  const dirty = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const raw = (extra as AnyObj)[rowsKey];
    if (Array.isArray(raw) && raw.length) {
      setBuyers(raw.map((b: AnyObj) => ({ name: b.name || "", email: b.email || "", phone: b.phone || "" })));
      seeded.current = true;
    }
  }, [extra]);

  // Name the actual client on every confirmation — the last real safeguard
  // before anything client-facing (same rule as the Transaction Kit).
  const clientLabel = buyers.map((b) => b.name.trim()).filter(Boolean).join(" & ") || "the clients";

  const persistBuyers = (rows: BuyerRow[]) => {
    void api.setAdminDealToggle(dealId, rowsKey, rows as any);
    void api.setAdminDealToggle(dealId, namesKey, rows.map((r) => r.name.trim()).filter(Boolean) as any);
    // Seller side only: also land email + phone on the seller.* keys the Seller
    // Information section, the MLC fill and the signing package read, so the
    // card is not the only place they exist. The buyer path is left exactly as
    // it was -- seeding buyer email/phone from lossy getters is what wiped real
    // contact details once already (see the seeding note above).
    if (isListing) {
      const emails = rows.map((r) => r.email.trim()).filter(Boolean).join("; ");
      const phones = rows.map((r) => r.phone.trim()).filter(Boolean).join("; ");
      void api.setAdminDealToggle(dealId, "sellerEmails", emails || null);
      void api.setAdminDealToggle(dealId, "sellerPhones", phones || null);
    }
  };
  // Only persist rows the user actually touched — a bare blur with no edit must
  // never overwrite saved data.
  const persistIfDirty = () => { if (dirty.current) persistBuyers(buyers); };
  const setBuyerField = (i: number, k: keyof BuyerRow, v: string) => {
    dirty.current = true;
    setBuyers((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  };
  const addBuyer = () => { dirty.current = true; setBuyers((rows) => { const n = [...rows, { name: "", email: "", phone: "" }]; persistBuyers(n); return n; }); };
  const removeBuyer = (i: number) => { dirty.current = true; setBuyers((rows) => { const n = rows.filter((_, j) => j !== i); persistBuyers(n.length ? n : [{ name: "", email: "", phone: "" }]); return n.length ? n : [{ name: "", email: "", phone: "" }]; }); };

  const setDocStatus = (key: string, val: string) => {
    setStatusOverride((s) => ({ ...s, [key]: val }));
    void api.setAdminDealToggle(dealId, "onboard_" + key, val || null);
  };
  const genOne = async (key: string) => {
    setDrafting((s) => ({ ...s, [key]: true }));
    try {
      const r = await api.sendOnboardingDoc(dealId, key, docFields[key]);
      if (r.url) { void api.setAdminDealToggle(dealId, "onboard_" + key + "_url", r.url); }
      setDocStatus(key, "drafted");
      setPkgMsg("");
    } catch (e) {
      // Say so on the card. Before this the failure was swallowed by a bare
      // try/finally, the row still flipped to Drafted, and the only signal was
      // an unchanged PDF. (2026-07-29)
      setPkgMsg(`Could not draft the ${key.toUpperCase()}: ${(e as Error)?.message || "unknown error"}. Nothing was changed.`);
      throw e;
    } finally {
      setDrafting((s) => ({ ...s, [key]: false }));
    }
  };
  // The one button: draft every shared doc that isn't signed yet, in order, so
  // each row flips To do -> Drafting -> Drafted as it lands.
  const draftAll = async () => {
    setBusy("draft"); setPkgMsg("");
    try {
      for (const k of unsigned) await genOne(k);
    } catch {
      setPkgMsg("Could not draft one of the documents. Check the deal's runs and try again.");
    } finally { setBusy(""); }
  };
  const redraftOne = async (key: string) => {
    setBusy(key);
    try { await genOne(key); } finally { setBusy(""); }
  };
  // Same desktop-shell constraint as the offer-kit / listing-kit doc opens: a
  // window.open onto the BACKEND origin is allowed straight into an Electron
  // window, which has no PDF plugin, so the tab comes up blank. Swapping the
  // loopback host (127.0.0.1 <-> localhost) puts the URL off the backend origin,
  // so the shell hands it to the real browser, which renders PDFs. The token
  // rides as ?token= because window.open can't set an Authorization header --
  // web_auth.py allowlists this read-only path (_ONBOARDING_DOC_PATH_RE).
  const openDoc = async (key: string, download = false) => {
    // Never show a PDF that disagrees with the card. A signed doc is frozen and
    // must never be regenerated.
    if (status[key] !== "signed" && isDrafted(key) && isStale(key)) await genOne(key);
    const tok = (window as AnyObj).__ELEVATE_SESSION_TOKEN__ || "";
    const origin = window.location.origin;
    const externalOrigin = origin.includes("127.0.0.1")
      ? origin.replace("127.0.0.1", "localhost")
      : origin.replace("localhost", "127.0.0.1");
    window.open(
      `${externalOrigin}/api/admin/deals/${encodeURIComponent(dealId)}/onboarding-doc/${encodeURIComponent(key)}?token=${encodeURIComponent(tok)}&v=${Date.now()}${download ? "&download=1" : ""}`,
      "_blank", "noopener,noreferrer");
  };
  const sendPackage = async () => {
    const chosen = unsigned.filter((k) => sel.has(k));
    if (!chosen.length) { setPkgMsg("Pick at least one document to send."); return; }
    setBusy("pkg"); setPkgMsg("");
    try {
      // Rebuild anything missing OR edited since its last draft, so the envelope
      // can never carry a PDF that disagrees with the card. Signed docs are
      // already excluded (`unsigned`) and are never regenerated.
      for (const k of chosen.filter((k) => !isDrafted(k) || isStale(k))) await genOne(k);
      const r = await api.sendForSignatures(dealId, chosen);
      setPkgMsg(r && (r as { runId?: string }).runId
        ? "Signing run dispatched. The envelope is being drafted — you'll get it to review and approve before anything sends to the clients."
        : "Dispatched. You'll get the envelope to review before it sends.");
    } catch {
      setPkgMsg("Could not dispatch the signing run. Try again, or check the deal's runs.");
    } finally { setBusy(""); }
  };

  const unsigned = signable.filter((k) => status[k] !== "signed");
  const selectedCount = unsigned.filter((k) => sel.has(k)).length;
  // A row is only Drafted if the PDF actually landed. The status toggle alone
  // lies: a run that failed part-way (or predates onboardingDocs bookkeeping)
  // leaves onboard_<form>="sent" with no file, so the row claimed Drafted and
  // Open PDF 404'd. Requiring the recorded filePath makes the badge honest and
  // puts the row back in the draft queue so the one button re-fills it.
  // "sent" is the legacy spelling of drafted.
  const docFile = (k: string) =>
    (((extra as AnyObj).onboardingDocs || {})[k] || {}).filePath || "";
  const isDrafted = (k: string) =>
    ["drafted", "sent", "signed"].includes(status[k] || "") &&
    (status[k] === "signed" || !!docFile(k));
  // What "Draft the N remaining" acts on: never drafted, or edited since.
  const toDraft = unsigned.filter((k) => !isDrafted(k) || isStale(k));
  const anyDrafting = Object.values(drafting).some(Boolean);
  const docsDone = docs.filter((it) => status[it.key] === "signed").length;
  const docsTotal = docs.length;
  const namedBuyers = buyers.filter((b) => b.name.trim()).length;
  const clientFilled = namedBuyers + clientFields.filter((f) => !perPartyKeys.has(f.key) && (fval(f.key) || "").trim()).length;
  const clientTotal = 1 + clientFields.filter((f) => !perPartyKeys.has(f.key)).length;
  const searchFilled = searchFields.filter((f) => (fval(f.key) || "").trim()).length;
  const dealClientFields = clientFields.filter((f) => !perPartyKeys.has(f.key));
  // Onboarding is "done enough" to hand off to Offer Prep once the buyer is
  // identified (name + a way to reach them) and the search / subject is captured.
  // The signing docs (Agency/DORTS/PNC) are tracked below but do NOT gate the
  // handoff — they get signed alongside offer prep. When this is true the panel
  // defaults COLLAPSED so Offer Prep is the focus; clicking the header reopens it
  // (manualOpen always wins).
  const hasBuyerContact = buyers.some((b) => b.email.trim() || b.phone.trim());
  const infoComplete = namedBuyers > 0 && hasBuyerContact
    && searchFields.length > 0 && searchFilled >= Math.ceil(searchFields.length / 2);
  const open = manualOpen !== null ? manualOpen : ((currentStage ?? 0) === 0 && !infoComplete);

  // "sent" is the legacy value written by the old Generate button — it only ever
  // meant "the PDF was filled", never that anything reached a client, so it
  // reads as Drafted alongside the current value.
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
  // Same shape and tokens as the Transaction Kit's secondary button, so a
  // "Draft the N remaining" looks identical wherever it appears.
  const rowBtn: React.CSSProperties = { fontSize: 12.5, fontWeight: 700, color: "var(--ds-ink)", border: `1px solid var(--ds-border-strong)`, borderRadius: 7, padding: "8px 14px", background: "#fff", cursor: "pointer" };
  const subWrap: React.CSSProperties = { border: `1px solid ${LINE}`, borderRadius: 11, overflow: "hidden", marginBottom: 12 };


  // Every paperwork surface on the card renders through the same list, so
  // Onboarding, the Transaction Kit and the Listing Kit stay identical. This
  // adapter maps onboarding's own status vocabulary onto it.
  const rowState = (key: string): KitDocState => {
    if (drafting[key]) return "building";
    if (status[key] === "signed") return "ready";
    if (!isDrafted(key)) return "unbuilt";
    return isStale(key) ? "stale" : "ready";
  };
  const docRows = docs.map((d) => ({
    id: d.key,
    name: d.label,
    state: rowState(d.key),
    statusText: status[d.key] === "signed" ? "Signed" : undefined,
    generatedAt: draftedAt(d.key) || undefined,
  }));

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setManualOpen(!open)} style={{ padding: "14px 18px", background: NAVY, color: "#fff", cursor: "pointer" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 14.5, fontWeight: 700 }}>Client Onboarding</span>
          <span style={{ fontSize: 11.5, fontWeight: 700, color: "#aeb9d4" }}>{open ? "▾" : "▸"}</span>
        </div>
        <div style={{ fontSize: 11.5, color: "#aeb9d4", marginTop: 4 }}>
          {isListing
            ? "Client details → what they are buying next → DORTS + PNC → draft → send for signature."
            : "Client details → documents → draft → send for signature."}
        </div>
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
                      <span style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.3 }}>{partyNoun} {i + 1}</span>
                      {buyers.length > 1 && <span onClick={() => removeBuyer(i)} style={{ fontSize: 12, color: "#b7c0d0", cursor: "pointer" }}>✕ remove</span>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1.3fr 1fr", gap: 9 }}>
                      <label><span style={lblS}>Name</span><input value={b.name} placeholder="Full legal name" onChange={(e) => setBuyerField(i, "name", e.target.value)} onBlur={persistIfDirty} style={inS} /></label>
                      <label><span style={lblS}>Email</span><input value={b.email} placeholder="email" onChange={(e) => setBuyerField(i, "email", e.target.value)} onBlur={persistIfDirty} style={inS} /></label>
                      <label><span style={lblS}>Phone</span><input value={b.phone} placeholder="phone" onChange={(e) => setBuyerField(i, "phone", e.target.value)} onBlur={persistIfDirty} style={inS} /></label>
                    </div>
                  </div>
                ))}
                <button onClick={addBuyer} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: `1.5px dashed #c7d0e0`, background: "#fafbfd", color: NAVY, fontSize: 12.5, fontWeight: 700, padding: "7px 14px", borderRadius: 8, cursor: "pointer", marginBottom: 12 }}>+ Add {partyNoun.toLowerCase()}</button>
                {dealClientFields.length > 0 && fieldGrid(dealClientFields)}
              </div>
            )}
          </div>

          {/* 2 · Property Search Criteria */}
          <div style={subWrap}>
            {subHead("search", "2", isListing ? "Next Move + Property Search" : "Property Search Criteria", `${searchFilled} of ${searchFields.length} filled`, searchFields.length > 0 && searchFilled >= Math.ceil(searchFields.length / 2))}
            {subOpen.search && <div style={{ padding: "13px 14px" }}>{fieldGrid(searchFields)}</div>}
          </div>

          {/* 3 · Onboarding Documents */}
          <div style={subWrap}>
            {subHead("docs", "3", "Onboarding Documents", `${docsDone} of ${docsTotal} signed`, docsDone === docsTotal)}
            {subOpen.docs && (
              <div style={{ padding: "6px 14px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, margin: "8px 0 4px" }}>
                  <span style={{ fontSize: 12.5, color: MUTED }}>
                    {anyDrafting || busy === "draft"
                      ? "Drafting…"
                      : `${signable.filter(isDrafted).length} drafted. ${toDraft.length} still to draft.`}
                  </span>
                  {/* Same shape as the Transaction Kit: a quiet catch-up action
                      that disappears when there is nothing left to catch up on. */}
                  {toDraft.length > 0 && (
                    <button onClick={draftAll} disabled={!!busy}
                      style={{ ...rowBtn, whiteSpace: "nowrap", opacity: busy ? 0.7 : 1, minHeight: isMobile ? 44 : undefined }}>
                      {anyDrafting || busy === "draft" ? "Drafting…" : `Draft the ${toDraft.length} remaining`}
                    </button>
                  )}
                </div>
                <KitDocumentList
                  rows={docRows}
                  fieldDefs={[]}
                  fieldsUrl={(id) =>
                    `/api/admin/deals/${encodeURIComponent(dealId)}/onboarding-doc/${encodeURIComponent(id)}/fields?v=${Date.now()}`}
                  previewUrl={(id, page, dpi) =>
                    `/api/admin/deals/${encodeURIComponent(dealId)}/onboarding-doc/${encodeURIComponent(id)}/preview?page=${page}&dpi=${dpi}&v=${Date.now()}`}
                  onDraft={(id) => redraftOne(id)}
                  onOpen={(id, download) => void openDoc(id, download)}
                  onSaveField={(id, key, value) => { setDf(id, key, value); persistDf(id, key, value); }}
                  isMobile={isMobile}
                  isNarrow={isMobile}
                  footNote="Edits save as you type. Drafting opens the document so you can read it first — it stays on this machine until you save it to Drive or send it for signature."
                />
                {unsigned.length > 0 && !sendOpen && (
                  <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 14, paddingTop: 13, borderTop: "1px solid #eef1f6" }}>
                    <button onClick={() => { setSel(new Set(unsigned.filter(isDrafted))); setSendOpen(true); }}
                      disabled={!!busy || !unsigned.some(isDrafted)}
                      style={{ background: unsigned.some(isDrafted) ? TERRA : "#9aa6bd", border: "none", color: "#fff", fontSize: 13.5, fontWeight: 700, padding: "11px 18px", borderRadius: 9, cursor: unsigned.some(isDrafted) ? "pointer" : "default", minHeight: isMobile ? 46 : undefined }}>
                      {unsigned.filter(isDrafted).length ? `Send ${unsigned.filter(isDrafted).length} for signature` : "Send for signature"}
                    </button>
                    <span style={{ flexBasis: "100%", fontSize: 12, color: MUTED }}>
                      Sending redrafts anything you edited first. Nothing reaches {clientLabel} without the review card.
                    </span>
                  </div>
                )}
                {sendOpen && (
                  <div style={{ marginTop: 14, border: `1px solid ${LINE}`, borderRadius: 11, background: "#fbfcfe", padding: "15px 16px" }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: NAVY }}>Send to {clientLabel}?</div>
                    <div style={{ fontSize: 12.5, color: MUTED, margin: "4px 0 10px" }}>
                      One DigiSign envelope. Untick anything you are not sending yet — it stays on the deal.
                    </div>
                    {unsigned.filter(isDrafted).map((k) => {
                      const on = sel.has(k);
                      return (
                        <button key={k} type="button" role="checkbox" aria-checked={on} onClick={() => toggleSel(k)}
                          style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 0", width: "100%", background: "none", border: "none", borderTop: "1px solid #eef1f6", textAlign: "left", font: "inherit", cursor: "pointer", minHeight: isMobile ? 44 : undefined }}>
                          <span aria-hidden="true" style={{ width: 20, height: 20, borderRadius: 6, flexShrink: 0, background: on ? NAVY : "#fff", border: `1.6px solid ${on ? NAVY : "#cdd5e2"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 12 }}>{on ? "✓" : ""}</span>
                          <span style={{ fontSize: 13.5, fontWeight: 600, color: on ? NAVY : "#9aa4b8" }}>{docs.find((d) => d.key === k)?.label || k}</span>
                        </button>
                      );
                    })}
                    <SendGapWarning gaps={sendGaps.filter((g) => sel.has(g.id))}
                      nameOf={(id) => docs.find((d) => d.key === id)?.label} />
                    <div style={{ display: "flex", gap: 9, marginTop: 13, alignItems: "center", flexWrap: "wrap" }}>
                      <button onClick={() => setSendOpen(false)} style={{ ...rowBtn, minHeight: isMobile ? 44 : undefined }}>Cancel</button>
                      <button onClick={() => { setSendOpen(false); void sendPackage(); }} disabled={!!busy || selectedCount === 0}
                        style={{ ...rowBtn, background: selectedCount === 0 ? "#9aa6bd" : TERRA, borderColor: "transparent", color: "#fff", minHeight: isMobile ? 44 : undefined }}>
                        {busy === "pkg" ? "Dispatching…" : `Send ${selectedCount} to ${clientLabel}`}
                      </button>
                      <span style={{ fontSize: 12, color: MUTED }}>Nothing sends — it lands as a review card first.</span>
                    </div>
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
