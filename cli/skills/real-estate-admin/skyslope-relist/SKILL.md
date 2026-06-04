---
name: "skyslope-relist"
description: "Relist a previously cancelled or expired property in SkySlope (the compliance/transaction platform) by creating a new Listing transaction from the prior one. Reuses sellers, property, PID/legal, and documents from the old transaction; only the listing dates, list price, and commission change. Companion to the Matrix `relisting` skill — Matrix handles the MLS, this handles SkySlope. Trigger on \"relist [address] in skyslope\", \"prep skyslope for relist [address]\", \"create the skyslope listing for the relist\", \"add [address] to skyslope as a relist\", or any request to put a cancelled/expired listing back into SkySlope."
category: "real-estate-admin"
metadata:
  elevate:
    tags: [real-estate, compliance, skyslope, relist]
    runtime:
      result_writer: admin-result-writer
access:
  entitlement: "real_estate_admin"
---

# SkySlope Relist — new Listing transaction from a prior one

The realtor's process for putting a cancelled or expired listing back into SkySlope
without rebuilding the transaction from scratch. Pairs with the `relisting` skill
(which handles the Matrix/MLS side) — run both to fully relist a property.

This skill is provider-neutral: the compliance portal is whatever was configured
at onboarding (SkySlope or another). Treat the portal name, login URL, transaction
types, and checklist labels as tenant configuration, never hardcoded.

## CRITICAL — read first

1. **Read `lessons.md` in this folder BEFORE every run** and apply every lesson.
   The portal UI uses session-specific input IDs that change between runs — bind by
   visible label text, never a raw id. **Append a lesson AFTER every run** when
   anything is unclear, breaks, or the realtor corrects you (`[date] | what happened
   | rule/insight`). This skill only compounds value if we record what we learn.
2. **The relist rule (durable):** on a relist, only the **listing start/effective
   date, expiration date, list price, and commission** change. Sellers, property,
   PID/legal description, address, and reused documents carry from the prior
   transaction. Do NOT change other fields without explicit instruction.
3. **Never invent data.** If the prior transaction, a required field, or a portal
   login isn't available, ASK the realtor in chat before proceeding. MFA/login
   needed is `waiting_human`, not a silent failure.

## Flow

1. **Identify the property + the prior transaction.** Match the cancelled/expired
   SkySlope Listing by address, MLS#, or transaction ID. If you can't find it, ask
   the realtor for the prior MLS# or transaction ID.
2. **Open the configured compliance portal** through Browser Use / the provider
   connector and sign in. If login or MFA is required, stop and report
   `waiting_human` with the exact prompt.
3. **Create a new Listing transaction** for the property — duplicate from the prior
   one if the portal supports it, otherwise create a new Listing and copy forward
   the carry-over fields (sellers, property, PID/legal, address, agent/brokerage
   from the onboarded profile).
4. **Set only the relist fields**, asking the realtor for any not on file:
   - Listing start / effective date
   - Expiration date
   - List price
   - Commission (listing + buyer-agency split)
5. **Carry forward documents** from the prior transaction where the portal allows
   (or note which need re-upload). Do not mark any checklist item complete unless
   the portal says complete or evidence is attached.
6. **Write the result back to the deal** — new transaction ID, status, and any
   missing-document tasks — then close through `admin-result-writer`.

## Rules

- Local read/create in the portal only. Never email, send, or sign anything from
  this skill.
- If portal labels differ from the province package, keep both labels in the
  artifact/task.
- If the relist already has a live SkySlope transaction, stop and confirm with the
  realtor before creating a duplicate.

## Output Contract

```json
{
  "workflow": "skyslope-relist",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "provider": "",
  "prior_transaction_id": "",
  "new_transaction_id": "",
  "fields_changed": ["listing_date", "expiration_date", "list_price", "commission"],
  "missing": [],
  "notes": ""
}
```
