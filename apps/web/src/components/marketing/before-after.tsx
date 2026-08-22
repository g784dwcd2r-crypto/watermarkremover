"use client";

import { cn } from "@artrestore/ui";
import * as React from "react";

/**
 * A draggable before/after comparison.
 *
 * Keyboard accessible: the handle is a slider, so arrow keys move it and screen
 * readers announce the position. All demonstration assets are generated
 * procedurally by this repository, so nothing here carries third-party rights.
 */
export function BeforeAfter({
  beforeSrc,
  afterSrc,
  beforeLabel = "Before",
  afterLabel = "After",
  caption,
  className,
  initial = 0.5,
}: {
  beforeSrc: string;
  afterSrc: string;
  beforeLabel?: string;
  afterLabel?: string;
  caption?: React.ReactNode;
  className?: string;
  initial?: number;
}) {
  const [position, setPosition] = React.useState(initial);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const dragging = React.useRef(false);

  const updateFromClientX = React.useCallback((clientX: number) => {
    const element = containerRef.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    setPosition(Math.min(1, Math.max(0, (clientX - bounds.left) / bounds.width)));
  }, []);

  React.useEffect(() => {
    const move = (event: PointerEvent) => {
      if (dragging.current) updateFromClientX(event.clientX);
    };
    const stop = () => {
      dragging.current = false;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
  }, [updateFromClientX]);

  const percent = Math.round(position * 100);

  return (
    <figure className={cn("flex flex-col gap-3", className)}>
      <div
        ref={containerRef}
        className="relative select-none overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-paper-sunken)]"
        onPointerDown={(event) => {
          dragging.current = true;
          updateFromClientX(event.clientX);
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={afterSrc} alt={afterLabel} className="block w-full" draggable={false} />
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ clipPath: `inset(0 ${100 - percent}% 0 0)` }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={beforeSrc}
            alt={beforeLabel}
            className="block w-full"
            draggable={false}
            style={{ width: "100%" }}
          />
        </div>

        <div
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/90 shadow-[0_0_0_1px_rgba(0,0,0,0.25)]"
          style={{ left: `${percent}%` }}
          aria-hidden="true"
        />

        <input
          type="range"
          min={0}
          max={100}
          value={percent}
          aria-label={`Comparison position between ${beforeLabel} and ${afterLabel}`}
          onChange={(event) => setPosition(Number(event.target.value) / 100)}
          className="absolute inset-x-0 bottom-3 mx-auto w-[calc(100%-2rem)] cursor-ew-resize accent-[var(--color-primary)]"
        />

        <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-[var(--color-ink)]/75 px-2.5 py-1 text-xs font-medium text-white">
          {beforeLabel}
        </span>
        <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-[var(--color-primary)]/90 px-2.5 py-1 text-xs font-medium text-white">
          {afterLabel}
        </span>
      </div>
      {caption ? (
        <figcaption className="text-sm text-[var(--color-ink-muted)]">{caption}</figcaption>
      ) : null}
    </figure>
  );
}
