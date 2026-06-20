import type {
  BuyerWatchlistEntry,
  LeadSectionSummary,
  OutreachTemplate,
  SourceConnectorStatus,
  SourceInboxDraft,
  SourceInboxProfile,
  SourceInboxSentItem,
  SourceInboxThread,
} from "@/lib/api-types";
import type {
  LeadsDraft,
  LeadsHeat,
  LeadsHotEntry,
  LeadsPipeline,
  LeadsProfile,
  LeadsSentMessage,
  LeadsSkippedEntry,
  LeadsSource,
  LeadsSourceHealth,
  LeadsTemplateItem,
  LeadsTemplateLane,
} from "./leads-data";

function ageLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (!isFinite(t) || t <= 0) return "—";
  const diffMs = Date.now() - t;
  if (diffMs < 0) return "now";
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  const w = Math.floor(d / 7);
  if (w < 5) return `${w}w`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo`;
  return `${Math.floor(d / 365)}y`;
}

function sourceHealth(s: SourceConnectorStatus): LeadsSourceHealth {
  if (s.blocked || s.lastError) return "blocked";
  if (s.state === "error") return "error";
  return "live";
}

function heatFromScore(score: number | null | undefined, label?: string): LeadsHeat {
  if (label === "hot") return "hot";
  if (label === "warm" || label === "watch") return "warm";
  if (typeof score === "number" && score >= 0.7) return "hot";
  if (typeof score === "number" && score >= 0.35) return "warm";
  return "cold";
}

export function mapLeadsSources(
  sources: SourceConnectorStatus[],
  drafts: SourceInboxDraft[],
  threads: SourceInboxThread[],
): LeadsSource[] {
  const out: LeadsSource[] = [];
  const totalCount = drafts.length + threads.length;
  out.push({ id: "all", label: "All", count: totalCount, isAll: true });

  const draftCounts = new Map<string, number>();
  for (const d of drafts) draftCounts.set(d.sourceId, (draftCounts.get(d.sourceId) ?? 0) + 1);
  const threadCounts = new Map<string, number>();
  for (const t of threads) threadCounts.set(t.sourceId, (threadCounts.get(t.sourceId) ?? 0) + 1);

  for (const s of sources) {
    if (!s.connected && !s.importOnly) continue;
    const count = (draftCounts.get(s.id) ?? 0) + (threadCounts.get(s.id) ?? 0);
    if (count === 0 && !s.connected) continue;
    out.push({
      id: s.id,
      label: s.label,
      count,
      health: sourceHealth(s),
    });
  }
  return out;
}

export function mapLeadsDrafts(drafts: SourceInboxDraft[]): LeadsDraft[] {
  return drafts.map((d) => ({
    id: d.id,
    name: d.personName || "Unknown",
    source: d.sourceLabel || d.sourceId,
    channel: (d.channel || "").toUpperCase() || "—",
    age: ageLabel(d.latestAt),
    body: d.draftText || "",
    heat: heatFromScore(d.score ?? null, d.leadLabel ?? undefined),
    sourceId: d.sourceId,
    taskId: d.taskId,
  }));
}

function statusLabel(profile: SourceInboxProfile): string {
  if (profile.status === "new_lead") return "New Lead";
  if (profile.status === "follow_up") return "Follow Up";
  if (profile.status === "ghosting") return "Ghosting";
  if (profile.status === "dead") return "Dead";
  if (profile.status === "closed_seller") return "Closed Seller";
  if (profile.status === "closed_buyer") return "Closed Buyer";
  if (profile.crmStage) return profile.crmStage;
  return profile.heatLabel === "hot" ? "Hot" : "Open";
}

export function mapLeadsProfiles(profiles: SourceInboxProfile[]): LeadsProfile[] {
  return profiles.map((p) => {
    const verified = p.verifiers.length > 0 || p.hasCrm;
    const heatLabel = p.heatLabel === "hot" ? "hot" : p.heatLabel === "warm" ? "warm" : "watch";
    const group: LeadsProfile["group"] = heatLabel === "hot" ? "active" : verified ? "verified" : "unverified";
    const firstThreadKey = (p.threadIds && p.threadIds[0]) || "";
    const firstSourceId = (p.sourceIds && p.sourceIds[0]) || "";
    let sourceId = firstSourceId;
    let threadId = firstThreadKey;
    if (firstThreadKey.includes(":") && firstSourceId) {
      const prefix = firstSourceId + ":";
      if (firstThreadKey.startsWith(prefix)) {
        threadId = firstThreadKey.slice(prefix.length);
      }
    }
    if (!sourceId && firstThreadKey.includes(":")) {
      sourceId = firstThreadKey.split(":", 1)[0];
    }
    return {
      id: p.id,
      name: p.displayName || "Unknown",
      heat: typeof p.heatScore === "number" ? p.heatScore : 0,
      group,
      verified,
      status: statusLabel(p),
      source: (p.sources && p.sources[0]) || (p.sourceIds && p.sourceIds[0]) || "—",
      email: p.emails[0] || "",
      phone: p.phones[0] || "",
      contact: p.emails[0] || p.phones[0] || "",
      threads: p.threadCount,
      age: ageLabel(p.latestAt),
      tags: p.tags || [],
      sub: p.crmStage || (p.leadSource ? `Source: ${p.leadSource}` : ""),
      lastMsg: p.latestText || "",
      lastTouch: ageLabel(p.statusUpdatedAt || p.latestAt),
      sourceId,
      threadId,
      contactIds: p.contactIds || [],
      favorite: Boolean(p.favorite),
      favoritedAt: p.favoritedAt ?? null,
    };
  });
}

function profileThreadRef(p: SourceInboxProfile): { sourceId?: string; threadId?: string } {
  const firstThreadKey = (p.threadIds && p.threadIds[0]) || "";
  const firstSourceId = (p.sourceIds && p.sourceIds[0]) || "";
  let sourceId = firstSourceId;
  let threadId = firstThreadKey;
  if (firstThreadKey.includes(":") && firstSourceId) {
    const prefix = firstSourceId + ":";
    if (firstThreadKey.startsWith(prefix)) threadId = firstThreadKey.slice(prefix.length);
  }
  if (!sourceId && firstThreadKey.includes(":")) sourceId = firstThreadKey.split(":", 1)[0];
  return { sourceId, threadId };
}

function draftQueueEntry(d: SourceInboxDraft, signal: string): LeadsHotEntry {
  return {
    id: d.id,
    name: d.personName || "Unknown",
    signal: d.scoreReason || signal,
    age: ageLabel(d.latestAt),
    sourceId: d.sourceId,
    threadId: d.threadId,
  };
}

function sectionQueueEntries(
  sectionId: "hot" | "follow_up",
  leadSections: Record<string, LeadSectionSummary> | undefined,
  profiles: SourceInboxProfile[],
  threads: SourceInboxThread[],
  fallbackDrafts: SourceInboxDraft[],
  signal: string,
): LeadsHotEntry[] {
  const seen = new Set<string>();
  const usedContacts = new Set<string>();
  const out: LeadsHotEntry[] = [];
  const add = (entry: LeadsHotEntry) => {
    if (!entry.id || seen.has(entry.id)) return;
    seen.add(entry.id);
    out.push(entry);
  };
  const section = leadSections?.[sectionId];
  const profileById = new Map(profiles.map((p) => [p.id, p]));
  const threadById = new Map(threads.map((t) => [t.id, t]));

  for (const profileId of section?.profileIds ?? []) {
    const p = profileById.get(profileId);
    if (!p) continue;
    for (const contactId of p.contactIds ?? []) usedContacts.add(contactId);
    add({
      id: `profile:${p.id}`,
      name: p.displayName || "Unknown",
      signal: p.latestText || signal,
      age: ageLabel(p.statusUpdatedAt || p.latestAt),
      ...profileThreadRef(p),
    });
  }
  const sectionContacts = new Set(section?.contactIds ?? []);
  for (const p of profiles) {
    if (!(p.contactIds ?? []).some((contactId) => sectionContacts.has(contactId))) continue;
    for (const contactId of p.contactIds ?? []) usedContacts.add(contactId);
    add({
      id: `profile:${p.id}`,
      name: p.displayName || "Unknown",
      signal: p.latestText || signal,
      age: ageLabel(p.statusUpdatedAt || p.latestAt),
      ...profileThreadRef(p),
    });
  }
  for (const threadId of section?.threadIds ?? []) {
    const t = threadById.get(threadId);
    if (!t || (t.contactId && usedContacts.has(t.contactId))) continue;
    add({
      id: `thread:${t.id}`,
      name: t.personName || "Unknown",
      signal: t.latestText || signal,
      age: ageLabel(t.latestAt),
      sourceId: t.sourceId,
      threadId: t.threadId,
    });
  }
  for (const draft of fallbackDrafts) add(draftQueueEntry(draft, signal));
  return out.slice(0, 8);
}

function skippedTime(d: SourceInboxDraft): number {
  const value = d.skippedAt || d.latestAt;
  const time = value ? new Date(value).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
}

export function mapLeadsPipeline(
  drafts: SourceInboxDraft[],
  skipped: SourceInboxDraft[],
  buyers: BuyerWatchlistEntry[],
  leadSections?: Record<string, LeadSectionSummary>,
  profiles: SourceInboxProfile[] = [],
  threads: SourceInboxThread[] = [],
): LeadsPipeline {
  const hotDrafts = drafts.filter(
    (d) => d.leadLabel === "hot" || (typeof d.score === "number" && d.score >= 0.7),
  );
  const followupDrafts = drafts.filter((d) => d.outreachLane === "follow-ups");
  const hot = sectionQueueEntries("hot", leadSections, profiles, threads, hotDrafts, "Hot signal");
  const followups = sectionQueueEntries(
    "follow_up",
    leadSections,
    profiles,
    threads,
    followupDrafts,
    "Follow-up cadence",
  );

  const skippedOut: LeadsSkippedEntry[] = [...skipped]
    .sort((a, b) => skippedTime(b) - skippedTime(a))
    .map((d) => ({
      id: d.id,
      name: d.personName || "Unknown",
      reason: d.scoreReason || "Skipped",
      sourceId: d.sourceId,
      taskId: d.taskId,
    }));

  return {
    hot,
    followups,
    buyers: Math.max(buyers.length, leadSections?.buyer_search?.count ?? 0),
    skipped: skippedOut,
  };
}

export function computeLeadsKpis(
  drafts: SourceInboxDraft[],
  profiles: SourceInboxProfile[],
): {
  drafts: number;
  hot: number;
  avgFirstTouch: string;
  avgDaysSinceTouch: string;
  replyRate: string;
  newLeads7d: string | number;
  medianWait: string;
  nextRun: string;
} {
  const hot = drafts.filter(
    (d) => d.leadLabel === "hot" || (typeof d.score === "number" && d.score >= 0.7),
  ).length;

  const now = Date.now();
  const sevenD = 7 * 24 * 60 * 60 * 1000;
  const newLeads7d = profiles.filter((p) => {
    const t = new Date(p.statusUpdatedAt || p.latestAt).getTime();
    return isFinite(t) && now - t < sevenD;
  }).length;

  const fiveYears = 5 * 365 * 24 * 60 * 60 * 1000;
  const touchAges = profiles
    .map((p) => {
      const t = new Date(p.statusUpdatedAt || p.latestAt).getTime();
      if (!isFinite(t) || t <= 0) return null;
      const age = now - t;
      if (age < 0 || age > fiveYears) return null;
      return age;
    })
    .filter((v): v is number => v !== null);
  const avgDaysMs =
    touchAges.length > 0 ? touchAges.reduce((a, b) => a + b, 0) / touchAges.length : 0;
  const avgDays = Math.round(avgDaysMs / (24 * 60 * 60 * 1000));

  return {
    drafts: drafts.length,
    hot,
    avgFirstTouch: "—",
    avgDaysSinceTouch: avgDays > 0 ? `${avgDays}d` : "—",
    replyRate: "—",
    newLeads7d,
    medianWait: "—",
    nextRun: "—",
  };
}

const LANE_LABELS: Record<string, string> = {
  "new-outreach": "New outreach",
  "hot-leads-watcher": "Hot leads watcher",
  "follow-ups": "Follow-ups",
};

const LANE_ICONS: Record<string, string> = {
  "new-outreach": "sparkles",
  "hot-leads-watcher": "flame",
  "follow-ups": "clock",
};

export function mapLeadsTemplates(templates: OutreachTemplate[]): LeadsTemplateLane[] {
  const byLane = new Map<string, OutreachTemplate[]>();
  for (const t of templates) {
    const lane = t.lane || "new-outreach";
    if (!byLane.has(lane)) byLane.set(lane, []);
    byLane.get(lane)!.push(t);
  }
  const result: LeadsTemplateLane[] = [];
  const order = ["new-outreach", "hot-leads-watcher", "follow-ups"];
  const seen = new Set<string>();
  const push = (lane: string, list: OutreachTemplate[]) => {
    seen.add(lane);
    const active = list.filter((t) => t.active && t.status === "active").length;
    const sent = list.reduce((s, t) => s + (t.uses || 0), 0);
    const replies = list.reduce((s, t) => s + (t.replies || 0), 0);
    const replyRate = sent > 0 ? Math.round((replies / sent) * 100) : 0;
    const items: LeadsTemplateItem[] = list.map((t) => ({
      id: t.id,
      name: t.name || "(untitled)",
      body: t.body || "",
      used: t.uses || 0,
      replies: t.replies || 0,
      replyRate: typeof t.replyRate === "number" ? Math.round(t.replyRate * 100) : null,
      active: Boolean(t.active && t.status === "active"),
    }));
    result.push({
      lane: LANE_LABELS[lane] || lane,
      laneId: lane,
      icon: LANE_ICONS[lane] || "sparkles",
      active,
      sent,
      replyRate,
      needMore: "",
      templates: items,
    });
  };
  for (const lane of order) {
    if (byLane.has(lane)) push(lane, byLane.get(lane)!);
  }
  for (const [lane, list] of byLane.entries()) {
    if (!seen.has(lane)) push(lane, list);
  }
  return result;
}

function transportFromChannel(channel: string | undefined): LeadsSentMessage["transport"] {
  const c = (channel || "").toLowerCase();
  if (c.includes("imessage")) return "IMESSAGE";
  if (c.includes("sms")) return "SMS";
  if (c.includes("stub")) return "STUB";
  return (channel || "").toUpperCase() || "STUB";
}

export function mapLeadsSent(items: SourceInboxSentItem[]): LeadsSentMessage[] {
  return items.map((it) => {
    const recipient =
      it.payload?.recipient?.person_name ||
      it.payload?.recipient?.phone ||
      it.payload?.recipient?.email ||
      it.payload?.recipient?.social_handle ||
      "—";
    const source = it.payload?.channel_meta?.toolkit
      ? String(it.payload.channel_meta.toolkit)
      : it.sourceId;
    return {
      id: it.id,
      when: ageLabel(it.updatedAt || it.createdAt),
      recipient,
      source,
      transport: transportFromChannel(it.channel),
      message: it.payload?.draft_text || "",
      msgId: it.providerMessageId || it.idempotencyKey || it.id,
      status: it.status === "sent" ? "sent" : it.status === "failed" ? "failed" : it.status,
    };
  });
}
