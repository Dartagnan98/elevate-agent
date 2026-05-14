import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  Routes,
  Route,
  NavLink,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Activity,
  Archive,
  BarChart3,
  BookOpen,
  Bot,
  AlertTriangle,
  Brain,
  BriefcaseBusiness,
  Building2,
  ChevronDown,
  ChevronRight,
  Clock,
  Code,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  Globe,
  Heart,
  Home,
  KeyRound,
  ListChecks,
  Loader2,
  MailOpen,
  Maximize2,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Package,
  PanelLeftClose,
  Pause,
  Pencil,
  Pin,
  Plus,
  Puzzle,
  RotateCw,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  Terminal,
  Megaphone,
  Users,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { SelectionSwitcher } from "@nous-research/ui/ui/components/selection-switcher";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { api, type CronJob, type SessionInfo } from "@/lib/api";
import type { AccessStatusResponse } from "@/lib/api-types";
import { cn, timeAgo } from "@/lib/utils";
import { Backdrop } from "@/components/Backdrop";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { SidebarUserPill } from "@/components/SidebarUserPill";
import { SidebarStatusStrip } from "@/components/SidebarStatusStrip";
import { Toast } from "@/components/Toast";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { useSystemActions } from "@/contexts/useSystemActions";
import type { SystemAction } from "@/contexts/system-actions-context";
const ConfigPage = lazy(() => import("@/pages/ConfigPage"));
const DocsPage = lazy(() => import("@/pages/DocsPage"));
const EnvPage = lazy(() => import("@/pages/EnvPage"));
const SessionsPage = lazy(() => import("@/pages/SessionsPage"));
const LogsPage = lazy(() => import("@/pages/LogsPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const CronPage = lazy(() => import("@/pages/CronPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const AgentHubPage = lazy(() => import("@/pages/AgentHubPage"));
const DesktopSetupPage = lazy(() => import("@/pages/DesktopSetupPage"));
const ProjectPage = lazy(() => import("@/pages/ProjectPage"));
const RealEstateAdminPage = lazy(() =>
  import("@/pages/real-estate-hub/admin").then((m) => ({ default: m.RealEstateAdminPage })),
);
const RealEstateTemplatesPage = lazy(() => import("@/pages/RealEstateTemplatesPage"));
const RealEstateLeadsPage = lazy(() =>
  import("@/pages/RealEstateHubPages").then((m) => ({ default: m.RealEstateLeadsPage })),
);
const RealEstateMemoryPage = lazy(() =>
  import("@/pages/real-estate-hub/memory").then((m) => ({ default: m.RealEstateMemoryPage })),
);
const RealEstateSocialMediaPage = lazy(() =>
  import("@/pages/real-estate-hub/social").then((m) => ({ default: m.RealEstateSocialMediaPage })),
);
const RealEstateTasksPage = lazy(() =>
  import("@/pages/real-estate-hub/tasks").then((m) => ({ default: m.RealEstateTasksPage })),
);
const RealEstateTodayPage = lazy(() =>
  import("@/pages/real-estate-hub/today").then((m) => ({ default: m.RealEstateTodayPage })),
);
import { useI18n } from "@/i18n";
import { PluginPage, PluginSlot, usePlugins } from "@/plugins";
import type { PluginManifest } from "@/plugins";
import { useTheme } from "@/themes";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { useToast } from "@/hooks/useToast";

function RootRedirect() {
  return <Navigate to="/today" replace />;
}

function CoreRootRedirect() {
  return <Navigate to={isDashboardEmbeddedChatEnabled() ? "/chat" : "/hub"} replace />;
}

function AccessLoadingPage() {
  return (
    <div className="onboarding-overlay relative flex min-h-[calc(100vh-4rem)] items-center justify-center overflow-hidden">
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex flex-col items-center gap-3">
        <Loader2 className="onboarding-rise h-5 w-5 animate-spin text-primary" />
        <span className="onboarding-rise-delay-1 font-mono-ui text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
          Loading access
        </span>
      </div>
    </div>
  );
}

function LockedDashboardRedirect() {
  return <Navigate to="/hub" replace />;
}

function MarketingRedirect() {
  return <Navigate to="/social-media" replace />;
}

function AdminRedirect() {
  return <Navigate to="/admin" replace />;
}

function ApprovalsRedirect() {
  return <Navigate to="/today" replace />;
}

const CHAT_NAV_ITEM: NavItem = {
  path: "/chat",
  labelKey: "chat",
  label: "Chat",
  icon: MessageSquare,
};

/** Built-in routes except paid pack dashboards and /chat. */
const BUILTIN_ROUTES_BASE: Record<string, ComponentType> = {
  "/hub": AgentHubPage,
  "/desktop-setup": DesktopSetupPage,
  "/project": ProjectPage,
  "/sessions": SessionsPage,
  "/analytics": AnalyticsPage,
  "/logs": LogsPage,
  "/cron": CronPage,
  "/skills": SkillsPage,
  "/config": ConfigPage,
  "/env": EnvPage,
  "/docs": DocsPage,
};

const BUILTIN_NAV_REST: NavItem[] = [
  {
    path: "/hub",
    label: "Agent Hub",
    icon: Bot,
  },
  {
    path: "/desktop-setup",
    label: "Desktop Setup",
    icon: ShieldCheck,
  },
  {
    path: "/sessions",
    labelKey: "sessions",
    label: "Sessions",
    icon: MessageSquare,
  },
  {
    path: "/project",
    labelKey: "project",
    label: "Project",
    icon: Folder,
  },
  {
    path: "/analytics",
    labelKey: "analytics",
    label: "Analytics",
    icon: BarChart3,
  },
  { path: "/logs", labelKey: "logs", label: "Logs", icon: FileText },
  { path: "/cron", labelKey: "cron", label: "Cron", icon: Clock },
  { path: "/skills", labelKey: "skills", label: "Skills", icon: Package },
  { path: "/config", labelKey: "config", label: "Config", icon: Settings },
  { path: "/env", labelKey: "keys", label: "Keys", icon: KeyRound },
  {
    path: "/docs",
    labelKey: "documentation",
    label: "Documentation",
    icon: BookOpen,
  },
];

const ICON_MAP: Record<string, ComponentType<{ className?: string }>> = {
  Activity,
  BarChart3,
  Clock,
  FileText,
  KeyRound,
  MessageSquare,
  Package,
  Settings,
  Puzzle,
  Sparkles,
  Terminal,
  Globe,
  Database,
  Brain,
  Shield,
  ShieldCheck,
  Wrench,
  Zap,
  Heart,
  Star,
  Code,
  Eye,
  Home,
  Users,
  Building2,
  BriefcaseBusiness,
  Megaphone,
  ListChecks,
};

function resolveIcon(name: string): ComponentType<{ className?: string }> {
  return ICON_MAP[name] ?? Puzzle;
}

function buildNavItems(builtIn: NavItem[], manifests: PluginManifest[]): NavItem[] {
  const items = [...builtIn];

  for (const manifest of manifests) {
    if (manifest.tab.override) continue;
    if (manifest.tab.hidden) continue;

    const pluginItem: NavItem = {
      path: manifest.tab.path,
      label: manifest.label,
      icon: resolveIcon(manifest.icon),
    };

    const pos = manifest.tab.position ?? "end";
    if (pos === "end") {
      items.push(pluginItem);
    } else if (pos.startsWith("after:")) {
      const target = "/" + pos.slice(6);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx + 1 : items.length, 0, pluginItem);
    } else if (pos.startsWith("before:")) {
      const target = "/" + pos.slice(7);
      const idx = items.findIndex((i) => i.path === target);
      items.splice(idx >= 0 ? idx : items.length, 0, pluginItem);
    } else {
      items.push(pluginItem);
    }
  }

  return items;
}

function buildRoutes(
  builtinRoutes: Record<string, ComponentType>,
  manifests: PluginManifest[],
): Array<{
  key: string;
  path: string;
  element: ReactNode;
}> {
  const byOverride = new Map<string, PluginManifest>();
  const addons: PluginManifest[] = [];

  for (const m of manifests) {
    if (m.tab.override) {
      byOverride.set(m.tab.override, m);
    } else {
      addons.push(m);
    }
  }

  const routes: Array<{
    key: string;
    path: string;
    element: ReactNode;
  }> = [];

  for (const [path, Component] of Object.entries(builtinRoutes)) {
    const om = byOverride.get(path);
    if (om) {
      routes.push({
        key: `override:${om.name}`,
        path,
        element: <PluginPage name={om.name} />,
      });
    } else {
      routes.push({ key: `builtin:${path}`, path, element: <Component /> });
    }
  }

  for (const m of addons) {
    if (m.tab.hidden) continue;
    if (builtinRoutes[m.tab.path]) continue;
    routes.push({
      key: `plugin:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  for (const m of manifests) {
    if (!m.tab.hidden) continue;
    if (builtinRoutes[m.tab.path] || m.tab.override) continue;
    routes.push({
      key: `plugin:hidden:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  return routes;
}

type RealEstatePackAccess = AccessStatusResponse["packs"];

const DEFAULT_REAL_ESTATE_PACKS: RealEstatePackAccess = {
  realEstateSales: false,
  realEstateMarketing: false,
  realEstateAdmin: false,
  realEstateCma: false,
  realEstateAny: false,
};

function hasRealEstateDashboard(packs: RealEstatePackAccess): boolean {
  return packs.realEstateSales || packs.realEstateMarketing || packs.realEstateAdmin;
}

function buildAccessControlledBuiltinRoutes(
  embeddedChat: boolean,
  packs: RealEstatePackAccess,
  accessPending = false,
): Record<string, ComponentType> {
  const realEstateDashboard = hasRealEstateDashboard(packs);
  const PendingOrLocked = accessPending ? AccessLoadingPage : LockedDashboardRedirect;
  return {
    "/": accessPending ? AccessLoadingPage : realEstateDashboard ? RootRedirect : CoreRootRedirect,
    "/today": realEstateDashboard ? RealEstateTodayPage : PendingOrLocked,
    "/leads": packs.realEstateSales ? RealEstateLeadsPage : PendingOrLocked,
    "/admin": packs.realEstateAdmin ? RealEstateAdminPage : PendingOrLocked,
    "/admin/templates": packs.realEstateAdmin
      ? RealEstateTemplatesPage
      : PendingOrLocked,
    "/listings": packs.realEstateAdmin ? AdminRedirect : PendingOrLocked,
    "/deals": packs.realEstateAdmin ? AdminRedirect : PendingOrLocked,
    "/social-media": packs.realEstateMarketing
      ? RealEstateSocialMediaPage
      : PendingOrLocked,
    "/marketing": packs.realEstateMarketing ? MarketingRedirect : PendingOrLocked,
    "/tasks": RealEstateTasksPage,
    "/approvals": packs.realEstateAdmin ? ApprovalsRedirect : PendingOrLocked,
    "/memory": RealEstateMemoryPage,
    ...BUILTIN_ROUTES_BASE,
    ...(embeddedChat ? { "/chat": ChatPage } : {}),
  };
}

export default function App() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { manifests } = usePlugins();
  const { theme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem("elevate.sidebar.collapsed.v1") === "1";
    } catch {
      return false;
    }
  });
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(
          "elevate.sidebar.collapsed.v1",
          next ? "1" : "0",
        );
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const isDocsRoute = pathname === "/docs" || pathname === "/docs/";
  const normalizedPath = pathname.replace(/\/$/, "") || "/";
  const isChatRoute = normalizedPath === "/chat";
  const isConfigRoute = normalizedPath === "/config";
  const embeddedChat = isDashboardEmbeddedChatEnabled();
  const [accessStatus, setAccessStatus] = useState<AccessStatusResponse | null>(null);
  const [accessChecked, setAccessChecked] = useState(false);
  const [accessVersion, setAccessVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setAccessChecked(false);
    api
      .getAccessStatus()
      .then((status) => {
        if (!cancelled) setAccessStatus(status);
      })
      .catch(() => {
        if (!cancelled) setAccessStatus(null);
      })
      .finally(() => {
        if (!cancelled) setAccessChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [accessVersion]);

  useEffect(() => {
    const handler = () => setAccessVersion((v) => v + 1);
    window.addEventListener("elevate:auth-changed", handler);
    return () => window.removeEventListener("elevate:auth-changed", handler);
  }, []);

  const realEstatePacks = accessStatus?.packs ?? DEFAULT_REAL_ESTATE_PACKS;
  const realEstateDashboard = hasRealEstateDashboard(realEstatePacks);

  const builtinRoutes = useMemo(
    () => buildAccessControlledBuiltinRoutes(embeddedChat, realEstatePacks, !accessChecked),
    [accessChecked, embeddedChat, realEstatePacks],
  );

  const builtinNav = useMemo(
    () =>
      embeddedChat ? [CHAT_NAV_ITEM, ...BUILTIN_NAV_REST] : BUILTIN_NAV_REST,
    [embeddedChat],
  );

  const navItems = useMemo(
    () => buildNavItems(builtinNav, manifests),
    [builtinNav, manifests],
  );
  const routes = useMemo(
    () => buildRoutes(builtinRoutes, manifests),
    [builtinRoutes, manifests],
  );
  const pluginTabMeta = useMemo(
    () =>
      manifests
        .filter((m) => !m.tab.hidden)
        .map((m) => ({
          path: m.tab.override ?? m.tab.path,
          label: m.label,
        })),
    [manifests],
  );

  const layoutVariant = theme.layoutVariant ?? "standard";

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [mobileOpen]);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return (
    <div
      data-layout-variant={layoutVariant}
      className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base font-sans normal-case text-midground antialiased"
    >
      <SelectionSwitcher />
      <Backdrop />
      <PluginSlot name="backdrop" />

      <header
        className={cn(
          "lg:hidden fixed top-0 left-0 right-0 z-40 h-12",
          "flex items-center gap-2 px-3",
          "bg-background-base shadow-[0_1px_0_color-mix(in_srgb,var(--midground-base)_7%,transparent)]",
        )}
      >
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label={t.app.openNavigation}
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          className={cn(
            "inline-flex h-11 w-11 items-center justify-center",
            "text-midground/70 hover:text-midground transition-colors cursor-pointer",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          )}
        >
          <Menu className="h-4 w-4" />
        </button>

        <Typography
          className="text-[0.95rem] font-semibold leading-none tracking-normal text-midground"
        >
          {t.app.brand}
        </Typography>
      </header>

      {mobileOpen && (
        <button
          type="button"
          aria-label={t.app.closeNavigation}
          onClick={closeMobile}
          className={cn(
            "lg:hidden fixed inset-0 z-40",
            "bg-black/60 cursor-pointer",
          )}
        />
      )}

      <PluginSlot name="header-banner" />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-12 lg:pt-0">
        <div className="flex min-h-0 min-w-0 flex-1">
          <aside
            id="app-sidebar"
            aria-label={t.app.navigation}
            className={cn(
              "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-[312px] max-w-[calc(100vw-1.5rem)] min-h-0 flex-col",
              "bg-[var(--sidebar-bg)]",
              "transition-transform duration-200 ease-out",
              mobileOpen ? "translate-x-0" : "-translate-x-full",
              sidebarCollapsed
                ? "lg:hidden"
                : cn(
                    "lg:sticky lg:translate-x-0 lg:shrink-0",
                    // Floating / pilled treatment on desktop: inset from the
                    // window edges so the page background frames the sidebar.
                    "lg:top-2 lg:my-2 lg:ml-2 lg:h-[calc(100dvh-1rem)]",
                    "lg:overflow-hidden lg:rounded-xl lg:border lg:border-[var(--sidebar-border)]",
                    "lg:shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_-12px_rgba(0,0,0,0.45)]",
                  ),
              isConfigRoute && "lg:hidden",
            )}
          >
            <DesktopSidebar
              embeddedChat={embeddedChat}
              navItems={navItems}
              onNavigate={closeMobile}
              onToggleSidebar={toggleSidebar}
              readyToLoad={accessChecked}
              realEstatePacks={realEstatePacks}
            />
          </aside>

          <PageHeaderProvider
            pluginTabs={pluginTabMeta}
            sidebarCollapsed={sidebarCollapsed && !isConfigRoute}
            onShowSidebar={toggleSidebar}
          >
            <div
              className={cn(
                "relative z-2 flex min-w-0 min-h-0 flex-1 flex-col",
                isConfigRoute && "p-0",
                isChatRoute && "p-0 bg-[var(--chat-bg)]",
                !isConfigRoute && !isChatRoute && "px-3 sm:px-6 pt-2 sm:pt-4 lg:pt-6 pb-4 sm:pb-8",
                isDocsRoute && "min-h-0 flex-1",
              )}
            >
              <PluginSlot name="pre-main" />
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute && !isConfigRoute && "elevate-page-shell",
                  isDocsRoute && "elevate-docs-shell",
                  (isDocsRoute || isChatRoute) && "min-h-0 flex flex-1 flex-col",
                )}
              >
                <div
                  key={normalizedPath}
                  className={cn(
                    "min-w-0",
                    (isDocsRoute || isChatRoute) && "min-h-0 flex flex-1 flex-col",
                    !isChatRoute && !isConfigRoute && "elevate-route-transition",
                  )}
                >
                  <Suspense
                    fallback={
                      <div className="onboarding-overlay relative flex min-h-[calc(100vh-9rem)] items-center justify-center overflow-hidden">
                        <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
                        <div className="relative flex flex-col items-center gap-3">
                          <Loader2 className="onboarding-rise h-5 w-5 animate-spin text-primary" />
                          <span className="onboarding-rise-delay-1 font-mono-ui text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                            Loading
                          </span>
                        </div>
                      </div>
                    }
                  >
                    <Routes>
                      {routes.map(({ key, path, element }) => (
                        <Route key={key} path={path} element={element} />
                      ))}
                      <Route
                        path="*"
                        element={
                          <Navigate
                            to={realEstateDashboard ? "/today" : "/hub"}
                            replace
                          />
                        }
                      />
                    </Routes>
                  </Suspense>
                </div>
              </div>
              <PluginSlot name="post-main" />
            </div>
          </PageHeaderProvider>
        </div>
      </div>

      <PluginSlot name="overlay" />
    </div>
  );
}

const PINNED_SESSIONS_KEY = "elevate.sidebar.pinnedSessions";
const UNREAD_SESSIONS_KEY = "elevate.sidebar.unreadSessions";
const ARCHIVED_SESSIONS_KEY = "elevate.sidebar.archivedSessions";
const SIDEBAR_SESSION_LIMIT = 48;

function readStoredSessionIds(key: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === "string")
      : [];
  } catch {
    return [];
  }
}

function writeStoredSessionIds(key: string, ids: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // Local sidebar state is a convenience only; failing closed keeps navigation usable.
  }
}

function readPinnedSessionIds(): string[] {
  return readStoredSessionIds(PINNED_SESSIONS_KEY);
}

function writePinnedSessionIds(ids: string[]): void {
  writeStoredSessionIds(PINNED_SESSIONS_KEY, ids);
}

function readUnreadSessionIds(): string[] {
  return readStoredSessionIds(UNREAD_SESSIONS_KEY);
}

function writeUnreadSessionIds(ids: string[]): void {
  writeStoredSessionIds(UNREAD_SESSIONS_KEY, ids);
}

function readArchivedSessionIds(): string[] {
  return readStoredSessionIds(ARCHIVED_SESSIONS_KEY);
}

function writeArchivedSessionIds(ids: string[]): void {
  writeStoredSessionIds(ARCHIVED_SESSIONS_KEY, ids);
}

function sessionTitle(session: SessionInfo): string {
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled chat";
}

function cronJobIdFromSession(session: SessionInfo): string | null {
  if ((session.source ?? "") !== "cron") return null;
  if (!session.id?.startsWith("cron_")) return null;
  return session.id.replace(/^cron_/, "").split("_", 1)[0] ?? null;
}

function isCronSession(session: SessionInfo): boolean {
  return cronJobIdFromSession(session) !== null;
}

function sessionRoute(session: SessionInfo, embeddedChat: boolean): string {
  if (!embeddedChat) return "/hub";
  return `/chat?resume=${encodeURIComponent(session.id)}`;
}

function compactSessionAge(ts: number): string {
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "now";
  if (delta < 3600) return `${Math.max(1, Math.floor(delta / 60))}m`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
  return `${Math.floor(delta / 86400)}d`;
}

type SessionMenuState = {
  session: SessionInfo;
  x: number;
  y: number;
};

async function copyToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function DesktopSidebar({
  embeddedChat,
  navItems,
  onNavigate,
  onToggleSidebar,
  readyToLoad,
  realEstatePacks,
}: {
  embeddedChat: boolean;
  navItems: NavItem[];
  onNavigate: () => void;
  onToggleSidebar: () => void;
  readyToLoad: boolean;
  realEstatePacks: RealEstatePackAccess;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionError, setSessionError] = useState(false);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [automationsOpen, setAutomationsOpen] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem("elevate.sidebar.automations.v3") !== "0";
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "elevate.sidebar.automations.v3",
        automationsOpen ? "1" : "0",
      );
    } catch {
      /* ignore */
    }
  }, [automationsOpen]);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => {
    try {
      const raw = window.localStorage.getItem("elevate.sidebar.sections.v1");
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const toggleSection = useCallback((key: string) => {
    setCollapsedSections((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try {
        window.localStorage.setItem("elevate.sidebar.sections.v1", JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const openSearch = useCallback(() => {
    setSearchOpen(true);
    requestAnimationFrame(() => searchRef.current?.focus());
  }, []);
  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    setQuery("");
  }, []);
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => readPinnedSessionIds());
  const [unreadIds, setUnreadIds] = useState<string[]>(() => readUnreadSessionIds());
  const [archivedIds, setArchivedIds] = useState<string[]>(() =>
    readArchivedSessionIds(),
  );
  const [sessionMenu, setSessionMenu] = useState<SessionMenuState | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { themeName } = useTheme();
  const sidebarLogoSrc =
    themeName === "light" ? "/elevateos-wordmark.png" : "/elevateos-wordmark-dark.png";

  const loadSessions = useCallback(() => {
    api
      .getSessions(SIDEBAR_SESSION_LIMIT, 0, { includeTotal: false })
      .then((resp) => {
        setSessions(resp.sessions);
        setSessionError(false);
      })
      .catch(() => setSessionError(true))
      .finally(() => setSessionsLoading(false));
  }, []);

  useEffect(() => {
    if (!readyToLoad) return;
    const initialLoad = window.setTimeout(loadSessions, 120);
    if (typeof document === "undefined") return;
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (!id) id = window.setInterval(loadSessions, 12000);
    };
    const stop = () => {
      if (id) { window.clearInterval(id); id = null; }
    };
    const onVisibility = () => {
      if (document.hidden) stop(); else { loadSessions(); start(); }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(initialLoad);
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [loadSessions, readyToLoad]);

  useEffect(() => {
    if (!readyToLoad) return;
    let cancelled = false;
    const loadJobs = () => {
      api
        .getCronJobs()
        .then((jobs) => {
          if (!cancelled) setCronJobs(jobs ?? []);
        })
        .catch(() => {
          /* sidebar can render empty if cron API is down */
        });
    };
    const initialLoad = window.setTimeout(loadJobs, 300);
    const id = window.setInterval(() => {
      if (typeof document === "undefined" || !document.hidden) loadJobs();
    }, 20000);
    return () => {
      cancelled = true;
      window.clearTimeout(initialLoad);
      window.clearInterval(id);
    };
  }, [readyToLoad]);

  useEffect(() => {
    writePinnedSessionIds(pinnedIds);
  }, [pinnedIds]);

  useEffect(() => {
    writeUnreadSessionIds(unreadIds);
  }, [unreadIds]);

  useEffect(() => {
    writeArchivedSessionIds(archivedIds);
  }, [archivedIds]);

  useEffect(() => {
    if (!sessionMenu) return;
    const close = () => setSessionMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [sessionMenu]);

  useEffect(() => {
    const onOpenMenu = (event: Event) => {
      const ce = event as CustomEvent<{ sessionId: string; x: number; y: number }>;
      const detail = ce.detail;
      if (!detail?.sessionId) return;
      const match = sessions.find((s) => s.id === detail.sessionId);
      if (!match) return;
      setSessionMenu({ session: match, x: detail.x, y: detail.y });
    };
    window.addEventListener("elevate:open-session-menu", onOpenMenu);
    return () => window.removeEventListener("elevate:open-session-menu", onOpenMenu);
  }, [sessions]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      const isTyping =
        target?.isContentEditable ||
        tagName === "INPUT" ||
        tagName === "TEXTAREA" ||
        tagName === "SELECT";
      if (isTyping) return;
      event.preventDefault();
      openSearch();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openSearch]);

  const filteredSessions = useMemo(() => {
    const visibleSessions = sessions.filter(
      (session) => !archivedIds.includes(session.id),
    );
    const q = query.trim().toLowerCase();
    if (!q) return visibleSessions;
    return visibleSessions.filter((session) => {
      const haystack = [
        sessionTitle(session),
        session.preview ?? "",
        session.source ?? "",
        session.model ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [archivedIds, query, sessions]);

  const pinnedSessions = filteredSessions
    .filter((session) => pinnedIds.includes(session.id) && !isCronSession(session))
    .slice(0, 8);
  const spotlightIds = new Set(pinnedSessions.map((session) => session.id));
  const chatSessions = filteredSessions
    .filter((session) => !spotlightIds.has(session.id) && !isCronSession(session))
    .slice(0, 18);
  const cronSessionsByJobId = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const session of sessions) {
      const jobId = cronJobIdFromSession(session);
      if (!jobId) continue;
      const list = map.get(jobId) ?? [];
      list.push(session);
      map.set(jobId, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (b.last_active ?? 0) - (a.last_active ?? 0));
    }
    return map;
  }, [sessions]);
  const latestCronSessionByJobId = useMemo(() => {
    const map = new Map<string, SessionInfo>();
    for (const [jobId, list] of cronSessionsByJobId) {
      if (list[0]) map.set(jobId, list[0]);
    }
    return map;
  }, [cronSessionsByJobId]);
  const runningCronJobIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [jobId, session] of latestCronSessionByJobId) {
      if (session.is_active) ids.add(jobId);
    }
    return ids;
  }, [latestCronSessionByJobId]);
  const systemPaths = new Set(["/analytics", "/logs", "/env", "/docs"]);
  const toolNavItems = navItems.filter((item) => systemPaths.has(item.path));
  const realEstateDashboard = hasRealEstateDashboard(realEstatePacks);
  const realEstateNavItems: NavItem[] = [];
  if (realEstateDashboard) {
    realEstateNavItems.push({ icon: Home, label: "Today", path: "/today" });
  }
  if (realEstatePacks.realEstateSales) {
    realEstateNavItems.push({ icon: Users, label: "Leads", path: "/leads" });
  }
  if (realEstatePacks.realEstateAdmin) {
    realEstateNavItems.push({ icon: BriefcaseBusiness, label: "Admin", path: "/admin" });
  }
  if (realEstatePacks.realEstateMarketing) {
    realEstateNavItems.push({ icon: Megaphone, label: "Social Media", path: "/social-media" });
  }
  const go = (path: string) => {
    navigate(path);
    onNavigate();
  };

  const startNewChat = () => {
    if (!embeddedChat) {
      go("/hub");
      return;
    }
    navigate(`/chat?new=${Date.now()}`);
    onNavigate();
  };

  const togglePinned = (sessionId: string) => {
    setPinnedIds((prev) =>
      prev.includes(sessionId)
        ? prev.filter((id) => id !== sessionId)
        : [sessionId, ...prev].slice(0, 8),
    );
  };

  const openSession = useCallback(
    (session: SessionInfo) => {
      setUnreadIds((prev) => prev.filter((id) => id !== session.id));
      navigate(sessionRoute(session, embeddedChat));
      onNavigate();
    },
    [embeddedChat, navigate, onNavigate],
  );

  const openSessionMenu = useCallback(
    (session: SessionInfo, event: MouseEvent<HTMLElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setSessionMenu({ session, x: event.clientX, y: event.clientY });
    },
    [],
  );

  const renameSession = useCallback(
    (session: SessionInfo) => {
      setSessionMenu(null);
      setRenamingSessionId(session.id);
    },
    [],
  );

  const commitRename = useCallback(
    async (sessionId: string, newTitle: string) => {
      setRenamingSessionId(null);
      try {
        const response = await api.renameSession(sessionId, newTitle.trim() || null);
        setSessions((prev) =>
          prev.map((item) =>
            item.id === sessionId ? { ...item, title: response.title } : item,
          ),
        );
        showToast("Session renamed", "success");
      } catch {
        showToast("Failed to rename session", "error");
      }
    },
    [showToast],
  );

  const toggleUnread = useCallback(
    (session: SessionInfo) => {
      setSessionMenu(null);
      setUnreadIds((prev) => {
        if (prev.includes(session.id)) {
          showToast("Marked as read", "success");
          return prev.filter((id) => id !== session.id);
        }
        showToast("Marked as unread", "success");
        return [session.id, ...prev];
      });
    },
    [showToast],
  );

  const copySessionId = useCallback(
    async (session: SessionInfo) => {
      setSessionMenu(null);
      try {
        await copyToClipboard(session.id);
        showToast("Session ID copied", "success");
      } catch {
        showToast("Could not copy session ID", "error");
      }
    },
    [showToast],
  );

  const copySessionDeepLink = useCallback(
    async (session: SessionInfo) => {
      setSessionMenu(null);
      const url = new URL(sessionRoute(session, true), window.location.origin);
      try {
        await copyToClipboard(url.toString());
        showToast("Deeplink copied", "success");
      } catch {
        showToast("Could not copy deeplink", "error");
      }
    },
    [showToast],
  );

  const copyWorkingDirectory = useCallback(async () => {
    setSessionMenu(null);
    try {
      const status = await api.getStatus();
      await copyToClipboard(status.project_root || status.elevate_home);
      showToast("Working directory copied", "success");
    } catch {
      showToast("Could not copy working directory", "error");
    }
  }, [showToast]);

  const revealSession = useCallback(
    async (session: SessionInfo) => {
      setSessionMenu(null);
      try {
        await api.revealSession(session.id);
        showToast("Opened in Finder", "success");
      } catch {
        showToast("Could not open session location", "error");
      }
    },
    [showToast],
  );

  const openMiniWindow = useCallback((session: SessionInfo) => {
    setSessionMenu(null);
    const url = sessionRoute(session, true);
    window.open(
      url,
      `elevate-session-${session.id}`,
      "popup,width=920,height=760,menubar=no,toolbar=no,location=no,status=no",
    );
  }, []);

  const sessionArchive = useConfirmDelete<string>({
    onDelete: useCallback(
      async (sessionId: string) => {
        try {
          setArchivedIds((prev) =>
            prev.includes(sessionId) ? prev : [sessionId, ...prev],
          );
          setPinnedIds((prev) => prev.filter((id) => id !== sessionId));
          setUnreadIds((prev) => prev.filter((id) => id !== sessionId));

          const activeResumeId = new URLSearchParams(location.search).get("resume");
          if (
            embeddedChat &&
            location.pathname === "/chat" &&
            activeResumeId === sessionId
          ) {
            navigate("/chat");
          }

          showToast("Chat archived", "success");
        } catch (error) {
          showToast("Failed to archive chat", "error");
          throw error;
        }
      },
      [embeddedChat, location.pathname, location.search, navigate, showToast],
    ),
  });

  const pendingArchiveSession = sessionArchive.pendingId
    ? sessions.find((session) => session.id === sessionArchive.pendingId)
    : null;

  const navLabel = (item: NavItem) =>
    item.labelKey
      ? ((t.app.nav as Record<string, string>)[item.labelKey] ?? item.label)
      : item.label;

  return (
    <div className="normal-case flex min-h-0 flex-1 flex-col font-sans text-[14px] tracking-normal text-[var(--sidebar-text)]">
      <Toast toast={toast} />
      <DeleteConfirmDialog
        open={sessionArchive.isOpen}
        onCancel={sessionArchive.cancel}
        onConfirm={sessionArchive.confirm}
        title="Archive chat?"
        description={
          pendingArchiveSession
            ? `"${sessionTitle(pendingArchiveSession)}" will be hidden from this sidebar. Its saved session data stays on this machine.`
            : "This chat will be hidden from this sidebar. Its saved session data stays on this machine."
        }
        loading={sessionArchive.isDeleting}
      />
      {sessionMenu && (
        <SessionContextMenu
          menu={sessionMenu}
          pinned={pinnedIds.includes(sessionMenu.session.id)}
          unread={unreadIds.includes(sessionMenu.session.id)}
          onClose={() => setSessionMenu(null)}
          onTogglePinned={(session) => {
            setSessionMenu(null);
            togglePinned(session.id);
          }}
          onRename={renameSession}
          onArchive={(session) => {
            setSessionMenu(null);
            sessionArchive.requestDelete(session.id);
          }}
          onToggleUnread={toggleUnread}
          onOpenFinder={revealSession}
          onCopyWorkingDirectory={copyWorkingDirectory}
          onCopySessionId={copySessionId}
          onCopyDeeplink={copySessionDeepLink}
          onOpenMiniWindow={openMiniWindow}
        />
      )}
      <div
        className="relative flex h-11 shrink-0 items-center pl-[5.25rem] pr-3 lg:pl-[5.25rem]"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <div className="flex h-7 w-[9.75rem] min-w-0 items-center">
          <img
            src={sidebarLogoSrc}
            alt="Elevation"
            className="h-6 w-full object-contain"
            draggable={false}
          />
        </div>

        <button
          type="button"
          onClick={onNavigate}
          aria-label={t.app.closeNavigation}
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          className={cn(
            "absolute right-3 top-1/2 inline-flex h-11 w-11 -translate-y-1/2 shrink-0 items-center justify-center lg:hidden",
            "rounded-lg text-muted-foreground hover:bg-accent hover:text-midground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          )}
        >
          <X className="h-4 w-4" />
        </button>

        <div
          className="absolute right-2 top-1/2 hidden lg:flex -translate-y-1/2 items-center gap-1"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <button
            type="button"
            onClick={() => (searchOpen ? closeSearch() : openSearch())}
            aria-label={searchOpen ? "Close search" : "Search"}
            aria-pressed={searchOpen}
            className={cn(
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
              "text-[var(--sidebar-icon-muted)] hover:text-[var(--sidebar-text-active)] hover:bg-[var(--sidebar-row-hover)]",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              searchOpen && "bg-[var(--sidebar-row-hover)] text-[var(--sidebar-text-active)]",
            )}
          >
            <Search className="h-3.5 w-3.5" />
          </button>

          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label="Collapse sidebar"
            className={cn(
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
              "text-[var(--sidebar-icon-muted)] hover:text-[var(--sidebar-text-active)] hover:bg-[var(--sidebar-row-hover)]",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            )}
          >
            <PanelLeftClose className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <PluginSlot name="header-left" />

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-2.5 py-1.5">
        <div className="space-y-0.5">
          <button
            type="button"
            onClick={startNewChat}
            className={sidebarActionClass(false, true)}
          >
            <Plus className="h-4 w-4 shrink-0 text-[var(--sidebar-icon)]" />
            <span className="truncate">New chat</span>
          </button>
          {searchOpen && (
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--sidebar-icon)]" />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    closeSearch();
                  }
                }}
                aria-label="Search chats and navigation"
                placeholder="Search"
                className={cn(
                  "h-11 w-full rounded-lg bg-[var(--sidebar-row)] shadow-[inset_0_0_0_1px_var(--sidebar-border)] lg:h-8 lg:rounded-md",
                  "pl-9 pr-9 text-[0.9rem] text-[var(--sidebar-text-strong)] placeholder:text-[var(--sidebar-text-muted)] lg:text-[0.86rem]",
                  "outline-none transition-colors focus:bg-[var(--chat-surface-strong)] focus:shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_34%,transparent),0_0_0_3px_color-mix(in_srgb,var(--color-primary)_10%,transparent)]",
                )}
              />
              <button
                type="button"
                onClick={closeSearch}
                aria-label={query ? t.common.clear : "Close search"}
                className="absolute right-0.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-md text-[var(--sidebar-icon-muted)] hover:text-[var(--sidebar-icon)] lg:h-7 lg:w-7 lg:right-0.5"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>

        {realEstateNavItems.length > 0 && (
          <div className="mt-2.5">
            <SidebarSectionLabel
              collapsed={collapsedSections.realEstate}
              onToggle={() => toggleSection("realEstate")}
            >
              Real Estate
            </SidebarSectionLabel>
            {!collapsedSections.realEstate && (
              <div className="space-y-0.5">
                {realEstateNavItems.map((item) => (
                  <SidebarAction
                    key={item.path}
                    icon={item.icon}
                    label={item.label}
                    path={item.path}
                    onNavigate={go}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        <div className="mt-2.5">
          <SidebarSectionLabel
            collapsed={collapsedSections.agent}
            onToggle={() => toggleSection("agent")}
          >
            Agent
          </SidebarSectionLabel>
          {!collapsedSections.agent && (
            <div className="space-y-0.5">
              <SidebarAction icon={Bot} label="Agent Hub" path="/hub" onNavigate={go} />
              <SidebarAction icon={ListChecks} label="Tasks" path="/tasks" onNavigate={go} />
              <SidebarAction icon={Brain} label="Memory" path="/memory" onNavigate={go} />
              <SidebarAction icon={Puzzle} label="Skills" path="/skills" onNavigate={go} />
              <SidebarAction icon={Clock} label="Automations" path="/cron" onNavigate={go} />
            </div>
          )}
        </div>

        {pinnedSessions.length > 0 && (
          <SessionSection
            embeddedChat={embeddedChat}
            label="Pinned"
            onOpenContextMenu={openSessionMenu}
            onOpenSession={openSession}
            onTogglePinned={togglePinned}
            pinnedIds={pinnedIds}
            renamingSessionId={renamingSessionId}
            onCommitRename={commitRename}
            onCancelRename={() => setRenamingSessionId(null)}
            sessions={pinnedSessions}
            unreadIds={unreadIds}
          />
        )}

        <SessionSection
          embeddedChat={embeddedChat}
          label="Chats"
          loading={sessionsLoading}
          onOpenContextMenu={openSessionMenu}
          onOpenSession={openSession}
          onTogglePinned={togglePinned}
          pinnedIds={pinnedIds}
          renamingSessionId={renamingSessionId}
          onCommitRename={commitRename}
          onCancelRename={() => setRenamingSessionId(null)}
          sessions={chatSessions}
          unreadIds={unreadIds}
          statusText={
            sessionError
              ? "Sessions unavailable"
              : !sessionsLoading && chatSessions.length === 0
                ? "No chats yet"
                : undefined
          }
        />

        <AutomationsSection
          jobs={cronJobs}
          open={automationsOpen}
          onToggle={() => setAutomationsOpen((prev) => !prev)}
          liveJobIds={runningCronJobIds}
          sessionsByJobId={cronSessionsByJobId}
          onOpenCron={(jobId) => {
            const latest = latestCronSessionByJobId.get(jobId);
            if (latest) {
              openSession(latest);
              return;
            }
            navigate(`/cron#cron-job-${jobId}`);
            onNavigate();
          }}
          onOpenSession={openSession}
        />

        {toolNavItems.length > 0 && (
          <div className="mt-3">
            <SidebarSectionLabel
              collapsed={collapsedSections.tools}
              onToggle={() => toggleSection("tools")}
            >
              Tools
            </SidebarSectionLabel>
            {!collapsedSections.tools && (
              <div className="space-y-0.5">
                {toolNavItems.map((item) => (
                  <SidebarAction
                    key={item.path}
                    icon={item.icon}
                    label={navLabel(item)}
                    path={item.path}
                    onNavigate={go}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        <SidebarSystemActions onNavigate={onNavigate} />
      </div>

      <div className="shrink-0 px-2 pb-2">
        <SidebarUserPill />
      </div>
    </div>
  );
}

function SidebarSectionLabel({
  children,
  collapsed,
  onToggle,
}: {
  children: ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  const baseClass =
    "mb-0.5 mt-3 first:mt-0 px-2 text-[0.62rem] font-semibold uppercase tracking-wider text-[var(--sidebar-text)]";
  if (!onToggle) {
    return <div className={baseClass}>{children}</div>;
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      className={cn(
        baseClass,
        "group flex w-full items-center justify-between gap-1.5 cursor-pointer",
        "hover:text-[var(--sidebar-text-active)] transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm",
      )}
    >
      <span>{children}</span>
      <ChevronDown
        className={cn(
          "h-3 w-3 shrink-0 transition-transform duration-150",
          collapsed && "-rotate-90",
        )}
      />
    </button>
  );
}

function sidebarActionClass(active: boolean, primary = false) {
  return cn(
    "group flex min-h-8 w-full items-center rounded-md px-2 py-1 text-left text-sm",
    "cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
    primary && "font-medium text-[var(--sidebar-text-strong)]",
    active
      ? "text-[var(--sidebar-text-active)] font-medium"
      : "text-[var(--sidebar-text)] hover:text-[var(--sidebar-text-active)]",
  );
}

function SidebarAction({
  icon: Icon,
  label,
  onNavigate,
  path,
  primary = false,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  onNavigate: (path: string) => void;
  path: string;
  primary?: boolean;
}) {
  return (
    <NavLink
      to={path}
      end={path === "/today" || path === "/hub" || path === "/sessions"}
      onClick={(event) => {
        event.preventDefault();
        onNavigate(path);
      }}
      className={({ isActive }) =>
        cn(sidebarActionClass(isActive, primary), "flex items-center gap-2")
      }
    >
      <Icon className="h-4 w-4 shrink-0 text-[var(--sidebar-icon)]" />
      <span className="min-w-0 truncate">{label}</span>
    </NavLink>
  );
}

function SessionSection({
  embeddedChat,
  label,
  loading = false,
  onCancelRename,
  onCommitRename,
  onOpenContextMenu,
  onOpenSession,
  onTogglePinned,
  pinnedIds,
  renamingSessionId,
  sessions,
  statusText,
  unreadIds,
}: {
  embeddedChat: boolean;
  label: string;
  loading?: boolean;
  onCancelRename: () => void;
  onCommitRename: (sessionId: string, title: string) => void;
  onOpenContextMenu: (session: SessionInfo, event: MouseEvent<HTMLElement>) => void;
  onOpenSession: (session: SessionInfo) => void;
  onTogglePinned: (sessionId: string) => void;
  pinnedIds: string[];
  renamingSessionId: string | null;
  sessions: SessionInfo[];
  statusText?: string;
  unreadIds: string[];
}) {
  return (
    <div className="mt-3 lg:mt-2.5">
      <SidebarSectionLabel>{label}</SidebarSectionLabel>
      <div className="space-y-0.5">
        {sessions.map((session) => (
          <SessionListItem
            key={session.id}
            embeddedChat={embeddedChat}
            isRenaming={renamingSessionId === session.id}
            onCancelRename={onCancelRename}
            onCommitRename={onCommitRename}
            onOpenContextMenu={onOpenContextMenu}
            onOpenSession={onOpenSession}
            onTogglePinned={onTogglePinned}
            pinned={pinnedIds.includes(session.id)}
            session={session}
            unread={unreadIds.includes(session.id)}
          />
        ))}
      </div>

      {(loading || statusText) && sessions.length === 0 && (
        <div className="px-2.5 py-1 text-[0.8rem] text-[var(--sidebar-text-muted)]">
          {loading ? "Loading chats" : statusText}
        </div>
      )}
    </div>
  );
}

const SESSION_IDLE_MS = 24 * 60 * 60 * 1000;

function SessionStatusDot({
  lastActive,
  unread,
}: {
  lastActive: number;
  unread: boolean;
}) {
  let tone: "warning" | "idle" | "ok";
  let label: string;
  if (unread) {
    tone = "warning";
    label = "Needs attention";
  } else if (
    !lastActive ||
    Date.now() - lastActive * 1000 > SESSION_IDLE_MS
  ) {
    tone = "idle";
    label = "Inactive";
  } else {
    tone = "ok";
    label = "Done";
  }
  const dotClass =
    tone === "warning"
      ? "bg-[var(--color-warning,#d9a040)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-warning,#d9a040)_14%,transparent)]"
      : tone === "idle"
        ? "bg-[var(--sidebar-icon-muted)]"
        : "bg-[var(--color-success,#7a9e87)]";
  return (
    <span
      aria-label={label}
      title={label}
      className={cn(
        "h-2 w-2 shrink-0 rounded-full lg:h-1.5 lg:w-1.5",
        dotClass,
      )}
    />
  );
}

function SessionListItem({
  embeddedChat,
  isRenaming = false,
  onCancelRename,
  onCommitRename,
  onOpenContextMenu,
  onOpenSession,
  onTogglePinned,
  pinned,
  session,
  unread,
  displayTitle,
}: {
  embeddedChat: boolean;
  isRenaming?: boolean;
  onCancelRename?: () => void;
  onCommitRename?: (sessionId: string, title: string) => void;
  onOpenContextMenu: (session: SessionInfo, event: MouseEvent<HTMLElement>) => void;
  onOpenSession: (session: SessionInfo) => void;
  onTogglePinned: (sessionId: string) => void;
  pinned: boolean;
  session: SessionInfo;
  unread: boolean;
  displayTitle?: string;
}) {
  const route = sessionRoute(session, embeddedChat);
  const location = useLocation();
  const renameRef = useRef<HTMLInputElement>(null);
  const active =
    embeddedChat &&
    location.pathname === "/chat" &&
    new URLSearchParams(location.search).get("resume") === session.id;
  const title = displayTitle ?? sessionTitle(session);

  useEffect(() => {
    if (isRenaming) renameRef.current?.focus();
  }, [isRenaming]);

  if (isRenaming) {
    return (
      <div className={cn(
        "group relative flex min-h-11 items-center rounded-lg lg:min-h-[34px] lg:rounded-md",
        "bg-[var(--sidebar-row-active)]",
      )}>
        <input
          ref={renameRef}
          defaultValue={title}
          className="min-w-0 flex-1 rounded-md bg-transparent px-2.5 py-2 text-[0.9rem] font-medium leading-5 text-[var(--sidebar-text-active)] outline-none ring-1 ring-[var(--color-primary)] lg:px-2 lg:py-1"
          onBlur={(event) => onCommitRename?.(session.id, event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") { event.preventDefault(); onCommitRename?.(session.id, event.currentTarget.value); }
            if (event.key === "Escape") { event.preventDefault(); onCancelRename?.(); }
          }}
        />
      </div>
    );
  }

  return (
    <div
      onContextMenu={(event) => onOpenContextMenu(session, event)}
      className={cn(
        "group relative flex min-h-11 items-center rounded-lg lg:min-h-[34px] lg:rounded-md",
        "transition-colors duration-150",
        active
          ? "bg-[var(--sidebar-row-active)] text-[var(--sidebar-text-active)]"
          : "text-[var(--sidebar-text)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text-active)]",
      )}
    >
      <NavLink
        to={route}
        onClick={(event) => {
          event.preventDefault();
          onOpenSession(session);
        }}
        className="flex min-w-0 flex-1 self-stretch items-center gap-2 rounded-lg px-2.5 py-2 pr-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground lg:gap-1.5 lg:px-2 lg:py-1 lg:group-hover:pr-16 lg:group-focus-within:pr-16"
      >
        {session.is_active ? (
          <Loader2
            aria-label="Running"
            className="h-3.5 w-3.5 shrink-0 animate-spin text-primary lg:h-3 lg:w-3"
          />
        ) : (
          <SessionStatusDot
            lastActive={session.last_active}
            unread={unread}
          />
        )}
        <span className="min-w-0 flex-1 truncate text-[0.9rem] font-medium leading-5 lg:text-[0.9rem] lg:leading-5">
          {title}
        </span>
        <span className="ml-auto shrink-0 text-[0.75rem] leading-none text-[var(--sidebar-text-muted)] tabular-nums lg:text-[0.82rem] lg:transition-opacity lg:duration-100 lg:group-hover:opacity-0 lg:group-focus-within:opacity-0">
          <span className="tabular-nums">{compactSessionAge(session.last_active)}</span>
        </span>
        <span className="sr-only">
          {title} · {session.is_active ? "running, " : ""}
          {session.source ?? "local"} {timeAgo(session.last_active)}
        </span>
      </NavLink>
      <div className="pointer-events-none absolute right-1 top-1/2 hidden -translate-y-1/2 items-center rounded-md bg-[var(--sidebar-row-hover)] opacity-0 shadow-[0_0_0_1px_var(--sidebar-border)] transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100 lg:flex">
        <button
          type="button"
          aria-label={pinned ? "Unpin chat" : "Pin chat"}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onTogglePinned(session.id);
          }}
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors",
            pinned
              ? "text-primary"
              : "text-[var(--sidebar-icon-muted)] hover:text-[var(--sidebar-icon)]",
          )}
        >
          <Pin className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Open chat menu"
          title="Open chat menu"
          onClick={(event) => onOpenContextMenu(session, event)}
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
            "text-[var(--sidebar-icon-muted)] transition-colors",
            "hover:text-[var(--sidebar-icon)]",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
          )}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>
      <button
        type="button"
        aria-label={pinned ? "Unpin chat" : "Pin chat"}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onTogglePinned(session.id);
        }}
        className={cn(
          "flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors lg:hidden",
          pinned
            ? "text-primary"
            : "text-[var(--sidebar-icon-muted)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-icon)]",
        )}
      >
        <Pin className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        aria-label="Open chat menu"
        title="Open chat menu"
        onClick={(event) => onOpenContextMenu(session, event)}
        className={cn(
          "mr-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-md lg:hidden",
          "text-[var(--sidebar-icon-muted)] transition-colors",
          "hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-icon)]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
        )}
      >
        <MoreHorizontal className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function formatNextRun(iso?: string | null): string {
  if (!iso) return "—";
  const target = new Date(iso).getTime();
  const delta = target - Date.now();
  if (Number.isNaN(target)) return "—";
  if (delta < 0) return "due";
  const minutes = Math.round(delta / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}

function AutomationsSection({
  jobs,
  open,
  onToggle,
  onOpenCron,
  onOpenSession,
  liveJobIds,
  sessionsByJobId,
}: {
  jobs: CronJob[];
  open: boolean;
  onToggle: () => void;
  onOpenCron: (jobId: string) => void;
  onOpenSession: (session: SessionInfo) => void;
  liveJobIds: Set<string>;
  sessionsByJobId: Map<string, SessionInfo[]>;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (jobs.length === 0) return null;
  const visible = jobs.slice(0, 24);
  const liveCount = jobs.filter(
    (job) => job.state === "enabled" || job.state === "scheduled",
  ).length;
  const runningCount = liveJobIds.size;
  const toggleExpand = (jobId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };
  return (
    <div className="mt-3 lg:mt-2.5">
      <SidebarSectionLabel collapsed={!open} onToggle={onToggle}>
        <span className="flex w-full items-center gap-1.5">
          <span>Automations</span>
          <span className="font-normal normal-case tracking-normal text-[var(--sidebar-text-muted)]/80 tabular-nums">
            {jobs.length}
          </span>
          {liveCount > 0 && (
            <span className="ml-auto flex items-center gap-1 normal-case tracking-normal text-[var(--sidebar-text-muted)]">
              {runningCount > 0 ? (
                <span className="relative flex h-2 w-2 items-center justify-center">
                  <span className="absolute h-2 w-2 animate-ping rounded-full bg-success/60" />
                  <span className="relative h-1.5 w-1.5 rounded-full bg-success" />
                </span>
              ) : (
                <Clock className="h-3 w-3" />
              )}
              {runningCount > 0 ? `${runningCount} running` : `${liveCount} live`}
            </span>
          )}
        </span>
      </SidebarSectionLabel>
      {open && (
        <div className="mt-1 space-y-0.5 lg:mt-0.5">
          {visible.map((job) => {
            const title =
              (job.name && job.name.trim()) ||
              job.prompt.slice(0, 48).trim() ||
              job.id;
            const paused = job.state === "paused";
            const errored = job.state === "error" || !!job.last_error;
            const running = liveJobIds.has(job.id);
            const runs = sessionsByJobId.get(job.id) ?? [];
            const isExpanded = expanded.has(job.id);
            const recentRuns = runs.slice(0, 8);
            return (
              <div key={job.id}>
              <div className="group/row flex min-h-11 w-full items-center lg:min-h-[34px]">
              <button
                type="button"
                onClick={() => onOpenCron(job.id)}
                className={cn(
                  "group flex min-h-11 flex-1 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors lg:min-h-[34px] lg:gap-1.5 lg:rounded-md lg:px-2 lg:py-1",
                  "text-[var(--sidebar-text)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text-active)]",
                )}
                title={`${title} · ${job.schedule_display}${running ? " · running now" : ""}${job.last_error ? ` · ${job.last_error}` : ""}`}
              >
                {running ? (
                  <span className="relative flex h-3 w-3 shrink-0 items-center justify-center">
                    <span className="absolute h-2.5 w-2.5 animate-ping rounded-full bg-success/60" />
                    <span className="relative h-1.5 w-1.5 rounded-full bg-success" />
                  </span>
                ) : errored ? (
                  <AlertTriangle className="h-3 w-3 shrink-0 text-destructive" />
                ) : paused ? (
                  <Pause className="h-3 w-3 shrink-0 text-warning" />
                ) : (
                  <Clock className="h-3 w-3 shrink-0 text-[var(--sidebar-icon-muted)]" />
                )}
                <span className="min-w-0 flex-1 truncate text-[0.9rem] font-medium leading-5 lg:text-[0.9rem] lg:leading-5">
                  {title}
                </span>
                <span
                  className={cn(
                    "ml-auto shrink-0 text-[0.75rem] leading-none tabular-nums lg:text-[0.82rem]",
                    running ? "text-success" : "text-[var(--sidebar-text-muted)]",
                  )}
                >
                  {running ? "live" : paused ? "paused" : formatNextRun(job.next_run_at)}
                </span>
              </button>
              {runs.length > 0 && (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleExpand(job.id);
                  }}
                  className={cn(
                    "ml-0.5 flex h-7 w-6 shrink-0 items-center justify-center rounded-md text-[var(--sidebar-text-muted)] transition-colors",
                    "hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text-active)]",
                  )}
                  title={`${runs.length} run${runs.length === 1 ? "" : "s"}`}
                  aria-label={isExpanded ? "Collapse run history" : "Expand run history"}
                  aria-expanded={isExpanded}
                >
                  <ChevronRight
                    className={cn(
                      "h-3.5 w-3.5 transition-transform",
                      isExpanded && "rotate-90",
                    )}
                  />
                </button>
              )}
              </div>
              {isExpanded && recentRuns.length > 0 && (
                <div className="ml-3.5 mt-0.5 mb-1 space-y-0.5 border-l border-[var(--sidebar-border)]/60 pl-1.5 lg:mt-0.5 lg:space-y-0">
                  {recentRuns.map((session) => {
                    const runLabel =
                      session.preview?.trim() ||
                      (session.title && session.title.trim() !== "Untitled"
                        ? session.title.trim()
                        : "") ||
                      `Run · ${new Date((session.last_active ?? 0) * 1000).toLocaleString()}`;
                    return (
                    <button
                      key={session.id}
                      type="button"
                      onClick={() => onOpenSession(session)}
                      className={cn(
                        "flex min-h-11 w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors lg:min-h-[34px] lg:gap-1.5 lg:rounded-md lg:px-2 lg:py-1",
                        "text-[var(--sidebar-text)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text-active)]",
                      )}
                      title={`${runLabel} · ${new Date((session.last_active ?? 0) * 1000).toLocaleString()}`}
                    >
                      <span className="min-w-0 flex-1 truncate text-[0.9rem] font-medium leading-5 lg:text-[0.9rem] lg:leading-5">
                        {runLabel}
                      </span>
                      <span className="ml-auto shrink-0 text-[0.75rem] leading-none text-[var(--sidebar-text-muted)] tabular-nums lg:text-[0.82rem]">
                        {compactSessionAge(session.last_active ?? 0)}
                      </span>
                    </button>
                    );
                  })}
                </div>
              )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SessionContextMenu({
  menu,
  pinned,
  unread,
  onArchive,
  onClose,
  onCopyDeeplink,
  onCopySessionId,
  onCopyWorkingDirectory,
  onOpenFinder,
  onOpenMiniWindow,
  onRename,
  onTogglePinned,
  onToggleUnread,
}: {
  menu: SessionMenuState;
  pinned: boolean;
  unread: boolean;
  onArchive: (session: SessionInfo) => void;
  onClose: () => void;
  onCopyDeeplink: (session: SessionInfo) => void;
  onCopySessionId: (session: SessionInfo) => void;
  onCopyWorkingDirectory: () => void;
  onOpenFinder: (session: SessionInfo) => void;
  onOpenMiniWindow: (session: SessionInfo) => void;
  onRename: (session: SessionInfo) => void;
  onTogglePinned: (session: SessionInfo) => void;
  onToggleUnread: (session: SessionInfo) => void;
}) {
  const menuWidth = 264;
  const menuHeight = 374;
  const left =
    typeof window === "undefined"
      ? menu.x
      : Math.min(menu.x, Math.max(8, window.innerWidth - menuWidth - 8));
  const top =
    typeof window === "undefined"
      ? menu.y
      : Math.min(menu.y, Math.max(8, window.innerHeight - menuHeight - 8));

  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    menuRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = (action: () => void) => {
    action();
    onClose();
  };

  return createPortal(
    <>
      <div
        className="fixed inset-0 z-[99]"
        onClick={onClose}
        onContextMenu={(event) => { event.preventDefault(); onClose(); }}
      />
      <div
        ref={menuRef}
        role="menu"
        aria-label={`Options for ${sessionTitle(menu.session)}`}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onContextMenu={(event) => event.preventDefault()}
        style={{ left, top }}
        className={cn(
          "fixed z-[100] w-[16.5rem] rounded-lg p-1.5 outline-none",
          "border border-border bg-card text-midground shadow-[0_8px_24px_rgba(0,0,0,0.18)]",
        )}
      >
      <SessionMenuButton
        icon={Pin}
        label={pinned ? "Unpin chat" : "Pin chat"}
        onClick={() => run(() => onTogglePinned(menu.session))}
      />
      <SessionMenuButton
        icon={Pencil}
        label="Rename chat"
        onClick={() => run(() => onRename(menu.session))}
      />
      <SessionMenuButton
        icon={Archive}
        label="Archive chat"
        destructive
        onClick={() => run(() => onArchive(menu.session))}
      />
      <SessionMenuButton
        icon={MailOpen}
        label={unread ? "Mark as read" : "Mark as unread"}
        onClick={() => run(() => onToggleUnread(menu.session))}
      />
      <SessionMenuSeparator />
      <SessionMenuButton
        icon={FolderOpen}
        label="Open in Finder"
        onClick={() => run(() => onOpenFinder(menu.session))}
      />
      <SessionMenuButton
        icon={Copy}
        label="Copy working directory"
        onClick={() => run(onCopyWorkingDirectory)}
      />
      <SessionMenuButton
        icon={Copy}
        label="Copy session ID"
        onClick={() => run(() => onCopySessionId(menu.session))}
      />
      <SessionMenuButton
        icon={ExternalLink}
        label="Copy deeplink"
        onClick={() => run(() => onCopyDeeplink(menu.session))}
      />
      <SessionMenuSeparator />
      <SessionMenuButton
        icon={Maximize2}
        label="Open in mini window"
        onClick={() => run(() => onOpenMiniWindow(menu.session))}
      />
    </div>
    </>,
    document.body,
  );
}

function SessionMenuSeparator() {
  return (
    <div className="my-1 h-px bg-[color-mix(in_srgb,var(--midground-base)_12%,transparent)]" />
  );
}

function SessionMenuButton({
  destructive = false,
  icon: Icon,
  label,
  onClick,
}: {
  destructive?: boolean;
  icon: ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className={cn(
        "flex min-h-9 w-full items-center gap-3 rounded-xl px-3 text-left text-[0.9rem] font-semibold leading-none",
        "transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
        destructive
          ? "text-destructive hover:bg-destructive/10"
          : "text-midground hover:bg-accent/80",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 opacity-75" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function SidebarSystemActions({ onNavigate }: { onNavigate: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeAction, isBusy, isRunning, pendingAction, runAction, updateStatus } =
    useSystemActions();
  const updateBehind = updateStatus?.available ? updateStatus.behind : null;

  const items: SystemActionItem[] = [
    {
      action: "restart",
      icon: RotateCw,
      label: t.status.restartGateway,
      runningLabel: t.status.restartingGateway,
      spin: true,
    },
    {
      action: "update",
      icon: Download,
      label: updateStatus?.available ? t.status.updatesAvailable : t.status.updateElevate,
      runningLabel: t.status.updatingElevate,
      spin: false,
    },
  ];

  const handleClick = (action: SystemAction) => {
    if (isBusy) return;
    void runAction(action);
    navigate("/tasks");
    onNavigate();
  };

  return (
    <div
      className={cn(
        "shrink-0 flex flex-col px-2 py-2 lg:py-1.5",
      )}
    >
      <span
        className={cn(
          "px-2.5 pt-0.5 pb-1 lg:px-2 lg:pb-0.5",
          "text-[0.72rem] font-semibold tracking-normal text-[var(--sidebar-text-muted)]",
        )}
      >
        {t.app.system}
      </span>

      <SidebarStatusStrip />

      <ul className="flex flex-col">
        {items.map(({ action, icon: Icon, label, runningLabel, spin }) => {
          const isPending = pendingAction === action;
          const isActionRunning =
            activeAction === action && isRunning && !isPending;
          const busy = isPending || isActionRunning;
          const displayLabel = isActionRunning ? runningLabel : label;
          const disabled = isBusy && !busy;

          return (
            <li key={action}>
              <button
                type="button"
                onClick={() => handleClick(action)}
                disabled={disabled}
                aria-busy={busy}
                className={cn(
                  "group relative flex w-full items-center gap-3 lg:gap-2",
                  "min-h-11 rounded-lg px-2.5 py-2 lg:min-h-8 lg:rounded-md lg:px-2 lg:py-1",
                  "text-[0.92rem] font-medium tracking-normal lg:text-[0.9rem]",
                  "text-left whitespace-nowrap transition-colors cursor-pointer",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
                  busy
                    ? "bg-[var(--sidebar-row-active)] text-[var(--sidebar-text-active)]"
                    : "text-[var(--sidebar-text)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--sidebar-text-active)]",
                  "disabled:cursor-not-allowed disabled:opacity-30",
                )}
              >
                {isPending ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[var(--sidebar-icon)]" />
                ) : (
                  <Icon
                    className={cn(
                      "h-[17px] w-[17px] shrink-0 text-[var(--sidebar-icon)] lg:h-4 lg:w-4",
                      isActionRunning && spin && "animate-spin",
                      isActionRunning && !spin && "animate-pulse",
                    )}
                  />
                )}

                <span className="truncate">{displayLabel}</span>

                {action === "update" && updateBehind && updateBehind > 0 && !busy && (
                  <span
                    aria-label={`${updateBehind} update commits available`}
                    className="ml-auto rounded-full bg-warning/15 px-1.5 py-0.5 text-[0.68rem] font-semibold leading-none text-warning"
                  >
                    {updateBehind}
                  </span>
                )}

                {busy && (
                  <span
                    aria-hidden
                    className="ml-auto h-1.5 w-1.5 rounded-full bg-success"
                  />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
}

interface SystemActionItem {
  action: SystemAction;
  icon: ComponentType<{ className?: string }>;
  label: string;
  runningLabel: string;
  spin: boolean;
}
