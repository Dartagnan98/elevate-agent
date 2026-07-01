import { useCallback, useEffect, useState } from "react";
import { fetchJSON } from "@/lib/api";
import { Clock, AlertTriangle } from "../icons";
import { DeskBar } from "./desk-bar";

type CDItem = {
  dealId: string;
  address: string;
  side: string;
  kind: string;
  label: string;
  date: string;
  daysDelta: number;
  rel: string;
  bucket: string;
};
type CDResp = {
  ok: boolean;
  items: CDItem[];
  counts: { overdue: number; today: number; thisWeek: number; upcoming: number };
};

const BUCKETS: Array<[string, string]> = [
  ["overdue", "Overdue"],
  ["today", "Today"],
  ["this_week", "This week"],
  ["upcoming", "Upcoming"],
];

function fmtDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("en-CA", { month: "short", day: "numeric" });
}

/** Critical dates — collapsible deadline bar between the KPI block and board. */
export default function CriticalDates({ onOpenDeal }: { onOpenDeal: (dealId: string) => void }) {
  const [data, setData] = useState<CDResp | null>(null);
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);

  const load = useCallback(() => {
    fetchJSON<CDResp>("/api/admin/critical-dates")
      .then((r) => setData(r))
      .catch(() => setData(null));
  }, []);
  useEffect(() => { load(); }, [load]);

  const c = data?.counts ?? { overdue: 0, today: 0, thisWeek: 0, upcoming: 0 };
  const total = c.overdue + c.today + c.thisWeek + c.upcoming;
  const alert = c.overdue > 0;

  // Auto-expand once on load when something is overdue; respect manual toggles after.
  useEffect(() => {
    if (data && !touched && c.overdue > 0) setOpen(true);
  }, [data, touched, c.overdue]);

  const summary =
    total === 0
      ? "All clear — no upcoming deadlines"
      : `${c.overdue} overdue · ${c.today} due today · ${c.thisWeek} this week`;

  const items = data?.items ?? [];

  return (
    <DeskBar
      tone={alert ? "alert" : "neutral"}
      leftIcon={alert ? <AlertTriangle /> : <Clock />}
      label="Critical dates"
      summary={summary}
      expanded={open}
      onToggle={() => { setTouched(true); setOpen((o) => !o); }}
    >
      {total === 0 ? (
        <div className="dsk-empty">No deadlines in the next 14 days.</div>
      ) : (
        BUCKETS.map(([key, title]) => {
          const rows = items.filter((i) => i.bucket === key);
          if (!rows.length) return null;
          return (
            <div key={key} className="dsk-group">
              <div className="dsk-group-head">
                {title} <span className="dsk-group-n">{rows.length}</span>
              </div>
              {rows.map((i, idx) => (
                <div key={`${i.dealId}-${i.kind}-${idx}`} className="dsk-row">
                  <span className="dsk-date">{fmtDate(i.date)}</span>
                  <span className={`dsk-relpill ${i.bucket}`}>{i.rel}</span>
                  <span className="dsk-row-main">
                    <span className="dsk-row-addr" title={i.address}>{i.address}</span>
                    <span className="dsk-row-sub">{i.side} · {i.label}</span>
                  </span>
                  <button type="button" className="dsk-row-btn" onClick={() => onOpenDeal(i.dealId)}>
                    {i.bucket === "overdue" || i.bucket === "today" ? "Resolve" : "View"}
                  </button>
                </div>
              ))}
            </div>
          );
        })
      )}
    </DeskBar>
  );
}
