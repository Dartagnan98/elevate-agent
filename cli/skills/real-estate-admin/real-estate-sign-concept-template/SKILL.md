---
name: real-estate-sign-concept-template
description: "Build a for-sale sign concept from local brand/logo/headshot assets when Canva is down. Use when the realtor asks for a for-sale sign, a sign refresh, a Canva sign template, or wants existing team assets located first."
triggers:
  - User asks for a for-sale sign, sign concept, sign refresh, real estate sign template, or Canva sign template.
  - User asks to locate brand/logo/headshot assets first, then return a draft export path or exact missing items.
  - User wants a quick visual concept using existing realtor/team assets rather than a fully finalized print file.
---

# Real Estate Sign Concept Template

Use this when asked to make a refreshed real-estate for-sale sign concept/template from existing brand assets. The workflow is useful when Canva access is not available locally, but brand/logo/headshot files exist in the workspace.

## Workflow

1. **Search known asset locations first**
   - Start with the user's workspace and shared-team-brain folders, not a broad filesystem scan.
   - Useful searches:
     - `search_files(target="files", path="/Users/admin", pattern="*<brand name>*")`
     - `search_files(target="files", path="/Users/admin", pattern="*<realtor first name>*")`
     - `search_files(target="files", path="/Users/admin", pattern="*canva*")`
     - Narrow to `/Users/admin/shared-team-brain/files`, `<project-tools-dir>/knowledge`, and `<project-tools-dir>/data/brand/assets` when broad searches time out.
   - For the realtor's own brand specifically, useful paths include:
     - `<project-tools-dir>/knowledge/brand-guide.md`
     - `<project-tools-dir>/data/brand/assets/exp-realty-canada-logo.png`
     - `/Users/admin/shared-team-brain/files/Team Logos/PNGs/<Brand> Team Colour.png`
     - `/Users/admin/shared-team-brain/files/Team Logos/PNGs/<Brand> Team Black.png`
     - `/Users/admin/shared-team-brain/files/Team Logos/PNGs/<Brand> Team White.png`
     - `/Users/admin/shared-team-brain/files/<Brokerage folder>/Photos for covers/<headshot file>.PNG`
     - `/Users/admin/Downloads/eXp Canada - Black.png` or `/Users/admin/Downloads/eXp Canada - White.png`

2. **Read brand guidance if present**
   - Use `read_file` for brand-guide files.
   - Read the realtor's own local brand guide for her actual palette/type tokens rather than assuming a fixed set — every realtor's brand kit differs. A typical brand guide will name a primary/accent/neutral palette (hex values) and a heading/body font pairing; extract those exact tokens from the guide file before designing.

3. **Generate an asset contact sheet before designing**
   - Use a short Python/Pillow script to print file dimensions/modes and create a contact sheet of candidate logos/headshots.
   - Review the contact sheet with `vision_analyze` to choose the strongest headshot and identify logo visibility issues.
   - This avoids choosing the wrong crop or an old logo variant.

4. **Build a local draft when Canva is inaccessible**
   - If no Canva session/API/template is accessible, do not stall. Create a local concept/export with Pillow or another available graphics library.
   - Good default format: 24x18 landscape at 150 DPI (`3600x2700`) for a concept preview. Export PNG and PDF.
   - Use a clear output folder, e.g. `/Users/admin/<project-name>/`.
   - Include a small preview JPG for fast review and Telegram delivery if needed.

5. **Layout pattern that has worked well for realtor for-sale signs**
   - Top high-contrast brand-colour slab with large `FOR SALE` in a contrasting colour.
   - Accent-colour divider line under the header.
   - Neutral body with centered team/brand logo near top.
   - Arched or rounded headshot crop on the left, with an accent frame.
   - Right-side text block:
     - Local service-area line, e.g. `SERVING <REGION>`
     - `<Realtor Name>`
     - `REALTOR® | <Brokerage>`
     - Short brand copy if appropriate.
     - Website/contact strip.
   - Add a small compliance caveat in notes, not as prominent final copy.

6. **Crop headshots deliberately**
   - For landscape or environmental portraits, test multiple crops and make a crop-options contact sheet.
   - Review with `vision_analyze` before final export.
   - When cropping a source headshot for an arched portrait frame, test a centered crop first and adjust from the contact-sheet review rather than guessing a single fixed box.

7. **Recover from render/script failures before abandoning the concept**
   - If the failed run shows `'dict' object has no attribute 'lstrip'`, check any helper that parses hex colours or paths. The common cause is passing a Canva/API-style dict such as `{"hex": "#044B35"}` or `{"rgb": [4, 75, 53]}` into code that does `value.lstrip('#')`.
   - Fix with a defensive parser that accepts both strings and dicts, e.g. choose `value['hex']`, or return `tuple(value['rgb'][:3])`, before falling back to `str(value).strip().lstrip('#')`.
   - When writing Pillow scripts, pass text font arguments by keyword (`font=...`) to avoid `TypeError: text() got multiple values for argument 'fill'`.
   - After each patch, rerun the script and keep the generated source script in the deliverables so the layout remains reproducible.

8. **Verify outputs visually and mechanically**
   - Use `vision_analyze` on the preview JPG for obvious layout/readability issues, typos, clipping, logo placement, and distracting artifacts.
   - If an arched/rounded headshot uses a rectangular shadow or mat, rebuild the shadow/mat with the same mask as the crop so no square block shows behind it.
   - Use `terminal` or file stats to confirm the final PNG/PDF/preview exist and have nonzero size.

9. **Final response should be concise**
   - Report what was created, the exact export paths, the source assets used, and exact missing production items.
   - If a Canva rebuild is requested but no Canva access exists, say so plainly and list what is needed.

## Production caveats to include

- A local concept is not the same as an editable Canva template unless Canva access/design link is provided.
- Confirm approved phone number, email, website, and preferred logo variant before print.
- Confirm brokerage/board compliance requirements before production.
- Do not invent contact details. Use placeholders and list them as missing if not found.

## Example final deliverables

- Print-size PNG: `/Users/admin/<brand>-sign-refresh/<brand>-for-sale-sign-concept-v1.png`
- PDF export: `/Users/admin/<brand>-sign-refresh/<brand>-for-sale-sign-concept-v1.pdf`
- Preview JPG: `/Users/admin/<brand>-sign-refresh/<brand>-for-sale-sign-concept-v1-preview.jpg`
- Design notes: `/Users/admin/<brand>-sign-refresh/design-notes.md`

## Pitfalls

- Broad `/Users/admin` file searches may time out. Narrow quickly to likely brand/workspace folders.
- Do not assume the first name-matched file is a good headshot. Many are documents or old shoot files.
- Do not treat an old/superseded team logo as the current one if a newer asset exists. Verify against the current brand guide.
- Do not open browser/desktop/localhost previews in Telegram context. Send `MEDIA:` paths or provide concise local paths instead.
- Do not finalize sign copy as print-ready if approved phone/email/compliance details are missing.
- If a background/subagent sign-concept run reports `'dict' object has no attribute 'lstrip'`, first check whether artifacts were already written before rerunning from scratch. This error can come from Elevate's delegation/reporting wrapper (`delegate_tool.py` calling `_looks_like_error_output(content)` then `content.lstrip()` on a dict child result), not the sign-rendering script. Verify `/Users/admin/.elevate/logs/errors.log` or `agent.log`, then search for recovered outputs such as the design notes, preview JPG, PDF, and the rebuild script in the output folder. Update the design notes with the actual wrapper diagnosis so the user is not told the design script failed when only result reporting failed.
