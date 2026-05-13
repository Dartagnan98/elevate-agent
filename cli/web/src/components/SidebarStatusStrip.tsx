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
      <div className="px-5 py-1.5" aria-hidden>
        <div className="h-2 w-[80%] max-w-full animate-pulse rounded-sm bg-midground/10" />
      </div>
    );
  }

  const gw = gatewayLine(status, t);
  const { activeSessionsLabel, gatewayStatusLabel } = t.app;
  const overviewPath = isDashboardEmbeddedChatEnabled() ? "/chat" : "/tasks";

  return (
    <Link
      to={overviewPath}
      title={t.app.statusOverview}
      className={cn(
        "flex min-h-11 items-center text-left lg:min-h-0",
        "px-5 pb-2 pt-1 lg:px-4 lg:pb-1 lg:pt-0.5",
        "text-[var(--sidebar-text-muted)]",
        "transition-colors hover:text-[var(--sidebar-text)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        "focus-visible:ring-inset",
      )}
    >
      <div className="flex flex-col gap-1 font-mondwest text-[0.72rem] leading-snug tracking-[0.06em] lg:gap-0.5 lg:text-[0.68rem]">
        <p className="break-words">
          <span className="text-[var(--sidebar-text-faint)]">{gatewayStatusLabel}</span>{" "}
          <span className={cn("font-medium", gw.tone)}>{gw.label}</span>
        </p>

        <p className="break-words">
          <span className="text-[var(--sidebar-text-faint)]">{activeSessionsLabel}</span>{" "}
          <span className="tabular-nums text-[var(--sidebar-text-muted)]">
            {status.active_sessions}
          </span>
        </p>
      </div>
    </Link>
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
