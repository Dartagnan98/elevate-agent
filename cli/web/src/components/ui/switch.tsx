import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type SwitchProps = {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  className?: string;
  disabled?: boolean;
  id?: string;
} & Pick<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "aria-labelledby" | "title">;

export function Switch({
  checked,
  onCheckedChange,
  className,
  disabled,
  id,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  title,
}: SwitchProps) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      title={title}
      disabled={disabled}
      className={cn(
        "peer inline-flex h-[36px] w-[56px] shrink-0 cursor-pointer items-center rounded-full border transition-colors md:h-5 md:w-9",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary border-primary" : "bg-card border-border",
        className,
      )}
      onClick={() => onCheckedChange(!checked)}
    >
      <span
        className={cn(
          "pointer-events-none block h-6 w-6 rounded-full transition-transform md:h-3.5 md:w-3.5",
          checked
            ? "translate-x-[26px] bg-primary-foreground md:translate-x-4"
            : "translate-x-1 bg-muted-foreground md:translate-x-0.5",
        )}
      />
    </button>
  );
}
