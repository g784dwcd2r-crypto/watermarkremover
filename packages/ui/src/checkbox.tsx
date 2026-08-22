"use client";

import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import * as React from "react";

import { cn } from "./utils";

export const Checkbox = React.forwardRef<
  React.ComponentRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(function Checkbox({ className, ...props }, ref) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        "peer size-5 shrink-0 rounded-[var(--radius-sm)] border border-[var(--color-line-strong)] bg-[var(--color-paper-raised)] data-[state=checked]:border-[var(--color-primary)] data-[state=checked]:bg-[var(--color-primary)] data-[state=checked]:text-[var(--color-on-primary)] disabled:opacity-55",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center">
        <Check className="size-3.5" aria-hidden="true" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});

/** A checkbox with its label and supporting copy, used for the consent gates. */
export function ConsentCheckbox({
  id,
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
}: {
  id: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-paper-sunken)] p-3">
      <Checkbox
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onCheckedChange(value === true)}
        aria-describedby={description ? `${id}-description` : undefined}
        className="mt-0.5"
      />
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium text-[var(--color-ink)]">
          {label}
        </label>
        {description ? (
          <p id={`${id}-description`} className="text-xs text-[var(--color-ink-muted)]">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}
