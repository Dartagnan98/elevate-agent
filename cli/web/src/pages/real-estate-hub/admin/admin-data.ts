// Seed data for the Elevation Agent admin board.
// Ported from /tmp/elevate-design/src/admin-data.jsx — will be replaced with real API data.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PipelinePhase = {
  id: string;
  stage: string;
  name: string;
  next: string;
  note?: string;
  motion?: string;
  hint?: string;
};

export type Deal = {
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
  top25Note?: string;
};

export type BuyerDeal = {
  id: string;
  side: "buyer";
  phase: string;
  addr: string;
  line2: string;
  badge: string;
  progress: string;
  next: string;
  blocked?: boolean;
  primary?: boolean;
  top25Note?: string;
};

export type AdminAction = {
  id: string;
  kind: "review" | "resume";
  title: string;
  desc: string;
  schedule?: string;
  next?: string;
  session?: string;
};

export type AdminAutomationStatus =
  | "error"
  | "scheduled"
  | "blocked"
  | "optional";

export type AdminAutomation = {
  id: string;
  name: string;
  status: AdminAutomationStatus;
  schedule: string;
  nextRun: string;
  detail: string;
};

export type WorkItem = {
  id: string;
  title: string;
  session: string;
  tools: number;
};

export type Showing = {
  id: string;
  time: string;
  address: string;
  client: string;
  kind: "showing" | "open-house";
};

export type PhaseDetail = {
  motion: string;
  movesOn: string;
  gate: string;
  checklist: string[];
  documents: [string, string][];
};

export type ConditionEnum = {
  id: string;
  label: string;
};

// ---------------------------------------------------------------------------
// Listing pipeline S0-S10
// ---------------------------------------------------------------------------

export const ADMIN_PIPELINE: PipelinePhase[] = [
  { id: "pre-cma",    stage: "S0",  name: "Pre-CMA",                  next: "pre-CMA Google Form complete + Lofty contact verified",      note: "automated · approval" },
  { id: "cma",        stage: "S1",  name: "CMA / Evaluation",         next: "CMA PDF/evaluation complete + client says yes",              note: "automated + background · approval" },
  { id: "intake",     stage: "S2",  name: "Listing Intake",           next: "MLC intake complete + listing docs ready",                  note: "automated · approval" },
  { id: "skyslope",   stage: "S3",  name: "SkySlope & Matrix Prep",   next: "signed docs saved + SkySlope/Matrix prep complete",         note: "automated + background · approval" },
  { id: "go",         stage: "S4",  name: "Marketing Go",             next: "photos cleaned/saved + Marketing Go package ready",         note: "automated + background · approval" },
  { id: "live",       stage: "S5",  name: "Listing Live / Marketing", next: "Flodesk mailout sent",                                     note: "automated + background · approval" },
  { id: "offer",      stage: "S6",  name: "Accepted Offer",           next: "accepted-offer dates verified",                            note: "automated + background · approval" },
  { id: "conditions", stage: "S7",  name: "Condition Removal",        next: "conditions removed + deposit verified",                    note: "automated + background · approval" },
  { id: "closed",     stage: "S8",  name: "Closed",                   next: "file closed + nurture queued",                             note: "automated + background" },
];

// ---------------------------------------------------------------------------
// Buyer pipeline S0-S10
// ---------------------------------------------------------------------------

export const ADMIN_BUYER_PIPELINE: PipelinePhase[] = [
  { id: "offer",        stage: "S0",  name: "Offer Prep",          motion: "manual", next: "Moves on offer package ready",            hint: "Comps + offer paperwork" },
  { id: "accepted",     stage: "S1",  name: "Accepted",            motion: "manual", next: "Moves on accepted-offer checked",         hint: "Lender + docs" },
  { id: "conditions",   stage: "S2",  name: "Condition Removal",   motion: "manual", next: "Moves on conditions removed",             hint: "Inspection + property review + deposit" },
  { id: "closed",       stage: "S4",  name: "Closed",              motion: "manual", next: "Moves on file archived",                  hint: "Archive + nurture" },
];

// ---------------------------------------------------------------------------
// Listing deals by phase (d1-d15)
// ---------------------------------------------------------------------------

export const ADMIN_DEALS: Deal[] = [
  { id: "d1",  phase: "pre-cma",    addr: "Demo Listing 202601",                         line2: "123 Sample Lane, Vancouver, BC",                   badge: "Pre-CMA",                 progress: "0/3", next: "Pre-CMA Google Form filled" },
  { id: "d2",  phase: "pre-cma",    addr: "Demo Listing 202602",                         line2: "610 Sample Drive, Kelowna, BC",                    badge: "Pre-CMA",                 progress: "0/3", next: "Pre-CMA Google Form filled" },
  { id: "d3",  phase: "live",       addr: "11-7155 Sample Drive, Kamloops, BC",           line2: "11-7155 Sample Drive, Kamloops, BC",               badge: "Listing Live / Marketing", progress: "3/5", next: "Flodesk mailout sent",       price: "$349,900", mls: "DEMO10378689", blocked: true, primary: true },
  { id: "d4",  phase: "live",       addr: "1232 Harbour Street #1403, Kelowna, BC",       line2: "1232 Harbour Street #1403, Kelowna, BC",           badge: "Listing Live / Marketing", progress: "0/5", next: "Just listed blast sent" },
  { id: "d5",  phase: "live",       addr: "1127 Cedar Street, Kamloops, BC",              line2: "1127 Cedar Street, Kamloops, BC",                  badge: "Listing Live / Marketing", progress: "0/5", next: "Just listed blast sent" },
  { id: "d6",  phase: "live",       addr: "17-750 Ridge Drive, Kamloops, BC",             line2: "17-750 Ridge Drive, Kamloops, BC",                 badge: "Listing Live / Marketing", progress: "3/5", next: "Flodesk mailout sent" },
  { id: "d7",  phase: "live",       addr: "703-525 Market Street, Kamloops, BC",          line2: "703-525 Market Street, Kamloops, BC",              badge: "Listing Live / Marketing", progress: "3/5", next: "Flodesk mailout sent" },
  { id: "d8",  phase: "live",       addr: "1872 Valley Crescent, Kamloops, BC",           line2: "1872 Valley Crescent, Kamloops, BC",               badge: "Listing Live / Marketing", progress: "1/5", next: "Lofty text blast sent" },
  { id: "d9",  phase: "live",       addr: "1836 Greenway Avenue #43, Kamloops, BC",       line2: "1836 Greenway Avenue #43, Kamloops, BC",           badge: "Listing Live / Marketing", progress: "0/5", next: "Just listed blast sent" },
  { id: "d10", phase: "conditions", addr: "Lot 3 Ridge Place, Powell River, BC",          line2: "Lot 3 Ridge Place, Powell River, BC",              badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
  { id: "d11", phase: "conditions", addr: "460 Market St #801, Kamloops, BC",             line2: "460 Market St #801, Kamloops, BC",                 badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
  { id: "d12", phase: "conditions", addr: "1616 Hillcrest Avenue, Kamloops, BC",          line2: "1616 Hillcrest Avenue, Kamloops, BC",              badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
  { id: "d13", phase: "conditions", addr: "610 Sample Drive, Kamloops, BC",               line2: "610 Sample Drive, Kamloops, BC",                   badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
  { id: "d14", phase: "conditions", addr: "815 Demo Drive, Kamloops, BC",                 line2: "815 Demo Drive, Kamloops, BC",                     badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
  { id: "d15", phase: "conditions", addr: "1121 Builder Way, Kamloops, BC",               line2: "1121 Builder Way, Kamloops, BC",                   badge: "Condition Removal",                          next: "Condition removal / waiver sent" },
];

// ---------------------------------------------------------------------------
// Buyer deals (b1-b4)
// ---------------------------------------------------------------------------

export const ADMIN_BUYER_DEALS: BuyerDeal[] = [
  { id: "b1", side: "buyer", phase: "offer",  addr: "Priya Devi — buyer track",     line2: "Looking: Brock area, $550–650K, 2BR+",   badge: "Offer Prep",   progress: "2/4", next: "Offer package ready" },
  { id: "b2", side: "buyer", phase: "offer", addr: "Marcus Greene — buyer track",   line2: "Looking: Sahali/Aberdeen, $700K+, 3BR",       badge: "Offer Prep", progress: "1/3", next: "Offer package ready" },
  { id: "b3", side: "buyer", phase: "offer", addr: "Sam & Rosie — buyer track",     line2: "Couple, first-time buyers, $400–500K",   badge: "Offer Prep",       progress: "0/2", next: "Offer package ready" },
  { id: "b4", side: "buyer", phase: "offer",  addr: "Linda Hayworth — buyer track",  line2: "Repeat client, $850K range",                   badge: "Offer Prep",   progress: "3/4", next: "Comps pulled, awaiting client sign-off", blocked: true },
];

// ---------------------------------------------------------------------------
// Admin action board (review + resume items)
// ---------------------------------------------------------------------------

export const ADMIN_ACTIONS: AdminAction[] = [
  { id: "ar1", kind: "review", title: "Admin review: Hot Leads Watcher",        desc: "Run the outreach skill in monitor mode. Scan every connected source (Lofty CRM, Apple Messages, Gmail, SMS, social via Composio) for hot signals since the last run: inbound replies, viewing requests, repeat opens, CRM stage moves, listing alerts. Re-score heat across the inbox and surface the top 10 hottest leads. For any lead with a brand-new inbound message that needs a reply, draft a same-channel response and queue it for approval. Do not send.", schedule: "0 8 * * *" },
  { id: "ar2", kind: "review", title: "Admin review: Social Content Engine",    desc: "Run the social-content-engine skill (weekly content engine for the connected real estate agent). Steps: 1. Pull last-30-day post metrics from every connected social platform (Instagram, TikTok, YouTube, Facebook, LinkedIn) using the bundled native fetchers. 2. Aggregate + rank with scripts/aggregate.py. 3. Research current real-estate content trends in the agent’s market via the last30days skill. 4. Read inbox + CRM signals with scripts/read_signals.py to ground ideas in real client questions. 5. Generate 5–10…", next: "unknown" },
  { id: "ar3", kind: "review", title: "Admin review: Gmail Doc Router",         desc: "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, match listing documents to active Elevation deals with deal-matcher, file documents to the correct Drive folder, and write artifacts/checklist evidence back to the deal with admin-result-writer. Do not send messages.", next: "16d ago" },
  { id: "ar4", kind: "resume", title: "Admin workflow: WEBForms transaction setup", desc: "Open WEBForms, authenticate with the configured account, and create the transaction shell.", session: "tui · 13h ago" },
  { id: "ar5", kind: "resume", title: "Admin workflow: Go into webforms and create a transaction", desc: "Go into webforms and create a transaction", session: "tui · 11h ago" },
  { id: "ar6", kind: "resume", title: "Admin workflow: Go into webforms and create a transaction", desc: "Go into webforms and create a transaction", session: "tui · 13h ago" },
  { id: "ar7", kind: "resume", title: "Admin workflow: Go into webforms and create a transaction", desc: "Go into webforms and create a transaction", session: "tui · 14h ago" },
  { id: "ar8", kind: "resume", title: "Admin workflow: Go into webforms and create a transaction", desc: "Go into webforms and create a transaction", session: "tui · 14h ago" },
];

// ---------------------------------------------------------------------------
// Right-rail automations (different from sidebar automations in data.ts)
// ---------------------------------------------------------------------------

export const ADMIN_AUTOMATIONS: AdminAutomation[] = [
  { id: "au1", name: "Hot Leads Watcher",     status: "error",     schedule: "0 8 * * *",    nextRun: "Error",        detail: "Failed to compute next run for recurring schedule (is the 'croniter' package installed in the gateway's Python env?)" },
  { id: "au2", name: "Social Content Engine",  status: "scheduled", schedule: "0 7 * * 1",    nextRun: "Next unknown", detail: "" },
  { id: "au3", name: "Gmail Doc Router",       status: "blocked",   schedule: "0 9 * * 1",    nextRun: "Next 16d ago", detail: "Admin setup incomplete: enable after Gmail, Drive, CRM/deal matching, and admin-result-writer callback are verified." },
  { id: "au4", name: "Seller Update",          status: "blocked",   schedule: "0 16 * * 1-5", nextRun: "Next 19d ago", detail: "Admin setup incomplete: enable after ShowingTime/BrokerBay access, Gmail draft lane, deal matching, and result callback are…" },
  { id: "au5", name: "Market Stats Watcher",   status: "optional",  schedule: "0 7 * * 1",    nextRun: "Next 16d ago", detail: "Optional market-memory automation, not a core transaction-stage mover. Enable after regional market inputs are configured." },
];

// ---------------------------------------------------------------------------
// Work log
// ---------------------------------------------------------------------------

export const ADMIN_WORK: WorkItem[] = [
  { id: "aw1", title: "WEBForms transaction setup",                                                  session: "tui · 13h ago · 1 messages",   tools: 8 },
  { id: "aw2", title: "Go into webforms and create a transaction",                                        session: "tui · 11h ago · 418 messages", tools: 202 },
  { id: "aw3", title: "Go into webforms and create a transaction",                                        session: "tui · 13h ago · 23 messages",  tools: 18 },
  { id: "aw4", title: "Go into webforms and create a transaction",                                        session: "tui · 14h ago · 2 messages",   tools: 8 },
  { id: "aw5", title: "Go into webforms and create a transaction",                                        session: "tui · 14h ago · 1 messages",   tools: 8 },
  { id: "aw6", title: "MLS Per-Listing Engagement — owner_agent=Outreach, surfaces:…",          session: "tui · 18h ago · 26 messages",  tools: 12 },
];

// ---------------------------------------------------------------------------
// Upcoming showings
// ---------------------------------------------------------------------------

export const ADMIN_SHOWINGS: Showing[] = [
  { id: "sh1", time: "Today · 4:30 PM",    address: "1232 Harbour Street #1403, Kelowna", client: "Marcus G.",         kind: "showing" },
  { id: "sh2", time: "Tomorrow · 10:00 AM", address: "11-7155 Sample Drive, Kamloops",     client: "Priya + Dev Patel", kind: "showing" },
  { id: "sh3", time: "Tomorrow · 2:15 PM",  address: "17-750 Ridge Drive, Kamloops",       client: "Linda Hayworth",    kind: "showing" },
  { id: "sh4", time: "Wed · 11:00 AM",      address: "1872 Valley Crescent, Kamloops",     client: "Sam & Rosie",       kind: "open-house" },
  { id: "sh5", time: "Thu · 5:00 PM",       address: "1127 Cedar Street, Kamloops",        client: "James Okafor",      kind: "showing" },
];

// ---------------------------------------------------------------------------
// Phase details (listing)
// ---------------------------------------------------------------------------

export const ADMIN_PHASE_DETAILS: Record<string, PhaseDetail> = {
  "pre-cma": {
    motion: "automated · approval",
    movesOn: "pre-CMA Google Form complete + Lofty contact verified",
    gate: "confirm missing contact/form details",
    checklist: ["Pre-CMA Google Form filled", "Lofty contact verified / created", "Client/property notes saved for CMA"],
    documents: [["PNC", "Privacy Notice & Consent Form"], ["lockbox-auth", "Lockbox Acknowledgement, Consent, Release, and Indemnity"]],
  },
  "cma": {
    motion: "automated · approval",
    movesOn: "CMA PDF/evaluation complete + client says yes",
    gate: "approve CMA/evaluation before client delivery",
    checklist: ["CMA PDF / evaluation ready", "Pricing story approved", "Client said yes to listing"],
    documents: [["fee-service-agreement", "Fee for Service Agreement"], ["disc-of-remuneration", "Disclosure of Remuneration"], ["disc-seller-remuneration", "Disclosure to Seller of Expected Remuneration"], ["ELC", "Exclusive Listing Contract"], ["MLC", "Multiple Listing Contract"]],
  },
  "intake": {
    motion: "automated + background · approval",
    movesOn: "MLC intake complete + listing docs ready",
    gate: "approve docs/signature placements before signing send",
    checklist: ["MLC intake triggered", "Missing listing fields surfaced", "Listing docs/signature placements ready for approval"],
    documents: [["disc-conflict-interest", "Disclosure Regarding Conflict of Interest Between Clients"], ["disc-interest-buying", "Disclosure of Interest in Trade - Buying/Selling"], ["PDS-res", "Property Disclosure Statement - Residential"], ["PNDS", "Property No-Disclosure Statement (PNDS)"]],
  },
  "skyslope": {
    motion: "automated + background · approval",
    movesOn: "signed docs saved + SkySlope/Matrix prep complete",
    gate: "approve Matrix draft before publish",
    checklist: ["Signed listing docs saved to Drive", "SkySlope file created / synced", "Matrix listing started", "Matrix missing fields surfaced"],
    documents: [],
  },
  "go": {
    motion: "automated · approval",
    movesOn: "photos cleaned/saved + Marketing Go package ready + Matrix photos uploaded",
    gate: "answer Marketing Go/photo questions and approve launch assets before external publishing",
    checklist: ["Marketing Go started after SkySlope/Matrix prep", "Photographer Google Drive/photo link received or requested", "Marketing Go questions answered / blockers surfaced", "Photo cleanup complete", "Cleaned photos saved to listing Google Drive folder", "Best 99 Matrix photos selected if photographer sent more than 99", "Photos uploaded to Matrix/Xposure", "Marketing package ready for approval"],
    documents: [],
  },
  "live": {
    motion: "automated + background · approval",
    movesOn: "offer accepted",
    gate: "approve outgoing drafts",
    checklist: ["Just listed blast sent", "Social posts published", "Flodesk mailout sent", "Lofty text blast sent", "Live marketing checklist complete"],
    documents: [["general-release", "General Release & Authorization to Pay Deposit Funds"], ["CPS-addendum", "CPS - Addendum/Amendment"], ["CPS-res", "Contract of Purchase and Sale (CPS) - Residential"]],
  },
  "offer": {
    motion: "automated + background · approval",
    movesOn: "accepted-offer dates verified",
    gate: "review offer terms",
    checklist: ["Contract reviewed within 24 hours", "Accepted-offer checklist email sent", "FINTRAC details captured", "Calendar dates added", "Moving checklist sent", "Accepted-offer admin verified"],
    documents: [["listing-amendment", "Listing Amendment (various types)"]],
  },
  "conditions": {
    motion: "automated + background · approval",
    movesOn: "conditions removed + deposit verified",
    gate: "confirm condition removal",
    checklist: ["Condition removal / waiver sent", "Title charges verified", "Property disclosure docs received", "Lawyer info requested", "Conditions removed / waived"],
    documents: [],
  },
  "closing": {
    motion: "automated + background · approval",
    movesOn: "closing package complete",
    gate: "confirm closing package",
    checklist: ["Lawyer / conveyancer package sent", "Down payment to trust", "Mortgage instructions received", "Insurance binder confirmed", "Client signed at lawyer", "Funds released", "Closing admin verified"],
    documents: [],
  },
  "closed": {
    motion: "automated · approval",
    movesOn: "file closed + nurture queued",
    gate: "approve closeout",
    checklist: ["Commission submitted", "SkySlope deal closed", "Sold update sent", "Closing gift sent", "Review requested", "Closed file archived"],
    documents: [],
  },
};

// ---------------------------------------------------------------------------
// Phase details (buyer)
// ---------------------------------------------------------------------------

export const ADMIN_BUYER_PHASE_DETAILS: Record<string, PhaseDetail> = {
  "intake": {
    motion: "manual",
    movesOn: "profile verified",
    gate: "confirm buyer profile + budget",
    checklist: ["Buyer profile (budget, financing, areas, beds, must-haves)", "MLS / Lofty search filter built"],
    documents: [["PNC", "Privacy Notice & Consent Form"], ["lockbox-auth", "Lockbox Acknowledgement, Consent, Release, and Indemnity"]],
  },
  "search": {
    motion: "manual",
    movesOn: "search criteria ready",
    gate: "confirm property shortlist + ranked-fit",
    checklist: ["Property shortlist + ranked-fit", "Showing route + itinerary", "Preview notes per property"],
    documents: [["fee-service-agreement", "Fee for Service Agreement"], ["buyer-acknowledgement", "Buyer Agency Acknowledgement"], ["BAEC", "Buyer Agency Exclusive Contract"], ["buyer-ack-info", "Buyer's Acknowledgement of Information - Recommended Conditions"], ["fee-agreement-seller-pays", "Fee Agreement - Seller Pays"], ["notice-seller-assignment-terms", "Notice to Seller of Assignment of Terms"], ["disc-of-remuneration", "Disclosure of Remuneration"], ["disc-seller-remuneration", "Disclosure to Seller of Expected Remuneration"]],
  },
  "tours": {
    motion: "manual",
    movesOn: "showing notes complete",
    gate: "confirm showing feedback captured",
    checklist: ["Per-showing follow-up draft", "Feedback summary (liked / disliked / dealbreakers)"],
    documents: [["disc-conflict-interest", "Disclosure Regarding Conflict of Interest Between Clients"], ["disc-interest-buying", "Disclosure of Interest in Trade - Buying/Selling"], ["disc-interest-lease", "Disclosure of Interest in Trade - Leasing/Renting"], ["disc-referral-payment", "Disclosure of Referral Payment"], ["disc-referral-received", "Disclosure of Referral Payment Received"], ["disc-unrep", "Disclosure of Risks to Unrepresented Parties"], ["PDS-res", "Property Disclosure Statement - Residential"], ["PNDS", "Property No-Disclosure Statement (PNDS)"]],
  },
  "followup": {
    motion: "manual",
    movesOn: "follow-up complete",
    gate: "approve follow-up + offer-prep strategy",
    checklist: ["Buyer criteria updated", "Comparable sales pulled", "Offer document checklist + strategy"],
    documents: [],
  },
  "offer": {
    motion: "manual",
    movesOn: "offer package ready",
    gate: "approve offer package before submission",
    checklist: ["Lender paperwork sent", "Accepted-offer checklist run", "Doc list (offer, addenda, disclosures, deposit receipt)"],
    documents: [],
  },
  "accepted": {
    motion: "manual",
    movesOn: "accepted-offer checklist complete",
    gate: "confirm post-acceptance setup",
    checklist: ["Inspection booked", "Insurance deadline tracked", "Strata / condo review (if applicable)"],
    documents: [],
  },
  "conditions": {
    motion: "manual",
    movesOn: "conditions tracked",
    gate: "confirm condition status before subjects-off",
    checklist: ["Deposit due date tracked", "Lawyer / conveyancer info captured", "SkySlope missing-doc list cleared"],
    documents: [["general-release", "General Release & Authorization to Pay Deposit Funds"], ["assign-new-dev", "Assignment of Contract of Purchase and Sale - New Development"], ["CPS-addendum", "CPS - Addendum/Amendment"], ["CPS-nothird", "CPS - Leasehold in First Nations - 3rd Party Approval Not Required"], ["CPS-yesthird", "CPS - Leasehold in First Nations - 3rd Party Approval Required"], ["CPS-manu-addendum", "CPS - Manufactured Home - Addendum"], ["CPS-manu", "CPS - Manufactured Home on a Rental Site"], ["CPS-res", "Contract of Purchase and Sale (CPS) - Residential"]],
  },
  "removed": {
    motion: "manual",
    movesOn: "conditions removed",
    gate: "confirm subjects-off + deposit",
    checklist: ["All conditions removed / waived", "Deposit received", "Completion + possession dates locked"],
    documents: [["listing-amendment", "Listing Amendment (various types)"]],
  },
  "closing": {
    motion: "manual",
    movesOn: "closing checklist complete",
    gate: "confirm closing package",
    checklist: ["Final docs forwarded to lawyer", "Completion checklist complete", "Final walkthrough scheduled"],
    documents: [],
  },
  "possession": {
    motion: "manual",
    movesOn: "possession follow-up queued",
    gate: "confirm handoff complete",
    checklist: ["Utility / change-of-address reminder sent", "Key handoff coordinated", "Closing gift sent", "Thank-you / review / referral drafts queued", "One-week-after follow-up scheduled", "Anniversary reminder added"],
    documents: [],
  },
  "buyer-closed": {
    motion: "manual",
    movesOn: "file archived",
    gate: "approve archive",
    checklist: ["Buyer file archived"],
    documents: [],
  },
};

// ---------------------------------------------------------------------------
// Condition enums (dropdown fields)
// ---------------------------------------------------------------------------

export const ADMIN_CONDITION_ENUMS: ConditionEnum[] = [
  { id: "signing-authority", label: "Signing authority" },
  { id: "fintrac-form",     label: "FINTRAC form type" },
  { id: "listing-track",    label: "Listing track" },
  { id: "property-subtype", label: "Property subtype" },
  { id: "estate-status",    label: "Estate status" },
  { id: "transaction-type", label: "Transaction type" },
  { id: "listing-type",     label: "Listing type" },
];

// ---------------------------------------------------------------------------
// Condition toggles (boolean fields)
// ---------------------------------------------------------------------------

export const ADMIN_CONDITION_TOGGLES: string[] = [
  "PEP",
  "Tenanted",
  "POA signing",
  "Corporate",
  "Has suite",
  "Multiple offers",
  "Family member",
  "Dual representation",
  "Unrepresented other side",
  "Lockbox",
  "Delayed offer",
  "Sale of buyer's property",
];
