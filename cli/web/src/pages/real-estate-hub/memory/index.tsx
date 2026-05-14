import { lazy, Suspense } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Clock,
  MessageSquare,
  Network,
} from "lucide-react";
import type { AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isoTimeAgo } from "@/lib/utils";
import {
  HubMetric,
  HubShell,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";

const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);

function MemoryGraphView({
  nodes,
  edges,
}: {
  nodes: AgentHubMemoryNode[];
  edges: { source: string; target: string; type: string }[];
}) {
  if (nodes.length === 0) {
    return (
      <div className="font-mono-ui flex h-48 items-center justify-center px-4 text-center text-[0.72rem] text-muted-foreground/80">
        Graph is empty — memory will populate as agents process sessions.
      </div>
    );
  }
  return (
    <Suspense
      fallback={
        <div className="font-mono-ui flex h-64 items-center justify-center text-[0.72rem] text-muted-foreground/80">
          Loading graph…
        </div>
      }
    >
      <MemoryConstellation
        className="max-h-[38rem] min-h-[24rem]"
        edges={edges}
        nodes={nodes}
      />
    </Suspense>
  );
}

export function RealEstateMemoryPage() {
  const data = useRealEstateHubData();
  useHubHeader("Memory", data);
  const memory = data.snapshot?.memory;

  const pending = memory?.journal.pending ?? 0;
  const failed = memory?.journal.failed ?? 0;
  const processed = memory?.journal.processed ?? 0;
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

  return (
    <HubShell
      data={data}
      eyebrow="Memory Graph"
      icon={Brain}
      title="Memory"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryTile
          icon={Clock}
          label="Pipeline"
          value={pipelineState.label}
          tone={pipelineState.tone}
        />
        <SummaryTile
          icon={CheckCircle2}
          label="Last ingest"
          value={latestIngest ? isoTimeAgo(latestIngest) : "Never"}
          tone={latestIngest ? "ok" : "warn"}
        />
        <SummaryTile
          icon={Brain}
          label="Embeddings"
          value={memory?.embedding.enabled ? memory.embedding.model || "On" : "Off"}
          tone={memory?.embedding.enabled ? "ok" : "warn"}
        />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className="overflow-hidden bg-card p-0">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Network className="h-4 w-4 text-primary" />
                Knowledge graph
              </CardTitle>
              <Badge variant={memory?.embedding.enabled ? "success" : "outline"}>
                {memory?.embedding.enabled ? "Embeddings on" : "Embeddings off"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <MemoryGraphView
              nodes={memory?.graph.nodes ?? []}
              edges={memory?.graph.edges ?? []}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Pipeline</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <HubMetric icon={Clock} label="Pending" value={pending} />
              <HubMetric icon={CheckCircle2} label="Processed" value={processed} />
              <HubMetric icon={AlertTriangle} label="Failed" value={failed} />
              <HubMetric icon={MessageSquare} label="Active sessions" value={memory?.journal.active_session_count ?? 0} />
            </div>
            <div className="rounded-md border border-border bg-card p-3 text-xs leading-5 text-muted-foreground">
              <div className="font-medium text-foreground">
                {memory?.provider ?? "memory"} · {memory?.embedding.provider ?? "no embedding"}
              </div>
              <div className="mt-1 truncate">{memory?.db_path ?? "No memory database path yet."}</div>
            </div>
            {recentSessions.length > 0 && (
              <div className="space-y-1.5">
                <div className="font-mono-ui px-1 text-[0.68rem] uppercase tracking-wider text-muted-foreground">
                  Recent sessions
                </div>
                <div className="space-y-1">
                  {recentSessions.slice(0, 6).map((session) => (
                    <div
                      key={`${session.session_id}-${session.session_day}`}
                      className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-background/40 px-2.5 py-1.5 text-xs"
                    >
                      <div className="min-w-0 truncate">
                        <span className="font-medium text-foreground">{session.session_day}</span>
                        <span className="ml-1.5 text-muted-foreground/70">
                          {session.latest_created_at ? isoTimeAgo(session.latest_created_at) : ""}
                        </span>
                      </div>
                      <Badge variant="outline" className="shrink-0">{session.total}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </HubShell>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Clock;
  label: string;
  value: string | number;
  tone: "ok" | "warn" | "active";
}) {
  const valueClass =
    tone === "warn"
      ? "text-warning"
      : tone === "active"
        ? "text-primary"
        : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 truncate text-lg font-semibold ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}
