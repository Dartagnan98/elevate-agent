// Seed data for the Elevate Agent admin dashboard.
// Ported from /tmp/elevate-design/src/data.jsx — will be replaced with real API data.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NavItem = {
  id: string;
  label: string;
  icon: string;
  badge?: string;
};

export type AutomationStatus = "live" | "warn" | "paused" | "ok";

export type Automation = {
  id: string;
  name: string;
  status: AutomationStatus;
  age: string | null;
  expandable?: boolean;
};

export type SessionStatus =
  | "working"
  | "needs-perms"
  | "done"
  | "inactive"
  | "error";

export type SessionGroup = "today" | "yesterday" | "earlier";

export type Session = {
  id: string;
  title: string;
  preview: string;
  source: string;
  age: string;
  group: SessionGroup;
  status: SessionStatus;
  pinned?: boolean;
  active?: boolean;
};

export type MockUser = {
  email: string;
  name: string;
  role: string;
  initial: string;
  gatewayState: "running" | "starting" | "failed";
  activeSessions: number;
  theme: "dark" | "light";
  locale: string;
  hasUpdate: boolean;
};

export type SourceMeta = {
  icon: string;
  label: string;
};

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

export const NAV_REAL_ESTATE: NavItem[] = [
  { id: "today",  label: "Today",        icon: "Home",      badge: "4" },
  { id: "leads",  label: "Leads",        icon: "Users",     badge: "12" },
  { id: "admin",  label: "Admin",        icon: "Briefcase", badge: "3" },
  { id: "social", label: "Social Media", icon: "Megaphone" },
];

export const NAV_AGENT: NavItem[] = [
  { id: "hub",    label: "Agent Hub", icon: "Bot" },
  { id: "tasks",  label: "Tasks",     icon: "ListChecks", badge: "2" },
  { id: "memory", label: "Memory",    icon: "Brain" },
  { id: "skills", label: "Skills",    icon: "Puzzle" },
];

export const NAV_TOOLS: NavItem[] = [
  { id: "analytics", label: "Analytics",     icon: "BarChart" },
  { id: "logs",      label: "Logs",          icon: "FileText" },
  { id: "keys",      label: "Keys",          icon: "KeyRound" },
  { id: "docs",      label: "Documentation", icon: "BookOpen" },
];

// ---------------------------------------------------------------------------
// Sidebar automations
// Status drives the leading icon:
//   live   -> clock        warn   -> alert triangle
//   paused -> pause        ok     -> check (rare; default green dot)
// ---------------------------------------------------------------------------

export const MOCK_AUTOMATIONS: Automation[] = [
  { id: "a1",  name: "Memory maintenance benchmark",       status: "live",   age: "14h" },
  { id: "a2",  name: "Elevate memory maintenance smoke",   status: "warn",   age: null },
  { id: "a3",  name: "New Outreach",                       status: "warn",   age: null,  expandable: true },
  { id: "a4",  name: "Hot Leads Watcher",                  status: "warn",   age: null,  expandable: true },
  { id: "a5",  name: "Social Content Engine",              status: "live",   age: "5d",  expandable: true },
  { id: "a6",  name: "Follow-ups",                         status: "live",   age: "1h",  expandable: true },
  { id: "a7",  name: "Private Searches",                   status: "warn",   age: null,  expandable: true },
  { id: "a8",  name: "Gmail Doc Router",                   status: "paused", age: null },
  { id: "a9",  name: "Seller Update",                      status: "paused", age: null },
  { id: "a10", name: "Market Stats Watcher",               status: "paused", age: null },
];

// ---------------------------------------------------------------------------
// Sessions -- mix of statuses, grouped by recency
// ---------------------------------------------------------------------------

export const MOCK_SESSIONS: Session[] = [
  { id: "s1",  title: "Run source connector: Xposure MLS",                   preview: "Fetching 47 new listings · 12/47 done",                       source: "cron",     age: "2m",  group: "today",     status: "working",     pinned: false },
  { id: "s2",  title: "Go into webforms and create a transaction",            preview: "Awaiting approval: write_contact · run_bash",                 source: "telegram", age: "14m", group: "today",     status: "needs-perms", pinned: false },
  { id: "s3",  title: "session persistence smoke test",                       preview: "Smoke test: pass — Session DB lookup is working.",             source: "cli",      age: "11h", group: "today",     status: "done",        pinned: true, active: true },
  { id: "s4",  title: "https://webforms.realtorlink.ca/ Upload listing",      preview: "Listing 4287 Ash Crescent uploaded.",                              source: "cli",      age: "11h", group: "today",     status: "done" },
  { id: "s5",  title: "MLS Per-Listing Engagement — overnight digest",   preview: "127 views, 8 saves across 23 active listings.",                    source: "cron",     age: "16h", group: "today",     status: "done" },
  { id: "s6",  title: "Source connector: MLS Per-Listing",                    preview: "Sync complete — no errors.",                                   source: "cron",     age: "16h", group: "today",     status: "inactive" },
  { id: "s7",  title: "Generate CMA — 4287 Ash Crescent",               preview: "Failed: comparable data missing for V8X.",                          source: "cli",      age: "18h", group: "yesterday", status: "error" },
  { id: "s8",  title: "Source connector: Xposure MLS",                        preview: "Sync window closed at 21:04.",                                     source: "cron",     age: "1d",  group: "yesterday", status: "inactive" },
  { id: "s9",  title: "Draft follow-up: Marcus Greenwood",                    preview: "Approved · queued for 9:00 AM send.",                         source: "telegram", age: "1d",  group: "yesterday", status: "done" },
  { id: "s10", title: "Overnight automation — buyer watchlist refresh",   preview: "Loop terminated cleanly at 04:12.",                                source: "cron",     age: "2d",  group: "earlier",   status: "inactive" },
  { id: "s11", title: "Refactor lead-routing prompt v3",                      preview: "Saved 2 prompt variants for A/B.",                                 source: "cli",      age: "3d",  group: "earlier",   status: "inactive" },
  { id: "s12", title: "Discord ops bridge → relay test",                 preview: "12 messages relayed; 1 dropped.",                                  source: "discord",  age: "4d",  group: "earlier",   status: "inactive" },
];

// ---------------------------------------------------------------------------
// User popup / system state
// ---------------------------------------------------------------------------

export const MOCK_USER: MockUser = {
  email: "dartagnan@ctrlstrategies.com",
  name: "dartagnan",
  role: "Builder · Elevation HQ",
  initial: "D",
  gatewayState: "running",
  activeSessions: 2,
  theme: "dark",
  locale: "EN",
  hasUpdate: true,
};

// ---------------------------------------------------------------------------
// Source icons (cli / telegram / cron / discord)
// ---------------------------------------------------------------------------

export const SOURCE_META: Record<string, SourceMeta> = {
  cli:      { icon: "Terminal",  label: "cli" },
  telegram: { icon: "Telegram",  label: "telegram" },
  cron:     { icon: "Cron",      label: "cron" },
  discord:  { icon: "Discord",   label: "discord" },
  slack:    { icon: "Globe",     label: "slack" },
};
