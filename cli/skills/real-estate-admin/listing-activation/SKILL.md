---
name: listing-activation
description: Fulfil an explicit request to email a signed listing MLC to the configured BC Listings activation recipient and track requested, sent or failed status. Not proof that MLS publication occurred.
metadata:
  elevate:
    tags: [real-estate, listing, activation]
---

# Requested BC listing activation

Read the [shared trigger contract](../admin-result-writer/references/listing-stage-triggers.md). This handoff must carry the explicit request in listingTriggerEvidence; use that existing authorization for the requested email. Match the listing, verify the current fully signed MLC and get the BC Listings recipient from the agent's configured brokerage/verified prior activation procedure. Do not guess an email address or use another account's configuration.

Before sending, check the current run's prior artifacts, the deal's activation evidence and Sent mail for this exact listing/MLC/request. Resume an existing draft; do not send a duplicate on retry. If provider completion is uncertain, verify Sent mail before retrying. Prepare and send only the requested activation email with the verified MLC through the configured email skill/provider.

Record listingActivationStatus through admin_deal set_checklist (field=listingActivationStatus) as requested, sent, or failed, retaining the provider message ID/readback or exact blocker in a run artifact. Never overwrite verified_live with sent/failed. If documents, recipient or sending access are missing, close the current run waiting_human with those exact inputs.

A successful email is not MLS publication proof. Once authoritative MLS readback is available, use mls_live_verified with sourceId, matchConfirmed=true, publicationVerified=true, mlsNumber and verificationNotes. This resumes live marketing through the trigger interface. Do not publish just-listed claims merely because the card already says Listing Live.
