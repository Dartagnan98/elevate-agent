---
name: forms-version-monitor
description: "Keep a BC realtor's local approved-forms register current against official notices. Use when the realtor asks about local approved forms, stale-form risk, BCREA/BCFSA/board form changes, or whether a local form can replace WEBForms/TransactionDesk when 2FA blocks it."
metadata:
  elevate:
    tags: [real-estate, forms, compliance, bcrea, bcfsa, interior-realtors, watchdog]
    runtime:
      approval_required: false
---

# Forms Version Monitor

Use this skill whenever the realtor asks about local approved forms, stale-form risk, BCREA/BCFSA/board form changes, or whether a local form can be used instead of WEBForms/TransactionDesk.

Operational preference for this pattern: **local approved forms are the source of truth**, not WEBForms/TransactionDesk, when WEBForms two-step authentication repeatedly blocks workflows. The compliance guard is not "use WEBForms"; the guard is "verify and maintain the local approved-forms library against official update notices."

## Source Priority

1. Local approved-forms library / form-version register, once verified.
2. BCREA form launch/release notices in Gmail and BCREA website pages.
3. BCFSA advisories, bulletins, Knowledge Base updates, and clause/disclosure guidance.
4. Association of Interior REALTORS notices for local/board rules, InterLink/WEBForms access, association forms, and MLS rules.
5. WEBForms/TransactionDesk only as an optional cross-check when accessible, not as the day-to-day source of truth.

## Existing Watchers

- Gmail watcher script: `~/.elevate/scripts/form_notice_watchdog.py`
- Website watcher script: `~/.elevate/scripts/form_website_watchdog.py`
- Weekly Gmail cron job: `BC forms/compliance notice watcher`, schedule `0 9 * * 1`. Check `cronjob(action="list")` for the current job id on this box.

The watchers are designed to stay silent unless they detect a new relevant notice.

## Gmail Monitoring Queries

Monitor messages from:

- `bcrea@bcrea.bc.ca`
- `info@bcfsa.ca`
- `admin@interiorrealtors.com`
- `members@interiorrealtors.com`
- `listings@interiorrealtors.com`
- `support@interiorrealtors.com`

Key terms:

- Standard Forms, forms launch, forms release, revised forms, updated forms, new forms
- Contract of Purchase and Sale, Multiple Listing Contract, Exclusive Listing Contract
- Property Disclosure Statement, No Disclosure Statement, material latent defects
- Disclosure of Representation, expected remuneration, multiple offers
- contract clauses, clause templates, BCFSA Knowledge Base
- WEBForms, TransactionDesk, CREA WEBForms

## Website Monitoring Targets

The website watcher currently checks:

- BCREA Standard Forms resources: `https://www.bcrea.bc.ca/bcrea-access/standard-forms/`
- BCREA Fall Standard Forms Launch resources: `https://www.bcrea.bc.ca/bcrea-access/standard-forms/fall-2025-standard-forms-launch-resources/`
- BCFSA Real Estate Professional Resources: `https://www.bcfsa.ca/industry-resources/real-estate-professional-resources`
- BCFSA Knowledge Base advisory search for clauses
- BCFSA news search for forms and clauses
- Association of Interior REALTORS home/news surface: `https://www.interiorrealtors.ca/`

Pitfall: BCREA and board pages may block unauthenticated/script access. That does not make the workflow failed because Gmail notices are the stronger source. If a page blocks, record the blocker and rely on Gmail notice monitoring unless the realtor provides login/browser access.

## When a New Notice Is Found

1. Read the full Gmail message or changed website page.
2. Extract:
   - issuing organization
   - date
   - subject/title
   - affected form(s)
   - effective date
   - whether forms are new, revised, retired, or guidance-only
   - links to launch package/resources
3. Compare against the local approved-forms register.
4. If a local form may be stale, mark it **not safe for signature-ready use** until updated.
5. Create a concise task for the required update:
   - download/acquire new approved blank
   - update fill mapping
   - run test fill
   - verify no helper/green placement text
   - update local version register
6. Do not silently keep using the old local blank.

## Seeding Local Forms From SkySlope Archives

When the realtor asks to seed the local approved-form library from broker-approved firm/sold contracts:

1. Open SkySlope and use **More → Access Archives** or navigate to `https://app.skyslope.com/AccessArchive.aspx`.
2. Pull only firm/sold/archive files that passed broker/compliance approval.
3. Prefer the most recent files **after the last known BCREA/BCFSA form update** for that form family.
4. For each archive contract/package, download the final broker-approved PDFs and extract:
   - property type: single-family/freehold, strata, manufactured/mobile on rental site, leasehold, commercial, etc.
   - base form name and visible revision/version date
   - clause/subject wording actually used
   - file approval context/date and transaction close/firm date
5. Cross-reference against known updates before treating a clause/form as reusable, using the most recent BCREA/BCFSA standard-forms launch and clause-template advisories on record.
6. Store base forms separately from clause packs. Do not make one CPS template solve every scenario.
7. If the archive contract predates a known update for that form or clause family, mark it `reference_only` unless the realtor/managing broker confirms the wording is still approved.

## CPS Clause-Pack Model

Use this structure for CPS work:

- **Base form**: the approved official contract form family.
  - CPS Residential: single-family and most strata residential deals.
  - CPS Manufactured Home on Rental Site: mobiles/manufactured homes on pad/rental site.
  - Other base forms only when the property/transaction type requires them.
- **Clause pack**: the approved conditions/subjects for the property and offer scenario.
  - single-family/freehold buyer subjects
  - strata buyer subjects
  - manufactured/mobile-home buyer subjects
  - cash/subject-free variants
  - seller accepted-offer disclosure package
- **Deal-specific terms**: price, dates, deposit, included/excluded items, property-specific documents, and any realtor-directed wording.

Never invent legal clauses from scratch. Reuse realtor-approved templates, broker-approved archive wording, BCFSA/BCREA clause templates, or clauses from a prior contract the realtor identifies.

## Local Approved-Forms Register

Maintain a register with these fields for every form used locally:

```json
{
  "form_name": "",
  "local_path": "",
  "issuer": "BCREA|BCFSA|AIR|eXp|Other",
  "revision_date_or_version": "",
  "last_verified_at": "",
  "verification_source": "Gmail notice / website URL / launch package / WEBForms optional cross-check",
  "safe_for_signature_ready_use": true,
  "notes": ""
}
```

If no register exists yet, create one before expanding local forms. Suggested path:
`<elevate-home>/data/forms/local-approved-forms-register.json`

## Archive Seed Workflow Details Learned

The SkySlope Access Archive checklist download is a practical way to seed the local library when WEBForms/TransactionDesk is blocked:

1. In `AccessArchive.aspx`, each row's dropdown can export **Checklist Documents** as a ZIP. Browser download routing may ignore CDP download settings and land in `~/Downloads`, so verify/copy files manually after each download.
2. Copy archive ZIPs into:
   - `<elevate-home>/data/forms/skyslope-archive-seed/zips/`
3. Extract into:
   - `<elevate-home>/data/forms/skyslope-archive-seed/extracted/`
4. Use `pdfinfo` and `pdftotext` to classify extracted PDFs, extract visible form revision codes, and compute SHA256s. Build a small manifest script for this if one does not already exist; promote or recreate that logic if repeating the workflow.
5. Write/update:
   - `<elevate-home>/data/forms/skyslope-archive-seed/archive-seed-manifest.json`
   - `<elevate-home>/data/forms/local-approved-forms-register.json`
   - `<elevate-home>/data/forms/local-approved-clause-register.json`
6. Archive contracts are **seed references only**, not clean blanks. Register entries seeded from archives should stay:
   - `safe_for_signature_ready_use: false`
   - `status: seed_reference_only_pending_blank_template_and_fill_mapping`
   until a clean blank/template and fill mapping are verified.

Seed packages typically cover a mix of property types, for example:

- A strata residential file: Residential CPS + Strata PDS + Disclosure of Remuneration/DORT/PNC.
- A manufactured/mobile home on a rental site: Manufactured Home CPS + Manufactured Home on Rental Site Addendum + Residential PDS/PNC + MHR + park rules + Disclosure of Remuneration/DORT.
- A single-family/freehold file: CPS + Disclosure of Remuneration + DORT + PDS + PNC. CPS revision extraction may require manual review because `pdftotext` classification does not always reliably capture the visible revision code.

Pitfalls from a first seeding run:

- SkySlope direct username/password login may fail even when credentials are updated; the reliable route is the realtor manually logging into the connected browser session, then navigating to `https://app.skyslope.com/AccessArchive.aspx`.
- Never print or store the SkySlope password; credential values must remain redacted.
- Some PDFs contain text that confuses classification, for example a mobile package file may classify as MLC while adjacent CPS/addendum files are present. Manually inspect ambiguous files before updating the register.
- File names alone are not enough. Use extracted text, visible revision codes, package context, SHA256, and archive close/firm dates.

## Signature-Ready Rule

A local form can be used for signature-ready packages only when:

- it is listed in the local approved-forms register,
- its revision/version has been verified against recent official notices,
- there is no unresolved notice indicating it changed after the verified date,
- fill mapping has been tested on the current blank,
- output has been checked for missing fields, wrong signature blocks, and helper/placement text.

If any check fails, prepare only an internal worksheet or stop with `waiting_human` / update-needed status.

## Commands

Run Gmail watcher manually:

```bash
~/.elevate/scripts/form_notice_watchdog.py
```

Run website watcher manually:

```bash
~/.elevate/scripts/form_website_watchdog.py
```

List cron jobs:

```python
cronjob(action="list")
```

## Output Shape

Return concise status:

```json
{
  "status": "done|partial|waiting_human|failed",
  "new_notices": [],
  "affected_forms": [],
  "local_forms_marked_stale": [],
  "register_updates": [],
  "next_tasks": []
}
```

## Tracking Known Notices

Keep a running log of confirmed BCREA/BCFSA/board notices as they are found, each with issuing organization, date, subject/title, affected forms, and effective date. Typical notice types to expect: a standard-forms launch (new/revised CPS, listing contract, or disclosure forms made available on CREA WEBForms plus a launch package/resources page), a contract clause template advisory (updated clauses in the BCFSA Knowledge Base and CREA WEBForms), and a disclosures/material latent defects guidance update (revised PDS guidance/forms, a Property No Disclosure Statement, or changed material latent defect disclosure requirements).
