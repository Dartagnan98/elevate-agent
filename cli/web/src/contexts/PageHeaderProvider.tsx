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
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const [afterTitle, setAfterTitle] = useState<ReactNode>(null);
  const [end, setEnd] = useState<ReactNode>(null);

  // Clear any per-page title / toolbar slots when the path changes. Child routes
  // re-fill these on mount via usePageHeader.
  /* eslint-disable react-hooks/set-state-in-effect */
  useLayoutEffect(() => {
    setTitleOverride(null);
    setAfterTitle(null);
    setEnd(null);
  }, [pathname]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const defaultTitle = useMemo(
    () => resolvePageTitle(pathname, t, pluginTabs),
    [pathname, t, pluginTabs],
  );
  const displayTitle = titleOverride ?? defaultTitle;

  const isChatRoute = pathname === "/chat" || pathname === "/chat/";
  const isConfigRoute = pathname === "/config" || pathname === "/config/";

  const value = useMemo(
    () => ({
      setAfterTitle,
      setEnd,
      setTitle: setTitleOverride,
    }),
    [],
  );

  return (
    <PageHeaderContext.Provider value={value}>
      <div className="flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden">
        {!isChatRoute && !isConfigRoute && (
          <header
            className={cn(
              "z-1 w-full shrink-0",
              "box-border h-11 min-h-11",
              "bg-background",
              "overflow-hidden",
            )}
            role="banner"
            style={DRAG_REGION}
          >
            <div
              className={cn(
                "flex h-full w-full min-w-0 items-center gap-3 pr-3 sm:pr-6",
                sidebarCollapsed ? "pl-20" : "pl-3 sm:pl-6",
              )}
            >
              {sidebarCollapsed && onShowSidebar && (
                <button
                  type="button"
                  onClick={onShowSidebar}
                  aria-label="Show sidebar"
                  style={NO_DRAG_REGION}
                  className={cn(
                    "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                    "text-muted-foreground hover:text-foreground hover:bg-muted transition-colors",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  )}
                >
                  <PanelLeftOpen className="h-4 w-4" />
                </button>
              )}

              <div
                className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3"
                style={NO_DRAG_REGION}
              >
                <h1
                  className="min-w-0 truncate text-sm font-semibold tracking-normal text-midground"
                >
                  {displayTitle}
                </h1>
                {afterTitle}
              </div>

              {end ? (
                <div
                  className="flex min-w-0 shrink-0 justify-end"
                  style={NO_DRAG_REGION}
                >
                  {end}
                </div>
              ) : null}
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
