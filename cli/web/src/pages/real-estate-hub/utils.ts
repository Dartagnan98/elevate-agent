import type { SourceInboxProfile, SourceInboxResponse, SourceInboxThread } from "@/lib/api";
import { isoTimeAgo } from "@/lib/utils";

export function threadWhen(thread: SourceInboxThread): string {
  return thread.latestAt ? isoTimeAgo(thread.latestAt) : "unsynced";
}

export function heatVariant(item: { heatLabel: string }): "default" | "success" | "warning" | "destructive" | "outline" {
  if (item.heatLabel === "hot") return "destructive";
  if (item.heatLabel === "warm") return "warning";
  if (item.heatLabel === "watch") return "success";
  return "outline";
}

export type HeatTone = {
  dot: string;
  pill: string;
  text: string;
  ring: string;
  label: string;
};

export function heatStyles(label: string): HeatTone {
  switch (label) {
    case "hot":
      return {
        dot: "bg-destructive",
        pill: "bg-destructive/12 text-destructive border-destructive/45",
        text: "text-destructive",
        ring: "ring-destructive/30",
        label: "Hot lead",
      };
    case "warm":
      return {
        dot: "bg-warning",
        pill: "bg-warning/12 text-warning border-warning/45",
        text: "text-warning",
        ring: "ring-warning/30",
        label: "Warm lead",
      };
    case "watch":
      return {
        dot: "bg-success",
        pill: "bg-success/12 text-success border-success/40",
        text: "text-success",
        ring: "ring-success/30",
        label: "Lead to watch",
      };
    case "dead":
      return {
        dot: "bg-foreground/30",
        pill: "bg-card text-foreground/55 border-border line-through",
        text: "text-foreground/55",
        ring: "ring-border",
        label: "Dead lead",
      };
    default:
      return {
        dot: "bg-foreground/40",
        pill: "bg-card text-foreground/70 border-border",
        text: "text-foreground/70",
        ring: "ring-border",
        label: "Cold lead",
      };
  }
}

export function inboundWaitMinutes(thread: SourceInboxThread): number | null {
  if (!thread.latestAt) return null;
  if (thread.direction !== "inbound") return null;
  const ts = Date.parse(thread.latestAt);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, (Date.now() - ts) / 60000);
}

export type ResponsePulse = {
  unanswered: number;
  median: number | null;
  longest: number | null;
  longestThread: SourceInboxThread | null;
  breached5: number;
  breached30: number;
  breached60: number;
};

export function computeResponsePulse(threads: SourceInboxThread[]): ResponsePulse {
  const waits: Array<{ minutes: number; thread: SourceInboxThread }> = [];
  for (const thread of threads) {
    const minutes = inboundWaitMinutes(thread);
    if (minutes === null) continue;
    waits.push({ minutes, thread });
  }
  if (waits.length === 0) {
    return {
      unanswered: 0,
      median: null,
      longest: null,
      longestThread: null,
      breached5: 0,
      breached30: 0,
      breached60: 0,
    };
  }
  const sorted = waits.slice().sort((a, b) => a.minutes - b.minutes);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1
      ? sorted[mid].minutes
      : (sorted[mid - 1].minutes + sorted[mid].minutes) / 2;
  const longest = sorted[sorted.length - 1];
  return {
    unanswered: waits.length,
    median,
    longest: longest.minutes,
    longestThread: longest.thread,
    breached5: waits.filter((w) => w.minutes >= 5).length,
    breached30: waits.filter((w) => w.minutes >= 30).length,
    breached60: waits.filter((w) => w.minutes >= 60).length,
  };
}

export function formatMinutes(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 1440) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes - h * 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.floor(minutes / 1440)}d`;
}
const FOLLOWUP_CHANNELS = new Set([
  "email",
  "gmail",
  "sms",
  "imessage",
  "messenger",
  "facebook",
  "instagram",
  "instagram_dm",
  "whatsapp",
  "telegram",
]);

export function isFollowUpThread(thread: SourceInboxThread): boolean {
  const channel = (thread.channel || "").toLowerCase();
  if (!FOLLOWUP_CHANNELS.has(channel)) return false;
  // First outreach must have happened — at least one outbound from us.
  if ((thread.outboundCount ?? 0) < 1) return false;
  // Ball is in our court: last message came in.
  return thread.direction === "inbound";
}

export function leadSectionCount(
  sourceInbox: SourceInboxResponse | null | undefined,
  sectionId: string,
  fallback = 0,
): number {
  const value = sourceInbox?.leadSections?.[sectionId]?.count;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function threadMatchesSectionId(thread: SourceInboxThread, id: string): boolean {
  if (thread.id === id) return true;
  if (thread.threadId === id) return true;
  if (thread.conversationId && thread.conversationId === id) return true;
  return false;
}

export function leadSectionThreads(
  threads: SourceInboxThread[],
  sourceInbox: SourceInboxResponse | null | undefined,
  sectionId: string,
  fallback: SourceInboxThread[],
): SourceInboxThread[] {
  const section = sourceInbox?.leadSections?.[sectionId];
  if (!section) return fallback;
  const threadIds = new Set(section.threadIds ?? []);
  return threads.filter((thread) => {
    if (thread.leadSectionIds?.includes(sectionId)) return true;
    if (threadIds.size === 0) return false;
    for (const id of threadIds) {
      if (threadMatchesSectionId(thread, id)) return true;
    }
    return false;
  });
}

export function leadThreadBuckets(threads: SourceInboxThread[]) {
  const hot = threads.filter((thread) => thread.heatLabel === "hot").slice(0, 10);
  const followUp = threads
    .filter(isFollowUpThread)
    .sort((a, b) => {
      const heatDiff = (b.heatScore ?? 0) - (a.heatScore ?? 0);
      if (heatDiff !== 0) return heatDiff;
      const aTime = a.latestAt ? Date.parse(a.latestAt) : 0;
      const bTime = b.latestAt ? Date.parse(b.latestAt) : 0;
      return bTime - aTime;
    })
    .slice(0, 12);
  const placed = new Set<string>([...hot, ...followUp].map((t) => t.id));
  const remaining = threads.filter((thread) => !placed.has(thread.id));
  const watch: SourceInboxThread[] = [];
  const seenSources = new Set<string>(
    [...hot, ...followUp].map((t) => String(t.sourceId ?? "")),
  );
  for (const thread of remaining) {
    const sid = String(thread.sourceId ?? "");
    if (!seenSources.has(sid) && watch.length < 10) {
      watch.push(thread);
      seenSources.add(sid);
    }
  }
  for (const thread of remaining) {
    if (watch.length >= 10) break;
    if (!watch.includes(thread)) watch.push(thread);
  }
  return { followUp, hot, watch };
}
export function contactBuckets(profiles: SourceInboxProfile[]) {
  const crmContacts = profiles.filter((profile) => profile.hasCrm).slice(0, 12);
  const active = profiles
    .filter((profile) => !profile.hasCrm && profile.hasConversation && !profile.isPotentialLead)
    .slice(0, 8);
  const potential = profiles
    .filter((profile) => profile.isPotentialLead && !profile.hasCrm)
    .slice(0, 8);
  return { active, crmContacts, potential };
}

export function profileWhen(profile: SourceInboxProfile): string {
  return profile.latestAt ? isoTimeAgo(profile.latestAt) : "unsynced";
}
