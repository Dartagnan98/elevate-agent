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
    return "Agent Hub";
  }
  if (normalized === "/hub") {
    return "Agent Hub";
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
