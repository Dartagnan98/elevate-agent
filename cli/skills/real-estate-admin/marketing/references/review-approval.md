# Marketing Go: previews and ACTION NEEDED

Applies to complete Marketing Go runs and approved continuation. Build and visually verify every requested asset first. This uses Elevation's existing action queue; packs remain independently runnable and sellable.

## Preparation

Prepare landing HTML without deploying. Set `intended_landing_url` to the final canonical URL; keep `landing_url` null until deployment is verified. Finish captions and emails using the intended URL where appropriate. A coming-soon email keeps its mailto CTA. Buffer prep uses `--dry-run`; Mailjet prep uses `--dry-run` and writes `email-previews/<email-id>.html` and `.txt`. Inspect these exact rendered emails. Owner test email only when authorized, never schedule a campaign just to test it. A private/local image or unverified public image URL means the email is not ready to schedule.

Create `<run>/launch-review.json`:

```json
{
  "version": 1,
  "mode": "publish",
  "title": "Review marketing launch — <address>",
  "message": "Review the assets and launch plan. Approve to carry out only the listed actions.",
  "artifacts": [
    {"path": "landing/<slug>/index.html", "name": "Landing page"},
    {"path": "graphics/coming-soon.png", "name": "Coming-soon graphic"},
    {"path": "copy.md", "name": "Social captions"}
  ],
  "files": ["inputs.json", "posts.json"],
  "trees": ["landing"],
  "actions": [
    {"id": "publish_landing", "label": "Publish landing page", "details": "Publish to the exact canonical listing URL shown here."},
    {"id": "schedule_buffer", "label": "Schedule social posts", "details": "Use the reviewed captions and graphics on the channels and dates below."},
    {"id": "schedule_mailjet", "label": "Schedule email blast", "details": "Use the reviewed email body for the audience and dates below."}
  ],
  "notes": []
}
```

Use actual existing paths and a real URL, never literal placeholders. List all final PNGs, email previews, landing page, copy, and opted-in video/covers as artifacts. Editable SVGs and private photo ZIPs are supplementary downloads, not substitutes for previews. Include only prepared actions; excluded/partial video is explicitly noted and omitted from posts being scheduled. Include local supporting image directories in `trees` when needed. The helper derives actual social/email destinations and times from posts.json and provider settings, adds rendered email previews and a readable launch-plan preview, freezes the relevant provider routing configuration, and registers all artifacts durably with the original chat session.

```bash
node .claude/skills/marketing/scripts/review-launch.js <run-dir> prepare <originating-session-id> <deal-id> [existing-action-run-id]
```

Use the originating human chat session ID, not a delegated worker's session. It is retained as `reviewSessionId` / `sessionId` on existing run context. If no chat session exists, obtain/use a real review session instead of inventing one. Read back `/api/sessions/<session-id>/artifacts` and the Admin waiting run before claiming previews or ACTION NEEDED are ready. Do not overwrite this waiting prompt with an ordinary completion callback; report `waiting_human` with the returned reviewPackage and sessionId intact. Keep checklist publish/send items open.

If launch inputs are missing and no launch approval has been given, register the completed drafts with `mode: "prepare"`, `actions: []`, and concise structured `requiredFields` (for example launch date/time). The button collects inputs and prepares final approval; it grants no permission to publish. A pending optional video does not block otherwise ready landing/email/social actions.

## Approved continuation

When `resumeExistingArtifacts` contains this review package and decision, resume its existing run directory. Do not rerun render/copy/build. For prepare mode, read the actual providedAnswers first. If they explicitly authorize the existing assets, apply the recorded authorization as described below; otherwise complete missing inputs before asking for publishing approval. For publish mode, execute only the approved action IDs:

1. `publish_landing`: run deploy-landing.sh on the reviewed landing directory, then read back the public page and verify assets/URL.
2. `schedule_buffer`: run schedule-buffer.js on the same run directory. If approved copy links to the landing page, verify that page is live first.
3. `schedule_mailjet`: run schedule-mailjet.js on the same run directory. It reads the exact approved rendered HTML/text, not freshly regenerated email. Verify linked landing/image URLs first.

The scripts claim each approved action once through Elevation before their external mutation. Changed assets, templates, settings, destination/schedule, cancelled approval or elapsed dates require a fresh review. An interrupted/failed claim requires provider reconciliation before retrying; do not create duplicate posts or blasts. Record real provider IDs and read back actual status, times, content and channels. Keep partial failures visible. A queue acknowledgement alone is not launch completion.

For standalone packs outside Elevation, retain the pack's own explicit approval mechanism; do not bundle unrelated skills or require a separate resident automation. These shared Marketing Go scheduler scripts use the Elevation approval adapter when called.

## Honor approval already supplied with the timing

A response such as “coming soons can all get sent out right now, approving the landing page, will edit the video first” authorizes the existing coming-soon assets and landing page while excluding video. Do not reinterpret it as timing-only or ask for a second final approval merely because the original review was `mode: prepare`. Reuse the unchanged visible assets; finish technical preparation and verify provider routing. A date/time alone still is not approval.

Write a small consent JSON containing `sourceText` (the exact recorded human answer) and `approvedActions` (only its authorized action IDs), then run:

```bash
node .claude/skills/marketing/scripts/review-launch.js <run-dir> authorize-recorded <existing-run-id> <consent-json>
```

The existing-answer endpoint validates the recorded answer and the reviewed asset hashes, preserves an approval ledger, and marks this same run ready for execution without another popup. It does not spawn a second worker; continue execution in the current worker. Use `immediate` in the manifest schedule when the user says now; do not turn elapsed processing time into a new approval request. Technical authentication, connectivity or provider failures are execution blockers, not missing consent. Reconcile before retries, preserving provider IDs so nothing is sent twice.

If only the video is excluded/pending, create a separate video-only package and waiting run, with its own posts/inputs and preview links. Do not include video bytes in the approved non-video package's file tree. Changed video must not revoke the landing/email/graphics approval. A worker callback must preserve the review decision; it must not replace it with a generic “approve to launch” question.
