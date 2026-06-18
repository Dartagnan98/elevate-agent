# Implementation Plan - Stackable chat work rail + real shortcuts

Date: 2026-06-18
Repo: `/Users/dartagnanpatricio/elevate`
Status: implemented locally; web build and focused ChatPage test passed

## The fix in one line

Keep the existing side-panel system. Make Plan and Background tasks stack inside
the current right rail, let Preview keep its takeover behavior, wire real app
shortcuts, and delete the unused file-tree browse path before adding anything
new.

## Ponytail audit first

Ranked cuts/simplifications:

1. `delete:` cut the unused `/api/files/tree` backend/client path if no hidden
   caller exists. Replacement: current `GET /api/sessions/{id}/files` Files
   panel, which already lists files actually touched by the session.
   [`cli/elevate_cli/web_server.py:2893`, `cli/elevate_cli/web_server.py:2956`,
   `cli/web/src/lib/api.ts:414`, `cli/web/src/lib/api-types.ts:2491`]
2. `yagni:` do not create a new rail framework/router/provider. Replacement:
   keep `sidePanel`, add one stacked render branch for Plan + Background tasks.
   [`cli/web/src/pages/ChatPage.tsx:3147`,
   `cli/web/src/pages/ChatPage.tsx:8547`]
3. `shrink:` do not add backend persistence for rail open/closed state.
   Replacement: existing session DB for plan/todos, existing localStorage for
   UI preferences. [`cli/elevate_cli/web_server.py:4924`,
   `cli/elevate_cli/web_server.py:4990`,
   `cli/web/src/pages/ChatPage.tsx:497`]
4. `native:` do not build custom app zoom/minimize plumbing in React.
   Replacement: Electron menu roles for zoom in/out/reset and minimize, plus
   renderer shortcuts only for chat rail panels.
   [`desktop/src/main.js:953`, `desktop/src/main.js:972`]
5. `shrink:` do not save every plan as a `.md` file. Replacement: keep the plan
   in session history and add optional export later for serious handoff jobs.
   [`cli/tools/present_plan_tool.py:1`,
   `cli/elevate_cli/web_server.py:4990`]
6. `yagni:` do not add a shortcut dependency. Replacement: one small keydown
   listener and one shortcut table in `ChatPage.tsx`.
7. `shrink:` do not add Diff, Terminal, or a workspace file browser back into
   the rail. Replacement: Preview, Artifacts, Files, Background tasks, Plan.
   [`docs/chat-side-panels.md:3`, `docs/chat-side-panels.md:194`]

net: about -70 lines possible from file-tree browse cleanup, 0 deps possible.

## Observed current state

- The selector and individual panels already exist in
  `cli/web/src/components/ChatSidePanels.tsx`.
- `ChatPage.tsx` still has one active `sidePanel`, so Plan and Background tasks
  replace each other instead of stacking.
- Plan data is already durable at the session level:
  - `present_plan` returns Markdown as JSON tool output.
  - `/api/sessions/{id}/plan` reads the latest stored plan from the session.
  - `/api/sessions/{id}/todos` reads the latest todo/checklist state.
  - compression preserves plan/todo snapshots back into model context.
- Background tasks are already built from subagent/tool lifecycle data.
- Preview is already the wide/resizable mode.
- The selector displays shortcut hints for Preview/Files, but those hints are
  not backed by a central chat shortcut handler.
- Electron has navigation/window menu items, but no explicit zoom-in/zoom-out
  menu roles yet.

## Product rule

The rail has two classes of surface:

1. Preview-class surfaces: Preview owns the right side because files need space.
2. Work-class surfaces: Plan and Background tasks are status/control surfaces
   and should stack.

Do not make everything stackable. Files and Artifacts can stay selector panels.
The request is specifically about plan + background work staying visible while a
job runs.

## Phase 0 - Cleanup gate

### 0.1 Confirm `/api/files/tree` is unused

Run:

```bash
rg -n "getFilesTree|FilesTree|files/tree|FileTree" cli/web/src cli/elevate_cli docs
```

Current evidence shows only:

- backend endpoint
- typed API helper/types
- old docs
- unrelated Skills page local file-tree component

### 0.2 Delete if still unused

Remove:

- `_FILES_TREE_EXCLUDED`
- `_FILES_TREE_MAX_ENTRIES`
- `_resolve_tree_root`
- `_walk_files_tree`
- `GET /api/files/tree`
- `getFilesTree`
- `FileTreeNode`
- `FilesTreeResponse`
- stale doc wording that says the endpoint remains as latent browse capability

Keep:

- `/api/files/preview`
- `/api/sessions/{id}/files`
- current `FilesPanel`

Acceptance:

- `rg -n "files/tree|getFilesTree|FilesTreeResponse|FileTreeNode"` returns no
  product-code hits.
- Files panel still opens files via Preview.

Risk:

- If a hidden app route calls `/api/files/tree`, this deletion waits. Do not
  keep it just because it might be useful someday.

## Phase 1 - Stack Plan + Background tasks, no new framework

### 1.1 Keep `sidePanel`, add one stacked branch

Do not replace the entire panel model.

Minimal shape:

```ts
const isWorkPanel = sidePanel === "plan" || sidePanel === "tasks";
const shouldStackWork =
  isWorkPanel &&
  (runningBackgroundTasks > 0 || sidePanel === "tasks" || planReadyForApproval);
```

Then `renderSidePanel()` gets a work branch:

```tsx
case "plan":
case "tasks":
  return shouldStackWork ? (
    <StackedWorkPanels primary={sidePanel} ... />
  ) : (
    sidePanel === "plan" ? <PlanPanel ... /> : <BackgroundTasksPanel ... />
  );
```

This is intentionally less flexible than a generic panel framework.

### 1.2 Add `StackedWorkPanels` in `ChatSidePanels.tsx`

Do not create a new file.

Props:

```ts
type WorkPanelMode = "plan" | "tasks";

function StackedWorkPanels({
  primary,
  plan,
  tasks,
}: {
  primary: WorkPanelMode;
  plan: ReactNode;
  tasks: ReactNode;
})
```

Behavior:

- Desktop only uses a vertical stack.
- Primary panel gets roughly 56 percent of height.
- Secondary panel gets the rest.
- Each child keeps its existing `PanelShell`.
- No nested cards around panels.
- No separate close system in v1.

CSS can be Tailwind classes:

```tsx
<div className="flex h-full min-h-0 flex-col gap-2">
  <div className="min-h-[14rem] flex-[1.25] overflow-hidden">{primaryNode}</div>
  <div className="min-h-[11rem] flex-1 overflow-hidden">{secondaryNode}</div>
</div>
```

If this gets ugly, stop and use a simpler split:

```tsx
<div className="grid h-full min-h-0 grid-rows-2 gap-2">
```

### 1.3 Adjust auto-open rules

Current rules:

- Plan auto-opens only when `sidePanel === "none"`.
- Background tasks auto-open only when `sidePanel === "none"`.

Change:

- If Plan is open and a task starts, stay on `sidePanel === "plan"` and let the
  stacked branch show tasks below.
- If Tasks is open and a plan arrives, stay on `sidePanel === "tasks"` and let
  the stacked branch show plan below.
- If Preview is open, do not steal it.
- If Files/Artifacts are open, do not steal them in v1; show selector pulse only.
- If nothing is open, preserve current auto-open behavior.

Acceptance:

- Open Plan, start subagent: tasks appear below Plan.
- Open Background tasks, produce plan/todos: Plan appears in the same rail.
- Open Preview, start task: Preview remains open.
- Close rail: it closes both stacked work panels.

### 1.4 Do not solve perfect proportions yet

No drag handle between Plan and Tasks in v1.

Add it only when someone actually complains that the split is wrong after use.
The existing outer rail resize already covers most of the need.

## Phase 2 - Real shortcuts, smallest useful set

### 2.1 Electron native shortcuts

Use menu roles first.

In `desktop/src/main.js`, add explicit View items:

```js
{ role: "resetZoom", accelerator: "CmdOrCtrl+0" },
{ role: "zoomIn", accelerator: "CmdOrCtrl+Plus" },
{ role: "zoomIn", accelerator: "CmdOrCtrl+=" },
{ role: "zoomOut", accelerator: "CmdOrCtrl+-" },
```

Keep Window:

```js
{ role: "minimize", accelerator: "CmdOrCtrl+M" },
{ role: "zoom" },
```

No preload or IPC needed.

Acceptance:

- `Cmd+=` zooms in.
- `Cmd+-` zooms out.
- `Cmd+0` resets.
- `Cmd+M` minimizes.

### 2.2 Chat rail shortcuts

Add one renderer listener in `ChatPage.tsx`, near the existing Escape handler.

Shortcut table:

```ts
const CHAT_SHORTCUTS = [
  { key: "\\", mod: true, action: "toggle-work-rail" },
  { key: "p", mod: true, shift: true, action: "preview" },
  { key: "b", mod: true, shift: true, action: "tasks" },
  { key: "o", mod: true, shift: true, action: "plan" },
];
```

Behavior:

- `Cmd/Ctrl+\`: toggle work rail.
  - If no rail: open Plan if a plan exists or plan mode is active, else Tasks if
    tasks exist, else Plan empty state.
  - If Plan/Tasks stacked: close rail.
  - If Preview: close Preview back to work rail only if work exists; otherwise close.
- `Shift+Cmd/Ctrl+P`: open Preview.
- `Shift+Cmd/Ctrl+B`: open Background tasks.
- `Shift+Cmd/Ctrl+O`: open Plan.
- `Esc`: keep current close behavior.

Do not intercept plain typing. Only handle modifier shortcuts.

### 2.3 Make selector hints true

Update `SELECTOR_ROWS` hints to match actual bindings:

- Preview: `Shift+Cmd+P`
- Background tasks: `Shift+Cmd+B`
- Plan: `Shift+Cmd+O`
- Files: no shortcut in v1 unless requested

Files has no shortcut because we already have enough keys. Add it later if it
gets daily use.

Acceptance:

- Every visible shortcut hint triggers the matching panel.
- No shortcut fires while only typing plain text into the composer.
- `Enter` submit behavior remains unchanged.

## Phase 3 - Preview takeover without losing work state

Do not add new state yet. Use current `previewArtifact` and `sidePanel`.

Behavior:

- Opening Preview sets `sidePanel = "preview"` as today.
- Keep Plan/Tasks data alive because they are fetched from session endpoints and
  background task state already lives in ChatPage.
- When Preview closes:
  - If background tasks are running, return to `tasks`.
  - Else if `planReadyForApproval` or plan mode is active, return to `plan`.
  - Else close to none.

This gives the user a path back to work context without adding a hidden
previous-panel stack.

If the auto-return feels jumpy, make the fallback always close to none. Do not
add a history stack in v1.

## Phase 4 - Optional plan file export, not default

Do not save every plan as a `.md` file.

Add only one explicit action later:

- "Export plan" in Plan panel
- writes a Markdown artifact through an existing file/artifact path
- filename:
  `plan-<session-id-or-date>.md`
- include plan markdown, todo checklist, and session id

Default persistence remains session DB/history.

Acceptance for later:

- Exported file appears in Files/Artifacts.
- No file is created for tiny tasks unless user clicks Export or a future
  "serious job" toggle exists.

## Phase 5 - Verification

Frontend static checks:

```bash
npm --prefix cli/web test -- slashExec ChatPage.activityDigest
npm --prefix cli/web run build
```

Desktop static checks:

```bash
npm --prefix desktop run preflight:apple
```

Targeted manual/browser checks:

1. Open ChatPage in the desktop app or authenticated dashboard.
2. Put session in plan mode and trigger a plan.
3. Trigger a subagent/background task while Plan is visible.
4. Verify Plan and Background tasks are visible together.
5. Open a generated artifact/file.
6. Verify Preview takes over.
7. Close Preview.
8. Verify work rail returns to useful context or closes predictably.
9. Press every visible shortcut and verify it does exactly what the label says.
10. Verify `Cmd+=`, `Cmd+-`, `Cmd+0`, and `Cmd+M` work in the installed app.

Do not call this shipped from a dev server alone. Electron shortcuts need the
desktop shell.

## Files to touch

Likely:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/web/src/components/ChatSidePanels.tsx`
- `desktop/src/main.js`
- `docs/chat-side-panels.md`

Only if Phase 0 deletion is safe:

- `cli/elevate_cli/web_server.py`
- `cli/web/src/lib/api.ts`
- `cli/web/src/lib/api-types.ts`

## Files not to touch

- `cli/tools/present_plan_tool.py`
- `cli/tools/todo_tool.py`
- `cli/run_agent.py`
- session DB schema
- compaction code
- new dependencies

## Done means

- Plan and Background tasks stack.
- Preview still owns the rail when open.
- Existing Plan/Tasks/Files panels are reused.
- No new backend endpoint is added.
- Unused file-tree browse code is deleted or explicitly kept with a proven
  caller.
- Visible shortcut hints are real.
- Native zoom/minimize shortcuts work in the Electron app.
