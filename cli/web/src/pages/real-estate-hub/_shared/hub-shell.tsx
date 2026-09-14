import type { ComponentType, ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LoadingState } from "./loading-state";
import type { HubData } from "./types";

export function HubDataErrorBanner({
  className,
  data,
}: {
  className?: string;
  data: HubData;
}) {
  if (!data.error) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "flex flex-col gap-3 rounded-md border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <span className="min-w-0 break-words">{data.error}</span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0 border-warning/40 text-warning hover:bg-warning/10"
        disabled={data.refreshing}
        onClick={() => void data.refresh({ force: true })}
      >
        <RefreshCw className={cn("h-3.5 w-3.5", data.refreshing && "animate-spin")} aria-hidden="true" />
        Retry
      </Button>
    </div>
  );
}

export function HubShell({
  children,
  data,
  eyebrow,
  icon: Icon,
  title,
}: {
  children: ReactNode;
  data: HubData;
  eyebrow: string;
  hero?: string;
  icon: ComponentType<{ className?: string }>;
  title: string;
}) {
  if (data.loading && !data.snapshot && !data.status) return <LoadingState />;

  const gatewayOnline = !!(data.snapshot?.gateway.running || data.status?.gateway_running);
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;

  return (
    <div className="real-estate-hub flex flex-col gap-4 pb-6">
      <section className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
        <div className="min-w-0 flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground font-semibold">
              {eyebrow}
            </div>
            <h1 className="text-xl font-semibold leading-tight text-foreground sm:text-[1.6rem]">
              {title}
            </h1>
          </div>
        </div>
        <div className="font-mono-ui flex items-center gap-2 text-[0.72rem] text-muted-foreground">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-xs",
              gatewayOnline ? "text-muted-foreground" : "text-destructive",
            )}
          >
            <span
              className={cn("h-1.5 w-1.5 rounded-full", gatewayOnline ? "bg-success" : "bg-destructive")}
            />
            Agent {gatewayOnline ? "online" : "offline"}
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            {activeJobs} job{activeJobs === 1 ? "" : "s"}
          </span>
        </div>
        <HubDataErrorBanner className="basis-full" data={data} />
      </section>

      {children}
    </div>
  );
}
