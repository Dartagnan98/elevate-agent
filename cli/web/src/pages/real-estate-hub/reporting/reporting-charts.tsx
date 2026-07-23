import { useId } from "react";
import type { ReportingTrendPoint } from "./reporting-data";

/**
 * Hand-built SVG charts ported from design/crm-redesign/03-reporting.html
 * (hbars() and combo()). All colors come from route-scoped CSS custom
 * properties in reporting.css; every bar/point carries an SVG <title> so
 * screen readers and hover both get the real value.
 */

export interface HBarRow {
  id: string;
  label: string;
  /** null = this stage/row has no data source; rendered as an explicit gap. */
  value: number | null;
  accent?: boolean;
  note?: string;
}

const HBAR_WIDTH = 560;

export function HBars({
  rows,
  ariaLabel,
  fmt = (value: number) => value.toLocaleString("en-CA"),
  showPct = false,
  pctFor,
  padL = 128,
  padR = 54,
  rowH = 34,
  gap = 8,
}: {
  rows: HBarRow[];
  ariaLabel: string;
  fmt?: (value: number) => string;
  /** Render the mockup's right-hand "kept from stage above" column. */
  showPct?: boolean;
  /** Percent shown in the right column for a row (funnel keptPct). */
  pctFor?: (row: HBarRow, index: number) => number | null;
  padL?: number;
  padR?: number;
  rowH?: number;
  gap?: number;
}) {
  const top = 6;
  const measured = rows.map((row) => row.value).filter((v): v is number => v !== null);
  const max = Math.max(...measured, 1);
  const barW = HBAR_WIDTH - padL - padR;
  const height = top + rows.length * (rowH + gap);

  return (
    <svg
      className="rc-svg"
      viewBox={`0 0 ${HBAR_WIDTH} ${height}`}
      role="img"
      aria-label={ariaLabel}
    >
      {rows.map((row, index) => {
        const y = top + index * (rowH + gap);
        const midY = y + rowH / 2 + 4;
        const pct = showPct && pctFor ? pctFor(row, index) : null;
        return (
          <g key={row.id}>
            <rect x={padL} y={y} width={barW} height={rowH} rx={7} className="rc-track" />
            {row.value !== null ? (
              <rect
                x={padL}
                y={y}
                width={Math.max(3, barW * (row.value / max))}
                height={rowH}
                rx={7}
                className={row.accent ? "rc-bar rc-bar-accent" : "rc-bar"}
              >
                <title>{`${row.label} · ${fmt(row.value)}`}</title>
              </rect>
            ) : null}
            <text x={padL - 12} y={midY} textAnchor="end" fontSize={13} className="rc-lbl">
              {row.label}
            </text>
            <text
              x={padL + (row.value !== null ? Math.max(3, barW * (row.value / max)) : 0) + 8}
              y={midY}
              fontSize={row.value !== null ? 13 : 12}
              className={row.value !== null ? "rc-val" : "rc-gap"}
            >
              {row.value !== null ? fmt(row.value) : (row.note ?? "No data source yet")}
            </text>
            {showPct ? (
              <text x={HBAR_WIDTH - 2} y={midY} textAnchor="end" fontSize={11} className="rc-axl">
                {pct !== null ? `${pct}%` : index > 0 ? "—" : ""}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Combo trend: leads as area+line on the real y-axis; closings overlaid as a
 * dashed accent line inside its own visual band (bottom ~14-64% of the plot)
 * with real point labels — deliberately NOT a second axis. When the leads
 * series is unavailable the closings line still renders with its labels.
 */
export function ComboChart({
  leads,
  sales,
  ariaLabel,
}: {
  leads: ReportingTrendPoint[] | null;
  sales: ReportingTrendPoint[];
  ariaLabel: string;
}) {
  // React 19 useId emits guillemet-wrapped ids; strip anything unsafe for a
  // CSS url(#...) fragment reference while keeping the unique counter.
  const gradientId = `rc-area-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const W = 1120;
  const H = 300;
  const padL = 46;
  const padR = 30;
  const padT = 40;
  const padB = 34;
  const iw = W - padL - padR;
  const ih = H - padT - padB;
  const n = sales.length;
  if (n === 0) return null;

  const x = (index: number) => padL + iw * (n > 1 ? index / (n - 1) : 0.5);

  const leadMax = leads && leads.length > 0
    ? Math.max(...leads.map((point) => point.value), 1) * 1.2
    : 1;
  const y1 = (value: number) => padT + ih * (1 - value / leadMax);

  const saleValues = sales.map((point) => point.value);
  const saleMin = Math.min(...saleValues);
  const saleMax = Math.max(...saleValues);
  const y2 = (value: number) => {
    const t = (value - saleMin) / (saleMax - saleMin || 1);
    return padT + ih - (0.14 * ih + t * 0.5 * ih);
  };

  const leadsPath = leads && leads.length > 0
    ? leads.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y1(point.value)}`).join(" ")
    : null;
  const salesPath = sales
    .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y2(point.value)}`)
    .join(" ");

  return (
    <svg className="rc-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
      <defs>
        <linearGradient id={gradientId} x1={0} y1={0} x2={0} y2={1}>
          <stop offset="0%" className="rc-area-stop-a" />
          <stop offset="100%" className="rc-area-stop-b" />
        </linearGradient>
      </defs>

      {leads && leads.length > 0
        ? [0, 1, 2, 3].map((g) => {
            const gy = padT + (ih * g) / 3;
            return (
              <g key={g}>
                <line x1={padL} y1={gy} x2={W - padR} y2={gy} className="rc-grid" />
                <text x={padL - 8} y={gy + 4} textAnchor="end" fontSize={11} className="rc-axl">
                  {Math.round(leadMax * (1 - g / 3))}
                </text>
              </g>
            );
          })
        : null}

      {leadsPath ? (
        <>
          <path
            d={`${leadsPath} L ${x((leads as ReportingTrendPoint[]).length - 1)} ${padT + ih} L ${x(0)} ${padT + ih} Z`}
            fill={`url(#${gradientId})`}
          />
          <path d={leadsPath} className="rc-line" />
        </>
      ) : null}

      <path d={salesPath} className="rc-line-accent" />

      {sales.map((point, index) => (
        <g key={point.id}>
          {leads && leads[index] ? (
            <circle cx={x(index)} cy={y1(leads[index].value)} r={3.5} className="rc-dot">
              <title>{`${point.label} · ${leads[index].value.toLocaleString("en-CA")} leads`}</title>
            </circle>
          ) : null}
          <circle cx={x(index)} cy={y2(point.value)} r={3.5} className="rc-dot-accent">
            <title>{`${point.label} · ${point.value.toLocaleString("en-CA")} closings`}</title>
          </circle>
          <text
            x={x(index)}
            y={y2(point.value) - 9}
            textAnchor="middle"
            fontSize={11}
            className="rc-val rc-val-accent"
          >
            {point.value}
          </text>
          <text x={x(index)} y={H - 12} textAnchor="middle" fontSize={11} className="rc-axl">
            {point.label}
          </text>
        </g>
      ))}

      {leads && leads.length > 0 ? (
        <g>
          <line x1={padL} y1={16} x2={padL + 22} y2={16} className="rc-line" />
          <text x={padL + 28} y={20} fontSize={12} className="rc-legt">
            New leads
          </text>
          <line x1={padL + 120} y1={16} x2={padL + 142} y2={16} className="rc-line-accent" />
          <text x={padL + 148} y={20} fontSize={12} className="rc-legt">
            Closings
          </text>
        </g>
      ) : (
        <g>
          <line x1={padL} y1={16} x2={padL + 22} y2={16} className="rc-line-accent" />
          <text x={padL + 28} y={20} fontSize={12} className="rc-legt">
            Closings
          </text>
        </g>
      )}
    </svg>
  );
}
