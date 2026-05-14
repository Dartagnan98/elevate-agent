import {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  Clock,
  Database as DatabaseIcon,
  FileCheck2,
  FileText,
  Flame,
  Home,
  Loader2,
  Mail,
  Phone,
  Square as SquareIcon,
  Plus,
  RefreshCw,
  ShieldCheck,
  Target,
  Users,
  X as CloseIcon,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminActionRun,
  AdminContact,
  AdminDeal,
  AdminDealCreateRequest,
  AdminProvinceGuideCoverage,
  AdminSetupSnapshot,
  DealAttachmentCreateRequest,
  DealContactCreateRequest,
  DealContext,
  ProvinceStageDocumentItem,
  SourceInboxProfileVerifier,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, isoTimeAgo } from "@/lib/utils";
import {
  adminSetupDraftFromSnapshot,
  adminSetupPayloadFromDraft,
  type AdminSetupDraft,
} from "@/pages/real-estate-hub/admin-setup";
import { heatVariant } from "@/pages/real-estate-hub/utils";
import { verifierSummary } from "@/pages/real-estate-hub/profile-workflow";
import {
  ActionBoard,
  AdminRunDecisionRow,
  adminRunStatusVariant,
  HubShell,
  RecentSessions,
  TimedTasks,
  useHubHeader,
  useRealEstateHubData,
  WorkflowStrip,
  type AdminRunBusy,
} from "@/pages/real-estate-hub/_shared";
import {
  ADMIN_WORKFLOW_KEYWORDS,
  APPROVAL_CUE_KEYWORDS,
  approvalCueActions,
  approvalCueCount,
  jobAction,
  jobMatches,
  sessionAction,
  sessionMatches,
} from "@/pages/real-estate-hub/_shared/page-helpers";

const DEFAULT_ADMIN_AUTOMATIONS = [
  {
    name: "Gmail Doc Router",
    schedule: "0 9 * * 1",
    skill: "gmail-doc-router",
    skills: ["gmail-doc-router"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, match listing documents to active Elevate deals with deal-matcher, file documents to the correct Drive folder, and write artifacts/checklist evidence back to the deal with admin-result-writer. Do not send messages.",
  },
  {
    name: "Seller Update",
    schedule: "0 16 * * 1-5",
    skill: "seller-update",
    skills: ["seller-update"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the seller-update skill. Pull ShowingTime feedback/activity for active listings, match each listing to an Elevate deal, write the digest back to SQLite, and create Gmail seller-update drafts. Never send directly.",
  },
  {
    name: "Market Stats Watcher",
    schedule: "0 7 * * 1",
    skill: "market-stats-watcher",
    skills: ["market-stats-watcher"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the market-stats-watcher skill. Pull fresh market-stat emails and route useful market context into the real estate knowledge/admin workflow. Do not send messages.",
  },
];

const ADMIN_STAGE_NUMBERS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

type AdminSide = "listing" | "buyer";
type AdminStageNumber = (typeof ADMIN_STAGE_NUMBERS)[number];

const CANADIAN_PROVINCES: Array<{ code: string; label: string }> = [
  { code: "AB", label: "Alberta" },
  { code: "BC", label: "British Columbia" },
  { code: "MB", label: "Manitoba" },
  { code: "NB", label: "New Brunswick" },
  { code: "NL", label: "Newfoundland and Labrador" },
  { code: "NS", label: "Nova Scotia" },
  { code: "NT", label: "Northwest Territories" },
  { code: "NU", label: "Nunavut" },
  { code: "ON", label: "Ontario" },
  { code: "PEI", label: "Prince Edward Island" },
  { code: "QC", label: "Quebec" },
  { code: "SK", label: "Saskatchewan" },
  { code: "YK", label: "Yukon" },
];

const PROVINCE_LABEL_BY_CODE = new Map(CANADIAN_PROVINCES.map(({ code, label }) => [code, label]));

type AdminStageLabel = {
  title: string;
  subtitle: string;
};

type AdminColumn = {
  stage: AdminStageNumber;
  stageNumber: string;
  stageLabel?: string;
  labels: Record<AdminSide, AdminStageLabel>;
};

type AdminChecklistItem = { id: string; label: string };

type AdminPhaseAutomationInfo = {
  agents: string[];
  background: string[];
  moveSignal: string;
  approvalGate?: string;
};

type AdminEnumField =
  | "signing_authority"
  | "fintrac_form_type"
  | "listing_track"
  | "property_subtype"
  | "estate_status"
  | "transaction_type"
  | "listing_type";

type AdminToggleField =
  | "pep"
  | "tenanted"
  | "poa_signing"
  | "corporate"
  | "has_suite"
  | "multiple_offers"
  | "family_member"
  | "dual_rep"
  | "unrepresented_other_side"
  | "lockbox"
  | "delayed_offer"
  | "sale_of_buyers_property";

type AdminConditionField = AdminEnumField | AdminToggleField;
type AdminConditionValue = string | boolean | null;
type AdminCompletedByStage = Partial<Record<AdminStageNumber, Record<string, boolean>>>;

type AdminSourceContext = {
  profileName?: string;
  latestText?: string;
  latestAt?: string;
  heatLabel?: string;
  heatScore?: number;
  sources: string[];
  channels: string[];
  contactIds: string[];
  conversationIds: string[];
  verifiers: SourceInboxProfileVerifier[];
  rejectedContactId?: string;
};

type AdminCard = {
  id: string;
  side: AdminSide;
  stage: AdminStageNumber;
  client: string;
  contactInitials: string;
  property?: string;
  nextLabel?: string;
  nextDate?: string;
  daysOut?: number;
  pinnedTop25?: boolean;
  completedByStage?: AdminCompletedByStage;
  conditions?: Partial<Record<AdminConditionField, AdminConditionValue>>;
  sourceContext?: AdminSourceContext;
};

const ADMIN_SIDE_LABELS: Record<AdminSide, { title: string; description: string }> = {
  listing: {
    title: "Listing Admin",
    description: "CMA through closed file",
  },
  buyer: {
    title: "Buyer Admin",
    description: "Walkthrough through one-week follow-up",
  },
};

const ADMIN_COLUMNS: AdminColumn[] = [
  {
    stage: 0,
    stageNumber: "S0",
    stageLabel: "Commitment",
    labels: {
      listing: { title: "CMA / Prospect", subtitle: "Appointment + valuation" },
      buyer: { title: "Intake", subtitle: "Profile + budget" },
    },
  },
  {
    stage: 1,
    stageNumber: "S1",
    stageLabel: "Intake",
    labels: {
      listing: { title: "Listing Intake", subtitle: "Collect info for listing contract" },
      buyer: { title: "Search Setup", subtitle: "Criteria + MLS" },
    },
  },
  {
    stage: 2,
    stageNumber: "S2",
    stageLabel: "Docs",
    labels: {
      listing: { title: "Listing Contract / Documents", subtitle: "Create docs + signing" },
      buyer: { title: "Tours", subtitle: "Route + notes" },
    },
  },
  {
    stage: 3,
    stageNumber: "S3",
    stageLabel: "Photos",
    labels: {
      listing: { title: "Photos Ready", subtitle: "Photo capture + review" },
      buyer: { title: "Follow-Up", subtitle: "Feedback + fit" },
    },
  },
  {
    stage: 4,
    stageNumber: "S4",
    stageLabel: "MLS",
    labels: {
      listing: { title: "MLS Entry", subtitle: "Listing build + launch prep" },
      buyer: { title: "Offer Prep", subtitle: "Comps + offer paperwork" },
    },
  },
  {
    stage: 5,
    stageNumber: "S5",
    stageLabel: "Live",
    labels: {
      listing: { title: "Listing Live / Marketing", subtitle: "MLS live + seller updates" },
      buyer: { title: "Accepted", subtitle: "Lender + docs" },
    },
  },
  {
    stage: 6,
    stageNumber: "S6",
    stageLabel: "Contract",
    labels: {
      listing: { title: "Accepted Offer", subtitle: "Contract review + dates" },
      buyer: { title: "Conditions", subtitle: "Inspection + property review" },
    },
  },
  {
    stage: 7,
    stageNumber: "S7",
    stageLabel: "Conditions",
    labels: {
      listing: { title: "Condition Removal", subtitle: "Conditions + lawyer package" },
      buyer: { title: "Conditions Removed", subtitle: "Deposit + dates" },
    },
  },
  {
    stage: 8,
    stageNumber: "S8",
    stageLabel: "Closing",
    labels: {
      listing: { title: "Closing", subtitle: "Lawyer / conveyance + possession" },
      buyer: { title: "Closing", subtitle: "Lawyer + walkthrough" },
    },
  },
  {
    stage: 9,
    stageNumber: "S9",
    stageLabel: "Closed",
    labels: {
      listing: { title: "Closed", subtitle: "Archive + nurture" },
      buyer: { title: "Possession", subtitle: "Gift + follow-up" },
    },
  },
];

const ADMIN_PHASE_AUTOMATIONS: Record<AdminSide, Record<AdminStageNumber, AdminPhaseAutomationInfo>> = {
  listing: {
    0: {
      agents: ["seller-package", "cma"],
      background: [],
      moveSignal: "CMA ready + seller package sent",
      approvalGate: "approve package/draft",
    },
    1: {
      agents: ["mlc", "deal-matcher"],
      background: [],
      moveSignal: "listing intake complete",
      approvalGate: "confirm price + launch plan",
    },
    2: {
      agents: ["mlc", "signing-package", "skyslope-sync"],
      background: ["gmail-doc-router"],
      moveSignal: "signed listing contract + docs verified",
      approvalGate: "approve signing/docs",
    },
    3: {
      agents: ["photo-cleanup"],
      background: [],
      moveSignal: "photos approved",
      approvalGate: "human photo approval",
    },
    4: {
      agents: ["property-lookup", "listing-build"],
      background: [],
      moveSignal: "MLS package approved",
      approvalGate: "approve MLS copy/package",
    },
    5: {
      agents: ["marketing"],
      background: ["seller-update"],
      moveSignal: "offer accepted",
      approvalGate: "approve outgoing drafts",
    },
    6: {
      agents: ["offer-review"],
      background: ["gmail-doc-router"],
      moveSignal: "accepted-offer dates verified",
      approvalGate: "review offer terms",
    },
    7: {
      agents: ["subject-removal", "signing-package"],
      background: ["gmail-doc-router"],
      moveSignal: "conditions removed + deposit verified",
      approvalGate: "confirm condition removal",
    },
    8: {
      agents: ["closing-admin"],
      background: ["gmail-doc-router"],
      moveSignal: "closing package complete",
      approvalGate: "confirm closing package",
    },
    9: {
      agents: ["skyslope-sync", "marketing"],
      background: [],
      moveSignal: "file closed + nurture queued",
      approvalGate: "approve closeout",
    },
  },
  buyer: {
    0: { agents: [], background: [], moveSignal: "profile verified" },
    1: { agents: [], background: [], moveSignal: "search criteria ready" },
    2: { agents: [], background: [], moveSignal: "showing notes complete" },
    3: { agents: [], background: [], moveSignal: "follow-up complete" },
    4: { agents: [], background: [], moveSignal: "offer package ready" },
    5: { agents: [], background: [], moveSignal: "accepted-offer checklist complete" },
    6: { agents: [], background: [], moveSignal: "conditions tracked" },
    7: { agents: [], background: [], moveSignal: "conditions removed" },
    8: { agents: [], background: [], moveSignal: "closing checklist complete" },
    9: { agents: [], background: [], moveSignal: "possession follow-up queued" },
  },
};

// Per-stage checklist catalog. Card state (completedByStage) overlays this.
const ADMIN_STAGE_CHECKLISTS: Record<AdminSide, Record<AdminStageNumber, AdminChecklistItem[]>> = {
  listing: {
    0: [
    { id: "draft-cma-followup", label: "Draft CMA follow-up message" },
    { id: "pricing-recap", label: "Send pricing recap to seller" },
    { id: "missing-info-list", label: "Identify info needed before listing paperwork" },
    ],
    1: [
    { id: "workflow_stage_1_complete", label: "Listing details verified" },
    ],
    2: [
    { id: "workflow_title_ordered", label: "Title ordered" },
    { id: "workflow_sign_ordered", label: "Sign ordered" },
    { id: "workflow_stage_2_complete", label: "Signed docs verified" },
    ],
    3: [
    { id: "workflow_photos_in_drive", label: "Photos in Drive" },
    { id: "workflow_jeff_photo_review", label: "Photo review complete" },
    { id: "workflow_stage_3_complete", label: "Photos approved for listing" },
    ],
    4: [
    { id: "workflow_evalue_bc_age_verified", label: "Property valuation age verified" },
    { id: "workflow_listing_description_approved", label: "Listing description approved" },
    { id: "workflow_feature_sheet_uploaded", label: "Feature sheet uploaded" },
    { id: "workflow_ai_edited_photos_labelled", label: "AI-edited photos labelled" },
    { id: "workflow_stage_4_complete", label: "MLS package approved" },
    ],
    5: [
    { id: "workflow_just_listed_blast_sent", label: "Just listed blast sent" },
    { id: "workflow_social_posts_published", label: "Social posts published" },
    { id: "workflow_flodesk_mailout_sent", label: "Flodesk mailout sent" },
    { id: "workflow_lofty_text_blast_sent", label: "Lofty text blast sent" },
    { id: "workflow_stage_5_complete", label: "Live marketing checklist complete" },
    ],
    6: [
    { id: "workflow_within_24hrs_contract_reviewed", label: "Contract reviewed within 24 hours" },
    { id: "workflow_email_buyer_accepted_offer_checklist_sent", label: "Accepted-offer checklist email sent" },
    { id: "workflow_fintrac_drivers_occupation_employer_captured", label: "FINTRAC details captured" },
    { id: "workflow_calendar_dates_added", label: "Calendar dates added" },
    { id: "workflow_moving_checklist_sent", label: "Moving checklist sent" },
    { id: "workflow_stage_6_complete", label: "Accepted-offer admin verified" },
    ],
    7: [
    { id: "workflow_subject_removal_form_sent", label: "Condition removal / waiver sent" },
    { id: "workflow_title_charges_verified", label: "Title charges verified" },
    { id: "workflow_bir_pds_received", label: "Property disclosure docs received" },
    { id: "workflow_lawyer_info_requested", label: "Lawyer info requested" },
    { id: "workflow_stage_7_complete", label: "Conditions removed / waived" },
    ],
    8: [
    { id: "workflow_conveyancer_package_sent", label: "Lawyer / conveyancer package sent" },
    { id: "workflow_down_payment_to_trust", label: "Down payment to trust" },
    { id: "workflow_mortgage_instructions_received", label: "Mortgage instructions received" },
    { id: "workflow_insurance_binder_confirmed", label: "Insurance binder confirmed" },
    { id: "workflow_client_signed_lawyer", label: "Client signed at lawyer" },
    { id: "workflow_funds_released", label: "Funds released" },
    { id: "workflow_stage_8_complete", label: "Closing admin verified" },
    ],
    9: [
    { id: "workflow_commission_submitted", label: "Commission submitted" },
    { id: "workflow_skyslope_deal_closed", label: "SkySlope deal closed" },
    { id: "workflow_sold_update_sent", label: "Sold update sent" },
    { id: "workflow_closing_gift_sent", label: "Closing gift sent" },
    { id: "workflow_review_requested", label: "Review requested" },
    { id: "workflow_stage_9_complete", label: "Closed file archived" },
    ],
  },
  buyer: {
    0: [
    { id: "buyer-profile", label: "Buyer profile (budget, financing, areas, beds, must-haves)" },
    { id: "search-criteria", label: "MLS / Lofty search filter built" },
    ],
    1: [
    { id: "shortlist", label: "Property shortlist + ranked-fit" },
    { id: "showing-route", label: "Showing route + itinerary" },
    { id: "preview-notes", label: "Preview notes per property" },
    ],
    2: [
    { id: "followup-draft", label: "Per-showing follow-up draft" },
    { id: "feedback-summary", label: "Feedback summary (liked / disliked / dealbreakers)" },
    ],
    3: [
    { id: "criteria-update", label: "Buyer criteria updated" },
    { id: "comp-pull", label: "Comparable sales pulled" },
    { id: "cps-checklist", label: "Offer document checklist + strategy" },
    ],
    4: [
    { id: "lender-paperwork", label: "Lender paperwork sent" },
    { id: "accepted-offer-checklist", label: "Accepted-offer checklist run" },
    { id: "doc-list", label: "Doc list (offer, addenda, disclosures, deposit receipt)" },
    ],
    5: [
    { id: "inspection-booked", label: "Inspection booked" },
    { id: "insurance-deadline", label: "Insurance deadline tracked" },
    { id: "strata-review", label: "Strata / condo review (if applicable)" },
    ],
    6: [
    { id: "deposit-due", label: "Deposit due date tracked" },
    { id: "lawyer-info", label: "Lawyer / conveyancer info captured" },
    { id: "skyslope-docs", label: "SkySlope missing-doc list cleared" },
    ],
    7: [
    { id: "subjects-removed", label: "All conditions removed / waived" },
    { id: "deposit-received", label: "Deposit received" },
    { id: "completion-locked", label: "Completion + possession dates locked" },
    ],
    8: [
    { id: "lawyer-final-docs", label: "Final docs forwarded to lawyer" },
    { id: "completion-checklist", label: "Completion checklist complete" },
    { id: "final-walkthrough", label: "Final walkthrough scheduled" },
    ],
    9: [
    { id: "utility-reminder", label: "Utility / change-of-address reminder sent" },
    { id: "key-handoff", label: "Key handoff coordinated" },
    { id: "closing-gift", label: "Closing gift sent" },
    { id: "thank-you", label: "Thank-you / review / referral drafts queued" },
    { id: "one-week-followup", label: "One-week-after follow-up scheduled" },
    { id: "anniversary", label: "Anniversary reminder added" },
    ],
  },
};

const ADMIN_ENUM_CONDITIONS: Array<{
  field: AdminEnumField;
  label: string;
  options: Array<{ value: string; label: string }>;
}> = [
  {
    field: "signing_authority",
    label: "Signing authority",
    options: [
      { value: "seller", label: "Seller" },
      { value: "buyer", label: "Buyer" },
      { value: "both", label: "Both clients" },
      { value: "poa", label: "Power of attorney" },
      { value: "corporate", label: "Corporate signer" },
      { value: "estate_executor", label: "Estate executor" },
    ],
  },
  {
    field: "fintrac_form_type",
    label: "FINTRAC form type",
    options: [
      { value: "individual", label: "Individual" },
      { value: "corporation", label: "Corporation" },
      { value: "estate", label: "Estate" },
      { value: "poa", label: "Power of attorney" },
      { value: "third_party", label: "Third party" },
    ],
  },
  {
    field: "listing_track",
    label: "Listing track",
    options: [
      { value: "standard", label: "Standard" },
      { value: "rush", label: "Rush" },
      { value: "pre_market", label: "Pre-market" },
      { value: "relist", label: "Relist" },
    ],
  },
  {
    field: "property_subtype",
    label: "Property subtype",
    options: [
      { value: "detached", label: "Detached" },
      { value: "townhouse", label: "Townhouse" },
      { value: "condo", label: "Condo" },
      { value: "strata", label: "Strata" },
      { value: "acreage", label: "Acreage" },
      { value: "land", label: "Land" },
      { value: "multifamily", label: "Multifamily" },
    ],
  },
  {
    field: "estate_status",
    label: "Estate status",
    options: [
      { value: "none", label: "None" },
      { value: "estate_sale", label: "Estate sale" },
      { value: "probate_pending", label: "Probate pending" },
      { value: "probate_granted", label: "Probate granted" },
    ],
  },
  {
    field: "transaction_type",
    label: "Transaction type",
    options: [
      { value: "residential", label: "Residential" },
      { value: "commercial", label: "Commercial" },
      { value: "referral", label: "Referral" },
      { value: "assignment", label: "Assignment" },
    ],
  },
  {
    field: "listing_type",
    label: "Listing type",
    options: [
      { value: "mls", label: "MLS" },
      { value: "exclusive", label: "Exclusive" },
      { value: "coming_soon", label: "Coming soon" },
      { value: "mere_posting", label: "Mere posting" },
    ],
  },
];

const ADMIN_TOGGLE_CONDITIONS: Array<{ field: AdminToggleField; label: string }> = [
  { field: "pep", label: "PEP" },
  { field: "tenanted", label: "Tenanted" },
  { field: "poa_signing", label: "POA signing" },
  { field: "corporate", label: "Corporate" },
  { field: "has_suite", label: "Has suite" },
  { field: "multiple_offers", label: "Multiple offers" },
  { field: "family_member", label: "Family member" },
  { field: "dual_rep", label: "Dual representation" },
  { field: "unrepresented_other_side", label: "Unrepresented other side" },
  { field: "lockbox", label: "Lockbox" },
  { field: "delayed_offer", label: "Delayed offer" },
  { field: "sale_of_buyers_property", label: "Sale of buyer's property" },
];

const ADMIN_CONDITION_FIELD_SET = new Set<string>([
  ...ADMIN_ENUM_CONDITIONS.map((item) => item.field),
  ...ADMIN_TOGGLE_CONDITIONS.map((item) => item.field),
]);

const ADMIN_DEAL_CONDITION_API_KEYS: Record<AdminConditionField, keyof AdminDeal> = {
  signing_authority: "signingAuthority",
  fintrac_form_type: "fintracFormType",
  listing_track: "listingTrack",
  property_subtype: "propertySubtype",
  estate_status: "estateStatus",
  transaction_type: "transactionType",
  listing_type: "listingType",
  pep: "pep",
  tenanted: "tenanted",
  poa_signing: "poaSigning",
  corporate: "corporate",
  has_suite: "hasSuite",
  multiple_offers: "multipleOffers",
  family_member: "familyMember",
  dual_rep: "dualRep",
  unrepresented_other_side: "unrepresentedOtherSide",
  lockbox: "lockbox",
  delayed_offer: "delayedOffer",
  sale_of_buyers_property: "saleOfBuyersProperty",
};

function isAdminConditionField(field: string): field is AdminConditionField {
  return ADMIN_CONDITION_FIELD_SET.has(field);
}

function isAdminSide(value: unknown): value is AdminSide {
  return value === "listing" || value === "buyer";
}

function toAdminStage(value: unknown): AdminStageNumber {
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && ADMIN_STAGE_NUMBERS.includes(numeric as AdminStageNumber)) {
    return numeric as AdminStageNumber;
  }
  return 0;
}

function adminStageDefinition(stage: AdminStageNumber): AdminColumn {
  return ADMIN_COLUMNS.find((column) => column.stage === stage) ?? ADMIN_COLUMNS[0];
}

function adminStageLabel(side: AdminSide, stage: AdminStageNumber): AdminStageLabel {
  return adminStageDefinition(stage).labels[side];
}

function adminStageChecklist(side: AdminSide, stage: AdminStageNumber): AdminChecklistItem[] {
  return ADMIN_STAGE_CHECKLISTS[side][stage];
}

function adminPhaseAutomation(side: AdminSide, stage: AdminStageNumber): AdminPhaseAutomationInfo {
  return ADMIN_PHASE_AUTOMATIONS[side][stage];
}

function adminNextStage(card: AdminCard): AdminStageNumber | null {
  if (card.stage >= 9) return null;
  return (card.stage + 1) as AdminStageNumber;
}

function getStageProgress(card: AdminCard, stage: AdminStageNumber): { done: number; total: number; nextItem?: string } {
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  let done = 0;
  let nextItem: string | undefined;
  for (const item of items) {
    if (completed[item.id]) done++;
    else if (!nextItem) nextItem = item.label;
  }
  return { done, total: items.length, nextItem };
}

function getCardProgress(card: AdminCard): { done: number; total: number; nextItem?: string } {
  return getStageProgress(card, card.stage);
}

function adminChecklistStageForItem(side: AdminSide, itemId: string): AdminStageNumber | null {
  for (const stage of ADMIN_STAGE_NUMBERS) {
    if (adminStageChecklist(side, stage).some((item) => item.id === itemId)) {
      return stage;
    }
  }
  return null;
}

function initialsFromTitle(title: string): string {
  const words = title
    .replace(/[^a-z0-9\s&]/gi, " ")
    .split(/\s+/)
    .filter(Boolean);
  const initials = words
    .slice(0, 2)
    .map((word) => word.slice(0, 1).toUpperCase())
    .join("");
  return initials || "AD";
}

function adminConditionValueFromDeal(deal: AdminDeal, field: AdminConditionField): AdminConditionValue {
  const value = deal[ADMIN_DEAL_CONDITION_API_KEYS[field]];
  if (value === undefined) return null;
  if (typeof value === "string" || typeof value === "boolean" || value == null) {
    return value;
  }
  return String(value);
}

function adminConditionsFromDeal(deal: AdminDeal): Partial<Record<AdminConditionField, AdminConditionValue>> {
  const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
  for (const field of ADMIN_CONDITION_FIELD_SET) {
    if (isAdminConditionField(field)) {
      conditions[field] = adminConditionValueFromDeal(deal, field);
    }
  }
  return conditions;
}

function completedStagesFromDeal(deal: AdminDeal, side: AdminSide): AdminCompletedByStage {
  const completed: AdminCompletedByStage = {};
  const extraToggles = deal.extraToggles ?? {};
  for (const stage of ADMIN_STAGE_NUMBERS) {
    const stageCompleted: Record<string, boolean> = {};
    for (const item of adminStageChecklist(side, stage)) {
      if (extraToggles[item.id] === true) {
        stageCompleted[item.id] = true;
      }
    }
    if (Object.keys(stageCompleted).length > 0) {
      completed[stage] = stageCompleted;
    }
  }
  return completed;
}

function adminStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean)
    .slice(0, 6);
}

function adminStringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function adminNumberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function adminVerifierList(value: unknown): SourceInboxProfileVerifier[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const kind = adminStringValue(record.kind);
      const verifierValue = adminStringValue(record.value);
      const key = adminStringValue(record.key);
      if (!kind || !verifierValue || !key) return null;
      return { kind, value: verifierValue, key };
    })
    .filter((item): item is SourceInboxProfileVerifier => item !== null)
    .slice(0, 6);
}

function adminSourceContextFromDeal(deal: AdminDeal): AdminSourceContext | undefined {
  const extra = deal.extraToggles ?? {};
  if (!adminStringValue(extra.sourceProfileId) && extra.workflow !== "cma") return undefined;
  return {
    profileName: adminStringValue(extra.profileDisplayName) ?? adminStringValue(extra.sourceProfileName),
    latestText: adminStringValue(extra.profileLatestText) ?? adminStringValue(extra.sourceLatestText),
    latestAt: adminStringValue(extra.profileLatestAt) ?? adminStringValue(extra.sourceLatestAt),
    heatLabel: adminStringValue(extra.profileHeatLabel) ?? adminStringValue(extra.sourceHeatLabel),
    heatScore: adminNumberValue(extra.profileHeatScore) ?? adminNumberValue(extra.sourceHeatScore),
    sources: adminStringList(extra.profileSources).length
      ? adminStringList(extra.profileSources)
      : adminStringList(extra.sourceLabels),
    channels: adminStringList(extra.profileChannels).length
      ? adminStringList(extra.profileChannels)
      : adminStringList(extra.sourceChannels),
    contactIds: adminStringList(extra.profileContactIds).length
      ? adminStringList(extra.profileContactIds)
      : adminStringList(extra.sourceContactIds),
    conversationIds: adminStringList(extra.profileConversationIds).length
      ? adminStringList(extra.profileConversationIds)
      : adminStringList(extra.sourceConversationIds),
    verifiers: adminVerifierList(extra.profileVerifiers).length
      ? adminVerifierList(extra.profileVerifiers)
      : adminVerifierList(extra.sourceVerifiers),
    rejectedContactId: adminStringValue(extra.sourcePrimaryContactIdRejected),
  };
}

function adminCardFromDeal(deal: AdminDeal): AdminCard {
  const side = isAdminSide(deal.side) ? deal.side : "listing";
  const stage = toAdminStage(deal.currentStage);
  const stageLabel = adminStageLabel(side, stage);
  const property = deal.listingAddress || (deal.province ? `${deal.province} deal` : undefined);
  return {
    id: deal.id,
    side,
    stage,
    client: deal.title || "Untitled deal",
    contactInitials: initialsFromTitle(deal.title || "Admin deal"),
    property,
    nextLabel: stageLabel.title,
    pinnedTop25: deal.extraToggles?.pinnedTop25 === true || deal.extraToggles?.top25 === true,
    completedByStage: completedStagesFromDeal(deal, side),
    conditions: adminConditionsFromDeal(deal),
    sourceContext: adminSourceContextFromDeal(deal),
  };
}

function applyLocalDealField(card: AdminCard, field: string, value: AdminConditionValue): AdminCard {
  if (isAdminConditionField(field)) {
    return {
      ...card,
      conditions: {
        ...(card.conditions ?? {}),
        [field]: value,
      },
    };
  }

  const stage = adminChecklistStageForItem(card.side, field);
  if (stage == null) return card;

  const currentStageState = card.completedByStage?.[stage] ?? {};
  const nextStageState = { ...currentStageState };
  if (value === true) nextStageState[field] = true;
  else delete nextStageState[field];

  return {
    ...card,
    completedByStage: {
      ...(card.completedByStage ?? {}),
      [stage]: nextStageState,
    },
  };
}

function replaceCardFromDeal(cards: AdminCard[], deal: AdminDeal): AdminCard[] {
  const nextCard = adminCardFromDeal(deal);
  return cards.map((card) => (card.id === nextCard.id ? nextCard : card));
}

function isApiNotFound(error: unknown): boolean {
  return error instanceof Error && /^404\b/.test(error.message);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function useAdminSetup(): {
  setup: AdminSetupSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setSetup: (setup: AdminSetupSnapshot) => void;
} {
  const [setup, setSetup] = useState<AdminSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSetup(await api.getAdminSetup());
    } catch (err) {
      setError(errorMessage(err, "Admin setup failed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { setup, loading, error, refresh, setSetup };
}

function AdminSetupField({
  label,
  value,
  onChange,
  placeholder,
  suggestions,
  listId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  suggestions?: readonly string[];
  listId?: string;
}) {
  const resolvedListId = suggestions && suggestions.length > 0 ? listId : undefined;
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        list={resolvedListId}
        className="h-9 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {resolvedListId && (
        <datalist id={resolvedListId}>
          {suggestions!.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      )}
    </label>
  );
}

const PROVIDER_SUGGESTIONS = {
  email: ["Gmail", "Outlook", "Apple Mail"],
  calendar: ["Google Calendar", "Outlook Calendar", "Apple Calendar"],
  drive: ["Google Drive", "Dropbox", "SharePoint", "OneDrive"],
  crm: ["Lofty", "kvCORE", "BoldTrail", "Follow Up Boss", "Sierra Interactive", "Chime", "HubSpot"],
  mls: ["Matrix", "Paragon", "Xposure", "Stellar MLS", "MLS-Touch", "Realtor.ca"],
  forms: ["WEBForms", "TransactionDesk", "ZipForm", "Authentisign"],
  signing: ["DigiSign", "DocuSign", "Authentisign", "Dotloop", "PandaDoc"],
  compliance: ["SkySlope", "Lone Wolf", "Dotloop", "BrokerWolf"],
  showing: ["ShowingTime", "BrokerBay", "Aligned Showings", "ShowingSmart"],
  photo: ["Nano Banana", "Higgsfield", "BoxBrownie", "Virtual Staging AI"],
  fintrac: ["Fintracker", "Manual FIN# capture", "OneID", "Treefort"],
} as const;

function AdminSetupLaunch({
  setup,
  onSetupUpdated,
}: {
  setup: AdminSetupSnapshot;
  onSetupUpdated: (setup: AdminSetupSnapshot) => void;
}) {
  const [draft, setDraft] = useState<AdminSetupDraft>(() => adminSetupDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [provinceCoverage, setProvinceCoverage] = useState<AdminProvinceGuideCoverage[]>([]);
  const [provinceUnlocked, setProvinceUnlocked] = useState(false);

  const savedProvinceCode = (setup.profile?.province || "").trim().toUpperCase();

  useEffect(() => {
    setDraft(adminSetupDraftFromSnapshot(setup));
  }, [setup]);

  useEffect(() => {
    // Re-lock province when setup snapshot saves a new value.
    setProvinceUnlocked(false);
  }, [savedProvinceCode]);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminProvinceGuides()
      .then((guides) => {
        if (cancelled) return;
        if ("items" in guides) setProvinceCoverage(guides.items);
      })
      .catch(() => {
        if (!cancelled) setProvinceCoverage([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceCoverageByCode = useMemo(
    () => new Map(provinceCoverage.map((item) => [item.province, item])),
    [provinceCoverage],
  );
  const selectedProvinceCoverage = provinceCoverageByCode.get(draft.province.trim().toUpperCase());

  const updateDraft = useCallback(
    (field: keyof AdminSetupDraft, value: string) => {
      setDraft((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const submit = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.missingRequiredKeys.length === 0
          ? "Saved. Verify connections before Admin can start."
          : "Saved. Finish and verify the missing setup items before Admin can start.",
      );
    } catch (err) {
      setError(errorMessage(err, "Save admin setup failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const verify = useCallback(async () => {
    setVerifying(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      const verified = await api.verifyAdminSetup();
      if (verified.missingRequiredKeys.length === 0) {
        const completed = await api.completeAdminSetup();
        onSetupUpdated(completed);
        setSavedMessage("Admin setup is verified and ready.");
      } else {
        onSetupUpdated(verified);
        setSavedMessage("Checked live connectors. Finish the missing setup items before Admin can start.");
      }
    } catch (err) {
      setError(errorMessage(err, "Verify admin setup failed"));
    } finally {
      setVerifying(false);
    }
  }, [draft, onSetupUpdated]);

  const missingLabels = useMemo(() => {
    const labels = new Map(setup.items.map((item) => [item.key, item.label]));
    return setup.missingRequiredKeys.map((key) => labels.get(key) ?? key);
  }, [setup.items, setup.missingRequiredKeys]);
  const readinessBlockers = useMemo(
    () => (setup.readiness ?? []).filter((item) => !item.ready),
    [setup.readiness],
  );
  const verificationWarnings = setup.verificationWarnings ?? [];

  return (
    <section className="border-t border-border pt-6">
      <div className="flex flex-wrap items-start justify-between gap-6 pb-5 border-b border-border">
        <div className="min-w-0 max-w-3xl">
          <div className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground">
            Setup required
          </div>
          <h2 className="mt-1.5 text-[22px] font-medium leading-tight tracking-tight text-foreground">
            Connect the admin operating stack
          </h2>
          <p className="mt-2 text-[13px] leading-6 text-muted-foreground">
            Admin automations stay paused until the realtor profile, province package, accounts, providers, approval lane, and regional memory are configured.
          </p>
        </div>
        <div className="min-w-[180px]">
          <div className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground">
            Readiness
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="font-mono-ui text-[28px] leading-none font-medium text-foreground tabular-nums">{setup.completionPct}</span>
            <span className="font-mono-ui text-[13px] text-muted-foreground">%</span>
          </div>
          <div className="mt-3 h-px bg-border">
            <div className="h-full bg-primary" style={{ width: `${setup.completionPct}%` }} />
          </div>
        </div>
      </div>

      {missingLabels.length > 0 && (
        <div className="flex items-baseline gap-3 py-3 border-b border-border text-[13px]">
          <span className="shrink-0 font-mono-ui text-[10px] uppercase tracking-wider text-warning">
            Missing
          </span>
          <span className="text-foreground">{missingLabels.join(", ")}</span>
        </div>
      )}
      {readinessBlockers.length > 0 && (
        <div className="divide-y divide-border border-b border-border">
          {readinessBlockers.slice(0, 9).map((item) => (
            <div key={item.key} className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 py-3">
              <span className="text-[13px] font-medium text-foreground">{item.label}</span>
              <span
                className={cn(
                  "font-mono-ui text-[10px] uppercase tracking-wider tabular-nums",
                  item.state === "needs_runtime_verification" ? "text-warning" : "text-muted-foreground",
                )}
              >
                {item.state.replaceAll("_", " ")}
              </span>
              <p className="col-span-2 text-[12.5px] leading-5 text-muted-foreground">{item.action}</p>
            </div>
          ))}
          {readinessBlockers.length > 9 && (
            <div className="py-3 text-[12.5px] text-muted-foreground">
              +{readinessBlockers.length - 9} more setup item{readinessBlockers.length - 9 === 1 ? "" : "s"} pending
            </div>
          )}
        </div>
      )}
      {verificationWarnings.length > 0 && (
        <div className="py-3 border-b border-border text-[12.5px] leading-5 text-muted-foreground">
          {verificationWarnings.join(" ")}
        </div>
      )}

      <div className="pt-6 pb-2">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Realtor profile</div>
        <div className="grid gap-4 lg:grid-cols-3">
          <AdminSetupField label="Realtor legal name" value={draft.realtorLegalName} onChange={(v) => updateDraft("realtorLegalName", v)} />
          <AdminSetupField label="Licensed / public name" value={draft.licenseName} onChange={(v) => updateDraft("licenseName", v)} />
          <AdminSetupField label="Brokerage" value={draft.brokerageName} onChange={(v) => updateDraft("brokerageName", v)} />
          <AdminSetupField label="Team / PREC" value={draft.teamName} onChange={(v) => updateDraft("teamName", v)} />
          <label className="block min-w-0">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="block text-[12px] font-medium text-muted-foreground">Province / territory</span>
              <div className="flex items-center gap-2">
                {savedProvinceCode && !provinceUnlocked && (
                  <button
                    type="button"
                    onClick={() => setProvinceUnlocked(true)}
                    className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Change
                  </button>
                )}
                <span className="font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground/80">CA · Canada</span>
              </div>
            </div>
            {savedProvinceCode && !provinceUnlocked ? (
              <div className="flex h-9 w-full items-center rounded-md border border-border bg-muted/40 px-3 text-[13px] text-foreground">
                <span>{PROVINCE_LABEL_BY_CODE.get(savedProvinceCode) ?? savedProvinceCode}</span>
                <span className="ml-2 font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  saved
                </span>
              </div>
            ) : (
              <select
                value={draft.province.trim().toUpperCase()}
                onChange={(event) => updateDraft("province", event.target.value)}
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary/30"
              >
                <option value="">Select province</option>
                {CANADIAN_PROVINCES.map(({ code, label }) => {
                  const coverage = provinceCoverageByCode.get(code);
                  const suffix = coverage?.hasTransactionGuide ? " — full guide" : coverage ? " — reference" : "";
                  return (
                    <option key={code} value={code}>
                      {label}
                      {suffix}
                    </option>
                  );
                })}
              </select>
            )}
            {selectedProvinceCoverage && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
                </span>
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.referencePages} pages
                </span>
                {selectedProvinceCoverage.forms > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.forms} forms
                  </span>
                )}
                {selectedProvinceCoverage.checklists > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.checklists} checklists
                  </span>
                )}
              </div>
            )}
            {draft.province.trim() && !selectedProvinceCoverage && (
              <div className="mt-1.5 text-[11px] text-muted-foreground">
                No local guide for this province yet — fall back to manual references.
              </div>
            )}
          </label>
          <AdminSetupField label="Market" value={draft.market} onChange={(v) => updateDraft("market", v)} placeholder="Kamloops, Calgary..." />
          <AdminSetupField label="Board memberships" value={draft.boardMemberships} onChange={(v) => updateDraft("boardMemberships", v)} placeholder="AOIR, FVREB..." />
          <AdminSetupField label="Managing broker/admin email" value={draft.managingBrokerEmail} onChange={(v) => updateDraft("managingBrokerEmail", v)} />
          <AdminSetupField label="Admin approval channel" value={draft.approvalChannel} onChange={(v) => updateDraft("approvalChannel", v)} placeholder="Telegram Admin bot/lane" />
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Providers</div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AdminSetupField label="Email" value={draft.emailProvider} onChange={(v) => updateDraft("emailProvider", v)} placeholder="Gmail / Outlook account" suggestions={PROVIDER_SUGGESTIONS.email} listId="provider-email" />
          <AdminSetupField label="Calendar" value={draft.calendarProvider} onChange={(v) => updateDraft("calendarProvider", v)} placeholder="Google Calendar / Outlook" suggestions={PROVIDER_SUGGESTIONS.calendar} listId="provider-calendar" />
          <AdminSetupField label="Cloud drive" value={draft.driveProvider} onChange={(v) => updateDraft("driveProvider", v)} placeholder="Google Drive / SharePoint" suggestions={PROVIDER_SUGGESTIONS.drive} listId="provider-drive" />
          <AdminSetupField label="CRM" value={draft.crmProvider} onChange={(v) => updateDraft("crmProvider", v)} placeholder="Lofty, kvCORE, BoldTrail..." suggestions={PROVIDER_SUGGESTIONS.crm} listId="provider-crm" />
          <AdminSetupField label="MLS / board portal" value={draft.mlsProvider} onChange={(v) => updateDraft("mlsProvider", v)} placeholder="Matrix, Xposure, Paragon..." suggestions={PROVIDER_SUGGESTIONS.mls} listId="provider-mls" />
          <AdminSetupField label="Forms provider" value={draft.formsProvider} onChange={(v) => updateDraft("formsProvider", v)} placeholder="WEBForms / TransactionDesk" suggestions={PROVIDER_SUGGESTIONS.forms} listId="provider-forms" />
          <AdminSetupField label="Signing provider" value={draft.signingProvider} onChange={(v) => updateDraft("signingProvider", v)} placeholder="DigiSign / DocuSign" suggestions={PROVIDER_SUGGESTIONS.signing} listId="provider-signing" />
          <AdminSetupField label="Compliance platform" value={draft.complianceProvider} onChange={(v) => updateDraft("complianceProvider", v)} placeholder="SkySlope / Lone Wolf" suggestions={PROVIDER_SUGGESTIONS.compliance} listId="provider-compliance" />
          <AdminSetupField label="Showing platform" value={draft.showingProvider} onChange={(v) => updateDraft("showingProvider", v)} placeholder="ShowingTime / BrokerBay" suggestions={PROVIDER_SUGGESTIONS.showing} listId="provider-showing" />
          <AdminSetupField label="Photo processing" value={draft.photoProcessingProvider} onChange={(v) => updateDraft("photoProcessingProvider", v)} placeholder="Drive + Nano Banana / Higgsfield" suggestions={PROVIDER_SUGGESTIONS.photo} listId="provider-photo" />
          <AdminSetupField label="FINTRAC / ID workflow" value={draft.fintracProvider} onChange={(v) => updateDraft("fintracProvider", v)} placeholder="Fintracker / manual FIN# capture" suggestions={PROVIDER_SUGGESTIONS.fintrac} listId="provider-fintrac" />
          <AdminSetupField label="Folder pattern" value={draft.defaultFolderPattern} onChange={(v) => updateDraft("defaultFolderPattern", v)} />
          <AdminSetupField label="Commission / service notes" value={draft.commissionNotes} onChange={(v) => updateDraft("commissionNotes", v)} />
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Credentials</div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AdminSetupField label="MLS login URL" value={draft.mlsLoginUrl} onChange={(v) => updateDraft("mlsLoginUrl", v)} placeholder="https://..." />
          <AdminSetupField label="MLS credential ref" value={draft.mlsCredentialRef} onChange={(v) => updateDraft("mlsCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
          <AdminSetupField label={`${draft.complianceProvider?.trim() || "Compliance"} login URL`} value={draft.complianceLoginUrl} onChange={(v) => updateDraft("complianceLoginUrl", v)} placeholder="https://..." />
          <AdminSetupField label={`${draft.complianceProvider?.trim() || "Compliance"} credential ref`} value={draft.complianceCredentialRef} onChange={(v) => updateDraft("complianceCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
          <AdminSetupField label="Showing login URL" value={draft.showingLoginUrl} onChange={(v) => updateDraft("showingLoginUrl", v)} placeholder="https://..." />
          <AdminSetupField label="Showing credential ref" value={draft.showingCredentialRef} onChange={(v) => updateDraft("showingCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Workflow notes</div>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="block min-w-0">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Browser-use notes</span>
            <textarea
              value={draft.browserWorkflowNotes}
              onChange={(event) => updateDraft("browserWorkflowNotes", event.target.value)}
              placeholder="Board portal quirks, browser profile, MFA expectations, where to find MLS number, showing feedback, compliance status, and confirmation screens."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
          <label className="block min-w-0">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Regional memory</span>
            <textarea
              value={draft.regionalMemory}
              onChange={(event) => updateDraft("regionalMemory", event.target.value)}
              placeholder="Province docs, local MLS quirks, deposit rules, admin emails, property lookup sources, showing platform notes."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
          <label className="block min-w-0 lg:col-span-2">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Approval policy</span>
            <textarea
              value={draft.approvalPolicy}
              onChange={(event) => updateDraft("approvalPolicy", event.target.value)}
              placeholder="What AI can draft/upload, what needs approval, whether docs/MLS/signing can ever send without a human."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
        </div>
      </div>

      {(error || savedMessage) && (
        <div className={cn(
          "mt-6 flex items-baseline gap-3 py-3 border-t text-[13px]",
          error ? "border-destructive" : "border-success",
        )}>
          <span className={cn(
            "shrink-0 font-mono-ui text-[10px] uppercase tracking-wider",
            error ? "text-destructive" : "text-success",
          )}>
            {error ? "Error" : "Saved"}
          </span>
          <span className="text-foreground">{error || savedMessage}</span>
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-5">
        <p className="max-w-2xl text-[12.5px] leading-5 text-muted-foreground">
          Admin deal creation, profile handoffs, stage moves, task launches, and default automation seeding are blocked until this reaches 100%.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => void verify()} disabled={saving || verifying}>
            {verifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Verify connections
          </Button>
          <Button onClick={() => void submit()} disabled={saving || verifying}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
            Save setup
          </Button>
        </div>
      </div>
    </section>
  );
}

function useAdminDeals(): {
  deals: AdminCard[];
  loading: boolean;
  error: string | null;
  usingDevFallback: boolean;
  refresh: () => Promise<void>;
  moveDeal: (dealId: string, toStage: AdminStageNumber) => Promise<void>;
  setDealToggle: (dealId: string, field: string, value: AdminConditionValue) => Promise<void>;
  addLocalDeal: (card: AdminCard) => void;
  replaceLocalDeal: (placeholderId: string, deal: AdminDeal) => void;
} {
  const [deals, setDeals] = useState<AdminCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDevFallback, setUsingDevFallback] = useState(false);

  const loadDeals = useCallback(async () => {
    const response = await api.getAdminDeals({ limit: 200 });
    return response.items.map(adminCardFromDeal);
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const nextDeals = await loadDeals();
      if (nextDeals.length === 0) {
        setDeals([]);
        setUsingDevFallback(false);
      } else {
        setDeals(nextDeals);
        setUsingDevFallback(false);
      }
    } catch (err) {
      setError(errorMessage(err, "Admin deals failed"));
      setDeals([]);
      setUsingDevFallback(false);
    } finally {
      setLoading(false);
    }
  }, [loadDeals]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadDeals()
      .then((nextDeals) => {
        if (cancelled) return;
        if (nextDeals.length === 0) {
          setDeals([]);
          setUsingDevFallback(false);
        } else {
          setDeals(nextDeals);
          setUsingDevFallback(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(errorMessage(err, "Admin deals failed"));
        setDeals([]);
        setUsingDevFallback(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadDeals]);

  const moveDeal = useCallback(
    async (dealId: string, toStage: AdminStageNumber) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? { ...card, stage: toStage, nextLabel: adminStageLabel(card.side, toStage).title } : card)),
      );
      try {
        const updated = await api.moveAdminDeal(dealId, toStage);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/move returned 404; keeping optimistic local stage update.");
          return;
        }
        setError(errorMessage(err, "Move deal failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const setDealToggle = useCallback(
    async (dealId: string, field: string, value: AdminConditionValue) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? applyLocalDealField(card, field, value) : card)),
      );
      try {
        const updated = await api.setAdminDealToggle(dealId, field, value);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/toggle returned 404; keeping optimistic local toggle update.");
          return;
        }
        setError(errorMessage(err, "Set deal toggle failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const addLocalDeal = useCallback((card: AdminCard) => {
    setDeals((prev) => [card, ...prev]);
  }, []);

  const replaceLocalDeal = useCallback((placeholderId: string, deal: AdminDeal) => {
    const fresh = adminCardFromDeal(deal);
    setDeals((prev) => prev.map((card) => (card.id === placeholderId ? fresh : card)));
  }, []);

  return { deals, loading, error, usingDevFallback, refresh, moveDeal, setDealToggle, addLocalDeal, replaceLocalDeal };
}

function dueLabel(days?: number): { text: string; tone: "muted" | "warn" | "danger" | "ok" } {
  if (days == null) return { text: "—", tone: "muted" };
  if (days < 0) return { text: `${-days}d overdue`, tone: "danger" };
  if (days === 0) return { text: "today", tone: "warn" };
  if (days === 1) return { text: "tomorrow", tone: "warn" };
  if (days <= 3) return { text: `in ${days}d`, tone: "warn" };
  return { text: `in ${days}d`, tone: "ok" };
}

const AdminKanbanCard = memo(function AdminKanbanCard({
  card,
  onSelect,
  onDragStart,
}: {
  card: AdminCard;
  onSelect?: (id: string) => void;
  onDragStart?: (id: string) => void;
}) {
  const due = dueLabel(card.daysOut);
  const { done, total, nextItem } = getCardProgress(card);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <button
      type="button"
      draggable
      onClick={() => onSelect?.(card.id)}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", card.id);
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(card.id);
      }}
      className="group relative w-full text-left border border-border bg-card px-3 py-2.5 hover:border-foreground/40 focus:outline-none focus-visible:border-primary transition-colors cursor-grab active:cursor-grabbing rounded-sm"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13.5px] font-medium leading-tight text-foreground">
          {card.client}
        </span>
        {card.pinnedTop25 && (
          <span title="Top 25" className="shrink-0 font-mono-ui text-[10px] uppercase tracking-wider text-warning">
            Top
          </span>
        )}
      </div>
      {card.property && (
        <div className="mt-1 truncate text-[12px] text-muted-foreground">
          {card.property}
        </div>
      )}
      {card.nextLabel && (
        <div className="mt-2 flex items-baseline gap-2 text-[12px]">
          <span className="truncate text-foreground">{card.nextLabel}</span>
          <span
            className={cn(
              "ml-auto shrink-0 font-mono-ui text-[11px] tabular-nums",
              due.tone === "danger" && "text-destructive",
              due.tone === "warn" && "text-warning",
              due.tone === "ok" && "text-muted-foreground",
              due.tone === "muted" && "text-muted-foreground",
            )}
          >
            {due.text}
          </span>
        </div>
      )}
      <div className="mt-2.5 flex items-center gap-2">
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Stage checklist progress"
          className="h-px flex-1 bg-border"
        >
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
        <span className="shrink-0 font-mono-ui text-[10px] tabular-nums text-muted-foreground">
          {done}/{total}
        </span>
      </div>
      {nextItem && (
        <div className="mt-1.5 truncate text-[11.5px] text-muted-foreground">
          <span className="font-mono-ui text-[9.5px] uppercase tracking-wider text-muted-foreground/70 mr-1.5">Next</span>
          {nextItem}
        </div>
      )}
    </button>
  );
});

function AdminPhaseSummary({
  phase,
  dense = false,
}: {
  phase: AdminPhaseAutomationInfo;
  dense?: boolean;
}) {
  const agentNames = phase.agents.join(", ");
  const backgroundNames = phase.background.join(", ");
  const summaryTitle = [
    phase.agents.length ? `Stage skills: ${agentNames}` : "No stage-entry skill wired",
    phase.background.length ? `Background: ${backgroundNames}` : null,
    phase.approvalGate ? `Approval gate: ${phase.approvalGate}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const automationLabel =
    phase.agents.length > 0
      ? phase.background.length > 0
        ? "automated + background"
        : "automated"
      : "manual";

  return (
    <div className={cn("flex flex-col gap-0.5", dense ? "mt-1" : "mt-1.5")} title={summaryTitle}>
      <div className="flex min-w-0 items-center gap-1.5 text-[0.7rem] leading-tight">
        <span className="truncate text-muted-foreground/85">{automationLabel}</span>
        {phase.approvalGate && (
          <>
            <span className="shrink-0 text-muted-foreground/45">·</span>
            <span className="shrink-0 text-warning">approval</span>
          </>
        )}
      </div>
      <div className="truncate text-[0.66rem] leading-tight text-muted-foreground/85">
        Moves on {phase.moveSignal}
      </div>
    </div>
  );
}

function AdminKanbanColumn(props: {
  side: AdminSide;
  stage: AdminStageNumber;
  cards: AdminCard[];
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (stage: AdminStageNumber) => void;
}) {
  const { side, stage, cards, onCardSelect, onCardDragStart, onCardDrop } = props;
  const column = adminStageDefinition(stage);
  const label = column.labels[side];
  const phase = adminPhaseAutomation(side, stage);
  const [isDragOver, setIsDragOver] = useState(false);
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        if (!isDragOver) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragOver(false);
        onCardDrop(stage);
      }}
      className={cn(
        "flex h-full min-w-[18.5rem] flex-col border-r border-border bg-background transition-colors",
        isDragOver && "bg-muted",
      )}
    >
      <div className="sticky top-0 z-10 border-b border-border bg-background px-3 py-3" title={label.subtitle}>
        <div className="flex items-baseline justify-between gap-2">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="font-mono-ui text-[10px] tabular-nums uppercase tracking-wider text-muted-foreground">
              {column.stageNumber.toString().padStart(2, "0")}
            </span>
            <span className="truncate text-[13px] font-medium text-foreground">{label.title}</span>
          </div>
          <span className="font-mono-ui text-[11px] tabular-nums text-muted-foreground">
            {cards.length}
          </span>
        </div>
        <AdminPhaseSummary phase={phase} />
      </div>
      <div className="flex flex-col gap-1.5 p-2">
        {cards.length === 0 ? (
          <p className="px-3 py-3 text-xs text-muted-foreground/70">
            {label.subtitle}
          </p>
        ) : (
          cards.map((card) => (
            <AdminKanbanCard
              key={card.id}
              card={card}
              onSelect={onCardSelect}
              onDragStart={onCardDragStart}
            />
          ))
        )}
      </div>
    </div>
  );
}

function AdminKanbanSwimlane({
  side,
  title,
  description,
  cardsByStage,
  totalCount,
  onCardSelect,
  onCardDragStart,
  onCardDrop,
}: {
  side: AdminSide;
  title: string;
  description: string;
  cardsByStage: Record<AdminStageNumber, AdminCard[]>;
  totalCount: number;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (side: AdminSide, stage: AdminStageNumber) => void;
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
          {totalCount} active
        </span>
        <span className="hidden text-[0.72rem] text-muted-foreground sm:inline">{description}</span>
      </div>
      <div
        className="grid gap-2 overflow-x-auto pb-1"
        style={{ gridTemplateColumns: `repeat(${ADMIN_STAGE_NUMBERS.length}, 18.5rem)` }}
      >
        {ADMIN_STAGE_NUMBERS.map((stage) => (
          <AdminKanbanColumn
            key={`${side}-${stage}`}
            side={side}
            stage={stage}
            cards={cardsByStage[stage] ?? []}
            onCardSelect={onCardSelect}
            onCardDragStart={onCardDragStart}
            onCardDrop={(targetStage) => onCardDrop(side, targetStage)}
          />
        ))}
      </div>
    </section>
  );
}

function AdminTop25Strip({
  cards,
  devFallback,
  onCardSelect,
  onCardDragStart,
}: {
  cards: AdminCard[];
  devFallback: boolean;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
}) {
  const pinned = cards.filter((c) => c.pinnedTop25);
  return (
    <section className="rounded-md border border-border bg-card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-warning" />
          <h2 className="text-[0.95rem] font-semibold text-foreground">TOP 25</h2>
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
            {pinned.length} pinned · {Math.max(0, 25 - pinned.length)} slots open
          </span>
          {devFallback && (
            <span className="rounded-sm border border-border bg-transparent px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-wider text-warning">
              dev-fallback
            </span>
          )}
        </div>
        <span className="text-[0.72rem] text-muted-foreground hidden sm:inline">
          Pinned clients still live in their stage column.
        </span>
      </div>
      {pinned.length === 0 ? (
        <p className="mt-2 px-1 py-1 text-xs text-muted-foreground/80">
          No clients pinned — pin from any card to add to TOP 25.
        </p>
      ) : (
        <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
          {pinned.map((card) => (
            <div key={card.id} className="min-w-[16rem] max-w-[16rem]">
              <AdminKanbanCard card={card} onSelect={onCardSelect} onDragStart={onCardDragStart} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AdminCardStageSection({
  card,
  stage,
  isCurrent,
  isPast,
  expanded,
  onToggleExpand,
  onToggleItem,
  documents,
}: {
  card: AdminCard;
  stage: AdminStageNumber;
  isCurrent: boolean;
  isPast: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleItem: (itemId: string, completed: boolean) => void;
  documents?: ProvinceStageDocumentItem[];
}) {
  const column = adminStageDefinition(stage);
  const label = column.labels[card.side];
  const phase = adminPhaseAutomation(card.side, stage);
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  const done = items.reduce((n, item) => n + (completed[item.id] ? 1 : 0), 0);
  const total = items.length;
  const allDone = total > 0 && done === total;

  return (
    <div
      className={cn(
        "rounded-md border bg-card",
        isCurrent ? "border-primary" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-md"
      >
        <div className="flex h-6 w-6 shrink-0 items-center justify-center">
          {isPast && allDone ? (
            <CheckCircle2 className="h-5 w-5 text-primary/80" />
          ) : isCurrent ? (
            <span className="inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
          ) : (
            <span className="inline-flex h-2.5 w-2.5 rounded-full border border-border" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-[0.86rem] font-semibold leading-tight",
                isCurrent ? "text-foreground" : isPast ? "text-foreground/85" : "text-muted-foreground",
              )}
            >
              {label.title}
            </span>
            {isCurrent && (
              <span className="font-mono-ui text-[0.58rem] uppercase tracking-wider text-primary">
                current
              </span>
            )}
          </div>
          <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            {column.stageNumber} · {column.stageLabel ?? label.subtitle}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[0.66rem] leading-tight text-muted-foreground">
            <Target className="h-3 w-3 shrink-0 text-muted-foreground/80" />
            <span className="truncate">{phase.moveSignal}</span>
          </div>
        </div>
        <span
          className={cn(
            "font-mono-ui text-[0.66rem] tabular-nums",
            allDone ? "text-primary" : "text-muted-foreground",
          )}
        >
          {done}/{total}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t border-border px-3 py-2.5">
          <div className="mb-2 rounded-sm border border-border bg-card px-2 py-2">
            <AdminPhaseSummary phase={phase} dense />
            {phase.approvalGate && (
              <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[0.68rem] text-muted-foreground">
                <ShieldCheck className="h-3 w-3 shrink-0 text-warning" />
                <span className="truncate">Gate: {phase.approvalGate}</span>
              </div>
            )}
          </div>
          {items.length === 0 ? (
            <div className="text-[0.72rem] text-muted-foreground">No checklist items defined for this stage.</div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {items.map((item) => {
                const isDone = !!completed[item.id];
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onToggleItem(item.id, !isDone)}
                      className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      {isDone ? (
                        <CheckSquare className="mt-[1px] h-4 w-4 shrink-0 text-primary" />
                      ) : (
                        <SquareIcon className="mt-[1px] h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <span
                        className={cn(
                          "text-[0.82rem] leading-snug",
                          isDone ? "text-muted-foreground line-through decoration-muted-foreground/50" : "text-foreground",
                        )}
                      >
                        {item.label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {documents && documents.length > 0 && (
            <div className="mt-3 border-t border-border pt-2.5">
              <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Province documents · {documents.length}
              </div>
              <ul className="flex flex-col gap-1">
                {documents.map((doc) => (
                  <li
                    key={`${doc.source}-${doc.code}`}
                    className="flex items-start gap-2 text-[0.78rem] leading-snug"
                  >
                    <FileText className="mt-[1px] h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <span className="font-medium text-foreground">{doc.code}</span>
                      <span className="text-muted-foreground"> · {doc.name}</span>
                      {doc.condition && (
                        <span className="font-mono-ui ml-1 text-[0.62rem] uppercase tracking-wider text-warning">
                          if {doc.condition.field}={doc.condition.value}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdminCardConditionsSection({
  card,
  onConditionChange,
}: {
  card: AdminCard;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
}) {
  const conditions = card.conditions ?? {};
  return (
    <section className="mt-4">
      <h3 className="text-[0.86rem] font-semibold text-foreground">Conditions</h3>
      <div className="mt-2 space-y-4">
        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Enums
          </div>
          <div className="divide-y divide-border">
            {ADMIN_ENUM_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const value = typeof current === "string" ? current : "";
              const hasCustomValue = value !== "" && !condition.options.some((option) => option.value === value);
              return (
                <label
                  key={condition.field}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="min-w-0 flex-1 text-[0.78rem] font-medium text-foreground">
                    {condition.label}
                  </span>
                  <select
                    value={value}
                    onChange={(event) => onConditionChange(condition.field, event.currentTarget.value || null)}
                    className="h-10 max-w-[12rem] rounded-md border border-border bg-background px-2 text-[0.78rem] text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">Not set</option>
                    {hasCustomValue && <option value={value}>{value}</option>}
                    {condition.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
        </div>

        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Yes / No
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {ADMIN_TOGGLE_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const checked = current === true;
              const label = current == null ? "Unset" : checked ? "Yes" : "No";
              return (
                <button
                  key={condition.field}
                  type="button"
                  aria-pressed={checked}
                  onClick={() => onConditionChange(condition.field, !checked)}
                  className="flex min-h-11 items-center gap-2 rounded-sm px-2.5 py-2 text-left hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {checked ? (
                    <CheckSquare className="h-4 w-4 shrink-0 text-primary" />
                  ) : (
                    <SquareIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 text-[0.78rem] leading-tight text-foreground">
                    {condition.label}
                  </span>
                  <span className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    {label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function AdminCardSourceSection({ context }: { context: AdminSourceContext }) {
  const heat = context.heatLabel
    ? `${context.heatLabel}${context.heatScore != null ? ` ${context.heatScore}` : ""}`
    : null;
  return (
    <section className="mb-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.86rem] font-semibold text-foreground">
          {context.profileName || "Source profile"}
        </span>
        {heat && <Badge variant={context.heatLabel ? heatVariant({ heatLabel: context.heatLabel }) : "outline"}>{heat}</Badge>}
        {context.contactIds.length > 0 && !context.rejectedContactId && <Badge variant="success">DB contact</Badge>}
        <Badge variant={context.verifiers.length > 0 ? "success" : "warning"}>
          {verifierSummary(context.verifiers)}
        </Badge>
        {context.rejectedContactId && <Badge variant="warning">source contact only</Badge>}
      </div>
      {context.latestText && (
        <p className="mt-2 line-clamp-3 text-[0.8rem] leading-5 text-muted-foreground">
          {context.latestText}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {context.sources.map((source) => (
          <Badge key={`source-${source}`} variant="outline">{source}</Badge>
        ))}
        {context.channels.map((channel) => (
          <Badge key={`channel-${channel}`} variant="outline">{channel}</Badge>
        ))}
        {context.conversationIds.length > 0 && (
          <Badge variant="outline">
            {context.conversationIds.length} conversation{context.conversationIds.length === 1 ? "" : "s"}
          </Badge>
        )}
        {context.latestAt && <Badge variant="outline">{isoTimeAgo(context.latestAt)}</Badge>}
      </div>
    </section>
  );
}

function isPersistedAdminDealId(id: string): boolean {
  return /^[a-f0-9]{32}$/i.test(id);
}

function adminContextDate(value?: string | null): string {
  if (!value) return "Not set";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return isoTimeAgo(value);
}

function adminContextMoney(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Not set";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value);
}

function AdminDealContextSection({
  context,
  loading,
  error,
  busy,
  onAdvance,
  onUpdateFields,
  onAddAttachment,
  onAddContact,
  onApproveRun,
  onCancelRun,
}: {
  context: DealContext | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onAdvance: (force?: boolean) => Promise<void>;
  onUpdateFields: (fields: Record<string, unknown>) => Promise<void>;
  onAddAttachment: (body: DealAttachmentCreateRequest) => Promise<void>;
  onAddContact: (body: DealContactCreateRequest) => Promise<void>;
  onApproveRun: (runId: string) => Promise<void>;
  onCancelRun: (runId: string) => Promise<void>;
}) {
  const [actionMode, setActionMode] = useState<"dates" | "doc" | "contact" | null>(null);
  const [approvalBusyRun, setApprovalBusyRun] = useState<AdminRunBusy>(null);
  const [fieldDraft, setFieldDraft] = useState({
    listingDate: "",
    subjectRemovalDate: "",
    depositDueDate: "",
    completionDate: "",
    possessionDate: "",
    mlsNumber: "",
    listPrice: "",
  });
  const [docDraft, setDocDraft] = useState({ kind: "cma_report", filePath: "", summary: "" });
  const [contactDraft, setContactDraft] = useState({ role: "lawyer", contactId: "", notes: "" });
  const deal = context?.deal ?? null;
  const primary = context?.primaryContact ?? null;
  const coContacts = context?.coContacts ?? [];
  const attachments = context?.attachments ?? [];
  const priorRuns = context?.priorRuns ?? [];
  const flow = context?.dealFlow ?? null;
  const gate = flow?.gate ?? null;
  const pendingHumanRuns = priorRuns.filter((run) => run.status === "waiting_human");
  const resolvePendingRun = async (run: AdminActionRun, approved: boolean) => {
    if (busy || approvalBusyRun) return;
    setApprovalBusyRun({ id: run.id, action: approved ? "approve" : "cancel" });
    try {
      if (approved) {
        await onApproveRun(run.id);
      } else {
        await onCancelRun(run.id);
      }
    } finally {
      setApprovalBusyRun(null);
    }
  };
  const dateRows: Array<[string, string]> = deal
    ? ([
        ["Listing", deal.listingDate],
        ["Offer", deal.offerDate],
        ["Conditions", deal.subjectRemovalDate],
        ["Deposit", deal.depositDueDate],
        ["Completion", deal.completionDate],
        ["Possession", deal.possessionDate],
      ] as Array<[string, string | null | undefined]>).flatMap(([label, value]) =>
        value ? [[label, value]] : [],
      )
    : [];
  const moneyRows: Array<[string, number]> = deal
    ? ([
        ["List price", deal.listPrice],
        ["Offer price", deal.offerPrice],
        ["Deposit", deal.depositAmount],
      ] as Array<[string, number | null | undefined]>).flatMap(([label, value]) =>
        typeof value === "number" ? [[label, value]] : [],
      )
    : [];

  return (
    <section className="mb-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <DatabaseIcon className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="text-[0.88rem] font-semibold text-foreground">Transaction file</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {loading && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </Badge>
          )}
          {deal?.board && <Badge variant="outline">{deal.board}</Badge>}
          {deal?.market && <Badge variant="outline">{deal.market}</Badge>}
          {context && <Badge variant="outline">{attachments.length} docs</Badge>}
          {context && <Badge variant="outline">{priorRuns.length} runs</Badge>}
        </div>
      </div>

      {!loading && error && (
        <div className="mt-2 rounded-sm border border-border bg-background px-3 py-2 text-[0.78rem] text-warning">
          {error}
        </div>
      )}

      {!loading && !error && !context && (
        <div className="mt-2 rounded-sm border border-dashed border-border bg-background px-3 py-3 text-[0.78rem] text-muted-foreground">
          This preview card is not backed by a saved deal file yet.
        </div>
      )}

      {context && deal && (
        <div className="mt-3 space-y-3">
          {gate && (
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    Phase gate
                  </div>
                  <div className="mt-1 text-[0.86rem] font-medium text-foreground">
                    {gate.stageName}
                    {gate.nextStageName ? ` -> ${gate.nextStageName}` : ""}
                  </div>
                </div>
                <Badge variant={gate.canAdvance ? "success" : "warning"}>
                  {gate.canAdvance ? "ready" : "blocked"}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 text-[0.74rem] sm:grid-cols-2">
                <div>
                  <span className="text-muted-foreground">Checklist: </span>
                  <span className="text-foreground">
                    {gate.completedChecklist}/{gate.totalChecklist}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Package: </span>
                  <span className="text-foreground">{flow?.packageKey}</span>
                </div>
              </div>
              {(gate.missingChecklist.length > 0 || gate.missingFields.length > 0 || gate.missingDocs.length > 0 || gate.blockingRuns.length > 0) && (
                <div className="mt-2 space-y-1.5 text-[0.74rem]">
                  {gate.missingChecklist.slice(0, 4).map((item) => (
                    <div key={`check-${item.id}`} className="text-muted-foreground">
                      Missing checklist: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingFields.slice(0, 4).map((item) => (
                    <div key={`field-${item.field}`} className="text-muted-foreground">
                      Missing field: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingDocs.slice(0, 4).map((item) => (
                    <div key={`doc-${item.kind}`} className="text-muted-foreground">
                      Missing doc: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.blockingRuns.slice(0, 4).map((run) => (
                    <div key={`run-${run.id}`} className="text-muted-foreground">
                      Waiting run: <span className="text-foreground">{run.label}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" disabled={!gate.canAdvance || busy} onClick={() => void onAdvance(false)}>
                  {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Advance phase
                </Button>
                {!gate.canAdvance && gate.nextStage != null && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void onAdvance(true)}>
                    Force advance
                  </Button>
                )}
              </div>
	            </div>
	          )}

	          {flow?.backgroundAutomations?.length ? (
	            <div className="rounded-sm border border-border bg-background px-3 py-2">
	              <div className="flex flex-wrap items-center justify-between gap-2">
	                <div>
	                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
	                    Background automations
	                  </div>
	                  <div className="mt-1 text-[0.78rem] text-muted-foreground">
	                    Cron skills feed evidence into this deal; phases consume the results.
	                  </div>
	                </div>
	                <Badge variant="outline">{flow.backgroundAutomations.length}</Badge>
	              </div>
	              <div className="mt-2 grid gap-2 sm:grid-cols-2">
	                {flow.backgroundAutomations.map((item) => (
	                  <div key={item.id} className="rounded-md border border-border bg-card px-2 py-2">
	                    <div className="flex min-w-0 items-center justify-between gap-2">
	                      <span className="truncate text-[0.8rem] font-medium text-foreground">{item.name}</span>
	                      <Badge variant="secondary">{item.kind}</Badge>
	                    </div>
	                    <div className="mt-1 truncate font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
	                      {item.skill}
	                    </div>
	                  </div>
	                ))}
	              </div>
	            </div>
	          ) : null}

	          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Primary contact
              </div>
              <div className="mt-1 truncate text-[0.86rem] font-medium text-foreground">
                {primary?.displayName ?? "Not linked"}
              </div>
              {(primary?.primaryEmail || primary?.primaryPhone) && (
                <div className="mt-1 space-y-0.5 text-[0.74rem] text-muted-foreground">
                  {primary.primaryEmail && <div className="truncate">{primary.primaryEmail}</div>}
                  {primary.primaryPhone && <div>{primary.primaryPhone}</div>}
                </div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Important dates
              </div>
              {dateRows.length > 0 ? (
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[0.74rem]">
                  {dateRows.slice(0, 6).map(([label, value]) => (
                    <div key={label} className="min-w-0">
                      <span className="text-muted-foreground">{label}: </span>
                      <span className="text-foreground">{adminContextDate(value)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1 text-[0.74rem] text-muted-foreground">No dates set</div>
              )}
            </div>
          </div>

          {(moneyRows.length > 0 || deal.mlsNumber || deal.legalDescription) && (
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                File details
              </div>
              <div className="mt-1 grid gap-x-3 gap-y-1 text-[0.74rem] sm:grid-cols-2">
                {moneyRows.map(([label, value]) => (
                  <div key={label}>
                    <span className="text-muted-foreground">{label}: </span>
                    <span className="text-foreground">{adminContextMoney(value)}</span>
                  </div>
                ))}
                {deal.mlsNumber && (
                  <div>
                    <span className="text-muted-foreground">MLS: </span>
                    <span className="text-foreground">{deal.mlsNumber}</span>
                  </div>
                )}
                {deal.legalDescription && (
                  <div className="sm:col-span-2">
                    <span className="text-muted-foreground">Legal: </span>
                    <span className="text-foreground">{deal.legalDescription}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)]">
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <Users className="h-3 w-3" />
                Co-contacts
              </div>
              {coContacts.length > 0 ? (
                <div className="mt-1.5 space-y-1">
                  {coContacts.slice(0, 3).map((item) => (
                    <div key={item.id} className="min-w-0 text-xs leading-5">
                      <span className="font-medium text-foreground">{item.role}</span>
                      <span className="text-muted-foreground"> · </span>
                      <span className="text-muted-foreground">{item.contact?.displayName ?? item.contactId}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">None linked</div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <FileText className="h-3 w-3" />
                Documents
              </div>
              {attachments.length > 0 ? (
                <div className="mt-1.5 space-y-1.5">
                  {attachments.slice(0, 3).map((item) => (
                    <div
                      key={item.id}
                      className="min-w-0 text-xs leading-5 line-clamp-3"
                      title={item.summary || item.filePath}
                    >
                      <span className="font-medium text-foreground">{item.kind}</span>
                      {item.summary && <span className="text-muted-foreground"> · {item.summary}</span>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">No docs attached</div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <Clock className="h-3 w-3" />
                Prior runs
              </div>
              {priorRuns.length > 0 ? (
                <div className="mt-1.5 space-y-1.5">
                  {priorRuns.slice(0, 3).map((run) => (
                    <div key={run.id} className="min-w-0">
                      <div className="truncate text-xs font-medium leading-5 text-foreground">
                        {run.registryName ?? run.skill ?? "Admin run"}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <Badge variant={adminRunStatusVariant(run.status)}>{run.status}</Badge>
                        <span className="text-[0.68rem] text-muted-foreground">{isoTimeAgo(run.updatedAt)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">No runs yet</div>
              )}
            </div>
          </div>

          <div className="rounded-sm border border-border bg-background px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Source actions
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant={actionMode === "dates" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "dates" ? null : "dates")}>
                  <CalendarClock className="h-3.5 w-3.5" />
                  Dates
                </Button>
                <Button size="sm" variant={actionMode === "doc" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "doc" ? null : "doc")}>
                  <FileText className="h-3.5 w-3.5" />
                  Attach
                </Button>
                <Button size="sm" variant={actionMode === "contact" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "contact" ? null : "contact")}>
                  <Users className="h-3.5 w-3.5" />
                  Co-contact
                </Button>
              </div>
            </div>

            {actionMode === "dates" && (
              <form
                className="mt-3 grid gap-2 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const fields = Object.fromEntries(
                    Object.entries(fieldDraft).filter(([, value]) => value.trim()),
                  );
                  void onUpdateFields(fields).then(() => {
                    setFieldDraft({
                      listingDate: "",
                      subjectRemovalDate: "",
                      depositDueDate: "",
                      completionDate: "",
                      possessionDate: "",
                      mlsNumber: "",
                      listPrice: "",
                    });
                    setActionMode(null);
                  });
                }}
              >
                {(["listingDate", "subjectRemovalDate", "depositDueDate", "completionDate", "possessionDate", "mlsNumber", "listPrice"] as const).map((field) => (
                  <label key={field} className="text-[0.72rem] text-muted-foreground">
                    {field}
                    <input
                      value={fieldDraft[field]}
                      onChange={(event) => setFieldDraft((prev) => ({ ...prev, [field]: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  </label>
                ))}
                <div className="sm:col-span-2">
                  <Button size="sm" type="submit" disabled={busy}>Update file fields</Button>
                </div>
              </form>
            )}

            {actionMode === "doc" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddAttachment({
                    kind: docDraft.kind,
                    filePath: docDraft.filePath,
                    summary: docDraft.summary || null,
                  }).then(() => {
                    setDocDraft({ kind: "cma_report", filePath: "", summary: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={docDraft.kind} onChange={(event) => setDocDraft((prev) => ({ ...prev, kind: event.target.value }))} placeholder="kind, e.g. cma_report" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={docDraft.filePath} onChange={(event) => setDocDraft((prev) => ({ ...prev, filePath: event.target.value }))} placeholder="/path/to/file.pdf" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={docDraft.summary} onChange={(event) => setDocDraft((prev) => ({ ...prev, summary: event.target.value }))} placeholder="summary" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !docDraft.kind.trim() || !docDraft.filePath.trim()}>Attach document</Button>
              </form>
            )}

            {actionMode === "contact" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddContact({
                    role: contactDraft.role,
                    contactId: contactDraft.contactId,
                    notes: contactDraft.notes || null,
                  }).then(() => {
                    setContactDraft({ role: "lawyer", contactId: "", notes: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={contactDraft.role} onChange={(event) => setContactDraft((prev) => ({ ...prev, role: event.target.value }))} placeholder="role, e.g. lawyer" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={contactDraft.contactId} onChange={(event) => setContactDraft((prev) => ({ ...prev, contactId: event.target.value }))} placeholder="contact id" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={contactDraft.notes} onChange={(event) => setContactDraft((prev) => ({ ...prev, notes: event.target.value }))} placeholder="notes" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !contactDraft.role.trim() || !contactDraft.contactId.trim()}>Add co-contact</Button>
              </form>
            )}
          </div>

          {pendingHumanRuns.length > 0 && (
            <div className="grid gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[12px] font-semibold text-warning">
                    Pending approvals
                  </div>
                  <div className="mt-1 text-[0.76rem] leading-5 text-muted-foreground">
                    These are the Admin decisions blocking the next run or phase move.
                  </div>
                </div>
                <Badge variant="warning">{pendingHumanRuns.length}</Badge>
              </div>
              <div className="mt-2 space-y-2">
                {pendingHumanRuns.map((run) => (
                  <AdminRunDecisionRow
                    key={run.id}
                    compact
                    busyRun={busy ? { id: "__busy__", action: "approve" } : approvalBusyRun}
                    run={run}
                    onApprove={() => void resolvePendingRun(run, true)}
                    onCancel={() => void resolvePendingRun(run, false)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function AdminCardDetailPanel({
  card,
  onClose,
  onToggleItem,
  onConditionChange,
  onMoveToNext,
  onDealUpdated,
}: {
  card: AdminCard;
  onClose: () => void;
  onToggleItem: (stage: AdminStageNumber, itemId: string, completed: boolean) => void;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
  onMoveToNext: () => void;
  onDealUpdated: (deal: AdminDeal) => void;
}) {
  const nextStage = adminNextStage(card);
  const currentProgress = getCardProgress(card);
  const currentComplete = currentProgress.total > 0 && currentProgress.done === currentProgress.total;
  const currentStage = adminStageDefinition(card.stage);
  const currentLabel = currentStage.labels[card.side];
  const nextLabel = nextStage == null ? null : adminStageLabel(card.side, nextStage);

  const [expanded, setExpanded] = useState<Set<AdminStageNumber>>(() => new Set([card.stage]));
  const [dealContext, setDealContext] = useState<DealContext | null>(null);
  const [dealContextLoading, setDealContextLoading] = useState(false);
  const [dealContextError, setDealContextError] = useState<string | null>(null);
  const [dealActionBusy, setDealActionBusy] = useState(false);
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setExpanded((prev) => (prev.has(card.stage) ? prev : new Set([...prev, card.stage])));
  }, [card.stage]);

  useEffect(() => {
    let active = true;
    setDealContext(null);
    setDealContextError(null);
    if (!isPersistedAdminDealId(card.id)) {
      setDealContextLoading(false);
      return () => {
        active = false;
      };
    }
    setDealContextLoading(true);
    api.getDealContext(card.id)
      .then((context) => {
        if (active) setDealContext(context);
      })
      .catch((err) => {
        if (active) {
          setDealContextError(errorMessage(err, "Deal context failed"));
        }
      })
      .finally(() => {
        if (active) setDealContextLoading(false);
      });
    return () => {
      active = false;
    };
  }, [card.id]);

  const reloadDealContext = useCallback(async () => {
    if (!isPersistedAdminDealId(card.id)) return null;
    const context = await api.getDealContext(card.id);
    setDealContext(context);
    onDealUpdated(context.deal);
    return context;
  }, [card.id, onDealUpdated]);

  const runDealAction = useCallback(
    async (action: () => Promise<void>) => {
      setDealActionBusy(true);
      setDealContextError(null);
      try {
        await action();
      } catch (err) {
        setDealContextError(errorMessage(err, "Deal action failed"));
      } finally {
        setDealActionBusy(false);
      }
    },
    [],
  );

  const handleAdvancePhase = useCallback(
    (force = false) =>
      runDealAction(async () => {
        const context = await api.advanceDeal(card.id, force);
        setDealContext(context);
        onDealUpdated(context.deal);
      }),
    [card.id, onDealUpdated, runDealAction],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Focus trap + restore focus on close.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;

    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );

    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });

    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, []);

  const toggleSection = (stage: AdminStageNumber) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  };

  const due = dueLabel(card.daysOut);
  const laneLabel = ADMIN_SIDE_LABELS[card.side].title;
  const phaseGate = dealContext?.dealFlow?.gate ?? null;
  const showAdvancePrompt = nextStage != null && nextLabel && (phaseGate ? phaseGate.canAdvance : currentComplete);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close detail"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 flex h-full w-full flex-col bg-card sm:h-auto sm:max-h-full sm:w-full sm:max-w-[42rem] sm:rounded-md sm:border sm:border-border md:max-w-[48rem] lg:max-w-[56rem]"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
              <span>{laneLabel} admin</span>
              <span>·</span>
              <span className="text-primary">{currentStage.stageNumber}</span>
              <span>·</span>
              <span className="text-primary">{currentLabel.title}</span>
              {card.pinnedTop25 && (
                <span className="inline-flex items-center gap-1 rounded-sm border border-border bg-transparent px-1.5 py-0.5 text-warning">
                  <Flame className="h-2.5 w-2.5" />
                  Top
                </span>
              )}
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              {card.client}
            </h2>
            {card.property && (
              <div className="mt-1 flex items-start gap-1.5 text-[0.78rem] text-muted-foreground">
                <Building2 className="mt-[2px] h-3.5 w-3.5 shrink-0" />
                <span>{card.property}</span>
              </div>
            )}
            {card.nextLabel && (
              <div className="mt-1 flex items-center gap-1.5 text-[0.78rem]">
                <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-foreground">{card.nextLabel}</span>
                <span
                  className={cn(
                    "font-mono-ui text-[0.68rem]",
                    due.tone === "danger" && "text-destructive",
                    due.tone === "warn" && "text-warning",
                    due.tone === "ok" && "text-muted-foreground",
                    due.tone === "muted" && "text-muted-foreground",
                  )}
                >
                  · {due.text}
                </span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {showAdvancePrompt && nextStage != null && nextLabel && (
          <div className="border-b border-border bg-muted px-4 py-2.5">
            <div className="flex items-center gap-2 text-[0.78rem]">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="text-foreground">
                All {currentStage.stageNumber} items done - move to {nextLabel.title}?
              </span>
              <button
                type="button"
                onClick={() => {
                  if (phaseGate) void handleAdvancePhase(false);
                  else onMoveToNext();
                }}
                className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm border border-border bg-card px-3 py-2 text-[0.8rem] font-medium text-primary hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Move card →
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {card.sourceContext && <AdminCardSourceSection context={card.sourceContext} />}
          <AdminDealContextSection
            context={dealContext}
            loading={dealContextLoading}
            error={dealContextError}
            busy={dealActionBusy}
            onAdvance={handleAdvancePhase}
            onUpdateFields={(fields) =>
              runDealAction(async () => {
                const deal = await api.updateDealFields(card.id, fields);
                onDealUpdated(deal);
                await reloadDealContext();
              })
            }
            onAddAttachment={(body) =>
              runDealAction(async () => {
                await api.addDealAttachment(card.id, body);
                await reloadDealContext();
              })
            }
            onAddContact={(body) =>
              runDealAction(async () => {
                await api.addDealContact(card.id, body);
                await reloadDealContext();
              })
            }
            onApproveRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: true, runNow: true });
                await reloadDealContext();
              })
            }
            onCancelRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: false, runNow: false });
                await reloadDealContext();
              })
            }
          />
          <div className="flex flex-col gap-2">
            {ADMIN_STAGE_NUMBERS.map((stage) => (
                <AdminCardStageSection
                  key={`${card.side}-${stage}`}
                  card={card}
                  stage={stage}
                  isCurrent={stage === card.stage}
                  isPast={stage < card.stage}
                  expanded={expanded.has(stage)}
                  onToggleExpand={() => toggleSection(stage)}
                  onToggleItem={(itemId, completed) => onToggleItem(stage, itemId, completed)}
                  documents={dealContext?.stageDocuments?.stages[String(stage)] ?? []}
                />
            ))}
          </div>
          <AdminCardConditionsSection card={card} onConditionChange={onConditionChange} />
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function NewDealDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (placeholderCard: AdminCard, request: AdminDealCreateRequest) => Promise<void>;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const [title, setTitle] = useState("");
  const [side, setSide] = useState<AdminSide>("listing");
  const [stage, setStage] = useState<AdminStageNumber>(0);
  const [province, setProvince] = useState("");
  const [setupProvince, setSetupProvince] = useState("");
  const [provinceOverride, setProvinceOverride] = useState(false);
  const [provinceCoverage, setProvinceCoverage] = useState<AdminProvinceGuideCoverage[]>([]);
  const [contactId, setContactId] = useState<string | null>(null);
  const [contactQuery, setContactQuery] = useState("");
  const [contacts, setContacts] = useState<AdminContact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState<string | null>(null);
  const [listingAddress, setListingAddress] = useState("");
  const [propertySubtype, setPropertySubtype] = useState("");
  const [listingType, setListingType] = useState("");
  const [signingAuthority, setSigningAuthority] = useState("");
  const [transactionType, setTransactionType] = useState("");
  const [notes, setNotes] = useState("");
  const [notesAutoFilled, setNotesAutoFilled] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;
    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );
    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminJurisdiction()
      .then((jurisdiction) => {
        if (cancelled) return;
        const code = (jurisdiction.province || "").trim().toUpperCase();
        setProvince(code);
        setSetupProvince(code);
      })
      .catch(() => {});
    api
      .getAdminProvinceGuides()
      .then((guides) => {
        if (cancelled) return;
        if ("items" in guides) {
          setProvinceCoverage(guides.items);
        }
      })
      .catch(() => {
        if (!cancelled) setProvinceCoverage([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setContactsLoading(true);
    setContactsError(null);
    api
      .getAdminContacts({ limit: 200 })
      .then((response) => {
        if (cancelled) return;
        setContacts(response.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setContactsError(err instanceof Error ? err.message : "Could not load contacts");
      })
      .finally(() => {
        if (!cancelled) setContactsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceCoverageByCode = useMemo(() => {
    return new Map(provinceCoverage.map((item) => [item.province, item]));
  }, [provinceCoverage]);

  const selectedProvinceCoverage = provinceCoverageByCode.get(province);

  const filteredContacts = useMemo(() => {
    const q = contactQuery.trim().toLowerCase();
    if (!q) return contacts.slice(0, 8);
    return contacts
      .filter((contact) => {
        const haystack = [contact.displayName, contact.primaryEmail, contact.primaryPhone]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .slice(0, 8);
  }, [contacts, contactQuery]);

  const selectedContact = contacts.find((c) => c.id === contactId) ?? null;

  const handleSelectContact = (contact: AdminContact) => {
    setContactId(contact.id);
    setContactQuery("");
    if (!title.trim() && contact.displayName) {
      setTitle(contact.displayName);
    }
    if (!notes.trim() || notesAutoFilled) {
      const bits: string[] = [];
      if (contact.sourceKey) bits.push(`Source: ${contact.sourceKey}`);
      if (contact.type) bits.push(`Type: ${contact.type}`);
      if (contact.stage) bits.push(`Stage: ${contact.stage}`);
      if (contact.lastActivityAt) bits.push(`Last activity: ${isoTimeAgo(contact.lastActivityAt)}`);
      if (contact.ownerNotes) bits.push(`\nNotes: ${contact.ownerNotes}`);
      const filled = bits.join("\n");
      if (filled) {
        setNotes(filled);
        setNotesAutoFilled(true);
      }
    }
  };

  const clearContact = () => {
    setContactId(null);
    setContactQuery("");
    if (notesAutoFilled) {
      setNotes("");
      setNotesAutoFilled(false);
    }
  };

  const canSubmit = title.trim().length > 0 && province.trim().length > 0 && !submitting;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    const cleanTitle = title.trim();
    const cleanAddress = listingAddress.trim();
    const cleanNotes = notes.trim();
    const placeholderId = `local-${Date.now()}`;
    const stageLabel = adminStageLabel(side, stage);
    const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
    const fields: Record<string, unknown> = {};
    if (side === "listing") {
      if (signingAuthority) {
        fields.signing_authority = signingAuthority;
        conditions.signing_authority = signingAuthority;
      }
      if (listingType) {
        fields.listing_type = listingType;
        conditions.listing_type = listingType;
      }
    } else if (transactionType) {
      fields.transaction_type = transactionType;
      conditions.transaction_type = transactionType;
    }
    if (propertySubtype) {
      fields.property_subtype = propertySubtype;
      conditions.property_subtype = propertySubtype;
    }
    if (cleanNotes) fields.notes = cleanNotes;
    const placeholder: AdminCard = {
      id: placeholderId,
      side,
      stage,
      client: cleanTitle,
      contactInitials: initialsFromTitle(cleanTitle),
      property: cleanAddress || `${province} deal`,
      nextLabel: stageLabel.title,
      pinnedTop25: false,
      completedByStage: {},
      conditions,
    };
    const request: AdminDealCreateRequest = {
      title: cleanTitle,
      side,
      province,
      currentStage: stage,
      primaryContactId: contactId,
      listingAddress: side === "listing" ? cleanAddress || null : null,
      fields,
    };
    try {
      await onCreated(placeholder, request);
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Could not create deal");
    } finally {
      setSubmitting(false);
    }
  };

  const subtypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "property_subtype")?.options ?? [];
  const listingTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "listing_type")?.options ?? [];
  const signingAuthorityOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "signing_authority")?.options ?? [];
  const transactionTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "transaction_type")?.options ?? [];

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close new deal"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 flex h-full w-full flex-col bg-card sm:h-auto sm:max-h-[calc(100vh-3rem)] sm:w-full sm:max-w-[34rem] sm:rounded-md sm:border sm:border-border"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
              New deal
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              Add a card to the board
            </h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-11 w-11 shrink-0" aria-label="Close">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground" htmlFor={`${titleId}-side`}>
              Side
            </label>
            <div id={`${titleId}-side`} role="radiogroup" className="mt-1.5 grid grid-cols-2 gap-2">
              {(["listing", "buyer"] as AdminSide[]).map((option) => {
                const active = side === option;
                const Icon = option === "listing" ? Home : Users;
                return (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSide(option)}
                    className={cn(
                      "flex min-h-11 items-center justify-center gap-2 rounded-sm border px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      active
                        ? "border-primary bg-muted text-foreground"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
                    {ADMIN_SIDE_LABELS[option].title}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label htmlFor={`${titleId}-province`} className="block text-[12px] font-medium text-muted-foreground">
                Province / territory <span className="text-destructive">*</span>
              </label>
              {setupProvince && !provinceOverride && (
                <button
                  type="button"
                  onClick={() => setProvinceOverride(true)}
                  className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Change for this deal
                </button>
              )}
              {setupProvince && provinceOverride && (
                <button
                  type="button"
                  onClick={() => {
                    setProvinceOverride(false);
                    setProvince(setupProvince);
                  }}
                  className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Reset to setup ({setupProvince})
                </button>
              )}
            </div>
            {setupProvince && !provinceOverride ? (
              <div
                id={`${titleId}-province`}
                className="mt-1.5 flex h-11 w-full items-center rounded-sm border border-border bg-muted/40 px-3 text-[0.88rem] text-foreground"
              >
                <span>{PROVINCE_LABEL_BY_CODE.get(setupProvince) ?? setupProvince}</span>
                <span className="ml-2 font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  from setup
                </span>
              </div>
            ) : (
              <select
                id={`${titleId}-province`}
                value={province}
                onChange={(e) => setProvince(e.target.value)}
                required
                className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select province</option>
                {CANADIAN_PROVINCES.map(({ code, label }) => {
                  const coverage = provinceCoverageByCode.get(code);
                  const suffix = coverage?.hasTransactionGuide ? " - full guide" : coverage ? " - reference" : "";
                  return (
                    <option key={code} value={code}>
                      {label}
                      {suffix}
                    </option>
                  );
                })}
              </select>
            )}
            {selectedProvinceCoverage && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
                </span>
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.referencePages} pages
                </span>
                {selectedProvinceCoverage.forms > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.forms} forms
                  </span>
                )}
              </div>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-contact`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Contact (optional)
            </label>
            {selectedContact ? (
              <div className="mt-1.5 rounded-sm border border-border bg-card px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[0.92rem] font-semibold text-foreground">
                      {selectedContact.displayName ?? "(unnamed)"}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.74rem] text-muted-foreground">
                      {selectedContact.primaryEmail && (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" aria-hidden />
                          <span className="truncate">{selectedContact.primaryEmail}</span>
                        </span>
                      )}
                      {selectedContact.primaryPhone && (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" aria-hidden />
                          <span>{selectedContact.primaryPhone}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <Button type="button" variant="ghost" size="sm" onClick={clearContact} className="shrink-0">
                    Change
                  </Button>
                </div>
                {(selectedContact.type || selectedContact.stage || selectedContact.sourceKey) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {selectedContact.type && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        {selectedContact.type}
                      </span>
                    )}
                    {selectedContact.stage && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        {selectedContact.stage}
                      </span>
                    )}
                    {selectedContact.sourceKey && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        src: {selectedContact.sourceKey}
                      </span>
                    )}
                  </div>
                )}
                {(selectedContact.lastActivityAt || selectedContact.ownerNotes) && (
                  <div className="mt-2 space-y-1 border-t border-border pt-2 text-[0.72rem] text-muted-foreground">
                    {selectedContact.lastActivityAt && (
                      <div className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" aria-hidden />
                        <span>last activity {isoTimeAgo(selectedContact.lastActivityAt)}</span>
                      </div>
                    )}
                    {selectedContact.ownerNotes && (
                      <div className="line-clamp-2 italic">"{selectedContact.ownerNotes}"</div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <>
                <input
                  id={`${titleId}-contact`}
                  type="text"
                  value={contactQuery}
                  onChange={(e) => setContactQuery(e.target.value)}
                  placeholder={contactsLoading ? "Loading contacts…" : "Search by name, email, phone"}
                  className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  autoComplete="off"
                />
                {contactsError && (
                  <div className="mt-1 text-[0.72rem] text-warning">{contactsError}</div>
                )}
                {filteredContacts.length > 0 && (
                  <div className="mt-1.5 max-h-48 overflow-y-auto rounded-sm border border-border bg-card">
                    {filteredContacts.map((contact) => (
                      <button
                        key={contact.id}
                        type="button"
                        onClick={() => handleSelectContact(contact)}
                        className="flex w-full items-start gap-3 border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-muted focus:outline-none focus:bg-muted"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[0.86rem] font-medium text-foreground">
                            {contact.displayName ?? "(unnamed)"}
                          </div>
                          <div className="truncate text-[0.72rem] text-muted-foreground">
                            {contact.primaryEmail ?? contact.primaryPhone ?? "no contact info"}
                          </div>
                        </div>
                        {contact.type && (
                          <span className="font-mono-ui shrink-0 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                            {contact.type}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                {!contactsLoading && contacts.length === 0 && !contactsError && (
                  <div className="mt-1 text-[0.72rem] text-muted-foreground">
                    No contacts in DB yet. Skip this field or sync your CRM first.
                  </div>
                )}
              </>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-title`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Title <span className="text-destructive">*</span>
            </label>
            <input
              id={`${titleId}-title`}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={side === "listing" ? "e.g. Lewis Creek seller" : "e.g. Tessa & Ryan"}
              required
              className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label htmlFor={`${titleId}-stage`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Starting stage
            </label>
            <select
              id={`${titleId}-stage`}
              value={stage}
              onChange={(e) => setStage(toAdminStage(Number(e.target.value)))}
              className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {ADMIN_STAGE_NUMBERS.map((s) => {
                const def = adminStageDefinition(s);
                return (
                  <option key={s} value={s}>
                    {def.stageNumber} · {def.labels[side].title}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="space-y-3 rounded-sm border border-border bg-card px-3 py-3">
            <div className="text-[12px] font-semibold text-muted-foreground">
              {side === "listing" ? "Property" : "Search"}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-address`} className="block text-[0.74rem] text-muted-foreground">
                  Listing address
                </label>
                <input
                  id={`${titleId}-address`}
                  type="text"
                  value={listingAddress}
                  onChange={(e) => setListingAddress(e.target.value)}
                  placeholder="e.g. 123 Lewis Creek Rd, Kelowna BC"
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor={`${titleId}-subtype`} className="block text-[0.74rem] text-muted-foreground">
                  Property type
                </label>
                <select
                  id={`${titleId}-subtype`}
                  value={propertySubtype}
                  onChange={(e) => setPropertySubtype(e.target.value)}
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="">— select —</option>
                  {subtypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {side === "listing" ? (
                <div>
                  <label htmlFor={`${titleId}-listing-type`} className="block text-[0.74rem] text-muted-foreground">
                    Listing type
                  </label>
                  <select
                    id={`${titleId}-listing-type`}
                    value={listingType}
                    onChange={(e) => setListingType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">— select —</option>
                    {listingTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div>
                  <label htmlFor={`${titleId}-tx-type`} className="block text-[0.74rem] text-muted-foreground">
                    Transaction type
                  </label>
                  <select
                    id={`${titleId}-tx-type`}
                    value={transactionType}
                    onChange={(e) => setTransactionType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">— select —</option>
                    {transactionTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-signing`} className="block text-[0.74rem] text-muted-foreground">
                  Signing authority
                </label>
                <select
                  id={`${titleId}-signing`}
                  value={signingAuthority}
                  onChange={(e) => setSigningAuthority(e.target.value)}
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="">— select —</option>
                  {signingAuthorityOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label htmlFor={`${titleId}-notes`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
                Notes
              </label>
              {notesAutoFilled && (
                <span className="text-[0.7rem] text-primary">
                  auto-filled from contact
                </span>
              )}
            </div>
            <textarea
              id={`${titleId}-notes`}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                if (notesAutoFilled) setNotesAutoFilled(false);
              }}
              rows={3}
              placeholder="Anything relevant to start this deal — context, urgency, source"
              className="mt-1.5 w-full rounded-sm border border-border bg-background px-3 py-2 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          {submitError && (
            <div className="rounded-sm border border-border bg-card px-3 py-2 text-[0.78rem] text-destructive">
              {submitError}
            </div>
          )}

          <div className="mt-auto flex items-center justify-end gap-2 border-t border-border pt-3">
            <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create deal
            </Button>
          </div>
        </form>
      </aside>
    </div>,
    document.body,
  );
}

function AdminKanbanBoard() {
  const adminDeals = useAdminDeals();
  const cards = adminDeals.deals;
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [activeSide, setActiveSide] = useState<AdminSide>("listing");
  const [showNewDeal, setShowNewDeal] = useState(false);
  const draggingIdRef = useRef<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const dealQuery = searchParams.get("deal");
  const handledDealQueryRef = useRef<string | null>(null);

  useEffect(() => {
    if (!dealQuery) {
      handledDealQueryRef.current = null;
      return;
    }
    if (handledDealQueryRef.current === dealQuery) return;
    const match = cards.find((c) => c.id === dealQuery);
    if (!match) return;
    handledDealQueryRef.current = dealQuery;
    setSelectedCardId(match.id);
    setActiveSide(match.side);
  }, [dealQuery, cards]);

  const clearDealQuery = useCallback(() => {
    if (!searchParams.has("deal")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("deal");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const closeDetailPanel = useCallback(() => {
    setSelectedCardId(null);
    clearDealQuery();
  }, [clearDealQuery]);

  const handleCreateDeal = useCallback(
    async (placeholder: AdminCard, request: AdminDealCreateRequest) => {
      adminDeals.addLocalDeal(placeholder);
      setActiveSide(placeholder.side);
      try {
        const created = await api.createAdminDeal(request);
        adminDeals.replaceLocalDeal(placeholder.id, created);
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals returned 404; keeping optimistic local card.");
          return;
        }
        throw err;
      }
    },
    [adminDeals],
  );

  const selectedCard = cards.find((c) => c.id === selectedCardId) ?? null;

  const buckets = useMemo(() => {
    const empty = (): Record<AdminStageNumber, AdminCard[]> => ({
      0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: [],
    });
    const byStage: Record<AdminSide, Record<AdminStageNumber, AdminCard[]>> = {
      listing: empty(),
      buyer: empty(),
    };
    const counts: Record<AdminSide, number> = { listing: 0, buyer: 0 };
    for (const card of cards) {
      byStage[card.side][card.stage].push(card);
      counts[card.side] += 1;
    }
    return { byStage, counts };
  }, [cards]);

  const handleMoveToNext = useCallback(
    (cardId: string) => {
      const card = cards.find((candidate) => candidate.id === cardId);
      const nextStage = card ? adminNextStage(card) : null;
      if (nextStage != null) void adminDeals.moveDeal(cardId, nextStage);
    },
    [adminDeals, cards],
  );

  const handleToggleItem = useCallback(
    (cardId: string, itemId: string, completed: boolean) => {
      void adminDeals.setDealToggle(cardId, itemId, completed);
    },
    [adminDeals],
  );

  const handleConditionChange = useCallback(
    (cardId: string, field: AdminConditionField, value: AdminConditionValue) => {
      void adminDeals.setDealToggle(cardId, field, value);
    },
    [adminDeals],
  );

  const handleCardDragStart = useCallback((cardId: string) => {
    draggingIdRef.current = cardId;
  }, []);

  const handleCardDrop = useCallback(
    (targetSide: AdminSide, targetStage: AdminStageNumber) => {
      const draggedId = draggingIdRef.current;
      draggingIdRef.current = null;
      if (!draggedId) return;
      const card = cards.find((candidate) => candidate.id === draggedId);
      if (!card) return;
      if (card.side !== targetSide) return; // cross-side moves not supported
      if (card.stage === targetStage) return;
      void adminDeals.moveDeal(draggedId, targetStage);
    },
    [adminDeals, cards],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2">
        <div role="status" aria-live="polite" className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
            {cards.length} admin deals
          </span>
          {adminDeals.loading && (
            <span className="inline-flex items-center gap-1 font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </span>
          )}
          {adminDeals.usingDevFallback && (
            <span className="rounded-sm border border-border bg-transparent px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-wider text-warning">
              dev-fallback
            </span>
          )}
          {adminDeals.error && (
            <span className="truncate text-[0.72rem] text-warning">{adminDeals.error}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => setShowNewDeal(true)}>
            <Plus className="h-3.5 w-3.5" />
            New deal
          </Button>
          <Button variant="outline" size="sm" onClick={() => void adminDeals.refresh()} disabled={adminDeals.loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", adminDeals.loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>
      <AdminTop25Strip
        cards={cards}
        devFallback={adminDeals.usingDevFallback}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
      />
      {!adminDeals.loading && !adminDeals.error && cards.length === 0 && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No saved transaction files yet — use New deal above, or push a qualified profile from Leads.
        </p>
      )}
      <div role="tablist" aria-label="Deal side" className="flex items-center gap-1 border-b border-border">
        {(["listing", "buyer"] as AdminSide[]).map((side) => {
          const active = activeSide === side;
          const Icon = side === "listing" ? Home : Users;
          return (
            <button
              key={side}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveSide(side)}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
              <span>{ADMIN_SIDE_LABELS[side].title}</span>
              <span
                className={cn(
                  "font-mono-ui text-[0.65rem] uppercase tracking-wider",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                {buckets.counts[side]}
              </span>
            </button>
          );
        })}
      </div>
      <AdminKanbanSwimlane
        side={activeSide}
        title={ADMIN_SIDE_LABELS[activeSide].title}
        description={ADMIN_SIDE_LABELS[activeSide].description}
        cardsByStage={buckets.byStage[activeSide]}
        totalCount={buckets.counts[activeSide]}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
        onCardDrop={handleCardDrop}
      />
      {selectedCard && (
        <AdminCardDetailPanel
          card={selectedCard}
          onClose={closeDetailPanel}
          onToggleItem={(_stage, itemId, completed) => handleToggleItem(selectedCard.id, itemId, completed)}
          onConditionChange={(field, value) => handleConditionChange(selectedCard.id, field, value)}
          onMoveToNext={() => handleMoveToNext(selectedCard.id)}
          onDealUpdated={(deal) => adminDeals.replaceLocalDeal(selectedCard.id, deal)}
        />
      )}
      {showNewDeal && (
        <NewDealDialog onClose={() => setShowNewDeal(false)} onCreated={handleCreateDeal} />
      )}
    </div>
  );
}

export function RealEstateAdminPage() {
  const data = useRealEstateHubData();
  const adminSetup = useAdminSetup();
  useHubHeader("Admin", data);
  useEffect(() => {
    if (!adminSetup.setup?.complete) return;
    let cancelled = false;
    (async () => {
      try {
        const [cronDefaults, actionDefaults] = await Promise.all([
          api.ensureLaneCronJobs(DEFAULT_ADMIN_AUTOMATIONS),
          api.ensureDefaultAdminActions(),
        ]);
        const changedCronDefaults = cronDefaults.created.length + (cronDefaults.updated?.length ?? 0);
        const changedActionDefaults = actionDefaults.created.length + (actionDefaults.updated?.length ?? 0);
        if (!cancelled && (changedCronDefaults > 0 || changedActionDefaults > 0)) {
          await data.refresh();
        }
      } catch {
        // Best-effort defaults. Existing cron jobs still render, and the Cron
        // page/action registry can create these manually if the backend is unavailable.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adminSetup.setup?.complete, data.refresh]);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ADMIN_WORKFLOW_KEYWORDS),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ADMIN_WORKFLOW_KEYWORDS),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Admin"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Admin check", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Admin workflow", FileCheck2)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Admin Desk"
      icon={BriefcaseBusiness}
      title="Admin"
    >
      <WorkflowStrip
        items={[
          {
            icon: Building2,
            label: "Admin sessions",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Nightly checks", value: jobs.length },
          {
            icon: FileCheck2,
            label: "Active workflows",
            value: activeSessions.length,
          },
          {
            icon: CheckCircle2,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      {adminSetup.loading && (
        <div className="rounded-md border border-border bg-card px-4 py-5 text-[0.86rem] text-muted-foreground">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          Loading Admin setup
        </div>
      )}
      {adminSetup.error && (
        <div className="rounded-md border border-border bg-card px-4 py-3 text-[0.84rem] text-warning">
          {adminSetup.error}
        </div>
      )}
      {!adminSetup.loading && adminSetup.setup && !adminSetup.setup.complete && (
        <AdminSetupLaunch setup={adminSetup.setup} onSetupUpdated={adminSetup.setSetup} />
      )}
      {!adminSetup.loading && adminSetup.setup && !adminSetup.setup.complete && (
        <TimedTasks jobs={jobs} empty="No admin/document schedules are installed yet." title="Admin automations" />
      )}
      {!adminSetup.loading && adminSetup.setup?.complete && (
        <>
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/admin/templates" className="inline-flex">
          <Button variant="outline" size="sm">
            <FileCheck2 className="h-3.5 w-3.5" />
            Templates
          </Button>
        </Link>
      </div>
      <AdminKanbanBoard />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Admin action board"
          empty="No admin actions are waiting yet. CMA, seller-update, listing contract, signing, and listing/deal sessions will appear here."
        />
        <TimedTasks jobs={jobs} empty="No admin/document schedules yet." title="Admin automations" />
      </div>
      <RecentSessions
        title="Admin work"
        sessions={sessions}
        empty="No admin-specific sessions found yet. CMA, seller updates, listing contract, signing packages, WebForms, and listing/deal cron work will land here."
      />
        </>
      )}
    </HubShell>
  );
}
