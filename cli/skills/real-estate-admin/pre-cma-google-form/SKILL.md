---
name: pre-cma-google-form
description: Run the Pre-CMA dashboard workflow through Lofty, Mailjet, and Xposure. Use when a new seller/prospect is ready for Pre-CMA intake, or when a dashboard card moves into the Pre-CMA tab. Not for filling the old CMA Google Form, which this workflow replaces.
metadata:
  elevate:
    tags: [real-estate, pre-cma, lofty, mailjet, seller-package, dashboard]
    runtime:
      approval_required: false
---

# Pre-CMA Dashboard Workflow

Use when a new seller/prospect is ready for Pre-CMA intake, or when a dashboard card moves into the **Pre-CMA** tab.

This replaces the old Google Form workflow. Do **not** fill or submit the realtor's previous CMA Google Form. The Pre-CMA workflow now handles the same outcomes directly:

1. create or verify the seller/client contact in Lofty,
2. prepare the Mailjet seller marketing package,
3. send or queue the seller package according to the approval rules below,
4. export Xposure preview PDFs for the realtor, and
5. save a clean handoff for the CMA workflow.

This section is not for giving the realtor a final evaluation or pricing opinion. The Xposure preview is still important because it lets the realtor see what the property could be worth before walking through: old subject MLS context plus recent similar solds with photos, so she can visually compare condition, finish level, layout, and market position before the full CMA.

## Current Mailjet Seller Package

- Mailjet template ID: `8055687`.
- Title: `Pre-CMA Seller Package - <brokerage brand>`.
- Subject: `<Brokerage Brand> Marketing Package`.
- Legacy ID `14342651` returned 404 with current Mailjet credentials and should not be used for routing.
- Sender must be the realtor's configured name/address, e.g. `<Realtor Name> <realtor@example.com>`.
- The greeting uses Mailjet contact data: `[[data:seller_names:"there"]]`.
- The Mailjet greeting should use first names only, not full legal/display names. For one seller, set `seller_names` to the seller's first name only. For two sellers, set it to both first names, for example `Russ & Lori`.
- The current visual fixes are intentional and should be preserved: email-safe YouTube thumbnail/button blocks, handwritten-style brand signature above the green footer, branded “Let’s stay connected” footer, social links, website link, legal address, and unsubscribe link.
- When verifying or rebuilding the seller package styling, use `/Users/admin/elevate-premium/knowledge/brand-guide.md` as the brand source, then apply the configured brokerage Mailjet aesthetic.

## Required Inputs

Ask for only missing pieces in one concise prompt:

- Client/seller name or names.
- Email and/or phone.
- Property address.
- CMA reason: pricing appointment, listing presentation, informal evaluation, price reduction, or other. Default to `homeowner wants a price on their home` if the realtor does not specify.
- Known seller goals, timing, motivation, and concerns.
- Known seller-provided property details, upgrades, condition notes, and special features, if already provided. Do not ask the realtor for basic public/MLS property facts first; look them up from eValueBC / BC Assessment and the old Xposure sold listing.

## Phase Map

| Phase | Output | Human Checkpoint |
| --- | --- | --- |
| contact | Lofty contact found/created/updated with ID, email, phone, and seller/client name. | Missing or conflicting identity/contact info. |
| mailjet-package | Mailjet contact created/updated, `seller_names` set, seller package draft/template verified, test/preview optional. | Required before first/new client-facing send unless the realtor explicitly requested the package be sent to that recipient. |
| xposure-preview | Old MLS sheet plus recent similar/area solds pulled from Xposure, printed/exported to PDF, and attached to the deal record. | Portal access issue, ambiguous subject match, or unsafe external send action. |
| handoff | CMA-ready handoff saved to Admin/CMA record. | Missing required CMA inputs. |

## Rules

- Pre-CMA comes before the CMA/PDF evaluation tab.
- This workflow no longer uses the Google Form. Do not search Drive for the CMA Google Form, derive form field IDs, submit public Google Forms, or treat a form response as the handoff artifact. The skill name is a historical holdover from that old Google Form era; the workflow itself is the direct dashboard-driven flow below.
- If the realtor asks to "start a new deal" for a Pre-CMA and provides only the property address, create a listing-side deal in `operational.db` at `current_stage=0`, `status='active'`, `province='BC'`, with `listing_track='pre-cma'`, and title it `<address> Pre-CMA`. Check first for an existing deal where `listing_address` or `title` matches the address to avoid duplicates. Add a `deal_events.kind='created'` event with payload `workflow='pre-cma'`, `phase='contact'`, `status='waiting_human'`, the address, and the missing Pre-CMA fields. Do not ask for the missing fields before creating the card unless the address itself is ambiguous.
- For new Pre-CMA cards, default the CMA reason to: `homeowner wants a price on their home`, unless the realtor provides a different reason.
- Verify or create/update the client contact in Lofty before marking Pre-CMA complete.
- Save the Lofty contact ID/status, seller/client names, email, phone, property address, seller goals, timing, and property notes into the handoff.
- Prepare the Mailjet seller package after the seller contact information is known:
  - ensure the seller is on the appropriate Mailjet contact/list if a list-send/contact-based send is used,
  - set or update Mailjet contact property `seller_names`,
  - verify template `8055687` (`Pre-CMA Seller Package - <brokerage brand>`) still uses the realtor's configured sender address,
  - never leave example names in the greeting.
- Sending policy for the Mailjet seller package:
  - When the realtor asks to do/run the Pre-CMA from the dashboard, that request is approval to automatically send the seller package after the seller contacts are verified/created in Lofty and the recipient email address is verified. Do not ask for separate send approval in this scenario.
  - Copy the realtor on every seller package email so she can confirm it was sent. Use her configured personal email as the CC address unless she specifies a different copy address.
  - Test sends to the realtor are safe and can be sent when requested.
  - Never send to an ambiguous recipient or unverified email address.
- After the property/client information is provided, pull the prior/old MLS sheet for the subject property from Xposure when available.
- For missing basic subject-property facts, do not stop and ask the realtor first. Look up the property on eValueBC / BC Assessment and the prior/old sold listing in Xposure, then use sourced facts for the pre-CMA intake. BC Assessment address search can be queried directly with `/Property/Search/GetByAddress?addr=<address>` and returns a property id for `/Property/Info/<id>`; if the detail page is script-rendered or incomplete, use it as an address/PID match and cross-check public sources like REW, HonestDoor, SnapUp, or municipal property reports. Record source conflicts and treat the old Xposure sold listing as the tie-breaker for beds, baths, finished square footage, and exact sale date.
- Before the realtor's walkthrough, pull only comparable Xposure sold homes from the same area/neighbourhood within the last 5 months. Use similarity filters for bedroom count, bathroom count, finished square footage, property subtype, and meaningful property features when known. Do not pull every area sale unless the realtor explicitly asks for all area sales.
- Recent solds should be visually useful for the realtor. Print/export the comparable solds with photos, preferably using an Xposure photo/full template such as `1upFullWithExtraPhotos`, `Complete w/photos: Full`, or the closest available photo report. If a grid export fallback is required, note that it is a fallback and still verify the PDF contains the selected comparable solds.
- Print/export the old MLS sheet and recent similar/area solds to PDF and attach them to the deal. This Matrix/Xposure PDF export step should run automatically once the Pre-CMA card is started and solds criteria are provided; do not pause for another approval. After the PDFs are created, email them to the realtor and send the PDFs to the configured Telegram/home channel. This delivery step is internal to the realtor and is part of normal Pre-CMA completion once the realtor has requested the workflow; do not ask for a second confirmation unless the recipient/channel is ambiguous or the send would go somewhere client-facing.
- This Xposure preview is not the final CMA and must not include a client-facing evaluation, formal price recommendation, or pricing opinion. Internally, its purpose is to help the realtor quickly see what the property could be worth before walking through. It should give her a practical visual pricing context from: (1) the subject property's last/old MLS sheet from Xposure, and (2) recent similar sold homes from the last 5 months, filtered for comparable beds, baths, finished square footage, subtype, condition/renovation level when known, and suite/garage features when relevant, exported to PDF with photos. Treat the photo-rich solds as the key pre-walkthrough value check because the realtor can compare finishes/layout/condition visually before building the full CMA.
- Once Pre-CMA is complete, the next dashboard move should be to **CMA / Evaluation**, where the CMA skill creates the PDF and pricing evaluation.
- Once the client says yes to listing with the realtor, moving the CMA card to **Listing Intake** should trigger the MLC skill.

## Operational Notes Learned

- Lofty matching: use phone/email/contact ID as verifiers before matching conversations or docs. Do not create duplicates if an existing contact is found.
- Mailjet seller package personalization depends on contact data. Before sending to a seller, verify the contact property `seller_names` is populated with first names only, not full names, exactly how the realtor wants the greeting to read. Mailjet contact properties must exist before `contactslist/{id}/managecontact` can set them; if Mailjet returns `Object properties invalid` for `seller_names` or `property_address`, create them first with `POST /v3/REST/contactmetadata` using `{ "Name": "seller_names", "Datatype": "str", "NameSpace": "static" }` and the same shape for `property_address`.
- For Pre-CMA seller package sends, use the Mailjet template `8055687` as the content source, but run a brand check before proof/client send. If the source HTML does not match the current brokerage email system from `/Users/admin/elevate-premium/knowledge/brand-guide.md` and the configured companion templates (cream background, white 600px card, brand color palette, brand fonts, section dividers, note blocks/CTA styling, branded footer), rebuild the rendered HTML into that layout before sending. Personalize `[[data:seller_names:"there"]]`; campaign test sends do not satisfy the real workflow because the seller must receive it and the realtor's configured personal email must be copied.
- If using a campaign draft's HTML in a transactional send, replace campaign-only placeholders like `[[UNSUB_LINK_EN]]` with a safe website/preferences fallback rather than leaving raw campaign placeholders in the transactional email.
- Lofty `POST /leads` can return a `leadId` that immediately 404s on `GET /leads/{id}` even though the lead appears in `GET /leads?q=<email>`. If direct GET fails, verify by exact email match in the search results and record the caveat instead of treating the create as failed.
- If editing Mailjet seller package HTML, avoid Flodesk SVG/video embeds. Use email-safe linked thumbnails and buttons for videos; Flodesk `<svg><foreignObject>` video blocks can overlap or render badly in email clients.
- BC Assessment details pages can be mostly script-rendered, but the address search value is base64 for `OID_EVBC` (example `QTAwMDBOV1hTSw==` -> `A0000NWXSK`). To get assessment facts, use a single `urllib`/requests session: load `/Property/Info/<encoded-id>` to collect cookies, `gistoken`, and `mapserverUrl`, then query `{mapserverUrl}/0/query` with the same cookies, `token=<gistoken>`, `where=OID_EVBC='<decoded id>'`, `outFields=*`, `returnGeometry=false`, `f=json`. Without preserving the page session cookies the ArcGIS call can return `498 Invalid Token` even if the token was scraped correctly.
- AOIR/Xposure/Matrix login starts at `https://iam.interiorbc.ca/idp/login`. Credentials may be stored under existing MLS/AOIR environment aliases used by the CMA/Xposure skills. Never expose credential values in output or artifacts. For non-browser automation, POST username/password plus `_csrf` to the IAM login, parse the auto-submit SAML form, POST it to `https://members.interiorbc.ca/saml`, then request `https://matrix.interiorbc.ca/matrix/`, parse the second IAM SAML form, and POST it to `https://matrix.interiorbc.ca/matrix/login.aspx?passthrough=2&noredirect=1`. A successful Matrix session has cookies like `MLSAuth`, `LoginSig`, and `MatrixLoginName`; the app loads at `/Matrix/r/Search` for the responsive search page.
- For the subject's last MLS sheet in Xposure: search by address, include Sold status, select the exact subject row, open/construct the PrintEmail view with template `1upFull`, then use Chrome/CDP `Page.printToPDF` to save the sheet. Verify with `pdfinfo` and `pdftotext` for the subject address and MLS number.
- For recent sales: search Xposure for comparable sold homes, not all neighbourhood solds by default. Start with same neighbourhood/area, same property subtype, Sold status, and a 5-month sold-date lookback. Then filter to similar bedrooms, bathrooms, and finished square footage. Use known meaningful features as comparability filters/notes, for example renovated condition, basement suite, bedroom split, garage, lot/parking, and property style. Export the solds with photos so the realtor can visually compare condition and finish level. Only broaden the criteria if too few comparable solds are available, and note the broadened assumption in the handoff.
- Xposure date fields may validate `MM/DD/YY` and normalize to `YYYY/MM/DD`; full four-digit year input can fail validation. Set readonly date fields programmatically if needed, then call the page validation/change events before search.
- If Xposure's print-preview JS fails for large grid exports, printing the search-results page directly to PDF is an acceptable fallback, provided `pdftotext` verifies the first and last expected rows/MLS numbers appear in the PDF.
- After exporting the Xposure PDFs, email both PDFs to the realtor and send both PDF files to Telegram/home channel using native media attachments (`MEDIA:<path>`). Verify Gmail returns a SENT message id and Telegram returns a success/message id before marking the delivery complete.
- If an Xposure saved-list/browser helper times out during its final/cleanup step, do not treat that alone as a workflow failure. First verify whether the helper already matched the saved list and whether the actual MLS data, photo capture, PDFs, attachments, email, and Telegram delivery completed. Mark the helper timeout as a caveat only when those downstream artifacts are independently verified.
- For sparse acreage Pre-CMA sold searches, do not jump straight from a tight same-neighbourhood search to remote low-price acreage references. Correct fallback order is: same minor area / same subtype / similar beds-baths with 5-6 month lookback; then same minor area with 12 month lookback; only then widen to full major area while preserving subtype, bed-bath similarity, and a realistic price band. If the same-neighbourhood 12-month pass has only 1-2 solds, keep those as selected solds and label the packet “limited same-area evidence” rather than replacing them with distant Clearwater/Lillooet/Ashcroft 3-bed/1-bath outliers. When full-major-area fallback is needed, prefer higher-similarity Kamloops and District acreage records by subtype, beds/baths, acreage/utility, and price relevance, and clearly label each widened comp’s search pass.
- `full-cma-run.js` can hang in the final comp photo/address-lookup phase when a widened comp address does not parse cleanly, observed with `7390 River Heights Drive` where address lookup logged an empty street number. If the run already produced the selected sold list, comp data/photos for earlier comps, and an `xposure-saved-list-*.json` proving MLS-batch saved-list creation, kill the hung process, preserve those artifacts, and report the hang as a blocker/caveat instead of losing the rerun. Use the saved-list JSON and process log as proof of selected solds if PDFs still need manual/secondary rendering.
- Attach generated PDFs to `deal_attachments` in `operational.db` and log `deal_events.kind='attachment_added'`; `deal_events.kind` is constrained to `created`, `stage_transition`, `toggle_change`, `run_result`, `attachment_added`, or `contact_linked`.
- For Stage 0 Pre-CMA **pipeline/test** runs where prior Xposure preview artifacts already exist but the deal has no verified seller/client name or email, do not send the seller package to any client and do not mark Lofty/contact verification complete. Re-verify the existing old-MLS and recent-solds PDFs mechanically, write a concise test audit artifact beside the prior CMA/Pre-CMA folder, and close as `waiting_human` asking for seller/client name, email, lead source, CMA timing, and whether the next run should send to the client or remain realtor-only.
- If a Stage 0 Pre-CMA **pipeline/test** run explicitly scopes delivery to the realtor only, for example a transactional send to her configured personal email and forbids campaign/list sends, it is safe to send a single Mailjet transactional test email to the realtor after re-verifying the local Xposure preview PDFs. The email must clearly say internal/test/review only and must not imply a client-ready CMA or pricing recommendation. Record Mailjet MessageUUID/MessageID in a local audit artifact, attach that artifact through `admin-result-writer`, leave `lofty_contact_verified` incomplete, and create/keep a next task for `lofty-crm-client-contacts` before any real client-facing delivery.
- For these test runs, use the scheduled Admin callback with a stable idempotency key and verify readback from `admin_action_runs` plus the new `deal_attachments` row before reporting success. If `127.0.0.1:9119` refuses connection, retry the exact final payload and token on `127.0.0.1:9120`; only claim operational writes after a 2xx and readback. If both endpoints fail, query `admin_action_runs` and `deal_attachments` afterward and explicitly report that no new operational updates were written; do not imply the local audit was attached unless readback proves it.
- For Stage 0 Pre-CMA **test-send-to-realtor** reruns where the deal still lacks a primary contact/Lofty verification but already has verified Xposure preview artifacts attached, treat the run as an artifact-reconciliation + waiting-human closure, not a full send. First verify the existing PDF/JSON/MD artifacts mechanically (`pdfinfo`, `pdftotext`, JSON parse, file existence/hash), then post one `waiting_human` result with the verified artifacts attached and a concise prompt for `verified client email` and `Lofty contact ID or confirm create/update`. If the injected callback port `127.0.0.1:9119` refuses, safe-retry the identical final payload/idempotency key on `127.0.0.1:9120`, then read back `admin_action_runs` and `deal_attachments` to confirm the run status, human prompt, and newly attached rows before reporting. Do not send Mailjet/seller package emails, mark `lofty_contact_verified`, or advance Stage 0 until Lofty/contact verification exists, even if the payload text says autonomous/send-to-realtor.

## Output Contract

```json
{
  "workflow": "pre-cma",
  "phase": "contact|mailjet-package|xposure-preview|handoff",
  "status": "done|partial|failed|waiting_human",
  "contact": {
    "lofty_contact_id": "",
    "lofty_status": "found|created|updated|missing|conflict",
    "name": "",
    "email": "",
    "phone": ""
  },
  "address": "",
  "seller_package": {
    "mailjet_template_id": "8055687",
    "sender": "<Realtor Name> <realtor@example.com>",
    "seller_names_property_set": true,
    "status": "prepared|queued_for_approval|sent|test_sent|skipped|failed",
    "recipient_email": "",
    "mailjet_send_id": ""
  },
  "artifacts": [],
  "xposure_preview": {
    "old_mls_sheet_pdf": "",
    "recent_similar_solds_pdf": "",
    "solds_criteria": {
      "lookback_months": 5,
      "area": "",
      "square_footage_basis": "",
      "bedroom_basis": "",
      "bathroom_basis": "",
      "feature_basis": "renovation level, basement suite, garage, parking/lot, style where known",
      "photos_included": true
    },
    "emailed_to_realtor": true,
    "sent_to_telegram": true
  },
  "missing_fields": [],
  "next": {
    "skill": "cma",
    "phase": "collect"
  }
}
```


## Pre-CMA REQUIRED contact onboarding (2026-06-22) — these are part of THIS skill, not optional

The seller package send DEPENDS on the contact existing. Before (and so that) the seller package can go out, the Pre-CMA skill MUST do all of these — do NOT skip them and do NOT stop with "can't send without a Lofty contact"; CREATING that contact is your job here:
1. **Create a NEW contact in Lofty** for the seller — name, email, phone, property address, lead source. (Use the Lofty CRM contact path / `lofty-crm-client-contacts`.)
2. **Add that contact to Mailjet** (the seller-package send needs them as a Mailjet contact — this is the gating dependency; without it the template send has no recipient record).
3. **Fill out the Google Master Sheet** with the contact info.
4. **THEN send the Mailjet seller package** (template 8055687) to that contact.
Order matters: 1 → 2 → 3 → 4. If any of 1–3 genuinely errors (API down, auth), surface a CONCISE waiting_human naming the exact failed step — but never silently skip them or downgrade to a generic placeholder email. The 2026-06-22 autonomous test run skipped 1–3 and sent a placeholder; that is the bug.


## Seller package MUST be the RENDERED branded template 8055687 — never a hand-built email (2026-06-22 bug)

The 2026-06-22 runs sent a CUSTOM transactional email assembled from the template's text. WRONG. The recipient must receive the ACTUAL approved branded template, rendered.
- Send it as the template via the Mailjet Send API (the API is explicitly allowed for THIS template-render step — it is a Mailjet template operation, not a freeform browser action). Equivalent of:
  `POST https://api.mailjet.com/v3.1/send` with
  `{"Messages":[{"From":{"Email":"<realtor@example.com>","Name":"<Realtor Name>"},"To":[{"Email":"<seller email>"}],"TemplateID":8055687,"TemplateLanguage":true,"Variables":{"seller_names":"<seller first name>"}}]}`
  (auth: MAILJET_API_KEY / MAILJET_SECRET_KEY).
- This renders "Pre-CMA Seller Package - <brokerage brand>" (subject "<Brokerage Brand> Marketing Package"). DO NOT build your own Subject/HTML from the template content — use `TemplateID` so the branded, approved template is exactly what sends.
- Set `Variables.seller_names` (and any contact data the template expects) so the greeting fills.
- Mailjet `CustomID` has a 64-character limit. For Admin run/test sends, use a short stable value like `pcma1740s3tmpl` / `pcma1740s3comps`, not the full deal/run/idempotency string. If Mailjet returns `mj-0006 Characters limit exceeded for the property` on `CustomID`, treat it as payload rejected before send, log the process warning, shorten `CustomID`, and retry. Do not assume an email was sent until Mailjet returns `Status: success` with MessageUUID/MessageID.

## Comps batch is a SEPARATE email — actually send it (required deliverable)

Pulling the Xposure sold-comps PDF to disk is NOT done. EMAIL the area sold comps to the seller as their own message (attach the sold-comps PDF, or link it). This is a required Pre-CMA deliverable — do not skip it or merely reference paths.


## Lofty contact must be RICH + auto-enriched via a lead/client audit (2026-06-22)

Creating a Lofty contact with just name+email is NOT enough. Capture phone number(s), spouse/partner, additional emails, mailing address, and any other known detail. And do NOT make the realtor type it — run a LEAD/CLIENT AUDIT first: search the name (+email) across her Gmail, her macOS phone Contacts, and her iMessage history, consolidate everything found (phones, spouse/partner, extra emails, address), and use it to fill BOTH the Lofty contact AND the deal score-card fields as completely as possible. Enrichment runs BEFORE creating/updating Lofty so the contact is created rich, not minimal.


## Enrich BEFORE creating the Lofty contact — run the lead/client audit

Before creating/updating the Lofty contact, RUN the lead/client audit to gather everything already known about the person:
  `python3 /Users/admin/elevate-premium/scripts/contact-audit.py "<seller full name>" "<seller email>"`
It returns JSON: `phones[]`, `emails[]`, `spouse_or_partner[]`, `family[]`, `mailingAddresses[]` (sourced from macOS Contacts + iMessage + Gmail). Use that output to fill the Lofty contact AND the deal score-card seller fields as completely as possible — phone(s), all emails, mailing address, spouse/partner (and note family). NEVER create a name+email-only contact when the audit surfaced more. If the audit finds an existing email that conflicts with the one given (e.g. a hotmail vs gmail), surface that in the contact decision.


## MANDATORY final step — the completion gate (do NOT close the run without it)

After running the Pre-CMA chain, you MUST run the deterministic completion gate:
  `python3 /Users/admin/elevate-premium/scripts/pre-cma-gate.py <deal_id> --heal`
It verifies all 6 deliverables FROM THE SYSTEMS THEMSELVES (Lofty linkage, enrichment/phone on card, Mailjet contact, Master Sheet row, branded template 8055687 sent, comps packet sent) and auto-heals the healable misses (Mailjet add / Sheet append / template send / comps send), then re-verifies.
- Only close the run as DONE / mark Stage 0 complete if the gate exits 0 (PASS — all GREEN).
- If the gate reports RED on `lofty_contact` or `enrichment` (not auto-healable), surface a CONCISE waiting_human naming exactly that gap. Never report success when the gate is RED.
This gate is the source of truth for Pre-CMA completion — the chain steps above are best-effort; the gate is what guarantees it.
