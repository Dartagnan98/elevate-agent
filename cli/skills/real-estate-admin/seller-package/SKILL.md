---
name: seller-package
description: "Draft the pre-appointment seller package email after a listing appointment is booked. Use when the realtor says 'send the seller package', 'prep for the listing appointment', or 'draft the pre-listing email' for a booked seller. Collects verifiers (name/email/phone/address) and, on approved send, promotes the contact to the /admin listing kanban at stage 0 (CMA / Prospect). On the Pre-CMA stage-entry or resume trigger (mode: pre_cma) it AUTO-SENDS approved Mailjet template 8055687 -- adding the card to Pre-CMA IS the approval. Every other invocation drafts and waits for explicit approval. Not for post-list showing-feedback emails — use seller-update; not for the CMA itself — use cma."
metadata:
  elevate:
    tags: [real-estate, seller, email, pre-listing, admin-entry]
    runtime:
      # Pre-CMA stage-entry/resume runs SEND (see the send exception in Rules).
      # Approval applies to every OTHER invocation.
      approval_required: false
      pre_cma_auto_send: true
      result_writer: admin-result-writer
      promotes_to_admin: true
      admin_side: listing
      admin_entry_stage: 0
---

# Seller Package

Use after a seller appointment is booked. This skill is the **entry point** for the /admin listing kanban — on approved send, the contact is promoted to listing-side stage 0 ("CMA / Prospect"). CMA work then runs against the new deal.

Draft the seller package email using the realtor profile, brokerage details, appointment context, property address, and any local/regional memory. Create a Gmail/Outlook draft or human approval task. Do not send directly — **except on the Pre-CMA stage-entry trigger, which auto-sends approved Mailjet template `8055687`. See "Pre-CMA stage-entry send exception" below.**

## Position In Flow

```text
Lead in /leads (listing_active=1)
→ seller-package: collect verifiers + draft email
→ human approval
→ send seller package
→ close_to_admin(side='listing')   ← lands on /admin kanban stage 0
→ cma + listing-intake (stage 0 → 1)
→ MLC / listing paperwork (stage 2)
```

## Required Inputs

**Only these hard verifiers can block a draft** — they are what promote the contact to /admin:

- `contact_id` — the contact in /leads being closed into admin.
- `seller_names` — full legal name(s) of the seller(s).
- `seller_email` OR `seller_phone` — at least one reachable channel (both is better; either one is enough to draft).
- `listing_address` — property address (line + city + province + postal code if known).
- Realtor profile, brokerage, value proposition, and local proof points from memory/onboarding.
- Email account for draft creation.

**Optional — never block on these. Record if present, otherwise proceed and leave blank:**

- `appointment_date` — date/time of the listing appointment. A pre-CMA / pre-appointment package routinely has no appointment yet. Missing appointment_date is NOT a reason to park `waiting_human`; draft the package anyway.

Only return `status: "waiting_human"` when a hard verifier above (name, address, or a reachable email/phone) is genuinely missing AND cannot be enriched from Contacts/CRM/Gmail/iMessage. List only those in `requiredFields`. Never park a draft for a merely-nice-to-have field.

**Never fabricate a field to avoid parking.** Leaving an optional field (appointment date, etc.) blank is correct; inventing a value for it is a defect. Only write values that came from a real cited source (intake form, a CRM record you read, or the user). Never guess a name, email, phone, address, appointment, or date.

## Rules

### Pre-CMA stage-entry send exception (Skyleigh, confirmed 2026-07-02, RESTORED 2026-08-21)

When this skill is invoked by the **`S0 Prepare Pre-CMA seller package` stage-entry trigger** (registry `abb8a10381ca4a4d8ea69230cfb2b6d9`, `mode: pre_cma`), **SEND — do not park an approval card.**

- Skyleigh treats *adding the seller to the Pre-CMA column* as her approval. Asking again is a second gate in front of a decision she already made, and it is how a seller ends up getting nothing at all. On 2026-08-20 Tod Wouters (426 Gleneagles Drive) received no package for a full day because this exception had gone missing from the skill and the run parked instead.
- **Send ONLY template `8055687`**, `TemplateLanguage: true`, `Variables: {"seller_names": <first names only>}`. Everything in the approved-template rules below still binds: if the template cannot be read or rendered, STOP `waiting_human`. **Never** compose, rebuild, or `html2` a substitute. The absence of the template is never authorization to write one.
- The ONLY thing that may block this send is a genuinely missing hard verifier (seller name, or a reachable email/phone). Park `waiting_human` for that, and when the missing value later lands on the deal, **RE-RUN and send** — see "Resuming after the info arrives" below.
- Every OTHER client-facing send (non-Pre-CMA, or any template that is not `8055687`) still requires explicit human approval. This exception is narrow on purpose.

### Resuming after the info arrives

The dedup rule further down ("Stage 0 burst superseded by CRM/contact verification") stops a duplicate draft while a sibling contact-verification card is still open. It must NOT become a permanent silence:

- If the sibling card was **answered** and the deal now HAS a reachable seller email/phone, and Mailjet shows **no** package ever sent to that address, then send the package. The supersede was a "wait", not a "never".
- If the sibling card was **declined/cancelled** and the contact details are present anyway, same thing: send.
- Only stay silent when the package genuinely already went to that recipient (verify via Mailjet `/contact/<email>` + `/message?Contact=<id>`), or when the hard verifiers are still missing.

### General rules

- Outside `mode: pre_cma`, draft only unless the human explicitly approves send. In Skyleigh's operating language, a direct request like "send the seller package to <email>, her name is <name>" is approval to send now, not a request for another draft/approval cycle.
- Do not promote to /admin until the seller package has been approved AND sent (or queued to send). Drafted-but-unsent does not move the contact off /leads.
- On approved send, the skill MUST:
  1. Update the contact verifiers on `contacts` (primary_email, primary_phone, display_name) using the collected inputs.
  2. Call `close_to_admin(contact_id, side='listing', listing_address=..., actor='seller-package', workflow='listing')` — this creates the listing deal at stage 0 and flips `contacts.stage='closed'` so the lane flags clear from /leads widgets.
  3. Record `deal_id` from the resulting deal on the run handoff.
- After admin promotion, attach the seller-package draft/sent artifact to the new deal_id through `admin-result-writer`.
- Do not create MLC/listing checklist completion from this step — that lives at stage 2.

## Template Rules

- The absence of the approved template is never authorization to compose one: template unreadable or missing → STOP with `waiting_human`. **This is now enforced in code, not just here:** every Mailjet sender routes through `~/elevate-premium/scripts/mailjet-guard.py`, which lets an approved template through untouched but HOLDS any custom email, sends Skyleigh a test copy, and requires her approval token before it can reach a client. Do not try to route around it with a raw curl or a new script — the nightly watchdog flags any ungated sender. This rule was born from a real unapproved send, and it generalizes to every templated client-send.
- Mailjet template maintenance: back up `GET /template/<id>` and `/detailcontent` before any edit, modify only `detailcontent`, and verify by re-reading after the write. Email images must be public HTTPS URLs, never local paths.
- Mailjet seller-package ID distinction: saved campaign draft `14342651` is not the v3.1 transactional template ID. For an approved one-off seller-package send, use API-visible template `8055687` (`Pre-CMA Seller Package - Forever Real Estate`) with `TemplateLanguage: true` and `Variables: {"seller_names": <first names only>}`. The current detail content contains `[[data:seller_names:"there"]]`; use first names only in that variable (one seller: `Lori`; multiple sellers: `Russ & Lori`).
- Verification for one-off Mailjet sends: before sending, read back `/template/8055687` and `/template/8055687/detailcontent`, confirm the ID and `seller_names` variable exist, and check recent messages for the recipient to avoid duplicate package sends. After sending, keep provider proof from `/v3.1/send` (`MessageUUID`, `MessageID`, `MessageHref`) and poll `/contact/<email>` plus `/message?Contact=<id>&ShowSubject=true` for readback. It is acceptable for `/message` to show a queued row without subject/custom ID immediately after send; the provider response plus contact/message readback verifies acceptance.
- Mailjet `CustomID` is capped at 64 characters. Do not use the full `<skill>:<deal_id>:<run_id>` idempotency key as the provider `CustomID`; keep the long idempotency key in the operational-store result, and use a short provider-safe value such as `sellerpkg:<deal8>:<run8>`. If Mailjet rejects the first send with `mj-0006` / “Characters limit exceeded” for `CustomID`, verify the run is still live/approved, retry only with metadata shortened, keep recipient/template/subject/variables unchanged, and write a retry audit artifact.
- If the Mailjet MCP helper becomes unreachable or lacks template-send coverage, do not improvise a portal/manual-send path. Use the maintained local script pattern under an artifact folder, loading Mailjet env from `/Users/admin/skyleigh-tools/.env`, `/Users/admin/elevate-premium/.env`, or `/Users/admin/.elevate/skyleigh-passwords.env`, and write a JSON proof artifact with endpoints called, template hash/readback, recipient, CC, variables, provider proof, and final verification.
- If Skyleigh immediately asks for a same-day Zoom link follow-up to the seller after the package, treat that as an approved one-off Gmail send when the recipient is the same verified seller. Use Skyleigh's saved Zoom PMR (`https://us02web.zoom.us/j/2725799556`, Meeting ID `272 579 9556`), send from Gmail with `gws gmail +send`, CC `skyleigh.mccallum@gmail.com`, include the current Gmail default `sendAs` signature from `gws gmail users settings sendAs list --params '{"userId":"me"}'`, and verify with `gws gmail +read --headers`. Store a JSON proof artifact beside the seller-package proof. Do not update the Admin board for this follow-up unless a deal stage, checklist item, date, or price actually changed.

## Output Contract

```json
{
  "workflow": "seller-package",
  "status": "drafted|waiting_human|sent|failed",
  "deal_id": "",
  "draft_id": "",
  "contact_id": "",
  "missing_fields": [],
  "approval_required": true,   // false on a mode:pre_cma run -- it sends
  "admin_promoted": false,
  "admin_side": "listing",
  "admin_stage": 0
}
```

`admin_promoted` flips to `true` only after `close_to_admin` returns a deal_id. On `status: "sent"` without admin promotion, treat the run as incomplete and re-attempt the promotion before closing.

## Approval-draft implementation notes (NON-pre_cma invocations ONLY)

> A `mode: pre_cma` run SENDS and must never park an approval card. Everything in this section applies only to other invocations. See "Pre-CMA stage-entry send exception" above.

When Stage 0 already has the hard verifiers (`contact_id`, seller name, reachable email/phone, and listing address), do not park the run for optional appointment/date details. For a Mailjet-backed seller package:

1. Read and back up both `GET /template/<id>` and `GET /template/<id>/detailcontent` before using the template.
2. Inspect the detail content for personalization fields. Current seller-package template 8055687 uses `[[data:seller_names:"there"]]`; render this with the seller's first name for the approval preview and include the personalization value in the structured payload.
3. Create local artifacts before any send: approval preview markdown, structured Mailjet send payload JSON, template backup JSON, detailcontent backup JSON, and a short workflow audit.
4. Record the run as `waiting_human` with a concise pure-approval prompt and `requiredFields: []`. Do **not** add a `type: select` / approval text field for "Approve send"; the dashboard's approve/dismiss controls come from the empty-field pure approval. Do not mark admin promotion complete and do not move the contact/deal until the approved send actually occurs.
5. If the localhost callback is unavailable, use the `admin-result-writer` fallback path (`admin_deal complete_run` when available, otherwise `record_run_result` through the live Elevate app Python data layer) and then read back `admin_action_runs` plus `deal_attachments` to verify the human prompt and artifacts landed on the card. A rerun may already have the preview/payload artifacts attached and `human_prompt_json` populated but still lack `result_json`/`result_idempotency_key`; in that case, do not recreate Mailjet artifacts or draft again. Close the same run with the stable approval-draft idempotency key, the existing artifact list, `status: waiting_human`, and the same pure-approval prompt, then verify the run row and attachment `source_run_id` before reporting.

## Failure Modes

- **Missing verifier**: `status: "waiting_human"`, `requiredFields` lists which of seller_names/seller_email/seller_phone/listing_address are missing. Do not draft.
- **Contact already promoted**: if `contacts.stage='closed'` and a listing deal already exists for this contact, skip promotion, attach the new artifact to the existing deal, and return `admin_promoted: true` with the existing `deal_id`.
- **Existing deal card lacks profile verifier metadata**: `close_to_admin` matches active Admin deals by `sourceProfileId` / primary contact / verifier keys, not by address alone. If a Stage 0 card already exists for the property but lacks `primary_contact_id` and profile verifier metadata, `close_to_admin` may create a duplicate “Seller: <name>” card after the approved send. Reconcile immediately: stamp the existing property card with `sourceProfileId`, `sourceProfileIds`, `profileContactIds`, `profileEmails`, `profileVerifierKeys`, `profileDisplayName`, `sourceAdminSide='listing'`, and `workflow='listing'` using per-field `set_deal_toggle`/data-layer writes; rerun `close_to_admin` so it updates the existing card with `matchReason='source_profile'`; archive the duplicate card with `set_deal_status(status='archived')`; attach a reconciliation audit to the active deal and verify there is one active property card.
- **Existing waiting-human seller-package run**: before creating a Mailjet draft on a rerun, read the current `admin_action_runs` for the same deal/skill. If an earlier seller-package run is already `waiting_human` with a valid approval draft/payload artifact, do **not** create another draft/list/campaign. Treat the new rerun as superseded or skipped, report the existing active approval prompt, and attach only a small audit note if the rerun produced any useful proof. If a duplicate draft was already created during fallback, verify it remains unsent and attach that as a supplemental audit only; keep the original waiting-human run as the active approval card.
- **Existing Mailjet seller-package/marketing-package send**: before creating an approval draft or auto-sending a Pre-CMA resume, read Mailjet `/contact/<seller_email>` and `/message?Contact=<id>&ShowSubject=true` for the verified seller email. If readback shows a recent `sent` message for the Forever Real Estate seller/marketing package or pre-CMA package to that same recipient, do **not** create another approval prompt or send payload. This duplicate-safety check wins even if a later template preflight finds an unrelated template metadata problem such as missing subject readback — the correct outcome is `skipped_existing_package_message`, not `waiting_human`, because no send is needed. Write a JSON proof artifact with the recipient/contact/message readback and a short workflow audit; attach both to the active matched deal. If a later duplicate Stage 0 seller-package run already has that proof attached from a sibling run, do not re-query/re-send just to satisfy the new run: verify the existing proof file locally, write a small current-run reconciliation audit, close the current run as `skipped_existing_package_message` with the stable current-run idempotency key, and attach both the current audit plus the existing proof under the current `source_run_id`. If the result callback refuses connection, use `admin_deal complete_run` with that same final payload, then read back `admin_action_runs` and `deal_attachments.source_run_id` before reporting. If `admin_deal attach` creates visible rows but drops `source_run_id`, immediately add/read back the same artifacts through `elevate_db(action="call", function="add_deal_attachment", kwargs={...})` with the current run id so the run provenance is preserved. Safely copy proven verifier fields such as `workflow_client_1_name` and `workflow_client_1_email`, then read back the deal gate and report only the remaining Stage 0 blockers.
- **Injected run deal not found / duplicate-id mismatch**: if `admin_deal show` or `admin_action_runs` readback cannot find the injected `deal_id`/`run_id`, do not blindly fail or send against the missing card. First use the injected hard verifiers (primary contact id, seller email/phone, exact address, title) to query active deals and action runs. If exactly one active matching deal exists by primary contact/email/address, continue on that active deal, write a run-specific audit naming the mismatch, and attach any proof artifacts there. If the original callback/run id is absent from the operational store, do not claim the run callback closed; use the active card state instead, and if its gate is clear, advance it through `admin_deal advance` after readback. If multiple active candidates match, stop as `waiting_human` with the candidates.
- **Archived duplicate deal rerun**: if the current stage-entry run is on an archived duplicate card, first query for active deals with the same `primary_contact_id` or normalized listing address. If an active matching deal already has the seller-package proof/artifacts or has advanced past Stage 0 with the seller-package outcome, do not create another draft/send/approval. Close the archived duplicate run as `skipped` with a stable idempotency key such as `seller-package:<archived_deal_id>:<run_id>:archived-duplicate-existing-active-deal`, no checklist updates, no human prompt, and verify the run readback. When there is no new ask and the active deal already carries the outcome, cron delivery may be `[SILENT]`.
- **Callback down / superseded result**: if the callback port is unavailable and `record_run_result` or `admin_deal complete_run` says the rerun result was already recorded, read back the active sibling run before retrying. A superseded rerun should not be forced into a new approval. Use `add_deal_attachment` through the Elevate data layer only for supplemental audit evidence that needs the superseded `source_run_id`.
- **Stage 0 burst superseded by CRM/contact verification**: never resurrect the CANCELLED run itself -- but a supersede is a "wait", not a "never". On a `resume: true` run, or once the sibling card has been answered OR declined, apply "Resuming after the info arrives": if the deal now has a reachable email and Mailjet shows no package ever sent to that address, SEND. `[SILENT]` is correct ONLY while the sibling card is still open or the hard verifiers are still missing. Read back the active sibling run, the deal gate, deal attachments, and current `extra_toggles_json`/visible fields. Sibling runs may have copied hard verifiers such as `workflow_client_1_name`, `workflow_client_1_email`, and `workflow_lead_source` after the active human prompt was first written, so report from the current gate state, not from stale prompt text. If a sibling waiting-human card is STILL OPEN and the hard verifiers are still missing, cron delivery may be `[SILENT]`. Once that card closes either way, re-check and send.
- **close_to_admin rejected (no verifier on contact row)**: this should not happen if required inputs are enforced; if it does, return `status: "failed"` with the rejection reason and do NOT mark the package as sent — the human has to fix the contact record first.


## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
