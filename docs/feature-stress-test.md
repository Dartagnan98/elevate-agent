# Elevate Agent — Full Feature Stress Test (2026-06-03)

Exercises every multi-agent + context feature in one sitting: parallel subagents,
nested agent teams, mixture-of-agents, compaction, and cross-compaction memory —
and doubles as a real-world stress of the fresh-mount blank fix (heavy streaming +
context churn is exactly where blanks used to show).

## Pre-flight (already done this session)
- `config.yaml` toolsets now include: `delegation`, `moa`, `web`, `memory`, `skills`.
- `delegation.max_spawn_depth = 2` (orchestrator→leaf teams), `max_concurrent_children = 4`.
- Backup at `~/.elevate/config.yaml.bak-*`.
- App relaunched so the new toolsets load.
- **Caveat:** model is `gpt-5.5` via Codex. Subagents inherit it, so a big fan-out
  can hit Codex rate limits. If a stage stalls/429s, run stages one at a time, or set
  `delegation.model` to an API-keyed model.

Paste each stage as a single chat message. Watch the activity panel for subagent cards.

---

## Stage 1 — Parallel subagents (fan-out + synthesize)
```
Use delegate_task to spawn 3 subagents IN PARALLEL, each with the web toolset:
  1. Research the 2025 real-estate commission lawsuit (NAR settlement) — 3 bullet takeaways.
  2. Research how AI is changing real-estate lead-gen in 2025 — 3 bullet takeaways.
  3. Research the top 3 CRMs realtors use in 2025 with one differentiator each.
When all three return, synthesize a single 5-bullet brief and label which subagent each point came from.
```
**Pass:** 3 subagent cards run concurrently (not one-after-another), all 3 return,
final brief cites sub-1/2/3. Output streams live the whole time, no blank.

---

## Stage 2 — Agent team (orchestrator → leaf, nested depth 2)
```
Use delegate_task with role "orchestrator" to run ONE subagent that itself spawns
its own leaf subagents. Goal: produce a go-to-market mini-plan for a realtor coaching
offer. The orchestrator should break it into (a) ICP + positioning, (b) 3-channel
acquisition plan, (c) a 4-email nurture outline, delegate each to its own leaf agent,
then assemble them into one document. Return the assembled plan.
```
**Pass:** you see an orchestrator card that itself shows child leaf cards under it
(2 levels deep). If it errors with a depth/limit message, `max_spawn_depth` didn't
take — confirm it's 2 and the app was relaunched.

---

## Stage 3 — Mixture of Agents (multi-model consensus)
```
Use mixture_of_agents on this question: "A realtor has $2,000/mo for marketing and
zero database. Spend it on paid ads, content, or cold outreach — and why?"
Show each agent's independent answer, then the synthesized final recommendation.
```
**Pass:** multiple independent drafts appear, then one merged answer. (If MoA says it
needs more providers/keys, that's a config limit, not the agent — note it and move on.)

---

## Stage 4 — Compaction + memory (the hard one)
This invokes the built-in `compaction-stress-test` skill. Run as ONE message:
```
Run a compaction stress test.

Memorize these facts exactly, ack each as [STORED n]:
1. The launch codeword is "Cascade-Vermillion".
2. The pilot client is Uppercuts Willowbrook.
3. The target CPL is $14.
4. The retainer is $2,500/mo on a 90-day term.
5. The kill rule is 3x target CPL over 7 days.
6. The scale rule is +20% budget when CPA holds for 3 days.
7. My broker split is 80/20.
8. The demo is booked for June 18 at 2pm.

Then force context growth: use read_file to read cli/web/src/pages/ChatPage.tsx
in 1,200-line chunks, sequentially, until you hit a compaction. Print [COMPACTED 1]
when it fires, then keep going to the end of the file.

Finally, WITHOUT scrolling up, recall all 8 facts from durable memory. Print
[RECALL n] CORRECT/LOST for each, state how many compactions fired and whether the
summary was real, and give a scorecard: compactions / facts correct / facts lost.
```
**Pass:** `[STORED 1..8]` → reads stream → `[COMPACTED 1]` → `[RECALL 1..8]` all
CORRECT → scorecard 8/8. Crucially: **output stays live across the compaction**
(this is the path that used to blank). If any fact comes back LOST, memory didn't
persist it — that's a real finding.

---

## Stage 5 — Combined torture (multi-agent UNDER a full context)
Run this immediately after Stage 4, in the SAME chat (context is already huge):
```
Now, while this conversation is large, delegate_task 3 parallel subagents to each
draft one cold-outreach DM (realtor voice) for: a FSBO seller, an expired listing,
and a past client. Then merge into a 3-message sequence. After they finish, tell me
the launch codeword and the demo date from memory.
```
**Pass:** subagents spawn fine despite the big parent context, sequence assembles,
AND it still recalls "Cascade-Vermillion" + "June 18 2pm" (memory survived compaction
+ delegation). No blank, no frozen output.

---

## Stage 6 — Blank-fix regression (UI, not the agent)
While Stages 1–5 are producing long transcripts:
- Click between this chat and 2–3 other chats in the sidebar, fast, several times.
- Quit + reopen the app with this chat active.
**Pass:** transcript never goes blank and never partially drops. (Diagnostics are
still wired — `tail -f ~/.elevate/logs/blank-trace.log`; you should see only
`blocked ...` / `recovered ...`, never `LIST WIPED`.)

---

## Scorecard to fill in
| Feature | Pass? | Notes |
|---|---|---|
| Parallel subagents (S1) | | concurrent? synthesized? |
| Agent team / nesting (S2) | | 2 levels deep? |
| Mixture of agents (S3) | | multiple drafts + merge? |
| Compaction (S4) | | compactions fired / live output? |
| Memory across compaction (S4/S5) | | facts correct __/8 |
| Subagents under big context (S5) | | spawned ok? |
| Blank fix (S6) | | any LIST WIPED in log? |
