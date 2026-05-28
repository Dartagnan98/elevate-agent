import type { AdminDeal, AdminUpcomingEvent } from "@/lib/api-types";

export interface AdminEvent {
  id: string;
  time: string;
  address: string;
  when: Date;
  kind: string;
  title?: string;
  source?: string;
  dealId?: string | null;
}

function fmtWhen(d: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today.getTime() + 86_400_000);
  const weekOut = new Date(today.getTime() + 7 * 86_400_000);
  const t = new Date(d.getFullYear(), d.getMonth(), d.getDate());

  const hour = d.getHours();
  const min = d.getMinutes();
  const hasTime = hour !== 0 || min !== 0;
  const timeStr = hasTime
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : "";

  let prefix: string;
  if (t.getTime() === today.getTime()) prefix = "Today";
  else if (t.getTime() === tomorrow.getTime()) prefix = "Tomorrow";
  else if (t < weekOut) {
    prefix = d.toLocaleDateString([], { weekday: "short" });
  } else {
    prefix = d.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return hasTime ? `${prefix} · ${timeStr}` : prefix;
}

function shortAddr(addr: string | null | undefined, fallback: string): string {
  const a = (addr || "").trim();
  if (!a) return fallback;
  return a.length > 44 ? a.slice(0, 42) + "…" : a;
}

export function adminUpcomingEventToAdminEvent(event: AdminUpcomingEvent): AdminEvent | null {
  if (!event.startAt) return null;
  const when = new Date(event.startAt);
  if (Number.isNaN(when.getTime())) return null;
  const label = event.title || event.kind || "Calendar event";
  const address = shortAddr(event.address || event.location, label);
  return {
    id: event.id,
    time: `${fmtWhen(when)} · ${label}`,
    address,
    when,
    kind: event.kind || label,
    title: label,
    source: event.source,
    dealId: event.dealId,
  };
}

export function mapAdminUpcomingEvents(events: AdminUpcomingEvent[]): AdminEvent[] {
  return events
    .map(adminUpcomingEventToAdminEvent)
    .filter((event): event is AdminEvent => Boolean(event))
    .sort((a, b) => a.when.getTime() - b.when.getTime())
    .slice(0, 8);
}

export function computeAdminEvents(deals: AdminDeal[]): AdminEvent[] {
  const now = new Date();
  const horizon = new Date(now.getTime() + 21 * 86_400_000);
  const out: AdminEvent[] = [];

  for (const d of deals) {
    const addr = shortAddr(d.listingAddress, d.title || "Untitled deal");
    const fields: Array<[keyof AdminDeal, string]> = [
      ["subjectRemovalDate", "Subject removal"],
      ["depositDueDate", "Deposit due"],
      ["completionDate", "Completion"],
      ["possessionDate", "Possession"],
      ["offerDate", "Offer"],
      ["listingDate", "Listing live"],
    ];
    for (const [key, label] of fields) {
      const raw = d[key] as string | null | undefined;
      if (!raw) continue;
      const when = new Date(raw);
      if (Number.isNaN(when.getTime())) continue;
      if (when < now) continue;
      if (when > horizon) continue;
      out.push({
        id: `${d.id}:${key}`,
        time: `${fmtWhen(when)} · ${label}`,
        address: addr,
        when,
        kind: label,
      });
    }
  }

  out.sort((a, b) => a.when.getTime() - b.when.getTime());
  return out.slice(0, 8);
}
