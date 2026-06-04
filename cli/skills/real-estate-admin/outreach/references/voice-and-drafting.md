# Voice & Drafting Guide

The full voice spec for lead outreach. **Read this every run before Phase 3, together
with the realtor's own `docs/voice/realtor-profile.md`** (which holds *this* realtor's
specific phrases, tone, and tier playbook). This file is the generic craft; the
realtor-profile is who they are. If the realtor-profile is missing or thin, draft
conservatively in a plain, warm, human voice and ask the realtor for a few real texts
they've sent so we can populate it.

## The one rule that matters most

**Read the lead's actual history before you write a word.** Open the Lofty thread and
the iMessage history for that lead. The draft has to sound like the next message in a
real conversation — not the first line of a campaign. If you've already talked to this
person, never reintroduce yourself or the brokerage.

A message that ignores the existing thread is the #1 failure. It reads as a bot and
the realtor will not send it.

## What good sounds like

- **A busy human realtor texting**, not marketing copy. Short. One idea. Lowercase is
  fine. Contractions, not formal grammar.
- **Matched to the lead's energy.** If they wrote two casual lines, answer in two
  casual lines. If they're formal, be a touch more formal. Mirror, don't reset.
- **Specific to them.** Reference the actual thing — the area they asked about, the
  listing they viewed, the question they left hanging — not a generic hook.
- **One clear ask**, and an easy one. "Want me to send a few in that area?" beats
  "Let me know how I can help with your real estate needs!"

## Hard bans (these are what make it sound automated)

- ❌ "I saw you came through the website" / "you registered on my site" as an opener to
  someone you've already been talking to. Only use source language for a genuine
  first touch, and only if the source data supports it.
- ❌ Reintroducing yourself ("Hi, this is [name] from [brokerage]") in an existing
  thread.
- ❌ Corporate filler: "reaching out," "touching base," "just following up," "your
  real estate needs," "feel free to," "at your earliest convenience."
- ❌ Em dashes. Ever.
- ❌ Multiple asks, links, or a wall of text in a first message.
- ❌ Inventing source attribution, pre-approval/financing references, or anything from
  internal Lofty data in a first message.

## Situational defaults

- **First-touch, cold:** ask about area/neighbourhood or what they're looking for
  before price. Warm and low-pressure. Source language only if real.
- **Reply to an active thread:** answer what they actually said. No CTA pivot, no
  "anyway, want to book a call?" if they were just chatting.
- **Re-engagement (gone quiet):** light, specific, easy to answer. Reference the last
  real thing, not "checking in."
- **Their own listing (`ownership = own_listing`):** disclose it's the realtor's
  listing, ask if they're already represented, do not pitch as their buyer agent.

## Before you finalize each draft, check

1. Would a real person text this, or does it smell like a tool? (If unsure, it's the tool.)
2. Does it respect the existing thread (no re-intro, no repeated ask)?
3. Is it in *this* realtor's voice per `docs/voice/realtor-profile.md`?
4. One ask, no em dashes, no corporate filler, true source only?
5. Is it short enough to read at a glance?

If a draft fails any of these, rewrite it. Then write both `drafts.json` and the
review-friendly `drafts.md` for the realtor to approve.
