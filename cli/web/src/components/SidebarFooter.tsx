import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

export function SidebarFooter() {
  const status = useSidebarStatus();
  const { t } = useI18n();

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-between gap-2",
        "px-3 py-2 lg:px-2 lg:py-1.5",
      )}
    >
      <Typography
        mondwest
        className="font-mono-ui text-[0.78rem] tabular-nums tracking-[0.06em] text-[var(--sidebar-text-muted)] lg:text-[0.72rem]"
      >
        {status?.version != null ? `v${status.version}` : "—"}
      </Typography>

      <a
        href="https://github.com/Dartagnan98/elevate-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "font-mondwest text-[0.76rem] tracking-[0.08em] text-[var(--sidebar-text-strong)] lg:text-[0.7rem]",
          "transition-opacity hover:opacity-90",
          "focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        )}
      >
        {t.app.footer.org}
      </a>
    </div>
  );
}
