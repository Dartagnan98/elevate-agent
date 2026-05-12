# Admin Hub — BC Guide × Elevate Skills Gap Analysis

Cross-references BC's `transaction-guide-bc/` content + the pilot realtor's PCS scripts
against Elevate's existing skills/cron/UI to identify what should auto-launch
during each Admin Hub kanban phase, and where the gaps are.

**Settings model:** Province is a backend setting. pilot realtor = BC. When other
provinces onboard, the same kanban + checklist scaffolding hot-swaps the BC
content for `transaction-guide-ab/`, `-on/`, etc. (already normalized to the
same layout — see `~/client-tools/scripts/normalize-province-layout.cjs`.)

---

## Section A — BC Guide Inventory

### 12 Checklists

| Checklist | Type | Key Forms |
|---|---|---|
| listing-for-sale | Seller / MLS | MLC, PDS-res, FINTRAC, disc-of-remuneration |
| listing-for-sale-exclusive | Seller / Exclusive | ELC, PDS-res, privacy notice |
| listing-for-sale-conditionals | Seller / Conditional | MLC + condition addendums |
| listing-for-rent | Landlord / Rental | lease-res, tenant disclosures |
| listing-assignment | Seller / Assignment | listing-amendment, notice-seller-assignment-terms |
| purchase-residential | Buyer / MLS purchase | CPS-res, BAEC, PDS-res |
| purchase-residential-conditionals | Buyer / Conditional offer | CPS-res + addendums |
| purchase-pre-construction | Buyer / Pre-construction | CPS-nothird / CPS-yesthird, deposit schedule |
| purchase-assignment | Buyer / Assignment | assign-new-dev |
| referral | Referral | disc-referral-payment, disc-referral-received |
| letter-of-opinion | Agent service | LOO standard form |
| rental-placement | Tenant placement | lease-res, tenant-agency-contract, fee-agreement-landlord-pays |

### 21 Best-Practices Topics → Phase Surfacing

- **Inspections** → B2 (offer prep) + B3 (subject removal)
- **Strata / condo resale** → B3 (strata review)
- **Probate / estate sales** → S1 (pricing) + S2 (POA forms)
- **FSBO** → S2 (intake)
- **Oil tanks · Radon** → B2 (inspection conditions)
- **Tenants** → S2 (occupied listings)
- **GST · all-about-taxes** → S4/S5 + B5 (closing)
- **Foreclosures** → S1 (pricing strategy)
- **Mobile / manufactured / modular** → property-type fork at S2 / B1
- **First Nations land** → pre-offer due diligence
- **Power of attorney / corporate clients** → S2 (signing setup)
- **Pre-construction · new construction · assignments** → dedicated lanes
- **Land assembly** → offer strategy
- **Cottage / recreational** → property-type specialty
- **Commission practices** → all phases
- **Multiple / referential offers** → S3
- **Single-family resale · condo resale** → general reference

### 36 Form Folders

- **Listing (5):** MLC, ELC, lockbox-auth, colist-joint, colist-separate
- **Purchase (7):** CPS-res, CPS-addendum, CPS-manu, CPS-nothird, CPS-yesthird, PDS-res, assign-new-dev
- **Disclosure / consent (6):** PNDS, PNC, disc-conflict-interest, disc-interest-buying, disc-of-remuneration, privacy
- **Buyer rep (4):** BAEC, buyer-ack-info, buyer-acknowledgement, buyer-advisement
- **Other (14):** lease-res, fee agreements, listing-amendment, notice-seller-assignment-terms, tenant-agency-contract, etc.

`forms/inventory.json` already carries name + category + description + page count + image URLs for each form — this is **directly usable as a UI form picker**.

---

## Section B — Existing Elevate Capabilities

| Capability | Path | Phase fit |
|---|---|---|
| Lofty CRM sync | `cli/elevate_cli/source_connectors.py → sync_lofty_crm_source()` | All phases (contact + activity backbone) |
| AI draft generation (LLM) | `cli/elevate_cli/template_suggester.py` | S1, S3, S5, B2, B5 (any draft) |
| Fallback draft templates | `cli/elevate_cli/source_connectors.py → _fallback_draft_for_thread()` | All inbound threads |
| Cron / scheduled jobs | `cli/cron/` (`jobs.py`, `scheduler.py`) | Mid-phase recurring (digests, reminders) |
| Skill catalog (30+) | `cli/skills/` | Composable per-phase actions |
| `lead-scorer` skill | `cli/skills/lead-scorer/` | B1 (gates Walkthrough lane entry) |
| `outreach-lanes` skill | `cli/skills/outreach-lanes/` | All seller/buyer drafting |
| `social-content-engine` | `cli/skills/social-content-engine/` | S3 (Marketing posts) |
| Admin Hub kanban UI | `cli/web/src/pages/RealEstateHubPages.tsx` (`AdminKanbanBoard`, `ADMIN_PHASE_CHECKLISTS`) | All — already shipped |
| PCS leads scraper | `~/client-tools/scripts/pcs-leads-scraper.cjs` | B1 entry (Xposure → Lofty hot-buyer pipeline) |
| PCS hot-leads analyzer | `~/client-tools/scripts/pcs-hot-leads-analyzer.cjs` | B1 (auto-score, set Lofty stage) |
| PCS hot-leads PDF | `~/client-tools/scripts/pcs-hot-leads-pdf.cjs` | B1 (weekly report) |

**Confirmed gaps:** no CMA generator, no MLC/DigiSign integration, no SkySlope API, no ShowingTime API, no inspection scheduler, no lender notifier, no per-showing feedback capture.

---

## Section C — Per-Phase Launch Points + Gaps

Legend: ✅ have it · 🟡 partial · ❌ gap

### S1 · CMA
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters S1 | Generate CMA follow-up draft | ❌ | checklist-listing-for-sale.md (pricing) |
| Card enters S1 | Pull pricing recap + comparables summary | ❌ | best-practices/foreclosures, probate-estate-sales |
| Mid-phase | Seller-conversion nudge if no commitment in 7d | ❌ | Phase 1 |

### S2 · Pre-Listing
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters S2 | MLC pre-fill skeleton from contact + property | ❌ | checklist-listing-for-sale.md, forms/MLC/README.md |
| Card enters S2 | Queue DigiSign envelope (MLC + PDS-res + FINTRAC + disc-remuneration) | ❌ | listing checklist required-docs |
| Card enters S2 | Trigger title pull task | ❌ | listing checklist |
| Property = strata | Inject strata-resale best-practice checklist | ❌ | best-practices/residential-condo-resale.md |
| Property = occupied | Inject tenants best-practice checklist | ❌ | best-practices/tenants.md |
| 24h before MLC due | Reminder + missing-docs check | ❌ | implicit |
| DigiSign envelope sent | Poll signature status, escalate if stalled | ❌ | implicit |

### S3 · Marketing & Showings
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters S3 | Draft MLS remarks + public description | ❌ | listing checklist (Marketing) |
| Card enters S3 | Queue social posts (`social-content-engine` skill) | 🟡 skill exists, not wired | best-practices/single-family-residential-resale |
| Mon 9am Pacific | Weekly ShowingTime + market digest | ❌ ShowingTime API gap | listing checklist |
| Multiple offers received | Inject multiple-and-referential-offers playbook | ❌ | best-practices/multiple-and-referential-offers.md |
| Offer accepted | Auto-suggest move to S4 | 🟡 (Move card → pill exists, but no offer-event trigger) | Phase 6 |

### S4 · Under Contract / SkySlope
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters S4 | Create SkySlope deal record from MLC + offer | ❌ | Phase 6-7 |
| Card enters S4 | Generate offer summary + subject-removal deadline card | ❌ | listing checklist |
| Card enters S4 | Notify lawyer/conveyancer with checklist | ❌ | listing checklist |
| Subject removal -7d | Reminder + inspection-doc check | ❌ | best-practices/inspections.md |
| Deposit confirmed | Update deal status, ping seller | ❌ | listing checklist |
| Daily | Poll SkySlope missing-docs list, escalate to lender/lawyer | ❌ | SkySlope is brokerage of record |

### S5 · Closing & Gift
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters S5 | Generate thank-you + review request + referral draft | 🟡 templater exists, no transaction context | Phase 8 |
| Possession date | Schedule key-handoff coordination email | 🟡 cron exists, not transaction-aware | listing checklist |
| Possession date + 30d | Auto-archive card, move to past-client nurture (Lofty stage flip) | ❌ | listing checklist |
| Anniversary | Auto-fire 1yr reminder | 🟡 cron infra exists | implicit |

### B1 · Walkthrough
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| PCS hot-lead detected | Auto-create B1 card from `pcs-hot-leads-analyzer.cjs` | ❌ wiring gap (script writes to Lofty, not to Admin Hub) | purchase-residential intake |
| Card enters B1 | Buyer profile intake form (budget, areas, financing pre-check) | ❌ | purchase-residential checklist |
| Card enters B1 | Build MLS / Lofty search filter from buyer profile | 🟡 Lofty sync reads saved searches; no auto-filter generation | purchase-residential checklist |
| Card enters B1 | Generate showing route + itinerary | ❌ | purchase-residential checklist |
| Property type = pre-construction / mobile / FN land | Inject corresponding best-practice checklist | ❌ | best-practices/pre-construction-condos, mobile-manufactured-modular-home, first-nations-land |

### B2 · Showing Follow-up
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Showing logged | Per-showing follow-up draft + feedback capture form | ❌ no showing-event capture | Phase 3-4 |
| Buyer feedback received | Synthesize summary + update buyer criteria | ❌ | Phase 3-4 |
| Card enters B2 | Pull comparable sales for top property | ❌ | purchase-residential checklist |
| Possible-offer flag set | Inject offer-strategy playbook | ❌ | best-practices/multiple-and-referential-offers |

### B3 · Under Contract / SkySlope
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters B3 | Create SkySlope deal from CPS + buyer info | ❌ | Phase 5-6 |
| Card enters B3 | Send lender paperwork checklist | ❌ | purchase-residential checklist |
| Card enters B3 | Schedule inspection + draft inspection-condition clause | ❌ | best-practices/inspections, oil-tanks, radon |
| Property = strata | Trigger strata review checklist | ❌ | best-practices/residential-condo-resale |
| Insurance deadline -5d | Reminder + draft confirmation email | ❌ | purchase-residential checklist |
| Deposit due -2d | Escalate if not received | ❌ | purchase-residential checklist |
| All subjects removed | Auto-suggest move to B4 | 🟡 manual move pill exists | Phase 6 |

### B4 · Subjects Off
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters B4 | Confirm subjects + deposit checklist | 🟡 manual checklist only | Phase 6 tail |
| Card enters B4 | Generate lawyer instruction package | ❌ | Phase 6 tail |

### B5 · Moving / Possession
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters B5 | Thank-you / review / referral drafts | 🟡 templater exists, not transaction-aware | Phase 7-8 |
| Card enters B5 | Utility / change-of-address reminder draft | ❌ | Phase 7-8 |
| Possession date | Key handoff email | 🟡 cron + email infra exists | Phase 7-8 |
| Possession +7d | One-week-after follow-up | 🟡 cron infra exists | Phase 7-8 |
| Possession +30d | Auto-archive + past-client nurture | ❌ | Phase 8 |

### Other / Misc
| Trigger | Action | Status | BC ref |
|---|---|---|---|
| Card enters | Scope + referral fee agreement intake | ❌ | checklist-referral.md, disc-referral-payment |
| Card complete | Log outcome to past-client nurture | ❌ | implicit |

---

## Top 5 Build Priority (by operator impact)

1. **S2 → MLC pre-fill + DigiSign trigger.** Auto-fill MLC from contact + property data, queue DigiSign envelope, watch signature status. BC guide already has the entire required-docs list and form structure — this is wiring, not content. **Saves 2–3 hours per listing intake.**

2. **S4 / B3 → SkySlope deal record + missing-docs watcher.** Auto-create SkySlope deal from MLC (seller) or CPS (buyer); daily poll the missing-docs list; escalate to lawyer/lender when docs due. Highest transaction-coordination risk. **Saves 4–5 hours per deal.**

3. **B1 → PCS hot-lead → Admin Hub auto-spawn.** PCS scraper already runs and updates Lofty; missing piece is creating a B1 card in the kanban with the saved-search criteria pre-loaded. Pure wiring on top of existing scripts. **Closes the loop on a pipeline that already runs daily.**

4. **S3 → Weekly ShowingTime + market digest cron.** Mondays 9am Pacific. ShowingTime API integration is a true new build, but the cron infra + email drafting are ready. **Frees up 30 min/week per active listing and gives sellers a real heartbeat.**

5. **S1 → CMA follow-up + seller-conversion nudge.** LLM draft engine ready; needs CMA-context capture (price, comps, last-touch date) and a 7-day-no-commit auto-nudge. **Lifts CMA→listing conversion ratio.**

---

## Province-portability note

All BC content (checklists, best-practices, forms inventory) is already present
for AB, SK, MB, ON, QC, NB, NL, YT in matching layout. The Admin Hub should
read from `transaction-guide-{province}/` based on a workspace-level province
setting. Per-phase auto-launches stay the same; only the doc references and
form picker swap.
