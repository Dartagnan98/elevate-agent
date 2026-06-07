import { cn } from "@/lib/utils";

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded bg-muted", className)}
      {...props}
    />
  );
}

export function TextSkeleton({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2.5", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn(
            "h-3.5",
            index === lines - 1 ? "w-2/3" : index % 2 ? "w-5/6" : "w-full",
          )}
        />
      ))}
    </div>
  );
}

export function ListSkeleton({
  rows = 5,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-3", className)} aria-busy="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="min-h-[4.75rem] rounded-lg border border-border bg-card/60 p-4">
          <div className="flex items-start gap-3">
            <Skeleton className="h-10 w-10 shrink-0 rounded-md" />
            <div className="min-w-0 flex-1 space-y-2.5">
              <Skeleton className="h-4 w-2/5" />
              <TextSkeleton lines={2} />
            </div>
            <Skeleton className="h-6 w-16 shrink-0 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function BoardSkeleton({
  columns = 4,
  rows = 3,
  className,
}: {
  columns?: number;
  rows?: number;
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))]", className)}
      aria-busy="true"
    >
      {Array.from({ length: columns }).map((_, columnIndex) => (
        <div key={columnIndex} className="min-h-[18rem] space-y-3 rounded-lg border border-border bg-card/50 p-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-6 w-9 rounded-full" />
          </div>
          {Array.from({ length: rows }).map((_, rowIndex) => (
            <div key={rowIndex} className="min-h-[4.25rem] space-y-2.5 rounded-md border border-border bg-background/70 p-3">
              <Skeleton className="h-4 w-3/4" />
              <TextSkeleton lines={2} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton({
  rows = 5,
  variant = "list",
  className,
}: {
  rows?: number;
  variant?: "list" | "board" | "form";
  className?: string;
}) {
  return (
    <div className={cn("min-h-[calc(100dvh-8rem)] space-y-6", className)} aria-busy="true">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2.5">
          <Skeleton className="h-6 w-48 max-w-full" />
          <Skeleton className="h-3.5 w-80 max-w-full" />
        </div>
        <div className="flex shrink-0 gap-2">
          <Skeleton className="h-9 w-24 rounded-md" />
          <Skeleton className="h-9 w-9 rounded-md" />
        </div>
      </div>
      {variant === "board" ? (
        <BoardSkeleton rows={Math.max(3, Math.min(rows, 5))} />
      ) : variant === "form" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: rows }).map((_, index) => (
            <div key={index} className="min-h-[5.75rem] space-y-3 rounded-lg border border-border bg-card/60 p-4">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      ) : (
        <ListSkeleton rows={rows} />
      )}
    </div>
  );
}
