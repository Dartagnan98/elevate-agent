import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 font-sans text-[0.68rem] font-medium tracking-normal normal-case transition-colors",
  {
    variants: {
      variant: {
        default: "border-foreground/15 bg-foreground/8 text-foreground",
        secondary: "border-border/70 bg-secondary/80 text-secondary-foreground",
        destructive: "border-destructive/25 bg-destructive/12 text-destructive",
        outline: "border-border/70 bg-card/35 text-muted-foreground",
        success: "border-success/25 bg-success/12 text-success",
        warning: "border-warning/30 bg-warning/15 text-warning",
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
