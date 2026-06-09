import { useCallback, useLayoutEffect, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { useCachedResource } from "@/hooks/useCachedResource";
import {
  BarChart3,
  Brain,
  Cpu,
  Hash,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AnalyticsDailyEntry, AnalyticsModelEntry, AnalyticsSkillEntry } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RouteSkeleton } from "@/components/route-skeletons";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const CHART_HEIGHT_PX = 160;

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDate(day: string): string {
  try {
    const d = new Date(day + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return day;
  }
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function TokenBarChart({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  if (daily.length === 0) return null;

  const maxTokens = Math.max(...daily.map((d) => d.input_tokens + d.output_tokens), 1);

  return (
    <Card role="region" aria-labelledby="analytics-daily-tokens">
      <CardHeader>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-daily-tokens" className="text-base">{t.analytics.dailyTokenUsage}</CardTitle>
        </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <div className="h-2.5 w-2.5" style={{ background: "var(--midground)" }} />
            {t.analytics.input}
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2.5 w-2.5 bg-[var(--color-success)]" />
            {t.analytics.output}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-[2px]" style={{ height: CHART_HEIGHT_PX }}>
          {daily.map((d) => {
            const total = d.input_tokens + d.output_tokens;
            const inputH = Math.round((d.input_tokens / maxTokens) * CHART_HEIGHT_PX);
            const outputH = Math.round((d.output_tokens / maxTokens) * CHART_HEIGHT_PX);
            return (
              <div
                key={d.day}
                className="flex-1 min-w-0 group relative flex flex-col justify-end"
                style={{ height: CHART_HEIGHT_PX }}
              >
                {/* Tooltip */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10 pointer-events-none">
                  <div className="whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1.5 text-[10px] text-foreground">
                    <div className="font-medium">{formatDate(d.day)}</div>
                    <div>{t.analytics.input}: {formatTokens(d.input_tokens)}</div>
                    <div>{t.analytics.output}: {formatTokens(d.output_tokens)}</div>
                    <div>{t.analytics.total}: {formatTokens(total)}</div>
                  </div>
                </div>
                {/* Input bar */}
                <div
                  className="w-full"
                  style={{
                    backgroundColor: "color-mix(in srgb, var(--midground-base) 70%, transparent)",
                    height: Math.max(inputH, total > 0 ? 1 : 0),
                  }}
                />
                {/* Output bar */}
                <div
                  className="w-full bg-[var(--color-success)]/70"
                  style={{ height: Math.max(outputH, d.output_tokens > 0 ? 1 : 0) }}
                />
              </div>
            );
          })}
        </div>
        {/* X-axis labels */}
        <div className="flex justify-between mt-2 text-[10px] text-muted-foreground">
          <span>{daily.length > 0 ? formatDate(daily[0].day) : ""}</span>
          {daily.length > 2 && (
            <span>{formatDate(daily[Math.floor(daily.length / 2)].day)}</span>
          )}
          <span>{daily.length > 1 ? formatDate(daily[daily.length - 1].day) : ""}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function DailyTable({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  if (daily.length === 0) return null;

  const sorted = [...daily].reverse();

  return (
    <Card role="region" aria-labelledby="analytics-daily-breakdown">
      <CardHeader>
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-daily-breakdown" className="text-base">{t.analytics.dailyBreakdown}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.date}</th>
                <th className="text-right py-2 px-4 font-medium">{t.sessions.title}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.input}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.output}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((d) => {
                return (
                  <tr key={d.day} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                    <td className="py-2 pr-4 font-medium">{formatDate(d.day)}</td>
                    <td className="text-right py-2 px-4 text-muted-foreground">{d.sessions}</td>
                    <td className="text-right py-2 px-4">
                      <span style={{ color: "var(--midground)" }}>{formatTokens(d.input_tokens)}</span>
                    </td>
                    <td className="text-right py-2 pl-4">
                      <span className="text-[var(--color-success)]">{formatTokens(d.output_tokens)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function ModelTable({ models }: { models: AnalyticsModelEntry[] }) {
  const { t } = useI18n();
  if (models.length === 0) return null;

  const sorted = [...models].sort(
    (a, b) => b.input_tokens + b.output_tokens - (a.input_tokens + a.output_tokens),
  );

  return (
    <Card role="region" aria-labelledby="analytics-per-model">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-per-model" className="text-base">{t.analytics.perModelBreakdown}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.model}</th>
                <th className="text-right py-2 px-4 font-medium">{t.sessions.title}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.tokens}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((m) => (
                <tr key={m.model} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                  <td className="py-2 pr-4">
                    <span className="font-mono-ui text-xs">{m.model}</span>
                  </td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{m.sessions}</td>
                  <td className="text-right py-2 pl-4">
                    <span style={{ color: "var(--midground)" }}>{formatTokens(m.input_tokens)}</span>
                    {" / "}
                    <span className="text-[var(--color-success)]">{formatTokens(m.output_tokens)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillTable({ skills }: { skills: AnalyticsSkillEntry[] }) {
  const { t } = useI18n();
  if (skills.length === 0) return null;

  return (
    <Card role="region" aria-labelledby="analytics-top-skills">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-top-skills" className="text-base">{t.analytics.topSkills}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.skill}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.loads}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.edits}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.total}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.lastUsed}</th>
              </tr>
            </thead>
            <tbody>
              {skills.map((skill) => (
                <tr key={skill.skill} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                  <td className="py-2 pr-4">
                    <span className="font-mono-ui text-xs">{skill.skill}</span>
                  </td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{skill.view_count}</td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{skill.manage_count}</td>
                  <td className="text-right py-2 px-4">{skill.total_count}</td>
                  <td className="text-right py-2 pl-4 text-muted-foreground">
                    {skill.last_used_at ? timeAgo(skill.last_used_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Cached per period across tab switches; changing the period swaps to that
  // period's cached entry instantly and revalidates in the background.
  const { data, loading, error: cacheError, refresh } = useCachedResource(
    `analytics-${days}`,
    () => api.getAnalytics(days),
    { ttl: 5000 },
  );
  const error = cacheError ? String(cacheError) : null;
  const load = useCallback(() => {
    void refresh();
  }, [refresh]);

  useLayoutEffect(() => {
    const periodLabel =
      PERIODS.find((p) => p.days === days)?.label ?? `${days}d`;
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading && (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        )}
        <Badge variant="secondary" className="text-[10px]">
          {periodLabel}
        </Badge>
      </span>,
    );
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 sm:gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {PERIODS.map((p) => (
            <Button
              key={p.label}
              type="button"
              variant={days === p.days ? "default" : "outline"}
              size="sm"
              className="h-7 min-w-0 text-xs"
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          className="h-7 text-xs"
        >
          <RefreshCw className="mr-1 h-3 w-3" />
          {t.common.refresh}
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [days, loading, load, setAfterTitle, setEnd, t.common.refresh]);

  useRefreshOnAgentTurn(() => void load());

  return (
    <div className="flex flex-col gap-6">
      {loading && !data && (
        <RouteSkeleton path="/analytics" />
      )}

      {error && (
        <p className="px-1 py-1 text-xs text-destructive">{error}</p>
      )}

      {data && (
        <>
          {/* Summary cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <SummaryCard
              icon={Hash}
              label={t.analytics.totalTokens}
              value={formatTokens(data.totals.total_input + data.totals.total_output)}
              sub={t.analytics.inOut.replace("{input}", formatTokens(data.totals.total_input)).replace("{output}", formatTokens(data.totals.total_output))}
            />
            <SummaryCard
              icon={BarChart3}
              label={t.analytics.totalSessions}
              value={String(data.totals.total_sessions)}
              sub={`~${(data.totals.total_sessions / days).toFixed(1)}${t.analytics.perDayAvg}`}
            />
            <SummaryCard
              icon={TrendingUp}
              label={t.analytics.apiCalls}
              value={String(data.totals.total_api_calls ?? data.daily.reduce((sum, d) => sum + d.sessions, 0))}
              sub={t.analytics.acrossModels.replace("{count}", String(data.by_model.length))}
            />
          </div>

          {/* Bar chart */}
          <TokenBarChart daily={data.daily} />

          {/* Tables */}
          <DailyTable daily={data.daily} />
          <ModelTable models={data.by_model} />
          <SkillTable skills={data.skills.top_skills} />
        </>
      )}

      {data && data.daily.length === 0 && data.by_model.length === 0 && data.skills.top_skills.length === 0 && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          {t.analytics.noUsageData} {t.analytics.startSession}
        </p>
      )}
    </div>
  );
}
