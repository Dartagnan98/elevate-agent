import { ArrowUpRight, Clock, FileCheck, Flame, ServerCog } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { UrgentItem } from "./data";

const ICON_MAP: Record<UrgentItem["kind"], React.ComponentType<{ className?: string }>> = {
  draft: FileCheck,
  "hot-lead": Flame,
  "deal-task": ServerCog,
  "action-run": ServerCog,
};

const KIND_LABEL: Record<UrgentItem["kind"], string> = {
  draft: "Draft",
  "hot-lead": "Lead",
  "deal-task": "Admin",
  "action-run": "Action",
};

export function PriorityQueue({ items }: { items: UrgentItem[] }) {
  return (
    <section
      aria-label="Needs you now"
      className="rounded-md border border-border bg-card"
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div>
          <h2 className="text-[0.95rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Needs you now
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {items.length === 0 ? "Inbox is clear" : `${items.length} waiting`}
          </p>
        </div>
        <Link
          to="/leads"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Open leads
          <ArrowUpRight className="h-3 w-3" />
        </Link>
      </header>
      {items.length === 0 ? (
        <p className="px-3.5 py-3 text-xs text-muted-foreground/80">
          Nothing waiting on you. Drafts auto-approve when nothing is flagged.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <PriorityRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function PriorityRow({ item }: { item: UrgentItem }) {
  const Icon = ICON_MAP[item.kind];
  return (
    <li>
      <Link
        to={item.to}
        className={cn(
          "group flex items-start gap-3 px-3.5 py-2.5",
          "transition-colors hover:bg-muted/40 focus-visible:bg-muted/40",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
      >
        <span
          className={cn(
            "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded",
            item.tone === "danger" && "bg-destructive/15 text-destructive",
            item.tone === "warn" && "bg-warning/15 text-warning",
            item.tone === "neutral" && "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[0.88rem] font-medium leading-5 text-foreground">
              {item.title}
            </span>
            <span className="font-mono-ui shrink-0 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
              {KIND_LABEL[item.kind]}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="truncate text-[0.78rem] leading-4 text-muted-foreground">
              {item.meta}
            </span>
            {item.waitedMinutes != null && (
              <span
                className={cn(
                  "font-mono-ui inline-flex shrink-0 items-center gap-0.5 text-[0.62rem] tabular-nums",
                  item.tone === "danger" && "text-destructive",
                  item.tone === "warn" && "text-warning",
                  item.tone === "neutral" && "text-muted-foreground",
                )}
              >
                <Clock className="h-2.5 w-2.5" />
                {formatWait(item.waitedMinutes)}
              </span>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}

function formatWait(minutes: number): string {
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}
