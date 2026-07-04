---
name: "cancel-listing"
description: "Cancel an active listing that is NOT being relisted — seller withdrew for good. Use when the user says \"cancel the listing on [address]\", \"cancel [address]\", \"withdraw [address]\", \"[address] is cancelling and not relisting\", or \"seller is pulling [address]\". Fills the Cancellation of Multiple Listing Contract, drafts it in DigiSign after the realtor approves, emails the board to cancel the MLS status, files it (SkySlope + cancelled-listings.md + Lofty), and moves the seller into the ARCHIVED section of the board. Use the Cancel button (cancel-only). Not for relisting — if the seller IS relisting, use cancel-relist instead (one combined envelope)."
category: "real-estate-admin"
access:
  entitlement: "real_estate_admin"
---

# Cancel Listing — withdraw, no relist

The realtor's process when a seller cancels and is NOT relisting. The seller ends up archived, not back in the pipeline.

## CRITICAL — read first

1. **Read `lessons.md` BEFORE every run; append after.**
2. **Hard rules:**
   - **DigiSign DRAFT only, after the realtor approves the filled form.** Never auto-send. Their approval is the gate.
   - **We do NOT change Xposure/Interface status ourselves.** We **email the board's listings desk** and they cancel the MLS. This is required for every cancellation. Read the board contact email from config/onboarding — do not hardcode one.
   - **No back-office transactions email** (that's collapse-only). No back-on-market post.
   - **This is cancel-ONLY.** If relisting, this is the wrong skill — use `cancel-relist` so the paperwork goes in ONE envelope.
3. The cancellation form: commonly called the **Cancellation of Multiple Listing Contract** (a SkySlope checklist item). Depending on the board, this may be executed as a distinct **Cancellation** form or as an **Amendment of Multiple Listing Contract** with the **expiration date set to today, one minute before midnight**. If unsure which applies for this board, ask the realtor once and record it in lessons.md.

## Steps

1. **Resolve deal** (deal_id from the Cancel button, or address by phrase). Confirm `side='listing'`.
2. **Fill the Cancellation of Multiple Listing Contract** (amendment form, expiry → today 11:59 PM) with the deal data (sellers, address, MLS#, brokerage, managing broker — read brokerage/managing-broker details from config/onboarding). Use the `digisign` skill's blank-template + overlay (`scripts/fill-listing-package.py`).
3. **Show the realtor the filled PDF for approval** (chat can't render PDF — `pdftoppm` to PNG, send inline). On approval → **DigiSign DRAFT** (sellers + agent + managing broker). Stop — do not send.
4. After it comes back signed:
   - **Email the board's listings desk** (address from config/onboarding, cc the realtor) with the signed PDF: "Cancelling [address] (MLS# [#]) effective today, signed form attached + in SkySlope."
   - Save to `output/cancellations/<short-address>-cancellation.pdf` + upload to the listing's Drive folder.
   - Upload to the **SkySlope cancellation checklist item**.
   - Add a row to `knowledge/listings/cancelled-listings.md` (sellers, dates, DOM, signatures).
   - Lofty note on the seller lead.
   - Order Sign Down + remove lockbox (coordinate with whoever handles physical sign removal).
5. **Move the deal to ARCHIVED.** Set the deal `status = 'archived'` so the seller client drops out of the active pipeline into the board's Archived section. Add a note: "Cancelled <date>, not relisting — archived."

## Does NOT

- Does NOT relist (use `cancel-relist`).
- Does NOT change Xposure status directly (the board's listings desk does it).
- Does NOT send DigiSign without approval.
- Does NOT email back-office transactions, and does NOT post back-on-market.
