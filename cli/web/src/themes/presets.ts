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
