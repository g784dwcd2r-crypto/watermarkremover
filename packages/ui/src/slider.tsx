"use client";

import * as SliderPrimitive from "@radix-ui/react-slider";
import * as React from "react";

import { cn } from "./utils";

/** A labelled slider with a live numeric readout. */
export function Slider({
  id,
  label,
  value,
  min,
  max,
  step = 1,
  onValueChange,
  format,
  hint,
  disabled,
  className,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onValueChange: (value: number) => void;
  format?: (value: number) => string;
  hint?: string;
  disabled?: boolean;
  className?: string;
}) {
  const display = format ? format(value) : String(value);
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-[var(--color-ink)]">
          {label}
        </label>
        <span className="text-xs text-[var(--color-ink-muted)] tabular-nums">{display}</span>
      </div>
      <SliderPrimitive.Root
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={([next]) => onValueChange(next ?? value)}
        className="relative flex h-5 w-full touch-none items-center select-none"
      >
        <SliderPrimitive.Track className="relative h-1.5 w-full grow rounded-full bg-[var(--color-paper-sunken)]">
          <SliderPrimitive.Range className="absolute h-full rounded-full bg-[var(--color-primary)]" />
        </SliderPrimitive.Track>
        {/* Radix puts role="slider" on the thumb, so the accessible name and
            the value text belong there rather than on the root. */}
        <SliderPrimitive.Thumb
          id={id}
          aria-label={label}
          aria-valuetext={display}
          className="block size-4 rounded-full border-2 border-[var(--color-primary)] bg-[var(--color-paper-raised)] shadow-sm disabled:opacity-50"
        />
      </SliderPrimitive.Root>
      {hint ? <p className="text-xs text-[var(--color-ink-muted)]">{hint}</p> : null}
    </div>
  );
}
