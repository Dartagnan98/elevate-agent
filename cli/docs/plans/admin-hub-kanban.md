# Admin Hub — Kanban Model

Reconciles `admin-hub-seller-buyer-phases.md` (formal 8+8 phases)
with the pilot realtor's whiteboard sketch (Buyer Admin / Seller Admin / TOP 25 / Other items).

The Admin Hub is **not** a CRM replacement. It starts after intent is real:
- **Seller:** after CMA.
- **Buyer:** after they agree to walkthroughs/showings.

Lead gen, nurture, cold outreach, and unqualified inquiries belong in `/leads`, not here.

---

## Board Layout

Two parallel swimlanes (Seller, Buyer), plus two cross-cutting bins.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TOP 25  (pinned active clients across both lanes — the pilot realtor's focus list)│
├──────────────────────────────────────────────────────────────────────────┤
│ SELLER ADMIN                                                              │
│  CMA → Pre-Listing → Marketing & Showings → Under Contract → Closing/Gift│
├──────────────────────────────────────────────────────────────────────────┤
│ BUYER ADMIN                                                               │
│  Walkthrough → Showing Follow-up → Under Contract → Subjects Off →       │
│  Moving / Possession                                                      │
├──────────────────────────────────────────────────────────────────────────┤
│ Other Items  (one-offs that don't fit a lane: referrals, agent help, etc)│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Seller Columns (5)

Each column maps to one or two phases from the formal plan.

### 1. CMA
**Maps to:** Phase 1 — Post-CMA Seller Conversion
**Enters when:** CMA delivered or actively being prepared.
**Card actions:**
- Draft CMA follow-up
- Pricing recap
- Track objections
- Identify missing info before listing paperwork

**Exits to Pre-Listing when:** seller agrees to list (verbal commitment).

### 2. Pre-Listing
**Maps to:** Phase 2 — Listing Intake + Phase 3 — MLC / Listing Paperwork
**Whiteboard items:** prep paper · pull title · organize photos
**Card actions:**
- Listing intake checklist (legal names, address, price, commission, dates, included/excluded items, possession, tenancy, strata, showing instructions, lockbox, photo timing)
- Pull title
- Fill MLC + required forms
- Send DigiSign envelope
- Track signatures

**Exits to Marketing when:** MLC signed + property ready to go live.

### 3. Marketing & Showings
**Maps to:** Phase 4 — Listing Launch + Phase 5 — Active Listing Management
**Whiteboard items:** open house · email blast · weekly seller update
**Card actions:**
- MLS remarks + public description
- Feature sheet copy
- Photo/video/floorplan checklist
- Social posts + email campaign
- ShowingTime feedback weekly digest
- Market activity summary
- Pricing/action recommendation

**Exits to Under Contract when:** offer accepted.

### 4. Under Contract / SkySlope
**Maps to:** Phase 6 — Offer Management + Phase 7 — Accepted Offer / Transaction Heartbeat
**Whiteboard items:** SkySlope missing list
**Sub-checklist on each card (transaction heartbeat):**
- Offer summary
- Subject removal deadline
- Deposit status
- Inspection timing
- Document delivery
- Lawyer/conveyancer coordination
- Completion date
- Possession date
- SkySlope missing-doc list

**Exits to Closing when:** subjects off + lawyer engaged.

### 5. Closing & Gift
**Maps to:** Phase 8 — Completion / Post-Close
**Whiteboard items:** organize gift · closing
**Card actions:**
- Completion checklist
- Possession/key instructions
- Closing gift coordination
- Thank-you / review / referral drafts
- Move into past-client nurture
- Anniversary reminder

---

## Buyer Columns (5)

### 1. Walkthrough
**Maps to:** Phase 1 — Buyer Walkthrough Intake + Phase 2 — Search + Showing Plan
**Card actions:**
- Buyer profile (names, budget, financing status, areas, property type, beds/baths, must-haves, dealbreakers, timeline)
- MLS/Lofty search filter
- Property shortlist + ranked-fit
- Showing route + itinerary
- Preview notes

**Exits to Showing Follow-up when:** at least one showing complete.

### 2. Showing Follow-up
**Maps to:** Phase 3 — Showing Follow-Up + Phase 4 — Offer Prep
**Card actions:**
- Per-showing follow-up draft
- Feedback summary (liked/disliked/dealbreakers/price comfort)
- Updated criteria
- Possible-offer flag
- Comparable sales pull
- CPS input checklist
- Offer strategy notes

**Exits to Under Contract when:** offer written + accepted.

### 3. Under Contract / SkySlope
**Maps to:** Phase 5 — Offer / Negotiation + Phase 6 — Accepted Offer / Subject Removal
**Whiteboard items:** lender paperwork sent? · inspection booked? · accepted offer checklist · doc list · SkySlope missing list
**Sub-checklist on each card:**
- Lender paperwork sent (date)
- Inspection booked (date)
- Accepted offer checklist
- Doc list (CPS, addenda, disclosures, deposit receipt)
- Insurance deadline
- Strata review deadline
- Deposit due date
- Lawyer/conveyancer info
- SkySlope missing-doc list

**Exits to Subjects Off when:** all subjects removed + deposit confirmed.

### 4. Subjects Off
**Maps to:** Phase 6 tail — final subject removal
**Card actions:**
- Confirm all subjects removed
- Confirm deposit received
- Lock completion + possession dates
- Forward final docs to lawyer

**Exits to Moving / Possession when:** lawyer instructed + completion within ~10 days.

### 5. Moving / Possession
**Maps to:** Phase 7 — Completion / Possession + Phase 8 — Post-close
**Whiteboard items:** moving checklist · follow-up a week (nurture)
**Card actions:**
- Completion checklist
- Final walkthrough coordination
- Utility / change-of-address reminders
- Key handoff
- Closing gift
- Thank-you / review / referral drafts
- One-week-after follow-up
- Anniversary reminder

---

## Cross-Cutting Bins

### TOP 25 (pinned)
the pilot realtor's focus list. Manually pinned cards across both lanes — the 25 (or N)
clients she's actively driving this week. Cards still live in their phase
column; TOP 25 is a filter pin, not a duplicate.

### Other Items
Catch-all for transactions that don't fit Seller or Buyer flow:
- Agent-to-agent referrals
- Letters of opinion (no listing)
- Lease placements
- Investor introductions
- One-off paperwork favors

---

## Card Schema

```ts
type AdminCard = {
  id: string;                    // contact_id or transaction_id
  lane: "seller" | "buyer" | "other";
  column: SellerColumn | BuyerColumn | "other";
  client: {
    name: string;
    phone?: string;
    email?: string;
    contact_id: string;          // links to /leads + Lofty
  };
  property?: {
    address?: string;
    mls?: string;
    price?: number;
  };
  next_deadline?: {              // shown bold on card
    label: string;               // "Subject removal", "Inspection", "Completion"
    date: string;                // ISO
    days_out: number;
  };
  checklist: {                   // column-specific
    total: number;
    done: number;
    next_item?: string;          // shown as "Next: ..."
  };
  pinned_top25: boolean;
  last_touched: string;          // ISO — drives column-tail "stale" warning
  ai_drafts_pending: number;     // links into /leads draft queue
};
```

---

## Column Transition Rules

Movement is **manual** by pilot realtor (drag-and-drop) but the system **suggests
the next column** based on signals:

| From | To | Suggested when |
|---|---|---|
| Seller CMA | Pre-Listing | CMA marked delivered + verbal commitment in conversation |
| Seller Pre-Listing | Marketing | DigiSign envelope completed for MLC |
| Seller Marketing | Under Contract | Lofty stage = "Under Contract" or accepted-offer event |
| Seller Under Contract | Closing | Subjects-off date passes + completion <10 days |
| Buyer Walkthrough | Showing Follow-up | First showing logged |
| Buyer Showing Follow-up | Under Contract | Accepted-offer event |
| Buyer Under Contract | Subjects Off | Subject removal date passes |
| Buyer Subjects Off | Moving / Possession | Completion <10 days |
| Any closing column | (archive) | Possession date passes + 30 days |

pilot realtor always confirms the move. The system never auto-advances a card.

---

## Data Sources

| Field | Source |
|---|---|
| Client info | `contacts.jsonl` (Lofty sync) |
| Lofty stage | `lead-events.jsonl` |
| Showings | ShowingTime (manual until eXp API) |
| Offer events | Conversation parser → `lead-events.jsonl` |
| Documents | DigiSign / SkySlope (manual until APIs unblocked) |
| Deadlines | Card-level state, edited inline by pilot realtor |
| Drafts | `tasks.jsonl` (lead_follow_up + admin task types) |
| Transaction guide | `~/client-tools/knowledge/exp-agent-centre/transaction-guide-bc/` (referenced inline by checklist) |

---

## Build Order (matches phase doc's recommended order)

1. **Static board layout** — read-only kanban, seeded from contacts.jsonl with manually-set column field. *(this PR)*
2. **Seller CMA → Pre-Listing checklist UI** — first interactive column.
3. **MLC / Listing Paperwork lane** — DigiSign envelope tracking.
4. **Active Listing Updates lane** — ShowingTime pull + weekly digest.
5. **Transaction Heartbeat (shared Under Contract column logic)** — deadlines, reminders.
6. **Buyer Walkthrough → Showing Plan** — search criteria, route builder.
7. **Buyer Offer + Subject Removal** — feeds into shared heartbeat engine.

---

## Out of Scope (handled elsewhere)

- Lead capture / qualification → `/leads`
- AI draft generation → `/leads` autopilot
- Calendar / showing-time scheduling → `/today`
- Past-client nurture campaigns → `/leads` after card archives
- Brokerage compliance docs → Brivity / SkySlope direct, mirrored read-only here
