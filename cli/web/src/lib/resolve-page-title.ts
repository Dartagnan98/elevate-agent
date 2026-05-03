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

export function resolvePageTitle(
  pathname: string,
  t: Translations,
  pluginTabs: { path: string; label: string }[],
): string {
  const normalized = pathname.replace(/\/$/, "") || "/";
  if (normalized === "/") {
    return "Today";
  }
  if (normalized === "/today") {
    return "Today";
  }
  if (normalized === "/leads") {
    return "Leads";
  }
  if (normalized === "/admin") {
    return "Admin";
  }
  if (normalized === "/listings") {
    return "Admin";
  }
  if (normalized === "/deals") {
    return "Admin";
  }
  if (normalized === "/ads") {
    return "Ads";
  }
  if (normalized === "/social-media") {
    return "Social Media";
  }
  if (normalized === "/marketing") {
    return "Social Media";
  }
  if (normalized === "/tasks") {
    return "Tasks";
  }
  if (normalized === "/approvals") {
    return "Approvals";
  }
  if (normalized === "/memory") {
    return "Memory";
  }
  if (normalized === "/hub") {
    return "Agent Hub";
  }
  if (normalized === "/config") {
    return "Settings";
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
