import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Ops-tool badge: transparent surface, opaque border, left-edge color strip
// for state. No palette-glow tints. Mono uppercase label is the signal.
const badgeVariants = cva(
  "relative inline-flex items-center rounded-sm font-mono-ui border bg-transparent pl-2.5 pr-2 py-0.5 text-[0.68rem] font-medium uppercase tracking-[0.06em] transition-colors before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[2px] before:rounded-l-sm",
  {
    variants: {
      variant: {
        default: "border-border text-foreground before:bg-border",
        secondary: "border-border text-muted-foreground before:bg-border",
        destructive: "border-border text-destructive before:bg-destructive",
        outline: "border-border text-muted-foreground before:bg-transparent",
        success: "border-border text-success before:bg-success",
        warning: "border-border text-warning before:bg-warning",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
