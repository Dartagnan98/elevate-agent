import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import {
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  Code2,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  Megaphone,
  MoreVertical,
  Package,
  Paintbrush,
  Route,
  Search,
  Sparkles,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SkillInfo, SkillTreeNode } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Markdown } from "@/components/Markdown";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/* ------------------------------------------------------------------ */
/*  Workflow flow cards (kept compact above the tree)                  */
/* ------------------------------------------------------------------ */

const REAL_ESTATE_WORKFLOWS = [
  {
    key: "marketing",
    icon: Megaphone,
    label: "Marketing",
    names: [
      "cma",
      "cma-generator",
      "cma-router",
      "market-stats-watcher",
      "marketing",
      "marketing-landing",
      "seller-update",
      "seller-updates",
      "humanizer",
      "photo-cleanup",
    ],
  },
  {
    key: "sales",
    icon: Users,
    label: "Sales",
    names: [
      "lead-scorer",
      "listing-outreach",
      "outreach",
      "outreach-lanes",
      "real-estate-first-touch-outreach-run",
      "xposure-pcs-pipeline",
    ],
  },
  {
    key: "admin",
    icon: BriefcaseBusiness,
    label: "Admin",
    names: [
      "admin-agent",
      "listing-build",
      "seller-package",
      "offer-review",
      "deal-matcher",
      "subject-removal",
      "signing-package",
      "closing-admin",
      "skyslope-sync",
      "mlc",
      "webforms",
      "property-lookup",
      "quickbooks",
      "relisting",
      "skyleigh-vault",
    ],
  },
  {
    key: "social-media",
    icon: Paintbrush,
    label: "Social Media",
    names: ["social-content-engine"],
  },
] as const;

const REAL_ESTATE_SKILL_NAMES = new Set([
  "admin-agent",
  "admin-result-writer",
  "closing-admin",
  "cma",
  "cma-generator",
  "cma-router",
  "deal-matcher",
  "digisign",
  "gmail-doc-router",
  "humanizer",
  "lead-scorer",
  "listing-build",
  "listing-outreach",
  "marketing",
  "marketing-landing",
  "market-stats-watcher",
  "mlc",
  "offer-review",
  "outreach",
  "outreach-lanes",
  "photo-cleanup",
  "property-lookup",
  "quickbooks",
  "real-estate-first-touch-outreach-run",
  "relisting",
  "seller-package",
  "seller-update",
  "seller-updates",
  "signing-package",
  "skyslope-listing-creation",
  "skyslope-sync",
  "social-content-engine",
  "subject-removal",
  "webforms",
  "xposure-pcs-pipeline",
]);

const REAL_ESTATE_CATEGORY_GROUPS: Record<string, string> = {
  "real-estate": "real-estate-admin",
  "real-estate-admin": "real-estate-admin",
  "real-estate-cma": "real-estate-marketing",
  "real-estate-leads": "real-estate-sales",
  "real-estate-marketing": "real-estate-marketing",
  "real-estate-sales": "real-estate-sales",
  "real-estate-social": "real-estate-social-media",
  "real-estate-social-media": "real-estate-social-media",
};

const REAL_ESTATE_GROUP_LABELS: Record<string, string> = {
  "real-estate-admin": "Admin",
  "real-estate-marketing": "Marketing",
  "real-estate-sales": "Sales",
  "real-estate-social-media": "Social Media",
};

const REAL_ESTATE_MARKETING_SKILLS = new Set([
  "cma",
  "cma-generator",
  "cma-router",
  "humanizer",
  "market-stats-watcher",
  "marketing",
  "marketing-landing",
  "photo-cleanup",
  "seller-update",
  "seller-updates",
]);

const REAL_ESTATE_SALES_SKILLS = new Set([
  "lead-scorer",
  "listing-outreach",
  "outreach",
  "outreach-lanes",
  "real-estate-first-touch-outreach-run",
  "xposure-pcs-pipeline",
]);

const REAL_ESTATE_SOCIAL_SKILLS = new Set(["social-content-engine"]);

const REAL_ESTATE_KEYWORDS = [
  "cma",
  "deal",
  "digisign",
  "listing",
  "lofty",
  "mlc",
  "offer",
  "outreach",
  "realtor",
  "seller",
  "signing",
  "skyslope",
  "subject-removal",
  "webforms",
  "xposure",
];

interface SkillGroupDefinition {
  key: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

const SKILL_GROUPS: SkillGroupDefinition[] = [
  {
    key: "real-estate-marketing",
    label: "Marketing",
    description: "CMA, listing launch, seller updates, and market-facing assets.",
    icon: Megaphone,
  },
  {
    key: "real-estate-sales",
    label: "Sales",
    description: "Lead scoring, outreach, follow-up lanes, and buyer/seller handoff.",
    icon: Users,
  },
  {
    key: "real-estate-admin",
    label: "Admin",
    description: "Forms, signatures, deals, listings, docs, and MLS operations.",
    icon: BriefcaseBusiness,
  },
  {
    key: "real-estate-social-media",
    label: "Social Media",
    description: "Social content ideation, queueing, scheduling, and approvals.",
    icon: Paintbrush,
  },
  {
    key: "marketing-ads",
    label: "Marketing & ads",
    description: "Campaigns, ad audits, social posts, and growth workflows.",
    icon: Megaphone,
  },
  {
    key: "creative-media",
    label: "Creative & media",
    description: "Design, images, video, presentation, and content production.",
    icon: Paintbrush,
  },
  {
    key: "productivity-docs",
    label: "Productivity & documents",
    description: "Documents, PDFs, email, notes, and everyday work utilities.",
    icon: FileText,
  },
  {
    key: "research-data",
    label: "Research & data",
    description: "Research, data science, ML, and analysis helpers.",
    icon: Search,
  },
  {
    key: "engineering-automation",
    label: "Engineering & automation",
    description: "Coding, GitHub, agents, MCP, DevOps, and automation helpers.",
    icon: Code2,
  },
  {
    key: "other",
    label: "Other skills",
    description: "Installed skills that do not declare a clearer purpose yet.",
    icon: Package,
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fileIcon(name: string) {
  if (name === "SKILL.md") return Sparkles;
  if (name.endsWith(".md")) return FileText;
  return FileText;
}

function normalizeSkillCategory(category: string | null | undefined): string {
  return (category || "uncategorized").trim().toLowerCase();
}

function isRealEstateSkill(skill: SkillInfo): boolean {
  const name = skill.name.toLowerCase();
  const category = normalizeSkillCategory(skill.category);
  return (
    category.startsWith("real-estate") ||
    category === "real-estate" ||
    category === "real-estate-admin" ||
    REAL_ESTATE_SKILL_NAMES.has(name) ||
    REAL_ESTATE_KEYWORDS.some((keyword) => name.includes(keyword))
  );
}

function realEstateSkillGroupKey(skill: SkillInfo): string | null {
  const name = skill.name.toLowerCase();
  const category = normalizeSkillCategory(skill.category);
  const categoryGroup = REAL_ESTATE_CATEGORY_GROUPS[category];
  if (categoryGroup) return categoryGroup;
  if (REAL_ESTATE_SOCIAL_SKILLS.has(name)) return "real-estate-social-media";
  if (REAL_ESTATE_MARKETING_SKILLS.has(name)) return "real-estate-marketing";
  if (REAL_ESTATE_SALES_SKILLS.has(name)) return "real-estate-sales";
  if (isRealEstateSkill(skill)) return "real-estate-admin";
  return null;
}

function displaySkillCategory(skill: SkillInfo): string {
  const realEstateGroup = realEstateSkillGroupKey(skill);
  if (realEstateGroup) return REAL_ESTATE_GROUP_LABELS[realEstateGroup] ?? "Real Estate";
  const category = normalizeSkillCategory(skill.category);
  if (!category || category === "uncategorized") return "Local";
  return category
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function skillGroupKey(skill: SkillInfo): string {
  const realEstateGroup = realEstateSkillGroupKey(skill);
  if (realEstateGroup) return realEstateGroup;

  const category = normalizeSkillCategory(skill.category);
  if (["ads", "direct-response", "social-media"].includes(category)) {
    return "marketing-ads";
  }
  if (["creative", "media", "gaming"].includes(category)) {
    return "creative-media";
  }
  if (["email", "note-taking", "productivity", "smart-home"].includes(category)) {
    return "productivity-docs";
  }
  if (["data", "data-science", "mlops", "red-teaming", "research"].includes(category)) {
    return "research-data";
  }
  if (["apple", "autonomous-ai-agents", "devops", "github", "mcp", "software-development"].includes(category)) {
    return "engineering-automation";
  }
  return "other";
}

function groupSkillsByPurpose(skills: SkillInfo[]) {
  const grouped = new Map(SKILL_GROUPS.map((group) => [group.key, [] as SkillInfo[]]));
  for (const skill of skills) {
    const key = skillGroupKey(skill);
    const bucket = grouped.get(key) ?? grouped.get("other");
    bucket?.push(skill);
  }
  return SKILL_GROUPS.map((definition) => ({
    definition,
    items: (grouped.get(definition.key) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
  })).filter((group) => group.items.length > 0);
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string>("SKILL.md");
  const [trees, setTrees] = useState<Record<string, SkillTreeNode[]>>({});
  const [loadingTree, setLoadingTree] = useState<string | null>(null);
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [fileContent, setFileContent] = useState<string>("");
  const [fileLoading, setFileLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"render" | "raw">("render");
  const [togglingSkills, setTogglingSkills] = useState<Set<string>>(new Set());
  const [showWorkflows, setShowWorkflows] = useState(false);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  /* ---- Initial load ---- */
  useEffect(() => {
    api
      .getSkills()
      .then((s) => {
        setSkills(s);
        if (s.length > 0 && !selectedSkill) {
          const first = [...s].sort((a, b) => a.name.localeCompare(b.name))[0];
          if (first) {
            setSelectedSkill(first.name);
            setExpandedSkills(new Set([first.name]));
          }
        }
      })
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---- Lazy-load the tree for a skill ---- */
  const loadTree = useCallback(
    async (name: string) => {
      if (trees[name]) return;
      setLoadingTree(name);
      try {
        const res = await api.getSkillTree(name);
        setTrees((prev) => ({ ...prev, [name]: res.tree || [] }));
      } catch {
        setTrees((prev) => ({ ...prev, [name]: [] }));
      } finally {
        setLoadingTree((current) => (current === name ? null : current));
      }
    },
    [trees],
  );

  /* ---- Load file content for the currently selected leaf ---- */
  useEffect(() => {
    if (!selectedSkill) {
      setFileContent("");
      return;
    }
    setFileLoading(true);
    api
      .getSkillFile(selectedSkill, selectedPath)
      .then((res) => {
        if (res.binary) {
          setFileContent(`*(binary file — ${res.size ?? 0} bytes)*`);
        } else if (res.error) {
          setFileContent(`*${res.error}*`);
        } else {
          setFileContent(res.content ?? "");
        }
      })
      .catch(() => setFileContent("*Failed to load file*"))
      .finally(() => setFileLoading(false));
  }, [selectedSkill, selectedPath]);

  /* ---- When a skill is expanded for the first time, pull its tree ---- */
  useEffect(() => {
    if (selectedSkill && !trees[selectedSkill]) {
      loadTree(selectedSkill);
    }
  }, [selectedSkill, trees, loadTree]);

  /* ---- Toggle skill enable/disable ---- */
  const handleToggleSkill = async (skill: SkillInfo) => {
    setTogglingSkills((prev) => new Set(prev).add(skill.name));
    try {
      await api.toggleSkill(skill.name, !skill.enabled);
      setSkills((prev) =>
        prev.map((s) =>
          s.name === skill.name ? { ...s, enabled: !s.enabled } : s,
        ),
      );
      showToast(
        `${skill.name} ${skill.enabled ? t.common.disabled : t.common.enabled}`,
        "success",
      );
    } catch {
      showToast(`${t.common.failedToToggle} ${skill.name}`, "error");
    } finally {
      setTogglingSkills((prev) => {
        const next = new Set(prev);
        next.delete(skill.name);
        return next;
      });
    }
  };

  /* ---- Derived data ---- */
  const lowerSearch = search.trim().toLowerCase();
  const isSearching = lowerSearch.length > 0;

  const filteredSkills = useMemo(() => {
    if (!isSearching) return skills;
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(lowerSearch) ||
        s.description.toLowerCase().includes(lowerSearch) ||
        (s.category ?? "").toLowerCase().includes(lowerSearch),
    );
  }, [skills, isSearching, lowerSearch]);

  const skillGroups = useMemo(
    () => groupSkillsByPurpose(filteredSkills),
    [filteredSkills],
  );

  const skillsByName = useMemo(
    () => new Map(skills.map((skill) => [skill.name, skill])),
    [skills],
  );
  const enabledCount = skills.filter((s) => s.enabled).length;
  const activeSkill = selectedSkill ? skillsByName.get(selectedSkill) : null;

  /* ---- Page header ---- */
  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {t.skills.enabledOf
          .replace("{enabled}", String(enabledCount))
          .replace("{total}", String(skills.length))}
      </span>,
    );
    setEnd(
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowWorkflows((v) => !v)}
          className={`hidden sm:inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] transition-colors ${
            showWorkflows
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border bg-card text-muted-foreground hover:text-foreground"
          }`}
        >
          <Route className="h-3 w-3" />
          Flows
        </button>
        <div className="relative w-full min-w-0 sm:max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-8 pl-8 pr-7 text-xs"
            placeholder={t.common.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearch("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    enabledCount,
    loading,
    search,
    setAfterTitle,
    setEnd,
    showWorkflows,
    skills.length,
    t,
  ]);

  /* ---- Helpers ---- */
  const handleSelectSkill = (name: string, path = "SKILL.md") => {
    setSelectedSkill(name);
    setSelectedPath(path);
    setExpandedSkills((prev) => {
      const next = new Set(prev);
      next.add(name);
      return next;
    });
    if (!trees[name]) loadTree(name);
  };

  const toggleSkillExpansion = (name: string) => {
    setExpandedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
        if (!trees[name]) loadTree(name);
      }
      return next;
    });
  };

  const toggleFolder = (skillName: string, path: string) => {
    const key = `${skillName}::${path}`;
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /* ---- Loading ---- */
  if (loading) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Loading skills…
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      {showWorkflows && (
        <section className="rounded-md border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Route className="h-3.5 w-3.5 text-primary" />
              Real estate skill sections
            </div>
            <Badge variant="outline">
              {enabledCount}/{skills.length} enabled
            </Badge>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {REAL_ESTATE_WORKFLOWS.map((workflow) => (
              <WorkflowFlowCard
                key={workflow.key}
                workflow={workflow}
                skillsByName={skillsByName}
                togglingSkills={togglingSkills}
                onToggle={handleToggleSkill}
              />
            ))}
          </div>
        </section>
      )}

      {/* ============ Two-pane shell ============ */}
      <div className="grid min-h-[calc(100vh-12rem)] grid-cols-1 gap-0 rounded-md border border-border bg-card md:grid-cols-[280px_minmax(0,1fr)]">
        {/* ---- Left tree rail ---- */}
        <aside
          aria-label={t.skills.title}
          className="flex flex-col border-b border-border md:border-b-0 md:border-r"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-normal text-muted-foreground">
              <Package className="h-3 w-3" />
              <span>{t.skills.title}</span>
              <span className="text-muted-foreground/60">
                ({skills.length})
              </span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-1 py-2">
            {skillGroups.map(({ definition, items }) => (
              <TreeSection
                key={definition.key}
                definition={definition}
                items={items}
                trees={trees}
                loadingTree={loadingTree}
                expandedSkills={expandedSkills}
                expandedFolders={expandedFolders}
                selectedSkill={selectedSkill}
                selectedPath={selectedPath}
                togglingSkills={togglingSkills}
                onSelectSkill={handleSelectSkill}
                onToggleExpand={toggleSkillExpansion}
                onToggleFolder={toggleFolder}
                onToggleEnable={handleToggleSkill}
                isSearching={isSearching}
                defaultOpen={definition.key.startsWith("real-estate-")}
              />
            ))}

            {filteredSkills.length === 0 && (
              <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                {isSearching ? t.skills.noSkillsMatch : t.skills.noSkills}
              </p>
            )}
          </div>
        </aside>

        {/* ---- Right detail pane ---- */}
        <section className="flex min-w-0 flex-col">
          {activeSkill ? (
            <SkillDetail
              skill={activeSkill}
              filePath={selectedPath}
              fileContent={fileContent}
              fileLoading={fileLoading}
              viewMode={viewMode}
              setViewMode={setViewMode}
              toggling={togglingSkills.has(activeSkill.name)}
              onToggleEnable={() => handleToggleSkill(activeSkill)}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-12">
              <p className="text-xs text-muted-foreground">
                Select a skill from the rail to view its contents.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail: a section (Personal / Built-in)                         */
/* ------------------------------------------------------------------ */

interface TreeSectionProps {
  definition: SkillGroupDefinition;
  items: SkillInfo[];
  trees: Record<string, SkillTreeNode[]>;
  loadingTree: string | null;
  expandedSkills: Set<string>;
  expandedFolders: Set<string>;
  selectedSkill: string | null;
  selectedPath: string;
  togglingSkills: Set<string>;
  onSelectSkill: (name: string, path?: string) => void;
  onToggleExpand: (name: string) => void;
  onToggleFolder: (skillName: string, path: string) => void;
  onToggleEnable: (skill: SkillInfo) => void;
  isSearching: boolean;
  defaultOpen: boolean;
}

function TreeSection(props: TreeSectionProps) {
  const {
    definition,
    items,
    trees,
    loadingTree,
    expandedSkills,
    expandedFolders,
    selectedSkill,
    selectedPath,
    togglingSkills,
    onSelectSkill,
    onToggleExpand,
    onToggleFolder,
    onToggleEnable,
    isSearching,
    defaultOpen,
  } = props;
  const [open, setOpen] = useState(defaultOpen || isSearching);
  const Icon = definition.icon;
  const enabledCount = items.filter((skill) => skill.enabled).length;

  useEffect(() => {
    if (isSearching) setOpen(true);
  }, [isSearching]);

  if (items.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground/80 transition-colors hover:bg-foreground/5 hover:text-foreground"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Icon className="h-3.5 w-3.5 shrink-0 text-primary/80" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[11px] font-semibold text-foreground">
            {definition.label}
          </span>
          <span className="block truncate text-[9.5px] leading-4 text-muted-foreground/65">
            {definition.description}
          </span>
        </span>
        <span className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[9.5px] tabular-nums text-muted-foreground">
          {enabledCount}/{items.length}
        </span>
      </button>
      {open && (
        <ul className="mt-0.5 space-y-px">
          {items.map((skill) => {
            const isExpanded = expandedSkills.has(skill.name);
            const tree = trees[skill.name];
            const isSelected = selectedSkill === skill.name;
            const isLoadingTree = loadingTree === skill.name;
            return (
              <li key={skill.name}>
                <SkillRailRow
                  skill={skill}
                  selected={isSelected && selectedPath === "SKILL.md"}
                  expanded={isExpanded}
                  toggling={togglingSkills.has(skill.name)}
                  onSelect={() => onSelectSkill(skill.name, "SKILL.md")}
                  onToggleExpand={() => onToggleExpand(skill.name)}
                  onToggleEnable={() => onToggleEnable(skill)}
                />
                {isExpanded && (
                  <div className="ml-6 mt-0.5 mb-1 border-l border-border/60 pl-2">
                    {isLoadingTree && !tree && (
                      <div className="py-1 text-[10px] text-muted-foreground">
                        Loading…
                      </div>
                    )}
                    {tree && tree.length === 0 && (
                      <div className="py-1 text-[10px] text-muted-foreground/70">
                        No files
                      </div>
                    )}
                    {tree && tree.length > 0 && (
                      <FileTreeList
                        nodes={tree}
                        skillName={skill.name}
                        expandedFolders={expandedFolders}
                        selectedSkill={selectedSkill}
                        selectedPath={selectedPath}
                        onSelectFile={(path) => onSelectSkill(skill.name, path)}
                        onToggleFolder={(path) =>
                          onToggleFolder(skill.name, path)
                        }
                      />
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function SkillRailRow({
  skill,
  selected,
  expanded,
  toggling,
  onSelect,
  onToggleExpand,
  onToggleEnable,
}: {
  skill: SkillInfo;
  selected: boolean;
  expanded: boolean;
  toggling: boolean;
  onSelect: () => void;
  onToggleExpand: () => void;
  onToggleEnable: () => void;
}) {
  return (
    <div
      className={`group flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left transition-colors ${
        selected
          ? "bg-foreground/10 text-foreground"
          : "text-foreground/85 hover:bg-foreground/5"
      }`}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${skill.name}` : `Expand ${skill.name}`}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground/70 transition-colors hover:bg-foreground/10 hover:text-foreground"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-1.5 rounded-sm py-0.5 text-left"
      >
        <Sparkles
          className={`h-3 w-3 shrink-0 ${
            skill.enabled ? "text-primary" : "text-muted-foreground/50"
          }`}
        />
        <span
          className={`min-w-0 flex-1 truncate text-[12px] ${
            skill.enabled
              ? "text-foreground"
              : "text-muted-foreground line-through decoration-muted-foreground/40"
          }`}
        >
          {skill.name}
        </span>
      </button>
      <Switch
        checked={skill.enabled}
        disabled={toggling}
        onCheckedChange={() => onToggleEnable()}
        className="h-4 w-7 [&>span]:h-3 [&>span]:w-3"
      />
    </div>
  );
}

function FileTreeList({
  nodes,
  skillName,
  expandedFolders,
  selectedSkill,
  selectedPath,
  onSelectFile,
  onToggleFolder,
}: {
  nodes: SkillTreeNode[];
  skillName: string;
  expandedFolders: Set<string>;
  selectedSkill: string | null;
  selectedPath: string;
  onSelectFile: (path: string) => void;
  onToggleFolder: (path: string) => void;
}) {
  return (
    <ul className="space-y-px">
      {nodes.map((node) => {
        if (node.type === "dir") {
          const key = `${skillName}::${node.path}`;
          const open = expandedFolders.has(key);
          return (
            <li key={node.path}>
              <button
                type="button"
                onClick={() => onToggleFolder(node.path)}
                className="group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-foreground/80 hover:bg-foreground/5"
              >
                {open ? (
                  <FolderOpen className="h-3 w-3 shrink-0 text-muted-foreground" />
                ) : (
                  <Folder className="h-3 w-3 shrink-0 text-muted-foreground" />
                )}
                <span className="truncate text-[11.5px]">{node.name}</span>
                <ChevronRight
                  className={`ml-auto h-3 w-3 text-muted-foreground/60 transition-transform ${
                    open ? "rotate-90" : ""
                  }`}
                />
              </button>
              {open && node.children && node.children.length > 0 && (
                <div className="ml-3 mt-0.5 border-l border-border/40 pl-2">
                  <FileTreeList
                    nodes={node.children}
                    skillName={skillName}
                    expandedFolders={expandedFolders}
                    selectedSkill={selectedSkill}
                    selectedPath={selectedPath}
                    onSelectFile={onSelectFile}
                    onToggleFolder={onToggleFolder}
                  />
                </div>
              )}
            </li>
          );
        }

        const Icon = fileIcon(node.name);
        const isSelected =
          selectedSkill === skillName && selectedPath === node.path;
        const isSkillMd = node.name === "SKILL.md";
        return (
          <li key={node.path}>
            <button
              type="button"
              onClick={() => onSelectFile(node.path)}
              className={`group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors ${
                isSelected
                  ? "bg-foreground/10 text-foreground"
                  : "text-foreground/75 hover:bg-foreground/5"
              }`}
            >
              <Icon
                className={`h-3 w-3 shrink-0 ${
                  isSkillMd ? "text-primary" : "text-muted-foreground"
                }`}
              />
              <span className="truncate text-[11.5px]">{node.name}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/*  Right pane: skill detail + markdown preview                        */
/* ------------------------------------------------------------------ */

function SkillDetail({
  skill,
  filePath,
  fileContent,
  fileLoading,
  viewMode,
  setViewMode,
  toggling,
  onToggleEnable,
}: {
  skill: SkillInfo;
  filePath: string;
  fileContent: string;
  fileLoading: boolean;
  viewMode: "render" | "raw";
  setViewMode: (v: "render" | "raw") => void;
  toggling: boolean;
  onToggleEnable: () => void;
}) {
  const trigger = useMemo(() => {
    return skill.enabled ? "Slash command + auto" : "Disabled";
  }, [skill.enabled]);

  const addedBy = displaySkillCategory(skill);

  return (
    <div className="flex flex-1 flex-col">
      {/* Header */}
      <header className="flex items-start justify-between gap-4 border-b border-border px-5 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold text-foreground">
              {skill.name}
            </h2>
            {!skill.enabled && (
              <Badge variant="outline" className="text-[10px]">
                Disabled
              </Badge>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] sm:max-w-md">
            <span className="text-muted-foreground">Added by</span>
            <span className="text-muted-foreground">Trigger</span>
            <span className="font-mono-ui text-foreground">{addedBy}</span>
            <span className="font-mono-ui text-foreground">{trigger}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={skill.enabled}
            onCheckedChange={onToggleEnable}
            disabled={toggling}
          />
          <button
            type="button"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
            aria-label="More"
          >
            <MoreVertical className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Description block */}
      <div className="border-b border-border px-5 py-3">
        <div className="text-[11px] font-medium text-muted-foreground">
          Description
        </div>
        <p className="mt-1 text-xs leading-relaxed text-foreground/85">
          {skill.description || "No description provided."}
        </p>
      </div>

      {/* Path crumb + render/raw toggle */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-2">
        <div className="flex items-center gap-1.5 text-[11px] font-mono-ui text-muted-foreground">
          <FileText className="h-3 w-3" />
          <span>{filePath}</span>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-border bg-card p-0.5">
          <button
            type="button"
            onClick={() => setViewMode("render")}
            className={`flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] transition-colors ${
              viewMode === "render"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Render markdown"
          >
            <Eye className="h-3 w-3" />
          </button>
          <button
            type="button"
            onClick={() => setViewMode("raw")}
            className={`flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] transition-colors ${
              viewMode === "raw"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Show raw"
          >
            <Code2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {fileLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : viewMode === "render" ? (
          <div className="rounded-md border border-border bg-card/40 p-4">
            <Markdown content={stripFrontmatter(fileContent)} />
          </div>
        ) : (
          <pre className="rounded-md border border-border bg-card/60 p-4 text-xs font-mono leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
            {fileContent}
          </pre>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Workflow flow card (compact)                                       */
/* ------------------------------------------------------------------ */

function WorkflowFlowCard({
  workflow,
  skillsByName,
  togglingSkills,
  onToggle,
}: {
  workflow: (typeof REAL_ESTATE_WORKFLOWS)[number];
  skillsByName: Map<string, SkillInfo>;
  togglingSkills: Set<string>;
  onToggle: (skill: SkillInfo) => void;
}) {
  const Icon = workflow.icon;
  const present = workflow.names
    .map((name) => skillsByName.get(name))
    .filter((skill): skill is SkillInfo => Boolean(skill));
  const missing = workflow.names.filter((name) => !skillsByName.has(name));
  const enabled = present.filter((skill) => skill.enabled).length;

  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <div className="truncate text-sm font-semibold text-foreground">
            {workflow.label}
          </div>
        </div>
        <Badge variant={missing.length ? "warning" : "success"}>
          {present.length}/{workflow.names.length}
        </Badge>
      </div>
      <div className="mt-3 space-y-1.5">
        {present.map((skill) => (
          <div
            key={skill.name}
            className="flex items-center justify-between gap-2 rounded-md bg-card px-2.5 py-1.5"
          >
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-foreground">
                {skill.name}
              </div>
              <div className="mt-0.5 flex items-center gap-1 text-[0.65rem] text-muted-foreground">
                {skill.enabled && (
                  <CheckCircle2 className="h-3 w-3 text-success" />
                )}
                {skill.enabled ? "Enabled" : "Disabled"}
              </div>
            </div>
            <Switch
              checked={skill.enabled}
              disabled={togglingSkills.has(skill.name)}
              onCheckedChange={() => onToggle(skill)}
            />
          </div>
        ))}
        {missing.map((name) => (
          <div
            key={name}
            className="rounded-md border border-dashed border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground"
          >
            {name} missing
          </div>
        ))}
      </div>
      <div className="mt-3 text-[0.68rem] leading-4 text-muted-foreground">
        {enabled} enabled in this section.
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

function stripFrontmatter(text: string): string {
  if (!text.startsWith("---")) return text;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return text;
  return text.slice(end + 4).replace(/^\s*\n/, "");
}
