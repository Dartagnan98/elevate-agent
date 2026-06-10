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
  CheckCheck,
  FlaskConical,
  KanbanSquare,
  Folder,
  FolderOpen,
  Globe,
  Heart,
  Home,
  KeyRound,
  ListChecks,
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
  RefreshCw,
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
import { api, type CronJob, type SessionInfo, type UpdateStatusResponse } from "@/lib/api";
import type { AccessStatusResponse, LicenseStatusResponse } from "@/lib/api-types";
import { LoginCard } from "@/components/LoginCard";
import { cn, timeAgo } from "@/lib/utils";
import { Backdrop } from "@/components/Backdrop";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { SidebarUserPill } from "@/components/SidebarUserPill";
import { Toast } from "@/components/Toast";
import { RouteSkeleton } from "@/components/route-skeletons";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { useI18n } from "@/i18n";
import { PluginPage, PluginSlot, usePlugins } from "@/plugins";
import type { PluginManifest } from "@/plugins";
import { useTheme } from "@/themes";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { markStartup, reportStartup } from "@/lib/startup-performance";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { useToast } from "@/hooks/useToast";
import { useIconButtonTitles } from "@/hooks/useIconButtonTitles";
import { useSystemActions } from "@/contexts/useSystemActions";

const loadConfigPage = () => import("@/pages/ConfigPage");
const loadDocsPage = () => import("@/pages/DocsPage");
const loadEnvPage = () => import("@/pages/EnvPage");
const loadSessionsPage = () => import("@/pages/SessionsPage");
const loadLogsPage = () => import("@/pages/LogsPage");
const loadAnalyticsPage = () => import("@/pages/AnalyticsPage");
const loadCronPage = () => import("@/pages/CronPage");
const loadExperimentsPage = () => import("@/pages/ExperimentsPage");
const loadOverviewPage = () => import("@/pages/OverviewPage");
const loadCommsPage = () => import("@/pages/CommsPage");
const loadActivityPage2 = () => import("@/pages/ActivityPage");
const loadTasksPage = () => import("@/pages/TasksPage");
const loadApprovalsPage = () => import("@/pages/ApprovalsPage");
const loadSkillsPage = () => import("@/pages/SkillsPage");
const loadChatPage = () => import("@/pages/ChatPage");
const loadAgentHubPage = () => import("@/pages/AgentHubPage");
const loadDesktopSetupPage = () => import("@/pages/DesktopSetupPage");
const loadProjectPage = () => import("@/pages/ProjectPage");
const loadRealEstateAdminPage = () =>
  import("@/pages/real-estate-hub/admin").then((m) => ({ default: m.RealEstateAdminPage }));
const loadRealEstateTemplatesPage = () => import("@/pages/RealEstateTemplatesPage");
const loadRealEstateLeadsPage = () =>
  import("@/pages/RealEstateHubPages").then((m) => ({ default: m.RealEstateLeadsPage }));
const loadRealEstateMemoryPage = () =>
  import("@/pages/real-estate-hub/memory").then((m) => ({ default: m.RealEstateMemoryPage }));
const loadRealEstateSocialMediaPage = () =>
  import("@/pages/real-estate-hub/social").then((m) => ({ default: m.RealEstateSocialMediaPage }));
const loadRealEstateTodayPage = () =>
  import("@/pages/real-estate-hub/today").then((m) => ({ default: m.RealEstateTodayPage }));
const loadAgentOnboardingPage = () =>
  import("@/pages/agent-onboarding").then((m) => ({ default: m.AgentOnboardingPage }));

const ConfigPage = lazy(loadConfigPage);
const DocsPage = lazy(loadDocsPage);
const EnvPage = lazy(loadEnvPage);
const SessionsPage = lazy(loadSessionsPage);
const LogsPage = lazy(loadLogsPage);
const AnalyticsPage = lazy(loadAnalyticsPage);
const CronPage = lazy(loadCronPage);
const ExperimentsPage = lazy(loadExperimentsPage);
const OverviewPage = lazy(loadOverviewPage);
const CommsPage = lazy(loadCommsPage);
const ActivityFeedPage = lazy(loadActivityPage2);
const TasksPage = lazy(loadTasksPage);
const ApprovalsPage = lazy(loadApprovalsPage);
const SkillsPage = lazy(loadSkillsPage);
const ChatPage = lazy(loadChatPage);
const AgentHubPage = lazy(loadAgentHubPage);
const DesktopSetupPage = lazy(loadDesktopSetupPage);
const ProjectPage = lazy(loadProjectPage);
const RealEstateAdminPage = lazy(loadRealEstateAdminPage);
const RealEstateTemplatesPage = lazy(loadRealEstateTemplatesPage);
const RealEstateLeadsPage = lazy(loadRealEstateLeadsPage);
const RealEstateMemoryPage = lazy(loadRealEstateMemoryPage);
const RealEstateSocialMediaPage = lazy(loadRealEstateSocialMediaPage);
const RealEstateTodayPage = lazy(loadRealEstateTodayPage);
const AgentOnboardingPage = lazy(loadAgentOnboardingPage);

const ROUTE_PRELOADERS: Record<string, () => Promise<unknown>> = {
  "/today": loadRealEstateTodayPage,
  "/leads": loadRealEstateLeadsPage,
  "/admin": loadRealEstateAdminPage,
  "/admin/templates": loadRealEstateTemplatesPage,
  "/social-media": loadRealEstateSocialMediaPage,
  "/memory": loadRealEstateMemoryPage,
  "/hub": loadAgentHubPage,
  "/chat": loadChatPage,
  "/desktop-setup": loadDesktopSetupPage,
  "/agent-onboarding": loadAgentOnboardingPage,
  "/project": loadProjectPage,
  "/sessions": loadSessionsPage,
  "/analytics": loadAnalyticsPage,
  "/logs": loadLogsPage,
  "/cron": loadCronPage,
  "/heartbeat": loadCronPage,
  "/experiments": loadExperimentsPage,
  "/overview": loadOverviewPage,
  "/comms": loadCommsPage,
  "/activity": loadActivityPage2,
  "/tasks": loadTasksPage,
  "/approvals": loadApprovalsPage,
  "/skills": loadSkillsPage,
  "/config": loadConfigPage,
  "/env": loadEnvPage,
  "/docs": loadDocsPage,
};

const PRELOADED_ROUTES = new Set<string>();

function normalizePreloadPath(path: string): string {
  const base = path.split(/[?#]/)[0]?.replace(/\/$/, "") || "/";
  if (base === "/marketing") return "/social-media";
  if (base === "/listings" || base === "/deals") return "/admin";
  return base;
}

function preloadRealEstateRouteData(path: string): void {
  if (!["/", "/today", "/leads", "/admin", "/memory", "/social-media"].includes(path)) return;
  void import("@/pages/real-estate-hub/_shared/use-hub-data").then((module) => {
    void module.preloadRealEstateHubData(path);
  });
  if (path === "/leads") {
    void import("@/pages/real-estate-hub/leads/onboarding").then((module) => {
      void module.preloadLeadsSetup();
    });
  }
}

function preloadRoute(path: string): void {
  const key = normalizePreloadPath(path);
  const loader = ROUTE_PRELOADERS[key];
  if (!loader) {
    preloadRealEstateRouteData(key);
    return;
  }
  if (PRELOADED_ROUTES.has(key)) {
    preloadRealEstateRouteData(key);
    return;
  }
  PRELOADED_ROUTES.add(key);
  void loader()
    .then(() => preloadRealEstateRouteData(key))
    .catch(() => {
      PRELOADED_ROUTES.delete(key);
    });
}

function scheduleRouteWarmup(paths: string[]): () => void {
  let cancelled = false;
  const uniquePaths = Array.from(new Set(paths)).filter(Boolean);
  const timers: number[] = [];
  const start = window.setTimeout(() => {
    uniquePaths.forEach((path, index) => {
      const id = window.setTimeout(() => {
        if (!cancelled) preloadRoute(path);
      }, index * 250);
      timers.push(id);
    });
  }, 1500);
  timers.push(start);

  return () => {
    cancelled = true;
    timers.forEach((id) => window.clearTimeout(id));
  };
}

function RootRedirect() {
  // Start each launch on a fresh chat (mirrors the "New chat" button's
  // ?new=&seed= params) when embedded chat is available; else fall back to /today.
  const seed = useMemo(() => Date.now(), []);
  return (
    <Navigate
      to={isDashboardEmbeddedChatEnabled() ? `/chat?new=${seed}&seed=${seed}` : "/today"}
      replace
    />
  );
}

function CoreRootRedirect() {
  const seed = useMemo(() => Date.now(), []);
  return (
    <Navigate
      to={isDashboardEmbeddedChatEnabled() ? `/chat?new=${seed}&seed=${seed}` : "/hub"}
      replace
    />
  );
}

// Soft first-run gate. A customer whose agent setup isn't complete is routed to
// the onboarding wizard ONCE per app session when they land (desktop opens
// /hub directly, browser lands on /chat — this catches both since it lives in
// the authenticated shell, not the index route). It never traps them: they can
// navigate away freely, the sessionStorage flag stops it re-firing, and a
// returning/configured customer (setup complete) is never redirected. A failed
// status check is swallowed so the app is never blocked.
function OnboardingGate() {
  const navigate = useNavigate();
  const location = useLocation();
  const checkedRef = useRef(false);

  useEffect(() => {
    if (checkedRef.current) return;
    checkedRef.current = true;
    if (typeof window === "undefined") return;
    if (window.sessionStorage.getItem("elevate:onboarding-routed") === "1") return;
    // Already on onboarding (e.g. opened from the sidebar) — mark done, no nav.
    if (location.pathname.startsWith("/agent-onboarding")) {
      window.sessionStorage.setItem("elevate:onboarding-routed", "1");
      return;
    }
    let cancelled = false;
    api
      .getAgentSetup()
      .then((snap) => {
        if (cancelled) return;
        window.sessionStorage.setItem("elevate:onboarding-routed", "1");
        const complete = Boolean(snap && (snap.complete || snap.completedAt));
        if (!complete) {
          navigate("/agent-onboarding?run=1", { replace: true });
        }
      })
      .catch(() => {
        // Never block the app on a status-check failure; let them land normally.
      });
    return () => {
      cancelled = true;
    };
  }, [navigate, location.pathname]);

  return null;
}

function AccessLoadingPage() {
  return <RouteBundleFallback />;
}

function RouteBundleFallback() {
  const location = useLocation();
  return <RouteSkeleton path={location.pathname} />;
}

// Soft-locked page shown when a user lands on a route whose skill pack
// they don't have (or had revoked). Doesn't break navigation — just an
// upgrade CTA pointing them at Billing on Elevation HQ. Stays mounted so
// when an admin restores access the polling pick-up flips it back to the
// real feature route without the user reloading.
function UpgradeRequiredPage() {
  const billingUrl = "https://api.elevationrealestatehq.com/account#billing";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        padding: "32px 24px",
        textAlign: "center",
        gap: 14,
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: "color-mix(in srgb, var(--color-primary) 12%, transparent)",
          border: "1px solid color-mix(in srgb, var(--color-primary) 35%, transparent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-primary)",
          fontSize: 20,
        }}
      >
        ✦
      </div>
      <div style={{ fontSize: 18, fontWeight: 600, color: "var(--chat-text, #ECECEC)" }}>
        Upgrade to unlock this section
      </div>
      <div style={{ fontSize: 13, color: "var(--chat-muted, #A0A0A0)", maxWidth: 380, lineHeight: 1.45 }}>
        This skill pack isn't on your current plan. Add it from your Elevation
        Real Estate HQ billing to bring this tab back online.
      </div>
      <a
        href={billingUrl}
        target="_blank"
        rel="noreferrer"
        style={{
          marginTop: 4,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "9px 18px",
          background: "var(--color-primary)",
          color: "var(--color-primary-foreground)",
          borderRadius: 6,
          textDecoration: "none",
          fontSize: 13,
          fontWeight: 600,
        }}
      >
        Open billing
      </a>
    </div>
  );
}

function MarketingRedirect() {
  return <Navigate to="/social-media" replace />;
}

function AdminRedirect() {
  return <Navigate to="/admin" replace />;
}

function HeartbeatRedirect() {
  return <Navigate to="/cron?kind=heartbeats" replace />;
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
  "/agent-onboarding": AgentOnboardingPage,
  "/project": ProjectPage,
  "/sessions": SessionsPage,
  "/analytics": AnalyticsPage,
  "/logs": LogsPage,
  "/cron": CronPage,
  "/heartbeat": HeartbeatRedirect,
  "/experiments": ExperimentsPage,
  "/overview": OverviewPage,
  "/comms": CommsPage,
  "/activity": ActivityFeedPage,
  "/tasks": TasksPage,
  "/approvals": ApprovalsPage,
  "/skills": SkillsPage,
  "/config": ConfigPage,
  "/env": EnvPage,
  "/docs": DocsPage,
};

const BUILTIN_NAV_REST: NavItem[] = [
  {
    path: "/desktop-setup",
    label: "Desktop Setup",
    icon: ShieldCheck,
  },
  {
    path: "/agent-onboarding",
    label: "Agent Onboarding",
    icon: Sparkles,
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
  { path: "/cron", labelKey: "cron", label: "Automations", icon: Clock },
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
  const PendingOrLocked = accessPending ? AccessLoadingPage : UpgradeRequiredPage;
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
    "/memory": RealEstateMemoryPage,
    ...BUILTIN_ROUTES_BASE,
    ...(embeddedChat ? { "/chat": ChatPage } : {}),
  };
}

export default function App() {
  useIconButtonTitles();
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
  const isAdminRoute = normalizedPath === "/admin";
  const isLeadsRoute = normalizedPath === "/leads";
  const isTodayRoute = normalizedPath === "/today";
  const embeddedChat = isDashboardEmbeddedChatEnabled();
  const [accessStatus, setAccessStatus] = useState<AccessStatusResponse | null>(null);
  const [accessChecked, setAccessChecked] = useState(false);
  const [accessVersion, setAccessVersion] = useState(0);
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatusResponse | null>(null);
  const [licenseChecked, setLicenseChecked] = useState(false);
  const startupReportedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    if (accessVersion === 0) markStartup("access:request");
    api
      .getAccessStatus()
      .then((status) => {
        if (!cancelled) {
          if (accessVersion === 0) {
            markStartup("access:ready", status.mode ?? status.profile);
          }
          setAccessStatus(status);
        }
      })
      .catch(() => {
        if (!cancelled) {
          if (accessVersion === 0) markStartup("access:error");
          setAccessStatus(null);
        }
      })
      .finally(() => {
        if (!cancelled) setAccessChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [accessVersion]);

  // License gate — if a fresh install has no signed-in user, render
  // <LoginCard /> full-screen instead of dropping into an empty dashboard.
  // Re-checks on the same auth-changed / focus signals as accessStatus.
  useEffect(() => {
    let cancelled = false;
    if (accessVersion === 0) markStartup("license:request");
    api
      .getLicenseStatus()
      .then((status) => {
        if (!cancelled) {
          if (accessVersion === 0) {
            markStartup("license:ready", status.authenticated ? "authenticated" : "signed-out");
          }
          // Valid response => our session token is current; clear the reload guard.
          try { sessionStorage.removeItem("elevate:token-reload-at"); } catch { /* ignore */ }
          setLicenseStatus(status);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        // A 401 here means the dashboard rotated its in-memory session token
        // (it restarts once at startup to enable embedded chat) AFTER this
        // renderer loaded — so the injected token is stale. Reload once to pull
        // a fresh token instead of showing a false "signed out" screen. Guarded
        // by an 8s window so a genuinely unreachable backend can't reload-loop.
        if (msg.includes("401")) {
          try {
            const KEY = "elevate:token-reload-at";
            const last = Number(sessionStorage.getItem(KEY) || "0");
            if (Date.now() - last > 8000) {
              sessionStorage.setItem(KEY, String(Date.now()));
              window.location.reload();
              return;
            }
          } catch { /* ignore */ }
        }
        if (accessVersion === 0) markStartup("license:error");
        setLicenseStatus({ authenticated: false } as LicenseStatusResponse);
      })
      .finally(() => {
        if (!cancelled) setLicenseChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [accessVersion]);

  useEffect(() => {
    const handler = () => setAccessVersion((v) => v + 1);
    window.addEventListener("elevate:auth-changed", handler);

    // Refresh entitlements when the window regains focus and every 30s so an
    // admin revoking a skill pack lands on the user within seconds. The
    // existing auth-changed event only fires on local login/logout, which
    // misses remote revocations entirely.
    const onFocus = () => setAccessVersion((v) => v + 1);
    const onVisibility = () => {
      if (document.visibilityState === "visible") onFocus();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    const interval = window.setInterval(onFocus, 30_000);

    return () => {
      window.removeEventListener("elevate:auth-changed", handler);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(interval);
    };
  }, []);

  const realEstatePacks = accessStatus?.packs ?? DEFAULT_REAL_ESTATE_PACKS;
  const realEstateDashboard = hasRealEstateDashboard(realEstatePacks);

  useEffect(() => {
    if (startupReportedRef.current || !licenseChecked) return;
    if (licenseStatus?.authenticated && !accessChecked) return;
    startupReportedRef.current = true;
    markStartup(
      licenseStatus?.authenticated ? "ui:dashboard-ready" : "ui:login-ready",
      pathname,
    );
    window.requestAnimationFrame(() => reportStartup("initial-ready"));
  }, [accessChecked, licenseChecked, licenseStatus?.authenticated, pathname]);

  useEffect(() => {
    preloadRoute(pathname);
  }, [pathname]);

  useEffect(() => {
    if (!licenseChecked || !licenseStatus?.authenticated || !accessChecked) return;
    const warmPaths = [
      embeddedChat ? "/chat" : realEstateDashboard ? "/today" : "/hub",
      realEstatePacks.realEstateSales
        ? "/leads"
        : realEstatePacks.realEstateAdmin
          ? "/admin"
          : realEstatePacks.realEstateMarketing
            ? "/social-media"
            : "",
    ].filter(Boolean).slice(0, 2);
    return scheduleRouteWarmup(warmPaths);
  }, [
    accessChecked,
    embeddedChat,
    licenseChecked,
    licenseStatus?.authenticated,
    realEstateDashboard,
    realEstatePacks.realEstateAdmin,
    realEstatePacks.realEstateMarketing,
    realEstatePacks.realEstateSales,
  ]);

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
    const mql = window.matchMedia("(min-width: 0px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  // Auth gate — only block until we know whether to show login. Entitlement
  // checks can resolve behind the shell; route fallbacks stay visually quiet.
  if (!licenseChecked) return <RouteBundleFallback />;
  if (!licenseStatus?.authenticated) {
    return (
      <div className="onboarding-overlay relative flex h-dvh items-center justify-center overflow-hidden px-4 py-8">
        <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative w-full max-w-md">
          <LoginCard />
        </div>
      </div>
    );
  }

  return (
    <div
      data-accent="graphite"
      data-active-row="fill"
      data-artifacts="floating"
      data-density="compact"
      data-layout-variant={layoutVariant}
      data-sections="micro"
      className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base font-sans normal-case text-midground antialiased"
    >
      <SelectionSwitcher />
      <OnboardingGate />
      <Backdrop />
      <PluginSlot name="backdrop" />

      <header
        className={cn(
          // Desktop sidebar is persistent at every width (never auto-collapses),
          // so the mobile top bar is always hidden (min-[0px] = always).
          "min-[0px]:hidden fixed top-0 left-0 right-0 z-40 h-12",
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
            "min-[0px]:hidden fixed inset-0 z-40",
            "bg-black/60 cursor-pointer",
          )}
        />
      )}

      <PluginSlot name="header-banner" />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-12 min-[0px]:pt-0">
        <div className="flex min-h-0 min-w-0 flex-1">
          <aside
            id="app-sidebar"
            aria-label={t.app.navigation}
            className={cn(
              "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-[calc(var(--sidebar-w)+var(--sidebar-gap)*2)] max-w-[calc(100vw-1.5rem)] min-h-0 flex-col px-[var(--sidebar-gap)] pb-[var(--sidebar-gap)] pt-1",
              "bg-transparent",
              "transition-transform duration-200 ease-out",
              mobileOpen ? "translate-x-0" : "-translate-x-full",
              sidebarCollapsed
                ? "min-[0px]:hidden"
                : cn(
                    "min-[0px]:sticky min-[0px]:translate-x-0 min-[0px]:shrink-0",
                    "min-[0px]:top-0 min-[0px]:h-dvh",
                  ),
              isConfigRoute && "min-[0px]:hidden",
            )}
          >
            <DesktopSidebar
              embeddedChat={embeddedChat}
              navItems={navItems}
              onNavigate={closeMobile}
              onPreloadRoute={preloadRoute}
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
                isAdminRoute && "p-0",
                isLeadsRoute && "p-0",
                isTodayRoute && "p-0",
                !isConfigRoute && !isChatRoute && !isAdminRoute && !isLeadsRoute && !isTodayRoute && !isDocsRoute && "px-3 sm:px-6 pt-2 sm:pt-4 lg:pt-6 pb-4 sm:pb-8",
                isDocsRoute && "min-h-0 flex-1 px-4 sm:px-10 lg:px-16 pt-2 sm:pt-4 lg:pt-6 pb-4 sm:pb-8",
              )}
            >
              <PluginSlot name="pre-main" />
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute && !isConfigRoute && !isAdminRoute && !isLeadsRoute && !isTodayRoute && "elevate-page-shell",
                  isDocsRoute && "elevate-docs-shell",
                  (isDocsRoute || isChatRoute || isAdminRoute || isLeadsRoute || isTodayRoute) && "min-h-0 flex flex-1 flex-col",
                )}
              >
                <div
                  key={normalizedPath}
                  className={cn(
                    "min-w-0",
                    (isDocsRoute || isChatRoute || isAdminRoute || isLeadsRoute || isTodayRoute) && "min-h-0 flex flex-1 flex-col",
                    !isChatRoute && !isConfigRoute && !isAdminRoute && !isLeadsRoute && !isTodayRoute && "elevate-route-transition",
                  )}
                >
                  <Suspense
                    fallback={<RouteBundleFallback />}
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
const SIDEBAR_SESSION_PAGE_LIMIT = 200;
const SIDEBAR_SESSION_SCAN_LIMIT = 1400;
const SIDEBAR_CHAT_TARGET = 48;
const SIDEBAR_CRON_RUN_TARGET = 48;

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
  // No real title yet — show the first message as a stand-in, else a neutral
  // "General session" placeholder (never "Untitled") until a title is generated.
  return session.preview?.trim() || "General session";
}

const SIDEBAR_ACTIVE_STALE_SECONDS = 120;
const SIDEBAR_CRON_RECENT_EMPTY_SECONDS = 120;
const SIDEBAR_LOCAL_TURN_STALE_MS = 30 * 60 * 1000;
const CRON_SESSION_ID_RE = /^cron_([^_]+)_\d{8}_\d{6}$/;

function sessionActivitySeconds(session: SessionInfo): number {
  return session.last_active || session.started_at || 0;
}

function isFreshActiveSession(
  session: SessionInfo,
  nowSec = Date.now() / 1000,
): boolean {
  if (!session.is_active) return false;
  const lastActive = sessionActivitySeconds(session);
  return lastActive > 0 && nowSec - lastActive < SIDEBAR_ACTIVE_STALE_SECONDS;
}

function cronJobIdFromSession(session: SessionInfo): string | null {
  if (!isCronSession(session)) return null;
  return session.id.match(CRON_SESSION_ID_RE)?.[1] ?? null;
}

function isCronSession(session: SessionInfo): boolean {
  return (session.source ?? "") === "cron" || session.id?.startsWith("cron_");
}

function isDetachedAutomationSession(session: SessionInfo): boolean {
  if ((session.source ?? "") !== "cli") return false;
  const preview = session.preview?.trim().toLowerCase() ?? "";
  const title = session.title?.trim().toLowerCase() ?? "";
  return (
    preview.startsWith("you are an automation agent driving the aoir xposure") ||
    title === "daily pcs listing snapshot" ||
    title === "xposure buyer export source"
  );
}

function isSidebarAutomationSession(session: SessionInfo): boolean {
  return isCronSession(session) || isDetachedAutomationSession(session);
}

function shouldShowCronSession(session: SessionInfo, nowSec: number): boolean {
  if (!isCronSession(session)) return false;
  if ((session.message_count ?? 0) > 0) return true;
  if (isFreshActiveSession(session, nowSec)) return true;
  const startedAt = session.started_at ?? session.last_active ?? 0;
  return startedAt > 0 && nowSec - startedAt < SIDEBAR_CRON_RECENT_EMPTY_SECONDS;
}

function isSidebarRelevantSession(session: SessionInfo, nowSec: number): boolean {
  if (isDetachedAutomationSession(session)) return false;
  if (isCronSession(session)) return shouldShowCronSession(session, nowSec);
  if ((session.message_count ?? 0) > 0) return true;
  // A new session that's actively working stays put through its first turn —
  // even a long one — instead of vanishing after 10s and popping back when the
  // first message persists. An idle 0-message session falls off after the
  // active-stale window.
  if (session.is_active) return true;
  return isFreshActiveSession(session, nowSec);
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

type LocalActiveTurn = {
  startedAt: number;
  title?: string;
};

function applyLocalActiveTurns(
  sessions: SessionInfo[],
  activeTurns: Map<string, LocalActiveTurn>,
  nowMs = Date.now(),
): SessionInfo[] {
  if (!activeTurns.size) return sessions;
  const nowSec = nowMs / 1000;
  const liveIds = new Set<string>();
  for (const [sid, turn] of activeTurns) {
    if (nowMs - turn.startedAt > SIDEBAR_LOCAL_TURN_STALE_MS) {
      activeTurns.delete(sid);
      continue;
    }
    liveIds.add(sid);
  }
  if (!liveIds.size) return sessions;
  return sessions.map((session) =>
    liveIds.has(session.id)
      ? {
          ...session,
          is_active: true,
          last_active: Math.max(sessionActivitySeconds(session), nowSec),
        }
      : session,
  );
}

type DesktopUpdaterState = {
  status?: string;
  info?: { version?: string | null } | null;
  progress?: { percent?: number | null } | null;
  error?: string | null;
};

type DesktopUpdaterResult = {
  ok?: boolean;
  message?: string;
  version?: string | null;
};

type DesktopUpdaterApi = {
  getStatus: () => Promise<DesktopUpdaterState>;
  checkNow: () => Promise<DesktopUpdaterResult>;
  install: () => Promise<DesktopUpdaterResult>;
  onEvent?: (callback: (payload: DesktopUpdaterState) => void) => (() => void);
};

function getDesktopUpdater(): DesktopUpdaterApi | null {
  if (typeof window === "undefined") return null;
  const desktopWindow = window as Window & {
    elevateDesktop?: { updater?: DesktopUpdaterApi };
  };
  return desktopWindow.elevateDesktop?.updater ?? null;
}

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

// Sidebar chat list is cached to localStorage so it paints instantly on app
// restart (the dashboard backend takes a few seconds to boot; without this the
// sidebar sits empty until it's ready). Fresh data overwrites the cache once
// the API responds.
const SESSIONS_CACHE_KEY = "elevate.sidebar.sessions.v1";
function readCachedSessions(): SessionInfo[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSIONS_CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Never trust cached running state — clear it so a stale "running" row
    // doesn't flash the 3-dot indicator until live data confirms it.
    return parsed.map((s) => ({ ...s, is_active: false }));
  } catch {
    return [];
  }
}
function writeCachedSessions(sessions: SessionInfo[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(SESSIONS_CACHE_KEY, JSON.stringify(sessions.slice(0, 60)));
  } catch {
    /* ignore quota / serialization errors */
  }
}

function DesktopSidebar({
  embeddedChat,
  // navItems no longer rendered in the sidebar (Tools moved to the profile
  // menu); the prop stays on the type/caller but is unused here.
  onNavigate,
  onPreloadRoute,
  onToggleSidebar,
  readyToLoad,
  realEstatePacks,
}: {
  embeddedChat: boolean;
  navItems: NavItem[];
  onNavigate: () => void;
  onPreloadRoute?: (path: string) => void;
  onToggleSidebar: () => void;
  readyToLoad: boolean;
  realEstatePacks: RealEstatePackAccess;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>(readCachedSessions);
  // If we have a cached list, don't show the loading state — paint it instantly.
  const [sessionsLoading, setSessionsLoading] = useState(
    () => readCachedSessions().length === 0,
  );
  const [sessionError, setSessionError] = useState(false);
  // Optimistically-inserted new chats, keyed by id, with the insert timestamp.
  // A brand new chat's row doesn't exist server-side for a beat (the row +
  // first message persist asynchronously), so loadSessions preserves these
  // until the server list catches up or a short grace window elapses —
  // otherwise the reconciling refetch would wipe the row we just inserted.
  const optimisticSessionsRef = useRef<Map<string, { session: SessionInfo; ts: number }>>(
    new Map(),
  );
  const localActiveTurnsRef = useRef<Map<string, LocalActiveTurn>>(new Map());
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
  const [agentMoreOpen, setAgentMoreOpen] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem("elevate.sidebar.agentMore.v1") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "elevate.sidebar.agentMore.v1",
        agentMoreOpen ? "1" : "0",
      );
    } catch {
      /* ignore */
    }
  }, [agentMoreOpen]);
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
  const {
    activeAction,
    isBusy: systemActionBusy,
    isRunning: systemActionRunning,
    pendingAction,
    runAction,
    updateStatus,
  } = useSystemActions();
  const desktopUpdater = useMemo(getDesktopUpdater, []);
  const [desktopUpdate, setDesktopUpdate] = useState<DesktopUpdaterState | null>(null);

  useEffect(() => {
    if (!desktopUpdater) return;
    let alive = true;
    desktopUpdater
      .getStatus()
      .then((status) => {
        if (alive) setDesktopUpdate(status);
      })
      .catch(() => {
        if (alive) setDesktopUpdate(null);
      });
    const unsubscribe = desktopUpdater.onEvent?.((status) => setDesktopUpdate(status));
    return () => {
      alive = false;
      unsubscribe?.();
    };
  }, [desktopUpdater]);

  const [installing, setInstalling] = useState(false);
  const updateBusy =
    installing ||
    pendingAction === "update" ||
    (activeAction === "update" && systemActionRunning);

  const handleSidebarUpdate = useCallback(async () => {
    const desktopStatus = desktopUpdate?.status;
    if (desktopUpdater && desktopStatus === "ready") {
      // Acknowledge the click INSTANTLY. quitAndInstall has a couple-second
      // handoff before the window closes; without this the UI looks dead and
      // users click again.
      setInstalling(true);
      const result = await desktopUpdater.install();
      if (!result?.ok) {
        setInstalling(false);
        showToast(result?.message || "Update is not ready yet", "error");
      }
      return;
    }

    if (desktopUpdater && desktopStatus === "error") {
      const result = await desktopUpdater.checkNow();
      if (!result?.ok) {
        showToast(result?.message || "Could not check for updates", "error");
      }
      return;
    }

    if (updateStatus?.available) {
      await runAction("update");
      return;
    }

    if (desktopUpdater) {
      const result = await desktopUpdater.checkNow();
      if (!result?.ok) {
        showToast(result?.message || "Could not check for updates", "error");
      }
    }
  }, [desktopUpdate?.status, desktopUpdater, runAction, showToast, updateStatus?.available]);

  const loadSessions = useCallback(async (options?: { refresh?: boolean }) => {
    try {
      const nowSec = Date.now() / 1000;
      const byId = new Map<string, SessionInfo>();
      let chatCount = 0;
      let cronRunCount = 0;
      let hiddenAutomationCount = 0;

      for (
        let offset = 0;
        offset < SIDEBAR_SESSION_SCAN_LIMIT;
        offset += SIDEBAR_SESSION_PAGE_LIMIT
      ) {
        const resp = await api.getSessions(SIDEBAR_SESSION_PAGE_LIMIT, offset, {
          includeTotal: false,
          refresh: options?.refresh,
        });
        const page = resp.sessions ?? [];
        if (page.length === 0) break;

        for (const session of page) {
          if (isDetachedAutomationSession(session)) {
            hiddenAutomationCount += 1;
            continue;
          }
          if (!isSidebarRelevantSession(session, nowSec)) continue;
          if (!byId.has(session.id)) byId.set(session.id, session);
        }

        const loaded = Array.from(byId.values());
        chatCount = loaded.filter((session) => !isCronSession(session)).length;
        cronRunCount = loaded.filter(isCronSession).length;

        const hasEnoughVisibleRows =
          chatCount >= SIDEBAR_CHAT_TARGET &&
          (hiddenAutomationCount === 0 || cronRunCount >= SIDEBAR_CRON_RUN_TARGET);
        const noMorePages = page.length < SIDEBAR_SESSION_PAGE_LIMIT;
        if (hasEnoughVisibleRows || noMorePages) {
          break;
        }
      }

      let loadedSessions = Array.from(byId.values());

      // Preserve optimistically-inserted new chats the server list doesn't
      // carry yet. Once the server returns the id, drop the optimistic copy
      // (server wins); after a short grace window give up either way so a
      // failed send can't leave a ghost row.
      const optimistic = optimisticSessionsRef.current;
      if (optimistic.size) {
        const OPTIMISTIC_GRACE_MS = 30_000;
        const now = Date.now();
        const survivors: SessionInfo[] = [];
        for (const [sid, entry] of optimistic) {
          if (byId.has(sid)) {
            optimistic.delete(sid); // server caught up — its copy is in loadedSessions
          } else if (now - entry.ts < OPTIMISTIC_GRACE_MS) {
            survivors.push(entry.session); // keep showing until the server has it
          } else {
            optimistic.delete(sid); // grace elapsed — stop forcing it
          }
        }
        if (survivors.length) loadedSessions = [...survivors, ...loadedSessions];
      }

      loadedSessions = applyLocalActiveTurns(loadedSessions, localActiveTurnsRef.current);
      setSessions(loadedSessions);
      writeCachedSessions(loadedSessions);
      setSessionError(false);
    } catch {
      setSessionError(true);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  const loadCronJobs = useCallback((options?: { refresh?: boolean }) => {
    api
      .getCronJobs({ compact: true, refresh: options?.refresh })
      .then((jobs) => setCronJobs(jobs ?? []))
      .catch(() => {
        /* sidebar can render empty if cron API is down */
      });
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
      if (document.hidden) stop(); else { loadSessions({ refresh: true }); start(); }
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
    const initialLoad = window.setTimeout(loadCronJobs, 300);
    const id = window.setInterval(() => {
      if (typeof document === "undefined" || !document.hidden) loadCronJobs();
    }, 20000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(id);
    };
  }, [loadCronJobs, readyToLoad]);

  useEffect(() => {
    if (!readyToLoad) return;
    const onCronJobsChanged = () => {
      loadCronJobs({ refresh: true });
      loadSessions({ refresh: true });
    };
    window.addEventListener("elevate:cron-jobs-changed", onCronJobsChanged);
    return () => {
      window.removeEventListener("elevate:cron-jobs-changed", onCronJobsChanged);
    };
  }, [loadCronJobs, loadSessions, readyToLoad]);

  // Reshuffle the sidebar the moment a chat sends/finishes a turn, instead of
  // waiting for the 12s poll. ChatPage fires these as the user messages.
  useEffect(() => {
    if (!readyToLoad) return;
    const onActivity = (event: Event) => {
      // Optimistically float the active chat to the top right away, then
      // reconcile with the server so it stays put.
      const detail = (event as CustomEvent<{ sessionId?: string; title?: string }>)
        .detail;
      const sid = detail?.sessionId;
      const title = detail?.title?.trim();
      if (event.type === "elevate:agent-turn-complete" && sid) {
        localActiveTurnsRef.current.delete(sid);
      }
      if (sid) {
        const nowSec = Date.now() / 1000;
        if (event.type === "elevate:agent-turn-start") {
          localActiveTurnsRef.current.set(sid, {
            startedAt: Date.now(),
            title,
          });
        }
        setSessions((prev) => {
          const existing = prev.find((item) => item.id === sid);
          if (existing) {
            return prev.map((item) =>
              item.id === sid && event.type === "elevate:agent-turn-start"
                ? { ...item, last_active: nowSec, is_active: true }
                : item,
            );
          }
          // Only synthesize a row when the event carries a title — that signals
          // a brand new chat's first send. A title-less activity ping (an
          // existing chat floating) must NOT insert: the chat may simply be
          // off the loaded sidebar page, and a blank "Untitled" ghost would be
          // wrong. Those reconcile via the loadSessions refresh below.
          if (!title) return prev;
          // Brand new chat the server list doesn't carry yet — synthesize a row
          // so it appears the instant the user sends, instead of waiting up to
          // 12s for the next poll. message_count:1 keeps it past the sidebar's
          // fresh-only filter; loadSessions preserves it until the server has it.
          const optimistic: SessionInfo = {
            id: sid,
            source: "tui",
            model: null,
            title,
            started_at: nowSec,
            ended_at: null,
            last_active: nowSec,
            is_active: true,
            message_count: 1,
            tool_call_count: 0,
            input_tokens: 0,
            output_tokens: 0,
            preview: title,
          };
          optimisticSessionsRef.current.set(sid, { session: optimistic, ts: Date.now() });
          return [optimistic, ...prev];
        });
      }
      loadSessions({ refresh: true });
    };
    window.addEventListener("elevate:agent-turn-complete", onActivity);
    window.addEventListener("elevate:agent-turn-start", onActivity);
    return () => {
      window.removeEventListener("elevate:agent-turn-complete", onActivity);
      window.removeEventListener("elevate:agent-turn-start", onActivity);
    };
  }, [loadSessions, readyToLoad]);

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
    .filter((session) => pinnedIds.includes(session.id) && !isSidebarAutomationSession(session))
    .slice(0, 8);
  const spotlightIds = new Set(pinnedSessions.map((session) => session.id));
  const chatSessions = filteredSessions
    .filter((session) => !spotlightIds.has(session.id) && !isSidebarAutomationSession(session))
    // Most-recent first, but a running chat floats to the top immediately —
    // its last_active is stale until the turn finishes, so sort on is_active first.
    .sort((a, b) => {
      const nowSec = Date.now() / 1000;
      const aRunning = isFreshActiveSession(a, nowSec);
      const bRunning = isFreshActiveSession(b, nowSec);
      if (aRunning !== bRunning) return aRunning ? -1 : 1;
      return sessionActivitySeconds(b) - sessionActivitySeconds(a);
    })
    .slice(0, 18);
  const cronJobIds = useMemo(() => new Set(cronJobs.map((job) => job.id)), [cronJobs]);
  const cronJobIdByLastSessionId = useMemo(() => {
    const map = new Map<string, string>();
    for (const job of cronJobs) {
      if (job.last_session_id) map.set(job.last_session_id, job.id);
    }
    return map;
  }, [cronJobs]);
  const cronSessionsByJobId = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    const nowSec = Date.now() / 1000;
    for (const session of sessions) {
      const jobId = cronJobIdFromSession(session) ?? cronJobIdByLastSessionId.get(session.id);
      if (!jobId) continue;
      if (!cronJobIds.has(jobId)) continue;
      if (!shouldShowCronSession(session, nowSec)) continue;
      const list = map.get(jobId) ?? [];
      list.push(session);
      map.set(jobId, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => sessionActivitySeconds(b) - sessionActivitySeconds(a));
    }
    return map;
  }, [cronJobIdByLastSessionId, cronJobIds, sessions]);
  const latestCronSessionByJobId = useMemo(() => {
    const map = new Map<string, SessionInfo>();
    for (const [jobId, list] of cronSessionsByJobId) {
      if (list[0]) map.set(jobId, list[0]);
    }
    return map;
  }, [cronSessionsByJobId]);
  const runningCronJobIds = useMemo(() => {
    const ids = new Set<string>();
    const nowSec = Date.now() / 1000;
    for (const [jobId, session] of latestCronSessionByJobId) {
      if (isFreshActiveSession(session, nowSec)) ids.add(jobId);
    }
    return ids;
  }, [latestCronSessionByJobId]);
  const realEstateDashboard = hasRealEstateDashboard(realEstatePacks);
  const agentPrimaryNavItems: NavItem[] = [];
  if (realEstateDashboard) {
    agentPrimaryNavItems.push({ icon: Home, label: "Today", path: "/today" });
  }
  if (realEstatePacks.realEstateSales) {
    agentPrimaryNavItems.push({ icon: Users, label: "Leads", path: "/leads" });
  }
  if (realEstatePacks.realEstateAdmin) {
    agentPrimaryNavItems.push({ icon: BriefcaseBusiness, label: "Admin", path: "/admin" });
  }
  if (realEstatePacks.realEstateMarketing) {
    agentPrimaryNavItems.push({ icon: Megaphone, label: "Social Media", path: "/social-media" });
  }
  // Automations is the single scheduled-runs home; heartbeat check-ins are filtered there.
  agentPrimaryNavItems.push({ icon: Clock, label: "Automations", path: "/cron" });
  const agentMoreNavItems: NavItem[] = [
    { icon: BarChart3, label: "Overview", path: "/overview" },
    { icon: Bot, label: "Agents", path: "/hub" },
    { icon: FlaskConical, label: "Experiments", path: "/experiments" },
    { icon: KanbanSquare, label: "Tasks", path: "/tasks" },
    { icon: CheckCheck, label: "Approvals", path: "/approvals" },
    { icon: MessageSquare, label: "Comms", path: "/comms" },
    { icon: Activity, label: "Activity", path: "/activity" },
  ];
  const agentMoreActive = agentMoreNavItems.some((item) =>
    location.pathname === item.path || location.pathname.startsWith(`${item.path}/`),
  );
  const showAgentMoreItems = agentMoreOpen || agentMoreActive;
  const realEstateNavItems = [...agentPrimaryNavItems, ...agentMoreNavItems];
  const toolsNavItems: NavItem[] = [
    { icon: Puzzle, label: "Skills", path: "/skills" },
    { icon: Brain, label: "Memory graph", path: "/memory" },
  ];
  const go = (path: string) => {
    onPreloadRoute?.(path);
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


  return (
    <div className="sidebar normal-case font-sans text-[14px] tracking-normal text-[var(--sidebar-text)]">
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
        className="sidebar-top"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        {/* Logo removed per request — empty spacer keeps the row height and the
            traffic-light clearance on the left. */}
        <div className="h-7 w-[9.75rem] shrink-0" aria-hidden />

        <button
          type="button"
          onClick={onNavigate}
          aria-label={t.app.closeNavigation}
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          className={cn(
            "absolute right-3 top-1/2 inline-flex h-11 w-11 -translate-y-1/2 shrink-0 items-center justify-center min-[0px]:hidden",
            "rounded-lg text-muted-foreground hover:bg-accent hover:text-midground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          )}
        >
          <X className="h-4 w-4" />
        </button>

        <div
          className="tools hidden min-[0px]:flex"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <button
            type="button"
            onClick={() => (searchOpen ? closeSearch() : openSearch())}
            aria-label={searchOpen ? "Close search" : "Search"}
            aria-pressed={searchOpen}
            className={cn(
              "icon-btn",
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
              "icon-btn",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            )}
          >
            <PanelLeftClose className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="sidebar-scroll overflow-x-hidden">
        <div className="space-y-0.5">
          <button
            type="button"
            onClick={startNewChat}
            className="new-chat"
          >
            <Plus />
            <span className="truncate">New chat</span>
            <span className="kbd">⌘N</span>
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
                  "h-11 w-full rounded-lg bg-[var(--sidebar-row)] shadow-[inset_0_0_0_1px_var(--sidebar-border)] lg:h-8 lg:rounded-[7px]",
                  "pl-9 pr-9 text-[0.9rem] text-[var(--sidebar-text-strong)] placeholder:text-[var(--sidebar-text-muted)] lg:text-[0.86rem]",
                  "outline-none transition-colors focus:bg-[var(--chat-surface-strong)] focus:shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_34%,transparent),0_0_0_3px_color-mix(in_srgb,var(--color-primary)_10%,transparent)]",
                )}
              />
              <button
                type="button"
                onClick={closeSearch}
                aria-label={query ? t.common.clear : "Close search"}
                className="absolute right-0.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-[7px] text-[var(--sidebar-icon-muted)] hover:text-[var(--sidebar-icon)] lg:h-7 lg:w-7 lg:right-0.5"
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
              Agent
            </SidebarSectionLabel>
            {!collapsedSections.realEstate && (
              <div className="space-y-0.5">
                {agentPrimaryNavItems.map((item) => (
                  <SidebarAction
                    key={item.path}
                    icon={item.icon}
                    label={item.label}
                    path={item.path}
                    onNavigate={go}
                    onPreload={onPreloadRoute}
                  />
                ))}
                <SidebarMoreToggle
                  active={agentMoreActive}
                  open={showAgentMoreItems}
                  onToggle={() => setAgentMoreOpen((prev) => !prev)}
                />
                {showAgentMoreItems &&
                  agentMoreNavItems.map((item) => (
                    <SidebarAction
                      key={item.path}
                      icon={item.icon}
                      label={item.label}
                      path={item.path}
                      onNavigate={go}
                      onPreload={onPreloadRoute}
                    />
                  ))}
              </div>
            )}
          </div>
        )}

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
          onOpenSession={openSession}
        />

        <div className="mt-3 lg:mt-2.5">
          <SidebarSectionLabel
            collapsed={collapsedSections.tools}
            onToggle={() => toggleSection("tools")}
          >
            Tools
          </SidebarSectionLabel>
          {!collapsedSections.tools && (
            <div className="space-y-0.5">
              {toolsNavItems.map((item) => (
                <SidebarAction
                  key={item.path}
                  icon={item.icon}
                  label={item.label}
                  path={item.path}
                  onNavigate={go}
                  onPreload={onPreloadRoute}
                />
              ))}
            </div>
          )}
        </div>

      </div>

      <div className="sidebar-foot shrink-0">
        <SidebarUpdateCard
          desktopUpdate={desktopUpdate}
          cliUpdateStatus={updateStatus}
          disabled={systemActionBusy && !updateBusy}
          updateBusy={updateBusy}
          onClick={handleSidebarUpdate}
        />
        <SidebarUserPill />
      </div>
    </div>
  );
}

function SidebarUpdateCard({
  cliUpdateStatus,
  desktopUpdate,
  disabled,
  onClick,
  updateBusy,
}: {
  cliUpdateStatus: UpdateStatusResponse | null;
  desktopUpdate: DesktopUpdaterState | null;
  disabled: boolean;
  onClick: () => void;
  updateBusy: boolean;
}) {
  const desktopStatus = desktopUpdate?.status ?? "idle";
  const desktopVisible =
    desktopStatus === "available" ||
    desktopStatus === "downloading" ||
    desktopStatus === "ready" ||
    desktopStatus === "error";
  const cliVisible = Boolean(cliUpdateStatus?.available || updateBusy);
  if (!desktopVisible && !cliVisible) return null;

  const downloadingPercent =
    typeof desktopUpdate?.progress?.percent === "number"
      ? `${Math.round(desktopUpdate.progress.percent)}%`
      : null;
  const desktopVersion = desktopUpdate?.info?.version
    ? `v${desktopUpdate.info.version}`
    : "A new app version";
  const updateBehind = cliUpdateStatus?.behind ?? 0;

  let title = "Update available";
  let detail = updateBehind > 0
    ? `${updateBehind} backend change${updateBehind === 1 ? "" : "s"} ready`
    : "Backend update ready";
  let action = "Click here to update";
  let icon: ComponentType<{ className?: string }> = Download;
  let busy = updateBusy;
  let error = false;
  let blocked = disabled || updateBusy;

  if (desktopVisible) {
    if (desktopStatus === "ready") {
      title = "Update ready";
      detail = `${desktopVersion} is downloaded.`;
      action = "Click here to update";
      blocked = false;
    } else if (desktopStatus === "error") {
      title = "Update failed";
      detail = desktopUpdate?.error || "Check again when you are online.";
      action = "Check again";
      icon = AlertTriangle;
      error = true;
      blocked = false;
    } else {
      title = desktopStatus === "downloading" ? "Downloading update" : "Update available";
      detail = downloadingPercent ? `${downloadingPercent} downloaded` : "Preparing the app update.";
      action = "Preparing";
      icon = RefreshCw;
      busy = true;
      blocked = true;
    }
  } else if (updateBusy) {
    title = "Updating Elevate";
    detail = "Applying the backend update now.";
    action = "Updating";
    icon = RefreshCw;
    busy = true;
    blocked = true;
  }

  const Icon = icon;
  return (
    <button
      type="button"
      className={cn("sidebar-update-card", busy && "busy", error && "error")}
      disabled={blocked}
      onClick={onClick}
    >
      <Icon className={cn("update-icon", busy && "animate-spin")} />
      <span className="update-copy">
        <span className="update-title">{title}</span>
        <span className="update-detail">{detail}</span>
      </span>
      <span className="update-action">{action}</span>
    </button>
  );
}

function SidebarSectionLabel({
  badge,
  children,
  collapsed,
  onToggle,
}: {
  badge?: ReactNode;
  children: ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  if (!onToggle) {
    return (
      <div className="section-label">
        <ChevronDown />
        <span>{children}</span>
        {badge && <span className="section-badge">{badge}</span>}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      className={cn("section-label", collapsed && "collapsed")}
    >
      <ChevronDown />
      <span>{children}</span>
      {badge && <span className="section-badge">{badge}</span>}
    </button>
  );
}

function sidebarActionClass(active: boolean, primary = false) {
  return cn(
    "nav-row focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
    primary && "font-medium",
    active && "active",
  );
}

function SidebarMoreToggle({
  active,
  onToggle,
  open,
}: {
  active: boolean;
  onToggle: () => void;
  open: boolean;
}) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      className={cn(sidebarActionClass(active), "nav-row-more")}
    >
      <Icon />
      <span className="min-w-0 truncate">More</span>
    </button>
  );
}

function SidebarAction({
  icon: Icon,
  label,
  onNavigate,
  onPreload,
  path,
  primary = false,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  onNavigate: (path: string) => void;
  onPreload?: (path: string) => void;
  path: string;
  primary?: boolean;
}) {
  const handleIntent = () => onPreload?.(path);
  return (
    <NavLink
      to={path}
      end={path === "/today" || path === "/hub" || path === "/sessions"}
      onFocus={handleIntent}
      onPointerEnter={handleIntent}
      onTouchStart={handleIntent}
      onClick={(event) => {
        event.preventDefault();
        onNavigate(path);
      }}
      className={({ isActive }) =>
        sidebarActionClass(isActive, primary)
      }
    >
      <Icon />
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
  const groupedSessions = useMemo(() => {
    if (label !== "Chats") return null;
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
    const groups: Array<{ label: string; sessions: SessionInfo[] }> = [
      { label: "Today", sessions: [] },
      { label: "Yesterday", sessions: [] },
      { label: "Earlier", sessions: [] },
    ];
    for (const session of sessions) {
      const lastActive = (session.last_active ?? 0) * 1000;
      if (lastActive >= startOfToday) groups[0].sessions.push(session);
      else if (lastActive >= startOfYesterday) groups[1].sessions.push(session);
      else groups[2].sessions.push(session);
    }
    return groups.filter((group) => group.sessions.length > 0);
  }, [label, sessions]);

  const renderSession = (session: SessionInfo) => (
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
  );

  return (
    <div className="mt-3 lg:mt-2.5">
      <SidebarSectionLabel>{label}</SidebarSectionLabel>
      {groupedSessions ? (
        groupedSessions.map((group) => (
          <div key={group.label}>
            <div className="session-group-label">{group.label}</div>
            <div className="session-list">{group.sessions.map(renderSession)}</div>
          </div>
        ))
      ) : (
        <div className="session-list">{sessions.map(renderSession)}</div>
      )}

      {(loading || statusText) && sessions.length === 0 && (
        <div className="px-2.5 py-1 text-[0.8rem] text-[var(--sidebar-text-muted)]">
          {loading ? (
            <div className="space-y-1.5 py-1">
              <Skeleton className="h-3 w-full bg-[var(--sidebar-border)]" />
              <Skeleton className="h-3 w-4/5 bg-[var(--sidebar-border)]" />
            </div>
          ) : (
            statusText
          )}
        </div>
      )}
    </div>
  );
}

const SESSION_IDLE_MS = 24 * 60 * 60 * 1000;

function SessionStatusDot({
  lastActive,
  unread,
  running,
}: {
  lastActive: number;
  unread: boolean;
  running?: boolean;
}) {
  let tone: "warning" | "idle" | "ok";
  let label: string;
  if (running) {
    tone = "ok";
    label = "Running";
  } else if (unread) {
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
  // While a chat is actively running a turn, show three sequenced dots (the
  // "working" indicator) on its sidebar row instead of the single status dot.
  if (running) {
    return (
      <span
        aria-label={label}
        title={label}
        className="dots-working"
      >
        {[0, 1, 2].map((i) => (
          <span key={i} />
        ))}
      </span>
    );
  }
  return (
    <span
      aria-label={label}
      title={label}
      className={cn(
        "dot",
        tone === "warning" && "warn",
        tone === "idle" && "idle",
        tone === "ok" && "done",
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
  const running = isFreshActiveSession(session);

  useEffect(() => {
    if (isRenaming) renameRef.current?.focus();
  }, [isRenaming]);

  if (isRenaming) {
    return (
      <div className="session-row active">
        <input
          ref={renameRef}
          defaultValue={title}
          className="col-span-3 min-w-0 rounded-[7px] bg-transparent px-1 py-0.5 text-[13px] leading-[1.3] text-[var(--fg)] outline-none ring-1 ring-[var(--accent-ring)]"
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
      onClick={() => onOpenSession(session)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenSession(session);
        }
      }}
      role="button"
      tabIndex={0}
      title={title}
      data-status={unread ? "needs-perms" : running ? "working" : Date.now() - sessionActivitySeconds(session) * 1000 > SESSION_IDLE_MS ? "inactive" : "done"}
      className={cn(
        "session-row",
        active && "active",
      )}
    >
      <NavLink
        to={route}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onOpenSession(session);
        }}
        className="contents"
      >
        <span className="status-cell">
        <SessionStatusDot
          lastActive={session.last_active}
          unread={unread}
          running={running}
        />
        </span>
        <span className="title">{title}</span>
        <span className="age">{compactSessionAge(sessionActivitySeconds(session))}</span>
        <span className="sr-only">
          {title} · {running ? "running, " : ""}
          {session.source ?? "local"} {timeAgo(sessionActivitySeconds(session))}
        </span>
      </NavLink>
      <div className="session-actions hidden min-[0px]:flex">
        <button
          type="button"
          aria-label={pinned ? "Unpin chat" : "Pin chat"}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onTogglePinned(session.id);
          }}
          className={cn("icon-btn sm", pinned && "text-primary")}
        >
          <Pin className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Open chat menu"
          title="Open chat menu"
          onClick={(event) => onOpenContextMenu(session, event)}
          className="icon-btn sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>
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
  onOpenSession,
  liveJobIds,
  sessionsByJobId,
}: {
  jobs: CronJob[];
  open: boolean;
  onToggle: () => void;
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
      <SidebarSectionLabel
        collapsed={!open}
        onToggle={onToggle}
        badge={
          <>
            <span className="dim">{jobs.length}</span>
            {liveCount > 0 && (
              <span className="live-ind">
                <span className="dot" />
                {runningCount > 0 ? `${runningCount} running` : `${liveCount} live`}
              </span>
            )}
          </>
        }
      >
        Automations
      </SidebarSectionLabel>
      {open && (
        <div className="auto-list">
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
            const Icon = errored ? AlertTriangle : paused ? Pause : Clock;
            const status = errored ? "warn" : paused ? "paused" : "live";
            const trail = running ? "live" : paused ? "paused" : formatNextRun(job.next_run_at);
            const handleJobAction = () => {
              toggleExpand(job.id);
            };
            return (
              <div key={job.id}>
              <div
                className="auto-row"
                data-status={status}
                onClick={handleJobAction}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    handleJobAction();
                  }
                }}
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                title={`${title} · ${job.schedule_display}${running ? " · running now" : ""}${job.last_error ? ` · ${job.last_error}` : ""}`}
              >
                <ChevronRight
                  className={cn("auto-chev", isExpanded && "rotate-90")}
                  aria-hidden="true"
                />
                <Icon className="auto-icon" />
                <span className="title">{title}</span>
                <span className={cn("auto-trail", paused && "paused", trail === "—" && "dash")}>
                  {trail}
                </span>
              </div>
              {isExpanded && (
                <div className="session-list mb-1 mt-0.5">
	                  {recentRuns.length > 0 ? recentRuns.map((session) => {
	                    const runAt = sessionActivitySeconds(session);
	                    const runIsActive = isFreshActiveSession(session);
	                    const runLabel =
	                      session.preview?.trim() ||
	                      (session.title && session.title.trim() !== "Untitled"
	                        ? session.title.trim()
	                        : "") ||
	                      `Run · ${new Date(runAt * 1000).toLocaleString()}`;
	                    return (
	                    <button
	                      key={session.id}
	                      type="button"
	                      onClick={() => onOpenSession(session)}
	                      className="session-row"
	                      data-status={runIsActive ? "working" : "done"}
	                      title={`${runLabel} · ${new Date(runAt * 1000).toLocaleString()}`}
	                    >
	                      <span className="status-cell">
	                        <span className={cn("dot", runIsActive ? "warn" : "done")} />
	                      </span>
	                      <span className="title">{runLabel}</span>
	                      <span className="age">{compactSessionAge(runAt)}</span>
	                    </button>
	                    );
	                  }) : (
                    <div className="session-row auto-empty" data-status="inactive">
                      <span className="status-cell">
                        <span className="dot idle" />
                      </span>
                      <span className="title">No recorded runs yet</span>
                      <span className="age">—</span>
                    </div>
                  )}
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
          "fixed z-[100] w-[16.5rem] rounded-[10px] p-1 outline-none",
          "border border-[var(--sidebar-border-strong)] bg-[var(--chat-surface)] text-[var(--chat-muted-strong)]",
          "shadow-[0_24px_60px_-16px_rgba(0,0,0,0.7),0_1px_0_rgba(255,255,255,0.03)_inset]",
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
    <div className="my-1 h-px bg-[var(--sidebar-border)]" />
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
        "flex min-h-8 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left text-[12.5px] font-medium leading-none",
        "transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
        destructive
          ? "text-[var(--chat-danger)] hover:bg-[color-mix(in_srgb,var(--chat-danger)_10%,transparent)]"
          : "text-[var(--chat-muted-strong)] hover:bg-[var(--sidebar-row-hover)] hover:text-[var(--chat-text)]",
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-75" />
      <span className="truncate">{label}</span>
    </button>
  );
}

interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
}
