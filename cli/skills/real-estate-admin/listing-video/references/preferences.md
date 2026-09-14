# Forever listing-video preferences

Saved from Skyleigh's 125 Corry Place workflow, 2026-09-09. These are listing-video defaults, not coaching-video rules. New explicit directions override them.

## Editing and media

- Use her real recording at natural speaking speed. Remove long pauses, restarts and unusable takes by phrase, but do not force a 60-second runtime or speed her up to fit a template. The Corry edit was about 74 seconds; that is an example, not a target.
- Listen closely to the opening for clicks/blips and clipped consonants. Preserve complete phrases; use light click cleanup/fades only where needed. Keep approved audio unchanged during a graphics-only revision.
- Start with a strong property-specific hook and show the main selling feature early. Roughly 20% talking head / 80% full-screen property photos was the preferred balance, not a fixed timing rule. Return to her face for the CTA when usable footage exists.
- Match each photo to what she is saying. Gentle pans/zooms, clean cuts or soft dissolves; no small property box over her face or busy effects. Do not pretend an indoor recording was filmed at the listing.
- Use the exact property's clean, verified Drive photos. Never invent rooms, shop interiors, views or property features to fill missing shots. Photos-only video can use concise on-screen copy; get direction before adding narration that was not supplied.
- When the narration names local places (parks, trails, neighbourhood landmarks), source real photos or clips of those exact places and insert them during the matching words. Inventory each named location with transcript time, source, usage rights and final clip timing in `location-coverage.json`. Check the user's media/Drive first, then suitable licensed sources. Save credits and label area scenery so it is not mistaken for a property view. If a location or usable source cannot be verified, mark that location unresolved in the video handoff and tell Skyleigh; do not silently omit it or mark the video complete. This is part of the opted-in video workflow, not a second optional add-on.
- Prefer a clean paid BIGVU source/export. Check for a burned-in watermark; the subscription alone does not guarantee an old export is clean. A modest reframe of her own source is acceptable if it preserves the shot. Inspect the result before calling it watermark-free.

## Branding, face and text

- Forever only for listing marketing: Forest `#044B35`, Deep Forest `#033524`, Burnt Gold `#CE823E`, cream `#FAF9F7`. Read the current guide for authoritative assets.
- Social headline: Lato Black; supporting labels/body: Lato. Use Cormorant Garamond for the address/display text. Render actual installed font files for precise typography when using a deterministic layout; a generated approximation is not proof of the exact font.
- Use the actual high-resolution Forever wordmark and actual eXp logo, balanced by visual height. Never redraw/retype the wordmarks. Keep added greenery minimal: one subtle small accent near the footer/logo is enough. No ornate foliage frame.
- Preserve her approved face and natural expression. She preferred the original portrait over a lip-symmetry retouch; do not automatically beautify, reshape or symmetrize her lips/face. Prefer placing the actual cutout over regenerating the portrait. Preserve property geometry equally carefully when generating/editing a cover.
- Caption boxes and name/address plates should sit below her face, not cross her mouth. Check both talking-head sections, not only one frame.

## Mobile and grid checks before publishing

Desktop playback is not sufficient. Instagram overlays and crops vary; verify the intended mobile Reel/feed/profile views or a recent user screenshot before calling a placement safe.

- Working video: 1080×1920, 9:16, H.264/AAC, normal speed.
- The original Corry logo plate at y=145 was obscured on mobile. Future starting position: x≈65, y≈350, plate height≈121 on a 1080×1920 canvas. This is a conservative starting point, not a guarantee for every app view. Keep it clear of her face and interface controls. Move location labels below the logo when used.
- Corry captions began around y=1450, with the CTA/name panel around y=1140–1340. Adjust to the actual face and bottom interface area; keep all lines visible.
- Design the grid cover at 3:4 (e.g. 1080×1440). Entire house roof/entrance, headline, address, face and BOTH logos must survive the crop. Do not use a full-height 9:16 layout whose footer disappears.
- For a 9:16 cover frame, center the 1080×1440 cover in 1080×1920, padding 240px above and below with deep forest. Keep key content away from the cover's own edges. Check the actual 3:4 center crop at phone-grid size. Inspect other supported crops if the destination shows a different shape.
- Buffer's Instagram cover can come from a video frame. Where needed, include the approved padded cover in the first frame without shifting narration/timing. Verify current platform support; do not promise a custom YouTube Shorts cover via Buffer.
- Check the exported beginning, closing, photo transitions and B-roll; decode the complete output for errors and verify duration/audio sync. A graphics-only change should retain the approved audio stream where possible.

## Captions, links and publishing

- Include the verified current property landing-page URL in the platform copy from the start. Confirm it resolves to this listing and supports the description promised (full details/photos versus an actual downloadable info pack). Never copy an old price, MLS number or another property's URL blindly.
- Instagram: property hook, concise features, showing/info-package CTA, contact details and a small relevant hashtag set. Caption URLs are not clickable; use an existing relevant bio link destination or propose adding the property as an additional profile link without overwriting unrelated links. Do not say “link in bio” until verified. Do not silently replace the user's requested caption URL with no URL.
- Facebook: same approved message, remove ALL hashtags, retain the landing link.
- Humour is optional and recording-specific. The “counter stops” joke was requested for Corry only; do not reuse it on unrelated listings or invent speech mistakes.
- YouTube, when requested: clear location + distinctive feature + address in a concise title; useful first description lines, property details, contact/landing CTA and a few relevant hashtags. No keyword stuffing or ranking guarantees. Set public visibility and audience appropriately for real-estate buyers (not made for kids). Check the current Shorts requirements and supported Buffer settings. Separate caption files, tags or custom covers may require YouTube Studio; never claim unsupported settings were applied.
- Stories: distinguish a separate uploaded Story from sharing an existing Reel to Story. The latter required Instagram's phone app in this run. Verify current capabilities and do not publish an unrequested separate Story as a substitute.
- Use the saved Buffer connection, not a new service. Current integration notes: `knowledge/workflows/buffer.md`; config: `.claude/skills/marketing/config/buffer-channels.json`. Resolve channels by brand AND handle/service before posting; IDs can change. Do not post a Forever listing to Elevation or a personal channel by accident.
- The working API on this run was GraphQL `https://api.buffer.com/` with `BUFFER_TOKEN` from the project `.env`. Never print secrets. Discover organizations with `account { organizations { id name } }`, then `channels(input:{organizationId:...})`; `account.channels` is not the current query. Verify metadata types rather than reusing obsolete payloads.
- Drive video downloads worked at `https://drive.usercontent.google.com/download?id=<id>&export=download&confirm=t` after link access was enabled. Validate actual video bytes/content type. The `lh3.googleusercontent.com` route is for images, not video. Limit public link access to approved publishing assets.
- Store successful post IDs immediately. Poll that post for status, errors and live external URL rather than submitting again. An ambiguous timeout requires checking for an existing post before retrying. “Sending” is not “published”; notification publishing is not automatic posting.
- Published captions require the native platform when Buffer cannot edit them. An Instagram video's content cannot be replaced in place. Keep the original live unless the user authorizes a replacement and the disposition of the existing Reel.

## Reference run

`tasks/corry-bigvu-reel-20260909/` contains source-specific render scripts, fonts, transcripts and examples. Inspect/adapt them rather than executing them unchanged against a new listing. `render-mobile.py` lowers the logo; `125-Corry-Place-Forever-Grid-Cover.png` illustrates the 3:4 cover. These were saved for future use, not republished. Avoid creating multiple Drive copies of every intermediate render; retain final deliverables and the provenance needed to reproduce them.
