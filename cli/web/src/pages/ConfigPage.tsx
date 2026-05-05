import { useCallback, useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import {
  Code,
  Download,
  FormInput,
  RotateCcw,
  RefreshCw,
  Save,
  Search,
  Upload,
  X,
  Settings2,
  FileText,
  Settings,
  Bot,
  Monitor,
  Palette,
  Users,
  Brain,
  Package,
  Lock,
  Globe,
  Mic,
  Volume2,
  Ear,
  ClipboardList,
  MessageCircle,
  Wrench,
  FileQuestion,
  Filter,
  Network,
  ShieldCheck,
  Copy,
  KeyRound,
  Plug,
  ExternalLink,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Loader2,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import {
  api,
  type ComposioConnectedAccount,
  type ComposioStatus,
  type ComposioToolkit,
  type CrmIntegrationForm,
  type IntegrationSettingsResponse,
  type IntegrationTestResponse,
  type SourceConnectorsResponse,
  type SourceConnectorStatus,
} from "@/lib/api";
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { CRM_PRESETS, applyPreset, findPresetForForm, type CrmPreset } from "@/lib/crmPresets";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { AutoField } from "@/components/AutoField";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const CATEGORY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  general: Settings,
  agent: Bot,
  agent_hub: Users,
  platforms: Network,
  terminal: Monitor,
  display: Palette,
  delegation: Users,
  memory: Brain,
  access: ShieldCheck,
  plugins: Package,
  compression: Package,
  security: Lock,
  browser: Globe,
  voice: Mic,
  tts: Volume2,
  stt: Ear,
  logging: ClipboardList,
  discord: MessageCircle,
  auxiliary: Wrench,
};

function CategoryIcon({ category, className }: { category: string; className?: string }) {
  const Icon = CATEGORY_ICONS[category] ?? FileQuestion;
  return <Icon className={className ?? "h-4 w-4"} />;
}

const ADVANCED_CATEGORIES = new Set([
  "auxiliary",
  "browser",
  "compression",
  "discord",
  "logging",
  "security",
  "stt",
  "terminal",
  "tts",
  "voice",
]);

const SETTINGS_LANES = [
  {
    id: "real-estate",
    icon: Users,
    label: "Real estate",
    description: "Profile, access, and local team posture.",
    categories: ["access", "agent_hub", "platforms"],
  },
  {
    id: "agent",
    icon: Bot,
    label: "Agent runtime",
    description: "Models, delegation, orchestration, and behavior.",
    categories: ["agent", "delegation", "general"],
  },
  {
    id: "tools",
    icon: Wrench,
    label: "Tools and connectors",
    description: "Platforms, plugins, browser, terminal, and voice.",
    categories: ["platforms", "plugins", "terminal", "browser", "voice", "stt", "tts"],
  },
  {
    id: "memory",
    icon: Brain,
    label: "Memory",
    description: "Embeddings, session memory, graph state, and recall.",
    categories: ["memory", "compression"],
  },
] as const;

const SETUP_STEPS = [
  {
    label: "1. Connect the model",
    description: "Give Elevate its own OpenAI Codex session so the Hub can start chats without fighting the Codex app.",
    command: "elevate auth add openai-codex",
  },
  {
    label: "2. Pair Telegram",
    description: "Approve a pairing code from the bot so messages route into the local gateway.",
    command: "elevate pairing approve telegram <CODE>",
  },
  {
    label: "3. Restart local gateway",
    description: "Reload config, connectors, agents, skills, and memory settings after setup changes.",
    command: "elevate gateway restart",
  },
] as const;

function modelProvider(config: Record<string, unknown> | null): string {
  const model = config?.model;
  if (model && typeof model === "object" && !Array.isArray(model)) {
    const provider = (model as Record<string, unknown>).provider;
    if (typeof provider === "string" && provider.trim()) return provider;
  }
  return "not selected";
}

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

function connectorVariant(state: SourceConnectorStatus["state"]): "success" | "warning" | "outline" {
  if (state === "connected" || state === "import_only") return "success";
  if (state === "blocked" || state === "error" || state === "needs_operator") return "warning";
  return "outline";
}

function connectorSetupCopy(connector: SourceConnectorStatus): string {
  if (connector.initializeBehavior === "local_messages_import") {
    return connector.sourceExists
      ? "Re-imports synced Mac Messages into Elevate's local message index: people, conversations, messages, and conversation-days."
      : "Reads the synced Mac Messages database and builds a local Elevate message index for lead context.";
  }
  if (connector.initializeBehavior === "composio_social_setup") {
    return connector.sourceExists
      ? "Refreshes the local Composio social setup record and next operator step. Add social accounts inside Composio, then run a sync/import."
      : "Sets up Composio as the social account hub for metrics, DMs, comments, lead moments, content tasks, and approval-gated replies.";
  }
  return connector.sourceExists
    ? "Refreshes the local agent setup task and prompt for building the real connector. It does not fabricate demo lead data."
    : "Creates a local setup task for the agent/operator to build the webhook, poller, import command, or bridge.";
}

function connectorActionLabel(connector: SourceConnectorStatus, busy: boolean): string {
  if (busy) {
    if (connector.initializeBehavior === "local_messages_import") return "Importing";
    if (connector.initializeBehavior === "composio_social_setup") {
      return connector.sourceExists ? "Syncing social accounts" : "Preparing Composio";
    }
    return connector.sourceExists ? "Refreshing" : "Creating task";
  }
  if (connector.initializeBehavior === "local_messages_import") {
    return connector.sourceExists ? "Re-import messages" : "Import messages";
  }
  if (connector.initializeBehavior === "composio_social_setup") {
    return connector.sourceExists ? "Sync social accounts" : "Set up Composio";
  }
  return connector.sourceExists ? "Refresh setup task" : "Create setup task";
}

const TOOLKIT_PAGE_SIZE = 24;

function toolkitLogo(tk: ComposioToolkit | undefined): string | undefined {
  if (!tk) return undefined;
  return tk.meta?.logo ?? tk.logo;
}

function toolkitDescription(tk: ComposioToolkit | undefined): string | undefined {
  if (!tk) return undefined;
  return tk.meta?.description ?? tk.description;
}

function toolkitCategoryLabels(tk: ComposioToolkit): string[] {
  const out = new Set<string>();
  for (const c of tk.meta?.categories ?? []) {
    const name = (c?.name ?? c?.id ?? "").toString().trim();
    if (name) out.add(name.toLowerCase());
  }
  for (const c of tk.categories ?? []) {
    const name = (c?.name ?? c?.slug ?? c?.id ?? "").toString().trim();
    if (name) out.add(name.toLowerCase());
  }
  return [...out];
}

function ComposioPanel() {
  const [status, setStatus] = useState<ComposioStatus | null>(null);
  const [connections, setConnections] = useState<ComposioConnectedAccount[]>([]);
  const [toolkits, setToolkits] = useState<ComposioToolkit[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [connectingSlug, setConnectingSlug] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [toolkitQuery, setToolkitQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [visibleCount, setVisibleCount] = useState<number>(TOOLKIT_PAGE_SIZE);
  const [customAuthState, setCustomAuthState] = useState<{
    slug: string;
    name: string;
    authScheme?: string;
    authGuideUrl?: string | null;
    required: Array<{ name: string; displayName?: string; description?: string; type?: string; required?: boolean }>;
    optional: Array<{ name: string; displayName?: string; description?: string; type?: string; default?: string }>;
    values: Record<string, string>;
    submitting: boolean;
    error: string | null;
  } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.getComposioStatus();
      setStatus(s);
      if (s.valid) {
        const [conns, tks] = await Promise.all([
          api.getComposioConnections(),
          api.getComposioToolkits(),
        ]);
        const conData = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setConnections(Array.isArray(conData) ? conData : conData.items ?? []);
        const tkData = (tks.data as { items?: ComposioToolkit[] } | ComposioToolkit[]) ?? [];
        setToolkits(Array.isArray(tkData) ? tkData : tkData.items ?? []);
      } else {
        setConnections([]);
        setToolkits([]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // After Connect opens the Composio OAuth tab in a new window, the user
  // completes the flow there and switches back. Refresh on focus so the
  // newly-linked account shows up without making them hit Refresh.
  useEffect(() => {
    const onFocus = () => {
      if (status?.valid) void refresh();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh, status?.valid]);

  const saveKey = async () => {
    if (!keyInput.trim()) return;
    setSavingKey(true);
    setKeyError(null);
    try {
      const next = await api.setComposioKey(keyInput.trim());
      setStatus(next);
      if (!next.valid) {
        setKeyError(next.error ?? "Key saved but Composio rejected it.");
      } else {
        setKeyInput("");
      }
      await refresh();
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  };

  const clearKey = async () => {
    setSavingKey(true);
    setKeyError(null);
    try {
      const next = await api.clearComposioKey();
      setStatus(next);
      setConnections([]);
      setToolkits([]);
    } finally {
      setSavingKey(false);
    }
  };

  const connect = async (slug: string) => {
    setConnectingSlug(slug);
    setKeyError(null);
    try {
      const result = await api.initiateComposioConnection({ toolkitSlug: slug });
      const url = result.data?.redirect_url ?? result.data?.redirect_uri;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }
      // Composio returned no managed creds for this toolkit — fetch its
      // schema and open the custom-credentials modal so the user can paste
      // their own client_id / client_secret.
      const errMsg = (result.error || "") + " " + JSON.stringify((result as unknown as Record<string, unknown>).raw ?? "");
      const needsCustom =
        /Default auth config not found/i.test(errMsg) ||
        /Auth_Config_DefaultAuthConfigNotFound/i.test(errMsg) ||
        /use_custom_auth/i.test(errMsg);
      if (needsCustom) {
        const details = await api.getComposioToolkitDetails(slug);
        const tk = (details as unknown as { name?: string; slug?: string; auth_config_details?: unknown[] }) ?? {};
        // The /toolkits/{slug} payload comes back un-wrapped (no {ok,data})
        // in the `data` field via _request(); but our typed wrapper still
        // returns ComposioApiResult. Pull the underlying body either way.
        const body = (details.data ?? details) as unknown as {
          name?: string;
          slug?: string;
          auth_config_details?: Array<{
            name?: string;
            mode?: string;
            fields?: { auth_config_creation?: { required?: unknown[]; optional?: unknown[] } };
          }>;
          auth_guide_url?: string | null;
        };
        const scheme = body.auth_config_details?.[0];
        const required = (scheme?.fields?.auth_config_creation?.required ?? []) as Array<{
          name: string; displayName?: string; description?: string; type?: string; required?: boolean;
        }>;
        const optional = (scheme?.fields?.auth_config_creation?.optional ?? []) as Array<{
          name: string; displayName?: string; description?: string; type?: string; default?: string;
        }>;
        setCustomAuthState({
          slug,
          name: body.name || tk.name || slug,
          authScheme: scheme?.mode,
          authGuideUrl: body.auth_guide_url || null,
          required,
          optional,
          values: Object.fromEntries(
            [...required.map((f) => [f.name, ""]), ...optional.map((f) => [f.name, f.default ?? ""])],
          ) as Record<string, string>,
          submitting: false,
          error: null,
        });
        return;
      }
      if (result.error) {
        setKeyError(result.error);
      } else {
        setKeyError(
          `Composio didn't return an OAuth URL for ${slug}. Try Refresh, then click Add another again.`,
        );
      }
    } finally {
      setConnectingSlug(null);
    }
  };

  const submitCustomAuth = async () => {
    if (!customAuthState) return;
    const missing = customAuthState.required.filter((f) => !(customAuthState.values[f.name] || "").trim());
    if (missing.length > 0) {
      setCustomAuthState({
        ...customAuthState,
        error: `Required: ${missing.map((m) => m.displayName || m.name).join(", ")}`,
      });
      return;
    }
    setCustomAuthState({ ...customAuthState, submitting: true, error: null });
    try {
      const creds: Record<string, string> = {};
      for (const f of [...customAuthState.required, ...customAuthState.optional]) {
        const v = customAuthState.values[f.name];
        if (v && v.trim()) creds[f.name] = v.trim();
      }
      const result = await api.createComposioCustomAuth({
        toolkitSlug: customAuthState.slug,
        credentials: creds,
        authScheme: customAuthState.authScheme,
      });
      const url = result.data?.redirect_url ?? result.data?.redirect_uri;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        setCustomAuthState(null);
        await refresh();
      } else {
        setCustomAuthState({
          ...customAuthState,
          submitting: false,
          error: result.error || "Composio returned no redirect URL.",
        });
      }
    } catch (err) {
      setCustomAuthState({
        ...customAuthState,
        submitting: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const disconnect = async (id: string) => {
    if (!id) return;
    setConnectingSlug(id);
    try {
      await api.deleteComposioConnection(id);
      await refresh();
    } finally {
      setConnectingSlug(null);
    }
  };

  const statusBadge = (() => {
    if (!status) return <Badge variant="outline">checking...</Badge>;
    if (!status.hasKey) return <Badge variant="outline">not configured</Badge>;
    if (status.valid) return <Badge variant="success">connected</Badge>;
    return <Badge variant="warning">key invalid</Badge>;
  })();

  const connectedSlugs = new Set(
    connections.map((c) => c.toolkit?.slug).filter(Boolean) as string[],
  );

  const allCategories = useMemo(() => {
    const set = new Set<string>();
    for (const tk of toolkits) for (const c of toolkitCategoryLabels(tk)) set.add(c);
    return [...set].sort();
  }, [toolkits]);

  const filteredToolkits = useMemo(() => {
    const q = toolkitQuery.trim().toLowerCase();
    return toolkits.filter((tk) => {
      const slug = String(tk.slug ?? "").toLowerCase();
      const name = String(tk.name ?? "").toLowerCase();
      const desc = String(toolkitDescription(tk) ?? "").toLowerCase();
      if (q && !slug.includes(q) && !name.includes(q) && !desc.includes(q)) return false;
      if (categoryFilter !== "all") {
        const cats = toolkitCategoryLabels(tk);
        if (!cats.includes(categoryFilter)) return false;
      }
      return true;
    });
  }, [toolkits, toolkitQuery, categoryFilter]);

  useEffect(() => {
    setVisibleCount(TOOLKIT_PAGE_SIZE);
  }, [toolkitQuery, categoryFilter]);

  const visibleToolkits = filteredToolkits.slice(0, visibleCount);

  return (
    <Card id="composio" className="scroll-mt-24">
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Plug className="h-4 w-4 text-primary" />
              Composio
            </CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              One auth hub for both messaging (Gmail, Twilio, WhatsApp) and social (Instagram, X, LinkedIn). Add your Composio API key, then connect each app. Apps shown below are pulled live from your Composio account.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {statusBadge}
            <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-2xl border border-border/65 bg-background/35 p-3">
          <label className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground">
            <KeyRound className="h-3.5 w-3.5" />
            API key
          </label>
          {status?.hasKey ? (
            <div className="flex flex-wrap items-center gap-2">
              <code className="flex-1 truncate rounded-md bg-background/60 px-2 py-1.5 text-xs">
                {status.valid ? "key configured" : "key configured (invalid)"}
              </code>
              <Button variant="outline" size="sm" onClick={() => void clearKey()} disabled={savingKey}>
                <Trash2 className="h-3.5 w-3.5" />
                Remove
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="password"
                placeholder="ck_..."
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                className="min-w-[16rem] flex-1"
              />
              <Button size="sm" onClick={() => void saveKey()} disabled={savingKey || !keyInput.trim()}>
                {savingKey ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                Save
              </Button>
            </div>
          )}
          {keyError && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-500">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{keyError}</span>
            </div>
          )}
          {status && status.hasKey && !status.valid && !keyError && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-500">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{status.error ?? "Composio rejected the key. Rotate it at composio.dev and re-save."}</span>
            </div>
          )}
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            Get a key at{" "}
            <a
              href="https://app.composio.dev/developers"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline-offset-4 hover:underline"
            >
              composio.dev/developers
              <ExternalLink className="ml-1 inline h-3 w-3" />
            </a>
            . Stored in your local .env, never sent anywhere except Composio.
          </p>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Connected accounts ({connections.length})
            </h4>
          </div>
          {!status?.valid ? (
            <div className="rounded-2xl border border-dashed border-border/65 bg-background/25 px-4 py-6 text-center text-xs text-muted-foreground">
              <CircleSlash className="mx-auto mb-2 h-4 w-4" />
              Add a working API key to see your connected accounts.
            </div>
          ) : connections.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/65 bg-background/25 px-4 py-6 text-center text-xs text-muted-foreground">
              No accounts connected yet. Pick one below to start.
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {connections.map((conn, idx) => (
                <div
                  key={String(conn.id ?? idx)}
                  className="flex items-center gap-3 rounded-2xl border border-border/65 bg-background/35 p-3"
                >
                  {(conn.toolkit?.meta?.logo ?? conn.toolkit?.logo) ? (
                    <img
                      src={conn.toolkit?.meta?.logo ?? conn.toolkit?.logo}
                      alt=""
                      className="h-8 w-8 rounded-md bg-background/60 object-contain p-1"
                    />
                  ) : (
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-background/60">
                      <Plug className="h-4 w-4 text-muted-foreground" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">
                        {conn.toolkit?.name ?? conn.toolkit?.slug ?? "Unknown app"}
                      </span>
                      {conn.status === "ACTIVE" && (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                      )}
                    </div>
                    {conn.user_id && (
                      <div className="truncate text-xs text-muted-foreground">{conn.user_id}</div>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void disconnect(String(conn.id ?? ""))}
                    disabled={connectingSlug === String(conn.id ?? "")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        {status?.valid && (
          <div>
            <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Available apps ({filteredToolkits.length}
                {filteredToolkits.length !== toolkits.length ? ` of ${toolkits.length}` : ""})
              </h4>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="search"
                    placeholder="Search apps..."
                    value={toolkitQuery}
                    onChange={(e) => setToolkitQuery(e.target.value)}
                    className="h-8 w-44 pl-7 text-xs"
                  />
                </div>
                {allCategories.length > 0 && (
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="h-8 rounded-md border border-border/65 bg-background/60 px-2 text-xs text-foreground"
                  >
                    <option value="all">All categories</option>
                    {allCategories.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>
            {filteredToolkits.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border/65 bg-background/25 px-4 py-6 text-center text-xs text-muted-foreground">
                {toolkits.length === 0 ? "No toolkits returned by Composio." : "No apps match that filter."}
              </div>
            ) : (
              <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-8">
                {visibleToolkits.map((tk) => {
                  const slug = String(tk.slug ?? "");
                  const isConnected = connectedSlugs.has(slug);
                  const logo = toolkitLogo(tk);
                  const desc = toolkitDescription(tk);
                  return (
                    <div
                      key={slug}
                      className="group flex flex-col items-center gap-2 rounded-2xl border border-border/65 bg-background/35 p-3 text-center transition-colors hover:border-primary/60 hover:bg-background/55"
                      title={desc ? `${tk.name ?? slug} — ${desc}` : tk.name ?? slug}
                    >
                      {logo ? (
                        <img
                          src={logo}
                          alt=""
                          className="h-10 w-10 rounded-md bg-background/60 object-contain p-1"
                          loading="lazy"
                        />
                      ) : (
                        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-background/60">
                          <Plug className="h-4 w-4 text-muted-foreground" />
                        </div>
                      )}
                      <div className="w-full truncate text-xs font-medium text-foreground">
                        {tk.name ?? slug}
                      </div>
                      <Button
                        variant={isConnected ? "outline" : "default"}
                        size="sm"
                        className="h-7 w-full px-2 text-xs"
                        onClick={() => void connect(slug)}
                        disabled={connectingSlug === slug}
                      >
                        {connectingSlug === slug ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : isConnected ? (
                          "Add another"
                        ) : (
                          "Connect"
                        )}
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
            {visibleCount < filteredToolkits.length && (
              <div className="mt-3 flex items-center justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setVisibleCount((n) => n + TOOLKIT_PAGE_SIZE)}
                >
                  Load {Math.min(TOOLKIT_PAGE_SIZE, filteredToolkits.length - visibleCount)} more
                </Button>
              </div>
            )}
            {filteredToolkits.length > 0 && visibleCount >= filteredToolkits.length && (
              <p className="mt-2 text-xs text-muted-foreground">
                Showing all {filteredToolkits.length}{filteredToolkits.length !== toolkits.length ? ` of ${toolkits.length}` : ""} apps.
              </p>
            )}
          </div>
        )}
      </CardContent>
      {customAuthState && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
          onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
        >
          <div
            className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-base font-semibold">{customAuthState.name}</div>
                  <div className="text-xs text-muted-foreground">
                    This connection requires custom OAuth credentials.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
                  className="rounded-full bg-background/60 px-2 py-1 font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                >
                  close
                </button>
              </div>
              {customAuthState.authGuideUrl && (
                <a
                  href={customAuthState.authGuideUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-block text-xs text-primary hover:underline"
                >
                  View auth setup guide ↗
                </a>
              )}
            </div>
            <div className="space-y-4 px-5 py-4 max-h-[60vh] overflow-y-auto">
              {[...customAuthState.required, ...customAuthState.optional].map((field) => {
                const isOptional = !customAuthState.required.find((r) => r.name === field.name);
                const isSecret = /secret|password|token|key/i.test(field.name);
                return (
                  <div key={field.name} className="space-y-1">
                    <label className="flex items-center gap-1.5 text-sm font-medium">
                      {field.displayName || field.name}
                      {!isOptional && <span className="text-destructive">*</span>}
                      {isOptional && (
                        <span className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">optional</span>
                      )}
                    </label>
                    {field.description && (
                      <div className="text-xs text-muted-foreground">{field.description}</div>
                    )}
                    <input
                      type={isSecret ? "password" : "text"}
                      value={customAuthState.values[field.name] || ""}
                      onChange={(e) =>
                        setCustomAuthState({
                          ...customAuthState,
                          values: { ...customAuthState.values, [field.name]: e.target.value },
                          error: null,
                        })
                      }
                      placeholder={field.displayName || field.name}
                      className="w-full rounded-lg border border-border bg-background/40 px-3 py-2 text-sm outline-none focus:border-primary/60"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </div>
                );
              })}
              {customAuthState.error && (
                <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {customAuthState.error}
                </div>
              )}
            </div>
            <div className="border-t border-border px-5 py-3">
              <Button
                onClick={submitCustomAuth}
                disabled={customAuthState.submitting}
                className="w-full"
              >
                {customAuthState.submitting ? "Creating..." : "Create Auth Config & Connect"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

function SourceConnectorSettingsPanel() {
  const [data, setData] = useState<SourceConnectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [composioAccounts, setComposioAccounts] = useState<ComposioConnectedAccount[]>([]);
  const [composioReady, setComposioReady] = useState<boolean>(false);
  const [lastSyncSummary, setLastSyncSummary] = useState<{
    total_new?: number;
    total_fetched?: number;
    tick_at?: string;
  } | null>(null);
  const [fbPages, setFbPages] = useState<Array<{
    id: string;
    name: string;
    selected: boolean;
  }>>([]);
  const [fbPickerOpen, setFbPickerOpen] = useState(false);
  const [fbPickerLoading, setFbPickerLoading] = useState(false);
  const [fbPickerSaving, setFbPickerSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.getSourceConnectors());
    } finally {
      setLoading(false);
    }
  }, []);

  const loadComposio = useCallback(async () => {
    try {
      const status = await api.getComposioStatus();
      if (!status.valid) {
        setComposioReady(false);
        setComposioAccounts([]);
        return;
      }
      setComposioReady(true);
      const conns = await api.getComposioConnections();
      const body = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
      setComposioAccounts(Array.isArray(body) ? body : body.items ?? []);
    } catch {
      // Composio key not set yet — leave empty, the source row still works.
    }
  }, []);

  const loadFbPages = useCallback(async () => {
    setFbPickerLoading(true);
    try {
      const resp = await api.getComposioFacebookPages();
      if (resp.ok) {
        setFbPages(resp.pages.map(p => ({ id: p.id, name: p.name, selected: p.selected })));
      }
    } catch {
      // Composio not connected or no FB account — picker stays empty.
    } finally {
      setFbPickerLoading(false);
    }
  }, []);

  const toggleFbPage = async (pageId: string) => {
    const next = fbPages.map(p => p.id === pageId ? { ...p, selected: !p.selected } : p);
    setFbPages(next);
    setFbPickerSaving(true);
    try {
      const ids = next.filter(p => p.selected).map(p => p.id);
      await api.setComposioFacebookPages(ids);
    } finally {
      setFbPickerSaving(false);
    }
  };

  const hasFacebookAccount = composioAccounts.some(
    a => (a.toolkit?.slug ?? "").toLowerCase() === "facebook",
  );
  const fbSelectedCount = fbPages.filter(p => p.selected).length;

  useEffect(() => {
    void load();
    void loadComposio();
  }, [load, loadComposio]);

  useEffect(() => {
    if (hasFacebookAccount) {
      void loadFbPages();
    } else {
      setFbPages([]);
    }
  }, [hasFacebookAccount, loadFbPages]);

  const initialize = async (connector: SourceConnectorStatus) => {
    setBusyId(connector.id);
    try {
      const next = connector.sourceExists
        ? await api.refreshSourceConnector(connector.id)
        : await api.scaffoldSourceConnector(connector.id);
      setData(next);
      const refresh = (next as unknown as { refresh?: { total_new?: number; total_fetched?: number; tick_at?: string } }).refresh;
      if (refresh && connector.initializeBehavior === "composio_social_setup") {
        setLastSyncSummary(refresh);
        void loadComposio();
      }
    } finally {
      setBusyId(null);
    }
  };

  const copyPrompt = async (connector: SourceConnectorStatus) => {
    await navigator.clipboard.writeText(connector.prompt);
    setCopiedId(connector.id);
    window.setTimeout(() => setCopiedId(null), 1600);
  };

  const connectors = data?.connectors ?? [];
  const ready = connectors.filter((connector) => connector.state === "connected" || connector.state === "import_only").length;

  return (
    <Card id="connectors" className="scroll-mt-24">
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              Source connectors
            </CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Setup lives here. Apple Messages can build a real local message index. Social apps use Composio as the account hub. Other sources create an agent setup task until a webhook, poller, import command, or bridge exists.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{ready}/{connectors.length || 12} ready</Badge>
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-2xl border border-border/65 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
          <div className="font-medium text-foreground">Source root</div>
          <code className="mt-1 block break-all bg-transparent p-0">{data?.sourceRoot ?? "Loading source root..."}</code>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {connectors.map((connector) => (
            <div key={connector.id} className="rounded-2xl border border-border/65 bg-background/35 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold text-foreground">{connector.label}</span>
                    <Badge variant={connectorVariant(connector.state)}>{connector.state.replace(/_/g, " ")}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {connectorSetupCopy(connector)}
                  </p>
                </div>
                <Badge variant="outline">{connectorRecordTotal(connector)} records</Badge>
              </div>
              {connector.nextOperatorStep && (
                <div className="mt-3 rounded-xl bg-background/45 px-2.5 py-2 text-xs leading-5 text-muted-foreground">
                  {connector.nextOperatorStep}
                </div>
              )}
              {connector.initializeBehavior === "composio_social_setup" && (
                <div className="mt-3 rounded-xl border border-border/45 bg-background/45 p-2.5 text-xs">
                  {!composioReady ? (
                    <div className="text-muted-foreground">
                      Add your Composio API key in the Composio panel to connect social accounts.
                    </div>
                  ) : composioAccounts.length === 0 ? (
                    <div className="text-muted-foreground">
                      No social accounts connected yet. Add one from the Composio panel below.
                    </div>
                  ) : (
                    <>
                      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Social accounts ({composioAccounts.length})
                      </div>
                      <ul className="flex flex-wrap gap-1.5">
                        {composioAccounts.map((acc, idx) => {
                          const logo = acc.toolkit?.meta?.logo ?? acc.toolkit?.logo;
                          const name = acc.toolkit?.name ?? acc.toolkit?.slug ?? "Unknown";
                          return (
                            <li
                              key={String(acc.id ?? idx)}
                              className="inline-flex items-center gap-1.5 rounded-full border border-border/50 bg-background/50 px-2 py-0.5"
                              title={acc.user_id ? `${name} • ${acc.user_id}` : name}
                            >
                              {logo ? (
                                <img src={logo} alt="" className="h-3.5 w-3.5 rounded-sm object-contain" />
                              ) : (
                                <Plug className="h-3 w-3 text-muted-foreground" />
                              )}
                              <span className="text-[11px] text-foreground">{name}</span>
                              {acc.status === "ACTIVE" && (
                                <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                              )}
                            </li>
                          );
                        })}
                      </ul>
                      {hasFacebookAccount && (
                        <div className="mt-3 rounded-xl border border-border/40 bg-background/60 p-2.5">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                              Facebook pages on /leads
                            </div>
                            <button
                              type="button"
                              className="text-[11px] text-primary hover:underline"
                              onClick={() => {
                                setFbPickerOpen((v) => !v);
                                if (!fbPickerOpen) void loadFbPages();
                              }}
                            >
                              {fbPickerOpen ? "Done" : "Edit"}
                            </button>
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            {fbPickerLoading
                              ? "Loading pages..."
                              : fbPages.length === 0
                                ? "No pages found on this Facebook account."
                                : `${fbSelectedCount} of ${fbPages.length} pages will sync to the leads board. The Composio MCP stays connected to all of them.`}
                            {fbPickerSaving && <span className="ml-1 italic">Saving...</span>}
                          </div>
                          {fbPickerOpen && fbPages.length > 0 && (
                            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                              {fbPages.map((p) => (
                                <li key={p.id}>
                                  <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] text-foreground hover:bg-background/80">
                                    <input
                                      type="checkbox"
                                      checked={p.selected}
                                      onChange={() => void toggleFbPage(p.id)}
                                      className="h-3.5 w-3.5"
                                    />
                                    <span className="truncate">{p.name}</span>
                                  </label>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                      {lastSyncSummary && (
                        <div className="mt-2 text-[11px] text-muted-foreground">
                          Last sync: {lastSyncSummary.total_new ?? 0} new / {lastSyncSummary.total_fetched ?? 0} fetched
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline">{connector.ownerAgent}</Badge>
                {connector.connectionType && <Badge variant="outline">{connector.connectionType}</Badge>}
                <Button
                  variant={connector.sourceExists ? "outline" : "default"}
                  size="sm"
                  className="ml-auto h-7 px-2.5"
                  onClick={() => void initialize(connector)}
                  disabled={busyId === connector.id}
                >
                  {connectorActionLabel(connector, busyId === connector.id)}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2.5"
                  onClick={() => void copyPrompt(connector)}
                >
                  <Copy className="h-3.5 w-3.5" />
                  {copiedId === connector.id ? "Copied" : "Prompt"}
                </Button>
              </div>
            </div>
          ))}
          {loading && !connectors.length && (
            <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-6 text-sm text-muted-foreground">
              Loading connector blueprints...
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CrmIntegrationSettingsPanel() {
  const [data, setData] = useState<IntegrationSettingsResponse | null>(null);
  const [form, setForm] = useState<CrmIntegrationForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<IntegrationTestResponse | null>(null);
  const [mode, setMode] = useState<"picker" | "preset" | "custom">("picker");
  const [selectedPreset, setSelectedPreset] = useState<CrmPreset | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getIntegrations();
      setData(next);
      const initialForm = { ...next.crm, apiKey: "" };
      setForm(initialForm);
      const matchingPreset = findPresetForForm(initialForm);
      if (matchingPreset) {
        setSelectedPreset(matchingPreset);
        setMode("preset");
      } else if (initialForm.provider || initialForm.baseUrl) {
        setMode("custom");
      } else {
        setMode("picker");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const connectedPresetSlug = useMemo(() => {
    if (!data?.crm.hasApiKey) return null;
    const matching = findPresetForForm(data.crm);
    return matching?.slug ?? null;
  }, [data]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = (next: Partial<CrmIntegrationForm>) => {
    setForm((current) => current ? { ...current, ...next } : current);
  };

  const patchNested = <K extends "dbColumns" | "endpoints">(
    key: K,
    field: keyof CrmIntegrationForm[K],
    value: string,
  ) => {
    setForm((current) =>
      current
        ? { ...current, [key]: { ...current[key], [field]: value } }
        : current,
    );
  };

  const choosePreset = (preset: CrmPreset) => {
    setSelectedPreset(preset);
    setForm((current) => applyPreset(preset, current));
    setMode("preset");
    setTestResult(null);
    setShowAdvanced(false);
  };

  const chooseCustom = () => {
    setSelectedPreset(null);
    setMode("custom");
    setTestResult(null);
  };

  const backToPicker = () => {
    setMode("picker");
    setTestResult(null);
    setShowAdvanced(false);
  };

  const save = async () => {
    if (!form) return;
    setSaving(true);
    setTestResult(null);
    try {
      const next = await api.saveIntegrations(form);
      setData(next);
      const nextForm = { ...next.crm, apiKey: "" };
      setForm(nextForm);
      const matchingPreset = findPresetForForm(nextForm);
      if (matchingPreset) {
        setSelectedPreset(matchingPreset);
        setMode("preset");
      }
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!form) return;
    setTesting(true);
    try {
      setTestResult(await api.testIntegration(form));
    } finally {
      setTesting(false);
    }
  };

  const canSave = form && (form.apiKey || form.hasApiKey) && (form.baseUrl || mode === "custom");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          Connect your CRM
        </CardTitle>
        <p className="text-xs leading-5 text-foreground/70">
          Pick your CRM, paste your API key, and we handle the rest. Lofty, Follow Up Boss, Sierra, BoldTrail and Brivity are pre-wired.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading || !form ? (
          <div className="rounded-2xl border border-border bg-card px-4 py-6 text-sm text-foreground/70">
            Loading CRM settings...
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {CRM_PRESETS.map((preset) => {
                const isSelected = mode === "preset" && selectedPreset?.slug === preset.slug;
                const isConnected = connectedPresetSlug === preset.slug;
                return (
                  <button
                    key={preset.slug}
                    type="button"
                    onClick={() => choosePreset(preset)}
                    title={`${preset.label} — ${preset.description}`}
                    className={`group flex flex-col items-center gap-2 rounded-2xl border bg-card p-3 text-center transition-colors hover:border-primary/60 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${isSelected ? "border-primary" : "border-border"}`}
                  >
                    <div className="relative">
                      <img
                        src={preset.logo}
                        alt=""
                        width={40}
                        height={40}
                        loading="lazy"
                        decoding="async"
                        className="h-10 w-10 rounded-md bg-card object-contain p-1"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                          const fallback = e.currentTarget.nextElementSibling as HTMLElement | null;
                          if (fallback) fallback.style.display = "flex";
                        }}
                      />
                      <div className="hidden h-10 w-10 items-center justify-center rounded-md bg-card">
                        <Plug className="h-4 w-4 text-foreground/70" />
                      </div>
                      {isConnected && (
                        <CheckCircle2 className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full bg-card text-emerald-500" />
                      )}
                    </div>
                    <div className="w-full truncate text-xs font-medium text-foreground">{preset.label}</div>
                    <Button
                      variant={isConnected ? "outline" : "default"}
                      size="sm"
                      className="h-7 w-full px-2 text-xs"
                    >
                      {isConnected ? "Connected" : "Connect"}
                    </Button>
                  </button>
                );
              })}
              <button
                type="button"
                onClick={chooseCustom}
                title="Other — wire up any REST CRM"
                className={`group flex flex-col items-center gap-2 rounded-2xl border bg-card p-3 text-center transition-colors hover:border-primary/60 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${mode === "custom" ? "border-primary" : "border-border"}`}
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-card">
                  <Settings2 className="h-4 w-4 text-foreground/70" />
                </div>
                <div className="w-full truncate text-xs font-medium text-foreground">Other / Custom</div>
                <Button variant="outline" size="sm" className="h-7 w-full px-2 text-xs">Wire up</Button>
              </button>
            </div>

            {mode === "preset" && selectedPreset && (
              <div className="space-y-3 rounded-2xl border border-border bg-card p-4">
                <div className="flex items-center gap-3">
                  <img
                    src={selectedPreset.logo}
                    alt=""
                    width={32}
                    height={32}
                    className="h-8 w-8 rounded-md bg-card object-contain p-1"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                  <span className="text-sm font-semibold text-foreground">{selectedPreset.label}</span>
                </div>
                {selectedPreset.notice && (
              <div className="rounded-2xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-5 text-warning">
                <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5 align-text-bottom" />
                {selectedPreset.notice}
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-foreground/80" htmlFor="crm-preset-api-key">
                {selectedPreset.keyLabel}
              </label>
              <Input
                id="crm-preset-api-key"
                type="password"
                value={form.apiKey ?? ""}
                placeholder={form.hasApiKey ? `Saved · ${form.apiKeyPreview ?? "•••"}` : "Paste your API key"}
                onChange={(e) => patch({ apiKey: e.target.value })}
              />
              <a
                href={selectedPreset.helpUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-foreground/65 transition-colors hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" />
                Where do I find this? — {selectedPreset.helpText}
              </a>
            </div>
            {testResult && (
              <div className={`rounded-2xl border px-3 py-2 text-xs ${testResult.success ? "border-success/25 bg-success/10 text-success" : "border-warning/25 bg-warning/10 text-warning"}`}>
                {testResult.message ?? testResult.error ?? "Test finished"}
              </div>
            )}
            <div className="flex flex-wrap justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-9 px-3 text-foreground/70"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "Hide advanced" : "Show advanced"}
              </Button>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" className="h-9 px-3" onClick={() => void test()} disabled={testing || !canSave}>
                  {testing ? "Testing" : "Test connection"}
                </Button>
                <Button size="sm" className="h-9 px-3" onClick={() => void save()} disabled={saving || !canSave}>
                  {saving ? "Saving" : "Connect"}
                </Button>
              </div>
            </div>
            {showAdvanced && (
              <div className="space-y-3 rounded-2xl border border-border bg-card p-3">
                <div className="text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-foreground/55">
                  Advanced — pre-wired by preset
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={form.baseUrl} placeholder="base URL" onChange={(e) => patch({ baseUrl: e.target.value })} />
                  <Input value={form.authHeader} placeholder="header" onChange={(e) => patch({ authHeader: e.target.value })} />
                  <Input value={form.authPrefix} placeholder="prefix" onChange={(e) => patch({ authPrefix: e.target.value })} />
                  <Input value={form.endpoints.leads} placeholder="leads endpoint" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} />
                  <Input value={form.endpoints.lead} placeholder="lead endpoint" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} />
                  <Input value={form.endpoints.notes} placeholder="notes endpoint" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} />
                </div>
              </div>
            )}
              </div>
            )}
            {mode === "custom" && (
              <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Settings2 className="h-4 w-4 text-foreground/70" />
                <span className="text-sm font-semibold text-foreground">Custom CRM</span>
              </div>
              <Button variant="ghost" size="sm" className="h-9 px-3" onClick={backToPicker}>
                Change CRM
              </Button>
            </div>
            <div className="grid gap-2 md:grid-cols-3">
              <Input value={form.provider} placeholder="provider" onChange={(e) => patch({ provider: e.target.value })} />
              <Input value={form.label} placeholder="label" onChange={(e) => patch({ label: e.target.value })} />
              <Input value={form.baseUrl} placeholder="https://api.example.com" onChange={(e) => patch({ baseUrl: e.target.value })} />
              <Input value={form.apiKeyEnv} placeholder="CRM_API_KEY" onChange={(e) => patch({ apiKeyEnv: e.target.value })} />
              <Input value={form.apiKey ?? ""} type="password" placeholder={form.hasApiKey ? `API key ${form.apiKeyPreview ?? "saved"}` : "API key"} onChange={(e) => patch({ apiKey: e.target.value })} />
              <Input value={form.authType} placeholder="header or query" onChange={(e) => patch({ authType: e.target.value })} />
              <Input value={form.authHeader} placeholder="Authorization" onChange={(e) => patch({ authHeader: e.target.value })} />
              <Input value={form.authPrefix} placeholder="Bearer " onChange={(e) => patch({ authPrefix: e.target.value })} />
              <Input value={form.authQueryParam} placeholder="api_key" onChange={(e) => patch({ authQueryParam: e.target.value })} />
            </div>
            <div className="grid gap-2 md:grid-cols-3">
              <Input value={form.endpoints.leads} placeholder="/v1/leads" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} />
              <Input value={form.endpoints.lead} placeholder="/v1/leads/:id" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} />
              <Input value={form.endpoints.notes} placeholder="/v1/leads/:id/notes" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} />
              <Input value={form.dbColumns.leadId} placeholder="crm_lead_id" onChange={(e) => patchNested("dbColumns", "leadId", e.target.value)} />
              <Input value={form.dbColumns.stage} placeholder="crm_stage" onChange={(e) => patchNested("dbColumns", "stage", e.target.value)} />
              <Input value={form.dbColumns.tags} placeholder="crm_tags" onChange={(e) => patchNested("dbColumns", "tags", e.target.value)} />
            </div>
            <div className="rounded-2xl border border-border bg-card p-3 text-xs leading-5 text-foreground/65">
              <div>Config: <code className="bg-transparent p-0">{data?.configPath}</code></div>
              <div>Secrets: <code className="bg-transparent p-0">{data?.secretsPath}</code></div>
            </div>
            {testResult && (
              <div className={`rounded-2xl border px-3 py-2 text-xs ${testResult.success ? "border-success/25 bg-success/10 text-success" : "border-warning/25 bg-warning/10 text-warning"}`}>
                {testResult.message ?? testResult.error ?? "Test finished"}
              </div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" size="sm" className="h-9 px-3" onClick={() => void test()} disabled={testing}>
                {testing ? "Testing" : "Test"}
              </Button>
              <Button size="sm" className="h-9 px-3" onClick={() => void save()} disabled={saving}>
                {saving ? "Saving" : "Save CRM"}
              </Button>
            </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ConfigPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [yamlMode, setYamlMode] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(true);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();
  const { setEnd } = usePageHeader();
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace("#", "");
    if (!id) return;
    const tryScroll = (attempt = 0) => {
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (attempt < 10) window.setTimeout(() => tryScroll(attempt + 1), 100);
    };
    tryScroll();
  }, [location.hash]);

  useLayoutEffect(() => {
    if (!config || !schema) {
      setEnd(null);
      return;
    }
    setEnd(
      <div className="relative w-full min-w-0 sm:max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          className="h-8 pl-8 pr-7 text-xs"
          placeholder={t.common.search}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button
            type="button"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setSearchQuery("")}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>,
    );
    return () => setEnd(null);
  }, [config, schema, searchQuery, setEnd, t.common.search]);

  function prettyCategoryName(cat: string): string {
    const key = cat as keyof typeof t.config.categories;
    if (t.config.categories[key]) return t.config.categories[key];
    return cat.charAt(0).toUpperCase() + cat.slice(1);
  }

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {});
    api
      .getSchema()
      .then((resp) => {
        setSchema(resp.fields as Record<string, Record<string, unknown>>);
        setCategoryOrder(resp.category_order ?? []);
      })
      .catch(() => {});
    api.getDefaults().then(setDefaults).catch(() => {});
  }, []);

  // Load YAML when switching to YAML mode
  useEffect(() => {
    if (yamlMode) {
      setYamlLoading(true);
      api
        .getConfigRaw()
        .then((resp) => setYamlText(resp.yaml))
        .catch(() => showToast(t.config.failedToLoadRaw, "error"))
        .finally(() => setYamlLoading(false));
    }
  }, [yamlMode]);

  /* ---- Categories ---- */
  const categories = useMemo(() => {
    if (!schema) return [];
    const allCats = [...new Set(Object.values(schema).map((s) => String(s.category ?? "general")))];
    const ordered = categoryOrder.filter((c) => allCats.includes(c));
    const extra = allCats.filter((c) => !categoryOrder.includes(c)).sort();
    return [...ordered, ...extra];
  }, [schema, categoryOrder]);

  const visibleCategories = useMemo(
    () =>
      showAdvanced
        ? categories
        : categories.filter((category) => !ADVANCED_CATEGORIES.has(category)),
    [categories, showAdvanced],
  );

  useEffect(() => {
    if (!visibleCategories.length) return;
    if (!activeCategory || !visibleCategories.includes(activeCategory)) {
      setActiveCategory(visibleCategories[0]);
    }
  }, [activeCategory, visibleCategories]);

  /* ---- Category field counts ---- */
  const categoryCounts = useMemo(() => {
    if (!schema) return {};
    const counts: Record<string, number> = {};
    for (const s of Object.values(schema)) {
      const cat = String(s.category ?? "general");
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [schema]);

  /* ---- Search ---- */
  const isSearching = searchQuery.trim().length > 0;
  const lowerSearch = searchQuery.toLowerCase();

  const searchMatchedFields = useMemo(() => {
    if (!isSearching || !schema) return [];
    return Object.entries(schema).filter(([key, s]) => {
      const label = key.split(".").pop() ?? key;
      const humanLabel = label.replace(/_/g, " ");
      return (
        key.toLowerCase().includes(lowerSearch) ||
        humanLabel.toLowerCase().includes(lowerSearch) ||
        String(s.category ?? "").toLowerCase().includes(lowerSearch) ||
        String(s.description ?? "").toLowerCase().includes(lowerSearch)
      );
    });
  }, [isSearching, lowerSearch, schema]);

  /* ---- Active tab fields ---- */
  const activeFields = useMemo(() => {
    if (!schema || isSearching) return [];
    return Object.entries(schema).filter(
      ([, s]) => String(s.category ?? "general") === activeCategory
    );
  }, [schema, activeCategory, isSearching]);

  const laneSummaries = useMemo(
    () =>
      SETTINGS_LANES.map((lane) => {
        const count = lane.categories.reduce(
          (total, category) => total + (categoryCounts[category] || 0),
          0,
        );
        const ready = lane.categories.filter((category) => categories.includes(category));
        return { ...lane, count, ready };
      }),
    [categories, categoryCounts],
  );

  /* ---- Handlers ---- */
  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.saveConfig(config);
      showToast(t.config.configSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleYamlSave = async () => {
    setYamlSaving(true);
    try {
      await api.saveConfigRaw(yamlText);
      showToast(t.config.yamlConfigSaved, "success");
      api.getConfig().then(setConfig).catch(() => {});
    } catch (e) {
      showToast(`${t.config.failedToSaveYaml}: ${e}`, "error");
    } finally {
      setYamlSaving(false);
    }
  };

  const handleReset = () => {
    if (defaults) setConfig(structuredClone(defaults));
  };

  const handleExport = () => {
    if (!config) return;
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "elevate-config.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result ?? "");
        const fileName = file.name.toLowerCase();
        if (fileName.endsWith(".yaml") || fileName.endsWith(".yml")) {
          setYamlText(text);
          setYamlMode(true);
          showToast("YAML imported — review and save", "success");
        } else {
          const imported = JSON.parse(text);
          setConfig(imported);
          setYamlMode(false);
          showToast(`${t.config.configImported}. Click Save to write it.`, "success");
        }
      } catch {
        showToast(t.config.invalidJson, "error");
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    };
    reader.readAsText(file);
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setCopiedCommand(command);
      showToast("Command copied", "success");
      window.setTimeout(() => setCopiedCommand(null), 1600);
    } catch {
      showToast("Could not copy command", "error");
    }
  };

  /* ---- Loading ---- */
  if (!config || !schema) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  /* ---- Render field list (shared between search & normal) ---- */
  const renderFields = (fields: [string, Record<string, unknown>][], showCategory = false) => {
    let lastSection = "";
    let lastCat = "";
    return fields.map(([key, s]) => {
      const parts = key.split(".");
      const section = parts.length > 1 ? parts[0] : "";
      const cat = String(s.category ?? "general");
      const showCatBadge = showCategory && cat !== lastCat;
      const showSection = !showCategory && section && section !== lastSection && section !== activeCategory;
      lastSection = section;
      lastCat = cat;

      return (
        <div key={key}>
          {showCatBadge && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <CategoryIcon category={cat} className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-normal text-muted-foreground">
                {prettyCategoryName(cat)}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          {showSection && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <span className="text-xs font-semibold tracking-normal text-muted-foreground">
                {section.replace(/_/g, " ")}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          <div className="py-1">
            <AutoField
              schemaKey={key}
              schema={s}
              value={getNestedValue(config, key)}
              onChange={(v) => setConfig(setNestedValue(config, key, v))}
            />
          </div>
        </div>
      );
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      <section className="rounded-[1.45rem] border border-border bg-card/70 p-4 shadow-[0_20px_70px_color-mix(in_srgb,var(--background-base)_48%,transparent)]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
              <Settings2 className="h-3.5 w-3.5 text-primary" />
              ElevateOS settings
            </div>
            <h2 className="mt-1 text-xl font-semibold text-foreground">
              Configure the agent, real estate workspace, tools, and memory.
            </h2>
            <div className="mt-2 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
              <code className="truncate rounded-md bg-muted/50 px-2 py-1">
                {t.config.configPath}
              </code>
              <Badge variant="outline">Provider {modelProvider(config)}</Badge>
              <Badge variant={showAdvanced ? "warning" : "outline"}>
                {showAdvanced ? "Advanced visible" : "Core view"}
              </Badge>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              variant={showAdvanced ? "default" : "outline"}
              size="sm"
              onClick={() => setShowAdvanced((value) => !value)}
              className="gap-1.5"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Advanced options
            </Button>
            <Button variant="ghost" size="sm" onClick={handleExport} title={t.config.exportConfig} aria-label={t.config.exportConfig}>
              <Download className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              title={t.config.importConfig}
              aria-label={t.config.importConfig}
              className="gap-1.5"
            >
              <Upload className="h-3.5 w-3.5" />
              Import
            </Button>
            <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={handleImport} />
            <Button variant="ghost" size="sm" onClick={handleReset} title={t.config.resetDefaults} aria-label={t.config.resetDefaults}>
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>

            <div className="mx-1 h-5 w-px bg-border" />

            <Button
              variant={yamlMode ? "default" : "outline"}
              size="sm"
              onClick={() => setYamlMode(!yamlMode)}
              className="gap-1.5"
            >
              {yamlMode ? (
                <>
                  <FormInput className="h-3.5 w-3.5" />
                  {t.common.form}
                </>
              ) : (
                <>
                  <Code className="h-3.5 w-3.5" />
                  YAML
                </>
              )}
            </Button>

            {yamlMode ? (
              <Button size="sm" onClick={handleYamlSave} disabled={yamlSaving} className="gap-1.5">
                <Save className="h-3.5 w-3.5" />
                {yamlSaving ? t.common.saving : t.common.save}
              </Button>
            ) : (
              <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5">
                <Save className="h-3.5 w-3.5" />
                {saving ? t.common.saving : t.common.save}
              </Button>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="grid gap-2 md:grid-cols-3">
            {SETUP_STEPS.map((step) => (
              <div
                key={step.label}
                className="rounded-2xl border border-border/70 bg-background/35 p-3"
              >
                <div className="text-sm font-semibold text-foreground">{step.label}</div>
                <p className="mt-1 min-h-[2.5rem] text-xs leading-5 text-muted-foreground">
                  {step.description}
                </p>
                <button
                  type="button"
                  onClick={() => void copyCommand(step.command)}
                  className="mt-3 flex w-full items-center justify-between gap-2 rounded-xl bg-foreground/[0.055] px-2.5 py-2 text-left text-[0.72rem] text-muted-foreground transition-colors hover:bg-foreground/[0.09] hover:text-foreground"
                >
                  <code className="truncate bg-transparent p-0">{step.command}</code>
                  <Copy className="h-3.5 w-3.5 shrink-0" />
                </button>
                {copiedCommand === step.command && (
                  <div className="mt-1 text-[0.68rem] text-success">Copied</div>
                )}
              </div>
            ))}
          </div>

          <div className="rounded-2xl border border-border/70 bg-background/35 p-3">
            <div className="text-sm font-semibold text-foreground">Import / onboarding</div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Bring in an exported Elevate config, edit raw YAML, or jump to keys and OAuth. Imported files are staged until you click Save.
            </p>
            <div className="mt-3 grid gap-2">
              <Button size="sm" onClick={() => fileInputRef.current?.click()} className="justify-start">
                <Upload className="h-3.5 w-3.5" />
                Import JSON/YAML
              </Button>
              <Button variant="outline" size="sm" onClick={() => setYamlMode(true)} className="justify-start">
                <Code className="h-3.5 w-3.5" />
                Edit raw YAML
              </Button>
              <Link
                to="/env"
                className="inline-flex h-8 items-center justify-start gap-2 rounded-full border border-border/80 bg-card/60 px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
              >
                <KeyRound className="h-3.5 w-3.5" />
                Keys and OAuth
              </Link>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-2 lg:grid-cols-4">
          {laneSummaries.map((lane) => {
            const Icon = lane.icon;
            const target = lane.ready.find((category) => visibleCategories.includes(category)) ?? lane.ready[0];
            return (
              <button
                key={lane.id}
                type="button"
                onClick={() => {
                  if (target) {
                    if (ADVANCED_CATEGORIES.has(target)) setShowAdvanced(true);
                    setSearchQuery("");
                    setActiveCategory(target);
                  }
                }}
                className="rounded-2xl border border-border/70 bg-background/35 p-3 text-left transition-colors hover:bg-foreground/5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Icon className="h-4 w-4 shrink-0 text-primary" />
                    <div className="truncate text-sm font-semibold text-foreground">{lane.label}</div>
                  </div>
                  <Badge variant="outline">{lane.count}</Badge>
                </div>
                <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {lane.description}
                </p>
              </button>
            );
          })}
        </div>
      </section>

      <section>
        <ComposioPanel />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(24rem,0.95fr)]">
        <SourceConnectorSettingsPanel />
        <CrmIntegrationSettingsPanel />
      </section>

      {/* ═══════════════ YAML Mode ═══════════════ */}
      {yamlMode ? (
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t.config.rawYaml}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {yamlLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : (
              <textarea
                className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none border-t border-border"
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                spellCheck={false}
              />
            )}
          </CardContent>
        </Card>
      ) : (
        /* ═══════════════ Form Mode ═══════════════ */
        <div className="flex flex-col sm:flex-row gap-4">
          {/* ---- Filter panel ---- */}
          <aside aria-label={t.config.filters} className="sm:w-56 sm:shrink-0">
            <div className="sm:sticky sm:top-4">
              <div className="flex flex-col rounded-2xl border border-border bg-muted/20">
                {/* Panel heading */}
                <div className="hidden sm:flex items-center gap-2 px-3 py-2 border-b border-border">
                  <Filter className="h-3 w-3 text-muted-foreground" />
                  <span className="text-[0.68rem] font-medium tracking-normal text-muted-foreground">
                    {t.config.filters}
                  </span>
                </div>

                {/* Sections heading (hidden on mobile since it becomes a horizontal scroll) */}
                <div className="hidden px-3 pt-2 pb-1 text-[0.68rem] font-medium tracking-normal text-muted-foreground/70 sm:block">
                  {t.config.sections}
                </div>

                {/* Category nav — horizontal scroll on mobile, pill list on sm+ */}
                <div className="flex sm:flex-col gap-1 sm:gap-px p-2 sm:pt-1 overflow-x-auto sm:overflow-x-visible scrollbar-none sm:max-h-[calc(100vh-260px)] sm:overflow-y-auto">
                  {visibleCategories.map((cat) => {
                    const isActive = !isSearching && activeCategory === cat;

                    return (
                      <button
                        key={cat}
                        type="button"
                        onClick={() => {
                          setSearchQuery("");
                          setActiveCategory(cat);
                        }}
                        className={`
                          group flex items-center gap-2 px-2 py-1
                          rounded-xl text-left text-[11px] cursor-pointer whitespace-nowrap
                          transition-colors
                          ${
                            isActive
                              ? "bg-foreground/10 text-foreground"
                              : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
                          }
                        `}
                      >
                        <CategoryIcon category={cat} className="h-3.5 w-3.5 shrink-0" />
                        <span className="flex-1 truncate">{prettyCategoryName(cat)}</span>
                        <span
                          className={`text-[10px] tabular-nums ${
                            isActive
                              ? "text-foreground/60"
                              : "text-muted-foreground/50"
                          }`}
                        >
                          {categoryCounts[cat] || 0}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </aside>

          {/* ---- Content ---- */}
          <div className="flex-1 min-w-0">
            {isSearching ? (
              /* Search results */
              <Card>
                <CardHeader className="py-3 px-4">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Search className="h-4 w-4" />
                      {t.config.searchResults}
                    </CardTitle>
                    <Badge variant="secondary" className="text-[10px]">
                      {searchMatchedFields.length} {t.config.fields.replace("{s}", searchMatchedFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-2 px-4 pb-4">
                  {searchMatchedFields.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                    </p>
                  ) : (
                    renderFields(searchMatchedFields, true)
                  )}
                </CardContent>
              </Card>
            ) : (
              /* Active category */
              <Card>
                <CardHeader className="py-3 px-4">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <CategoryIcon category={activeCategory} className="h-4 w-4" />
                      {prettyCategoryName(activeCategory)}
                    </CardTitle>
                    <Badge variant="secondary" className="text-[10px]">
                      {activeFields.length} {t.config.fields.replace("{s}", activeFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-2 px-4 pb-4">
                  {renderFields(activeFields)}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
