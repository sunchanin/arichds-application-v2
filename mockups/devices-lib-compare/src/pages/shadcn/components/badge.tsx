import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "border-[var(--border)] bg-[var(--secondary)] text-[var(--secondary-foreground)]",
        success: "border-transparent bg-emerald-50 text-emerald-700",
        destructive: "border-transparent bg-red-50 text-red-700",
        info: "border-transparent bg-sky-50 text-sky-700",
        warning: "border-transparent bg-amber-50 text-amber-700",
        outline: "border-[var(--border)] bg-white text-[var(--foreground)]",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
