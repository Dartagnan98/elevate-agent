---
name: real-estate-social-strategy-discovery
description: Build or refresh a real-estate social strategy from brand assets and public profiles. Use when the user asks to build social pillars, learn from a website/Instagram, pull a prior strategy doc, or ground a real estate brand's social channels instead of using generic advice.
version: 0.1.0
metadata:
  elevate:
    tags: [real-estate, social-media, strategy, brand, discovery, instagram, website]
---

# Real Estate Social Strategy Discovery

Use this before creating social media pillars, a content calendar, profile direction, or a channel split for a realtor brand. The goal is to avoid generic Realtor Instagram advice and ground the strategy in the realtor's actual website, public social profiles, prior strategy docs, market, audience, and repeated opinions.

## Core rule

Do not jump straight to a 30-day calendar. First collect the brand truth, audience truth, local truth, and opinion truth. A useful social strategy needs facts plus the realtor's point of view.

## Workflow

### 1. Load prior strategy assets

Search for any existing strategy docs before recreating from scratch. If the user shares a ChatGPT project URL, open it in the browser while logged into the user's ChatGPT account if available, then mine both the project chat list and individual relevant chats. Use `document.body.innerText` / browser console extraction if snapshots hang. Click through enough representative chats to capture voice, format, captions, banned words, and visual/asset patterns. Be explicit if you only reviewed visible project metadata or a subset of chats.

For the user's ChatGPT projects, useful targets include:

- Brand/team project: listing captions, open-house copy, market snapshots, visual graphic references, and explicit voice rules.
- Coaching/agent-success project: podcast captions, coaching/mindset course prompts, AI/productivity/agent-success content, getting-into-real-estate mentorship, and agent-facing caption formats.

Search for any existing strategy docs before recreating from scratch.

- Search current repo/workspace for the person, brand, handle, and phrases like `social strategy`, `content pillars`, `Instagram`, plus any inspiration-account names or brand names the user has previously referenced.
- If the user references a Claude/ChatGPT session or previous strategy, use `session_search` first, then local file search.
- For Claude Code sessions, check local Claude project history under `~/.claude/projects` and app/cache artifacts if needed. If the user provides a Claude Code session URL and the strategy was committed to a Claude branch, fetch the branch file rather than reconstructing it from memory. Example pattern:
  - Find branch from session/context.
  - `git fetch origin <branch>` from the repo.
  - `git show FETCH_HEAD:path/to/strategy.md > /tmp/strategy.md`.
  - Copy into `docs/marketing/` or another clear strategy location.
  - Verify with `git diff --no-index` before reporting success.
- Never preserve secrets/tokens/passwords found while searching caches or crash dumps. Redact as `[REDACTED]` and do not include them in outputs or skills.

### 2. Mine the website

If `Browser Use CLI extraction` fails, fall back to direct fetch via Python/urllib or WordPress REST API.

Useful WordPress endpoints:

```bash
python3 - <<'PY'
import urllib.request, json
for endpoint in [
  'https://DOMAIN/wp-json/wp/v2/posts?per_page=50&_fields=link,title,excerpt,content,date,categories',
  'https://DOMAIN/wp-json/wp/v2/pages?per_page=50&_fields=link,title,excerpt'
]:
  req=urllib.request.Request(endpoint, headers={'User-Agent':'Mozilla/5.0'})
  print(endpoint)
  print(urllib.request.urlopen(req, timeout=20).read().decode()[:5000])
PY
```

Extract:

- Positioning and proof points.
- Services and markets served.
- Blog/topic themes.
- Repeated language.
- Local places, seasonal guides, buyer/seller FAQs.
- Coaching/team/podcast/agent-attraction content that may belong on a separate channel.

### 3. Mine public Instagram/profile data

Use web search and direct public page fetch. Public Instagram often exposes profile metadata even when feed access is limited.

Checks:

- `Browser Use CLI search("site:instagram.com/<handle> <handle> Instagram")`
- Fetch `https://www.instagram.com/<handle>/` with a browser-like user-agent.
- Extract `<meta name="description">`, `og:title`, and `og:description`.
- Search web snippets for public reel/post captions if the feed is not fully available.

Extract:

- Name line and identity stack.
- Bio text and linked/mentioned brands.
- Follower/post counts if exposed.
- Public caption themes and tone.
- Channel split implications, e.g. personal page versus team/brand page.

### 4. Ask for only the missing opinion layer

After website/social mining, ask for the few inputs that cannot be reliably inferred:

1. Top audiences.
2. Areas/neighbourhoods to prioritize or avoid.
3. Realtor opinions said often.
4. Local favourites currently loved.
5. What the page must not feel like.
6. How personal the brand page should be.
7. Main CTAs/offers.
8. Proof/client stories available for use.

Accept messy bullets. Clean them up yourself.

### 5. Separate channels clearly

If the realtor runs more than one brand/personal channel, use a split like this unless the user overrides it:

- Team/brand page: consumer-facing real estate lifestyle page. Local life, neighbourhoods, buyer/seller guidance, listings as lifestyle, proof, team trust. This page is not the place for agent coaching/brokerage-attraction content; translate those themes into buyer/seller/client-facing value.
- Realtor personal page: full identity stack, e.g. parent + Realtor + founder + coach + leadership + growth without burnout, if applicable to this realtor. Recent visible Instagram patterns often include persona development, growth mindset, intentionality, relationship-over-transaction, systems/leverage, AI buying back time, reflective long captions, and honest `what shifted / what I learned` storytelling.
- Coaching / agent-success channels (if the realtor also coaches or mentors other agents): agent education, systems, brokerage-attraction, podcast, AI dashboard and skill-pack marketing, high-performance-agent content.

Avoid making the team/brand page feel like an agent coaching page unless explicitly requested.

When the user asks to batch content for both the brand page and the personal page, do not duplicate the same calendar across both. Generate distinct but complementary content lanes. Mark each asset as `Brand only`, `Personal only`, or `Cross-post approved`, and rewrite cross-post captions/CTAs for each audience.

### 6. Convert inputs into usable pillars

Each pillar should include:

- Audience served.
- What the pillar proves.
- Topics/sub-pillars.
- Reels hooks.
- Carousel titles.
- Stories ideas.
- CTA.
- Boundaries or compliance notes.

Example pillar set built from a real discovery session (families/luxury/move-up-buyer market, one core service region plus a wider secondary region):

1. Local Life in [primary city] + [wider region].
2. Move-Up Family Strategy.
3. Seller Confidence.
4. Buyer Opportunity Watch.
5. Luxury + Lifestyle.
6. Investor Lens.
7. Trust + Proof.

Example of realtor-specific inputs worth preserving once discovered (illustrative, replace with this realtor's actual answers):

- Audiences: families with kids, luxury buyers/sellers, move-up families, investors, past clients, buyers/sellers across the primary and secondary service regions.
- Any neighbourhoods/developments the realtor has said not to actively market.
- Seller opinion: sellers over-focus on timing; lining timing up is the Realtor's job.
- Buyer opinion: buyers over-focus on the best time instead of watching for the right opportunities.
- Seller prep: the house does not need to be perfect, but less stuff is always better. Decluttering is huge. Less is more.
- Pricing: overpricing because "I'm not in a rush" erodes perceived value; buyers wonder what's wrong; the first two weeks on market are most important.
- Realtor trust: a good Realtor should not be frustrated by questions or pretend to know legal/technical answers; saying "I don't know, but I'll find out" is a strength.
- Local favourite spots the realtor names by name (restaurants, parks, landmarks) so content reads as locally grounded rather than generic.

### 7. Save durable strategy facts

Use `fact_store` for compact, reusable project facts discovered during the strategy session. Do not cram large strategy docs into always-on memory. Store source URI and tags such as `social-media-strategy`, `realtor-voice`, plus the specific brand/team name.

## Pitfalls

- Do not use generic real-estate content pillars before looking at the user's actual website/social content.
- Do not position a multi-region brand as covering only its most-mentioned city when it actually serves a wider region, unless the asset is intentionally city-specific.
- Do not include agent coaching/brokerage-attraction content on the consumer-facing brand page by default. Keep it consumer-facing unless the user asks otherwise.
- Do not ask for information already visible on the website or public profile.
- Do not expose secrets found during local-cache or browser-profile searching.
- Avoid fair-housing issues: do not target/exclude protected classes or make school/demographic claims as selling points.

## Verification

Before final response:

- Confirm the source files/pages/profiles actually existed and were read.
- If a strategy doc was copied from a branch/cache, verify the saved file matches the source.
- If facts were saved, report only the useful strategic result, not internal memory mechanics unless asked.
