# Handoff — Agent onboarding wizard rebuild (2026-05-14)

Companion to `handoff-2026-05-14.md` (earlier slices today). This one covers
the `/agent-onboarding` wizard rebuild — S89.20 through S89.25.

## Active goal (still standing)

From the original `/goal` directive — keep applying it:

> Continue the original UI production-polish goal. Read and follow
> `cli/docs/ui-production-polish-overnight-goal.md` exactly. Do not ask
> questions. Audit every tab/component, update
> `cli/docs/ui-production-polish-plan.md`, implement small verified local
> commits, do not push, and continue until done or blocked.

Plus user-approved scope expansion: "Full rebuild against real connect
flows" + "Full pairing ritual in wizard."

## What landed this session (newest first)

All on `main`, local only, **no push**.

| Commit | Slice | Scope |
| --- | --- | --- |
| `63f809d01` | — | Audit table log for S89.25 |
| `69743519b` | S89.25 | Real model catalog dropdown in wizard Step 1 |
| `5db9c64d3` | — | Audit table log for S89.20–24 |
| `17fc851cc` | S89.24 | Telegram pairing ritual in wizard step 3 (UI) |
| `fbf2c3b17` | S89.23 | Telegram pairing ritual endpoints (backend + types) |
| `0fd7b6271` | S89.22 | Wizard Composio step embeds real connect flow |
| `e66e7b53e` | S89.21 | Channel toggles reflect env + backend state |
| `d3467b4fc` | S89.20 | Wizard Step 1 reflects real CLI auth state |

### S89.20 — Step 1 reflects real CLI auth state (`d3467b4fc`)

The wizard's "Brain" step was driven entirely by env-overlay state. If
the user had run `elevate auth add anthropic` from the CLI it didn't
show up — the step still demanded an API key the user no longer needed.

**Changes** (`web/src/pages/agent-onboarding/wizard.tsx`):

- Pulled in `OAuthProvidersCard` and a `useEffect` that fetches
  `/api/providers/oauth` whenever the user lands on the models step.
- New `connectedProviderIds: Set<string>` memo flags providers with
  `status.logged_in === true`.
- Two stacked sections inside Step 1:
  1. Live OAuth providers card (real PKCE / device-code flows).
  2. Provider dropdown with `· connected` suffix on signed-in
     providers.
- `missingMessage` for this step now passes when ANY of: OAuth
  connected, env secret detected, user pasted a key in-session.
- Auto-defaults `primaryProvider` to the first connected
  non-`claude-code` provider when the draft is blank — saves a click
  if the user already authed via CLI.

### S89.21 — Channel toggles reflect env + backend state (`e66e7b53e`)

User said: *"these say off but they are on?"* All channel toggles
(Telegram / Discord / WhatsApp / Slack) read only from `draft.*BotToken`
which is empty when creds live in `~/.elevate/.env`.

**Changes** (`web/src/pages/agent-onboarding/wizard.tsx`):

- `configuredChannelKeys` useMemo scans `setup.items` for
  `operator_channel_*` rows with `status === "configured"`.
- Each channel toggle now unions the backend status with the
  draft-field check.
- Telegram additionally unions `draft.telegramSecretPresent` since the
  gateway's env-only state is the operational truth.

### S89.22 — Wizard Composio step embeds real connect flow (`0fd7b6271`)

Step 4 had a password field plus a dead `composioWorkspace` field that
Composio's managed-OAuth flow doesn't use. Connecting a toolkit required
a separate trip to ConfigPage.

**Changes** (`web/src/pages/agent-onboarding/wizard.tsx`):

- Removed the `composioWorkspace` `WizardField`.
- New `ComposioConnectionsInline` component (~200 lines, lazy-rendered
  when an API key is present):
  - Reads `getComposioStatus` / `getComposioConnections` /
    `getComposioToolkits`.
  - Renders connected chips + search + 12-toolkit grid.
  - Opens OAuth via `window.open(..., "_blank")` for managed flows.
  - Deep-links to `/config#composio` for custom-creds toolkits.
  - Refreshes on window focus.

### S89.23 — Telegram pairing endpoints (`fbf2c3b17`)

The CLI moved to a pairing ritual (`elevate gateway setup` + `elevate
pairing approve telegram <code>`) months ago, but the wizard still
asked for raw `chatId`. No path to drive the ritual from the UI.

**Backend changes** (`cli/elevate_cli/web_server.py`):

- `POST /api/telegram/pair/start`
  - Saves the BotFather token via `save_env_value` +
    `_sync_executive_telegram_aliases`.
  - Flips `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR=pair`.
  - Restarts the gateway in the background.
- `GET /api/telegram/pair/pending`
  - Wraps `gateway.pairing.PairingStore.list_pending("telegram")`.
  - Also returns already-approved users.
- `POST /api/telegram/pair/approve`
  - Calls `approve_code`.
  - Merges `user_id` into `TELEGRAM_ALLOWED_USERS`.
  - Flips `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR` back to `ignore` so
    strangers can't keep minting codes.
  - When `set_home: true`, pins `TELEGRAM_HOME_CHANNEL` via
    `_sync_executive_telegram_aliases`.
- All token-protected via `_require_token`.

**Frontend changes** (`web/src/lib/api.ts` + `api-types.ts`):

- `api.startTelegramPairing(botToken)`
- `api.listTelegramPairings()`
- `api.approveTelegramPairing(code, setHome)`
- Types: `TelegramPairStartResponse`, `TelegramPendingEntry`,
  `TelegramApprovedEntry`, `TelegramPairListResponse`,
  `TelegramPairApproveResponse`.

### S89.24 — Telegram pairing ritual in the wizard UI (`17fc851cc`)

New `TelegramPairingPanel` component inside the Telegram channel
toggle body. 3-stage state machine:

1. **Token entry** — paste BotFather token, click "Start pairing"
   (hits `/api/telegram/pair/start`).
2. **Polling** — 3-second loop against `/api/telegram/pair/pending`,
   "Waiting for /start" affordance. As soon as the bot mints a code,
   an Approve button renders inline.
3. **Paired** — confirmation + "Pair a different bot" reset.

Plus:

- Token-already-in-env fast-forwards past stage 1.
- After approval, refreshes the setup snapshot so the channel toggle
  stays lit on re-render.

### S89.25 — Real model catalog dropdown (`69743519b`)

User reaction to Step 1: *"why am i not able to go an pick allt he
otpoins we have for models and also scroll through the models available
we litereally haver the list"*. The Model ID field was a free-text
input. Live catalog already existed in
`elevate_cli.models.provider_model_ids` (live API for codex / nous /
anthropic / copilot + static fallback) but the wizard had no path to
it.

**Backend** (`cli/elevate_cli/web_server.py`):

- `GET /api/models/by-provider?provider=<id>` wraps
  `provider_model_ids(normalize_provider(provider))`. Returns
  `{provider, models[]}`. Degrades to empty list on error.

**Frontend** (`web/src/lib/api.ts` + `web/src/pages/agent-onboarding/wizard.tsx`):

- New `api.getProviderModels(providerId)`.
- `catalogProviderId` useMemo maps the grouped wizard provider value
  to the concrete provider id based on connection state:
  - `openai` → `openai-codex` when Codex auth is live.
  - `anthropic` → `claude-code` when subscription is the only flow.
  - `qwen` → `qwen-oauth`.
- `useEffect` refetches on `catalogProviderId` change with a
  cancellation flag.
- New `WizardModelPicker` component:
  - Scrollable native `<select>` populated by the live catalog.
  - Preserves the user's current value as the first option (so
    unreleased preview ids aren't silently dropped).
  - "custom…" toggle in the label swaps in a text input for one-off
    ids.
  - Shows `loading…` chip while fetching.
  - "X models available · scroll the list" footer text.

## Files touched this session

- `cli/elevate_cli/web_server.py` — pairing endpoints + model catalog
  endpoint (4 new routes total).
- `cli/web/src/lib/api.ts` — 4 new methods.
- `cli/web/src/lib/api-types.ts` — 5 new interfaces.
- `cli/web/src/pages/agent-onboarding/wizard.tsx` — Step 1, 3, 4
  rebuild + `TelegramPairingPanel` + `ComposioConnectionsInline` +
  `WizardModelPicker`.
- `cli/docs/ui-production-polish-plan.md` — 6 audit-table rows.
- `cli/elevate_cli/web_dist/` — rebuilt bundle.

## How to verify (run after every slice)

```bash
cd ~/elevate/cli/web
npx tsc -b
npx vite build
```

Both must exit 0. Bundle output goes to `cli/elevate_cli/web_dist/`.
Stage source + regenerated `web_dist/` together so the FastAPI backend
serves the new bundle.

Last clean run: `tsc -b` exit 0, vite 2.38s (S89.25 build).

## Selective staging (important)

`cli/elevate_cli/web_server.py` has a pre-existing dirty hunk
(source-connectors rewrite) from a prior session that has not yet been
committed. **Do not stage that hunk** — it's outside this session's
scope. Use `git apply --cached` with a trimmed patch when you need to
stage only your hunk in this file. Example:

```bash
git diff cli/elevate_cli/web_server.py > /tmp/ws.full.patch
head -36 /tmp/ws.full.patch > /tmp/ws.mine.patch   # only my hunk
git apply --cached /tmp/ws.mine.patch
```

Same applies to `web/src/pages/RealEstateHubPages.tsx` and other files
listed in `git status` as `M` but not authored by this session.

## What's still pending on the wizard

Nothing critical. Everything the user explicitly asked for is wired:

- Real OAuth providers (S89.20)
- Channel toggles reflect env state (S89.21)
- Composio managed-OAuth from inside the wizard (S89.22)
- Telegram pairing ritual end-to-end (S89.23 + S89.24)
- Scrollable model catalog dropdown (S89.25)

If you want to keep pushing the wizard, candidate next slices:

1. **Discord pairing ritual** — Telegram now has a pairing flow; Discord
   still asks for the channel ID raw. If Discord supports a similar
   pairing pattern in `gateway.pairing.PairingStore`, mirror the
   `TelegramPairingPanel` for Discord.
2. **Validate model id against catalog on Next** — if the user typed a
   custom model id that the provider rejects, the wizard finishes "OK"
   and the first prompt fails. Add a `validateModel` call (probably
   `/api/model/info` style HEAD-check) before advancing.
3. **Embedding model picker** — Step 1 still has a free-text Model ID
   field for the embedding model. Apply the same `WizardModelPicker`
   pattern, scoped to embedding-capable providers.
4. **Step 5 (subagents) review** — has not been audited this session;
   may have similar env-overlay vs real-state mismatches.

## Carry-over open issues (from `handoff-2026-05-14.md`, still live)

These are NOT new — bringing them forward so they're not lost:

1. **Backend agent loop hangs.** `prompt.submit` reaches the gateway
   but no streaming events come back. `session.interrupt` does not
   unstick it. Backend bug, not frontend. S37 (`bf40e1453`) papered
   over it for codex-300s timeouts via `close()`-from-daemon-thread but
   the root cause remains in the gateway/agent dispatch path.
2. **Steer does not persist across refresh.** Frontend mirrors steered
   text into the transcript; backend doesn't log it. Real fix is in
   the Python steer handler.
3. **Subagent activity invisible in chat.** Task tool's `tool.start`
   lands; child agent events never reach the wire. Backend
   instrumentation gap.
4. **Sidebar `is_active` lags.** 12s poll vs real-time busy state.
   Cheapest fix is a `liveSessionIds` context bumped by ChatPage.
5. **Stale `statusText` pill** ("Steer delivered" lingers).
6. **Steer-rejected UX** — no reason, no retry, no recovery.

## Carry-over user blockers (still pending action by Dartagnan)

1. **User runs `elevate auth`** to unblock Codex creds for the 3 cron
   jobs.
2. **Decide fallback draft policy** (kill `_fallback_draft_for_thread`
   vs gate behind outbound history). User leaning kill.
3. **Skipped / Approved / Dead lanes** on `/leads` page.
4. **Test Hormozi council** on Antonio / Uppercuts.
5. **Live PTY dispatch test** from CTRL Motion.

## Memory primer note

Active state is in `~/.claude/primer.md`. This handoff is the
long-form companion for the onboarding wizard rebuild work. The
earlier wave today (S79–S81: required-field gate, coach state lift,
optional-credentials wiring) is summarized in
`handoff-2026-05-14.md`.
