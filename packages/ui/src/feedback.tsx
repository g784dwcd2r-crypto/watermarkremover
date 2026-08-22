"use client";

import * as React from "react";

import { cn } from "./utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-[var(--radius-md)] bg-[var(--color-paper-sunken)]", className)}
      aria-hidden="true"
      {...props}
    />
  );
}

export function VisuallyHidden({ children }: { children: React.ReactNode }) {
  return <span className="sr-only">{children}</span>;
}

/**
 * A polite live region for status announcements.
 *
 * Rendered once near the top of the app so processing updates from anywhere in
 * the tree land in a single, predictable place for screen readers.
 */
export function LiveRegion({ message, assertive = false }: { message: string; assertive?: boolean }) {
  return (
    <div
      role="status"
      aria-live={assertive ? "assertive" : "polite"}
      aria-atomic="true"
      className="sr-only"
    >
      {message}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
  icon?: React.ElementType;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-[var(--color-line-strong)] bg-[var(--color-paper-raised)] px-6 py-12 text-center">
      {Icon ? <Icon className="size-8 text-[var(--color-ink-subtle)]" aria-hidden="true" /> : null}
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-[var(--color-ink)]">{title}</p>
        <p className="mx-auto max-w-md text-sm text-[var(--color-ink-muted)]">{description}</p>
      </div>
      {action}
    </div>
  );
}
