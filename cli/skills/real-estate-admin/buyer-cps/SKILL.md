---
name: buyer-cps
requires_onboarding: [forms_provider]
description: Prepare a buyer-side Contract of Purchase and Sale (CPS) draft, never sent for signature. Use when a buyer-side Admin card enters Offer Prep, or the realtor asks to prepare a CPS / offer paperwork for a buyer; collects offer terms, opens WEBForms/TransactionDesk, and routes missing fields to human approval before signing or sending. Not for accepted-offer/collapse handling — use offer-review or collapse-sale instead.
metadata:
  elevate:
    tags: [real-estate, admin, buyer, offer, cps, webforms, contract]
    runtime:
      approval_required: true
---

# Buyer CPS


<!-- FILING VERIFICATION GATE — insert verbatim at the TOP of every accepted-offer /
     document-filing skill (offer-review, listing-accepted-offer, buyer-cps). Identical
     block in each, so the rule is guaranteed-present whenever the skill loads. This is
     the SKILL-layer fix for recall starvation: critical verification rules must be
     front-loaded and ENFORCED via a machine-checkable artifact, not buried in prose or
     left to probabilistic memory recall.
     v2 — hardened after adversarial review against a real 11-class failure
     corpus. Every "should" that isn't backed by an artifact field was removed; the
     `status: passed` predicate now spans signatures, parties, terms, identity, and
     persistence, and only the sub-checks for surfaces THIS task actually touches apply. -->

## ⛔ FILING VERIFICATION GATE — run FIRST, and never claim done without it

MANDATORY before any document is selected, filled, uploaded, filed, sent, or treated as
accepted, and before any calendar event, status change, checklist mark, or client send.
Build the `verification` artifact below, attach it to the deal, and include it in the
output contract. **Never report done / fixed / accepted / firm / sold / uploaded / sent
unless `verification.status == "passed"`.** "Passed" means every sub-check for the
surfaces this task touched is satisfied with recorded evidence. If any required check
cannot be satisfied with visible evidence, STOP and return `waiting_human` with the
exact blocker. Apply only the sub-checks relevant to what this task actually does (a
draft-only run skips the persistence sub-check; a run that doesn't touch included/excluded
items skips that sub-check) — but you may not skip a sub-check for a surface you DID touch.

1. **Side.** State SELLER-side (the realtor represents the seller / her own listing) or BUYER-side
   (the realtor represents the buyer). Every template, checklist, and email is side-specific.

2. **Active transaction.** Confirm you are on the ACTIVE, non-cancelled transaction — never
   the first/cancelled search result. Record its id and the observed status (e.g. Incomplete,
   NOT Canceled/App).

3. **Parties from the contract body.** Read the CPS body (not the signature block) and list
   every named buyer and every named seller, with the page where they are named. Then list
   any party currently on the file / SkySlope header that is NOT in the current CPS — those
   are stale/collapsed-sale leftovers (e.g. an old buyer from a cancelled deal) and must be
   removed; they may not remain.

4. **Execution per party, per required page (visual).** Render the signature/initial pages
   (pdftoppm / contact sheet) and visually confirm — text extraction shows printed names
   even when the line is blank, so OCR/vision the actual marks. For EVERY named party,
   record which initial pages are required vs which are present, and whether the signature
   is present. A document is fully executed only when, for every named party, required
   initial pages == present initial pages AND signature is present. Reject any version
   missing a party's marks. An emailed PDF is not a signed envelope; subjects like "Signing
   complete" / "Envelope completed" are NOT proof.

5. **Acceptance.** A CPS is accepted only when BOTH sides have fully executed and a Section 28
   final-acceptance date exists. Buyer-signed-only is a PENDING seller-signature package, not
   an accepted offer — handle it as a draft/handoff and stop. (This is true regardless of
   which side the realtor represents — side controls the template, not whether seller execution
   is required.)

6. **Select exactly one** fully-executed document that passed 3–5. If none passes, STOP
   (`waiting_human`). Never file, forward, upload, email, or otherwise send a partially-executed CPS unless the realtor explicitly asks for a partial/draft copy and the response labels it as partial.

7. **Template/checklist matches side** (only if you send a checklist/email or mark a
   checklist). The selected Mailjet template / checklist must match the side from step 1
   (seller-side → the Seller Accepted Offer template, not a buyer checklist). Record the
   template id/name and that it matches the side.

8. **Terms transcribed verbatim** (only if you fill contract terms). Copy included items and
   excluded items from the CPS exactly as listed, under the heading each appears under — do
   NOT merge, normalize, or infer which list an item belongs to. Record each with its
   section reference. Same discipline for price, deposit, and dates.

9. **Agent/brokerage identity** (only if you fill agent/office fields). Each agent line's
   office address / license / contact must belong to the agent NAMED on that line — never
   paste one agent's office address under a different agent's name. Add required dates next
   to each signature/initial line; add a signature only where that party actually signs.

10. **Persistence — verify the write, not the exit code** (only if you wrote/uploaded
    anything). After every write/upload, RE-READ the actual persisted value (portal row
    status, attached filename / HFFileName, the field value after reload) — a browser script
    can report failure when the row advanced, or success when nothing persisted. Record
    observed vs expected per write. No "done/uploaded/filed/sent" claim is allowed unless
    every write this run performed has a verified read-back.

### Required artifact: `verification`

```json
{
  "side": "seller|buyer",
  "active_transaction_id": "",
  "transaction_status_observed": "",
  "party_count_basis": "<CPS page where buyers/sellers are named>",
  "named_buyers": ["..."],
  "named_sellers": ["..."],
  "stale_parties_to_remove": [],
  "parties": [
    {"name": "", "role": "buyer|seller",
     "initials_pages_required": [], "initials_pages_present": [],
     "signature_present": false, "evidence_render_path": ""}
  ],
  "both_sides_executed": false,
  "final_acceptance_date": null,
  "selected_document": "",
  "candidates_rejected": [{"file": "", "reason": ""}],
  "checklist_template_selected": null,
  "checklist_template_matches_side": null,
  "included_items": [{"item": "", "cps_section_ref": ""}],
  "excluded_items": [{"item": "", "cps_section_ref": ""}],
  "inclusions_exclusions_verified_against_page": null,
  "agent_identity": [{"role": "listing|cooperating|reviewer", "name": "", "office_address": "", "matches_named_agent": null}],
  "persistence_checks": [{"target": "", "expected": "", "observed": "", "verified": false}],
  "status": "passed|failed|pending",
  "blocker": ""
}
```

**`status: passed` requires ALL of:**
- `side` set; `active_transaction_id` set and `transaction_status_observed` is a
  non-cancelled status; `stale_parties_to_remove` empty (or each has a matching verified
  removal in `persistence_checks`).
- `named_buyers`/`named_sellers` transcribed from `party_count_basis` (contract body).
- For every party: `initials_pages_present` == `initials_pages_required` AND
  `signature_present: true`, each with an `evidence_render_path`.
- `both_sides_executed: true` AND `final_acceptance_date` non-null.
- Exactly one `selected_document`.
- IF a checklist/email is involved: `checklist_template_matches_side: true`.
- IF included/excluded terms were filled: `inclusions_exclusions_verified_against_page: true`.
- IF agent/office fields were filled: every `agent_identity[].matches_named_agent: true`.
- IF anything was written/uploaded: every `persistence_checks[].verified: true`.

Otherwise `failed`/`pending` → `waiting_human` with `blocker`. Sub-checks for surfaces this
task did NOT touch are not required (leave their fields null), but you may not skip a
sub-check for a surface you did touch.

---

Use this skill when a buyer-side Admin card enters **Offer Prep** or when the realtor asks to prepare a Contract of Purchase and Sale / CPS / offer paperwork for a buyer.

This skill prepares a **draft** CPS package only. Never send, sign, submit, or file the CPS without a separate explicit human approval step.

Critical form-source rule: use the official/current approved form source that the realtor provides or that is already in the system. If the realtor exports/downloads the real WEBForms PDFs and emails them to herself, treat those exported PDFs as the operative approved form artifacts and fill only the missing fields on those PDFs. Do not generate or send a custom CPS layout, PDF-first term sheet, AI-made contract, or substitute draft as the CPS. In exact Realtor Beta, the bundled BC province pack is reference-only and current versions are explicitly unverified: obtain the licensed blank through the live-verified forms provider or brokerage library, and never use a mutable local pack/register by itself as proof of currency or authorization. Stable may use the realtor's maintained local approved-forms pack/register only when it has a clean current template and tested fill mapping. For mobile/manufactured homes on rental sites, use the approved WEBForms/BCREA **CPS Manufactured Home on Rental Site** / mobile-home CPS template and manufactured-home addendum/clause pack when required. If the required licensed blank cannot be acquired and verified, stop at `form_update_needed` / `waiting_human`; do not fall back to a custom layout.

## Trigger Context

Admin action runs should pass:

- `deal_id`
- `side=buyer`
- Offer Prep stage identity from the live Admin board, not memory. As of the rebuilt buyer pipeline this is usually `currentStage=1` / Offer Prep (`0=Hot Leads`, `1=Offer Prep`, `2=Accepted Offer`, `3=Condition Removal`, `4=Closed`). Older memory may incorrectly call Offer Prep stage 4; verify with `admin_deal(action="show")` or `deals_overview` before moving.
- Any known buyer names, property address, MLS number, offer terms, subjects, deposit, dates, inclusions/exclusions, and notes from the deal fields or `extraToggles`.

If the realtor asks to “find or create” the buyer deal/contact, run `deals_overview` first and search contacts/deals before creating anything. If a matching buyer deal exists in Hot Leads and the request is explicitly Offer Prep, move it to Offer Prep with `admin_deal(action="move", to_stage=1)` rather than creating a duplicate. Then persist recovered offer terms with `admin_deal(action="set_fields")`, attach the draft artifacts, and re-read attachments/deal state before reporting completion.

## Pre-Draft Question Gate

Before any CPS population starts, gather the offer terms from the current user message, deal fields, recent conversation/session context, attached ID/document images, and prior artifacts. Do **not** ask the realtor to repeat terms that are present in the current conversation or recoverable from the deal/session/files. If required terms are still missing after that retrieval pass, ask the realtor for only the missing offer terms in one compact prompt.

Ask for missing:

1. Buyer legal name(s).
2. Property address.
3. Offer price.
4. Deposit amount.
5. Completion date.
6. Possession date and possession time, if known.
7. Adjustment date.
8. Subject removal deadline.
9. Subjects/conditions to include.
10. Included items, if any.
11. Excluded items, if any.

Default deposit timing on all CPS drafts: **deposit payable upon subject removal**. Ask for the deposit amount, but do not ask for a different timing unless the realtor volunteers one.

## Required Inputs Before Drafting

Do not guess these. If missing after the pre-draft question gate, write a `waiting_human` result with one concise prompt asking for the missing fields.

1. Buyer legal name(s).
2. Property address.
3. Offer price.
4. Deposit amount. Timing defaults to upon subject removal.
5. Completion date.
6. Possession date and possession time, if known.
7. Adjustment date.
8. Subjects/conditions and subject removal deadline.
9. Included/excluded items, if any.

Seller names, seller realtor, and seller brokerage should be pulled from the MLS listing after searching the property address and importing/listing data. Only ask the realtor for those if MLS/WEBForms cannot retrieve them.

## Standard BC Buyer Offer Defaults

Use only as draft defaults and flag for review:

- Exact Realtor Beta source of truth: the current licensed blank acquired through the live-verified forms provider or brokerage library. The bundled BC catalog and any mutable local register are reference aids only and cannot prove form currency. Stable retains its maintained local approved-forms library behavior. A provider MFA block is a `waiting_human` condition, never permission to bypass the source gate.
- Role: Selling Agent / buyer side.
- Form selection uses a base-form + clause-pack model:
  - CPS Residential for regular freehold/single-family and most strata residential offers.
  - CPS Manufactured Home on Rental Site for mobiles/manufactured homes on pad/rental site.
  - Other CPS base forms only when transaction/property type requires them.
- Clause/condition pack selection is separate from the base form:
  - single-family/freehold buyer subjects
  - strata buyer subjects, often using the same CPS Residential base but with strata-document/Form B/bylaw/minutes/insurance/budget/depreciation-report review clauses
  - manufactured/mobile-home buyer subjects, including park approval/tenancy assignment, park rules/site tenancy agreement, MHR, CSA/electrical, pad rent, permits/BIR where applicable
  - cash/subject-free or other variants only when the realtor confirms terms
- Deposit timing: payable upon subject removal.
- Addendum/subject forms: include only when terms require them.
- Signing/send policy: `draft_only` until the realtor approves.

## MLS Search + Listing Document Capture

When the realtor provides a property address and MLS number is not already known:

1. Search the property address in AOIR Xposure/Matrix.
2. Identify the active listing and save the MLS number to the deal.
3. Pull/import the listing details needed for the CPS, including seller name(s), listing realtor, listing realtor brokerage, property identifiers, legal description/PID when available, taxes, strata details, included appliances/items, and listing remarks/facts.
4. Open the listing's Documents tab.
5. Download/save every relevant listing document attached there into the Admin deal package, because those documents are part of what the realtor sends to the buyer.
6. Attach each downloaded listing document to the Admin deal with kind `buyer_listing_document` or a more specific kind when clear, such as `property_disclosure_statement`, `title`, `strata_docs`, `floor_plan`, `form_b`, or `listing_supplement`.
7. Verify file paths, document count, and document names before marking the document capture complete.

## Workflow

1. Match the Admin deal using `deal_id` first. Verify side is buyer and stage is Offer Prep or user explicitly requested buyer CPS prep.
2. Pull source-of-truth deal context from Admin database/API.
3. Run the pre-draft question gate before populating the CPS.
4. Extract known CPS fields from deal fields, the realtor's answers, notes, top25 notes, buyer criteria, conversation snippets, and attached MLS/property docs.
5. Search/import MLS listing data from the property address when the MLS number is missing, then save the MLS number and listing-party details to the deal.
6. Save listing Documents-tab attachments to the Admin deal package.
7. Select the approved CPS base form source. Priority order:
   - Actual WEBForms/TransactionDesk exported PDFs that the realtor provided by Gmail/download.
   - A current clean WEBForms/TransactionDesk export you can access directly.
   - Stable only: the realtor's local approved-forms pack/register when `data/forms/local-approved-forms-register.json` and the blank/template path confirm the required clean current form and tested fill mapping. Exact Realtor Beta must not use this fallback without a live-verified provider acquisition of the licensed blank.
8. Select the approved clause pack by property type and offer scenario, then draft the CPS Residential, CPS Manufactured Home on Rental Site, or other required base form as applicable. For mobile/manufactured-home-on-rental-site offers, use the mobile/manufactured-home CPS plus manufactured-home rental-site addendum, not a residential CPS.
9. If the realtor has emailed/downloaded actual WEBForms PDFs, fill the missing fields directly onto those PDFs instead of rebuilding the package from local images or a new layout. Preserve WEBForms-entered values unless they are clearly incomplete or the realtor asked to change them. Use text extraction plus visual spot checks to identify blanks, then overlay only the missing values. Merge the filled CPS, addendum, remuneration/disclosure, and any other actual exported forms into one clean review copy.
10. Save/download an editable draft PDF when possible, or save a local draft artifact. If the required official/current form or clause pack is missing/unverified, stop at `waiting_human` / `form_update_needed` rather than substituting an unapproved layout.
11. Create or update a Google Drive review folder/link, or another preview link, for the draft paperwork and include that review link in the user-facing result so the realtor can open the draft immediately.
11. Attach the draft artifact to the Admin deal.
11. Add checklist update `cps_draft=true` only after a transaction or PDF draft is verified.
12. Create next tasks for realtor review, missing terms, and signing-package prep once approved.

## Actual WEBForms PDF Fill Recovery

Use this when WEBForms/browser access is blocked but the realtor downloads the actual WEBForms forms and emails them to herself.

1. Search Gmail for recent self-sent attachments using property/form terms, for example `from:me to:me has:attachment newer_than:1d (<street-name> OR <civic-number> OR CPS OR mobile)`.
2. Download the attachments into the deal/offer folder, preserving filenames. Confirm the actual forms are present, such as CPS, manufactured-home addendum, Disclosure of Remuneration, DORT, etc.
3. Use `pdfinfo` and `pdftotext`/PyMuPDF to identify which fields WEBForms already populated and which are blank. For image-based PDFs or layout uncertainty, render the relevant pages with `pdftoppm` and use `vision_analyze` for visual spot checks.
   - Deposit amounts are legal/compliance fields. If text extraction shows a blank/uncertain deposit line but the Admin deal card has a deposit amount, do not assume the PDF is correct. Render the CPS page and visually confirm the deposit field. If still blank, overlay the verified Admin/source deposit amount onto the actual WEBForms PDF and record the source used.
   - Disclosure of Remuneration is not ready if the commission amount/method of calculation or payer/from field is blank. Verify cooperating commission from MLS/Xposure or another explicit source before filling. If no reliable source is available, stop as `waiting_human` with the exact missing remuneration wording instead of creating/sending a signing envelope.
4. Fill only the missing fields by overlaying text on the actual WEBForms PDFs. Do **not** rebuild the package in a new layout, do not use annotated guide pages, and do not overwrite existing WEBForms-populated values unless the user asked for a correction.
   - Preserve the original form lines. Do not draw white rectangles or cover blank lines to make space unless you are deliberately redacting/replacing an incorrect existing value. Light text overlays should sit on/just above the existing blank lines so the output still looks like the WEBForms form.
   - Before placing inclusions/exclusions, visually locate the `INCLUDING:` and `EXCLUDING:` labels on the form page. Appliances/items the realtor says are included must go on the first blank after `INCLUDING:`, never the `EXCLUDING:` line.
   - If a field was already filled by WEBForms, such as seller name or subject dates, leave it alone unless it is wrong. Adding duplicate text over an existing value makes the review copy look messy and untrustworthy.
5. For manufactured-home CPS packages, use listing/MHR/source docs to fill registration details where missing: MHR registration number, serial number, CSA/TSBC label, year, make/model, park name, pad/site, park owner/address, pad rent, seller/buyer names/addresses, purchase price, deposit, included items, and signature print names.
6. Keep signature lines blank for the signing provider. Populate print names for review when appropriate.
7. Merge the filled actual PDFs into one clean review copy and send it immediately as a MEDIA attachment or Drive/preview link.
8. Report any fields left intentionally blank, especially final acceptance, offer-open-for-acceptance time, signatures/initials, or anything requiring the realtor confirmation. Never send for signatures from this recovery flow.

## Missing-Field Human Prompt

If key offer terms are missing, return a compact prompt in this shape:

```json
{
  "status": "waiting_human",
  "human_prompt": {
    "title": "Buyer CPS terms needed",
    "message": "I can draft the CPS once I have: buyer names, property address, offer price, deposit amount, completion, possession, adjustment, subject removal deadline, subjects, and included/excluded items. Deposit timing will default to upon subject removal.",
    "fields": ["buyer_names", "property_address", "offer_price", "deposit_amount", "completion_date", "possession_date", "adjustment_date", "subject_removal_deadline", "subjects", "included_items", "excluded_items"]
  }
}
```

## Completion Gate

Before reporting `done`, verify:

- Correct buyer deal and client names.
- The pre-draft question gate was answered or the run is `waiting_human`.
- Correct property address / MLS.
- MLS search/import populated seller name(s), seller realtor, and seller brokerage when available.
- Listing Documents-tab attachments were downloaded/saved to the Admin deal package, or the exact reason they were unavailable is listed.
- Correct WEBForms role: buyer / Selling Agent.
- Draft CPS exists as WEBForms transaction and/or editable PDF.
- Deposit timing is upon subject removal unless the realtor explicitly instructed otherwise.
- Draft is not sent for signature.
- Missing/assumed terms are explicitly listed for the realtor review.
- Admin deal has artifact and checklist updates.

## Output Contract

Return through `admin-result-writer`:

```json
{
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "skill": "buyer-cps",
  "property_address": "",
  "mls": "",
  "buyer_names": [],
  "seller_names": [],
  "seller_realtor": "",
  "seller_brokerage": "",
  "offer_terms_found": {
    "offer_price": "",
    "deposit_amount": "",
    "deposit_timing": "upon subject removal",
    "completion_date": "",
    "possession_date": "",
    "adjustment_date": "",
    "subject_removal_deadline": "",
    "subjects": [],
    "included_items": [],
    "excluded_items": []
  },
  "missing_fields": [],
  "listing_documents_saved": [],
  "artifacts": [
    {"kind": "cps_draft", "file_path": "", "summary": "Draft CPS PDF or WEBForms transaction"},
    {"kind": "buyer_listing_document", "file_path": "", "summary": "Listing Documents-tab attachment"}
  ],
  "checklist_updates": [
    {"field": "cps_draft", "value": true},
    {"field": "listing_documents_saved", "value": true}
  ],
  "next_tasks": [
    {"title": "Realtor review CPS draft before sending", "kind": "human_review"}
  ],
  "human_prompt": null,
  "risks": []
}
```

## Pitfalls
- Lesson for BC CPS/offer paperwork: client/buyer needs to sign or initial the Customary Costs section / line 6 when preparing signing packages. Verify the signature/initial placement before sending for signatures.

- If the realtor downloads actual WEBForms PDFs and emails them to herself, use those actual PDFs as the source-of-truth form package. Fill missing fields directly on them with light text overlays, preserve WEBForms-populated terms such as subject dates unless the realtor asks to change them, and merge the resulting CPS/addendum/disclosures into one clean review copy. This is preferred over local image overlays or a clean-but-custom worksheet because the realtor wants to review exactly what would be sent for signatures.
- When overlaying onto actual WEBForms PDFs, preserve the visible form structure. Do not use white cover boxes or erase blank lines just to fit text; that makes the review copy look messy and incomplete. Render the target pages before and after, visually confirm text is on the intended blanks, and especially confirm included items are on the `INCLUDING:` line rather than `EXCLUDING:`. If a first pass looks messy, rebuild from the untouched original WEBForms export instead of layering fixes onto the bad output.
- If the realtor sends a WEBForms mobile-home CPS how-to/reference by Gmail (subject line naming the mobile-home CPS process, PDF attachment), save it locally under the offer's artifact folder, e.g. `<elevate-home>/data/offers/<property-slug>/webforms-howto/<filename>.pdf`, and use it as the operating reference for how to create/populate mobile-home CPS transactions in WEBForms going forward.
- Buyer-side may be labelled **Selling Agent** in WEBForms.
- CPS Strata may still download with a Residential title, verify by clauses/forms included.
- Mobile-home offers must use the WEBForms/BCREA **Contract of Purchase and Sale of a Manufactured Home on a Rental Site** / mobile-home CPS template, not a residential/strata CPS. If the realtor says “use the CPS for mobile homes,” treat that as a hard form-selection requirement.
- the realtor expects approved local/system templates by default. Do **not** substitute a newly designed PDF/layout as the actual CPS when she asks for “the CPS.” If the required approved local form or clause pack is missing or unverified, send only a clearly marked review worksheet/term sheet and state it is not the approved CPS/signing package.
- When the realtor says to use the same conditions as a prior contract, locate that prior CPS/PDF, extract the subject clauses/terms, update dates/property-specific references, and preserve the substance. For a mobile-home precedent, reusable subjects typically include park approval/tenancy assignment, park rules/site tenancy agreement, BIR/permits, property disclosure/no-disclosure, financing, insurance, inspection, CSA/electrical approval, tax notice, and professional advice, plus terms for incorporated documents, measurements/zoning, electrical warranty, appliance working order, and information authorization.
- Xposure mobile-home listing document pulls may require searching the active listing by visible unit/street fields, opening the listing, then using the Documents tab. Save/verify every PDF before considering listing-document capture complete. For a mobile/manufactured-home listing, the Documents tab typically produces MHR, No Disclosure, Park Rules, and Electrical PDFs.
- Do not treat a client being in Top 25 as enough to draft an offer. Top 25 notes are buyer criteria only, not offer terms.
- Always run the pre-draft question gate before CPS population.
- Deposit timing defaults to upon subject removal on all the realtor CPS drafts.
- If only buyer criteria exists, stop at `waiting_human` and ask for offer terms.
- Search the property address for the MLS number before asking the realtor for seller/listing-agent details.
- Save listing Documents-tab attachments before considering the buyer package ready.
- Never send to DigiSign/AuthentiSign from this skill; hand off to `signing-package` only after the realtor approves the draft.
- When the realtor asks a status/review question such as “did you re-draft the offer paperwork?”, do not infer completion from related emails or non-offer attachments. Verify there is an actual CPS/offer artifact in the deal, local offer folder, Drive, WEBForms transaction, or Gmail attachment before saying it was redrafted. If Gmail has only supporting documents, such as an inspection PDF from the listing agent, save/report those separately and state clearly that the revised CPS/offer package is not verified yet.
- If the realtor explicitly asks to proceed after the clean approved CPS template is still unverified, create a **review-only populated form preview**, not a signature-ready CPS. Reuse the local approved-form/reference assets and pulled listing documents, then visibly overlay the actual known data onto the correct CPS form pages/addendum pages so the realtor can see exactly what would be sent. Do not stop at a PDF-first term sheet, worksheet, unpopulated blank form, or generic summary package when she asked to review drafted paperwork. Watermark/label every generated page `REVIEW ONLY - NOT FOR SIGNATURE`, erase or cover any green helper/sample text before adding typed values, leave actual signature lines blank unless using the signing provider, but populate printed names, dates, parties, price, deposit, completion/possession/adjustment, included/excluded items, agency fields, and addendum clauses. Include a known-data fill map, missing-fields checklist, recommended document set, and source PDFs, then return an immediate review artifact path/link (MEDIA attachment, Drive folder, or preview link). Do not mark `cps_draft=true` and do not call it drafted paperwork/signing package until a clean approved blank/template and fill mapping are verified.
- When verifying or attaching generated PDFs saved in Google Drive/CloudStorage, macOS Google Drive may throw `OSError: [Errno 11] Resource deadlock avoided` even when the Drive file exists. Use the local generator output under `/private/tmp/cps-gen-<deal_id>/` for PDF text/page verification and Admin attachment when available, then record the Drive URL from the deal toggle (`cpsDraftUrl`) or save output separately. Do not treat the CloudStorage read error as proof the draft failed.
- When the realtor asks to finish Offer Prep after prior automations ran, do not assume the CPS prep still needs to be generated. First re-read `admin_deal(action="show")`, `deals_overview`, deal contacts, `admin_action_runs`, `deal_attachments`, and recent `deal_events`. If an existing stage/card, contact, and draft-only CPS package are already present, verify the artifact instead of creating a duplicate: check file existence, SHA256, `pdfinfo` page count, `pdftotext` key terms, and scan for helper/sample text. Attach a compact final verification/doc-list artifact, set `cps-drafted=true` and `doc-list=true` only after verification, then re-read the gate. If only `lender-paperwork` remains missing, report that as the blocker and do not move beyond Offer Prep.
- If a stale Buyer Accepted / offer-review run was triggered while the buyer card belongs in Offer Prep, cancel/clear the stale accepted-offer blocker only after verifying there is no fully executed accepted-offer package. Keep the valid Offer Prep draft-only artifacts intact and do not run accepted-offer review/signing from draft-only CPS artifacts. If the stale prompt has fields like `Next step` and `Document link or notes`, resolve them from stored `admin_action_runs.human_prompt_json` / `result_json`, current `admin_deal(action="show")`, `deal_attachments`, and source manifests before asking the realtor again. Example resolution: `Next step = Attach CPS draft / continue offer prep`; `Document link or notes = verified inbound Webforms/TransactionDesk CPS path + manifest identifiers`. Attach a recovery memo and only continue to no-send/no-signature draft state unless there is explicit signing/send approval.
- If the realtor sends an ID image for a buyer, extract only the buyer full legal name and current address needed for the form. Do not reproduce or store licence number, DOB, image metadata, or other non-required ID details in the draft summary. If any name/address portion is unclear, mark that specific piece `unclear` rather than guessing.
- When using a prior CPS as a clause precedent, extract both the `SUBJECTS` and the later `TERMS` pages, not just a deal-sheet summary. Preserve the substance but adapt property-specific references, park name, dates, seller/buyer names, and included items to the new offer. For mobile/manufactured-home precedents, this usually includes park rules/approval, RTB-10/site tenancy assignment, MHR, BIR/permits, PDS/no-disclosure, financing, insurance, inspection, CSA/electrical, tax notice, professional advice, incorporation of docs, measurements/zoning, electrical warranty, appliance declaration, confidentiality, stigmatized-property warranty, seller insurance, seller cleanup/possessions/key/bin obligations, force majeure, and related-transaction effects.
- Always sanity-check date relationships before calling the package ready for signature: subject removal should normally be before completion. If the realtor provides a subject-removal date after completion, carry it into a review-only draft if asked to proceed, but flag it prominently as `DATE CHECK REQUIRED BEFORE SIGNING` and do not send for signature until corrected/confirmed.
- When resolving buyer-side offer-prep blockers from an MLS listing, use local/free Browser Use CLI only. If Xposure search results do not open the row from the address link, select the listing checkbox, use Actions → Print Preview, choose a full REALTOR report, then switch to the new `PrintEmail?automaticPrint=0&mlsId=...` tab and extract the full report text. The full report exposes commission, inclusions/exclusions, owner names, title/possession/taxes, and listing office/rep facts. For remuneration disclosure on buyer-side offers, use the listing `Commission` field as the calculation source, and preserve it as a method such as `3% on first $100,000 and 1.5% on balance + GST`; calculate dollar equivalents with `terminal`/Python only if needed for review notes. If the source CPS PDF is encrypted but decrypts with an empty password, `pdfunite` may fail; combine the clean package with `pypdf.PdfReader(...).decrypt('')` and `PdfWriter` instead, then verify `pdfinfo` page count and `Encrypted: no`.
