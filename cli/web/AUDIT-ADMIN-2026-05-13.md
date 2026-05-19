# Admin Page Audit — Per-Component

**File:** `src/pages/real-estate-hub/admin/index.tsx`
**LOC:** 3,645
**Date:** 2026-05-13
**Method:** Component-by-component pass with line-precise slop evidence.

---

## Component Inventory & Verdict

| # | Component | Lines | LOC | Slop hits | Verdict |
|---|-----------|-------|-----|-----------|---------|
| 1 | `AdminSetupField`           | 906–929   | 24  | 0 | ✅ Redesigned this session |
| 2 | `AdminSetupLaunch`          | 930–1314  | 385 | 1 | ✅ Mostly redesigned (1 leak at L1152) |
| 3 | `AdminKanbanCard`           | 1315–1397 | 83  | 0 | ✅ Redesigned this session |
| 4 | `AdminPhaseSummary`         | 1398–1469 | 72  | 5 | ⚠️ Pill spam — 5 translucent palette pills (P0) |
| 5 | `AdminKanbanColumn`         | 1470–1536 | 67  | 0 | ✅ Redesigned this session |
| 6 | `AdminKanbanSwimlane`       | 1537–1583 | 47  | 0 | ✅ Clean |
| 7 | `AdminTop25Strip`           | 1584–1636 | 53  | 4 | ⚠️ Warning glow chrome (P1) |
| 8 | `AdminCardStageSection`     | 1637–1771 | 135 | 4 | ⚠️ `rounded-xl bg-background/30/35` (P1) |
| 9 | `AdminCardConditionsSection`| 1772–1857 | 86  | 1 | ⚠️ Minor (P2) |
| 10| `AdminCardSourceSection`    | 1858–1916 | 59  | 1 | ⚠️ Section card (P2) |
| 11| `AdminDealContextSection`   | 1917–2391 | 475 | 12 | 🛑 **Worst component in file** (P0) |
| 12| `AdminCardDetailPanel`      | 2392–2697 | 306 | 6 | 🛑 Modal chrome + primary glow banner (P0) |
| 13| `NewDealDialog`             | 2698–3330 | 633 | 14 | 🛑 **Largest + heavy slop** (P0) |
| 14| `AdminKanbanBoard`          | 3331–3525 | 195 | 5 | ⚠️ Board chrome + status bar (P1) |
| 15| `RealEstateAdminPage`       | 3526–3645 | 120 | 0 | ✅ Page wrapper clean |

**Totals:** 53 slop hits, concentrated in 4 components (AdminDealContextSection, NewDealDialog, AdminCardDetailPanel, AdminPhaseSummary).

---

## P0 — Blocking

### 1. `AdminDealContextSection` (1917–2391) — 12 slop hits in 475 lines

This is the **right-rail details panel** for a selected deal — appraisal, financing, conditions, dates, agents, etc. Currently 10 sibling `rounded-lg border-border/45 bg-background/30 px-3 py-2` cards stacked vertically — pure card-stack AI slop.

**Evidence:**
- L1997: section wrapper `rounded-xl border-border/60 bg-background/35 px-3 py-3` (also at L1863)
- L2018: `rounded-lg border-warning/35 bg-warning/10` warning callout
- L2024: `rounded-lg border-dashed border-border/50 bg-background/25` empty state
- L2032, **2098, 2112, 2127, 2141, 2161, 2189, 2208, 2226, 2251**: 10× `rounded-lg border-border/45 bg-background/30 px-3 py-2` field-group cards

**Fix:**
Replace the 10 stacked cards with a single `<dl>` definition-list inside the section, using `divide-y divide-border` rows. Each row: 10px mono uppercase label on left, tabular-nums value on right. Result: ~50% less vertical space, scannable like a config readout.

```tsx
<section className="border-t border-border pt-4">
  <h3 className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground">
    Deal context
  </h3>
  <dl className="mt-3 divide-y divide-border">
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="font-mono-ui text-[11px] uppercase tracking-wider text-muted-foreground">Appraisal</dt>
      <dd className="text-[13px] tabular-nums text-foreground">{value}</dd>
    </div>
    {/* repeat 9 more times */}
  </dl>
</section>
```

### 2. `NewDealDialog` (2698–3330) — 14 slop hits in 633 lines

The **"create deal" modal**. 633 lines is itself a smell — should be split into steps. Slop is concentrated in form chrome and side-toggle buttons.

**Evidence:**
- L2944: `bg-background/60 backdrop-blur-sm` overlay — *legit for modal, keep*
- L2951: `bg-card shadow-2xl sm:rounded-2xl sm:border-border/60` panel — strip the `2xl`, use `rounded-md`, lose `shadow-2xl`
- L2985–2986: side-toggle (listing/buyer) selected state `border-primary bg-primary/10 text-foreground` vs unselected `border-border/60 bg-background/40 text-muted-foreground` — replace with mono labels + 2px-left primary border on selected, no translucent fill
- L3022, 3025, 3029, 3070, 3075, 3080: 6× `font-mono-ui rounded border-border/{50,60} bg-background/{40,50} px-1.5 py-0.5 text-[0.58rem]` chips — these are field hints/prefills. Convert to inline mono text, no chip chrome
- L3042: `rounded-lg border-primary/40 bg-primary/5` primary banner — strip the glow, use `border-t border-primary pt-3` instead
- L3087: `border-t border-primary/20` — primary-tinted divider, use `border-t border-border`
- L3115: `rounded-lg border-border/40 bg-background/50` dropdown — convert to flat `border border-border bg-popover`
- L3121: hover state `hover:bg-background/80` — use `hover:bg-muted`
- L3185: `rounded-lg border-border/40 bg-background/30 px-3 py-3` section card — convert to `border-t border-border pt-4`
- L3310: `rounded-lg border-destructive/40 bg-destructive/5` error — keep red border, drop the `/5` fill, use mono uppercase label

**Fix priorities:**
1. Split `NewDealDialog` into 3–4 sequential steps (basics → parties → dates → review). Each step under 200 lines.
2. Flatten field-hint chips to inline mono.
3. Replace primary-tinted banners with `border-t border-primary` strips.
4. Strip all `bg-background/{30..60}` translucent surfaces in favor of `bg-popover` / `bg-card` solid.

### 3. `AdminCardDetailPanel` (2392–2697) — 6 slop hits in 306 lines

The **side-sheet** that opens when you click a kanban card. Same overlay-modal pattern as NewDealDialog plus a primary-tinted action bar.

**Evidence:**
- L2554: `bg-background/60 backdrop-blur-sm` overlay — *legit, keep*
- L2561: `bg-card shadow-2xl sm:rounded-2xl sm:border-border/60` panel — strip `2xl` corners, lose `shadow-2xl`
- L2572: `rounded-full border-warning/40 bg-warning/10 px-1.5 py-0.5` warning pill — replace with mono uppercase label `STALE` + left-edge warning strip
- L2608: close button `hover:bg-background/60` — use `hover:bg-muted`
- L2616: `border-b border-border/60 bg-primary/5 px-4 py-2.5` — **primary glow action bar**. Strip the `/5` fill, keep border. Action bar should be solid `bg-muted` or `bg-card` with left-edge `border-l-2 border-primary`.
- L2628: action button `border-primary/40 bg-primary/10 hover:bg-primary/20` mono label — convert to standard primary button (`bg-primary text-primary-foreground`) since this is the action bar's primary CTA

### 4. `AdminPhaseSummary` (1398–1469) — 5 palette pills in 72 lines

The mini badge row inside each kanban card showing **stage automation** (agent skill + background skills + approval gate). Currently 4 different colored pill types (primary/success/warning/neutral) — reads like a CI status dashboard, not an ops tool.

**Evidence:**
- L1419: `border-primary/25 bg-primary/10 text-primary` agent pill
- L1428: `border-border/50 bg-background/35 text-muted-foreground` "task list" placeholder pill
- L1438: `border-success/25 bg-success/10 text-success` background skill pill
- L1447: `border-warning/30 bg-warning/10 text-warning` approval gate pill
- L1454: `border-border/45 bg-background/30 text-muted-foreground` "+N hidden" pill

**Fix:**
Replace pill row with a single inline mono line, color-coded by left-edge dot (1px square, not a circle):

```
■ agent.followup  ■ cron.scoring  ■ approval  +2
```

Single line, 11px mono lowercase, no rounded-full backgrounds. Color is on the small left-edge marker only. Tooltip for full skill name.

---

## P1 — Major

### 5. `AdminKanbanBoard` (3331–3525) — Status bar + empty/error chrome

**Evidence:**
- L3418: status bar `rounded-2xl border-border/50 bg-card/30 px-3 py-2` — convert to `border-b border-border bg-background` flush strip, no rounded corners
- L3430: dev-fallback warning pill — convert to inline mono uppercase + dot
- L3456: empty-state `rounded-2xl border-dashed border-border/60 bg-card/25` — convert to bare mono line + button
- L3601: `rounded-2xl border-border/50 bg-card/30` (likely a footer/note) — convert to `border-t border-border pt-4`
- L3607: `rounded-2xl border-warning/35 bg-warning/10` error/warning — convert to mono `border-l-2 border-warning pl-3` strip

### 6. `AdminTop25Strip` (1584–1636) — Warning glow chrome

This strip flags "Top 25 deals at risk." Currently entire strip is wrapped in a warning glow:

**Evidence:**
- L1597: `rounded-2xl border-warning/35 bg-warning/5 p-3` — wrap the whole strip in warning paint
- L1606: warning pill `rounded-full border-warning/40 bg-warning/10`
- L1616: empty state `rounded-xl border-dashed border-border/40 bg-background/20`
- L1619: warning pill inside empty state

**Fix:**
- Outer: bare `border-t border-border pt-3` strip with a `border-l-2 border-warning pl-3` left-edge accent only
- Header: mono uppercase `TOP 25 — AT RISK` label + count tabular-nums
- Cards inside: already redesigned (AdminKanbanCard has left-edge warning strip per session work)
- Empty state: one mono line, no dashed border

### 7. `AdminCardStageSection` (1637–1771) — Stage picker cards

The stage-switcher inside the detail panel — each stage option is a `rounded-xl` clickable card.

**Evidence:**
- L1666: stage option `rounded-xl border bg-background/30`
- L1673: button `rounded-xl focus:ring-2 focus:ring-primary/30`
- L1725: nested `rounded-lg border-border/45 bg-background/35`
- L1745: row hover `hover:bg-background/60`

**Fix:**
- Convert stage options from rounded cards to `divide-y divide-border` rows
- Active stage: 2px left primary border + mono uppercase label
- Inactive: bare row with hover `bg-muted/50`
- No nested rounded cards inside the section

### 8. `AdminCardSourceSection` (1858–1916)

**Evidence:**
- L1863: `rounded-xl border-border/60 bg-background/35 px-3 py-3` section wrapper

**Fix:** Replace section card with `border-t border-border pt-3` flush section with mono eyebrow.

### 9. `AdminCardConditionsSection` (1772–1857)

**Evidence:**
- L1835: condition row `flex min-h-11 items-center rounded-lg hover:bg-background/60 focus:ring-2 focus:ring-primary/30`

**Fix:** Drop `rounded-lg` (use `rounded-sm`), replace `hover:bg-background/60` with `hover:bg-muted`. Keep `min-h-11` for touch target.

---

## P2 — Minor

### 10. `AdminSetupLaunch` L1152 — error/success border-tint leak

**Evidence:**
```
error ? "border-destructive/40" : "border-success/40"
```

**Fix:** Use solid `border-destructive` / `border-success` (no `/40` opacity).

---

## Patterns Specific to Admin

### Pattern A: Section-as-card vs section-as-divider
Admin uses `rounded-xl border bg-background/35` for **every** content section (5+ sites). Should use `border-t border-border pt-4` with a 10px mono uppercase eyebrow — flush sections, no card chrome.

### Pattern B: Pill-as-status vs label-as-status
Admin uses `rounded-full border-{palette}/X bg-{palette}/Y` for **every** status indicator (15+ sites). Should use mono uppercase label + left-edge color dot OR 2px left-edge color strip on the parent row.

### Pattern C: Translucent form chrome
NewDealDialog uses `bg-background/40`, `bg-background/50`, `bg-background/60` interchangeably for field hints, dropdowns, and surfaces. Should be solid `bg-popover` / `bg-input` / `bg-muted` tokens.

### Pattern D: Primary-tinted callouts
Banner action bars and primary-step callouts use `bg-primary/5` or `bg-primary/10` glow fills (L2616, L3042). Should be solid surface + `border-l-2 border-primary` left strip, no fill.

### Pattern E: `shadow-2xl` on modals
Both NewDealDialog (L2951) and AdminCardDetailPanel (L2561) use `shadow-2xl`. Ops-tool aesthetic: 1px border, no shadow, optional 1px `inset-shadow` for depth.

---

## Already-Shipped Pattern References

Use these for the redesign — they are the standard now:

- **`AdminKanbanCard` (1315–1397)** — 1px borders, mono tabular-nums, warning left-edge strip for Top-25, h-px progress lines, hover `border-foreground/40`
- **`AdminKanbanColumn` (1470–1536)** — sticky header, mono stage label `01`/`02`/`03` zero-padded, divide-y rows, bare empty state
- **`AdminSetupField` (906–929)** — 12px label, h-9 input, `bg-background` solid, `rounded-md` corners, `focus:ring-1 focus:ring-primary/30`
- **`AdminSetupLaunch` (930–1314)** — inline mono progress header, no hero card, divide-y blockers list, section borders not card chrome

---

## Recommended Sequence (Admin Only)

In order, with estimated LOC delta:

1. **[P0] `AdminPhaseSummary`** (72 LOC → ~50 LOC) — Pill row → mono inline line. ~30 min.
2. **[P0] `AdminCardDetailPanel`** (306 LOC → ~270 LOC) — Strip `shadow-2xl`, drop `rounded-2xl`, flatten action bar, convert warning pill to mono+strip. ~45 min.
3. **[P0] `AdminDealContextSection`** (475 LOC → ~350 LOC) — 10 stacked cards → `divide-y dl`. Biggest single win. ~60 min.
4. **[P0] `NewDealDialog`** (633 LOC → ~450 LOC) — Strip modal chrome, flatten field-hint chips, convert step callouts. Optional: split into 3 step components. ~90 min.
5. **[P1] `AdminKanbanBoard`** (195 LOC) — Status bar, empty state, error chrome flush. ~30 min.
6. **[P1] `AdminTop25Strip`** (53 LOC) — Strip warning wrap, use left-edge accent. ~20 min.
7. **[P1] `AdminCardStageSection`** (135 LOC) — Cards → divide-y rows. ~30 min.
8. **[P1] `AdminCardSourceSection`** (59 LOC) — Section card → flush section. ~15 min.
9. **[P1] `AdminCardConditionsSection`** (86 LOC) — `rounded-lg` → `rounded-sm`, hover token. ~15 min.
10. **[P2] `AdminSetupLaunch` L1152** — Solid border colors. ~5 min.

**Total estimate:** ~5–6 hours of focused work to bring admin to parity with the already-shipped kanban card/column pattern.

---

## Verdict

Admin is **40% redesigned** — the kanban column + card + setup form are at parity with the Claude Code target. The remaining **60%** (detail panel, new-deal modal, deal-context rail, phase summary pills, board chrome) is still AI-default.

The good news: the patterns to apply are all already proven in this file. The fix is mechanical, not exploratory — strip rounded-2xl/shadow-2xl/translucent palette glow and replace with 1px borders + divide-y + mono labels + left-edge color strips.
