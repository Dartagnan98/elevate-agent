import type { ReactNode } from "react";
import { AgentHubSkeleton } from "@/components/agent-hub/AgentHubSkeleton";
import { BoardSkeleton, ListSkeleton, PageSkeleton, Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type RouteSkeletonProps = {
  className?: string;
  path?: string;
};

function normalizePath(path?: string) {
  if (!path) return "/";
  return path.split("?")[0].replace(/\/+$/, "") || "/";
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

export function RouteSkeleton({ className, path }: RouteSkeletonProps) {
  const normalizedPath = normalizePath(path);

  if (normalizedPath === "/hub") return <AgentHubSkeleton />;
  if (normalizedPath === "/" || normalizedPath === "/today" || normalizedPath === "/admin" || normalizedPath === "/leads" || normalizedPath === "/social-media" || normalizedPath === "/memory") {
    return <DashboardSkeleton className={className} />;
  }
  if (normalizedPath === "/chat") return <ChatSkeleton className={className} />;
  if (normalizedPath === "/docs") return <DocsSkeleton className={className} />;
  if (["/config", "/env", "/desktop-setup", "/project", "/agent-onboarding"].includes(normalizedPath)) {
    return <FormPageSkeleton className={className} />;
  }
  if (["/sessions", "/logs", "/activity", "/approvals", "/comms"].includes(normalizedPath)) {
    return <ListPageSkeleton className={className} />;
  }
  if (["/tasks", "/cron", "/heartbeat", "/experiments", "/skills", "/analytics"].includes(normalizedPath)) {
    return <BoardPageSkeleton className={className} />;
  }

  return (
    <Shell className={cn("min-h-[20rem] p-4", className)}>
      <PageSkeleton rows={4} />
    </Shell>
  );
}
