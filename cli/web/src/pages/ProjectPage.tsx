import { useCallback, useEffect, useLayoutEffect, useMemo } from "react";
import { useCachedResource } from "@/hooks/useCachedResource";
import {
  Bot,
  Brain,
  CheckCircle2,
  Clock,
  Database,
  Folder,
  KeyRound,
  RefreshCw,
  Settings,
  Terminal,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, isoTimeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RouteSkeleton } from "@/components/route-skeletons";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

function stateVariant(value: boolean | string | null | undefined): "success" | "warning" | "outline" {
  if (value === true || value === "running" || value === "connected" || value === "active") {
    return "success";
  }
  if (value === "starting" || value === "pending") return "warning";
  return "outline";
}

function MiniStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Folder;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-[0.68rem] font-medium">
          {label}
        </span>
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

function PathRow({ icon: Icon, label, value }: { icon: typeof Folder; label: string; value: string }) {
  return (
    <div className="grid gap-1 px-3 py-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <code className="min-w-0 break-all text-xs text-foreground/90">{value || "-"}</code>
    </div>
  );
}

export default function ProjectPage() {
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Cached across tab switches: revisiting a project paints instantly.
  const { data, loading, error: cacheError, refresh } = useCachedResource(
    "project-page",
    async () => {
      const [nextStatus, nextHub] = await Promise.all([
        api.getStatus(),
        api.getAgentHub({
          includeMemoryGraph: false,
          includeSessionTotal: false,
          includeOrchestration: false,
          includeHarness: false,
        }),
      ]);
      return { status: nextStatus, hub: nextHub };
    },
    { ttl: 5000 },
  );
  const status = data?.status ?? null;
  const hub = data?.hub ?? null;
  const load = useCallback(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (cacheError) {
      showToast(cacheError instanceof Error ? cacheError.message : "Project failed to load", "error");
    }
  }, [cacheError, showToast]);

  useLayoutEffect(() => {
    setAfterTitle(
      status ? (
        <span className="text-xs text-muted-foreground">
          {status.gateway_running ? "Gateway online" : "Gateway offline"}
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
  }, [load, loading, setAfterTitle, setEnd, status]);

  const connectedPlatforms = useMemo(
    () => hub?.platforms.filter((platform) => platform.configured) ?? [],
    [hub],
  );
  const enabledAgents = hub?.agents.filter((agent) => agent.enabled) ?? [];
  const embeddingLabel =
    hub?.memory.embedding.enabled
      ? `${hub.memory.embedding.provider}:${hub.memory.embedding.model}`
      : "off";

  if (loading && !status && !hub) {
    return <RouteSkeleton path="/project" />;
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="overflow-hidden rounded-md border border-border bg-card">
        <div className="grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={stateVariant(status?.gateway_running)}>
                {status?.gateway_running ? "Gateway online" : "Gateway offline"}
              </Badge>
              <Badge variant={stateVariant(status?.gateway_state)}>
                {status?.gateway_state ?? "unknown"}
              </Badge>
              <Badge variant={status?.config_version === status?.latest_config_version ? "success" : "warning"}>
                config {status?.config_version ?? "-"} / {status?.latest_config_version ?? "-"}
              </Badge>
              <Badge variant="outline">v{status?.version ?? "-"}</Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MiniStat icon={Bot} label="Agents" value={enabledAgents.length} />
              <MiniStat icon={Terminal} label="Platforms" value={connectedPlatforms.length} />
              <MiniStat icon={Brain} label="Memory" value={embeddingLabel} />
              <MiniStat icon={Clock} label="Sessions" value={hub?.sessions.active ?? status?.active_sessions ?? 0} />
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Local Project</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <PathRow icon={Folder} label="Code" value={status?.project_root ?? ""} />
                <PathRow icon={Settings} label="Config" value={status?.config_path ?? ""} />
                <PathRow icon={KeyRound} label="Secrets" value={status?.env_path ?? ""} />
                <PathRow icon={Database} label="Memory DB" value={hub?.memory.db_path ?? ""} />
                <PathRow icon={Folder} label="Data" value={status?.elevate_home ?? ""} />
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Runtime</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Model</span>
                  <span className="truncate text-right">{hub?.model.model || "not set"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Provider</span>
                  <span className="truncate text-right">{hub?.model.provider || "-"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Gateway PID</span>
                  <span>{status?.gateway_pid ?? "-"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Updated</span>
                  <span>{status?.gateway_updated_at ? isoTimeAgo(status.gateway_updated_at) : "-"}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Project Surface</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <MiniStat icon={Wrench} label="Tools" value={hub?.toolsets.enabled.length ?? 0} />
                  <MiniStat icon={CheckCircle2} label="Skills" value={hub?.skills.enabled ?? 0} />
                  <MiniStat icon={Database} label="Facts" value={hub?.memory.facts ?? 0} />
                  <MiniStat icon={Brain} label="Vectors" value={hub?.memory.embeddings ?? 0} />
                </div>
                <div className="flex flex-wrap gap-1">
                  {(connectedPlatforms.length ? connectedPlatforms : hub?.platforms.slice(0, 3) ?? []).map((platform) => (
                    <Badge key={platform.name} variant={platform.configured ? "success" : "outline"}>
                      {platform.name}
                    </Badge>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1">
                  {enabledAgents.slice(0, 5).map((agent) => (
                    <Badge key={agent.id} variant="outline">
                      {agent.name}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>
    </div>
  );
}
