---
name: "price-reduction"
description: "Reduce the list price on an active listing. Use when the user clicks the Price Reduction button or says \"price reduce [address] to [price]\", \"drop [address] to [price]\", \"reduce the price on [address]\", \"new price on [address]\", or \"price reduction signed on [address]\" (Phase 2): fills the BCREA Amendment to Listing Contract (price change), shows the realtor the filled amendment for approval, and on her approval sends it to the seller(s) for signature via DigiSign. When the signed amendment returns, updates the card list_price to the new figure, runs skyslope-sync, and fires the marketing revamp (landing-page price update + Price Improved Buffer posts + Mailjet price-adjustment blast). Never a back-on-market / just-listed post — this is a price improvement, not a relist."
category: "real-estate-admin"
access:
  entitlement: "real_estate_admin"
---

# Price Reduction — amendment, approval, DigiSign to sellers, then marketing revamp

The realtor's standard process when an active listing drops its price. The goal: get the BCREA Amendment to Listing Contract (price change) filled and signed by the sellers, then once the new price is FIRM, update the card and revamp the marketing at the new figure — landing page, social, and email — without ever framing it as "back on market".

This is a TWO-PHASE skill:
- **Phase 1 — initiate:** fill the amendment, get the realtor's approval, and on approval send it to the seller(s) for signature. Stamp the card as pending. **Do NOT change `list_price` yet.**
- **Phase 2 — on signed return:** update `list_price`, run `skyslope-sync`, and fire the marketing revamp.

## CRITICAL — read first

1. **Read `lessons.md` BEFORE every run.** Apply every lesson. Append a new lesson AFTER every run or correction. Format: `[date] | what happened | rule/insight`.
2. **The realtor's hard rules (durable):**
   - **Never change `list_price` before the amendment is signed.** The new price only goes on the card in Phase 2, after the seller(s) sign. Phase 1 records the reduction as *pending* only.
   - **DigiSign is sent to the seller(s) only AFTER the realtor approves the filled amendment.** Approval IS the send authorization (unlike collapse-sale, which is draft-only). But still: never create or send the envelope before she has seen and approved the filled PDF. Her approval is the gate.
   - **NO back-on-market / just-listed / "back on market" framing anywhere.** This is a price improvement, not a relist. Marketing copy uses "Price Improved" / "New Price", never "back on market".
   - **Marketing only fires in Phase 2, after the price is firm.** Do not touch `marketing`, `marketing-landing`, or Mailjet in Phase 1.
   - **Voice per `knowledge/realtor-profile.md`** for every seller-facing or public word.
3. **Per-form rule:** the amendment is filled the blank-template + overlay way (download the blank ONCE, fill via `scripts/fill-listing-package.py` / reportlab-pymupdf overlay — same as MLC/CPS). Never cascade two WEBForms forms in one transaction.

## What this skill does

**Phase 1:** resolve deal → read current `list_price` → ask new price → fill the Amendment to Listing Contract → show it to the realtor (PNG) for approval → on approval, DigiSign-send to the seller(s) → stamp `extra.priceReductionPending` + a waiting-on-signature reminder.

**Phase 2:** on signed return → set `list_price` = new price → stamp `extra.priceReducedFrom/To/At` → clear the pending reminder → update `active-listings.md` → remind to update Xposure/MLS price → run `skyslope-sync` → fire the marketing revamp (landing → Buffer → Mailjet).

## What this skill does NOT do

- Does NOT change `list_price` in Phase 1 (only Phase 2, after signing).
- Does NOT post "back on market" / "just listed" anywhere — it's a price improvement.
- Does NOT fire any marketing in Phase 1.
- Does NOT update the Xposure/MLS price itself (no API) — it reminds the realtor to do it manually.
- Does NOT send the amendment before the realtor approves the filled PDF.

---

# PHASE 1 — Initiate (Price Reduction button or "price reduce [address] to [price]")

## Step 1 — Resolve the deal + current price

- **Deal** — required. If fired from the Price Reduction button, the `deal_id` is passed in. If triggered by phrase, resolve the address to the deal row.
- **Side** — this is a **listing-side** action only. If `deals.side = 'buyer'`, stop and tell the realtor price reduction is listing-side only.
- **Current price** — read `deals.list_price` (the card's current list price). This is the OLD price.

## Step 2 — Ask the new price

- If the new price was given in the trigger ("price reduce 3710 Louis Creek to $519,900"), capture it.
- If not, ask one short question: **"What's the new list price for <address>?"**
- Record `old = <current list_price>` → `new = <answer>`. Sanity check: new should be lower than old; if not, confirm with her once.

## Step 3 — Fill the Amendment to Listing Contract (price change)

The BCREA **Amendment to Listing Contract** form, price-change variant.

1. Download the **blank** amendment template ONCE (the `digisign` / `webforms` blank-template source — same place MLC/CPS blanks come from). Do not pull it from a sibling WEBForms transaction (no cascade).
2. Fill it via the `digisign` skill's overlay approach (`scripts/fill-listing-package.py`, reportlab/pymupdf). Populate:
   - **Seller name(s)** — from the deal's seller contacts.
   - **Property address** + **legal description / PID** (from the deal / title on file).
   - **MLS#** — from the deal.
   - **OLD list price** and **NEW list price** (the price-change clause: "The List Price is amended from $OLD to $NEW").
   - **Date** — today.
   - **Listing brokerage / licensee** — the realtor's name and brokerage on file for the deal.
3. Save the filled PDF to `output/<short-address>-price-reduction/Amendment-to-Listing-Contract_<short-address>_filled.pdf`.

## Step 4 — Approval gate (show the realtor the filled amendment)

- Her chat cannot render PDFs. Convert the filled amendment pages to PNG (`pdftoppm` at /opt/homebrew/bin) and send inline.
- Show the OLD → NEW price in the message so she can sanity-check at a glance.
- **WAIT for her explicit approval.** Her approval is the gate AND the send authorization. Do not proceed to Step 5 without it.

## Step 5 — On approval → DigiSign to the SELLER(S)

Unlike collapse-sale (draft only), here **approval authorizes the send**.

1. Create the DigiSign envelope via the `digisign` skill from the filled amendment.
2. Add the **seller(s)** as the recipient(s) and place their signature/initial blocks.
3. **Send it to the seller(s) for signature.** (Approval IS the send authorization. Still never sent before approval.)
4. Confirm delivery and tell the realtor it's out for the sellers' signature.

## Step 6 — Stamp the card (pending, NOT firm)

1. Record the pending reduction on the card `extra`:
   ```json
   "priceReductionPending": {
     "from": "<old price>",
     "to": "<new price>",
     "sentAt": "<ISO>",
     "amendmentPath": "output/<short-address>-price-reduction/Amendment-to-Listing-Contract_<short-address>_filled.pdf"
   }
   ```
2. Add a deal note: "Price reduction <old> → <new> — Amendment to Listing Contract sent to seller(s) for signature <date>. Awaiting signature."
3. Add a **waiting-on-you reminder** on the card: "Price amendment out for seller signature — not yet signed."
4. **Do NOT change `list_price`.** It stays at the old figure until Phase 2.

---

# PHASE 2 — On signed return ("price reduction signed on [address]", or doc-router detects the signed amendment)

Fires when the **fully-signed** amendment comes back — via `gmail-doc-router` / `skyslope-sync`, a direct upload, or the realtor saying "price reduction signed on <address>".

## Step 1 — Update the card (now the price is firm)

1. Set `deals.list_price` = the NEW price.
2. Stamp the card `extra`:
   ```json
   "priceReducedFrom": "<old price>",
   "priceReducedTo": "<new price>",
   "priceReducedAt": "<ISO>",
   "priceReductionSource": "Amendment to Listing Contract (signed)"
   ```
3. Clear `extra.priceReductionPending` and the "waiting for seller signature" reminder.
4. Update `knowledge/listings/active-listings.md` — the listing's price line to the new figure.
5. **Remind the realtor to update the Xposure/MLS price manually** (no API): "New price is firm. Update the Xposure/MLS list price to <new> when you get a sec."

## Step 2 — Run `skyslope-sync`

Run the `skyslope-sync` skill to attach the signed amendment to the deal in SkySlope. **SkySlope has NO API** — `skyslope-sync` drives the portal via Browser Use. Never attempt a manual SkySlope API call.

## Step 3 — Fire the marketing revamp (only now, price is firm)

Frame everything as a **price improvement** — never "back on market".

a. **Landing page** — run `marketing-landing` to update the listing's landing-page price to the new figure (redeploy the page).

b. **Buffer** — run `marketing` to schedule **"Price Improved" / "New Price"** social posts at the adjusted price. Graphics + copy in the realtor's voice (`knowledge/realtor-profile.md`); D/E rotation per `data/marketing/counter.json`. No "just listed" / "back on market" wording.

c. **Mailjet** — send the **price-adjustment** template blast to the relevant list via the Mailjet path (`scripts/send-mailjet.js` / the price-adjustment template), the new price in the copy. Confirm recipients + subject + body with the realtor before sending (standard Mailjet confirm gate).

## Step 4 — Close the loop

- Deal note: "Price reduction firm <old> → <new> (signed amendment). Card + active-listings.md updated, SkySlope synced, marketing revamp fired (landing + Buffer + Mailjet)."
- File the signed amendment to the listing's Drive folder if the doc router has not already.

---

## Auto-update hook (Phase 2 from the inbox)

Phase 2 also fires when the **`gmail-doc-router`** detects an inbound **"Amendment to Listing Contract" with a price change** for a deal — so a reduction that comes back by email (or one that originated outside the button entirely) still updates the card and revamps the marketing. The doc router files the PDF to the deal's Drive folder, then hands off to `price-reduction` Phase 2 with the matched address + new price. See the pointer in `gmail-doc-router/SKILL.md`.

## Notes

- The Price Reduction **button** in the Elevate admin card (next to Collapse Sale, listing-side only) is the primary Phase-1 trigger; it fires this skill via the admin-action registry with the `deal_id`. The natural-language triggers above also let the realtor run it by talking to the Elevate agent (including on Telegram).
- Mirrors the collapse-sale button→skill→fill→approval→DigiSign pattern, with two differences: (1) approval here authorizes the SEND (not draft-only), and (2) Phase 2 fires the marketing revamp once the price is firm.
