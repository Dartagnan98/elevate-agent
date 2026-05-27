# Xposure per-buyer engagement -- field inventory

Goal: extend the `xposure-pcs` connector and `buyer-brief` enrichment to
capture which listings each buyer is viewing, how many times, and when.

## How to reach the data (Playwright path)

1. Navigate to `https://interiorrealtors.xposureapp.com/portal/air/Contacts`
2. For each buyer row, click `a.contact-detail-link` (the name link).
   This loads the buyer profile at `/portal/air/ManageClients` with tabs:
   General | PCS | Timeline | Meet.
3. On the PCS tab the "All Searches" table lists every saved search.
   Each row's View column is a `<a>` with onclick:
   `javascript:manageClients.manageResults('<SEARCH_ID>', '1')`.
4. Invoking `manageClients.manageResults(searchId, '1')` opens a **NEW WINDOW**
   at `https://interiorrealtors.xposureapp.com/pcs/air/DoLogin`. Title:
   "Private Client Services™ (PCS)". This is a "one-way mirror" -- the
   client's exact PCS view, read-only for the agent.
5. The new window dump is what we scrape.

## Exposed data on the Client View page

### Per-buyer / per-search summary (top of page)
- **Last Client Access**: full timestamp (e.g. `May 22/26 2:44PM Pacific time`)
- **Results**: total listings matched (e.g. 140)
- **Favorites**: count (e.g. 2)
- **Removed**: count (e.g. 36)
- **Queue**: count of pending-send listings
- Tabs to other views: Timeline, Meet

### Per-listing card (one per matched listing)
Every listing card has a status line directly above the address:

| State string                       | Meaning                          |
| ---------------------------------- | -------------------------------- |
| `New No Views`                     | newly added match, no views yet  |
| `PC No Views`                      | previously compared, no views    |
| `No Views`                         | older, never opened              |
| `Viewed <Mon DD/YY> N Views`       | opened N times, last on that day |

Fields available per card:
- **mls_id** (e.g. `10388863`)
- **address** (street + city + area + sub-area)
- **major_area** / **minor_area**
- **list_price** (string, `$524,900.00`)
- **status** (`Active`, etc)
- **beds**, **baths**
- **year_built**
- **style** (`Bi-Level`, `Bungalow`, `Rancher`, ...)
- **type** (`Single Family - Detached`, etc)
- **lot_size**, **fin_area**, **ensuites**, **PID**, **DOM**, **parking**, **taxes**
- **features** (comma list)
- **description** (first paragraph)
- **photo_count**
- **view_status** -- parsed from the status string above
- **view_count** -- integer (defaults 0)
- **last_viewed_at** -- date or null

### Sort options (proof the fields exist)
- Last Viewed Ascending / Descending
- Number of views Ascending / Descending
- Last Modified, Address, Current Price, Major Area, Minor Area, Beds,
  Baths, Lot Area, Year Built, MLS #

Sorting by `Last Viewed Descending` gives us the most recently engaged
listings first -- ideal scrape order.

## Proposed schema (PG migration 0014_pcs_listing_views.sql)

```sql
CREATE TABLE IF NOT EXISTS pcs_listing_views (
    contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    search_id       TEXT NOT NULL,        -- xposure saved-search id
    mls_id          TEXT NOT NULL,
    address         TEXT,
    major_area      TEXT,
    minor_area      TEXT,
    list_price_cents BIGINT,
    status          TEXT,
    beds            INTEGER,
    baths           INTEGER,
    year_built      INTEGER,
    style           TEXT,
    property_type   TEXT,
    dom_days        INTEGER,
    view_count      INTEGER NOT NULL DEFAULT 0,
    last_viewed_at  DATE,
    view_state      TEXT,                 -- 'new' | 'pc' | 'older' | 'viewed' | 'favorite' | 'removed'
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contact_id, search_id, mls_id)
);

CREATE INDEX idx_pcs_listing_views_contact ON pcs_listing_views(contact_id);
CREATE INDEX idx_pcs_listing_views_active ON pcs_listing_views(contact_id, last_viewed_at)
    WHERE view_count > 0;
```

Also extend `pcs_buyers` with summary counts:

```sql
ALTER TABLE pcs_buyers
    ADD COLUMN IF NOT EXISTS results_count       INTEGER,
    ADD COLUMN IF NOT EXISTS favorites_count     INTEGER,
    ADD COLUMN IF NOT EXISTS removed_count       INTEGER,
    ADD COLUMN IF NOT EXISTS queue_count         INTEGER,
    ADD COLUMN IF NOT EXISTS last_client_access  TIMESTAMPTZ;
```

## Brief enrichment additions

Current brief:
> `$800k-$1.20M, 3+ bed, Aberdeen, last search 6d ago. 14 searches in 90d`

After listing-view scrape:
> `$800k-$1.20M, 3+ bed, Aberdeen. Last login May 22 (2:44pm). 140 matches / 2 favorites / 36 removed. Top views: 11 Jasper Dr (3x), 376 Hollywood Cres (2x).`

## Outreach triggers (cron job #23)

The activity flagger can now fire on:
1. **Engagement spike** -- view_count diff ≥ 3 on any single listing in 7d
2. **Repeat-view threshold** -- ≥ 5 views total on same MLS# in 14d
3. **Favorite added** -- favorites_count > previous favorites_count
4. **Returned from dormant** -- last_client_access fresh after 30d+ gap
5. **Specific listing returned** -- viewer looked at listing X then came
   back to it days later (top signal in real estate)

## Scraper strategy

Per buyer with at least one saved search:
1. Land on `/portal/air/ManageClients` via contact-detail-link click.
2. Read the All Searches table to enumerate search IDs.
3. For each search ID:
   - `await page.evaluate(id => manageClients.manageResults(id, '1'))`
   - Wait for new tab (`context.waitForEvent('page')`).
   - On the new tab, set sort = "Last Viewed Descending" to surface
     engaged listings first.
   - Page through results (140 listings per Nancy -> probably paginated;
     check page text for "Showing N to M of K").
   - Parse each card. Stop when `view_count = 0` strings dominate
     (everything below is unengaged so OK to skip on incremental runs).
   - Close the tab.

Cost: 1-2 new-window scrape per active buyer. With ~50 active buyers in
the system and 1-2 searches each, this is 50-100 listing pages every
2 days -- well within Xposure rate limits given current scrape pace.

Local cache file: `~/.elevate/snapshots/pcs-listing-views.jsonl`
(append-only mirror, same pattern as buyers.jsonl).
