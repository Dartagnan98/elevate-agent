# EPIC - Desktop production debug readiness

Date: 2026-06-18
Repo: `/Users/dartagnanpatricio/elevate`
Status: production-readiness epic

> **Outcome:** when the desktop app fails, we can classify the break in minutes:
> launch/backend, local API auth, active chat WebSocket, feature data route,
> scheduler/worker, plugin mount, hosted login/license, or updater.
>
> **Production outcome:** every desktop-reachable debug pathway has a current
> source read, caller proof, contract test or explicit test gap, and runtime
> probe before we call the app production-ready.
>
> **Center:** this epic is about the user opening `Elevate.app` and every local
> or hosted route family that can affect that experience.

## Two Debug Modes

The app needs two different debugging modes.

Fast path: classify the immediate desktop break without reading the whole repo:

1. Did Electron start the right local dashboard?
2. Is the served dashboard the active runtime, not stale source or stale bundle?
3. Does the local `/api/*` token path work?
4. Does the active chat path through `/api/ws` work?
5. Only then do feature routes, cron, plugins, and hosted backend matter.

Production sweep: prove every debug pathway is readable and testable:

1. Inventory every local FastAPI route, WebSocket, plugin route, hosted Next
   route, desktop IPC surface, and frontend caller.
2. Assign each route to a route family and owner file.
3. Link each route family to existing tests or a missing-test item.
4. Add runtime probes for installed `Elevate.app`, local dev dashboard, and
   hosted backend flows.
5. Fail readiness when a route has no caller proof, no contract test, and no
   conscious reason to leave it untested.

The rule: **prove the runtime before debugging the feature; prove the full route
map before calling production ready.**

## Out Of Scope

- New route observability service before the inventory and tests prove a gap.
- New source-inbox reader.
- Generated bundle source review, except for bundled-vs-served asset checks.
- Live hosted smoke against production credentials without a staging plan.
- Replacing existing route contracts with a new test framework.

## Route Map Truth Tests

Before debugging a route, test that this epic is still reading the repo
correctly. A stale map is a bug in the debug plan, not evidence that the app is
broken.

Each pathway gets three checks:

- Read check: `rg` or `find` proves the route, caller, IPC handler, or source
  anchor still exists.
- Contract check: the narrowest existing test proves the expected behavior
  without packaging the app.
- Runtime check: a curl, browser, WebSocket, or app-log probe runs against the
  actual desktop-selected port.

Minimum route-map checks:

- Desktop launch/updater: prove `backendIsReady`, bundle checks,
  `updater:status`, `updater:install`, and `updater:check` still exist; prove
  `preload.js` exposes the updater action; prove `App.tsx` calls it; prove the
  packaged updater feed and mac zip target still exist.
- Local auth: prove the session header name, public allowlist, middleware gate,
  frontend header injection, and Vite dev token scrape still line up.
- Active chat: prove `ChatPage` still constructs `GatewayClient`, the client
  still opens `/api/ws`, FastAPI still serves `/api/ws`, and the gateway still
  exposes `session.create`, `session.list`, and `session.resume`.
- Secondary chat routes: prove `/api/pty`, `/api/pub`, and `/api/events` are
  active callers before using them in a first-line chat diagnosis.
- Feature routes: prove frontend callers and server routes both exist for
  source inbox, cron attention, plugin manifests, plugin API mount, admin deals,
  admin tasks, today, and agent hub.
- Hosted routes: prove desktop/CLI callers where applicable and Next route
  handlers exist for health, login, license refresh, `/link` device approval,
  device poll, diagnostics ingestion, and alternate login-code flows.

Testing ladder by pathway:

- Desktop launch/updater: read `desktop/src/main.js`, `desktop/src/preload.js`,
  `cli/web/src/App.tsx`, and `desktop/package.json`; add narrow contract tests
  when readiness or updater serialization changes; runtime probe is `main.log`,
  `/api/status`, `/`, and bundled-vs-served assets.
- Local auth: read `web_server.py`, `api.ts`, and `vite.config.ts`; contract
  tests are the narrow backend auth tests; add a small frontend header-injection
  test before claiming browser coverage; runtime probe is one protected local
  route with and without the session header.
- Active chat: read `ChatPage`, `GatewayClient`, FastAPI `/api/ws`, and
  `tui_gateway`; first prove embedded chat is enabled and `/chat` is mounted;
  contract tests are `/api/ws` `gateway.ready`, named gateway resume tests, and
  existing `gatewayClient` reconnect tests; runtime probe is a real WebSocket
  against the selected desktop port.
- Feature routes: read frontend callers and server routes together; contract
  tests use named route tests only; missing feature-route tests must be added
  before the epic claims coverage; runtime probe uses the existing route with
  `debug=1` only where the route already supports it or this epic adds it.
- Hosted routes: read Next route filenames plus desktop/CLI callers; contract
  coverage is missing today, so the epic should not claim hosted behavior is
  tested until route-handler tests or a documented staging probe exist.

Rule: if a read check fails, update this epic before implementing a product fix.

## Production Sweep Scope

Everything below is in scope for production readiness. The fast path can skip
most of it during an incident; the release gate cannot.

Local desktop and Electron:

- App launch, backend selection, stale bundle eviction, installed app logging.
- Desktop auth IPC, external hosted auth links, updater IPC, updater feed config.
- Packaged assets, bundled `web_dist`, app version, updater log lines.

Local FastAPI route families:

- Health, access, local license activation, local license code flow, cloud-skill
  sync, logout.
- Gateway restart/start, workspace status/open, local update/status, actions.
- Files, uploads, sessions, session search, transcript messages, todos, plan,
  files, turn usage, artifacts, child sessions, reveal/delete, logs.
- Config, tiers, env, model info, available models, provider OAuth start/submit,
  poll, delete, and raw config.
- Contacts, active contacts, admin contacts, conflicts, signals.
- Admin/leads/agent setup, onboarding chat, browser-use launch, pack onboarding,
  province guides.
- Admin deals, upcoming events, deal context, deal fields, deal advance,
  attachments, action runs, actions, admin tasks, admin templates.
- Threads, lanes, onboarding status, outreach templates, source connectors,
  source inbox, sender tick/stats.
- Composio, Ayrshare, integrations, social snapshot/ideas/posts/refresh.
- Skills, toolsets, analytics usage.
- Cron jobs, backfill, trigger, pause/resume/delete, cron attention.
- Heartbeat surfaces, experiments, cycles, routes, goals, automations, tasks,
  approvals.
- Activity, comms delivery channels, comms feed/channels, message send.
- Agent hub, agent packs, agent configs, handoffs, worker tick/wake, harness.
- Chat WebSockets: `/api/ws`, `/api/pty`, `/api/pub`, `/api/events`.
- Dashboard themes, dashboard plugins, plugin assets, plugin API routes.

Hosted backend route families:

- Health.
- Auth login, signup, forgot/reset password, login-code request/verify,
  invitation accept.
- License refresh.
- Device start, lookup, approve, deny, poll.
- `me`, email, password, licenses, sign-out-everywhere.
- Orgs and admin org/user/search/audit routes.
- Skills list/run, automations list, Stripe checkout/portal/webhook.
- Diagnostics session-events.

Production readiness artifacts:

- Route inventory: every local/hosted route and WebSocket with file and line.
- Frontend caller map: every `fetchJSON`, raw `/api/`, WebSocket, and desktop
  IPC caller.
- Test coverage map: route family -> existing test command -> missing tests.
- Runtime smoke map: installed app, dev dashboard, packaged asset, local API,
  WebSocket, feature route, hosted route.
- Missing-test ledger: every route family without contract coverage and the
  smallest test needed.
- No-secret support bundle: log paths, route probes, version, port, asset refs,
  updater lines, and failure classification.

Current verified snapshot, 2026-06-18:

- Local inventory: 325 decorated local routes/WebSockets, split as 242 in
  `web_server.py`, 18 in `agent_hub.py`, 15 in `source_connectors.py`, 12 in
  `cron.py`, 1 in `today.py`, 36 in the Kanban plugin API, and 1 in the
  example plugin API.
- Local route identity fingerprint: `52094886efcfdce6`.
- Hosted inventory: 38 tracked `backend/src/app/api/**/route.ts` files.
  `backend/package.json` now has a `test` script using `node:test` plus the
  existing `tsx` dependency. `backend/test/hosted-routes.test.ts` covers
  health, login 200/402, login-code request/verify, refresh rotation/402
  revoke, device start/lookup/approve/deny/poll, and diagnostics
  auth/sanitizer/idempotent upsert.
- Hosted route file inventory:
  - `backend/src/app/api/admin/audit/route.ts`
  - `backend/src/app/api/admin/orgs/[id]/members/[userId]/route.ts`
  - `backend/src/app/api/admin/orgs/[id]/members/route.ts`
  - `backend/src/app/api/admin/orgs/[id]/route.ts`
  - `backend/src/app/api/admin/orgs/route.ts`
  - `backend/src/app/api/admin/search/route.ts`
  - `backend/src/app/api/admin/users/[id]/licenses/[licenseId]/route.ts`
  - `backend/src/app/api/admin/users/[id]/licenses/route.ts`
  - `backend/src/app/api/admin/users/[id]/route.ts`
  - `backend/src/app/api/admin/users/route.ts`
  - `backend/src/app/api/auth/forgot/route.ts`
  - `backend/src/app/api/auth/login/route.ts`
  - `backend/src/app/api/auth/login-code/request/route.ts`
  - `backend/src/app/api/auth/login-code/verify/route.ts`
  - `backend/src/app/api/auth/reset/route.ts`
  - `backend/src/app/api/auth/signup/route.ts`
  - `backend/src/app/api/automations/list/route.ts`
  - `backend/src/app/api/device/approve/route.ts`
  - `backend/src/app/api/device/deny/route.ts`
  - `backend/src/app/api/device/lookup/route.ts`
  - `backend/src/app/api/device/poll/route.ts`
  - `backend/src/app/api/device/start/route.ts`
  - `backend/src/app/api/diagnostics/session-events/route.ts`
  - `backend/src/app/api/health/route.ts`
  - `backend/src/app/api/invitations/accept/route.ts`
  - `backend/src/app/api/license/refresh/route.ts`
  - `backend/src/app/api/me/email/route.ts`
  - `backend/src/app/api/me/licenses/[id]/route.ts`
  - `backend/src/app/api/me/licenses/route.ts`
  - `backend/src/app/api/me/password/route.ts`
  - `backend/src/app/api/me/route.ts`
  - `backend/src/app/api/me/sign-out-everywhere/route.ts`
  - `backend/src/app/api/orgs/route.ts`
  - `backend/src/app/api/skills/list/route.ts`
  - `backend/src/app/api/skills/run/route.ts`
  - `backend/src/app/api/stripe/checkout/route.ts`
  - `backend/src/app/api/stripe/portal/route.ts`
  - `backend/src/app/api/stripe/webhook/route.ts`
- Caller inventory: the latest sweep found 443 frontend/desktop caller
  references across `fetchJSON`, raw fetches, `/api/` strings, WebSockets, and
  desktop IPC.
- Caller inventory fingerprint: `3110b150ce9d70dd`.
- Closed in this pass: `/api/ws` missing/bad-token/embedded-disabled backend
  tests, frontend `api.ts` session-header injection test, served-SPA
  `HttpOnly` session-cookie authorization test,
  `/api/source-inbox?debug=1` read-path/counts/sanitized fallback metadata,
  direct `/api/cron/attention` contract test, example plugin API mount test, serialized
  updater manual checks, dead updater `dismissToast` preload exposure,
  `GatewayClient` WebSocket close-code/reason propagation, stale updater
  polling comment, backend hosted route-handler harness, hosted device
  lookup/deny contracts, hosted login-code request/verify contract, hosted
  revoked-bearer and license/user ownership 403 contracts, hosted route file-list drift guard,
  hosted account/org/skills-list/automation-list read contracts,
  hosted signup/forgot/reset contract with visible production mailer outage
  and reset cleanup-before-password-change ordering,
  hosted inactive invitation accepts return `402` without consuming the invite or
  adding membership,
  hosted admin missing-record mutations return 404 instead of false success,
  dashboard nav/route/preloader drift guard, FastAPI `/docs` shadow moved to
  `/api/docs` and `/api/openapi.json` so the dashboard `/docs` deep link
  serves the SPA and the developer schema does not crash on plugin routes,
  stricter `/api/status` readiness for desktop launch, release-path
  `smoke:mac` gate, preflight public-feed version comparison, post-ship public
  feed/artifact verification, installed app `codesign`/`spctl` smoke gate,
  packaged WhatsApp bridge/package checks, installed smoke reads the selected
  dashboard port from `main.log`, records it in JSON, compares served dashboard
  assets to the installed `web_dist`, and probes one protected HTTP route
  without/with the extracted session token before sidecar prompts, ignores old
  untimestamped bad-log continuations, desktop
  top-level navigation blocks arbitrary `file://` and external schemes,
  gateway reinstall when a previously
  missing packaged resource is recovered, gateway version-change installs
  kickstart launchd before advancing `.gateway_version`, Admin cron effective
  skills qualify ambiguous real-estate skill names, cron lane seeding repairs
  existing job agents, cron rejects unknown agent ids instead of silently
  skipping, Cron route load/attention failures render real error states,
  `/social-media` direct loads fetch cron workflow data for the jobs header,
  debug share rejects nonpositive `--lines`, local route identity
  fingerprint drift guard, release feed merge rejects app-bundle/package version
  mismatch, finalization requires all current x64/arm64 zip/dmg artifacts,
  ship refuses a mismatched local feed before any remote mutation, lazy
  `tts.edge` install spec matches packaged core dependency policy, production
  support bundle redaction for session-recorder events, and remote
  `elevate debug share --no-redact` rejection before upload, and dashboard
  plugin rescan auth gating, and `debug.trace` blank-trace log redaction.
- Installed app smoke: `/Users/dartagnanpatricio/Applications/Elevate.app`
  passes `cli/scripts/installed_runtime_smoke.py` for `1.2.58` before and
  after first launch. The 1.2.57 installed-app seal failure is closed by the
  lazy `tts.edge` dependency-range fix plus the packaged pycache isolation that
  keeps Python bytecode out of `Contents/Resources`. The fresh-log scanner now
  skips stale untimestamped continuation lines from old timestamp blocks while
  still catching fresh bad continuations.
- Fresh candidate smoke: signed/notarized `desktop/dist/mac/Elevate.app` and
  `desktop/dist/mac-arm64/Elevate.app` for `1.2.58` pass app-version, seal,
  repo `web_dist` parity, and packaged WhatsApp bridge checks, including
  `bridge.js`, `package.json`, `package-lock.json`, and `node_modules`.

## Route Center

### 1. Desktop Launch And Updater

Primary files:

- `desktop/src/main.js`
- `desktop/src/preload.js`
- `desktop/package.json`
- `cli/web/src/App.tsx`

Source anchors:

- Default port: `PREFERRED_PORT` is `9119` in
  `desktop/src/main.js:45`.
- Startup milestones use `markStartup(...)` in
  `desktop/src/main.js:122`.
- Backend readiness now requires `GET /api/status` to return `200` plus the
  expected Elevate status payload shape in `desktop/src/main.js:696`.
- Stale bundle checks compare served and bundled Vite assets in
  `desktop/src/main.js:705` and `desktop/src/main.js:735`.
- Backend spawn and timeout path live in `ensureBackend(...)` at
  `desktop/src/main.js:847`.
- Updater IPC includes `updater:status`, `updater:install`, and
  `updater:check` at `desktop/src/main.js:1650`,
  `desktop/src/main.js:1653`, and `desktop/src/main.js:1663`.
- `preload.js` exposes `checkNow` at `desktop/src/preload.js:25`, and the
  renderer calls it in `cli/web/src/App.tsx:1476` and
  `cli/web/src/App.tsx:1489`.
- Packaged updater config lives in `desktop/package.json`; keep the check to
  provider URL, mac `zip` target, and `electron-updater` dependency.

Debug questions:

- Which port did Electron select?
- Did `/api/status` return a real healthy status, not just any 4xx?
- Does `/` include the embedded chat flag?
- Do served Vite assets match the bundled `web_dist/index.html`?
- Which launcher path won: bundled Python/CLI, repo venv, PATH `elevate`, or
  fallback?
- Is an updater check already in flight, or did `updater:check` bypass the
  serialized checker?

First fix candidates:

- Done: make readiness less lossy than `status >= 200 && status < 500`.
- Remaining: add one compact startup probe log with port, status code, asset-match result,
  embedded-chat flag, and launcher kind.
- Route `updater:check` through the same serialized updater guard as scheduled
  checks.
- Delete the dead `dismissToast` preload exposure if touching updater IPC. Do
  not add a handler unless the UI proves it needs one.

### 2. Local API Auth And 401s

Primary files:

- `cli/elevate_cli/web_server.py`
- `cli/web/src/lib/api.ts`
- `cli/web/vite.config.ts`

Source anchors:

- Local session header is `X-Elevate-Session-Token` at
  `cli/elevate_cli/web_server.py:280`.
- Public local API allowlist starts at `cli/elevate_cli/web_server.py:349`.
- Header, cookie, and legacy bearer acceptance is in
  `_has_valid_session_token(...)` at `cli/elevate_cli/web_server.py:364`.
- Non-public `/api/*` routes are gated by middleware at
  `cli/elevate_cli/web_server.py:511`.
- React injects the header in `cli/web/src/lib/api.ts:270`.
- Vite dev token scraping warns when it cannot find the dashboard token in
  `cli/web/vite.config.ts:33`.

Debug questions:

- Did the served HTML inject `window.__ELEVATE_SESSION_TOKEN__`?
- Did the browser send the `elevate_session` cookie?
- Did `api.ts` set `X-Elevate-Session-Token`?
- Is this a local dashboard 401, or a hosted backend bearer-token 401?

First fix candidate:

- Document the curl and HTML-token checklist first. Add a no-secret auth
  diagnostic only if repeated desktop failures remain ambiguous after those
  checks.

No-secret local auth checklist:

- Read the selected port from `~/Library/Logs/Elevate/main.log`
  (`backend:port-selected`).
- `curl -sS http://127.0.0.1:<port>/ | rg "__ELEVATE_SESSION_TOKEN__|elevate_session"`.
- `curl -i http://127.0.0.1:<port>/api/status` should return `200` with
  `version` and `gateway_running`.
- A protected local route without the session header should return a local
  dashboard `401`; hosted bearer `401/402/403` belongs to the backend routes
  in Issue 5.

### 3. Active Chat Path

Primary files:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/web/src/lib/gatewayClient.ts`
- `cli/elevate_cli/web_server.py`
- `cli/tui_gateway/ws.py`
- `cli/tui_gateway/server.py`

Source anchors:

- Active React chat uses a shared `GatewayClient` in
  `cli/web/src/pages/ChatPage.tsx:844` and
  `cli/web/src/pages/ChatPage.tsx:863`.
- `/chat` is only active when embedded chat is enabled in `cli/web/src/App.tsx`.
- `GatewayClient` opens `/api/ws` in `cli/web/src/lib/gatewayClient.ts:149`.
- FastAPI exposes `/api/ws` at `cli/elevate_cli/web_server.py:12033`.
- The WebSocket transport accepts at `cli/tui_gateway/ws.py:112`, emits
  `gateway.ready` around `cli/tui_gateway/ws.py:127`, and dispatches JSON-RPC
  at `cli/tui_gateway/ws.py:177`.
- `session.create`, `session.list`, and `session.resume` live at
  `cli/tui_gateway/server.py:2760`,
  `cli/tui_gateway/server.py:2900`, and
  `cli/tui_gateway/server.py:2972`.
- Replay ring state exists in `cli/tui_gateway/server.py:126` and event replay
  writes through `write_json(...)` around `cli/tui_gateway/server.py:786`.

Debug questions:

- Does `/api/ws` accept and emit `gateway.ready`?
- Is embedded chat enabled and is `/chat` mounted?
- Can it run `session.create`, `session.list`, and `session.resume`?
- Does reconnect preserve replay events?
- Are WebSocket close codes visible in the React error path?

First fix candidates:

- Done: surface `/api/ws` close code and reason in `GatewayClient`.
- Done: add `/api/ws` missing-token, bad-token, and embedded-chat-disabled
  backend tests for `4401` and `4403`.
- Keep `debug.trace` and `blank-trace.log` as post-failure render-drop evidence,
  not first-line route health. The sink lives at `cli/tui_gateway/server.py:4481`.
- Do not debug `/api/pty`, `/api/pub`, or `/api/events` until source/runtime
  evidence shows the active UI uses them for the failing path.

### 4. Feature Routes After Runtime Is Proven

Primary files:

- `cli/elevate_cli/web_routes/source_connectors.py`
- `cli/elevate_cli/web_routes/cron.py`
- `cli/elevate_cli/web_routes/today.py`
- `cli/elevate_cli/web_routes/agent_hub.py`
- `cli/elevate_cli/web_server.py`
- `cli/elevate_cli/data/`
- `cli/cron/`
- `cli/gateway/run.py`

Source anchors:

- Source connector routes start at
  `cli/elevate_cli/web_routes/source_connectors.py:103`; source-inbox starts
  at `cli/elevate_cli/web_routes/source_connectors.py:143`.
- Cron routes start at `cli/elevate_cli/web_routes/cron.py:96`.
- Cron attention exists at `cli/elevate_cli/web_routes/cron.py:384`.
- Today route is `cli/elevate_cli/web_routes/today.py:431`.
- Agent hub and worker routes start at
  `cli/elevate_cli/web_routes/agent_hub.py:922`.
- Admin deals route is `cli/elevate_cli/web_server.py:7016`.
- Admin tasks route is `cli/elevate_cli/web_server.py:9763`.
- Dashboard plugin rescan is manifest-only at
  `cli/elevate_cli/web_server.py:12632`.
- Plugin APIs mount under `/api/plugins/<name>` at
  `cli/elevate_cli/web_server.py:12677`.

Debug questions:

- Which source route owns the symptom?
- Does the route hit `connect()` and the expected data helper?
- Is a source inbox result coming from the operational store or JSONL fallback?
- Is cron job state healthy, or only the composite surface view healthy?
- Is a plugin manifest present but its API router not mounted?

First fix candidates:

- Done: add `debug=1` metadata to existing source-inbox responses only for
  active read path, fallback/error, and counts for threads, drafts,
  skipped/private buyers; `/leads` hub loads now request it and surface a
  compact read-path/count note when the inbox is empty or using fallback.
- Done: add a direct `/api/cron/attention` contract test. Do not add
  scheduler-thread or lock-owner metadata until a real failure proves "jobs due
  but ticker not moving."
- Done: add one positive protected example plugin API mount test. Keep public
  plugin manifest metadata to `has_api`; document restart behavior before
  adding public mount/import status.

### 5. Hosted Login, License, Device Flow, Diagnostics

Primary files:

- `backend/src/app/api/`
- `backend/src/lib/auth-guard.ts`
- `backend/src/lib/admin-guard.ts`
- `backend/src/lib/store.ts`

Source anchors:

- `/api/health` only proves the Next handler is alive at
  `backend/src/app/api/health/route.ts:5`.
- `requireAccess(...)` maps missing/invalid bearer to 401, revoked or
  cross-user license to 403, and inactive subscription to 402 in
  `backend/src/lib/auth-guard.ts:11` and `backend/src/lib/auth-guard.ts:22`.
- Admin routes add `requireAdmin(...)` in `backend/src/lib/admin-guard.ts:12`.
- Login is public/rate-limited in
  `backend/src/app/api/auth/login/route.ts:21`.
- License refresh uses refresh token hash in
  `backend/src/app/api/license/refresh/route.ts:25`.
- Desktop code-sign-in opens hosted `/link` from `desktop/src/login.html:198`
  through `desktop/src/main.js:1607` and `desktop/src/main.js:1612`.
- Device start and poll are public device-code routes in
  `backend/src/app/api/device/start/route.ts:24` and
  `backend/src/app/api/device/poll/route.ts:20`; lookup/approve are the hosted
  `/link` browser approval leg, not direct desktop curls.
- Login-code request/verify are alternate CLI/admin-web auth paths, not the
  first desktop debugging path.
- Diagnostics ingestion sanitizes/redacts and duplicate-upserts events in
  `backend/src/app/api/diagnostics/session-events/route.ts:155`,
  `backend/src/app/api/diagnostics/session-events/route.ts:184`, and
  `backend/src/app/api/diagnostics/session-events/route.ts:239`.

Debug questions:

- Is the issue hosted backend liveness, auth, license refresh, device flow, or
  local dashboard auth?
- Is a 401 local session-token auth or hosted bearer auth?
- Does diagnostics return only accepted count when sanitizer details are needed?

First fix candidates:

- Build a small hosted caller map: caller, path, method, auth type, token type,
  status-code meaning, and backend store touch. Do not build a full backend
  smoke suite in this desktop epic.
- Keep hosted to a caller-route map plus three future route-handler contracts:
  login/refresh, device approve-to-poll one-shot, and diagnostics
  sanitizer/idempotency. No per-route smoke suite.
- For desktop user reports, prioritize login, license refresh, `/link` device
  flow, and optional diagnostics before admin, skills, automations, or Stripe.

## Focused Issues

### Issue 0 - Route Map Truth Tests

Goal: make sure the debugging read is reading right before the team debugs the
app.

Deliverables:

- A route-map checklist covering desktop IPC, local auth, active chat, feature
  routes, and hosted routes. Hosted route file-list drift is exact-compared,
  not just count-checked.
- Each pathway lists read check, contract check, and runtime check.
- First failed read check is treated as doc drift until source proves otherwise.

Acceptance:

- Running the checklist shows whether `/api/ws`, local token injection, source
  inbox, cron attention, plugin mount, hosted license/device, and diagnostics
  paths still exist and have callers.
- The epic does not route people into `/api/pty`, `/api/pub`, `/api/events`, or
  hosted admin routes unless the read check proves the active failing path uses
  them.

### Issue 1 - Desktop Probe Playbook

Goal: classify launch failures without reading the whole repo.

Deliverable:

- One command or doc block that prints:
  - app version,
  - selected/listening port,
  - port owner,
  - `/api/status` code/body,
  - embedded-chat flag from `/`,
  - served asset refs,
  - bundled asset refs,
  - latest startup log summary,
  - updater log lines, unless the probe runs inside the renderer IPC context.

Acceptance:

- A blank/loading/stale-dashboard report is classified as backend crash, stale
  bundle, auth gate, wrong port, or renderer load failure in under five minutes.

### Issue 2 - Tighten Launch And Updater Diagnostics

Goal: remove the biggest desktop ambiguity.

Deliverables:

- Done: make `backendIsReady(...)` require a meaningful healthy status.
- Remaining: add compact startup probe logging before `backend:timeout`.
- Done: route `updater:check` through the serialized update-check path.
- Done: delete the dead `dismissToast` preload exposure.
- Done: fix stale updater comment that says two hours while code polls every
  three minutes.

Acceptance:

- `backend:timeout` includes enough detail to know which check failed.
- Update checks cannot run in parallel through IPC. Verified locally by static
  check: `autoUpdater.checkForUpdates()` has one call site behind the shared
  guard.

### Issue 3 - Local Auth And `/api/ws` Debugging

Goal: make 401s and chat socket failures self-explanatory.

Deliverables:

- No-secret local auth diagnostic or equivalent documented curl checklist.
- Done: local auth contract tests cover missing token, bad token, custom
  session-header plus proxy `Authorization`, and served-SPA session-cookie
  authorization before JS runs.
- Done: `GatewayClient` surfaces `/api/ws` close code/reason.
- Done: focused backend tests for missing token, bad token, and embedded-chat
  disabled `/api/ws` `4401`/`4403`.

Acceptance:

- Local 401 can be separated from hosted bearer 401.
- Chat socket failures show `4401`, `4403`, or network/close context instead of
  only `"WebSocket closed"`.

### Issue 4 - Feature Route Debug Metadata

Goal: only after runtime/auth/chat are healthy, make feature route symptoms
traceable to their owner.

Deliverables:

- Done: source inbox backend `debug=1` metadata on the existing route; fallback
  errors return exception type plus stable code only, not raw DB exception text.
- Done: direct `/api/cron/attention` route contract test.
- Done: positive protected example plugin API mount contract test.
- Remaining: plugin restart behavior is documented before any public
  mount-status metadata.

Acceptance:

- Empty source inbox reports show operational-vs-legacy path and counts.
- Cron/attention reports are tested at the route, not inferred from the
  composite surfaces page.
- Plugin API 404s distinguish missing manifest, missing asset, and unmounted API
  router only after the positive mount contract exists.

### Issue 5 - Hosted Caller Map, Not Hosted Smoke Suite

Goal: avoid confusing hosted auth/license failures with local desktop failures.

Deliverable:

- Small matrix for hosted routes used by desktop:
  - `/api/health`,
  - `/api/auth/login`,
  - `/api/license/refresh`,
  - `/link` browser approval leg,
  - device start/lookup/approve/poll,
  - `/api/diagnostics/session-events`,
  - login-code request/verify as alternate CLI/admin auth.

Acceptance:

- Each route lists caller, auth type, status-code meaning, and what it proves.
- Hosted tests stay limited to login/refresh, device approve-to-poll one-shot,
  and diagnostics sanitizer/idempotency once a backend test harness exists.
- Admin, skills, automations, and Stripe stay downstream unless the report names
  them.

### Issue 6 - Complete Route Inventory

Goal: make route drift impossible to miss.

Deliverables:

- Generated local FastAPI inventory: path, method, file, line, route family.
- Generated local WebSocket inventory: path, auth gate, file, line, active caller.
- Generated plugin inventory: manifest, asset entry, API file, API routes,
  WebSocket routes.
- Generated hosted Next inventory: path, method, file, auth guard, store touch.
- Generated desktop IPC inventory: channel, preload exposure, renderer caller,
  main handler.

Acceptance:

- Every route-shaped thing from `web_server.py`, `web_routes`, `cli/plugins`,
  `backend/src/app/api`, and `desktop/src` appears exactly once in the map.
- Every inventory row has one of: active frontend caller, runtime-only caller,
  CLI caller, hosted web caller, plugin caller, or intentionally orphaned.
- CI or a local check fails when the route inventory changes and the map is not
  refreshed.

Current status: `cli/docs/desktop-debug-route-inventory.tsv` is generated from
local FastAPI routes/WebSockets, dashboard plugin APIs, and hosted Next route
handlers, and `cli/tests/elevate_cli/test_debug_route_inventory.py` fails when
the checked-in TSV drifts. Caller, runtime smoke, and desktop IPC maps remain
separate readiness artifacts.

### Issue 7 - Full Local Route Contract Coverage

Goal: local dashboard production readiness is tested by route family, not only
the main desktop funnel.

Deliverables:

- Contract coverage map for these route families:
  - local auth, status, license, config/env/model/provider,
  - sessions/files/uploads/logs/actions/workspace,
  - contacts/admin/leads/setup/onboarding,
  - admin deals/actions/tasks/templates,
  - source connectors/source inbox/outreach/sender,
  - cron/heartbeats/tasks/approvals/experiments,
  - comms/channels/social/integrations/composio/ayrshare,
  - skills/toolsets/analytics,
  - agent hub/handoffs/worker/harness,
  - dashboard themes/plugins/plugin APIs/assets,
  - chat WebSockets and secondary PTY/pub/events.
- Existing tests are linked by node, not just broad file names.
- Missing route-family tests are listed with the smallest new test needed.

Acceptance:

- No active local route family is marked production-ready without at least one
  focused contract test or a documented, approved gap.
- Broad test files are allowed in the production sweep, but every broad file
  must explain which route family it covers.
- Feature routes with `debug=1` claims have tests proving the debug payload
  cannot drift silently.

### Issue 8 - Hosted Backend Production Coverage

Goal: hosted routes that affect desktop auth, licensing, diagnostics, account
state, and billing have route-handler coverage.

Deliverables:

- Backend test harness for Next route handlers exists in
  `backend/test/route-harness.ts`; `backend/package.json` has a `test` script.
- Contract tests for auth login/signup/forgot/reset/login-code, license refresh,
  device start/lookup/approve/deny/poll, diagnostics ingestion, `me`, orgs,
  admin, skills, automations, and Stripe webhook route behavior.
- Staging smoke plan for live hosted dependencies: Supabase, Stripe, email,
  diagnostics, and license/device flows.

Acceptance:

- `/api/health` is treated only as Next liveness.
- License refresh tests assert access-token rotation and entitlements, not a
  `license_id` field that the route does not return.
- Device tests prove approve-to-poll one-shot behavior.
- Diagnostics tests prove sanitizer behavior and idempotent duplicate upsert.
- Stripe webhook stays isolated from desktop readiness except when billing is
  the named failure.

### Issue 9 - Frontend Caller And Error-State Coverage

Goal: every route read is paired with the UI path and error surface that uses it.

Deliverables:

- Caller map for `cli/web/src/lib/api.ts`, raw `fetch`, raw `/api/` strings,
  WebSocket constructors, desktop IPC access, and hosted external links.
- UI error-state inventory for dashboard startup, login, chat, admin, leads,
  cron, plugins, agent hub, integrations, social, and hosted auth.
- Done: frontend tests for central API error parsing, session header injection,
  `GatewayClient` close code/reason, and `/leads` profile-status label mapping
  for the persisted source-inbox status route.
- Done: `/leads` profile status dropdown now calls
  `POST /api/source-inbox/profile` instead of only mutating local component
  state; the route contract test proves the dashboard POST reaches
  `update_profile_state`.
- Remaining: at least one critical empty/error state per major dashboard
  surface.

Acceptance:

- Every production route family has a known caller or is marked intentionally
  runtime-only.
- Local 401, hosted bearer 401, hosted 402, hosted 403, and network failure are
  distinguishable in the UI or debug output.
- Chat socket failures preserve close code/reason through the React error path.

### Issue 10 - Runtime Smoke And Packaged App Readiness

Goal: tests prove the repo code works, and runtime probes prove the installed
app is reading the same build.

Deliverables:

- Dev dashboard smoke: start server, read selected port, probe `/api/status`,
  `/`, one protected route, `/api/ws`, and representative feature routes.
- Packaged app smoke: launch installed app, read
  `~/Library/Logs/Elevate/main.log`, compare bundled-vs-served assets, verify
  selected port, auth injection, updater state/log lines, and app version.
- Current packaged proof: installed app seal validation is part of
  `cli/scripts/installed_runtime_smoke.py`; the final installed `1.2.58` app
  passes app-version, notarized seal validation, repo/installed `web_dist`
  parity, served-asset parity, packaged WhatsApp bridge checks, protected HTTP
  auth without/with extracted session token, `/api/ws` streaming, final text,
  and session resume. Final installed Comms channel probe returned
  `invalid_count: 0` after the legacy self-recipient projection fix.
- Fresh candidate proof: `release:mac` now runs `smoke:mac` before `ship:mac`.
  Current local `1.2.58` x64 and arm64 built apps pass app-version, seal, repo
  `web_dist` parity, and packaged WhatsApp bridge checks after the final Comms
  fix.
- Preflight proof: `desktop/scripts/preflight-apple-release.js` compares the
  package version to the public update feed, not stale local `dist/` output.
- Local ship proof: `desktop/scripts/ship-to-hetzner.js` verifies the local
  feed version, required x64/arm64 zip/dmg set, sizes, and sha512 hashes before
  running any `rsync`/`ssh` remote mutation.
- Post-ship proof: `desktop/scripts/ship-to-hetzner.js` now refuses to print
  "live" until the public `latest-mac.yml` matches the package version plus
  local `url`/`sha512`/`size` entries, and all referenced zip/dmg artifacts
  plus stable latest DMG aliases answer with the expected byte size.
- Hosted staging smoke: health, login, refresh, device flow, diagnostics, and
  Stripe webhook only in staging.
- Support bundle command that collects no secrets and redacts tokens.

Acceptance:

- A fresh install, update, and restart are smoke-tested before production-ready.
- Packaged-only failures have a repeatable probe, not a manual hunt.
- Support bundle includes enough evidence to classify launch/backend/auth/chat/
  feature/hosted/updater failures without exposing tokens.

### Issue 11 - Production Missing-Test Ledger

Goal: unresolved testing gaps are visible, owned, and finite.

Deliverables:

- Ledger columns: route family, route examples, current caller, existing tests,
  missing contract, runtime smoke, owner, priority, block readiness yes/no.
- Closed gaps from this pass:
  - `/api/ws` missing-token, bad-token, and embedded-chat-disabled close codes,
  - frontend `api.ts` session-header injection,
  - `/api/source-inbox?debug=1` read-path/counts/sanitized fallback metadata,
  - `/api/cron/attention`,
  - positive protected example plugin API mount,
  - updater manual-check serialization,
  - dead updater `dismissToast` preload exposure,
  - `GatewayClient` WebSocket close-code/reason propagation,
  - hosted backend route-handler harness,
  - hosted login/refresh/device/diagnostics handler contracts,
  - hosted revoked-bearer `403` contract,
  - route inventory drift guard with exact hosted file-list comparison,
  - desktop launch readiness requiring `200` plus Elevate status payload,
  - release-path `smoke:mac` gate before `ship:mac`,
  - Apple preflight public-feed version gate,
  - local pre-ship feed/artifact version/hash/size gate,
  - finalize exact x64/arm64 zip/dmg artifact gate,
  - post-ship public feed/artifact verifier before declaring a release live,
  - installed app `codesign`/`spctl` smoke gate,
  - packaged WhatsApp bridge script/package/dependency checks,
  - installed runtime smoke discovers the selected dashboard port from
    `main.log`, records it, compares served assets to installed `web_dist`,
    probes protected local HTTP auth before sidecar prompts, and ignores stale
    untimestamped bad-log continuations,
  - desktop top-level navigation rejects arbitrary `file://` and external
    schemes while allowing dashboard/app-owned local pages,
  - desktop preload IPC contract checks every exposed invoke has a main handler
    and every exposed bridge leaf has a renderer caller, with unused
    `auth.status/logout` bridge leaves removed,
  - desktop install fallback handles rejected install/retry IPC and reloads the
    setup page when installer exit `0` still leaves the backend unavailable,
  - hosted account/org/skills-list/automation-list read contracts,
  - hosted signup/forgot/reset route contract, production mailer outage
    visibility, and reset cleanup-before-password-change ordering,
  - hosted self-service license read/revoke tenant guard and
    sign-out-everywhere current-license preservation,
  - hosted bearer license/user ownership binding,
  - signed hosted Stripe webhook contract preventing unknown subscription
    prices from granting `pro`,
  - account billing distinguishes Stripe customer records from active
    subscriptions so checkout customer creation alone does not hide upgrade
    buttons,
  - hosted Stripe checkout/portal external failures return JSON errors, and
    checkout audit logging cannot break a Stripe redirect URL,
  - hosted org seat-limit enforcement for direct member adds and stale
    invitation accepts,
  - hosted inactive invitation accepts do not consume the invite or add
    membership before returning `402`,
  - hosted admin license listing and tenant-safe revoke contract,
  - hosted `skills/run` requested-skill and invocation-audit contract,
  - hosted admin missing-record mutation `404` contracts,
  - hosted device poll refuses to return a one-shot refresh token if clearing
    `refresh_token_plain` fails,
  - social media page surfaces partial route-load failures instead of only
    showing an error when every source fails,
  - Cron route load and attention failures surface real error text,
  - `/social-media` direct loads include workflow/cron data for the jobs header,
  - desktop gateway reinstall when gateway status reports a recovered
    packaged-resource `_missing` error,
  - fresh arm64 candidate runtime smoke with bundled-vs-repo `web_dist`,
    served asset parity, protected local HTTP auth, `/api/ws` stream events,
    final text, and transcript resume proof,
  - unpacked app-dir updater checks skip cleanly when `app-update.yml` is not
    bundled instead of logging an ENOENT updater error,
  - `elevate debug share --session/--last` recorder-event support bundle
    section with export-time re-sanitization and redaction report,
  - remote `elevate debug share --no-redact` is rejected before upload; no-redact
    mode is local-only,
  - `/api/dashboard/plugins/rescan` requires the dashboard session token while
    `/api/dashboard/plugins` remains public read-only,
  - `debug.trace` redacts blank-trace email/token/password/path values before
    writing `blank-trace.log`,
  - backend diagnostics string redaction for email/token/password/path values.
- Remaining readiness-blocking gaps include:
  - public update feed/artifacts not yet shipped and verified for `1.2.58`
    (current public feed is still `1.2.51`),
  - `/Users/dartagnanpatricio/Applications/Elevate.app` is still stale relative
    to the fresh candidate and needs replacement from finalized/notarized
    artifacts plus installed-app smoke,
  - packaged updater status/check/install still needs focused proof against a
    finalized app with `app-update.yml`,
  - UI E2E is not yet complete across install, login, chat, tools,
    automations, update, and quit/reopen,
  - hosted backend coverage still lacks deeper admin/org mutation success/
    permission route contracts and automation mutation failure mocks,
  - route-family coverage ledger is seeded, but full row-level route inventory
    is not complete yet,
  - live runtime warnings still need owner/recovery classification: WhatsApp
    enabled but not paired, Oura MCP connection failure, missing
    `OPENAI_API_KEY` for embeddings, Composio Gmail HTTP 422, and config
    version `24` behind latest `25`.

Acceptance:

- Production-ready cannot be claimed while any readiness-blocking gap is open.
- Non-blocking gaps are explicitly labeled non-blocking with a reason.
- Ledger updates are part of the verification command set.

## Debug Attack Order

1. Run the Route Map Truth Tests for the suspected pathway.
2. Read `~/Library/Logs/Elevate/main.log` and identify the selected port.
3. Probe `/api/status` and `/` on that port.
4. Compare served assets to bundled `cli/elevate_cli/web_dist/index.html`.
5. Confirm local API token injection with one protected route.
6. Test `/api/ws`: `gateway.ready`, `session.create`, `session.list`,
   `session.resume`.
7. Only then inspect feature routes:
   - source inbox and today,
   - admin deals/tasks,
   - cron jobs and cron attention,
   - agent worker,
   - plugin manifest and plugin API.
8. If login/license is involved, switch to hosted caller map:
   - health means only Next is up,
   - login/license/device flow prove account state,
   - diagnostics prove event ingestion.

## Verification Commands

```bash
cd /Users/dartagnanpatricio/elevate

# Frontend/desktop builds require Node >=22.12. In Codex desktop, prefer:
export PATH=/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH

# Fast-path route-map truth checks. If one fails, fix the epic before debugging behavior.
rg -n "backendIsReady|backendBundleMatches|dashboardChatEnabled|ensureBackend|updater:check|updater:status|updater:install|elevateDesktop|desktopUpdater|checkNow" \
  desktop/src/main.js desktop/src/preload.js cli/web/src/App.tsx
rg -n "provider|url|target|zip|electron-updater" desktop/package.json
rg -n "_SESSION_HEADER_NAME|_PUBLIC_API_PATHS|_has_valid_session_token|auth_middleware|X-Elevate-Session-Token|__ELEVATE_SESSION_TOKEN__|fetchJSONNetwork" \
  cli/elevate_cli/web_server.py cli/web/src/lib/api.ts cli/web/vite.config.ts
rg -n "embeddedChat|__ELEVATE_DASHBOARD_EMBEDDED_CHAT__|ELEVATE_DASHBOARD_TUI|/chat" \
  cli/web/src/App.tsx cli/elevate_cli/web_server.py cli/elevate_cli/main.py
rg -n "GatewayClient|/api/ws|session\\.create|session\\.resume|session\\.list" \
  cli/web/src/pages/ChatPage.tsx cli/web/src/lib/gatewayClient.ts cli/elevate_cli/web_server.py cli/tui_gateway
rg -n "ChatSidebar|/api/pty|/api/pub|/api/events" \
  cli/web/src cli/elevate_cli/web_server.py
rg -n "/api/source-inbox|/api/cron/attention|/api/dashboard/plugins|/api/plugins|/api/today|/api/agent" \
  cli/web/src/lib/api.ts cli/elevate_cli/web_routes cli/elevate_cli/web_server.py
find backend/src/app/api -path "*route.ts" -type f | sort | \
  rg "backend/src/app/api/(health|auth/login|auth/login-code/(request|verify)|license/refresh|device/(start|lookup|approve|deny|poll)|diagnostics/session-events)/route.ts"
rg -n "api\\.openExternal\\(\"link\"\\)|/link|api/license/refresh|api/device/(start|lookup|approve|deny|poll)|api/diagnostics/session-events|auth/login-code|requireAccess|requireAdmin" \
  desktop/src/main.js desktop/src/login.html cli/elevate_cli/license.py \
  cli/elevate_cli/diagnostics/session_uploader.py backend/src/app/link/page.tsx \
  backend/src/app/admin/login/page.tsx backend/src/app/api backend/src/lib

# Production sweep inventory: all local routes, hosted routes, callers, and tests.
rg -n "@(app|router)\\.(get|post|put|patch|delete)|@app\\.websocket|@router\\.websocket" \
  cli/elevate_cli/web_server.py cli/elevate_cli/web_routes cli/plugins --glob "*.py" \
  | tee /tmp/elevate-local-route-inventory.txt
find backend/src/app/api -path "*route.ts" -type f | sort
rg -n "fetchJSON|cachedFetchJSON|fetch\\(|/api/|new WebSocket|elevateDesktop|openExternal\\(" \
  desktop/src cli/web/src backend/src/app --glob "!**/web_dist/**" --glob "!**/node_modules/**" \
  | tee /tmp/elevate-frontend-caller-inventory.txt
find cli/tests -type f -name "test_*.py" | sort \
  | tee /tmp/elevate-pytest-file-inventory.txt
find cli/web/src -type f \( -name "*.test.ts" -o -name "*.test.tsx" -o -name "*.spec.ts" -o -name "*.spec.tsx" \) | sort \
  | tee /tmp/elevate-vitest-file-inventory.txt
find backend -maxdepth 3 -type f \( -name "*test*" -o -name "vitest.config.*" -o -name "jest.config.*" \) \
  -not -path "*/node_modules/*" -not -path "*/.next/*" | sort \
  | tee /tmp/elevate-backend-test-inventory.txt

# Fast-path contract tests after source reads pass.
cd /Users/dartagnanpatricio/elevate/cli
.venv/bin/python -m pytest \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_unauthenticated_api_blocked \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_reveal_env_var_bad_token \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_gateway_ws_ready_and_clean_disconnect \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_gateway_ws_rejects_missing_token \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_gateway_ws_rejects_bad_token \
  tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::test_gateway_ws_rejects_when_embedded_chat_disabled \
  tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_source_inbox_debug_reports_db_read_path_and_counts \
  tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_source_inbox_debug_reports_jsonl_fallback \
  tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_cron_attention_reports_errored_and_stale_jobs \
  tests/hermes_cli/test_web_server.py::TestNewEndpoints::test_example_plugin_api_mount \
  tests/tui_gateway/test_protocol.py::test_session_resume_returns_hydrated_messages \
  tests/tui_gateway/test_protocol.py::test_session_resume_multicasts_events_to_all_attached_transports \
  tests/elevate_cli/data/test_today.py::test_today_endpoint_returns_page_snapshot \
  tests/elevate_cli/test_admin_deals_endpoints.py::test_admin_tasks_endpoint_projects_phase_gate_and_ai_actions \
  -q

# Secondary chat routes only after proving the active failure uses them.
.venv/bin/python -m pytest tests/hermes_cli/test_web_server.py::TestPtyWebSocket -q

cd /Users/dartagnanpatricio/elevate/cli/web
npm test -- gatewayClient
npm test -- api-errors

cd /Users/dartagnanpatricio/elevate
node --check desktop/src/main.js
node --check desktop/src/preload.js
rg -n "updater:dismiss-toast|dismissToast|autoUpdater\\.checkForUpdates\\(" desktop/src/main.js desktop/src/preload.js

# Production sweep test collection. This is broader than the fast incident path.
cd /Users/dartagnanpatricio/elevate/cli
.venv/bin/python -m pytest -q \
  tests/elevate_cli/test_session_recorder.py \
  tests/hermes_cli/test_debug.py \
  tests/elevate_cli/test_debug_route_inventory.py \
  tests/elevate_cli/test_installed_runtime_smoke.py
.venv/bin/python -m pytest --collect-only -q \
  tests/hermes_cli/test_web_server.py \
  tests/hermes_cli/test_web_server_host_header.py \
  tests/elevate_cli/test_lifecycle_endpoints.py \
  tests/elevate_cli/test_admin_deals_endpoints.py \
  tests/elevate_cli/test_admin_dispatch_endpoints.py \
  tests/elevate_cli/test_admin_templates_endpoints.py \
  tests/elevate_cli/data/test_today.py \
  tests/elevate_cli/test_agent_hub_pg.py \
  tests/elevate_cli/test_agent_hub_cortext_packs.py \
  tests/elevate_cli/test_agent_handoffs.py \
  tests/elevate_cli/test_source_connector_run_sessions.py \
  tests/hermes_cli/test_cron.py \
  tests/hermes_cli/test_plugins.py \
  tests/hermes_cli/test_agent_hub.py \
  tests/test_tui_gateway_server.py \
  tests/tui_gateway/test_protocol.py

cd /Users/dartagnanpatricio/elevate/cli/web
npm test
npm run build

cd /Users/dartagnanpatricio/elevate/backend
npm test
npm run build

# Remaining missing tests/probes to add with implementation:
# - Fresh installed app must pass codesign/spctl and bundled web_dist parity.
```

Current missing local route-family contract ledger:

- `composio`: backend routes and dashboard callers exist; no local
  `cli/tests` contract yet.
- `ayrshare`: backend routes and dashboard callers exist; no local
  `cli/tests` contract yet.
- `social`: backend routes and dashboard callers exist; no local `cli/tests`
  contract yet.
- `integrations`: backend routes and dashboard callers exist; no local
  `cli/tests` contract yet.
- `activity`: fleet feed route and dashboard caller exist; no local
  `cli/tests` contract yet.

## Done Definition

- Desktop failures classify through the funnel before feature debugging starts.
- The launch probe explains readiness failures without a broad repo scan.
- Route-map truth checks pass or the epic is updated before implementation
  starts.
- Local 401s and hosted bearer 401s are visibly different.
- Chat debugging starts at the active `/api/ws` path.
- Feature route debugging adds metadata to existing routes before adding new
  readers or observability systems.
- Production route inventory, frontend caller inventory, test coverage map,
  runtime smoke map, and missing-test ledger exist and are current.
- Every local route family has a contract test or an explicit readiness gap.
- Every hosted route family has route-handler coverage or an explicit staging
  smoke/gap.
- Packaged `Elevate.app` launch/update/runtime smoke passes before production
  readiness is claimed.
