import { describe, expect, it } from "vitest";

import {
  campaignGroup,
  describeDays,
  formatDue,
  layerClashes,
  sameDayClashes,
  segmentLabel,
} from "../drips-helpers";

const warm = [
  { day: 1, channel: "text" as const },
  { day: 4, channel: "email" as const },
  { day: 9, channel: "text" as const },
  { day: 14, channel: "email" as const },
  { day: 21, channel: "text" as const },
  { day: 30, channel: "email" as const },
  { day: 40, channel: "text" as const },
  { day: 50, channel: "email" as const },
  { day: 60, channel: "text" as const },
  { day: 70, channel: "email" as const },
  { day: 85, channel: "email" as const },
  { day: 92, channel: "tag" as const },
];

const buyerCourse = [3, 5, 7, 11, 13, 16, 18, 22, 24].map((day) => ({ day, channel: "email" as const }));

describe("describeDays", () => {
  it("summarises long schedules and ignores tag steps", () => {
    expect(describeDays(warm)).toBe("Days 1, 4, 9, 14, 21, 30 … 85 · 11 touches");
  });
  it("handles short and empty schedules", () => {
    expect(describeDays([{ day: 1, channel: "call" }])).toBe("Day 1 · 1 touch");
    expect(describeDays([])).toBe("No scheduled touches");
  });
});

describe("clash detection", () => {
  it("flags two sends on one day inside a campaign", () => {
    expect(sameDayClashes([...warm, { day: 4, channel: "text" }])).toEqual([4]);
    expect(sameDayClashes(warm)).toEqual([]);
  });
  it("calls allowed on a send day are not a clash", () => {
    expect(sameDayClashes([{ day: 1, channel: "call" }, { day: 1, channel: "text" }])).toEqual([]);
  });
  it("confirms the Elevation course days miss the Warm Nurture days", () => {
    expect(layerClashes(warm, buyerCourse)).toEqual([]);
    expect(layerClashes(warm, [{ day: 14, channel: "email" }])).toEqual([14]);
  });
});

describe("formatDue", () => {
  it("words the distance from the board date", () => {
    expect(formatDue("2026-10-01", "2026-10-01")).toBe("Today");
    expect(formatDue("2026-10-02", "2026-10-01")).toBe("Tomorrow");
    expect(formatDue("2026-09-30", "2026-10-01")).toBe("1 day late");
    expect(formatDue("2026-09-25", "2026-10-01")).toBe("6 days late");
    expect(formatDue("2026-10-05", "2026-10-01")).toBe("In 4 days");
    expect(formatDue("2026-11-05", "2026-10-01")).toBe("2026-11-05");
  });
});

describe("grouping + labels", () => {
  it("puts playbooks, layers and nurture campaigns in their groups", () => {
    expect(campaignGroup({ kind: "playbook", role: "primary" })).toBe("playbook");
    expect(campaignGroup({ kind: "course", role: "layer" })).toBe("layer");
    expect(campaignGroup({ kind: "custom", role: "primary" })).toBe("primary");
  });
  it("falls back to the key when a segment was deleted", () => {
    const segments = [{ key: "warm", label: "Warm" }] as never;
    expect(segmentLabel(segments, "warm")).toBe("Warm");
    expect(segmentLabel(segments, "gone")).toBe("gone");
    expect(segmentLabel(segments, null)).toBe("No segment");
  });
});
