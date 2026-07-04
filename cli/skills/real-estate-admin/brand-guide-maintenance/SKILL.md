---
name: brand-guide-maintenance
description: "Patch stale brand-guide paths and config references across skills/templates. Use when the user asks where the brand guide is used, notices marketing/email/social/sign/CMA output is off-brand, or a brand rule changes."
triggers:
  - User asks where branding guides are connected or used.
  - User asks to update brand rules across skills/templates.
  - User notices marketing/email/social/sign/CMA outputs are off-brand.
  - A new brand preference is learned.
---

# Brand Guide Maintenance

Use this to keep the brand source of truth and the skill layer aligned.

## Source of truth

Primary local brand guide, at a path such as:

`<elevate-home>/knowledge/brand-guide.md`

Current brand overrides should live near the top of that file, above any older scraped/legacy guide content. The guide should include, at minimum:

- Primary and secondary brand colors (hex values)
- Background/paper colors
- Display heading font
- Body copy font for landing pages and branded marketing emails
- Body font for social graphics
- The realtor's brokerage-compliance logo asset path
- Any scope note distinguishing client-facing brand voice from internal/coaching or brokerage-attraction content

## Audit steps

1. Search active skills for brand references and stale paths.

   Use `search_files` or `execute_code` against the active skills directories (local skills plus any cloud/synced skills directory).

   Search terms:

   - `brand-guide.md`
   - `brand guide`
   - the guide's configured path, and any known legacy/stale path
   - `config/realtor.json`
   - the current brand's hex color values
   - the current brand's display/body font names
   - the brokerage-compliance logo reference

2. Ignore backups/runtime copies unless explicitly asked.

   Exclude obvious non-active paths:

   - `skill-backups/`
   - `skills-backups/`
   - `pre-update-safety/`
   - `runtime-overrides/`
   - parked updater/app bundle copies
   - one-off incident/guard skills unless the brand issue is actually inside those guards

3. Identify four categories.

   - Direct current guide references: skills that point to the current brand-guide path.
   - Embedded style rules: skills that mention colors/fonts/logo rules but do not read the guide.
   - Stale config-as-brand references: skills that still say brand colors/fonts come from `config/realtor.json`, `brand.colors`, or `brand.fonts`. Keep `config/realtor.json` references for domains, channels, brokerage identity, geography, and deploy settings; only replace the color/font/style source.
   - Hard-coded script styling: scripts that hard-code brand CSS/colors/fonts.

4. Patch active skills when useful.

   If a skill uses a stale brand-guide path, patch it to the current guide path.

   If a skill says brand colors/fonts come from `config/realtor.json`, patch that line to say they come from the current brand guide plus the current brand's aesthetic, while leaving non-brand config uses alone.

   If a skill only embeds style tokens, add a concise line saying to use the current brand guide as the base source when exact tokens are needed, then apply the current brand's overrides.

5. Update the brand guide itself when the user gives a durable brand preference.

   Patch the brand guide directly. Keep the current override section concise and operational, not a long history.

6. Verify.

   Re-run searches to confirm no active skill still points to stale brand-guide paths. Read the changed lines back before reporting.

## Known active brand-related skill categories

These should stay aligned with the guide: marketing/newsletter/content skills, landing-page skills, client-vault or resource skills, subject-removal or transaction-document skills that render branded output, social-content batching, offer-review, sign-concept/template skills, and any listing-marketing render skill (thumbnails, feature sheets, mailer templates).

## Reporting format

Report briefly:

- Brand guide source path.
- Skills patched or confirmed.
- Stale references removed.
- Anything intentionally left alone, especially script hard-coding that would require a bigger refactor.

## Pitfalls

- Do not edit files inside app bundles or parked updater copies.
- Do not treat old backups as active skills.
- Do not overwrite all skill references to `config/realtor.json`; some references may still be correct for channels/domains/identity. Only replace brand/color/font usage when the brand guide is the better source.
- Do not rewrite generated marketing scripts unless the user asks for a refactor. Many scripts hard-code styling and changing them can alter live deliverables.
