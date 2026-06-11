---
name: idea-grooming
description: "Pressure-test a captured idea against an objective rubric and write a structured analysis back into the source file. Use when: a new idea drops into an Ideas/ inbox (manual or cron-watched), or when re-grilling an existing groomed idea against fresh market data."
category: agent-ops
---

# Idea Grooming

You evaluate captured ideas against a rubric and write the analysis **back into the source file in place**. The original capture stays at the top, untouched. Frontmatter flips from `status: raw` to `status: groomed` and gets the structured fields populated.

This skill is domain-agnostic — the rubric works for financial newsletters, perfumery products, fitness apps, AI tools, anything. **Domain customization** (which questions to emphasize, what counts as novelty in this space, what comparables to surface) lives in the **agent's own identity and memory**, not in this skill. Read your `MEMORY.md` / `memory/<day>.md` (or use the **memory** tool to recall) for the domain overlay. If your domain focus, toolsets, skills, or role need to change, that's a **manage_agent** operation — never edit config files by hand.

---

## Inputs

A markdown file at a path the operator provides (typically `<vault>/Ideas/<idea>.md`). The file follows the canonical template:

```yaml
---
title: <one-line idea title>
status: raw
created: YYYY-MM-DD
groomed:
captured_by: <sam | quint | other>
tags: []
originality_score:
market_size:
manual_burden:
verdict:
folder_promoted: false
---

# <Title>

## Original capture
<verbatim source>

## Originality
*(empty — you fill)*

## Market potential
*(empty — you fill)*

## Moats
## Barriers
## Scaling vulnerabilities
## Manual burden
## Verdict
```

If a file you're asked to groom doesn't have the frontmatter shell, add it. Don't refuse the work just because the format is off.

---

## Posture (read this every time)

- **Ground every claim in something concrete.** "There's clearly demand" is not a claim. "Stratechery has 30k+ paid subs at $120/yr in this exact category" is.
- **Default to skepticism.** Most ideas are average. Originality is rare; mark `originality_score: 2` if that's the truth.
- **Surface disagreement.** If two parts of the analysis tension (huge market BUT massive moats already in place), say so.
- **No flattery.** If verdict is `kill`, write the kill reason cleanly. The whole point of grooming is sharper thinking, not validation.
- **Write the body in plain language.** This is read by humans, not by other agents. No bureaucratese.

---

## Section-by-section rubric

### Originality (1-5)

- **1** — exists at scale, undifferentiated copy
- **2** — exists, this version has a small twist
- **3** — meaningful differentiation in a crowded space
- **4** — genuinely new angle in a known category
- **5** — new category, no obvious comparable

Always name the closest 2-3 comparables explicitly. If there are none, that's a flag — most "original" ideas just have unfindable competition, not zero.

### Market potential

Three reads:
- **Who buys/uses** — name the persona, not "people who want X"
- **Demand signal** — what's already paying for nearby goods? Search trends? Subreddit activity? Conference floor density?
- **Size band** — `small` (<$10M TAM, lifestyle), `mid` ($10M–$1B, real business), `large` ($1B–$50B, venture-scale), `massive` ($50B+, generational)

Pick the band you can defend. If you'd cringe at a partner reading your defense, drop a band.

### Moats

For each defensible advantage, mark it:
- **Data** — proprietary data accumulating with use
- **Distribution** — owned audience, established channel
- **Brand** — recognized name worth a premium
- **Network** — value increases with users
- **Switching cost** — pain to leave, not just inertia
- **Regulatory** — license/compliance barrier
- **Talent** — rare skill concentrated here
- **IP** — patents, copyright, trade secret

For each: **load-bearing** (would actually defend in a price war) or **weak** (sounds defensible, isn't). Don't list a moat if it's weak — say "no real moat" honestly.

### Barriers

What would actually stop us from shipping v1?
- **Tech** — does it exist, is it ours to build, do we have skills
- **Capital** — burn rate to MVP
- **Distribution** — how do customers find this
- **Regulation** — license/compliance to operate
- **Talent** — who has to be hired
- **Customer trust** — does the audience believe a 2-person op can deliver

Rank by which would ACTUALLY stop us. Customer trust often beats tech.

### Scaling vulnerabilities

What breaks between MVP and 10x / 100x / 1000x:
- Manual-ops bottleneck (does someone have to touch every customer)
- Unit economics (cost curve flat or flipping negative at scale)
- Support burden (who answers tickets at 1k users)
- Compliance scope (regulation tightens at audience size)
- Vendor lock-in (Mailchimp limits, API rate limits, etc.)

For each: at what scale does this bite? Day 1, 100 users, 10k users?

### Manual burden

Honest labor estimate:
- **low** — <2 hr/week to operate at MVP scale
- **med** — 2–15 hr/week
- **high** — 15+ hr/week, requires a hire to scale

Be specific about WHERE the burden sits — content production, customer success, ops, content review. AI helps where it's actually generative; not where it's review/judgment.

### Verdict

- **pursue** — passes on all dimensions OR strong enough on 2-3 to justify exploring deeper. Add 1-3 concrete next moves.
- **park** — promising but blocked by timing, capital, or another priority. Add a "revisit when X" condition.
- **kill** — fails core dimension (no moat AND no market AND no originality). Add the one-line kill reason.
- **needs-more** — analysis genuinely can't conclude with available info. Add what to learn.

---

## Promotion rule (single file → folder)

Promote a `.md` to a folder (`<idea-name>/Index.md` + `Notes/` + `References/` + `Open Questions.md`) when ALL true:
- `verdict: pursue`
- 3+ distinct work threads (e.g. tech build + brand work + customer dev + legal review)
- The single-file structure is becoming hard to reason about

Set `folder_promoted: true` in frontmatter when you do this. Move the original file to become `Index.md` in the new folder.

---

## Domain overlay (read your memory)

Before grooming, recall your own domain-specific signals from memory (the **memory** tool, plus your `MEMORY.md` / `memory/<day>.md`):
- **domains** — what spaces you work in (financial, perfumery, fitness, ai-communities, etc.)
- **comparables seed** — known companies/products in this space the rubric should consider
- **market signals** — things that count as demand evidence in this domain
- **kill dimensions** — domain-specific dealbreakers (e.g. "regulated advice without a license" for financial)

If you have no domain context in memory, run the rubric domain-agnostic and surface in the verdict that no domain context was loaded. To make a domain overlay stick across runs, write it with the **memory** tool — don't hand-edit any config.

---

## Output

You write the analysis **back into the source file in place**:
1. Update frontmatter: `status: groomed`, `groomed: <today's date>`, fill `originality_score`, `market_size`, `manual_burden`, `verdict`, populate `tags` if useful
2. Fill each section body in the rubric order above
3. If verdict is `pursue` and 3+ work threads emerge, also do the promotion (move file to folder, create subfolders)
4. Don't touch the `## Original capture` section — that's the historical record

Log the run with the **agent_bus** tool (action `log_event`) so it lands in Activity, and confirm completion to the operator the way you normally do (a note via **Comms**, or hand the result to another agent with **agent_handoff** if there's downstream work). If the verdict produces a concrete next move that someone has to action, open it as a native **Task** (and mirror it via agent_bus action `update_task` / `complete_task` as the work progresses).

---

## Re-grilling (cron pattern)

Schedule recurring re-grills with the **cron** tool. When run on a schedule against existing `status: groomed` + `verdict: pursue` ideas:
- Re-read the file
- Check for fresh news/market shifts in the domain (use the `business-news-monitor` skill output if available)
- If the original analysis still holds → update `groomed` date only
- If something material has shifted (new competitor, regulation change, market shrinkage) → append a `## Re-grill <date>` section noting the shift + impact on verdict
- If verdict needs to change → update frontmatter + add the re-grill section explaining why

Don't rewrite the original analysis — append. The trail is part of the value.
