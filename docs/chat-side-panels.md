# Chat side panels — selector + Preview / Plan / Background tasks / Files

> Goal (Dartagnan): bring back the panel-selector icon in the chat header, with a menu
> of side panels — **Preview · Files · Background tasks · Plan** (NOT Diff, NOT Terminal).
> Plan should auto-open when the agent writes a plan. Reference UI = Claude Code's panel
> dropdown (Preview/Diff/Terminal/Files/Background tasks/Plan); we build the Elevate
> equivalent, trimmed.

## The big simplification (corrected after code verification 2026-06-04)

**Background tasks** is the only truly no-backend panel. **Plan** and **Files** each need a
small backend endpoint. Here's why, verified against the code:

- **Background tasks** = pure frontend from the tool stream. ✅ Confirmed. The chat frontend
  builds `toolsByMessage` as `ToolEntry[]` (type in `cli/web/src/components/ToolCall.tsx:23`),
  and `ToolEntry` already carries an explicit `status: "running" | "done" | "error"`. So filter
  the stream for `name ∈ {delegate, mixture_of_agents, agent_handoff}` and read `.status`
  directly — no need to infer "result present yet." These are all real registered tools
  (`tools/delegate_tool.py`, `tools/mixture_of_agents_tool.py`, `tools/agent_handoff_tool.py`),
  so they DO appear in the stream.
  - ⚠️ **Drop `agent/background_review.py` from the filter.** It is NOT a model-callable tool
    (no registry entry; it's an auto post-session reflection agent with a memory/skills-only
    whitelist). It never emits a tool call into `toolsByMessage`, so the stream filter can't
    see it. Surfacing it would need the separate instrumentation in the "Later (optional)" note.
  - ⚠️ **Honest framing:** `delegate`/`mixture_of_agents` run **synchronously inside the
    assistant turn** (`delegate_tool.py:2190` blocks on `with ThreadPoolExecutor(...)`). They
    are not Claude-Code-style background jobs that outlive the turn — they show `running` only
    while that turn is mid-stream, then flip to `done`. This panel is really a "subagent
    activity log," which is fine — just don't promise live background monitoring.

- **Plan** = ❌ NOT available from the tool stream as-is — needs a small endpoint.
  The agent's `TodoStore` (`tools/todo_tool.py`) holds `{id, content, status}` items and the
  todo tool RETURNS `{"todos":[...], "summary":{total,pending,in_progress,completed,cancelled}}`
  as its result content. BUT the frontend `ToolEntry` does **not** model a `todos` array — it
  only keeps display strings (`summary?`, `preview?`, `context?`), and `summary` is built as
  `cut(result.content)` where `cut()` **truncates to 300 chars** (`ChatPage.tsx:863` and the
  build site at `:888`). Any real plan (5+ items) overflows 300 chars → the embedded JSON is
  silently chopped → not parseable. So you cannot reliably render a checklist from the stream.
  - Could you scan the *raw* messages instead? The raw `/api/sessions/{id}/messages` payload
    DOES carry full untruncated tool content (`db.get_messages`, `chat_sessions.py:558`, no
    truncation) — but the frontend discards it: `normalizeStoredTranscript` (`ChatPage.tsx:853`)
    projects raw → `ChatMessage[]` (the only thing kept in state, `:2661`) and the full content
    is gone after the `.then`. The live SSE path truncates too (every `ToolEntry` field goes
    through `cut()`). So a fresh, just-written plan is ONLY available truncated. Client-side
    scanning would need new raw-message retention AND still miss the live case.
  - ✅ **Fix (small, robust):** add `GET /api/sessions/{id}/todos` reusing the backwards-scan in
    `run_agent.py:4662 _hydrate_todo_store` against `db.get_messages` (already exposed by
    `/api/sessions/{id}/messages`, `web_server.py:4527`). Return `{todos, summary}`. Panel
    fetches on open + refetches when a new `todo` entry appears in the stream (stream = cheap
    *trigger*, endpoint = *source of truth*). ~20 lines.
    - ⚠️ Timing: the endpoint reflects *persisted* `chat_messages`. Confirm WHEN the gateway
      writes a turn's tool results to the DB — if at turn end, auto-open on a fresh plan fires
      at turn end (fine); if you want it to pop mid-turn the instant the tool runs, you'd need
      the gateway to also write/emit todo results live (bigger). v1: turn-end is acceptable.

- **Files** = uses the session-files endpoint. A workspace tree was tried, but
  real chats touch scattered absolute paths, so the useful view is "files this
  session worked on."

Net: build order is still Plan-first (headline), but Plan ships with a tiny endpoint, not zero.

## State model (ChatPage)

Replace the single `previewArtifact` driver with a `sidePanel` mode:

```ts
type SidePanelMode = "none" | "preview" | "plan" | "tasks" | "files";
const [sidePanel, setSidePanel] = useState<SidePanelMode>("none");
// previewArtifact still holds WHICH artifact when sidePanel === "preview".
```

The desktop `<aside>` is at `ChatPage.tsx:6183` (currently keyed off `previewArtifact`:
preview render when set, the `w-[16.25rem]` activity view when not). Render by mode:
- `preview` → `ArtifactPreviewPane` (unchanged; opening an artifact sets mode=preview).
- `plan` → `<PlanPanel sessionId={sessionId} tools={allSessionTools} />`
- `tasks` → `<BackgroundTasksPanel tools={allSessionTools} />`
- `files` → `<FilesPanel root={workspaceRoot} onOpenFile={openArtifactPreview} />`
- `none` → the existing activity/usage view.

The driver to fold in is `const [previewArtifact, setPreviewArtifact] = useState(...)`
(`ChatPage.tsx:2657`). Keep `previewArtifact` as the "WHICH artifact" holder, add `sidePanel`
as the mode; opening an artifact sets both.

⚠️ **Mobile/narrow:** there are TWO additional portal asides for `narrow` screens — the activity
portal (`mobilePanelOpen`, `:5800`) and the preview portal (`mobilePreviewPortal`, `:5835`).
The plan above is desktop-only. Either (a) explicitly scope v1 to desktop (`lg:`) and leave
narrow as-is, or (b) extend the narrow portals to take a mode too. Recommend (a) for v1.

Width: keep the 50/50 even-open behavior already shipped (shell-width based: `shellWidth * 0.5`
at `ChatPage.tsx:2980`). The aside is shown when `sidePanel !== "none"`.

## 1. Selector dropdown (header)

Add the selector to `.chat-top` (`ChatPage.tsx:5862`). ⚠️ Reality check on "bring back": there
was never a multi-panel dropdown. What existed was a single **no-op artifacts toggle** that got
gated to mobile-only (commit `b6d8557a5 fix(chat): hide the no-op artifacts-panel toggle on
desktop`). Today the only remnant is the `narrow`-gated "Toggle artifacts panel" button
(`PanelLeftOpen`, `setMobilePanelOpen`, ~`ChatPage.tsx:5908`). So this is a **build**, not a
restore: add a desktop-visible icon+chevron. `PanelRight` is NOT imported — either import it
from lucide or reuse the already-imported `PanelLeftOpen` (`:48`). `WebkitAppRegion:no-drag`
(the header is drag-region). On click, open a portal menu — **reuse `handleOpenChatMenu`**, the
existing header dropdown right next to it (the breadcrumb `ChevronDown` "Chat options" menu),
which already does the `getBoundingClientRect()` → portal popover pattern. Rows:

| Row | icon | shortcut | action |
|---|---|---|---|
| Preview | FileText | ⇧⌘P | `setSidePanel("preview")` (disabled if no current artifact) |
| Files | Folder | ⇧⌘F | `setSidePanel("files")` |
| Background tasks | (sub-agent glyph) | — | `setSidePanel("tasks")` |
| Plan | ListChecks | — | `setSidePanel("plan")` |

NO Diff, NO Terminal. Show a check/active dot next to the current mode. The button shows
always on desktop (this is the fix for "I want that little icon back").

Keyboard shortcuts optional (nice-to-have): wire ⇧⌘P / ⇧⌘F via a keydown listener.

## 2. Plan panel  (the headline — auto-opens)

**Data:** fetch `GET /api/sessions/{id}/todos` → `{todos: [{id, content, status}], summary}`.
The tool name in the stream is exactly `"todo"` (registry `todo_tool.py:270`; there is NO
`TodoWrite` alias in Elevate — drop that). Status enum is `pending | in_progress | completed |
cancelled` — **four** values (`VALID_STATUSES`, `todo_tool.py:22`), not three. Do NOT parse
`todos` out of `toolsByMessage` — that string is truncated to 300 chars (see "big
simplification"); use the endpoint as source of truth and the stream only as a refresh trigger.

**UI:** a checklist — each item with a status glyph (○ pending / ◐ in_progress / ✓ completed /
~~✗~~ cancelled, struck through), content text, and a top progress bar (completed/total). Empty
state: "No plan yet — Claude writes the plan here as it works." (mirror the reference).

**Auto-open:** a `useEffect` watching the tool stream — when a NEW `todo` tool entry appears
(detect via `toolsByMessage`, then refetch the endpoint) AND the user hasn't explicitly closed
the plan this session, `setSidePanel("plan")`. Reuse the existing dismissed-flag pattern
(`previewAutoOpenDisabledRef`, `ChatPage.tsx:2659`, persisted under the localStorage key
`elevate.chat.previewAutoOpenDisabled.v1` at `:383`) so it doesn't fight the user — or add a
sibling `planAutoOpenDisabled` flag if Plan and Preview should dismiss independently.

## 3. Background tasks panel

**Data:** from the tool stream, filter `name ∈ {delegate, mixture_of_agents, agent_handoff}`.
(Do NOT include `background_review` — not a tool, never in the stream; see "big
simplification".) For each: title (`summary`/`context` first arg), `status` (read
`ToolEntry.status` directly — `running`/`done`/`error`), timestamp (`startedAt`/`completedAt`),
and a short detail. Newest first. Note these are blocking-within-turn subagent calls, so
`running` only appears during the active assistant turn.

**UI:** list of cards — name + a status badge (Running spinner / Completed) + relative time +
optional one-line detail. Header "Background tasks", a "Finished" section + "Clear" affordance
(client-side hide). Mirror the reference layout.

**Later (optional):** if we want running-vs-done to be live + accurate beyond "result present
yet," instrument the spawn points (delegate_tool/mixture_of_agents/background_review) to emit
a lightweight task record; but v1 from the tool stream is enough.

## 4. Files panel

**Backend:** `GET /api/sessions/{id}/files` returns the files the session
actually touched. Keep `/api/files/preview` for reads. Do not bring back a
generic workspace tree unless a specific workflow needs it.

**UI:** a filterable grouped file list. Click a file → opens it in the
**Preview** panel (`setSidePanel("preview")` + load that artifact).

## Build order

1. **Selector + state model + Plan panel.** Headline. Ships with ONE small endpoint
   (`GET /api/sessions/{id}/todos`, reuses `_hydrate_todo_store`) + the selector dropdown +
   `sidePanel` state refactor + `PlanPanel` + auto-open. (Plan is NOT zero-backend — see "big
   simplification".)
2. **Background tasks panel** (pure tool-stream filter + `ToolEntry.status`; truly no backend).
   Actually the cheapest panel — consider doing it alongside step 1 to de-risk the selector.
3. **Files panel** (`/api/sessions/{id}/files` + click-to-preview).

## Integration points (line anchors verified 2026-06-04)
- `cli/web/src/pages/ChatPage.tsx`: `.chat-top` header `:5862` (selector; existing narrow
  toggle `:5908`, sibling dropdown `handleOpenChatMenu`); desktop `<aside>` `:6183`
  (render-by-mode); narrow portals `:5800` + `:5835`; `toolsByMessage` (live `useMemo` `:5580`,
  history-rebuild `:868`); `previewArtifact` state `:2657` + `openArtifactPreview` `:2966` (fold
  into `sidePanel`); `previewAutoOpenDisabledRef` `:2659` + key `:383` (reuse for Plan);
  50/50 width `:2980`.
- `cli/web/src/components/ToolCall.tsx:23` (`ToolEntry` type) — note: only display strings +
  `status`, NO structured `todos`. If you later want todos in the stream, extend here + both
  build paths.
- `cli/tools/todo_tool.py` — `TodoStore` + 4-status enum (`:22`), return shape
  `{todos, summary}`, tool name `"todo"` (`:270`). Read reference, no change.
- `cli/run_agent.py:4662 _hydrate_todo_store` — backwards-scan for the last todo; **reuse this
  for the new `/api/sessions/{id}/todos` endpoint.**
- `cli/tools/{delegate_tool,mixture_of_agents_tool,agent_handoff_tool}.py` — tool names to
  filter for Background tasks. `agent/background_review.py` is NOT a tool (exclude).
- `cli/elevate_cli/web_server.py` (`/api/files/preview`,
  `/api/sessions/{id}/files`, `/api/sessions/{id}/todos`) — file preview,
  session-file inventory, and plan state.

## Out of scope (per Dartagnan)
- **Diff** and **Terminal** — not wanted, not built.

## Status — BUILT 2026-06-04 (local, not deployed)

All three panels + selector shipped in the working tree. `tsc -b` clean, `vite build` clean,
eslint clean (warnings only, matching existing patterns).

**Backend** (`cli/elevate_cli/web_server.py`):
- `GET /api/sessions/{id}/todos` — backwards-scan mirror of `_hydrate_todo_store`, returns
  `{todos, summary}` untruncated. Verified against the live DB (found a real session's 4-item
  list, correct `{id,content,status}` shape + counts).
- `GET /api/files/tree?root=&depth=` was built as a lazy browse endpoint but
  later proved unnecessary for the chat Files panel.

**Frontend** (`cli/web/src/components/ChatSidePanels.tsx` — new; `pages/ChatPage.tsx` wired):
- `SidePanelSelector` (header `PanelRight`+chevron dropdown, Preview/Files/Background tasks/Plan,
  active check, Preview disabled w/o artifact). In `.chat-top` toggle-rail, all sizes.
- `PlanPanel` — checklist w/ 4 status glyphs + progress bar; fetches the endpoint; auto-opens on
  new `todo` tool entry unless dismissed (reuses the dismissed-flag pattern). Stream = trigger,
  endpoint = source of truth.
- `BackgroundTasksPanel` — pure tool-stream filter on `{delegate, mixture_of_agents,
  agent_handoff}` + `ToolEntry.status`, Running/Finished sections. No backend.
- `FilesPanel` — lists the files the agent actually worked on this session,
  deduped + grouped by directory, filter box, click-file→Preview. Elevate chats
  have no single workspace dir (`/api/status` working_directory is null; agents
  touch scattered absolute paths), so a tree rooted at one dir was wrong — it
  fell back to Elevate's install dir.
- **Preview always opens** — selecting Preview with no current artifact shows an `EmptyPreviewPanel`
  ("No preview") instead of being a disabled/dead menu row (per Dartagnan: panels should pop up
  on click even when empty).
- `sidePanel` mode added alongside `previewArtifact` (folded in, not ripped out); shared 50/50
  resize; Escape + mobile portal generalized to all modes. Desktop aside renders by mode.

**Verification gap:** no in-app screenshot — the desktop injects the dashboard session token via
the Electron shell, so a bare dev server can't reach the authed ChatPage. UI consistency is by
construction (every panel mirrors `ArtifactPreviewPane`'s shell + chat tokens). A live visual
needs a dashboard deploy (build web_dist + copy `.py` into the app Resources + relaunch).

**Not deployed.** To ship: `cd cli/web && npm run build` (done) → quit Elevate.app → `pkill -f
"elevate_cli.main dashboard"` → copy `web_dist` + changed `.py` into the app Resources →
relaunch. Desktop bump (`release:mac`) pushes to all accounts.
