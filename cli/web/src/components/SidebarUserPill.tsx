import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  ChevronUp,
  Download,
  FileText,
  Globe,
  KeyRound,
  LogOut,
  RotateCw,
  Settings,
  Sparkles,
  User,
} from "lucide-react";
import { api } from "@/lib/api";
import type { LicenseStatusResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { useSystemActions } from "@/contexts/useSystemActions";
import { useI18n } from "@/i18n";

export function SidebarUserPill() {
  const navigate = useNavigate();
  const status = useSidebarStatus();
  const { activeAction, isBusy, isRunning, pendingAction, runAction, updateStatus } =
    useSystemActions();
  const { locale, setLocale } = useI18n();
  const [license, setLicense] = useState<LicenseStatusResponse | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api.getLicenseStatus().then(setLicense).catch(() => setLicense(null));
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener("elevate:auth-changed", handler);
    return () => window.removeEventListener("elevate:auth-changed", handler);
  }, [load]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", load);
    const tick = window.setInterval(load, 30_000);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", load);
      window.clearInterval(tick);
    };
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const handleSignOut = async () => {
    try {
      await api.logoutLicense();
      window.dispatchEvent(new Event("elevate:auth-changed"));
    } catch { /* ignore */ }
    setOpen(false);
  };

  const emailLabel = license?.authenticated
    ? license.email ?? "Signed in"
    : "Not signed in";
  const nameLabel = license?.authenticated && license.email
    ? license.email.split("@")[0]
    : "Not signed in";
  const initial = license?.authenticated && license.email
    ? license.email[0]
    : "?";
  const tierLabel = license?.authenticated
    ? (license.tier === "builder" ? "Builder" : "Pro")
    : "Local";

  const gatewayState = status?.gateway_state || (status?.gateway_running ? "running" : "stopped");
  const gatewayRunning = gatewayState === "running" || status?.gateway_running;
  const activeSessions = status?.active_sessions ?? 0;
  const hasUpdate = Boolean(updateStatus?.available);
  const updateBehind = updateStatus?.behind ?? 0;
  const desktopManagedUpdate =
    updateStatus?.error === "desktop_app_managed_update";
  const localeLabel = locale === "zh" ? "中文" : "EN";
  const restartBusy =
    pendingAction === "restart" || (activeAction === "restart" && isRunning);
  const updateBusy =
    pendingAction === "update" || (activeAction === "update" && isRunning);

  const runSystemAction = (action: "restart" | "update") => {
    if (isBusy && !(action === "restart" ? restartBusy : updateBusy)) return;
    void runAction(action);
  };

  return (
    <div ref={ref} className="user-pill-wrap">
      {open && (
        <div
          className="user-menu"
          onClick={(event) => event.stopPropagation()}
          role="menu"
        >
          <div className="user-menu-email">{emailLabel}</div>

          <div className="user-menu-section">
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/config"); setOpen(false); }}
            >
              <Settings />
              <span>Settings</span>
            </button>
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/agent-onboarding?run=1"); setOpen(false); }}
            >
              <Sparkles />
              <span>Run onboarding</span>
            </button>
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/desktop-setup"); setOpen(false); }}
            >
              <User />
              <span>Account</span>
            </button>
          </div>

          {/* Tools — moved here from the sidebar's Tools section. */}
          <div className="user-menu-section">
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/analytics"); setOpen(false); }}
            >
              <BarChart3 />
              <span>Analytics</span>
            </button>
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/logs"); setOpen(false); }}
            >
              <FileText />
              <span>Logs</span>
            </button>
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/env"); setOpen(false); }}
            >
              <KeyRound />
              <span>Keys</span>
            </button>
            <button
              type="button"
              className="user-menu-row"
              role="menuitem"
              onClick={() => { navigate("/docs"); setOpen(false); }}
            >
              <BookOpen />
              <span>Documentation</span>
            </button>
          </div>

          <div className="user-menu-section">
            <div className="user-menu-toggles">
              {/* Light mode removed — app is dark-only. */}
              <button
                type="button"
                className="user-menu-toggle"
                onClick={() => setLocale(locale === "en" ? "zh" : "en")}
              >
                <Globe />
                <span>{localeLabel}</span>
              </button>
            </div>
          </div>

          <div className="user-menu-section system">
            <div className="user-menu-status">
              <span className="dim">Gateway</span>
              <span className={gatewayRunning ? "ok" : "warn"}>
                {gatewayRunning ? "● running" : `● ${gatewayState}`}
              </span>
            </div>
            <div className="user-menu-status">
              <span className="dim">Active sessions</span>
              <span>{activeSessions}</span>
            </div>
            <button
              type="button"
              className="user-menu-row"
              disabled={isBusy && !restartBusy}
              role="menuitem"
              onClick={() => runSystemAction("restart")}
            >
              <RotateCw className={cn(restartBusy && "animate-spin")} />
              <span>{restartBusy ? "Restarting gateway" : "Restart gateway"}</span>
            </button>
            {!desktopManagedUpdate && (
              <button
                type="button"
                className="user-menu-row"
                disabled={isBusy && !updateBusy}
                role="menuitem"
                onClick={() => runSystemAction("update")}
              >
                <Download className={cn(updateBusy && "animate-pulse")} />
                <span>{updateBusy ? "Updating Elevate" : "Update Elevate"}</span>
                {hasUpdate && !updateBusy && (
                  <span className="user-menu-tag">
                    {updateBehind > 0 ? updateBehind : "new"}
                  </span>
                )}
              </button>
            )}
          </div>

          {license?.authenticated && (
            <div className="user-menu-section">
              <button
                type="button"
                className="user-menu-row danger"
                role="menuitem"
                onClick={handleSignOut}
              >
                <LogOut />
                <span>Sign out</span>
              </button>
            </div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={cn("user-pill", open && "open")}
      >
        <div className="avatar">{initial}</div>
        <div className="who">
          <div className="name">
            {nameLabel}
            {tierLabel ? <span className="role"> · {tierLabel}</span> : null}
          </div>
        </div>
        <ChevronUp className={cn("user-chev", open && "open")} />
      </button>
    </div>
  );
}
