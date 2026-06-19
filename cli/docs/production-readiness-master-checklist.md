# Production Readiness Master Checklist

Repo: `/Users/dartagnanpatricio/elevate`
Scope: Apple Silicon, current macOS, previous macOS, fresh install, upgrade.
Rule: `UNKNOWN` counts as `FAIL` for release.

This is the top-level gate for taking Elevate production-ready across the
desktop shell, dashboard, agent runtime, gateway/cron, data layer, hosted
backend, and release/update path. It intentionally reuses existing scripts,
tests, and docs before adding anything new.

## Done Definition

Production-ready means every critical path has all five:

- Working UI.
- Passing automated or manual smoke evidence.
- Visible recovery for known failures.
- Structured trace for unknown failures.
- Reproducible release gate.

Critical path:

`install -> login -> chat -> tools -> automations -> update -> quit/reopen`

## Status Legend

- `PASS`: current evidence proves the gate.
- `FAIL`: current evidence contradicts the gate.
- `UNKNOWN`: not checked yet, or evidence is too narrow.
- `N/A`: explicitly outside current scope.

## 1. Root Product Wiring

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| ROOT-01 | Repo state understood | PASS iff `git status --short` is reviewed and unrelated dirty work is preserved | PASS | Reviewed: production checklist, desktop release files, release preflight/doc updates dirty; pre-existing untracked root `main.js` preserved |
| ROOT-02 | Version ownership | PASS iff root, desktop, backend, CLI/package versions are intentionally aligned or documented as separate schemes | PASS | Separate schemes verified: root bootstrap `0.12.0`, desktop `1.2.58`, backend `0.1.0`, CLI `0.11.0` |
| ROOT-03 | One-command developer sanity | PASS iff the smallest repo-level sanity command is documented and runs clean | PASS | `npm run smoke:npx-github` passes |
| ROOT-04 | Local-only commit | PASS iff final production changes are committed locally and no remote push occurs | UNKNOWN | `git log -1`, no `git push` |

## 2. Desktop Shell

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| DESK-01 | App boot | PASS iff Electron opens a window and records startup milestones | PASS | Installed `/Users/dartagnanpatricio/Applications/Elevate.app` v1.2.58 launched; `~/Library/Logs/Elevate/main.log` records `dashboard-loaded 3633ms` |
| DESK-02 | Backend selection | PASS iff desktop selects a live local dashboard port and rejects stale bundles | PASS | `curl http://127.0.0.1:9120/api/status` returns Elevate status payload after installed-app launch |
| DESK-03 | Fallback pages | PASS iff loading/install failure screens are reachable and their buttons work | UNKNOWN | Source VM test proves install/retry rejected IPC restores controls with visible failure text, and main-process installer exit `0` reloads setup when the backend is still unavailable; live manual fallback page pass still required |
| DESK-04 | Desktop IPC | PASS iff every exposed preload action has a main-process handler and at least one caller | PASS | `node --test desktop/test/navigation-guard.test.js desktop/test/ipc-contract.test.js` proves each `ipcRenderer.invoke` exposed from preload has an `ipcMain.handle`, each exposed bridge leaf has a caller, and unused `auth.status/logout` bridge leaves were removed |
| DESK-05 | External navigation | PASS iff untrusted links cannot navigate the main window or launch unsafe schemes | PASS | `node --test desktop/test/navigation-guard.test.js` proves top-level navigation allows only dashboard/app-owned local files and rejects arbitrary `file://`, external http(s), and mailto schemes; `setWindowOpenHandler` still only hands http(s)/mailto to the OS |
| DESK-06 | Permissions | PASS iff microphone and file-preview permissions are scoped and visible on denial | UNKNOWN | Permission handler source plus manual probe |
| DESK-07 | Quit/reopen | PASS iff close, quit, reopen, and activate restore the dashboard without orphan state | UNKNOWN | Manual installed-app pass |
| DESK-08 | SMS outbox | PASS iff approved SMS requests produce result files and failures are visible | UNKNOWN | Outbox fixture or manual probe |

## 3. Desktop Local Screens

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| HTML-01 | Loading screen | PASS iff loading screen never traps the user silently | UNKNOWN | Manual startup and backend-failure pass |
| HTML-02 | Install screen | PASS iff Install and Retry buttons call working IPC and show result state | UNKNOWN | Manual UI pass |
| HTML-03 | Login screen legacy path | PASS iff legacy login screen is either unreachable by design or fully working | UNKNOWN | Source route audit |
| HTML-04 | Overlay | PASS iff computer-use overlay appears only while the activity flag is fresh and never steals focus | UNKNOWN | Manual flag-file probe |

## 4. React Dashboard App

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| WEB-01 | Build | PASS iff TypeScript and Vite build are clean | PASS | `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web run build` passes; default Node 20.9.0 fails engine |
| WEB-02 | Route reachability | PASS iff every sidebar/nav route renders a page, empty state, or visible error | PASS | Source guard proves nav routes are mounted/preloaded; TestClient proves `/docs` serves the SPA and `/api/docs` serves Swagger. Live installed 1.2.58 rendered Chat, Today, Leads, Admin, Social Media, Automations, Overview, Agents, Experiments, Tasks, Approvals, Comms, Activity, Skills, and Memory graph. Final installed browser pass shows `/approvals`, `/comms`, `/activity`, `/docs`, and `/cron` have correct headings/current nav and no visible errors |
| WEB-03 | Dead buttons | PASS iff every visible button/link/toggle either works, is disabled with reason, or is hidden | UNKNOWN | Browser/manual pass |
| WEB-04 | UI collisions | PASS iff desktop-width and narrow-width screenshots show no clipped/overlapping critical controls | UNKNOWN | Browser/manual screenshots |
| WEB-05 | Auth header contract | PASS iff dashboard API client sends the local session header where required | PASS | `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web test -- api-errors` proves `fetchJSON` injects `X-Elevate-Session-Token` from `window.__ELEVATE_SESSION_TOKEN__` |
| WEB-06 | Error states | PASS iff route failures show visible recovery, not silent blank panels | UNKNOWN | Cron load/attention failures now have visible messages and unit coverage; broader mocked/manual route-failure probes still required |
| WEB-07 | Accessibility basics | PASS iff keyboard focus, contrast, labels, and dialog focus are usable on critical pages | UNKNOWN | Manual a11y pass |

## 5. Local Dashboard Server

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| API-01 | Route inventory | PASS iff local FastAPI route inventory matches source and drift fails a test | PASS | `cli/docs/desktop-debug-route-inventory.tsv` is generated from local FastAPI/WebSocket, plugin API, and hosted Next route rows; `cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_dashboard_route_registry.py cli/tests/elevate_cli/test_debug_route_inventory.py` guards drift |
| API-02 | Health/status | PASS iff `/api/status` exposes enough version/gateway readiness to classify startup | PASS | `/api/status` includes app version, config paths, gateway pid/state, platform states, update timestamps, and active session count |
| API-03 | Auth gate | PASS iff protected routes reject missing/bad token and accept valid local token | PASS | `cli/tests/hermes_cli/test_web_server.py` now proves missing token rejects, bad token rejects, custom session header coexists with proxy `Authorization`, served SPA sets `HttpOnly` `elevate_session`, and cookie-only browser requests can read protected `/api/env`; installed runtime smoke also probes protected HTTP without/with the extracted token |
| API-04 | Chat WebSocket | PASS iff `/api/ws` connects, streams, reports close reasons, and recovers visibly | PASS | Fresh arm64 candidate sidecar smoke passed against `desktop/dist/smoke-arm64/mac-arm64/Elevate.app` with served assets, protected HTTP auth, `/api/ws` stream events, final text, and resume proof; `cli/tests/hermes_cli/test_web_server.py -k websocket` covers ready/bad-token/missing-token/disabled close codes; `npm --prefix cli/web test -- gatewayClient.test.ts` covers frontend stale socket recovery and close code/reason propagation |
| API-05 | Feature route contracts | PASS iff each dashboard route family has a caller and a contract test or explicit gap | UNKNOWN | Route/caller/test map |
| API-06 | Debug routes | PASS iff debug endpoints redact secrets and are not production footguns | UNKNOWN | `/api/source-inbox?debug=1` fallback errors now return exception type plus stable code only, with a regression asserting DSNs/tokens/emails/local paths are absent; remote `debug share --no-redact` is rejected before upload and `--no-redact` is local-only; dashboard plugin rescan requires session auth; `debug.trace` redacts blank-trace email/token/password/path values before logging |

## 6. Agent Runtime Core

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| AGENT-01 | Provider/model fallback | PASS iff failed primary provider produces visible fallback or visible error | UNKNOWN | Targeted tests |
| AGENT-02 | Chat loop | PASS iff normal, long, interrupted, and retried chats complete or recover visibly | UNKNOWN | Runtime tests/smoke |
| AGENT-03 | Tools | PASS iff critical tools have schema validation, error reporting, and no silent no-op | UNKNOWN | Tool tests |
| AGENT-04 | Memory/compaction | PASS iff long sessions compact/resume without message loss | UNKNOWN | Installed runtime smoke |
| AGENT-05 | Media/files | PASS iff uploads/previews fail safely and do not leak local paths/secrets | UNKNOWN | Tests/manual probe |
| AGENT-06 | Traceability | PASS iff every agent turn has a session id and enough content-free events to debug | UNKNOWN | Session recorder/log evidence |

## 7. Gateway, Platforms, And Cron

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| GATE-01 | Launchd install | PASS iff gateway install, bootout/bootstrap, and version refresh work on Apple Silicon | PASS | Installed v1.2.58 launch refreshed `.gateway_version` from `1.2.57` to `1.2.58`; `/api/status` shows gateway pid `73142` running |
| GATE-02 | Gateway death recovery | PASS iff killed gateway is detected and recovered or shown visibly to user | UNKNOWN | Manual kill/recovery probe |
| GATE-03 | Cron scheduler | PASS iff scheduled jobs run, fail visibly, and do not block unrelated ticks | PASS | `cli/.venv/bin/python -m pytest cli/tests/hermes_cli/test_agent_hub_effective_skills.py cli/tests/cron/test_scheduler.py -q` passes; post-upgrade log window from line 8110 has no ambiguous-skill scheduler skips; cron load/attention errors are surfaced in source and covered by Vitest |
| GATE-04 | Heartbeats | PASS iff heartbeat automation runs and leaves trace/recovery on failure | UNKNOWN | Cron/gateway test |
| GATE-05 | Platform sends | PASS iff Telegram/SMS/WhatsApp/etc. failures leave visible status and logs | UNKNOWN | Platform tests or scoped manual probes |
| GATE-06 | Stuck job handling | PASS iff stuck jobs are timeouted, logged, and safe to retry | UNKNOWN | Tests/source review |

## 8. Local Data Layer

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| DATA-01 | Fresh DB init | PASS iff fresh `ELEVATE_HOME` initializes cleanly | UNKNOWN | Isolated smoke |
| DATA-02 | Upgrade migrations | PASS iff previous-version data migrates without loss | UNKNOWN | Migration tests |
| DATA-03 | Corrupt state recovery | PASS iff corrupt DB/state shows visible recovery instructions and leaves trace | UNKNOWN | Fault-injection probe |
| DATA-04 | Duplicate prevention | PASS iff critical write paths avoid duplicate sends/tasks/messages | UNKNOWN | Tests/source review |
| DATA-05 | Backup/rollback | PASS iff destructive migrations or state resets have documented rollback/backup path | UNKNOWN | Docs/source review |

## 9. Real Estate And CRM Features

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| CRM-01 | Real Estate Hub | PASS iff hub pages render, buttons work, and empty/error states are visible | UNKNOWN | Live installed pass rendered Today, Leads, Admin, Social Media, Automations, Overview, Agents, Experiments, Tasks, Approvals, Comms, Activity, Skills, and Memory graph; source now loads workflow data for direct Social Media visits and `/leads` source-inbox debug metadata for empty/fallback reads. Final installed `/api/comms/channels` returned `invalid_count: 0` after legacy self-recipient channel projection fix. Button/action safety still required |
| CRM-02 | Admin deal flow | PASS iff deal view/edit/advance/actions have API contracts and UI recovery | UNKNOWN | Existing tests/manual pass |
| CRM-03 | Connectors | PASS iff missing credentials and failed external services show clear recovery | UNKNOWN | Live status proves WhatsApp missing pairing is visible; Oura MCP and Composio Gmail 422 warnings still need owner/recovery classification |
| CRM-04 | Source inbox/leads | PASS iff source inbox/leads routes have caller, test, runtime probe | UNKNOWN | Backend source-inbox debug contracts plus frontend empty/fallback debug note pass; full action/button runtime map still required |
| CRM-05 | Onboarding | PASS iff onboarding can finish, seed required data, and recover from connector failure | UNKNOWN | Isolated/manual pass |

## 10. Hosted Backend And HQ API

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| HOST-01 | Hosted route inventory | PASS iff every `backend/src/app/api/**/route.ts` is tracked and drift-tested | PASS | `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test -- hosted-routes.test.ts` passes hosted route drift/contracts |
| HOST-02 | Auth/license | PASS iff login, refresh, revoke, expired subscription, and logout paths are tested | PASS | `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm test -- hosted-routes.test.ts` covers login, signup, forgot/reset, refresh, expired subscription, login-code, revoked bearer, bearer license/user ownership binding, `/api/me/licenses` read/self-revoke tenant guard, and `/api/me/sign-out-everywhere` preserving the current license |
| HOST-03 | Device code flow | PASS iff start/lookup/approve/deny/poll are tested and visible in UI | UNKNOWN | Backend tests + desktop/dashboard caller |
| HOST-04 | Diagnostics ingestion | PASS iff diagnostics auth, redaction, idempotency, and failure handling are tested | PASS | `npm --prefix backend test` passes diagnostics auth/sanitizer/idempotency/revoked-license tests |
| HOST-05 | Admin/account | PASS iff account/admin APIs enforce guards and expose visible errors | UNKNOWN | Account/org read contracts, admin missing-record 404s, org seat-limit enforcement for direct member add plus stale invite accept, inactive invite accept no longer consumes the invite or adds membership before returning `402`, and admin license revoke tenant-safety pass; deeper admin mutation success/permission matrix still needs coverage |
| HOST-06 | Stripe/skills/automations | PASS iff external-service failures are visible and tested with mocks | UNKNOWN | Skills/automations list gating and `skills/run` requested-skill/invocation audit pass; signed Stripe webhook test now proves unknown subscription prices do not grant `pro`; account billing distinguishes Stripe customer from active subscription; checkout customer/session failures and portal session failures return JSON errors, and checkout audit logging is best-effort; automation mutations and broader external failure mocks still need coverage |

## 11. Release And Update Path

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-01 | Apple preflight | PASS iff release preflight passes on release machine | PASS | `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run preflight:apple` passes for 1.2.58 and verifies public feed is 1.2.51 |
| REL-02 | Packaged build | PASS iff arm64 packaged app builds and launches | PASS | 1.2.58 x64/arm64 app bundles built; `npm --prefix desktop run finalize:mac` signed/notarized/stapled x64 and arm64 DMGs |
| REL-03 | Code signing/seal | PASS iff installed and built app pass `codesign --verify --deep --strict` and `spctl --assess` | PASS | `npm --prefix desktop run smoke:mac` passes for 1.2.58; installed 1.2.58 passes seal smoke before and after first launch |
| REL-04 | Bundled runtime parity | PASS iff installed bundle `cli` and `web_dist` match expected source/build | PASS | Final installed `/Users/dartagnanpatricio/Applications/Elevate.app` v1.2.58 passes full installed runtime smoke: app version, notarized seal, repo/installed `web_dist` parity, served asset parity, protected HTTP auth, `/api/ws` streaming, final text, and resume proof |
| REL-05 | Updater feed | PASS iff feed version/artifacts/checksums match the build being shipped | PASS | `desktop/dist/latest-mac.yml` is version 1.2.58 with x64/arm64 zip+dmg urls, sha512, and sizes |
| REL-06 | Update failure recovery | PASS iff failed download/install leaves visible state and retry path | UNKNOWN | Unpacked app-dir candidates now skip updater checks cleanly when `app-update.yml` is absent; packaged updater status/check/install still needs a focused probe |
| REL-07 | Rollback | PASS iff rollback procedure is documented and artifact-retention is verified | UNKNOWN | Release docs/artifact store |

## 12. Observability And Support

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| OBS-01 | Structured logs | PASS iff desktop, dashboard server, gateway, and hosted backend include request/session ids | UNKNOWN | Source/log sample |
| OBS-02 | Crash capture | PASS iff renderer/main/gateway crashes leave a supportable trace | UNKNOWN | Fault-injection/manual probe |
| OBS-03 | Support bundle | PASS iff user can create a no-secret diagnostic bundle with logs, versions, port, route status | UNKNOWN | Support bundle command/UI |
| OBS-04 | Redaction | PASS iff support bundle and diagnostics strip tokens, prompts, messages, paths, stack payloads | UNKNOWN | Tests/source review |
| OBS-05 | Runbook | PASS iff support has a current "what to ask/check" doc for common failures | UNKNOWN | Docs |

## 13. Security And Privacy

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| SEC-01 | IPC boundary | PASS iff renderer cannot call unscoped filesystem/shell/network IPC | UNKNOWN | Source review/tests |
| SEC-02 | Token storage | PASS iff local tokens are permissioned and never logged | UNKNOWN | Source review/log scan |
| SEC-03 | CSP/navigation | PASS iff dashboard CSP/navigation prevents unsafe top-level nav and external schemes | UNKNOWN | Source review/manual probe |
| SEC-04 | File preview safety | PASS iff previews cannot exfiltrate arbitrary local files or frame unsafe content | UNKNOWN | Tests/source review |
| SEC-05 | Hosted guards | PASS iff hosted account/admin routes enforce auth/admin guards | UNKNOWN | Backend tests |

## 14. Performance And Stability

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| PERF-01 | Cold start | PASS iff fresh and warm startup fit target and log milestones | UNKNOWN | Startup timeline sample |
| PERF-02 | Idle load | PASS iff app/gateway idle CPU and memory are acceptable after 10 minutes | UNKNOWN | Activity Monitor/ps sample |
| PERF-03 | Long chat | PASS iff long chat does not leak memory or lose transcript | UNKNOWN | Smoke/soak |
| PERF-04 | Big data pages | PASS iff logs/tasks/real-estate pages handle large local datasets | UNKNOWN | Fixture/manual pass |
| PERF-05 | Update timing | PASS iff update check/download/install does not freeze critical UI | UNKNOWN | Packaged update probe |

## 15. Environment Matrix

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| ENV-01 | Apple Silicon fresh install | PASS iff clean install works end-to-end | UNKNOWN | Manual/install smoke |
| ENV-02 | Apple Silicon upgrade | PASS iff upgrade from previous shipped app works end-to-end | UNKNOWN | Manual/update smoke |
| ENV-03 | Previous macOS | PASS iff same critical path works on previous supported macOS | UNKNOWN | Manual matrix record |
| ENV-04 | Offline/bad network | PASS iff login/license/update/API failures are visible and recoverable | UNKNOWN | Network fault probe |
| ENV-05 | Missing permissions/tools | PASS iff missing mic/Messages/imsg/browser credentials show recovery | UNKNOWN | Manual fault probe |

## 16. Final Go/No-Go

| ID | Item | Pass/fail done gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| GO-01 | All critical gates pass | PASS iff all non-N/A checklist rows above are PASS | FAIL | Checklist still has UNKNOWN rows across UI E2E, recovery, observability, security, performance, and environment matrix |
| GO-02 | No P0/P1 open bugs | PASS iff no open critical bugs remain in the ledger | FAIL | Open runtime/config issues still need classification: WhatsApp enabled but not paired, config version `24` behind latest `25`, earlier Oura MCP, missing `OPENAI_API_KEY`, Composio Gmail HTTP 422 warnings, and one full-file parallel web-server run timed out in `/api/pub` broadcast before isolated rerun passed |
| GO-03 | Tests green | PASS iff selected repo-wide test suite is green and listed | PASS | Listed evidence commands pass for web build, backend tests, targeted pytest, desktop preflight, mac smoke, and installed-app smoke |
| GO-04 | UI E2E checked | PASS iff install -> login -> chat -> tools -> automations -> update -> quit/reopen is checked | UNKNOWN | Manual/browser report |
| GO-05 | Local commit | PASS iff all production-readiness changes are committed locally only | UNKNOWN | `git log -1`, remote untouched |

## First Evidence Commands

Run these before marking any row PASS:

```bash
git status --short
PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web run build
npm --prefix backend test
cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_debug_route_inventory.py cli/tests/elevate_cli/test_installed_runtime_smoke.py
cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --skip-sidecar
```

If one command fails, fix the smallest failing gate first.

## Evidence Log

- PASS: `npm run smoke:npx-github`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web run build`
- PASS: `npm --prefix backend test`
- PASS: `cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_debug_route_inventory.py cli/tests/elevate_cli/test_installed_runtime_smoke.py`
- FAIL: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --skip-sidecar`
- PASS after replacing stale installed app: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --skip-sidecar`
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac-arm64/Elevate.app --skip-sidecar`
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac/Elevate.app --skip-sidecar`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run preflight:apple`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run build:mac`
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac-arm64/Elevate.app --skip-sidecar` for 1.2.54
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac/Elevate.app --skip-sidecar` for 1.2.54
- PASS: replaced installed app with 1.2.54 and reran `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --skip-sidecar`
- PASS: launched installed 1.2.54; `curl http://127.0.0.1:9120/api/status` shows gateway `running`, fresh pid/timestamps, Telegram/API connected, and WhatsApp `whatsapp_not_paired` instead of `whatsapp_bridge_missing`
- PASS: `launchctl print gui/$(id -u)/ai.elevate.gateway` shows gateway running from `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli`
- FAIL: fresh `gateway.error.log` shows cron jobs skipped because several skill names are ambiguous (`gmail-doc-router`, `subject-removal`, `digisign`, `webforms`)
- PASS: `cli/.venv/bin/python -m pytest cli/tests/hermes_cli/test_agent_hub_effective_skills.py cli/tests/cron/test_scheduler.py -q`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run preflight:apple` for 1.2.57; public feed still 1.2.51, so package version is safely greater than published latest
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run build:mac` for 1.2.57 after clearing stale duplicate build/finalizer processes
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac-arm64/Elevate.app --skip-sidecar` for 1.2.57
- PASS: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app desktop/dist/mac/Elevate.app --skip-sidecar` for 1.2.57
- PASS: replaced installed app with 1.2.57 and reran `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --skip-sidecar`
- PASS: launched installed 1.2.57; `.gateway_version` advanced from `1.2.56` to `1.2.57`, gateway pid changed from `36454` to `79664`, and `/api/status` settled to `gateway_running=true`
- PASS: post-upgrade log window `tail -n +8110 ~/.elevate/logs/gateway.error.log` has no ambiguous-skill scheduler skips
- NOTE: current visible runtime warnings after 1.2.57 are WhatsApp not paired, Oura MCP connection failure, missing `OPENAI_API_KEY` for embeddings, Composio Gmail HTTP 422, and local config version `24` behind latest `25`
- PASS: `cli/.venv/bin/python -m pytest cli/tests/tools/test_lazy_deps.py -q`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run preflight:apple` for 1.2.58; public feed still 1.2.51
- PASS: 1.2.58 x64 and arm64 app bundles built; `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run smoke:mac`
- PASS: `APPLE_KEYCHAIN_PROFILE=elevate-notarization PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run finalize:mac`
- PASS: `desktop/dist/latest-mac.yml` is version 1.2.58 with x64/arm64 zip+dmg urls, sha512, and sizes
- PASS: replaced installed app with clean arm64 1.2.58 and ran pre-launch smoke: `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --expected-app-version 1.2.58 --skip-sidecar`
- PASS: launched installed 1.2.58; `.gateway_version` advanced from `1.2.57` to `1.2.58`, gateway pid `73142` running, API/Telegram connected, WhatsApp visibly `whatsapp_not_paired`
- PASS: post-launch installed 1.2.58 seal smoke passed, proving first launch did not mutate the signed bundle
- PASS: post-1.2.58 gateway log window from line 8120 has no ambiguous-skill scheduler skips; only WhatsApp not-paired warnings are present
- PASS: source route guard and `/docs` collision fix: `cli/.venv/bin/python -m pytest cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_docs_dashboard_route_is_not_fastapi_swagger cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_fastapi_swagger_lives_under_api_docs cli/tests/elevate_cli/test_dashboard_route_registry.py cli/tests/elevate_cli/test_debug_route_inventory.py -q`
- UNKNOWN/FLAKE: full `cli/.venv/bin/python -m pytest cli/tests/hermes_cli/test_web_server.py cli/tests/elevate_cli/test_dashboard_route_registry.py cli/tests/elevate_cli/test_debug_route_inventory.py -q` reached 152 passed then timed out once in `TestPtyWebSocket::test_pub_broadcasts_to_events_subscribers`; isolated rerun of that test passed
- FAIL found in live installed 1.2.58 UI pass: `/approvals` route rendered Approvals content while the page chrome title still showed `Today`
- PASS in source: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm exec vitest run src/lib/__tests__/resolve-page-title.test.ts src/pages/__tests__/CronPage.errors.test.ts src/pages/real-estate-hub/_shared/__tests__/use-hub-data.flags.test.ts` from `cli/web`
- PASS in source: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web run build` rebuilt `cli/elevate_cli/web_dist` with corrected dashboard route titles
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test -- hosted-routes.test.ts`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm test -- hosted-routes.test.ts` from `backend` after adding signup/forgot/reset, production mailer outage, admin missing-record 404, and `skills/run` requested-skill/invocation coverage
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test -- --test-name-pattern "hosted bearer licenses must belong"`
- FAIL then PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/elevate_cli/test_installed_runtime_smoke.py::test_recent_log_scan_ignores_old_untimestamped_continuations` first proved old untimestamped `BLANK-TRACE` continuations could false-fail fresh smoke, then passed after the scanner was scoped to fresh timestamp blocks
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" node --test desktop/test/navigation-guard.test.js`
- PASS: `cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_installed_runtime_smoke.py cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_fastapi_openapi_schema_lives_under_api cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_docs_dashboard_route_is_not_fastapi_swagger cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_fastapi_swagger_lives_under_api_docs -q`
- PASS: `cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_debug_route_inventory.py cli/tests/elevate_cli/test_dashboard_route_registry.py -q`
- PASS/BUGS: live installed 1.2.58 route pass rendered Comms, Activity, Skills, and Memory graph; Comms/Activity still show generic `Web UI` page chrome in installed app, while source route-title fix covers them for the next rebuild
- PASS: live installed 1.2.58 Memory graph populated after initial shell load with 78 nodes / 92 links, replay control, and recent ingest details
- NOTE: old installed app backed up at `/Users/dartagnanpatricio/Applications/Elevate.app.backup-20260618-214427-1.2.51`
- NOTE: previous 1.2.53 installed app backed up at `/Users/dartagnanpatricio/Applications/Elevate.app.backup-20260618-220758-1.2.53`
- NOTE: previous 1.2.57 installed app backed up at `/Users/dartagnanpatricio/Applications/Elevate.app.backup-20260618-235359-1.2.57`; a locally mutated 1.2.58 verification copy was backed up at `/Users/dartagnanpatricio/Applications/Elevate.app.backup-20260618-235625-1.2.58-pycache-mutated`
- NOTE: default shell Node is `v20.9.0`; repo dashboard build needs Node `>=22.12 <26`. `/opt/homebrew/opt/node@22/bin/node` is available and works.
- PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_unauthenticated_api_blocked cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_dashboard_session_cookie_authorizes_api_requests cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_reveal_env_var_bad_token cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_reveal_env_var_custom_session_header_ignores_proxy_authorization`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web test -- api-errors`
- FAIL then PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test -- --test-name-pattern "inactive invite accepts"` first proved inactive invite accepts returned `402` after mutating the invite to `accepted`; after the route-order fix it passes
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test`
- PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_source_inbox_debug_reports_jsonl_fallback cli/tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_source_inbox_debug_reports_db_read_path_and_counts`
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix cli/web run build`
- PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/hermes_cli/test_debug.py`
- PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/elevate_cli/test_debug_route_inventory.py cli/tests/elevate_cli/test_debug_route_coverage_ledger.py cli/tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_dashboard_plugin_rescan_requires_session_token`
- FAIL then PASS: `PYTHONDONTWRITEBYTECODE=1 cli/.venv/bin/python -m pytest -q cli/tests/test_tui_gateway_server.py::test_debug_trace_log_redacts_secrets` first proved `blank-trace.log` wrote raw renderer debug secrets, then passed after gateway redaction
- FAIL then PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix backend test -- --test-name-pattern "stripe checkout returns JSON|stripe checkout still returns|stripe portal returns JSON"` first proved checkout/portal Stripe and audit failures escaped the routes, then passed with stable JSON failures and best-effort audit logging
- FAIL then PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" node --test desktop/test/install-flow.test.js` first proved rejected install/retry IPC and installer-success/backend-not-ready states could leave setup stuck, then passed after visible recovery handling
- PASS: `cli/.venv/bin/python -m pytest cli/tests/elevate_cli/test_agent_handoffs.py::test_agent_comms_projection_and_routes -q` covers implicit and legacy self-recipient handoff replies staying in the original comms pair
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run build:mac` rebuilt signed/notarized x64 and arm64 1.2.58 artifacts after the final Comms projection fix
- PASS: `PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm --prefix desktop run smoke:mac` for the final 1.2.58 x64/arm64 artifacts
- PASS: replaced installed app with final arm64 1.2.58 and ran `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --expected-app-version 1.2.58 --skip-sidecar`
- PASS: final full installed runtime smoke `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --installed-app /Users/dartagnanpatricio/Applications/Elevate.app --expected-app-version 1.2.58 --timeout 90`; output `/tmp/elevate-installed-smoke-1781858738.json`
- PASS: final installed `/api/comms/channels?limit=250` returned `total: 7`, `invalid_count: 0`; legacy `executive-assistant--executive-assistant` channel no longer surfaces
- PASS: final browser route pass showed `/approvals`, `/comms`, `/activity`, `/docs`, and `/cron` render expected headings/current nav with no visible errors
