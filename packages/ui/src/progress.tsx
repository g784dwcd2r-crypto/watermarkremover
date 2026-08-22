"use client";

import * as React from "react";

import { cn } from "./utils";

/**
 * A determinate progress bar.
 *
 * The percentage is mirrored into a polite live region so screen-reader users
 * hear processing progress without the bar itself chattering on every frame.
 */
export function Progress({
  value,
  label,
  message,
  className,
  announceEvery = 10,
}: {
  value: number;
  label: string;
  message?: string;
  className?: string;
  announceEvery?: number;
}) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const [announced, setAnnounced] = React.useState(0);

  React.useEffect(() => {
    setAnnounced((previous) =>
      percent === 100 || percent - previous >= announceEvery ? percent : previous,
    );
  }, [percent, announceEvery]);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-[var(--color-ink)]">{label}</span>
        <span className="text-xs tabular-nums text-[var(--color-ink-muted)]">{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
        className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-paper-sunken)]"
      >
        <div
          className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
      {message ? <p className="text-xs text-[var(--color-ink-muted)]">{message}</p> : null}
      <p className="sr-only" aria-live="polite">
        {message ? `${message}. ` : ""}
        {announced}% complete
      </p>
    </div>
  );
}
