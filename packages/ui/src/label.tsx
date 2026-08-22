"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";

import { cn } from "./utils";

export const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(function Label({ className, ...props }, ref) {
  return (
    <LabelPrimitive.Root
      ref={ref}
      className={cn("text-sm font-medium text-[var(--color-ink)]", className)}
      {...props}
    />
  );
});

/**
 * A labelled control with optional help and error text.
 *
 * The description and error are wired to the input through `aria-describedby`
 * by the caller passing `id`, so screen readers announce them with the field.
 */
export function Field({
  label,
  htmlFor,
  description,
  error,
  required,
  children,
  className,
}: {
  label: React.ReactNode;
  htmlFor: string;
  description?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="ml-1 text-[var(--color-danger)]" aria-hidden="true">
            *
          </span>
        ) : null}
      </Label>
      {description ? (
        <p id={`${htmlFor}-description`} className="text-xs text-[var(--color-ink-muted)]">
          {description}
        </p>
      ) : null}
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="text-xs text-[var(--color-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
