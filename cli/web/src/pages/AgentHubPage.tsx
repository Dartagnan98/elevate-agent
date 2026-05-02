import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  CalendarClock,
  CheckCircle2,
  CircleOff,
  Database,
  KeyRound,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Shield,
  Sparkles,
  Terminal,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubAgent,
  AgentHubMemoryNode,
  AgentHubPlatform,
  AgentHubSnapshot,
  HarnessSnapshot,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

const STATUS_COPY: Record<string, string> = {
  online: "Online",
  ready: "Ready",
  offline: "Offline",
  disabled: "Disabled",
  needs_model: "Needs model",
};

function statusVariant(status: string): "success" | "warning" | "outline" | "secondary" {
  if (status === "online" || status === "ready") return "success";
  if (status === "needs_model") return "warning";
  if (status === "disabled") return "secondary";
  return "outline";
}

function nodePosition(node: AgentHubMemoryNode, index: number, total: number) {
  const isEntity = node.type === "entity";
  const radius = isEntity ? 88 : 48;
  const offset = isEntity ? 0 : Math.PI / Math.max(total, 1);
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 + offset;
  return {
    x: 128 + Math.cos(angle) * radius,
    y: 112 + Math.sin(angle) * radius,
  };
}

function MemoryGraph({
  nodes,
  edges,
}: {
  nodes: AgentHubMemoryNode[];
  edges: { source: string; target: string; type: string }[];
}) {
  const positions = useMemo(() => {
    const byType = new Map<string, AgentHubMemoryNode[]>();
    for (const node of nodes) {
      const key = node.type === "entity" ? "entity" : "fact";
      byType.set(key, [...(byType.get(key) ?? []), node]);
    }
    const map = new Map<string, { x: number; y: number }>();
    for (const [type, grouped] of byType.entries()) {
      grouped.forEach((node, index) => {
        map.set(node.id, nodePosition({ ...node, type }, index, grouped.length));
      });
    }
    return map;
  }, [nodes]);

  if (!nodes.length) {
    return (
      <div className="flex h-56 items-center justify-center rounded-2xl border border-border bg-muted/20 text-sm text-muted-foreground">
        No graph nodes yet
      </div>
    );
  }

  return (
    <div className="relative h-56 overflow-hidden rounded-2xl border border-border bg-muted/20">
      <svg viewBox="0 0 256 224" className="h-full w-full">
        <g opacity="0.7">
          {edges.map((edge, index) => {
            const source = positions.get(edge.source);
            const target = positions.get(edge.target);
            if (!source || !target) return null;
            return (
              <line
                key={`${edge.source}-${edge.target}-${index}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke="currentColor"
                strokeWidth="0.8"
                className="text-border"
              />
            );
          })}
        </g>
        <circle
          cx="128"
          cy="112"
          r="28"
          className="fill-primary/10 stroke-primary/40"
          strokeWidth="1.2"
        />
        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const entity = node.type === "entity";
          const r = entity ? 7 : 5;
          return (
            <g key={node.id}>
              <circle
                cx={pos.x}
                cy={pos.y}
                r={r}
                className={cn(
                  entity ? "fill-warning/80 stroke-warning" : "fill-primary/70 stroke-primary",
                )}
                strokeWidth="1"
              />
              <title>{node.label}</title>
            </g>
          );
        })}
      </svg>
      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-wrap gap-1">
        {nodes.slice(0, 5).map((node) => (
          <Badge key={node.id} variant="outline" className="max-w-[10rem] truncate">
            {node.label}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-2xl border border-border bg-muted/20 px-3 py-2">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-[0.68rem] font-medium">
          {label}
        </span>
      </div>
      <div className="mt-1 text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentHubAgent }) {
  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            <CardTitle>{agent.name}</CardTitle>
          </div>
          <Badge variant={statusVariant(agent.status)}>
            {STATUS_COPY[agent.status] ?? agent.status}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">{agent.description || agent.role}</div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <MiniMetric label="Sessions" value={agent.session_count} />
          <MiniMetric label="Active" value={agent.active_session_count} />
        </div>
        <ChipRow icon={Terminal} items={agent.platforms} empty="No platforms" />
        <ChipRow icon={Wrench} items={agent.toolsets} empty="Global tools" />
        {agent.skills.length > 0 && (
          <ChipRow icon={Sparkles} items={agent.skills} empty="No skills" />
        )}
      </CardContent>
    </Card>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-border bg-background/30 px-2 py-2">
      <div className="text-[0.68rem] font-medium text-muted-foreground">
        {label}
      </div>
      <div className="text-base font-semibold">{value}</div>
    </div>
  );
}

function ChipRow({
  icon: Icon,
  items,
  empty,
}: {
  icon: typeof Terminal;
  items: string[];
  empty: string;
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-wrap gap-1">
        {(items.length ? items : [empty]).slice(0, 7).map((item) => (
          <Badge key={item} variant="outline" className="max-w-full truncate">
            {item}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function PlatformRow({ platform }: { platform: AgentHubPlatform }) {
  const runtimeState = platform.runtime?.state ?? (platform.configured ? "configured" : "blank");
  return (
    <div className="px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {platform.configured ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />
          ) : (
            <CircleOff className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{platform.name}</div>
            <div className="text-xs text-muted-foreground">{runtimeState}</div>
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          {platform.token_configured && <Badge variant="success">Token</Badge>}
          {platform.api_key_configured && <Badge variant="success">Key</Badge>}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant="outline">{platform.approved_users} paired</Badge>
        <Badge variant={platform.pending_pairings.length ? "warning" : "outline"}>
          {platform.pending_pairings.length} pending
        </Badge>
        {platform.home_channel?.name && (
          <Badge variant="outline">{platform.home_channel.name}</Badge>
        )}
      </div>
      {platform.pending_pairings.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {platform.pending_pairings.map((pairing) => (
            <Badge key={`${platform.name}-${pairing.code}`} variant="warning">
              {pairing.code}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function isHarnessSnapshot(value: AgentHubSnapshot["harness"]): value is HarnessSnapshot {
  return Boolean(value && "server" in value && "orchestration" in value);
}

function formatSavings(value: number | null | undefined) {
  if (typeof value !== "number") return "-";
  return `${value.toFixed(1)}%`;
}

function HarnessCard({ harness }: { harness?: AgentHubSnapshot["harness"] }) {
  if (!isHarnessSnapshot(harness)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Harness</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Harness snapshot unavailable
        </CardContent>
      </Card>
    );
  }

  const best = harness.performance.best_profile;
  const worst = harness.performance.worst_profile;
  const connectedClients = harness.server.clients.filter((client) => client.connected);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Harness</CardTitle>
          <Badge variant={harness.server.gateway_running ? "success" : "warning"}>
            {harness.server.pattern}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <MiniMetric label="Clients" value={`${connectedClients.length}/${harness.server.clients.length}`} />
          <MiniMetric label="Routed" value={harness.orchestration.route_labeled_runs} />
          <MiniMetric label="Events" value={harness.orchestration.recent_events} />
          <MiniMetric label="Ready Runs" value={harness.orchestration.plan_graph.ready_runs} />
          <MiniMetric label="Blocked" value={harness.orchestration.plan_graph.blocked_runs} />
          <MiniMetric label="Safety" value={harness.safety.external_actions_policy} />
          <MiniMetric label="Memory Flow" value={harness.memory.pipeline.state} />
        </div>
        {harness.performance.available ? (
          <div className="rounded-2xl border border-border bg-muted/20 p-2 text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Baseline</span>
              <span>{harness.performance.baseline_request_tokens ?? 0} tokens</span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Best profile</span>
              <span>
                {best?.name ?? "-"} / {formatSavings(best?.savings_pct)}
              </span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Weakest profile</span>
              <span>
                {worst?.name ?? "-"} / {formatSavings(worst?.savings_pct)}
              </span>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-border bg-muted/20 p-2 text-xs text-muted-foreground">
            {harness.performance.error || "Performance profiles skipped"}
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          {harness.orchestration.lifecycle_states.slice(0, 7).map((state) => (
            <Badge key={state} variant="outline">
              {state}
            </Badge>
          ))}
        </div>
        {harness.memory.pipeline.recent_events?.length ? (
          <div className="rounded-2xl border border-border bg-muted/20 p-2 text-xs">
            <div className="mb-1 text-muted-foreground">Memory activity</div>
            {harness.memory.pipeline.recent_events.slice(0, 3).map((event, index) => (
              <div key={`${event.timestamp ?? "event"}-${index}`} className="truncate">
                {event.kind ?? "memory"}{event.status ? ` / ${event.status}` : ""}
                {event.message ? `: ${event.message}` : ""}
              </div>
            ))}
          </div>
        ) : null}
        {harness.recommendations.length > 0 && (
          <div className="space-y-1 text-xs text-muted-foreground">
            {harness.recommendations.slice(0, 2).map((item) => (
              <div key={item}>- {item}</div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function AgentHubPage() {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(async () => {
    try {
      setSnapshot(await api.getAgentHub());
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent Hub failed", "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useLayoutEffect(() => {
    setAfterTitle(
      snapshot ? (
        <span className="text-xs text-muted-foreground">
          {snapshot.gateway.running ? "Gateway online" : "Gateway offline"}
        </span>
      ) : null,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={load} disabled={loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, setAfterTitle, setEnd, snapshot]);

  const connectedPlatforms = useMemo(
    () => snapshot?.platforms.filter((platform) => platform.configured) ?? [],
    [snapshot],
  );
  const executiveAgent = useMemo(
    () =>
      snapshot?.agents.find((agent) => agent.id === "executive-assistant") ??
      snapshot?.agents[0] ??
      null,
    [snapshot],
  );
  const activeAgents = snapshot?.agents.filter((agent) => agent.enabled) ?? [];
  const liveSessions = snapshot?.sessions.recent.filter((session) => session.is_active) ?? [];
  const pendingPairings =
    snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ??
    0;
  const memoryEmbeddingLabel = snapshot?.memory.embedding.enabled
    ? `${snapshot.memory.embedding.provider}:${snapshot.memory.embedding.model}`
    : "off";

  const runAction = async (name: "start" | "restart") => {
    setBusyAction(name);
    try {
      const result = name === "start" ? await api.startGateway() : await api.restartGateway();
      showToast(`${result.name} started as PID ${result.pid}`, "success");
      setTimeout(load, 1200);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Gateway action failed", "error");
    } finally {
      setBusyAction(null);
    }
  };

  if (loading && !snapshot) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="py-24 text-center text-muted-foreground">
        Agent Hub unavailable
      </div>
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="overflow-hidden rounded-[1.6rem] border border-border bg-card/70 shadow-[0_24px_90px_rgba(0,0,0,0.16)]">
        <div className="grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={snapshot.gateway.running ? "success" : "warning"}>
                {snapshot.gateway.running ? "Gateway online" : "Gateway offline"}
              </Badge>
              <Badge variant="outline">
                {snapshot.model.provider || "model"} / {snapshot.model.model || "not set"}
              </Badge>
              <Badge variant={snapshot.memory.embedding.enabled ? "success" : "outline"}>
                Memory {memoryEmbeddingLabel}
              </Badge>
            </div>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
              <div className="min-w-0">
                <div className="text-xs font-medium text-muted-foreground">
                  Main agent
                </div>
                <h1 className="mt-1 truncate text-2xl font-semibold leading-tight text-foreground sm:text-3xl">
                  {executiveAgent?.name ?? "Executive Assistant"}
                </h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  {executiveAgent?.description ||
                    executiveAgent?.role ||
                    "Primary operator and orchestration agent for the local Elevate workspace."}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MiniMetric label="Agent team" value={activeAgents.length} />
                <MiniMetric label="Live chats" value={liveSessions.length} />
                <MiniMetric label="Memory queue" value={snapshot.memory.journal.pending} />
                <MiniMetric label="Cron live" value={snapshot.cron.enabled} />
              </div>
            </div>
          </div>

          <Card className="bg-background/35">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle>Gateway</CardTitle>
                <Badge variant={snapshot.gateway.running ? "success" : "warning"}>
                  {snapshot.gateway.pid ? `PID ${snapshot.gateway.pid}` : "Stopped"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  size="sm"
                  onClick={() => runAction("start")}
                  disabled={busyAction !== null}
                >
                  {busyAction === "start" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Start
                </Button>
                <Button
                  className="flex-1"
                  size="sm"
                  variant="outline"
                  onClick={() => runAction("restart")}
                  disabled={busyAction !== null}
                >
                  {busyAction === "restart" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCw className="h-3.5 w-3.5" />
                  )}
                  Restart
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <MiniMetric label="State" value={snapshot.gateway.state || "unknown"} />
                <MiniMetric
                  label="Updated"
                  value={snapshot.gateway.updated_at ? isoTimeAgo(snapshot.gateway.updated_at) : "unknown"}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat icon={Activity} label="Gateway" value={snapshot.gateway.running ? "Online" : "Offline"} />
        <Stat icon={Users} label="Agents" value={snapshot.agents.length} />
        <Stat icon={Terminal} label="Active" value={snapshot.sessions.active} />
        <Stat icon={Brain} label="Facts" value={snapshot.memory.facts} />
        <Stat icon={Database} label="Entities" value={snapshot.memory.entities} />
        <Stat icon={CalendarClock} label="Cron" value={snapshot.cron.enabled} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle>Agent Orchestration</CardTitle>
                <Badge variant={snapshot.gateway.running ? "success" : "warning"}>
                  {activeAgents.length} enabled
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2">
                {snapshot.agents.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} />
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Runtime</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-4">
              <MiniMetric label="Model" value={snapshot.model.model || "Not set"} />
              <MiniMetric label="Toolsets" value={snapshot.toolsets.enabled.length} />
              <MiniMetric label="Skills" value={`${snapshot.skills.enabled}/${snapshot.skills.total}`} />
              <MiniMetric label="Pairings" value={pendingPairings} />
            </CardContent>
          </Card>

          <HarnessCard harness={snapshot.harness} />
        </div>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Memory Graph</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <MemoryGraph
                nodes={snapshot.memory.graph.nodes}
                edges={snapshot.memory.graph.edges}
              />
              <div className="grid grid-cols-2 gap-2">
                <MiniMetric label="Pending" value={snapshot.memory.journal.pending} />
                <MiniMetric label="Segments" value={snapshot.memory.journal.session_segment_count} />
              </div>
              <div className="text-xs text-muted-foreground">
                {snapshot.memory.provider} memory / {memoryEmbeddingLabel}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sessions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {snapshot.sessions.recent.slice(0, 8).map((session) => (
                <div key={session.id} className="rounded-2xl border border-border bg-muted/20 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm">{session.title || "Untitled session"}</span>
                    {session.is_active && <Badge variant="success">Live</Badge>}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{session.source}</span>
                    <span>{session.message_count} msgs</span>
                    <span>{timeAgo(session.last_active)}</span>
                  </div>
                </div>
              ))}
              {!snapshot.sessions.recent.length && (
                <div className="py-4 text-sm text-muted-foreground">No sessions yet</div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Connections</CardTitle>
            </CardHeader>
            <div className="max-h-[24rem] overflow-y-auto">
              {(connectedPlatforms.length ? connectedPlatforms : snapshot.platforms.slice(0, 5)).map(
                (platform) => (
                  <PlatformRow key={platform.name} platform={platform} />
                ),
              )}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Access</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">{snapshot.access.label}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(snapshot.access.entitlements).map(([name, entitlement]) => (
                  <Badge
                    key={name}
                    variant={entitlement.status === "active" ? "success" : "outline"}
                  >
                    {name}
                  </Badge>
                ))}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <KeyRound className="h-3.5 w-3.5" />
                <span className="truncate">{snapshot.config_path}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tools</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1">
                {snapshot.toolsets.enabled.slice(0, 16).map((toolset) => (
                  <Badge key={toolset} variant="outline">
                    {toolset}
                  </Badge>
                ))}
                {!snapshot.toolsets.enabled.length && <Badge variant="warning">No toolsets</Badge>}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        Snapshot {timeAgo(snapshot.generated_at)} / {snapshot.elevate_home}
      </div>
    </div>
  );
}
