---
name: social-content-engine
description: Weekly real-estate social content engine. Pulls full native metrics from every connected platform (IG, TikTok, YouTube Shorts, FB, LinkedIn), researches what's trending in real estate via last30days, reads inbox/CRM signals for grounded ideation, and writes 5-10 approval-gated content ideas to the /social-media queue. Runs weekly via cron.
version: 0.1.0
metadata:
  elevate:
    tags: [social-media, content, real-estate, weekly, approval-gated]
    related_skills: [last30days, outreach-lanes]
steps:
  - id: pull_metrics
    tier: utility
    description: Fetch full native metric payloads for last 30 days of posts across every connected platform. Append to social-metrics.jsonl.
  - id: aggregate
    tier: utility
    description: Compute hook rate, hold rate, engagement rate, follower-growth-per-post. Rank top performers. Write weekly snapshot.
  - id: research_trends
    tier: research
    description: Call last30days research scoped to real-estate trends in the client's market (city, listing type, audience).
  - id: read_signals
    tier: utility
    description: Pull recent inbox themes (last 14d), CRM activity (new listings, price changes, status moves), and lead asks.
  - id: generate_ideas
    tier: draft
    description: Compose 5-10 ideas with hook + format + best post time + reasoning, grounded in metrics + trends + signals.
  - id: queue_approvals
    tier: utility
    description: Write each idea as task_type=content_idea to tasks.jsonl. Human approves on /social-media.
  - id: log_run
    tier: utility
    description: Record run summary (metrics pulled, ideas generated, sources used) to social-runs.jsonl for review.
---

# Social Content Engine

You run the weekly content engine for a real estate agent. Your job is to look at what's actually performing on their accounts, what's happening in their market and on social right now, and what their leads are asking about — then propose a small queue of content ideas the human can approve, edit, or reject on `/social-media`.

You **never auto-publish**. You draft ideas. The human approves and schedules.

## Inputs

The cron prompt fires this skill weekly (Monday 7am Pacific). Optional args:

- `lookback` — days of post history to pull. Default: `30`.
- `idea_count` — target idea count. Default: `7` (range 5-10).
- `force_refresh_metrics` — if true, re-pull even if last fetch < 24h ago.

## Workflow

### 1. Pull metrics

For each connected platform (Instagram, TikTok, YouTube, Facebook, LinkedIn), call the matching native fetcher script:

```
python3 scripts/instagram_insights.py --lookback 30
python3 scripts/tiktok_insights.py --lookback 30
python3 scripts/youtube_analytics.py --lookback 30
python3 scripts/facebook_insights.py --lookback 30
python3 scripts/linkedin_insights.py --lookback 30
```

Each fetcher reads its OAuth token from Composio, pulls every post in the lookback window, and writes the full metric payload (one JSON line per post per pull) to:

```
~/.elevate/state/<workspace>/social-metrics.jsonl
```

If a platform isn't connected, the fetcher exits 0 with a `not_configured` line — keep going.

### 2. Aggregate + rank

```
python3 scripts/aggregate.py --lookback 30
```

Reads social-metrics.jsonl, normalizes each platform's native metric vocabulary into a common shape, and computes per-post:

- **engagement rate** = (likes + comments + saves + shares) / reach
- **save rate** = saves / reach (IG signal of high-intent content)
- **hook rate** = plays / impressions (only meaningful when both are exposed and distinct, i.e. Facebook video and YouTube long-form — null on autoplay platforms)
- **hold rate** = avg watch time / duration (videos with both fields)

Outputs `~/.elevate/state/<workspace>/social-snapshot.json` with: top 10 posts cross-platform, bottom 10, per-platform top/bottom 5, format breakdown (Reels vs Feed vs Carousel vs Short etc), week-over-week deltas, account-level totals (follower count, account reach).

### 3. Research trends

Invoke the bundled `last30days` research skill scoped to real estate:

```
last30 real estate content trends [city] [market segment]
```

Where `[city]` and `[market segment]` come from the workspace profile. If the agent has a niche (luxury, first-time buyers, investment property, rural acreage), append it.

Save the research output to `~/.elevate/state/<workspace>/social-research/<YYYY-MM-DD>.md`.

### 4. Read signals

```
python3 scripts/read_signals.py --lookback 30 --max-questions 30 --max-events 50
```

Returns JSON with:

- `inbound_questions` — recent inbound messages from real (non-automated) senders that look like questions, tagged with channel + topics matched
- `lead_events` — CRM-synced events in window (lead created, stage moved, hot score)
- `hot_topics` — top topic hits across the window (first-time-buyer, pre-approval, condo-docs, market-trends, etc) using a real-estate keyword universe
- `topic_counts` — full counter for the window
- `sources_scanned` — every connected source the script saw

The script uses the same `_is_automated_sender_record` filter as `/leads` so newsletters and noreply blasts don't pollute the signal set.

### 5. Generate ideas

Produce 5-10 ideas. Each idea has:

```json
{
  "format": "Reel | Carousel | Static | Story | Short | Long video | Tweet thread",
  "platform": ["instagram", "tiktok"],   // 1-3 platforms it fits
  "hook": "First 3 seconds verbatim, written for hold-rate.",
  "concept": "What the post is about in plain language.",
  "outline": ["Beat 1", "Beat 2", "Beat 3"],
  "best_post_time": "ISO-8601 local time (use historical engagement-by-hour data)",
  "grounded_in": {
    "metric": "Optional: top-performing past post that informed this",
    "trend": "Optional: last30days finding that informed this",
    "signal": "Optional: lead question or CRM event that informed this"
  },
  "reasoning": "1-2 sentences on why this should perform."
}
```

Quality rules:

- Every idea cites at least one of `metric`, `trend`, or `signal`. No idea ships unsourced.
- Match the agent's voice from `~/.elevate/SOUL.md` (or workspace voice profile). If no SOUL.md exists, default to plain, conversational, no real estate cliches.
- Avoid topics already covered by posts in the last 14 days (check social-metrics.jsonl for recent post captions).
- Diverse formats: don't propose 7 Reels in a row. Aim for a mix.
- Compliance: no fair-housing-violating language, no specific commission claims, no guaranteed-outcome promises.

### 6. Queue approvals

For each idea, call:

```
python3 scripts/queue_idea.py \
  --platform <instagram|tiktok|youtube|facebook|linkedin> \
  --format <reel|short|feed|carousel|story|video|text> \
  --hook "<one-line opener>" \
  --concept "<2-3 sentence summary>" \
  --outline "<beat 1>" "<beat 2>" "<beat 3>" \
  --best-post-time "<e.g. Tuesday 7pm Pacific>" \
  --target-audience "<who>" \
  --grounded-in-metric "<post_id + key metric>"  # OR
  --grounded-in-trend  "<one-line trend reference>" # OR
  --grounded-in-signal "<inbox/CRM signal reference>" \
  --reasoning "<why this lands>"
```

The script enforces the "must cite at least one of metric/trend/signal" rule and writes the task to `data/sources/social/tasks.jsonl` with `task_type=social_post_idea`, `approval_required=true`, `target_ui_surfaces=["Social Media", "Approvals"]`. The `/social-media` page reads these and renders them in the AI Idea Approval Queue.

### 7. Log run

Append one line to `~/.elevate/state/<workspace>/social-runs.jsonl`:

```json
{
  "run_at": "<iso>",
  "lookback_days": 30,
  "platforms_pulled": ["instagram", "tiktok"],
  "platforms_skipped": ["youtube", "facebook", "linkedin"],
  "post_count": 47,
  "ideas_generated": 7,
  "research_topics": ["winnipeg real estate trends", "first time buyer content"],
  "errors": []
}
```

## Wrap-up

Tell the user, in one short paragraph: which platforms pulled, how many posts analyzed, how many ideas queued, and any platform that was skipped (not connected, rate limited, or auth failed). Nothing more. Detail lives on `/social-media`.

## Rules

- **Never publish.** Ideas are ideas until the human approves and schedules.
- **Never invent metrics.** If a platform didn't return a number, the idea cites trends or signals only — never made-up performance figures.
- **Real estate scope.** This skill is wired for real estate agents. No general-purpose content advice.
- **Postal-code geo.** When proposing local content, reference the agent's actual served postal codes from the workspace profile, not arbitrary radius circles.
- **No fair-housing violations.** Never generate content that targets/excludes protected classes. Never reference school ratings as a buying factor. Never use neighborhood demographics as selling points.

## Failure modes

- If 0 platforms are connected, exit cleanly with a Telegram-friendly note: "No social platforms connected — connect at least one in Settings → Channels and re-run."
- If metric fetchers fail for ALL connected platforms, fall back to ideas grounded in `trend` + `signal` only. Note the metric outage in the run log.
- If `last30days` research times out (> 8 min), proceed with whatever it returned and note the partial result.
- If idea generator produces fewer than 3 viable ideas after dedup against recent posts, surface that as an explicit message — don't pad with junk.

## First-run backfill

On the first run for a workspace, set `--lookback 90` to pull a richer baseline. Subsequent runs use 30. The aggregator uses the full 90d window for percentile ranking but the 30d window for "what's hot right now."
