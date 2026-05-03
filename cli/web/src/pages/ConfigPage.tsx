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
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  type CrmIntegrationForm,
  type IntegrationSettingsResponse,
  type IntegrationTestResponse,
  type SourceConnectorsResponse,
  type SourceConnectorStatus,
} from "@/lib/api";
import { getNestedValue, setNestedValue } from "@/lib/nested";
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
  return connector.sourceExists
    ? "Refreshes the local agent setup task and prompt for building the real connector. It does not fabricate demo lead data."
    : "Creates a local setup task for the agent/operator to build the webhook, poller, import command, or bridge.";
}

function connectorActionLabel(connector: SourceConnectorStatus, busy: boolean): string {
  if (busy) {
    return connector.initializeBehavior === "local_messages_import" ? "Importing" : "Creating task";
  }
  if (connector.initializeBehavior === "local_messages_import") {
    return connector.sourceExists ? "Re-import messages" : "Import messages";
  }
  return connector.sourceExists ? "Refresh setup task" : "Create setup task";
}

function SourceConnectorSettingsPanel() {
  const [data, setData] = useState<SourceConnectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.getSourceConnectors());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const initialize = async (sourceId: string) => {
    setBusyId(sourceId);
    try {
      setData(await api.scaffoldSourceConnector(sourceId));
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
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              Source connectors
            </CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Setup lives here. Apple Messages can build a real local message index; other sources create an agent setup task until a webhook, poller, import command, or bridge exists.
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
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline">{connector.ownerAgent}</Badge>
                {connector.connectionType && <Badge variant="outline">{connector.connectionType}</Badge>}
                <Button
                  variant={connector.sourceExists ? "outline" : "default"}
                  size="sm"
                  className="ml-auto h-7 px-2.5"
                  onClick={() => void initialize(connector.id)}
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getIntegrations();
      setData(next);
      setForm({ ...next.crm, apiKey: "" });
    } finally {
      setLoading(false);
    }
  }, []);

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

  const save = async () => {
    if (!form) return;
    setSaving(true);
    setTestResult(null);
    try {
      const next = await api.saveIntegrations(form);
      setData(next);
      setForm({ ...next.crm, apiKey: "" });
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          CRM/API connector
        </CardTitle>
        <p className="text-xs leading-5 text-muted-foreground">
          Provider-neutral CRM settings. Lofty, Follow Up Boss, kvCORE, and other presets can fill this shape later.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading || !form ? (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-6 text-sm text-muted-foreground">
            Loading CRM settings...
          </div>
        ) : (
          <>
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
            <div className="rounded-2xl border border-border/65 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
              <div>Config: <code className="bg-transparent p-0">{data?.configPath}</code></div>
              <div>Secrets: <code className="bg-transparent p-0">{data?.secretsPath}</code></div>
            </div>
            {testResult && (
              <div className={`rounded-2xl border px-3 py-2 text-xs ${testResult.success ? "border-success/25 bg-success/10 text-success" : "border-warning/25 bg-warning/10 text-warning"}`}>
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
