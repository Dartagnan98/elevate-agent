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
  description: "Navy workspace with copper real-estate controls",
  palette: {
    background: { hex: "#101827", alpha: 1 },
    midground: { hex: "#f4f7f5", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(206, 130, 62, 0.14)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  colorOverrides: {
    card: "color-mix(in srgb, #f4f7f5 5%, #101827)",
    cardForeground: "#f4f7f5",
    popover: "color-mix(in srgb, #f4f7f5 6%, #101827)",
    popoverForeground: "#f4f7f5",
    primary: "#CE823E",
    primaryForeground: "#101827",
    secondary: "color-mix(in srgb, #f4f7f5 9%, #101827)",
    secondaryForeground: "#f4f7f5",
    muted: "color-mix(in srgb, #f4f7f5 8%, #101827)",
    mutedForeground: "color-mix(in srgb, #f4f7f5 58%, transparent)",
    accent: "color-mix(in srgb, #CE823E 14%, #101827)",
    accentForeground: "#f4f7f5",
    destructive: "#ff827d",
    destructiveForeground: "#101827",
    success: "#44c487",
    warning: "#f3bf67",
    border: "color-mix(in srgb, #f4f7f5 14%, transparent)",
    input: "color-mix(in srgb, #f4f7f5 16%, transparent)",
    ring: "#CE823E",
  },
};

export const lightTheme: DashboardTheme = {
  name: "light",
  label: "Light",
  description: "Clean real-estate workspace with navy and copper accents",
  palette: {
    background: { hex: "#f7f7f4", alpha: 1 },
    midground: { hex: "#1b2a4a", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(206, 130, 62, 0.10)",
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
    ring: "#CE823E",
  },
};

export const defaultTheme = darkTheme;

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  dark: darkTheme,
  light: lightTheme,
};
