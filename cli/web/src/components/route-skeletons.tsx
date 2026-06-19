import type { ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { AgentHubSkeleton } from "@/components/agent-hub/AgentHubSkeleton";
import { Button } from "@/components/ui/button";
import { BoardSkeleton, ListSkeleton, PageSkeleton, Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type RouteSkeletonProps = {
  className?: string;
  path?: string;
};

type RouteLoadErrorProps = {
  title: string;
  error: unknown;
  onRetry?: () => void | Promise<void>;
  retryLabel?: string;
  className?: string;
};

function normalizePath(path?: string) {
  if (!path) return "/";
  return path.split("?")[0].replace(/\/+$/, "") || "/";
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (error == null) return "Unknown error";
  return String(error);
}

export function RouteLoadError({
  title,
  error,
  onRetry,
  retryLabel = "Retry",
  className,
}: RouteLoadErrorProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-medium">{title}</p>
          <p className="mt-1 break-words text-xs text-destructive/80">
            {errorMessage(error)}
          </p>
        </div>
      </div>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 border-destructive/40 text-destructive hover:bg-destructive/10"
          onClick={() => void onRetry()}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

function Shell({
  children,
  className,
  srLabel = "Loading view",
}: {
  children: ReactNode;
  className?: string;
  srLabel?: string;
}) {
  return (
    <div role="status" aria-live="polite" className={cn("w-full", className)}>
      <span className="sr-only">{srLabel}</span>
      {children}
    </div>
  );
}

function HeaderSkeleton({ actions = 2 }: { actions?: number }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 pb-4">
      <div className="flex min-w-0 items-center gap-3">
        <Skeleton className="h-9 w-9 rounded-xl" />
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-56 max-w-[70vw]" />
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        {Array.from({ length: actions }).map((_, index) => (
          <Skeleton key={index} className={cn("h-9 rounded-md", index === 0 ? "w-24" : "w-9")} />
        ))}
      </div>
    </div>
  );
}

function MetricStripSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="min-h-[5.25rem] rounded-lg border border-border bg-card/60 p-4">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="mt-3 h-7 w-16" />
          <Skeleton className="mt-2 h-3 w-32 max-w-full" />
        </div>
      ))}
    </div>
  );
}

function DashboardSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("real-estate-hub flex min-h-[calc(100dvh-6rem)] flex-col gap-4 pb-6", className)}>
      <HeaderSkeleton />
      <MetricStripSkeleton />
      <div className="grid min-h-[32rem] gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4 rounded-lg border border-border bg-card/55 p-4">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-5 w-36" />
            <Skeleton className="h-8 w-24 rounded-md" />
          </div>
          <BoardSkeleton columns={3} rows={3} />
        </div>
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card/55 p-4">
            <Skeleton className="h-5 w-32" />
            <div className="mt-4">
              <ListSkeleton rows={4} />
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card/55 p-4">
            <Skeleton className="h-5 w-28" />
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <Skeleton className="h-20 rounded-lg" />
              <Skeleton className="h-20 rounded-lg" />
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}

function ListPageSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("min-h-[calc(100dvh-8rem)] space-y-5", className)}>
      <HeaderSkeleton />
      <div className="grid gap-3 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <div className="rounded-lg border border-border bg-card/55 p-4">
          <Skeleton className="h-4 w-24" />
          <div className="mt-4 space-y-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-9 rounded-md" />
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-border bg-card/55 p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-9 w-48 rounded-md" />
          </div>
          <ListSkeleton rows={6} />
        </div>
      </div>
    </Shell>
  );
}

function BoardPageSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("min-h-[calc(100dvh-8rem)] space-y-5", className)}>
      <HeaderSkeleton />
      <MetricStripSkeleton count={3} />
      <BoardSkeleton columns={4} rows={4} />
    </Shell>
  );
}

function FormPageSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("min-h-[calc(100dvh-8rem)] space-y-5", className)}>
      <HeaderSkeleton actions={1} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="rounded-lg border border-border bg-card/55 p-4">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="mt-3 h-10 w-full rounded-md" />
              <Skeleton className="mt-3 h-3.5 w-4/5" />
            </div>
          ))}
        </div>
        <div className="rounded-lg border border-border bg-card/55 p-4">
          <Skeleton className="h-5 w-40" />
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="space-y-2">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-10 w-full rounded-md" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </Shell>
  );
}

function ChatSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("flex min-h-[calc(100dvh-4rem)] flex-col bg-[var(--chat-bg)]", className)}>
      <div className="flex-1 space-y-5 px-4 py-6 sm:px-8">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className={cn("flex", index % 2 ? "justify-end" : "justify-start")}>
            <div className={cn("space-y-2 rounded-xl border border-border bg-card/50 p-4", index % 2 ? "w-[min(34rem,78%)]" : "w-[min(42rem,88%)]")}>
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-border/60 p-4">
        <Skeleton className="mx-auto h-14 w-full max-w-4xl rounded-xl" />
      </div>
    </Shell>
  );
}

function DocsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("grid min-h-[calc(100dvh-8rem)] gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]", className)}>
      <div className="space-y-2 border-r border-border/60 pr-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-8 rounded-md" />
        ))}
      </div>
      <div className="max-w-4xl space-y-5">
        <Skeleton className="h-8 w-72 max-w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </Shell>
  );
}

/* ---- shared sub-shapes ------------------------------------------------ */

function TabsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="flex gap-4 border-b border-border/60 pb-px">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-28 rounded-md" />
      ))}
    </div>
  );
}

function PillRowSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="flex flex-wrap gap-2">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-20 rounded-full" />
      ))}
    </div>
  );
}

function CardListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-border bg-card/60 p-3">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-3.5 w-4/5" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---- per-page skeletons (match each page 1:1) ------------------------- */

// /cron — Automations: header + 3-way segmented + [280px | 1fr] two-pane
function CronSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("flex flex-col gap-4", className)}>
      <HeaderSkeleton actions={3} />
      <Skeleton className="h-9 w-72 rounded-md" />
      <div className="grid min-h-[calc(100vh-12rem)] gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2 rounded-lg border border-border bg-card/40 p-3">
          <Skeleton className="h-4 w-36" />
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md border border-border/60 p-2">
              <Skeleton className="h-2 w-2 rounded-full" />
              <Skeleton className="h-4 flex-1" />
            </div>
          ))}
        </div>
        <div className="space-y-4 rounded-lg border border-border bg-card/40 p-4">
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-4 w-32" />
              </div>
            ))}
          </div>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-40 w-full rounded-md" />
        </div>
      </div>
    </Shell>
  );
}

// /overview — header + 4 metrics + action card + two list cards + wide card
function OverviewSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto max-w-6xl space-y-5", className)}>
      <HeaderSkeleton actions={1} />
      <MetricStripSkeleton count={4} />
      <div className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
        <Skeleton className="h-5 w-40" />
        <ListSkeleton rows={2} />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.85fr)]">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-16" />
            </div>
            <ListSkeleton rows={i === 0 ? 6 : 5} />
          </div>
        ))}
      </div>
      <div className="grid gap-5 rounded-lg border border-border bg-card/60 p-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-4 w-28" />
            <ListSkeleton rows={4} />
          </div>
        ))}
      </div>
    </Shell>
  );
}

// /experiments — header + 5 stat tiles + 3 tabs + stack of agent cards
function ExperimentsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto max-w-4xl space-y-6", className)}>
      <HeaderSkeleton actions={1} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-2 rounded-lg border border-border bg-card/60 p-3">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-12" />
          </div>
        ))}
      </div>
      <TabsSkeleton count={3} />
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex items-center justify-between rounded-lg border border-border bg-card/60 p-4">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-5 w-24 rounded-full" />
          </div>
        ))}
      </div>
    </Shell>
  );
}

// /tasks — header + view toggle + filter row + 4-col kanban
function TasksSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto max-w-6xl space-y-4", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 pb-4">
        <Skeleton className="h-7 w-28" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-40 rounded-md" />
          <Skeleton className="h-9 w-24 rounded-md" />
        </div>
      </div>
      <PillRowSkeleton count={5} />
      <BoardSkeleton columns={4} rows={3} />
    </Shell>
  );
}

// /approvals — header + 3 tabs (count badges) + card list
function ApprovalsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto max-w-4xl space-y-6 pb-16", className)}>
      <HeaderSkeleton actions={1} />
      <TabsSkeleton count={3} />
      <CardListSkeleton rows={5} />
    </Shell>
  );
}

// /comms — header + 3 tabs + agent filter row + [1fr | 300px] two-pane
function CommsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto max-w-6xl space-y-6 pb-16", className)}>
      <HeaderSkeleton actions={1} />
      <TabsSkeleton count={3} />
      <PillRowSkeleton count={6} />
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="space-y-3">
          <Skeleton className="h-9 w-full rounded-md" />
          <CardListSkeleton rows={5} />
        </div>
        <div className="space-y-3">
          <Skeleton className="h-32 w-full rounded-lg" />
          <ListSkeleton rows={5} />
        </div>
      </div>
    </Shell>
  );
}

// /activity — header + agent filter pills + icon|content|time feed
function ActivitySkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("mx-auto w-full max-w-3xl space-y-6 pb-16", className)}>
      <HeaderSkeleton actions={1} />
      <PillRowSkeleton count={4} />
      <ul className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <li key={i} className="flex items-start gap-3 rounded-lg border border-border bg-card/60 p-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-4 w-16 rounded-full" />
              </div>
              <Skeleton className="h-4 w-4/5" />
            </div>
            <Skeleton className="h-3 w-12 shrink-0" />
          </li>
        ))}
      </ul>
    </Shell>
  );
}

// /sessions — recent-sessions preview grid (5) + session row list + pager
function SessionsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("flex flex-col gap-4", className)}>
      <HeaderSkeleton actions={1} />
      <div className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
        <Skeleton className="h-4 w-32" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="space-y-2 rounded-lg border border-border/60 p-3">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-3 w-full" />
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 rounded-lg border border-border bg-card/60 p-3">
            <Skeleton className="h-5 w-5 rounded" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-8 w-8 rounded-md" />
            <Skeleton className="h-8 w-8 rounded-md" />
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <Skeleton className="h-3 w-28" />
        <div className="flex gap-2">
          <Skeleton className="h-8 w-20 rounded-md" />
          <Skeleton className="h-8 w-16 rounded-md" />
        </div>
      </div>
    </Shell>
  );
}

// /skills — header + [280px | 1fr] two-pane (group rail + detail pane)
function SkillsSkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("flex flex-col gap-4", className)}>
      <HeaderSkeleton actions={2} />
      <div className="grid min-h-[calc(100vh-12rem)] gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2 rounded-lg border border-border bg-card/40 p-3">
          <Skeleton className="h-4 w-20" />
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md border border-border/60 p-2">
              <Skeleton className="h-4 w-4 rounded" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-4 w-10 rounded-full" />
            </div>
          ))}
        </div>
        <div className="space-y-4 rounded-lg border border-border bg-card/40 p-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-6 w-12 rounded-full" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-10 rounded-md" />
            <Skeleton className="h-10 rounded-md" />
          </div>
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-8 w-2/3 rounded-md" />
          <Skeleton className="h-64 w-full rounded-md" />
        </div>
      </div>
    </Shell>
  );
}

// /memory — Memory graph: 3 metric tiles + [graph canvas | ingest sidebar]
function MemorySkeleton({ className }: { className?: string }) {
  return (
    <Shell className={cn("space-y-4", className)}>
      <div className="grid gap-3 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2 rounded-lg border border-border bg-card/60 p-4">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-6 w-28" />
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-5 w-24 rounded-full" />
          </div>
          <Skeleton className="h-[28rem] w-full rounded-lg" />
        </div>
        <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3.5 w-2/3" />
          <ListSkeleton rows={6} />
        </div>
      </div>
    </Shell>
  );
}

export function RouteSkeleton({ className, path }: RouteSkeletonProps) {
  const normalizedPath = normalizePath(path);

  if (normalizedPath === "/hub") return <AgentHubSkeleton />;

  // Per-page skeletons that mirror each view's real layout 1:1.
  if (normalizedPath === "/cron") return <CronSkeleton className={className} />;
  if (normalizedPath === "/overview") return <OverviewSkeleton className={className} />;
  if (normalizedPath === "/experiments") return <ExperimentsSkeleton className={className} />;
  if (normalizedPath === "/tasks") return <TasksSkeleton className={className} />;
  if (normalizedPath === "/approvals") return <ApprovalsSkeleton className={className} />;
  if (normalizedPath === "/comms") return <CommsSkeleton className={className} />;
  if (normalizedPath === "/activity") return <ActivitySkeleton className={className} />;
  if (normalizedPath === "/sessions") return <SessionsSkeleton className={className} />;
  if (normalizedPath === "/skills") return <SkillsSkeleton className={className} />;
  if (normalizedPath === "/memory") return <MemorySkeleton className={className} />;

  if (normalizedPath === "/" || normalizedPath === "/today" || normalizedPath === "/admin" || normalizedPath === "/leads" || normalizedPath === "/social-media") {
    return <DashboardSkeleton className={className} />;
  }
  if (normalizedPath === "/chat") return <ChatSkeleton className={className} />;
  if (normalizedPath === "/docs") return <DocsSkeleton className={className} />;
  if (["/config", "/env", "/desktop-setup", "/project", "/agent-onboarding"].includes(normalizedPath)) {
    return <FormPageSkeleton className={className} />;
  }
  if (["/logs"].includes(normalizedPath)) {
    return <ListPageSkeleton className={className} />;
  }
  if (["/heartbeat", "/analytics"].includes(normalizedPath)) {
    return <BoardPageSkeleton className={className} />;
  }

  return (
    <Shell className={cn("min-h-[20rem] p-4", className)}>
      <PageSkeleton rows={4} />
    </Shell>
  );
}
