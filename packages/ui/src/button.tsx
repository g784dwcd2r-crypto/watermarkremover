"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] font-medium transition-colors disabled:pointer-events-none disabled:opacity-55 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--color-primary)] text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)]",
        secondary:
          "border border-[var(--color-line-strong)] bg-[var(--color-paper-raised)] text-[var(--color-ink)] hover:bg-[var(--color-paper-sunken)]",
        accent:
          "bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:brightness-95",
        ghost: "text-[var(--color-ink-muted)] hover:bg-[var(--color-paper-sunken)] hover:text-[var(--color-ink)]",
        danger: "bg-[var(--color-danger)] text-white hover:brightness-95",
        link: "text-[var(--color-primary)] underline underline-offset-4 hover:text-[var(--color-primary-hover)]",
      },
      size: {
        sm: "h-8 px-3 text-sm [&_svg]:size-4",
        md: "h-10 px-4 text-sm [&_svg]:size-4",
        lg: "h-12 px-6 text-base [&_svg]:size-5",
        icon: "size-9 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Renders a spinner and marks the control busy for assistive technology. */
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, loading = false, children, disabled, ...props },
  ref,
) {
  if (asChild) {
    // Slot forwards props onto exactly one child, so the spinner cannot be
    // injected here. `asChild` is used for links, which never show a spinner.
    return (
      <Slot ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props}>
        {children}
      </Slot>
    );
  }

  return (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <span
          className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      ) : null}
      {children}
    </button>
  );
});

export { buttonVariants };
