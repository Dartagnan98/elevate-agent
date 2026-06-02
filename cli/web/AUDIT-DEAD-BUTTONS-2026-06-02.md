# Dead Button Audit — Today / Leads / Admin / Social (2026-06-02)

Live render path per tab confirmed. Orphan/legacy files noted but not the live UI.

## TODAY (`pages/real-estate-hub/today/components/today-board.tsx` is live)
Orphans (not rendered): priority-queue, pulse-strip, intelligence-strip, day-shape, data.ts.

| Element | Line | State | Fix target |
|---|---|---|---|
| **Deal cards** (`DealCard`/`ActiveDeals`) | 742/770/783 | DEAD — non-interactive `<article>` | Open Admin `DealDetailModal`. Carry `AdminDeal` through, map `currentStage`→phase id. |
| "Open leads" | 273 | DEAD — `href="#/leads"` (BrowserRouter, no route) | `<Link to="/leads">` |
| "Open queue" | 574 | DEAD — `href="#/leads"` | `<Link to="/leads">` |
| "Open admin" | 778 | DEAD — `href="#/admin"` | `<Link to="/admin">` |
| "All sources" | 854 | DEAD — `href="#/leads"` | `<Link to="/leads">` |
| "Full calendar" | 646 | DEAD — `href="#"` | `<Link to="/schedule">` |
| "Open"/"Settings"/"View all"/"7-day trend" | 436,466,505,702,722 | DEAD — `href="#"` | Best-available real surface (admin/leads/schedule) or `<Link>` |
| "Approve all" | 573 | DEAD — no onClick | loop drafts → `onDraftAction("approve",id)` |
| "Edit" (per draft) | 615 | DEAD — no onClick | expand row / route to /leads |
| Skip / Approve & send | 612/616 | WIRED | — |
| `onRefresh` prop | — | orphaned (no button) | render a refresh button or drop |

## LEADS (`leads/components/leads-board.tsx` live; `onboarding.tsx` fully wired)
| Element | Line | State | Fix target |
|---|---|---|---|
| Header **Refresh** | 1234 | DEAD — shell never passes `onRefresh` | pass `onRefresh` from LeadsDesignShell |
| **New lead** | 1236 | DEAD — no onClick | no createLead endpoint → `<Link to="/config#connectors">` (add source) |
| Connect-more chips | 134 | DEAD | `<Link to="/config#connectors">` |
| Open Settings (alert) | 240 | DEAD | `<Link to="/config#connectors">` |
| edit template link | 287 | DEAD (stopProp only) | switch to Templates tab |
| Bulk **Skip** | 420 | DEAD | loop selected → `onDraftAction("skip")` |
| Bulk **Approve {n}** | 421 | DEAD | loop selected → `onDraftAction("approve")` |
| Hot **Draft reply** | 465 | DEAD | open ProfileDrawer (compose) |
| Hot **Open thread** | 466 | DEAD | open ProfileDrawer |
| Skipped **Undo** | 486 | DEAD | `onDraftAction("restore"/"pending")` |
| Templates **Suggest variant** | 840 | DEAD | `api.suggestOutreachTemplate` |
| Templates **New template** | 861 | DEAD | open editor → `api.createOutreachTemplate` |
| Template **Pause/Edit/Delete** | 809-811 | DEAD | `api.updateOutreachTemplate` / `deleteOutreachTemplate` |
| Sent **Refresh** | 895 | DEAD | re-fetch sent |
| Sent include-queued | 890 | cosmetic no-op | wire filter or drop |
| Status pill change | 594/1031 | local only (not persisted) | flag (no contact-status endpoint) |

## ADMIN (`admin/components/admin-board.tsx` + `deal-modal.tsx` live)
Legacy `RealEstateAdminPageLegacy` (index.tsx, `void`'d) = dead code but holds working handlers to port.
| Element | Line | State | Fix target |
|---|---|---|---|
| **New deal** | admin-board 721 | DEAD — no onClick | open new-deal dialog → `api.createAdminDeal` |
| **Search deals** | 777 | DEAD — query state unused | filter `activeDeals` by query |
| DealCard keyboard | 185 | tabIndex, no onKeyDown | add Enter/Space → onOpen |
| Modal **Advance phase** | deal-modal 217 | DEAD | `api.advanceDeal` |
| Modal **Force advance** | 220 | DEAD | `api.advanceDeal(force)` |
| Modal **Dates/Attach/Co-contact** | 381/385/389 | DEAD | `updateDealFields`/`addDealAttachment`/`addDealContact` |
| Modal condition enums/toggles | 526/537 | DEAD | `api.setAdminDealToggle` |
| Connector "Ask the coach" | index 1944 | inert (no-op openCoach) | wire openCoach in AdminDesignShell |
| Refresh / Re-run onboarding / Tabs / Top25 | 717/720/766/733 | WIRED | — |

## SOCIAL (`social/board.tsx` live) — healthiest
| Element | Line | State | Fix target |
|---|---|---|---|
| "Generate now" | 178 | mislabeled (only refetches) | relabel "Check again" (no generate endpoint) |
| Range pill chevron | 421 | decorative `<span>` w/ chevron | drop chevron (real control = Lookback select) |
| everything else | — | WIRED | — |

## Confirmed API methods (lib/api.ts)
suggestOutreachTemplate, createOutreachTemplate, updateOutreachTemplate, deleteOutreachTemplate, approveOutreachTemplate, advanceDeal, createAdminDeal, updateDealFields, addDealAttachment, addDealContact, setAdminDealToggle, moveAdminDeal, getAdminDeals, getDealContext, updateSourceInboxDraft, socialIdeaAction, refreshSocialMetrics.
No endpoint exists for: manual create-lead, persist-contact-status, generate-ideas-now → wire to nearest real surface.
