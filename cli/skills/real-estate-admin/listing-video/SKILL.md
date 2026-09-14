---
name: listing-video
description: Create Forever listing-tour videos from Skyleigh's recording and property photos, with mobile-safe branding, grid covers, captions and platform copy. Use for an opted-in Marketing Go video add-on or a direct listing-video request; coaching-call clips belong to short-form-video.
metadata:
  elevate:
    tags: [skyleigh, forever, marketing, listing-video]
    related_skills: [marketing, marketing-inputs, marketing-landing, marketing-buffer]
---

# Listing Video

When resumed from an approved `reviewPackage` containing existing video/posts/inputs, execute only its approved Buffer action from that package directory. Do not rerender the video or create another approval for the same reviewed cut. A video-only review remains separate from already approved landing, email and still-graphic actions.

An optional companion to Marketing Go, not a replacement for the normal listing launch.
Working root: `/Users/admin/elevate-premium` (`~/skyleigh-tools` resolves here).
Read `knowledge/brand-guide.md` and [the saved video preferences](references/preferences.md) before editing.

## Intake and routing

Marketing Go asks once per listing launch, alongside its other missing inputs:

> Would you like a video for this listing—using your recording, using photos only, or not this time?

Use an answer already supplied in the conversation or saved run; do not ask again on resume. A direct request to make a listing video is already an opt-in. A photos-only choice means a photo-led video; it does not authorize a synthetic version of Skyleigh's voice or face. If she says later, retain that decision without a repeated prompt.

Persist in the existing run's `inputs.json` (or the deal's launch-input artifact when no run exists):

```json
"listing_video": {
  "choice": "recording",
  "asked": true,
  "source_files": []
}
```

`choice` is `recording`, `photos_only`, `no`, `later`, or `pending`. Missing legacy data means unknown, not consent and not a silent no. Ask during interactive intake; an unattended launch records pending and continues the ordinary launch. Merge this field without replacing other inputs.

For `recording` or `photos_only`, prepare alongside the normal phases. Ask only for genuinely missing media/style details. Missing footage or an unanswered optional choice must not hold up ordinary graphics, landing page, copy or email work. Use the landing handoff's verified URL when writing video copy.

## Deliverables

Keep video work under `data/marketing/runs/<run>/video/`, with source references rather than extra source copies where practical:

- A natural-paced vertical video, with captions and actual Forever/eXp assets. Match named local places in the narration with verified location photos/clips; include the location-coverage record and disclose any unresolved source.
- A 3:4 profile-grid cover plus a 9:16 cover frame containing it centrally.
- Separate Instagram, Facebook and optional YouTube copy with the verified landing page and contact CTA.
- Review links in the listing's current Google Drive marketing folder.
- `handoffs/video.handoff.json`: choice, status (`pending`, `skipped`, `waiting_media`, `ready_for_review`, `approved`, `published`, `partial`), source paths, final artifacts/Drive IDs, landing URL, platform choices, actual post IDs/URLs, and remaining work. Approval and publication are separate states.

Use `references/preferences.md` for editing, crop checks and publishing behavior. Do not hard-code Corry's address, claims, credentials, media, IDs or caption joke into another listing.

## Scope and completion

Opting into a video authorizes preparation, not public posting. Reuse publishing authorization already given for this exact video and channels; otherwise present the concrete preview/copy before publishing. Choosing YouTube or Stories is separate from choosing Instagram/Facebook. Never silently repost a live video to fix graphics: explain that replacement loses transferred engagement and obtain direction about the current post.

If Skyleigh says to save a preference for next time, record it without changing the current live posts. For the Corry run on 2026-09-09 she explicitly chose to keep the live posts; mobile/crop revisions are future preferences, not authorization to republish or archive.
