# Elevation CRM redesign — handoff package

Four HTML mockups + a build spec for wiring them into the live Elevate app.

## Files
| File | What it is |
|---|---|
| `01-leads-list.html` | Leads list page (opens on "Leads") — filters, sections, bulk actions, inline drafts |
| `02-contact-card.html` | Contact/client card (opens on a lead) — notes, tags, searches, Top 25 |
| `03-reporting.html` | Reporting dashboard — goals, funnel, conversion, marketing ROI, activity calculator |
| `BUILD-SPEC.md` | How to wire each screen to existing Elevate code + what's new |

Open any `.html` in a browser to see it live and interactive (light + dark, hover tooltips).

## Live interactive versions (same mockups)
- Feature Map (the wishlist / plan): https://claude.ai/code/artifact/ec53734b-5577-419c-81a7-8e5810bb431d
- Leads list: https://claude.ai/code/artifact/1222a009-6a26-45e5-a81e-5ac38d27c5ec
- Contact card: https://claude.ai/code/artifact/9373134f-84b8-41a7-ae89-45bd73088f35
- Reporting: https://claude.ai/code/artifact/ef893533-804e-4c21-a6c3-8aac4186994f

## For the developer
These are **design specs, not deployable pages** — they run on fake data. Read `BUILD-SPEC.md` first: it maps each screen to the existing React code under `cli/web/src/pages/real-estate-hub/leads/` and lists the data-model additions. Build into the `elevate-agent` repo source and merge (not the app bundle — bundle edits get wiped on update).
