---
name: social-content-batching
description: Batch social content across a realtor's brand and personal channels, keeping lanes apart. Use when social strategy inputs are known and the user asks to batch content for the brand page, their personal page, dashboard/AI skill-pack marketing, or all channels together.
version: 0.2.0
metadata:
  elevate:
    tags: [real-estate, social-media, content-batching, instagram, facebook, brand-page, realtor-personal, ai-dashboard]
---

# Social Content Batching

Use this to create practical content batches for a realtor's social ecosystem. It should produce ready-to-review ideas, scripts, captions, carousel outlines, story prompts, and visual direction while protecting the channel split.

## Core rule

One batching run can cover multiple channels, but the content must not be duplicated across channels. Create distinct but complementary calendars. Cross-post only when a topic naturally fits more than one audience, and rewrite the caption, CTA, and angle for each account.

## Prerequisite discovery

Before batching, load `real-estate-social-strategy-discovery` if the strategy context is missing, stale, or the user references an inspiration account, ChatGPT pulls, recent Instagram/Facebook posts, or brand/channel setup.

If the user asks whether recent social posts were reviewed, verify instead of assuming:

- Try connected account tools first if available.
- If Composio returns auth errors or connected-account tools fail, use browser/public profile access and extract visible captions/alt text from recent posts/reels/collabs.
- Be clear about what was and was not reviewed, e.g. Instagram visible public posts reviewed, Facebook not verified.

## Channel modes

### 1. Brand/team client-facing mode

Use for the realtor's brand/team page and listing pages.

Purpose:

- Buyers, sellers, past clients, investors, local community.
- The realtor's full service region, not just the most-mentioned city.
- Listings as lifestyle stories, local life, neighbourhood guidance, buyer/seller education, market clarity, proof, testimonials, team trust.

Hard boundaries:

- No agent coaching, brokerage attraction, or business-building content.
- No `you guys`.
- Skip any neighbourhoods/developments the realtor has said not to actively market.
- Translate agent-facing themes into client value.

Examples of translation:

- Agent systems theme -> `Better systems mean fewer missed details and a calmer client experience.`
- AI efficiency theme -> `More organized back-end work gives us more energy for the conversations and care that matter.`
- Growth mindset theme -> `Buying or selling is easier when decisions come from clarity instead of pressure.`

Visual style:

- Use the project's `knowledge/brand-guide.md` (or equivalent stored brand-guide file) as the base brand source when exact tokens are needed, then apply the current editorial direction the realtor has set.
- Use the realtor's actual brand palette and type system once known (example seen in one build-out: forest green, deep green, burnt gold, cream/paper backgrounds with editorial serif headings and clean sans body copy).
- Clean spacing, warm lifestyle photography, homes/neighbourhood details, not cluttered realtor flyers.
- If this batching run produces actual image assets or hands off to a graphic/Buffer workflow, apply the same visual QA gate used by `marketing`: locked reference source, exported contact sheet, dimension/aspect checks, approved-photo-source verification, and visual comparison before calling the package ready.
- Do not include Just Listed / Coming Soon / Open House listing-card production in this skill; that workflow lives in a separate skill.
- Keep a brand-building/editorial system for education, neighbourhood, seller-prep, market-update, local-life, relationship-building, and listing-photo-based value content.
- Use approved active/current listing photos as educational or lifestyle visuals when helpful. Example: a kitchen photo can support buyer education about layout, or a living room photo can support seller education about presentation.
- For active/current listing status, use the Admin dashboard/deals overview as the source of truth before asking the user. Pull active listing candidates from `deals_overview` / Admin dashboard, then use the matching Google Drive listing folders to grab listing photos. The realtor will provide approved personal/BTS photos separately, so do not block brand-page listing-photo posts on missing personal photos.
- When a listing-photo-based value post references availability, verify the property is still active and include address + MLS® number where appropriate: `This home is currently available at [address]. MLS® [number].`
- Do not overload graphics. Move details into caption or carousel slides instead of packing too many specs/contact lines into one cover.

### 2. Realtor personal-brand mode

Use for the realtor's personal Instagram/Facebook handle and personal-style content.

Purpose:

- The realtor as parent/family member, Realtor, founder, coach, leader (adjust to whichever of these roles actually apply to this realtor).
- Persona development, growth mindset, intentionality, relationship-over-transaction, leadership, systems/leverage, AI buying back time, reflective long captions, honest lessons, and `what shifted / what I learned` storytelling.

Tone:

- First-person and reflective.
- Long-form captions are allowed when the post is about a lesson, growth, or leadership.
- Grounded, candid, and practical rather than polished generic coaching.

Useful angles:

- `The relationship is the business.`
- `The goal is not to make real estate less personal. It is to protect the personal part.`
- `The version of me who built this had to show up before the result did.`
- `AI/systems buy back time so I can give more energy to clients and relationships.`

### 3. Coaching / agent-success mode

Use for a coaching/agent-success brand, podcast, dashboard/AI, and agent-facing channels. Only applies if the realtor also coaches or mentors other agents.

Primary purpose: help agents become more successful.

Content should mostly focus on:

- coaching agents
- podcast and guest highlights
- sales/business growth
- marketing and follow-up strategy
- productivity audits
- AI leverage and workflows
- dashboard/skill-pack marketing
- systems that support client care
- agent success roadmap
- getting into real estate
- partner-with-the-realtor content

Positioning:

- This channel is coaching and agent success first.
- AI content should be sales/business driven: more leverage, better follow-up, fewer missed opportunities, more consistent client care, stronger relationships, and more time for income-producing work.
- Do not lead with `free AI tools` as a blunt offer.
- Say that agents who partner/work directly with the realtor get access to the roadmap, systems, AI stack, agent packs, and support the realtor is actually using.
- Frame it as partnership, leverage, systems, client care, and building with support.
- Position the realtor as an experienced mentor/coach (adjust the specific track record to what this realtor has actually done).
- Avoid `join my downline` energy. Keep it honest, practical, aspirational, and grounded in mentorship, systems, relationships, and growth.

Sample angles:

- `Most agents do not need more hours. They need fewer leaks.`
- `AI is not replacing the relationship. It is buying back the time to protect it.`
- `I do not want AI that answers random prompts. I want AI that knows the workflow.`
- `When agents build beside me, they are not starting from scratch.`
- `If you are thinking about getting into real estate, I would rather you understand what this business actually takes before you only see the highlight reel.`
- `There is a difference between getting licensed and building a real business.`

### 4. Getting into real estate / mentorship mode

Use for personal, coaching, or agent-facing channels when the audience is considering real estate or wants mentorship. Only applies if the realtor also coaches or mentors other agents.

Purpose:

- Help people decide whether real estate is a fit.
- Explain the mindset shift from employee to entrepreneur.
- Show the value of mentorship, systems, follow-up, client care, and leadership.
- Invite people to partner with the realtor without making the content feel like recruiting copy.

Useful topics:

- What the realtor wishes people knew before getting licensed.
- What new agents underestimate.
- Why relationships matter more than scripts.
- The difference between being busy and building a business.
- How AI and systems can shorten the learning curve without replacing the human part.
- What support looks like when someone works directly with the realtor.

## Batch input checklist

If not already provided, infer what you can and ask only for true blockers:

1. Channels to batch: brand/team page, realtor personal, agent-success/coaching, Facebook, Instagram, stories, reels, email repurpose.
2. Batch size: weekly, monthly, listing launch, themed, or both channels.
3. Priority goal: listing leads, buyer leads, past-client nurture, local authority, partnership/agent attraction, dashboard/skill-pack sales.
4. Any current listings, events, launches, or timely topics.
5. Inspiration-account source material or examples if the user has not pasted them yet.

Do not ask again for known defaults unless they affect the output.

## Output format

For multi-channel batches, use a table with these columns:

| Post | Account | Status | Theme | Format | Hook | Angle | CTA | Visual direction | Notes |
|---|---|---|---|---|---|---|---|---|---|

`Status` must be one of:

- `Brand only`
- `Personal only`
- `Agent-success only`
- `Cross-post approved`

For each batch, also include:

- Caption drafts in the realtor's style.
- Reel shot list or B-roll notes for reel/video posts.
- Carousel slide outline for carousel posts.
- Story sequence prompts when useful.
- Hashtag/keyword suggestions only if requested or operationally useful.

## Default batch mix and frequency

When the user says `batch content for both`, default to a daily-capable proofing package if enough quality content exists:

- Brand/team page: daily if possible, focused on brand, education, local lifestyle, buyer/seller guidance, and listing-photo-based value posts.
- Realtor personal: daily if possible, with a mix of persona development, growth mindset, family/business balance, relationship-over-transaction, AI/time-back, leadership, and mentorship.
- Coaching/agent-facing (if applicable): 5 to 7 posts/week, mostly about helping agents become more successful through coaching, podcast/guest highlights, sales/business growth, productivity, AI leverage, dashboard/skill-pack education, and partner-with-the-realtor content.
- 2 to 3 optional cross-post or related-root concepts, rewritten separately for each account.
- 3 to 5 story prompts per channel where useful.

Quality rule: do not fill the calendar just to post daily. If source material or visuals are weak, reduce frequency and flag what is needed.

Caption length rule: ask or infer whether the realtor likes a mix of short and long captions. Rotate short punchy captions, medium educational captions, and longer reflective/story captions within each batch when that mix fits their style.

Adjust if the user specifies weekly/monthly/listing-launch.

## Cross-post rules

A cross-post is allowed only if both audiences care. Never copy/paste the exact same caption between the brand page and personal.

Example root topic: seller overpricing.

- Brand version: educational seller guidance about first two weeks on market and perceived value.
- Personal version: the realtor's reflective opinion from repeated seller conversations.

Example root topic: AI systems.

- Brand version: client benefit: organized systems create better communication and fewer missed details.
- Personal/agent-success version: agent leverage: dashboard and workflows buy back time for client relationships.

## Realtor writing rules

When writing captions in the realtor's voice, first learn their actual preferences from strategy discovery or prior samples; a real example set looked like this:

- Use warm, direct, conversational language.
- `I feel like` is preferred for opinions.
- Use `we` language where natural.
- No em dashes.
- Space before `?` and `!` in client-facing drafts.
- A single signature emoji only if one is needed.
- Avoid `at the end of the day`, `take this with a grain of salt`, `would you be opposed to`, and `you guys`.

### Brand / listing caption rewrite mode

Use these rules for listing captions, open-house copy, market snapshots, subject lines, preview text, and caption alternatives, calibrated from the realtor's own prior samples (e.g. a ChatGPT project or brand voice doc):

- Lead with the feeling, setup, or buyer benefit, not just the specs.
- Translate features into real-life meaning: e.g. not just `big yard`, but `a yard big enough for the kids and the dog to actually run around`.
- Use short paragraphs with blank lines between them.
- Keep the tone conversational, confident, and polished, like telling a friend about a strong listing.
- Good recurring phrases: `this is one of those...`, `the kind of home...`, `what makes this work...`, `photos do not fully capture...`, `come see it in person and you will get it`, `honestly...`, `I feel like...`.
- For open houses, explain why the property is worth seeing in person, not only date/time/specs.
- For market snapshots, keep the tone calm and strategic: clarity, preparation, thoughtful decisions, well-positioned homes, buyer opportunity, seller strategy.
- When the user asks for `more`, `make it sound like me`, or `have feelings on it`, increase specificity, warmth, and practical buyer meaning rather than adding generic hype.

Banned generic real-estate words/phrases for brand/listing copy unless quoted from user-provided source:

- discover
- nestled
- stunning
- perfect blend
- dream home
- don't miss out
- boasts
- features
- offers
- imagine
- picture yourself
- rare find
- unlock
- elevate
- embark

## Verification before finalizing

- Confirm brand-page content is consumer-facing.
- Confirm personal content preserves persona/growth/relationship/system themes when relevant.
- Confirm agent-success content is not accidentally placed on the brand page.
- Confirm cross-post items are intentionally marked and rewritten per channel.
- If source review was incomplete, say exactly what still needs to be reviewed.
