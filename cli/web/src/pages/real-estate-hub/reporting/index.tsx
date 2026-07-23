import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  Mail,
  Megaphone,
  MessageSquareText,
  Phone,
  RefreshCw,
  Target,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Segmented } from "@/components/ui/segmented";
import {
  HubDataErrorBanner,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";
import type {
  ActivityMath,
  GoalProgressRow,
  ReportingBreakdownRow,
  ReportingFunnelStage,
  ReportingMetric,
  ReportingRateId,
  ReportingTrendPoint,
  SourceConversionRow,
} from "./reporting-data";
import { GoalsModal } from "./goals-modal";
import { ComboChart, HBars } from "./reporting-charts";
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

const RATE_LABELS: Record<ReportingRateId, string> = {
  leadToConversation: "lead → conversation",
  conversationToAppointment: "conversation → appointment",
  appointmentToClient: "appointment → client",
  clientToClose: "client → close",
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

function GoalProgressCard({
  rows,
  goalsLoaded,
  onEdit,
}: {
  rows: GoalProgressRow[];
  goalsLoaded: boolean;
  onEdit: () => void;
}) {
  return (
    <section className="report-goalcard" aria-labelledby="report-goals-title">
      <div className="report-goalcard-hd">
        <h2 id="report-goals-title">Goal progress</h2>
        <button type="button" className="report-goal-edit" onClick={onEdit}>
          Edit goals
        </button>
      </div>
      {!goalsLoaded && (
        <p className="report-data-note">
          Saved goals did not load this refresh — progress bars need the stored targets.
        </p>
      )}
      <div className="report-goal-grid">
        {rows.map((row) => (
          <div key={row.id} className="report-goal">
            <div className="report-goal-top">
              <span className="report-goal-label">{row.label}</span>
              <span className="report-goal-num">
                {row.currentDisplay}{" "}
                <span className="report-goal-target">/ {row.goalDisplay}</span>
              </span>
            </div>
            <div
              className="report-goal-bar"
              role="img"
              aria-label={
                row.pct === null
                  ? `${row.label}: ${row.note ?? "progress unavailable"}`
                  : `${row.label}: ${row.pct}% to goal`
              }
            >
              {row.pct !== null && (
                <span
                  className={`is-${row.tone}`}
                  style={{ width: `${Math.max(row.pct, 2)}%` }}
                />
              )}
            </div>
            <span className={`report-goal-pct ${row.tone ? `is-${row.tone}` : ""}`}>
              {row.pct !== null
                ? `${row.pct}% to goal`
                : (row.note ?? (row.goal === null ? "No goal set" : "No data source yet"))}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ActivityMathCard({
  math,
  onSetGoal,
}: {
  math: ActivityMath | null;
  onSetGoal: () => void;
}) {
  if (!math) {
    return (
      <section className="report-mathcard" aria-labelledby="report-math-title">
        <div className="report-math-hd">
          <div>
            <h2 id="report-math-title">What it takes to hit your goal</h2>
            <p>Worked backward from your funnel's conversion rates — so you know your daily number.</p>
          </div>
        </div>
        <div className="report-empty" role="status">
          <strong>No closings goal saved yet</strong>
          <span>Set a monthly closings goal and this card works the funnel backward for you.</span>
          <button type="button" className="report-goal-edit" onClick={onSetGoal}>
            Set a closings goal
          </button>
        </div>
      </section>
    );
  }

  const steps = [
    { id: "leads", value: math.leads, label: "leads" },
    { id: "conversations", value: math.conversations, label: "conversations" },
    { id: "appointments", value: math.appointments, label: "appointments" },
    { id: "clients", value: math.clients, label: "client meetings" },
    {
      id: "closings",
      value: math.closingsGoal,
      label: math.closingsGoal === 1 ? "closing" : "closings",
      goal: true,
    },
  ];

  return (
    <section className="report-mathcard" aria-labelledby="report-math-title">
      <div className="report-math-hd">
        <div>
          <h2 id="report-math-title">What it takes to hit your goal</h2>
          <p>Worked backward from your funnel's conversion rates — so you know your daily number.</p>
        </div>
        <div className="report-bigratio">
          <span className="report-bigratio-n">{math.conversationsPerSale.toLocaleString("en-CA")}</span>
          <span className="report-bigratio-l">conversations per sale</span>
        </div>
      </div>
      <div className="report-mathrow">
        {steps.map((step, index) => (
          <div key={step.id} className="report-mathstep-wrap">
            <div className={`report-mathstep ${step.goal ? "is-goal" : ""}`}>
              <span className="report-mathstep-n">{step.value.toLocaleString("en-CA")}</span>
              <span className="report-mathstep-l">{step.label}</span>
            </div>
            {index < steps.length - 1 && (
              <span className="report-matharrow" aria-hidden="true">→</span>
            )}
          </div>
        ))}
      </div>
      <p className="report-mathcadence">
        To hit <strong>{math.closingsGoal.toLocaleString("en-CA")}</strong>{" "}
        {math.closingsGoal === 1 ? "closing" : "closings"} a month, that's about{" "}
        <strong>{math.conversations.toLocaleString("en-CA")}</strong> conversations a month —
        roughly <strong>{math.perWeek.toLocaleString("en-CA")}</strong> a week, or{" "}
        <strong>{math.perDay.toLocaleString("en-CA")}</strong> a day.
      </p>
      {math.usesDefaults && (
        <p className="report-math-defaults">
          Using industry default rates for{" "}
          {math.defaultRateIds.map((id) => RATE_LABELS[id]).join(", ")} until enough history is
          recorded.
        </p>
      )}
    </section>
  );
}

function ChartPanel({
  id,
  icon: Icon,
  title,
  caption,
  wide,
  children,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  caption: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`report-panel ${wide ? "report-panel-wide" : ""}`}
      aria-labelledby={`${id}-title`}
    >
      <div className="report-panel-heading">
        <span className="report-panel-icon" aria-hidden="true"><Icon /></span>
        <div>
          <h2 id={`${id}-title`}>{title}</h2>
          <p>{caption}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="report-empty" role="status">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function FunnelPanel({ funnel }: { funnel: ReportingFunnelStage[] | null }) {
  return (
    <ChartPanel
      id="report-funnel"
      icon={BarChart3}
      title="Lead-to-close funnel"
      caption="Current pipeline statuses in the source window. Right column = kept from the stage above."
    >
      {funnel === null ? (
        <EmptyState
          title="Lead coverage did not load"
          detail="Refresh to rebuild the funnel from pipeline statuses."
        />
      ) : (
        <HBars
          ariaLabel="Lead to close funnel"
          rows={funnel.map((stage) => ({
            id: stage.id,
            label: stage.label,
            value: stage.value,
            note: stage.note,
          }))}
          showPct
          pctFor={(_, index) => funnel[index].keptPct}
          padL={120}
          padR={96}
        />
      )}
    </ChartPanel>
  );
}

function ConversionBySourcePanel({ rows }: { rows: SourceConversionRow[] | null }) {
  return (
    <ChartPanel
      id="report-conv"
      icon={UsersRound}
      title="Conversion by source"
      caption="Share of each recorded source's leads now in a client or closed stage."
    >
      {rows === null ? (
        <EmptyState
          title="Lead coverage did not load"
          detail="Refresh to rebuild source conversion from lead profiles."
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No lead sources recorded yet"
          detail="This chart fills in as profiles get a lead source and move through the pipeline."
        />
      ) : (
        <HBars
          ariaLabel="Conversion rate by lead source"
          rows={rows.map((row) => ({ id: row.id, label: row.label, value: row.pct }))}
          fmt={(value) => `${value}%`}
          padL={118}
          rowH={rows.length > 7 ? 26 : 34}
        />
      )}
    </ChartPanel>
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
    <ChartPanel
      id="report-closedsrc"
      icon={BarChart3}
      title="Where closed deals came from"
      caption={`Recorded source on dated deals closed in ${year}.`}
    >
      {rows === null ? (
        <EmptyState
          title="Closed-deal data did not load"
          detail="Refresh to try the Admin deal source again."
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No dated closed deals recorded this year"
          detail="This chart populates from real deal close dates and recorded sources."
        />
      ) : (
        <HBars
          ariaLabel="Closed deals by source"
          rows={rows.map((row, index) => ({ ...row, accent: index === 0 }))}
          fmt={(value) => `${value.toLocaleString("en-CA")} ${value === 1 ? "deal" : "deals"}`}
          padL={112}
          padR={70}
          rowH={rows.length > 7 ? 26 : 34}
        />
      )}
      {(partial || undated > 0) && (
        <p className="report-data-note">
          {partial ? "Deal history reached the reporting read limit. " : ""}
          {undated > 0
            ? `${undated.toLocaleString("en-CA")} closed ${undated === 1 ? "deal has" : "deals have"} no usable close date and ${undated === 1 ? "is" : "are"} excluded.`
            : ""}
        </p>
      )}
    </ChartPanel>
  );
}

function MarketingSpendPanel() {
  return (
    <ChartPanel
      id="report-spend"
      icon={Megaphone}
      title="Marketing spend"
      caption="Dollars into each channel."
    >
      <EmptyState
        title="No spend ledger yet"
        detail="Elevate does not record per-channel marketing spend. Bars, cost per lead, and cost per closed deal appear once a spend source exists."
      />
    </ChartPanel>
  );
}

function TrendPanel({
  closingsByMonth,
  salesByYear,
}: {
  closingsByMonth: ReportingTrendPoint[] | null;
  salesByYear: ReportingBreakdownRow[] | null;
}) {
  const [view, setView] = useState<"monthly" | "yoy">("monthly");
  const totalClosings = closingsByMonth?.reduce((sum, point) => sum + point.value, 0) ?? 0;

  return (
    <section className="report-panel report-panel-wide" aria-labelledby="report-trend-title">
      <div className="report-trend-hd">
        <div className="report-panel-heading">
          <span className="report-panel-icon" aria-hidden="true"><CalendarDays /></span>
          <div>
            <h2 id="report-trend-title">Leads &amp; sales over time</h2>
            <p>
              Closings drawn in their own band with real point labels — never a second axis. The
              leads line joins once lead-created timestamps are recorded.
            </p>
          </div>
        </div>
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: "monthly", label: "Monthly" },
            { value: "yoy", label: "Year over year" },
          ]}
        />
      </div>

      {view === "monthly" ? (
        closingsByMonth === null ? (
          <EmptyState
            title="Closing history did not load"
            detail="Refresh to try the Admin deal source again."
          />
        ) : totalClosings === 0 ? (
          <EmptyState
            title="No dated closings in the last six months"
            detail="The trend appears after a deal records a close date."
          />
        ) : (
          <>
            <ComboChart
              leads={null}
              sales={closingsByMonth}
              ariaLabel="Closings by month; leads series unavailable"
            />
            <p className="report-data-note">
              Lead-created timestamps are not recorded yet, so only the closings series can be
              drawn honestly.
            </p>
          </>
        )
      ) : (
        <div className="report-yoy">
          <div>
            <span className="report-tlabel">Leads by year</span>
            <EmptyState
              title="No lead-created dates recorded"
              detail="Leads by year needs dated lead creation, which is not stored yet."
            />
          </div>
          <div>
            <span className="report-tlabel">Sales by year</span>
            {salesByYear === null ? (
              <EmptyState
                title="Closed-deal data did not load"
                detail="Refresh to try the Admin deal source again."
              />
            ) : salesByYear.length === 0 ? (
              <EmptyState
                title="No dated closed deals recorded"
                detail="Yearly sales appear after deals record close dates."
              />
            ) : (
              <HBars
                ariaLabel="Sales by year"
                rows={salesByYear.map((row, index) => ({
                  ...row,
                  accent: index === salesByYear.length - 1,
                }))}
                fmt={(value) => `${value.toLocaleString("en-CA")} ${value === 1 ? "sale" : "sales"}`}
                padL={88}
                padR={64}
                rowH={32}
              />
            )}
          </div>
        </div>
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
        <span>Checking lead coverage, recorded send rows, closed deals, and saved goals.</span>
      </div>
    </div>
  );
}

export function RealEstateReportingPage() {
  const hubData = useRealEstateHubData();
  const reporting = useReportingData();
  const { snapshot } = reporting;
  const [goalsOpen, setGoalsOpen] = useState(false);
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
  const openGoals = useCallback(() => setGoalsOpen(true), []);

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
          <div className="report-masthead">
            <div className="report-masthead-copy">
              <span className="report-eyebrow">Recorded source data only</span>
              <p>
                Sample values from the design handoff are intentionally excluded. Coverage is a
                recent source window ({snapshot.coverage.profiles?.toLocaleString("en-CA") ?? "—"}{" "}
                profiles · {snapshot.coverage.conversations?.toLocaleString("en-CA") ?? "—"}{" "}
                conversations); a dash means the app cannot prove that metric yet.
              </p>
              <span className="report-updated">{lastUpdated}</span>
            </div>
            <div className="report-masthead-actions">
              <button type="button" className="report-goalbtn" onClick={openGoals}>
                <Target aria-hidden="true" />
                Set goals
              </button>
              <button
                type="button"
                className="report-range"
                disabled
                aria-label="Date range is fixed to the last 30 days for now; a range picker is coming"
              >
                Last 30 days
              </button>
            </div>
          </div>

          <GoalProgressCard
            rows={snapshot.goalProgress}
            goalsLoaded={snapshot.goals !== null}
            onEdit={openGoals}
          />

          <section className="report-kpis" aria-label={`Activity in the last ${snapshot.periodDays} days`}>
            {snapshot.kpis.map((metric) => <MetricCard key={metric.id} metric={metric} />)}
          </section>

          <ActivityMathCard math={snapshot.activityMath} onSetGoal={openGoals} />

          <div className="report-grid">
            <FunnelPanel funnel={snapshot.funnel} />
            <ConversionBySourcePanel rows={snapshot.conversionBySource} />
            <ClosedSourcePanel
              rows={snapshot.closedDealsBySource}
              partial={snapshot.closedDealsPartial}
              undated={snapshot.undatedClosedDeals}
              year={reportYear}
            />
            <MarketingSpendPanel />
            <TrendPanel
              closingsByMonth={snapshot.closedDealsByMonth}
              salesByYear={snapshot.salesByYear}
            />
          </div>

          <p className="report-footnote">
            Pipeline value, GCI, and deal-level dollars remain on Admin. Reporting never
            substitutes sample data for missing production records.
          </p>
        </>
      )}

      {goalsOpen && (
        <GoalsModal
          goals={snapshot.goals}
          onClose={() => setGoalsOpen(false)}
          onSaved={refreshAll}
        />
      )}
    </div>
  );
}

export default RealEstateReportingPage;
