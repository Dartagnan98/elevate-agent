# Blank-Chat Bug — Handoff for a Fresh Session (2026-06-03)

> **Purpose:** close "Caveat 2" — the render-then-vanish blank in the desktop
> chat. This doc is self-contained: a session/person with **zero prior context**
> can pick it up, reproduce, fix, verify, and strip the debug scaffolding.
> Repo: `~/elevate`. The bug lives entirely in **`cli/web/src/pages/ChatPage.tsx`**.

---

## UPDATE 2026-06-03 (session 2) — candidate fix applied, deployed, no regression in 35 mounts

- **Applied the doc's candidate else-branch patch** in `ChatPage.tsx` (~3494). New guard
  blocks the populated→empty wipe when `prev.length >= 2 && _chatKey === "__fresh_chat__"
  && renderedChatKeyRef.current != null && renderedChatKeyRef.current !== "__fresh_chat__"`
  — i.e. resumeId transiently fell to nothing on a fresh mount while we still hold a real
  rendered chat. Logs `"blocked fresh-mount transient-null wipe (connect else)"`.
- **Safety confirmed:** every deliberate new chat navigates with `?new=<id>` (App.tsx:1612
  `startNewChat`, plus hub/config/onboarding seeds), so `_chatKey` is never `"__fresh_chat__"`
  for a real new chat → the guard can't strand a genuine fresh start.
- **Built + hot-swapped + LIVE:** chunk `ChatPage-D9EGzdAO.js` → `ChatPage-DriP2QUo.js`,
  rsync'd into the running app, served (200; old chunk 404).
- **Verification run: 35 quit+relaunch cycles** auto-resuming a 6-message chat
  (`20260603_143249_3f492b`). Result: **0 `LIST WIPED`, 0 `vanished`, 0 regressions** —
  transcript survived every relaunch. **BUT also 0 `blocked` events** → the else-branch
  transient-null race did **not reproduce** in 35 rapid mounts, so the guard was never
  observed actively catching it. The original only fired ~2x across a full DAY of real
  working churn (busy/active-turn sessions); rapid relaunches of a COMPLETED session don't
  replicate that timing. Verdict: logic-correct fix, no regression, **race not re-triggered
  → not yet positively proven.** Leave scaffolding IN and watch `blank-trace.log` during
  normal use to confirm `"blocked fresh-mount..."` fires (or that `LIST WIPED` never does).
- **STILL OPEN — separate bug:** the 14:33 partial drops (`listBefore:4 → listAfter:2`,
  no accompanying `LIST WIPED`) are NOT a full wipe and NOT touched by this fix. They come
  from a merge path (`mergeServerWithCache` / `mergeActiveTurnSnapshot`, sites ~4124–4179)
  dropping already-rendered turns. Needs its own investigation.
- **Do NOT strip scaffolding yet** (step "Strip the scaffolding" stays pending) — the
  3-trigger matrix is not green; the diagnostics are still earning their keep.

---

## UPDATE 2026-06-03 (session 3) — partial-drop pinned + fixed; watcher false-positive found

- **Pinned the partial-drop (4→2) to ONE site:** the `session.resume` handler at
  `ChatPage.tsx` ~4161. It builds `merged = mergeServerWithCache(hydrated,
  restoreTranscript(resumeId))` — i.e. from the **localStorage cache**, which can lag
  the live `prev` (a turn that just rendered isn't cached yet). Its setter only guarded
  the full-empty case (`merged.length === 0`), so a shorter-but-non-empty `merged` was
  returned raw and partial-dropped the live list. `mergeServerWithCache`'s own
  `blankTraceIfDropped` did NOT fire because its `cached` arg (the localStorage copy) was
  itself short — which is why session 2 saw "vanished" (3270 watcher) but no "merge dropped".
- **Fix applied (~4178):** same-chat partial-drop guard — when `merged.length <
  prev.length` for the same chat, return `mergeServerWithCache(merged, prev)` (prev as the
  cache) so prev's rendered tail is recovered. Logs `"recovered same-chat partial drop
  (resume merge)"`. Gated to same-chat (`renderedChatKeyRef === _chatKey` / minted) so a
  real chat switch still replaces. Built + hot-swapped: **ChatPage-BDQbfCIA.js, served 200.**
- **CRITICAL — the 3270 "vanished" watcher has FALSE POSITIVES.** It tracks rendered
  answers by **id**. On resume, the merge swaps cache ids (`stored-N`) for server ids for
  the SAME content, so it logs `"rendered assistant answer vanished"` with **`listBefore ==
  listAfter`** (content preserved, just remapped). NOT blanks. Verified: a post-fix relaunch
  produced three such events, all `listBefore:6 → listAfter:6`. **Real drops = `listAfter <
  listBefore`. Equal-count "vanished" events are id-remap noise — ignore them.**
- **Still open / next:**
  - The id-remap also forces a React remount (key change) of those answers → a flicker.
    Refinement: in `mergeServerWithCache`, keep the cached id when a server message matches
    by fingerprint (kills the remount + the watcher noise).
  - Positive proof of both guards still pending (race hard to trigger on demand). Watch
    `blank-trace.log` in real use for `"recovered same-chat partial drop"` /
    `"blocked fresh-mount transient-null wipe"` firing, and for any `listAfter < listBefore`.
  - Scaffolding still IN; don't strip until a count-drop never appears across real use.

---

## TL;DR

- **Symptom:** an on-screen chat transcript suddenly goes **blank** — the message
  list is wiped to empty (or partially shrinks), erasing rendered assistant
  answers. Not a render crash (no error boundary); it's a `setMessages` state wipe.
- **Status after a 6-version chase (1.1.2 → 1.1.8):**
  - ✅ **Compaction path** — solid. Verified 2026-06-03 with a 14-fact memory test
    across a forced compaction: 14/14 recalled, output stayed live.
  - ✅ **WS reconnect path** (sleep/wake, network blip) — **guarded** by
    `reconnectRunRef` (see below). Blocks the wipe.
  - ❌ **Fresh-mount / app-relaunch path** — **STILL SLIPS.** This is the open gap.
- **The fix is a timing-race tightrope** (that's why it took 6 versions). Do NOT
  rush it. Reproduce → fix → verify against `blank-trace.log` → only then strip.

**Important version note:** `ChatPage.tsx` was **not modified** in the 1.1.9→1.1.13
work (scoping/delegate/gates). The running build's chunk is `ChatPage-D9EGzdAO.js`
and is identical across 1.1.10–1.1.13. So the blank logic you're reading IS what
ships in 1.1.13.

---

## The evidence (real blanks caught today)

`~/.elevate/logs/blank-trace.log` after a day of app relaunches (my churn):

```
14:26:15 sid=d0a1d52f {"msg":"LIST WIPED to empty","prevCount":3, ...stack...}
14:32:43 sid=cc287ea6 {"msg":"LIST WIPED to empty","prevCount":2, ...stack...}
14:32:43 sid=         {"msg":"rendered assistant answer vanished from list",
                       "wasChars":3791,"nowChars":"REMOVED","listBefore":2,"listAfter":0}
14:33:56 sid=         {"msg":"rendered assistant answer vanished from list",
                       "wasChars":541,"listBefore":4,"listAfter":2}
14:33:56 sid=         {"msg":"rendered assistant answer vanished from list",
                       "wasChars":432,"listBefore":4,"listAfter":2}
```

- `"LIST WIPED to empty"` = the wrapped setter saw a populated→empty wipe and
  **let it through** (bug). `"blocked list wipe ..."` would mean the guard caught
  it (good). There are **0 blocked** events and **2 raw wipes** here.
- The 14:32–14:33 events fired during **app relaunches** (full page reloads =
  fresh mounts), NOT WS reconnects — which is exactly why the reconnect guard
  didn't cover them.

---

## Architecture (what's already there)

All in `cli/web/src/pages/ChatPage.tsx`:

### 1. The wrapped setter + reconnect guard — lines 2633–2665
```ts
const [messages, setMessagesRaw] = useState<ChatMessage[]>([]);
const setMessages = useCallback((updater) => {
  setMessagesRaw((prev) => {
    const next = typeof updater === "function" ? updater(prev) : updater;
    if (prev.length >= 2 && (next?.length ?? 0) === 0) {
      if (reconnectRunRef.current) {            // <-- ONLY guards WS reconnects
        blankTrace("blocked list wipe during reconnect window", {prevCount: prev.length});
        return prev;                            // block
      }
      blankTrace("LIST WIPED to empty", {prevCount: prev.length, stack: new Error().stack...});
    }
    return next;                                // allow (THIS is the slip)
  });
}, []);
```
Every `setMessages` call funnels through here. It only *blocks* when
`reconnectRunRef.current` is true. Outside that window it logs and allows.

### 2. The connect-effect else-branch — lines 3473–3495 (the actual wiper)
```ts
} else {  // no resumeId
  const _chatKey = resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
  setMessages((prev) => {
    if (prev.length &&
        (renderedChatKeyRef.current === _chatKey ||
         (mintedSessionIdRef.current != null && mintedSessionIdRef.current === resumeId))) {
      blankTrace("blocked same-chat list wipe (connect else)", {...});
      return prev;                              // block
    }
    renderedChatKeyRef.current = _chatKey;
    return [];                                  // <-- WIPE
  });
}
```

### 3. Trace plumbing (the scaffolding to remove at the end)
- `blankTrace(message, data)` — **`ChatPage.tsx:1460`**. Forwards to the gateway.
- `blankTraceIfDropped(...)` — **`ChatPage.tsx:1474`** — the "rendered assistant
  answer vanished from list" detector.
- Gateway sink — **`cli/tui_gateway/server.py:3012`**: `@method("debug.trace")`
  appends to `<ELEVATE_HOME>/logs/blank-trace.log` (lines 3014–3017).
- Sourcemaps — **`cli/web/vite.config.ts:72`** `sourcemap: true`.

---

## Ref lifecycles (read these before touching anything)

- **`reconnectRunRef`** (`useRef(false)`, line 2576): set `true` at **5037** and
  **5076**, cleared `false` at **5039** and **5078**. These bracket the WS
  reconnect / liveness-watchdog re-run. The window does NOT open on a fresh mount.
- **`renderedChatKeyRef`** (`useRef(null)`, line 2571): set at **3419, 3492,
  4101, 4156, 4179**; read as the guard at **3482, 4146, 4169**. **Resets to
  `null` on a fresh mount** (new ref) — this is why the else-branch guard
  (`renderedChatKeyRef.current === _chatKey`) misses on relaunch.
- **`historyHydratedRef`** (`useRef(false)`, line 2602): **reset to `false` at
  line 3381 at the START of every effect run**, set `true` at 3418/3435/3441.
  ⚠️ **Because of the 3381 reset, it is `false` inside the else-branch — so you
  CANNOT use `historyHydratedRef` as the "we have a real transcript" signal in
  the wipe path.** (Rules out the most obvious patch.)
- The connect effect starts ~**3373** (`useEffect`, `if (!autoResumeDecided) return;`),
  sets `persistedSessionIdRef.current = resumeId` (3382), then `if (resumeId) {`
  (~3408, restore+hydrate) … `else {` (3473, wipe).

---

## The gap, precisely

On a **fresh mount** (app relaunch / update-apply / page reload) with a chat that
gets restored from cache:

1. Effect run A: `resumeId = X` → IF branch restores cache (`setMessages(restoredCached)`,
   list → N≥2) and sets `renderedChatKeyRef.current = X` (line 3419).
2. Effect run B: `resumeId` transiently `null` (reattach/remount) → ELSE branch.
   `prev.length = N≥2`, but `_chatKey = (null ?? newChatId ?? seedKey ?? "__fresh_chat__")`.
   `renderedChatKeyRef.current === X !== _chatKey` → guard misses → **`return []` → BLANK.**
3. `reconnectRunRef.current` is `false` (it's a mount, not a WS reconnect), so the
   wrapped-setter guard (2646) doesn't catch it either.

It's a **race** — the cache-restore usually wins (which is why compaction reloads
looked clean), but sometimes run B wipes before/around the restore.

---

## Fix hypothesis (UNVERIFIED — verify before shipping)

The distinguishing signal between a **transient null resumeId** (don't blank) and
an **intentional new chat** (do clear) is likely the `_chatKey` fallthrough:

- Transient/uninitialized → `resumeId`, `newChatId`, `seedKey` all null →
  `_chatKey === "__fresh_chat__"`.
- Deliberate new chat → has a real `newChatId` (or `seedKey`) → `_chatKey !== "__fresh_chat__"`.

**Candidate patch (else-branch, ~3480):** also block the wipe when
`prev.length >= 2 && _chatKey === "__fresh_chat__" && renderedChatKeyRef.current != null
&& renderedChatKeyRef.current !== "__fresh_chat__"` — i.e. we previously rendered a
real chat and resumeId just fell to nothing. Keep `return prev` instead of `[]`.

**MUST verify before trusting it:**
- Confirm `newChatId` / `seedKey` are actually set on a deliberate "new chat"
  action (grep their definitions + the new-chat handler) so this doesn't strand
  stale messages when the user really starts fresh.
- Confirm there isn't a *second* wiper path (lines 4124–4179 also call
  `setMessages([...])` / set `renderedChatKeyRef`). The 14:33 partial drops
  (4→2) suggest a merge/dedup path may also drop rendered turns — check
  `mergeServerWithCache` / `mergeActiveTurnSnapshot` and the 4124/4142/4166 sites.
- Alternative/■safer approach: open the `reconnectRunRef` window for the first
  ~N seconds after mount (or until first successful hydrate), so the wrapped
  setter blocks ANY populated→empty wipe during the mount window. Empty→new-chat
  is unaffected (guard requires `prev.length >= 2`). Risk: a user starting a new
  chat within the window — measure how real that is.

---

## Reproduce

1. Be on 1.1.13 (or current). Open a **populated** chat (≥2 messages). Dartagnan's
   restored account has 1,447 chats — any real one works.
2. `tail -f ~/.elevate/logs/blank-trace.log`
3. Trigger a **fresh mount**: quit + relaunch the app
   (`osascript -e 'quit app "Elevate"'` then `open ~/Applications/Elevate.app`),
   with that chat as the active/restored one. Repeat a few times — it's a race.
4. A `"LIST WIPED to empty"` (not `"blocked ..."`) + `"rendered assistant answer
   vanished"` with `listAfter < listBefore` = the bug fired.

Also exercise the other two historical triggers for completeness:
- **WS reconnect:** with a chat open, `kill` the dashboard on :9120 (or toggle
  network) so the renderer's liveness-watchdog reconnects. Expect `"blocked ..."`.
- **Continuation mint:** continue a session (run a turn that mints a continuation).

---

## Verify a fix

After patching, repeat **Reproduce** step 3 many times. Pass =
**`blank-trace.log` shows only `"blocked ..."` (or nothing) — never `"LIST WIPED
to empty"` — and the transcript visibly survives every relaunch.** Re-run the WS
reconnect + a compaction turn too. The 3-trigger matrix must be all-green.

Sourcemap caveat: decoding the minified stack (`ChatPage-D9EGzdAO.js:13:xxxx`) via
the `.map` is **imprecise** — it pointed at line 3047 (an unrelated media-query
effect). Don't trust the exact decoded line; reason from the code paths above.

(Decode helper, if needed — Node has a built-in, no install:
`node -e 'const{SourceMap}=require("node:module");const m=new SourceMap(JSON.parse(require("fs").readFileSync(process.argv[1])));console.log(m.findEntry(13,4689))' cli/elevate_cli/web_dist/assets/ChatPage-D9EGzdAO.js.map`)

---

## Strip the scaffolding (ONLY after the 3-trigger matrix is green)

Keep the **guards** (they're the fix). Remove the **diagnostics**:
1. `ChatPage.tsx` — remove the `blankTrace(...)` log calls (keep the `return prev`
   blocks!), remove `blankTrace` (1460) + `blankTraceIfDropped` (1474) and their
   call sites.
2. `cli/tui_gateway/server.py:3012–3017` — remove the `@method("debug.trace")` sink.
3. `cli/web/vite.config.ts:72` — `sourcemap: true` → `false`.
4. Rebuild + ship as **1.1.14**.

---

## Build / deploy

- Web only (for hot-swap test): `npm --prefix cli/web run build` → output lands in
  `cli/elevate_cli/web_dist`. Hot-swap into the running app:
  `rsync -a --delete cli/elevate_cli/web_dist/ "~/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist/"`,
  then quit+relaunch the app. (ChatPage is the renderer — a web rebuild + relaunch
  is enough; no Python restart needed.)
- Full release (1.1.14): `cd desktop && APPLE_KEYCHAIN_PROFILE=elevate-notarization
  npm run release:mac` (builds dmg/zip, notarizes, ships to
  `api.elevationrealestatehq.com/updates`). Bump `desktop/package.json` version first.

---

## Key files index

| What | Where |
|---|---|
| All blank logic | `cli/web/src/pages/ChatPage.tsx` |
| Wrapped setter + reconnect guard | ChatPage.tsx **2633–2665** |
| Connect else-branch wiper | ChatPage.tsx **3473–3495** |
| Other setMessages/renderedChatKeyRef sites | ChatPage.tsx **4124–4179** |
| `blankTrace` / `blankTraceIfDropped` | ChatPage.tsx **1460 / 1474** |
| Ref decls | reconnectRunRef **2576**, renderedChatKeyRef **2571**, historyHydratedRef **2602** |
| reconnect window open/close | ChatPage.tsx **5037/5039, 5076/5078** |
| Gateway trace sink | `cli/tui_gateway/server.py` **3012–3017** |
| Sourcemap flag | `cli/web/vite.config.ts` **72** |
| Live evidence | `~/.elevate/logs/blank-trace.log` |
| Prior fixes (git) | `git log -i --grep=blank` (1.1.2→1.1.8) |
