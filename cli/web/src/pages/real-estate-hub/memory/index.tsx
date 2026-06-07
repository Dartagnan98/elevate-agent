import { lazy, Suspense } from "react";
import type { ComponentType, SVGProps } from "react";
import { Brain, CheckCircle2, Clock, Network } from "lucide-react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { isoTimeAgo } from "@/lib/utils";
import { LoadingState, useHubHeader, useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import "./memory.css";

const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);

function MemoryGraphView({
  compact,
  nodes,
  edges,
}: {
  compact: boolean;
  nodes: AgentHubMemoryNode[];
  edges: AgentHubMemoryEdge[];
}) {
  if (nodes.length === 0) {
    return (
      <div className="mem-graph-empty mono">
        Graph is empty — memory will populate as agents process sessions.
      </div>
    );
  }
  return (
    <Suspense fallback={<div className="mem-graph-empty mono"><Skeleton className="h-24 w-full" /></div>}>
      <MemoryConstellation className="mem-constellation-host" compact={compact} edges={edges} nodes={nodes} />
    </Suspense>
  );
}

export function RealEstateMemoryPage() {
  const data = useRealEstateHubData();
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;
  // Agent status + job count live in the breadcrumb bar — no separate in-page
  // hero. (The breadcrumb already renders the gateway/agent status dot + label;
  // we just fold the job count in after it.)
  useHubHeader("Memory", data, {
    afterExtra: (
      <>
        <span className="text-muted-foreground/45">·</span>
        <span>
          {activeJobs} job{activeJobs === 1 ? "" : "s"}
        </span>
      </>
    ),
  });
  const memory = data.snapshot?.memory;

  // Preserve HubShell's loading guard.
  if (data.loading && !data.snapshot && !data.status) {
    return (
      <div className="mem-root">
        <LoadingState />
      </div>
    );
  }

  const pending = memory?.journal.pending ?? 0;
  const failed = memory?.journal.failed ?? 0;
  const activeSessionCount = memory?.journal.active_session_count ?? 0;
  const pipelineState =
    failed > 0
      ? { tone: "warn" as const, label: `${failed} failed` }
      : pending > 0
        ? { tone: "active" as const, label: `${pending} pending` }
        : { tone: "ok" as const, label: "Idle" };

  const recentSessions = memory?.journal.sessions ?? [];
  const latestIngest = recentSessions
    .map((s) => s.latest_created_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .reverse()[0];

  const embeddingsOn = Boolean(memory?.embedding.enabled);
  const embeddingModel = memory?.embedding.model || "On";

  return (
    <div className="mem-root">
      <div className="mem-inner">
        {/* Title/status/job-count/Refresh all live in the app breadcrumb bar
            (useHubHeader) — no separate in-page hero or status row here. */}
        <div className="mem-tiles">
          <SummaryTile icon={Clock} label="Pipeline" value={pipelineState.label} tone={pipelineState.tone} />
          <SummaryTile
            icon={CheckCircle2}
            label="Last ingest"
            value={latestIngest ? isoTimeAgo(latestIngest) : "Never"}
            tone={latestIngest ? "ok" : "warn"}
          />
          <SummaryTile
            icon={Brain}
            label="Embeddings"
            value={embeddingsOn ? embeddingModel : "Off"}
            tone={embeddingsOn ? "neutral" : "warn"}
          />
        </div>

        <div className="mem-grid">
          <div className="mem-card mem-graph-card">
            <div className="mem-card-head">
              <div className="mem-card-title">
                <Network width="15" height="15" />
                Knowledge graph
              </div>
              <span className={"mem-badge " + (embeddingsOn ? "on" : "")}>
                {embeddingsOn ? "Embeddings on" : "Embeddings off"}
              </span>
            </div>
            <div className="mem-card-body">
              <MemoryGraphView
                compact={false}
                nodes={memory?.graph.nodes ?? []}
                edges={memory?.graph.edges ?? []}
              />
            </div>
          </div>

          <div className="mem-card">
            <div className="mem-card-head">
              <div className="mem-card-title">Recent ingest</div>
            </div>
            <div className="mem-card-body mem-ingest">
              <div className="mem-ingest-active">
                <span className="dim">Active sessions</span>
                <span className="mem-ingest-count mono">{activeSessionCount}</span>
              </div>
              <div className="mem-provider">
                <div className="mem-provider-name">
                  {memory?.provider ?? "memory"} · {memory?.embedding.provider ?? "no embedding"}
                </div>
                <div className="mem-provider-path mono">{memory?.db_path ?? "No memory database path yet."}</div>
              </div>
              <div className="mem-sessions-label">Sessions</div>
              {recentSessions.length > 0 ? (
                <div className="mem-sessions">
                  {recentSessions.slice(0, 6).map((session) => (
                    <div className="mem-session" key={`${session.session_id}-${session.session_day}`}>
                      <div className="mem-session-l">
                        <span className="mem-session-day">{session.session_day}</span>
                        <span className="mem-session-ago">
                          {session.latest_created_at ? isoTimeAgo(session.latest_created_at) : ""}
                        </span>
                      </div>
                      <span className="mem-session-total mono">{session.total}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mem-sessions-empty">No recent ingest sessions.</div>
              )}
            </div>
          </div>
        </div>

        {data.error && (
          <div className="mem-tile mem-tile-value warn" style={{ marginTop: 16 }}>
            {data.error}
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  value: string | number;
  tone: "ok" | "warn" | "active" | "neutral";
}) {
  return (
    <div className="mem-tile">
      <div className="mem-tile-label mono">
        <Icon width="13" height="13" />
        {label}
      </div>
      <div className={"mem-tile-value " + tone}>{value}</div>
    </div>
  );
}
