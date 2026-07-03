# Skill library doctrine

Canonical source for skill `description` formatting and the shared doctrine
blocks pasted into skill bodies. `tests/skills/test_skill_library_format.py`
enforces this file: the doctrine blocks below are byte-compared against the
skills that must carry them. **Edit a block here and re-paste it everywhere it
appears — never edit a pasted copy in place.**

## Why this exists

Skill descriptions are the routing surface. Three consumers read them, each with
a different truncation:

- Cron on-demand index — 180 chars (`cron/scheduler.py`)
- Interactive system-prompt skills index — 60 chars (`agent/skill_utils.py`)
- `skills_list` tool — 1024 chars (`tools/skills_tool.py`)

A description whose useful signal sits past char 60/180 routes badly on the
tightest surface. Before this sweep, 100 of 186 descriptions ran past 180 chars
and truncated mid-sentence. The format below front-loads the discriminating
signal so it survives every cut.

## Description format

```
<Zone A: imperative capability clause — target <=55 chars, hard <=90>. Use when
<Zone B: 2-5 verbatim user phrases in quotes and/or situations; the word "Use "
must start within the first 120 chars>. Not for <Zone C: anti-trigger> — use
<sibling-skill> instead[; not for <second anti-trigger>]. <optional input/
precondition note>
```

Budgets: total description <= 950 chars; the whole frontmatter block <= 3500
bytes (the frontmatter read window is 4000 bytes). Zone A is what the 60-char
surface shows, so lead with the discriminating noun/verb, not boilerplate.

Worked example (`real-estate-admin/listing-outreach`):

> Draft seller outreach tuned to a listing's condition. Use when the realtor
> says "message the seller", "nudge my listing clients", or a listing's DOM or
> price position warrants a check-in. Not for buyer-lead texting — use
> outreach-lanes; not for scheduled seller report packets — use seller-updates.

`triggers:` frontmatter is dead metadata (no consumer) — leave existing ones
untouched, do not add new ones; fold trigger phrases into the description.

## Name normalization

Frontmatter `name` must equal the skill directory name. One rename in this
sweep: `creative/creative-ideation` (`name: ideation` -> `name:
creative-ideation`) because agent loadouts reference `creative-ideation` and the
cron index keys by frontmatter name. Frozen exceptions (no loadout references
them; renames carry a sync-manifest cost, so they stay as-is and the lint test
pins the set so it cannot grow):

```
ALLOWED_NAME_MISMATCHES = {
  "lm-evaluation-harness": "evaluating-llms-harness",
  "vllm": "serving-llms-vllm",
  "audiocraft": "audiocraft-audio-generation",
  "segment-anything": "segment-anything-model",
  "trl-fine-tuning": "fine-tuning-with-trl",
}
```

## Autonomy-rules append (souls)

Appended verbatim (append-only, single leading space) to every agent's
`autonomy_rules` in `elevate_cli/agent_hub.py` so stored 1.2.60 souls remain
strict prefixes and self-upgrade via the reconcile:

> Before interrupting the user with a question, try to answer it yourself from the CRM, deals, threads, files, and memory; ask only when the answer genuinely belongs to the user (approvals, preferences, private facts), batch related questions into a single ask, and otherwise proceed on the most reasonable interpretation and state the assumption.

---

# Doctrine blocks

Each block is pasted verbatim (byte-for-byte) at the END of every target skill's
`SKILL.md` body. The lint test whitespace-normalizes line-by-line, so keep the
line breaks stable.

## BLOCK: search-doctrine

Targets: `research/arxiv`, `research/blogwatcher`, `research/llm-wiki`,
`research/polymarket`, `research/research-paper-writing`,
`agent-ops/web-research`, `agent-ops/autoresearch`, `agent-ops/source-collection`,
`agent-ops/signal-scoring`, `real-estate-admin/market-stats-watcher`.

```markdown
## Search doctrine

- Internal first: possessives and client or deal names ("my listing", "the Hendersons", "that Kamloops buyer") mean CRM, deals, threads, and memory BEFORE any web search. The web is for the outside world; this box already knows the inside one.
- Queries are 1-6 words. Start broad, then narrow with one qualifier at a time. Never rerun a near-identical query — if results repeat, change the angle or the tool, not the phrasing.
- Search results are pointers, not sources. Fetch the full page before citing or acting on anything that matters.
- Scale effort to the ask: a single fact is 1 call; a comparison or survey is 3-5; a deep dive is 5-10 with cross-source triangulation. Stop when new results only repeat what you already have.
```

## BLOCK: fair-housing

Targets: `real-estate-admin/marketing`, `real-estate-admin/listing-outreach`,
`real-estate-admin/listing-build`, `real-estate-admin/marketing-landing`,
`real-estate-admin/seller-updates`, `real-estate-admin/outreach`,
`real-estate-admin/relisting`, `social-content-engine`, `social-media/xurl`,
`outreach-lanes`, `lead-scorer`, `creative/creative-ideation`.

```markdown
## Fair housing & copy boundaries

- Fair housing is absolute: never write, imply, or optimize copy around protected classes (race, color, religion, sex, disability, familial status, national origin, or local additions such as age or source of income). Describe the property and its features, never the neighbors or "who this home is for." "Great for young families" fails; "4 beds, fenced yard, two blocks to the elementary school" passes.
- Targeting and scoring follow the same line: no audience filters, lead scores, or send/skip decisions keyed on protected classes or their proxies.
- Never lift another agent's listing copy, photos, or brand phrasing. Other listings are data (facts, price, days on market), not copy to reuse. Write from the property record and the owner's materials; when quoting a document such as an inspection, attribute it.
```

## BLOCK: provenance

Targets: `cma`, `real-estate-admin/cma-generator`,
`real-estate-admin/market-stats-watcher`, `real-estate-admin/deal-matcher`,
`real-estate-admin/property-lookup`, `real-estate-admin/offer-review`,
`real-estate-admin/seller-package`, `real-estate-admin/closing-admin`.

```markdown
## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
```

## BLOCK: draft-pairs

Targets: `outreach-lanes` (new section after `## Rules`) and
`real-estate-admin/outreach/references/voice-and-drafting.md` (appended).

```markdown
## Draft examples — write the GOOD column

**Memory voice.** CRM history and ingested notes are context, never citations. Write like someone who simply knows the client.
- BAD: "I saw in my notes that your daughter starts at TRU in September, and my records show you were looking at 3-beds near Sahali."
- GOOD: "how's the TRU countdown going? still thinking Sahali for the fall, or has the search wandered?"

**No CTA pivot.** Reply to what they actually sent; earn the ask or skip it.
- Lead: "haha yeah that storm knocked our fence right over"
- BAD: "Sorry to hear about the fence! By the way, do you have 15 minutes this week for a quick call about your home search?"
- GOOD: "brutal haha, half the fences on our street went too. patchable or full rebuild?"

**Sensitive gating.** Divorce, death, finances, health: never surface it first, even helpfully. Let them raise it; then respond with care and keep it out of anything marketing-flavored.
- BAD: "Since the divorce is finalizing next month, want me to line up some 2-bed condos in your new budget?"
- GOOD (only after they raised it): "that's a lot to carry. whenever you feel like looking, I can quietly pull a few options — no rush from me."
```

---

# Tier 1 — routing-critical (66 skills)

The union of the 7 `DEFAULT_AGENT_DEFS` loadouts and `SHARED_AGENT_SKILLS`.
Every one appears in some agent's cron on-demand index, so descriptions here are
hand-crafted first.

agent-ops: activity-channel, agent-management, approvals, auto-skill,
autoresearch, brief-generation, calendar-management, catalog-browse, comms,
cron-management, delegation-matrix, delivery-routing, email-triage,
env-management, evening-review, event-logging, goal-management,
guardrails-reference, heartbeat, human-tasks, knowledge-base, memory,
morning-review, oauth-rotation, onboarding, pending-items-summary,
prompt-engineering, relationship-review, signal-scoring, system-diagnostics,
tasks, weekly-review, worker-agents.

real-estate-admin: admin-agent, admin-result-writer, closing-admin,
cma-generator, deal-matcher, digisign, gmail-doc-router, listing-build,
listing-outreach, lofty-crm-client-contacts, market-stats-watcher, marketing,
marketing-landing, offer-review, photo-cleanup, property-lookup, seller-updates,
signing-package, skyslope-sync, subject-removal, webforms.

creative: architecture-diagram, baoyu-infographic, creative-ideation, humanizer.
productivity: nano-pdf, powerpoint.
real-estate: surface-heartbeat, theta-wave.
top-level: cma, lead-scorer, outreach-lanes, social-content-engine.
