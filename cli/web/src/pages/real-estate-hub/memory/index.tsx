import { lazy, Suspense, useState } from "react";
import type { CSSProperties } from "react";
import {
  Brain,
  CheckCircle2,
  Clock,
  Network,
} from "lucide-react";
import type { AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, isoTimeAgo } from "@/lib/utils";
import {
  HubShell,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";

const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);

// Entity hue presets. The graph tints its nodes/edges off `--color-primary`
// (see MemoryConstellation graphStyle color-mix expressions), so overriding
// that var on the graph wrapper re-hues the constellation without touching the
// rest of the app's theme. No backing API — this is a local view preference.
const ENTITY_HUES: { name: string; value: string }[] = [
  { name: "silver", value: "#CBD0D8" },
  { name: "indigo", value: "#8E8CF2" },
  { name: "violet", value: "#B07CF0" },
  { name: "sky", value: "#6FA8F5" },
  { name: "mint", value: "#56D6A6" },
];

type GraphDensity = "expanded" | "compact";

function MemoryGraphView({
  compact,
  nodes,
  edges,
}: {
  compact: boolean;
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
        compact={compact}
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

  // View preferences (no backing API — local, per-view tweaks mirroring the
  // design's "Tweaks" controls).
  // TODO: persist density + entity hue if these should survive reloads.
  const [density, setDensity] = useState<GraphDensity>("expanded");
  const [entityHue, setEntityHue] = useState<string>(ENTITY_HUES[0].value);

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
          value={embeddingsOn ? memory?.embedding.model || "On" : "Off"}
          tone={embeddingsOn ? "ok" : "warn"}
        />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className="overflow-hidden bg-card p-0">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Network className="h-4 w-4 text-primary" />
                Knowledge graph
              </CardTitle>
              <div className="flex items-center gap-3">
                <DensityToggle value={density} onChange={setDensity} />
                <EntityHuePicker value={entityHue} onChange={setEntityHue} />
                <Badge variant={embeddingsOn ? "success" : "outline"}>
                  {embeddingsOn ? "Embeddings on" : "Embeddings off"}
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {/* Scope the hue override to the graph so it re-tints the
                constellation without re-theming the rest of the page. */}
            <div style={{ "--color-primary": entityHue } as CSSProperties}>
              <MemoryGraphView
                compact={density === "compact"}
                nodes={memory?.graph.nodes ?? []}
                edges={memory?.graph.edges ?? []}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent ingest</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-muted-foreground">Active sessions</span>
              <span className="font-medium text-foreground tabular-nums">{activeSessionCount}</span>
            </div>
            <div className="rounded-md border border-border bg-card p-3 text-xs leading-5 text-muted-foreground">
              <div className="font-medium text-foreground">
                {memory?.provider ?? "memory"} · {memory?.embedding.provider ?? "no embedding"}
              </div>
              <div className="mt-1 truncate font-mono-ui">{memory?.db_path ?? "No memory database path yet."}</div>
            </div>
            {recentSessions.length > 0 ? (
              <div className="space-y-1.5">
                <div className="px-1 text-[0.68rem] font-medium uppercase tracking-wider text-muted-foreground">
                  Sessions
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
            ) : (
              <p className="px-1 text-xs text-muted-foreground/80">
                No recent ingest sessions.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </HubShell>
  );
}

function DensityToggle({
  value,
  onChange,
}: {
  value: GraphDensity;
  onChange: (value: GraphDensity) => void;
}) {
  const options: GraphDensity[] = ["expanded", "compact"];
  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-md border border-border/60 bg-background/60 p-0.5"
      role="radiogroup"
      aria-label="Graph density"
    >
      {options.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={value === option}
          onClick={() => onChange(option)}
          className={cn(
            "font-mono-ui rounded px-2 py-0.5 text-[0.66rem] capitalize transition-colors",
            value === option
              ? "bg-primary/12 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function EntityHuePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Entity hue">
      {ENTITY_HUES.map((hue) => (
        <button
          key={hue.value}
          type="button"
          role="radio"
          aria-checked={value === hue.value}
          title={hue.name}
          onClick={() => onChange(hue.value)}
          style={{ background: hue.value }}
          className={cn(
            "h-4 w-4 rounded-full ring-1 ring-inset ring-black/10 transition-transform hover:scale-110",
            value === hue.value && "ring-2 ring-offset-1 ring-offset-card ring-foreground/70",
          )}
        />
      ))}
    </div>
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
      <div className="font-mono-ui flex items-center gap-2 text-[0.68rem] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 truncate text-lg font-semibold ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}
