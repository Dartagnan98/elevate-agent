---
name: cma-pdf-internal-share
description: Find, verify, and email the newest CMA PDF for a property internally to the realtor only. Use when the realtor asks to share, send me, or email me a CMA PDF, or wants the latest CMA report delivered internally. Not for sending CMA materials externally to clients or sellers.
version: 1.0.0
author: elevate
metadata:
  elevate:
    tags: [real-estate-admin, cma, email, artifacts]
---

# CMA PDF Share to Realtor

Use this when the realtor asks for the latest CMA PDF to be emailed to her. Treat the request as approval to send **to the realtor only**. Do not send to clients unless she explicitly asks and approvals/client-delivery policy is satisfied.

## Steps

1. **Identify the deal/property**
   - Start with `deals_overview` and locate the matching property/deal by address.
   - If the address is not obvious, query `deals` / `deal_attachments` through `elevate_db` rather than searching blindly.

2. **Find the most recent CMA PDF attachment/artifact**
   - Query `deal_attachments` for the deal, newest first:
     - `kind` like `cma_report`, `cma_report_*`, or relevant email proof rows.
     - Prefer the newest actual `.pdf` attachment over proof JSON.
   - Also search the local CMA artifact folder for newer regenerated files when the user says a delivery failed or names a recent revision that may not have been attached yet:
     - `search_files(target='files', path='<cma-artifacts-root>', pattern='*<address>*pdf')`
     - Prefer filenames that encode final/client-ready/revision state, e.g. `CLIENT-READY`, price, `PROSPECTING`, and current date.
   - If a newer proof JSON references an email but the actual PDF row is just below it, use that newest PDF path.

3. **Verify the PDF before sending**
   - Check the file exists and has non-zero size.
   - If `pdfinfo` is available, verify page count, letter page size, and that it is not encrypted/broken.
   - Use `pdftotext` proof files or generate extracted text and check for:
     - correct address/property
     - `Market Evaluation` / CMA language
     - current recommended price
     - stale prices/addresses absent
     - any named revision content present (for example, prospecting-tool section text, MLS anchor, screenshot caption, search-count numbers).
   - For CMA visuals, verify the photo manifest if present. Confirm photos are Xposure/MLS verified and that each comparable has at least 6 photos, ideally 8, when available.
   - Use the flattened/openable/client-ready PDF where available, especially if older PDFs had rendering issues.
   - If automated visual QA says `needs_visual_review`, that is not automatically a failure. Open/read the generated contact sheet or screenshots with vision and confirm it visually matches the approved client-ready Market Evaluation style before delivery.

4. **Deliver internally to the realtor only**
   - If the realtor asks for delivery in the current chat thread only, do not email. Return the PDF as a `MEDIA:/absolute/path.pdf` attachment in the final response and state that no client/external send occurred.
   - If she asks to email it internally, use the realtor's own configured personal/internal email unless she specifies otherwise.
   - Keep the body short and in the realtor's style if writing as the assistant:
     - Warm one-line greeting using her name.
     - Mention the attached CMA PDF.
     - If relevant, add a caution such as: keep it as internal review unless/until the comp photos are verified from Xposure/MLS.
   - Do **not** send to sellers/clients from this workflow.

5. **Email transport fallback order**
   - If an approved email tool with attachment support is loaded, use it first.
   - If using terminal email:
     - Himalaya may not be installed even when the skill exists. Verify with `himalaya --version` before relying on it.
     - Gmail SMTP can fail with `Application-specific password required` even when `GMAIL_USER` / `GMAIL_PASSWORD` exist in the configured credentials env file.
     - For Gmail API via `gws`, do **not** pass a base64 RFC822 email with attachments in `--json` when the PDF is several MB; this can fail with `OSError: [Errno 7] Argument list too long`. Instead write the full RFC822 message to an `.eml` file under the CMA run directory and use media upload:
       `gws gmail users messages send --params '{"userId":"me"}' --upload email_tmp/<message>.eml --upload-content-type message/rfc822 --format json`
       Run the command with `cwd` set to the CMA run directory because `gws --upload` rejects paths outside the current directory. Verify the sent message with `gws gmail users messages get` and metadata headers `To` and `Subject`.
   - If Gmail SMTP fails and Mailjet transactional credentials are available in the configured credentials env file, Mailjet `/v3.1/send` can send a PDF attachment using base64 `Attachments`. Use only for internal delivery to the realtor unless approvals/client policy allows otherwise.
   - Never print API secrets. Parse env files in Python and print only safe delivery IDs/status.

6. **Record proof**
   - Write a JSON proof beside the CMA artifacts, ideally under an `email_proofs/` folder.
   - Include:
     - timestamp
     - channel/transport
     - from/to/subject
     - attachment path/name/byte size
     - provider message id / UUID
     - note that it was sent only to the realtor, not clients

7. **Final response**
   - Confirm it was sent.
   - Name the attached file.
   - State clearly that it went only to the realtor, not the clients.
   - Include any internal-review caveat if the PDF uses unverified comp photos or other draft material.

## Pitfalls

- Do not treat the newest email proof JSON as the attachment. It is proof, not the PDF.
- Do not use stale draft PDFs if a newer flattened/openable CMA report exists.
- Do not send client-facing CMA materials to sellers without explicit approval.
- For CMA visuals, comp photos should be verified from Xposure/Matrix/MLS, ideally 6 to 8 photos per comp when available. If a report used unverified public thumbnails, call that out as internal-review only.
- Board-sync is not required when the task is only finding/sending an internal artifact and no deal stage, checklist item, price, or key date changed.

## Verification checklist

- Matching deal/address confirmed.
- PDF path selected from newest relevant attachment.
- File exists, non-empty, and page count/render health checked when possible.
- Email send returned provider success.
- Proof JSON saved.
- Final user response includes filename and internal-only status.
