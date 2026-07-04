---
name: paid-ad-intake
description: Auto-intake for paid-ad leads (Making It Rain). Use when the user says "import paid ad leads", "run paid ad intake", "new making it rain lead", or "check for paid ad leads": parses new "New Lead Submitted" Gmail notifications, creates the lead in Lofty, writes it to the Leads > Paid Ads dashboard tab, and drafts an approval-gated first-touch in the realtor's voice that references the actual ad/listing. Runs on a 5-min cron. Never sends.
metadata:
  type: cron
  owner: Outreach
---

# Paid Ad Intake (Making It Rain)

The realtor runs paid-ad programs through **Making It Rain** (Evocalize). When
someone fills a lead form, MIR emails a `New Lead Submitted` notification. This
skill turns each of those emails into a tracked, contactable lead automatically.

## What it does (per new lead)
1. Parse the MIR notification (name, email, phone, program/ad, listing, order id).
2. Create the lead in **Lofty** (`source=expmakingitrain`, stage `New Leads`, tags
   `paid-ads` + `making-it-rain` + ad-type) — unless that contact already exists.
3. Append the canonical records the dashboard reads under
   `~/.elevate/tools/data/sources/paid-ads/` (contacts / conversations / messages /
   lead-events / tasks).
4. Write an **approval-gated first-touch draft** in the realtor's voice that references
   the **actual** ad/listing — never a hard-coded property. The draft shows on
   **Leads > Paid Ads** for the realtor to Approve, Edit, or Skip.
5. Mark the Gmail message processed so it never re-imports.

**Nothing is ever sent.** Every draft is approval-gated.

## How it runs
- Engine: `scripts/paid-ad-intake.py` (deterministic, stdlib + `gws` Gmail CLI + Lofty REST).
- Runner: `scripts/paid-ad-intake.sh` → writes `output/paid-ad-intake-status.json`.
- Cron: `com.elevate.paid-ad-intake` LaunchAgent, every 300s (`StartInterval`).
- Idempotency: `~/.elevate/tools/data/sources/paid-ads/making-it-rain-state.json`
  (`processed_message_ids`) + de-dupe vs existing contacts by gmail id / email / phone.

## Manual use
```
python3 scripts/paid-ad-intake.py --dry-run --newer-than 14d   # parse + plan, no writes
python3 scripts/paid-ad-intake.py                              # live intake
python3 scripts/paid-ad-intake.py --seed-state                 # baseline: mark current matches processed
```

## Draft voice rules (CRITICAL — see [[realtor-profile]])
- No em dashes. Warm, "it's {first name} with {brokerage}".
- **Listing eXposure ad leads (program names a real address) get the realtor's property-specific
  message:** "Hi {first}, it's {realtor first name} from {brokerage}. I saw your name pop up after you viewed
  my listing at {address}." Then status-aware (auto from active-listings.md / sold-listings.md):
  active → "I'd be happy to get you in to see it, or send you some other similar homes if you like.
  Or were you just browsing?"; under accepted offer / sold → "We have an accepted offer on this one,
  but I am happy to send you some other similar homes if you like. Or were you just browsing?"
- **Only reference a specific listing when the PROGRAM name corroborates a real street address**
  (`trusted_listing()` — program first, never the stored listing field). Generic "Custom Listing"
  or buyer-leads programs → safe generic opener. Never claim an accepted offer on an active listing.
  This is the bug this skill exists to prevent (an early ad-hoc batch hard-coded one street address
  on everyone, including leads whose ad was generic).

## Ongoing nurture
Paid-ad leads land in Lofty with `source=expmakingitrain`, so the `outreach` workflow
already picks them up for follow-up drafting. Cadence lives in
`knowledge/lead-segment-cadence.md` (Paid Ad row). First-touch = this skill's card;
day-3 / day-7 / day-14 nudges = outreach.

## Source of truth / when things break
- Workflow doc: `knowledge/workflows/paid-ad-intake.md`
- Watchdog check: `scripts/watchdog-nightly.sh` (paid-ad-intake section, with stress test)
- The dashboard `paid-ads` source is registered in the **monolith**
  `~/Elevation/elevate_cli/source_connectors.py` (blueprint + WIRED + owner + UI). The
  modular `source_connector_modules/source_catalog.py` in `elevate-current-src` is NOT loaded
  by the running app and has drifted — keep both in sync for Dartagnan's upstream merge.
