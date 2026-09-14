import { useConfirmation } from "@/hooks/useConfirmation";
import { useCallback, useEffect, useState } from "react";
import { fetchJSON } from "@/lib/api";
import { Clock, AlertTriangle } from "../icons";
import { DeskBar } from "./desk-bar";
import { useDeskResource } from "../use-desk-resource";

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
export default function CriticalDates({ onOpenDeal, refreshKey, onChanged }: { onOpenDeal: (dealId: string) => void; refreshKey?: unknown; onChanged?: () => void | Promise<void> }) {
  const { confirm: confirmAction, dialog: confirmationDialog } = useConfirmation();
  const { data, loading, error, load } = useDeskResource<CDResp>("/api/admin/critical-dates", refreshKey);
  const [actionError, setActionError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);


  const c = data?.counts ?? { overdue: 0, today: 0, thisWeek: 0, upcoming: 0 };
  const total = c.overdue + c.today + c.thisWeek + c.upcoming;
  const alert = c.overdue > 0;

  // Auto-expand once on load when something is overdue; respect manual toggles after.
  useEffect(() => {
    if (data && !touched && c.overdue > 0) setOpen(true);
  }, [data, touched, c.overdue]);

  const summary = error ? "Could not refresh deadlines — retry below" : !data ? "Loading deadlines…" :
    total === 0
      ? "All clear — no upcoming deadlines"
      : `${c.overdue} overdue · ${c.today} due today · ${c.thisWeek} this week`;

  const items = data?.items ?? [];

  // Resolve-all-overdue: completion/possession/expiry have no per-date "done"
  // flag, so the only way they leave this section is the deal leaving
  // status='active'. For fully-closed properties that's the correct action —
  // mark each overdue deal CLOSED and all its date rows drop off at once.
  const resolveAllOverdue = useCallback(async () => {
    const overdue = items.filter((i) => i.bucket === "overdue");
    const addrs = Array.from(new Set(overdue.map((i) => i.address)));
    if (!addrs.length || busy || loading || error) return;
    const msg =
      `Resolve all ${overdue.length} overdue item${overdue.length > 1 ? "s" : ""}?\n\n` +
      `This marks ${addrs.length} deal${addrs.length > 1 ? "s" : ""} CLOSED and clears all their dates:\n` +
      addrs.map((a) => `  • ${a}`).join("\n") +
      `\n\nThey come off the active board. Continue?`;
    if (!(await confirmAction(msg))) return;
    setBusy(true);
    setActionError(null);
    try {
      await fetchJSON("/api/admin/critical-dates/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bucket: "overdue" }),
      });
      void onChanged?.();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not close the overdue deals. Please retry.");
    } finally {
      setBusy(false);
      void load();
    }
  }, [items, busy, loading, error, load, onChanged]);

  return <>{confirmationDialog}{(
    <DeskBar
      tone={alert || error ? "alert" : "neutral"}
      leftIcon={alert ? <AlertTriangle /> : <Clock />}
      label="Critical dates"
      summary={summary}
      expanded={open}
      onToggle={() => { setTouched(true); setOpen((o) => !o); }}
    >
      {error && <div className="dsk-err" role="alert">Deadlines could not refresh. {data ? "Showing the last available dates." : "Your deadlines have not been checked."} <button type="button" className="dsk-row-btn" disabled={loading} onClick={() => void load()}>{loading ? "Retrying…" : "Retry"}</button></div>}
      {actionError && <div className="dsk-err" role="alert">{actionError}</div>}
      {!data ? <div className="dsk-empty" role="status">{loading ? "Loading deadlines…" : "Deadline information is unavailable."}</div> : total === 0 ? (
        <div className="dsk-empty">No deadlines in the next 14 days.</div>
      ) : (
        BUCKETS.map(([key, title]) => {
          const rows = items.filter((i) => i.bucket === key);
          if (!rows.length) return null;
          return (
            <div key={key} className="dsk-group">
              <div className="dsk-group-head">
                {title} <span className="dsk-group-n">{rows.length}</span>
                {key === "overdue" && (
                  <button
                    type="button"
                    className="dsk-resolve-all"
                    disabled={busy || loading || !!error}
                    onClick={resolveAllOverdue}
                  >
                    {busy ? "Closing deals…" : "Close all overdue deals"}
                  </button>
                )}
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
  )}</>;
}
