import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronUp, LogOut, Settings, User } from "lucide-react";
import { api } from "@/lib/api";
import type { LicenseStatusResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

export function SidebarUserPill() {
  const navigate = useNavigate();
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

  const tierLabel = license?.authenticated
    ? (license.tier === "builder" ? "Builder" : "Pro")
    : null;

  return (
    <div ref={ref} className="relative">
      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 right-0 mb-1 rounded-xl",
            "border border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]",
            "shadow-lg shadow-black/30",
            "animate-in fade-in slide-in-from-bottom-2 duration-150",
            "z-50 overflow-hidden",
          )}
        >
          <div className="px-3.5 pb-1 pt-3">
            <p className="truncate text-[0.78rem] font-medium text-[var(--sidebar-text-muted)]">
              {emailLabel}
            </p>
          </div>

          <div className="px-1.5 py-1">
            <button
              type="button"
              onClick={() => { navigate("/config"); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
              )}
            >
              <Settings className="h-4 w-4 text-[var(--sidebar-icon)]" />
              Settings
            </button>

            <button
              type="button"
              onClick={() => { navigate("/desktop-setup"); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
              )}
            >
              <User className="h-4 w-4 text-[var(--sidebar-icon)]" />
              Account
            </button>
          </div>

          <div className="flex items-center gap-2 border-t border-[var(--sidebar-border)] px-3.5 py-2">
            <ThemeSwitcher dropUp />
            <LanguageSwitcher />
          </div>

          {license?.authenticated && (
            <div className="border-t border-[var(--sidebar-border)] px-1.5 py-1">
              <button
                type="button"
                onClick={handleSignOut}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                  "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
                )}
              >
                <LogOut className="h-4 w-4 text-[var(--sidebar-icon)]" />
                Sign out
              </button>
            </div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left",
          "transition-colors hover:bg-[var(--sidebar-row-hover)]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          open && "bg-[var(--sidebar-row-hover)]",
        )}
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--sidebar-row)] text-[0.7rem] font-semibold uppercase text-[var(--sidebar-text-muted)]">
          {license?.authenticated && license.email
            ? license.email[0]
            : "?"}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[0.82rem] font-medium leading-tight text-[var(--sidebar-text-strong)]">
            {license?.authenticated && license.email
              ? license.email.split("@")[0]
              : "Not signed in"}
          </p>
          {tierLabel && (
            <p className="text-[0.68rem] leading-tight text-[var(--sidebar-text-muted)]">
              {tierLabel}
            </p>
          )}
        </div>
        <ChevronUp className={cn(
          "h-3.5 w-3.5 shrink-0 text-[var(--sidebar-icon-muted)] transition-transform",
          !open && "rotate-180",
        )} />
      </button>
    </div>
  );
}
