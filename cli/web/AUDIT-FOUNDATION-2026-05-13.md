# Foundation Audit — Elevate Desktop Dashboards

**Date:** 2026-05-13
**Scope:** CSS tokens, theme system, UI primitives, non-UI components, hooks, contexts, Electron shell, IPC surface
**Target aesthetic:** Claude Code dashboard — warm-tinted dark `#1a1b1a` / `#212321` / `#2a2c2a`, Geist Sans + JetBrains Mono, terracotta accent `#D97757`, ops-tool precision, no gradients/glassmorphism

**Companion docs:** AUDIT-DESKTOP-DASHBOARDS-2026-05-13.md (executive), AUDIT-FULL-2026-05-13.md (per-page), AUDIT-ADMIN-2026-05-13.md (admin deep dive)

---

## TL;DR — The Headline

> **The foundation contradicts the target aesthetic at three load-bearing points. No amount of per-page polish fixes this until the foundation is corrected.**

1. **Dark theme ships a NAVY background `#101827`** — described as "warm-tinted dark" in metadata but it's a cool blue-grey. Memory and audit target says `#1a1b1a` (warm dark).
2. **Typography preset still ships APTOS first** — `index.css` says Geist Sans, `presets.ts` says Aptos. ThemeProvider's preset wins on mount.
3. **`@theme inline` defaults still bake old orange `#CE823E`** — terracotta `#D97757` only arrives via runtime ThemeProvider override, causing flash-of-wrong-color (FOWC) on every page load and shipping the old orange into the build.

These three primitives cascade through every page. Combined with translucent-by-default UI primitives (cards/buttons/inputs all bg-card/55-80, rounded-md/lg/xl, palette-tinted badges, custom drop shadows), the entire dashboard renders as a slightly-off iteration of the target instead of nailing it.

---

## Audit Health Score (Foundation Layer)

| # | Dimension | Score | Key Finding |
|---|-----------|-------|-------------|
| 1 | Token Coherence | 1/4 | Dark theme = navy not warm dark; primary baked as old orange in `@theme inline` |
| 2 | Typography | 1/4 | Preset ships Aptos despite Geist being the stated target |
| 3 | UI Primitive Slop | 1/4 | Every shadcn primitive carries rounded-md/lg/xl + translucent palette tints |
| 4 | Foundation A11y | 3/4 | Focus styles defined, contrast acceptable, missing keyboard-trap audits on dialogs |
| 5 | Anti-Patterns | 1/4 | Translucent surfaces, palette/12-30 tints, custom shadow-[...] glows, glassmorphism on global header |
| **Total** | | **7/20** | **Poor** — major overhaul before per-page work pays off |

**Rating:** Poor. Foundation rework is a prerequisite for per-page redesign — otherwise every page fix is fighting the base layer.

---

## 1. CSS Token System — `src/index.css` (563 LOC)

### P0 — Dark default background is navy not warm dark

**File:** `src/index.css:58–60`

```css
--background: color-mix(in srgb, #101827 100%, transparent);
--background-base: #101827;
--background-alpha: 1;
```

**Then echoed in preset:** `src/themes/presets.ts:43`

```ts
background: { hex: "#101827", alpha: 1 },
```

**Impact:** Every page renders against `#101827` — cool navy with blue undertone. The Claude Code aesthetic memory specifies warm-tinted dark `#1a1b1a` / `#212321` / `#2a2c2a`. Every "card surface" derives from this via `color-mix(... var(--midground-base) N%, var(--background-base))` — so cards are blue-tinted too, not warm.

**Fix:** Change both `:root --background-base` and `darkTheme.palette.background.hex` to `#1a1b1a`. Then introduce surface tiers: surface = `#212321`, surface-strong = `#2a2c2a`, border-strong = `#353735`, matching the warm tint baked into `install.html` already (`--bg: #1a1b1a; --surface: #212321; --border: #2a2c2a; --border-strong: #353735`).

**Severity:** P0 — foundation-level color is wrong. Affects every page.

---

### P0 — Old orange `#CE823E` baked into `@theme inline`

**File:** `src/index.css:257, 271`

```css
@theme inline {
  ...
  --color-primary: #CE823E;
  ...
  --color-ring: #CE823E;
}
```

**File:** `src/index.css:106`

```css
--chat-accent: var(--color-primary, #CE823E);
```

**File:** `src/index.css:114`

```css
--sidebar-row-active: color-mix(in srgb, var(--color-primary, #7fb2ff) 15%, var(--midground-base) 7%);
```

**Impact:**
- Tailwind v4 `@theme inline` bakes `#CE823E` into generated `text-primary`/`bg-primary`/`border-primary` utility classes
- ThemeProvider's `applyTheme` overrides `--color-primary` via inline style on `:root` (presets.ts:56 `primary: "#D97757"`), so visible UI lands at terracotta after hydration
- BUT: pre-hydration first paint shows old orange — flash-of-wrong-color on every cold load
- Two fallback chains (`var(--color-primary, #CE823E)` and `var(--color-primary, #7fb2ff)`) — second one falls back to BLUE not orange, indicating drift
- Per memory: "Accent: Claude terracotta orange `#D97757`. Swapped from warm off-white 2026-04-17."

**Fix:** Replace all three `#CE823E` literals with `#D97757`. Replace `#7fb2ff` fallback with `#D97757`. Update `@theme inline` defaults to match the preset.

**Severity:** P0 — site-wide accent baked wrong at the CSS layer.

---

### P0 — Translucent border/input by design = washed-out borders

**File:** `src/index.css:269–270`

```css
--color-border: color-mix(in srgb, var(--midground-base) 15%, transparent);
--color-input: color-mix(in srgb, var(--midground-base) 15%, transparent);
```

**Impact:** Every `border-border` resolves to `color-mix(... 15% midground, transparent)` — a translucent border that washes out on dark backgrounds. The Claude Code aesthetic uses `1px solid #2a2c2a` (opaque, defined hairline). The current translucent approach is the source of the "soft, indistinct edges" feel — opposite of "ops-tool precision."

**Fix:** Make `--color-border` and `--color-border-strong` opaque hex (`#2a2c2a` / `#353735`). Keep an explicit `--color-border-soft` if soft borders are wanted in specific places, but make it opt-in.

**Severity:** P0 — every bordered surface on every page is fighting this.

---

### P1 — Baseline `--radius: 0.5rem` (8px) too large for ops-tool precision

**File:** `src/index.css:89–90`

```css
--radius: 0.5rem;
--theme-radius: 0.5rem;
```

**Then derived:** lines 275–278

```css
--radius-sm: calc(var(--theme-radius) - 4px);  /* 4px */
--radius-md: calc(var(--theme-radius) - 2px);  /* 6px */
--radius-lg: var(--theme-radius);              /* 8px */
--radius-xl: calc(var(--theme-radius) + 4px);  /* 12px */
```

**Impact:** UI primitives use `rounded-lg` (8px) and `rounded-xl` (12px) by default. Claude Code aesthetic is `rounded-sm` (4px) / `rounded-md` (6px) for ops tools. Reducing the base radius scales everything down without per-component edits.

**Fix:** Drop `--radius` to `0.375rem` (6px). The derived sm/md/lg/xl become 2/4/6/10px which is much closer to the target.

**Severity:** P1 — single-line change with site-wide effect.

---

### P1 — `.elevate-page-shell` strips ALL uppercase + tracking globally

**File:** `src/index.css:178–185`

```css
.elevate-page-shell .uppercase {
  text-transform: none;
  letter-spacing: 0;
}

.elevate-page-shell [class*="tracking-["] {
  letter-spacing: 0;
}
```

**Impact:** Every page wrapped in `elevate-page-shell` (which is most of them) has all `.uppercase` and `[class*="tracking-["]` neutralized. This was likely a deliberate de-AI-slop move at some point — kill all uppercase tracked labels because they were used everywhere as decoration.

But Claude Code aesthetic DOES use mono uppercase tracked labels — sparingly, for structural elements (column headers, timestamps, status codes). The current rule throws the baby out with the bathwater. AgentHubPage uses `font-mono-ui text-[10px] uppercase tracking-wider` for column headers and this rule kills it inside `.elevate-page-shell`.

**Verification needed:** Check whether AgentHubPage is wrapped in `.elevate-page-shell` or escapes it.

**Fix:** Remove the blanket override. Restore uppercase + tracking by default. If specific pages have AI-slop tracked labels, fix them at the call site, not site-wide.

**Severity:** P1 — neutralizes a key part of the target aesthetic.

---

### P1 — Textarea/pre/iframe radii too round + iframe drop shadow

**File:** `src/index.css:202, 208, 221, 223`

```css
.elevate-page-shell textarea { border-radius: 1rem; }       /* 16px */
.elevate-page-shell pre { border-radius: 1rem; }            /* 16px */
.elevate-docs-shell iframe {
  border-radius: 1.35rem;                                    /* 21.6px */
  box-shadow: 0 24px 90px rgba(0, 0, 0, 0.22);
}
```

**Impact:** Textareas and `<pre>` blocks (used heavily in Chat, Settings, Memory) are 16px-rounded. Iframes in Docs are nearly 22px rounded with a heavy drop shadow. None of this matches ops-tool precision.

**Fix:** Drop textarea/pre to `0.375rem` (6px). Drop iframe to `0.5rem`, kill the drop shadow (use border instead).

**Severity:** P1.

---

### P2 — `--warm-glow` baked into Backdrop

**File:** `src/index.css:63`

```css
--warm-glow: rgba(217, 119, 87, 0.14);
```

Used by `<Backdrop />` component to paint a soft terracotta glow behind page chrome. This is decorative — defensible if subtle, but evaluate whether it's adding ambient warmth or AI-slop atmosphere.

**Severity:** P2 — judgment call, lean kill if it's noticeable.

---

### P3 — `memory-constellation` decorations

**File:** `src/index.css:368–488`

The memory constellation visualization has its own animation suite (edge-flow, halo-breathe, node-enter), drop-shadows tinted with `--color-primary`, gradient overlays. This is a single feature on `/memory` page. Reasonable to keep as a focused interactive viz, but the drop-shadow filters and gradient overlays are non-trivial visual weight.

**Severity:** P3 — re-audit only if `/memory` redesign changes the viz approach.

---

## 2. Theme System — `src/themes/presets.ts` + `src/themes/context.tsx`

### P0 — Typography preset ships Aptos as first sans

**File:** `src/themes/presets.ts:17`

```ts
const SYSTEM_SANS =
  'Aptos, "Avenir Next", "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
```

**Override path:** `themes/context.tsx:302` → `typographyVars(theme.typography)` → sets `--theme-font-sans` inline on `:root` → wins over `index.css:69`'s Geist value.

**Result:** Even though `index.css:5` imports Geist from Google Fonts and `index.css:69` sets Geist as the default, **users see Aptos** because ThemeProvider's preset overrides on mount. The Geist import succeeds but no rule references it (until ThemeProvider's preset is fixed).

**Memory says:** "Fonts: Geist Sans everywhere. JetBrains Mono only for all-caps structural labels."

**Fix:** Replace `SYSTEM_SANS` value with the Geist stack from `index.css:69`. Replace `SYSTEM_MONO` with the Geist Mono stack from `index.css:72`.

**Severity:** P0 — every page renders in the wrong sans.

---

### P0 — Dark theme description vs. reality contradiction

**File:** `src/themes/presets.ts:38–48`

```ts
export const darkTheme: DashboardTheme = {
  name: "dark",
  label: "Dark",
  description: "Warm-tinted dark workspace with terracotta accent",
  palette: {
    background: { hex: "#101827", alpha: 1 },   // navy, not warm
    midground: { hex: "#f4f7f5", alpha: 1 },    // cool mint white
    ...
  }
};
```

**Impact:** Background is cool navy, midground is cool mint white. Color mixing of these produces uniformly cool-leaning surfaces. The description claims "warm-tinted" but the hexes are objectively cool. Must change both:

- `background.hex`: `#101827` → `#1a1b1a` (warm dark)
- `midground.hex`: `#f4f7f5` → `#ececec` (neutral light, matches Claude install.html `--text: #ececec`)

This single change cascades into every derived surface (`--chat-surface`, `--chat-border`, `--color-card`, `--color-muted`, `--sidebar-*`).

**Severity:** P0 — foundation-level color cast wrong.

---

### P1 — Light theme uses navy `#1B2A4A` as primary

**File:** `src/themes/presets.ts:92`

```ts
primary: "#1B2A4A",
```

**Impact:** Light theme intentionally swaps primary to navy. This is a stylistic choice for "Clean real-estate workspace" but creates inconsistency: dark theme = terracotta, light theme = navy. Buttons, focus rings, and links change identity entirely between themes. Consider:

- Option A: Keep current — dark = terracotta CTA, light = navy CTA (real-estate professional feel)
- Option B: Unify on terracotta in both themes — preserves brand identity

This is a design call. Flag for user decision.

**Severity:** P1 — judgment call, no obvious "right" answer.

---

### P2 — Legacy theme aliases map cyberpunk/ember/midnight/mono/rose → dark

**File:** `src/themes/context.tsx:30–37`

```ts
const LEGACY_THEME_ALIASES: Record<string, string> = {
  cyberpunk: DEFAULT_THEME_NAME,
  default: DEFAULT_THEME_NAME,
  ember: DEFAULT_THEME_NAME,
  midnight: DEFAULT_THEME_NAME,
  mono: DEFAULT_THEME_NAME,
  rose: DEFAULT_THEME_NAME,
};
```

These were prior theme names that no longer exist; aliases keep stored preferences from breaking. Fine to keep but document why each legacy name maps where it does, or kill the dead names entirely (current users on `dark` won't notice).

**Severity:** P3.

---

## 3. UI Primitives — `src/components/ui/*.tsx` (11 files)

**Status:** Every primitive carries baseline slop. Cascade impact: every consuming page inherits the wrong defaults.

### P0 — Card default: rounded-lg + translucent background

**File:** `src/components/ui/card.tsx:29`

```ts
className={cn(
  "w-full rounded-lg border border-border/70 bg-card/80",
  ...
)}
```

**Impact:** Every `<Card>` site-wide renders with:
- `rounded-lg` = 8px (target is 4–6px)
- `border-border/70` = already-translucent border further reduced to 70% opacity
- `bg-card/80` = card color at 80% — translucent surface mixing with whatever's behind

This is the source of the "soft, smudgy edges" feel across the dashboard. Used by ~50+ consumers.

**Fix:** `rounded-md border border-border bg-card`. Or with the foundation fixes above, default to a 6px solid-bordered, opaque-surfaced card.

**Severity:** P0 — cascade-impact primitive.

---

### P0 — Button outline variant: translucent surface

**File:** `src/components/ui/button.tsx:12`

```ts
outline: "border border-border/80 bg-card/60",
```

**Impact:** Outline buttons (used as secondary CTA throughout) render with 60% surface opacity. Hover/focus states layer translucency on translucency.

**Fix:** `border border-border bg-card` opaque.

**Severity:** P0.

---

### P0 — Badge palette tints (4 variants)

**File:** `src/components/ui/badge.tsx:11–14`

```ts
default: "bg-card text-foreground",
success: "bg-success/12 text-success",
warning: "bg-warning/15 text-warning",
destructive: "bg-destructive/12 text-destructive",
```

**Impact:** Status pills (deal stages, lead temperatures, agent statuses) all use the palette-tint pattern that the target aesthetic explicitly rejects. AgentHubPage proves you can convey state without palette-glow pills (mono uppercase label + left-edge color strip).

**Fix:** Restructure badges as:
- `mono uppercase tracking-wider text-[10px]` typography
- Border + transparent background by default
- Left-edge accent strip OR colored dot for state, not full background tint

**Severity:** P0 — appears on every page that surfaces status.

---

### P0 — Input field: translucent surface + rounded-md

**File:** `src/components/ui/input.tsx:7`

```ts
"flex h-9 w-full rounded-md border border-border/80 bg-card/55"
```

**Impact:** Form inputs across NewDealDialog, Settings, Search, Login all render at 55% opacity. Focus visibility is impaired against translucent backgrounds.

**Fix:** `rounded-sm border border-border bg-background` solid.

**Severity:** P0.

---

### P0 — Select trigger + dropdown over-rounded + custom shadow

**File:** `src/components/ui/select.tsx:94, 116`

```ts
// Trigger
"rounded-xl"  // 12px
// Dropdown
"rounded-2xl bg-popover shadow-[0_18px_54px_rgba(0,0,0,0.22)]"  // 16px + custom drop shadow
```

**Impact:** Every Select component (workspace pickers, stage filters, assignee dropdowns) ships with rounded-xl trigger and rounded-2xl dropdown with custom drop shadow. The shadow + rounding combo is one of the strongest AI-slop tells — "floating glassy panel" aesthetic.

**Fix:** `rounded-sm` trigger, `rounded-md` dropdown, replace shadow with `border border-border-strong`.

**Severity:** P0.

---

### P0 — Confirm dialog: rounded-xl + shadow-2xl-class custom shadow

**File:** `src/components/ui/confirm-dialog.tsx:68`

```ts
"rounded-xl border border-border/80 bg-card shadow-[0_18px_56px_rgba(0,0,0,0.22)]"
```

**Same pattern as Select.** Every confirm/destructive dialog is rounded-xl + heavy custom drop shadow.

**Fix:** `rounded-md border border-border-strong`. Drop shadow.

**Severity:** P0.

---

### P1 — Segmented + Tabs: inset-shadow pattern

**File:** `src/components/ui/segmented.tsx:14`

```ts
"inline-flex gap-0.5 rounded-lg bg-card/70 p-0.5 shadow-[inset_0_0_0_1px_var(--chat-border)]"
```

**File:** `src/components/ui/tabs.tsx:21`

```ts
"rounded-lg bg-card/70 shadow-[inset_0_0_0_1px_var(--chat-border)]"
```

**Impact:** Tab strips and segmented controls render with rounded-lg + translucent surface + inset 1px shadow (used as a border-replacement that respects rounding). The pattern is fine but the values are too soft — rounded-lg too large, translucent surface again.

**Fix:** `rounded-sm bg-background border border-border` — get rid of the inset-shadow trick, use actual borders.

**Severity:** P1.

---

### P1 — Switch palette glow on checked state

**File:** `src/components/ui/switch.tsx:27`

```ts
checked ? "bg-success/18 border-success/35" : "bg-card/70"
```

**Impact:** Switch components use the same palette-tint approach when on. Color-glow on a binary control is louder than necessary.

**Fix:** `checked ? "bg-primary border-primary"` solid terracotta. The contrast between on/off is the signal; no need for additional tinting.

**Severity:** P1.

---

## 4. Non-UI Components — `src/components/*.tsx` (20 files)

**Slop hits already mapped pre-compact.** Summary by component:

| Component | File:Lines | Slop Hits | Severity |
|-----------|-----------|-----------|----------|
| ChatSidebar | 62, 65, 332 | 3 palette tints | P1 |
| LoginCard | 161, 299 | 2 palette tints | P1 |
| Markdown | 360 | `bg-warning/30` | P2 |
| ModelInfoCard | 55 | `rounded-2xl bg-muted/30` | P1 |
| MemoryConstellation | 574, 589, 779, 790, 805, 808, 830 | 7 surfaces with mixed rounding + translucency | P1 |
| **ModelPickerDialog** | 141, 147, 288, 369 | **`bg-background/85 backdrop-blur-sm` overlay + `rounded-xl shadow-[0_18px_56px]` panel + `bg-primary/10` selected** | **P0** |
| **OAuthLoginModal** | 180, 186, 347 | **Same modal pattern as above** | **P0** |
| PlatformsCard | 46 | `rounded-2xl border` | P1 |
| SidebarUserPill | 65 | `rounded-xl` popover | P1 |
| Toast | 29, 30 | `bg-success/15` + `bg-destructive/15` (legit toast usage) | clean |
| ThemeSwitcher | 80 | `shadow-[0_8px_24px_rgba(0,0,0,0.18)]` | P1 |
| SlashPopover | 577, 598, 619 | `shadow-[0_12px_36px]` + `rounded-xl` rows + inset-shadow pills | P1 |
| ToolCall | 39 | `border-primary/40 bg-primary/[0.04]` running state | P2 |
| Backdrop | (decorative) | warm-glow + noise overlay | judgment call |
| ChatHeader, Codeblock, ContextEditor, others | — | clean | — |

### The Modal Pattern (P0, applies to ModelPickerDialog + OAuthLoginModal + ConfirmDialog)

```ts
// Overlay
"fixed inset-0 z-50 bg-background/85 backdrop-blur-sm"
// Panel
"rounded-xl border border-border/80 bg-card shadow-[0_18px_56px_rgba(0,0,0,0.22)]"
// Selected row
"bg-primary/10 text-primary"
```

This pattern is the strongest AI-slop tell in the codebase. Backdrop-blur over the page, rounded-xl floating panel, custom heavy drop shadow, palette-glow selection. Three components use it; ConfirmDialog inherits via primitive.

**Fix:** Solid backdrop (`bg-background/60` without blur, OR full `bg-background`), `rounded-md` panel, opaque border instead of shadow, selected row = solid `bg-primary text-primary-foreground` with mono ID label.

---

## 5. Hooks + Contexts (Functional Layer)

Functionally clean. One UI hit:

### P1 — Global header glassmorphism

**File:** `src/contexts/PageHeaderProvider.tsx:58`

```ts
"bg-background-base/72 backdrop-blur-sm"
```

**Impact:** Every page (except `/chat` and `/config`) renders its top chrome with 72% background + backdrop-blur. This is the GLOBAL HEADER bar — site-wide glassmorphism on the most-seen element.

**Fix:** `bg-background border-b border-border` solid.

**Severity:** P1 — single line, every page.

Other hooks/contexts (SystemActions, useToast, useConfirmDelete, useSidebarStatus, page-header-context, useSystemActions, usePageHeader) are functionally tight and have no UI surface.

---

## 6. Electron Shell — `~/elevate/desktop/src/`

### Architecture (clean, security-good)

- `main.js` (412L): spawns Python `elevate_cli` backend on `:9119`, waits for ready signal, loads React app from local backend, falls back to install.html if not reachable.
- `preload.js` (7L): exposes only `retry` and `install` to renderer via contextBridge — minimal IPC surface, **good security posture**.
- `install.html` (149L): setup screen, terracotta-styled, matches target aesthetic correctly.
- `loading.html`: pre-boot loading screen.

### P1 — Electron window backgroundColor mismatches CSS background

**File:** `~/elevate/desktop/src/main.js:300`

```js
backgroundColor: "#1a1b1a",
```

**vs.** `index.css:59` `--background-base: #101827`.

**Impact:** Electron paints the native window background as warm `#1a1b1a` (matching target). Then the web app loads and paints `#101827` (navy) on top. Result: brief flash of warm dark → navy on every cold launch. The Electron native background is right; the web app's background is wrong. Fixing token #1 above makes them match.

**Severity:** P1 — secondary consequence of foundation P0 fix.

---

### P2 — Menu shortcuts only cover 5 of 9+ navigable routes

**File:** `~/elevate/desktop/src/main.js:257–262`

```js
{ label: "Chat", accelerator: "CmdOrCtrl+1", click: () => loadAppPath("/chat") },
{ label: "Agent Hub", accelerator: "CmdOrCtrl+2", click: () => loadAppPath("/hub") },
{ label: "Setup", accelerator: "CmdOrCtrl+3", click: () => loadAppPath("/desktop-setup") },
{ label: "Tasks", accelerator: "CmdOrCtrl+4", click: () => loadAppPath("/tasks") },
{ label: "Memory", accelerator: "CmdOrCtrl+5", click: () => loadAppPath("/memory") },
```

**Impact:** No shortcuts for `/leads`, `/admin`, `/social`, `/today`, `/analytics`, `/sessions`, `/config`. Power-user efficiency loss.

**Fix:** Add Cmd+6 Leads, Cmd+7 Admin, Cmd+8 Social, Cmd+9 Today. Or restructure to feature-flag-aware (read backend's enabled routes).

**Severity:** P2.

---

### P3 — `npx --yes github:Dartagnan98/elevate-agent install --skip-setup` is a network-trusted execution path

**File:** `~/elevate/desktop/src/main.js:357–358`

```js
installProcess = spawn(npx, ["--yes", "github:Dartagnan98/elevate-agent", "install", "--skip-setup"], ...);
```

**Impact:** When install button is clicked, npx pulls and executes the latest commit from GitHub. Trust model: user clicks install → app executes arbitrary code from GitHub. Standard for self-hosted CLI installs but worth noting.

**Severity:** P3 — informational, by design.

---

### P3 — sandbox: false in webPreferences

**File:** `~/elevate/desktop/src/main.js:306`

```js
sandbox: false,
```

contextIsolation is on, nodeIntegration is off. Sandbox could be true for tighter renderer isolation. Probably off because the renderer needs to load from localhost backend — sandbox restrictions might break some flows.

**Severity:** P3 — defensible, document the reason.

---

## 7. Systemic Patterns (Site-Wide Anti-Patterns)

| # | Pattern | Location | Severity |
|---|---------|----------|----------|
| 1 | Translucent surfaces (`bg-card/55-80`) | Every UI primitive | **P0** |
| 2 | Palette-tint badges/pills (`bg-{success,warning,destructive}/12-30`) | Badge primitive, 80+ consumers | **P0** |
| 3 | Custom heavy drop shadows (`shadow-[0_18px_56px_rgba(0,0,0,0.22)]`) | All modals, dropdowns | **P0** |
| 4 | rounded-xl / rounded-2xl on panels | All modals, popovers, info cards | **P0** |
| 5 | Backdrop-blur on modal overlays | ModelPicker, OAuthLogin, ConfirmDialog | **P0** |
| 6 | Backdrop-blur on global header | PageHeaderProvider | P1 |
| 7 | Translucent borders (`border-border/70-80`) | Card, Button, Input, everywhere | P1 |
| 8 | Inset-shadow pseudo-borders | Tabs, Segmented | P1 |
| 9 | Palette-glow selected states (`bg-primary/10`) | ModelPicker rows | P1 |
| 10 | Warm-glow ambient backdrop | Backdrop component | P2 |
| 11 | Color-mix translucent everything | Token derivation chain | P2 |

---

## Recommended Foundation Fix Order

Execute in this order — each one's blast radius is smaller than the one above it.

### Phase F1 — Token corrections (1–2 hours)

1. **`index.css:59`** → `--background-base: #1a1b1a`
2. **`index.css:55`** → `--midground-base: #ececec`
3. **`index.css:257, 271, 106, 114`** → replace `#CE823E` and `#7fb2ff` with `#D97757`
4. **`index.css:269–270`** → opaque `--color-border: #2a2c2a`, `--color-border-strong: #353735`
5. **`index.css:89–90`** → `--radius: 0.375rem`
6. **`index.css:178–185`** → remove the `.elevate-page-shell .uppercase` neutralizer
7. **`index.css:202, 208, 221, 223`** → drop textarea/pre/iframe radii to `0.375–0.5rem`, kill iframe shadow

### Phase F2 — Preset corrections (30 min)

8. **`presets.ts:17`** → `SYSTEM_SANS` to Geist Sans stack (mirror index.css:69)
9. **`presets.ts:18`** → `SYSTEM_MONO` to Geist Mono stack (mirror index.css:72)
10. **`presets.ts:43`** → `background.hex: "#1a1b1a"`
11. **`presets.ts:44`** → `midground.hex: "#ececec"`
12. **`presets.ts:88, 104, 105`** → light theme border/input/card review against new foundation

### Phase F3 — UI primitives (2–3 hours)

13. **card.tsx:29** → `rounded-md border border-border bg-card`
14. **button.tsx:12** → outline = `border border-border bg-card`
15. **badge.tsx:11–14** → restructure all 4 variants as mono-label + left-edge strip + transparent bg
16. **input.tsx:7** → `rounded-sm border border-border bg-background`
17. **select.tsx:94, 116** → trigger `rounded-sm`, dropdown `rounded-md border border-border-strong`, no shadow
18. **confirm-dialog.tsx:68** → `rounded-md border border-border-strong`, no shadow
19. **segmented.tsx:14, tabs.tsx:21** → `rounded-sm bg-background border border-border`
20. **switch.tsx:27** → checked = `bg-primary border-primary`

### Phase F4 — Modal pattern (1 hour)

21. **ModelPickerDialog.tsx:141, 147, 288, 369** → solid backdrop, `rounded-md` panel, no custom shadow, solid selected row
22. **OAuthLoginModal.tsx:180, 186, 347** → same pattern
23. **PageHeaderProvider.tsx:58** → `bg-background border-b border-border` solid

### Phase F5 — Cleanup pass (1 hour)

24. Sweep remaining hits in components/* per the table in §4
25. Verify Backdrop + warm-glow against new foundation
26. Audit `.elevate-page-shell` rule for residual conflicts

**Total foundation rework: ~6–8 hours**. After this lands, the per-page audit findings reduce by ~60% because most slop hits inherit from the primitives.

---

## What's NOT Broken

Affirmative findings worth preserving:

- **AgentHubPage.tsx** — 0 anti-pattern hits across 10 components. Already implements the target aesthetic: mono uppercase column headers, divide-y instead of card grids, left-edge state strips, opaque borders. **Use as reference implementation.**
- **install.html** — already shipped with correct warm dark `#1a1b1a` / `#212321` / `#2a2c2a` and `#D97757` accent. The Electron pre-boot screens are already on target.
- **PageHeaderProvider header structure** — clean slot-based design (title + afterTitle + end), good responsive behavior, only the glassmorphism style needs to come off.
- **Hooks/contexts** — functionally tight, no architectural redesign needed.
- **Electron IPC surface** — minimal (2 handlers), proper contextIsolation, well-scoped permissions.
- **Theme override architecture** — the layered approach (CSS defaults → preset → inline runtime override) is sound; only the values need correcting.

---

## Next Steps

1. **Confirm foundation fix order with user** before touching code
2. **Land F1+F2 as one PR** (CSS + presets) — single-shot color/font/radius correction
3. **Land F3 as one PR** (UI primitives) — cascade fixes
4. **Land F4 as one PR** (modals + global header)
5. **Re-audit per-page after foundation lands** — expect 60% slop reduction without per-page edits, remaining hits are page-specific

After foundation, the per-page redesigns in tasks #23-28 will start from a clean slate where the target aesthetic is the default, not something every page has to fight to express.
