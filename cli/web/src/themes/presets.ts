import type { DashboardTheme, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Elevation keeps the dashboard chrome deliberately simple: one refined dark
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

const GRAPHITE_LAYOUT: ThemeLayout = {
  radius: "0.4375rem",
  density: "compact",
};

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const darkTheme: DashboardTheme = {
  name: "dark",
  label: "Dark",
  description: "Graphite workspace with neutral chrome and compact session flow",
  palette: {
    background: { hex: "#0F0F0F", alpha: 1 },
    midground: { hex: "#ececec", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(176, 176, 176, 0.08)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: GRAPHITE_LAYOUT,
  colorOverrides: {
    card: "#1A1A1A",
    cardForeground: "#ececec",
    popover: "#1A1A1A",
    popoverForeground: "#ececec",
    primary: "#8A8A8A",
    primaryForeground: "#0F0F0F",
    secondary: "#202020",
    secondaryForeground: "#ececec",
    muted: "#1A1A1A",
    mutedForeground: "#A0A0A0",
    accent: "color-mix(in srgb, #8A8A8A 14%, #0F0F0F)",
    accentForeground: "#ececec",
    destructive: "#E07570",
    destructiveForeground: "#0F0F0F",
    success: "#4FC38A",
    warning: "#E0B257",
    border: "#2A2A2A",
    input: "#2A2A2A",
    ring: "#B0B0B0",
  },
};

export const lightTheme: DashboardTheme = {
  name: "light",
  label: "Light",
  description: "Clean graphite workspace for bright environments",
  palette: {
    background: { hex: "#f7f7f4", alpha: 1 },
    midground: { hex: "#202020", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(176, 176, 176, 0.08)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "#ffffff",
    cardForeground: "#202020",
    popover: "#ffffff",
    popoverForeground: "#202020",
    primary: "#404040",
    primaryForeground: "#f8fbff",
    secondary: "#e9ece7",
    secondaryForeground: "#202020",
    muted: "#ecefeb",
    mutedForeground: "#6d746f",
    accent: "#eeeeeb",
    accentForeground: "#202020",
    destructive: "#c94b45",
    destructiveForeground: "#fff7f6",
    success: "#16734f",
    warning: "#a96324",
    border: "#dde2db",
    input: "#cdd6cc",
    ring: "#8A8A8A",
  },
};

export const defaultTheme = darkTheme;

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  dark: darkTheme,
  light: lightTheme,
};
