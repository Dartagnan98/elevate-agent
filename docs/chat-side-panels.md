# Chat side panels — selector + Preview / Plan / Background tasks / Files

> Goal (Dartagnan): bring back the panel-selector icon in the chat header, with a menu
> of side panels — **Preview · Files · Background tasks · Plan** (NOT Diff, NOT Terminal).
> Plan should auto-open when the agent writes a plan. Reference UI = Claude Code's panel
> dropdown (Preview/Diff/Terminal/Files/Background tasks/Plan); we build the Elevate
> equivalent, trimmed.

## The big simplification

Plan and Background tasks need **no new backend**. The chat frontend already receives the
full tool-call stream per assistant message (`toolsByMessage` in ChatPage). Both panels are
derived from it:

- **Plan** = the latest `todo` tool result in the session. The agent's `TodoStore`
  (`tools/todo_tool.py`, `{id, content, status}` items) is in-memory per session and is even
  rehydrated from history (`run_agent.py:4662 _hydrate_todo_store` reads the last `todo` tool
  response). So the panel just finds the most recent `todo` tool call/result in
  `toolsByMessage` and renders its `todos[]`.
- **Background tasks** = tool calls that spawn background work: `delegate` (subagents,
  `tools/delegate_tool.py`), `mixture_of_agents` (`tools/mixture_of_agents_tool.py`),
  `agent_handoff` (`tools/agent_handoff_tool.py`), and background reviews
  (`agent/background_review.py`). Filter the tool stream for these names; status = running
  (no result yet) vs completed (result present).

Only **Files** needs a backend endpoint (a workspace tree).

## State model (ChatPage)

Replace the single `previewArtifact` driver with a `sidePanel` mode:

```ts
type SidePanelMode = "none" | "preview" | "plan" | "tasks" | "files";
const [sidePanel, setSidePanel] = useState<SidePanelMode>("none");
// previewArtifact still holds WHICH artifact when sidePanel === "preview".
```

The right `<aside>` (the existing one in ChatPage, ~line 6186) renders by mode:
- `preview` → `ArtifactPreviewPane` (unchanged; opening an artifact sets mode=preview).
- `plan` → `<PlanPanel tools={allSessionTools} />`
- `tasks` → `<BackgroundTasksPanel tools={allSessionTools} />`
- `files` → `<FilesPanel root={workspaceRoot} />`
- `none` → the existing activity/usage view.

Width: keep the 50/50 even-open behavior already shipped (shell-width based). The aside is
shown when `sidePanel !== "none"`.

## 1. Selector dropdown (header)

Bring back the icon in `.chat-top` (the one removed/gated earlier). A split-panel icon +
chevron (`PanelRight` + `ChevronDown`), `WebkitAppRegion:no-drag`. On click, a small portal
menu (reuse the `Modal`/portal pattern or a lightweight popover) with rows:

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

**Data:** scan `toolsByMessage` (all assistant messages, newest first) for the most recent
tool with `name === "todo"` (or `TodoWrite`). Its result/args carry `todos: [{id, content,
status}]` (status ∈ `pending|in_progress|completed`). Parse and render.

**UI:** a checklist — each item with a status glyph (○ pending / ◐ in_progress / ✓ completed),
content text, and a top progress bar (completed/total). Empty state: "No plan yet — Claude
writes the plan here as it works." (mirror the reference).

**Auto-open:** a `useEffect` watching the tool stream — when a NEW `todo` tool result appears
(todos length grows or content changes) AND the user hasn't explicitly closed the plan this
session, `setSidePanel("plan")`. Respect a dismissed flag like the existing
`previewAutoOpenDisabled` pattern so it doesn't fight the user.

## 3. Background tasks panel

**Data:** from the tool stream, filter `name ∈ {delegate, mixture_of_agents, agent_handoff}`
(+ any background-review markers). For each: title (tool summary/first arg), status (running
if no result yet else completed), timestamp, and a short detail. Newest first. (cortextOS
note: these are the Elevate equivalents of "Background tasks" — real subagent/async spawns.)

**UI:** list of cards — name + a status badge (Running spinner / Completed) + relative time +
optional one-line detail. Header "Background tasks", a "Finished" section + "Clear" affordance
(client-side hide). Mirror the reference layout.

**Later (optional):** if we want running-vs-done to be live + accurate beyond "result present
yet," instrument the spawn points (delegate_tool/mixture_of_agents/background_review) to emit
a lightweight task record; but v1 from the tool stream is enough.

## 4. Files panel

**Backend (new):** `GET /api/files/tree?root=<dir>&depth=N` → a nested `{name, path, type:
dir|file, children?}` tree for the chat's workspace root (default the session's working dir;
clamp to it — no escaping). Follow the existing `/api/skills/{name}/tree` pattern
(web_server.py:9768) + `/api/files/preview` (2758) for reads. Guard against huge dirs (cap
entries, lazy-load children on expand).

**UI:** a filterable tree (the reference's "Filter files… (?text to search contents)"). Plain
filter = name match; `?term` = content search (optional v2, calls a grep endpoint). Click a
file → opens it in the **Preview** panel (`setSidePanel("preview")` + load that artifact).

## Build order

1. **Selector + state model + Plan panel** (data ready in the tool stream; auto-open). This is
   the headline and ships without backend.
2. **Background tasks panel** (tool-stream filter; same plumbing as Plan).
3. **Files panel** (`/api/files/tree` endpoint + tree UI + click-to-preview).

## Integration points
- `cli/web/src/pages/ChatPage.tsx`: `.chat-top` header (selector), the right `<aside>` (~6186,
  render-by-mode), `toolsByMessage`/`tracesByMessage` (the tool stream), `previewArtifact`
  + `openArtifactPreview` (fold into `sidePanel`), `previewAutoOpenDisabled` (reuse for Plan).
- `cli/tools/todo_tool.py` (`TodoStore`, item shape) — read shape reference, no change.
- `cli/tools/{delegate_tool,mixture_of_agents_tool,agent_handoff_tool}.py` — tool names to
  filter for Background tasks.
- `cli/elevate_cli/web_server.py:9768` (`/api/skills/{name}/tree`) + `:2758`
  (`/api/files/preview`) — patterns for the new `/api/files/tree`.

## Out of scope (per Dartagnan)
- **Diff** and **Terminal** — not wanted, not built.
