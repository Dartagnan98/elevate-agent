import type {
  DripCampaign,
  DripCampaignKind,
  DripCampaignRole,
  DripChannel,
  DripSegment,
  DripStep,
} from "@/lib/api";

export const CHANNEL_LABELS: Record<DripChannel, string> = {
  call: "Call",
  text: "Text",
  email: "Email",
  task: "Task",
  tag: "Move the tag",
};

export const CHANNEL_OPTIONS: DripChannel[] = ["text", "email", "call", "task", "tag"];

export const KIND_LABELS: Record<DripCampaignKind, string> = {
  nurture: "Nurture",
  course: "Course",
  playbook: "Playbook",
  custom: "Custom",
};

export const ROLE_LABELS: Record<DripCampaignRole, string> = {
  primary: "One at a time",
  layer: "Runs alongside",
};

export const SEND_CHANNELS: ReadonlySet<DripChannel> = new Set<DripChannel>(["text", "email"]);

export const FALLBACK_SEGMENT_COLOR = "#8A8F98";

type DayStep = Pick<DripStep, "day" | "channel">;

/** "Days 1, 4, 9, 14, 21, 30 … 85 · 11 touches" for a campaign card. */
export function describeDays(steps: DayStep[]): string {
  const sendSteps = steps.filter((s) => s.channel !== "tag");
  const days = Array.from(new Set(sendSteps.map((s) => s.day))).sort((a, b) => a - b);
  if (days.length === 0) return "No scheduled touches";
  const shown = days.length > 8 ? `${days.slice(0, 6).join(", ")} … ${days[days.length - 1]}` : days.join(", ");
  const touches = sendSteps.length;
  return `${days.length === 1 ? "Day" : "Days"} ${shown} · ${touches} ${touches === 1 ? "touch" : "touches"}`;
}

/** Days where one campaign would send two texts/emails to the same person. */
export function sameDayClashes(steps: DayStep[]): number[] {
  const counts = new Map<number, number>();
  for (const step of steps) {
    if (!SEND_CHANNELS.has(step.channel)) continue;
    counts.set(step.day, (counts.get(step.day) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .filter(([, n]) => n > 1)
    .map(([day]) => day)
    .sort((a, b) => a - b);
}

/** Send days a layer (course) shares with the campaign it runs alongside. */
export function layerClashes(primary: DayStep[], layer: DayStep[]): number[] {
  const primaryDays = new Set(primary.filter((s) => SEND_CHANNELS.has(s.channel)).map((s) => s.day));
  return Array.from(new Set(layer.filter((s) => SEND_CHANNELS.has(s.channel)).map((s) => s.day)))
    .filter((day) => primaryDays.has(day))
    .sort((a, b) => a - b);
}

export function segmentColor(segment: DripSegment | null | undefined): string {
  return segment?.color || FALLBACK_SEGMENT_COLOR;
}

export function segmentLabel(segments: DripSegment[], key: string | null | undefined): string {
  if (!key) return "No segment";
  return segments.find((s) => s.key === key)?.label ?? key;
}

function parseDay(value: string): number {
  const [y, m, d] = value.slice(0, 10).split("-").map((part) => Number(part));
  return Date.UTC(y, (m || 1) - 1, d || 1);
}

/** Relative wording for a due date against the board's date. */
export function formatDue(dueDate: string, today: string): string {
  const diff = Math.round((parseDay(dueDate) - parseDay(today)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "1 day late";
  if (diff < 0) return `${Math.abs(diff)} days late`;
  if (diff <= 7) return `In ${diff} days`;
  return dueDate.slice(0, 10);
}

export function isoToday(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export type CampaignGroup = "primary" | "layer" | "playbook";

export function campaignGroup(campaign: Pick<DripCampaign, "kind" | "role">): CampaignGroup {
  if (campaign.kind === "playbook") return "playbook";
  return campaign.role === "layer" ? "layer" : "primary";
}

export const GROUP_TITLES: Record<CampaignGroup, { title: string; hint: string }> = {
  primary: {
    title: "Nurture campaigns",
    hint: "One per person at a time. Moving the segment ends the old one and starts the new one the same day.",
  },
  layer: {
    title: "Layers",
    hint: "Run alongside a nurture campaign on pre-set days that never clash. Courses run once per person.",
  },
  playbook: {
    title: "Playbooks",
    hint: "Rhythms you work by hand: the guide, the checklist, and a few reminders on your task list.",
  },
};

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}
