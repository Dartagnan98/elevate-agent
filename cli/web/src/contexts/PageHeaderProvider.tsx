import { useLayoutEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { PanelLeftOpen } from "lucide-react";
import { PageHeaderContext } from "./page-header-context";
import { resolvePageTitle } from "@/lib/resolve-page-title";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

const DRAG_REGION = { WebkitAppRegion: "drag" } as CSSProperties;
const NO_DRAG_REGION = { WebkitAppRegion: "no-drag" } as CSSProperties;

export function PageHeaderProvider({
  children,
  pluginTabs,
  sidebarCollapsed = false,
  onShowSidebar,
}: {
  children: ReactNode;
  pluginTabs: { path: string; label: string }[];
  sidebarCollapsed?: boolean;
  onShowSidebar?: () => void;
}) {
  const { pathname } = useLocation();
  const { t } = useI18n();
  const [titleOverride, setTitleOverride] = useState<ReactNode | null>(null);
  const [beforeTitle, setBeforeTitle] = useState<ReactNode>(null);
  const [afterTitle, setAfterTitle] = useState<ReactNode>(null);
  const [end, setEnd] = useState<ReactNode>(null);

  // Clear any per-page title / toolbar slots when the path changes. Child routes
  // re-fill these on mount via usePageHeader.
  /* eslint-disable react-hooks/set-state-in-effect */
  useLayoutEffect(() => {
    setTitleOverride(null);
    setBeforeTitle(null);
    setAfterTitle(null);
    setEnd(null);
  }, [pathname]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const defaultTitle = useMemo(
    () => resolvePageTitle(pathname, t, pluginTabs),
    [pathname, t, pluginTabs],
  );
  const displayTitle: ReactNode = titleOverride ?? defaultTitle;

  const isConfigRoute = pathname === "/config" || pathname === "/config/";
  const isChatRoute = pathname === "/" || pathname.startsWith("/chat");

  const value = useMemo(
    () => ({
      setAfterTitle,
      setBeforeTitle,
      setEnd,
      setTitle: setTitleOverride,
      sidebarCollapsed,
      onShowSidebar,
    }),
    [sidebarCollapsed, onShowSidebar],
  );

  return (
    <PageHeaderContext.Provider value={value}>
      <div className="flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden">
        {!isConfigRoute && !isChatRoute && (
          <header
            className={cn(
              "z-1 w-full shrink-0",
              "box-border",
              isChatRoute ? "h-11 min-h-11" : "h-16 min-h-16",
              isChatRoute ? "bg-[var(--chat-bg)]" : "bg-background",
              "overflow-hidden",
            )}
            role="banner"
            style={DRAG_REGION}
          >
            <div
              className={cn(
                "flex h-full w-full min-w-0 items-center gap-4",
                isChatRoute ? "py-1.5 px-4 sm:px-6" : "py-3 pr-5 sm:pr-10",
                !isChatRoute && (sidebarCollapsed ? "pl-20" : "pl-5 sm:pl-10"),
              )}
            >
              {sidebarCollapsed && onShowSidebar && (
                <button
                  type="button"
                  onClick={onShowSidebar}
                  aria-label="Show sidebar"
                  style={NO_DRAG_REGION}
                  className={cn(
                    "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                    "text-muted-foreground hover:text-foreground hover:bg-muted transition-colors",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  )}
                >
                  <PanelLeftOpen className="h-3.5 w-3.5" />
                </button>
              )}

              {isChatRoute ? (
                <div
                  className="mx-auto flex w-full min-w-0 max-w-[52rem] items-center gap-2 sm:gap-3"
                  style={NO_DRAG_REGION}
                >
                  {beforeTitle}
                  <h1 className="min-w-0 truncate text-[0.95rem] font-semibold leading-6 tracking-[-0.005em] text-[var(--chat-text)]">
                    {displayTitle}
                  </h1>
                  {end}
                  {afterTitle}
                </div>
              ) : (
                <>
                  <div className="flex min-w-0 flex-1 items-center gap-4">
                    <div
                      className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3"
                      style={NO_DRAG_REGION}
                    >
                      {beforeTitle}
                      <h1 className="min-w-0 truncate text-[0.95rem] font-semibold leading-6 tracking-[-0.005em] text-midground">
                        {displayTitle}
                      </h1>
                      {afterTitle}
                    </div>
                  </div>
                  {end ? (
                    <div
                      className="flex min-w-0 shrink-0 justify-end"
                      style={NO_DRAG_REGION}
                    >
                      {end}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </header>
        )}

        <main
          className={cn(
            "min-h-0 w-full min-w-0 flex-1 flex flex-col",
            isChatRoute
              ? "overflow-hidden"
              : "overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]",
          )}
        >
          {children}
        </main>
      </div>
    </PageHeaderContext.Provider>
  );
}
