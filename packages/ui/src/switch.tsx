"use client";

import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as React from "react";

import { cn } from "./utils";

export function Switch({
  id,
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
  className,
  accessibleLabel,
}: {
  id: string;
  label: React.ReactNode;
  description?: React.ReactNode;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled?: boolean;
  className?: string;
  /** Required when `label` is empty, so the switch is never a nameless button. */
  accessibleLabel?: string;
}) {
  const hasVisibleLabel = Boolean(label);
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className={cn("flex flex-col gap-0.5", !hasVisibleLabel && "sr-only")}>
        <label htmlFor={id} className="text-sm font-medium text-[var(--color-ink)]">
          {hasVisibleLabel ? label : accessibleLabel}
        </label>
        {description ? (
          <p id={`${id}-description`} className="text-xs text-[var(--color-ink-muted)]">
            {description}
          </p>
        ) : null}
      </div>
      <SwitchPrimitive.Root
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        aria-label={hasVisibleLabel ? undefined : accessibleLabel}
        aria-describedby={description ? `${id}-description` : undefined}
        className="relative h-6 w-11 shrink-0 rounded-full border border-transparent bg-[var(--color-line-strong)] transition-colors disabled:opacity-55 data-[state=checked]:bg-[var(--color-primary)]"
      >
        <SwitchPrimitive.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[22px]" />
      </SwitchPrimitive.Root>
    </div>
  );
}
