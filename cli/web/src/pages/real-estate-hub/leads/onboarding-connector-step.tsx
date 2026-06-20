import { AlertTriangle, CheckCircle2, Circle, Copy, Link as LinkIcon, Play, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { ListSkeleton } from "@/components/ui/skeleton";
import type { OutreachConnectorRef, SourceConnectorStatus } from "@/lib/api-types";
import { cn } from "@/lib/utils";

import {
  connectorRecordTotal,
  connectorSetupCopy,
  connectorStateClasses,
  connectorStateLabel,
} from "./onboarding-data";
import { OUTREACH_HINTS } from "./onboarding-form-parts";

type CopyPromptStatus = Record<string, { kind: "success" | "error"; message: string }>;

export function LeadsConnectorSetupStep({
  connectors,
  loading,
  runningPromptId,
  copyStatus,
  onRefresh,
  onRunPrompt,
  onCopyPrompt,
}: {
  connectors: SourceConnectorStatus[];
  loading: boolean;
  runningPromptId: string | null;
  copyStatus: CopyPromptStatus;
  onRefresh: () => void;
  onRunPrompt: (connector: SourceConnectorStatus) => void;
  onCopyPrompt: (connector: SourceConnectorStatus) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to="/config#connectors"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-card/60 px-3 py-1.5 text-[12.5px] font-medium text-foreground backdrop-blur-sm hover:bg-muted"
        >
          <LinkIcon className="h-3.5 w-3.5" />
          Open Source Connectors
        </Link>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={loading}
          className="h-8 gap-1 px-2 text-[11.5px]"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <ul className="divide-y divide-border/40 overflow-hidden rounded-md border border-border/60 bg-card/40 backdrop-blur-sm">
        {connectors.length === 0 && !loading && (
          <li className="px-3 py-4 text-[12px] text-muted-foreground">
            No outreach connectors found. Check that your install seeded `data/sources/`.
          </li>
        )}
        {connectors.length === 0 && loading && (
          <li className="px-3 py-4">
            <ListSkeleton rows={3} />
          </li>
        )}
        {connectors.map((connector) => {
          const total = connectorRecordTotal(connector);
          const hint = OUTREACH_HINTS[connector.id as OutreachConnectorRef["id"]];
          const setupCopy = connectorSetupCopy(connector);
          return (
            <li key={connector.id} className="px-3 py-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold text-foreground">{connector.label}</span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium",
                        connectorStateClasses(connector.state),
                      )}
                    >
                      {connector.state === "connected" || connector.state === "import_only" ? (
                        <CheckCircle2 className="h-3 w-3" />
                      ) : connector.state === "blocked" || connector.state === "error" ? (
                        <AlertTriangle className="h-3 w-3" />
                      ) : (
                        <Circle className="h-3 w-3" />
                      )}
                      {connectorStateLabel(connector.state)}
                    </span>
                    {total > 0 && (
                      <span className="text-[10.5px] text-muted-foreground">
                        {total.toLocaleString()} records
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
                    {hint?.tagline || setupCopy}
                  </p>
                  {connector.nextOperatorStep && (
                    <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/80">
                      Next: {connector.nextOperatorStep}
                    </p>
                  )}
                  {connector.lastError && (
                    <p className="mt-1.5 text-[11px] leading-5 text-destructive/80">
                      {connector.lastError}
                    </p>
                  )}
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                  {connector.ownerAgent}
                </span>
                {connector.connectionType && (
                  <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {connector.connectionType}
                  </span>
                )}
                <Button
                  size="sm"
                  variant="default"
                  className="ml-auto h-7 gap-1 px-2 text-[11.5px]"
                  disabled={runningPromptId === connector.id}
                  onClick={() => onRunPrompt(connector)}
                  aria-label={`Run setup prompt for ${connector.label}`}
                >
                  <Play className="h-3 w-3" />
                  {runningPromptId === connector.id ? "Opening chat…" : "Run prompt"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2"
                  onClick={() => onCopyPrompt(connector)}
                  aria-label={`Copy setup prompt for ${connector.label}`}
                  title="Copy prompt text"
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
              {copyStatus[connector.id] && (
                <p
                  className={cn(
                    "mt-2 text-[11.5px]",
                    copyStatus[connector.id].kind === "error"
                      ? "text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  {copyStatus[connector.id].message}
                </p>
              )}
            </li>
          );
        })}
      </ul>

      <p className="text-[11.5px] text-muted-foreground/80">
        Run prompt opens a chat seeded with the connector's setup prompt — same flow as Config → Source connectors.
        Elevation auto-routes by lead device: iPhone → iMessage, Android → SMS / RCS.
      </p>
    </div>
  );
}
