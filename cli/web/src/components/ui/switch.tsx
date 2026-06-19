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
        "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary border-primary" : "bg-card border-border",
        className,
      )}
      onClick={() => onCheckedChange(!checked)}
    >
      <span
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full transition-transform",
          checked ? "translate-x-4 bg-primary-foreground" : "translate-x-0.5 bg-muted-foreground",
        )}
      />
    </button>
  );
}
