import { lazy, Suspense, useState } from "react";
import type { ComponentType, CSSProperties, SVGProps } from "react";
import { Brain, CheckCircle2, Clock, Network } from "lucide-react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { isoTimeAgo } from "@/lib/utils";
import { LoadingState, useHubHeader, useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import "./memory.css";

const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);

type GraphDensity = "expanded" | "compact";

// Entity-hue presets. The graph tints its entity / project / community / plaud
// nodes off `--color-primary` (see MemoryConstellation graphStyle color-mix
// expressions), so overriding that var on the page root re-hues the
// constellation without touching the rest of the app. No backing API — this is
// a local view preference (the design exposed it via a Tweaks panel we stripped).
const ENTITY_HUES: { name: string; value: string }[] = [
  { name: "indigo", value: "#8E8CF2" },
  { name: "violet", value: "#B07CF0" },
  { name: "sky", value: "#6FA8F5" },
  { name: "mint", value: "#56D6A6" },
  { name: "silver", value: "#CBD0D8" },
];

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
    <Suspense fallback={<div className="mem-graph-empty mono">Loading graph…</div>}>
      <MemoryConstellation className="mem-constellation-host" compact={compact} edges={edges} nodes={nodes} />
    </Suspense>
  );
}

export function RealEstateMemoryPage() {
  const data = useRealEstateHubData();
  useHubHeader("Memory", data);
  const memory = data.snapshot?.memory;

  // Local view preferences (no backing API). TODO: persist density + entity hue
  // if these should survive reloads.
  const [density, setDensity] = useState<GraphDensity>("expanded");
  const [entityHue, setEntityHue] = useState<string>(ENTITY_HUES[0].value);

  // Preserve HubShell's loading guard.
  if (data.loading && !data.snapshot && !data.status) {
    return (
      <div className="mem-root">
        <LoadingState />
      </div>
    );
  }

  const gatewayOnline = Boolean(data.snapshot?.gateway.running || data.status?.gateway_running);
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;

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
    <div className="mem-root" style={{ "--color-primary": entityHue } as CSSProperties}>
      <div className="mem-inner">
        {/* Title/status/Refresh live in the app page header (useHubHeader),
            matching the Admin/Leads single-top-bar pattern — no in-page
            duplicate top bar here. */}
        <section className="mem-hero">
          <div className="mem-hero-l">
            <span className="mem-hero-icon">
              <Brain width="17" height="17" />
            </span>
            <div>
              <div className="mem-hero-eyebrow mono">Memory graph</div>
              <h1 className="mem-hero-title">Memory</h1>
            </div>
          </div>
          <div className="mem-hero-r mono">
            <span className={gatewayOnline ? "ok" : "err"}>
              <span className="mem-r-dot" />
              {gatewayOnline ? "Agent online" : "Agent offline"}
            </span>
            <span className="dim">·</span>
            <span className="dim">
              {activeJobs} job{activeJobs === 1 ? "" : "s"}
            </span>
          </div>
        </section>

        <div className="mem-divider" />

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
              <div className="mem-graph-controls">
                <DensityToggle value={density} onChange={setDensity} />
                <EntityHuePicker value={entityHue} onChange={setEntityHue} />
                <span className={"mem-badge " + (embeddingsOn ? "on" : "")}>
                  {embeddingsOn ? "Embeddings on" : "Embeddings off"}
                </span>
              </div>
            </div>
            <div className="mem-card-body">
              <MemoryGraphView
                compact={density === "compact"}
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

function DensityToggle({ value, onChange }: { value: GraphDensity; onChange: (value: GraphDensity) => void }) {
  const options: GraphDensity[] = ["expanded", "compact"];
  return (
    <div className="mem-density" role="radiogroup" aria-label="Graph density">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={value === option}
          onClick={() => onChange(option)}
          className={"mem-density-opt mono" + (value === option ? " active" : "")}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function EntityHuePicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="mem-accent-row" role="radiogroup" aria-label="Entity hue">
      {ENTITY_HUES.map((hue) => (
        <button
          key={hue.value}
          type="button"
          role="radio"
          aria-checked={value === hue.value}
          title={hue.name}
          onClick={() => onChange(hue.value)}
          style={{ background: hue.value }}
          className={"mem-accent-sw" + (value === hue.value ? " active" : "")}
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
