# Elevation CRM redesign — build spec (for Dart)

Handoff spec for wiring the four HTML mockups into the live Elevate app. The mockups are **interactive design specs**, not deployable pages — they run on fake data and their buttons only manipulate the DOM. This doc maps each screen to the existing code and lists what's new so nothing has to be reverse-engineered from the HTML.

## Deploy model
- Build into the **repo source** (`Dartagnan98/elevate-agent`, working copy `~/.elevate/elevate-current-src`), then merge — that's the durable path. Direct bundle edits get wiped on app auto-update.
- Web app is React/TSX under `cli/web/src/pages/real-estate-hub/`. Leads code already lives in `.../leads/`.

## The four mockups (design source of truth)
| Screen | Artifact |
|---|---|
| CRM Feature Map (wishlist) | claude.ai/code/artifact/ec53734b-5577-419c-81a7-8e5810bb431d |
| Leads list (opens on "Leads") | claude.ai/code/artifact/1222a009-6a26-45e5-a81e-5ac38d27c5ec |
| Contact card (opens on a lead) | claude.ai/code/artifact/9373134f-84b8-41a7-ae89-45bd73088f35 |
| Reporting | claude.ai/code/artifact/ef893533-804e-4c21-a6c3-8aac4186994f |

Brand tokens (already in mockups): navy `#182848`, terracotta `#C46340`, blue `#5E8AD0`; full light+dark token set in each file's `:root`.

---

## 1. Leads list  →  reskin `leads/` (mostly exists)
Existing files map almost 1:1:
- `components/leads-board.tsx` — root. Keep; restructure to the new section tabs.
- `components/leads-tabs.tsx` — currently Action board / Profiles / Templates / Sent / Didn't Send / Paid Ads. New tabs = **Leads / Templates / Sent / Didn't Send** ("Leads" = the old Profiles table merged with the action board's draft surfacing).
- `components/profiles-list.tsx` — the row list. `ProfileRow` already has avatar+heat, name+verified, email, phone, status pill, source, lastTouch, favorite star. Extend the row to the mockup: add the **pipeline-stage pill**, the **temperature tag**, and the **Next/AI cell** (draft-ready chip / next action). Row `onClick` opens the contact drawer (see §2).
- `components/action-queue.tsx` + `draft-row.tsx` — the AI-draft approval + **Approve & Schedule datetime picker already exist**. Reuse `draft-row.tsx`'s scheduler for the mockup's inline "Send later" (default tomorrow 9am, validate future → UTC). The inline draft on a row = the same edit/send/skip/schedule flow surfaced in-row instead of a separate queue.
- `components/sent-view.tsx`, `not-sent-view.tsx`, `templates-view.tsx` — power the **Sent / Didn't Send / Templates** tabs. Already exist; restyle to the mockup's list rows.
- `leads-data.ts` / `use-leads-board-data.ts` — types + data hook.

New on this screen:
- **Three-axis filter** (Source / Pipeline / Temp) as side-by-side dropdowns + a **Filters popover** (adds Tags multi-select) + **name search**. State is unified — a pick in the popover and the dropdown reflect each other.
- **Bulk actions bar** on checked rows: Mass Email, Mass Text, Assign to agent, More → Change Pipeline / Segments / Tags, Send to Dialer (Postcards/Letters = "soon"). Wire to existing send engine + a bulk-update endpoint.
- **+ Add New** menu: New lead / New pipeline stage / New segment / New tag (custom stages+segments are per-account config).
- Drafting/voice: reuse the existing **outreach/voice skill + approval-gated send path** (`next_retry_at`), not a generic model.

## 2. Contact card  →  `components/profile-drawer.tsx` (exists as a drawer)
The mockup is the full-page version of the existing profile drawer. Build to it:
- Identity, consent-to-contact (CASL), tasks, appointments, family/relationships.
- **Threaded Notes** — upgrade the single owner-notes field to a timestamped thread with single-pin-to-top + quick-add from the compose box.
- **Activity timeline** — stitch texts (128k msg history) + calls + notes + searches + deal changes into one feed.
- **Compose** with Note / Text / Email toggle (same send engine, both channels).
- **Tags** (grouped: Property needs / Financial / Location / Relationship / Buying window / Mortgage renewal) + add-your-own. Tags are where filtering on the list keys off.
- **Add to Top 25** button — flags the contact into the account's **Top 25 list**, which surfaces on the admin board as its own Top 25 dashboard. Toggle sets a `top25` flag on the contact (with a visible badge on the card); the admin Top 25 view filters `WHERE top25 = true`. Comes from her follow-up system (hot leads → Top 25 for special care).
- Tabs: Overview + **Searches** (saved criteria) are built; **Properties / Documents / Automations** are intentional "under construction" stubs (Properties = engagement history; Automations = drip campaigns) — build later.

## 3. Reporting  →  NET-NEW page under `real-estate-hub/`
No existing equivalent. Charts in the mockup are hand-built inline SVG (funnel/bars/area/combo helpers) — reimplement with the same specs (or a lib, but keep single-axis, colorblind-safe, light+dark). Sections:
- KPI tiles in flow order: New leads → Calls → Texts → Emails → Appointments booked → Lead→client.
- **Goal setting**: modal (leads/appointments/closings/GCI targets) + Goal-progress bars (% to goal). Store goals per-account.
- **What it takes** calculator: reverse the funnel's real conversion rates from the closings goal → required leads/conversations/appointments + per-day conversation number. Recomputes on goal change.
- Lead-to-close funnel (Leads → Conversations → Appointments → Clients → Under contract → Closed) w/ step %.
- Conversion by source, Where closed deals came from, Marketing spend (per-channel $, cost per lead/deal).
- Leads & sales over time — leads area + closings overlaid (dashed, own visual band, real labels), + Year-over-year tab.
- Pipeline value + closed-deal $ intentionally NOT here (live on admin page).

---

## Data model additions (shared)
- **Segments** (time-horizon): Hot 0-30 / Warm 30-90 / Lukewarm 90-180 / Cool 180-365+ / SOI / Nurture. New contact field (or derive from days-since-activity + relationship). Source of truth: `reference_lead_follow_up_segments`.
- **Pipeline stages**: New Lead / Attempted Contact / Prospect / Client / Pending Deal / Closed / Referred / Realtor Contact / Trash. Align `LeadsProfile.status` to these; support custom stages.
- **Sources**: add YouTube, Door knocking, Sign call, Realtor.ca to the existing source set (Apple Messages / Composio-gmail / Composio-instagram / Lofty / paid / website / referral). Keep leads-list and reporting source lists in sync.
- **Tags**: new multi-value field on contact; feed the leads-list tag filter + contact-card tag section.
- **Goals**: new per-account table (leads/appts/closings/GCI targets); read by reporting + admin.
- **Appointments**: tracked entity so the Conversations → Appointments → Clients → Closed chain is real (drives funnel + the calculator).

## Suggested build order
1. Leads list reskin (biggest reuse) + contact drawer to match — the daily-driver.
2. Data model: segments + pipeline stage alignment + tags + new sources.
3. Reporting page (net-new) + goals storage.
4. Bulk actions + custom stages/segments.
5. Deferred: Properties, Documents, Automations panels; drip-campaign builder.

## Open items flagged in the mockups (toast stubs today)
- Change Pipeline / Segments / Tags bulk pickers (currently confirmation toasts).
- Add-lead form.
- Real date-range on reporting (changes the numbers).
