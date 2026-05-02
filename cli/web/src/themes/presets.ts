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

/** Sans stack for the local app shell: polished on macOS/Windows, no webfont dependency. */
const SYSTEM_SANS =
  'Aptos, "Avenir Next", "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

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
  description: "Deep blue-black workspace for focused agent work",
  palette: {
    background: { hex: "#181a1d", alpha: 1 },
    midground: { hex: "#f0f3f7", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(69, 126, 210, 0.16)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "color-mix(in srgb, #f0f3f7 5%, #181a1d)",
    cardForeground: "#f0f3f7",
    popover: "color-mix(in srgb, #f0f3f7 6%, #181a1d)",
    popoverForeground: "#f0f3f7",
    primary: "#7fb2ff",
    primaryForeground: "#101215",
    secondary: "color-mix(in srgb, #f0f3f7 9%, #181a1d)",
    secondaryForeground: "#f0f3f7",
    muted: "color-mix(in srgb, #f0f3f7 8%, #181a1d)",
    mutedForeground: "color-mix(in srgb, #f0f3f7 58%, transparent)",
    accent: "color-mix(in srgb, #7fb2ff 14%, #181a1d)",
    accentForeground: "#f0f3f7",
    destructive: "#ff827d",
    destructiveForeground: "#101215",
    success: "#35d58b",
    warning: "#f3bf67",
    border: "color-mix(in srgb, #f0f3f7 14%, transparent)",
    input: "color-mix(in srgb, #f0f3f7 16%, transparent)",
    ring: "#7fb2ff",
  },
};

export const lightTheme: DashboardTheme = {
  name: "light",
  label: "Light",
  description: "Bright workspace with crisp blue agent controls",
  palette: {
    background: { hex: "#f6f8fb", alpha: 1 },
    midground: { hex: "#17233a", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(66, 116, 205, 0.10)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "#ffffff",
    cardForeground: "#17233a",
    popover: "#ffffff",
    popoverForeground: "#17233a",
    primary: "#1f5ca8",
    primaryForeground: "#f8fbff",
    secondary: "#e7edf6",
    secondaryForeground: "#17233a",
    muted: "#e9eef6",
    mutedForeground: "#66728a",
    accent: "#dce8f8",
    accentForeground: "#17233a",
    destructive: "#c94b45",
    destructiveForeground: "#fff7f6",
    success: "#168a59",
    warning: "#a96917",
    border: "#d9e1ec",
    input: "#cbd5e2",
    ring: "#1f5ca8",
  },
};

export const defaultTheme = darkTheme;

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  dark: darkTheme,
  light: lightTheme,
};
