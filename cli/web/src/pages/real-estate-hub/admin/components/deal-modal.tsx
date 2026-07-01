
import React, { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  Home,
  Clock,
  Database,
  Chevron,
} from "../icons";
import {
  ADMIN_PIPELINE,
  ADMIN_BUYER_PIPELINE,
  ADMIN_PHASE_DETAILS,
  ADMIN_BUYER_PHASE_DETAILS,
} from "../admin-data";
import { api } from "@/lib/api";
import type { DealContext, AdminDeal } from "@/lib/api-types";
import OfferKitWizard from "./offer-kit-wizard";
import ListingKitWizard from "./listing-kit-wizard";
import DocumentsPanel from "./documents-panel";
import OnboardingPanel from "./onboarding-panel";
import CmaWizard from "./cma-wizard";
import OzzieChatPanel from "./ozzie-chat-panel";
import DepositCard, { deriveDeposit } from "./deposit-card";
import "./stage-rail.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Deal {
  id: string;
  phase: string;
  addr: string;
  line2: string;
  badge: string;
  progress?: string;
  next: string;
  price?: string;
  mls?: string;
  blocked?: boolean;
  primary?: boolean;
  owner?: string;
  ownerInitial?: string;
  daysInStage?: string;
  side?: string;
}

interface DealDetailModalProps {
  deal: Deal;
  onClose: () => void;
}

type InfoFieldKind = "text" | "url" | "select";

interface InfoFieldDef {
  key: string;
  label: string;
  kind?: InfoFieldKind;
  options?: string[];
}

interface InfoSectionDef {
  id: string;
  title: string;
  subtitle: string;
  fields: InfoFieldDef[];
  minListingPhase?: string;
  // When set, the section only renders if the deal's propertySubtype is one of
  // these values. Used for the Strata + Manufactured/Mobile-Home field groups.
  subtypes?: string[];
  // Read-only sections render a custom body instead of the editable field grid.
  // Used for the SkySlope missing-documents punch list, populated by the
  // Mon/Wed skyslope-audit (extra.skyslopeMissing + extra.skyslopeCheckedAt).
  readonly?: boolean;
}

// One missing SkySlope checklist item written by the audit:
//   { doc: "FINTRAC Individual", status: "Required Attach" }
interface SkyslopeMissingItem {
  doc: string;
  status?: string;
}

const CORE_PROPERTY_FIELDS: InfoFieldDef[] = [
  { key: "core.propertyAddress", label: "Property address" },
  { key: "core.unitNumber", label: "Unit number" },
  { key: "core.city", label: "City" },
  { key: "core.province", label: "Province" },
  { key: "core.postalCode", label: "Postal code" },
  { key: "core.mlsNumber", label: "MLS number" },
  { key: "core.pid", label: "PID" },
  { key: "core.legalDescription", label: "Legal description" },
  { key: "core.rollFolioNumber", label: "Roll / folio number" },
  { key: "core.propertyType", label: "Property type", kind: "select", options: ["detached", "townhouse", "condo", "manufactured home", "land"] },
  { key: "core.bedrooms", label: "Bedrooms" },
  { key: "core.bathrooms", label: "Bathrooms" },
  { key: "core.livingSqft", label: "Living area (sq ft)" },
  { key: "core.neighbourhood", label: "Neighbourhood" },
  { key: "core.tenureTitleType", label: "Tenure/title type", kind: "select", options: ["freehold", "strata", "leasehold", "manufactured home on pad/site"] },
  { key: "core.listingDriveFolderLink", label: "Listing Drive folder link", kind: "url" },
  { key: "core.skySlopeFileLink", label: "SkySlope file link", kind: "url" },
  { key: "core.matrixXposureDraftLink", label: "Matrix / Xposure draft link", kind: "url" },
  { key: "core.liveListingUrl", label: "Live listing URL", kind: "url" },
  { key: "core.landingPageUrl", label: "Landing page URL", kind: "url" },
];

const SELLER_INFORMATION_FIELDS: InfoFieldDef[] = [
  { key: "seller.legalNames", label: "Seller legal name(s)" },
  { key: "seller.preferredNames", label: "Seller preferred name(s)" },
  { key: "seller.emails", label: "Seller email(s)" },
  { key: "seller.phones", label: "Seller phone(s)" },
  { key: "seller.mailingAddress", label: "Seller mailing address" },
  { key: "seller.residencyStatus", label: "Seller residency status" },
  { key: "seller.signingLocationProvince", label: "Signing location/province" },
  { key: "seller.signingAuthority", label: "Signing authority", kind: "select", options: ["individual", "POA", "estate", "corporation", "trust"] },
  { key: "seller.preferredSigningEmail", label: "Preferred signing email" },
  { key: "seller.lawyerChosen", label: "Lawyer/notary chosen ?", kind: "select", options: ["yes", "no", "unknown"] },
  { key: "seller.lawyerName", label: "Seller lawyer/notary name" },
  { key: "seller.lawyerFirm", label: "Firm" },
  { key: "seller.lawyerEmail", label: "Email" },
  { key: "seller.lawyerPhone", label: "Phone" },
  { key: "seller.lawyerCityProvince", label: "City/province" },
];



const LISTING_CONTRACT_FIELDS: InfoFieldDef[] = [
  { key: "mlc.listingPrice", label: "Listing price" },
  { key: "mlc.commissionTerms", label: "Commission terms" },
  { key: "mlc.cooperatingBrokerageCommission", label: "Cooperating brokerage commission" },
  { key: "mlc.contractEffectiveDate", label: "Contract effective date" },
  { key: "mlc.expiryDate", label: "Expiry date" },
  { key: "mlc.plannedMlsLiveDate", label: "Planned MLS/live date" },
  { key: "mlc.comingSoonDate", label: "Coming-soon date, if any" },
  { key: "mlc.listingStatus", label: "Listing status", kind: "select", options: ["prep", "signed", "Matrix incomplete", "Marketing Go", "live", "accepted offer", "firm", "closed"] },
  { key: "mlc.includedItems", label: "Included items" },
  { key: "mlc.excludedItems", label: "Excluded items" },
  { key: "mlc.tenancyDetails", label: "Tenancy details" },
  { key: "mlc.sellerInstructions", label: "Seller instructions" },
  { key: "mlc.occupancy", label: "Occupancy", kind: "select", options: ["owner occupied", "tenant occupied", "vacant"] },
  { key: "mlc.showingInstructions", label: "Showing instructions" },
  { key: "mlc.lockboxCodeStatus", label: "Lockbox code/status" },
  { key: "mlc.signRiderStatus", label: "Sign/rider status" },
];

// Strata fields — only relevant when the property is a strata lot. Strata fee
// is taken from the seller at listing, then VERIFIED against the strata
// documents (Form B / financials) after an accepted offer.
const STRATA_FIELDS: InfoFieldDef[] = [
  { key: "core.strataFee", label: "Strata Fee (monthly)" },
  { key: "core.strataPlan", label: "Strata Plan #" },
];

// Manufactured / Mobile-Home registry fields — only relevant when the property
// is a mobile/manufactured home. Pad rent is taken from the seller at listing,
// then VERIFIED against the Site Tenancy Agreement after an accepted offer; the
// registry data comes from the Manufactured Home Registry (MHR) / the CPS for a
// manufactured home on a rental site.
const MOBILE_HOME_FIELDS: InfoFieldDef[] = [
  { key: "core.unitMake", label: "Make" },
  { key: "core.unitModel", label: "Model" },
  { key: "core.unitYear", label: "Year" },
  { key: "core.serialNo", label: "Serial No." },
  { key: "core.csaNo", label: "CSA / TSBC Silver Label No." },
  { key: "core.mhrNo", label: "MHR Registration No." },
  { key: "core.padRent", label: "Pad / Site Rent (monthly)" },
  { key: "core.parkName", label: "Manufactured Home Park" },
];

const PROPERTY_SPECS_FIELDS: InfoFieldDef[] = [
  { key: "specs.bedrooms", label: "Bedrooms" },
  { key: "specs.bathrooms", label: "Bathrooms" },
  { key: "specs.squareFootage", label: "Square footage" },
  { key: "specs.yearBuilt", label: "Year built" },
  { key: "specs.lotSize", label: "Lot size" },
  { key: "specs.strataFeeMonthly", label: "Strata fee (monthly)" },
  { key: "specs.parking", label: "Parking" },
  { key: "specs.includedAppliances", label: "Included appliances" },
  { key: "specs.bonusFeatures", label: "Bonus / selling features" },
];

const COUNTERPARTY_FIELDS: InfoFieldDef[] = [
  { key: "offer.buyerNames", label: "Buyer name(s)" },
  { key: "offer.cooperatingAgent", label: "Cooperating agent" },
  { key: "offer.cooperatingBrokerage", label: "Cooperating brokerage" },
  { key: "offer.cooperatingAgentPhone", label: "Cooperating agent phone" },
  { key: "offer.cooperatingAgentEmail", label: "Cooperating agent email" },
];

// Buyer-side client + home-search criteria. Shown instead of the listing
// property sections when the card is a buyer lead (Top 25 hot buyers).
const BUYER_CLIENT_FIELDS: InfoFieldDef[] = [
  { key: "buyer.clientNames", label: "Client name(s)" },
  { key: "buyer.emails", label: "Client email(s)" },
  { key: "buyer.phones", label: "Client phone(s)" },
  { key: "buyer.mailingAddress", label: "Client mailing address" },
  { key: "buyer.timeline", label: "Buying timeline" },
  { key: "buyer.financingStatus", label: "Financing status", kind: "select", options: ["pre-approved", "pre-qualified", "cash", "not started", "unknown"] },
  { key: "buyer.lenderBroker", label: "Lender / mortgage broker" },
];

const BUYER_SEARCH_FIELDS: InfoFieldDef[] = [
  { key: "buyer.budget", label: "Budget / price range" },
  { key: "buyer.lookingFor", label: "Looking for (summary)" },
  { key: "buyer.preferredAreas", label: "Preferred areas / neighbourhoods" },
  { key: "buyer.propertyType", label: "Property type", kind: "select", options: ["detached", "townhouse", "condo", "manufactured home", "land", "any"] },
  { key: "buyer.bedrooms", label: "Bedrooms wanted" },
  { key: "buyer.bathrooms", label: "Bathrooms wanted" },
  { key: "buyer.mustHaves", label: "Must-haves" },
  { key: "buyer.dealBreakers", label: "Deal-breakers" },
  { key: "buyer.notes", label: "Search notes" },
];

// Seller-side prospect view. Shown while a listing lead is still at the
// Pre-CMA stage — just who they are + what they want to sell. The full
// listing sections (Core Property, Specs, Seller, MLC) unlock once the
// deal moves forward into the CMA stage and beyond.
const SELLER_PROSPECT_FIELDS: InfoFieldDef[] = [
  { key: "prospect.clientNames", label: "Seller name(s)" },
  { key: "prospect.emails", label: "Seller email(s)" },
  { key: "prospect.phones", label: "Seller phone(s)" },
  { key: "prospect.propertyAddress", label: "Property address" },
  { key: "prospect.timeline", label: "Selling timeline" },
  { key: "prospect.priceExpectation", label: "Price expectation" },
  { key: "prospect.situation", label: "Situation / reason for selling" },
  { key: "prospect.notes", label: "Notes" },
];

const SELLER_PROSPECT_SECTIONS: InfoSectionDef[] = [
  {
    id: "prospect",
    title: "Seller Prospect",
    subtitle: "Lead-level details only. The full Core Property, Specs, Seller, and MLC sections unlock once this card moves forward into the CMA stage.",
    fields: SELLER_PROSPECT_FIELDS,
  },
];


// Client + Search live inside the Client Onboarding section; Subject Property
// (MLS / PID / legal) lives in the Transaction Kit wizard's property step, which
// pulls them from the title — so there is no standalone buyer info section.
const BUYER_INFO_SECTIONS: InfoSectionDef[] = [];

const INFO_SECTIONS: InfoSectionDef[] = [
  {
    id: "core",
    title: "Core Property Section",
    subtitle: "Reusable details for MLC, CPS, SkySlope, WEBForms, Matrix, marketing, landing pages, signing, TRS, subject removal, and conveyancing.",
    fields: CORE_PROPERTY_FIELDS,
  },
  {
    id: "strata",
    title: "Strata Details",
    subtitle: "Strata fee + plan number. Fee taken from the seller at listing, verified against the strata documents after an accepted offer.",
    fields: STRATA_FIELDS,
    subtypes: ["strata"],
  },
  {
    id: "mobileHome",
    title: "Manufactured / Mobile Home",
    subtitle: "Registry + park details. Pad rent taken from the seller at listing, verified against the Site Tenancy Agreement after an accepted offer; registry data from the MHR / Manufactured-Home CPS.",
    fields: MOBILE_HOME_FIELDS,
    subtypes: ["mobile", "manufactured"],
  },
  {
    id: "specs",
    title: "Property Specs",
    subtitle: "Beds, baths, size, features — quick reference for marketing + paperwork. Auto-pulled from listing data; the landing page is built from these.",
    fields: PROPERTY_SPECS_FIELDS,
  },
  {
    id: "counterparty",
    title: "Accepted-Offer Counterparty",
    subtitle: "Buyer + cooperating agent/brokerage. Fills the SkySlope transaction. Unlocks at accepted offer.",
    fields: COUNTERPARTY_FIELDS,
    minListingPhase: "offer",
  },
  {
    id: "seller",
    title: "Seller Information Section",
    subtitle: "Listing-side seller identity, signing, and lawyer/notary details.",
    fields: SELLER_INFORMATION_FIELDS,
  },
  {
    id: "mlc",
    title: "Listing Contract / MLC Section",
    subtitle: "Listing-side contract terms that unlock once the card reaches Listing Intake.",
    fields: LISTING_CONTRACT_FIELDS,
    minListingPhase: "intake",
  },
  {
    id: "skyslope",
    title: "SkySlope — Missing Documents",
    subtitle: "Required/incomplete checklist items from the SkySlope compliance file. Audited Mon/Wed, or refreshed by a skyslope-sync run.",
    fields: [],
    readonly: true,
  },
];

// Read SkySlope missing items off extraToggles, tolerating bad shapes.
function readSkyslopeMissing(extra: Record<string, unknown>): SkyslopeMissingItem[] | null {
  const raw = extra.skyslopeMissing;
  if (!Array.isArray(raw)) return null;
  return raw
    .map((entry): SkyslopeMissingItem | null => {
      if (entry && typeof entry === "object") {
        const doc = stringValue((entry as Record<string, unknown>).doc);
        const status = stringValue((entry as Record<string, unknown>).status);
        if (doc) return status ? { doc, status } : { doc };
      }
      if (typeof entry === "string" && entry.trim()) return { doc: entry.trim() };
      return null;
    })
    .filter((x): x is SkyslopeMissingItem => x !== null);
}

// ---------------------------------------------------------------------------
// Checklist: DB-backed manual checks + data-driven auto-completion
// ---------------------------------------------------------------------------
//
// Manual checks are stored server-side in extra.checklistManual (a JSON array of
// itemKeys) via the same setAdminDealToggle path the info fields use, so they
// survive a browser change and are writable by server-side skills. Auto-checks
// are derived from the deal's real data: filling a field (contact, MLS#, CMA,
// MLC, offer, subjects, SkySlope, closing) makes the matching checklist item
// render CHECKED with no click required.

// Read the DB-backed manual checked-item keys off extraToggles, tolerating both
// a real array and a JSON-string round-trip (setAdminDealToggle only accepts
// string | boolean | null, so the value is written as a JSON string).
function readChecklistManual(extra: Record<string, unknown>): string[] {
  const raw = extra.checklistManual;
  let arr: unknown = raw;
  if (typeof raw === "string") {
    try {
      arr = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(arr)) return [];
  return arr.filter((x): x is string => typeof x === "string" && x.length > 0);
}

type AutoPredicate = (deal: AdminDeal, extra: Record<string, unknown>) => boolean;

const nonEmptyString = (v: unknown): boolean =>
  typeof v === "string" && v.trim().length > 0;

// Per-checklist-item completion predicates, keyed by the exact item string used
// in ADMIN_PHASE_DETAILS / ADMIN_BUYER_PHASE_DETAILS. An item not in this map is
// judgment-only and stays manual. Item strings are unique enough across both
// pipelines that a single string key is safe.
const CHECKLIST_AUTO_CONDITIONS: Record<string, AutoPredicate> = {
  // ── Listing: pre-cma ──
  "Lofty contact verified / created": (d) =>
    !!d.loftyContactId || !!d.primaryContactId,
  // "Client/property notes saved for CMA" → no signal → manual

  // ── Listing: cma ──
  "CMA PDF / evaluation ready": (_d, e) =>
    nonEmptyString(e.cmaPdfUrl) || nonEmptyString(e.cmaPdf) || nonEmptyString(e.cmaEvaluationUrl),
  // "Pricing story approved" → judgment → manual
  // "Client said yes to listing" → judgment → manual

  // ── Listing: intake ──
  "MLC intake triggered": (d, e) =>
    !!e.mlcSigned || nonEmptyString(e.listingDriveFolderLink) || (d.currentStage ?? 0) >= 2,
  "Missing listing fields surfaced": (d) => (d.currentStage ?? 0) >= 2,
  "Listing docs/signature placements ready for approval": (d, e) =>
    !!e.mlcSigned || (d.currentStage ?? 0) >= 3,

  // ── Listing: skyslope ──
  "Signed listing docs saved to Drive": (_d, e) =>
    !!e.mlcSigned || nonEmptyString(e.listingDriveFolderLink),
  "SkySlope file created / synced": (_d, e) =>
    Array.isArray(e.skyslopeMissing) || nonEmptyString(e.skyslopeCheckedAt),
  "Matrix listing started": (d) => !!d.mlsNumber,
  "Matrix missing fields surfaced": (d) => (d.currentStage ?? 0) >= 4,

  // ── Listing: go / live (MLS-backed) ──
  // "Just listed blast sent", social posts, Flodesk, Lofty text blast → marketing
  //   signals; no clean data flag → manual.

  // ── Listing: offer ──
  "Contract reviewed within 24 hours": (d) => !!d.offerPrice || !!d.offerAcceptedAt,
  "Accepted-offer admin verified": (d) => !!d.offerPrice || !!d.offerAcceptedAt,
  "Calendar dates added": (d) =>
    !!d.subjectRemovalDate || !!d.completionDate || !!d.possessionDate,

  // ── Listing: conditions / closing ──
  "Title charges verified": (_d, e) =>
    nonEmptyString(e.legalDescription) || nonEmptyString(e.pid),
  "Conditions removed / waived": (d, e) =>
    !!d.subjectRemovalDate || !!e.subjectsRemovedAt || !!d.subjectsRemovedAt,
  "Funds released": (d) => !!d.completionDate || !!d.completedAt,

  // ── Listing: closed ──
  "SkySlope deal closed": (d) => d.status === "closed" || !!d.completedAt,
  "Closed file archived": (d) => d.status === "closed" || d.status === "archived",

  // ── Buyer: search ──
  // judgment / process items → manual

  // ── Buyer: offer ──
  "Doc list (offer, addenda, disclosures, deposit receipt)": (d) => !!d.offerPrice,

  // ── Buyer: accepted ──
  // inspection / insurance tracking → manual

  // ── Buyer: conditions ──
  "Lawyer / conveyancer info captured": (_d, e) =>
    nonEmptyString(e.lawyerName) || nonEmptyString(e.lawyerInfo),
  "SkySlope missing-doc list cleared": (_d, e) =>
    Array.isArray(e.skyslopeMissing) && (e.skyslopeMissing as unknown[]).length === 0,

  // ── Buyer: removed ──
  "All conditions removed / waived": (d, e) =>
    !!d.subjectRemovalDate || !!e.subjectsRemovedAt || !!d.subjectsRemovedAt,
  "Completion + possession dates locked": (d) =>
    !!d.completionDate && !!d.possessionDate,

  // ── Buyer: closing / buyer-closed ──
  "Buyer file archived": (d) => d.status === "archived" || d.status === "closed",
};

// True when the deal's data marks this checklist item complete, no click needed.
function isAutoChecked(
  item: string,
  deal: AdminDeal | undefined,
  extra: Record<string, unknown>,
): boolean {
  if (!deal) return false;
  const pred = CHECKLIST_AUTO_CONDITIONS[item];
  if (!pred) return false;
  try {
    return pred(deal, extra);
  } catch {
    return false;
  }
}

// "checked 3 days ago" style relative date for the audit timestamp.
function relativeDate(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diffMs = Date.now() - t;
  const day = 86400000;
  const days = Math.floor(diffMs / day);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

const MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtMoney(n: number): string {
  return "$" + Math.round(n).toLocaleString();
}
function fmtShortDate(s: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  if (!m) return s || "";
  return MONTHS_ABBR[parseInt(m[2], 10) - 1] + " " + parseInt(m[3], 10);
}

function joinValues(values: Array<string | null | undefined>): string {
  return values.map((v) => (v || "").trim()).filter(Boolean).join("; ");
}

function splitAddress(address: string, provinceFallback: string) {
  const postal = address.match(/[A-Z]\d[A-Z][ -]?\d[A-Z]\d/i)?.[0]?.toUpperCase() || "";
  const withoutPostal = postal ? address.replace(postal, "").replace(/,\s*$/, "").trim() : address.trim();
  const parts = withoutPostal.split(",").map((part) => part.trim()).filter(Boolean);
  const street = parts[0] || address;
  const city = parts.length > 1 ? parts[1] : "";
  const province = parts.find((part) => /\b(BC|AB|SK|MB|ON|QC|NB|NS|PE|NL|YT|NT|NU)\b/i.test(part))?.match(/\b(BC|AB|SK|MB|ON|QC|NB|NS|PE|NL|YT|NT|NU)\b/i)?.[0]?.toUpperCase() || provinceFallback || "BC";
  const unit = street.match(/^(?:#|unit\s+|suite\s+)?([A-Za-z0-9-]+)\s*[-–]/i)?.[1] || "";
  return { street, unit, city, province, postal };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DealDetailModal({ deal, onClose }: DealDetailModalProps) {
  const isBuyer      = deal.side === "buyer";
  // Listing-side lead still at Pre-CMA: show the trimmed prospect view until
  // it moves forward into the CMA stage.
  const isSellerProspect = !isBuyer && deal.phase === "pre-cma";
  const pipeline      = isBuyer ? ADMIN_BUYER_PIPELINE      : ADMIN_PIPELINE;
  const phaseDetails  = isBuyer ? ADMIN_BUYER_PHASE_DETAILS  : ADMIN_PHASE_DETAILS;
  const sideCrumb     = isBuyer ? "BUYER ADMIN ADMIN"        : "LISTING ADMIN ADMIN";

  // Completed + upcoming stages collapse to a one-line summary; the current
  // stage auto-expands (see the effect below). Starts empty so nothing flashes
  // open before the real current stage is known.
  const [openPhases, setOpenPhases] = useState<Set<string>>(() => new Set());
  const userToggledPhasesRef = React.useRef(false);
  // Manual checklist checks live in the DB at extra.checklistManual (array of
  // itemKeys). Seeded from contextDeal once it loads; toggles write back through
  // setAdminDealToggle. Auto-checked items are derived separately from deal data.
  const [manualChecks, setManualChecks] = useState<Set<string>>(new Set());
  const [openInfoSections, setOpenInfoSections] = useState<Set<string>>(
    () => new Set(isBuyer ? [] : isSellerProspect ? ["prospect"] : ["core", "seller", "mlc"])
  );
  const [infoValues, setInfoValues] = useState<Record<string, string>>({});
  const [savingInfoKey, setSavingInfoKey] = useState<string | null>(null);

  // Real per-deal context from the backend (province guide, per-stage province
  // documents, conditional docs). Falls back to seed data when a deal has no
  // saved file yet (demo/placeholder cards), so this never regresses.
  const [ctx, setCtx] = useState<DealContext | null>(null);
  const [answeringRun, setAnsweringRun] = useState<string | null>(null);
  const reloadCtx = useCallback(() => {
    if (!deal.id) return;
    api
      .getDealContext(deal.id)
      .then((c) => setCtx(c))
      .catch(() => {});
  }, [deal.id]);
  useEffect(() => {
    if (!deal.id) return;
    let active = true;
    api
      .getDealContext(deal.id)
      .then((c) => {
        if (active) setCtx(c);
      })
      .catch(() => {
        /* no saved deal file — keep seed fallback */
      });
    return () => {
      active = false;
    };
  }, [deal.id]);
  const answerRun = useCallback(
    async (runId: string, approved: boolean) => {
      setAnsweringRun(runId);
      try {
        await api.approveAdminActionRun(runId, { approved, runNow: approved });
        // Best-effort side-effect: when a WAITING ON YOU item is approved on
        // this deal's scorecard, resolve any matching surface-approval (its
        // description carries `Deal: <deal_id>`) so it stops showing in the
        // separate approvals queue. Never block or throw into the main flow.
        if (approved && deal.id) {
          try {
            const { approvals } = await api.getSurfaceApprovals("pending");
            const matches = (approvals || []).filter((a) =>
              (a.description || "").includes(deal.id),
            );
            for (const a of matches) {
              await api.resolveSurfaceApproval(a.id, "approve", "Cleared via scorecard approval");
            }
            if (matches.length) reloadCtx();
          } catch {
            /* surface-approvals API absent/404/empty — silently continue */
          }
        }
        reloadCtx();
      } finally {
        setAnsweringRun(null);
      }
    },
    [reloadCtx, deal.id],
  );
  // Fillable "Waiting on you" card: the operator types answers to the run's
  // requiredFields and submits them; the skill re-runs with the answers filled
  // in (no chat round-trip). Keyed by runId -> { field -> typed value }.
  const [fieldAnswers, setFieldAnswers] = useState<Record<string, Record<string, string>>>({});
  const [submittingAnswers, setSubmittingAnswers] = useState<string | null>(null);
  const submitAnswers = useCallback(
    async (runId: string, fields: string[]) => {
      const entered = fieldAnswers[runId] || {};
      const answers: Record<string, string> = {};
      for (const f of fields) {
        const v = (entered[f] || "").trim();
        if (v) answers[f] = v;
      }
      if (Object.keys(answers).length === 0) return;
      setSubmittingAnswers(runId);
      try {
        await api.answerAdminActionRun(runId, { answers, runNow: true });
        setFieldAnswers((prev) => ({ ...prev, [runId]: {} }));
        reloadCtx();
      } finally {
        setSubmittingAnswers(null);
      }
    },
    [fieldAnswers, reloadCtx],
  );
  // Open the approved CMA PDF in the user's real browser (renders PDFs inline).
  // Same desktop-shell constraints as openRunPdf below: no blob windows, no PDF
  // plugin in app windows, http(s) URLs off the backend origin go to the OS
  // browser. So hit the same server via its alternate loopback host + ?token=.
  // Active only when a cma_report exists.
  const openCmaPdf = useCallback(() => {
    const token =
      (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    const origin = window.location.origin;
    const externalOrigin = origin.includes("127.0.0.1")
      ? origin.replace("127.0.0.1", "localhost")
      : origin.replace("localhost", "127.0.0.1");
    // Backend route is /api/admin/deals/{id}/cma-pdf (1.2.59). The old
    // /api/deals/... path 404s → the auth layer returns 401 → the new tab shows
    // {"detail":"Unauthorized"}. Use the /admin/ path the route is registered at.
    // The PDF response carries an etag/last-modified with no Cache-Control, so a
    // browser that once cached the download-style (attachment) response keeps
    // re-serving it. A per-open cache-buster forces a fresh fetch of the current
    // inline response so it OPENS in the viewer instead of downloading.
    window.open(
      `${externalOrigin}/api/admin/deals/${deal.id}/cma-pdf?token=${encodeURIComponent(token)}&v=${Date.now()}`,
      "_blank",
      "noopener,noreferrer",
    );
  }, [deal.id]);
  // Offer-kit: open one editable kit document in a new tab (same loopback +
  // ?token= trick as openCmaPdf), and approve/un-approve a kit document.
  // Same shell constraints as openCmaPdf above. Opens the listing's latest
  // weekly seller-update PDF. Active only when a seller_update attachment exists.
  const openSellerUpdatePdf = useCallback(() => {
    const token =
      (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
    const origin = window.location.origin;
    const externalOrigin = origin.includes("127.0.0.1")
      ? origin.replace("127.0.0.1", "localhost")
      : origin.replace("localhost", "127.0.0.1");
    window.open(
      `${externalOrigin}/api/deals/${deal.id}/seller-update-pdf?token=${encodeURIComponent(token)}`,
      "_blank",
      "noopener,noreferrer",
    );
  }, [deal.id]);
  // Open the PDF a skill drafted and parked on a waiting run (e.g. a
  // General/Trust Release awaiting approval) in the user's real browser, which
  // renders PDFs inline. The desktop shell can't: its windows have no PDF
  // plugin (grey box), and its window-open handler denies blob: URLs. The
  // handler routes http(s) URLs that DON'T match the backend origin to the OS
  // browser via shell.openExternal — so we hit the SAME local server through
  // its alternate loopback host (127.0.0.1 <-> localhost). Auth rides on the
  // ?token= query param since a new tab can't send an auth header, and the
  // backend whitelists ?token= for this read-only download path.
  const openRunPdf = useCallback(
    (runId: string) => {
      const token =
        (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ ||
        "";
      const origin = window.location.origin;
      const externalOrigin = origin.includes("127.0.0.1")
        ? origin.replace("127.0.0.1", "localhost")
        : origin.replace("localhost", "127.0.0.1");
      const url = `${externalOrigin}/api/deals/${deal.id}/run-draft-pdf/${runId}?token=${encodeURIComponent(token)}`;
      window.open(url, "_blank", "noopener,noreferrer");
    },
    [deal.id],
  );
  // Approve & Send the weekly seller-update Gmail draft (PDF attached) the
  // seller-updates workflow already created. External send => gated behind a
  // confirm dialog; never fires on a single click. On success we stamp the
  // local sent state + reload context so the button re-renders as "Sent".
  const [confirmSendUpdate, setConfirmSendUpdate] = useState(false);
  const [sendingUpdate, setSendingUpdate] = useState(false);
  const [sendUpdateError, setSendUpdateError] = useState<string | null>(null);
  const [sentUpdateAtLocal, setSentUpdateAtLocal] = useState<string | null>(null);
  const [pendingSkillConfirm, setPendingSkillConfirm] = useState<string | null>(null);
  const [skillNotice, setSkillNotice] = useState<string | null>(null);
  const sendSellerUpdate = useCallback(async () => {
    setSendingUpdate(true);
    setSendUpdateError(null);
    try {
      const res = await api.sendDealSellerUpdate(deal.id);
      setSentUpdateAtLocal(res.sentAt || new Date().toISOString());
      setConfirmSendUpdate(false);
      reloadCtx();
    } catch (e) {
      setSendUpdateError(e instanceof Error ? e.message : String(e));
    } finally {
      setSendingUpdate(false);
    }
  }, [deal.id, reloadCtx]);

  // Fire an Elevate skill on this deal via the harness (queues + runs it).
  // The skill does the work and asks before anything is sent (DigiSign gates).
  const [firingSkill, setFiringSkill] = useState<string | null>(null);
  const fireSkill = useCallback(
    async (skill: string, label: string) => {
      if (pendingSkillConfirm !== skill) {
        setPendingSkillConfirm(skill);
        setSkillNotice(`Click ${label} again to start the workflow.`);
        return;
      }
      setPendingSkillConfirm(null);
      setSkillNotice(null);
      setFiringSkill(skill);
      try {
        await api.runAdminDealTask({ dealId: deal.id, skill, title: label, runNow: true });
        reloadCtx();
      } finally {
        setFiringSkill(null);
      }
    },
    [deal.id, pendingSkillConfirm, reloadCtx],
  );

  const guide = ctx?.provinceGuide ?? null;
  const provinceLabel =
    guide?.provinceLabel || (ctx?.deal?.province ?? "").toUpperCase() || "VANCOUVER";
  // Real province documents for a stage label like "S8" -> stageDocuments[8].
  const contextDeal = ctx?.deal;
  const extra = contextDeal?.extraToggles ?? {};
  const addressParts = splitAddress(
    contextDeal?.listingAddress || deal.line2 || deal.addr || "",
    contextDeal?.province || provinceLabel || "BC"
  );
  const sellerContacts = [
    ctx?.primaryContact ?? null,
    ...(ctx?.coContacts || [])
      .filter((c) => /seller|owner|client/i.test(c.role || ""))
      .map((c) => c.contact ?? null),
  ].filter((c): c is NonNullable<typeof c> => Boolean(c));
  const sellerNames = joinValues(sellerContacts.map((c) => c.displayName));
  const sellerEmails = joinValues(sellerContacts.map((c) => c.primaryEmail));
  const sellerPhones = joinValues(sellerContacts.map((c) => c.primaryPhone));

  const buyerContacts = [
    ctx?.primaryContact ?? null,
    ...(ctx?.coContacts || []).map((c) => c.contact ?? null),
  ].filter((c): c is NonNullable<typeof c> => Boolean(c));
  const buyerNamesAuto = joinValues(buyerContacts.map((c) => c.displayName));
  const buyerEmailsAuto = joinValues(buyerContacts.map((c) => c.primaryEmail));
  const buyerPhonesAuto = joinValues(buyerContacts.map((c) => c.primaryPhone));

  const autoInfoValue = (key: string): string => {
    const saved = stringValue(extra[key]);
    if (saved) return saved;
    switch (key) {
      case "core.propertyAddress": return addressParts.street || contextDeal?.listingAddress || deal.line2 || deal.addr || "";
      case "core.unitNumber": return addressParts.unit;
      case "core.city": return addressParts.city;
      case "core.province": return contextDeal?.province || addressParts.province;
      case "core.postalCode": return addressParts.postal;
      case "core.mlsNumber": return contextDeal?.mlsNumber || deal.mls || "";
      case "core.legalDescription": return contextDeal?.legalDescription || "";
      case "core.propertyType": return contextDeal?.propertySubtype || stringValue(extra.propertyType);
      case "core.bedrooms": return stringValue(extra.bedrooms || extra.beds);
      case "core.bathrooms": return stringValue(extra.bathrooms || extra.baths);
      case "core.livingSqft": return stringValue(extra.livingSqft || extra.squareFootage || extra.finishedArea);
      case "core.neighbourhood": return stringValue(extra.neighbourhood || extra.neighborhood);
      case "core.tenureTitleType": return stringValue(extra.tenureTitleType);
      case "core.pid": return stringValue(extra.pid);
      case "core.rollFolioNumber": return stringValue(extra.rollFolioNumber || extra.folioNumber || extra.rollNumber);
      case "core.listingDriveFolderLink": return stringValue(extra.listingDriveFolderLink || extra.driveFolderUrl || extra.driveFolderLink);
      case "core.skySlopeFileLink": return stringValue(extra.skySlopeFileLink || extra.skyslopeFileLink);
      case "core.matrixXposureDraftLink": return stringValue(extra.matrixXposureDraftLink || extra.matrixDraftLink || extra.xposureDraftLink);
      case "core.liveListingUrl": return stringValue(extra.liveListingUrl || extra.mlsUrl);
      case "core.landingPageUrl": return stringValue(extra.landingPageUrl || extra.landingUrl);
      // Strata group — only rendered for strata subtypes
      case "core.strataFee": return stringValue(extra.strataFee || extra.strataFeeMonthly);
      case "core.strataPlan": return stringValue(extra.strataPlan);
      // Manufactured / mobile-home group — only rendered for mobile subtypes
      case "core.unitMake": return stringValue(extra.unitMake);
      case "core.unitModel": return stringValue(extra.unitModel);
      case "core.unitYear": return stringValue(extra.unitYear);
      case "core.serialNo": return stringValue(extra.serialNo);
      case "core.csaNo": return stringValue(extra.csaNo);
      case "core.mhrNo": return stringValue(extra.mhrNo);
      case "core.padRent": return stringValue(extra.padRent);
      case "core.parkName": return stringValue(extra.parkName);
      case "seller.legalNames": return stringValue(extra.sellerLegalNames) || sellerNames;
      case "seller.preferredNames": return stringValue(extra.sellerPreferredNames) || sellerNames;
      case "seller.emails": return stringValue(extra.sellerEmails) || sellerEmails;
      case "seller.phones": return stringValue(extra.sellerPhones) || sellerPhones;
      case "seller.signingAuthority": return contextDeal?.signingAuthority || stringValue(extra.signingAuthority);
      case "seller.preferredSigningEmail": return stringValue(extra.preferredSigningEmail) || sellerEmails.split(";")[0]?.trim() || "";
      case "seller.mailingAddress": return stringValue(extra.sellerMailingAddress);
      case "seller.residencyStatus": return stringValue(extra.sellerResidencyStatus);
      case "seller.signingLocationProvince": return stringValue(extra.signingLocationProvince);
      case "seller.lawyerChosen": return stringValue(extra.sellerLawyerChosen);
      case "seller.lawyerName": return stringValue(extra.sellerLawyerName);
      case "seller.lawyerFirm": return stringValue(extra.sellerLawyerFirm);
      case "seller.lawyerEmail": return stringValue(extra.sellerLawyerEmail);
      case "seller.lawyerPhone": return stringValue(extra.sellerLawyerPhone);
      case "seller.lawyerCityProvince": return stringValue(extra.sellerLawyerCityProvince);
      case "mlc.listingPrice": return stringValue(extra.mlcListingPrice) || (contextDeal?.listPrice ? `$${contextDeal.listPrice.toLocaleString()}` : deal.price || "");
      case "mlc.commissionTerms": return stringValue(extra.mlcCommissionTerms || extra.commissionTerms);
      case "mlc.cooperatingBrokerageCommission": return stringValue(extra.mlcCooperatingBrokerageCommission || extra.cooperatingBrokerageCommission);
      case "mlc.contractEffectiveDate": return stringValue(extra.mlcContractEffectiveDate || extra.contractEffectiveDate || contextDeal?.listingDate);
      case "mlc.expiryDate": return stringValue(extra.mlcExpiryDate || extra.expiryDate);
      case "mlc.plannedMlsLiveDate": return stringValue(extra.mlcPlannedMlsLiveDate || extra.plannedMlsLiveDate || contextDeal?.listingPublishedAt);
      case "mlc.comingSoonDate": return stringValue(extra.mlcComingSoonDate || extra.comingSoonDate);
      case "mlc.listingStatus": return stringValue(extra.mlcListingStatus || extra.listingStatus);
      case "mlc.includedItems": return stringValue(extra.mlcIncludedItems || extra.includedItems);
      case "mlc.excludedItems": return stringValue(extra.mlcExcludedItems || extra.excludedItems);
      case "mlc.tenancyDetails": return stringValue(extra.mlcTenancyDetails || extra.tenancyDetails);
      case "mlc.sellerInstructions": return stringValue(extra.mlcSellerInstructions || extra.sellerInstructions);
      case "mlc.occupancy": return stringValue(extra.mlcOccupancy || extra.occupancy);
      case "mlc.showingInstructions": return stringValue(extra.mlcShowingInstructions || extra.showingInstructions);
      case "mlc.lockboxCodeStatus": return stringValue(extra.mlcLockboxCodeStatus || extra.lockboxCodeStatus);
      case "mlc.signRiderStatus": return stringValue(extra.mlcSignRiderStatus || extra.signRiderStatus);
      // Property Specs — auto-pulled from listing data (extra_toggles_json)
      case "specs.bedrooms": return stringValue(extra.bedrooms || extra.beds);
      case "specs.bathrooms": return stringValue(extra.bathrooms || extra.baths);
      case "specs.squareFootage": return stringValue(extra.squareFootage || extra.sqft || extra.squareFeet || extra.finishedArea);
      case "specs.yearBuilt": return stringValue(extra.yearBuilt || extra.year_built);
      case "specs.lotSize": return stringValue(extra.lotSize || extra.lotSizeSqft || extra.lot_size_sqft);
      case "specs.strataFeeMonthly": return extra.strataFeeMonthly ? `$${stringValue(extra.strataFeeMonthly)}/mo` : stringValue(extra.strataFee);
      case "specs.parking": return stringValue(extra.parking || extra.garage);
      case "specs.includedAppliances": return stringValue(extra.includedAppliances || extra.appliances);
      case "specs.bonusFeatures": return Array.isArray(extra.featuresBullets) ? extra.featuresBullets.join(" · ") : stringValue(extra.bonusFeatures || extra.featuresBullets);
      // Accepted-Offer Counterparty — fills SkySlope transaction
      case "offer.buyerNames": return Array.isArray(extra.skyslopeBuyerNames) ? extra.skyslopeBuyerNames.join(", ") : stringValue(extra.buyerNames || extra.skyslopeBuyerNames);
      case "offer.cooperatingAgent": return stringValue(extra.cooperatingAgent || extra.coopAgent);
      case "offer.cooperatingBrokerage": return stringValue(extra.cooperatingBrokerage || extra.coopBrokerage);
      case "offer.cooperatingAgentPhone": return stringValue(extra.cooperatingAgentPhone || extra.coopAgentPhone);
      case "offer.cooperatingAgentEmail": return stringValue(extra.cooperatingAgentEmail || extra.coopAgentEmail);
      // Buyer client + home-search criteria — from the hot-lead form + contacts
      // The accepted-offer / SkySlope flow stores buyer names as buyerNames /
      // skyslopeBuyerNames (see offer.buyerNames above), NOT buyerClientNames —
      // without reading those the card fell through to the deal title/address.
      case "buyer.clientNames": return stringValue(extra.buyerClientNames)
        || (Array.isArray(extra.skyslopeBuyerNames) ? extra.skyslopeBuyerNames.join(", ") : stringValue(extra.buyerNames))
        || buyerNamesAuto || contextDeal?.title || deal.addr.replace(/\s*[—-]\s*buyer track$/i, "");
      case "buyer.emails": return stringValue(extra.buyerEmails) || buyerEmailsAuto;
      case "buyer.phones": return stringValue(extra.buyerPhones) || buyerPhonesAuto;
      case "buyer.mailingAddress": return stringValue(extra.mailingAddress);
      case "buyer.targetMls": return stringValue(extra.targetMls) || (contextDeal?.mlsNumber || "");
      case "buyer.cpsPid": return stringValue(extra.cpsPid);
      case "buyer.cpsLegalDescription": return stringValue(extra.cpsLegalDescription) || (contextDeal?.legalDescription || "");
      case "buyer.timeline": return stringValue(extra.buyerTimeline || extra.hotLeadTimeline);
      case "buyer.financingStatus": return stringValue(extra.buyerFinancingStatus || extra.financingStatus);
      case "buyer.lenderBroker": return stringValue(extra.buyerLenderBroker || extra.lenderBroker);
      case "buyer.budget": return stringValue(extra.buyerBudget || extra.hotLeadBudget || extra.budget);
      case "buyer.lookingFor": return stringValue(extra.buyerLookingFor || extra.hotLeadLookingFor || extra.lookingFor || extra.top25Note);
      case "buyer.preferredAreas": return stringValue(extra.buyerPreferredAreas || extra.preferredAreas || extra.areas);
      case "buyer.propertyType": return stringValue(extra.buyerPropertyType);
      case "buyer.bedrooms": return stringValue(extra.buyerBedrooms || extra.buyerBeds);
      case "buyer.bathrooms": return stringValue(extra.buyerBathrooms || extra.buyerBaths);
      case "buyer.mustHaves": return stringValue(extra.buyerMustHaves || extra.mustHaves);
      case "buyer.dealBreakers": return stringValue(extra.buyerDealBreakers || extra.dealBreakers);
      case "buyer.notes": return stringValue(extra.buyerNotes);
      // Seller prospect — lead-level details before the deal moves into CMA
      case "prospect.clientNames": return stringValue(extra.prospectClientNames) || sellerNames || contextDeal?.title || "";
      case "prospect.emails": return stringValue(extra.prospectEmails) || sellerEmails;
      case "prospect.phones": return stringValue(extra.prospectPhones) || sellerPhones;
      case "prospect.propertyAddress": return stringValue(extra.prospectPropertyAddress) || contextDeal?.listingAddress || deal.line2 || deal.addr || "";
      case "prospect.timeline": return stringValue(extra.prospectTimeline || extra.hotLeadTimeline);
      case "prospect.priceExpectation": return stringValue(extra.prospectPriceExpectation || extra.hotLeadBudget || extra.budget);
      case "prospect.situation": return stringValue(extra.prospectSituation || extra.hotLeadLookingFor || extra.lookingFor || extra.top25Note);
      case "prospect.notes": return stringValue(extra.prospectNotes);
      default: return saved;
    }
  };

  const infoFieldValue = (key: string) => infoValues[key] ?? autoInfoValue(key);
  const landingUrl = (infoFieldValue("mlc.landingPageUrl") || infoFieldValue("core.landingPageUrl") || "").trim();

  // ── Listing Performance (listing-side only) ──
  // Reads from the deal's extra toggles; populated by the weekly seller update.
  const perfMetrics: Array<{ key: string; label: string; value: string; tone?: "blue" | "orange" }> = [
    { key: "perfDom", label: "Days on Market", value: stringValue(extra.perfDom) },
    { key: "perfClientViews", label: "Client Views", value: stringValue(extra.perfClientViews), tone: "blue" },
    { key: "perfAgentViews", label: "Agent Views", value: stringValue(extra.perfAgentViews), tone: "blue" },
    { key: "perfFavorites", label: "Favorites", value: stringValue(extra.perfFavorites), tone: "blue" },
    { key: "perfAgentPrints", label: "Agent Prints", value: stringValue(extra.perfAgentPrints) },
    { key: "perfShowings", label: "Showings", value: stringValue(extra.perfShowings), tone: "orange" },
  ];
  const perfUpdatedAt = stringValue(extra.perfUpdatedAt).trim();
  const perfHasAny = perfMetrics.some((m) => m.value.trim());
  const showPerf = Boolean(perfUpdatedAt) || perfHasAny;
  // Documents panel shows the real Drive files; this is the "still missing" list at the current stage.
  const trayMissingDocs = ctx?.dealFlow?.gate?.missingDocs ?? [];
  const filledCount = (section: InfoSectionDef) =>
    section.fields.filter((field) => infoFieldValue(field.key).trim()).length;
  const saveInfoField = async (key: string, value: string) => {
    setSavingInfoKey(key);
    try {
      // Field keys are namespaced (e.g. "core.pid"), but the getters read the
      // bare suffix off `extra` (extra.pid). The backend stores the key
      // verbatim, so we must save under the bare key — otherwise the edit lands
      // in extra["core.pid"] and the card can't read it back (it vanishes on
      // reload). Strip the namespace prefix to match what the getters read.
      const storageKey = key.includes(".") ? key.slice(key.indexOf(".") + 1) : key;
      await api.setAdminDealToggle(deal.id, storageKey, value.trim() || null);
    } finally {
      setSavingInfoKey(null);
    }
  };
  const toggleInfoSection = (id: string) =>
    setOpenInfoSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const currentPhase = pipeline.find((p) => p.id === deal.phase) || pipeline[0];
  const currentIdx   = pipeline.indexOf(currentPhase);

  // Auto-expand the current stage and keep completed + upcoming collapsed.
  // Stops managing once the user manually toggles or jumps to a stage.
  React.useEffect(() => {
    if (userToggledPhasesRef.current) return;
    setOpenPhases(new Set(currentPhase ? [currentPhase.id] : []));
    if (currentIdx > 0) {
      requestAnimationFrame(() => {
        document.getElementById(`abm-phase-${currentPhase?.id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPhase?.id, currentIdx]);

  const itemKey = (phaseId: string, item: string, idx: number) => `${phaseId}:${idx}:${item}`;

  // An item is checked when its data condition is auto-satisfied OR it's in the
  // DB-backed manual set. Auto-checked items need no click.
  const isItemChecked = (phaseId: string, item: string, idx: number): boolean =>
    isAutoChecked(item, contextDeal, extra) || manualChecks.has(itemKey(phaseId, item, idx));
  const isItemAuto = (item: string): boolean => isAutoChecked(item, contextDeal, extra);

  // Seed/sync the manual set from the DB whenever the deal context (re)loads.
  const manualFromDb = JSON.stringify(readChecklistManual(extra).sort());
  useEffect(() => {
    setManualChecks(new Set(JSON.parse(manualFromDb) as string[]));
  }, [manualFromDb]);

  // Toggle a manual check. Auto-satisfied items are already shown checked and
  // don't need a manual entry, so toggling one is a no-op for completion. We
  // still let the click flow through for non-auto items, persisting the new set
  // to extra.checklistManual via the same path the info fields use.
  const toggleChecklistItem = (phaseId: string, item: string, idx: number) => {
    if (isAutoChecked(item, contextDeal, extra)) return;
    const key = itemKey(phaseId, item, idx);
    setManualChecks((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      api
        .setAdminDealToggle(deal.id, "checklistManual", JSON.stringify(Array.from(next)))
        .catch(() => {});
      return next;
    });
  };

  const togglePhase = (id: string) => {
    userToggledPhasesRef.current = true;
    setOpenPhases((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  // Jump rail: open the target stage and scroll it into view.
  const jumpToStage = (id: string) => {
    userToggledPhasesRef.current = true;
    setOpenPhases((s) => { const n = new Set(s); n.add(id); return n; });
    requestAnimationFrame(() => {
      document.getElementById(`abm-phase-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  // Alias icons to match original variable names
  const Calendar  = Clock;
  const ChevDown  = Chevron;

  return createPortal(
    <div className="ab-modal-backdrop" onClick={onClose}>
      <div
        className="ab-modal"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        role="dialog"
      >
        <button className="ab-modal-close" onClick={onClose} aria-label="Close">
          <span className="x">&times;</span>
        </button>

        {/* Header (flush, no card) */}
        <header className="abm-head">
          <div className="abm-crumbs mono">
            <span>{sideCrumb}</span>
            <span className="sep">&middot;</span>
            <span className="stage">{currentPhase.stage}</span>
            <span className="sep">&middot;</span>
            <span className="stage">{currentPhase.name.toUpperCase()}</span>
          </div>
          <div className="abm-title-row">
            <h2 className="abm-title">{deal.addr}</h2>
            {/* Per-property "Ask Ozzie" chat — trigger sits by the address, panel floats */}
            <OzzieChatPanel dealId={deal.id} address={deal.addr} />
          </div>
          <div className="abm-meta">
            <span className="abm-meta-row">
              <Home />
              <span>{deal.line2}</span>
            </span>
            <span className="abm-meta-row">
              <Calendar />
              <span>{currentPhase.name}</span>
              <span className="dim">&middot;</span>
              <span className="dim">&mdash;</span>
            </span>
          </div>
          {contextDeal && (contextDeal.listPrice != null || contextDeal.offerPrice != null || contextDeal.depositAmount != null || contextDeal.commissionPct != null || contextDeal.completionDate) && (
            <div className="abm-money">
              {contextDeal.listPrice != null && (
                <div className="abm-money-cell">
                  <span className="k mono">List</span>
                  <span className="v">{fmtMoney(contextDeal.listPrice)}</span>
                </div>
              )}
              {contextDeal.offerPrice != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Accepted Offer</span>
                  <span className="v o">{fmtMoney(contextDeal.offerPrice)}</span>
                  {contextDeal.listPrice ? (
                    <span className="n">{Math.round((contextDeal.offerPrice / contextDeal.listPrice) * 100)}% of ask</span>
                  ) : null}
                </div>
              )}
              {(() => {
                const dep = deriveDeposit(contextDeal as unknown as Record<string, unknown>, extra as unknown as Record<string, unknown>);
                return (
                  <div className="abm-money-cell">
                    <span className="k mono">Deposit</span>
                    {dep.status === "not_due" ? (
                      <span className="v" style={{ fontSize: 12.5, color: "var(--fg-faint)" }}>Expected at subject removal</span>
                    ) : dep.status === "received" ? (
                      <>
                        <span className="v b">{dep.amount != null ? fmtMoney(dep.amount) : "Received"}</span>
                        {dep.receivedDate ? <span className="n">received {fmtShortDate(dep.receivedDate)}</span> : null}
                      </>
                    ) : (
                      <>
                        <span className="v b">{dep.amount != null ? fmtMoney(dep.amount) : "Not set"}</span>
                        {dep.dueDate ? <span className="n">due {fmtShortDate(dep.dueDate)}</span> : null}
                      </>
                    )}
                  </div>
                );
              })()}
              {contextDeal.commissionPct != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Commission</span>
                  <span className="v">{contextDeal.commissionPct}%</span>
                </div>
              )}
              {contextDeal.completionDate && (
                <div className="abm-money-cell">
                  <span className="k mono">Completion</span>
                  <span className="v">{fmtShortDate(contextDeal.completionDate)}</span>
                  {contextDeal.possessionDate ? (
                    <span className="n">poss. {fmtShortDate(contextDeal.possessionDate)}</span>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </header>

        <div className="abm-actionbar">
          <button className="abm-btn primary" type="button" disabled title="Stage advancement is handled from the board.">Advance phase</button>
          <button className="abm-btn ghost" type="button" disabled title="Manual force advance is unavailable for this deal.">Force advance</button>
          <button
            className="abm-btn collapse-sale"
            type="button"
            disabled={firingSkill === "collapse-sale"}
            onClick={() => fireSkill("collapse-sale", "Collapse Sale")}
          >
            {firingSkill === "collapse-sale" ? "Starting…" : "Collapse Sale"}
          </button>
          {isBuyer && (stringValue(extra.cpsPackageUrl) || stringValue(extra.cpsDraftUrl)) && (
            <a
              className="abm-btn"
              href={stringValue(extra.cpsPackageUrl) || stringValue(extra.cpsDraftUrl)}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: "none" }}
            >
              {stringValue(extra.cpsPackageUrl) ? "Open Offer Package ↗" : "Open CPS Draft ↗"}
            </a>
          )}
          {!isBuyer && (
            <button
              className="abm-btn price-reduction"
              type="button"
              disabled={firingSkill === "price-reduction"}
              onClick={() => fireSkill("price-reduction", "Price Reduction")}
            >
              {firingSkill === "price-reduction" ? "Starting…" : "Price Reduction"}
            </button>
          )}
          {!isBuyer && (
            <button
              className="abm-btn cancel-only"
              type="button"
              disabled={firingSkill === "cancel-listing"}
              onClick={() => fireSkill("cancel-listing", "Cancel")}
            >
              {firingSkill === "cancel-listing" ? "Starting…" : "Cancel"}
            </button>
          )}
          {!isBuyer && (
            <button
              className="abm-btn cancel-relist"
              type="button"
              disabled={firingSkill === "cancel-relist"}
              onClick={() => fireSkill("cancel-relist", "Cancel + Relist")}
            >
              {firingSkill === "cancel-relist" ? "Starting…" : "Cancel + Relist"}
            </button>
          )}
          {!isBuyer && (
            <a
              className={"abm-btn landing" + (landingUrl ? "" : " empty")}
              href={landingUrl || undefined}
              target="_blank"
              rel="noreferrer"
            >
              {landingUrl ? "Landing Page ↗" : "Landing Page — add URL"}
            </a>
          )}
          {!isBuyer && (() => {
            const cmaReady = (ctx?.attachments ?? []).some((a) => a.kind === "cma_report");
            return (
              <button
                className={"abm-btn cma-pdf" + (cmaReady ? "" : " empty")}
                type="button"
                disabled={!cmaReady}
                onClick={cmaReady ? openCmaPdf : undefined}
                title={cmaReady ? "Open the approved CMA PDF" : "No approved CMA yet"}
              >
                {cmaReady ? "CMA PDF ↗" : "CMA PDF — pending"}
              </button>
            );
          })()}
        </div>
        {skillNotice && <div className="abm-confirm-error" role="status">{skillNotice}</div>}

        {!isBuyer && (
          <div className="abm-perf">
            <div className="abm-perf-head">
              <span className="abm-perf-title">Listing Performance</span>
              {perfUpdatedAt && (
                <span className="abm-perf-asof mono">as of {fmtShortDate(perfUpdatedAt)}</span>
              )}
              {(() => {
                const sellerUpdateReady = (ctx?.attachments ?? []).some(
                  (a) => a.kind === "seller_update",
                );
                const draftId = stringValue(extra.sellerUpdateDraftId);
                const sellerEmail = stringValue(extra.sellerUpdateSellerEmail);
                const sentAt = sentUpdateAtLocal || stringValue(extra.sellerUpdateSentAt);
                return (
                  <>
                    <button
                      className={"abm-btn seller-pdf" + (sellerUpdateReady ? "" : " empty")}
                      type="button"
                      disabled={!sellerUpdateReady}
                      onClick={sellerUpdateReady ? openSellerUpdatePdf : undefined}
                      title={
                        sellerUpdateReady
                          ? "Open the latest weekly seller update PDF"
                          : "No weekly seller update yet"
                      }
                    >
                      {sellerUpdateReady ? "Weekly Update PDF ↗" : "Weekly Update — pending"}
                    </button>
                    {draftId ? (
                      sentAt ? (
                        <button
                          className="abm-btn send-update sent"
                          type="button"
                          disabled
                          title={`Weekly update emailed ${relativeDate(sentAt)}`}
                        >
                          Sent {relativeDate(sentAt)}
                        </button>
                      ) : (
                        <button
                          className="abm-btn send-update"
                          type="button"
                          onClick={() => {
                            setSendUpdateError(null);
                            setConfirmSendUpdate(true);
                          }}
                          title={`Email this week's update PDF to ${sellerEmail || "the seller"}`}
                        >
                          Approve &amp; Send
                        </button>
                      )
                    ) : null}
                  </>
                );
              })()}
            </div>
            {showPerf ? (
              <div className="abm-perf-grid">
                {perfMetrics.map((m) => {
                  const showOrange = m.tone === "orange" && Number(m.value) > 0;
                  const cls =
                    "abm-perf-num" +
                    (m.tone === "blue" ? " blue" : "") +
                    (showOrange ? " orange" : "");
                  return (
                    <div className="abm-perf-cell" key={m.key}>
                      <span className={cls}>{m.value.trim() || "—"}</span>
                      <span className="abm-perf-label mono">{m.label}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="abm-perf-empty">
                No performance data yet — pulls in with your weekly seller update.
              </div>
            )}
          </div>
        )}

        <div className="ab-modal-scroll">
          {(() => {
            // Visible "it's working" state for in-flight runs. Without this a
            // running skill (e.g. a CMA that takes minutes) showed nothing on
            // the card, so it looked dead and people re-clicked / re-created.
            const running = (ctx?.priorRuns ?? []).filter((r) => r.status === "running");
            if (!running.length) return null;
            return (
              <div
                style={{
                  margin: "8px 0",
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: "rgba(94,138,208,0.10)",
                  border: "1px solid rgba(94,138,208,0.35)",
                }}
              >
                <style>{"@keyframes abmPulse{0%,100%{opacity:1}50%{opacity:.3}}"}</style>
                <div
                  className="mono"
                  style={{ fontSize: "0.72rem", letterSpacing: "0.05em", opacity: 0.85, display: "flex", alignItems: "center", gap: 6 }}
                >
                  <span
                    style={{ width: 8, height: 8, borderRadius: "50%", background: "#5E8AD0", display: "inline-block", animation: "abmPulse 1.1s ease-in-out infinite" }}
                  />
                  WORKING &middot; {running.length}
                </div>
                {running.map((r) => (
                  <div key={r.id} style={{ fontSize: "0.85rem", marginTop: 4 }}>
                    {String(r.registryName ?? "Running a skill")}… this can take a few minutes. You don't need to do anything.
                  </div>
                ))}
              </div>
            );
          })()}
          {(() => {
            const waiting = (ctx?.priorRuns ?? []).filter((r) => r.status === "waiting_human");
            if (!waiting.length) return null;
            return (
              <div className="abm-waiting">
                <div className="abm-waiting-head mono">WAITING ON YOU &middot; {waiting.length}</div>
                {waiting.map((r) => {
                  const hp = (r.humanPrompt ?? {}) as Record<string, unknown>;
                  const title = String(hp.title ?? r.registryName ?? "Needs your input");
                  const message = hp.message ? String(hp.message) : "";
                  // requiredFields entries can be plain strings (free-text) or
                  // objects { label, help, type:"select", options:[...] } so a
                  // decision renders as a dropdown with real choices + context.
                  const fields = (Array.isArray(hp.requiredFields)
                    ? (hp.requiredFields as unknown[]).map((f) => {
                        if (f && typeof f === "object") {
                          const o = f as Record<string, unknown>;
                          return {
                            label: String(o.label ?? o.name ?? o.key ?? ""),
                            help: o.help ? String(o.help) : "",
                            type: o.type === "select" ? "select" : o.type === "textarea" ? "textarea" : "text",
                            options: Array.isArray(o.options)
                              ? (o.options as unknown[]).map(String)
                              : [],
                          };
                        }
                        return { label: String(f), help: "", type: "text", options: [] as string[] };
                      })
                    : []
                  ).filter((f) => f.label);
                  // Hardcoded guarantee: Pre-CMA / CMA / listing / marketing cards
                  // always offer a spot to drop a property-photos Google Drive link,
                  // even if the skill did not ask for it. Optional — never required
                  // to submit. Deduped so a skill that already added a photo/drive
                  // field is not doubled. Scoped by skill/card context so unrelated
                  // cards (offers, closing, subject removal) do not get the field.
                  const PHOTOS_FIELD_LABEL = "Property photos (Google Drive link)";
                  const photoCtxId = (
                    String(r.skill ?? "") + " " + String(r.registryName ?? "")
                  ).toLowerCase();
                  const photoRelevant = /cma|seller-package|listing|marketing|photo/.test(photoCtxId);
                  const formFields =
                    fields.length > 0 &&
                    photoRelevant &&
                    !fields.some((f) => /photo/i.test(f.label) || /drive/i.test(f.label))
                      ? [
                          ...fields,
                          {
                            label: PHOTOS_FIELD_LABEL,
                            help: "Paste a Google Drive or Dropbox link to the property photos so the CMA can pull from them. Optional.",
                            type: "text",
                            options: [] as string[],
                          },
                        ]
                      : fields;
                  const hasDraftPdf =
                    (typeof hp.previewPdf === "string" && hp.previewPdf.trim() !== "") ||
                    (typeof (hp as Record<string, unknown>).preview_pdf === "string" &&
                      String((hp as Record<string, unknown>).preview_pdf).trim() !== "");
                  return (
                    <div className="abm-waiting-item" key={r.id}>
                      <div className="abm-waiting-title">{title}</div>
                      {message && <div className="abm-waiting-msg">{message}</div>}
                      {fields.length > 0 && (
                        <div className="abm-waiting-form">
                          <div className="abm-waiting-needs mono">FILL IN TO CONTINUE</div>
                          {formFields.map((f, i) => {
                            const setVal = (v: string) =>
                              setFieldAnswers((prev) => ({
                                ...prev,
                                [r.id]: { ...(prev[r.id] || {}), [f.label]: v },
                              }));
                            return (
                              <label className="abm-waiting-field" key={i}>
                                <span className="abm-waiting-field-label">{f.label}</span>
                                {f.help && <span className="abm-waiting-field-help">{f.help}</span>}
                                {f.type === "select" && f.options.length > 0 ? (
                                  <select
                                    className="abm-waiting-input"
                                    value={fieldAnswers[r.id]?.[f.label] ?? ""}
                                    disabled={submittingAnswers === r.id}
                                    onChange={(e) => setVal(e.target.value)}
                                  >
                                    <option value="" disabled>
                                      Choose…
                                    </option>
                                    {f.options.map((opt, j) => (
                                      <option key={j} value={opt}>
                                        {opt}
                                      </option>
                                    ))}
                                  </select>
                                ) : f.type === "textarea" ? (
                                  <textarea
                                    className="abm-waiting-input abm-waiting-textarea"
                                    rows={3}
                                    value={fieldAnswers[r.id]?.[f.label] ?? ""}
                                    placeholder={`Type ${f.label}…`}
                                    disabled={submittingAnswers === r.id}
                                    onChange={(e) => setVal(e.target.value)}
                                  />
                                ) : (
                                  <input
                                    type="text"
                                    className="abm-waiting-input"
                                    value={fieldAnswers[r.id]?.[f.label] ?? ""}
                                    placeholder={`Type ${f.label}…`}
                                    disabled={submittingAnswers === r.id}
                                    onChange={(e) => setVal(e.target.value)}
                                  />
                                )}
                              </label>
                            );
                          })}
                        </div>
                      )}
                      <div className="abm-waiting-actions">
                        {hasDraftPdf && (
                          <button
                            type="button"
                            className="abm-waiting-btn preview"
                            onClick={() => openRunPdf(r.id)}
                            title="Open the drafted PDF before you approve"
                          >
                            Preview PDF ↗
                          </button>
                        )}
                        {fields.length > 0 && (
                          <button
                            type="button"
                            className="abm-waiting-btn submit"
                            disabled={
                              submittingAnswers === r.id ||
                              !Object.values(fieldAnswers[r.id] || {}).some((v) => v.trim())
                            }
                            onClick={() => submitAnswers(r.id, formFields.map((f) => f.label))}
                            title="Send your answers and continue the skill"
                          >
                            {submittingAnswers === r.id ? "Sending…" : "Submit & run"}
                          </button>
                        )}
                        {/* Approve & re-run IGNORES typed fields — only show it on
                            no-field approval cards, never alongside a fillable form
                            (where it would silently drop the user's answers). */}
                        {fields.length === 0 && (
                          <button
                            type="button"
                            className="abm-waiting-btn approve"
                            disabled={answeringRun === r.id}
                            onClick={() => answerRun(r.id, true)}
                          >
                            {answeringRun === r.id ? "Working…" : "Approve & re-run"}
                          </button>
                        )}
                        <button
                          type="button"
                          className="abm-waiting-btn dismiss"
                          disabled={answeringRun === r.id}
                          onClick={() => answerRun(r.id, false)}
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}

          {((contextDeal?.side || (deal as unknown as { side?: string }).side) !== "buyer") && (
            <CmaWizard dealId={deal.id} />
          )}

          {((contextDeal?.side || (deal as unknown as { side?: string }).side) !== "buyer") && (
            <ListingKitWizard
              dealId={deal.id}
              extra={extra}
              address={(contextDeal as unknown as { listingAddress?: string })?.listingAddress ?? (deal as unknown as { listingAddress?: string; address?: string })?.listingAddress ?? (deal as unknown as { address?: string })?.address}
              sellerName={(extra as unknown as { sellerNames?: string }).sellerNames}
              currentStage={(contextDeal as unknown as { currentStage?: number })?.currentStage ?? (deal as unknown as { currentStage?: number })?.currentStage ?? 0}
              onUpdate={reloadCtx}
            />
          )}

          {((contextDeal?.side || (deal as unknown as { side?: string }).side) === "buyer") && (
            <OnboardingPanel dealId={deal.id} extra={extra}
              currentStage={(contextDeal as unknown as { currentStage?: number })?.currentStage ?? (deal as unknown as { currentStage?: number })?.currentStage ?? 0}
              clientFields={BUYER_CLIENT_FIELDS} searchFields={BUYER_SEARCH_FIELDS}
              fieldValue={infoFieldValue} saveField={saveInfoField} />
          )}

          {((contextDeal?.side || (deal as unknown as { side?: string }).side) === "buyer") && (
            <OfferKitWizard
              dealId={deal.id}
              extra={extra}
              address={(contextDeal as unknown as { listingAddress?: string })?.listingAddress ?? (deal as unknown as { listingAddress?: string; address?: string })?.listingAddress ?? (deal as unknown as { address?: string })?.address}
              buyerName={(extra as unknown as { buyerNames?: string }).buyerNames}
              currentStage={(contextDeal as unknown as { currentStage?: number })?.currentStage ?? (deal as unknown as { currentStage?: number })?.currentStage ?? 0}
              onUpdate={reloadCtx}
            />
          )}


          {/* Deposit — tracked record (shows from accepted offer onward) */}
          {contextDeal && ((contextDeal.offerPrice != null) || ((contextDeal.currentStage ?? 0) >= 5)) && (
            <DepositCard
              dealId={deal.id}
              deal={contextDeal as unknown as Record<string, unknown>}
              toggles={extra as unknown as Record<string, unknown>}
              currentStage={contextDeal.currentStage ?? 0}
              subjectRemovalStage={((contextDeal.side || (deal as unknown as { side?: string }).side) === "buyer") ? 5 : 6}
              onUpdate={reloadCtx}
            />
          )}

          <div className="abm-cols">
            {/* ─── Left column: Transaction file ─── */}
            <div className="abm-col abm-col-left">
              <section className="abm-card">
                <header className="abm-card-head">
                  <div className="abm-card-title">
                    <Database />
                    <span>Transaction file</span>
                  </div>
                  <div className="abm-card-pills">
                    <span className="abm-pill mono">{provinceLabel}</span>
                    <span className="abm-pill mono">{(ctx?.attachments?.length ?? 0)} DOCS</span>
                    <span className="abm-pill mono">{(ctx?.priorRuns?.length ?? 0)} RUNS</span>
                  </div>
                </header>

                {/* Reusable info sections */}
                <div className="abm-info-stack">
                  {(isBuyer ? BUYER_INFO_SECTIONS : isSellerProspect ? SELLER_PROSPECT_SECTIONS : INFO_SECTIONS).filter((section) => {
                    if (section.minListingPhase) {
                      const minPhase = pipeline.find((p) => p.id === section.minListingPhase);
                      if (!minPhase || currentIdx < pipeline.indexOf(minPhase)) return false;
                    }
                    // Strata / mobile-home groups only show for the matching propertySubtype.
                    // propertySubtype is free-text ("strata apartment", "manufactured/mobile on land"),
                    // so match on lowercase keyword substrings, not exact enum values.
                    if (section.subtypes) {
                      const subtype = (contextDeal?.propertySubtype ?? "").toLowerCase();
                      if (!section.subtypes.some((s) => subtype.includes(s))) {
                        return false;
                      }
                    }
                    return true;
                  }).map((section) => {
                    const open = openInfoSections.has(section.id);
                    const done = section.readonly ? 0 : filledCount(section);
                    const skyslopeMissing = section.readonly ? readSkyslopeMissing(extra) : null;
                    const skyslopeCheckedAt = section.readonly ? stringValue(extra.skyslopeCheckedAt) : "";
                    const skyslopeCount =
                      section.id === "skyslope" && skyslopeMissing ? skyslopeMissing.length : null;
                    return (
                      <section className="abm-info-section" key={section.id}>
                        <button
                          type="button"
                          className="abm-info-head"
                          onClick={() => toggleInfoSection(section.id)}
                          aria-expanded={open}
                        >
                          <div>
                            <div className="abm-info-title">{section.title}</div>
                            <div className="abm-info-sub">{section.subtitle}</div>
                          </div>
                          {section.readonly ? (
                            skyslopeCount === null ? (
                              <span className="abm-phase-count mono">—</span>
                            ) : (
                              <span
                                className={"abm-phase-count mono" + (skyslopeCount > 0 ? " warn" : " ok")}
                              >
                                {skyslopeCount > 0 ? `${skyslopeCount} open` : "clear"}
                              </span>
                            )
                          ) : (
                            <span className="abm-phase-count mono">{done}/{section.fields.length}</span>
                          )}
                          <ChevDown className={"abm-phase-chev" + (open ? " open" : "")} />
                        </button>
                        {open && section.id === "skyslope" && (
                          <div className="abm-skyslope-body">
                            {skyslopeMissing && skyslopeMissing.length > 0 ? (
                              <>
                                <div className="abm-skyslope-head mono">
                                  {skyslopeMissing.length} missing
                                  {skyslopeCheckedAt ? ` · checked ${relativeDate(skyslopeCheckedAt)}` : ""}
                                </div>
                                <ul className="abm-skyslope-list">
                                  {skyslopeMissing.map((item, i) => (
                                    <li className="abm-skyslope-row" key={`${item.doc}-${i}`}>
                                      <span className="abm-skyslope-doc">{item.doc}</span>
                                      {item.status && (
                                        <span className="abm-skyslope-chip">{item.status}</span>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </>
                            ) : skyslopeMissing && skyslopeMissing.length === 0 && skyslopeCheckedAt ? (
                              <div className="abm-skyslope-clear">
                                ✓ All required SkySlope docs attached — checked {fmtShortDate(skyslopeCheckedAt)}
                              </div>
                            ) : (
                              <div className="abm-skyslope-empty">
                                Not yet checked — runs Mon/Wed, or trigger skyslope-sync.
                              </div>
                            )}
                          </div>
                        )}
                        {open && section.id !== "skyslope" && (
                          <div className="abm-info-grid">
                            {section.fields.map((field) => {
                              const value = infoFieldValue(field.key);
                              const saving = savingInfoKey === field.key;
                              return (
                                <label className="abm-info-field" key={field.key}>
                                  <span>
                                    {field.label}
                                    {saving && <em className="mono">saving</em>}
                                  </span>
                                  {field.kind === "select" ? (
                                    <select
                                      value={value}
                                      onChange={(e) => {
                                        const next = e.target.value;
                                        setInfoValues((prev) => ({ ...prev, [field.key]: next }));
                                        void saveInfoField(field.key, next);
                                      }}
                                    >
                                      <option value="">Not set</option>
                                      {(field.options || []).map((option) => (
                                        <option key={option} value={option}>{option}</option>
                                      ))}
                                    </select>
                                  ) : (
                                    <input
                                      type={field.kind === "url" ? "url" : "text"}
                                      value={value}
                                      placeholder="Not set yet"
                                      onChange={(e) => setInfoValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
                                      onBlur={(e) => void saveInfoField(field.key, e.target.value)}
                                    />
                                  )}
                                </label>
                              );
                            })}
                          </div>
                        )}
                      </section>
                    );
                  })}
                  <div className="abm-info-placeholder">
                    More sections can unlock here as the card moves through the pipeline.
                  </div>
                  {/* OfferPrepPanel retired — replaced by the Offer Kit wizard above. */}
                </div>

                {/* Documents — the deal's Drive folder, with what's still missing */}
                <DocumentsPanel dealId={deal.id} missing={trayMissingDocs.map((d) => d.label)} />

              </section>
            </div>

            {/* ─── Right column: Phase accordion list ─── */}
            <div className="abm-col abm-col-right">
              {/* Stage jump rail — click a chip to scroll to + expand that stage */}
              <div className="abm-stage-rail" role="tablist" aria-label="Jump to stage">
                {pipeline.map((p) => {
                  const i = pipeline.indexOf(p);
                  const st = i < currentIdx ? "done" : i === currentIdx ? "current" : "todo";
                  return (
                    <button
                      key={p.id}
                      type="button"
                      className={"abm-rail-chip " + st}
                      aria-label={`Jump to ${p.stage} · ${p.name}`}
                      title={`${p.stage} · ${p.name}`}
                      onClick={() => jumpToStage(p.id)}
                    >
                      {p.stage}
                    </button>
                  );
                })}
              </div>
              {pipeline.map((p) => {
                const detail = phaseDetails[p.id] || {
                  checklist: [] as string[],
                  documents: [] as [string, string][],
                  motion: "",
                  movesOn: "",
                  gate: "",
                };
                const idx     = pipeline.indexOf(p);
                const checkedCount = detail.checklist.filter((item, itemIdx) =>
                  isItemChecked(p.id, item, itemIdx)
                ).length;
                const done    = detail.checklist.length > 0 && checkedCount === detail.checklist.length;
                const current = idx === currentIdx;
                const open    = openPhases.has(p.id);

                return (
                  <div
                    key={p.id}
                    id={`abm-phase-${p.id}`}
                    className={
                      "abm-phase" +
                      (current ? " current" : "") +
                      (done ? " done" : "")
                    }
                  >
                    <button
                      type="button"
                      className="abm-phase-head"
                      onClick={() => togglePhase(p.id)}
                      aria-expanded={open}
                    >
                      <span
                        className="abm-phase-radio"
                        data-state={current ? "current" : done ? "done" : "todo"}
                      />
                      <div className="abm-phase-title-block">
                        <div className="abm-phase-title">
                          <span>{p.name}</span>
                          {current && (
                            <span className="abm-tag current mono">CURRENT</span>
                          )}
                        </div>
                        <div className="abm-phase-sub mono">
                          {p.stage} &middot;{" "}
                          {p.name.toUpperCase().replace(/ \/ /g, " · ")}
                        </div>
                        <div className="abm-phase-trigger">
                          <span className="abm-bullet" />
                          {detail.movesOn}
                        </div>
                      </div>
                      <span className="abm-phase-count mono">
                        {checkedCount}/{detail.checklist.length}
                      </span>
                      <ChevDown
                        className={
                          "abm-phase-chev" + (open ? " open" : "")
                        }
                      />
                    </button>

                    {open && (
                      <div className="abm-phase-body">
                        <div className="abm-phase-motion">
                          <div className="abm-phase-motion-head">
                            <span>{detail.motion.split(" · ")[0]}</span>
                            <span className="sep">&middot;</span>
                            <span className="abm-phase-approval">
                              {detail.motion.split(" · ")[1] || "approval"}
                            </span>
                          </div>
                          <div className="abm-phase-motion-line">
                            Moves on {detail.movesOn}
                          </div>
                          <div className="abm-phase-motion-gate">
                            <span className="abm-shield">&#x26E8;</span> Gate:{" "}
                            {detail.gate}
                          </div>
                        </div>

                        <div className="abm-section-label mono">
                          WORKFLOW CHECKLIST · CHECK OFF AS COMPLETED
                        </div>
                        <ul className="abm-checklist">
                          {detail.checklist.map((c, i) => {
                            const auto = isItemAuto(c);
                            const checked = auto || manualChecks.has(itemKey(p.id, c, i));
                            return (
                              <li key={i}>
                                <button
                                  type="button"
                                  className="abm-checklist-item"
                                  onClick={() => toggleChecklistItem(p.id, c, i)}
                                  aria-pressed={checked}
                                  disabled={auto}
                                  title={auto ? "Auto-completed from deal data" : undefined}
                                >
                                  <span className={"abm-check-box" + (checked ? " checked" : "")} />
                                  <span className={checked ? "done" : ""}>{c}</span>
                                  {auto && <span className="abm-check-auto mono">auto</span>}
                                </button>
                              </li>
                            );
                          })}
                        </ul>

                        {/* PROVINCE DOCUMENTS section removed per Skyleigh — the
                            auto-generated province doc list was inaccurate. */}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>
      {confirmSendUpdate && (
        <div
          className="abm-confirm-overlay"
          onClick={() => {
            if (!sendingUpdate) setConfirmSendUpdate(false);
          }}
        >
          <div className="abm-confirm" onClick={(e) => e.stopPropagation()}>
            <div className="abm-confirm-title">Send this week&rsquo;s update?</div>
            <div className="abm-confirm-body">
              This emails the weekly update PDF you just reviewed to{" "}
              {stringValue(extra.sellerUpdateSellerEmail) || "the seller"}.
            </div>
            {sendUpdateError && <div className="abm-confirm-error">{sendUpdateError}</div>}
            <div className="abm-confirm-actions">
              <button
                className="abm-btn ghost"
                type="button"
                disabled={sendingUpdate}
                onClick={() => setConfirmSendUpdate(false)}
              >
                Cancel
              </button>
              <button
                className="abm-btn send-update"
                type="button"
                disabled={sendingUpdate}
                onClick={sendSellerUpdate}
              >
                {sendingUpdate ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
