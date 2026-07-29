// Offer Kit wizard (buyer side) — replaces the old OfferPrepPanel + kit list with
// a 4-step flow: Property -> Terms -> Subjects -> Build & Preview. Step 1 here;
// later steps land incrementally. Selections persist to deals.extra_toggles_json
// via setAdminDealToggle (bare keys), so the existing backend reads them as-is.
import React, { useState, useCallback, useEffect } from "react";
import { api } from "../../../../lib/api";
import { clauseLibrary } from "../cps/cps-libraries";
import ClausePickerModal from "./clause-picker-modal";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import KitDocumentList, { type KitDocState, useSendCheck, SendGapWarning } from "./kit-document-list";

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

const STEPS = ["Property", "Terms", "Subjects", "Documents"];

// The kit has to be able to name the client. Intake paths write the buyer's
// name to different keys (a plain string from SkySlope, an array from
// onboarding, objects from the workflow), and reading only `buyerNames` is why
// the header said "Buyer" and the send sheet said "the buyer(s)" on any deal
// that came in through onboarding. Naming the actual person is the last real
// safeguard before something goes to a client, so this reads every source.
const _has = (extra: AnyObj, k: string) => !!String(extra[k] ?? "").trim();
const propertyComplete = (extra: AnyObj) =>
  _has(extra, "pid") || _has(extra, "legalDescription") || _has(extra, "legal");
const termsComplete = (extra: AnyObj) =>
  _has(extra, "cpsPurchasePrice") && _has(extra, "completionDate");
function initialStep(extra: AnyObj, currentStage: number): number {
  if (currentStage >= 2) return 4;
  return propertyComplete(extra) && termsComplete(extra) ? 4 : 1;
}

function resolveBuyerNames(extra: AnyObj, passed?: string, dealTitle?: string): string {
  const clean = (s: unknown) => String(s ?? "").trim();
  const flatten = (v: unknown): string => {
    if (Array.isArray(v)) {
      return v
        .map((x) => clean(typeof x === "string" ? x : (x as AnyObj)?.name))
        .filter(Boolean)
        .join(" & ");
    }
    if (v && typeof v === "object") return clean((v as AnyObj).name);
    return clean(v);
  };
  const candidates: unknown[] = [
    passed,
    extra.buyerNames,
    extra.buyerClientNames,
    extra.onboardingBuyers,
    extra.workflow_client_1_name,
    extra.skyslopeBuyerNames,
    extra.skyslopeBuyerNamesRaw,
    extra.profileDisplayName,
  ];
  for (const c of candidates) {
    const v = flatten(c);
    if (v) return v;
  }
  // Last resort: the card's own title, minus the scaffolding we add to it.
  const t = clean(dealTitle).replace(/^buyer:\s*/i, "").replace(/\s+[—-]\s+buyer track$/i, "").trim();
  return t;
}

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
  // CPS is on by default but NOT required — Skyleigh can skip it when she already
  // has a CPS in hand and only wants the rest of the package built.
  { id: "cps-residential", label: "CPS — Contract of Purchase & Sale" },
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
  dealTitle,
  currentStage,
  onUpdate,
}: {
  dealId: string;
  extra: AnyObj;
  address?: string;
  buyerName?: string;
  dealTitle?: string;
  currentStage?: number;
  onUpdate?: () => void;
}) {
  const isMobile = useIsMobile();
  // Every place the kit refers to the client resolves through this one call.
  const buyerNames = resolveBuyerNames(extra, buyerName, dealTitle);
  const buyerLabel = buyerNames || "the buyer(s)";
  // 44pt targets on a phone, per HIG. Inline styles can't be reached by a
  // media query, so the height rides the same hook the grids use.
  const tap = isMobile ? 44 : undefined;
  // Built Documents uses its own, wider breakpoint: the doc rows run out of room
  // well before the 640 the rest of the wizard uses.
  const isNarrow = useIsMobile(900);
  // Fixed multi-column field grids collapse to a single column on a phone
  // (CSS media queries can't reach these inline styles).
  const cols = (n: number) => (isMobile ? "1fr" : Array(n).fill("1fr").join(" "));
  // Open on the step that still has work in it. It used to open on Property
  // every time — even when the screen itself said the pull was already done —
  // and past acceptance the kit is only ever opened to get a document out.
  const [step, setStep] = useState(() => initialStep(extra, currentStage ?? 0));
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
  // Save a brand-new personal clause to the shared library so it's reusable on
  // every future deal (persists to webforms-clauses.json server-side), then drop
  // it into the picker's Personal folder immediately.
  const addPersonalClause = useCallback(async (title: string, wording: string) => {
    const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    const res = await fetch("/api/admin/clause-library/personal", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ title, wording }),
    });
    const data = await res.json().catch(() => null);
    const clause = data && data.clause;
    if (!clause) throw new Error("save failed");
    setWfFolders((prev) => {
      const base = prev || [
        { key: "personal", label: "Personal Clauses", clauses: [] as AnyObj[] },
        { key: "office", label: "Office Clauses", clauses: [] as AnyObj[] },
        { key: "system", label: "System Clauses", clauses: allClauses },
      ];
      return base.map((f) => (f.key === "personal" ? { ...f, clauses: [...f.clauses, clause] } : f));
    });
  }, [allClauses]);

  // ── build (Step 4) ──
  const [kitForms, setKitForms] = useState<Record<string, boolean>>(
    () => (extra.cpsKitForms as Record<string, boolean>) || { ...KIT_FORM_DEFAULTS },
  );
  const toggleKitForm = (id: string) => {
    setKitForms((p) => { const next = { ...p, [id]: !(p[id] ?? KIT_FORM_DEFAULTS[id] ?? true) }; api.setAdminDealToggle(dealId, "cpsKitForms", next as any).catch(() => {}); return next; });
  };
  const [building, setBuilding] = useState(false);
  const [builtMsg, setBuiltMsg] = useState("");
  const buildKit = useCallback(async () => {
    const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    setBuilding(true); setBuiltMsg("");
    try {
      // Make sure the current subject selection is saved before we assemble it.
      // Persist the umbrella here too — the property-type click also saves it, but
      // if that write flaked the deal would build on the wrong (residential) base.
      // Saving it at Build guarantees the umbrella matches what's on screen.
      await api.setAdminDealToggle(dealId, "cpsUmbrella", umbrella).catch(() => {});
      await api.setAdminDealToggle(dealId, "cpsClauses", Array.from(selectedClauses) as any).catch(() => {});
      await api.setAdminDealToggle(dealId, "cpsCustomClauses", customClauses as any).catch(() => {});
      // Always seed the document slots (this creates the DORTS / Privacy / etc.
      // records, not just the CPS). We only skip GENERATING the CPS PDF below when
      // the CPS is turned off — the seed itself must always run.
      const buildRes = await fetch(`/api/admin/deals/${dealId}/offer-kit/build`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }).catch(() => null);
      if (!buildRes || !buildRes.ok) {
        const detail = buildRes ? await buildRes.text().catch(() => "") : "no response";
        setBuiltMsg(`✗ Draft failed — ${String(detail).slice(0, 160) || "could not seed the kit"}`);
        return;
      }
      let enabled = KIT_FORMS.filter((f) => kitForms[f.id] ?? KIT_FORM_DEFAULTS[f.id] ?? true).map((f) => f.id);
      if (umbrella === "mobile") {
        // Mobile swaps the residential CPS + generic addendum for the Manufactured
        // Home (Rental Site) contract (same cps-residential slot — the backend picks
        // the manufactured template) + its dedicated addendum, which carries the
        // subjects. Drop the generic addendum; generate the manufactured addendum.
        enabled = enabled.filter((id) => id !== "cps-addendum");
        if (!enabled.includes("cps-mobile-addendum")) {
          const i = enabled.indexOf("cps-residential");
          if (i >= 0) enabled.splice(i + 1, 0, "cps-mobile-addendum");
          else enabled.push("cps-mobile-addendum");
        }
      }
      // Generate each form and record the ACTUAL result — a 500 or a hollow fill
      // must not read as success. Collect failures + blank-field warnings so the
      // operator sees exactly what still needs attention.
      const failed: string[] = [];
      const warns: string[] = [];
      for (const id of enabled) {
        const r = await fetch(`/api/admin/deals/${dealId}/kit-doc/${id}/generate`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }).catch(() => null);
        if (!r || !r.ok) { failed.push(id); continue; }
        const body = await r.json().catch(() => ({} as any));
        if (Array.isArray(body?.warnings) && body.warnings.length && id === "cps-residential") {
          warns.push(...body.warnings.map((w: string) => `CPS: ${w}`));
        }
      }
      const ok = enabled.length - failed.length;
      if (failed.length) {
        setBuiltMsg(`⚠ Drafted ${ok} of ${enabled.length} — ${failed.length} failed to generate (${failed.join(", ")}). Check the fields and redraft.`);
      } else if (warns.length) {
        setBuiltMsg(`✓ Drafted ${ok} documents — ${warns.length} blank to complete: ${warns.join("; ")}`);
      } else {
        setBuiltMsg(`✓ Drafted ${ok} documents into the kit`);
      }
      onUpdate?.();
    } finally { setBuilding(false); }
  }, [dealId, kitForms, onUpdate, selectedClauses, customClauses, umbrella]);

  // ── built kit documents (Step 4, post-build) ─────────────────────────────
  // Folded in from the old standalone "Transaction Kit" card so build + open +
  // edit + approve all live inside the wizard. Self-contained handlers (same
  // endpoints the card used) so deal-modal no longer renders a second surface.
  type KitDoc = { id: string; name: string; status?: string; ready?: boolean; fields?: Record<string, string>;
    filePath?: string; generatedAt?: string; editedAt?: string };
  const builtDocs: KitDoc[] = ((extra as unknown as { offerKit?: { documents?: KitDoc[] } }).offerKit?.documents) || [];
  const [generatingKit, setGeneratingKit] = useState<string | null>(null);
  // ── Step 4 helpers ────────────────────────────────────────────────────────
  // A doc is stale when its fields were edited after the PDF was built. The
  // backend stamps editedAt on a field save and generatedAt on a build, so this
  // is a fact rather than a guess.
  const docIsStale = (d?: KitDoc) => !!d?.editedAt && (!d.generatedAt || d.editedAt > d.generatedAt);
  // Standard forms follow their toggle; anything added or uploaded is in the kit
  // by virtue of existing.
  const kitIncluded = (id: string) => {
    const std = KIT_FORMS.find((f) => f.id === id);
    if (!std && id !== "cps-mobile-addendum") return true;
    if (std?.required) return true;
    return kitForms[id] ?? KIT_FORM_DEFAULTS[id] ?? true;
  };
  // Which docs go in the envelope. Chosen in the send sheet, defaulting to
  // everything that is built and not stale.
  const [sendOpen, setSendOpen] = useState(false);
  const [signSel, setSignSel] = useState<Set<string>>(new Set());
  const [drafting, setDrafting] = useState(false);
  const [draftSignMsg, setDraftSignMsg] = useState("");
  useEffect(() => {
    if (!sendOpen) return;
    setSignSel(new Set(builtDocs.filter((d) => d.filePath && !docIsStale(d)).map((d) => d.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendOpen]);
  const toggleSign = (id: string) => setSignSel((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  // Which of the ticked documents would go out with a disclosure unanswered.
  // Declared here, above the `if (collapsed)` early-return — a hook below it
  // changes the hook count between renders and React tears the card down.
  const sendGaps = useSendCheck(dealId, "buyer", Array.from(signSel), sendOpen);
  const tok = () => (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";

  const draftForSignatures = useCallback(async () => {
    const ids = Array.from(signSel);
    if (!ids.length) return;
    setDrafting(true); setDraftSignMsg("");
    try {
      // Regenerate anything edited since it was drafted BEFORE it goes in the
      // envelope. Leaving that to a Redraft button the operator had to remember
      // is how stale values reach a client.
      const stale = ids.filter((id) => docIsStale(builtDocs.find((d) => d.id === id)));
      for (const id of stale) {
        await fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(id)}/generate`,
          { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } })
          .catch(() => null);
      }
      const res = await fetch(`/api/admin/deals/${dealId}/offer-kit/draft-signatures`, {
        method: "POST",
        headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" },
        body: JSON.stringify({ docIds: ids }),
      });
      if (res.ok) {
        setDraftSignMsg("✓ Drafted for signatures. Review & approve the card, then it creates a DigiSign draft in SkySlope for you to send.");
        onUpdate?.();
      } else {
        const e = await res.json().catch(() => null);
        setDraftSignMsg(`Couldn't draft for signatures: ${(e && e.detail) || res.status}`);
      }
    } finally { setDrafting(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId, signSel, onUpdate, builtDocs]);
  const openKitDoc = useCallback((docId: string, download = false) => {
    const origin = window.location.origin;
    const externalOrigin = origin.includes("127.0.0.1") ? origin.replace("127.0.0.1", "localhost") : origin.replace("localhost", "127.0.0.1");
    window.open(`${externalOrigin}/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}?token=${encodeURIComponent(tok())}&v=${Date.now()}${download ? "&download=1" : ""}`, "_blank");
  }, [dealId]);
  const saveKitField = useCallback((docId: string, key: string, value: string) => {
    fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}/field`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" }, body: JSON.stringify({ key, value }) }).catch(() => {});
  }, [dealId]);
  const generateKitDoc = useCallback(async (docId: string, label?: string) => {
    setGeneratingKit(docId); setBuiltMsg("");
    const name = label || docId;
    try {
      const r = await fetch(`/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(docId)}/generate`, { method: "POST", headers: { Authorization: `Bearer ${tok()}`, "Content-Type": "application/json" } }).catch(() => null);
      if (!r || !r.ok) {
        const e = r ? await r.json().catch(() => null) : null;
        setBuiltMsg(`✗ ${name} did not draft — ${(e && e.detail) || (r ? `error ${r.status}` : "no response")}`);
        return;
      }
      const body = await r.json().catch(() => ({} as any));
      const warns: string[] = Array.isArray(body?.warnings) ? body.warnings : [];
      setBuiltMsg(warns.length
        ? `✓ ${name} drafted — still blank: ${warns.join("; ")}`
        : `✓ ${name} drafted.`);
      onUpdate?.();
    } finally { setGeneratingKit(null); }
  }, [dealId, onUpdate]);

  // ── Add a form (#6): upload a PDF, or pick from the wired-template catalog ──
  const [addFormOpen, setAddFormOpen] = useState(false);
  const [addingForm, setAddingForm] = useState(false);
  // Forms that have a fillable template wired backend-side but aren't in the
  // default 6. Grows as more templates are wired; upload covers everything else.
  const builtIds = new Set(builtDocs.map((d) => d.id));
  // Conditional disclosures — only some deals need them, so they live here
  // rather than in every kit. All are wired to a fillable template except
  // subject-removal, whose PDF on disk is flat (it will say so if you add it).
  // No Subject Removal: Skyleigh uses the Notice of Condition Waiver /
  // conditional removal instead (2026-07-27).
  const FORM_CATALOG: { id: string; label: string }[] = [
    { id: "expected-remuneration", label: "Disclosure to Sellers of Expected Remuneration" },
    { id: "multiple-offers", label: "Disclosure of Multiple Offers Presented" },
    { id: "material-latent-defects", label: "REALTORS' Disclosure of Material Latent Defects" },
    { id: "interest-in-trade", label: "BCFSA — Disclosure of Interest in Trade" },
    { id: "referral-payment", label: "Disclosure of Referral Payment" },
    { id: "exp-referral-payment", label: "eXp (BC) — Disclosure of Referral Payment to be Received" },
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
        <div style={{ fontWeight: 700, fontSize: 19 }}>{buyerNames || "Buyer"} — Transaction Kit</div>
        <div style={{ fontSize: 13, color: "#aeb8cc", marginTop: 3 }}>
          {address || "Property"}{mls ? ` · MLS ${mls}` : ""}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <span style={{ background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 12, letterSpacing: 0.5, padding: "5px 12px", borderRadius: 999, whiteSpace: "nowrap" }}>OFFER PREP</span>
        <button type="button" onClick={() => setCollapsed(true)} title="Minimize" aria-label="Minimize the Transaction Kit" style={{ background: "transparent", border: "1px solid #ffffff44", color: "#fff", borderRadius: 7, padding: "4px 11px", fontSize: 13, fontWeight: 700, cursor: "pointer", minHeight: tap, minWidth: tap }}>▴</button>
      </div>
    </div>
  );

  // ── state used by Step 4 ──────────────────────────────────────────────────
  // Declared ABOVE the collapsed early-return. Anything below it only runs on
  // the expanded render, so a hook down there changes the hook count between
  // renders and React tears the component down (error #310) the moment the
  // card is opened.
  const [showExcluded, setShowExcluded] = useState(false);
  if (collapsed) {
    return (
      <section style={{ border: `1px solid ${BORDER}`, borderRadius: 12, marginBottom: 16, overflow: "hidden" }}>
        <button type="button" onClick={() => setCollapsed(false)} style={{ width: "100%", background: NAVY, color: "#fff", border: "none", padding: "13px 22px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", textAlign: "left" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{buyerNames || "Buyer"} — Transaction Kit</div>
            <div style={{ fontSize: 12, color: "#aeb8cc", marginTop: 2 }}>{accepted ? "Offer accepted · kit on file" : (address || "property")}</div>
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#cdd5e4", whiteSpace: "nowrap" }}>▾</span>
        </button>
      </section>
    );
  }

  // ── step indicator ──────────────────────────────────────────────────────
  // A breadcrumb, not four equal circles. Finished steps recede; the current
  // one is the only thing emphasised. The old rail took a full band across the
  // card and the deal card's sticky header sliced it in half on scroll.
  // Every step is directly reachable — each answer persists as you go, so
  // there is nothing to gate.
  const stepComplete = (n: number) =>
    n === 1 ? propertyComplete(extra)
    : n === 2 ? termsComplete(extra)
    : n === 3 ? selectedClauses.size > 0
    : false;
  const Stepper = (
    <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", margin: "0 0 16px" }}>
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = stepComplete(n) && n !== step;
        const active = n === step;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button
              type="button"
              onClick={() => setStep(n)}
              aria-current={active ? "step" : undefined}
              title={`Go to step ${n}: ${label}`}
              style={{
                display: "flex", alignItems: "center", gap: 6, border: "none", cursor: "pointer",
                font: "inherit", padding: "6px 10px", borderRadius: 7, minHeight: tap ? 40 : undefined,
                background: active ? "#fff" : "transparent",
                boxShadow: active ? "0 1px 2px rgba(24,40,72,.09)" : "none",
                color: active ? INK : MUTED, fontWeight: active ? 800 : 600, fontSize: 13,
                whiteSpace: "nowrap",
              }}
            >
              {done && <span style={{ color: GREEN, fontWeight: 800 }}>✓</span>}
              {label}
            </button>
            {i < STEPS.length - 1 && <span style={{ color: "#c9ced6", fontSize: 11 }}>›</span>}
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
          <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 10 }}>
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
      <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14, marginBottom: 14 }}>
        {cell("PURCHASE PRICE", "cpsPurchasePrice", "$630,000")}
        {cell("DEPOSIT", "cpsDeposit", "$10,000")}
        {cell("DEPOSIT DUE", "cpsDepositTerms", "on subject removal")}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: cols(4), gap: 14, marginBottom: 14 }}>
        {cell("SUBJECT REMOVAL", "subjectRemovalDate", "Jul 14")}
        {cell("COMPLETION", "completionDate", "Aug 12")}
        {cell("POSSESSION", "possessionDate", "Aug 14")}
        {cell("ADJUSTMENT", "adjustmentDate", "Aug 12")}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14, marginBottom: 14 }}>
        {cell("INCLUDED ITEMS", "cpsInclusions", "all appliances, window coverings…")}
        {cell("EXCLUDED ITEMS", "cpsExclusions", "staging furniture…")}
        {cell("DESIGNATED AGENCY", "designatedAgency", "Skyleigh McCallum")}
      </div>
      {umbrella === "mobile" && (
        <div style={{ marginTop: 4, borderTop: `1px solid ${BORDER}`, paddingTop: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: INK, marginBottom: 4 }}>Manufactured home specs</div>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 12 }}>
            Auto-filled from the MLS + Mobile Home Registry when you pull the listing. The CSA / Silver Label number often isn&rsquo;t on the MLS &mdash; add it here from the registry (the mobile&rsquo;s title) if needed. Fills the CPS + addendum.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14, marginBottom: 14 }}>
            {cell("REGISTRATION #", "mhRegistration", "008438")}
            {cell("SERIAL #", "mhSerial", "5300")}
            {cell("CSA / SILVER LABEL", "mhCsaLabel", "009173")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: cols(3), gap: 14, marginBottom: 14 }}>
            {cell("YEAR", "mhYear", "1974")}
            {cell("MAKE", "mhMake", "Bendix")}
            {cell("MODEL", "mhModel", "Leader")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: cols(2), gap: 14 }}>
            {cell("PARK NAME", "mhParkName", "Oakdale MHP")}
            {cell("PAD RENT", "mhPadRent", "$765")}
          </div>
        </div>
      )}
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
  // ── Step 4: one list of documents ────────────────────────────────────────
  // Rebuilt 2026-07-27. Previously this screen showed the same document three
  // times (a toggle to include it, a row to approve it, a checkbox to send it),
  // which is what made it unnavigable. Now a document is ONE row that carries
  // its whole state, and the choice of what goes in the envelope is made in the
  // send sheet, at the moment it matters, instead of as a permanent third list.
  // "Approve" is gone: it gated nothing (nothing forced a review, and an
  // approved doc still had to be ticked and confirmed). Reviewing is invited by
  // the row's own primary button, and the send sheet is the deliberate step.
  type RowState = "excluded" | "unbuilt" | "building" | "stale" | "ready";
  const rowStateOf = (id: string): RowState => {
    const d = builtDocs.find((x) => x.id === id);
    if (generatingKit === id || (building && !d?.filePath)) return "building";
    if (!kitIncluded(id)) return "excluded";
    if (!d || !d.filePath) return "unbuilt";
    if (docIsStale(d)) return "stale";
    return "ready";
  };
  // Every document the kit knows about: the standard forms plus anything added
  // or uploaded. One entry per document, no duplicates.
  const allRows: { id: string; name: string; required?: boolean }[] = [
    ...KIT_FORMS.filter((f) => !(umbrella === "mobile" && f.id === "cps-addendum"))
      .map((f) => ({ id: f.id, name: f.label, required: f.required })),
    ...(umbrella === "mobile" ? [{ id: "cps-mobile-addendum", name: "CPS — Manufactured Home Addendum" }] : []),
    ...builtDocs
      .filter((d) => !KIT_FORMS.some((f) => f.id === d.id) && d.id !== "cps-mobile-addendum")
      .map((d) => ({ id: d.id, name: d.name })),
  ];
  const includedRows = allRows.filter((r) => kitIncluded(r.id));
  const excludedRows = allRows.filter((r) => !kitIncluded(r.id));
  const needsBuild = includedRows.filter((r) => ["unbuilt", "stale"].includes(rowStateOf(r.id)));
  const sendable = includedRows.filter((r) => rowStateOf(r.id) === "ready");
  const linkBtn: React.CSSProperties = {
    background: "none", border: "none", padding: 0, color: BLUE, fontWeight: 700,
    fontSize: 12.5, cursor: "pointer", font: "inherit", display: "inline-flex", alignItems: "center",
  };
  const BORDER_STRONG = "var(--ds-border-strong)";

  const Step4 = (
    <div style={panel}>
      <div style={{ fontWeight: 700, fontSize: 16, color: INK }}>
        Documents{buyerNames ? ` for ${buyerNames}` : ""}
      </div>
      <div style={{ fontSize: 13, color: MUTED, margin: "5px 0 10px" }}>
        {building || generatingKit
          ? "Drafting…"
          : needsBuild.length === 0 && sendable.length > 0
            ? `All ${sendable.length} drafted and ready to send.`
            : `${sendable.length} drafted. ${needsBuild.length} still to draft.`}
      </div>

      <KitDocumentList
        rows={includedRows.map((r) => ({
          id: r.id,
          name: r.name,
          required: r.required,
          state: rowStateOf(r.id) as KitDocState,
          generatedAt: builtDocs.find((x) => x.id === r.id)?.generatedAt,
          fields: builtDocs.find((x) => x.id === r.id)?.fields,
        }))}
        fieldDefs={KIT_DOC_FIELDS.map((f) => ({ key: f.key, label: f.label, multiline: f.multiline }))}
        previewUrl={(id, page, dpi) =>
          `/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(id)}/preview?page=${page}&dpi=${dpi}&v=${Date.now()}`}
        fieldsUrl={(id) => `/api/admin/deals/${dealId}/kit-doc/${encodeURIComponent(id)}/fields?v=${Date.now()}`}
        onDraft={(id, name) => void generateKitDoc(id, name)}
        onOpen={(id, download) => openKitDoc(id, download)}
        onSaveField={saveKitField}
        onExclude={(id) => { if (KIT_FORMS.some((f) => f.id === id)) toggleKitForm(id); }}
        isMobile={isMobile}
        isNarrow={isNarrow}
      />

      {/* Not in this kit: one line, not a row each. */}
      {excludedRows.length > 0 && (
        <div style={{ borderTop: "1px solid #eef0f3", padding: "12px 4px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 13, color: MUTED }}>
              {excludedRows.length} form{excludedRows.length === 1 ? "" : "s"} not in this kit
            </span>
            <button type="button" onClick={() => setShowExcluded((s) => !s)} style={{ ...linkBtn, minHeight: tap }}>
              {showExcluded ? "Hide" : "Show"}
            </button>
          </div>
          {showExcluded && excludedRows.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
              <span style={{ fontSize: 13.5, color: "#9aa0a6" }}>{r.name}</span>
              <button type="button" onClick={() => toggleKitForm(r.id)} style={{ ...kitBtn, minHeight: tap }}>Add to the kit</button>
            </div>
          ))}
        </div>
      )}

      {/* Add a form — the last row of the same list, not a separate panel. */}
      <div style={{ borderTop: "1px solid #eef0f3" }}>
        {!addFormOpen ? (
          <button type="button" onClick={() => setAddFormOpen(true)} style={{ width: "100%", padding: "13px 0", display: "flex", alignItems: "center", gap: 13, color: MUTED, background: "none", border: "none", cursor: "pointer", textAlign: "left", minHeight: tap }}>
            <span style={{ width: 21, height: 21, borderRadius: 6, background: NAVY, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700, flexShrink: 0 }}>+</span>
            <span>
              <span style={{ display: "block", fontSize: 14, fontWeight: 600, color: INK }}>Add a form</span>
              <span style={{ display: "block", fontSize: 12.5, marginTop: 2 }}>Upload a PDF, or pick from the catalog</span>
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
            {FORM_CATALOG.length > 0 && (
              <>
                <div style={{ fontSize: 11, color: MUTED, fontWeight: 700, letterSpacing: 0.4, margin: "4px 0 6px" }}>OR PICK FROM THE CATALOG</div>
                {FORM_CATALOG.map((f) => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid #eef0f3" }}>
                    <span style={{ fontSize: 14, color: INK, fontWeight: 600 }}>{f.label}</span>
                    <button type="button" disabled={addingForm} onClick={() => void addCatalogForm(f.id, f.label)} style={{ ...kitBtn, minHeight: tap }}>Add</button>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Two actions, permanently distinct. Drafting is local and reversible;
          sending reaches a client. They never swap places in one control. */}
      {!sendOpen && (
        <div style={{ display: "flex", gap: 11, flexWrap: "wrap", alignItems: "center", marginTop: 18, paddingTop: 16, borderTop: `1px solid ${BORDER}` }}>
          {needsBuild.length > 0 && (
            <button
              type="button"
              disabled={building}
              onClick={() => void buildKit()}
              style={{ padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 14.5, border: `1px solid ${BORDER_STRONG}`, background: "#fff", color: INK, cursor: building ? "default" : "pointer", opacity: building ? 0.65 : 1, minHeight: tap }}
            >
              {building ? "Drafting…" : `Draft the ${needsBuild.length} remaining`}
            </button>
          )}
          <button
            type="button"
            disabled={building || sendable.length === 0}
            onClick={() => setSendOpen(true)}
            style={{ padding: "11px 20px", borderRadius: 9, fontWeight: 700, fontSize: 14.5, border: "none", color: "#fff", cursor: sendable.length === 0 ? "default" : "pointer", minHeight: tap,
              background: sendable.length === 0 || building ? "#9aa6bd" : ORANGE }}
          >
            {sendable.length ? `Send ${sendable.length} for signature` : "Send for signature"}
          </button>
          <div style={{ flexBasis: "100%", fontSize: 12.5, color: MUTED }}>
            Sending redrafts anything you edited first, then creates one DigiSign envelope. Nothing leaves without the next screen.
          </div>
        </div>
      )}

      {/* The send sheet is the one deliberate confirming action, and it names
          the person the envelope is addressed to. */}
      {sendOpen && (
        <div style={{ marginTop: 16, border: `1px solid ${BORDER}`, borderRadius: 11, background: "#fbfcfe", padding: "16px 18px" }}>
          <div style={{ fontSize: 14.5, fontWeight: 700, color: INK }}>Send to {buyerLabel}?</div>
          <div style={{ fontSize: 13, color: MUTED, margin: "4px 0 11px" }}>
            One DigiSign envelope for {address || "this property"}. Untick anything you are not sending yet — it stays in the kit.
          </div>
          {sendable.map((r) => {
            const on = signSel.has(r.id);
            return (
              <button
                key={r.id}
                type="button"
                role="checkbox"
                aria-checked={on}
                onClick={() => toggleSign(r.id)}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0", cursor: "pointer", width: "100%", background: "none", border: "none", borderTop: "1px solid #eef0f3", textAlign: "left", font: "inherit", minHeight: tap }}
              >
                <span aria-hidden="true" style={{ width: 21, height: 21, borderRadius: 6, flexShrink: 0, background: on ? NAVY : "#fff", border: `1.6px solid ${on ? NAVY : "#c9ced6"}`, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13 }}>{on ? "✓" : ""}</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: on ? INK : "#9aa0a6" }}>{r.name}</span>
              </button>
            );
          })}
          <SendGapWarning gaps={sendGaps.filter((g) => signSel.has(g.id))}
            nameOf={(id) => sendable.find((r) => r.id === id)?.name} />
          <div style={{ display: "flex", gap: 9, marginTop: 14, alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" onClick={() => setSendOpen(false)} style={{ ...kitBtn, minHeight: tap }}>Cancel</button>
            <button type="button" disabled={drafting || signSel.size === 0}
              onClick={() => { setSendOpen(false); void draftForSignatures(); }}
              style={{ ...kitBtn, minHeight: tap, background: signSel.size === 0 ? "#9aa6bd" : ORANGE, borderColor: "transparent", color: "#fff", padding: "9px 16px", fontSize: 13.5 }}>
              {drafting ? "Drafting…" : `Send ${signSel.size} to ${buyerLabel}`}
            </button>
            <span style={{ fontSize: 12.5, color: MUTED }}>Nothing sends — it lands as a draft in DigiSign.</span>
          </div>
        </div>
      )}

      {builtMsg && <div style={{ marginTop: 12, color: builtMsg.startsWith("✓") ? GREEN : ORANGE, fontWeight: 700, fontSize: 14 }}>{builtMsg}</div>}
      {draftSignMsg && <div style={{ marginTop: 10, color: draftSignMsg.startsWith("✓") ? GREEN : ORANGE, fontWeight: 700, fontSize: 13.5 }}>{draftSignMsg}</div>}
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
        <div>{Stepper}</div>
        {step === 1 ? Step1 : step === 2 ? Step2 : step === 3 ? Step3 : step === 4 ? Step4 : Placeholder}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18, gap: 12 }}>
          {step > 1 ? (
            <button type="button" onClick={() => setStep((s) => s - 1)} style={{ ...navBtn, background: "#fff", color: INK, border: `1px solid ${BORDER}` }}>← Back</button>
          ) : <span />}
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {step < 4 && (
              <button type="button" onClick={() => setStep((s) => Math.min(4, s + 1))} style={{ ...navBtn, background: NAVY, color: "#fff" }}>
                {step === 1 ? "Continue to Terms →" : step === 2 ? "Continue to Subjects →" : "Continue to Documents →"}
              </button>
            )}
          </div>
        </div>
      </div>

      <ClausePickerModal
        open={clausePickerOpen}
        onClose={() => setClausePickerOpen(false)}
        onInsert={insertClauses}
        onAddPersonalClause={addPersonalClause}
        folders={clauseFolders as unknown as { key: string; label: string; clauses: { id: string }[] }[]}
        preselected={selectedClauses}
      />
    </section>
  );
}
