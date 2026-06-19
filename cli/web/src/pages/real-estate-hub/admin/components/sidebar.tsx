
import { useState, useMemo, useEffect, useRef, type ComponentType, type SVGProps } from "react";
import {
  Home,
  Users,
  Briefcase,
  Megaphone,
  Bot,
  ListChecks,
  Brain,
  Puzzle,
  BarChart,
  FileText,
  KeyRound,
  BookOpen,
  Plus,
  Search,
  PanelLeft,
  Chevron,
  ChevronRight,
  ChevronUp,
  Settings,
  Sparkles,
  User,
  Moon,
  Sun,
  Globe,
  Refresh,
  Download,
  LogOut,
  AlertTriangle,
  Pause,
  Clock,
} from "../icons";
import {
  NAV_REAL_ESTATE,
  NAV_AGENT,
  NAV_TOOLS,
  MOCK_SESSIONS,
  MOCK_AUTOMATIONS,
  MOCK_USER,
} from "../data";
import type { NavItem, Automation, Session } from "../data";

// ---------------------------------------------------------------------------
// Icon lookup -- data stores icon names as strings; resolve to components
// ---------------------------------------------------------------------------

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

const ICON_MAP: Record<string, IconComponent> = {
  Home,
  Users,
  Briefcase,
  Megaphone,
  Bot,
  ListChecks,
  Brain,
  Puzzle,
  BarChart,
  FileText,
  KeyRound,
  BookOpen,
  AlertTriangle,
  Pause,
  Clock,
};

function resolveIcon(name: string): IconComponent {
  return ICON_MAP[name] ?? Home;
}

// ---------------------------------------------------------------------------
// StatusDot
// ---------------------------------------------------------------------------

export function StatusDot({ status }: { status: string }) {
  if (status === "working") {
    return (
      <div className="dots-working" aria-label="working" role="img">
        <span></span><span></span><span></span>
      </div>
    );
  }
  const cls =
    status === "done"        ? "dot done" :
    status === "needs-perms" ? "dot warn" :
    status === "error"       ? "dot error" :
                               "dot idle";
  return <div className={cls} aria-label={status} role="img" />;
}

function activateOnEnterSpace(
  event: React.KeyboardEvent<HTMLElement>,
  onActivate: () => void,
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onActivate();
  }
}

// ---------------------------------------------------------------------------
// SectionLabel
// ---------------------------------------------------------------------------

function SectionLabel({
  label,
  collapsed,
  onToggle,
  badge,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  badge?: React.ReactNode;
}) {
  return (
    <div
      className={"section-label" + (collapsed ? " collapsed" : "")}
      onClick={onToggle}
      onKeyDown={(event) => activateOnEnterSpace(event, onToggle)}
      role="button"
      tabIndex={0}
    >
      <Chevron />
      <span>{label}</span>
      {badge && <span className="section-badge">{badge}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NavRow
// ---------------------------------------------------------------------------

function NavRow({
  item,
  active,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  onClick: () => void;
}) {
  const Icon = resolveIcon(item.icon);
  return (
    <div
      className={"nav-row" + (active ? " active" : "")}
      onClick={onClick}
      onKeyDown={(event) => activateOnEnterSpace(event, onClick)}
      role="button"
      tabIndex={0}
    >
      <Icon />
      <span>{item.label}</span>
      {item.badge && <span className="nav-badge">{item.badge}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SessionRow
// ---------------------------------------------------------------------------

function SessionRow({
  session,
  active,
  onClick,
}: {
  session: Session;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div
      className={"session-row" + (active ? " active" : "")}
      data-status={session.status}
      onClick={onClick}
      onKeyDown={(event) => activateOnEnterSpace(event, onClick)}
      role="button"
      tabIndex={0}
      title={session.title}
    >
      <div className="status-cell">
        <StatusDot status={session.status} />
      </div>
      <div className="title">{session.title}</div>
      <div className="age">{session.age}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SessionGroup
// ---------------------------------------------------------------------------

function SessionGroup({
  label,
  sessions,
  activeId,
  onSelect,
}: {
  label: string;
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  if (!sessions.length) return null;
  return (
    <>
      <div className="session-group-label">{label}</div>
      <div className="session-list">
        {sessions.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            active={s.id === activeId}
            onClick={() => onSelect(s.id)}
          />
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// AutomationRow
// ---------------------------------------------------------------------------

function AutomationRow({
  auto,
  active,
  onClick,
}: {
  auto: Automation;
  active: boolean;
  onClick: () => void;
}) {
  const Icon =
    auto.status === "warn"   ? AlertTriangle :
    auto.status === "paused" ? Pause :
                               Clock;
  const trailing =
    auto.status === "paused" ? <span className="auto-trail paused">paused</span> :
    auto.age                 ? <span className="auto-trail">{auto.age}</span> :
                               <span className="auto-trail dash">&mdash;</span>;
  return (
    <div
      className={"auto-row" + (active ? " active" : "")}
      data-status={auto.status}
      onClick={onClick}
      onKeyDown={(event) => activateOnEnterSpace(event, onClick)}
      role="button"
      tabIndex={0}
      title={auto.name}
    >
      <Icon />
      <span className="title">{auto.name}</span>
      {trailing}
      {auto.expandable && <ChevronRight className="auto-chev" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserMenu (popup above the user pill)
// ---------------------------------------------------------------------------

function UserMenu({ onClose: _onClose }: { onClose: () => void }) {
  void _onClose;
  const u = MOCK_USER;

  const [theme, setTheme] = useState(u.theme);
  const [locale, setLocale] = useState(u.locale);

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  return (
    <div className="user-menu" onClick={stop} role="menu">
      <div className="user-menu-email">{u.email}</div>

      <div className="user-menu-section">
        <button className="user-menu-row" role="menuitem">
          <Settings /><span>Settings</span>
        </button>
        <button className="user-menu-row" role="menuitem">
          <Sparkles /><span>Run onboarding</span>
        </button>
        <button className="user-menu-row" role="menuitem">
          <User /><span>Account</span>
        </button>
      </div>

      <div className="user-menu-section">
        <div className="user-menu-toggles">
          <button
            className={"user-menu-toggle" + (theme === "dark" ? " active" : "")}
            onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Moon /> : <Sun />}
            <span>{theme === "dark" ? "Dark" : "Light"}</span>
          </button>
          <button
            className="user-menu-toggle"
            onClick={() => setLocale((l) => l === "EN" ? "中文" : "EN")}
          >
            <Globe />
            <span>{locale}</span>
          </button>
        </div>
      </div>

      <div className="user-menu-section system">
        <div className="user-menu-status">
          <span className="dim">Gateway</span>
          <span className={u.gatewayState === "running" ? "ok" : "warn"}>
            {u.gatewayState === "running" ? "● running" : "● " + u.gatewayState}
          </span>
        </div>
        <div className="user-menu-status">
          <span className="dim">Active sessions</span>
          <span>{u.activeSessions}</span>
        </div>
        <button className="user-menu-row" role="menuitem">
          <Refresh /><span>Restart gateway</span>
        </button>
        <button className="user-menu-row" role="menuitem">
          <Download /><span>Update Elevation</span>
          {u.hasUpdate && <span className="user-menu-tag">new</span>}
        </button>
      </div>

      <div className="user-menu-section">
        <button className="user-menu-row danger" role="menuitem">
          <LogOut /><span>Sign out</span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserPill
// ---------------------------------------------------------------------------

function UserPill() {
  const u = MOCK_USER;
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="user-pill-wrap" ref={wrapRef}>
      {open && <UserMenu onClose={() => setOpen(false)} />}
      <div
        className={"user-pill" + (open ? " open" : "")}
        role="button"
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(event) => activateOnEnterSpace(event, () => setOpen((o) => !o))}
      >
        <div className="avatar">{u.initial}</div>
        <div className="who">
          <div className="name">{u.name}</div>
          <div className="role">{u.role}</div>
        </div>
        <ChevronUp className={"user-chev" + (open ? " open" : "")} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar props
// ---------------------------------------------------------------------------

interface SidebarProps {
  activeNav: string;
  onNavSelect: (id: string) => void;
  activeSessionId: string | null;
  onSessionSelect: (id: string) => void;
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({ activeNav, onNavSelect, activeSessionId, onSessionSelect }: SidebarProps) {
  const [collapsed, setCollapsed] = useState({
    realEstate: false,
    agent: false,
    chats: false,
    automations: false,
    tools: false,
  });
  const toggle = (k: keyof typeof collapsed) =>
    setCollapsed((c) => ({ ...c, [k]: !c[k] }));
  const [activeAuto, setActiveAuto] = useState("a10");

  const grouped = useMemo(
    () => ({
      today: MOCK_SESSIONS.filter((s) => s.group === "today"),
      yesterday: MOCK_SESSIONS.filter((s) => s.group === "yesterday"),
      earlier: MOCK_SESSIONS.filter((s) => s.group === "earlier"),
    }),
    [],
  );

  const liveAutomations = MOCK_AUTOMATIONS.filter((a) => a.status === "live").length;

  return (
    <div className="sidebar-shell">
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="lights">
            <div className="light close"></div>
            <div className="light min"></div>
            <div className="light max"></div>
          </div>
          <div className="tools">
            <button className="icon-btn" type="button" aria-label="Collapse sidebar" title="Collapse sidebar">
              <PanelLeft aria-hidden="true" />
            </button>
            <button className="icon-btn" type="button" aria-label="Search" title="Search (&#x2318;K)">
              <Search aria-hidden="true" />
            </button>
          </div>
        </div>

        <button className="new-chat" type="button">
          <Plus />
          <span>New chat</span>
          <span className="kbd">&#x2318;N</span>
        </button>

        <div className="sidebar-scroll">
          {/* Real estate */}
          <div className="section">
            <SectionLabel
              label="Real estate"
              collapsed={collapsed.realEstate}
              onToggle={() => toggle("realEstate")}
            />
            {!collapsed.realEstate &&
              NAV_REAL_ESTATE.map((item) => (
                <NavRow
                  key={item.id}
                  item={item}
                  active={activeNav === item.id}
                  onClick={() => onNavSelect(item.id)}
                />
              ))}
          </div>

          {/* Agent */}
          <div className="section">
            <SectionLabel
              label="Agent"
              collapsed={collapsed.agent}
              onToggle={() => toggle("agent")}
            />
            {!collapsed.agent &&
              NAV_AGENT.map((item) => (
                <NavRow
                  key={item.id}
                  item={item}
                  active={activeNav === item.id}
                  onClick={() => onNavSelect(item.id)}
                />
              ))}
          </div>

          {/* Chats */}
          <div className="section">
            <SectionLabel
              label="Chats"
              collapsed={collapsed.chats}
              onToggle={() => toggle("chats")}
            />
            {!collapsed.chats && (
              <>
                <SessionGroup
                  label="Today"
                  sessions={grouped.today}
                  activeId={activeSessionId}
                  onSelect={onSessionSelect}
                />
                <SessionGroup
                  label="Yesterday"
                  sessions={grouped.yesterday}
                  activeId={activeSessionId}
                  onSelect={onSessionSelect}
                />
                <SessionGroup
                  label="Earlier"
                  sessions={grouped.earlier}
                  activeId={activeSessionId}
                  onSelect={onSessionSelect}
                />
              </>
            )}
          </div>

          {/* Automations */}
          <div className="section">
            <SectionLabel
              label="Automations"
              collapsed={collapsed.automations}
              onToggle={() => toggle("automations")}
              badge={
                <>
                  <span className="dim">{MOCK_AUTOMATIONS.length}</span>
                  <span className="live-ind">
                    <span className="dot"></span>
                    {liveAutomations} live
                  </span>
                </>
              }
            />
            {!collapsed.automations && (
              <div className="auto-list">
                {MOCK_AUTOMATIONS.map((a) => (
                  <AutomationRow
                    key={a.id}
                    auto={a}
                    active={a.id === activeAuto}
                    onClick={() => setActiveAuto(a.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Tools */}
          <div className="section">
            <SectionLabel
              label="Tools"
              collapsed={collapsed.tools}
              onToggle={() => toggle("tools")}
            />
            {!collapsed.tools &&
              NAV_TOOLS.map((item) => (
                <NavRow
                  key={item.id}
                  item={item}
                  active={activeNav === item.id}
                  onClick={() => onNavSelect(item.id)}
                />
              ))}
          </div>
        </div>

        <div className="sidebar-foot">
          <UserPill />
        </div>
      </aside>
    </div>
  );
}

export default Sidebar;
