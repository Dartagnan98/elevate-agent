import type { Translations } from "@/i18n/types";

const BUILTIN: Record<string, keyof Translations["app"]["nav"]> = {
  "/chat": "chat",
  "/project": "project",
  "/sessions": "sessions",
  "/analytics": "analytics",
  "/logs": "logs",
  "/cron": "cron",
  "/skills": "skills",
  "/config": "config",
  "/env": "keys",
  "/docs": "documentation",
};

const ROUTE_TITLES: Record<string, string> = {
  "/": "Today",
  "/today": "Today",
  "/leads": "Leads",
  "/admin": "Admin",
  "/listings": "Admin",
  "/deals": "Admin",
  "/admin/templates": "Templates",
  "/social-media": "Social Media",
  "/marketing": "Social Media",
  "/overview": "Overview",
  "/hub": "Agent Hub",
  "/experiments": "Experiments",
  "/tasks": "Tasks",
  "/approvals": "Approvals",
  "/comms": "Comms",
  "/activity": "Activity",
  "/memory": "Memory graph",
  "/desktop-setup": "Desktop Setup",
  "/agent-onboarding": "Agent Onboarding",
  "/config": "Settings",
  "/heartbeat": "Automations",
};

export function resolvePageTitle(
  pathname: string,
  t: Translations,
  pluginTabs: { path: string; label: string }[],
): string {
  const normalized = pathname.replace(/\/$/, "") || "/";
  const title = ROUTE_TITLES[normalized];
  if (title) {
    return title;
  }
  const plugin = pluginTabs.find((p) => p.path === normalized);
  if (plugin) {
    return plugin.label;
  }
  const key = BUILTIN[normalized];
  if (key) {
    return t.app.nav[key];
  }
  return t.app.webUi;
}
