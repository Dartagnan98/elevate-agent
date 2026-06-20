
import React, { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
// The modal is portaled to <body> and can be opened outside AdminDesignShell.
import "../admin.css";
import {
  Home,
  Clock,
  Database,
  FileText,
  Chevron,
} from "../icons";
import {
  ADMIN_PIPELINE,
  ADMIN_BUYER_PIPELINE,
  ADMIN_PHASE_DETAILS,
  ADMIN_BUYER_PHASE_DETAILS,
} from "../admin-data";
import { api } from "@/lib/api";
import type { DealContext } from "@/lib/api-types";

function isPersistedDealId(id: string): boolean {
  return /^[a-f0-9]{32}$/i.test(id);
}

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
  /** Called after a change that should refresh the board (e.g. Top 25 pin toggle). */
  onChanged?: () => void;
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

const INFO_SECTIONS: InfoSectionDef[] = [
  {
    id: "core",
    title: "Core Property Section",
    subtitle: "Reusable details for MLC, CPS, SkySlope, WEBForms, Matrix, marketing, landing pages, signing, TRS, subject removal, and conveyancing.",
    fields: CORE_PROPERTY_FIELDS,
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
];

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

export default function DealDetailModal({ deal, onClose, onChanged }: DealDetailModalProps) {
  const isBuyer      = deal.side === "buyer";
  const pipeline      = isBuyer ? ADMIN_BUYER_PIPELINE      : ADMIN_PIPELINE;
  const phaseDetails  = isBuyer ? ADMIN_BUYER_PHASE_DETAILS  : ADMIN_PHASE_DETAILS;
  const sideCrumb     = isBuyer ? "BUYER ADMIN ADMIN"        : "LISTING ADMIN ADMIN";

  const [openPhases, setOpenPhases] = useState<Set<string>>(
    () => new Set(pipeline.map((p) => p.id))
  );
  const checklistStorageKey = `admin-scorecard-checklist:${deal.id}`;
  const [checkedItems, setCheckedItems] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(window.localStorage.getItem(checklistStorageKey) || "[]"));
    } catch {
      return new Set();
    }
  });
  const [openInfoSections, setOpenInfoSections] = useState<Set<string>>(
    () => new Set(["core", "seller", "mlc"])
  );
  const [infoValues, setInfoValues] = useState<Record<string, string>>({});
  const [savingInfoKey, setSavingInfoKey] = useState<string | null>(null);

  // Top 25 pin state. Seed from the board's mapped flag (deal.primary), then
  // reconcile against the authoritative extraToggles once the deal context loads.
  const [pinnedTop25, setPinnedTop25] = useState<boolean>(Boolean(deal.primary));
  const [savingPin, setSavingPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const persisted = isPersistedDealId(deal.id);

  // Real per-deal context from the backend (province guide, per-stage province
  // documents, conditional docs). Falls back to seed data when a deal has no
  // saved file yet (demo/placeholder cards), so this never regresses.
  const [ctx, setCtx] = useState<DealContext | null>(null);
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

  const refetch = useCallback(async () => {
    if (!deal.id) return;
    const next = await api.getDealContext(deal.id);
    setCtx(next);
  }, [deal.id]);

  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      if (!persisted || busy) return;
      setBusy(true);
      setActionError(null);
      try {
        await fn();
        await refetch();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Action failed");
      } finally {
        setBusy(false);
      }
    },
    [persisted, busy, refetch],
  );

  const handleAdvance = useCallback(
    (force = false) => runAction(() => api.advanceDeal(deal.id, force)),
    [runAction, deal.id],
  );

  const guide = ctx?.provinceGuide ?? null;
  const provinceLabel =
    guide?.provinceLabel || (ctx?.deal?.province ?? "").toUpperCase() || "VANCOUVER";
  // Real province documents for a stage label like "S8" -> stageDocuments[8].
  const realStageDocs = (stageLabel: string) => {
    const n = Number((stageLabel || "").replace(/[^0-9]/g, ""));
    return ctx?.stageDocuments?.stages?.[String(n)] ?? [];
  };

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
      case "core.tenureTitleType": return stringValue(extra.tenureTitleType);
      case "core.pid": return stringValue(extra.pid);
      case "core.rollFolioNumber": return stringValue(extra.rollFolioNumber || extra.folioNumber || extra.rollNumber);
      case "core.listingDriveFolderLink": return stringValue(extra.listingDriveFolderLink || extra.driveFolderUrl || extra.driveFolderLink);
      case "core.skySlopeFileLink": return stringValue(extra.skySlopeFileLink || extra.skyslopeFileLink);
      case "core.matrixXposureDraftLink": return stringValue(extra.matrixXposureDraftLink || extra.matrixDraftLink || extra.xposureDraftLink);
      case "core.liveListingUrl": return stringValue(extra.liveListingUrl || extra.mlsUrl);
      case "core.landingPageUrl": return stringValue(extra.landingPageUrl || extra.landingUrl);
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
      default: return saved;
    }
  };

  const infoFieldValue = (key: string) => infoValues[key] ?? autoInfoValue(key);
  const landingUrl = (infoFieldValue("mlc.landingPageUrl") || infoFieldValue("core.landingPageUrl") || "").trim();
  const hasCmaReport = (ctx?.attachments ?? []).some((a) => a.kind === "cma_report");
  const openCmaPdf = () => {
    const sessionWindow = window as Window & { __ELEVATE_SESSION_TOKEN__?: string };
    const token = sessionWindow.__ELEVATE_SESSION_TOKEN__ || "";
    const opened = window.open(
      "/api/admin/deals/" + deal.id + "/cma-pdf?token=" + encodeURIComponent(token),
      "_blank",
      "noopener,noreferrer",
    );
    if (opened) opened.opener = null;
  };
  // Master document tray: what we HAVE (attachments, deduped by kind) + what's MISSING at the current stage
  const humanizeKind = (k: string) =>
    k.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const haveDocs = Array.from(
    new Map((ctx?.attachments ?? []).map((a) => [a.kind, a])).values()
  );
  const trayMissingDocs = ctx?.dealFlow?.gate?.missingDocs ?? [];
  const trayTotal = haveDocs.length + trayMissingDocs.length;
  const filledCount = (section: InfoSectionDef) =>
    section.fields.filter((field) => infoFieldValue(field.key).trim()).length;
  const saveInfoField = async (key: string, value: string) => {
    setSavingInfoKey(key);
    try {
      await api.setAdminDealToggle(deal.id, key, value.trim() || null);
    } finally {
      setSavingInfoKey(null);
    }
  };
  // Reconcile pin state from authoritative toggles once the deal context loads.
  useEffect(() => {
    if (!contextDeal) return;
    setPinnedTop25(extra.pinnedTop25 === true || extra.top25 === true);
  }, [contextDeal]);

  const toggleTop25 = async () => {
    if (savingPin) return;
    const next = !pinnedTop25;
    setSavingPin(true);
    setPinnedTop25(next); // optimistic
    try {
      await api.setAdminDealToggle(deal.id, "pinnedTop25", next);
      onChanged?.(); // reload board so the card moves in/out of Top 25
    } catch {
      setPinnedTop25(!next); // revert on failure
    } finally {
      setSavingPin(false);
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
  const itemKey = (phaseId: string, item: string, idx: number) => `${phaseId}:${idx}:${item}`;

  useEffect(() => {
    window.localStorage.setItem(checklistStorageKey, JSON.stringify(Array.from(checkedItems)));
  }, [checkedItems, checklistStorageKey]);

  const toggleChecklistItem = (phaseId: string, item: string, idx: number) => {
    const key = itemKey(phaseId, item, idx);
    setCheckedItems((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const togglePhase = (id: string) =>
    setOpenPhases((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  // Alias icons to match original variable names
  const Calendar  = Clock;
  const FileTxt   = FileText;
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
          <h2 className="abm-title">{deal.addr}</h2>
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
              {contextDeal.depositAmount != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Deposit</span>
                  <span className="v b">{fmtMoney(contextDeal.depositAmount)}</span>
                </div>
              )}
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
          <button
            className="abm-btn primary"
            type="button"
            disabled={!persisted || busy}
            onClick={() => void handleAdvance(false)}
          >
            {busy ? "Working..." : "Advance phase"}
          </button>
          <button
            className="abm-btn ghost"
            type="button"
            disabled={!persisted || busy}
            onClick={() => void handleAdvance(true)}
          >
            Force advance
          </button>
          <button
            className={"abm-btn top25-toggle" + (pinnedTop25 ? " active" : "")}
            type="button"
            disabled={savingPin}
            onClick={toggleTop25}
          >
            {pinnedTop25 ? "✓ In Top 25" : "+ Top 25"}
          </button>
          <button className="abm-btn collapse-sale" type="button" disabled title="Collapse wiring is not ported yet">
            Collapse Sale
          </button>
          {!isBuyer && (
            <button className="abm-btn cancel-relist" type="button" disabled title="Relist wiring is not ported yet">
              Cancel / Relist
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
          {!isBuyer && (
            <button
              className={"abm-btn cma-pdf" + (hasCmaReport ? "" : " empty")}
              type="button"
              disabled={!hasCmaReport}
              onClick={hasCmaReport ? openCmaPdf : undefined}
            >
              {hasCmaReport ? "CMA PDF ↗" : "CMA PDF — pending"}
            </button>
          )}
          {actionError && (
            <span className="abm-actionbar-error" role="status">
              {actionError}
            </span>
          )}
        </div>

        <div className="ab-modal-scroll">
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
                  {INFO_SECTIONS.filter((section) => {
                    if (isBuyer && section.id !== "core") return false;
                    if (section.minListingPhase) {
                      const minPhase = pipeline.find((p) => p.id === section.minListingPhase);
                      if (!minPhase || currentIdx < pipeline.indexOf(minPhase)) return false;
                    }
                    return true;
                  }).map((section) => {
                    const open = openInfoSections.has(section.id);
                    const done = filledCount(section);
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
                          <span className="abm-phase-count mono">{done}/{section.fields.length}</span>
                          <ChevDown className={"abm-phase-chev" + (open ? " open" : "")} />
                        </button>
                        {open && (
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
                </div>

                {/* Master document tray — one rollup of every doc, have vs missing */}
                <div className="abm-section abm-doctray">
                  <div className="abm-section-row">
                    <span className="abm-section-label mono">DOCUMENT CHECKLIST</span>
                    <span className="abm-doctray-prog mono">
                      {haveDocs.length}/{trayTotal} on file
                    </span>
                  </div>
                  <div className="abm-doctray-bar">
                    <span
                      className="abm-doctray-fill"
                      style={{ width: trayTotal ? `${Math.round((haveDocs.length / trayTotal) * 100)}%` : "0%" }}
                    />
                  </div>
                  <div className="abm-doctray-grid">
                    {haveDocs.map((d) => (
                      <div className="abm-doc-chip have" key={d.id} title={d.summary || d.kind}>
                        <span className="abm-doc-box" />
                        <span>{humanizeKind(d.kind)}</span>
                      </div>
                    ))}
                    {trayMissingDocs.map((d) => (
                      <div className="abm-doc-chip missing" key={"m-" + d.kind}>
                        <span className="abm-doc-box" />
                        <span>{d.label}</span>
                      </div>
                    ))}
                  </div>
                </div>

              </section>
            </div>

            {/* ─── Right column: Phase accordion list ─── */}
            <div className="abm-col abm-col-right">
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
                  checkedItems.has(itemKey(p.id, item, itemIdx))
                ).length;
                const done    = detail.checklist.length > 0 && checkedCount === detail.checklist.length;
                const current = idx === currentIdx;
                const open    = openPhases.has(p.id);
                // Prefer this province's real per-stage documents (from its
                // transaction guide); fall back to seed docs when unavailable.
                const provDocs = realStageDocs(p.stage);
                const docsToShow: [string, string][] = provDocs.length
                  ? provDocs.map((d) => [d.code, d.name] as [string, string])
                  : detail.documents;

                return (
                  <div
                    key={p.id}
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
                            const checked = checkedItems.has(itemKey(p.id, c, i));
                            return (
                              <li key={i}>
                                <button
                                  type="button"
                                  className="abm-check-row"
                                  onClick={() => toggleChecklistItem(p.id, c, i)}
                                  aria-pressed={checked}
                                >
                                  <span className="abm-check-box" data-checked={checked ? "true" : "false"} />
                                  <span className={checked ? "done" : ""}>{c}</span>
                                </button>
                              </li>
                            );
                          })}
                        </ul>

                        {docsToShow.length > 0 && (
                          <div className="abm-province">
                            <div className="abm-section-label mono">
                              PROVINCE DOCUMENTS &middot; {docsToShow.length}
                            </div>
                            <ul className="abm-doc-list">
                              {docsToShow.map(([key, name], i) => (
                                <li key={i}>
                                  <FileTxt />
                                  <strong className="mono">{key}</strong>
                                  <span className="dim">&middot;</span>
                                  <span>{name}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>
    </div>,
    document.body,
  );
}
