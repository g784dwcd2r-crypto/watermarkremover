"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as React from "react";

import { cn } from "./utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(function TabsList({ className, ...props }, ref) {
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-[var(--color-paper-sunken)] p-1",
        className,
      )}
      {...props}
    />
  );
});

export const TabsTrigger = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(function TabsTrigger({ className, ...props }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "rounded-[var(--radius-sm)] px-3 py-1.5 text-sm font-medium text-[var(--color-ink-muted)] transition-colors data-[state=active]:bg-[var(--color-paper-raised)] data-[state=active]:text-[var(--color-ink)] data-[state=active]:shadow-sm",
        className,
      )}
      {...props}
    />
  );
});

export const TabsContent = TabsPrimitive.Content;
