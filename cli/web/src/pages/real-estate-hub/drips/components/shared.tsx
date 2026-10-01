import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { DripChannel, DripSegment } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CHANNEL_LABELS, segmentColor } from "../drips-helpers";

export const fieldClass =
  "flex w-full rounded-sm border border-input bg-field px-3 py-1.5 font-sans text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70 disabled:cursor-not-allowed disabled:opacity-50";

export function SegmentChip({
  segment,
  label,
  className,
}: {
  segment?: DripSegment | null;
  label?: string;
  className?: string;
}) {
  const text = label ?? segment?.label ?? "No segment";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-0.5 text-[0.7rem] font-medium text-foreground",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: segment ? segmentColor(segment) : "var(--color-muted-foreground)" }}
      />
      {text}
    </span>
  );
}

const CHANNEL_VARIANT: Record<DripChannel, "default" | "secondary" | "success" | "warning" | "outline"> = {
  call: "warning",
  text: "default",
  email: "secondary",
  task: "outline",
  tag: "success",
};

export function ChannelBadge({ channel }: { channel: DripChannel }) {
  return <Badge variant={CHANNEL_VARIANT[channel]}>{CHANNEL_LABELS[channel]}</Badge>;
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-[0.72rem] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[0.72rem] leading-4 text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function Section({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-md border border-border bg-card", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[0.95rem] font-semibold leading-5 text-foreground">{title}</h2>
          {hint && <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{hint}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Note({
  tone = "info",
  children,
  className,
}: {
  tone?: "info" | "error" | "success" | "warning";
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-border bg-muted/30 text-muted-foreground",
    error: "border-destructive/40 bg-destructive/10 text-destructive",
    success: "border-success/40 bg-success/10 text-success",
    warning: "border-warning/40 bg-warning/10 text-warning",
  } as const;
  return (
    <div role={tone === "error" ? "alert" : undefined} className={cn("rounded-md border px-3 py-2 text-xs leading-5", tones[tone], className)}>
      {children}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-center">
      <p className="text-sm font-medium text-foreground">{title}</p>
      {hint && <p className="max-w-md text-xs leading-5 text-muted-foreground">{hint}</p>}
      {action}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex min-w-[7rem] flex-col gap-0.5 rounded-md border border-border bg-card px-3 py-2">
      <span className="font-mono-ui text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold leading-6 text-foreground">{value}</span>
      {hint && <span className="text-[0.7rem] text-muted-foreground">{hint}</span>}
    </div>
  );
}
