import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { PulseStat } from "./data";

export function PulseStrip({ stats }: { stats: PulseStat[] }) {
  const greeting = useMemo(() => greetingForNow(), []);
  return (
    <section aria-label="Today pulse" className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <div>
          <h2 className="text-[1.05rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            {greeting}
          </h2>
          <p className="font-mono-ui text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground">
            Today at a glance
          </p>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {stats.map((stat) => (
          <PulseCard key={stat.label} stat={stat} />
        ))}
      </div>
    </section>
  );
}

function PulseCard({ stat }: { stat: PulseStat }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border border-border bg-card px-3 py-2.5",
        "transition-colors",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-ui truncate text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
          {stat.label}
        </span>
        {stat.deltaLabel && (
          <span
            className={cn(
              "font-mono-ui text-[0.62rem] tabular-nums",
              stat.delta == null && "text-muted-foreground",
              stat.delta != null && stat.delta > 0 && "text-success",
              stat.delta != null && stat.delta < 0 && "text-warning",
              stat.delta === 0 && "text-muted-foreground",
            )}
          >
            {stat.deltaLabel}
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-2">
        <span
          className={cn(
            "text-[1.4rem] font-semibold leading-none tabular-nums tracking-[-0.01em]",
            stat.tone === "danger" && "text-destructive",
            stat.tone === "warn" && "text-warning",
            stat.tone === "good" && "text-foreground",
            stat.tone === "neutral" && "text-foreground",
          )}
        >
          {stat.value}
        </span>
        <Sparkline values={stat.spark} tone={stat.tone} />
      </div>
    </div>
  );
}

function Sparkline({ values, tone }: { values: number[]; tone: PulseStat["tone"] }) {
  const width = 64;
  const height = 20;
  const safe = values.length > 0 ? values : [0];
  const max = Math.max(1, ...safe);
  const stepX = safe.length > 1 ? width / (safe.length - 1) : width;
  const points = safe
    .map((v, i) => {
      const x = safe.length === 1 ? width / 2 : i * stepX;
      const y = height - (v / max) * (height - 2) - 1;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const areaPoints = `0,${height} ${points} ${width},${height}`;
  const stroke =
    tone === "danger"
      ? "var(--destructive)"
      : tone === "warn"
        ? "var(--warning)"
        : tone === "good"
          ? "var(--success)"
          : "var(--muted-foreground)";
  return (
    <svg
      aria-hidden="true"
      className="shrink-0"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
    >
      <polygon fill={stroke} opacity={0.12} points={areaPoints} />
      <polyline fill="none" points={points} stroke={stroke} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.25} />
    </svg>
  );
}

function greetingForNow(): string {
  const hour = new Date().getHours();
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  if (hour < 21) return "Good evening";
  return "Late night";
}
