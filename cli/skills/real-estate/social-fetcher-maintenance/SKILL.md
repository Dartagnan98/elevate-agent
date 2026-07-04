---
name: social-fetcher-maintenance
description: Debug social-content-engine metric fetcher scripts directly, bypassing a stale skill file. Use when fixing Instagram/Facebook/YouTube/TikTok/LinkedIn social metrics fetchers, Composio account lookup failures, misleading not_configured statuses, or Elevate venv/runtime issues.
triggers:
  - social metric fetcher script bug
  - Instagram/Facebook/YouTube metrics return not_configured unexpectedly
  - Composio account lookup failure is masked
  - user says not to load social-content-engine/SKILL.md
  - dashboard social refresh fetcher path mismatch
---

# Social Fetcher Maintenance

Use this when the user asks for direct fixes to social metric fetcher scripts, especially if they explicitly say **do not load or open `social-content-engine/SKILL.md`**.

## Core rule

If the user says not to load/open `social-content-engine/SKILL.md`, do not call `skill_view('social-content-engine')` and do not read `SKILL.md`. Work directly against the scripts.

## Known script locations

There may be two active copies:

1. User skill copy:
   - `/Users/admin/.elevate/skills/social-content-engine/scripts/`

2. Source/runtime fallback copy used by dashboard loader:
   - `/Users/admin/.elevate/elevate/cli/skills/social-content-engine/scripts/`

The dashboard loader in `elevate_cli/web_server.py` may look for:

```python
~/.elevate/skills/social-media/social-content-engine/scripts
```

then fall back to the source tree:

```python
~/.elevate/elevate/cli/skills/social-content-engine/scripts
```

So if the user-skill path is not the actual runtime path, patch the fallback source copy too.

## Required interpreter

Run fetcher scripts with the Elevate app venv Python, not system Python:

```bash
/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python
```

System `/usr/bin/python3` can miss dependencies like `httpx`, which used to be misreported as `not_configured`.

## Maintenance steps

1. Locate the scripts without opening `SKILL.md`:

```bash
# Use search_files or direct paths, not skill_view.
/Users/admin/.elevate/skills/social-content-engine/scripts/
/Users/admin/.elevate/elevate/cli/skills/social-content-engine/scripts/
```

2. Read only the relevant `.py` files:

- `_metrics_io.py`
- `instagram_insights.py`
- `facebook_insights.py`
- `youtube_analytics.py`
- Other platform fetchers only if requested.

3. Patch `_metrics_io.find_composio_account()` so dependency/API failures are explicit:

- Add `ComposioAccountLookupError(RuntimeError)`.
- Raise it when `from elevate_cli import composio_client` fails.
- Raise it when `list_all_connected_accounts(...)` returns `ok: false`.
- Return `None` only for a true empty account list.

4. Patch each fetcher to catch lookup failures:

```python
try:
    account = find_composio_account(TOOLKIT_SLUG)
except ComposioAccountLookupError as exc:
    summary["status"] = "account_lookup_failed"
    summary["errors"].append(str(exc))
    return summary
if not account:
    summary["status"] = "not_configured"
    return summary
```

5. For Composio account IDs, use both supported keys:

```python
account_id = account.get("id") or account.get("connected_account_id")
```

6. For Instagram account-level insights, match Composio's current tool schema:

```python
acc_resp = composio_client.execute_tool(
    SLUG_USER_INSIGHTS,
    account_id,
    {
        "metric": ["reach", "follower_count", "profile_views"],
        "period": "day",
        "since": cutoff.date().isoformat(),
        "until": datetime.now(timezone.utc).date().isoformat(),
    },
)
```

Do not send `metric` as a comma-separated string. Do not send Unix timestamps for `since`/`until`; Composio's schema expects `YYYY-MM-DD` strings. Avoid unsupported/deprecated account metrics like `website_clicks` in this fetcher.

7. For Facebook Page Insights, avoid legacy Graph API metrics that now return HTTP 400. Use a currently-valid `period=day` metric list and surface Graph API errors instead of silently writing empty account metrics:

```python
PAGE_METRICS = [
    "page_impressions_unique",
    "page_views_total",
    "page_post_engagements",
    "page_actions_post_reactions_total",
    "page_total_actions",
    "page_video_views",
    "page_follows",
    "page_daily_follows",
    "page_daily_unfollows",
]
```

Known invalid/deprecated metrics to remove from this fetcher include `page_impressions`, `page_engaged_users`, `page_fans`, and `page_fan_adds`.

8. For YouTube, keep the repair minimal unless the user asks for deeper video analytics. Make basic channel stats land even when there are no recent videos:

- Discover the channel ID from playlist/channel payloads when needed.
- Call `YOUTUBE_GET_CHANNEL_STATISTICS` with:

```python
{"id": channel_id, "part": "statistics,snippet"}
```

- Unwrap both common Composio shapes, such as `{data: {channels: [...]}}` and `{response_data: {items: [...]}}`.
- Append the channel account metric before recent-video processing, using `post_id=f"_account_{channel_id}"`.
- Include at least `subscriber_count`, `view_count`, and `video_count`.
- If listing videos, use YouTube-style params for `YOUTUBE_LIST_CHANNEL_VIDEOS`:

```python
{"channelId": channel_id, "part": "snippet", "maxResults": min(max_posts, 50)}
```

Do not over-engineer video sorting/listing when the user only asked for basic channel stats.

9. For repeated pulls, include raw payloads only on first-seen posts:

```python
first_seen = not has_post_been_seen("facebook", str(post_id))
append_metric(..., include_raw=first_seen)
```

Instagram may already calculate `first_seen`, but verify it is actually used in `append_metric(...)`.

10. Sync fixes to both relevant copies when needed:

```bash
# Prefer targeted patches. If one copy is already correct and the other is stale,
# copying the corrected files is acceptable for these script-only fixes.
```

8. Compile-check with the Elevate venv:

```bash
PY="/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python"
ROOT="/Users/admin/.elevate/elevate/cli/skills/social-content-engine/scripts"
"$PY" -m py_compile \
  "$ROOT/_metrics_io.py" \
  "$ROOT/instagram_insights.py" \
  "$ROOT/facebook_insights.py" \
  "$ROOT/youtube_analytics.py"
```

9. Run the fetchers with the Elevate venv:

```bash
PY="/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python"
ROOT="/Users/admin/.elevate/elevate/cli/skills/social-content-engine/scripts"
for s in instagram_insights.py facebook_insights.py youtube_analytics.py; do
  echo "--- $s ---"
  ELEVATE_WORKSPACE_ID=default "$PY" "$ROOT/$s" --lookback 30 --max-posts 5
  echo
done
```

10. Verify the old misleading path is fixed:

```bash
/usr/bin/python3 /Users/admin/.elevate/elevate/cli/skills/social-content-engine/scripts/instagram_insights.py --lookback 30 --max-posts 1 || true
```

Expected: `status` should be `account_lookup_failed`, with an error such as `No module named 'httpx'`. It must not say `not_configured` for dependency/import failures.

## Reporting format

Report:

- Files edited.
- Whether `SKILL.md` was avoided if requested.
- Compile result.
- Per-platform run table: status, posts seen, posts with insights, errors.
- Whether `/usr/bin/python3` now surfaces `account_lookup_failed` instead of `not_configured`.

## Pitfalls

- Do not assume `/Users/admin/.elevate/skills/social-content-engine/scripts` is the runtime path. Check the dashboard loader or patch the source fallback too.
- Do not use system Python for verification except the intentional negative test.
- Do not claim platform auth is fixed just because runtime/lookup bugs are fixed. If a platform returns 0 posts with status `ok`, say exactly that.
- Avoid writing social metric outputs into a repo workspace accidentally. Set `ELEVATE_WORKSPACE_ID=default` during test runs when appropriate.
