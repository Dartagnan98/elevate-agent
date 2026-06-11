# Chat transcript refactor — kill the vanish-bug class

**Problem.** ChatPage.tsx (9,816 lines) keeps the transcript as one React
`messages` array with 15 writers, reconciled across 4 sources of truth (live
stream events, React state, localStorage cache, gateway history) with **no
stable message identity** — server hydrates mint random ids
(`history-{i}-{uuid}`), so merges match by content fingerprint. 12 stacked
"vanish guards" each patch one race; new features (subagent views, compaction
rotation, mint-mid-stream) keep minting new races. Evidence:
`~/.elevate/logs/blank-trace.log` on customer boxes — "rendered assistant
answer vanished from list", "list cleared for new chat" firing on populated
chats, a 945-char reply fingerprint-replaced by a 417-char stale partial.

**Invariant we're buying:** a rendered message can never be removed or
shrunk except by explicit user action. Achieved by stable ids + set-union
merges — "replace the list" stops existing as an operation.

---

## Phase 0 — Stopgap (1.2.10, ships immediately)

Tactical patches for tonight's trace while the refactor cooks:

1. **Artifact noise filter** (done in tree): `isInternalArtifactPath()` —
   temp dirs (`/var/folders`, `/tmp`), `.elevate` state dirs,
   `elevate-cwd-*`/`elevate-snap-*` shims — applied to `extractPathsFromText`
   and subagent `files_written`. Internal plumbing never cards as artifacts.
2. **Wipe-guard hardening**: the populated→empty block currently requires
   `prev.length >= 2`; tonight's trace shows a 1-message list wiped
   (`listBefore: 1, listAfter: 0`). Block at `>= 1`.
3. **No-shrink merge**: wherever fingerprint matching reconciles a rendered
   assistant message (mergeServerWithCache + the id-remap site), the longer
   content wins. Kills the 945→417 stale-partial replacement.

## Phase 1 — Stable message identity end-to-end (backend)

1. **Mint at the gateway.** At `message.start` the gateway mints
   `message_id = "{persisted_sid}.{turn_seq}"` (monotonic per session) and
   carries it on every `message.delta` / `message.complete` payload.
2. **Persist it.** Migration `0031_chat_message_ids.sql`: add
   `client_message_id TEXT` to `chat_messages`; write it on append. Legacy
   rows hydrate as `legacy-{BIGSERIAL id}` — still stable across fetches.
3. **Expose it.** `_history_to_messages`, `session.resume` payload, and the
   REST transcript endpoint all include `id` per message.
4. **User turns.** Client mints a uuid, sends it with `chat.send`; gateway
   echoes it in the ack and persists it — the optimistic user bubble and the
   persisted row are the same identity, no reconciliation guess.

Tests: ids present + stable across two resumes; delta/complete events carry
the same id; legacy sessions hydrate with deterministic ids.

## Phase 2 — Transcript store outside the component (frontend)

New `web/src/lib/transcript-store.ts`:

- `Map<chatKey, OrderedMap<messageId, ChatMessage>>`, bound to React via
  `useSyncExternalStore`.
- Ops: `upsert(chatKey, msg)` (streaming content may only GROW for an id;
  shrink attempts are dropped + telemetry-logged), `unionHydrate(chatKey,
  msgs)` (set-union by id, idempotent), `clear(chatKey)` (ONLY from the
  explicit New Chat action), `snapshot(chatKey)` (localStorage write-through —
  cache becomes a cold-start preview, not a merge source).
- **chatKey = lineage root id.** Compaction rotates the live session id
  mid-chat; the store keys on the lineage root (already tracked for the usage
  footer) so rotation never re-keys the transcript.

## Phase 3 — Rewire ChatPage

1. Replace `useState<ChatMessage[]>` with the store binding. All 15 write
   sites become store ops: stream events upsert by `message_id`; hydrate →
   `unionHydrate`; user send → upsert with client id.
2. **Split the mega connect-effect** into three narrow effects:
   (a) session lifecycle (create/resume/close), (b) event subscription →
   store upserts, (c) one-shot hydration per chatKey. Finishing a turn can no
   longer re-trigger hydration; URL mint (?new= → ?resume=) only swaps
   chatKey.
3. **Delete:** the 12 vanish guards, `mergeServerWithCache`, the fingerprint
   merge, the id-remap, and collapse the 7 identity refs to two
   (chatKey + live gateway sid). `blankTrace` survives as telemetry on store
   invariant violations only.

## Phase 4 — Verification (before any customer sees it)

- **Unit:** store invariants — no shrink, union idempotent, clear only
  explicit, lineage re-key stability.
- **Race sims (jsdom):** hydrate-during-stream; remount mid-turn; mint
  mid-stream; compaction rotation mid-chat; gateway reconnect; subagent
  drill-in/out.
- **Playwright e2e on the built app:** send → stream → navigate away
  mid-stream → return (reply intact, no flash); new-chat switch + back; kill
  gateway mid-turn (interrupted marker, no wipe).
- **CI guard:** zero direct `setMessagesRaw` writers outside the store
  binding (grep test, same pattern as test_tool_exposure / test_write_schema).
- **Burn-in:** ≥1 day on Dartagnan's box; then verify on Justin's —
  blank-trace.log must stay silent through a full test script. Then ship as
  1.2.11.

## Known sharp edges

- **Compaction rotation** is the hardest case — lineage mapping must be
  bulletproof or the store re-keys mid-chat (test first, build second).
- **Subagent snapshot views** are read-only sessions — they get their own
  chatKey and never subscribe to live events.
- Queued sends, plan-mode (`present_plan`), and voice flow are untouched but
  in the blast radius — covered by the e2e list.
- Desktop ships the web bundle — phases 1–3 land as ONE release (1.2.11);
  protocol additions are additive so an old web bundle on a new gateway (or
  vice versa during staged rollout) degrades to current behavior.

## Sequencing

- Phase 0: tonight, ships as 1.2.10 with the cron/artifact fixes.
- Phases 1–4: one focused session, full test pass, burn-in, ship 1.2.11.
