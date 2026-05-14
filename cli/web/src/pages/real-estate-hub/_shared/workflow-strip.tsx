import type { ComponentType } from "react";

export function WorkflowStrip({
  items,
}: {
  items: Array<{
    icon?: ComponentType<{ className?: string }>;
    label: string;
    value: string | number;
  }>;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-1 gap-y-1 px-1 py-1 text-sm text-muted-foreground">
      {items.map((item, i) => (
        <span key={item.label} className="inline-flex items-baseline gap-1">
          {i > 0 && <span aria-hidden="true" className="mx-1.5 text-border">·</span>}
          <span className="font-medium tabular-nums text-foreground">{item.value}</span>
          <span>{item.label}</span>
        </span>
      ))}
    </div>
  );
}
