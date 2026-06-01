import { useCallback, useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import {
  ChevronLeft,
  Code,
  Download,
  FormInput,
  Menu,
  RotateCcw,
  RefreshCw,
  Save,
  Search,
  Upload,
  X,
  Settings2,
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
  Puzzle,
  Play,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
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

const SETUP_STEPS = [
  {
    label: "1. Connect the model",
    description: "Give Elevation its own OpenAI Codex session so the Hub can start chats without fighting the Codex app.",
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

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

function connectorVariant(state: SourceConnectorStatus["state"]): "success" | "warning" | "outline" {
  if (state === "connected" || state === "import_only") return "success";
  if (state === "blocked" || state === "error" || state === "needs_operator") return "warning";
  return "outline";
}

function connectorSetupCopy(connector: SourceConnectorStatus): string {
  // Server-side blueprint description is the source of truth. Fall back to a
  // generic line only if the backend didn't ship one (older API).
  if (connector.description && connector.description.trim()) {
    return connector.description;
  }
  return connector.sourceExists
    ? "Connector files exist. Run sync to refresh."
    : "Initialize this source to create the connector files.";
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

  const refresh = useCallback(async (fresh = false) => {
    setLoading(true);
    try {
      const s = await api.getComposioStatus();
      setStatus(s);
      if (s.valid) {
        const [conns, tks] = await Promise.all([
          api.getComposioConnections(fresh),
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
      if (status?.valid) void refresh(true);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh, status?.valid]);

  useEffect(() => {
    if (!customAuthState) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !customAuthState.submitting) {
        setCustomAuthState(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [customAuthState]);

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
      await refresh(true);
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
        await refresh(true);
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
      await refresh(true);
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
    <section id="composio" className="scroll-mt-24 space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">Composio</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            One auth hub for messaging (Gmail, Twilio, WhatsApp) and social (Instagram, X, LinkedIn). Add your API key, then connect each app.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {statusBadge}
          <Button variant="outline" size="sm" onClick={() => void refresh(true)} disabled={loading}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </header>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
          <KeyRound className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          API key
        </label>
        {status?.hasKey ? (
          <div className="flex flex-wrap items-center gap-2">
            <code className="flex-1 truncate rounded-md border border-border bg-transparent px-2 py-1.5 text-xs">
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
          <div className="flex items-start gap-1.5 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{keyError}</span>
          </div>
        )}
        {status && status.hasKey && !status.valid && !keyError && (
          <div className="flex items-start gap-1.5 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{status.error ?? "Composio rejected the key. Rotate it at composio.dev and re-save."}</span>
          </div>
        )}
        <p className="text-xs leading-5 text-muted-foreground">
          Get a key at{" "}
          <a
            href="https://app.composio.dev/developers"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            composio.dev/developers
            <ExternalLink className="ml-1 inline h-3 w-3" aria-hidden="true" />
          </a>
          . Stored in your local .env, never sent anywhere except Composio.
        </p>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-medium text-foreground">
          Connected accounts <span className="text-muted-foreground">({connections.length})</span>
        </h3>
        {!status?.valid ? (
          <div className="flex items-start gap-2 text-sm text-muted-foreground">
            <CircleSlash className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Add a working API key to see your connected accounts.
          </div>
        ) : connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">No accounts connected yet. Pick one below to start.</p>
        ) : (
          <ul className="divide-y divide-border/50 border-y border-border/50">
            {connections.map((conn, idx) => (
              <li
                key={String(conn.id ?? idx)}
                className="flex items-center gap-3 py-2.5"
              >
                {(conn.toolkit?.meta?.logo ?? conn.toolkit?.logo) ? (
                  <img
                    src={conn.toolkit?.meta?.logo ?? conn.toolkit?.logo}
                    alt=""
                    className="h-7 w-7 rounded-md object-contain"
                  />
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center">
                    <Plug className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-foreground">
                      {conn.toolkit?.name ?? conn.toolkit?.slug ?? "Unknown app"}
                    </span>
                    {conn.status === "ACTIVE" && (
                      <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-label="Active" />
                    )}
                  </div>
                  {conn.user_id && (
                    <div className="truncate text-xs text-muted-foreground">{conn.user_id}</div>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Disconnect ${conn.toolkit?.name ?? "account"}`}
                  onClick={() => void disconnect(String(conn.id ?? ""))}
                  disabled={connectingSlug === String(conn.id ?? "")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {status?.valid && (
        <div>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-sm font-medium text-foreground">
              Available apps <span className="text-muted-foreground">({filteredToolkits.length}
              {filteredToolkits.length !== toolkits.length ? ` of ${toolkits.length}` : ""})</span>
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input
                  type="search"
                  placeholder="Search apps..."
                  aria-label="Search Composio apps"
                  value={toolkitQuery}
                  onChange={(e) => setToolkitQuery(e.target.value)}
                  className="h-8 w-44 pl-7 text-xs"
                />
              </div>
              {allCategories.length > 0 && (
                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  aria-label="Filter by category"
                  className="h-8 rounded-md border border-border bg-transparent px-2 text-xs text-foreground"
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
            <p className="text-sm text-muted-foreground">
              {toolkits.length === 0 ? "No toolkits returned by Composio." : "No apps match that filter."}
            </p>
          ) : (
            <div className="grid gap-1.5 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-8">
              {visibleToolkits.map((tk) => {
                const slug = String(tk.slug ?? "");
                const isConnected = connectedSlugs.has(slug);
                const logo = toolkitLogo(tk);
                const desc = toolkitDescription(tk);
                return (
                  <button
                    key={slug}
                    type="button"
                    onClick={() => void connect(slug)}
                    disabled={connectingSlug === slug}
                    aria-label={isConnected ? `Add another ${tk.name ?? slug} connection` : `Connect ${tk.name ?? slug}`}
                    title={desc ? `${tk.name ?? slug} — ${desc}` : tk.name ?? slug}
                    className="group flex min-h-[44px] flex-col items-center gap-1.5 rounded-md border border-border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
                  >
                    {logo ? (
                      <img
                        src={logo}
                        alt=""
                        className="h-9 w-9 rounded-md object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-9 w-9 items-center justify-center rounded-md">
                        <Plug className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      </div>
                    )}
                    <span className="w-full truncate text-xs font-medium text-foreground">
                      {tk.name ?? slug}
                    </span>
                    <span className="text-[0.68rem] text-muted-foreground group-hover:text-foreground">
                      {connectingSlug === slug ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                      ) : isConnected ? (
                        "Add another"
                      ) : (
                        "Connect"
                      )}
                    </span>
                  </button>
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
      {customAuthState && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 p-4"
          onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="composio-auth-title"
            className="relative w-full max-w-lg overflow-hidden rounded-lg border border-border bg-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div id="composio-auth-title" className="text-base font-semibold">{customAuthState.name}</div>
                  <div className="text-xs text-muted-foreground">
                    This connection requires custom OAuth credentials.
                  </div>
                </div>
                <button
                  type="button"
                  aria-label="Close dialog"
                  onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
                  className="-mr-2 flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                >
                  <X className="h-4 w-4" />
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
                        <span className="text-xs font-normal text-muted-foreground">(optional)</span>
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
                      className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-ring"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </div>
                );
              })}
              {customAuthState.error && (
                <div className="rounded-md border border-border bg-card px-3 py-2 text-xs text-destructive">
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
    </section>
  );
}

function SourceConnectorSettingsPanel() {
  const navigate = useNavigate();
  const [data, setData] = useState<SourceConnectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [runningPromptId, setRunningPromptId] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<Record<string, { kind: string; message: string }>>({});
  const [composioAccounts, setComposioAccounts] = useState<ComposioConnectedAccount[]>([]);
  const [composioReady, setComposioReady] = useState<boolean>(false);
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

  const promptForConnector = async (connector: SourceConnectorStatus): Promise<string> => {
    const existing = (connector.prompt || "").trim();
    if (existing) return existing;
    const resp = await api.getSourceConnectorPrompt(connector.id);
    return (resp.prompt || "").trim();
  };

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

  const runPrompt = async (connector: SourceConnectorStatus) => {
    const opensChat = connector.runMode === "agent_session" || !connector.wired;
    setRunningPromptId(connector.id);
    setRunResults((prev) => {
      const next = { ...prev };
      delete next[connector.id];
      return next;
    });
    try {
      // Server-inline connectors can safely complete inside the API request.
      // Browser-driven MLS scrapers need a visible PTY-backed chat session so
      // the operator can watch MFA, browser steps, and terminal output.
      if (!opensChat) {
        try {
          const resp = await api.runSourceConnectorPrompt(connector.id);
          const outcome = resp.run?.outcome;
          setRunResults((prev) => ({
            ...prev,
            [connector.id]: {
              kind: outcome?.kind ?? "ok",
              message: outcome?.message ?? "Sync finished.",
            },
          }));
        } catch (err) {
          setRunResults((prev) => ({
            ...prev,
            [connector.id]: {
              kind: "error",
              message: err instanceof Error ? err.message : "Sync failed.",
            },
          }));
        } finally {
          void load();
        }
        return;
      }
      const prompt = await promptForConnector(connector);
      if (!prompt) return;
      const ts = String(Date.now());
      const seedTitle = connector.runMode === "agent_session" ? "Run source connector" : "Source connector";
      const seedText = `${seedTitle}: ${connector.label} (${connector.id})\n\n${prompt}`;
      try {
        window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText);
      } catch {
        // sessionStorage disabled — fall back to navigating without seed; the
        // user can still paste from clipboard via the secondary button.
      }
      navigate(`/chat?new=${ts}&seed=${ts}`);
    } finally {
      setRunningPromptId(null);
    }
  };

  const copyPromptText = async (connector: SourceConnectorStatus) => {
    try {
      await navigator.clipboard.writeText(await promptForConnector(connector));
    } catch {
      // clipboard not available — silently skip; primary path is run.
    }
  };

  const connectors = data?.connectors ?? [];
  const ready = connectors.filter((connector) => connector.state === "connected" || connector.state === "import_only").length;

  return (
    <section id="connectors" className="scroll-mt-24 space-y-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Network className="h-4 w-4 text-primary" aria-hidden="true" />
            Source connectors
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            Where Elevation pulls its data from. Grouped by purpose: messages & inbox, CRM, MLS / buyer intelligence, social, and back-office. Each connector self-describes what it does.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{ready}/{connectors.length || 12} ready</Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh source connectors"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </header>

      <div className="text-sm leading-6 text-muted-foreground">
        <div className="font-medium text-foreground">Source root</div>
        <code className="mt-1 block break-all bg-transparent p-0 font-mono text-xs">
          {data?.sourceRoot ?? "Loading source root..."}
        </code>
      </div>

      {(() => {
        const categories = data?.categories ?? [];
        const fallback = { id: "other", label: "Other", description: "" };
        const groups = new Map<string, SourceConnectorStatus[]>();
        for (const c of connectors) {
          const key = c.category || fallback.id;
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(c);
        }
        const ordered = [
          ...categories.filter((c) => groups.has(c.id)),
          ...[...groups.keys()]
            .filter((id) => !categories.some((c) => c.id === id))
            .map((id) => ({ ...fallback, id, label: id })),
        ];
        return ordered.map((cat) => {
          const rows = groups.get(cat.id) ?? [];
          if (!rows.length) return null;
          const readyInCat = rows.filter((r) => r.state === "connected" || r.state === "import_only").length;
          return (
            <section key={cat.id} className="space-y-3">
              <div className="flex flex-col gap-1 border-t border-border/50 pt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">{cat.label}</h3>
                  <Badge variant="outline" className="text-[10px]">{readyInCat}/{rows.length}</Badge>
                </div>
                {cat.description && (
                  <p className="max-w-prose text-xs leading-5 text-muted-foreground">{cat.description}</p>
                )}
              </div>
              <ul className="divide-y divide-border/50">
                {rows.map((connector) => (
                  <li key={connector.id} className="py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">{connector.label}</span>
                  <Badge variant={connectorVariant(connector.state)}>{connector.state.replace(/_/g, " ")}</Badge>
                </div>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {connectorSetupCopy(connector)}
                </p>
              </div>
              <Badge variant="outline">{connectorRecordTotal(connector)} records</Badge>
            </div>
            {connector.nextOperatorStep && (
              <div className="mt-3 text-sm leading-6 text-muted-foreground">
                {connector.nextOperatorStep}
              </div>
            )}
            {connector.initializeBehavior === "composio_social_setup" && (
              <div className="mt-3 text-sm">
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
                    <div className="mb-1.5 text-xs text-muted-foreground">
                      Social accounts ({composioAccounts.length})
                    </div>
                    <ul className="flex flex-wrap gap-1.5">
                      {composioAccounts.map((acc, idx) => {
                        const logo = acc.toolkit?.meta?.logo ?? acc.toolkit?.logo;
                        const name = acc.toolkit?.name ?? acc.toolkit?.slug ?? "Unknown";
                        return (
                          <li
                            key={String(acc.id ?? idx)}
                            className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-2 py-0.5"
                            title={acc.user_id ? `${name} • ${acc.user_id}` : name}
                          >
                            {logo ? (
                              <img src={logo} alt="" className="h-3.5 w-3.5 rounded-sm object-contain" />
                            ) : (
                              <Plug className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                            )}
                            <span className="text-xs text-foreground">{name}</span>
                            {acc.status === "ACTIVE" && (
                              <CheckCircle2 className="h-3 w-3 text-success" aria-hidden="true" />
                            )}
                          </li>
                        );
                      })}
                    </ul>
                    {hasFacebookAccount && (
                      <div className="mt-3 border-t border-border/40 pt-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs font-medium text-foreground">
                            Facebook pages on /leads
                          </div>
                          <button
                            type="button"
                            className="text-xs text-primary hover:underline"
                            onClick={() => {
                              setFbPickerOpen((v) => !v);
                              if (!fbPickerOpen) void loadFbPages();
                            }}
                            aria-expanded={fbPickerOpen}
                          >
                            {fbPickerOpen ? "Done" : "Edit"}
                          </button>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
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
                                <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-xs text-foreground hover:bg-foreground/[0.04]">
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
                  </>
                )}
              </div>
            )}
            {runResults[connector.id] && (
              <div
                className={
                  "mt-3 rounded-md border px-3 py-2 text-xs leading-5 " +
                  (runResults[connector.id].kind === "error"
                    ? "border-destructive/40 bg-destructive/5 text-destructive"
                    : runResults[connector.id].kind === "needs_operator"
                      ? "border-warning/40 bg-warning/5 text-foreground"
                      : "border-success/40 bg-success/5 text-foreground")
                }
              >
                {runResults[connector.id].message}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline">{connector.ownerAgent}</Badge>
              {connector.connectionType && <Badge variant="outline">{connector.connectionType}</Badge>}
              {(() => {
                const opensChat = connector.runMode === "agent_session" || !connector.wired;
                const busy = runningPromptId === connector.id;
                const idleLabel = opensChat
                  ? (connector.runMode === "agent_session" ? "Open run session" : "Open setup chat")
                  : "Run sync";
                const busyLabel = opensChat
                  ? (connector.runMode === "agent_session" ? "Opening session…" : "Opening chat…")
                  : "Running…";
                return (
              <Button
                variant="default"
                size="sm"
                className="ml-auto"
                onClick={() => void runPrompt(connector)}
                disabled={busy}
                aria-label={opensChat ? `Open chat session for ${connector.label}` : `Run sync for ${connector.label}`}
              >
                <Play className="h-3.5 w-3.5" aria-hidden="true" />
                {busy ? busyLabel : idleLabel}
              </Button>
                );
              })()}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void copyPromptText(connector)}
                aria-label={`Copy setup prompt text for ${connector.label}`}
                title="Copy prompt text"
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </div>
          </li>
                ))}
              </ul>
            </section>
          );
        });
      })()}
      {loading && !connectors.length && (
        <div className="py-6 text-sm text-muted-foreground">Loading connector blueprints...</div>
      )}
    </section>
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
    <section className="space-y-5">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" />
          Connect your CRM
        </h2>
        <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
          Pick your CRM, paste your API key, and we handle the rest. Lofty, Follow Up Boss, Sierra, BoldTrail and Brivity are pre-wired.
        </p>
      </header>
      <div className="space-y-4">
        {loading || !form ? (
          <div className="py-6 text-sm text-muted-foreground">Loading CRM settings...</div>
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
                    aria-pressed={isSelected}
                    title={`${preset.label} — ${preset.description}`}
                    className={`group flex min-h-[44px] flex-col items-center gap-2 rounded-md border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${isSelected ? "border-primary" : "border-border/60"}`}
                  >
                    <div className="relative">
                      <img
                        src={preset.logo}
                        alt=""
                        width={40}
                        height={40}
                        loading="lazy"
                        decoding="async"
                        className="h-10 w-10 rounded-md object-contain p-1"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                          const fallback = e.currentTarget.nextElementSibling as HTMLElement | null;
                          if (fallback) fallback.style.display = "flex";
                        }}
                      />
                      <div className="hidden h-10 w-10 items-center justify-center rounded-md">
                        <Plug className="h-4 w-4 text-foreground/70" />
                      </div>
                      {isConnected && (
                        <CheckCircle2 className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full bg-card text-success" />
                      )}
                    </div>
                    <span className="w-full truncate text-xs font-medium text-foreground">{preset.label}</span>
                    <span
                      className={`mt-0.5 text-[0.7rem] ${isConnected ? "text-success" : "text-muted-foreground group-hover:text-foreground"}`}
                    >
                      {isConnected ? "Connected" : "Connect"}
                    </span>
                  </button>
                );
              })}
              <button
                type="button"
                onClick={chooseCustom}
                aria-pressed={mode === "custom"}
                title="Other — wire up any REST CRM"
                className={`group flex min-h-[44px] flex-col items-center gap-2 rounded-md border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${mode === "custom" ? "border-primary" : "border-border/60"}`}
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-md">
                  <Settings2 className="h-4 w-4 text-foreground/70" />
                </div>
                <span className="w-full truncate text-xs font-medium text-foreground">Other / Custom</span>
                <span className="mt-0.5 text-[0.7rem] text-muted-foreground group-hover:text-foreground">Wire up</span>
              </button>
            </div>

            {mode === "preset" && selectedPreset && (
              <div className="space-y-4 border-t border-border/50 pt-4">
                <div className="flex items-center gap-3">
                  <img
                    src={selectedPreset.logo}
                    alt=""
                    width={32}
                    height={32}
                    className="h-8 w-8 rounded-md object-contain p-1"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                  <span className="text-base font-semibold text-foreground">{selectedPreset.label}</span>
                </div>
                {selectedPreset.notice && (
                  <div className="rounded-md border border-border bg-card px-3 py-2 text-sm leading-6 text-warning">
                    <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5 align-text-bottom" aria-hidden="true" />
                    {selectedPreset.notice}
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground" htmlFor="crm-preset-api-key">
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
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                    Where do I find this? — {selectedPreset.helpText}
                  </a>
                </div>
                {testResult && (
                  <div className={`rounded-md border border-border bg-card px-3 py-2 text-sm ${testResult.success ? "text-success" : "text-warning"}`} role="status">
                    {testResult.message ?? testResult.error ?? "Test finished"}
                  </div>
                )}
                <div className="flex flex-wrap justify-between gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowAdvanced((v) => !v)}
                    aria-expanded={showAdvanced}
                  >
                    {showAdvanced ? "Hide advanced" : "Show advanced"}
                  </Button>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => void test()} disabled={testing || !canSave}>
                      {testing ? "Testing" : "Test connection"}
                    </Button>
                    <Button size="sm" onClick={() => void save()} disabled={saving || !canSave}>
                      {saving ? "Saving" : "Connect"}
                    </Button>
                  </div>
                </div>
                {showAdvanced && (
                  <div className="space-y-3 border-t border-border/40 pt-3">
                    <div className="text-xs text-muted-foreground">Advanced — pre-wired by preset</div>
                    <div className="grid gap-2 md:grid-cols-3">
                      <Input value={form.baseUrl} placeholder="base URL" onChange={(e) => patch({ baseUrl: e.target.value })} aria-label="Base URL" />
                      <Input value={form.authHeader} placeholder="header" onChange={(e) => patch({ authHeader: e.target.value })} aria-label="Auth header" />
                      <Input value={form.authPrefix} placeholder="prefix" onChange={(e) => patch({ authPrefix: e.target.value })} aria-label="Auth prefix" />
                      <Input value={form.endpoints.leads} placeholder="leads endpoint" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} aria-label="Leads endpoint" />
                      <Input value={form.endpoints.lead} placeholder="lead endpoint" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} aria-label="Lead endpoint" />
                      <Input value={form.endpoints.notes} placeholder="notes endpoint" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} aria-label="Notes endpoint" />
                    </div>
                  </div>
                )}
              </div>
            )}
            {mode === "custom" && (
              <div className="space-y-4 border-t border-border/50 pt-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Settings2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    <span className="text-base font-semibold text-foreground">Custom CRM</span>
                  </div>
                  <Button variant="ghost" size="sm" onClick={backToPicker}>
                    Change CRM
                  </Button>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={form.provider} placeholder="provider" onChange={(e) => patch({ provider: e.target.value })} aria-label="Provider" />
                  <Input value={form.label} placeholder="label" onChange={(e) => patch({ label: e.target.value })} aria-label="Label" />
                  <Input value={form.baseUrl} placeholder="https://api.example.com" onChange={(e) => patch({ baseUrl: e.target.value })} aria-label="Base URL" />
                  <Input value={form.apiKeyEnv} placeholder="CRM_API_KEY" onChange={(e) => patch({ apiKeyEnv: e.target.value })} aria-label="API key env var name" />
                  <Input value={form.apiKey ?? ""} type="password" placeholder={form.hasApiKey ? `API key ${form.apiKeyPreview ?? "saved"}` : "API key"} onChange={(e) => patch({ apiKey: e.target.value })} aria-label="API key" />
                  <Input value={form.authType} placeholder="header or query" onChange={(e) => patch({ authType: e.target.value })} aria-label="Auth type" />
                  <Input value={form.authHeader} placeholder="Authorization" onChange={(e) => patch({ authHeader: e.target.value })} aria-label="Auth header" />
                  <Input value={form.authPrefix} placeholder="Bearer " onChange={(e) => patch({ authPrefix: e.target.value })} aria-label="Auth prefix" />
                  <Input value={form.authQueryParam} placeholder="api_key" onChange={(e) => patch({ authQueryParam: e.target.value })} aria-label="Auth query param" />
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={form.endpoints.leads} placeholder="/v1/leads" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} aria-label="Leads endpoint" />
                  <Input value={form.endpoints.lead} placeholder="/v1/leads/:id" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} aria-label="Lead endpoint" />
                  <Input value={form.endpoints.notes} placeholder="/v1/leads/:id/notes" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} aria-label="Notes endpoint" />
                  <Input value={form.dbColumns.leadId} placeholder="crm_lead_id" onChange={(e) => patchNested("dbColumns", "leadId", e.target.value)} aria-label="Lead ID column" />
                  <Input value={form.dbColumns.stage} placeholder="crm_stage" onChange={(e) => patchNested("dbColumns", "stage", e.target.value)} aria-label="Stage column" />
                  <Input value={form.dbColumns.tags} placeholder="crm_tags" onChange={(e) => patchNested("dbColumns", "tags", e.target.value)} aria-label="Tags column" />
                </div>
                <div className="text-xs leading-6 text-muted-foreground">
                  <div>Config: <code className="bg-transparent p-0 font-mono">{data?.configPath}</code></div>
                  <div>Secrets: <code className="bg-transparent p-0 font-mono">{data?.secretsPath}</code></div>
                </div>
                {testResult && (
                  <div className={`rounded-md border border-border bg-card px-3 py-2 text-sm ${testResult.success ? "text-success" : "text-warning"}`} role="status">
                    {testResult.message ?? testResult.error ?? "Test finished"}
                  </div>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" size="sm" onClick={() => void test()} disabled={testing}>
                    {testing ? "Testing" : "Test"}
                  </Button>
                  <Button size="sm" onClick={() => void save()} disabled={saving}>
                    {saving ? "Saving" : "Save CRM"}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

interface ChannelsPanelProps {
  config: Record<string, unknown> | null;
  setConfig: (next: Record<string, unknown>) => void;
}

function ChannelsPanel({ config, setConfig }: ChannelsPanelProps) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [envVars, setEnvVars] = useState<Record<string, { is_set: boolean; redacted_value: string | null }>>({});
  const [connectors, setConnectors] = useState<SourceConnectorsResponse | null>(null);
  const [composioAccounts, setComposioAccounts] = useState<ComposioConnectedAccount[]>([]);
  const [botTokenInput, setBotTokenInput] = useState("");
  const [savingBotToken, setSavingBotToken] = useState(false);
  const [channelEdits, setChannelEdits] = useState<Record<string, string>>({});
  const [savingChannel, setSavingChannel] = useState<string | null>(null);
  const [savingWhatsapp, setSavingWhatsapp] = useState(false);

  const reload = useCallback(async () => {
    try {
      const env = await api.getEnvVars();
      setEnvVars(env as unknown as Record<string, { is_set: boolean; redacted_value: string | null }>);
    } catch {
      // env endpoint failing is non-fatal; UI degrades to "not configured"
    }
    try {
      setConnectors(await api.getSourceConnectors());
    } catch { /* ignore */ }
    try {
      const status = await api.getComposioStatus();
      if (status.valid) {
        const conns = await api.getComposioConnections();
        const body = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setComposioAccounts(Array.isArray(body) ? body : body.items ?? []);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const agents = useMemo(() => {
    const hub = (config?.["agent_hub"] as Record<string, unknown> | undefined) ?? {};
    const list = (hub["agents"] as Array<Record<string, unknown>> | undefined) ?? [];
    return list.map((agent) => {
      const meta = (agent.metadata as Record<string, unknown> | undefined) ?? {};
      return {
        id: String(agent.id ?? ""),
        name: String(agent.name ?? agent.id ?? ""),
        enabled: Boolean(agent.enabled),
        tokenEnv: String(meta.telegram_bot_token_env ?? ""),
        channelEnv: String(meta.telegram_target_env ?? ""),
      };
    });
  }, [config]);

  const botTokenSet = Boolean(envVars["TELEGRAM_BOT_TOKEN"]?.is_set);
  const botTokenPreview = envVars["TELEGRAM_BOT_TOKEN"]?.redacted_value ?? "";

  const saveBotToken = async () => {
    if (!botTokenInput.trim()) return;
    setSavingBotToken(true);
    try {
      await api.setEnvVar("TELEGRAM_BOT_TOKEN", botTokenInput.trim());
      setBotTokenInput("");
      await reload();
      showToast("Telegram bot token saved", "success");
    } catch (err) {
      showToast(`Failed to save token: ${String(err)}`, "error");
    } finally {
      setSavingBotToken(false);
    }
  };

  const saveChannelFor = async (key: string) => {
    const value = (channelEdits[key] ?? "").trim();
    setSavingChannel(key);
    try {
      if (!value) {
        await api.deleteEnvVar(key);
      } else {
        await api.setEnvVar(key, value);
      }
      setChannelEdits((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      await reload();
      showToast("Channel saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSavingChannel(null);
    }
  };

  const startSetupChat = (label: string, prompt: string) => {
    const ts = String(Date.now());
    const seedText = `${label}\n\n${prompt}`;
    try { window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText); } catch { /* ignore */ }
    navigate(`/chat?new=${ts}&seed=${ts}`);
  };

  const sourceConnectorPrompt = async (sourceId: string, fallback: string): Promise<string> => {
    try {
      const resp = await api.getSourceConnectorPrompt(sourceId);
      const prompt = (resp.prompt || "").trim();
      return prompt || fallback;
    } catch {
      return fallback;
    }
  };

  const appleConnector = connectors?.connectors?.find((c) => c.id === "apple-messages");
  const appleConnected = appleConnector?.state === "connected" || appleConnector?.state === "import_only";

  const whatsappAccount = composioAccounts.find(
    (a) => (a.toolkit?.slug ?? "").toLowerCase().includes("whatsapp"),
  );
  const imessageAccount = composioAccounts.find(
    (a) => (a.toolkit?.slug ?? "").toLowerCase().includes("imessage"),
  );

  const whatsappCfg = (config?.["whatsapp"] as Record<string, unknown> | undefined) ?? {};
  const whatsappPrefix = String(whatsappCfg["reply_prefix"] ?? "");
  const [whatsappPrefixInput, setWhatsappPrefixInput] = useState<string | null>(null);
  const effectivePrefix = whatsappPrefixInput ?? whatsappPrefix;

  const saveWhatsappPrefix = async () => {
    if (!config) return;
    setSavingWhatsapp(true);
    try {
      const next = { ...config } as Record<string, unknown>;
      const wa = { ...(next.whatsapp as Record<string, unknown> | undefined ?? {}) };
      if (effectivePrefix === "") {
        delete wa.reply_prefix;
      } else {
        wa.reply_prefix = effectivePrefix;
      }
      next.whatsapp = wa;
      await api.saveConfig(next);
      setConfig(next);
      setWhatsappPrefixInput(null);
      showToast("WhatsApp settings saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSavingWhatsapp(false);
    }
  };

  return (
    <section className="space-y-8">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <MessageCircle className="h-4 w-4 text-primary" aria-hidden="true" />
          Channels
        </h2>
        <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
          Where messages flow in and out. Set tokens, route agents to channels, and configure send/receive for Telegram, iMessage, and WhatsApp.
        </p>
      </header>

      {/* Telegram */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Telegram</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Inbound DMs, channel chats, and per-agent routing.</p>
          </div>
          <Badge variant={botTokenSet ? "success" : "outline"}>
            {botTokenSet ? "Bot token set" : "No bot token"}
          </Badge>
        </div>

        <div className="mt-3">
          <label className="block text-xs font-medium text-foreground/80">Bot token</label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            From <span className="font-mono">@BotFather</span>. Stored as <span className="font-mono">TELEGRAM_BOT_TOKEN</span> in your env.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Input
              type="password"
              autoComplete="off"
              placeholder={botTokenSet ? botTokenPreview || "•••••••• (currently set)" : "123456789:ABCdef..."}
              value={botTokenInput}
              onChange={(e) => setBotTokenInput(e.target.value)}
              className="h-8 text-sm"
            />
            <Button size="sm" onClick={() => void saveBotToken()} disabled={savingBotToken || !botTokenInput.trim()}>
              {savingBotToken ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>

        <div className="mt-4">
          <div className="text-xs font-medium text-foreground/80">Per-agent channel routing</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            One chat/topic per agent. Paste a Telegram chat ID (negative for groups) or run <span className="font-mono">/elevate pair</span> in the chat.
          </p>
          <div className="mt-2 divide-y divide-border/40 rounded-md border border-border/40">
            {agents.length === 0 && (
              <div className="px-3 py-2 text-xs text-muted-foreground/80">No agents configured.</div>
            )}
            {agents.map((agent) => {
              const currentPreview = envVars[agent.channelEnv]?.redacted_value ?? "";
              const currentSet = Boolean(envVars[agent.channelEnv]?.is_set);
              const editing = channelEdits[agent.channelEnv] !== undefined;
              const inputValue = editing ? channelEdits[agent.channelEnv] : "";
              return (
                <div key={agent.id} className="flex items-center gap-2 px-3 py-2">
                  <div className="min-w-[8rem] flex-shrink-0">
                    <div className="text-sm font-medium text-foreground">{agent.name}</div>
                    {!agent.enabled && <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">disabled</span>}
                  </div>
                  <Input
                    className="h-7 flex-1 text-xs font-mono"
                    placeholder={currentSet ? currentPreview || "(set)" : "-1001234567890"}
                    value={inputValue}
                    onChange={(e) => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: e.target.value }))}
                  />
                  {editing ? (
                    <Button
                      size="sm"
                      variant="default"
                      onClick={() => void saveChannelFor(agent.channelEnv)}
                      disabled={savingChannel === agent.channelEnv}
                    >
                      {savingChannel === agent.channelEnv ? "…" : "Save"}
                    </Button>
                  ) : currentSet ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: "" }))}
                    >
                      Change
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: "" }))}
                    >
                      Set
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              startSetupChat(
                "Channel setup: Telegram",
                "Help me wire up Telegram for Elevation. I want to test that my bot can receive messages, route to the right agent (executive-assistant by default), and send replies back. Walk me through pairing and verify with a test message.",
              )
            }
          >
            <Play className="h-3.5 w-3.5" />
            Setup chat
          </Button>
          <Link
            to="/env"
            className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <KeyRound className="h-3.5 w-3.5" />
            All Telegram env vars
          </Link>
        </div>
      </div>

      {/* iMessage */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">iMessage</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Mac Messages: read history, contacts, conversation context. Sending uses Apple Messages or a Composio bridge.</p>
          </div>
          <Badge variant={appleConnected ? "success" : "outline"}>
            {appleConnected ? "Connected" : (appleConnector?.state ?? "Not set up")}
          </Badge>
        </div>

        <div className="mt-3 space-y-2 text-xs">
          <div className="flex items-center justify-between gap-3 rounded-md border border-border/40 px-3 py-2">
            <div>
              <div className="font-medium text-foreground">Receive (read Messages DB)</div>
              <div className="text-muted-foreground/80">Local sync from <span className="font-mono">~/Library/Messages/chat.db</span></div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void (async () => {
                const prompt = await sourceConnectorPrompt(
                  appleConnector?.id || "apple-messages",
                  "Help me wire iMessage so Elevation can read my Mac Messages history into the local message index. Walk me through Full Disk Access for the Elevation binary and run a first sync.",
                );
                startSetupChat(
                  "Channel setup: iMessage receive",
                  prompt,
                );
              })()}
            >
              <Play className="h-3.5 w-3.5" />
              Setup chat
            </Button>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-md border border-border/40 px-3 py-2">
            <div>
              <div className="font-medium text-foreground">Send</div>
              <div className="text-muted-foreground/80">
                {imessageAccount ? "Composio iMessage account connected" : "Native AppleScript send (built-in) or connect Composio for cloud sending"}
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                startSetupChat(
                  "Channel setup: iMessage send",
                  "Set up iMessage sending. My default is AppleScript on this Mac (so Messages.app needs to be running and signed in). Walk me through verifying it works with a test send to one of my contacts. If I should use Composio instead, tell me when.",
                )
              }
            >
              <Play className="h-3.5 w-3.5" />
              Setup chat
            </Button>
          </div>
        </div>
      </div>

      {/* WhatsApp */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">WhatsApp</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Inbound and outbound WhatsApp via Composio (WhatsApp Business / Cloud API).</p>
          </div>
          <Badge variant={whatsappAccount ? "success" : "outline"}>
            {whatsappAccount ? "Connected" : "Not connected"}
          </Badge>
        </div>

        <div className="mt-3">
          <label className="block text-xs font-medium text-foreground/80">Reply prefix</label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Prepended to every outgoing WhatsApp message. Default is &quot;▲ *Elevation*&quot;. Empty string disables it.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Input
              className="h-8 text-sm font-mono"
              placeholder="▲ *Elevation*"
              value={effectivePrefix}
              onChange={(e) => setWhatsappPrefixInput(e.target.value)}
            />
            <Button
              size="sm"
              onClick={() => void saveWhatsappPrefix()}
              disabled={savingWhatsapp || whatsappPrefixInput === null}
            >
              {savingWhatsapp ? "…" : "Save"}
            </Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              startSetupChat(
                "Channel setup: WhatsApp",
                "Help me wire WhatsApp send/receive for Elevation via Composio. I want one connected number that can receive messages into Elevation and send replies. Walk me through what I need (Business account, phone number, webhook) and verify with a test message.",
              )
            }
          >
            <Play className="h-3.5 w-3.5" />
            Setup chat
          </Button>
          <Link
            to="/settings#composio"
            className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Plug className="h-3.5 w-3.5" />
            Composio integrations
          </Link>
        </div>
      </div>
    </section>
  );
}

interface MemoryPanelProps {
  config: Record<string, unknown> | null;
  setConfig: (next: Record<string, unknown>) => void;
}

function MemoryPanel({ config, setConfig }: MemoryPanelProps) {
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (config) setDraft(structuredClone(config));
  }, [config]);

  if (!draft) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const get = (path: string): unknown => getNestedValue(draft, path);
  const set = (path: string, value: unknown) => setDraft(setNestedValue(draft, path, value) as Record<string, unknown>);

  const dirty = JSON.stringify(draft) !== JSON.stringify(config);

  const save = async () => {
    setSaving(true);
    try {
      await api.saveConfig(draft);
      setConfig(draft);
      showToast("Memory settings saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const memoryEnabled = Boolean(get("memory.memory_enabled"));
  const userProfileEnabled = Boolean(get("memory.user_profile_enabled"));
  const provider = String(get("memory.provider") ?? "");
  const memoryCharLimit = Number(get("memory.memory_char_limit") ?? 2200);
  const userCharLimit = Number(get("memory.user_char_limit") ?? 1375);

  const autoExtract = Boolean(get("plugins.elevate-memory-store.auto_extract"));
  const turnJournal = Boolean(get("plugins.elevate-memory-store.turn_journal_enabled"));
  const dailyOrganize = Boolean(get("plugins.elevate-memory-store.daily_organize_enabled"));
  const graphRecall = Boolean(get("plugins.elevate-memory-store.graph_recall_enabled"));
  const recentRecall = Boolean(get("plugins.elevate-memory-store.recent_recall_enabled"));
  const embeddingEnabled = Boolean(get("plugins.elevate-memory-store.embedding_enabled"));

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            Memory
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            What Elevation remembers between sessions. Curated memory is injected into the system prompt; the memory store is the durable backing index.
          </p>
        </div>
        <Button size="sm" onClick={() => void save()} disabled={saving || !dirty}>
          <Save className="h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save"}
        </Button>
      </header>

      <div className="rounded-lg border border-border/60 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Curated memory (injected into prompt)</h3>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Enable curated memory</span>
          <Switch checked={memoryEnabled} onCheckedChange={(v) => set("memory.memory_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Include user profile</span>
          <Switch checked={userProfileEnabled} onCheckedChange={(v) => set("memory.user_profile_enabled", v)} />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted-foreground">Memory char limit</label>
            <Input
              type="number"
              className="mt-1 h-8 text-sm"
              value={memoryCharLimit}
              onChange={(e) => set("memory.memory_char_limit", Number(e.target.value) || 0)}
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground">User profile char limit</label>
            <Input
              type="number"
              className="mt-1 h-8 text-sm"
              value={userCharLimit}
              onChange={(e) => set("memory.user_char_limit", Number(e.target.value) || 0)}
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-muted-foreground">External provider</label>
          <select
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-sm"
            value={provider}
            onChange={(e) => set("memory.provider", e.target.value)}
          >
            <option value="">Built-in only</option>
            <option value="openviking">OpenViking</option>
            <option value="mem0">Mem0</option>
            <option value="hindsight">Hindsight</option>
            <option value="holographic">Holographic</option>
            <option value="retaindb">RetainDB</option>
            <option value="byterover">Byterover</option>
          </select>
        </div>
      </div>

      <div className="rounded-lg border border-border/60 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Memory store (durable index)</h3>
        <p className="text-xs text-muted-foreground">
          Local SQLite-backed memory store at <span className="font-mono">$ELEVATE_HOME/memory_store.db</span>.
        </p>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Auto-extract facts from each turn</span>
          <Switch checked={autoExtract} onCheckedChange={(v) => set("plugins.elevate-memory-store.auto_extract", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Turn-by-turn journal</span>
          <Switch checked={turnJournal} onCheckedChange={(v) => set("plugins.elevate-memory-store.turn_journal_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Daily organize (compress + cluster)</span>
          <Switch checked={dailyOrganize} onCheckedChange={(v) => set("plugins.elevate-memory-store.daily_organize_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Recent recall (last few turns)</span>
          <Switch checked={recentRecall} onCheckedChange={(v) => set("plugins.elevate-memory-store.recent_recall_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Graph recall (concept neighbors)</span>
          <Switch checked={graphRecall} onCheckedChange={(v) => set("plugins.elevate-memory-store.graph_recall_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Embedding-based recall</span>
          <Switch checked={embeddingEnabled} onCheckedChange={(v) => set("plugins.elevate-memory-store.embedding_enabled", v)} />
        </label>
      </div>
    </section>
  );
}

interface PluginsPanelProps {
  config: Record<string, unknown>;
  setConfig: (next: Record<string, unknown>) => void;
}

function PluginsPanel({ config, setConfig }: PluginsPanelProps) {
  const [discovered, setDiscovered] = useState<Array<{
    name: string;
    label: string;
    description: string;
    version: string;
    source: string;
  }> | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const plugins = await api.getPlugins();
      setDiscovered(
        plugins.map((p) => ({
          name: p.name,
          label: p.label || p.name,
          description: p.description || "",
          version: p.version || "0.0.0",
          source: p.source || "user",
        })),
      );
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load plugins");
      setDiscovered([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRescan = useCallback(async () => {
    setRescanning(true);
    try {
      await api.rescanPlugins();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rescan failed");
    } finally {
      setRescanning(false);
    }
  }, [load]);

  const enabled = useMemo(() => {
    const raw = getNestedValue(config, "plugins.enabled");
    return Array.isArray(raw) ? (raw as string[]) : [];
  }, [config]);
  const disabled = useMemo(() => {
    const raw = getNestedValue(config, "plugins.disabled");
    return Array.isArray(raw) ? (raw as string[]) : [];
  }, [config]);

  const togglePlugin = (name: string, on: boolean) => {
    const nextEnabled = on
      ? [...new Set([...enabled, name])]
      : enabled.filter((n) => n !== name);
    const nextDisabled = on
      ? disabled.filter((n) => n !== name)
      : disabled;
    let next = setNestedValue(config, "plugins.enabled", nextEnabled);
    next = setNestedValue(next, "plugins.disabled", nextDisabled);
    setConfig(next);
  };

  const discoveredNames = new Set((discovered ?? []).map((p) => p.name));
  const orphanEnabled = enabled.filter((n) => !discoveredNames.has(n));

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Puzzle className="h-4 w-4 text-primary" aria-hidden="true" />
            Installed plugins
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            Plugins live in <code className="bg-transparent p-0 font-mono text-xs">~/.elevate/plugins/</code> and bundled directories. Toggle one on to load it next time the agent starts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {discovered ? `${discovered.length} discovered` : "Loading..."}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleRescan()}
            disabled={rescanning}
            aria-label="Rescan plugins"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${rescanning ? "animate-spin" : ""}`} aria-hidden="true" />
            Rescan
          </Button>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-border bg-card px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {discovered === null ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading plugins…</p>
      ) : discovered.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No plugins discovered. Drop a plugin directory under <code className="bg-transparent p-0 font-mono text-xs">~/.elevate/plugins/</code> and click Rescan.
        </p>
      ) : (
        <ul className="divide-y divide-border/50 border-y border-border/50">
          {discovered.map((plugin) => {
            const isOn = enabled.includes(plugin.name);
            return (
              <li key={plugin.name} className="py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">{plugin.label}</span>
                      <Badge variant="outline" className="text-[0.7rem]">
                        {plugin.source}
                      </Badge>
                      <span className="font-mono text-[0.7rem] text-foreground/60">v{plugin.version}</span>
                    </div>
                    {plugin.description && (
                      <p className="mt-1 text-sm leading-6 text-foreground/80">
                        {plugin.description}
                      </p>
                    )}
                    <code className="mt-1 block bg-transparent p-0 font-mono text-[0.7rem] text-foreground/55">
                      {plugin.name}
                    </code>
                  </div>
                  <div className="shrink-0 pt-0.5">
                    <Switch
                      checked={isOn}
                      onCheckedChange={(v) => togglePlugin(plugin.name, v)}
                      aria-label={`${isOn ? "Disable" : "Enable"} ${plugin.label}`}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {orphanEnabled.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
            Enabled but not found
          </div>
          <p className="text-xs leading-6 text-foreground/70">
            These plugin names are in your config but no matching directory was discovered. Remove them or install the plugin.
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {orphanEnabled.map((name) => (
              <li
                key={name}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-2 py-1 text-xs"
              >
                <code className="bg-transparent p-0 font-mono">{name}</code>
                <button
                  type="button"
                  onClick={() => togglePlugin(name, false)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${name} from enabled list`}
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
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
  const [activePane, setActivePane] = useState<"config" | "channels" | "memory" | "composio" | "connectors" | "crm" | "setup">("channels");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { toast, showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();
  const { setEnd } = usePageHeader();
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace("#", "");
    if (!id) return;
    // Map hash to its containing pane so deep-links from outside (e.g.
    // /config#connectors from the leads onboarding card) actually reveal
    // the pane that hosts the section before scroll-into-view tries to
    // resolve the anchor.
    const PANE_BY_HASH: Record<string, typeof activePane> = {
      channels: "channels",
      memory: "memory",
      connectors: "connectors",
      composio: "composio",
      crm: "crm",
      setup: "setup",
    };
    const targetPane = PANE_BY_HASH[id];
    if (targetPane && targetPane !== activePane) {
      setActivePane(targetPane);
    }
    const tryScroll = (attempt = 0) => {
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (attempt < 10) window.setTimeout(() => tryScroll(attempt + 1), 100);
    };
    tryScroll();
  }, [location.hash, activePane]);

  useLayoutEffect(() => {
    setEnd(null);
    return () => setEnd(null);
  }, [setEnd]);

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
    return Object.entries(schema).filter(([key, s]) => {
      if (String(s.category ?? "general") !== activeCategory) return false;
      // The PluginsPanel replaces the raw enabled/disabled list inputs.
      if (activeCategory === "plugins" && (key === "plugins.enabled" || key === "plugins.disabled")) {
        return false;
      }
      return true;
    });
  }, [schema, activeCategory, isSearching]);

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
      <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading config…</p>
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
            <div className="mt-10 mb-2 first:mt-2">
              <div className="flex items-center gap-2">
                <CategoryIcon category={cat} className="h-4 w-4 text-muted-foreground" />
                <span className="text-base font-semibold text-foreground">
                  {prettyCategoryName(cat)}
                </span>
              </div>
            </div>
          )}
          {showSection && (
            <div className="mt-10 mb-2 first:mt-2">
              <span className="text-sm font-semibold text-foreground">
                {section.charAt(0).toUpperCase() + section.slice(1).replace(/_/g, " ")}
              </span>
            </div>
          )}
          <div className="py-6 first:pt-2">
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

  const sidebarItems = [
    ...visibleCategories.map((cat) => ({
      id: cat,
      pane: "config" as const,
      label: prettyCategoryName(cat),
      icon: <CategoryIcon category={cat} className="h-4 w-4" />,
    })),
  ];

  const integrationItems = [
    { id: "channels", pane: "channels" as const, label: "Channels", icon: <MessageCircle className="h-4 w-4" /> },
    { id: "memory", pane: "memory" as const, label: "Memory", icon: <Brain className="h-4 w-4" /> },
    { id: "connectors", pane: "connectors" as const, label: "Sources", icon: <Network className="h-4 w-4" /> },
    { id: "crm", pane: "crm" as const, label: "CRM", icon: <Users className="h-4 w-4" /> },
    { id: "composio", pane: "composio" as const, label: "Composio", icon: <Plug className="h-4 w-4" /> },
    { id: "setup", pane: "setup" as const, label: "Setup commands", icon: <Wrench className="h-4 w-4" /> },
  ];

  const activeNavLabel =
    activePane === "config"
      ? prettyCategoryName(activeCategory) || "Settings"
      : integrationItems.find((i) => i.pane === activePane)?.label ?? "Settings";

  return (
    <div className="flex h-dvh flex-col justify-center md:flex-row md:pt-[3.25rem]">
      <Toast toast={toast} />
      <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={handleImport} />

      {/* Desktop drag-region spacer — matches chat title bar height so macOS
          traffic lights have breathing room and the page header doesn't crash
          into the very top of the window. */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 hidden h-[3.25rem] md:block"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      />

      {/* Mobile top bar */}
      <div className="flex items-center gap-2 border-b border-border/50 px-4 py-2 md:hidden">
        <Link
          to="/"
          aria-label="Back to app"
          className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
        </Link>
        <button
          type="button"
          aria-label="Open settings navigation"
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen(true)}
          className="flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-foreground transition-colors hover:bg-foreground/[0.06]"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
          <span>{activeNavLabel}</span>
        </button>
      </div>

      {/* Mobile drawer scrim */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      <div className="flex h-full min-h-0 w-full flex-1 max-w-[1280px] mx-auto">
      {/* ---- Sidebar ---- */}
      <aside
        className={`
          ${mobileNavOpen ? "fixed inset-y-0 left-0 z-50 w-72 bg-background shadow-xl" : "hidden"}
          md:static md:z-auto md:block md:w-64 md:shadow-none md:bg-transparent
          shrink-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden
        `}
        aria-label="Settings navigation"
      >
        <div className="py-4">
          {/* Back + title (desktop) / Close (mobile drawer) */}
          <div className="flex items-center gap-2 px-4 pb-3">
            <Link
              to="/"
              aria-label="Back to app"
              className="hidden md:flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground hover:bg-foreground/[0.06]"
            >
              <ChevronLeft className="h-4 w-4" />
            </Link>
            <span className="text-sm font-semibold text-foreground">Settings</span>
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => setMobileNavOpen(false)}
              className="ml-auto flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground md:hidden"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Search */}
          <div className="px-3 pb-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              <Input
                className="h-9 pl-8 pr-9 text-sm"
                placeholder={t.common.search}
                aria-label="Search settings"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  aria-label="Clear search"
                  className="absolute right-1 top-1/2 -translate-y-1/2 flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  onClick={() => setSearchQuery("")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* Primary navigation */}
          <nav className="flex flex-col gap-0.5 px-2" aria-label="Settings">
            {integrationItems.map((item) => {
              const isActive = activePane === item.pane;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => {
                    setSearchQuery("");
                    setActivePane(item.pane);
                    setMobileNavOpen(false);
                  }}
                  className={`
                    flex min-h-[36px] items-center gap-2.5 rounded-md px-3 py-1.5 text-left text-sm
                    transition-colors
                    ${isActive
                      ? "bg-foreground/[0.08] text-foreground font-medium"
                      : "text-foreground/85 hover:text-foreground hover:bg-foreground/[0.04]"
                    }
                  `}
                >
                  <span className={isActive ? "text-foreground" : "text-foreground/70"} aria-hidden="true">{item.icon}</span>
                  <span className="flex-1 truncate">{item.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Advanced (schema-driven) categories — collapsed by default */}
          <div className="mx-3 my-3 border-t border-border/50" />
          <div className="px-3">
            <button
              type="button"
              aria-expanded={showAdvanced}
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex w-full min-h-[36px] items-center justify-between rounded-md px-3 py-1.5 text-sm text-muted-foreground/80 transition-colors hover:text-foreground hover:bg-foreground/[0.04]"
            >
              <span className="flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Advanced settings
              </span>
              <span className="text-xs">{showAdvanced ? "Hide" : "Show"}</span>
            </button>
          </div>

          {showAdvanced && (
            <nav className="mt-1 flex flex-col gap-0.5 px-2" aria-label="Advanced settings categories">
              {sidebarItems.map((item) => {
                const isActive = !isSearching && activePane === "config" && activeCategory === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => {
                      setSearchQuery("");
                      setActivePane("config");
                      setActiveCategory(item.id);
                      setMobileNavOpen(false);
                    }}
                    className={`
                      flex min-h-[32px] items-center gap-2.5 rounded-md px-3 py-1 text-left text-[13px]
                      transition-colors
                      ${isActive
                        ? "bg-foreground/[0.08] text-foreground font-medium"
                        : "text-foreground/75 hover:text-foreground hover:bg-foreground/[0.04]"
                      }
                    `}
                  >
                    <span className={isActive ? "text-foreground" : "text-foreground/60"} aria-hidden="true">{item.icon}</span>
                    <span className="flex-1 truncate">{item.label}</span>
                  </button>
                );
              })}
            </nav>
          )}
        </div>
      </aside>

      {/* ---- Content ---- */}
      <div className="flex-1 overflow-y-auto min-w-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="mx-auto max-w-4xl px-4 py-6 md:px-12 md:py-8">

          {/* ---- Channels pane ---- */}
          {activePane === "channels" && config && <ChannelsPanel config={config} setConfig={setConfig} />}

          {/* ---- Memory pane ---- */}
          {activePane === "memory" && config && <MemoryPanel config={config} setConfig={setConfig} />}

          {/* ---- Composio pane ---- */}
          {activePane === "composio" && <ComposioPanel />}

          {/* ---- Source connectors pane ---- */}
          {activePane === "connectors" && <SourceConnectorSettingsPanel />}

          {/* ---- CRM pane ---- */}
          {activePane === "crm" && <CrmIntegrationSettingsPanel />}

          {/* ---- Setup commands pane ---- */}
          {activePane === "setup" && (
            <div>
              <h2 className="text-lg font-semibold text-foreground">Setup commands</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Run these in your terminal to configure the agent runtime.
              </p>
              <div className="mt-6 space-y-4">
                {SETUP_STEPS.map((step) => (
                  <div key={step.label} className="border-b border-border/40 pb-4 last:border-0">
                    <div className="text-sm font-medium text-foreground">{step.label}</div>
                    <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
                    <button
                      type="button"
                      onClick={() => void copyCommand(step.command)}
                      className="mt-2 flex items-center gap-2 rounded-lg bg-foreground/[0.05] px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-foreground/[0.09] hover:text-foreground"
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

              <div className="mt-8">
                <h3 className="text-sm font-semibold text-foreground">Import / Export</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Bring in an exported config, edit raw YAML, or manage API keys.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()}>
                    <Upload className="h-3.5 w-3.5" />
                    Import JSON/YAML
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleExport}>
                    <Download className="h-3.5 w-3.5" />
                    Export
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => { setYamlMode(true); setActivePane("config"); }}>
                    <Code className="h-3.5 w-3.5" />
                    Edit raw YAML
                  </Button>
                  <Link
                    to="/env"
                    className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    Keys and OAuth
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* ---- Config pane ---- */}
          {activePane === "config" && (
            <>
              {/* YAML mode */}
              {yamlMode ? (
                <div>
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-foreground">{t.config.rawYaml}</h2>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setYamlMode(false)}>
                        <FormInput className="h-3.5 w-3.5" />
                        {t.common.form}
                      </Button>
                      <Button size="sm" onClick={handleYamlSave} disabled={yamlSaving}>
                        <Save className="h-3.5 w-3.5" />
                        {yamlSaving ? t.common.saving : t.common.save}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-4 rounded-md border border-border overflow-hidden">
                    {yamlLoading ? (
                      <p className="px-3 py-3 text-xs text-muted-foreground/80">Loading YAML…</p>
                    ) : (
                      <textarea
                        className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none"
                        value={yamlText}
                        onChange={(e) => setYamlText(e.target.value)}
                        spellCheck={false}
                      />
                    )}
                  </div>
                </div>
              ) : isSearching ? (
                /* Search results */
                <div>
                  <h2 className="text-lg font-semibold text-foreground">{t.config.searchResults}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {searchMatchedFields.length} {t.config.fields.replace("{s}", searchMatchedFields.length !== 1 ? "s" : "")} matching &ldquo;{searchQuery}&rdquo;
                  </p>
                  <div className="mt-4">
                    {searchMatchedFields.length === 0 ? (
                      <p className="px-1 py-1 text-xs text-muted-foreground/80">
                        {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                      </p>
                    ) : (
                      renderFields(searchMatchedFields, true)
                    )}
                  </div>
                </div>
              ) : (
                /* Active category */
                <div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-foreground">{prettyCategoryName(activeCategory)}</h2>
                      <p className="mt-0.5 text-xs text-foreground/70">
                        {activeFields.length} settings
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="ghost" size="sm" onClick={handleReset} title={t.config.resetDefaults}>
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="sm" onClick={handleSave} disabled={saving}>
                        <Save className="h-3.5 w-3.5" />
                        {saving ? t.common.saving : t.common.save}
                      </Button>
                    </div>
                  </div>
                  {activeCategory === "plugins" && (
                    <div className="mt-6">
                      <PluginsPanel config={config} setConfig={setConfig} />
                    </div>
                  )}
                  <div className="mt-4">
                    {renderFields(activeFields)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
