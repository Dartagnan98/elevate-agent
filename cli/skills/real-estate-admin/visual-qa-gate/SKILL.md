---
name: visual-qa-gate
description: "Gate a visually driven output on a render/screenshot comparison before calling it ready. Use whenever reporting done on Mailjet previews, social/Buffer graphics, CMA or Market Evaluation PDFs, landing pages, listing ads, flyers, or sign concepts, since API success or file existence alone is not proof the design is correct."
---

# Visual QA Gate

Use when producing or reviewing any visually driven output for the realtor: Mailjet previews, social media graphics, Buffer/Instagram/Facebook drafts, CMA/Market Evaluation PDFs, landing pages, listing ads, thumbnails, flyers, brochures, sign concepts, and other branded visual deliverables.

## Core rule

Do not call a visual deliverable ready based only on API success, file existence, draft status, or data correctness. It must pass a render/screenshot/reference comparison gate first, unless the user explicitly asks for a mechanical action only (for example, "send me a test" after they fixed the design themselves).

## Process

1. **Lock the reference**
   - Use the user-provided screenshot/PDF/template ID, or the approved workflow reference.
   - For CMA/Market Evaluation PDFs, use the current approved template unless the realtor provides a newer reference.
   - For Mailjet, use the approved branded template/reference and any user-provided screenshot.
   - For social graphics, use the locked brand social template/reference for that asset type.

2. **Render the current output**
   - Capture the actual Mailjet preview, Buffer/platform preview, live landing page, or rendered PDF/image output.
   - For PDFs, render pages to screenshots and build a contact sheet.

3. **Compare visually**
   Check at minimum:
   - logo size and placement
   - header/footer layout
   - image choice and crop
   - colour palette and contrast
   - typography treatment
   - margins/spacing/alignment
   - CTA/button styling
   - required brokerage/team branding
   - stale price, date, MLS, open house, address, or listing copy
   - off-brand older template/flyer elements resurfacing

4. **Save proof artifacts**
   - Store output screenshot(s), contact sheet if multi-page/batch, and a short JSON/MD QA note with pass/fail and required fixes.

5. **Only then report ready**
   - If it fails visual comparison, describe the specific mismatch and fix it or hand it to the owning agent/workflow.
   - External sends, scheduling, MLS publishing, and client-facing delivery still need human approval unless the realtor already gave explicit approval for that exact action.

## Workflow-specific notes

### Mailjet
- Verify draft status, subject, sender, list, image URLs, unsubscribe/merge tags, then render and visually compare.
- When the realtor provides a screenshot with marked-up areas (for example, a red rectangle around a logo/header space), treat the marked region as a visual sizing/layout requirement, not just general inspiration.
- Footer/header references must be matched structurally: if the reference is a full-width branded card with portrait, stacked logos, large name text, body copy, and CTA buttons, do not substitute a small conventional email signature/footer.
- Do not overwrite a user/Claude-fixed draft when the user says they already fixed it; immediately stop active edit runs and switch to read-only verification or test-send only.
- Test-send is not proof that the design is visually correct; it is delivery proof.

### Social/Buffer
- Export or capture a contact sheet for graphics batches.
- Verify platform dimensions/aspect ratios and approved photo source.
- Buffer API success is not enough; inspect/capture platform crop preview when possible.

### CMA / Market Evaluation
- Use the realtor's currently approved CMA visual template unless superseded by a newer reference.
- Render generated CMA PDF to screenshots and compare cover, strengths/considerations, pricing-story, comp/table/data, and final recommendation pages.
- Data accuracy and PDF export success are necessary but not sufficient.

### Landing pages
- Landing pages already follow this pattern most consistently: scaffold, render, screenshot, verify, deploy/live-check.
- Use landing pages as the standard for other visual workflows.