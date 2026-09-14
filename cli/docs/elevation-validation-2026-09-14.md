# Elevation validation — September 14, 2026

This review covers the accumulated Elevation source branch and the latest update
snapshot, `49d2d7fa`. Its preceding snapshot is `40121931`. The fork's `main`
(`3028ae9e`) is an ancestor, 420 commits behind the update snapshot, so the pull
request includes earlier accumulated work as well as the 156-file September
update. The separate validation checkout preserves newer work in the live source
folder.

## Validation fixes

- Telegram conflict tests previously replaced every `asyncio.sleep` with an
  immediate mock. The background agent refresh loop could then run forever
  without yielding. The tests now skip only retry backoff, preserve normal
  cooperative waits, await the actual scheduled retry, verify polling restarted,
  and disconnect the mock adapter. Six tests finish in under a second.
- Two new listing-preview tests failed before reaching preview generation because
  their deliberately minimal database mock did not provide title-preparation
  facts. These preview tests now begin at the prepared-listing boundary. The
  separate real endpoint test still verifies that missing title evidence blocks
  signature preparation. All 34 kit, MLC handoff, and title checks pass.

No application behavior was changed by these validation fixes.

## Baseline comparison

The initial full backend attempt stopped at 96% with 189 failures and a collection
error. Of those failures, 187 tests also exist in `40121931`: 180 failures reproduced
there, while seven passed in the focused baseline run. The two tests introduced by
the latest snapshot were the listing-preview fixtures repaired above.

The seven differing results were checked again on the current snapshot. Six pass
when run in isolation. The remaining file-patch hint test also fails when run alone
on the baseline: its relative path resolves inside the protected source checkout.
These outcomes point to test order/environment sensitivity, rather than a new
application regression in the September update.

The MCP collection error also reproduces on the baseline. The existing Python
environment lacks `mcp`, which is already declared in the development dependencies.
Installing only missing test packages in an isolated import path resolves MCP
collection and its focused tests without changing the application's environment.

The prior frontend run passed 198 tests and failed four. All four failure names
also reproduce on `40121931`; the targeted baseline frontend run had seven failures
across those same four test files. The production TypeScript/Vite build passed.

## Full backend follow-up

The canonical `scripts/run_tests.sh` wrapper completed in 10 minutes 19 seconds:
**18,132 passed, 187 failed, 272 skipped**, with no collection error or suite hang.
It used four workers, a separate startup `ELEVATE_HOME`, disposable test
directories, the missing MCP dependency, a 120-second per-test timeout, and JUnit
output. All 238 focused MCP/OAuth tests also pass.

Of the 187 full-run failures, 179 were already confirmed on the baseline. The
remaining eight tests were run on both snapshots with the same dependencies and
ordering: both produced five failures and three passes. This brings the total to
184 failures reproduced on the baseline. The three that fail in the full suite
but pass in the focused comparison on both snapshots are:

- `tests/gateway/test_usage_ledger.py::test_recent_turns_tie_breaks_by_newest_id`
- `tests/test_tui_gateway_server.py::test_prompt_submit_forwards_persist_user_message`
- `tests/tools/test_vercel_sandbox_environment.py::TestSnapshotPersistence::test_cleanup_stops_when_snapshot_fails_without_storing_metadata`

Those three remain unresolved full-suite/state-isolation issues. One reproduced
MCP image assertion is specific to macOS `/tmp` versus `/private/tmp` path spelling.
No remaining failure was reproducible only on the latest snapshot in these
comparisons; this does not establish that the branch is free of regressions.

## Merge status

Draft review is appropriate while the full-branch failures remain unresolved.
Confirmed older failures span API authentication expectations, gateway session and
prompt handling, memory/Postgres behavior, admin stage expectations, route
inventory, and tool behavior. Reproducing a failure on the baseline does not make
it acceptable or prove that it is only a test issue. The branch has not been merged
into `main`.
