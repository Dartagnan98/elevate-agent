import type { DayBucket, HourBucket } from "./data";

export function DayShape({
  hourBuckets,
  dayBuckets,
}: {
  hourBuckets: HourBucket[];
  dayBuckets: DayBucket[];
}) {
  return (
    <section aria-label="Day shape" className="grid gap-3 lg:grid-cols-2">
      <TodayHourly buckets={hourBuckets} />
      <WeekRollup buckets={dayBuckets} />
    </section>
  );
}

function TodayHourly({ buckets }: { buckets: HourBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.leadsIn + b.repliesOut));
  const width = 320;
  const height = 88;
  const padX = 4;
  const stepX = (width - padX * 2) / Math.max(1, buckets.length - 1);
  const leadsLine = buckets
    .map((b, i) => `${padX + i * stepX},${height - (b.leadsIn / max) * (height - 8) - 4}`)
    .join(" ");
  const repliesLine = buckets
    .map((b, i) => `${padX + i * stepX},${height - (b.repliesOut / max) * (height - 8) - 4}`)
    .join(" ");
  const totalLeads = buckets.reduce((sum, b) => sum + b.leadsIn, 0);
  const totalReplies = buckets.reduce((sum, b) => sum + b.repliesOut, 0);
  const noActivity = totalLeads === 0 && totalReplies === 0;

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-[0.9rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Today, hour by hour
          </h3>
          <p className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
            Inbound vs outbound
          </p>
        </div>
        <div className="flex items-center gap-2.5 text-[0.7rem]">
          <Legend swatch="var(--primary)" label={`${totalLeads} in`} />
          <Legend swatch="var(--muted-foreground)" label={`${totalReplies} out`} />
        </div>
      </header>
      <svg
        aria-hidden="true"
        className="w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {/* gridlines */}
        {[0.25, 0.5, 0.75].map((p) => (
          <line
            key={p}
            x1={padX}
            x2={width - padX}
            y1={height - p * (height - 8) - 4}
            y2={height - p * (height - 8) - 4}
            stroke="var(--border)"
            strokeDasharray="2 3"
            strokeWidth={0.6}
          />
        ))}
        {!noActivity && (
          <>
            <polyline
              fill="none"
              points={repliesLine}
              stroke="var(--muted-foreground)"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.25}
            />
            <polyline
              fill="none"
              points={leadsLine}
              stroke="var(--primary)"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.75}
            />
          </>
        )}
        {noActivity && (
          <text
            fill="var(--muted-foreground)"
            fontSize={9}
            textAnchor="middle"
            x={width / 2}
            y={height / 2 + 2}
          >
            No activity today yet
          </text>
        )}
      </svg>
      <div className="font-mono-ui mt-1 flex justify-between text-[0.58rem] uppercase tracking-[0.12em] text-muted-foreground">
        {[0, 6, 12, 18, 23].map((h) => (
          <span key={h}>{buckets[h]?.label ?? ""}</span>
        ))}
      </div>
    </div>
  );
}

function WeekRollup({ buckets }: { buckets: DayBucket[] }) {
  const max = Math.max(
    1,
    ...buckets.map((b) => b.leadsIn + b.repliesOut + b.dealsAdvanced),
  );
  const width = 320;
  const height = 88;
  const padX = 6;
  const padY = 4;
  const colCount = buckets.length;
  const colWidth = (width - padX * 2) / colCount;
  const barWidth = Math.max(8, colWidth * 0.6);

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-[0.9rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Last 7 days
          </h3>
          <p className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
            Leads · replies · deals advanced
          </p>
        </div>
        <div className="flex items-center gap-2.5 text-[0.7rem]">
          <Legend swatch="var(--primary)" label="In" />
          <Legend swatch="var(--muted-foreground)" label="Out" />
          <Legend swatch="var(--success)" label="Deals" />
        </div>
      </header>
      <svg
        aria-hidden="true"
        className="w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {buckets.map((bucket, i) => {
          const total = bucket.leadsIn + bucket.repliesOut + bucket.dealsAdvanced;
          const colX = padX + i * colWidth + (colWidth - barWidth) / 2;
          const usableHeight = height - padY * 2 - 10;
          const inH = total > 0 ? (bucket.leadsIn / max) * usableHeight : 0;
          const outH = total > 0 ? (bucket.repliesOut / max) * usableHeight : 0;
          const dealH = total > 0 ? (bucket.dealsAdvanced / max) * usableHeight : 0;
          let yCursor = height - padY - 10;
          const inY = yCursor - inH;
          yCursor = inY;
          const outY = yCursor - outH;
          yCursor = outY;
          const dealY = yCursor - dealH;
          const isToday = i === buckets.length - 1;
          return (
            <g key={bucket.iso}>
              {bucket.dealsAdvanced > 0 && (
                <rect
                  x={colX}
                  y={dealY}
                  width={barWidth}
                  height={dealH}
                  fill="var(--success)"
                  opacity={0.85}
                  rx={1}
                />
              )}
              {bucket.repliesOut > 0 && (
                <rect
                  x={colX}
                  y={outY}
                  width={barWidth}
                  height={outH}
                  fill="var(--muted-foreground)"
                  opacity={0.6}
                  rx={1}
                />
              )}
              {bucket.leadsIn > 0 && (
                <rect
                  x={colX}
                  y={inY}
                  width={barWidth}
                  height={inH}
                  fill="var(--primary)"
                  rx={1}
                />
              )}
              <text
                fill={isToday ? "var(--foreground)" : "var(--muted-foreground)"}
                fontFamily="var(--font-mono)"
                fontSize={8}
                fontWeight={isToday ? 600 : 400}
                textAnchor="middle"
                x={colX + barWidth / 2}
                y={height - 1}
              >
                {bucket.label.toUpperCase()}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-sm"
        style={{ backgroundColor: swatch }}
      />
      <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.12em]">{label}</span>
    </span>
  );
}
