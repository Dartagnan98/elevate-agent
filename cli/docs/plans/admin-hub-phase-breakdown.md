# Admin Hub — Phase Breakdown (Cheat Sheet)

Quick reference for what each kanban column means, when a card enters,
when it exits, and what checklist items live inside.

Two lanes (Seller, Buyer) of 5 phases each + an Other lane.

---

## SELLER LANE — 5 phases

### S1 · CMA  *(maps to formal Phase 1)*
**Enter:** CMA delivered or actively being prepared.
**Exit → Pre-Listing:** seller verbally agrees to list.

Checklist:
- Draft CMA follow-up message
- Send pricing recap to seller
- Track seller objections + questions
- Identify info needed before listing paperwork
- Prepare listing intake request

---

### S2 · Pre-Listing  *(formal Phases 2 + 3 — Intake + MLC)*
**Enter:** seller committed, paperwork begins.
**Exit → Marketing:** MLC signed + property ready to go live.

Checklist:
- Collect legal names + address
- Confirm listing price + commission + dates
- Document included/excluded items + possession
- Pull title
- Organize photos / floorplan / video schedule
- Fill MLC + required forms
- Send DigiSign envelope
- Confirm all signatures received

---

### S3 · Marketing & Showings  *(formal Phases 4 + 5 — Launch + Active Mgmt)*
**Enter:** listing live on MLS.
**Exit → Under Contract:** offer accepted.

Checklist:
- Draft MLS remarks + public description
- Feature sheet copy
- Social posts queued
- Email blast sent
- Open house scheduled
- Weekly ShowingTime + market digest sent

---

### S4 · Under Contract / SkySlope  *(formal Phases 6 + 7 — Offer + Heartbeat)*
**Enter:** offer accepted.
**Exit → Closing:** subjects off + lawyer engaged.

Checklist (transaction heartbeat):
- Offer summary prepared
- Subject removal deadline tracked
- Deposit landed in trust
- Inspection scheduled
- Lawyer / conveyancer engaged
- SkySlope missing-doc list cleared
- Completion + possession dates locked

---

### S5 · Closing & Gift  *(formal Phase 8 — Completion + Post-Close)*
**Enter:** subjects removed, deal firm.
**Exit → archive:** possession + 30 days.

Checklist:
- Completion checklist complete
- Key handoff coordinated
- Closing gift ordered + sent
- Thank-you / review / referral drafts queued
- Anniversary reminder added
- Moved into past-client nurture

---

## BUYER LANE — 5 phases

### B1 · Walkthrough  *(formal Phases 1 + 2 — Intake + Search)*
**Enter:** buyer agrees to showings.
**Exit → Showing Follow-up:** at least one showing complete.

Checklist:
- Buyer profile (budget, financing, areas, beds, must-haves)
- MLS / Lofty search filter built
- Property shortlist + ranked-fit
- Showing route + itinerary
- Preview notes per property

---

### B2 · Showing Follow-up  *(formal Phases 3 + 4 — Follow-Up + Offer Prep)*
**Enter:** showings underway.
**Exit → Under Contract:** offer written + accepted.

Checklist:
- Per-showing follow-up draft
- Feedback summary (liked / disliked / dealbreakers)
- Buyer criteria updated
- Comparable sales pulled
- CPS input checklist + offer strategy

---

### B3 · Under Contract / SkySlope  *(formal Phases 5 + 6 — Offer + Subject Removal)*
**Enter:** offer accepted.
**Exit → Subjects Off:** all subjects removed + deposit confirmed.

Checklist:
- Lender paperwork sent
- Inspection booked
- Accepted-offer checklist run
- Doc list (CPS, addenda, disclosures, deposit receipt)
- Insurance deadline tracked
- Strata review (if applicable)
- Deposit due date tracked
- Lawyer / conveyancer info captured
- SkySlope missing-doc list cleared

---

### B4 · Subjects Off  *(formal Phase 6 tail)*
**Enter:** final subject window closing.
**Exit → Moving / Possession:** lawyer instructed + completion within ~10 days.

Checklist:
- All subjects removed
- Deposit received
- Completion + possession dates locked
- Final docs forwarded to lawyer

---

### B5 · Moving / Possession  *(formal Phases 7 + 8 — Completion + Post-Close)*
**Enter:** lawyer engaged, possession on calendar.
**Exit → archive:** possession + 30 days.

Checklist:
- Completion checklist complete
- Final walkthrough scheduled
- Utility / change-of-address reminder sent
- Key handoff coordinated
- Closing gift sent
- Thank-you / review / referral drafts queued
- One-week-after follow-up scheduled
- Anniversary reminder added

---

## OTHER LANE

### O · Misc
For one-offs that don't fit Seller/Buyer: agent referrals, LOOs without
listing, lease placements, investor intros, paperwork favors.

Checklist:
- Define scope of one-off task
- Capture agreement / referral fee
- Mark complete + log outcome

---

## Cross-Cutting

### TOP 25 (pinned strip)
Manually-pinned focus list. Cards stay in their phase column; the strip
is a filter pin, not a duplicate.

---

## Phase → Formal Phase Mapping

| Lane   | Kanban column          | Formal phases (from `admin-hub-seller-buyer-phases.md`) |
|--------|------------------------|------------------------------------------------------------------|
| Seller | CMA                    | 1 — Post-CMA conversion                                          |
| Seller | Pre-Listing            | 2 — Intake + 3 — MLC / Listing Paperwork                         |
| Seller | Marketing & Showings   | 4 — Launch + 5 — Active Listing Mgmt                             |
| Seller | Under Contract         | 6 — Offer Mgmt + 7 — Transaction Heartbeat                       |
| Seller | Closing & Gift         | 8 — Completion / Post-Close                                      |
| Buyer  | Walkthrough            | 1 — Walkthrough Intake + 2 — Search + Showing Plan               |
| Buyer  | Showing Follow-up      | 3 — Showing Follow-Up + 4 — Offer Prep                           |
| Buyer  | Under Contract         | 5 — Offer / Negotiation + 6 — Accepted Offer / Subject Removal   |
| Buyer  | Subjects Off           | 6 tail — final subject removal                                   |
| Buyer  | Moving / Possession    | 7 — Completion + 8 — Post-Close                                  |
| Other  | Misc                   | (none — catch-all)                                               |

---

## Where this lives in the UI

- Columns render at `/admin` via `AdminKanbanBoard` in `web/src/pages/RealEstateHubPages.tsx`.
- Per-phase checklist items are defined in `ADMIN_PHASE_CHECKLISTS` in the same file.
- Each card opens a side panel showing all 5 phases for its lane as
  collapsible dropdowns; current phase auto-expanded with editable
  checkboxes; past phases collapsed (✓ if complete); future phases
  collapsed and previewable.
- When the current phase hits 100%, panel header shows a "Move card →"
  pill that advances the card to the next column.
