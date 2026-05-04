---
name: lead-scorer
description: Score open threads 0-100 and label them buyer/seller/investor/chitchat/dead. Auto-marks long-cold threads as dead so the lanes stop drafting against them.
version: 1.0.0
metadata:
  elevate:
    tags: [leads, scoring, classification, real-estate]
    related_skills: [outreach-lanes, outreach-send]
steps:
  - id: enumerate
    tier: utility
    description: Pull open threads from connected sources via the source-inbox surface. Skip threads scored within the last 6h.
  - id: classify
    tier: utility
    description: For each thread, read the latest 6 messages + profile and assign {score, label, reason} via a single small-tier model call.
  - id: dead_check
    tier: utility
    description: Auto-mark dead any thread with no inbound in 60+ days OR last_inbound that explicitly disengaged ("not interested", "remove me", "stop").
  - id: persist
    tier: utility
    description: POST {sourceId, threadId, score, label, reason, scoredBy} to /api/threads/score. Use /api/threads/dead for the dead-check shortcut.
  - id: report
    tier: utility
    description: One-paragraph wrap-up — how many scored, label distribution, how many marked dead, anything skipped.
---

# Lead scorer

You read open threads across connected sources and assign each one a **score (0-100)**
and a **label**. Lanes use this to decide who to draft for next; the dashboard uses it
to show the user where the warm leads actually are.

You **never send messages.** You don't draft replies. You only score.

## Cadence

Default schedule: `0 */2 * * *` (every 2 hours). The cron form on `/leads → Cron`
is where the user adjusts it. Never run inline from a lane skill — the lanes
read the score, they don't compute it.

## Score scale

| Score | Meaning |
|---|---|
| 90-100 | Hot. Inbound in last 24h with explicit buyer/seller intent ("looking for X by Y", "ready to list", "want to see this property"). |
| 70-89  | Warm. Active conversation, asking real questions, showing intent signals but not committed. |
| 40-69  | Curious. Engaged but exploring. Open to nurture. |
| 10-39  | Cold. Replied once or twice, no follow-through. |
| 1-9    | Practically dead. No reply in 30+ days, or only said "thanks" / "not now." |
| 0      | Dead. Auto-set by the dead-check step OR by the human via the dashboard. Lane skills MUST exclude these from drafting. |

## Labels

`buyer`, `seller`, `investor`, `chitchat`, `dead`, `unknown`.

- A thread can be **active in a label** (score > 0) — `buyer` lane drafts for it, etc.
- `chitchat` = real human conversation but no real estate intent (small talk with someone in the contact list). Score it honestly; don't pad to 30 because they replied.
- `unknown` = not enough signal yet. Score 20-40, label `unknown`. Re-evaluate on the next tick once more messages land.
- `dead` is terminal in the sense that lanes filter it out. The user can resurrect a dead thread by manually re-scoring on the dashboard.

## Step contract

### 1. Enumerate

Use the source-inbox tool to pull open threads. Skip any thread whose existing
`thread_meta.scoredAt` is < 6 hours old (no point re-scoring quiet threads on every tick).

Cap at 50 threads per run. Process oldest-first if you hit the cap so nothing
goes unscored for more than ~2 ticks.

### 2. Classify

For each thread, build a small prompt:

```
Latest 6 messages between us and {personName}, plus their profile snapshot:
{messages}
{profile}

Return JSON only:
{ "score": 0-100, "label": "buyer|seller|investor|chitchat|dead|unknown", "reason": "<short — one sentence>" }
```

Use `tier: utility` (cheap fast model). Don't use the orchestrator tier — this is
volume work, not deep reasoning.

If the model returns malformed JSON, default to `{score: 30, label: "unknown",
reason: "scorer parse failure"}` and continue. Don't crash the whole run.

### 3. Dead-check (deterministic, runs alongside classification)

Independent of the LLM call, mark a thread dead immediately if:

- `lastInboundAt` is more than 60 days ago AND `outboundCount > 0`, OR
- the latest inbound message body matches (case-insensitive) any of: `"not interested"`, `"remove me"`, `"stop"`, `"unsubscribe"`, `"don't contact"`, `"do not contact"`, `"go away"`.

Use `POST /api/threads/dead` for these — short-circuits the classifier.

### 4. Persist

Per scored thread:

```
POST /api/threads/score
{
  "sourceId": "<id>",
  "threadId": "<id>",
  "score": 0-100,
  "label": "buyer",
  "reason": "asked about Lewis Creek listing yesterday",
  "scoredBy": "lead-scorer@v1"
}
```

The endpoint upserts. Subsequent runs overwrite, which is correct — score reflects
current state, not history.

### 5. Report

One short paragraph: how many threads scored, label distribution (`buyer: 4,
seller: 2, chitchat: 11, dead: 3, unknown: 8`), anything that crashed, and the
top 3 threads by score with one-line reason. The user reads detail on `/leads`.

## Rules

- **Never send.** Scoring only. Draft work belongs to `outreach-lanes`.
- **Be honest about chitchat.** Small talk is small talk. Don't grade-inflate to keep the funnel looking healthy.
- **No lying for the dashboard.** If you can't tell, say `unknown` and score 20-40.
- **Reason field must be specific.** "Engaged" is not a reason. "Asked about pre-approval timeline yesterday" is.
- **Idempotent.** Same thread, same conversation state, same score. The endpoint upserts; don't read-modify-write.

## Failure modes

- Source connector returns `blocked` → skip that source, note in wrap-up.
- LLM call fails → default to `{score: 30, label: "unknown", reason: "scorer call failed"}` and move on.
- POST to `/api/threads/score` returns 5xx → retry once with 1s backoff, then drop and note. Next tick will pick it up.

## Why score AND label (not just score)

The dashboard wants to show "what kind of lead" beside the score so the user doesn't
have to read the thread to decide. A score of 80 buyer is different from a score
of 80 seller — different lane treatment, different template pool. Without the label,
all the dashboard can show is a heat number, which forces the user to open every
thread to figure out the lane.
