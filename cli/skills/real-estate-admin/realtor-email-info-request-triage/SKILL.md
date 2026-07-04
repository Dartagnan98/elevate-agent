---
name: realtor-email-info-request-triage
description: "Triage another agent's email asking for factual listing or deal facts. Use when the realtor asks to find that email, pull source-backed answers, and either send a verified reply or draft one if anything is missing or risky."
metadata:
  elevate:
    tags: [real-estate, admin, gmail, deal-matching, email-reply, safety]
---

# Realtor Email Info Request Triage

Use this when the realtor asks you to find an email from another agent/realtor asking for listing/deal information, extract exactly what they requested, gather factual answers, and either send a concise reply or draft one if anything is missing or risky.

## Safety rule

Only send if every requested answer is factual, source-backed, and non-risky. Draft only if the request touches any of:

- A decision or recommendation.
- Price, strategy, negotiation position, contract/legal interpretation, disclosure risk, or client-sensitive judgment.
- Missing or unverified facts such as lockbox/access codes, roof age, mechanical age, seller instructions, accepted-offer details, tenancy, exclusions/inclusions, or condition/disclosure facts.

If any requested item is missing, draft the reply and clearly identify the blocker in the final report.

## Procedure

1. **Search Gmail for the sender and latest relevant message.**
   - Prefer `gws` when available.
   - Example:
     ```bash
     gws gmail users messages list --params '{"userId":"me","q":"from:agent@example.com","maxResults":10}' --format json
     gws gmail users messages get --params '{"userId":"me","id":"MESSAGE_ID","format":"full"}' --format json
     ```
   - Capture message ID, thread ID, subject, date, sender, recipient, and snippet/body.
   - For “continue the reply” tasks, fetch the full Gmail thread before drafting/sending:
     ```bash
     gws gmail users threads get --params '{"userId":"me","id":"THREAD_ID","format":"full"}' --format json
     ```
     Check whether the realtor/assistant already sent a partial reply. If yes, do **not** duplicate it; send only the newly verified follow-up facts, and keep any still-unverified items out of the email.

2. **Extract exactly what was requested and what has already been answered.**
   - Separate each requested fact/question into bullets.
   - Mark each item as `answered`, `verified_now`, or `still_blocked` after reading the thread.
   - Do not answer broader inferred questions unless the email clearly asks for them.

3. **Match to the correct deal/listing.**
   - Use strongest identifiers first: exact address, MLS number, deal ID, sender/contact match.
   - Start with `deals_overview` for active deals, then query `deals`, `deal_events`, `deal_attachments`, and `notes` with `elevate_db` as needed.
   - If identifiers conflict or multiple deals match, stop and return candidates instead of drafting/sending.

4. **Gather source-backed facts.**
   - Query the matched `deals.extra_toggles_json` plus structured fields like address, MLS number, listing date, list price, year built, legal/PID, dates, stage, etc.
   - Check `deal_attachments` summaries for source docs, marketing copy, property reports, Matrix handoffs, MLCs, and audits.
   - Read local artifacts if paths exist. Common useful sources:
     - Marketing copy PDF or approved listing copy for public feature/mechanical details.
     - MLC/signed listing package for listing price, effective/expiry dates, seller authority, and basic address/legal facts.
     - BC Assessment/property lookup for year built, beds/baths, lot size, assessment data.
   - If recorded paths are stale/missing, search by address slug under `/Users/admin`, `<project-tools-dir>`, `/Users/admin/shared-team-brain/files`, and `<realtor-tools-dir>` before giving up.
   - For PDS/title/title-charge requests:
     - Match the deal by exact address and MLS first, then confirm PID/legal/title number from `deals`, `extra_toggles_json`, or the title search text.
     - Locate the PDS by address slug in current listing folders and shared-team-brain/archive folders, not just `deal_attachments`; older signed PDS files may live under `shared-team-brain/files/1 - Client Files/Archives/Incomplete YYYY/<address>/`.
     - Use `pdftotext`/`pdfinfo` to verify the PDS and title search actually reference the subject property/address/PID before packaging.
     - Parse the title search for **all** Charges, Liens and Interests. Include separate non-financial instruments only; exclude mortgage/financial charges unless the user explicitly asks for them.
     - Also parse **Legal Notations**. If the title references permit/legal-notation numbers, search for separate Land Title instruments by registration number. Treat missing legal-notation instruments as a blocker/gap, because the title search alone is not the same as the separate non-financial legal notation package.
     - Package the available PDFs into a clearly named outgoing folder/zip with a README listing included docs, excluded financial charges, and any missing legal-notation instruments.
     - Realtors typically do **not** save financial title charges as part of these listing packages by default. Do not treat missing mortgages/other financial charges as a blocker, and do not go hunting for them unless the realtor explicitly asks. If non-financial legal-notation instruments are missing after a reasonable search, route that as a clear gap/approval item; if the realtor approves sending what is available, send the available PDS/title/non-financial package with a concise gap note rather than continuing to block.
   - For listing feature/update questions, also search the deal's `extra_toggles_json` for `sourceArtifactRoot`, then inspect address-slug artifacts in that root. Useful reusable files include `*-walkthrough-notes-structured.json`, `*-client-overview-fireflies-notes.txt`, CMA HTML/PDF, parsed property data, and archived `subject-analysis.json` files. These may contain realtor-verified upgrade/mechanical/roof notes that are not in the signed MLC.

5. **Decide send vs draft.**
   - Send only if all facts included in the reply are verified and low-risk.
   - If the original request has multiple items and only some are verified, you may send a narrow follow-up containing only the newly verified facts **when the thread already has a prior partial reply or the user explicitly asks to send what is verified**. Do not mention or answer the still-unverified item in the email unless saying the realtor is confirming it is necessary for context.
   - Draft instead of sending if the missing item is central to the requested reply, if the first response would need to acknowledge a blocker, or if any wording could imply unverified access/lockbox/seller-instruction/disclosure details.
   - For client-facing or agent-facing wording, match the realtor's style: casual, concise, no em dashes when possible, `Hi/Hey Name :)`, warm but not over-explaining.

6. **Create/send through Gmail.**
   - For draft replies, create a draft in the same thread with `threadId`, `In-Reply-To`, and `References` set from the original email.
   - For user-approved sends with multiple PDFs/large attachments, build the MIME message in Python and send through Gmail REST `users.messages.send` using the existing `gws` OAuth credential/token flow instead of passing the base64 MIME as a huge command-line argument. The `gws --json "$payload"` path can fail with shell `argument list too long`; direct REST avoids argv limits while using the same authorized Gmail account.
   - After any direct REST send, verify with Gmail by fetching the returned message ID and checking it has the `SENT` label. Save proof JSON with message ID, thread ID, subject, timestamp, recipients, and attachment filenames.
   - Example draft creation pattern:
     ```python
     from email.message import EmailMessage
     import base64, json, shlex

     msg = EmailMessage()
     msg['To'] = 'Name <email@example.com>'
     msg['From'] = 'Realtor Name <realtor@example.com>'
     msg['Subject'] = 'Re: Original subject'
     msg['In-Reply-To'] = '<original-message-id>'
     msg['References'] = '<original-message-id>'
     msg.set_content(body)
     raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip('=')
     payload = json.dumps({'message': {'raw': raw, 'threadId': thread_id}})
     # gws gmail users drafts create --params '{"userId":"me"}' --json "$payload" --format json
     ```
   - Verify the created draft with `gws gmail users drafts get` and capture draft ID/message ID.

7. **Record proof on the deal.**
   - Attach the draft/send proof to the deal with `admin_deal(action='attach')` using a `gmail://draft/<draft_id>` or `gmail://message/<message_id>` style path.
   - If `admin_deal` cannot add arbitrary events, use an attachment summary for the audit trail.

8. **Final report shape.**
   - State whether sent or drafted.
   - Include original email proof: sender, subject, date, Gmail message ID/thread ID.
   - List exactly what was requested.
   - List the verified facts gathered.
   - If drafted, include the blocker and the draft body.
   - Include draft/send proof IDs.

## Pitfalls

- Do not send when access/lockbox details, roof age, mechanical age, or seller disclosures are missing. These sound factual but can create risk if guessed.
- Gmail snippets can be enough to identify relevance, but fetch full payload before extracting exact requests.
- `gws` may warn about token-cache decryption but still work through keyring; treat successful API output as usable.
- Some stored attachment paths may no longer exist locally even when the deal record references them. Search the filesystem by address slug before concluding the artifact is unavailable.
- PDS/title package requests often live partly outside the deal record. Check shared-team-brain archives and older incomplete-listing folders for the PDS and title-charge PDFs.
- Title searches can list both charge instruments and legal notations. Do not represent a title package as complete when legal-notation instruments are missing; either retrieve/order them or route approval with a clear gap note.
- `gws drive files get --params '{"fileId":"...","alt":"media"}'` may save binary content as `download.pdf` or `download.bin` in the current working directory. Move/rename immediately before the next download so files do not overwrite each other. `gws drive files download --output` can reject paths outside the current directory.
- Large Gmail draft payloads with attachments can exceed shell argument limits if passed as `gws --json "$payload"`; `gws --json @file` is not supported in this environment. Prefer provider/API client tooling that accepts request bodies without giant argv, or stop with the prepared package plus approval/blocker rather than forcing a send.
- If Apple Notes `memo` is unavailable, do not block. Continue through Elevate DB notes, Drive files, local `<realtor-tools-dir>/scripts/output` artifacts, and session/archive files.
- `admin_deal` may not support an `add_event` action; use `attach` with a concise summary to leave proof on the deal.
