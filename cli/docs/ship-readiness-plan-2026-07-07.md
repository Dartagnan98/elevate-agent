# Elevate Ship-Readiness Plan

**Baseline:** 1.2.63 · main @ `0b381cfb1` · generated 2026-07-07
**Source:** 7-dimension production-readiness audit (0 P0 · 5 P1 · 13 P2 · 4 P3). Every P0/P1 bug-class finding adversarially re-verified in code (4 confirmed, 1 refuted). The 10 first-to-build fixes were then spec'd against their real files.
**Companion visual:** artifacts — readiness console + gate board.

## The bar

Clear **Gate A + Gate B** and the product is defensibly production-ready for wider sale: **~7–11 focused dev-days.** C and D make it durable and run as fast-follow / standing policy.

Gates are ordered by *what they protect*, not just severity:

| Gate | Protects | Target | Effort | Blocking sale? |
|------|----------|--------|--------|----------------|
| A — Trust the data | no silent loss / corruption / dead-screen | 1.2.64 | ~2–3d | **yes** |
| B — Ship safely | can't ship a regression / can canary / see crashes / roll back | 1.2.65 → 1.3-beta | ~5–8d | **yes** |
| C — Harden | close divergence at source, security posture | 1.3.x | ~4–6d | no |
| D — Pay down | maintainability, at-rest secrets | continuous | policy + slices | no |

---

## Gate A — Trust the data  ·  target 1.2.64  ·  ~2–3 dev-days  ·  all parallel

**Pass criteria:** a customer can never be shown a truncated/stale transcript; memory recall never silently blanks or loses a write; retries never duplicate messages; a render error never leaves a dead white screen.

- [x] **A1 · Dual-store read completeness guard** — P1 · verified · 4–6h · risk MED · owner: core
  - Files: `cli/elevate_state.py` → `get_messages` (~2452), `get_messages_as_conversation` (~2774), `message_count` (~3362); new helpers `_sqlite_message_count` + `_pg_rows_or_sqlite_fallback`.
  - Do: add an index-only SQLite count; fall back PG→SQLite **only when `sqlite_count > len(pg_rows)`** (asymmetric — falling back on equal/less blanks legitimately-foreign PG sessions). One helper covers all three read sites. **Also fix co-located latent bug:** `get_messages_as_conversation` uses `if rows is None` (vs `if rows:` in `get_messages`), so an empty PG result silently returns an empty conversation — change to fall back on `rows is None or divergence`.
  - Risk: trust direction is the whole risk — a wrong rule returns empty for foreign sessions. Test **both** directions.
  - Test: session with N SQLite rows, monkeypatch PG to return N-1 → assert all N returned + divergence WARNING; PG returns full N → assert PG path used; SQLite empty + PG has 5 → assert 5 returned (not empty); lineage variant for `as_conversation`.
  - Note: does **not** cover `get_compression_tip` (that's C1 — walks lineage, opposite trust direction) or `replace_messages` (a write/source, made harmless by this read guard).

- [x] **A2 · Serialize holographic-memory reads under the store lock** — P1 · verified · 3–5h · risk LOW · owner: core
  - Files: `cli/plugins/memory/holographic/store.py` (add `_read()` helper near L490), `retrieval.py` (6 read sites: ~161, ~240, ~315, and the `_fts_candidates` / rollback paths).
  - Do: route every `FactRetriever` `conn.execute`/fetch (+ its rollback) through a `with self.store._lock:` helper. Keep the span tight — **not** over the Python scoring loops or the `semantic_search()` network call.
  - Why it's worse than "unlocked read": the reader's `rollback_quietly()` on the shared autocommit=False connection **aborts the main thread's uncommitted write** → silent memory loss (your stated concern). Option A (one lock) chosen over a dedicated reader connection: lower risk, sufficient.
  - Test: concurrency regression — one store, K background threads driving retrieval while the main thread writes; assert no `another operation in progress`, no lost writes, recall non-empty.

- [x] **A3 · Per-row flush-index advance (stop duplicate transcript rows)** — P2 · 1–2h · risk LOW · owner: core
  - Files: `cli/run_agent.py` → `_flush_messages_to_session_db` (loop 3814–3882, cursor set 3880, log 3882).
  - Do: advance `_last_flushed_db_idx` **per successful append** inside the loop (not once after the batch); raise the swallowed persist log above WARNING. No migration. Fully fixes within-run duplication.
  - Test: mock `append_message` to raise on message 3 of 5 → assert rows 1–2 persisted once, cursor at 2, retry does not re-insert 1–2.
  - Note: the durable belt (UNIQUE index + dedupe migration) is **C4** — ship A3 first so C4's migration runs against a no-new-dups baseline.

- [x] **A4 · React ErrorBoundary + global error toast** — P2 · verified · 3–5h · risk LOW · owner: frontend
  - Files: `cli/web/src/main.tsx` (L18, wrap root), `App.tsx` (route-level boundary), new `components/ErrorBoundary.tsx` + `components/GlobalErrorToasts.tsx`.
  - Do: two boundaries — root (whole-app) + route-level (a chat crash shouldn't kill the sidebar) — with a visible "Something went wrong — Reload" fallback; window `error`/`unhandledrejection` listeners. **No global toast bus exists** (`useToast` is per-component) → the listener ships its own small self-contained toast.
  - Test: node-env test asserts `getDerivedStateFromError` sets `{hasError:true}` and the fallback renders a reload button.

---

## Gate B — Ship safely  ·  target 1.2.65 → 1.3.0-beta  ·  ~5–8 dev-days  ·  ORDERED: B1 → B2 → (B3 ∥ B4)

**Pass criteria:** a broken commit can't reach a customer without failing a gate; a risky release hits an opt-in canary before the fleet; a crash is visible without SSH; a bad build can be rolled back.

- [x] **B1 · CI gate on push + PR** — P1 (corroborated ×2) · 4–8h · risk LOW · owner: infra (Will)
  - Files: new `.github/workflows/ci.yml` (~60 lines, 2 jobs) mirroring `cli/scripts/run_tests.sh` (which already documents the contract and references a not-yet-existing workflow).
  - Do: parallel jobs — pytest (hermetic; `conftest.py` already isolates ELEVATE_HOME/TZ/seed + scrubs creds) + skills lint; frontend `vitest`. **`behavioral_eval` needs a live provider login → keep as a local release precondition, NOT in stock CI** (or a self-hosted runner later).
  - Do first — it protects every change after it.
  - Test: open a PR that deliberately breaks a test (e.g. edit a route so `test_debug_route_inventory` drifts) → confirm red.

- [x] **B2 · Beta / stable release channels** — P2 · 1.5–2.5d · risk MED · owner: infra (Will)
  - Files: `desktop/src/updater.js` (`resolveChannel()` + set `autoUpdater.channel` before first check), `desktop/scripts/{merge-mac-feed,finalize-mac-dist,ship-to-hetzner}.js` (FEED name from `ELEVATE_RELEASE_CHANNEL`).
  - Do: one build → one notarized artifact set; channel = **which feed yml a box points at**. Publish `beta-mac.yml` beside `latest-mac.yml`; opt a box into beta via `~/.elevate/update-channel` (or env); soak; promote same artifacts to latest. Foundation + the real backstop for B3.
  - Test: `updater-behavior.test.js` — `resolveChannel` returns beta from env / file, latest when absent.

- [x] **B3 · Crash-on-launch update guard + documented rollback** — P1 · 1–1.5d · risk MED · owner: infra (Will) · soft-dep: B2 (both edit updater first-check path)
  - Files: `desktop/src/app-lifecycle.js` (47–62: move `kickoffUpdates` before `startDesktop`, try/catch both), `updater.js` (watchdog + `update-downloaded` auto-install, fired-once guard), `main.js` (isHealthy plumbing), `main-window.js` (markHealthy on did-finish-load).
  - **Reality:** `startup-log.js` `installMainCrashCapture` calls `app.exit(1)` on uncaught → a hard crash loop **cannot** self-heal in-process. This fix closes the "alive-but-broken/hung" class; the rollback path (pinned prior DMG on the feed — see `release-rollback-runbook.md` — + B2 canary) closes the rest. **Partial in code, closed by process.**
  - Test: `app-lifecycle.test.js` — throwing `startDesktop` stub → assert `kickoffUpdates` runs before it and sms/deeplink still fire.

- [x] **B4 · Electron crash / error telemetry (opt-in)** — P1 · 1.5–2d · risk LOW · owner: backend + desktop
  - Files: new `backend/src/app/api/diagnostics/crash/route.ts` (~90 lines, clone the hardened `session-events` route), extract `backend/src/lib/redact.ts`, new Supabase table `app_crash_reports`; `desktop/src/main.js` (POST uncaughtException/unhandledRejection).
  - Scope: **only the Electron main process is blind** — the Python CLI already ships `session_recorder.py` + opt-in `session_uploader.py`. Clone the existing auth-guarded, rate-limited, **PII-redacted** pattern; send `{version, arch, stack, startup-timeline}` — **never transcript content** (existing route deliberately forbids `stack`/`traceback` for PII → the crash route must redact paths/emails/keys itself).
  - Ties into Skyleigh's in-app bug-button → same pipe, so a manual report carries a stack.
  - Test: unit — rejects without access token (401), redacts `/Users/skyleigh/…` + email + `sk-…` from a stack.

---

## Gate C — Harden  ·  target 1.3.x  ·  ~4–6 dev-days  ·  fast-follow

**Pass criteria:** dual-store divergence closed at the source (not just masked on read); memory corrections not silently dropped; security posture holds under remote exposure.

- [x] **C1 · `get_compression_tip` PG-staleness — own analysis** — P2 · verified · 4–6h — `elevate_state.py:1626`. Walks the session **lineage**, not message rows; its own comment asserts the *opposite* trust direction (PG fresher). A1's count guard does not apply — resolve via dirty-flag/reconcile. Do not fold into A1.
- [x] **C2 · Auto SQLite→PG drift reconciliation** — P2 · 4–6h — `elevate_cli/data/_pg_drift_reconcile.py`. Logic exists but only runs manually. Wire the idempotent safe-direction backfill into gateway/app startup or a periodic task; surface a drift health metric.
- [x] **C3 · Near-dup fact merge — signal value corrections** — P2 · 2–3h — `holographic/store.py:1134`. "$500k"→"$750k" scores as near-dup and the new number is dropped while the agent is told it saved. Return `content_updated=false`, or treat numeric divergence as supersession.
- [ ] **C4 · UNIQUE index on messages + dedupe migration** — P2 · 4–6h · risk MED — `elevate_state.py` `_init_schema` (version-gated). The durable belt to A3. Risky: live DBs likely carry dups → per-DB backup + version-gated dedupe before the index. Ship after A3.
- [x] **C5 · Gateway self-heal off the main thread** — P2 · 3–5h — `desktop/src/gateway-self-heal.js`. Swap up-to-90s blocking `spawnSync` for async `spawn`. Already fire-and-forget off the startup path (lower urgency) but still freezes IPC/menus while it runs.
- [x] **C6 · Security posture for remote exposure** — P2/P3 · 1–2d — `license.py:210` (don't gate value on the unsigned license.json + add a CI guard that no bundled skill is locally-only entitlement-gated), `web_spa.py:56` (require real login for non-loopback exposure; keep PTY off the HTML-served token), `chat_websockets.py:129` (move the WS token out of the URL query string). Bounded today (paid content is server-gated) — do before exposing more boxes.

---

## Gate D — Pay down  ·  continuous  ·  standing policy (not a dated stop)

**Pass criteria:** the codebase gets *more* maintainable over time; at-rest secrets move to the OS keychain.

- [x] **D1 · Mega-file ceiling** — P2 · 4–6h + policy — add a CI line-count guard so `run_agent.py`/`gateway/run.py`/`cli.py`/`server.py`/`ChatPage.tsx` can't grow; extract one pure helper cluster (`cli/run_agent.py` → new `cli/agent/response_text.py`) behind characterization tests to prove the forwarder idiom (already used at `run_agent.py:8664`); then chip continuously. **Not** a big-bang rewrite — the easy 80% is already split (`agent/` is 88 files).
- [ ] **D2 · ChatPage windowing tests** — P2 · 4–6h — RTL coverage for tail render on open, "Load earlier" preserving scroll without dropping the pinned latest row, cache-hydration reuse. Locks in the 1.2.63 fix so the bug class can't silently return.
- [ ] **D3 · Lock the multicast transports list** — P3 · 1–2h — `tui_gateway/server.py:836`. Guard the per-session transports list with the existing history_lock; remove on disconnect explicitly.
- [ ] **D4 · At-rest secrets → OS keychain** — P3 · ~1d — `elevate_cli/portal_credentials.py:207`. Move provider keys + portal passwords from plaintext (0600) to Keychain, or encrypt with a machine-bound key. Confirm no home-dir fs-sync includes the store.
- [x] **D5 · Preflight-assert `app-update.yml` is bundled** — P3 · 1h — `desktop/src/updater.js:38`. Packaging assertion so a build can't ship missing update metadata; downgrade that condition to log-only, not a permanent user-facing error card.
- [ ] **D6 · (optional) Re-enable differential/delta updates** — P2 · L — `desktop/src/main.js:63`. Currently disabled by design (blockmaps purged) to dodge a real macOS differential-signature bug. Path to re-enable: verify nothing writes into `Contents/Resources` at runtime (`codesign --verify --deep --strict` after a full real session), then re-enable per-channel behind a soak. Low priority — a deliberate tradeoff, not a defect.

---

## Owner lanes

- **Core (you):** A1, A2, A3 · C1, C2 (deep DB context).
- **Infra (Will):** B1 CI, B2 channels, B3 crash-guard, D1 ceiling.
- **Frontend:** A4 ErrorBoundary, D2 ChatPage tests.
- **Backend + desktop:** B4 telemetry (Next.js route + Electron main).
- **QA (Jeff):** bug-button → B4 pipe; run the B2 canary box; verify each gate's pass criteria.

All of Gate A is parallel. Gate B is the one ordered sequence: **B1 → B2 → (B3 ∥ B4)**.

---

## Fable review notes (2026-07-07)

Reviewed the full plan against the audit + the 10 code-grounded specs for coherence. Findings:

- **All 22 findings are placed** — 5 P1, 13 P2, 4 P3 accounted for across A–D. Cross-checked severities and file:line against the verified audit.
- **Correction 1:** the P2 "re-enable differential downloads" (main.js:63) had no gate slot in the first draft → parked as **D6** (optional). Completeness matters or the plan misrepresents coverage.
- **Correction 2:** crash telemetry (B4) was mislabeled "frontend" → relabeled **backend + desktop** (it's a Next.js route + Electron main; no React involved).
- **Dependency chain validated:** A3 → C4 (stop new dups before the dedupe migration); B1 → B2 → B3 (CI guards all; channel backstops the crash-guard whose in-process fix is only partial because of `app.exit(1)` on uncaught). B4 is independent of B3.
- **Scope honesty preserved from the specs:** CI is mostly wiring (contract already exists); crash-loop is only partially closable in code (process + rollback close it); telemetry is Electron-only (Python already covered); mega-files are policy + slices, not a milestone.
- **No contradictions found** between any spec and its audit finding. One estimate note: Gate A totals ~11–18h of work ≈ 1.5–2.5 dev-days; "2–3d" is the conservative wall-clock with review/verify overhead.
