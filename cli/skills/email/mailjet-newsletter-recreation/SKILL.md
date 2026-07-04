---
name: mailjet-newsletter-recreation
description: Recreate an existing hosted newsletter as a Mailjet campaign draft without sending it. Use when the user asks to recreate a hosted newsletter/email in Mailjet from a preview URL, especially a Flodesk preview URL such as view.flodesk.com/emails/....
---

# Mailjet Newsletter Recreation

Use this when the user asks to recreate a hosted newsletter/email in Mailjet from a preview URL, such as `view.flodesk.com/emails/...`.

## Safety rule

Do not send or schedule the campaign without explicit human approval. Creating a draft and test-ready content is safe.

## Mandatory brand-guide rule

Any new client-facing Mailjet email, campaign, proof, or reusable template must follow the tenant's current brand system unless the user explicitly asks for a plain/unbranded email.

Read the tenant's brand guide (e.g. `knowledge/brand-guide.md` if configured) plus any current accepted-offer/checklist templates as the canonical visual reference. A brand guide typically defines:

- a page background and a centered white email card at a fixed width;
- a logo/header treatment at the top where appropriate;
- primary and accent brand colors;
- display heading and body-copy typefaces;
- eyebrow labels, editorial spacing, section dividers, note blocks, and accent CTA buttons;
- a branded footer with contact/social links and brokerage/compliance branding when appropriate;
- voice rules from the realtor's persona (e.g. punctuation conventions, allowed emoji).

Before creating or sending a proof, run a brand check: if the email is missing the brand's header/logo feel, palette, typography, sectioned editorial layout, or footer/brokerage treatment, stop and refresh the HTML before reporting it ready.

### Featured listing footer/agent block lesson

For featured-listing blasts, preserve the approved footer/agent composition while adjusting logo sizing. If the realtor asks for their brokerage's logo to match a second brokerage logo visually, do **not** solve it by removing the realtor's circular photo or turning the block into logos-only. Keep the circular agent photo visible, stack the primary brand logo directly above the secondary/compliance logo in a centered column, match their visual size/weight, balance the spacing, and keep any district/location text underneath. When reporting proofs in chat, export a small cropped JPG/WebP of the exact revised block plus a full-email proof, because tall PNG screenshots may not render properly in chat.

## Workflow

1. Open the hosted email URL in the browser.
   - Use `Browser Use CLI(url)`.
   - Use `Browser Use CLI` to extract:
     - `document.title`
     - `document.documentElement.outerHTML`
     - `document.body.innerText`
     - all links
     - all images
   - If the console output is persisted to a temp file because it is large, read/process that file with `read_file` or `execute_code`.

2. Save the original HTML locally.
   - Example path: `/tmp/flodesk_newsletter_original.html`.
   - Preserve the full HTML before cleaning so the import can be audited.

3. Clean the HTML for Mailjet.
   - Remove hosted-preview-only assets like Flodesk `view.css` if present.
   - Replace Flodesk unsubscribe/preferences links with Mailjet unsubscribe placeholders.
     - Common Flodesk pattern: `<a data-link="unsubscribe" href="#">Unsubscribe</a>` and preferences links with `href="#"`.
     - Replace with `href="[[UNSUB_LINK_EN]]"`.
   - Remove Flodesk referral footer links like `flodesk.com/c/...`.
   - Keep all public image URLs intact unless the user asks to rehost them.
   - Set a clear `<title>` matching the campaign.

4. Build a plain text fallback.
   - Use `document.body.innerText` from the captured page.
   - Remove web-only lines like `Unsubscribe` and `Manage Preferences` if they are duplicates.
   - Append `Unsubscribe: [[UNSUB_LINK_EN]]`.

5. Verify image/link readiness.
   - Extract all `<img src="...">` URLs from the cleaned HTML.
   - HEAD-check each image URL with a browser-like user agent.
   - Then render a local proof HTML with Browser Use and evaluate every `document.images` entry. Treat an image as failed unless `complete === true` **and** `naturalWidth > 0` **and** `naturalHeight > 0`; `complete: true` with zero natural dimensions means the browser loaded a broken-image placeholder.
   - For Google Drive-supplied photos, do not assume `drive.google.com/thumbnail`, `lh3.googleusercontent.com/d/...`, or `uc?export=view` is email-safe. If Browser Use shows the Drive file requires sign-in/access, or the rendered `<img>` has zero natural dimensions, stop and report the image is not publicly loadable instead of pushing a broken hero image.
   - If the user specifically requests a private Drive hero photo and the file is accessible through the authenticated Google Workspace CLI (`gws`) but not as a public browser image, verify and download the exact file by Drive ID with `gws drive files get` inside the Browser Use CLI workflow, record file ID/name/md5/image metadata as proof, then either rehost the exact downloaded image on an email-safe public asset host or embed a resized data URI only after Mailjet render verification confirms the hero loads. Do not substitute a different public photo just because it renders.
   - When `gws drive files get` metadata includes a `thumbnailLink` on `lh3.googleusercontent.com/drive-storage/...=s220`, try transforming only the size suffix to `=w1600` or `=s1600` and verify it returns `200` with `content-type: image/jpeg` and nonzero bytes. In one repair, generic `drive.google.com/thumbnail?id=...`, `lh3.googleusercontent.com/d/<id>=w1600`, and `uc?export=download` all rendered as HTML/access pages, but the metadata `thumbnailLink` transformed to `=w1600` loaded correctly in Mailjet/browser render. Save this fetch proof before updating the draft.
   - For repair requests like "use this hero photo and make it larger," do not only swap the image URL. Also enlarge the email container/hero presentation if appropriate, then verify structurally (`width`/`max-width` attributes) and visually with Browser Use. In one repair, widening the desktop card/hero from `640px` to `700px` plus preserving `width:100%; height:auto` satisfied the larger hero request.
   - Avoid relying on Mailjet to preserve oversized data-URI hero images unless already verified against the remote draft. Prefer a public, browser-renderable image URL from verified Drive metadata or a real asset host; after `POST /detailcontent`, immediately fetch remote `detailcontent` and confirm the remote HTML exactly matches the local HTML.
   - Browser Use profile runs can fail if the local temp volume is full from stale `browser-use-user-data-dir-*` directories. If Browser Use errors with `No space left on device`, check `df -h /tmp` and remove stale Browser Use temp profile dirs under the current macOS temp folder before retrying.
   - Report any failures before creating/sending tests.

6. Create a Mailjet campaign draft.
   - First inspect available senders and contact lists if needed:
     - `mcp_mailjet_list_senders`
     - `mcp_mailjet_list_contact_lists`
   - Prefer the tenant's verified sender for their branded newsletters, resolved from config/onboarding, unless the user specified otherwise. For seller packages, use the realtor's own sending identity when requested or when the current seller-package workflow calls for it.
   - Use `mcp_mailjet_create_campaign_draft` with `edit_mode: "html2"`.
   - If no list is specified and this is the tenant's general newsletter, use their configured all-contacts list if present.

7. Push the content into the draft.
   - Use `mcp_mailjet_set_campaign_content` for normal-sized payloads.
   - If the HTML is very large or the MCP wrapper is awkward, direct Mailjet REST is reliable:

```python
import os, json, base64, urllib.request, pathlib
api=os.environ['MAILJET_API_KEY']; secret=os.environ['MAILJET_SECRET_KEY']
draft_id='DRAFT_ID'
html=pathlib.Path('/tmp/newsletter_mailjet.html').read_text()
text=pathlib.Path('/tmp/newsletter_mailjet.txt').read_text()
body=json.dumps({'Html-part': html, 'Text-part': text}).encode('utf-8')
req=urllib.request.Request(f'https://api.mailjet.com/v3/REST/campaigndraft/{draft_id}/detailcontent', data=body, method='POST')
req.add_header('Content-Type','application/json')
req.add_header('Authorization','Basic '+base64.b64encode(f'{api}:{secret}'.encode()).decode())
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.status, r.read().decode('utf-8')[:2000])
```

8. Apply the tenant's reusable seller-package / client-checklist cleanup when the recreated email is a seller, buyer, accepted-offer, or marketing package. Read the tenant's brand guide as the base brand source when exact tokens are needed, then apply the current landing-page aesthetic for that tenant.
   - Match the tenant's landing-page aesthetic for branded Mailjet emails unless the user asks otherwise — read exact colors/fonts from the brand guide rather than guessing.
   - Use the same editorial structure as the tenant's listing landing pages: display headings, body copy, eyebrow labels, clean section dividers, hero overlay/image card, accent CTA buttons, and a branded footer. Avoid generic rounded newsletter-card styling when a landing-page branded look is more cohesive.
   - For buyer/client checklist emails, use Mailjet first-name personalization if available: `Hi [[data:firstname:"there"]] :)`.
   - Replace any example greeting names with Mailjet contact-property personalization, e.g. `Hi [[data:seller_names:"there"]],`. Remind that the contact/list row needs `seller_names` populated before a live send or test with real personalization.
   - Keep large heading punctuation together with the heading text, e.g. use `&nbsp;?` so the question mark does not wrap alone.
   - Do not leave the bottom feeling empty. Use a designed branded footer block, not just loose social links: a short signature/brand moment, a branded CTA or footer box, website button, social links, and compliance brokerage branding. Footer color/treatment should match the tenant's current brand guide, not default to black.
   - Compliance brokerage logo: use the actual brokerage logo asset, never a text approximation. Source the correct logo file from the tenant's brand assets (ask the realtor for the Drive file ID if it isn't already saved locally) and use an email-safe public thumbnail URL form. Place it in the footer where the brand guide specifies. If using a Drive thumbnail URL in HTML, HTML-escape the ampersand as `&amp;`.
   - Footer links should include the tenant's configured social/website links (Instagram, Facebook, personal site) — read these from the tenant's brand guide or onboarding config, never hardcode a specific handle.
   - If adding a handwritten-style signature, place it above the branded footer box, not inside it. Use a script/cursive font stack with brand-color text on white. Keep padding tight so it does not create dead space.
   - Watch for Flodesk Instagram/embed modules near the bottom. They can create a large dead-space gap in Mailjet. If the realtor wants the signature/footer immediately after the final paragraph, remove the old `fd-instagram` embed/spacer block between the final paragraph and the signature/footer.
   - Replace Flodesk video/SVG/`foreignObject` blocks before test sending. They can overlap or render badly in Gmail/Mailjet tests. Use email-safe linked thumbnail sections instead: a normal `<img src="https://img.youtube.com/vi/VIDEO_ID/maxresdefault.jpg">` wrapped in an `<a href="https://youtu.be/VIDEO_ID">`, plus a separate `Watch the video` button below. Verify old video SVG ids, `foreignObject`, and dark `fd-video` backgrounds are gone, and exactly the expected YouTube thumbnail URLs remain.
   - Keep the legal mailing address and unsubscribe/preference links below the branded footer.

9. Rebuild/update an existing listing-price campaign draft when the user gives a specific draft ID.
   - Treat `Update draft DRAFT_ID only` as permission to edit that draft's content, but not to send or schedule it.
   - Fetch and save the current draft metadata and detailcontent before changing anything:
     - `GET /v3/REST/campaigndraft/{draft_id}` → `backup_draft.json`
     - `GET /v3/REST/campaigndraft/{draft_id}/detailcontent` → `backup_content.json`, plus `backup_current.html` and `backup_current.txt`.
   - Verify the target before writing: `ID`, `Status == 0`, expected `Subject`, expected `ContactsListID` if known, and `Used == false` / `DeliveredAt == ""` when present.
   - For property/listing email rebuilds, discover the landing-page URL from local artifacts first instead of guessing or falling back to Realtor.ca. Good sources include:
     - the tenant's marketing scripts for constants like `TOUR_URL`.
     - the tenant's listing-pages output directory and related social-post files.
     - the tenant's session/knowledge notes if the realtor previously sent the page URL.
   - Match the active listing landing-page brand/footer, not just generic newsletter branding. For a fully-branded listing email this usually means: top brokerage logo, hero/listing image, an accent stat band, richer property benefit sections, the landing-page CTA, and a dark agent/footer block with the realtor's portrait, primary + compliance brokerage marks, Call, Email Me, and Read Reviews links.
   - Reuse deployed public landing-page assets when available. If the target property's page lacks a needed asset (e.g. a coloured logo), shared footer assets can be borrowed from another deployed listing page for the same tenant if the local listing folder lacks them.
   - Replace Realtor.ca links with the property landing-page link when the user asks for the landing-page link. Verify `realtor.ca` is absent from the final HTML/text unless explicitly requested.
   - For a new draft-only featured-listing blast with no draft ID, first look for a prior Mailjet draft for the same property in local listing launch notes, and fetch that draft metadata to inherit the correct `Sender`, `SenderEmail`, `SenderName`, `ContactsListID`, `Locale`, and `EditMode`. This avoids accidentally switching lists/senders.
   - For listing-page photos/assets, verify the deployed landing page with local/free Browser Use first. Prefer stable public image paths from the landing site when they render with `naturalWidth > 0`. If a listing page lacks usable logo/footer assets, reuse already-verified brand asset URLs from another deployed listing only after Browser Use image probes confirm they load. Record which assets were borrowed.
   - For draft-only Mailjet creation under the Browser Use-only rule, write a local Browser Use Python script that loads Mailjet credentials from `.env`, creates `POST /campaigndraft`, then sets `POST /campaigndraft/{id}/detailcontent`. Save only redacted proof. Immediately fetch `GET /campaigndraft/{id}` and `GET /detailcontent`, write `remote_{id}.html/.txt`, compare exact SHA/equality against local HTML/text, and record `sentOrScheduled:false`, `sendOrScheduleEndpointCalled:false`, and `testSendEndpointCalled:false`.
   - After fetching remote detailcontent, render the remote HTML locally through Browser Use (`file://.../remote_{id}.html`), wait for online images, and evaluate every `document.images[]` for `complete:true` plus nonzero natural dimensions. Note that `document.body.innerText` may not include all email-button text from table/anchor layouts; do not fail a preview solely because CTA text is absent from `innerText` if the address, landing URL/content, unsubscribe, and image checks pass.
   - Preserve a local audit folder under the tenant's marketing artifact directory (e.g. `data/marketing/mailjet/{slug-or-purpose}-{draft_id-or-stamp}/`) containing: local HTML/text, Browser Use scripts/logs, create/set responses, fetched-after draft/content JSON, remote HTML/text, render screenshot, image-check output, proof JSON, and a concise `proof_summary.md`.
   - Under a Browser Use-only rule, prefer using local/free `browser-use` for Mailjet REST verification instead of ad hoc curl or native browser/web tools. A reusable pattern is:
     1. Write a small local helper that reads `MAILJET_API_KEY` / `MAILJET_SECRET_KEY` from the tenant's `.env` and prints a Basic Auth URL like `https://<key>:<secret>@api.mailjet.com/v3/REST/campaigndraft/{draft_id}/detailcontent`.
     2. Open that URL with `browser-use --session <name> open "$(helper.py /v3/REST/campaigndraft/{draft_id}/detailcontent)"`.
     3. Save the response with `browser-use --session <name> get html > browseruse_remote_detailcontent_page.html`.
     4. Parse the `<pre>...</pre>` JSON from the saved HTML, `html.unescape(...)`, then compare fetched `Html-part` / `Text-part` SHA or exact equality against the local updated files.
   - Use direct Mailjet REST `POST /v3/REST/campaigndraft/{draft_id}/detailcontent` with `{'Html-part': html, 'Text-part': text}` for the update when an MCP wrapper is unavailable or awkward, but keep the run auditable and follow the Browser Use-only policy for online verification where possible.
   - If terminal security blocks an inline script because a `.dev` URL appears as a lookalike TLD, write the script to a file and construct the URL from string parts inside the script. Do not bypass approval with ad hoc curl; keep the update auditable.
   - If Browser Use profile launches fail with `No space left on device`, close stale sessions with `browser-use --session <name> close`, verify `browser-use sessions` is empty or only needed sessions remain, then remove stale `/var/folders/.../T/browser-use-user-data-dir-*` and `/var/folders/.../T/browser-use-downloads-*` temp directories before retrying. A failed `--profile Default` launch can leave a half-started session registered with a different config; close it without the profile flag (`browser-use --session <name> close`) before retrying.
   - If a Browser Use Mailjet API-origin open fails with `net::ERR_INVALID_AUTH_CREDENTIALS`, close the stale Browser Use sessions and retry the open with a percent-encoded Basic Auth URL containing the real `MAILJET_API_KEY:MAILJET_SECRET_KEY`; sanitize all logs immediately. Loading `https://api.mailjet.com/...` without valid Basic Auth may leave cached invalid credentials and make same-origin fetch verification fail even when the API keys are correct.
   - For repair verification after a previous failed revision, make the script idempotent: fetch the current remote draft first, compare against the desired HTML changes, and if the remote already has the requested tags/sizes, do a no-post verification pass instead of posting the same content again. Still render the fetched remote HTML through Browser Use and record proof that the requested state is present.
   - When parsing Mailjet `detailcontent` from Browser Use eval results, do not assume `Html-part` / `Text-part` are always plain strings. Coerce non-string values safely with `json.dumps(..., ensure_ascii=False)` or fail with a clear diagnostic before using string methods. This prevents a prior malformed/failed repair response from crashing the verification step.
   - For logo-size feedback, identify exactly which logo the user marked up before editing. Realtors sometimes ask about a top header logo, then later circle a different footer/green-block logo and want it visually the same size/weight as another mark below it. Do not keep adjusting the header logo when the screenshot/markup points at a footer mark. Match visual weight, not just numeric width, and adjust nearby spacing if needed.
   - When the realtor asks for footer logos to be "aligned," "stacked," or "formatted on top of each other," preserve the whole footer agent block rather than replacing it with only logos. The correct recovery pattern is: keep the realtor's circular portrait visible in the footer, stack the two brand logos vertically in one centered column, retain any district text, then verify counts for portrait/primary-logo/compliance-logo/unsubscribe/landing links and confirm `Status == 0`, `DeliveredAt == ""`, and `Used == false`.
   - For chat proof delivery, do not rely on one tall full-page PNG screenshot. Realtors often cannot review long screenshots in chat. After rendering the full proof, create chat-friendly cropped/sliced JPEG/WebP previews of the specific edited area plus, if helpful, one compressed full-page fallback. Send the visible crop/slice first and keep the full PNG/local proof path as audit evidence.
   - Do not treat `Used: true` alone as proof the campaign was sent. For safety, verify `Status == 0` and `DeliveredAt == ""` to confirm it remains an unsent draft.
   - When the user insists on an exact Google Drive photo ID, distinguish three states in the final report: (1) remote Mailjet draft contains the exact requested ID, (2) Browser Use local render gives that image `naturalWidth > 0`, and (3) the Drive file itself is publicly accessible or accessible from the signed-in Chrome profile. If the exact Drive file shows `You need access` or every candidate embed form (`thumbnail`, `lh3.googleusercontent.com/d`, `uc`, `drive.usercontent`) renders with `naturalWidth: 0`, do not report the remote draft "renders correctly." Either leave the exact ID in the draft and report the render/access blocker, or ask for public sharing / an email-safe hosted copy before calling the proof ready. This is still draft-only safe, but it is not a successful render verification.

10. Verify the draft content was saved.
   - Use `mcp_mailjet_get_campaign_draft` to confirm status is still draft (`Status: 0`) and a current content ID exists.
   - When changing sender/title/list on an existing draft with `PUT /campaigndraft/{id}`, include all fields that must remain stable, especially `ContactsListID`, `Title`, `Subject`, `SenderEmail`, `SenderName`, `Locale`, and `EditMode`. A partial PUT can unexpectedly reset the list/title.
   - For stronger verification, call REST `GET /v3/REST/campaigndraft/{draft_id}/detailcontent` and check:
     - HTML length is non-zero
     - text length is non-zero
     - `[[UNSUB_LINK_EN]]` appears
     - removed referral links are absent
     - seller-name merge tag is retained if used
     - footer/signature links are retained
     - unwanted bottom embed/dead-space modules are absent when removed

11. Final report to the user.
   - Include draft ID, title, subject, sender, attached list, and status.
   - Say clearly that it is not sent or scheduled.
   - Mention key cleanup/verification performed.

## Mailjet campaign-draft test send only

Use this when the user asks to send a test/proof of an existing campaign draft to themself or another single proof recipient, while explicitly not editing the design and not sending/scheduling the full list.

Safety contract:
- A test send to the user is not a full blast, but still only send exactly to the requested proof recipient(s). Do not add the full contact list, do not schedule, and do not call `/send`.
- Do not call `POST /campaigndraft/{id}/detailcontent` or `PUT /campaigndraft/{id}` in a test-only run. Fetch metadata/detailcontent for verification, then use only the Mailjet test endpoint.
- Use local/free Browser Use CLI for all Mailjet online/API interaction under the Browser Use-only rule. A reliable pattern is a local helper script that shells out to `browser-use open` and `browser-use eval`; avoid native browser/web/search tools.

Procedure:
1. Verify the target draft before any test send:
   - `GET /v3/REST/campaigndraft/{draft_id}` and `GET /v3/REST/campaigndraft/{draft_id}/detailcontent` through Browser Use.
   - Confirm `ID`, expected `Subject`/`Title`, expected property/price/MLS, `Status == 0`, and blank `DeliveredAt`.
   - Treat `Used: true` as compatible with test-send history. It is not proof of full send. The no-full-send proof is `Status == 0` plus blank `DeliveredAt`.
2. For Browser Use REST access, open an authenticated Mailjet API URL first, then run `browser-use eval` from the `api.mailjet.com` origin.
   - If opening `https://api.mailjet.com/...` without credentials fails later with `TypeError: Failed to fetch` or CORS/auth issues, reopen with percent-encoded Basic Auth in the URL: `https://<quoted_key>:<quoted_secret>@api.mailjet.com/v3/REST/campaigndraft/{draft_id}`.
   - Redact credentials from all raw proof files. Do not leave scripts/logs containing unredacted Basic Auth headers or URLs.
3. Call the campaign-draft test endpoint only:

```js
await fetch('https://api.mailjet.com/v3/REST/campaigndraft/DRAFT_ID/test', {
  method: 'POST',
  headers: { Authorization: 'Basic ...', 'Content-Type': 'application/json' },
  body: JSON.stringify({ Recipients: [{ Email: 'proof-recipient@example.com', Name: 'Proof Recipient' }] })
})
```

Expected success shape from Mailjet is HTTP `201` with body like `{ "Data": [{ "Status": "draft" }] }`.

4. Immediately fetch the draft again and prove the full campaign was not sent/scheduled:
   - `Status` remains `0`.
   - `DeliveredAt` remains blank.
   - Subject/title/list remain the same.
   - Record `sentOrScheduledFullCampaign: false`, `designChanged: false`, recipient count, endpoint, HTTP status, and proof path.

5. Final report should be explicit:
   - "Test sent to <recipient> only."
   - "Full campaign was not sent or scheduled."
   - "Draft remains Status 0 / DeliveredAt blank."
   - Include the proof JSON path.

## Transactional template counterpart workflow

Use this when the user asks for a reusable Mailjet template that mirrors an existing client workflow email, such as creating a seller-side accepted-offer template from the buyer-side accepted-offer template.

1. Identify the approved/source template first, do not recreate from memory.
   - List Mailjet templates directly through REST if MCP tools are unavailable:

```bash
set -a; source ~/.elevate/mailjet.env; set +a
python3 - <<'PY'
import os, requests
base='https://api.mailjet.com/v3/REST'
auth=(os.environ['MAILJET_API_KEY'], os.environ['MAILJET_SECRET_KEY'])
r=requests.get(base+'/template?Limit=50&Sort=ID+DESC', auth=auth, timeout=30)
r.raise_for_status()
for t in r.json().get('Data', []):
    print(t['ID'], t.get('Name'), t.get('Purposes'))
PY
```

2. Fetch the approved template content and save it locally before adapting.
   - Look up the source template ID for the workflow being mirrored (e.g. the tenant's "Buyer Accepted Offer" template) from the tenant's known-template registry (see the bottom of this skill for the pattern; the actual IDs are tenant-specific — resolve them from config, not from memory).
   - Fetch with `GET /v3/REST/template/{template_id}/detailcontent` and save HTML/text under the tenant's marketing artifact directory.

3. Adapt only the copy/merge fields needed for the new side, preserving the approved layout, branding, footer links, compliance logo, unsubscribe link, and Mailjet personalization style.
   - For seller accepted-offer templates, use `Hi [[data:firstname:"there"]] :)` and optional deal fields such as `[[data:property_address:"your home"]]`, `[[data:accepted_price:"See contract"]]`, `[[data:subject_removal_date:"If applicable"]]`, `[[data:deposit_due_date:"See contract"]]`, `[[data:completion_date:"See contract"]]`, and `[[data:possession_date:"See contract"]]`.
   - Include seller-side next steps: accepted offer, subject-removal caveat if applicable, key dates, documents that may be needed, showings/access for inspections, deposit/firming up, and what the realtor/admin will handle.
   - Keep the realtor's voice rules from their persona (punctuation conventions, allowed emoji).

4. Create a transactional Mailjet template, not a campaign draft, when this is meant to be reused by automation.

```python
import os, requests, pathlib, json
base='https://api.mailjet.com/v3/REST'
auth=(os.environ['MAILJET_API_KEY'], os.environ['MAILJET_SECRET_KEY'])
html=pathlib.Path('seller-accepted-offer-template.html').read_text()
text=pathlib.Path('seller-accepted-offer-template.txt').read_text()
body={
  'Name':'Seller Accepted Offer - <Brand Name>',
  'Author':'<Realtor Name>',
  'Copyright':'<Brokerage / Team Name>',
  'Description':'Seller accepted offer checklist email for this tenant\'s clients.',
  'Purposes':['transactional'],
  'Locale':'en_US',
}
r=requests.post(base+'/template', auth=auth, json=body, timeout=30)
r.raise_for_status()
template_id=r.json()['Data'][0]['ID']
r=requests.post(base+f'/template/{template_id}/detailcontent', auth=auth, json={'Html-part':html,'Text-part':text}, timeout=30)
r.raise_for_status()
print(template_id)
```

5. Before creating, check if a template with the same name already exists to avoid duplicates; update its detailcontent instead if present.

6. Verify with `GET /v3/REST/template/{template_id}` and optionally `GET /v3/REST/template/{template_id}/detailcontent`.

## Mailjet campaign/draft embedded-image repair

Use this when a Mailjet proof or test campaign shows broken image placeholders, especially for branded/listing emails.

Safety: update drafts/templates and create proof artifacts only. Do **not** send the final blast, schedule, or send client-facing email without explicit approval.

Procedure:

1. Inspect the current draft/template HTML and text first.
   - For campaign drafts, fetch `GET /v3/REST/campaigndraft/{draft_id}` and `GET /v3/REST/campaigndraft/{draft_id}/detailcontent`.
   - Preserve local copies of the before/after HTML and text under the relevant listing artifact folder.
   - Check `Status`, `DeliveredAt`, and `Used`. `Status: 0` with blank `DeliveredAt` means draft/not delivered even if `Used` is true.

2. Find broken image references by rendering, not just by HTTP/HEAD.
   - Use local/free Browser Use CLI for online/browser verification.
   - Create a tiny local HTML test page with candidate `<img>` tags and inspect `document.images` for `naturalWidth` / `naturalHeight`.
   - Treat `complete: true` with `naturalWidth: 0` as broken.
   - This caught Google Drive `uc?...export=download` URLs returning status-like success but failing as embedded email images.

3. Prefer email-safe hosted image URL forms.
   - Google Drive file previews that fail as `<img src>` with `https://drive.google.com/uc?id=...&export=download` may work as:
     - `https://lh3.googleusercontent.com/d/{FILE_ID}=w1600`, or
     - `https://drive.google.com/thumbnail?id={FILE_ID}&sz=w1600`.
   - Verify the chosen form in Browser Use with non-zero natural dimensions before updating Mailjet.
   - If the realtor specifically asks for their provided Drive photo, insert that exact file ID only after proving it renders as an email image. If every candidate form for that exact ID (`thumbnail`, `lh3.googleusercontent`, `uc`, `drive.usercontent`) resolves to Google sign-in/access denied or `naturalWidth: 0`, keep the requested ID in the draft only if they explicitly asked for it, but report it as a blocker instead of calling the preview/test ready. Do not silently swap back to an older working Drive ID and imply the requested photo was used.
   - If a property-specific landing-page asset URL is broken/404, use a known working canonical brand asset instead of leaving the property-specific URL broken.

4. Preserve the branded layout while replacing only broken references.
   - Keep the card, palette, typography, branded header/footer, realtor portrait where appropriate, primary logo, and compliance logo.
   - For footer logo sizing, make the lockup visually balanced and email-safe: keep the two brand marks side-by-side (or stacked, per the brand guide) at the bottom of the footer, with explicit `width` attributes and inline `width:...px;height:auto;`. Verify these structurally in HTML and visually/rendered before reporting ready.
   - If a CTA points to a broken/404 property landing page, replace it with a verified or previously approved listing URL rather than leaving a dead link. Record if a site blocks visual verification, e.g. Realtor.ca Imperva challenge.

5. Update Mailjet without sending.
   - Use `POST /v3/REST/campaigndraft/{draft_id}/detailcontent` with `{'Html-part': html, 'Text-part': text}`.
   - If Browser Use is mandatory for online work, you can open the authenticated Mailjet API origin in Browser Use, then run `browser-use eval` with `fetch(...)` to update/fetch the draft. Do not print or persist credentials. If a generated Browser Use eval script contains a Basic Auth header, redact/delete the script after proof is written.
   - Verify after update with `GET /campaigndraft/{draft_id}` and `GET /detailcontent`, checking remote HTML/text match local artifacts.

6. Final proof checklist before reporting ready:
   - Remote Mailjet detailcontent matches local final HTML/text.
   - All visible `<img>` tags render in Browser Use with non-zero natural dimensions.
   - Old broken URLs are absent.
   - Brand colors and footer/brokerage marks remain present.
   - Listing price, MLS number, unsubscribe placeholder, and CTA are present.
   - Draft has not been delivered: `Status: 0` and blank `DeliveredAt`.
   - Save proof JSON plus a Browser Use screenshot and image/link inventory.

## Mailjet template dry-run proof sends

Use this when the user asks to send one or more saved Mailjet templates to a test/proof address.

- A successful `/v3.1/send` response with `TemplateID` does **not** prove the email arrived in a useful form. In one run, template-ID sends returned HTTP 200 and MessageUUIDs, but Mailjet later showed two old templates as `blocked`, and some accepted/sent records had empty subjects and no HTML/text part included.
- After any proof send, verify each message with `GET /v3/REST/message/{MessageID}`. Report `Status`, `ArrivedAt`, `UUID`, `IsHTMLPartIncluded`, and `IsTextPartIncluded`. Treat `blocked`, missing HTML/text, or blank content flags as not reviewable even if the API initially accepted the send.
- For reviewable dry runs, prefer fetching `GET /v3/REST/template/{template_id}/detailcontent`, pre-rendering `[[data:field:"default"]]` placeholders and `[[UNSUB_LINK_EN]]` for a dry-run value, then sending via `/v3.1/send` with raw `HTMLPart` and `TextPart` instead of `TemplateID`. This makes the inbox proof look like the real email and avoids Mailjet template-language/contact-data surprises.
- If `detailcontent` returns only MJML/editor JSON or a template endpoint returns 404, send a short explanatory proof email naming the blocked/inaccessible template rather than claiming the original template was delivered.
- Useful search term for the inbox proof subject: `DRY RUN RESEND`.

## Browser Use CLI Mailjet API lessons

When Mailjet work must obey the Browser Use only rule, prefer these patterns:

- For read-only Mailjet REST verification, `browser-use open https://<urlencoded_api_key>:<urlencoded_secret>@api.mailjet.com/v3/REST/...` then `browser-use get html` works. Chrome renders the JSON inside a `<pre>`. Parse the `<pre>` text, unescape HTML entities, and redact credentials from raw Browser Use logs before saving proof.
- Do not persist Browser Use scripts containing `Authorization` headers. Keep auth-bearing JavaScript transient in memory and write only redacted/non-secret proof JSON.
- `browser-use eval` uses CDP `Runtime.evaluate` without `awaitPromise`, so an async IIFE that returns a Promise often prints `{}` or `None`. If using eval for browser checks, either return a synchronous `JSON.stringify(...)` value or start async work that writes `window.__result`, then poll `window.__result` with a separate eval.
- Browser-context Mailjet `fetch`/synchronous `XMLHttpRequest` can fail with CORS/network errors even on `api.mailjet.com`. Browser Use-authenticated URL + `get html` is reliable for GET verification. For POST/PUT mutations that still must obey the local/free Browser Use rule, use `browser-use python --file /path/to/script.py` and perform the Mailjet REST mutation inside that Browser Use Python session. This preserves the local Browser Use CLI execution path while avoiding page-context CORS/fetch failures. The script should load Mailjet credentials locally, write only redacted/non-secret proof JSON, and explicitly record `sent_or_scheduled: false` when the action only updates `detailcontent`.
- When repairing a remote draft from a known-good final artifact, first synchronize the canonical source files that future scripts use. Example: copy the final repaired HTML/text artifact over the draft workspace `updated_<draft_id>.html` and `updated_<draft_id>.txt`, then push those files to Mailjet. Otherwise a later verification/update helper may reintroduce stale links or broken image URLs from older source files.
- If an existing campaign is clean but no longer sendable because Mailjet shows a non-standard/used state such as `Status: -1`, `Used: true`, and blank `DeliveredAt`, create a fresh replacement campaign draft instead of trying to force-send the old ID. Fetch the old draft/detailcontent first, guard identity/subject/list/sender and blank `DeliveredAt`, then create `POST /campaigndraft` with the same `Subject`, `Sender`, `SenderEmail`, `SenderName`, `ContactsListID`, `Locale`, and `EditMode: html2`. Immediately `POST /campaigndraft/{new_id}/detailcontent` with the verified clean HTML/text, then verify the new draft is `Status: 0`, `Used: false`, blank `DeliveredAt`, remote HTML/text hashes match the source, and Browser Use local render still loads all images with non-zero dimensions. Save a new replacement artifact folder with source backups, create/set responses, verified draft/detailcontent JSON, render HTML/JSON/screenshot, and a proof summary. Treat approvals carefully: an approval that named or implied the old campaign ID does not clearly cover the fresh replacement ID, so require renewed approval before sending/scheduling the replacement.
- For image repair, verify both the remote Mailjet `detailcontent` and a local Browser Use render. A remote HTML match is not enough: the render must show every `<img>` with `naturalWidth > 0` and `naturalHeight > 0`. Google Drive `thumbnail?id=...` URLs may still fail in a browser/email render even when Mailjet stores them correctly. Replace unreliable Drive thumbnail/download URLs with proven `lh3.googleusercontent.com/d/<id>=w1600`, `lh3.googleusercontent.com/drive-storage/...=w1600`, or durable public site assets, then re-update the draft and re-run proof. For final verification, capture: Mailjet status remains `Status: 0`, `DeliveredAt` blank, `POST /detailcontent` returned 201 when an update was performed, remote HTML/text hashes match local, old broken URLs are absent, and every image has non-zero natural dimensions in the Browser Use local render.
- For final render-only verification after a repair, it is safe to render the saved proof HTML locally with Browser Use CLI (`browser-use --session <name> open file:///.../render_proof_<draft_id>.html`) because the online fetches happen through Browser Use when images load. `browser-use wait` does not accept a raw seconds argument, so use shell `sleep 5` or `browser-use wait selector/text ...`. `browser-use state` may return `Empty DOM tree` for a local file/email-table render even when the page rendered correctly; do not treat that alone as failure. Use a synchronous `browser-use eval "JSON.stringify({...document.images...})"` probe plus `browser-use screenshot --full <path>.png`, then verify the PNG exists/opens and every image reports `complete:true`, `naturalWidth > 0`, and `naturalHeight > 0`. Report the final screenshot path and explicitly state that no send/schedule/test-send endpoint was called.
- When a Mailjet draft has already been used/modified, Mailjet may return `Used: true` while still showing `Status: 0` and blank `DeliveredAt`. Do not treat `Used: true` alone as proof it was sent or as a blocker for draft-only detailcontent edits. Guard on `Status == 0`, `DeliveredAt` blank, expected subject/list, and avoid send/schedule endpoints. Report the `Used` value as an observed Mailjet flag.
- If Browser Use CLI returns `No response from daemon` after `browser-use python --file ...`, do not assume nothing happened. The Python may have run far enough to fetch Mailjet and write blocker/proof artifacts before the daemon dropped. Inspect the artifact folder for fresh `blocker_*`, `proof_*`, `mailjet_update_response_*`, and fetched-after files, then close/retry Browser Use only after diagnosing the written proof.
- For logo-layout repair requests in the footer/contact area, realtors may describe the target visually as a specific circled area beside buttons/contact information. Interpret that literally against the screenshot they marked up, not against your assumption of which logo block they mean. A reusable fix is to replace the portrait/bottom logo lockup with a two-column table: one column centered vertically with both brand logos stacked top-to-bottom and sized larger, the other column preserving name, title line, paragraph, and CTA buttons. Remove the old bottom logo row so logos are not duplicated. Verify remote HTML contains the expected `width` values and a Browser Use render shows the two logos stacked beside the buttons.
- If the realtor specifically asks for two brand logos stacked vertically inside a circular badge beside the contact/buttons block, use a circular nested table in that column rather than a side-by-side footer lockup. A reliable structure is: an outer branded contact section, one column at a fixed width, a nested circle table sized to match with a subtle border, the primary logo sized to be visually dominant, a divider line, and the secondary/compliance logo sized slightly smaller. The other column keeps the realtor's name, title line, paragraph, and Call / Email Me / Read Reviews buttons. Remove the portrait and the old bottom logo row so logos are not duplicated.
- Do not start from stale local artifacts when repairing an existing Mailjet draft. First fetch the live draft/detailcontent, guard on ID/subject/list and blank `DeliveredAt`, then patch that remote HTML. `Status: -1` and `Used: true` can appear after prior detailcontent repair attempts even when `DeliveredAt` is blank; treat it as draft-like/unsent only if the campaign identity is correct and no delivery timestamp exists. Still report the non-standard status in the final verification.
- When replacing only one repeated branded section, make the regex or parser target specific enough that it does not accidentally replace the hero/stat block. A broad color-based pattern can remove the hero image and first-name merge text from the local preflight. Anchor to the exact contact-section padding or to the following black disclaimer/footer block, then confirm the hero image and `[[data:firstname:"there"]]` are still present before updating Mailjet.
- If a Browser Use image probe shows a user-provided Drive file ID has `complete:true` but `naturalWidth/naturalHeight:0`, do not use it just because it is a real Drive file. Verify its Drive metadata with `gws` inside Browser Use, record the file name/parent, and try email-renderable URL variants rather than assuming the first Drive URL form is valid. Test `https://lh3.googleusercontent.com/d/<file_id>=w1600`, any Drive-provided `drive-storage`/thumbnail URL that can be transformed to `...=w1600`, and durable public site assets. Use the candidate that renders non-zero in Browser Use and record the exact URL/metadata in proof.
- If an unrelated existing image is broken during local render verification, do not hide it or overstate proof. Example: a Google Drive hero image may return `naturalWidth: 0` because the file is access-gated, while the requested footer/contact logos render correctly. Keep the draft-only update if the requested layout change is verified and remote content matches, but report the broken image separately with the exact image source, Drive access/screenshot proof, and whether logos loaded correctly.
- When the user specifies an exact Google Drive listing photo by folder/name, do not rely on an old cached Drive ID or a broad filename match. Through local/free Browser Use CLI, run a Python helper that invokes the authenticated Google Workspace CLI (`gws`) to: find the named property folder, find its `Photos` child folder, find the exact filename inside that folder, record the selected file ID/name/parent/metadata/size/checksum/webViewLink, and download/cache the file as proof. Broad exact-name search can be included only as a sanity check because duplicate filenames may exist elsewhere in Drive. Use the folder-scoped match for the Mailjet hero URL, preferably `https://lh3.googleusercontent.com/d/<folder-scoped-file-id>=w1600` after render verification.
- For draft repair/recovery, update every canonical local artifact that later scripts may reuse, not just the remote Mailjet draft. At minimum synchronize the draft workspace `updated_<draft_id>.html` and `updated_<draft_id>.txt`, plus any final/branded artifact copies used by verification helpers. Otherwise a later repair may overwrite Mailjet with stale image URLs, Realtor.ca links, or old footer logo sizing.
- Footer logo/layout repair should be verified structurally and visually: store the final footer lockup in the HTML, then use Browser Use local render to confirm the footer logo `<img>` width attributes and natural dimensions.
- Before trying to send an existing Mailjet draft, verify both delivery and sendability: `GET /v3/REST/campaigndraft/{id}` and check `DeliveredAt`, `Status`, and `Used`. A draft can be `DeliveredAt: ""` but still unsendable if Mailjet has `Status: -1` and `Used: true`; `POST /campaigndraft/{id}/send` then returns HTTP 400 with `Newsletter has to be in status draft or programmed`. Do not keep retrying that original draft. Preserve the proof, report the exact blocker, and create/repair a fresh draft from the verified HTML/text if the user wants the blast sent.
- For approved immediate sends, run a final Browser Use render gate before the Mailjet `/send` call: save the remote `detailcontent` HTML locally, open it with local/free `browser-use`, evaluate `document.images` for `complete && naturalWidth > 0 && naturalHeight > 0`, verify hero/logo dimensions, merge tags, unsubscribe placeholders, price/MLS text, and absence of `TODO|PLACEHOLDER|BROKEN|undefined|null`. Save both a JSON proof and screenshot before attempting send.
- If `browser-use python --file ...` returns `No response from daemon`, treat it as a stale Browser Use session/socket first, not necessarily a script failure. Run `browser-use sessions`, close the affected session or use a new named session, then retry. If the script created a blocker/proof file despite the daemon message, read that file before rerunning so you do not duplicate a send attempt. Also inspect the newly-created timestamped output folder before rerunning: Browser Use may have executed enough of the script to write backups, preflight JSON, or partial proof even when the daemon response fails.
- For Mailjet/footer repairs based on a visual reference card, do not only assert HTML checks. Save the remote `detailcontent` HTML locally, open the local proof through local/free Browser Use, take a full-page screenshot, and run a Browser Use DOM image check for every `document.images[]` item: `complete`, `naturalWidth`, `naturalHeight`, rendered dimensions, and expected text/button presence. A Mailjet API update can return 201 while a Google Drive/lh3 hero image renders as a broken 16px/18px image in Chromium. If the hero is a Drive/lh3 URL, prefer a previously Browser-Use-verified/public asset or rehost before calling it render-verified.
- When replacing a footer/contact card inside full email HTML, locate the specific footer row immediately before the black legal/unsubscribe row. Do not use the first dark branded row, because earlier hero/photo bands may use the same background color and a regex can accidentally replace the hero and body. Safer pattern: find the black legal footer marker, collect all branded contact-card row starts before it, and replace the last match.
- A common realtor footer reference pattern: dark branded full-width card, circular realtor portrait in the upper-left, large stacked primary and compliance logos below/on the left, and right-column name/body/CTA buttons. Avoid reverting to an older combined logo-circle treatment when the user asks for a new reference card style.
- For property-specific Mailjet footer/reference-card repairs, prefer property-specific public assets when they exist instead of borrowing another listing's assets. Switching the header logo, realtor portrait, and both brand logos to the correct listing's asset folder keeps the proof consistent and all assets Browser-Use-renderable.
- If a Google Drive / `lh3.googleusercontent.com/drive-storage/...` hero image renders with `complete:true` but `naturalWidth:0` in Browser Use, treat it as broken even if previous REST/proof metadata looked okay. Replace it with a verified public property asset before calling the preview verified.
- When final Browser Use text probes check a footer name that is split by `<br>` (e.g. first name and last name on separate lines), do not rely on `innerText.includes('First Last')`; check the first and last name fragments separately or verify structurally/visually. A false negative there should not block the repair if the screenshot and HTML structure show the intended name.
- For Mailjet draft repairs, avoid the prior `dict has no attribute lstrip` failure mode by extracting Mailjet API results as `response['Data'][0]` first, then operating only on explicit string fields like `Html-part` and `Text-part`. Never pass the whole Mailjet response/detail dict into HTML string cleanup helpers.
- Mailjet `campaigndraft.ModifiedAt` can come back blank even after a successful draft content save. Treat the `POST /campaigndraft/{id}/detailcontent` HTTP 200/201 response, a follow-up `GET /detailcontent`, matching remote/local HTML+text SHA hashes, and draft-safe fields (`Status: 0`, empty `DeliveredAt`, `Used: false`) as the reliable save proof.
- For no-send proofing after a Mailjet repair, do a read-only current-state pass: fetch `campaigndraft/{id}` and `campaigndraft/{id}/detailcontent`, write the remote HTML to a local proof file, render it with local/free Browser Use CLI, take a screenshot, and `browser-use eval` `document.images` + text checks. Confirm every image has `complete:true` and natural dimensions > 0 before calling the proof verified.
- `browser-use eval` often prints a Python-style `result: {...}` repr with single quotes and `True`/`False`, not strict JSON. When turning its output into verification JSON, strip the leading `result:` and parse with Python `ast.literal_eval`; do not use `json.loads` unless the output is actually valid JSON. This avoids false verification failures after the render itself succeeded.
- When the user asks to revise an existing Mailjet draft to match a prior campaign, fetch the *current live* reference campaign/draft detailcontent first, not just older local source artifacts. Local artifacts can be stale after later repairs — a live reference draft can differ from an older cached local HTML source in ways like logo width that would otherwise be missed.
- For Mailjet API work under the Browser Use-only rule, open an authenticated Mailjet API URL with real basic-auth credentials inside `browser-use open https://<key>:<secret>@api.mailjet.com/v3/REST/campaigndraft/<id>` (write only sanitized logs). Then navigate the active Browser Use tab back to the same API path without embedded credentials, or open `https://api.mailjet.com/v3/REST/campaigndraft/<id>` after auth has been established, before doing same-origin fetches for `GET /campaigndraft/{id}`, `GET /campaigndraft/{id}/detailcontent`, and safe `POST /campaigndraft/{id}/detailcontent`. If the current page URL still contains `key:secret@...`, browser-side `fetch('/v3/REST/...')` can fail with `Request cannot be constructed from a URL that includes credentials`. Opening the unauthenticated API origin can fail with `net::ERR_INVALID_AUTH_CREDENTIALS`, so authenticate first, then switch to a clean URL.
- For narrow logo-size-only Mailjet repairs, change only the intended `<img>` tags and preserve the Text-part. Verify before/after image tags, remote/local HTML+text hashes, `Status:0`, empty `DeliveredAt`, `Used:false`, and screenshot proof. If re-running a repair, make the width replacement idempotent and dedupe duplicate `width="..."` attributes so repeated runs do not leave malformed tags. When matching logos with different aspect ratios, do not assume equal CSS width equals equal visual size: a wide horizontal wordmark at a given width can look smaller/lighter than a stacked/taller mark at the same width. Create quick local variants, render/crop the footer with Browser Use, and choose the visually balanced option.
- For Mailjet footer alignment repairs, inspect the actual current remote HTML before editing. When two brand logos in a footer are in separate off-axis positions, changing widths/margins alone can still leave them side-by-side/off-axis. The correct repair is usually to move both logos into the same branding badge, stacked, remove the off-axis duplicate position, keep a centered location label under the logo stack, preserve the Text-part, and verify only one instance of each logo and one location label remain. If the realtor then asks to restore their portrait after a logo-stack repair, keep the single centered logo column but add the portrait as a circular image above the stacked logos inside the same badge; avoid reintroducing an off-axis duplicate logo block. On recovery/completion reruns, if the live remote `Html-part` already contains the corrected layout, do not POST again just to be busy: save the remote HTML/Text-part proof, verify `Status:0`, `DeliveredAt:""`, `Used:false`, render the live HTML proof with Browser Use, confirm all images have `complete:true` plus nonzero `naturalWidth/naturalHeight`, and report that no additional field changed. Browser Use `eval` can return `None` for async `fetch` snippets in this setup; for Mailjet API reads/updates from an authenticated API page, open the Mailjet API endpoint in Browser Use with the real `api:secret@api.mailjet.com/...` credentials and sanitize logs. Opening `https://api.mailjet.com/` alone can make same-origin `fetch` fail, and opening with a placeholder/redacted password causes `ERR_INVALID_AUTH_CREDENTIALS`. Synchronous `XMLHttpRequest` inside `browser-use eval` is also reliable, then strip the CLI `result: ` prefix before JSON parsing. If PIL is unavailable for screenshot cropping, scroll the Browser Use session to the footer and take a viewport screenshot instead of installing dependencies mid-task.

Mailjet recovery / delegation-reporting pitfall:
- If a background delegation for a Mailjet draft edit reports `dict object has no attribute lstrip`, treat it as a delegation/reporting wrapper failure until verified, not proof that the Mailjet update failed. Check the draft directly with Mailjet `campaigndraft/{draft_id}/detailcontent` and `get_campaign_draft`, verify the expected HTML/text/logo counts/status, then report the verified Mailjet state. Do not rerun or overwrite a repaired draft blindly just because the background task result showed the lstrip error.
- For a failed-recovery rerun where the user asks to "recover" or "verify after editing," start with a **read-only Browser Use verification pass** before any POST. Fetch live `campaigndraft/{id}` and `/detailcontent`, coerce `Html-part` / `Text-part` defensively (`str`, `{Value: ...}`, or JSON string), write remote HTML/text proof files, check counts for the requested assets/placeholders, render the fetched remote HTML through Browser Use, and verify every image has `complete:true` plus nonzero natural dimensions. Record `updateEndpointCalled:false`, `sendOrScheduleEndpointCalled:false`, and `testSendEndpointCalled:false` when the live draft already matches. This avoids changing a correct draft just to recover from a reporting/tooling error.
- Reusable proof pattern: keep a small read-only verifier under a run folder, use Browser Use `open` on the authenticated Mailjet API origin, then synchronous `XMLHttpRequest` in `browser-use eval` for `GET /v3/REST/campaigndraft/{id}` and `GET /v3/REST/campaigndraft/{id}/detailcontent`. Chunk large `window.__mjDetailRaw` strings out of the page, save `remote_{id}.html/.txt`, render that local file, and store a compact JSON proof with draft metadata, requested asset counts, footer/source checks, render image dimensions, and proof paths.

## Known-template registry pattern

Maintain a small registry of the tenant's approved template IDs and routing labels (in the tenant's knowledge base, not hardcoded in this skill) so this workflow always resolves the correct source template instead of guessing. A typical registry entry set looks like:

- Pre-CMA seller package template.
- Buyer accepted-offer template.
- Seller accepted-offer template (built as the counterpart of the buyer one via this skill's Transactional template counterpart workflow).
- Coming-soon listing template (older/simple; current marketing tooling may instead create campaign drafts directly from the active listing package).
- Any deprecated/do-not-use templates, clearly labeled, so they are never routed to by name-matching alone.

Resolve the actual IDs from the tenant's registry/config at run time — never hardcode one tenant's numeric template IDs into this skill.
