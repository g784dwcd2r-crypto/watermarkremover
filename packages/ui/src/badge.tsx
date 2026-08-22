import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--color-paper-sunken)] text-[var(--color-ink-muted)]",
        primary: "bg-[var(--color-primary-soft)] text-[var(--color-primary-hover)]",
        accent: "bg-[var(--color-accent-soft)] text-[var(--color-accent-text)]",
        success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
        warning: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
        danger: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
        info: "bg-[var(--color-info-soft)] text-[var(--color-info)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
