---
name: "market-stats-watcher"
description: "Watches Gmail for the monthly AOIR Market Statistics email, clicks into InterLink for Okanagan/Shuswap and Kamloops & District stats, extracts all data, and saves as markdown files organized by region and month. Trigger on: \"pull market stats\", \"market stats\", \"check for new stats\", \"AOIR stats\", or runs automatically on a monthly cron when the email arrives."
category: "real-estate-marketing"
access:
  entitlement: "real_estate_cma"
---

# Market Stats Watcher

**Client**: the realtor, AOIR Realtor
**Trigger**: "pull market stats" or runs on monthly cron
**Output**: Markdown files under `market-stats/<region>/` for ALL four regions: okanagan-shuswap, kamloops-and-district, kootenay, south-peace-river

## Overview

The Association of Interior REALTORS sends a monthly email with links to regional market statistics on InterLink. This skill watches for that email, extracts the links, opens them via Playwright (using the same AOIR login as the CMA skill), pulls all stats data, and saves it as organized markdown files.

The CMA Breakdown skill reads the latest month's stats file before making pricing decisions, giving it real market context (absorption rate, DOM averages, inventory levels) beyond what a small comp search reveals.

## Email Details

- **Subject pattern**: `Market Statistics - [Month] [Year] Member Stats Release`
- **From**: Association of Interior REALTORS® via gmail.mcsv.net
- **Frequency**: Monthly (typically first week of month, stats are for previous month)
- **Example**: "Market Statistics - February 2026 Member Stats Release" sent Mar 4, 2026

## Email Contents

The email contains:
- "[Month] [Year] Market Statistics Member Resources" heading
- "InterLink" link to the stats portal
- Region buttons (links) -- pull ALL regions:
  - **Okanagan/Shuswap** -- PULL
  - **Kamloops & District** -- PULL
  - **Kootenay Region** -- PULL
  - **South Peace River** -- PULL

## Folder Structure

```
market-stats/
├── okanagan-shuswap/
│   ├── 2026-01.md
│   ├── 2026-02.md
│   └── 2026-03.md
└── kamloops-and-district/
    ├── 2026-01.md
    ├── 2026-02.md
    └── 2026-03.md
```

Each file is named `YYYY-MM.md` where the month is the stats month (not the email date). So February 2026 stats email (sent March 4) saves as `2026-02.md`.

## Execution Flow

### Step 1: Find the Email

**Via gws CLI (automated):**
```bash
gws gmail users.messages.list --userId me --q "subject:'Market Statistics' subject:'Member Stats Release' newer_than:7d"
```

**Via Gmail MCP tool (manual trigger):**
Search Gmail for: `subject:"Market Statistics" subject:"Member Stats Release"`
Get the most recent one. Read the full message to extract the HTML body.

### Step 2: Extract Region Links

Parse the email HTML body for the two region button links:
- Find link containing "Okanagan" or "okanagan" in the button text
- Find link containing "Kamloops" or "kamloops" in the button text
- These are typically links to InterLink (interiorbc.ca or similar)

### Step 3: Open InterLink via Playwright

The InterLink stats pages require AOIR login -- same credentials as Xposure (MLS_USERNAME / MLS_PASSWORD in .env).

**Click path:**
1. Open the Okanagan/Shuswap link in Playwright browser
2. If redirected to login page (iam.interiorbc.ca), login with MLS creds
3. Wait for stats page to load
4. Extract all visible stats data from the page
5. Screenshot to `market-stats/screenshots/YYYY-MM-okanagan.jpg`
6. Repeat for Kamloops & District link

### Step 4: Extract Stats Data

From each region's stats page, extract:
- **Total active listings** (current inventory)
- **Total sold listings** (for the month)
- **Average days on market** (DOM)
- **Average sale price**
- **Median sale price**
- **Sales-to-active ratio** (if shown)
- **New listings** (for the month)
- **Benchmark price** (if shown)
- **Year-over-year changes** (if shown)
- **Breakdown by property type** (Single Family, Townhouse, Condo, etc.)
- Any narrative/commentary from the economics department

Also look for:
- Infographics (screenshot these)
- Sub-division breakdowns (Sahali, Aberdeen, Brocklehurst, etc.)
- Price range distribution

### Step 5: Save as Markdown

Write the extracted data to the appropriate markdown file.

**File format:**
```markdown
# [Region] Market Statistics - [Month] [Year]

*Source: Association of Interior REALTORS® Monthly Stats Release*
*Extracted: [extraction date]*

## Summary

| Metric | Value | YoY Change |
|--------|-------|------------|
| Active Listings | X | +/-X% |
| Sold Listings | X | +/-X% |
| New Listings | X | +/-X% |
| Average DOM | X days | +/-X |
| Average Sale Price | $X | +/-X% |
| Median Sale Price | $X | +/-X% |
| Sales-to-Active Ratio | X% | -- |
| Months of Inventory | X | -- |

## Market Classification

Based on months of inventory:
- 0-4 months: Seller's Market
- 4-6 months: Balanced Market
- 6+ months: Buyer's Market

**Current: [classification]**

## By Property Type

### Single Family Detached
| Metric | Value |
|--------|-------|
| Active | X |
| Sold | X |
| Avg Price | $X |
| Avg DOM | X |

### Townhouse
[same format]

### Condo/Apartment
[same format]

## Sub-Area Breakdown (if available)

### Sahali
[stats]

### Aberdeen
[stats]

[etc.]

## Commentary

[Any narrative from the economics department or media release]

## Raw Data Notes

[Any additional data points, footnotes, or caveats]
```

### Step 6: Verify and Log

- Confirm both files were written
- Log the extraction to `market-stats/pull-log.json`:
```json
{
  "pulls": [
    {
      "date": "2026-03-21",
      "statsMonth": "2026-02",
      "emailSubject": "Market Statistics - February 2026 Member Stats Release",
      "regions": ["okanagan-shuswap", "kamloops-and-district"],
      "success": true
    }
  ]
}
```

## How CMA Skill Uses This Data

The CMA Breakdown skill reads the latest markdown file for the relevant region before generating the pricing recommendation:

1. Determine which region the subject property is in (Kamloops vs Okanagan)
2. Read `market-stats/[region]/` and find the most recent YYYY-MM.md file
3. Extract: months of inventory, average DOM, market classification, average sale price
4. Feed into absorption rate analysis and pricing strategy
5. Reference in the evaluation email: "Based on the most recent AOIR market statistics for [region] ([month] [year]), there are currently X months of inventory, indicating a [buyer's/seller's/balanced] market."

## Cron Setup

Run monthly, ~5 days after month end (to give AOIR time to send the email):

```bash
# Check for new stats email on the 6th of every month at 10am
0 10 6 * * claude -p "pull market stats"
```

Or set up a Gmail watch via gws:
```bash
gws gmail +watch --query "subject:'Market Statistics' subject:'Member Stats Release'" --format ndjson
```

## Dependencies

- Playwright (same as CMA skill)
- AOIR login credentials (MLS_USERNAME / MLS_PASSWORD in .env)
- Gmail access via gws CLI or Gmail MCP tool
- sharp (for screenshot processing, already installed for CMA)

## Error Handling

- If email not found: log "no new stats email" and exit cleanly
- If InterLink login fails: try MFA via gws, then fail gracefully
- If stats page doesn't load: screenshot the error page, log it, continue to next region
- If data extraction is partial: save what was extracted, note missing fields in the markdown
- Never block. Never stop. Save partial data and report.

## Lessons (MANDATORY -- read before every run, write after every correction)

**File: `.claude/skills/market-stats-watcher/lessons.md`**

**Before every run:**
1. Read `.claude/skills/market-stats-watcher/lessons.md` -- apply EVERY lesson. No exceptions.

**After every run (success or failure):**
1. If selectors changed on InterLink, log the new working selector
2. If email pattern changed, log the new subject/sender pattern

**When the realtor corrects output:**
1. Immediately append to `.claude/skills/market-stats-watcher/lessons.md`
2. Format: `[date] | [what went wrong] | [the rule to follow]`
3. This is not optional. Every correction compounds.

## Run-State Handoff

This is a daemon-style workflow, not a chatty agent workflow. Every run should
write a compact handoff:

`market-stats/run-state/<YYYY-MM>.handoff.json`

Required fields:

- `status`: done, partial, failed, or skipped.
- `email_found`: sender, subject, message id, and date.
- `regions`: one entry for each region with extracted file path and missing fields.
- `outputs`: markdown files written under `market-stats/<region>/`.
- `risks`: selector drift, missing links, MFA, partial extraction.
- `next`: whether CMA context can trust this month's stats.
