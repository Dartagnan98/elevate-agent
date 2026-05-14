import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Moon, Sun } from "lucide-react";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { BUILTIN_THEMES, useTheme } from "@/themes";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * Compact light/dark picker mounted next to the language switcher in the
 * header.
 *
 * When placed at the bottom of a container (e.g. the sidebar rail), pass
 * `dropUp` so the menu opens above the trigger instead of clipping below
 * the viewport.
 */
export function ThemeSwitcher({ dropUp = false }: ThemeSwitcherProps) {
  const { themeName, availableThemes, setTheme } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        close();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  const current = availableThemes.find((th) => th.name === themeName);
  const label = current?.label ?? themeName;
  const ActiveIcon = themeName === "light" ? Sun : Moon;

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex h-8 items-center gap-2 rounded-lg border border-border px-2.5 text-[0.82rem]",
          "bg-card text-[var(--sidebar-text)] transition-colors hover:text-[var(--sidebar-text-active)]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
        title={t.theme?.switchTheme ?? "Switch theme"}
        aria-label={t.theme?.switchTheme ?? "Switch theme"}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <ActiveIcon className="h-4 w-4 text-[var(--sidebar-icon)]" />
        <Typography
          className="hidden text-[0.82rem] font-medium normal-case tracking-normal sm:inline"
        >
          {label}
        </Typography>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t.theme?.title ?? "Theme"}
          className={cn(
            "absolute z-50 min-w-[240px]",
            dropUp ? "left-0 bottom-full mb-1" : "right-0 top-full mt-1",
            "overflow-hidden rounded-md border border-border bg-card",
          )}
        >
          <div className="border-b border-border px-3 py-2">
            <Typography className="text-xs font-semibold normal-case text-muted-foreground">
              {t.theme?.title ?? "Theme"}
            </Typography>
          </div>

          {availableThemes.map((th) => {
            const isActive = th.name === themeName;
            const preset = BUILTIN_THEMES[th.name];

            return (
              <button
                key={th.name}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  setTheme(th.name);
                  close();
                }}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2 text-left transition-colors cursor-pointer",
                  "hover:bg-accent",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {preset ? (
                  <ThemeSwatch theme={preset.name} />
                ) : (
                  <PlaceholderSwatch />
                )}

                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <Typography
                    className="truncate text-sm font-medium normal-case tracking-normal"
                  >
                    {th.label}
                  </Typography>
                  {th.description && (
                    <Typography className="truncate text-xs normal-case tracking-normal text-muted-foreground">
                      {th.description}
                    </Typography>
                  )}
                </div>

                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 text-primary",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ThemeSwatch({ theme }: { theme: string }) {
  const preset = BUILTIN_THEMES[theme];
  if (!preset) return <PlaceholderSwatch />;
  const { background, midground, warmGlow } = preset.palette;
  return (
    <div
      aria-hidden
      className="flex h-5 w-10 shrink-0 overflow-hidden rounded-md border border-border"
    >
      <span className="flex-1" style={{ background: background.hex }} />
      <span className="flex-1" style={{ background: midground.hex }} />
      <span className="flex-1" style={{ background: warmGlow }} />
    </div>
  );
}

function PlaceholderSwatch() {
  return (
    <div
      aria-hidden
      className="h-5 w-10 shrink-0 rounded-md border border-dashed border-border"
    />
  );
}

interface ThemeSwitcherProps {
  dropUp?: boolean;
}
