import { useCallback, useMemo } from "react";
import type { CSSProperties } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  Database,
  Mail,
  Megaphone,
  MessageSquareText,
  Phone,
  RefreshCw,
  Target,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  HubDataErrorBanner,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";
import type {
  ReportingBreakdownRow,
  ReportingMetric,
  ReportingTrendPoint,
} from "./reporting-data";
import { useReportingData } from "./use-reporting-data";
import "./reporting.css";

const KPI_ICONS: Record<ReportingMetric["id"], LucideIcon> = {
  "new-leads": UsersRound,
  calls: Phone,
  texts: MessageSquareText,
  emails: Mail,
  appointments: CalendarDays,
  "lead-client": BarChart3,
};

function MetricCard({ metric }: { metric: ReportingMetric }) {
  const Icon = KPI_ICONS[metric.id];
  const statusLabel =
    metric.status === "available"
      ? "Recorded"
      : metric.status === "partial"
        ? "Partial history"
        : "Not available";

  return (
    <article className={`report-kpi is-${metric.status}`}>
      <div className="report-kpi-heading">
        <span className="report-kpi-icon" aria-hidden="true">
          <Icon />
        </span>
        <span className={`report-status-chip is-${metric.status}`}>{statusLabel}</span>
      </div>
      <strong className="report-kpi-value">{metric.displayValue}</strong>
      <h2>{metric.label}</h2>
      <p>{metric.note}</p>
    </article>
  );
}

function DataGapPanel({
  icon: Icon,
  title,
  description,
  requirement,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  requirement: string;
}) {
  return (
    <section className="report-panel report-gap" aria-labelledby={`gap-${title.replace(/\s+/g, "-").toLowerCase()}`}>
      <div className="report-panel-heading">
        <span className="report-panel-icon" aria-hidden="true"><Icon /></span>
        <div>
          <h2 id={`gap-${title.replace(/\s+/g, "-").toLowerCase()}`}>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <div className="report-gap-body">
        <Database aria-hidden="true" />
        <div>
          <strong>Waiting for a canonical data source</strong>
          <span>{requirement}</span>
        </div>
      </div>
    </section>
  );
}

function BreakdownBars({ rows }: { rows: ReportingBreakdownRow[] }) {
  const maximum = Math.max(...rows.map((row) => row.value), 1);
  return (
    <ul className="report-bars" aria-label="Closed deals by recorded source">
      {rows.map((row) => {
        const width = Math.max(4, (row.value / maximum) * 100);
        return (
          <li key={row.id}>
            <div className="report-bar-label">
              <span>{row.label}</span>
              <strong>{row.value.toLocaleString("en-CA")}</strong>
            </div>
            <div className="report-bar-track" aria-hidden="true">
              <span style={{ width: `${width}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ClosedSourcePanel({
  rows,
  partial,
  undated,
  year,
}: {
  rows: ReportingBreakdownRow[] | null;
  partial: boolean;
  undated: number;
  year: number;
}) {
  return (
    <section className="report-panel" aria-labelledby="closed-source-title">
      <div className="report-panel-heading">
        <span className="report-panel-icon" aria-hidden="true"><BarChart3 /></span>
        <div>
          <h2 id="closed-source-title">Where closed deals came from</h2>
          <p>Recorded source on dated deals closed in {year}.</p>
        </div>
      </div>
      {rows === null ? (
        <div className="report-empty" role="status">
          <strong>Closed-deal data did not load</strong>
          <span>Refresh to try the Admin deal source again.</span>
        </div>
      ) : rows.length === 0 ? (
        <div className="report-empty" role="status">
          <strong>No dated closed deals recorded this year</strong>
          <span>This chart will populate from real deal close dates and recorded sources.</span>
        </div>
      ) : (
        <BreakdownBars rows={rows} />
      )}
      {(partial || undated > 0) && (
        <p className="report-data-note">
          {partial ? "Deal history reached the reporting read limit. " : ""}
          {undated > 0
            ? `${undated.toLocaleString("en-CA")} closed ${undated === 1 ? "deal has" : "deals have"} no usable close date and ${undated === 1 ? "is" : "are"} excluded.`
            : ""}
        </p>
      )}
    </section>
  );
}

function ClosingTrend({ points }: { points: ReportingTrendPoint[] | null }) {
  const total = points?.reduce((sum, point) => sum + point.value, 0) ?? 0;
  const maximum = Math.max(...(points?.map((point) => point.value) ?? [0]), 1);

  return (
    <section className="report-panel report-panel-wide" aria-labelledby="closing-trend-title">
      <div className="report-panel-heading">
        <span className="report-panel-icon" aria-hidden="true"><CalendarDays /></span>
        <div>
          <h2 id="closing-trend-title">Closed deals over time</h2>
          <p>Six-month view from recorded close dates. Lead trend joins when lead-created timestamps are available.</p>
        </div>
      </div>
      {points === null ? (
        <div className="report-empty" role="status">
          <strong>Closing history did not load</strong>
          <span>Refresh to try the Admin deal source again.</span>
        </div>
      ) : total === 0 ? (
        <div className="report-empty" role="status">
          <strong>No dated closings in the last six months</strong>
          <span>The trend will appear after a deal records a close date.</span>
        </div>
      ) : (
        <ol className="report-trend" aria-label="Closed deals for the last six months">
          {points.map((point) => {
            const height = point.value === 0 ? 0 : Math.max(10, (point.value / maximum) * 100);
            const style = { "--report-bar-height": `${height}%` } as CSSProperties;
            return (
              <li key={point.id} aria-label={`${point.label}: ${point.value} closed deals`}>
                <strong>{point.value}</strong>
                <span className="report-trend-column" aria-hidden="true">
                  <span style={style} />
                </span>
                <span>{point.label}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function LoadingReport() {
  return (
    <div className="report-loading" role="status" aria-live="polite">
      <RefreshCw aria-hidden="true" />
      <div>
        <strong>Loading reporting data</strong>
        <span>Checking lead coverage, recorded send rows, and closed deals.</span>
      </div>
    </div>
  );
}

export function RealEstateReportingPage() {
  const hubData = useRealEstateHubData();
  const reporting = useReportingData();
  const { snapshot } = reporting;
  const refreshReporting = reporting.refresh;
  const refreshAll = useCallback(async () => {
    await refreshReporting();
  }, [refreshReporting]);
  const headerExtra = useMemo(
    () => (
      <span className="reporting-header-context">
        <span aria-hidden="true">·</span>
        <span>recorded send rows · last {snapshot.periodDays} days</span>
      </span>
    ),
    [snapshot.periodDays],
  );

  useHubHeader("Reporting", hubData, {
    onRefresh: refreshAll,
    refreshing: reporting.refreshing,
    afterExtra: headerExtra,
  });

  const lastUpdated = useMemo(() => {
    if (!reporting.updatedAt) return "Not updated yet";
    return `Updated ${new Intl.DateTimeFormat("en-CA", {
      hour: "numeric",
      minute: "2-digit",
    }).format(reporting.updatedAt)}`;
  }, [reporting.updatedAt]);
  const reportYear = new Date(snapshot.asOf).getUTCFullYear();

  return (
    <div className="reporting-root" aria-busy={reporting.loading}>
      <HubDataErrorBanner className="mb-3" data={hubData} />

      {reporting.error && (
        <div className="report-error" role="alert" aria-live="polite">
          <AlertTriangle aria-hidden="true" />
          <span>{reporting.error}</span>
          <button type="button" onClick={() => void refreshAll()} disabled={reporting.refreshing}>
            <RefreshCw aria-hidden="true" />
            {reporting.refreshing ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {reporting.loading ? (
        <LoadingReport />
      ) : (
        <>
          <section className="report-context" aria-label="Reporting coverage">
            <div className="report-context-copy">
              <span className="report-eyebrow">Recorded source data only</span>
              <p>
                Sample values from the design handoff are intentionally excluded. Coverage is a recent source window, not the full contact directory; a dash means the app cannot prove that metric yet.
              </p>
            </div>
            <dl>
              <div>
                <dt>Profiles in source window</dt>
                <dd>{snapshot.coverage.profiles?.toLocaleString("en-CA") ?? "—"}</dd>
              </div>
              <div>
                <dt>Conversations in source window</dt>
                <dd>{snapshot.coverage.conversations?.toLocaleString("en-CA") ?? "—"}</dd>
              </div>
              <div>
                <dt>Sources returned</dt>
                <dd>{snapshot.coverage.sources?.toLocaleString("en-CA") ?? "—"}</dd>
              </div>
            </dl>
            <span className="report-updated">{lastUpdated}</span>
          </section>

          <section className="report-goals" aria-labelledby="report-goals-title">
            <div className="report-goals-icon" aria-hidden="true"><Target /></div>
            <div>
              <h2 id="report-goals-title">Goal progress</h2>
              <p id="report-goals-reason">
                Account-level lead, appointment, closing, and GCI goals are not stored yet. Progress stays blank until those targets can be saved durably.
              </p>
            </div>
            <button type="button" disabled aria-describedby="report-goals-reason">
              Set goals unavailable
            </button>
          </section>

          <section className="report-kpis" aria-label={`Activity in the last ${snapshot.periodDays} days`}>
            {snapshot.kpis.map((metric) => <MetricCard key={metric.id} metric={metric} />)}
          </section>

          <section className="report-calculator" aria-labelledby="report-calculator-title">
            <div>
              <span className="report-panel-icon" aria-hidden="true"><Target /></span>
              <div>
                <h2 id="report-calculator-title">What it takes to hit your goal</h2>
                <p>The calculator will work backward only after a saved closing goal and linked funnel events are available.</p>
              </div>
            </div>
            <span className="report-calculator-state">Not enough recorded data</span>
          </section>

          <div className="report-grid">
            <DataGapPanel
              icon={BarChart3}
              title="Lead-to-close funnel"
              description="A cohort funnel cannot be assembled from unrelated current totals."
              requirement="Needs dated lead creation, conversation, appointment, client, contract, and close events linked to the same lead."
            />
            <DataGapPanel
              icon={UsersRound}
              title="Conversion by source"
              description="Current profile sources are visible, but source-to-client attribution is not persisted."
              requirement="Needs a dated client-conversion event joined to the originating lead source."
            />
            <ClosedSourcePanel
              rows={snapshot.closedDealsBySource}
              partial={snapshot.closedDealsPartial}
              undated={snapshot.undatedClosedDeals}
              year={reportYear}
            />
            <DataGapPanel
              icon={Megaphone}
              title="Marketing spend"
              description="Elevate does not have a per-channel spend ledger yet."
              requirement="Needs dated spend, channel attribution, and links from campaigns to leads and closed deals."
            />
            <ClosingTrend points={snapshot.closedDealsByMonth} />
          </div>

          <p className="report-footnote">
            Pipeline value, GCI, and deal-level dollars remain on Admin. Reporting never substitutes sample data for missing production records.
          </p>
        </>
      )}
    </div>
  );
}

export default RealEstateReportingPage;
