# Skyleigh Card Extraction

Captured: 2026-06-20

This folder is an extraction-only snapshot of Skyleigh's card work. It is meant
to preserve the full work before any wiring, rebasing, or behavior changes in
the Elevate Agent repo.

No app source files are changed by this extraction. The artifacts here are
patches, metadata, and full file snapshots.

## Sources

### Elevate Agent card work

- Source host: `Skyleighs-MacBook-Pro.local`
- Source path: `/Users/admin/.elevate/elevate-current-src`
- Source branch/head: `main` at `0056717e85b2b52035dc250366b62dd2aedb15a8`
- Artifact patch: `elevate-agent/cards.patch`
- Full snapshots: `elevate-agent/snapshots/`
- Captured diff size: 6 files, 822 insertions, 572 deletions
- Remote checks at capture time: web TypeScript `PASS`, Python AST parse `PASS`

Changed files captured:

- `cli/elevate_cli/admin_deal_flow.py`
- `cli/elevate_cli/web_auth.py`
- `cli/elevate_cli/web_routes/admin_deals.py`
- `cli/web/src/pages/real-estate-hub/admin/admin.css`
- `cli/web/src/pages/real-estate-hub/admin/components/admin-board.tsx`
- `cli/web/src/pages/real-estate-hub/admin/components/deal-modal.tsx`

What this contains:

- A redesigned admin deal score-card modal.
- Top 25 pin/filter behavior.
- Accepted-offer and counterparty data fields.
- CMA PDF endpoint and token-in-query allowance for that endpoint.
- Document tray UI.
- Local checklist state keyed by deal id.

### ElevateOS operational-card/collapse work

- Source host: `Skyleighs-MacBook-Pro.local`
- Source path: `/Users/admin/elevateos`
- Source branch/head: `main` at `97914f620b114540075775e867800889e97bb6de`
- Existing-file patch: `elevateos/deals-page.patch`
- New-file patch: `elevateos/new-files.patch`
- Full snapshots: `elevateos/snapshots/`
- Remote checks at capture time: TypeScript `PASS`

Files captured:

- `dashboard/src/app/(dashboard)/deals/page.tsx`
- `dashboard/src/app/api/realestate/deals/[id]/collapse/route.ts`
- `dashboard/src/components/realestate/deal-collapsed-button.tsx`
- `dashboard/src/lib/realestate/operational-deals.ts`

What this contains:

- Operational property score-card columns.
- A collapse button component.
- Stage reset logic for seller and buyer operational flows.
- A Next API route that shells out to the installed Elevate Python runtime.

## Porting Order

1. Review patches and snapshots side by side against current `main`.
2. Port static score-card layout and CSS first, with no backend changes.
3. Port modal section rendering and read-only data display.
4. Wire Top 25 pinning to the existing Elevate Agent admin deal API.
5. Add CMA PDF route/auth allowance with backend tests.
6. Add document tray behavior.
7. Convert collapse/relist behavior from the `elevateos` Next route into native
   Elevate Agent FastAPI/data-layer code before wiring buttons.
8. Add tests and run UI smoke before any release build.

## Known Risks To Resolve Before Wiring

- `Collapse Sale` and `Cancel / Relist` must not remain visual-only buttons.
- The extracted checklist uses `localStorage`; decide whether production needs
  backend-persisted checklist state instead.
- The Elevate Agent source snapshot was taken from an older head than our local
  `main`; apply selectively instead of wholesale.
- The `elevateos` collapse route shells out to an installed app Python path.
  In Elevate Agent this should become an internal route/service call.
- The CMA PDF query-token exception should stay scoped only to the PDF route.

## Useful Files

- `elevate-agent/metadata.txt` records source git state, diff stats, and checks.
- `elevate-agent/cards.patch` is the full Skyleigh Elevate Agent diff.
- `elevate-agent/snapshots/` contains complete changed files from that repo.
- `elevateos/metadata.txt` records source git state, relevant status, and checks.
- `elevateos/deals-page.patch` captures the tracked dashboard page diff.
- `elevateos/new-files.patch` captures the three untracked new files.
- `elevateos/snapshots/` contains complete captured files from `elevateos`.
- `SHA256SUMS` records content hashes for the captured artifacts.
