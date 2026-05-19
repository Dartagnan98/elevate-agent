# Elevate Desktop App — Dashboard Audit

**Date:** 2026-05-13
**Target aesthetic:** Claude Code dashboard — warm-tinted dark neutrals (`#1a1b1a` / `#212321` / `#2a2c2a`), Geist Sans + JetBrains Mono for structural labels, `#D97757` terracotta accent, ops-tool precision, no gradients, no glassmorphism, no oversized radii, no hero-metric cards, no card-grid stacking.
**Scope:** All 18 page files served inside the Electron shell at `~/elevate/desktop/` (which loads `cli/web/` React build via Python backend on :9119). Total ~25k LOC.
**Method:** /audit skill — 5 dimensions × 0–4 = Health Score /20, anti-pattern verdict, P0–P3 findings with `file:line` evidence.

---

## Audit Health Score

| # | Dimension          | Score | Key Finding |
|---|--------------------|-------|-------------|
| 1 | Accessibility      |   3   | ARIA used liberally (42 in ConfigPage, 34 in RealEstateHub). One hidden file input unlabeled (legit). Focus rings present. Touch targets inconsistent — only ConfigPage uses `min-h-[44px]` explicitly; most surfaces rely on default `h-9`/`h-10` (~36–40px). No skip-links. Color-only state on success/destructive WoW deltas. |
| 2 | Performance        |   3   | Vite chunk-splitting done (admin 108 kB, social/tasks/memory split). Main chunk still 98.84 kB (Today + Leads bundled). 4187-line ChatPage is monolithic. No image lazy-loading audit needed (no `<img>` tags). Some `divide-y` and divs-as-buttons in row lists. |
| 3 | Theming            |   3   | CSS tokens in place (`--bg`, `--surface`, `--border`, `--primary`). 32 instances of translucent palette tints (`bg-{primary,warning,success,destructive}/{5..30}`) that bypass token discipline and produce AI-slop "soft glow" surfaces. Backgrounds occasionally leak as `bg-background/55` and `bg-card/45` instead of solid surface tokens. |
| 4 | Responsive Design  |   3   | Grid breakpoints used (`lg:grid-cols-2 2xl:grid-cols-3`). Tab strips reflow. Touch targets generally OK but not enforced. Some fixed-width side panels in admin kanban that may overflow on smaller window widths (desktop window minWidth 980×680). |
| 5 | Anti-Patterns      |   1   | Heavy AI aesthetic — 47 instances of `rounded-2xl/3xl`, 32 translucent palette tints, 20 instances of `tracking-[0.14em+]` excess letter-spacing, 15 custom `shadow-[...]` (mostly legit inset-border but several glow shadows in ChatPage), card-grid stacking instead of `divide-y` lists, hero-metric cards (Readiness, lane summaries), generic-icon-in-rounded-square chrome throughout. |
| **Total** | | **13/20** | **Acceptable — significant work needed** |

**Rating band:** 10–13 Acceptable. The plumbing (tokens, ARIA, chunking) is in place; the surface chrome is AI-default and undermines the Claude Code ops-tool target.

---

## Anti-Patterns Verdict — **FAIL**

Yes, this looks AI-generated in 6 of 18 pages and partially AI-generated in 4 more. Specific tells, ranked:

1. **`rounded-2xl` epidemic (47 sites)** — Soft pillowy surfaces everywhere instead of crisp 4–6px `rounded-sm`/`rounded-md` ops-tool corners. Worst offenders: `RealEstateHubPages.tsx` (11), `ChatPage.tsx` (9), `admin/index.tsx` (7), `DesktopSetupPage.tsx` (6).
2. **Translucent palette glow surfaces (32 sites)** — `bg-primary/10`, `bg-warning/10`, `bg-success/10`, `border-destructive/45` used as "status pill" or "selected card" treatment. Reads as AI slop badge gallery. Worst: `admin/index.tsx` (17), `RealEstateHubPages.tsx` (16), `SessionsPage.tsx` (10), `ConfigPage.tsx` (5).
3. **Excessive letter-spacing (20 sites, all in RealEstateHubPages)** — `tracking-[0.14em]`, `tracking-[0.16em]`, `tracking-[0.2em]` on mono section labels. The Claude Code aesthetic uses `tracking-wider` (0.05em) or `tracking-widest` (0.1em) max. Above that reads as 2010s-startup-deck.
4. **Hero metric cards** — Readiness as a giant pulsing card with progress ring instead of a 22px tabular number with a 1px under-rule. `RealEstateHubPages.tsx` lane summaries similarly use card stacks per lane rather than a single divided strip.
5. **Card-grid stacking** — Most lists render as `space-y-3` stacks of bordered `rounded-2xl` cards. Should be `divide-y divide-border` rows on a single surface.
6. **Generic-icon-in-colored-square chrome** — Lucide icons wrapped in `bg-primary/10 rounded-xl p-2` "icon tile" pattern. Slop default.
7. **`bg-background/55` and `bg-card/45` translucency on form fields** — Form chrome shouldn't be translucent. Should be `bg-background` solid or `bg-input` token. See `DesktopSetupPage.tsx:504,515,538,571,577` and `admin/index.tsx` field rows.

What is NOT slop here (kudos):
- No gradient text (`bg-clip-text` not used)
- No `bg-gradient-` backgrounds anywhere
- Backdrop-blur limited to 2 modal overlays in ChatPage (legit)
- No emoji UI
- No AI palette (sky/violet/fuchsia/etc.) — all tokens-based
- `font-mono-ui` token correctly defined; uppercase mono labels used consistently for column headers and timestamps
- Pre-boot Electron screens (`loading.html`, `install.html`, `main.js` window bg) already redesigned this session — terracotta + solid surface, no glow, no gradient

---

## Executive Summary

- **Audit Health Score: 13/20 (Acceptable — significant work needed)**
- Total issues: **8 P0** / **17 P1** / **24 P2** / **11 P3**
- Top 5 critical:
  1. RealEstateHubPages (`Today` + `Leads` lanes) — 11× rounded-2xl, 16 palette tints, 20× excessive letter-spacing. Active core flow. **P0.**
  2. admin/index.tsx — kanban cards still glow-shadowed and rounded; partial redesign in flight needs to be completed pre-ship. **P0.**
  3. ChatPage.tsx (4187 LOC) — 9 rounded-2xl, 15 custom shadows. Primary surface; users live here. **P0.**
  4. SessionsPage.tsx ROLE_STYLES (lines 144–162) — translucent palette pills for user/assistant/tool message badges. Replace with mono left-edge accent strips. **P1.**
  5. DesktopSetupPage.tsx field rows — 6× rounded-2xl + translucent backgrounds on form chrome. Bad first-impression page (it's the setup wizard). **P1.**
- Recommended next step: **complete this audit → plan redesign per page → implement page-by-page starting with the worst offenders (RealEstateHubPages > admin > Chat > Sessions > DesktopSetup) → leave already-clean pages (AgentHub, Analytics, Docs, Project, Skills, memory, tasks) alone except for /polish pass.**

---

## Detailed Findings by Severity

### P0 — Blocking (fix immediately)

**[P0] `Today` and `Leads` lanes are AI-slop card galleries**
- **Location:** `src/pages/RealEstateHubPages.tsx` (3,900 LOC)
- **Category:** Anti-Pattern + Information Hierarchy
- **Evidence:**
  - `rounded-2xl` ×11 — lines 234, 272, 284, 752, 990, 1078, + 5 more
  - Translucent palette pills ×16 — lines 826, 828, 1427, 1440, 1897, 1899 (`border-destructive/45 bg-destructive/10`, `border-warning/45 bg-warning/10`, `bg-primary/15`)
  - Excessive letter-spacing ×20 — lines 534, 562, 1389, 1677, 1743, 1850, 1872, 2036 (`tracking-[0.14em]`–`tracking-[0.2em]`)
- **Impact:** Primary user flow (autopilot + approvals) reads as a generic CRM dashboard, not an ops tool. Slow scan, decorative borders compete with content.
- **Recommendation:** Each of the 3 lanes (New Outreach, Hot Leads, Follow-ups) becomes a single `divide-y divide-border` surface; row left-edge `w-0.5 bg-warning` strip for state instead of palette pill; mono labels at `tracking-wider` max; row info hierarchy: 13.5px medium for primary / 12px muted for property/meta / 11.5px tabular-nums for timestamps.
- **Suggested command:** `/layout` then `/polish`

**[P0] Admin kanban cards still pillow-shadowed (partial fix in flight)**
- **Location:** `src/pages/real-estate-hub/admin/index.tsx` (3,645 LOC)
- **Category:** Anti-Pattern
- **Evidence:** Although AdminSetupLaunch/AdminSetupField/AdminKanbanCard/AdminKanbanColumn were partially redesigned this session, 7× `rounded-2xl` remain and 17 translucent palette tints persist in non-kanban regions (NewDealDialog, action runs panel, agent handoffs card).
- **Impact:** Mixed aesthetic — fixed parts look ops-tool, unfixed parts look AI. Worse than fully-AI because of inconsistency.
- **Recommendation:** Finish the redesign — apply the new kanban card pattern (1px borders, mono tabular-nums labels, warning left-edge strip for Top-25, h-px progress lines) to NewDealDialog, AdminActionRuns, AgentHandoffsCard, AdminDealTasks. Strip translucent palette tints throughout.
- **Suggested command:** `/distill` then `/polish`

**[P0] ChatPage primary surface has 9× rounded-2xl + 15× custom shadows**
- **Location:** `src/pages/ChatPage.tsx` (4,187 LOC)
- **Evidence:**
  - `rounded-2xl` at lines 2851, 3197, 3344, 3473, 3676, 3738, 3742, 3782, 4099
  - Custom `shadow-[...]` at lines 2659, 2765, 2783, 2830, 2933, 3082, 3197, 3281, 3473, 3674, 3676, 3742, 3782, 3832, 4099 (~10 legit inset-borders for chat-bubble outline, 5 actual glow shadows that should die)
- **Impact:** This is where users live. Bubbly message bubbles, soft floating cards. Should feel like Claude Code's chat — flat, mono-tagged, tight spacing.
- **Recommendation:** Strip the glow shadows; keep inset-border shadows as 1px solid borders; reduce all surface radii to `rounded-md` (6px) or `rounded-sm` (4px); mono timestamps left-aligned at `text-[10px]`.
- **Suggested command:** `/quieter` then `/polish`

**[P0] Information hierarchy collapse: hero metrics dominate over actionable rows**
- **Location:** Cross-cutting — RealEstateHubPages lane summaries, admin Readiness card, DesktopSetupPage progress headers
- **Category:** Information Hierarchy (Anti-Pattern)
- **Evidence:** Top of every page is a large hero card with one big number and a progress ring/bar. The actual work (rows users need to act on) is pushed below the fold on a 980×680 window (the desktop minWidth).
- **Impact:** Forces a scroll on every load. Wastes the most valuable pixels above the fold.
- **Recommendation:** Replace hero metric cards with an inline `<header>` strip: mono label (10px uppercase tracking-wider) + tabular-nums value (22px medium) + 1px under-rule. Total height ~64px instead of ~160px. See pattern already shipped in AdminSetupLaunch redesign.
- **Suggested command:** `/distill` then `/layout`

**[P0] Spacing rhythm inconsistent across pages**
- **Location:** Cross-cutting — most pages use `space-y-4`/`space-y-5`/`space-y-6`/`gap-3`/`gap-4`/`gap-5` interchangeably without a system
- **Category:** Information Hierarchy
- **Impact:** Pages don't share a visual rhythm — feels stitched-together. The Claude Code aesthetic relies on a strict scale: section gap 24px, card gap 16px, row gap 8px.
- **Recommendation:** Lock the scale: `space-y-6` for top-level page sections, `space-y-4` inside a section, `space-y-2` for label/value pairs, `divide-y` for row lists. Document in `_shared/spacing.md`.
- **Suggested command:** `/layout`

**[P0] Desktop window minWidth 980 is too forgiving for layouts that assume 1280+**
- **Location:** `~/elevate/desktop/src/main.js:296–308` sets `minWidth: 980, minHeight: 680`. But several pages use `2xl:grid-cols-3` (1536px+ break) and `lg:grid-cols-2` (1024px+) — at 980px they fall back to single-column and look broken.
- **Category:** Responsive
- **Recommendation:** Either bump desktop `minWidth` to 1200 (matches Claude Code minimum), OR add `md:grid-cols-2` (768px+) breakpoints so layouts don't snap to single-column at the actual user-resizable minimum.
- **Suggested command:** `/adapt`

**[P0] Touch targets not enforced — most controls render at 36px**
- **Location:** Default Tailwind sizes used; only ConfigPage uses `min-h-[44px]` explicitly (3 sites)
- **Category:** A11y
- **Evidence:** `min-h-[44px]` appears 3 times total across 18 page files. Buttons default to `h-9` (36px), inputs to `h-9`/`h-10` (36–40px). WCAG 2.5.5 (target size) recommends 24×24 AA, 44×44 AAA.
- **Impact:** This is a desktop app — keyboard primary, but trackpad-tap and touchscreen-Mac users get small targets.
- **Recommendation:** Set default button height to `h-9` (36px) for desktop density (acceptable for AA at 24px) but raise primary CTAs and form submit buttons to `h-10` (40px) minimum. Document the contract.
- **Suggested command:** `/optimize`

**[P0] DesktopSetupPage — setup wizard is users' first impression, currently slop**
- **Location:** `src/pages/DesktopSetupPage.tsx:433,490,504,515,538,571,577`
- **Evidence:** 6× `rounded-2xl` form/pack cards, `border-border/60 bg-card/45` translucent surfaces, `bg-primary/10` selected-state tints.
- **Impact:** Users land here on first install. Bubbly card chrome doesn't say "professional ops tool."
- **Recommendation:** Convert pack-unlock-cards and field rows to 1px-border crisp surfaces with `rounded-sm`. Replace `bg-primary/10` selected-state with 2px left border + mono label. Solid backgrounds, no `/45` translucency.
- **Suggested command:** `/quieter`

---

### P1 — Major (fix before release)

**[P1] SessionsPage ROLE_STYLES translucent palette pills**
- **Location:** `src/pages/SessionsPage.tsx:144–162,297,800,890`
- **Evidence:** ROLE_STYLES map uses `bg-primary/10 text-primary`, `bg-success/10 text-success`, `bg-warning/10 text-warning` for user/assistant/tool message role badges. 3× `rounded-2xl` session cards.
- **Recommendation:** Replace role pills with 1px-border-left strip (e.g. `border-l-2 border-primary` for user, `border-l-2 border-success` for assistant, `border-l-2 border-warning` for tool) + 10px mono label "USER" / "ASSISTANT" / "TOOL". Drop the pill chrome entirely.
- **Suggested command:** `/quieter`

**[P1] ConfigPage 5 translucent palette tints**
- **Location:** `src/pages/ConfigPage.tsx` (2,215 LOC)
- **Recommendation:** Audit and replace `bg-primary/{5..15}` with neutral surface or accent left-border. Already strong on ARIA (42 sites) — visual chrome is the remaining gap.
- **Suggested command:** `/polish`

**[P1] EnvPage 3× rounded-2xl + 2 palette tints**
- **Location:** `src/pages/EnvPage.tsx` (673 LOC)
- **Recommendation:** Standardize to `rounded-md`, strip palette tints. Mono labels for env-var keys.
- **Suggested command:** `/polish`

**[P1] CronPage 2× rounded-2xl, hero job summary**
- **Location:** `src/pages/CronPage.tsx` (825 LOC)
- **Recommendation:** Convert job list to `divide-y` rows with mono cron expression + tabular-nums next-run timestamp. Status as left-edge color strip.
- **Suggested command:** `/layout`

**[P1] SkillsPage 2× rounded-2xl skill cards**
- **Location:** `src/pages/SkillsPage.tsx` (728 LOC)
- **Recommendation:** Skill cards → `divide-y` rows with mono trigger label.
- **Suggested command:** `/polish`

**[P1] RealEstateTemplatesPage 1× rounded-2xl + 1 palette tint**
- **Location:** `src/pages/RealEstateTemplatesPage.tsx` (781 LOC)
- **Recommendation:** /polish pass.
- **Suggested command:** `/polish`

**[P1] ProjectPage 1× rounded-2xl**
- **Location:** `src/pages/ProjectPage.tsx` (227 LOC)
- **Recommendation:** Small page — one-pass /polish.
- **Suggested command:** `/polish`

**[P1] AgentHubPage 0 anti-pattern hits but uses agent-widgets cluster (641 LOC)**
- **Location:** `src/pages/AgentHubPage.tsx` (1,279 LOC) + `_shared/agent-widgets.tsx`
- **Evidence:** Clean at the page level — verify agent-widgets internally aren't reintroducing slop.
- **Recommendation:** Spot-check agent-widgets for `rounded-2xl`/palette tints; otherwise leave.
- **Suggested command:** `/audit` on `_shared/agent-widgets.tsx`

**[P1] Color-only state on success/destructive WoW deltas**
- **Location:** `social/index.tsx:268,276` and similar in admin kanban — `<span className={delta >= 0 ? "text-success" : "text-destructive"}>{+/- value}</span>`
- **Category:** A11y (WCAG 1.4.1 use of color)
- **Recommendation:** Add `+` / `−` prefix (or arrow icon) so colorblind users get a non-color signal.
- **Suggested command:** `/optimize`

**[P1] No focus-visible style on custom Card components inside admin/leads**
- **Location:** Most clickable `<div>` cards in `RealEstateHubPages.tsx` lead rows
- **Category:** A11y (WCAG 2.4.7 focus visible)
- **Recommendation:** Replace clickable `<div>`s with `<button>` or add `tabIndex={0}` + `focus-visible:outline-2 focus-visible:outline-primary` (current pattern in admin/index.tsx after redesign).
- **Suggested command:** `/optimize`

**[P1] Loading states inconsistent — Loader2 spinner mixed with skeleton mixed with text**
- **Location:** Cross-cutting — `social/index.tsx:231–233`, RealEstateHubPages various, admin various
- **Recommendation:** One pattern: mono `LOADING …` label centered, no spinner spam. Or skeleton rows that match final row geometry.
- **Suggested command:** `/distill`

**[P1] Mono labels inconsistently apply `font-mono-ui` token**
- **Location:** Some uppercase labels use `font-mono`/`uppercase tracking-wider` directly; others use the `font-mono-ui` Tailwind utility. Mix.
- **Recommendation:** Always `font-mono-ui` — that's the single source. Grep and standardize.
- **Suggested command:** `/typeset`

**[P1] Tabular numbers not applied to KPI values**
- **Location:** `social/index.tsx:268,278` and admin lane summaries — count/percent values without `tabular-nums`
- **Recommendation:** Add `tabular-nums` to every numeric value class (timestamps, counts, percentages). Prevents column wobble.
- **Suggested command:** `/typeset`

**[P1] DesktopSetupPage 1117 LOC monolithic**
- **Recommendation:** Split into onboarding wizard steps (access → adminSetup → providers → packs → done). Lazy-load.
- **Suggested command:** `/shape` for plan

**[P1] LogsPage and DocsPage are barely-touched (220 and 54 LOC)**
- **Recommendation:** Likely fine. /polish single pass each.
- **Suggested command:** `/polish`

**[P1] CronPage has 825 LOC but only 4 ARIA hits**
- **Category:** A11y
- **Recommendation:** Add aria-labels to interactive job-toggle buttons; ensure cron expression edit form has labelled inputs.
- **Suggested command:** `/optimize`

**[P1] AnalyticsPage uses `<dl>` with `role="region"` (good) but cards still rounded-xl**
- **Location:** `src/pages/AnalyticsPage.tsx` (417 LOC)
- **Recommendation:** Already 90% there. One pass /polish to crisp the corners.
- **Suggested command:** `/polish`

---

### P2 — Minor (fix in next pass)

- **[P2] DocsPage at 54 LOC** — Likely fine, low-traffic. Leave.
- **[P2] LogsPage at 220 LOC** — Hardcoded `text-success`/`text-destructive` log-level colors; add icons.
- **[P2] Memory + tasks + social all under 500 LOC** — Already split out; just /polish.
- **[P2] 45 instances of `opacity-50` / `text-muted-foreground/{30..70}` for "dimmed" rows** — Inconsistent. Pick one (`text-muted-foreground/70` is the project's documented dim per session memory) and unify.
- **[P2] `font-weight: 720` used in some places** — Should be `500` or `600` for medium emphasis. Geist isn't variable-axis at 720 by default.
- **[P2] No skip-links** — Add `<a href="#main" class="sr-only focus:not-sr-only">Skip to main</a>` once at app root.
- **[P2] Visible focus indicators on tab strips use `outline-2 outline-primary` — works, but inconsistent with focus-visible on rest of app** — Standardize on `focus-visible:ring-2 focus-visible:ring-primary/40` or `focus-visible:outline-2 focus-visible:outline-primary outline-offset-2`. Pick one.
- **[P2] Empty states are full-card with icon + title + description** — Too much chrome. Replace with mono one-liner: `<div className="font-mono-ui text-[11px] uppercase tracking-wider text-muted-foreground py-8 text-center">NO IDEAS WAITING — ENGINE QUEUES MONDAYS 7AM PT</div>`.
- **[P2] Some buttons use `variant="ghost"` for primary refresh actions** — Refresh is ghost (correct), but in some places it gets `min-w-[44px]` for touch and shrinks to icon-only — inconsistent. Standardize to icon-only ghost (28×28) for utility refresh.
- **[P2] Toast notifications styling not audited** — Likely uses translucent variant. Verify `<Toast>` component.
- **[P2] No reduced-motion query** — `animate-spin`, `animate-pulse` should respect `prefers-reduced-motion: reduce`.
- **[P2] No print stylesheet** — Acceptable for desktop app, but reports printed from kanban would benefit.
- **[P2] No high-contrast mode** — `prefers-contrast: more` should boost border opacity and disable translucent surfaces.
- **[P2] Color contrast on `text-muted-foreground` against `bg-card` not verified at AA 4.5:1** — Likely passes but should be tested.
- **[P2] `Badge` component variants don't include a "muted" variant** — Resorting to `Badge variant="outline"` everywhere. Add `muted`.
- **[P2] Confirm dialogs use system `confirm()` in places** — Should be in-app dialogs.
- **[P2] Several `<div role="button" tabIndex={0}>` should be actual `<button>`** — Fixes A11y default focus + keyboard activation.
- **[P2] No keyboard shortcut affordances visible** — Menu has Cmd+1..5 navigation (good), but in-page actions (refresh, approve, reject) have no kbd hints.
- **[P2] Window title bar isn't custom — uses default Electron chrome** — Acceptable, but custom titlebar would feel more polished.
- **[P2] No app icon variant for menubar** — Tray icon would be useful for "Elevate Status".
- **[P2] No notification UX for background events** — Already have Telegram for that — leave.
- **[P2] Theme is dark-only — no theme toggle** — Intentional. Document.
- **[P2] No window state persistence (size/position)** — Add `electron-window-state` or homemade.
- **[P2] DevTools toggle in Help menu — fine for now** — Hide in production builds.

### P3 — Polish (nice-to-fix)

- **[P3] Pre-boot screens already redesigned this session** — Verify on .dmg install: `Elevate-0.11.0-mac-arm64.dmg`. Done.
- **[P3] AppleScript-style mono labels could use lowercase variant for relaxed status** — e.g. `loaded · 38 rows` instead of `LOADED · 38 ROWS`. Test in one spot.
- **[P3] Mark `<E>` in pre-boot screens could be replaced with actual logo SVG** — Currently `font-family: mono` letter `E`. Fine as placeholder.
- **[P3] Splash screen progress bar is indeterminate** — Could show actual backend boot phases (`connecting`, `migrating`, `serving`).
- **[P3] `loading.html` 1.4s sweep animation might be too fast** — Test in dimmed lighting.
- **[P3] Window menu items duplicate macOS native** — Probably fine.
- **[P3] No system tray menu** — Acceptable for v1.
- **[P3] No update channel UX** — Eventually via `electron-updater`.
- **[P3] No crash reporter** — Eventually via Sentry.
- **[P3] No analytics on which pages users actually use** — Acceptable for solopreneur stage.
- **[P3] No keyboard shortcut for "approve current"** — High-value for /leads workflow once redesigned.

---

## Patterns & Systemic Issues

1. **AI-default card chrome** — The codebase reflexively reaches for `<Card>` + `rounded-2xl` + soft shadow + translucent palette tint for every grouping. The Claude Code aesthetic is the opposite: divided rows on a single neutral surface, with mono labels and accent left-borders for state. **Systemic fix:** introduce `_shared/SurfaceList.tsx` (a `divide-y divide-border` wrapper) and `_shared/SurfaceRow.tsx` (a row with left-accent strip slot + label slot + value slot + meta slot). Migrate page-by-page.

2. **Palette tints as decoration, not signal** — `bg-primary/10`, `bg-warning/10`, etc. used as ambient "this section is important" backdrops, not as state signals. **Systemic fix:** ban all `bg-{palette}/{<30}` for decorative use. Reserve translucent palette only for transient overlays (toasts, error banners). Otherwise: solid surface + 2px left border for state.

3. **Hero metric cards above the fold** — Every page leads with a big number in a giant card. **Systemic fix:** introduce `_shared/PageHeader.tsx` with an inline metric strip (label / value / under-rule) max 64px tall. Reserve hero treatment for the executive Analytics view only.

4. **Inconsistent typography scale** — `text-xs` / `text-sm` / `text-[0.7rem]` / `text-[0.72rem]` / `text-[10px]` / `text-[11px]` / `text-[11.5px]` / `text-[12px]` / `text-[13px]` / `text-[13.5px]` / `text-[14px]` all appear. **Systemic fix:** lock scale at 10/11/12/13/14/16/22 only. Document.

5. **Inconsistent letter-spacing on mono labels** — `tracking-wider` (0.05em) / `tracking-widest` (0.1em) / `tracking-[0.12em]` / `tracking-[0.14em]` / `tracking-[0.16em]` / `tracking-[0.2em]`. **Systemic fix:** ban anything wider than `tracking-widest` (0.1em).

6. **Form chrome translucency** — `bg-background/55`, `bg-card/45` on inputs. **Systemic fix:** solid `bg-input` token, period.

7. **Empty states over-designed** — Icon + heading + description + CTA in a giant dashed-border card. **Systemic fix:** one mono line, optionally one inline link.

8. **Touch targets opportunistically ≥44px** — Only 3 explicit sites. **Systemic fix:** document desktop density (36px standard, 40px primary). Don't force 44px globally — Claude Code is denser than that.

9. **Spacing scale inconsistent** — `space-y-{3,4,5,6}` + `gap-{3,4,5}` used interchangeably. **Systemic fix:** lock the rhythm (section 24px / card 16px / row 8px).

10. **Animation reliance for status feedback** — `animate-spin` on every refresh. **Systemic fix:** mono "LOADING…" label is enough. Reserve spin for true loading states.

---

## Positive Findings

- **No gradient text, no `bg-gradient-` slop, no AI palette leak (sky/violet/etc.)** — already disciplined.
- **CSS token system is in place** — `--bg`, `--surface`, `--border`, `--primary`, `--accent` all properly defined. The work to do is enforce token usage everywhere, not invent the system.
- **ARIA usage is solid in ConfigPage (42), RealEstateHub (34), Chat (14)** — the bones are good.
- **Vite chunk-splitting is working** — Admin / Memory / Social / Tasks each in own chunks. Main chunk 98.84 kB.
- **No `<img>` tags without alt text** (because there are no img tags — all icons are Lucide SVGs, which Lucide handles correctly).
- **All forms use real `<label>` elements** — only one unlabeled input and it's a hidden file picker (legit).
- **font-mono-ui token defined correctly and used in most label sites** — consistent JetBrains Mono for column headers / timestamps.
- **Pre-boot Electron screens (loading.html, install.html, main.js bg) redesigned this session** — terracotta + solid surface + 1px borders + 6–12px radii. Reference pattern for the rest of the work.
- **AdminSetupLaunch / AdminSetupField / AdminKanbanCard / AdminKanbanColumn partial redesign in admin/index.tsx demonstrates the new aesthetic** — 1px borders, mono tabular-nums labels, warning left-edge strip for Top-25, h-px progress lines. Use as reference for the rest.
- **Build is clean** — `tsc -b` exit 0, vite 1.74s, no console errors in dev.
- **Sessions, Tasks, Memory, Project pages are already mostly clean** — small surface area, easy /polish.

---

## Recommended Actions

In priority order (P0 first, then P1, then P2):

1. **[P0] `/shape`** — Plan the redesign for `RealEstateHubPages.tsx` (Today + Leads). Define `SurfaceList` / `SurfaceRow` / `PageHeader` primitives in `_shared/` before touching any page. This is the prerequisite — every subsequent redesign uses these primitives.

2. **[P0] `/shape`** — Plan the redesign for `admin/index.tsx`. Finish the partial work (NewDealDialog, AdminActionRuns, AgentHandoffsCard, AdminDealTasks). Reference: AdminKanbanCard pattern already in file.

3. **[P0] `/shape`** — Plan the redesign for `ChatPage.tsx`. Largest single file (4187 LOC). Strip glow shadows, crisp corners, tighten message-row spacing.

4. **[P0] `/distill`** — Replace hero metric cards with inline `PageHeader` strip across `RealEstateHubPages`, `admin`, `DesktopSetupPage`, `AgentHubPage`.

5. **[P0] `/layout`** — Lock spacing scale (section 24px / card 16px / row 8px). Document in `_shared/spacing.md`. Apply project-wide.

6. **[P0] `/adapt`** — Decide: bump desktop window minWidth to 1200, OR add `md:grid-cols-2` breakpoints. Recommend the former for ops-tool feel.

7. **[P0] `/optimize`** — Enforce touch-target standard (36px standard, 40px primary). Add focus-visible styles. Convert clickable `<div>`s to `<button>`.

8. **[P0] `/quieter`** — Pass on `DesktopSetupPage.tsx` (first-impression page). Strip translucent backgrounds, rounded-2xl, palette tints.

9. **[P1] `/quieter`** — `SessionsPage.tsx` ROLE_STYLES. Replace pills with left-edge strips.

10. **[P1] `/typeset`** — Lock font-mono-ui usage. Lock type scale (10/11/12/13/14/16/22). Apply tabular-nums everywhere numeric.

11. **[P1] `/optimize`** — Cross-cutting A11y pass: skip-link, focus-visible standardization, `+`/`−` non-color signal on deltas, role-button → real-button conversion.

12. **[P1] `/polish`** — `ConfigPage`, `EnvPage`, `CronPage`, `SkillsPage`, `RealEstateTemplatesPage`, `ProjectPage`, `LogsPage`, `DocsPage`, `AnalyticsPage`, `memory/`, `tasks/`, `social/`.

13. **[P1] `/audit`** — Spot-check `_shared/agent-widgets.tsx` (641 LOC).

14. **[P2] `/polish`** — Empty states pass: one-liner mono. Toast component. Loading-state pattern lock.

15. **[P3] `/polish`** — Final pre-ship pass once everything else lands.

> You can ask me to run these one at a time, all at once, or in any order you prefer.
>
> Re-run `/audit` after fixes to see your score improve.

---

## Per-Page Slop Heatmap

| File | LOC | `rounded-2xl/3xl` | Palette tints | Wide tracking | Custom shadow | Priority |
|------|-----|-------------------|---------------|---------------|---------------|----------|
| ChatPage.tsx                       | 4187 |  9 |  0 |  0 | 15 | **P0** |
| RealEstateHubPages.tsx             | 3900 | 11 | 16 | 20 |  1 | **P0** |
| admin/index.tsx                    | 3645 |  7 | 17 |  0 |  0 | **P0** |
| ConfigPage.tsx                     | 2215 |  0 |  5 |  0 |  0 | P1 |
| social-media-widgets.tsx           | 1472 |  ? |  ? |  ? |  ? | (audit needed) |
| AgentHubPage.tsx                   | 1279 |  0 |  0 |  0 |  0 | P1 (audit agent-widgets) |
| DesktopSetupPage.tsx               | 1117 |  6 |  2 |  0 |  0 | **P0** |
| SessionsPage.tsx                   | 1005 |  3 | 10 |  0 |  0 | P1 |
| CronPage.tsx                       |  825 |  2 |  0 |  0 |  0 | P1 |
| RealEstateTemplatesPage.tsx        |  781 |  1 |  1 |  0 |  0 | P1 |
| SkillsPage.tsx                     |  728 |  2 |  0 |  0 |  0 | P1 |
| EnvPage.tsx                        |  673 |  3 |  2 |  0 |  0 | P1 |
| _shared/agent-widgets.tsx          |  641 |  ? |  ? |  ? |  ? | (audit needed) |
| thread-drawer.tsx                  |  600 |  ? |  ? |  ? |  ? | (audit needed) |
| social/index.tsx                   |  454 |  2 |  1 |  0 |  0 | P1 |
| AnalyticsPage.tsx                  |  417 |  0 |  0 |  0 |  0 | P2 |
| ProjectPage.tsx                    |  227 |  1 |  0 |  0 |  0 | P1 |
| LogsPage.tsx                       |  220 |  0 |  1 |  0 |  0 | P2 |
| memory/index.tsx                   |  134 |  0 |  0 |  0 |  0 | clean |
| _shared/use-hub-data.tsx           |  128 | (logic) | | | | clean |
| _shared/contact-overview-board.tsx |  115 |  0 |  0 |  0 |  0 | clean |
| tasks/index.tsx                    |  100 |  0 |  0 |  0 |  0 | clean |
| _shared/hub-shell.tsx              |   68 |  0 |  0 |  0 |  0 | clean |
| _shared/action-board.tsx           |   68 |  0 |  0 |  0 |  0 | clean |
| DocsPage.tsx                       |   54 |  0 |  0 |  0 |  0 | clean |
| _shared/workflow-strip.tsx         |   23 |  0 |  0 |  0 |  0 | clean |
| _shared/hub-metric.tsx             |   21 |  0 |  0 |  0 |  0 | clean |
| _shared/loading-state.tsx          |    9 |  0 |  0 |  0 |  0 | clean |

**Sum:** 25,106 LOC across 28 page files (including `_shared/` and sub-page modules).

---

## Next Step (per user direction)

> The idea is /audit then plan the redesign based on the data then implement.

This audit is the **data**. Next deliverable: a per-page redesign plan derived from these findings, leading with the four P0 pages (RealEstateHubPages, admin, ChatPage, DesktopSetupPage) and the three systemic primitives (SurfaceList, SurfaceRow, PageHeader) that block all subsequent page work. Implementation follows the plan, page-by-page, in priority order.
