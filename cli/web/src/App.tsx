import {
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
  Brain,
  BriefcaseBusiness,
  Building2,
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
import { api, type SessionInfo } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Backdrop } from "@/components/Backdrop";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { SidebarFooter } from "@/components/SidebarFooter";
import { SidebarStatusStrip } from "@/components/SidebarStatusStrip";
import { Toast } from "@/components/Toast";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { useSystemActions } from "@/contexts/useSystemActions";
import type { SystemAction } from "@/contexts/system-actions-context";
import ConfigPage from "@/pages/ConfigPage";
import DocsPage from "@/pages/DocsPage";
import EnvPage from "@/pages/EnvPage";
import SessionsPage from "@/pages/SessionsPage";
import LogsPage from "@/pages/LogsPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import CronPage from "@/pages/CronPage";
import SkillsPage from "@/pages/SkillsPage";
import ChatPage from "@/pages/ChatPage";
import AgentHubPage from "@/pages/AgentHubPage";
import ProjectPage from "@/pages/ProjectPage";
import {
  RealEstateAdsPage,
  RealEstateDealsPage,
  RealEstateApprovalsPage,
  RealEstateLeadsPage,
  RealEstateListingsPage,
  RealEstateMemoryPage,
  RealEstateSocialMediaPage,
  RealEstateTasksPage,
  RealEstateTodayPage,
} from "@/pages/RealEstateHubPages";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
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

function MarketingRedirect() {
  return <Navigate to="/ads" replace />;
}

const CHAT_NAV_ITEM: NavItem = {
  path: "/chat",
  labelKey: "chat",
  label: "Chat",
  icon: MessageSquare,
};

/** Built-in routes except /chat (only with `elevate dashboard --tui`). */
const BUILTIN_ROUTES_CORE: Record<string, ComponentType> = {
  "/": RootRedirect,
  "/today": RealEstateTodayPage,
  "/leads": RealEstateLeadsPage,
  "/listings": RealEstateListingsPage,
  "/deals": RealEstateDealsPage,
  "/ads": RealEstateAdsPage,
  "/social-media": RealEstateSocialMediaPage,
  "/marketing": MarketingRedirect,
  "/tasks": RealEstateTasksPage,
  "/approvals": RealEstateApprovalsPage,
  "/memory": RealEstateMemoryPage,
  "/hub": AgentHubPage,
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
    path: "/today",
    label: "Today",
    icon: Home,
  },
  {
    path: "/leads",
    label: "Leads",
    icon: Users,
  },
  {
    path: "/listings",
    label: "Listings",
    icon: Building2,
  },
  {
    path: "/deals",
    label: "Deals",
    icon: BriefcaseBusiness,
  },
  {
    path: "/ads",
    label: "Ads",
    icon: BarChart3,
  },
  {
    path: "/social-media",
    label: "Social Media",
    icon: Megaphone,
  },
  {
    path: "/tasks",
    label: "Tasks",
    icon: ListChecks,
  },
  {
    path: "/approvals",
    label: "Approvals",
    icon: ShieldCheck,
  },
  {
    path: "/memory",
    label: "Memory",
    icon: Brain,
  },
  {
    path: "/hub",
    label: "Agent Hub",
    icon: Bot,
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

export default function App() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { manifests } = usePlugins();
  const { theme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const isDocsRoute = pathname === "/docs" || pathname === "/docs/";
  const normalizedPath = pathname.replace(/\/$/, "") || "/";
  const isChatRoute = normalizedPath === "/chat";
  const embeddedChat = isDashboardEmbeddedChatEnabled();

  const builtinRoutes = useMemo(
    () => ({
      ...BUILTIN_ROUTES_CORE,
      ...(embeddedChat ? { "/chat": ChatPage } : {}),
    }),
    [embeddedChat],
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
          "bg-background-base/92 shadow-[0_1px_0_color-mix(in_srgb,var(--midground-base)_7%,transparent)] backdrop-blur-sm",
        )}
      >
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label={t.app.openNavigation}
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center",
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
            "bg-black/60 backdrop-blur-sm cursor-pointer",
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
              "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-[19rem] max-w-[calc(100vw-1.5rem)] min-h-0 flex-col",
              "bg-[var(--sidebar-bg)] shadow-[inset_-1px_0_0_var(--sidebar-border)] backdrop-blur-sm",
              "transition-transform duration-200 ease-out",
              mobileOpen ? "translate-x-0" : "-translate-x-full",
              "lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0",
            )}
          >
            <DesktopSidebar
              embeddedChat={embeddedChat}
              navItems={navItems}
              onNavigate={closeMobile}
            />
          </aside>

          <PageHeaderProvider pluginTabs={pluginTabMeta}>
            <div
              className={cn(
                "relative z-2 flex min-w-0 min-h-0 flex-1 flex-col",
                "px-3 sm:px-6",
                isChatRoute
                  ? "pb-3 pt-1 sm:pb-4 sm:pt-2 lg:pt-4"
                  : "pt-2 sm:pt-4 lg:pt-6 pb-4 sm:pb-8",
                isDocsRoute && "min-h-0 flex-1",
              )}
            >
              <PluginSlot name="pre-main" />
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute && "elevate-page-shell",
                  isDocsRoute && "elevate-docs-shell",
                  (isDocsRoute || isChatRoute) && "min-h-0 flex flex-1 flex-col",
                )}
              >
                <Routes>
                  {routes.map(({ key, path, element }) => (
                    <Route key={key} path={path} element={element} />
                  ))}
                  <Route path="*" element={<Navigate to="/today" replace />} />
                </Routes>
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

function sessionRoute(session: SessionInfo, embeddedChat: boolean): string {
  if (!embeddedChat) return "/sessions";
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
}: {
  embeddedChat: boolean;
  navItems: NavItem[];
  onNavigate: () => void;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionError, setSessionError] = useState(false);
  const [query, setQuery] = useState("");
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => readPinnedSessionIds());
  const [unreadIds, setUnreadIds] = useState<string[]>(() => readUnreadSessionIds());
  const [archivedIds, setArchivedIds] = useState<string[]>(() =>
    readArchivedSessionIds(),
  );
  const [sessionMenu, setSessionMenu] = useState<SessionMenuState | null>(null);
  const { isBusy, pendingAction, runAction } = useSystemActions();
  const { toast, showToast } = useToast();

  const loadSessions = useCallback(() => {
    api
      .getSessions(SIDEBAR_SESSION_LIMIT)
      .then((resp) => {
        setSessions(resp.sessions);
        setSessionError(false);
      })
      .catch(() => setSessionError(true))
      .finally(() => setSessionsLoading(false));
  }, []);

  useEffect(() => {
    loadSessions();
    const id = window.setInterval(loadSessions, 5000);
    return () => window.clearInterval(id);
  }, [loadSessions]);

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

  const pinnedSessions = filteredSessions.filter((session) =>
    pinnedIds.includes(session.id),
  );
  const liveSessions = filteredSessions.filter((session) => session.is_active);
  const spotlightSessions = (pinnedSessions.length ? pinnedSessions : liveSessions)
    .slice(0, 4);
  const spotlightIds = new Set(spotlightSessions.map((session) => session.id));
  const recentSessions = filteredSessions
    .filter((session) => !spotlightIds.has(session.id))
    .slice(0, 18);

  const systemPaths = new Set(["/analytics", "/logs", "/env", "/docs"]);
  const toolNavItems = navItems.filter((item) => systemPaths.has(item.path));

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

  const focusSearch = () => {
    searchRef.current?.focus();
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
    async (session: SessionInfo) => {
      setSessionMenu(null);
      const currentTitle = sessionTitle(session);
      const title = window.prompt("Rename chat", currentTitle);
      if (title === null) return;
      try {
        const response = await api.renameSession(session.id, title.trim() || null);
        setSessions((prev) =>
          prev.map((item) =>
            item.id === session.id ? { ...item, title: response.title } : item,
          ),
        );
        showToast("Session renamed", "success");
      } catch (error) {
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
    <div className="normal-case flex min-h-0 flex-1 flex-col font-sans text-[13px] tracking-normal text-midground">
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
      <div className="flex h-[54px] shrink-0 items-center justify-between gap-3 px-3.5">
        <div className="flex items-center gap-2.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#ffbd2e]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
        </div>

        <div className="flex min-w-0 flex-1 justify-center">
          <div className="flex h-8 min-w-0 items-center rounded-xl bg-[#f7f7f7] px-2 shadow-[0_0_0_1px_rgba(27,42,74,0.12),0_10px_26px_rgba(0,0,0,0.16)]">
            <img
              src="/elevate-agent-wordmark.svg"
              alt="Elevate Agent"
              className="h-7 max-w-[8.7rem] object-contain"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => void runAction("update")}
          disabled={isBusy}
          className={cn(
            "hidden shrink-0 items-center rounded-full px-3 py-1.5 text-xs font-semibold",
            "bg-primary text-primary-foreground transition-opacity hover:opacity-90",
            "disabled:cursor-not-allowed disabled:opacity-50 sm:inline-flex",
          )}
        >
          {pendingAction === "update" ? "Updating" : "Update"}
        </button>

        <button
          type="button"
          onClick={onNavigate}
          aria-label={t.app.closeNavigation}
          className={cn(
            "lg:hidden inline-flex h-8 w-8 shrink-0 items-center justify-center",
            "rounded-lg text-muted-foreground hover:bg-accent hover:text-midground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          )}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <PluginSlot name="header-left" />

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-2.5 py-2.5">
        <div className="space-y-0.5">
          <button
            type="button"
            onClick={startNewChat}
            className={sidebarActionClass(false, true)}
          >
            <Plus className="h-[15px] w-[15px] shrink-0" />
            <span className="truncate">New chat</span>
          </button>
          <button
            type="button"
            onClick={focusSearch}
            className={sidebarActionClass(false)}
          >
            <Search className="h-[15px] w-[15px] shrink-0" />
            <span className="truncate">Search</span>
            <span className="ml-auto rounded-md bg-card/70 px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground">
              /
            </span>
          </button>
        </div>

        <div className="mt-3">
          <SidebarSectionLabel>Real Estate</SidebarSectionLabel>
          <div className="space-y-0.5">
            <SidebarAction icon={Home} label="Today" path="/today" onNavigate={go} />
            <SidebarAction icon={Users} label="Leads" path="/leads" onNavigate={go} />
            <SidebarAction icon={Building2} label="Listings" path="/listings" onNavigate={go} />
            <SidebarAction icon={BriefcaseBusiness} label="Deals" path="/deals" onNavigate={go} />
            <SidebarAction icon={BarChart3} label="Ads" path="/ads" onNavigate={go} />
            <SidebarAction icon={Megaphone} label="Social Media" path="/social-media" onNavigate={go} />
            <SidebarAction icon={ListChecks} label="Tasks" path="/tasks" onNavigate={go} />
            <SidebarAction icon={ShieldCheck} label="Approvals" path="/approvals" onNavigate={go} />
            <SidebarAction icon={Brain} label="Memory" path="/memory" onNavigate={go} />
          </div>
        </div>

        <div className="mt-3">
          <SidebarSectionLabel>Agent</SidebarSectionLabel>
          <div className="space-y-0.5">
            <SidebarAction icon={Bot} label="Agent Hub" path="/hub" onNavigate={go} />
            <SidebarAction icon={Puzzle} label="Skills" path="/skills" onNavigate={go} />
            <SidebarAction icon={Clock} label="Automations" path="/cron" onNavigate={go} />
            <SidebarAction icon={Folder} label="Project" path="/project" onNavigate={go} />
          </div>
        </div>

        <div className="relative mt-2.5">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search chats"
            className={cn(
              "h-8 w-full rounded-lg bg-[var(--sidebar-row)] shadow-[inset_0_0_0_1px_var(--sidebar-border)]",
              "pl-8 pr-8 text-[0.8rem] text-midground placeholder:text-muted-foreground",
              "outline-none transition-colors focus:bg-[var(--chat-surface-strong)] focus:shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_34%,transparent),0_0_0_3px_color-mix(in_srgb,var(--color-primary)_10%,transparent)]",
            )}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label={t.common.clear}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-midground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {spotlightSessions.length > 0 && (
          <SessionSection
            embeddedChat={embeddedChat}
            label="Pinned"
            onOpenContextMenu={openSessionMenu}
            onOpenSession={openSession}
            onTogglePinned={togglePinned}
            pinnedIds={pinnedIds}
            sessions={spotlightSessions}
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
          sessions={recentSessions}
          unreadIds={unreadIds}
          statusText={
            sessionError
              ? "Sessions unavailable"
              : !sessionsLoading && recentSessions.length === 0
                ? "No chats yet"
                : undefined
          }
        />

        {toolNavItems.length > 0 && (
          <div className="mt-4">
            <SidebarSectionLabel>Tools</SidebarSectionLabel>
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
          </div>
        )}
      </div>

      <SidebarSystemActions onNavigate={onNavigate} />

      <div className="shrink-0 px-2 pb-2">
        <button
          type="button"
          onClick={() => go("/config")}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[0.84rem]",
            "text-muted-foreground transition-colors hover:bg-accent hover:text-midground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          )}
        >
          <Settings className="h-[15px] w-[15px] shrink-0" />
          <span className="truncate">Settings</span>
        </button>

        <div className="flex items-center justify-between gap-2 px-1 py-1.5">
          <div className="flex min-w-0 items-center gap-2">
            <PluginSlot name="header-right" />
            <ThemeSwitcher dropUp />
            <LanguageSwitcher />
          </div>
        </div>

        <SidebarFooter />
      </div>
    </div>
  );
}

function SidebarSectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-1 px-2 text-[0.64rem] font-semibold normal-case text-muted-foreground">
      {children}
    </div>
  );
}

function sidebarActionClass(active: boolean, primary = false) {
  return cn(
    "group flex min-h-7 w-full items-center gap-2 rounded-lg px-2.5 py-1 text-left text-[0.8rem]",
    "cursor-pointer transition-all duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
    primary && "font-semibold",
    active
      ? "bg-[var(--sidebar-row-active)] text-midground"
      : "text-muted-foreground hover:bg-[var(--sidebar-row-hover)] hover:text-midground",
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
      className={({ isActive }) => sidebarActionClass(isActive, primary)}
    >
      <Icon className="h-[15px] w-[15px] shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  );
}

function SessionSection({
  embeddedChat,
  label,
  loading = false,
  onOpenContextMenu,
  onOpenSession,
  onTogglePinned,
  pinnedIds,
  sessions,
  statusText,
  unreadIds,
}: {
  embeddedChat: boolean;
  label: string;
  loading?: boolean;
  onOpenContextMenu: (session: SessionInfo, event: MouseEvent<HTMLElement>) => void;
  onOpenSession: (session: SessionInfo) => void;
  onTogglePinned: (sessionId: string) => void;
  pinnedIds: string[];
  sessions: SessionInfo[];
  statusText?: string;
  unreadIds: string[];
}) {
  return (
    <div className="mt-3">
      <SidebarSectionLabel>{label}</SidebarSectionLabel>
      <div className="space-y-0.5">
        {sessions.map((session) => (
          <SessionListItem
            key={session.id}
            embeddedChat={embeddedChat}
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
        <div className="px-2.5 py-1 text-[0.72rem] text-muted-foreground">
          {loading ? "Loading chats" : statusText}
        </div>
      )}
    </div>
  );
}

function SessionListItem({
  embeddedChat,
  onOpenContextMenu,
  onOpenSession,
  onTogglePinned,
  pinned,
  session,
  unread,
}: {
  embeddedChat: boolean;
  onOpenContextMenu: (session: SessionInfo, event: MouseEvent<HTMLElement>) => void;
  onOpenSession: (session: SessionInfo) => void;
  onTogglePinned: (sessionId: string) => void;
  pinned: boolean;
  session: SessionInfo;
  unread: boolean;
}) {
  const route = sessionRoute(session, embeddedChat);
  const location = useLocation();
  const active =
    embeddedChat &&
    location.pathname === "/chat" &&
    new URLSearchParams(location.search).get("resume") === session.id;
  return (
    <NavLink
      to={route}
      onClick={(event) => {
        event.preventDefault();
        onOpenSession(session);
      }}
      onContextMenu={(event) => onOpenContextMenu(session, event)}
      className={cn(
        "group relative flex min-h-7 items-center gap-2 rounded-lg px-2.5 py-1",
        "text-left transition-all duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
        active
          ? "bg-[var(--sidebar-row-active)] text-midground"
          : "text-muted-foreground hover:bg-[var(--sidebar-row-hover)] hover:text-midground",
      )}
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          unread
            ? "bg-primary shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-primary)_14%,transparent)]"
            : session.is_active
              ? "bg-success"
              : "bg-current/30",
        )}
      />
      <span className="min-w-0 flex-1 truncate text-[0.8rem] font-medium leading-4">
        {sessionTitle(session)}
      </span>
      <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[0.66rem] leading-none text-muted-foreground">
        {session.source && session.source !== "local" && (
          <span className="max-w-[3.25rem] truncate">{session.source}</span>
        )}
        <span className="tabular-nums">{compactSessionAge(session.last_active)}</span>
      </span>
      <button
        type="button"
        aria-label={pinned ? "Unpin chat" : "Pin chat"}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onTogglePinned(session.id);
        }}
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-colors",
          pinned
            ? "text-primary"
            : "text-muted-foreground/45 hover:bg-[var(--sidebar-row-hover)] hover:text-midground",
        )}
      >
        <Pin
          className={cn(
            "h-3 w-3 transition-opacity",
            pinned ? "opacity-100" : "opacity-45 group-hover:opacity-100",
          )}
        />
      </button>
      <button
        type="button"
        aria-label="Open chat menu"
        title="Open chat menu"
        onClick={(event) => onOpenContextMenu(session, event)}
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md",
          "text-muted-foreground/45 opacity-55 transition-all",
          "hover:bg-[var(--sidebar-row-hover)] hover:text-midground",
          "group-hover:opacity-100 focus-visible:opacity-100",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
        )}
      >
        <MoreHorizontal className="h-3 w-3" />
      </button>
      <span className="sr-only">
        {session.source ?? "local"} {timeAgo(session.last_active)}
      </span>
    </NavLink>
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

  const run = (action: () => void) => {
    action();
    onClose();
  };

  return createPortal(
    <div
      role="menu"
      aria-label={`Options for ${sessionTitle(menu.session)}`}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      style={{ left, top }}
      className={cn(
        "fixed z-[100] w-[16.5rem] rounded-2xl p-1.5",
        "bg-card/98 text-midground shadow-[0_18px_54px_color-mix(in_srgb,var(--midground-base)_22%,transparent),0_0_0_1px_color-mix(in_srgb,var(--midground-base)_14%,transparent)] backdrop-blur-xl",
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
    </div>,
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
  const { activeAction, isBusy, isRunning, pendingAction, runAction } =
    useSystemActions();

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
      label: t.status.updateElevate,
      runningLabel: t.status.updatingElevate,
      spin: false,
    },
  ];

  const handleClick = (action: SystemAction) => {
    if (isBusy) return;
    void runAction(action);
    navigate("/sessions");
    onNavigate();
  };

  return (
    <div
      className={cn(
        "shrink-0 flex flex-col px-2 py-2",
      )}
    >
      <span
        className={cn(
          "px-2.5 pt-0.5 pb-1",
          "text-[0.68rem] font-semibold tracking-normal text-muted-foreground",
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
                  "group relative flex w-full items-center gap-3",
                  "rounded-lg px-2.5 py-1.5",
                  "text-[0.82rem] font-medium tracking-normal",
                  "text-left whitespace-nowrap transition-colors cursor-pointer",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
                  busy
                    ? "bg-accent/85 text-midground"
                    : "text-muted-foreground hover:bg-accent/55 hover:text-midground",
                  "disabled:cursor-not-allowed disabled:opacity-30",
                )}
              >
                {isPending ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                ) : (
                  <Icon
                    className={cn(
                      "h-[15px] w-[15px] shrink-0",
                      isActionRunning && spin && "animate-spin",
                      isActionRunning && !spin && "animate-pulse",
                    )}
                  />
                )}

                <span className="truncate">{displayLabel}</span>

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
