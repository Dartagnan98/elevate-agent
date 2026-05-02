import { useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import {
  Code,
  Download,
  FormInput,
  RotateCcw,
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
} from "lucide-react";
import { api } from "@/lib/api";
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
  const [showAdvanced, setShowAdvanced] = useState(false);
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
        const imported = JSON.parse(reader.result as string);
        setConfig(imported);
        showToast(t.config.configImported, "success");
      } catch {
        showToast(t.config.invalidJson, "error");
      }
    };
    reader.readAsText(file);
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
            <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} title={t.config.importConfig} aria-label={t.config.importConfig}>
              <Upload className="h-3.5 w-3.5" />
            </Button>
            <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleImport} />
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
