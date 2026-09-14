# Marketing Go launch phase contract

Read for interactive listing-launch preparation, retries and recovered runs. Preserve the campaign's explicit exclusions and existing provider IDs.

## Intake and video

Ask once alongside missing launch inputs: “Would you like a video for this listing—using your recording, using photos only, or not this time?” Reuse answers already supplied. Merge `listing_video: {choice, asked, source_files}` into inputs.json; choice is recording, photos_only, no, later or pending. Missing legacy data means unknown, never a silent no. Unattended runs retain pending. An opted-in video uses the separate installed listing-video skill; absent footage or an unanswered optional choice does not block ordinary launch preparation. Save its status in handoffs/video.handoff.json.

## Deliver the complete review package

- Render: use the installed brand templates and actual high-resolution brand assets. Export usable PNG/JPEG files, with editable SVG/HTML only as additional source files. Inspect the final images at phone size for clipped addresses, overlapping photos/text, misplaced face crops, weak logo contrast and missing images. A file existing or naturalWidth > 0 does not establish acceptable composition. Missing Pillow is not a rendering blocker when the installed HTML/browser renderer is available.
- Landing: produce a property-specific preview with loaded photos, inspect desktop and mobile, and return a clearly labelled direct preview link or file. Write handoffs/landing.handoff.json even for preview-only work. Public deployment and MLS activation are separate actions; absence of a public MLS URL does not prevent a property-page preview. Keep campaign timing out of the lasting property page.
- Email: use the actual current branded ESP template and verify the phone-sized layout, sender, CTA and every image. Distinguish local email HTML, a provider campaign draft, a requested owner-only test, scheduled and sent. Record each separately. An owner-only proof can embed its images and use a truthful reply/contact CTA when the page is not public. Missing public asset URLs must not silently erase the email-proof step. Consult the installed email send gate and honor existing authorization. Never claim delivery from a preflight or local file alone.
- Copy/social: use campaign-appropriate wording and current provider discovery; unavailable scheduling does not invalidate finished local drafts. Preserve explicit open-house exclusions without inventing details. Do not automatically create just-listed or open-house variants outside the requested scope.
- Review: return labelled links for the social graphic, story, email preview and landing page, plus email-test status and the saved video choice. Include precise remaining work. “Three local SVGs” is a source-file inventory, not a completed launch package.

Every phase writes its handoff with complete/partial/preview-only/waiting status and evidence paths. The run remains partial when required review outputs or approvals are missing. On recovery, review artifact quality and handoff completeness before accepting the recovered files as finished. Keep live publish, schedule and audience send approvals separate from preparing or testing drafts. The listing-video skill remains optional and separately packaged.

## Template and saved-correction checks

Before producing a phase, read its installed SKILL.md, the relevant template, and the workspace marketing/lessons.md; landing work also reads marketing-landing/lessons.md. A successful render is not evidence that the requested design or campaign stage was followed. Preserve the installed template structure and the user's saved corrections rather than substituting an ad hoc layout.

- Coming-soon email uses the stage's coming-soon template and prompts, not the standalone featured-listing template. Keep it a teaser: omit price, full address and MLS number. Follow the requested section lengths; never invent a launch day when it is unconfirmed. Use the owner's actual brand marks and signature.
- Landing uses the saved landing template and its body/display fonts. Complete all property, area, lifestyle, setting, details, buyer-fit, gallery and contact sections. Apply the saved full portrait + brokerage-mark agent block, not an initials placeholder. Property details are text-only by default. Curate a room rotation from verified photos and avoid reusing the same photo across sections. Never invent an unavailable room view.
- Owner requests to receive/download assets are fulfilled through the private review hub and Drive. Do not add public photo-download controls, a photo ZIP, coming-soon copy or a preview-status banner to the landing page unless those website features are explicitly requested.
- Review delivery includes a clearly named Drive marketing folder with usable PNG/video files and download bundles, as well as direct previews. Do not describe a list of local source filenames as delivered media.
