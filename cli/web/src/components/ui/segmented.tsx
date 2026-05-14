import { cn } from "@/lib/utils";

export function Segmented<T extends string>({
  className,
  onChange,
  options,
  size = "sm",
  value,
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      className={cn(
        "inline-flex gap-0.5 rounded-sm bg-card border border-border p-0.5",
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;

        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "rounded-sm font-sans font-medium tracking-normal normal-case",
              "transition-colors cursor-pointer whitespace-nowrap",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
              size === "sm" && "h-7 px-2.5 text-xs",
              size === "md" && "h-8 px-3 text-xs",
              active
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function FilterGroup({
  children,
  className,
  label,
}: FilterGroupProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="text-xs font-medium tracking-normal normal-case text-muted-foreground/80">
        {label}
      </span>
      {children}
    </div>
  );
}

interface FilterGroupProps {
  children: React.ReactNode;
  className?: string;
  label: string;
}

interface SegmentedOption<T extends string> {
  label: string;
  value: T;
}

interface SegmentedProps<T extends string> {
  className?: string;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  size?: "sm" | "md";
  value: T;
}
