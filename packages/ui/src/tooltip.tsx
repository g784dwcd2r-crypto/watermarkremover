"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as React from "react";

import { cn } from "./utils";

export const TooltipProvider = TooltipPrimitive.Provider;

/**
 * A tooltip for icon-only controls.
 *
 * The `label` is also applied as the trigger's accessible name, so the control
 * is never announced as an unlabelled button when the tooltip is not open.
 */
export function Tooltip({
  label,
  children,
  side = "bottom",
  shortcut,
}: {
  label: string;
  children: React.ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  shortcut?: string;
}) {
  // Radix requires a Provider ancestor. Nesting providers is supported, so the
  // component carries its own: a tooltip should not explode because a test or a
  // stray subtree forgot to wrap it.
  return (
    <TooltipPrimitive.Provider delayDuration={250}>
      <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 flex items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--color-ink)] px-2.5 py-1.5 text-xs text-[var(--color-paper)] shadow-md",
          )}
        >
          {label}
          {shortcut ? (
            <kbd className="rounded border border-white/25 px-1 font-mono text-[10px] uppercase">
              {shortcut}
            </kbd>
          ) : null}
          <TooltipPrimitive.Arrow className="fill-[var(--color-ink)]" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
