---
name: "marketing-landing"
description: "Builds and previews a per-listing landing page (<landing-base>/<slug>/), then deploys to Cloudflare Pages on confirm. Runs after marketing-render and before marketing-copy so the live URL is available to social posts and the Mailjet email."
category: "real-estate-marketing"
tags: ["real-estate", "marketing", "landing-page", "cloudflare-pages", "listing-launch"]
access:
  entitlement: "real_estate_marketing"
---

# Marketing Landing

Run after `marketing-render`. Output is a per-listing landing page deployed to
`<domains.landing_base>/<slug>/` (slug = `inputs.address_slug`). The landing
base URL is `domains.landing_base` in `config/realtor.json` — the
`<landing-base>` value shown in command examples below is the
current realtor's; substitute the config value for any other realtor.

The page is built from a scaffold and then the realtor-voice prose is filled in by
the agent before the deploy step. the realtor always previews before push.

Working root:

```bash
cd ~/elevate-premium
```

## Step 1 -- Build scaffold

```bash
node .claude/skills/marketing/scripts/build-landing.js data/marketing/runs/<run>
```

This reads `<run>/inputs.json` and writes a scaffolded HTML file at:

```
data/marketing/runs/<run>/landing/<slug>/index.html
```

Deterministic tokens already filled in:

- Address (full + short), city, neighbourhood (`sub_division`), price, MLS#
- Hero photo (`main_photo` Drive URL)
- Beds / baths / sqft / year-built (parsed from `features_bullets` if matchable)
- Open house display (if set)
- Gallery built from `main_photo` + `interior_photo` + `secondary_photo` + `photo_4..6` + `recreational_photo` (skipped if null)
- Agent block always the realtor; brand colors / fonts from `config/realtor.json` (`brand`)
- Footer disclaimer + MLS line

Bespoke prose blocks are marked with `<!-- BESPOKE: ... -->` comments and
default to property-agnostic placeholder text.

## Step 2 -- Fill bespoke copy (agent task)

Read the scaffold and the listing's detail file (if any in
`docs/listings/<slug>.md`), then Edit each `<!-- BESPOKE: ... -->` block
to property-specific the realtor-voice copy:

| Block | What goes here |
|---|---|
| HERO_EYEBROW | Building / neighbourhood label, e.g. "Nicola Towers · South Kamloops" |
| HERO_H1 | One-line angle on what makes this property the property |
| VALUE_PROP | h2 + 2 paragraphs on the single biggest reason to care |
| SPLIT_1 | Step Outside / location-and-walkability hook |
| SPLIT_2 | Lifestyle / what living here actually looks like |
| THE_VIEW | What you wake up to: views, light, setting (h2 + 3 cards) |
| WHO_ITS_FOR | 3 buyer profiles for this specific property |
| TITLE_TAG | `<title>` + meta description (use the strongest hook) |

Voice rules: `docs/voice/realtor-profile.md` is the source of truth, including
the banned-phrase list. No em dashes. No sycophancy. Concrete sensory detail
beats generic adjectives every time.

Photo alt text: rewrite gallery and split alt attributes to describe what is
actually in the photo, not generic placeholders.

## Step 3 -- Preview

```bash
open file://$(pwd)/data/marketing/runs/<run>/landing/<slug>/index.html
```

Send the realtor the file path and ask: "Preview opened. Push live to
`https://<landing-base>/<slug>/`?" Wait for explicit confirm.

## Step 4 -- Deploy on confirm

If the realtor explicitly asks to publish the landing page, that counts as deploy confirmation. This is separate from Matrix / MLS publish. Do not touch Matrix unless she separately asks for Matrix.

Before deploying, verify the local HTML is safe:

```bash
python3 - <<'PY'
from pathlib import Path
import re, sys
html = Path('data/marketing/runs/<run>/landing/<slug>/index.html')
text = html.read_text()
assert 'BESPOKE:' not in text
assert 'src=""' not in text and "src=''" not in text
missing=[]
for src in re.findall(r'<img[^>]+src=["\\']([^"\\']+)["\\']', text):
    if not src.startswith(('http://','https://','data:')) and not (html.parent/src).exists():
        missing.append(src)
assert not missing, missing
PY
```

Deploy only through the safe assemble script, never through `wrangler pages deploy` directly on a single run folder:

```bash
.claude/skills/marketing/scripts/deploy-landing.sh data/marketing/runs/<run>/landing
```

The script assembles every active `data/marketing/runs/*/landing/<slug>/` into one temporary deploy directory so existing live pages are preserved.

After deploy, verify the canonical URL and page content:

```bash
curl -sI https://<landing-base>/<slug>/ | sed -n '1,12p'
curl -s https://<landing-base>/<slug>/ | python3 -c "import sys,re; html=sys.stdin.read(); print(re.search(r'<title>(.*?)</title>', html, re.S).group(1).strip()); print('has_empty_src=', 'src=\"\"' in html or \"src=''\" in html)"
```

Write `data/marketing/runs/<run>/handoffs/landing.handoff.json` yourself. The deploy script prints the canonical and preview URLs but does not write the handoff file.

Wrangler authenticates via OAuth as the realtor's email (`identity.email` in
`config/realtor.json`) -- no token needed. The Cloudflare Pages project name is
`deploy.cloudflare_pages_project` in `config/realtor.json`; the landing base URL
is `domains.landing_base`.

## Handoff

`data/marketing/runs/<run>/handoffs/landing.handoff.json`:

```json
{
  "status": "deployed",
  "run_id": "...",
  "address_slug": "...",
  "landing_url": "https://<landing-base>/<slug>/",
  "preview_url": "https://<hash>.<landing-base>/<slug>/",
  "html_path": "data/marketing/runs/<run>/landing/<slug>/index.html",
  "deployed_at": "...",
  "next": "marketing-copy"
}
```

If the realtor declines the push, write `status: "preview-only"` with no
`landing_url`. Downstream phases fall back to `domains.listings_fallback` in
`config/realtor.json`.

## Hard rules

- Never deploy without explicit the realtor confirm.
- Slug is always `inputs.address_slug`. Do not invent.
- Brand colors and fonts come from `config/realtor.json` (`brand.colors`,
  `brand.fonts`). Set in the template -- do not change per-run.
- Footer service-area text is `geography.service_area_phrase` from
  `config/realtor.json`. Never narrow it to the primary market only.
- Photos that are `null` in inputs.json must not appear in the rendered HTML
  (no broken `<img>` tags).
