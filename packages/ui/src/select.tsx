"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "./utils";

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export function Select({
  id,
  label,
  value,
  options,
  onValueChange,
  hint,
  disabled,
  className,
  hideLabel,
}: {
  id: string;
  label: string;
  value: string;
  options: SelectOption[];
  onValueChange: (value: string) => void;
  hint?: string;
  disabled?: boolean;
  className?: string;
  hideLabel?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className={cn("text-sm font-medium text-[var(--color-ink)]", hideLabel && "sr-only")}>
        {label}
      </label>
      <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectPrimitive.Trigger
          id={id}
          aria-label={label}
          className="flex h-10 w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--color-line-strong)] bg-[var(--color-paper-raised)] px-3 text-sm text-[var(--color-ink)] disabled:opacity-60"
        >
          <SelectPrimitive.Value />
          <SelectPrimitive.Icon>
            <ChevronDown className="size-4 text-[var(--color-ink-subtle)]" aria-hidden="true" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            position="popper"
            sideOffset={6}
            className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-paper-raised)] shadow-[var(--shadow-panel)]"
          >
            <SelectPrimitive.Viewport className="p-1">
              {options.map((option) => (
                <SelectPrimitive.Item
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className="relative flex cursor-pointer select-none flex-col gap-0.5 rounded-[var(--radius-sm)] px-8 py-2 text-sm data-[highlighted:outline-none] data-[highlighted]:bg-[var(--color-primary-soft)] data-[disabled]:opacity-50"
                >
                  <SelectPrimitive.ItemIndicator className="absolute left-2 top-2.5">
                    <Check className="size-4 text-[var(--color-primary)]" aria-hidden="true" />
                  </SelectPrimitive.ItemIndicator>
                  <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                  {option.description ? (
                    <span className="text-xs text-[var(--color-ink-muted)]">{option.description}</span>
                  ) : null}
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
      {hint ? <p className="text-xs text-[var(--color-ink-muted)]">{hint}</p> : null}
    </div>
  );
}
