---
name: "outreach"
description: "The realtor's proactive lead outreach workflow, end to end. Use when the realtor asks \"draft outreach\", \"who should I text\", \"who needs a follow up\", \"outreach texts\", \"morning brew\", \"reach out to my leads\", \"draft some texts\", lead re-engagement, \"send #N\", or end-of-day outreach hygiene. One skill, one continuous run: context -> classify -> draft -> validate -> send -> hygiene. No handoffs, no sub-skills."
category: "real-estate-sales"
tags: ["outreach", "lofty", "imessage", "workflow"]
access:
  entitlement: "real_estate_sales"
---

# Outreach Workflow

This is one linear runbook. Work it top to bottom for a full outreach run. Do not
stop between phases to "hand off" — there are no sub-skills and no handoff packets.
Carry the run forward yourself.

Working root:

```bash
cd ~/elevate-premium
```

**Before you start, read `lessons.md` in this folder.** It is the living record of
every correction the realtor has made. Apply every lesson. Append to it immediately
whenever they correct a draft (see "After the run").

Every run is also governed by:

1. `docs/voice/realtor-profile.md` — voice, relationship tiers, situational playbook.
2. `docs/playbooks/lead-segment-cadence.md` — Hot/Warm/Nurture/Cold/Bad Leads routing.
3. `docs/playbooks/lofty-tags.md` — used when hygiene proposes tag changes.
4. `docs/voice/hpa-script-book.md` — reference only, not the default voice.

## Always-apply rules

These hold for the entire run. Do not consult a reference for them — just do them.

- **Never send without explicit same-turn approval.** "Draft" means SHOW, not send.
  Only Phase 5 sends, and only after the realtor gives a clear "send" command.
- **Join iMessage history by phone number before deciding a lead is first-touch.**
  Names in Lofty are not reliable enough. The phone is the only reliable join.
- **Skip DNC, unsubscribed, bought-elsewhere, cannot-text, and active-snooze leads
  before drafting.** Check Lofty's unsubscribe flags every time.
- **Do not invent source attribution.** Website/FB/site language is allowed only
  when the source or viewed-property data supports it.
- **Cooldown is per-lead, not per-message-type.** Skip anyone the realtor texted in the
  last 5 days, across every channel.
- **Keep daily sends under 8** unless the realtor explicitly overrides.
- **Treat listing signals as sales context only.** Outreach does not manage
  listings; it uses listing facts to decide what conversation is safe and relevant.
- **If a buyer lead touched the realtor's own listing, use the disclosure-safe path:**
  disclose the listing relationship, ask whether they are already represented, and
  do not pitch the realtor as their buyer agent for that listing.
- **No em dashes, ever, in any draft.** Full voice checklist is in
  `references/voice-and-drafting.md`.
- **If a phase is partial, still finish the run with `status: partial`** and list
  exactly what is missing. Do not silently stop.

Realtor-safe flow the run follows:
`Context -> Lead role -> Trigger -> Listing ownership -> Representation safety ->
Sales situation -> Draft -> Validate -> Approve -> Send -> Hygiene`.

## Phase 1 — Context

Build the canonical lead-state file. This is the data surface the rest of the run
must trust. Do not draft in this phase.

```bash
mkdir -p data/outreach/runs/$(date +%F)/handoffs
LEAD_STATE_OUT="data/outreach/runs/$(date +%F)/lead-state.json" \
  python3 scripts/outreach/build-lead-state.py
```

Inputs the script joins:

- `.env` with `LOFTY_API_KEY` when Lofty is available.
- `data/messages.db` for iMessage history.
- `data/brew/events.jsonl` for sent, skipped, snoozed, deferred, and failed events.
- `/tmp/outreach-brew-state.json` when the brew has explicit handled names.

Required checks after the script runs:

- Confirm `data/outreach/runs/<date>/lead-state.json` was written.
- Confirm `counts` exists and includes next-action buckets.
- Confirm each lead carries the realtor-safe fields `lead_role`, `trigger`,
  `listing_context`, and `representation_safety`.
- If Lofty failed or `LOFTY_API_KEY` is missing, mark the phase `partial` (not
  `done`) and let iMessage-only reply triage continue.
- If `data/messages.db` is missing, mark phone-history confidence low and do not let
  later phases call anything a true first touch.

→ Realtor-safe field schema and the `own_listing` agency-safety rule are in
`references/realtor-safe-fields.md`.

## Phase 2 — Classify

Separate reply-needed, eligible, suppressed, hygiene, and long-term-nurture leads
before any message writing. Do not write copy in this phase.

```bash
node scripts/outreach/classify-leads.js \
  data/outreach/runs/$(date +%F)/lead-state.json \
  data/outreach/runs/$(date +%F)/classified-leads.json
```

This writes `classified-leads.json` with these arrays: `reply_needed`,
`draft_candidates`, `hygiene_candidates`, `send_suppressed`, `long_term_nurture`.

Apply the hard gates: DNC / unsubscribed / bought-elsewhere / "not looking" / hard
remove → `send_suppressed`; snoozed or cooldown leads never become candidates;
phone-matched iMessage history means not first-touch; weak attribution gets
`source_attribution_risk: true`; classify investor / seller / closed-client /
referral relationship type before drafting; `own_listing` ownership stays on
the disclosure-safe path; `unknown` ownership blocks specific listing claims.

→ Cooldown windows, segment routing, the DNC-vs-Cold decision rule, the candidate
shape, New Leads hygiene, and the closed-client protocol are all in
`references/cadence-and-routing.md`.

## Phase 3 — Draft

Draft realtor-voice iMessage or email outreach from classified candidates only.
Draft only from `draft_candidates` or `reply_needed`, never from `send_suppressed`.
Do not send in this phase.

Write both:

- `data/outreach/runs/<date>/drafts.json` — the structured draft packet.
- `data/outreach/runs/<date>/drafts.md` — the review-friendly copy the realtor reads.

Core drafting rules (full voice spec and templates in
`references/voice-and-drafting.md`):

- First-touch web/FB/website leads need true source attribution. Do not invent it.
- If `prior_thread_exists` is true, do not reintroduce the realtor.
- Cold first-touch asks about area/neighbourhood before price.
- Never mention pre-approval, financing tags, or internal Lofty data in the first message.
- `listing_context.ownership = own_listing` → disclose it is their listing, ask
  whether they are already working with an agent, do not pitch them as their buyer agent.
- `ownership = unknown` → no address, MLS, price-drop, status, or listing-specific claims.
- `ownership = other_agent_listing` → normal buyer follow-up allowed, first message
  still focused on area/criteria, not pressure.
- Real text style: short paragraphs, no signoff, specific final question, `:)` when
  warm, space before `?` and `!`.
- HPA ("would you be opposed to", A/B-camp language) is not the default voice.

`drafts.json` shape — each draft carries: `draft_id`, `lead_id`, `name`, `phone`,
`email`, `source`, `situation`, `lead_role`, `relationship_tier`, `trigger`,
`listing_context`, `representation_safety`, `prior_thread_exists`,
`source_attribution_verified`, `cooldown_status`, `body`,
`requires_confirmation: true`, `risks`.

Present drafts to the realtor like this:

```
Outreach Drafts -- [date]

1. ASIF SIDDIQUI [New Lead]
   Data: looking in Kamloops, $720K-$1.08M, 4 bed SFH, viewed $898K listing
   Situation: Section 5.1 -- First outreach to new lead
   Draft: Hi Asif ! It's [the realtor's first name] from [the realtor's brokerage] :)

          Saw you were looking at homes on my website. I'd hate to be one of
          those spam-y agents bombarding you with stuff that misses the mark haha.

          What areas have been catching your eye ?
```

Then ask: "want me to send any of these, edit them, or skip?"

## Phase 4 — Validate and hygiene-screen

Run QA on the drafts before any of them is shown as send-ready.

```bash
node scripts/outreach/validate-drafts.js \
  data/outreach/runs/$(date +%F)/drafts.json \
  data/outreach/runs/$(date +%F)/validation.json
```

Then do a human/agent QA pass against `lessons.md`,
`docs/voice/realtor-profile.md`, and `docs/playbooks/lead-segment-cadence.md`.

Block the draft until fixed if it:

- targets a DNC, unsubscribed, bought-elsewhere, cannot-text, snoozed, or cooldown lead.
- treats an existing phone-matched iMessage thread as first-touch.
- invents website/FB/listing attribution.
- uses banned voice patterns from lessons.
- asks price or pre-approval questions on a cold first touch.
- asks for a quick chat on first touch.
- uses the realtor's own listing as a buyer-representation pitch without disclosure and
  an "are you already working with an agent?" check.
- makes listing-specific claims when `listing_context.ownership = unknown`.
- lacks `requires_confirmation: true`.
- has no reachable phone or email.

Write `validation.json` and update `drafts.json` if you fix copy. Only drafts with
no `errors` are send-ready.

## Phase 5 — Send

Ship a draft only on explicit same-turn approval. This is the only phase that sends.

This phase can consume validated drafts from `data/outreach/runs/<date>/drafts.json`
and also supports legacy morning-brew drafts in `data/brew/latest.json`. The
`UserPromptSubmit` hook loads `data/brew/latest.md` + `latest.json` into context, so
today's brew drafts are already visible — don't re-read them unless the user
references a past day ("send the Molly draft from yesterday"), then read
`data/brew/<date>-morning.json`.

**Resolve the draft.** On "send #3" / "send draft 3": first look in today's
validated `drafts.json`; if no match, look up id=3 in `data/brew/latest.json` across
`hot_leads` + `followups`. If the user named a person, match by first name in those
arrays; if multiple match, ask which. If ambiguous or missing, say so and show the
available IDs.

**Confirm before sending.** ALWAYS show the final text + destination back to
the realtor first:

```
Ready to send:
  To: Dick Toucher (+1 780-318-3773) [Lofty lead 1146...]
  Message:
  Hi Dick ! This is [the realtor's first name] from [the realtor's brokerage].

  Saw you were checking out the Boxwood Rd place in Kelowna :)

  Are you still actively looking out that way ?

Send as-is, edit, or skip?
```

Wait for their reply. "Send" / "go" / "ship" / "yes" = proceed. "Edit" = they give new
text. "Skip" = log the skip, don't send. If they edited the draft with "delete/cut
paragraph N", re-show the updated draft and send ONLY what is in the updated preview.

**Send.** On confirm:

```bash
scripts/outreach/send-imessage.sh "+17803183773" "message body"
```

The script normalizes the phone, escapes the body, sends via Messages.app. Exit 0 =
sent, nonzero = failed.

**Log to Lofty.** If the lead has a `lofty_lead_id` (not all iMessage-only drafts
do):

```bash
node scripts/outreach/log-lofty-note.js <lofty_lead_id> \
  "[YYYY-MM-DD] iMessage sent: \"<first 80 chars of body>...\""
```

**Log the event.** Append one line to `data/brew/events.jsonl`:

```json
{"ts":"<ISO>","draft_id":3,"action":"sent","name":"Dick Toucher","phone":"+17803183773","lofty_lead_id":1146,"brew_date":"2026-04-16"}
```

Actions: `sent`, `skipped`, `edited_and_sent`, `send_failed`, `sent_via_email`,
`deferred`, `snoozed`, `dismissed`. This file is how tomorrow's brew knows NOT to
re-draft the same lead within cooldown.

**Bounces and failures.** If `send-imessage.sh` fails: tell the realtor "iMessage to
(phone) failed. Want me to try email, or skip?" If she says email and there is an
email on file, send via `gws gmail users messages send` with a brief subject derived
from the message, log a Lofty note, log the event as `sent_via_email`. If she skips,
log `send_failed`. For repeated bounces, mark the lead cannot-text in Lofty.

**Batch sends.** "Send all hot" / "send the top 3" — confirm the batch as a numbered
list first, wait for one "go", then send sequentially with 30-second spacing so
iMessage doesn't flag as spam. When the realtor approves a numbered list of N people
with "send to all", that means EXACTLY the N she saw minus any removals she called
out — never the larger pool. Ask "Send to those N only?" before any blast. Never
send to a name not on the explicitly-displayed list.

**Action verbs.** Every brew draft has 4 verbs the realtor types in chat:

| Verb | Trigger phrases | What you run |
|---|---|---|
| Send | "send #N" / "send draft N" / "send the [Name] draft" / "ship N" / "go on N" | confirm → `scripts/outreach/send-imessage.sh` → log Lofty → events.jsonl `action:"sent"` |
| Edit | "edit N: <new body>" / "rewrite N as <body>" | confirm → `scripts/outreach/send-imessage.sh` with new body → events.jsonl `action:"edited_sent"` (flips `approval_queue.resolution='edited_sent'`) |
| Snooze | "snooze N" (default 3d) / "snooze 5 for a week" / "snooze the Diane draft 2 days" | `python3 scripts/outreach/draft-action.py snooze N [days]` |
| Dismiss | "dismiss N" / "kill N" / "drop N" / "never message [Name]" | `python3 scripts/outreach/draft-action.py dismiss N` |

Snooze re-surfaces the lead in N days (default 3); the 10-min `draft_inbound.py`
poller and the morning brew both filter snoozed leads until `resurface_after`.
Dismiss is permanent. "skip N" maps to "snooze 3d" (legacy `action:"skipped"` was a
3-day soft kill — keep that behaviour). You don't need to confirm Snooze or Dismiss
before running — both are reversible. Just acknowledge after.

**Never.** Never send without an explicit confirm — a Telegram "go" is valid only if
it follows a "Ready to send" prompt you just sent. Never batch-send more than 8 in a
day. Never send between 9pm and 7am local unless the realtor explicitly overrides.

→ Full Lofty API reference (endpoints, fields, note formats, curl forms) is in
`references/lofty-api.md`.

## Phase 6 — Hygiene

Run after outreach was sent, when the realtor asks who replied, or during an
end-of-day / next-morning cleanup.

Report-only review:

```bash
node scripts/outreach/eod-review.js --days 3
```

Apply Lofty notes only after the realtor approves:

```bash
node scripts/outreach/eod-review.js --days 3 --apply
```

The script writes `output/eod-review/<date>.md`.

Hygiene rules:

- Re-query `data/messages.db` by phone for replies after each send.
- First split the contacted list into "replied" vs "silent" by joining
  `events.jsonl` against `data/messages.db` inbound messages. Apply hygiene only to
  the replied subset — silent leads already have send-time notes and give no new
  signal, so skip them. Do not write redundant outbound-only notes.
- Log Lofty notes for substantive replies: timeline, criteria, location, financing,
  life event, referral, seller signal, investor signal.
- Do not log routine chit-chat for closed clients unless it contains a useful memory
  or referral signal.
- Propose stage/tag changes; do not silently apply them unless the run mode
  explicitly approves it.
- Bought-elsewhere / not-looking / remove / stop / hard opt-out → `Bad Leads` plus
  cannot-contact flags.
- Future-possible but not-now leads → `Cold` or `Nurture` with a snooze based on
  `docs/playbooks/lead-segment-cadence.md`.
- Scan every lead in stage `New Leads`: if `data/messages.db` shows prior two-way
  conversation, move them out of New Leads to the right stage.

→ DNC-vs-Cold routing, segment-to-stage mapping, and the closed-client protocol are
in `references/cadence-and-routing.md`. Stage/tag/note endpoints are in
`references/lofty-api.md`.

## Completion Gate — run before reporting "done"

Drafting messages is not outreach. Sending is. Before reporting, verify each
line and cite the evidence:

- [ ] Every message that was supposed to send has a per-recipient send
  confirmation (provider message id / 200-OK), not just "draft written". A
  recipient with no confirmation did NOT get contacted — name them.
- [ ] `events.jsonl` updated with one send event per contacted lead.
- [ ] If Phase 6 hygiene ran: `output/eod-review/<date>.md` written.
- [ ] Lofty notes/stage changes applied ONLY for the replied subset and ONLY
  after the realtor's approval. Notes proposed-but-not-approved are not "done".

Status is `done` only if every intended send is confirmed. Any send that
failed, was skipped, or is still a draft = `partial` — say "partial", list the
exact recipients still pending, and do NOT claim the batch went out.

## After the run

When the realtor corrects a draft:

1. Immediately append a dated entry to `.claude/skills/outreach/lessons.md`.
2. Format: `[date] | [what went wrong] | [the rule to follow]`.
3. If she says "that doesn't sound like me", log the exact phrase and what she'd say.
4. If the correction is about a voice pattern that should live in
   `realtor-profile.md`, also propose an update to that file's Section 3, 5, or 9.

Every correction compounds. This is not optional.
