# BC listing stage triggers

User-defined workflow contract, September 9, 2026. Initial product scope: BC agents on Mac. These rules apply to the listing pipeline; do not apply listing stage indices to buyer deals. They supersede older blanket “manual moves only” instructions for the specific triggers below. They do not authorize advancing just because a run/checklist is complete.

## Entry rules

| Stage | Authorized entry trigger | Work started on entry |
|---|---|---|
| 0 — Pre-CMA | The realtor explicitly asks to add the client/property here. | Pre-CMA setup and client/property context. |
| 1 — CMA / Evaluation | The realtor requests comps after their walkthrough. | The maintained CMA/evaluation workflow. Do not infer this request from a completed Pre-CMA checklist. |
| 2 — Listing Intake | The realtor requests the move, says “prep a listing for [address],” or manually moves the card here. | Listing intake / MLC preparation and missing-information collection. Completing the CMA alone does not authorize this move. |
| 3 — SkySlope & Matrix Prep | Gmail/document review verifies a fully signed MLC matched to this listing, or the realtor asks to prepare SkySlope/Matrix for the address. | The listing compliance-file and incomplete MLS preparation workflows. |
| 4 — Marketing Go | Property photos are received and matched to the listing, or the realtor asks to prepare marketing in anticipation of photos. | Marketing preparation, including the listing landing page through marketing-landing. Prepare factual copy/page structure with missing-photo tasks when photos have not arrived; add the actual photos to that same work later. |
| 5 — Listing Live / Marketing | MLS publication is verified, or the realtor asks to email the MLC to BC Listings to activate the listing. | The live-listing workflow. For the email-request trigger, distinguish activation requested/sent/failed from publication verified. A board-stage label does not prove MLS publication. Hold public “just listed/live” claims until publication is verified. |
| 6 — Accepted Offer | The realtor asks to process an accepted offer, or Gmail/document review verifies a fully signed CPS for one of the realtor's listings. | Automatically start accepted-offer processing: extract and review contract terms, dates, deposit and conditions; attach evidence and surface missing information. A generic offer draft or an unsigned counteroffer is not this trigger. |
| 7 — Condition Removal | The document watcher verifies a fully signed condition-removal/waiver for the accepted contract, or the realtor says subject/condition removal has occurred. | Process the removal, upload the verified document to the matching SkySlope transaction, and retain the upload receipt/readback. If a verbal instruction arrives without the document, record the instruction and request/locate the document; do not claim it has been uploaded. |

A card stays in Listing Live until its accepted-offer trigger. It stays in Accepted Offer until its condition-removal trigger. Condition Removal does not mean Closed. Closing and failed-offer/relisting transitions remain to be specified.

Partial condition-removal behavior is awaiting the realtor's decision. Do not infer that all conditions are removed from a document addressing only some conditions. Preserve the remaining condition list and deadlines, and do not mark the deal firm without supporting evidence.

## Evidence and execution

- Resolve one listing deal and the applicable current contract using the address/MLS/parties and document contents. Ask when matching is ambiguous. Never use a filename, email subject, “completed envelope” label, or draft status alone as proof of full execution.
- For document triggers, retain the source message/document identifier, document checksum, match evidence, and signature/execution verification. Verify the relevant parties' execution; do not interpret this contract as legal advice about validity.
- For explicit requests, retain the request/session provenance. “Prep listing for [address]” is a listing-intake instruction; simply mentioning the property or finishing work is not.
- Use the supported stage transition and stage-entry dispatcher. Read the current stage and existing runs before acting. Entering the destination stage starts its workflow; do not also start a duplicate copy from chat or the watcher.
- Repeated Gmail delivery, the same PDF in another envelope, a repeated instruction, or late-arriving photos must resume/update existing work where applicable. Do not regress a later-stage deal or reprocess an old contract as a new accepted offer. A new contract/relist cycle requires its own identity.
- Keep the stage event and workflow-run provenance linked. If dispatch or an upload fails, leave a visible retry/blocker and resume the existing work. Never report “workflow started,” “filed,” or “live” without the corresponding readback.
- A manual card move is a stage-entry request too. It must trigger the destination workflow once. Do not fabricate checklist facts to make an old gate pass.
- Marketing preparation before photos is explicitly allowed. Photo-dependent work remains outstanding; do not substitute invented property photos or publish placeholders as final listing assets. Receiving photos later updates the existing package/page.
- The realtor has authorized uploading the matched condition-removal document to SkySlope as part of this workflow. Verify the destination transaction and document/checklist placement, then read back the upload. This does not authorize unrelated sends, signatures, deletion, final compliance submission, or public marketing publication.


## Runtime invocation (September 9)

Use `admin_deal(action="trigger", deal_id=..., trigger=..., evidence=...)` when that action is present in the tool schema. The supported installed CLI fallback is:

```sh
PYTHONPATH="$HOME/Elevation:/Applications/Elevate.app/Contents/Resources/cli" /Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 -m elevate_cli.listing_triggers --request-file /absolute/path/to/request.json
```

Write the request JSON with a file-writing tool, not shell interpolation. Shape: `{"deal_id":"...","trigger":"listing_prep_requested","evidence":{"sourceId":"session/message-id","requestText":"the actual user instruction","userRequested":true,"matchConfirmed":true}}`. Verify one current BC listing before invoking. This supported CLI uses the account-scoped operational connection and the same atomic stage dispatcher as the board; it is not a raw database bypass.

Triggers: comps_requested, listing_prep_requested, platform_prep_requested, signed_mlc_received, marketing_prep_requested, photos_received, mls_activation_requested, mls_live_verified, accepted_offer_requested, signed_cps_received, condition_removal_confirmed, signed_removal_received. Never use a completed checklist as request evidence. Manual board moves use the same dispatcher directly. Later stages/buyer behavior retain their existing path.

Explicit request triggers require sourceId, requestText, userRequested=true, matchConfirmed=true. Document/asset triggers require sourceId, attachmentId (owned by this deal), sha256, matchConfirmed=true. Signed-document triggers additionally require fullySigned=true, currentContractConfirmed=true, contractId and verificationNotes. Removal triggers require allConditionsRemoved=true until partial-removal policy is resolved. MLS verification requires sourceId, matchConfirmed=true, publicationVerified=true, mlsNumber, verificationNotes. Use actual verified evidence; these flags are not automatically true.

Returned runs are **queued**, not proof the workflows finished. Duplicate event IDs reuse their runs. If no stage workflow is enabled, the transition fails without moving the card. Queue/validation failures must remain visible and retry with the same sourceId/evidence. Never fall back to arbitrary force or raw SQL.
