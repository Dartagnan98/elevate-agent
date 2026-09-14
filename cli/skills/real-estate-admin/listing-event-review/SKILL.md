---
name: listing-event-review
description: Verify newly routed BC listing documents or property-photo evidence and apply an authorized listing stage trigger. Used by the Gmail document-review handoff; not a general inbox scan.
metadata:
  elevate:
    tags: [real-estate, listing, document-review]
---

# Verify a listing event

Read the [listing trigger contract](../admin-result-writer/references/listing-stage-triggers.md) and its runtime invocation section. Work only on the handoff's deal and `listingTriggerEvidence.attachments`. Do not invoke the Gmail scanner again.

Read the attached files and their original routing manifest/message context. Independently verify the address/MLS, parties, listing side and current contract. A routing score is a candidate match, not proof. Inspect signatures/execution in the actual document; an email subject, filename or completed-envelope label alone is insufficient. If text extraction does not establish execution, inspect the PDF pages through the available local document viewer. Preserve exact uncertainty rather than checking `fullySigned` speculatively.

Select a trigger only when established:

- Fully signed current MLC: `signed_mlc_received`.
- Fully signed current CPS for our listing: `signed_cps_received`.
- Fully signed condition removal/waiver for the active accepted contract: `signed_removal_received`. Establish that all conditions were removed; partial removal is a review item until its policy is defined.
- Actual property photos delivered for this listing: `photos_received`. Ignore signature logos, generic marketing images and unrelated attachments. For a photographer's download/gallery link, verify the source and listing, download a real photo or photo-package artifact and attach it before invoking the trigger. A link alone is not photo receipt proof.

For each supported event, pass sourceId (Gmail ID), attachmentId, actual SHA-256, matchConfirmed=true and the verification notes. Document events also require fullySigned=true, currentContractConfirmed=true and contractId (identify the contract by its canonical attachment/checksum or provider identity). Removal requires allConditionsRemoved=true. These are evidence-backed attestations, not defaults. Use a separate trigger request per verified document type; repeat delivery is deduplicated by bytes.

Call the supported trigger interface. It queues destination work; do not run a second offer-review/MLC/marketing/subject-removal workflow here. Record the returned stage/event/run IDs. Finish this review's current run through admin-result-writer with the verification artifact and stable result key. If the trigger returns an error or verification is ambiguous, finish `waiting_human` with the exact unresolved evidence. Unrelated documents are `succeeded` with a no-stage-change explanation, not blockers.

Never send marketing, sign, alter MLS, or upload unrelated documents in this review. Condition-removal filing is handled by the destination subject-removal workflow.
