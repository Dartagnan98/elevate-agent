import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Play, SkipForward } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { DripBoard, DripBoardItem, DripRunSummary, DripSegment } from "@/lib/api";
import { errorMessage, formatDue } from "../drips-helpers";
import { ChannelBadge, EmptyState, Note, SegmentChip, Section } from "./shared";

export function BoardView({
  board,
  segments,
  onChanged,
}: {
  board: DripBoard | null;
  segments: DripSegment[];
  onChanged: () => Promise<void> | void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runSummary, setRunSummary] = useState<DripRunSummary | null>(null);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      await onChanged();
    } catch (err) {
      setError(errorMessage(err, "That did not go through."));
    } finally {
      setBusyId(null);
    }
  };

  const runEngine = () =>
    act("run", async () => {
      const res = await api.runDrips();
      setRunSummary(res.run);
    });

  if (!board) return null;
  const empty = board.counts.overdue + board.counts.today + board.counts.upcoming === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs leading-5 text-muted-foreground">
          Everything due for the people on your campaigns. Copy the message, send it from your phone or inbox, then mark it sent.
          Calls land on your task list on their day.
        </p>
        <Button variant="outline" size="sm" onClick={() => void runEngine()} disabled={busyId !== null}>
          <Play className="h-3.5 w-3.5" aria-hidden="true" />
          {busyId === "run" ? "Running…" : "Run the engine now"}
        </Button>
      </div>
      {error && <Note tone="error">{error}</Note>}
      {runSummary && (
        <Note tone="success">
          Engine run for {runSummary.date}: {runSummary.routed.length} moved segment, {runSummary.completed} finished,
          {" "}{runSummary.restarted} restarted, {runSummary.tasksCreated} call tasks created, {runSummary.autoEnrolled} new leads enrolled.
          {runSummary.errors.length > 0 && ` ${runSummary.errors.length} could not be processed.`}
        </Note>
      )}
      {empty && (
        <EmptyState
          title="Nothing due"
          hint="Put a contact on a campaign, or move someone into a segment, and their touches show up here on their day."
        />
      )}
      {board.overdue.length > 0 && (
        <Section title={`Overdue (${board.overdue.length})`} hint="Catch these up first, or skip the ones that no longer make sense.">
          <ItemList items={board.overdue} board={board} segments={segments} busyId={busyId} onAct={act} />
        </Section>
      )}
      {board.today.length > 0 && (
        <Section title={`Today (${board.today.length})`}>
          <ItemList items={board.today} board={board} segments={segments} busyId={busyId} onAct={act} />
        </Section>
      )}
      {board.upcoming.length > 0 && (
        <Section title={`Next 7 days (${board.upcoming.length})`} hint="A preview. Nothing here needs you yet.">
          <ItemList items={board.upcoming} board={board} segments={segments} busyId={busyId} onAct={act} preview />
        </Section>
      )}
    </div>
  );
}

function ItemList({
  items,
  board,
  segments,
  busyId,
  onAct,
  preview = false,
}: {
  items: DripBoardItem[];
  board: DripBoard;
  segments: DripSegment[];
  busyId: string | null;
  onAct: (id: string, fn: () => Promise<unknown>) => Promise<void>;
  preview?: boolean;
}) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <BoardRow key={item.id} item={item} board={board} segments={segments} busy={busyId === item.id} onAct={onAct} preview={preview} />
      ))}
    </ul>
  );
}

function BoardRow({
  item,
  board,
  segments,
  busy,
  onAct,
  preview,
}: {
  item: DripBoardItem;
  board: DripBoard;
  segments: DripSegment[];
  busy: boolean;
  onAct: (id: string, fn: () => Promise<unknown>) => Promise<void>;
  preview: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const segment = item.contact.segment ? segments.find((s) => s.key === item.contact.segment) ?? null : null;
  const isRoute = item.channel === "tag";

  const copyText = async () => {
    const text = item.subject ? `${item.subject}\n\n${item.body}` : item.body;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked; the text stays visible to select by hand */
    }
  };

  const routeTo = (key: string) =>
    onAct(item.id, async () => {
      await api.setDripContactSegment(item.contact.id, { segment: key, note: `${item.campaignName} day ${item.day}` });
      await api.completeDripTouch(item.id, "done", `moved to ${key}`);
    });

  return (
    <li className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left hover:bg-foreground/5"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />}
        <span className={`font-mono-ui w-24 shrink-0 text-[0.7rem] ${item.daysLate > 0 ? "text-warning" : "text-muted-foreground"}`}>
          {formatDue(item.dueDate, board.date)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="text-sm font-medium text-foreground">{item.contact.name}</span>
          <span className="ml-2 text-xs text-muted-foreground">
            {item.campaignName} · day {item.day}
          </span>
        </span>
        <ChannelBadge channel={item.channel} />
        <span className="text-xs text-foreground">{item.title}</span>
        {item.contact.segment && <SegmentChip segment={segment} label={segment?.label ?? item.contact.segment} />}
        {item.videoMissing && <Badge variant="warning">video not recorded</Badge>}
        {item.taskId && <Badge variant="outline">on your tasks</Badge>}
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-border px-3 py-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.72rem] text-muted-foreground">
            {item.contact.phone && <span>{item.contact.phone}</span>}
            {item.contact.email && <span>{item.contact.email}</span>}
          </div>
          {isRoute ? (
            <div className="flex flex-col gap-2">
              <p className="whitespace-pre-line text-xs leading-5 text-foreground">{item.body}</p>
              <p className="text-[0.72rem] text-muted-foreground">
                Move them by what they told you. Leave it and the engine applies the default on its next run
                {item.routeTo && item.routeTo !== "done" && item.routeTo !== "restart" ? ` (${segments.find((s) => s.key === item.routeTo)?.label ?? item.routeTo})` : ""}.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {segments.filter((s) => s.enabled).map((s) => (
                  <Button key={s.key} variant="outline" size="sm" disabled={busy || preview} onClick={() => void routeTo(s.key)}>
                    <span className="h-2 w-2 rounded-full" style={{ background: s.color ?? "var(--color-muted-foreground)" }} aria-hidden="true" />
                    {s.label}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {item.subject && <div className="text-xs font-medium text-foreground">Subject: {item.subject}</div>}
              <pre className="whitespace-pre-wrap rounded-md border border-border bg-muted/20 px-3 py-2 font-sans text-xs leading-5 text-foreground">{item.body}</pre>
              {item.placeholders.length > 0 && (
                <Note tone="warning">Still to fill in by hand: {item.placeholders.join(", ")}</Note>
              )}
              {item.videoMissing && item.video && (
                <Note tone="warning">
                  This touch names the {item.video.name} video, which is not recorded yet. Record it on the Videos tab or delete the video line before sending.
                </Note>
              )}
              {item.notes && <p className="text-[0.72rem] leading-5 text-muted-foreground">{item.notes}</p>}
            </>
          )}
          {!preview && (
            <div className="flex flex-wrap items-center gap-2">
              {!isRoute && (
                <Button variant="outline" size="sm" onClick={() => void copyText()} disabled={busy}>
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                  {copied ? "Copied" : "Copy message"}
                </Button>
              )}
              {!isRoute && (
                <Button size="sm" onClick={() => void onAct(item.id, () => api.completeDripTouch(item.id, "done"))} disabled={busy}>
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  {item.channel === "call" || item.channel === "task" ? "Done" : "Mark sent"}
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => void onAct(item.id, () => api.completeDripTouch(item.id, "skipped"))} disabled={busy}>
                <SkipForward className="h-3.5 w-3.5" aria-hidden="true" />
                Skip
              </Button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
