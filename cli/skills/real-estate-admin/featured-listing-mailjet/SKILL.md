---
name: featured-listing-mailjet
description: "Build a Mailjet featured-listing campaign from the approved template and deal-card facts. Use when the realtor asks for a featured-listing blast, wants a listing highlighted to the database, or wants featured alerts drafted for several active listings."
---

# Featured Listing Mailjet

Use this skill to build a featured-listing Mailjet campaign draft in the realtor's approved brand style from a previously tested featured-listing email.

## Canonical template

Confirm the current canonical template before drafting — do not assume a fixed template id, since it can change per realtor/brand:

- Mailjet template id and name (look up via Mailjet REST if not already known/cached).
- The approved/tested campaign draft it was based on (id and subject).
- Local canonical files, typically under a path such as:
  - HTML: `<elevate-home>/data/marketing/mailjet/featured-listing-template/featured-listing-mailjet-template.html`
  - Text: `<elevate-home>/data/marketing/mailjet/featured-listing-template/featured-listing-mailjet-template.txt`
  - Metadata: `<elevate-home>/data/marketing/mailjet/featured-listing-template/featured-listing-mailjet-template.metadata.json`
  - Mailjet proof: `<elevate-home>/data/marketing/mailjet/featured-listing-template/mailjet-template-<id>-proof.json`
- Before relying on the template, verify the last save/detailcontent calls returned success and that the rendered template includes unsubscribe, property/landing placeholders, and the realtor's brand/brokerage footer branding.

## Hard rules

1. Treat Browser Use local/free CLI as the browser/online path for Mailjet previews and browser-like online checks. Do not use Browser Use Cloud/API/signup/profile sync.
2. Do not send, schedule, or blast without the realtor's explicit approval for that exact send/schedule.
3. A test send to the realtor is allowed when she explicitly asks for a test.
4. Use the realtor's active configured sender address. Do **not** use an inactive/legacy sender as the campaign sender; an inactive address may still be used as the test recipient if she confirms it.
5. Keep the realtor's writing style: first person, warm, plain, no em dashes, no third-person client-facing voice.
6. Include the listing landing page link in the header logo, hero image link, and CTA button.
7. Before any schedule/send, verify draft status is still draft and content/images/links render.

## Required inputs

Gather or infer from Admin/deal/listing records before drafting:

- Property address
- Neighbourhood / city label
- Listing price
- Bedrooms
- Bathrooms
- Square footage
- Landing page URL
- Public hero image URL
- Hero image alt text
- 4 to 6 listing-specific paragraphs about why the property is special
- Contact/list audience ID
- Subject line, usually `Featured listing: <address> in <neighbourhood>`

If the property facts or hero image are uncertain, verify from existing approved listing assets before drafting.

## Batch drafting guidance

When the realtor asks for featured alerts for other listings, or a batch over the next few weeks:

- Start from `deals_overview` and select **available active listing-side deals only**. Exclude listings with accepted-offer, subject-removal, or closing status unless she explicitly asks for an accepted/sold/under-contract campaign.
- Exclude any featured-listing campaign already sent recently, unless she asks to resend or repurpose it.
- Commercial/business-opportunity listings, such as restaurant/share-sale listings, should not be forced into the residential bed/bath/sq ft layout. Hold them for a custom business-feature version or ask for confirmation before drafting.
- Use Admin card audits, listing-build packages, landing-site files, and prior marketing run artifacts for facts. Prefer approved local artifacts over improvised copy.
- Public image URLs must be verified before Mailjet save. Local file paths cannot be used in Mailjet. A practical Browser Use check is to open a local HTML file containing candidate `<img>` tags, wait for load, then evaluate `document.images` for `complete`, `naturalWidth`, and `naturalHeight`.
- If a custom listing page exists locally under a landing-site data folder, its deployed/public image path should be read from the actual deployed site rather than guessed from a URL pattern; verify with Browser Use before using.
- Verify the audience/list once per batch (subscriber count can drift). Always re-check the list ID and count before sending/scheduling.
- For a batch, create a summary proof JSON with draft IDs, subjects, sender, list, status, screenshot paths, skipped listings, and a `no_send_schedule_test: true` flag.

## Workflow

0. **Pull authoritative data FIRST — never infer facts or scrape photos.** Skipping this step is what causes wrong property facts or a scraped hero photo on a draft.
   - **Property facts** (address, neighbourhood, price, bedrooms, bathrooms, square footage, year built, key features) come from the listing's **deal SCORE CARD** — the Admin deal card / `deals_overview` and the deal's stored fields are the source of truth. Pull them straight from the card; cross-check against the listing's landing page and any maintained active-listings reference doc. Do NOT infer, round, or invent any fact. If a field is blank on the card, leave it out rather than guessing.
   - **Hero photo** must be an APPROVED listing photo, and Mailjet requires a PUBLIC url for it. Get one in this order:
     - (a) the listing's **deployed landing page** — open the ACTUAL built/deployed page and read its real `<img>` src. Do NOT guess the public-site URL pattern; guessing is what breaks this step.
     - (b) an approved photo from the listing's **Google Drive photo folder** (locate it via the realtor's maintained listings data-sources reference), uploaded to a public host (Mailjet image upload, or the deployed landing site) to get a usable URL.
   - NEVER use Realtor.ca, Zolo, MLS thumbnails, or any scraped third-party photo as the hero. There is no scraped-photo fallback — if no approved public photo exists yet, upload one from Drive first.

1. **Load the canonical template.**
   - Read the local HTML/text files above.
   - Do not start from an old generic Mailjet template.

2. **Render a static campaign draft.**
   - Replace the template placeholders with listing-specific static values before saving the draft. Do not rely on contact-list fields for property facts.
   - Keep `[[data:firstname:"there"]]` for the greeting if sending to a Mailjet list.
   - Keep `[[UNSUB_LINK_EN]]` intact in HTML and text.
   - Replace these placeholders:
     - `property_address`
     - `neighbourhood`
     - `preheader`
     - `landing_url`
     - `hero_image_url`
     - `hero_alt`
     - `headline_summary`
     - `bedrooms`
     - `bathrooms`
     - `square_feet`
     - `list_price`
     - `opening_detail`
     - `paragraph_1` through `paragraph_5`

3. **Create/update Mailjet draft.**
   - Create a campaign draft shell with:
     - sender email: the realtor's active configured sender
     - sender name: the realtor's display name
     - edit mode: `html2`
     - contacts list: the intended audience/list
   - Set the rendered HTML/text content.
   - Do not send or schedule at this stage.

4. **Verify draft safety and rendering.**
   - Fetch the draft metadata and confirm:
     - `Status: 0`
     - `DeliveredAt: ""`
     - sender is the active configured sender
   - Render the saved HTML via local Browser Use CLI and capture:
     - full-page screenshot
     - readable section screenshots if needed
   - Verify:
     - all images load
     - landing URL appears in header/hero/CTA
     - unsubscribe exists in HTML/text
     - no old property-specific text remains
     - no em dashes

5. **Test send only if requested.**
   - If the realtor asks for a test, send test to her preferred test address unless she names another.
   - If Mailjet says a valid and active sender is required, switch to the active configured sender and retry the test.
   - After test, re-fetch draft metadata and report that it remains draft/not scheduled/not blasted.

6. **Approval gate for schedule/send.**
   - Before scheduling or sending to the list, ask for/require explicit approval of:
     - subject
     - audience/list
     - send time
     - final screenshots/content
   - Do not treat a successful test as approval to schedule.
   - If the realtor explicitly says to send the approved/tested draft now to the full database, that is approval for an immediate Mailjet full-list send. Run a final preflight read-back first, then call `POST /v3/REST/campaigndraft/{draft_id}/send` through local/free Browser Use CLI. Do not ask for a second approval.
   - Final full-send preflight must confirm: draft `Status: 0`, `DeliveredAt` empty, sender is the active configured sender, audience matches the intended full-database list, corrected property facts present in HTML/text, old wrong facts absent, unsubscribe present, greeting is safe, and images/links are the expected approved assets.
   - Greeting check can pass either with the Mailjet first-name merge tag (`[[data:firstname:"there"]]`) or with a deliberate static rendered greeting such as `Hi there :)`. Do not block a send solely because the merge tag was pre-rendered/static for a one-off tested draft.
   - After a successful send, fetch the draft again and report `Status`, `DeliveredAt`, subject, sender, list/subscriber count, and proof path. Mailjet may return `Status: "programmed"` from the send endpoint while the draft read-back shows `Status: 1` and `DeliveredAt` populated; treat that as sent/accepted and report the timestamp.

## Output back to the realtor

Return:

- Mailjet draft ID
- Subject
- Sender
- Audience/list ID/name
- Safety status: draft/tested/not scheduled/not blasted
- Test-send result if applicable
- Full-page screenshot and section screenshots
- Any blockers or approval needed before schedule/send

## Known pitfalls

- For database/listing blasts, verify the current full-database contact list id/name; do not assume a cached id/name is still current, and re-check the subscriber count before every batch.
- Hero/property photos must come from the realtor's approved Google Drive listing/photo folder or already-approved owned landing-page assets. Do not use Realtor.ca, Zolo, MLS thumbnails, or other third-party scraped listing photos as Mailjet hero images unless the realtor explicitly approves that source.
- Cross-check status against live `deals_overview` before excluding a listing from marketing. Verify current stage/status and neighbourhood directly from the deal record rather than assuming from memory.
- When the realtor corrects a listing's status, neighbourhood, bedrooms/bathrooms, price, square footage, or other marketing fact after a draft was created, treat it as a cleanup task, not just a copy edit: patch the Admin/audit artifact, landing page source/build/deploy output, local HTML/text, Mailjet draft subject/content, batch summary/skipped list, any reusable script data, old proof files that preserve the wrong wording, and add a correction note or fact so future runs do not resurrect the stale value. Then read back the remote Mailjet draft and deployed/public landing page to verify every visible occurrence changed.
- If an old buyer-signed package artifact could be mistaken for an accepted offer, label the artifact clearly as buyer-side / NOT accepted and explicitly say not to use it to mark accepted, sold, firm, subject-removed, or exclude from active marketing. Keep the extracted terms only as review history.
- If the approved landing-site image URL is broken or unverifiable, do NOT fall back to a scraped third-party photo (Realtor.ca, Zolo, MLS). Take an approved photo from the listing's Google Drive photo folder and upload it to a public host (Mailjet image upload / the deployed landing site) to get a usable hero URL; verify `naturalWidth > 0` before saving to Mailjet.
- An inactive legacy sender address may be usable as a test recipient only, never as the campaign sender.
- Mailjet test sends may mark the draft metadata `Used: true` while the campaign still remains `Status: 0` draft. Report both clearly.
- For one-off proof/test sends from templates, pre-render property placeholders manually. Do not rely on `[[data:property_*]]` contact fields unless those fields actually exist on the list.
- For Mailjet cleanup/correction tasks, update the reusable local render/script data first so the same bad copy is not regenerated, then render local HTML/text and push only `campaigndraft/{id}/detailcontent` and safe metadata if needed. Do not call send, schedule, or test-send endpoints. After saving, perform a remote read-back of both `campaigndraft/{id}` and `campaigndraft/{id}/detailcontent` through Browser Use CLI / Mailjet REST, and persist the fetched remote HTML/text plus a proof JSON confirming: Status remains `0`, DeliveredAt is empty, sender/list/subject are unchanged or expected, corrected wording is present, old wording is absent, and send/schedule/test endpoints were not called. For copy-only fixes such as repeated square footage, add explicit local and final read-back guards for the exact stale phrases plus a body-copy count check so the stats row/footer may keep square footage while the narrative body no longer repeats it.
- If Browser Use opens the Mailjet API URL with masked credentials and returns `net::ERR_INVALID_AUTH_CREDENTIALS`, do not mask the password in the actual URL. Use the real Basic Auth URL for the Browser Use session, then use XHR with the Authorization header for read/write calls.
- If the user says they cannot see the whole proof screenshot, create both a full-page screenshot and 2 to 4 readable viewport section screenshots.
- Read back detailcontent on any existing draft before deciding it is current: check for malformed merge-tag remnants, old facts, and expired open-house promos, since a draft shell can look usable while still carrying stale content underneath.
- For Mailjet API work under the Browser Use-only rule, establish the API origin by opening `https://<api_key>:<secret>@api.mailjet.com/v3/REST/...` in Browser Use, then run same-origin `XMLHttpRequest` with the Basic auth header from `browser-use eval`. Opening the unauthenticated API URL can fail with `net::ERR_INVALID_AUTH_CREDENTIALS` before eval/XHR has a chance to run.
- If a final send preflight fails for a conservative gate that is not actually a safety issue, inspect the saved proof JSON before rerunning. For example, a deliberate static greeting rendered for a one-off tested draft can look like a missing merge tag; accepting either the merge-tag greeting or a deliberate static safe greeting is the correct fix, not forcing a re-render.
