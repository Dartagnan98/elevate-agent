---
name: "seller-updates"
description: "the realtor's full Seller Updates workflow, end to end. Use for \"seller update\", \"weekly seller update\", \"weekly listing report\", \"weekly update\", \"run weekly listings\", \"listing snapshot\", \"listing rundown\", \"listing reports\", \"snapshot my listings\", \"where are we at with my listings\", \"draft seller emails for my listings\", \"showing feedback follow-up\", \"showing-time\", \"showingtime\", seller report PDFs, ShowingTime feedback, or active-listing rundowns. One skill, one continuous run: pull data -> build reports -> handle feedback -> draft emails. No handoffs, no sub-skills."
category: "real-estate-marketing"
tags: ["real-estate", "seller-updates", "showingtime", "sellerhub", "listing-snapshot", "workflow"]
access:
  entitlement: "real_estate_marketing"
---

# Seller Updates Workflow

This is one linear runbook. Work it top to bottom for a full seller update pass.
There are no sub-skills and no handoff packets — carry the run forward yourself.

For each active listing the run produces one comprehensive PDF (SellerHub stats,
comparables, buyer-demand-by-price, showings, an agent-conversation summary) and
one Gmail DRAFT to the seller with the PDF attached. Drafts land in Gmail Drafts
for review. **The skill never sends.**

**Before you start, read `lessons.md` in this folder.** It is the living record
of every correction the realtor has made on seller PDFs and on the feedback chase —
most of the gotchas below were learned the hard way and are encoded there.

Working root for every command:

```bash
cd ~/elevate-premium
```

This workflow **touches SkySlope** for listing identifiers and per-deal context.
Listing IDs (`ListingCheckList.aspx?id=<n>`), commission details, and transaction
notes pull from SkySlope. If a seller email gets archived back into the deal
record, that's a SkySlope upload — read `docs/playbooks/skyslope-automation.md`
for upload routing.

## Always-apply rules

These hold for the entire run. Do not consult a reference for them — just do them.

- **Only chase feedback on the realtor's OWN listings.** The ShowingTime feed mixes
  her listings (shown by other agents) with other people's listings she viewed
  as a buyer's agent. Texting the listing agent of someone else's property asking
  for "feedback" is wrong-direction and has happened before (Eric Putoto / 604
  Stansfield). `request-showing-feedback.cjs` filters the feed to MLS#s in
  `docs/listings/active-listings.md` (+ `cancelled-listings.md`) and aborts if
  that file is empty. When a new listing joins her book, make sure it lands in
  `active-listings.md` BEFORE the next ShowingTime sync.
- **PRIVACY — never put raw iMessages in the seller PDF.** Do NOT render verbatim
  inbound/outbound iMessage snippets. Many contain the realtor's private side
  conversations with sphere/family/agents. The PDF's conversation section must be
  a SUMMARY of conversations with OTHER AGENTS that shows she has been actively
  finding a buyer for THIS property: name (or anonymize) the agents, date-stamp
  the conversations, quote the agent-side question/feedback only when on-topic.
  Never quote the client's own messages back to them.
- **Never auto-send seller emails. Drafts only.** the realtor reviews and sends.
- **Ask for seller email confirmation when the auto match looks weak.** Treat
  auto-picked matches as guesses until reviewed. Skip listings she hasn't
  confirmed — fail safely, don't fail loudly.
- **Pending-feedback texts must dedupe.** Never text the same agent the same
  request twice for the same showing. Dedupe key is
  `listing_id + normalized phone + showing_date`, logged in
  `feedback-requests-sent.json`.
- **The comments field is what matters** on the reply loop. Rating / interest /
  price dropdowns are nice-to-haves — guess or skip if the reply doesn't give
  them. Don't bug the agent for more.
- **Every email needs human context.** Scripts produce a data skeleton. A draft
  that doesn't reference something specific to THIS seller and THIS listing —
  something a form letter couldn't — is not finished. See Phase 4.
- **The email and PDF should sound like the realtor** explaining this listing to
  this seller, not a generic ShowingTime export. → consult
  `references/voice-and-drafting.md`.
- **MIR / paid-ad results block: surface ONLY ad views, clicks, click-through
  rate, and new leads.** Never include budget, cost-per-click, or cost-per-lead.
  Always add a follow-up sentence on what the realtor did with the new leads and
  their disposition. → consult `references/pdf-format.md`.
- **Every seller PDF includes a "Your current competition" section.** → consult
  `references/pdf-format.md`.
- **Never auto-resolve direct listing URLs** (Realtor.ca anti-bot, Xposure
  deep-links fail). → consult `references/listing-urls.md`.
- Write run artifacts under `scripts/output/handoffs/seller-updates/<date>/`.

## Phase 0 — Precheck

- Confirm `docs/listings/active-listings.md` exists and is current. If it is
  empty or missing, stop — the feedback-chase aborts anyway, and the Phase 4
  context layer has nothing to anchor to.
- Confirm `scripts/.env` has `MLS_USERNAME` / `MLS_PASSWORD`.
- gws Gmail OAuth must be live (seller-finder + draft-creator need it). One-time
  setup: `gws auth login`. The refresh token persists in the macOS keychain.
- Both scrapers open a real Chromium window and may hit MFA — see the MFA note
  at the bottom; have Gmail access ready.
- **Freshness:** each scraper writes a dated JSON in `scripts/output/`. If
  today's file already exists, skip that scraper. Always re-run the report and
  draft steps — they are fast, run no browser, and pick up any data changes.

## Phase 1 — Pull data

Run only the stale pieces for today.

```bash
node scripts/seller-updates/showingtime-scraper.cjs --days=7
node scripts/seller-updates/seller-hub-scraper.cjs --no-screenshots
node scripts/marketing/prospecting-scraper.cjs
```

Flags: `showingtime-scraper.cjs` takes `--days=30` to widen the window and
`--all` to include already-seen feedback. `seller-hub-scraper.cjs` takes
`--date=YYYY-MM-DD` to target a specific file.

Expected outputs:

- `scripts/output/showingtime-feedback-YYYY-MM-DD.json`
- `scripts/output/seller-hub-YYYY-MM-DD.json`
- `scripts/output/prospecting-YYYY-MM-DD.json`

Also pull message context: relevant iMessages are part of the Seller Updates
context layer, read from `data/messages.db` (read-only immutable SQLite access —
a `file:<path>?mode=ro&immutable=1` URI; a bare `-readonly` returns
`SQLITE_CANTOPEN`). Capture recent seller concerns, agent feedback texted outside
ShowingTime, price conversations, and personal context that makes the email
sound like the realtor. `listing-report.cjs` and email drafting read this DB.

→ For ShowingTime / SellerHub / Prospecting click paths, the comp-parser DOM
anchors, data fields, and the synthetic-event gotcha on the Xposure listing
picker, consult `references/data-collection.md`.

**Nicola workaround:** if `seller-hub-scraper.cjs` times out on 703-525 Nicola
Street and `listing-report.cjs` drops it from `validListings`, use
`scripts/seller-updates/seller-update-nicola.cjs` (rolls last known-good Apr 28
hub stats forward). Document the staleness in the PDF. → see `lessons.md`.

## Phase 2 — Build the reports

Run after the data refresh. Always rebuild after data changes.

```bash
node scripts/seller-updates/listing-report.cjs --skip-mls
```

Expected outputs:

- `scripts/output/listing-reports/<slug>-YYYY-MM-DD.pdf`
- `scripts/output/listing-reports/<slug>-YYYY-MM-DD.json`
- refreshed `docs/listings/active-listings.md`

`--skip-mls` reuses the SellerHub comparables instead of a fresh MLS prospecting
search — faster, no MLS login. `--index=N` runs a single listing.
`--no-screenshots` skips PNGs.

Each listing report combines: ShowingTime showings/comments/agent names/interest
and pending feedback; SellerHub DOM, client views, agent views/prints, favorites,
comps, and trends; prospecting buyer-demand-by-price context; listing context
from `docs/listings/<slug>.md` and `active-listings.md`; and relevant
seller/agent message history from `data/messages.db`.

The PDF is the objective report. The JSON sidecar preserves the facts the Gmail
draft needs.

After the per-listing pull, roll the newest per-listing JSONs back into the
listings index:

```bash
node scripts/seller-updates/refresh-active-listings.js
```

It picks the newest JSON per address from `scripts/output/listing-reports/` and
rewrites `docs/listings/active-listings.md`.

**Legacy orchestrator.** `weekly-listing-report.cjs` (ShowingTime + Xposure
prospecting → per-listing weekly email drafts; flags `--listing=<MLS>`,
`--days=N`, `--skip-prospecting`) predates the combined-PDF `listing-report.cjs`.
Prefer `listing-report.cjs`. Only fall back to `weekly-listing-report.cjs` if you
explicitly need its lighter showings-only path.

→ For the locked competition section format (three groups, two price columns,
DOM column, clickable MLS links, CTA button), the conversation-summary privacy
rule, and the MIR ad-results block rules, consult `references/pdf-format.md`.

**Optional master/client PDFs.** `scripts/seller-updates/seller-hub-pdf.cjs`
builds two report PDFs from the latest `seller-hub-YYYY-MM-DD.json` — a MASTER
PDF for the realtor (cover + one detail page per listing, Telegram-delivered) and
per-seller CLIENT PDFs in `scripts/output/client-reports/<slug>-YYYY-MM-DD.pdf`
(soft language, internal cadence hidden, forwardable). Flags: `--no-telegram`,
`--date=YYYY-MM-DD`.

## Phase 3 — Handle feedback

After the report pass, ShowingTime shows pending agent feedback. Preview first,
then send:

```bash
node scripts/seller-updates/request-showing-feedback.cjs --dry-run
node scripts/seller-updates/request-showing-feedback.cjs
```

The script reads the latest showingtime-feedback JSON, filters to the realtor's own
listings (per `active-listings.md`), and iMessages each agent with a `pending`
status and a phone number. Two refinements it applies automatically:

- **Known agents get the casual variant.** If the agent already has a real
  `display_name` in `data/messages.db`, it drops the formal "this is the
  realtor's office" intro for a casual one-liner.
- **Already-answered agents get skipped.** It checks the agent's iMessage thread
  for the last 14 days for an inbound message naming the listing address. If they
  already gave feedback by text, it SKIPS the auto-text and surfaces the message
  so the realtor can push it into ShowingTime via `submit-showing-feedback.cjs`
  instead of double-asking.

When an agent replies by text/Telegram relay, submit the comment into
ShowingTime on their behalf:

```bash
node scripts/seller-updates/submit-showing-feedback.cjs \
  --listing=<MLS> \
  --agent="<Agent Name>" \
  --comments="<feedback text>" \
  --interested=somewhat --price=high --rating=4
```

`--comments` is required and is the field that matters; `--interested` /
`--price` / `--rating` are optional. Do NOT auto-parse ratings from free-text
replies — the realtor reviews and tells the Telegram agent what to submit.

## Phase 4 — Draft seller emails

Run after report PDFs are generated.

First, resolve any missing seller emails:

```bash
node scripts/seller-updates/find-seller-emails.js
```

It searches Gmail for the listing address, ranks correspondents (filtering out
the realtor + automation/agents/vendors), and caches the top human candidate per
MLS in `docs/listings/sellers.json`. Most sellers do not appear in Gmail at all
(the realtor works by iMessage/phone) — expect 0-3 candidates per listing. Treat the
auto-pick as a guess; eyeball the file and confirm or replace `email`.

**MANDATORY context layer — before drafting.** The scripts produce data, not
warmth. For each active listing, read the human context first, then rewrite the
script-generated draft so it sounds like the realtor talking to THIS seller about
THIS listing. → full recipe (Lofty API call, iMessage SQLite query, voice check)
in `references/voice-and-drafting.md`.

Then create the drafts:

```bash
node scripts/seller-updates/draft-listing-emails.js
```

Creates one Gmail draft per listing, the per-listing PDF attached, body in
the realtor's voice. Flags: `--mls=<MLS>` for one listing; `--dry-run` previews the
body without creating; `--no-recipient` skips the To: field so the realtor
addresses them manually.

Rules:

- Draft only. Never send.
- A draft that doesn't reference something specific to THIS seller/listing is
  not finished — rewrite before drafting to Gmail.

After this step, report which drafts were created and where — e.g. "8 drafts in
your Gmail Drafts folder, ready to review and send."

## MFA

Both scrapers write `scripts/.mfa-code` when they hit MFA and poll for it for up
to 3 minutes. Fetch the code from Gmail and write it into that file:

```bash
gws gmail search "xposure verification"
```

## Output map

```
scripts/output/
  showingtime-feedback-YYYY-MM-DD.json     raw showings + feedback
  seller-hub-YYYY-MM-DD.json               competitive + stats per listing
  prospecting-YYYY-MM-DD.json              buyer demand by price
  feedback-requests-sent.json              dedupe log of texts sent
  listing-reports/<slug>-YYYY-MM-DD.json   per-listing combined data sidecar
  listing-reports/<slug>-YYYY-MM-DD.pdf    per-listing PDF (attached to draft)
  client-reports/<slug>-YYYY-MM-DD.pdf     per-seller client-facing PDF (optional)
docs/listings/
  sellers.json                             MLS -> seller contact, grows over time
  active-listings.md                       auto-refreshed by listing-report.cjs
Gmail Drafts                               one per listing, ready to review + send
```

## Completion Gate — run before reporting "done"

One listing handled is not all listings handled. Before reporting, verify each
line — per listing — and cite the evidence:

- [ ] Every active listing has a per-listing PDF on disk
  (`scripts/output/listing-reports/<slug>-YYYY-MM-DD.pdf`), non-zero bytes.
- [ ] Every listing has a Gmail draft created — one per listing — with the PDF
  attached. A listing with no draft was skipped; name it.
- [ ] `docs/listings/sellers.json` updated for any new seller contact resolved
  this run.
- [ ] `feedback-requests-sent.json` updated if feedback texts were sent (and
  deduped — no double-sends).
- [ ] Drafts are drafts: nothing auto-sent. the realtor reviews and sends.

Status is `done` only if every active listing produced a PDF + draft. Any
listing missing either = `partial` — say "partial", name the listings that
didn't complete, and why (no seller contact, ShowingTime MFA, render fail).

## After the run

If a selector broke, a wrong-direction send was caught, a privacy slip happened,
or the realtor corrected any output, append a dated entry to `lessons.md`
(format: `[date] | issue | rule`).
