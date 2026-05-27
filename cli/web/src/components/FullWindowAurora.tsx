import { createPortal } from "react-dom";
import { Loader2 } from "lucide-react";
import { useTheme } from "@/themes/context";

export function FullWindowAurora({
  label,
  title = "Starting Elevate",
  subtitle = "Bringing the local agent runtime online.",
}: {
  label: string;
  title?: string;
  subtitle?: string;
}) {
  const { themeName } = useTheme();
  const logoSrc =
    themeName === "light" ? "/elevateos-wordmark.png" : "/elevateos-wordmark-dark.png";
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      role="status"
      aria-live="polite"
      className="onboarding-overlay fixed inset-0 z-[150] flex items-center justify-center overflow-hidden bg-background px-6 py-10"
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex flex-col items-center text-center">
        <div className="onboarding-rise flex h-7 items-center">
          <img
            src={logoSrc}
            alt="Elevation"
            className="h-6 w-auto object-contain"
            draggable={false}
          />
        </div>
        <div className="onboarding-rise-delay-1 mt-7 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </div>
        <h2 className="onboarding-rise-delay-2 mt-2 text-[26px] font-medium leading-[1.1] tracking-tight text-foreground">
          {title}
        </h2>
        <p className="onboarding-rise-delay-3 mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground">
          {subtitle}
        </p>
        <Loader2 className="onboarding-rise-delay-3 mt-6 h-4 w-4 animate-spin text-muted-foreground/70" />
      </div>
    </div>,
    document.body,
  );
}
