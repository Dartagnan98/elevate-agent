# Elevation validation — September 14, 2026

This review covers the accumulated Elevation branch, including the September
update snapshot `49d2d7fa` and the validation fixes that follow it. The fork's
`main` at `3028ae9e` predates the update snapshot by 420 commits, so the pull
request includes earlier branch history as well as the 156-file September update.
Work was isolated from the live source checkout.

## Application fixes

- Postgres memory results now serialize timestamps and numeric aggregates
  correctly. Duplicate facts handle the operational-store shim's wrapped
  uniqueness error without hiding unrelated integrity errors.
- Contact edits, deletion, outbound activity updates, and conversation status
  changes use the operational data layer. Real Postgres endpoint tests verify
  contact edits, deletion cascades, and preservation of unrelated contacts.
- Database-bound dashboard handlers run in FastAPI's worker threads instead of
  blocking its event loop. The route guard now follows nested routers, so it
  checks the actual mounted endpoints.
- The Today activity summary uses one reference time for its calculations.
- Dashboard actions use the existing accessible confirmation dialog. Pending
  confirmations cancel on navigation, and deposit/save/scheduling errors appear
  in the page instead of browser alerts or silent failures.
- Failed Vercel sandbox startup immediately stops and closes the sandbox without
  snapshotting an incomplete environment. Regression tests cover both startup
  timeouts and initial file-sync failure.

## Test repairs

API tests now exercise the generated-key authentication contract while retaining
missing/invalid-key rejection and bind-address checks. Gateway fixtures initialize
the current runner state, use canonical commands, and explicitly opt into automatic
tool selection where that behavior is under test.

Workflow tests preserve explicit human stage movement: clearing a gate makes a
deal eligible to advance without automatically moving it. Other stale expectations
were aligned with the current buyer stages, free-search fallback, and dashboard
design tokens. Operational-store tests use isolated accounts and Postgres-returned
IDs. File-tool fixtures write to temporary paths outside the protected checkout.

The earlier Telegram retry hang and listing-preview fixture failures are also
repaired. Route and caller inventories have been regenerated.

## Validation

- Frontend: **205 tests passed across 41 files**.
- Production TypeScript/Vite build: **passed**.
- Contact write/delete regression tests: **3 passed**.
- Sandbox and migration persistence checks: **27 passed**.
- Full backend: **18,354 passed, 0 failed, 0 errors, 271 skipped** in 9 minutes 5 seconds.

The backend runs use the canonical `scripts/run_tests.sh` wrapper with four
workers, isolated startup/test directories, credential variables removed, UTC,
and a 120-second per-test timeout. Missing declared development packages were
provided through a separate import path; the live application's Python
environment was not modified.

The final full run sets `ELEVATE_PG_CLEANUP=delete` for disposable test databases.
The two tests that deliberately restart Postgres to check persistence explicitly
use `stop` so their data remains available. Earlier attempts exhausted disk space
or were stopped before exhausting it; they are not counted as successful full
runs. Test logs and JUnit reports are retained outside the source tree.

The wrapper excludes integration/E2E directories and tests marked integration.
Optional dependency and platform skips do not establish coverage of those
features. This validation does not include a live deployment or external-service
end-to-end checks.
