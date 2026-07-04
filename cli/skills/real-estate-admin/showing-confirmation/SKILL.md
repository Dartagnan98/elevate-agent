---
name: showing-confirmation
description: "Confirm showing logistics and share a listing landing page with the cooperating agent. Use when the realtor says \"send the landing page to [agent] and tell them [instruction],\" or asks to confirm showing details for an active listing at stage-6 Listing Live."
metadata:
  elevate:
    tags: [real-estate, showing, listing-live, email, landing-page]
    runtime:
      approval_required: true
---

# Showing Confirmation

Use when the realtor asks to confirm showing details or send showing instructions to a cooperating agent for one of her active listings.

A direct request like “send the landing page to [agent] and tell them [showing instruction]” is approval to send that specific message. Do not ask for another confirmation unless the recipient or instruction is ambiguous.

## Workflow

1. **Match the listing first**
   - Query the operational database for the property address in `deals`.
   - Confirm the matched deal is the active listing, usually `side='listing'` and stage `6` Listing Live.
   - Pull address, MLS number, and any known deal attachments or source paths.

2. **Find or repair the landing page**
   - Check the canonical URL pattern from the realtor's tools config (e.g. `config/realtor.json`) or `docs/workflows/marketing-landing-pages.md`. Landing pages are typically hosted on a branded subdomain or Cloudflare Pages project, for example `https://<brand>-listings.pages.dev/<address_slug>/`.
   - Verify with a real HTTP request.
   - If the canonical page 404s but a marketing run exists, rebuild and deploy it instead of sending a broken link:
     - Locate run from `docs/listings/<address>-launch.md` or `data/marketing/runs/<run_id>/inputs.json`.
     - Build scaffold from the realtor's tools project directory:
       - `node .claude/skills/marketing/scripts/build-landing.js data/marketing/runs/<run_id>`
     - Fill every `BESPOKE:` block and placeholder text before deploy.
     - Correct stale price and MLS number from the listing detail file.
     - Deploy:
       - `bash .claude/skills/marketing/scripts/deploy-landing.sh data/marketing/runs/<run_id>/landing`
     - Re-verify the canonical URL returns HTTP 200 and shows the correct title/property.

3. **Find the cooperating agent contact**
   - Search local `contacts` first.
   - If missing, search Gmail for the exact name and likely spelling variants, especially brokerage roster/invite emails and ShowingTime threads.
   - Example reliable lookup:
     - `gws gmail users messages list --params '{"userId":"me","q":"<Agent Name> OR <LastName> OR <LastNameVariant>","maxResults":10}'`
     - Fetch metadata on promising messages and inspect To/Cc headers.
   - If no recipient email/phone can be verified, ask the realtor one concise question for the contact method.

4. **Send the message**
   - Use the realtor's client-facing cadence:
     - `Hi <Name> :)`
     - Short and direct.
     - Space before `!` and `?` where used.
     - No em dashes.
     - Warm sign-off only if needed, e.g. `Talk soon 💛`.
   - Example email body:
     - `Hi <Name> :)`
     - `Just sending over the landing page for 450 Main Street before your Showing:`
     - `<landing URL>`
     - `The front door will be unlocked for you.`
     - `Talk soon 💛`
     - `<realtor's first name>`
   - Send only the exact approved showing instruction. Do not add access details, lockbox codes, alarm notes, or occupancy details that the realtor did not provide.

5. **Verify and log**
   - Verify Gmail returns a sent message with `labelIds` containing `SENT`.
   - Upsert the cooperating agent into `contacts` if useful for future showing/admin workflows.
   - Add a `deal_events` row with `kind='run_result'`, `actor='assistant'`, and payload including:
     - recipient
     - subject/channel
     - sent message id
     - landing URL
     - showing instruction summary

## Pitfalls

- The presence of a marketing run does not mean the canonical landing page is live. Always verify the URL before sharing.
- Some old marketing-run inputs may have stale list price or `MLS TBD`; correct from current listing detail docs before deployment.
- Names may be misspelled in the realtor's dictation. Search likely spelling variants of the agent's name.
- Do not send a broken Cloudflare Pages URL. If it 404s, rebuild/deploy or ask for a different link.
- Do not use public web snippets alone as proof of recipient contact if Gmail/local records can verify a real email.

## Output Contract

```json
{
  "workflow": "showing-confirmation",
  "status": "done|waiting_human|failed",
  "deal_id": "",
  "recipient": "",
  "channel": "email|sms|imessage|other",
  "landing_url": "",
  "sent_message_id": "",
  "logged_event_id": "",
  "missing_inputs": [],
  "risks": []
}
```
