import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const indexCss = readFileSync(new URL("../../../../index.css", import.meta.url), "utf8");
const leadsCss = readFileSync(new URL("../../leads/leads.css", import.meta.url), "utf8");
const reportingCss = readFileSync(new URL("../reporting.css", import.meta.url), "utf8");

type ThemeContrast = {
  canvas: string;
  card: string;
  muted: string;
  blue: string;
  blueDecoration: string;
  terracotta: string;
  terracottaDecoration: string;
};

const THEMES: Record<"light" | "medium" | "dark", ThemeContrast> = {
  light: {
    canvas: "#f7f3ec",
    card: "#fffdf9",
    muted: "#62594d",
    blue: "#315f9f",
    blueDecoration: "#5e8ad0",
    terracotta: "#984025",
    terracottaDecoration: "#c46340",
  },
  medium: {
    canvas: "#e8e9ec",
    card: "#ffffff",
    muted: "#565f6a",
    blue: "#315c99",
    blueDecoration: "#5e8ad0",
    terracotta: "#943b22",
    terracottaDecoration: "#c46340",
  },
  dark: {
    canvas: "#1e1e22",
    card: "#1b2236",
    muted: "#b0bad0",
    blue: "#91b8ec",
    blueDecoration: "#7ba4e2",
    terracotta: "#f09b77",
    terracottaDecoration: "#e08a63",
  },
};

function rgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [0, 2, 4].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number];
}

function luminance(hex: string): number {
  const channels = rgb(hex).map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

function mixSrgb(foreground: string, background: string, foregroundWeight: number): string {
  const foregroundRgb = rgb(foreground);
  const backgroundRgb = rgb(background);
  return `#${foregroundRgb.map((channel, index) => (
    Math.round(channel * foregroundWeight + backgroundRgb[index] * (1 - foregroundWeight))
      .toString(16)
      .padStart(2, "0")
  )).join("")}`;
}

describe("CRM and reporting contrast tokens", () => {
  it("keeps small text at WCAG AA contrast on every route surface", () => {
    for (const palette of Object.values(THEMES)) {
      for (const surface of [palette.canvas, palette.card]) {
        expect(contrast(palette.muted, surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(palette.blue, surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(palette.terracotta, surface)).toBeGreaterThanOrEqual(4.5);
      }

      // Sixteen percent is the strongest text-bearing accent tint used by
      // either route, so it is the conservative chip/badge background check.
      expect(contrast(
        palette.blue,
        mixSrgb(palette.blueDecoration, palette.card, 0.16),
      )).toBeGreaterThanOrEqual(4.5);
      expect(contrast(
        palette.terracotta,
        mixSrgb(palette.terracottaDecoration, palette.card, 0.16),
      )).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("pins the audited tokens to the CRM, reporting, and theme stylesheets", () => {
    for (const palette of Object.values(THEMES)) {
      for (const token of [palette.muted, palette.blue, palette.terracotta]) {
        expect(leadsCss.toLowerCase()).toContain(token);
        expect(reportingCss.toLowerCase()).toContain(token);
      }
      expect(indexCss.toLowerCase()).toContain(palette.canvas);
      expect(indexCss.toLowerCase()).toContain(palette.card);
    }
    expect(leadsCss).toContain("--fg-muted: var(--crm-text-muted)");
    expect(leadsCss).toContain("--accent-ring: var(--crm-focus-ring)");
    expect(reportingCss).toContain("--fg-muted: var(--report-text-muted)");
    expect(reportingCss).toContain("outline: 2px solid var(--report-focus-ring)");
  });
});
