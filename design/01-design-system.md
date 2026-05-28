# Elevate: Design System
CSS tokens, theme definitions, UI primitives.

---
## `src/index.css`
```css
/* Geist Sans — primary UI font, matches Claude Code dashboard aesthetic.
   Geist Mono — used by .font-mono-ui for structural labels (column headers,
   timestamps, key shortcuts, status codes). MUST stay first so CSS @import
   rules precede @layer declarations from Tailwind. */
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap');

@import 'tailwindcss';
@import '@nous-research/ui/styles/globals.css';

/* Scan the published design-system bundle so its utility classes survive
   Tailwind's JIT purge. */
@source '../node_modules/@nous-research/ui/dist';

/* ------------------------------------------------------------------ */
/* JetBrains Mono — bundled for the embedded TUI (/chat tab).          */
/* Gives the terminal a proper monospace font even on systems where    */
/* the user doesn't have one installed locally; xterm.js picks it up   */
/* via ChatPage's `fontFamily` option.                                 */
/* Apache-2.0.                                                         */
/* ------------------------------------------------------------------ */

@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts-terminal/JetBrainsMono-Regular.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url('/fonts-terminal/JetBrainsMono-Bold.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: italic;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts-terminal/JetBrainsMono-Italic.woff2') format('woff2');
}

/* ------------------------------------------------------------------ */
/* Elevate - design-system tokens for the default dark palette.        */
/* ThemeProvider rewrites the same vars when the user switches light.  */
/* ------------------------------------------------------------------ */

:root {
  /* Defaults for the dark dashboard theme; ThemeProvider rewrites them as
     inline styles when a user switches to light. */
  --foreground: color-mix(in srgb, #ffffff 0%, transparent);
  --foreground-base: #ffffff;
  --foreground-alpha: 0;
  --midground: color-mix(in srgb, #ececec 100%, transparent);
  --midground-base: #ececec;
  --midground-alpha: 1;
  --background: color-mix(in srgb, #1a1b1a 100%, transparent);
  --background-base: #1a1b1a;
  --background-alpha: 1;

  /* Consumed by <Backdrop />; also theme-switchable. */
  --warm-glow: rgba(217, 119, 87, 0.14);
  --noise-opacity-mul: 0;

  /* Typography tokens — rewritten by ThemeProvider. Geist Sans is the primary
     UI font (Claude Code dashboard aesthetic); Geist Mono is used for all
     structural labels via the .font-mono-ui utility class. */
  --theme-font-sans: "Geist", "Inter", -apple-system, BlinkMacSystemFont,
    "Segoe UI Variable", "Segoe UI", system-ui, "Helvetica Neue", Arial,
    sans-serif;
  --theme-font-mono: "Geist Mono", "JetBrains Mono", ui-monospace, "SF Mono",
    "Cascadia Mono", Menlo, Consolas, monospace;
  --theme-font-display: var(--theme-font-sans);
  --theme-base-size: 15px;
  --theme-line-height: 1.55;
  --theme-letter-spacing: 0;

  /* The upstream UI kit ships decorative display utilities
     (Mondwest/Rules/Courier). Elevate keeps the chrome clean and sans-serif;
     code/log surfaces still opt into --theme-font-mono explicitly. */
  --font-sans: var(--theme-font-sans);
  --font-mondwest: var(--theme-font-sans);
  --font-rules-compressed: var(--theme-font-sans);
  --font-rules-expanded: var(--theme-font-sans);
  --font-courier: var(--theme-font-sans);

  /* Layout tokens. */
  --radius: 0.375rem;
  --theme-radius: 0.375rem;
  --theme-spacing-mul: 1;
  --theme-density: comfortable;

  /* Shared chat-shell tokens. These derive from the active theme so the
     ChatGPT-style workspace stays coherent in both dark and light modes. */
  --chat-bg: var(--background-base);
  --chat-surface: color-mix(in srgb, var(--midground-base) 4%, var(--background-base));
  --chat-surface-strong: color-mix(in srgb, var(--midground-base) 7%, var(--background-base));
  --chat-surface-soft: color-mix(in srgb, var(--midground-base) 2%, var(--background-base));
  --chat-border: color-mix(in srgb, var(--midground-base) 14%, transparent);
  --chat-border-strong: color-mix(in srgb, var(--midground-base) 22%, transparent);
  --chat-text: var(--midground);
  --chat-muted: color-mix(in srgb, var(--midground-base) 58%, transparent);
  --chat-muted-strong: color-mix(in srgb, var(--midground-base) 72%, transparent);
  --chat-user: color-mix(in srgb, #0b6bff 14%, transparent);
  --chat-user-text: color-mix(in srgb, #ffffff 90%, transparent);
  --chat-accent: var(--color-primary, #D97757);
  --chat-accent-soft: color-mix(in srgb, var(--chat-accent) 18%, var(--background-base));
  --chat-success: var(--color-success, #44c487);
  --chat-warning: var(--color-warning, #f3bf67);
  --chat-danger: var(--color-destructive, #ff827d);
  --sidebar-bg: color-mix(in srgb, var(--midground-base) 5%, var(--background-base));
  --sidebar-row: color-mix(in srgb, var(--midground-base) 4%, transparent);
  --sidebar-row-hover: color-mix(in srgb, var(--midground-base) 8%, transparent);
  --sidebar-row-active: color-mix(in srgb, var(--color-primary, #D97757) 15%, var(--midground-base) 7%);
  --sidebar-border: color-mix(in srgb, var(--midground-base) 10%, transparent);
  --sidebar-text: #ffffff;
  --sidebar-text-strong: #ffffff;
  --sidebar-text-active: #ffffff;
  --sidebar-text-muted: color-mix(in srgb, #ffffff 72%, transparent);
  --sidebar-text-faint: color-mix(in srgb, #ffffff 58%, transparent);
  --sidebar-icon: #ffffff;
  --sidebar-icon-muted: color-mix(in srgb, #ffffff 66%, transparent);
  --sidebar-logo-bg: color-mix(in srgb, var(--background-base) 72%, var(--midground-base) 28%);
  --sidebar-logo-border: color-mix(in srgb, var(--midground-base) 14%, transparent);
  --ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
  --ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
}

/* Theme tokens cascade into the document root so every descendant inherits
   the font stack, base size, and letter spacing without explicit calls. */
html {
  font-family: var(--theme-font-sans);
  font-size: var(--theme-base-size);
  line-height: var(--theme-line-height);
  letter-spacing: var(--theme-letter-spacing);
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
}

body {
  font-family: var(--theme-font-sans);
  min-height: 0;
  height: 100%;
  margin: 0;
  overflow: hidden;
}

code, kbd, pre, samp, .font-mono, .font-mono-ui {
  font-family: var(--theme-font-mono);
}

html .font-mondwest,
html .font-expanded,
html .font-compressed,
html .font-courier {
  font-family: var(--theme-font-sans);
}

/* Structural labels — column headers, timestamps, key shortcuts, status
   codes. Claude Code dashboard aesthetic: micro-text in mono, full-width sans
   above. Numbers stay tabular for column alignment. */
.font-mono-ui {
  font-family: var(--theme-font-mono);
  font-feature-settings: "tnum" on, "lnum" on;
}

/* Shared dashboard page skin. The chat view defines the strongest visual
   language, so non-chat pages borrow the same soft panels, muted separators,
   and native-feeling controls. */
.elevate-page-shell {
  --page-panel: var(--chat-surface);
  --page-panel-soft: var(--chat-surface-soft);
  --page-panel-strong: var(--chat-surface-strong);
  --page-border: var(--chat-border);
  --page-border-strong: var(--chat-border-strong);
  color: var(--chat-text);
}

.elevate-page-shell [class*="border-border"] {
  border-color: var(--page-border);
}

.elevate-page-shell table {
  border-collapse: separate;
  border-spacing: 0;
}

.elevate-page-shell thead tr,
.elevate-page-shell tbody tr {
  border-color: var(--page-border);
}

.elevate-page-shell textarea {
  border-radius: 0.375rem;
  border-color: var(--page-border-strong);
  background: color-mix(in srgb, var(--midground-base) 3%, var(--background-base));
}

.elevate-page-shell pre {
  border-radius: 0.375rem;
  border-color: var(--page-border);
  background: color-mix(in srgb, var(--midground-base) 3%, var(--background-base));
  color: var(--chat-text);
}

.elevate-page-shell code {
  border-radius: 0.25rem;
  background: color-mix(in srgb, var(--midground-base) 6%, var(--background-base));
  /* Inline code chips were rendering near-black on near-black because the
     foreground color inherited from a dimmed parent (e.g. text-muted-foreground
     on a setup-step list). Force a readable contrast via the canonical
     chat text token so chips like `chat:write` stay legible everywhere. */
  color: var(--chat-text);
  padding-inline: 0.35em;
  padding-block: 0.12em;
}

.elevate-page-shell pre code {
  border-radius: 0;
  background: transparent;
  color: inherit;
  padding: 0;
}

.elevate-docs-shell iframe {
  border-radius: 0.5rem;
  border-color: var(--page-border-strong);
}

/* Density: scale the shadcn spacing utilities via a multiplier. The DS
   components use `p-N` / `gap-N` / `space-*` classes which resolve against
   Tailwind's spacing scale; multiplying `--spacing` at :root scales them
   all proportionally in Tailwind v4. */
@theme inline {
  --spacing: calc(0.25rem * var(--theme-spacing-mul, 1));
}

#root {
  min-height: 0;
  height: 100%;
  max-height: 100%;
  overflow: hidden;
}

/* Bump `small` and `code` to readable dashboard sizes. */
small { font-size: 1.0625rem; }
code { font-size: 0.875rem; }

/* Shadcn-compat tokens.
   The dashboard's page code predates the Nous DS and uses shadcn-style
   utility classes (bg-card, text-muted-foreground, border-border, etc.)
   extensively. Rather than rewrite every call site, we expose those
   tokens on top of the Nous palette so classes continue to resolve. */
@theme inline {
  /* Remap foreground to midground so `text-foreground` / `bg-foreground`
     stay visible — in LENS_0, `--foreground` itself has alpha 0. */
  --color-foreground: var(--midground);

  --color-card: color-mix(in srgb, var(--midground-base) 5%, var(--background-base));
  --color-card-foreground: var(--midground);
  --color-primary: #D97757;
  --color-primary-foreground: var(--background-base);
  --color-secondary: color-mix(in srgb, var(--midground-base) 9%, var(--background-base));
  --color-secondary-foreground: var(--midground);
  --color-muted: color-mix(in srgb, var(--midground-base) 8%, var(--background-base));
  --color-muted-foreground: color-mix(in srgb, var(--midground-base) 55%, transparent);
  --color-accent: color-mix(in srgb, var(--color-primary) 14%, var(--background-base));
  --color-accent-foreground: var(--midground);
  --color-destructive: #ff827d;
  --color-destructive-foreground: var(--background-base);
  --color-success: #44c487;
  --color-warning: #f3bf67;
  --color-border: #2a2c2a;
  --color-input: #2a2c2a;
  --color-ring: #D97757;
  --color-popover: color-mix(in srgb, var(--midground-base) 6%, var(--background-base));
  --color-popover-foreground: var(--midground);

  --radius-sm: calc(var(--theme-radius) - 4px);
  --radius-md: calc(var(--theme-radius) - 2px);
  --radius-lg: var(--theme-radius);
  --radius-xl: calc(var(--theme-radius) + 4px);
}


/* Toast animations used by `components/Toast.tsx`. */
@keyframes toast-in {
  from { opacity: 0; transform: translateX(16px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes toast-out {
  from { opacity: 1; transform: translateX(0); }
  to   { opacity: 0; transform: translateX(16px); }
}

/* Generic fade + dialog entrance used by popovers and confirm dialogs. */
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes dialog-in {
  from { opacity: 0; transform: translateY(4px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes elevate-route-in {
  from {
    opacity: 0.72;
    transform: translate3d(0, 7px, 0) scale(0.998);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0) scale(1);
  }
}

@keyframes pack-unlock-rise {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes pack-unlock-save {
  0%   { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-success) 28%, transparent); }
  60%  { box-shadow: 0 0 0 8px color-mix(in srgb, var(--color-success) 0%, transparent); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-success) 0%, transparent); }
}

@keyframes elevate-shimmer-sweep {
  from { transform: translateX(-120%); }
  to   { transform: translateX(240%); }
}

@keyframes memory-node-enter {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.86);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes memory-edge-flow {
  from { stroke-dashoffset: 28; }
  to   { stroke-dashoffset: 0; }
}

@keyframes memory-halo-breathe {
  0%, 100% { opacity: 0.34; transform: scale(0.96); }
  50%      { opacity: 0.58; transform: scale(1.08); }
}

@keyframes onboarding-rise {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes onboarding-exit {
  from { opacity: 1; transform: translateY(0) scale(1); }
  to   { opacity: 0; transform: translateY(-14px) scale(0.992); }
}

@keyframes onboarding-aurora {
  0%, 100% { background-position: 0% 50%; }
  50%      { background-position: 100% 50%; }
}

.onboarding-overlay {
  background:
    radial-gradient(circle at 22% 18%, color-mix(in srgb, var(--color-primary) 18%, transparent) 0%, transparent 42%),
    radial-gradient(circle at 78% 82%, color-mix(in srgb, var(--color-primary) 12%, transparent) 0%, transparent 48%),
    var(--background-base);
}

.onboarding-aurora-bg {
  background:
    linear-gradient(120deg,
      color-mix(in srgb, var(--color-primary) 8%, transparent) 0%,
      transparent 35%,
      color-mix(in srgb, var(--color-primary) 6%, transparent) 70%,
      transparent 100%);
  background-size: 220% 220%;
  animation: onboarding-aurora 9s ease-in-out infinite;
}

.onboarding-rise {
  animation: onboarding-rise 600ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.onboarding-rise-delay-1 {
  animation: onboarding-rise 600ms cubic-bezier(0.22, 1, 0.36, 1) 160ms both;
}

.onboarding-rise-delay-2 {
  animation: onboarding-rise 600ms cubic-bezier(0.22, 1, 0.36, 1) 320ms both;
}

.onboarding-rise-delay-3 {
  animation: onboarding-rise 600ms cubic-bezier(0.22, 1, 0.36, 1) 480ms both;
}

.onboarding-exit {
  animation: onboarding-exit 380ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
}

@keyframes onboarding-step-check {
  from { transform: scale(0.6); opacity: 0; }
  to   { transform: scale(1);   opacity: 1; }
}
.onboarding-step-check {
  animation: onboarding-step-check 380ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes onboarding-step-pulse {
  0%, 100% { opacity: 0.55; transform: scale(0.92); }
  50%      { opacity: 1;    transform: scale(1.0); }
}
.onboarding-step-pulse {
  animation: onboarding-step-pulse 1.4s ease-in-out infinite;
}

@keyframes onboarding-coach-slide {
  from { opacity: 0; transform: translateY(24px); }
  to   { opacity: 1; transform: translateY(0); }
}
.onboarding-coach {
  animation: onboarding-coach-slide 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.memory-constellation {
  contain: layout paint;
}

.pack-unlock-card {
  animation: pack-unlock-rise 150ms ease-out both;
}

.pack-unlock-check {
  border-color: color-mix(in srgb, var(--color-primary) 38%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--background-base));
}

.pack-unlock-check.is-saved {
  animation: pack-unlock-save 480ms ease-out;
}

.pack-step-enter {
  animation: dialog-in 260ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.elevate-route-transition {
  animation: elevate-route-in 180ms var(--ease-out-quart) both;
}

@media (prefers-reduced-motion: reduce) {
  .pack-unlock-card,
  .pack-unlock-check.is-saved,
  .pack-step-enter,
  .elevate-route-transition {
    animation: none !important;
  }
}

.memory-constellation::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--background-base) 74%, transparent),
      transparent 18%,
      transparent 78%,
      color-mix(in srgb, var(--background-base) 70%, transparent)
    );
}

.memory-constellation-edge {
  pointer-events: none;
  transition:
    opacity 180ms cubic-bezier(0.25, 1, 0.5, 1),
    stroke 180ms cubic-bezier(0.25, 1, 0.5, 1),
    stroke-width 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.memory-constellation-edge-flow {
  stroke-dasharray: 20 8;
  animation: memory-edge-flow 2.8s linear infinite;
  animation-delay: var(--memory-edge-delay, 0ms);
}

.memory-constellation-edge-active {
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--color-primary) 38%, transparent));
}

.memory-constellation-node {
  cursor: pointer;
  outline: none;
  transform-box: fill-box;
  transform-origin: center;
  animation: memory-node-enter 440ms cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: var(--memory-node-delay, 0ms);
}

.memory-constellation-halo {
  opacity: 0.42;
  pointer-events: none;
  transform-box: fill-box;
  transform-origin: center;
  transition:
    opacity 180ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.memory-constellation-ring,
.memory-constellation-core {
  transition:
    filter 180ms cubic-bezier(0.25, 1, 0.5, 1),
    opacity 180ms cubic-bezier(0.25, 1, 0.5, 1),
    r 180ms cubic-bezier(0.25, 1, 0.5, 1),
    stroke-width 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.memory-constellation-ring {
  pointer-events: none;
}

.memory-constellation-node.is-linked .memory-constellation-halo {
  opacity: 0.64;
}

.memory-constellation-node.is-linked .memory-constellation-ring {
  opacity: 0.86;
}

.memory-constellation-node.is-linked .memory-constellation-core,
.memory-constellation-node.is-pinned .memory-constellation-core {
  filter: drop-shadow(0 0 7px color-mix(in srgb, var(--color-primary) 26%, transparent));
}

.memory-constellation-node.is-muted .memory-constellation-halo,
.memory-constellation-node.is-muted .memory-constellation-ring {
  opacity: 0.1;
}

.memory-constellation-node.is-active .memory-constellation-halo,
.memory-constellation-node:focus-visible .memory-constellation-halo {
  animation: memory-halo-breathe 1.8s cubic-bezier(0.25, 1, 0.5, 1) infinite;
}

.memory-constellation-node:focus-visible .memory-constellation-core {
  filter: drop-shadow(0 0 8px color-mix(in srgb, var(--color-primary) 42%, transparent));
}

.memory-constellation-label {
  paint-order: stroke;
  stroke: color-mix(in srgb, var(--background-base) 92%, transparent);
  stroke-width: 4px;
  stroke-linejoin: round;
  font-family: var(--theme-font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0;
  opacity: 0.84;
  pointer-events: none;
}

.memory-constellation-edge-label {
  paint-order: stroke;
  stroke: color-mix(in srgb, var(--background-base) 88%, transparent);
  stroke-width: 3px;
  stroke-linejoin: round;
  font-family: var(--theme-font-sans);
  font-size: 9px;
  font-weight: 500;
  opacity: 0.72;
  pointer-events: none;
}

.memory-constellation-hulls polygon {
  transition: opacity 220ms cubic-bezier(0.25, 1, 0.5, 1);
}

.elevate-thinking-shimmer {
  position: relative;
  overflow: hidden;
  background: color-mix(in srgb, var(--chat-surface-strong) 74%, transparent);
}

.elevate-thinking-shimmer::after {
  content: '';
  position: absolute;
  inset-block: 0;
  left: 0;
  width: 42%;
  background: linear-gradient(
    90deg,
    transparent,
    color-mix(in srgb, var(--chat-muted-strong) 18%, transparent),
    transparent
  );
  animation: elevate-shimmer-sweep 1.35s ease-in-out infinite;
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .elevate-thinking-shimmer::after {
    animation: none;
    display: none;
  }

  .memory-constellation-edge-flow,
  .memory-constellation-node,
  .memory-constellation-node.is-active .memory-constellation-halo,
  .memory-constellation-node:focus-visible .memory-constellation-halo {
    animation: none;
  }

  .memory-constellation-edge,
  .memory-constellation-halo,
  .memory-constellation-ring,
  .memory-constellation-core {
    transition: none;
  }
}

/* Hide scrollbar utility — used by the header's overflow-x nav row. */
.scrollbar-none {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.scrollbar-none::-webkit-scrollbar {
  display: none;
}

/* Plus-lighter blend used by logos/titles for a subtle glow. */
.blend-lighter {
  mix-blend-mode: plus-lighter;
}

/* Monospace stack for dense data readouts, code, and terminal-adjacent UI. */
.font-mono-ui {
  font-family: var(--theme-font-mono);
}

/* Subtle grain overlay for badges. */
.grain {
  position: relative;
}
.grain::after {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0.12;
  pointer-events: none;
  background: repeating-conic-gradient(currentColor 0% 25%, #0000 0% 50%) 0 0 /
    2px 2px;
}

```

---
## `src/themes/types.ts`
```ts
/**
 * Dashboard theme model.
 *
 * Themes customise three orthogonal layers:
 *
 *   1. `palette`       — the 3-layer color triplet (background/midground/
 *                         foreground) + warm-glow + noise opacity. The
 *                         design-system cascade in `src/index.css` derives
 *                         every shadcn-compat token (card, muted, border,
 *                         primary, etc.) from this triplet via `color-mix()`.
 *   2. `typography`    — font families, base font size, line height,
 *                         letter spacing. An optional `fontUrl` is injected
 *                         as `<link rel="stylesheet">` so self-hosted and
 *                         Google/Bunny/etc-hosted fonts both work.
 *   3. `layout`        — corner radius and density (spacing multiplier).
 *
 * Plus an optional `colorOverrides` escape hatch for themes that want to
 * pin specific shadcn tokens to exact values (e.g. a pastel theme that
 * needs a softer `destructive` red than the derived default).
 */

/** A color layer: hex base + alpha (0–1). */
export interface ThemeLayer {
  alpha: number;
  hex: string;
}

export interface ThemePalette {
  /** Deepest canvas color (typically near-black). */
  background: ThemeLayer;
  /** Primary text + accent. Most UI chrome reads this. */
  midground: ThemeLayer;
  /** Top-layer highlight. In LENS_0 this is white @ alpha 0 — invisible by
   *  default but still drives `--color-ring`-style accents. */
  foreground: ThemeLayer;
  /** Warm vignette color for <Backdrop />, as an rgba() string. */
  warmGlow: string;
  /** Scalar multiplier (0–1.2) on the noise overlay. Lower for softer themes
   *  like Mono and Rosé, higher for grittier themes like Cyberpunk. */
  noiseOpacity: number;
}

export interface ThemeTypography {
  /** CSS font-family stack for sans-serif body copy. */
  fontSans: string;
  /** CSS font-family stack for monospace / code blocks. */
  fontMono: string;
  /** Optional display/heading font stack. Falls back to `fontSans`. */
  fontDisplay?: string;
  /** Optional external stylesheet URL (e.g. Google Fonts, Bunny Fonts,
   *  self-hosted .woff2 @font-face sheet). Injected as a <link> in <head>
   *  on theme switch. Same URL is never injected twice. */
  fontUrl?: string;
  /** Root font size (controls rem scale). Example: `"14px"`, `"16px"`. */
  baseSize: string;
  /** Default line-height. Example: `"1.5"`, `"1.65"`. */
  lineHeight: string;
  /** Default letter-spacing. Example: `"0"`, `"0.01em"`, `"-0.01em"`. */
  letterSpacing: string;
}

export type ThemeDensity = "compact" | "comfortable" | "spacious";

export interface ThemeLayout {
  /** Corner-radius token. Example: `"0"`, `"0.25rem"`, `"0.5rem"`,
   *  `"1rem"`. Maps to `--radius` and cascades into every component. */
  radius: string;
  /** Spacing multiplier. `compact` = 0.85, `comfortable` = 1.0 (default),
   *  `spacious` = 1.2. Applied via the `--spacing-mul` CSS var. */
  density: ThemeDensity;
}

/** Overall layout variant the shell renders. `standard` = default single-
 *  column page layout. `cockpit` = reserves a left sidebar rail for a
 *  plugin slot (intended for HUD-style themes with persistent status panels).
 *  `tiled` = relaxes the main content max-width so pages can use the full
 *  viewport width. Themes set this; plugins react via CSS vars /
 *  `[data-layout-variant="..."]` selectors. */
export type ThemeLayoutVariant = "standard" | "cockpit" | "tiled";

/** Named hero/background assets a theme can populate. Each value is
 *  emitted as a CSS var (`--theme-asset-<name>`). The default shell
 *  consumes `bg` in `<Backdrop />` when present; other slots are
 *  plugin-facing — a cockpit sidebar plugin reads `--theme-asset-hero`
 *  to render its hero render without coupling to the theme name. */
export interface ThemeAssets {
  /** Full-viewport background image URL, injected under the noise layer. */
  bg?: string;
  /** Hero render (Gundam, mascot, wallpaper) — for plugin sidebars/overlays. */
  hero?: string;
  /** Logo mark — header slot consumers use this. */
  logo?: string;
  /** Faction/brand crest — header-left decoration. */
  crest?: string;
  /** Secondary sidebar illustration. */
  sidebar?: string;
  /** Alternate header artwork. */
  header?: string;
  /** User-defined named assets. Keyed by [a-zA-Z0-9_-] only.
   *  Emitted as `--theme-asset-custom-<key>`. */
  custom?: Record<string, string>;
}

/** Component-style override buckets. Each bucket's entries become CSS
 *  vars (`--component-<bucket>-<kebab-property>`) that shell components
 *  (Card, Backdrop, App header/footer, etc.) read. Values are plain CSS
 *  strings — we don't parse them, so themes can use `clip-path`,
 *  `border-image`, `background`, `box-shadow`, and anything else CSS
 *  accepts. */
export interface ThemeComponentStyles {
  card?: Record<string, string>;
  header?: Record<string, string>;
  footer?: Record<string, string>;
  sidebar?: Record<string, string>;
  tab?: Record<string, string>;
  progress?: Record<string, string>;
  badge?: Record<string, string>;
  backdrop?: Record<string, string>;
  page?: Record<string, string>;
}

/** Optional hex overrides keyed by shadcn-compat token name (without the
 *  `--color-` prefix). Any key set here wins over the DS cascade. */
export interface ThemeColorOverrides {
  card?: string;
  cardForeground?: string;
  popover?: string;
  popoverForeground?: string;
  primary?: string;
  primaryForeground?: string;
  secondary?: string;
  secondaryForeground?: string;
  muted?: string;
  mutedForeground?: string;
  accent?: string;
  accentForeground?: string;
  destructive?: string;
  destructiveForeground?: string;
  success?: string;
  warning?: string;
  border?: string;
  input?: string;
  ring?: string;
}

export interface DashboardTheme {
  description: string;
  label: string;
  name: string;
  palette: ThemePalette;
  typography: ThemeTypography;
  layout: ThemeLayout;
  /** Overall shell layout. Defaults to `"standard"` when absent. */
  layoutVariant?: ThemeLayoutVariant;
  /** Named + custom asset URLs exposed as CSS vars on theme apply. */
  assets?: ThemeAssets;
  /** Raw CSS injected as a scoped `<style>` tag on theme apply, cleaned up
   *  on theme switch. Intended for selector-level chrome that's too
   *  expressive for componentStyles alone (e.g. `::before` pseudo-elements,
   *  complex animations, media queries). */
  customCSS?: string;
  /** Per-component CSS-var overrides. See `ThemeComponentStyles`. */
  componentStyles?: ThemeComponentStyles;
  colorOverrides?: ThemeColorOverrides;
}

/**
 * Wire response shape for `GET /api/dashboard/themes`.
 *
 * The `themes` list is intentionally partial — built-in themes are fully
 * defined in `presets.ts`. Elevate currently exposes only light/dark product
 * themes, so `definition` is kept for wire compatibility with older clients.
 */
export interface ThemeListEntry {
  description: string;
  label: string;
  name: string;
  /** Full theme definition. Retained for wire compatibility; undefined for
   *  built-ins because the client already has those in `BUILTIN_THEMES`. */
  definition?: DashboardTheme;
}

export interface ThemeListResponse {
  active: string;
  themes: ThemeListEntry[];
}

```

---
## `src/themes/presets.ts`
```ts
import type { DashboardTheme, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Elevate keeps the dashboard chrome deliberately simple: one refined dark
 * mode and one clean light mode. Theme names must stay in sync with the
 * backend's `_BUILTIN_DASHBOARD_THEMES` list in `elevate_cli/web_server.py`.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Sans stack for the local app shell. Geist Sans is the primary UI font
 *  (Claude Code dashboard aesthetic); imported via Google Fonts in index.css.
 *  Falls back to Inter, then platform sans, then system-ui. */
const SYSTEM_SANS =
  '"Geist", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI Variable", "Segoe UI", system-ui, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  '"Geist Mono", "JetBrains Mono", ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

const DEFAULT_TYPOGRAPHY: ThemeTypography = {
  fontSans: SYSTEM_SANS,
  fontMono: SYSTEM_MONO,
  baseSize: "15px",
  lineHeight: "1.55",
  letterSpacing: "0",
};

const DEFAULT_LAYOUT: ThemeLayout = {
  radius: "0.5rem",
  density: "comfortable",
};

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const darkTheme: DashboardTheme = {
  name: "dark",
  label: "Dark",
  description: "Warm-tinted dark workspace with terracotta accent",
  palette: {
    background: { hex: "#1a1b1a", alpha: 1 },
    midground: { hex: "#ececec", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(217, 119, 87, 0.14)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "#212321",
    cardForeground: "#ececec",
    popover: "#212321",
    popoverForeground: "#ececec",
    primary: "#D97757",
    primaryForeground: "#1a1b1a",
    secondary: "#2a2c2a",
    secondaryForeground: "#ececec",
    muted: "#2a2c2a",
    mutedForeground: "color-mix(in srgb, #ececec 58%, transparent)",
    accent: "color-mix(in srgb, #D97757 14%, #1a1b1a)",
    accentForeground: "#ececec",
    destructive: "#ff827d",
    destructiveForeground: "#1a1b1a",
    success: "#44c487",
    warning: "#f3bf67",
    border: "#2a2c2a",
    input: "#2a2c2a",
    ring: "#D97757",
  },
};

export const lightTheme: DashboardTheme = {
  name: "light",
  label: "Light",
  description: "Clean real-estate workspace with navy and terracotta accents",
  palette: {
    background: { hex: "#f7f7f4", alpha: 1 },
    midground: { hex: "#1b2a4a", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(217, 119, 87, 0.10)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "#ffffff",
    cardForeground: "#1b2a4a",
    popover: "#ffffff",
    popoverForeground: "#1b2a4a",
    primary: "#1B2A4A",
    primaryForeground: "#f8fbff",
    secondary: "#e9ece7",
    secondaryForeground: "#1b2a4a",
    muted: "#ecefeb",
    mutedForeground: "#6d746f",
    accent: "#f2e4d7",
    accentForeground: "#1b2a4a",
    destructive: "#c94b45",
    destructiveForeground: "#fff7f6",
    success: "#16734f",
    warning: "#a96324",
    border: "#dde2db",
    input: "#cdd6cc",
    ring: "#D97757",
  },
};

export const defaultTheme = darkTheme;

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  dark: darkTheme,
  light: lightTheme,
};

```

---
## `src/themes/context.tsx`
```tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { BUILTIN_THEMES, defaultTheme } from "./presets";
import type {
  DashboardTheme,
  ThemeAssets,
  ThemeColorOverrides,
  ThemeComponentStyles,
  ThemeDensity,
  ThemeLayer,
  ThemeLayout,
  ThemeLayoutVariant,
  ThemePalette,
  ThemeTypography,
} from "./types";
import { api } from "@/lib/api";

/** LocalStorage key — pre-applied before the React tree mounts to avoid
 *  a visible flash of the default palette on theme-overridden installs. */
const STORAGE_KEY = "elevate-dashboard-theme";
const DEFAULT_THEME_NAME = "dark";
const BUILTIN_THEME_NAMES = new Set(Object.keys(BUILTIN_THEMES));
const LEGACY_THEME_ALIASES: Record<string, string> = {
  cyberpunk: DEFAULT_THEME_NAME,
  default: DEFAULT_THEME_NAME,
  ember: DEFAULT_THEME_NAME,
  midnight: DEFAULT_THEME_NAME,
  mono: DEFAULT_THEME_NAME,
  rose: DEFAULT_THEME_NAME,
};

/** Tracks fontUrls we've already injected so multiple theme switches don't
 *  pile up <link> tags. Keyed by URL. */
const INJECTED_FONT_URLS = new Set<string>();

// ---------------------------------------------------------------------------
// CSS variable builders
// ---------------------------------------------------------------------------

/** Turn a ThemeLayer into the two CSS expressions the DS consumes:
 *  `--<name>` (color-mix'd with alpha) and `--<name>-base` (opaque hex). */
function layerVars(
  name: "background" | "midground" | "foreground",
  layer: ThemeLayer,
): Record<string, string> {
  const pct = Math.round(layer.alpha * 100);
  return {
    [`--${name}`]: `color-mix(in srgb, ${layer.hex} ${pct}%, transparent)`,
    [`--${name}-base`]: layer.hex,
    [`--${name}-alpha`]: String(layer.alpha),
  };
}

function paletteVars(palette: ThemePalette): Record<string, string> {
  return {
    ...layerVars("background", palette.background),
    ...layerVars("midground", palette.midground),
    ...layerVars("foreground", palette.foreground),
    "--warm-glow": palette.warmGlow,
    "--noise-opacity-mul": String(palette.noiseOpacity),
  };
}

const DENSITY_MULTIPLIERS: Record<ThemeDensity, string> = {
  compact: "0.85",
  comfortable: "1",
  spacious: "1.2",
};

function typographyVars(typo: ThemeTypography): Record<string, string> {
  return {
    "--theme-font-sans": typo.fontSans,
    "--theme-font-mono": typo.fontMono,
    "--theme-font-display": typo.fontDisplay ?? typo.fontSans,
    "--theme-base-size": typo.baseSize,
    "--theme-line-height": typo.lineHeight,
    "--theme-letter-spacing": typo.letterSpacing,
  };
}

function layoutVars(layout: ThemeLayout): Record<string, string> {
  return {
    "--radius": layout.radius,
    "--theme-radius": layout.radius,
    "--theme-spacing-mul": DENSITY_MULTIPLIERS[layout.density] ?? "1",
    "--theme-density": layout.density,
  };
}

/** Map a color-overrides key (camelCase) to its `--color-*` CSS var. */
const OVERRIDE_KEY_TO_VAR: Record<keyof ThemeColorOverrides, string> = {
  card: "--color-card",
  cardForeground: "--color-card-foreground",
  popover: "--color-popover",
  popoverForeground: "--color-popover-foreground",
  primary: "--color-primary",
  primaryForeground: "--color-primary-foreground",
  secondary: "--color-secondary",
  secondaryForeground: "--color-secondary-foreground",
  muted: "--color-muted",
  mutedForeground: "--color-muted-foreground",
  accent: "--color-accent",
  accentForeground: "--color-accent-foreground",
  destructive: "--color-destructive",
  destructiveForeground: "--color-destructive-foreground",
  success: "--color-success",
  warning: "--color-warning",
  border: "--color-border",
  input: "--color-input",
  ring: "--color-ring",
};

/** Keys we might have written on a previous theme — needed to know which
 *  properties to clear when a theme with fewer overrides replaces one
 *  with more. */
const ALL_OVERRIDE_VARS = Object.values(OVERRIDE_KEY_TO_VAR);

function overrideVars(
  overrides: ThemeColorOverrides | undefined,
): Record<string, string> {
  if (!overrides) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(overrides)) {
    if (!value) continue;
    const cssVar = OVERRIDE_KEY_TO_VAR[key as keyof ThemeColorOverrides];
    if (cssVar) out[cssVar] = value;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Asset + component-style + layout variant vars
// ---------------------------------------------------------------------------

/** Well-known named asset slots a theme may populate. Kept in sync with
 *  `_THEME_NAMED_ASSET_KEYS` in `elevate_cli/web_server.py`. */
const NAMED_ASSET_KEYS = ["bg", "hero", "logo", "crest", "sidebar", "header"] as const;

/** Component buckets mirrored from the backend's `_THEME_COMPONENT_BUCKETS`.
 *  Each bucket emits `--component-<bucket>-<kebab-prop>` CSS vars. */
const COMPONENT_BUCKETS = [
  "card", "header", "footer", "sidebar", "tab",
  "progress", "badge", "backdrop", "page",
] as const;

/** Camel → kebab (`clipPath` → `clip-path`). */
function toKebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}

/** Build `--theme-asset-*` CSS vars from the assets block. Values are wrapped
 *  in `url(...)` when they look like a bare path/URL; raw CSS expressions
 *  (`linear-gradient(...)`, pre-wrapped `url(...)`, `none`) pass through. */
function assetVars(assets: ThemeAssets | undefined): Record<string, string> {
  if (!assets) return {};
  const out: Record<string, string> = {};
  const wrap = (v: string): string => {
    const trimmed = v.trim();
    if (!trimmed) return "";
    // Already a CSS image/gradient/url/none — don't re-wrap.
    if (/^(url\(|linear-gradient|radial-gradient|conic-gradient|none$)/i.test(trimmed)) {
      return trimmed;
    }
    // Bare path / http(s) URL / data: URL → wrap in url().
    return `url("${trimmed.replace(/"/g, '\\"')}")`;
  };
  for (const key of NAMED_ASSET_KEYS) {
    const val = assets[key];
    if (typeof val === "string" && val.trim()) {
      out[`--theme-asset-${key}`] = wrap(val);
      out[`--theme-asset-${key}-raw`] = val;
    }
  }
  if (assets.custom) {
    for (const [key, val] of Object.entries(assets.custom)) {
      if (typeof val !== "string" || !val.trim()) continue;
      if (!/^[a-zA-Z0-9_-]+$/.test(key)) continue;
      out[`--theme-asset-custom-${key}`] = wrap(val);
      out[`--theme-asset-custom-${key}-raw`] = val;
    }
  }
  return out;
}

/** Build `--component-<bucket>-<prop>` CSS vars from the componentStyles
 *  block. Values pass through untouched so themes can use any CSS expression. */
function componentStyleVars(
  styles: ThemeComponentStyles | undefined,
): Record<string, string> {
  if (!styles) return {};
  const out: Record<string, string> = {};
  for (const bucket of COMPONENT_BUCKETS) {
    const props = (styles as Record<string, Record<string, string> | undefined>)[bucket];
    if (!props) continue;
    for (const [prop, value] of Object.entries(props)) {
      if (typeof value !== "string" || !value.trim()) continue;
      // Same guardrail as backend — camelCase or kebab-case alnum only.
      if (!/^[a-zA-Z0-9_-]+$/.test(prop)) continue;
      out[`--component-${bucket}-${toKebab(prop)}`] = value;
    }
  }
  return out;
}

// Tracks keys we set on the previous theme so we can clear them when the
// next theme has fewer assets / component vars. Without this, switching
// from a richly-decorated theme to a plain one would leave stale vars.
let _PREV_DYNAMIC_VAR_KEYS: Set<string> = new Set();

/** ID for the injected <style> tag that carries a theme's customCSS.
 *  A single tag is reused + replaced on every theme switch. */
const CUSTOM_CSS_STYLE_ID = "elevate-theme-custom-css";

function applyCustomCSS(css: string | undefined) {
  if (typeof document === "undefined") return;
  let el = document.getElementById(CUSTOM_CSS_STYLE_ID) as HTMLStyleElement | null;
  if (!css || !css.trim()) {
    if (el) el.remove();
    return;
  }
  if (!el) {
    el = document.createElement("style");
    el.id = CUSTOM_CSS_STYLE_ID;
    el.setAttribute("data-elevate-theme-css", "true");
    document.head.appendChild(el);
  }
  el.textContent = css;
}

function applyLayoutVariant(variant: ThemeLayoutVariant | undefined) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const final: ThemeLayoutVariant = variant ?? "standard";
  root.dataset.layoutVariant = final;
  root.style.setProperty("--theme-layout-variant", final);
}

function normalizeThemeName(name: string | null | undefined): string {
  if (!name) return DEFAULT_THEME_NAME;
  if (BUILTIN_THEME_NAMES.has(name)) return name;
  return LEGACY_THEME_ALIASES[name] ?? DEFAULT_THEME_NAME;
}

// ---------------------------------------------------------------------------
// Font stylesheet injection
// ---------------------------------------------------------------------------

function injectFontStylesheet(url: string | undefined) {
  if (!url || typeof document === "undefined") return;
  if (INJECTED_FONT_URLS.has(url)) return;
  // Also skip if the page already has this href (e.g. SSR'd or persisted).
  const existing = document.querySelector<HTMLLinkElement>(
    `link[rel="stylesheet"][href="${CSS.escape(url)}"]`,
  );
  if (existing) {
    INJECTED_FONT_URLS.add(url);
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = url;
  link.setAttribute("data-elevate-theme-font", "true");
  document.head.appendChild(link);
  INJECTED_FONT_URLS.add(url);
}

// ---------------------------------------------------------------------------
// Apply a full theme to :root
// ---------------------------------------------------------------------------

function applyTheme(theme: DashboardTheme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Clear any overrides from a previous theme before applying the new set.
  for (const cssVar of ALL_OVERRIDE_VARS) {
    root.style.removeProperty(cssVar);
  }
  // Clear dynamic (asset/component) vars from the previous theme so the
  // new one starts clean — otherwise stale notched clip-paths, hero URLs,
  // etc. would bleed across theme switches.
  for (const prevKey of _PREV_DYNAMIC_VAR_KEYS) {
    root.style.removeProperty(prevKey);
  }

  const assetMap = assetVars(theme.assets);
  const componentMap = componentStyleVars(theme.componentStyles);
  _PREV_DYNAMIC_VAR_KEYS = new Set([
    ...Object.keys(assetMap),
    ...Object.keys(componentMap),
  ]);

  const vars = {
    ...paletteVars(theme.palette),
    ...typographyVars(theme.typography),
    ...layoutVars(theme.layout),
    ...overrideVars(theme.colorOverrides),
    ...assetMap,
    ...componentMap,
  };
  for (const [k, v] of Object.entries(vars)) {
    root.style.setProperty(k, v);
  }

  injectFontStylesheet(theme.typography.fontUrl);
  applyCustomCSS(theme.customCSS);
  applyLayoutVariant(theme.layoutVariant);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ThemeProvider({ children }: { children: ReactNode }) {
  /** Name of the currently active theme. Elevate intentionally supports only
   *  the two product modes here: dark and light. */
  const [themeName, setThemeName] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_THEME_NAME;
    return normalizeThemeName(window.localStorage.getItem(STORAGE_KEY));
  });

  /** All selectable themes shown in the picker. Server/user themes are ignored
   *  on purpose so old custom theme files cannot re-texture the app shell. */
  const [availableThemes] = useState<
    Array<{ description: string; label: string; name: string }>
  >(() =>
    Object.values(BUILTIN_THEMES).map((t) => ({
      name: t.name,
      label: t.label,
      description: t.description,
    })),
  );

  // Resolve a theme name to a full DashboardTheme, falling back to default
  // only when an old config/localStorage value points at a removed theme.
  const resolveTheme = useCallback(
    (name: string): DashboardTheme => {
      return BUILTIN_THEMES[normalizeThemeName(name)] ?? defaultTheme;
    },
    [],
  );

  // Re-apply on every themeName change.
  useEffect(() => {
    applyTheme(resolveTheme(themeName));
  }, [themeName, resolveTheme]);

  // Load server active preference once on mount, but normalize it to the
  // supported dark/light pair before it can affect the UI.
  useEffect(() => {
    let cancelled = false;
    api
      .getThemes()
      .then((resp) => {
        if (cancelled) return;
        const next = normalizeThemeName(resp.active);
        if (next !== themeName) {
          setThemeName(next);
          window.localStorage.setItem(STORAGE_KEY, next);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setTheme = useCallback(
    (name: string) => {
      const next = normalizeThemeName(name);
      setThemeName(next);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, next);
      }
      api.setTheme(next).catch(() => {});
    },
    [],
  );

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: resolveTheme(themeName),
      themeName,
      availableThemes,
      setTheme,
    }),
    [themeName, availableThemes, setTheme, resolveTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: defaultTheme,
  themeName: DEFAULT_THEME_NAME,
  availableThemes: Object.values(BUILTIN_THEMES).map((t) => ({
    name: t.name,
    label: t.label,
    description: t.description,
  })),
  setTheme: () => {},
});

interface ThemeContextValue {
  availableThemes: Array<{ description: string; label: string; name: string }>;
  setTheme: (name: string) => void;
  theme: DashboardTheme;
  themeName: string;
}

```

---
## `src/lib/utils.ts`
```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Relative time from a Unix epoch timestamp (seconds). */
export function timeAgo(ts: number): string {
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  if (delta < 172800) return "yesterday";
  return `${Math.floor(delta / 86400)}d ago`;
}

/** Relative time from an ISO-8601 timestamp string. */
export function isoTimeAgo(iso: string): string {
  const delta = (Date.now() - new Date(iso).getTime()) / 1000;
  if (delta < 0 || Number.isNaN(delta)) return "unknown";
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

```

---
## `src/components/ui/badge.tsx`
```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Ops-tool badge: transparent surface, opaque border, left-edge color strip
// for state. No palette-glow tints. Mono uppercase label is the signal.
const badgeVariants = cva(
  "relative inline-flex items-center rounded-sm font-mono-ui border bg-transparent pl-2.5 pr-2 py-0.5 text-[0.68rem] font-medium uppercase tracking-[0.06em] transition-colors before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[2px] before:rounded-l-sm",
  {
    variants: {
      variant: {
        default: "border-border text-foreground before:bg-border",
        secondary: "border-border text-muted-foreground before:bg-border",
        destructive: "border-border text-destructive before:bg-destructive",
        outline: "border-border text-muted-foreground before:bg-transparent",
        success: "border-border text-success before:bg-success",
        warning: "border-border text-warning before:bg-warning",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

```

---
## `src/components/ui/button.tsx`
```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-sans text-xs font-medium tracking-normal normal-case transition-colors cursor-pointer"
  + " focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-foreground/90 text-background shadow-sm hover:bg-foreground",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline: "border border-border bg-card text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/85",
        ghost: "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
        link: "text-foreground underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

```

---
## `src/components/ui/card.tsx`
```tsx
import { cn } from "@/lib/utils";

/**
 * Themed card primitive. Themes can restyle every card without touching
 * call sites by setting CSS vars under the `card` component-style bucket:
 *
 *   componentStyles:
 *     card:
 *       clipPath: "polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px)"
 *       border: "1px solid var(--color-ring)"
 *       background: "linear-gradient(180deg, var(--color-card) 0%, transparent 100%)"
 *       boxShadow: "0 0 0 1px var(--color-ring) inset, 0 0 24px -8px var(--warm-glow)"
 *
 * All properties are optional — vars that aren't set compute to their
 * CSS initial value, so the default shadcn-y card keeps looking normal
 * for themes that don't override anything.
 */
const CARD_STYLE: React.CSSProperties = {
  clipPath: "var(--component-card-clip-path)",
  borderImage: "var(--component-card-border-image)",
  background: "var(--component-card-background)",
  boxShadow: "var(--component-card-box-shadow)",
};

export function Card({ className, style, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "w-full rounded-md border border-border bg-card text-card-foreground",
        "overflow-hidden",
        className,
      )}
      style={{ ...CARD_STYLE, ...style }}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5 border-b border-border p-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-[0.95rem] font-semibold leading-5 tracking-normal text-foreground", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-xs leading-5 text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}

```

---
## `src/components/ui/confirm-dialog.tsx`
```tsx
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function ConfirmDialog({
  cancelLabel = "Cancel",
  confirmLabel = "Confirm",
  description,
  destructive = false,
  loading = false,
  onCancel,
  onConfirm,
  open,
  title,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Focus the confirm button when opened; trap ESC to cancel.
  useEffect(() => {
    if (!open) return;

    const prevActive = document.activeElement as HTMLElement | null;
    dialogRef.current
      ?.querySelector<HTMLButtonElement>("[data-confirm]")
      ?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };

    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      prevActive?.focus?.();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby={description ? "confirm-dialog-desc" : undefined}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center",
        "bg-black/60",
        "animate-[fade-in_150ms_ease-out]",
      )}
    >
      <div
        ref={dialogRef}
        className={cn(
          "relative w-full max-w-md mx-4",
          "overflow-hidden rounded-md border border-border bg-card",
          "animate-[dialog-in_180ms_ease-out]",
        )}
      >
        <div className="flex items-start gap-3 border-b border-border p-4">
          {destructive && (
            <div
              aria-hidden
              className="mt-0.5 shrink-0 text-destructive"
            >
              <AlertTriangle className="h-4 w-4" />
            </div>
          )}

          <div className="flex-1 min-w-0 flex flex-col gap-1">
            <h2
              id="confirm-dialog-title"
              className="text-sm font-semibold tracking-normal text-foreground"
            >
              {title}
            </h2>

            {description && (
              <p
                id="confirm-dialog-desc"
                className="text-xs leading-relaxed text-muted-foreground"
              >
                {description}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 p-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={loading}
          >
            {cancelLabel}
          </Button>
          <Button
            data-confirm
            type="button"
            variant={destructive ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmDialogProps {
  cancelLabel?: string;
  confirmLabel?: string;
  description?: string;
  destructive?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}

```

---
## `src/components/ui/input.tsx`
```tsx
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-sm border border-border bg-background px-3 py-1 font-sans text-sm transition-colors",
        "placeholder:text-muted-foreground",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70 focus-visible:border-ring/40",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

```

---
## `src/components/ui/label.tsx`
```tsx
import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-xs font-medium leading-none tracking-normal normal-case text-muted-foreground peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className,
      )}
      {...props}
    />
  );
}

```

---
## `src/components/ui/segmented.tsx`
```tsx
import { cn } from "@/lib/utils";

export function Segmented<T extends string>({
  className,
  onChange,
  options,
  size = "sm",
  value,
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      className={cn(
        "inline-flex gap-0.5 rounded-sm bg-card border border-border p-0.5",
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;

        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "rounded-sm font-sans font-medium tracking-normal normal-case",
              "transition-colors cursor-pointer whitespace-nowrap",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
              size === "sm" && "h-7 px-2.5 text-xs",
              size === "md" && "h-8 px-3 text-xs",
              active
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function FilterGroup({
  children,
  className,
  label,
}: FilterGroupProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="text-xs font-medium tracking-normal normal-case text-muted-foreground/80">
        {label}
      </span>
      {children}
    </div>
  );
}

interface FilterGroupProps {
  children: React.ReactNode;
  className?: string;
  label: string;
}

interface SegmentedOption<T extends string> {
  label: string;
  value: T;
}

interface SegmentedProps<T extends string> {
  className?: string;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  size?: "sm" | "md";
  value: T;
}

```

---
## `src/components/ui/select.tsx`
```tsx
import { useState, useRef, useEffect, useCallback } from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function Select({
  value,
  onValueChange,
  children,
  className,
  buttonClassName,
  id,
  disabled,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const options: SelectOptionData[] = [];
  flattenChildren(children, options);

  const selectedOption = options.find((o) => o.value === value);
  const displayLabel = selectedOption?.label ?? value ?? "";

  const close = useCallback(() => {
    setOpen(false);
    setHighlightedIndex(-1);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, close]);

  useEffect(() => {
    if (open && listRef.current && highlightedIndex >= 0) {
      const el = listRef.current.children[highlightedIndex] as HTMLElement | undefined;
      el?.scrollIntoView({ block: "nearest" });
    }
  }, [open, highlightedIndex]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;
    switch (e.key) {
      case "Enter":
      case " ":
        e.preventDefault();
        if (!open) {
          setOpen(true);
          setHighlightedIndex(options.findIndex((o) => o.value === value));
        } else if (highlightedIndex >= 0 && options[highlightedIndex]) {
          onValueChange?.(options[highlightedIndex].value);
          close();
        }
        break;
      case "ArrowDown":
        e.preventDefault();
        if (!open) {
          setOpen(true);
          setHighlightedIndex(options.findIndex((o) => o.value === value));
        } else {
          setHighlightedIndex((i) => Math.min(i + 1, options.length - 1));
        }
        break;
      case "ArrowUp":
        e.preventDefault();
        if (open) {
          setHighlightedIndex((i) => Math.max(i - 1, 0));
        }
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
    }
  };

  return (
    <div ref={containerRef} className={cn("relative", className)} id={id}>
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={handleKeyDown}
        className={cn(
          "flex h-9 w-full items-center justify-between rounded-sm border border-border bg-background px-3 py-1 font-sans text-sm text-left transition-colors",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70 focus-visible:border-ring/40",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "cursor-pointer",
          buttonClassName,
        )}
      >
        <span className={cn("truncate", !selectedOption && "text-muted-foreground")}>
          {displayLabel}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div
          ref={listRef}
          role="listbox"
          className={cn(
            "absolute z-50 mt-1 w-full overflow-hidden rounded-md border border-border bg-popover text-popover-foreground",
            "max-h-60 overflow-auto",
            "animate-[fade-in_100ms_ease-out]",
          )}
        >
          {options.map((opt, i) => {
            const isSelected = opt.value === value;
            const isHighlighted = i === highlightedIndex;
            return (
              <div
                key={opt.value}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setHighlightedIndex(i)}
                onClick={() => {
                  onValueChange?.(opt.value);
                  close();
                }}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 text-sm font-sans cursor-pointer transition-colors",
                  isHighlighted && "bg-foreground/10",
                  isSelected && "text-foreground",
                  !isSelected && "text-muted-foreground",
                )}
              >
                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    isSelected ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="truncate">{opt.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function SelectOption(_props: SelectOptionProps) {
  void _props;
  return null;
}

function flattenChildren(children: React.ReactNode, out: SelectOptionData[]) {
  const arr = Array.isArray(children) ? children : [children];
  for (const child of arr) {
    if (!child || typeof child !== "object" || !("props" in child)) continue;
    const props = child.props as Record<string, unknown>;
    if (props.value !== undefined) {
      out.push({
        value: String(props.value),
        label: typeof props.children === "string" ? props.children : String(props.value),
      });
    } else if (props.children) {
      flattenChildren(props.children as React.ReactNode, out);
    }
  }
}

interface SelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
  children?: React.ReactNode;
  className?: string;
  buttonClassName?: string;
  id?: string;
  disabled?: boolean;
}

interface SelectOptionProps {
  value: string;
  children: React.ReactNode;
}

interface SelectOptionData {
  value: string;
  label: string;
}

```

---
## `src/components/ui/separator.tsx`
```tsx
import { cn } from "@/lib/utils";

export function Separator({
  className,
  orientation = "horizontal",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { orientation?: "horizontal" | "vertical" }) {
  return (
    <div
      role="separator"
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  );
}

```

---
## `src/components/ui/switch.tsx`
```tsx
import { cn } from "@/lib/utils";

export function Switch({
  checked,
  onCheckedChange,
  className,
  disabled,
  id,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  className?: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary border-primary" : "bg-card border-border",
        className,
      )}
      onClick={() => onCheckedChange(!checked)}
    >
      <span
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full transition-transform",
          checked ? "translate-x-4 bg-primary-foreground" : "translate-x-0.5 bg-muted-foreground",
        )}
      />
    </button>
  );
}

```

---
## `src/components/ui/tabs.tsx`
```tsx
import { useState } from "react";
import { cn } from "@/lib/utils";

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: (active: string, setActive: (v: string) => void) => React.ReactNode;
  className?: string;
}) {
  const [active, setActive] = useState(defaultValue);
  return <div className={cn("flex flex-col gap-4", className)}>{children(active, setActive)}</div>;
}

export function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "inline-flex h-9 items-center justify-start gap-0.5 rounded-sm bg-card border border-border p-0.5 text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  active,
  value,
  onClick,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active: boolean; value: string }) {
  return (
    <button
      type="button"
      className={cn(
        "relative inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 font-sans text-xs font-medium tracking-normal normal-case transition-all cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "bg-secondary text-foreground"
          : "hover:text-foreground",
        className,
      )}
      value={value}
      onClick={onClick}
      {...props}
    />
  );
}

```
