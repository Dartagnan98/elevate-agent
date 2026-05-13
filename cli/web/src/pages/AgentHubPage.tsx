import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Brain,
  CalendarClock,
  CheckCircle2,
  CircleOff,
  Database,
  KeyRound,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  RotateCw,
  Save,
  Sparkles,
  Terminal,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubAgent,
  AgentHubPlatform,
  AgentHubSnapshot,
  EnvVarInfo,
  HarnessSnapshot,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MemoryConstellation } from "@/components/MemoryConstellation";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

const STATUS_COPY: Record<string, string> = {
  online: "Online",
  ready: "Ready",
  offline: "Offline",
  disabled: "Disabled",
  needs_model: "Needs model",
  needs_telegram: "Needs Telegram",
};

function envPlaceholder(
  envVars: Record<string, EnvVarInfo> | null,
  key: string,
  fallback: string,
) {
  const info = envVars?.[key];
  return info?.is_set && info.redacted_value ? info.redacted_value : fallback;
}

function agentTelegramEnvSegment(agentId: string) {
  const segment = agentId.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return segment || "AGENT";
}

function telegramFieldForAgent(agentId: string, label?: string) {
  const segment = agentTelegramEnvSegment(agentId);
  return {
    agentId,
    tokenKey: `ELEVATE_AGENT_${segment}_TELEGRAM_BOT_TOKEN`,
    key: `ELEVATE_AGENT_${segment}_TELEGRAM_CHANNEL`,
    label: label || agentId,
  };
}

const EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN";
const EXECUTIVE_TELEGRAM_CHANNEL_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL";

function looksLikeTelegramBotToken(value: string) {
  const text = value.trim().replace(/^telegram:/i, "");
  return /^\d{6,}:[A-Za-z0-9_-]{20,}$/.test(text);
}

function Stat({
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string | number;
}) {
  return (
    <span className="text-sm text-muted-foreground">
      <span className="font-medium tabular-nums text-foreground">{value}</span>{" "}
      {label}
    </span>
  );
}

function AgentCard({
  agent,
  telegramBotTokenPlaceholder,
  telegramBotTokenValue,
  telegramLanePlaceholder,
  telegramLaneValue,
  onTelegramLaneSave,
  onTelegramBotTokenChange,
  onTelegramLaneChange,
  savingTelegram,
}: {
  agent: AgentHubAgent;
  telegramBotTokenPlaceholder?: string;
  telegramBotTokenValue?: string;
  telegramLanePlaceholder?: string;
  telegramLaneValue?: string;
  onTelegramLaneSave?: () => void;
  onTelegramBotTokenChange?: (value: string) => void;
  onTelegramLaneChange?: (value: string) => void;
  savingTelegram?: boolean;
}) {
  const agentTelegramChanged = Boolean(
    telegramBotTokenValue?.trim() || telegramLaneValue?.trim(),
  );
  const telegramLane = agent.telegramLane;
  const telegramLaneReady = Boolean(telegramLane?.configured);
  const telegramLaneState = telegramLaneReady
    ? "Configured"
    : telegramLane?.duplicateSharedBot
      ? "Duplicate bot token"
      : telegramLane?.usesSharedBot
        ? "Needs own bot token"
      : telegramLane?.tokenConfigured
        ? "Missing chat target"
        : telegramLane?.targetConfigured
          ? "Missing bot token"
          : "Missing bot token and chat target";
  const telegramLaneDetail = telegramLane
    ? `${telegramLane.tokenEnv || "agent token env"} + ${telegramLane.targetEnv || "agent chat env"}`
    : "No Telegram lane required";

  return (
    <div className="rounded-md p-2 hover:bg-foreground/5">
      <div className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{agent.name}</span>
          </div>
          <span className={cn(
            "inline-flex items-center gap-1.5 text-xs",
            agent.status === "active" ? "text-muted-foreground" : "text-warning"
          )}>
            <span className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              agent.status === "active" ? "bg-emerald-500" : "bg-amber-500"
            )} />
            {STATUS_COPY[agent.status] ?? agent.status}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">{agent.description || agent.role}</div>
      </div>
      <div className="mt-2 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <MiniMetric label="Sessions" value={agent.session_count} />
          <MiniMetric label="Active" value={agent.active_session_count} />
        </div>
        <ChipRow icon={Terminal} items={agent.platforms} empty="No platforms" />
        <ChipRow icon={Wrench} items={agent.toolsets} empty="Global tools" />
        {agent.skills.length > 0 && (
          <ChipRow icon={Sparkles} items={agent.skills} empty="No skills" />
        )}
        {onTelegramLaneChange && (
          <div className="grid gap-1">
            <div className="flex items-center gap-2 text-[0.68rem] font-medium text-muted-foreground">
              <MessageSquare className="h-3.5 w-3.5" />
              <span>{agent.name} Telegram</span>
            </div>
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
              <label className="grid gap-1 text-[0.68rem] font-medium text-muted-foreground">
                <span>Bot token</span>
                <Input
                  autoComplete="new-password"
                  type="password"
                  value={telegramBotTokenValue ?? ""}
                  placeholder={telegramBotTokenPlaceholder ?? "BotFather token"}
                  onChange={(event) => onTelegramBotTokenChange?.(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && agentTelegramChanged && onTelegramLaneSave) {
                      event.preventDefault();
                      onTelegramLaneSave();
                    }
                  }}
                />
              </label>
              <label className="grid gap-1 text-[0.68rem] font-medium text-muted-foreground">
                <span>Chat/topic ID</span>
                <Input
                  value={telegramLaneValue ?? ""}
                  placeholder={telegramLanePlaceholder ?? "Chat ID or chat:topic"}
                  onChange={(event) => onTelegramLaneChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && agentTelegramChanged && onTelegramLaneSave) {
                      event.preventDefault();
                      onTelegramLaneSave();
                    }
                  }}
                />
              </label>
              <Button
                size="sm"
                variant="outline"
                onClick={onTelegramLaneSave}
                disabled={savingTelegram || !agentTelegramChanged}
              >
                {savingTelegram ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save
              </Button>
            </div>
            {telegramLane && (
              <div className="flex flex-wrap items-center gap-2 text-[0.68rem] text-muted-foreground">
                <span className={cn("text-[0.68rem]", telegramLaneReady ? "text-muted-foreground" : "text-warning")}>
                  {telegramLaneState}
                </span>
                <span className="min-w-0 truncate">{telegramLaneDetail}</span>
              </div>
            )}
            {telegramLane?.duplicateSharedBot && (
              <div className="text-[0.68rem] leading-5 text-warning">
                This agent is using the Executive bot token. Create a separate BotFather token for this agent.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="py-1">
      <div className="text-[0.68rem] text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

function ChipRow({
  items,
  empty,
}: {
  icon: typeof Terminal;
  items: string[];
  empty: string;
}) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
      {(items.length ? items : [empty]).slice(0, 7).map((item) => (
        <span key={item} className="max-w-full truncate">
          {item}
        </span>
      ))}
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
        <div className="flex shrink-0 gap-2 text-xs text-muted-foreground">
          {platform.token_configured && <span>token</span>}
          {platform.api_key_configured && <span>key</span>}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{platform.approved_users} paired</span>
        <span>·</span>
        <span className={platform.pending_pairings.length ? "text-warning" : ""}>
          {platform.pending_pairings.length} pending
        </span>
        {platform.home_channel?.name && (
          <><span>·</span><span>{platform.home_channel.name}</span></>
        )}
      </div>
      {platform.pending_pairings.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-2 text-xs text-warning">
          {platform.pending_pairings.map((pairing) => (
            <span key={`${platform.name}-${pairing.code}`}>
              {pairing.code}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function TelegramGatewayControls({
  envVars,
  hasChanges,
  home,
  onHomeChange,
  onRestart,
  onSave,
  onTokenChange,
  saving,
  token,
  tokenConfigured,
}: {
  envVars: Record<string, EnvVarInfo> | null;
  hasChanges: boolean;
  home: string;
  onHomeChange: (value: string) => void;
  onRestart: () => void;
  onSave: () => void;
  onTokenChange: (value: string) => void;
  saving: boolean;
  token: string;
  tokenConfigured: boolean;
}) {
  const saveOnEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && hasChanges) {
      event.preventDefault();
      onSave();
    }
  };

  return (
    <div className="py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-foreground">Executive Telegram</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className={cn("text-xs", tokenConfigured ? "text-muted-foreground" : "text-warning")}>
            {tokenConfigured ? "configured" : "needs token"}
          </span>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <div className="grid gap-1">
          <div className="text-[0.68rem] font-medium text-muted-foreground">Executive bot token</div>
          <Input
            autoComplete="new-password"
            type="password"
            value={token}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY,
              envPlaceholder(envVars, "TELEGRAM_BOT_TOKEN", "Executive BotFather token"),
            )}
            onChange={(event) => onTokenChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="grid gap-1">
          <div className="text-[0.68rem] font-medium text-muted-foreground">Executive chat/topic</div>
          <Input
            value={home}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_CHANNEL_KEY,
              envPlaceholder(envVars, "TELEGRAM_HOME_CHANNEL", "Executive chat ID"),
            )}
            onChange={(event) => onHomeChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="flex gap-2 md:justify-end">
          <Button
            size="sm"
            onClick={onSave}
            disabled={saving || !hasChanges}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={onRestart}>
            <RotateCw className="h-3.5 w-3.5" />
            Restart
          </Button>
        </div>
      </div>
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
      <div className="px-1">
        <div className="mb-2 text-sm font-medium">Harness</div>
        <div className="text-sm text-muted-foreground">
          Harness snapshot unavailable
        </div>
      </div>
    );
  }

  const best = harness.performance.best_profile;
  const worst = harness.performance.worst_profile;
  const connectedClients = harness.server.clients.filter((client) => client.connected);

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 px-1">
        <span className="text-sm font-medium">Harness</span>
        <span className="text-xs text-muted-foreground">· {harness.server.pattern}</span>
      </div>
      <div className="space-y-3 px-1">
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
          <div className="text-xs">
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
          <div className="text-xs text-muted-foreground">
            {harness.performance.error || "Performance profiles skipped"}
          </div>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {harness.orchestration.lifecycle_states.slice(0, 7).map((state) => (
            <span key={state}>{state}</span>
          ))}
        </div>
        {harness.memory.pipeline.recent_events?.length ? (
          <div className="text-xs">
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
      </div>
    </div>
  );
}

function HandoffBusCard({
  busy,
  handoffs,
  onRunWorker,
  onWakeWorker,
  worker,
}: {
  busy: boolean;
  handoffs: AgentHubSnapshot["handoffs"];
  onRunWorker: () => void;
  onWakeWorker: () => void;
  worker: AgentHubSnapshot["agentWorker"];
}) {
  const active = handoffs.queued + handoffs.running + handoffs.waitingHuman;
  const loopRunning = worker.loop?.running ?? false;
  const heartbeat = worker.heartbeat;
  const wake = worker.wake;
  const workerHealthy = worker.enabled && worker.state !== "error" && worker.state !== "disabled" && loopRunning;

  return (
    <div className="px-1">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Agent handoffs</span>
            <span className="text-xs text-muted-foreground">· {active} open</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Worker {worker.enabled ? worker.state : "disabled"}</span>
            <span>·</span>
            <span>Loop {loopRunning ? "running" : "stopped"}</span>
            {worker.lastTickAt && (<><span>·</span><span>Tick {isoTimeAgo(worker.lastTickAt)}</span></>)}
            {heartbeat?.lastBeatAt && (<><span>·</span><span>Heartbeat {isoTimeAgo(heartbeat.lastBeatAt)}</span></>)}
            {wake?.lastWakeAt && (<><span>·</span><span>Wake {isoTimeAgo(wake.lastWakeAt)}</span></>)}
            {worker.lastError && <span className="text-warning">{worker.lastError}</span>}
          </div>
          {handoffs.error && (
            <div className="mt-1 text-xs text-warning">{handoffs.error}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={onRunWorker}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Run worker
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onWakeWorker}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Wake loop
            </Button>
          </div>
        </div>
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
          <MiniMetric label="Queued" value={handoffs.queued} />
          <MiniMetric label="Running" value={handoffs.running} />
          <MiniMetric label="Human" value={handoffs.waitingHuman} />
          <MiniMetric label="Last handoffs" value={worker.drained.handoffs} />
          <MiniMetric label="Last admin" value={worker.drained.adminRuns} />
          <MiniMetric label="Wakes" value={wake?.count ?? 0} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", workerHealthy ? "bg-emerald-500" : "bg-amber-500")} />
            {worker.enabled ? "auto-drain on" : "auto-drain off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", loopRunning ? "bg-emerald-500" : "bg-amber-500")} />
            wake loop {loopRunning ? "on" : "off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", heartbeat?.enabled ? "bg-emerald-500" : "bg-amber-500")} />
            heartbeat {heartbeat?.intervalSeconds ?? "off"}s
          </span>
          {wake?.pending && <span className="text-warning">wake pending</span>}
          <span>handoff cap {worker.limits.handoffs}</span>
          <span>admin cap {worker.limits.adminRuns}</span>
        </div>
        {handoffs.byAgent.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {handoffs.byAgent.slice(0, 8).map((agent) => (
              <span key={agent.agentId} className={agent.queued || agent.running ? "text-warning" : ""}>
                {agent.agentId} {agent.queued + agent.running + agent.waitingHuman}/{agent.total}
              </span>
            ))}
          </div>
        )}
        <div className="space-y-0.5">
          {handoffs.recent.slice(0, 5).map((handoff) => (
            <div
              key={handoff.id}
              className="rounded-md px-1 py-1.5 hover:bg-foreground/5"
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 truncate text-sm font-medium">
                  {handoff.title}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {handoff.status.replace("_", " ")}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>{handoff.fromAgentId}</span>
                <span>→</span>
                <span>{handoff.toAgentId}</span>
                <span>·</span>
                <span>{isoTimeAgo(handoff.updatedAt)}</span>
              </div>
            </div>
          ))}
          {!handoffs.recent.length && (
            <div className="py-4 text-sm text-muted-foreground">No handoffs yet</div>
          )}
        </div>
      </div>
    </div>
  );
}

function SetupRunway({
  busyAction,
  onRestart,
  onStart,
  snapshot,
}: {
  busyAction: string | null;
  onRestart: () => void;
  onStart: () => void;
  snapshot: AgentHubSnapshot;
}) {
  const pendingPairings = snapshot.platforms.reduce(
    (total, platform) => total + platform.pending_pairings.length,
    0,
  );
  const configuredPlatforms = snapshot.platforms.filter((platform) => platform.configured).length;

  const items = [
    {
      icon: KeyRound,
      label: "Model auth",
      detail: snapshot.model.configured ? `${snapshot.model.provider} / ${snapshot.model.model}` : "Connect OpenAI Codex",
      state: snapshot.model.configured ? "ready" : "needs setup",
      to: "/env",
    },
    {
      icon: Terminal,
      label: "Gateway",
      detail: snapshot.gateway.running ? `Running${snapshot.gateway.pid ? ` as ${snapshot.gateway.pid}` : ""}` : "Start the local service",
      state: snapshot.gateway.running ? "online" : "offline",
      action: snapshot.gateway.running ? onRestart : onStart,
    },
    {
      icon: Users,
      label: "Messaging",
      detail: pendingPairings ? `${pendingPairings} pairing code${pendingPairings === 1 ? "" : "s"} waiting` : `${configuredPlatforms} connector${configuredPlatforms === 1 ? "" : "s"} configured`,
      state: pendingPairings ? "review" : configuredPlatforms ? "ready" : "blank",
      to: "/today",
    },
    {
      icon: Brain,
      label: "Memory",
      detail: snapshot.memory.embedding.enabled
        ? `${snapshot.memory.embedding.provider}:${snapshot.memory.embedding.model}`
        : "Turn on embeddings",
      state: snapshot.memory.embedding.enabled ? "ready" : "optional",
      to: "/memory",
    },
  ];

  return (
    <div className="px-1">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-sm font-medium">Setup runway</span>
        <Link
          to="/config"
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          Full settings
        </Link>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => {
          const Icon = item.icon;
          const content = (
            <>
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate text-sm font-semibold text-foreground">{item.label}</span>
                </div>
                <span className={cn(
                  "inline-flex items-center gap-1.5 text-xs",
                  item.state === "ready" || item.state === "online"
                    ? "text-muted-foreground"
                    : item.state === "review" || item.state === "needs setup"
                      ? "text-warning"
                      : "text-muted-foreground"
                )}>
                  <span className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    item.state === "ready" || item.state === "online"
                      ? "bg-emerald-500"
                      : item.state === "review" || item.state === "needs setup"
                        ? "bg-amber-500"
                        : "bg-border"
                  )} />
                  {item.state}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
            </>
          );

          if (item.action) {
            return (
              <button
                key={item.label}
                type="button"
                onClick={item.action}
                disabled={busyAction !== null}
                className="p-2 text-left transition-colors hover:bg-foreground/5 disabled:opacity-60 rounded-md"
              >
                {content}
              </button>
            );
          }

          return (
            <Link
              key={item.label}
              to={item.to ?? "/config"}
              className="p-2 transition-colors hover:bg-foreground/5 rounded-md"
            >
              {content}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function AgentHubPage() {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [envVars, setEnvVars] = useState<Record<string, EnvVarInfo> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [savingTelegram, setSavingTelegram] = useState(false);
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramHome, setTelegramHome] = useState("");
  const [telegramLanes, setTelegramLanes] = useState<Record<string, string>>({});
  const [telegramAgentTokens, setTelegramAgentTokens] = useState<Record<string, string>>({});
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(async () => {
    try {
      const [nextSnapshot, nextEnvVars] = await Promise.all([
        api.getAgentHub(),
        api.getEnvVars().catch(() => null),
      ]);
      setSnapshot(nextSnapshot);
      if (nextEnvVars) {
        setEnvVars(nextEnvVars);
      }
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
  const telegramPlatform = snapshot?.platforms.find(
    (platform) => platform.name.toLowerCase() === "telegram",
  );
  const telegramTokenConfigured = Boolean(
    telegramPlatform?.token_configured ||
      envVars?.TELEGRAM_BOT_TOKEN?.is_set ||
      envVars?.[EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY]?.is_set,
  );
  const telegramHasChanges = Boolean(
    telegramToken.trim() ||
      telegramHome.trim() ||
      (snapshot?.agents ?? []).some((agent) => {
        const field = telegramFieldForAgent(agent.id, agent.name);
        return Boolean((telegramAgentTokens[field.tokenKey] ?? "").trim() || (telegramLanes[field.key] ?? "").trim());
      }),
  );

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

  const runAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      const result = await api.runAgentWorkerTick();
      showToast(
        `Worker launched ${result.drained.handoffs} handoff${result.drained.handoffs === 1 ? "" : "s"} and ${result.drained.adminRuns} admin run${result.drained.adminRuns === 1 ? "" : "s"}`,
        "success",
      );
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const wakeAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      await api.wakeAgentWorker();
      showToast("Worker wake queued. Gateway loop will drain it.", "success");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker wake failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const saveTelegramConfig = async () => {
    const entries = new Map<string, string>();
    const executiveField = telegramFieldForAgent("executive-assistant", "Executive Assistant");
    const telegramTokenValue = telegramToken.trim();
    const telegramHomeValue = telegramHome.trim();
    const typedExecutiveToken = (telegramAgentTokens[executiveField.tokenKey] ?? "").trim();
    const typedExecutiveHome = (telegramLanes[executiveField.key] ?? "").trim();
    const executiveTokenCandidate = typedExecutiveToken || telegramTokenValue;
    for (const agent of snapshot?.agents ?? []) {
      if (agent.id === "executive-assistant") continue;
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (
        tokenValue &&
        ((telegramTokenValue && tokenValue === telegramTokenValue) ||
          (executiveTokenCandidate && tokenValue === executiveTokenCandidate))
      ) {
        showToast(`${agent.name} needs its own BotFather token; it cannot reuse Executive.`, "error");
        return;
      }
    }
    if (telegramTokenValue) {
      entries.set("TELEGRAM_BOT_TOKEN", telegramTokenValue);
      if (!typedExecutiveToken) {
        entries.set(EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY, telegramTokenValue);
      }
    }
    if (telegramHomeValue) {
      if (looksLikeTelegramBotToken(telegramHomeValue)) {
        showToast("Home channel expects a chat/topic ID, not a bot token.", "error");
        return;
      }
      entries.set("TELEGRAM_HOME_CHANNEL", telegramHomeValue);
      if (!typedExecutiveHome) {
        entries.set(EXECUTIVE_TELEGRAM_CHANNEL_KEY, telegramHomeValue);
      }
    }
    for (const agent of snapshot?.agents ?? []) {
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (tokenValue) {
        entries.set(field.tokenKey, tokenValue);
      }
      const value = (telegramLanes[field.key] ?? "").trim();
      if (value) {
        if (looksLikeTelegramBotToken(value)) {
          showToast(`${agent.name}: paste the bot token into Bot token, not Chat/topic ID.`, "error");
          return;
        }
        entries.set(field.key, value);
      }
    }
    if (!entries.size) return;

    setSavingTelegram(true);
    try {
      for (const [key, value] of entries.entries()) {
        await api.setEnvVar(key, value);
      }
      setTelegramToken("");
      setTelegramHome("");
      setTelegramLanes({});
      setTelegramAgentTokens({});
      await load();
      showToast("Telegram settings saved. Restart gateway to apply.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Telegram save failed", "error");
    } finally {
      setSavingTelegram(false);
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

      <section className="px-1">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <span className={cn("inline-block h-1.5 w-1.5 rounded-full", snapshot.gateway.running ? "bg-emerald-500" : "bg-amber-500")} />
                {snapshot.gateway.running ? "Gateway online" : "Gateway offline"}
              </span>
              <span>{snapshot.model.provider || "model"} / {snapshot.model.model || "not set"}</span>
              <span>Memory {memoryEmbeddingLabel}</span>
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
                <MiniMetric label="Handoffs" value={snapshot.handoffs.open} />
                <MiniMetric label="Memory queue" value={snapshot.memory.journal.pending} />
                <MiniMetric label="Cron live" value={snapshot.cron.enabled} />
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Gateway</span>
              <span className="text-xs text-muted-foreground">
                {snapshot.gateway.pid ? `PID ${snapshot.gateway.pid}` : "Stopped"}
              </span>
            </div>
            <div className="space-y-3">
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
            </div>
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1">
        <Stat icon={Activity} label="Gateway" value={snapshot.gateway.running ? "Online" : "Offline"} />
        <span className="text-border">·</span>
        <Stat icon={Users} label="Agents" value={snapshot.agents.length} />
        <span className="text-border">·</span>
        <Stat icon={Terminal} label="Active" value={snapshot.sessions.active} />
        <span className="text-border">·</span>
        <Stat icon={Brain} label="Facts" value={snapshot.memory.facts} />
        <span className="text-border">·</span>
        <Stat icon={Database} label="Entities" value={snapshot.memory.entities} />
        <span className="text-border">·</span>
        <Stat icon={CalendarClock} label="Cron" value={snapshot.cron.enabled} />
      </div>

      <SetupRunway
        busyAction={busyAction}
        onRestart={() => void runAction("restart")}
        onStart={() => void runAction("start")}
        snapshot={snapshot}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="flex flex-col gap-6">
          <div>
            <div className="mb-3 flex items-center gap-2 px-1">
              <span className="text-sm font-medium">Agent Orchestration</span>
              <span className="text-xs text-muted-foreground">· {activeAgents.length} enabled</span>
            </div>
            <div className="space-y-3">
              <TelegramGatewayControls
                envVars={envVars}
                hasChanges={telegramHasChanges}
                home={telegramHome}
                onHomeChange={setTelegramHome}
                onRestart={() => void runAction("restart")}
                onSave={() => void saveTelegramConfig()}
                onTokenChange={setTelegramToken}
                saving={savingTelegram}
                token={telegramToken}
                tokenConfigured={telegramTokenConfigured}
              />
              <div className="grid gap-3 md:grid-cols-2">
                {snapshot.agents.map((agent) => {
                  const telegramField = telegramFieldForAgent(agent.id, agent.name);
                  return (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      telegramBotTokenPlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.tokenKey, `${agent.name} bot token`)
                          : undefined
                      }
                      telegramBotTokenValue={
                        telegramField ? (telegramAgentTokens[telegramField.tokenKey] ?? "") : undefined
                      }
                      telegramLanePlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.key, "Chat ID or topic ID")
                          : undefined
                      }
                      telegramLaneValue={telegramField ? (telegramLanes[telegramField.key] ?? "") : undefined}
                      onTelegramBotTokenChange={
                        telegramField
                          ? (value) =>
                              setTelegramAgentTokens((prev) => ({
                                ...prev,
                                [telegramField.tokenKey]: value,
                              }))
                          : undefined
                      }
                      onTelegramLaneChange={
                        telegramField
                          ? (value) =>
                              setTelegramLanes((prev) => ({ ...prev, [telegramField.key]: value }))
                          : undefined
                      }
                      onTelegramLaneSave={() => void saveTelegramConfig()}
                      savingTelegram={savingTelegram}
                    />
                  );
                })}
              </div>
            </div>
          </div>

          <HandoffBusCard
            busy={handoffBusy}
            handoffs={snapshot.handoffs}
            onRunWorker={() => void runAgentWorker()}
            onWakeWorker={() => void wakeAgentWorker()}
            worker={snapshot.agentWorker}
          />

          <div>
            <div className="mb-2 px-1 text-sm font-medium">Runtime</div>
            <div className="grid gap-3 md:grid-cols-4 px-1">
              <MiniMetric label="Model" value={snapshot.model.model || "Not set"} />
              <MiniMetric label="Toolsets" value={snapshot.toolsets.enabled.length} />
              <MiniMetric label="Skills" value={`${snapshot.skills.enabled}/${snapshot.skills.total}`} />
              <MiniMetric label="Pairings" value={pendingPairings} />
            </div>
          </div>

          <HarnessCard harness={snapshot.harness} />
        </div>

        <div className="flex flex-col gap-6">
          <div>
            <div className="mb-2 px-1 text-sm font-medium">Memory Graph</div>
            <div className="space-y-3">
              <MemoryConstellation
                compact
                className="min-h-[21rem] rounded-md"
                nodes={snapshot.memory.graph.nodes}
                edges={snapshot.memory.graph.edges}
              />
              <div className="grid grid-cols-2 gap-2 px-1 md:grid-cols-4">
                <MiniMetric label="Pending" value={snapshot.memory.journal.pending} />
                <MiniMetric label="Segments" value={snapshot.memory.journal.session_segment_count} />
                <MiniMetric label="Communities" value={snapshot.memory.community_reports} />
                <MiniMetric label="Relations" value={snapshot.memory.relations} />
              </div>
              <div className="px-1 pb-2 text-xs text-muted-foreground">
                {snapshot.memory.provider} memory / {memoryEmbeddingLabel}
              </div>
            </div>
          </div>

          <div>
            <div className="mb-2 px-1 text-sm font-medium">Sessions</div>
            <div className="space-y-0.5">
              {snapshot.sessions.recent.slice(0, 8).map((session) => (
                <div key={session.id} className="rounded-md px-1 py-1.5 hover:bg-foreground/5">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm">{session.title || "Untitled session"}</span>
                    {session.is_active && (
                      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        live
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{session.source}</span>
                    <span>·</span>
                    <span>{session.message_count} msgs</span>
                    <span>·</span>
                    <span>{timeAgo(session.last_active)}</span>
                  </div>
                </div>
              ))}
              {!snapshot.sessions.recent.length && (
                <div className="py-4 text-sm text-muted-foreground">No sessions yet</div>
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 px-1 text-sm font-medium">Connections</div>
            <div className="max-h-[24rem] overflow-y-auto">
              {(connectedPlatforms.length ? connectedPlatforms : snapshot.platforms.slice(0, 5)).map(
                (platform) => (
                  <PlatformRow key={platform.name} platform={platform} />
                ),
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 px-1 text-sm font-medium">Access</div>
            <div className="space-y-2 px-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{snapshot.access.label}</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                {Object.entries(snapshot.access.entitlements).map(([name, entitlement]) => (
                  <span
                    key={name}
                    className="inline-flex items-center gap-1.5"
                  >
                    <span className={cn(
                      "inline-block h-1.5 w-1.5 rounded-full",
                      entitlement.status === "active" ? "bg-emerald-500" : "bg-border"
                    )} />
                    <span className="text-muted-foreground">{name}</span>
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="truncate">{snapshot.config_path}</span>
              </div>
            </div>
          </div>

          <div>
            <div className="mb-2 px-1 text-sm font-medium">Tools</div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 text-xs text-muted-foreground">
              {snapshot.toolsets.enabled.slice(0, 16).map((toolset) => (
                <span key={toolset}>{toolset}</span>
              ))}
              {!snapshot.toolsets.enabled.length && <span className="text-warning">No toolsets</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        Snapshot {timeAgo(snapshot.generated_at)} / {snapshot.elevate_home}
      </div>
    </div>
  );
}
