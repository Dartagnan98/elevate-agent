import { Link } from "react-router-dom";
import type { StatusResponse } from "@/lib/api";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";

/** Gateway + session summary for the System sidebar block (no separate strip chrome). */
export function SidebarStatusStrip() {
  const status = useSidebarStatus();
  const { t } = useI18n();

  if (status === null) {
    return (
      <div className="px-2 py-1" aria-hidden>
        <div className="h-6 w-full max-w-full animate-pulse rounded-[7px] bg-[var(--sidebar-row)]" />
      </div>
    );
  }

  const gw = gatewayLine(status, t);
  const { agentActivityLabel, appOpenLabel, appOpenValue, gatewayStatusLabel } = t.app;
  const overviewPath = isDashboardEmbeddedChatEnabled() ? "/chat" : "/tasks";

  return (
    <Link
      to={overviewPath}
      title={t.app.statusOverview}
      className={cn(
        "mx-0.5 mb-1 flex min-h-0 items-center rounded-[7px] px-2 py-1.5 text-left",
        "text-[var(--sidebar-text-muted)] transition-colors",
        "hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        "focus-visible:ring-inset",
      )}
    >
      <div className="flex w-full flex-col gap-1 text-[11.5px] leading-[1.35]">
        <StatusRow
          label={appOpenLabel}
          value={appOpenValue}
          valueClassName="text-success"
        />

        <StatusRow
          label={gatewayStatusLabel}
          value={gw.label}
          valueClassName={gw.tone}
        />

        <StatusRow
          label={agentActivityLabel}
          value={String(status.active_sessions)}
          valueClassName="tabular-nums text-[var(--sidebar-text-muted)]"
        />
      </div>
    </Link>
  );
}

function StatusRow({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <p className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
      <span className="min-w-0 truncate text-[var(--sidebar-text-faint)]">
        {label}
      </span>
      <span className={cn("shrink-0 font-medium", valueClassName)}>
        {value}
      </span>
    </p>
  );
}

function gatewayLine(
  status: StatusResponse,
  t: ReturnType<typeof useI18n>["t"],
): { label: string; tone: string } {
  const g = t.app.gatewayStrip;
  const byState: Record<string, { label: string; tone: string }> = {
    running: { label: g.running, tone: "text-success" },
    starting: { label: g.starting, tone: "text-warning" },
    startup_failed: { label: g.failed, tone: "text-destructive" },
    stopped: { label: g.stopped, tone: "text-[var(--sidebar-text-muted)]" },
  };
  if (status.gateway_state && byState[status.gateway_state]) {
    return byState[status.gateway_state];
  }
  return status.gateway_running
    ? { label: g.running, tone: "text-success" }
    : { label: g.off, tone: "text-[var(--sidebar-text-muted)]" };
}
