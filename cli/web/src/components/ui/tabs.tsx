import { useState } from "react";
import { cn } from "@/lib/utils";

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: (active: string, setActive: (v: string) => void) => React.ReactNode;
  className?: string;
}) {
  const [active, setActive] = useState(defaultValue);
  return <div className={cn("flex flex-col gap-4", className)}>{children(active, setActive)}</div>;
}

export function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "inline-flex h-9 items-center justify-start gap-0.5 rounded-full bg-card/70 p-0.5 text-muted-foreground shadow-[inset_0_0_0_1px_var(--chat-border)]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  active,
  value,
  onClick,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active: boolean; value: string }) {
  return (
    <button
      type="button"
      className={cn(
        "relative inline-flex h-8 items-center justify-center whitespace-nowrap rounded-full px-3 py-1.5 font-sans text-xs font-medium tracking-normal normal-case transition-all cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "bg-secondary text-foreground shadow-sm"
          : "hover:text-foreground",
        className,
      )}
      value={value}
      onClick={onClick}
      {...props}
    />
  );
}
