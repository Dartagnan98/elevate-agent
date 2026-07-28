import { useEffect, useState } from "react";

// Shared phone-width detector for the admin surfaces whose layouts are driven by
// inline styles (the CMA / Offer Kit / Listing Kit wizards). CSS media queries
// can't override inline styles, so those components reflow their fixed-column
// grids and no-wrap stepper rows off this hook instead. Class-based surfaces
// (the modal chrome, board, KPIs) stay in admin.css media queries.
//
// 640px matches the phone breakpoint already used in admin.css. SSR-safe: falls
// back to false when there's no window.
export function useIsMobile(breakpoint = 640): boolean {
  const query = `(max-width: ${breakpoint}px)`;
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window !== "undefined" && "matchMedia" in window
      ? window.matchMedia(query).matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || !("matchMedia" in window)) return;
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    // Sync once in case the width changed between render and effect.
    setIsMobile(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return isMobile;
}

export default useIsMobile;
