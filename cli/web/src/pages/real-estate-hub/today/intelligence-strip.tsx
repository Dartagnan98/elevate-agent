import {
  AlertTriangle,
  ArrowUpRight,
  Brain,
  CheckCircle2,
  DatabaseZap,
  FileCheck,
  GitPullRequest,
  Home,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { TodayIntelligenceItem } from "@/lib/api";
import { cn } from "@/lib/utils";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  approvals: FileCheck,
  pcs: Home,
  admin: CheckCircle2,
  identity: GitPullRequest,
  memory: Brain,
  source: DatabaseZap,
};

export function IntelligenceStrip({ items }: { items: TodayIntelligenceItem[] }) {
  if (!items.length) return null;

  return (
    <section aria-label="Operational intelligence" className="rounded-md border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div>
          <h2 className="text-[0.95rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Operational intelligence
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Live database signals the agent can read and act from
          </p>
        </div>
      </header>
      <div className="grid gap-px bg-border md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <IntelligenceCard key={item.id} item={item} />
        ))}
      </div>
    </section>
  );
}

function IntelligenceCard({ item }: { item: TodayIntelligenceItem }) {
  const Icon = ICONS[item.kind] ?? AlertTriangle;
  return (
    <Link
      to={item.to}
      className="group flex min-w-0 items-start gap-3 bg-card px-3.5 py-3 transition-colors hover:bg-muted/35 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <span
        className={cn(
          "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded",
          item.tone === "danger" && "bg-destructive/15 text-destructive",
          item.tone === "warn" && "bg-warning/15 text-warning",
          item.tone === "good" && "bg-success/15 text-success",
          item.tone === "neutral" && "bg-muted text-muted-foreground",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[0.82rem] font-medium leading-5 text-foreground">
            {item.title}
          </span>
          <ArrowUpRight className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <div className="mt-0.5 flex items-baseline gap-2">
          <span className="font-mono-ui text-[1.05rem] font-semibold leading-none tabular-nums text-foreground">
            {item.value.toLocaleString()}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {item.meta}
          </span>
        </div>
      </div>
    </Link>
  );
}
