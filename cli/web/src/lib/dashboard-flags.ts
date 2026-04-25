declare global {
  interface Window {
    /** Set true by the server only for `elevate dashboard --tui` (or ELEVATE_DASHBOARD_TUI=1). */
    __ELEVATE_DASHBOARD_EMBEDDED_CHAT__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`elevate dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__ === true;
}
