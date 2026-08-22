"use client";

import { cn } from "@artrestore/ui";
import * as React from "react";

import { useEditorStore } from "@/store/editor-store";

/**
 * Original / processed comparison.
 *
 * Four views because they answer different questions: the result alone, the two
 * side by side, a wipe for judging a boundary, and the difference map that
 * shows precisely which pixels the run touched.
 */
export function ComparisonView({
  originalUrl,
  processedUrl,
  differenceUrl,
  className,
}: {
  originalUrl: string | null;
  processedUrl: string | null;
  differenceUrl?: string | null;
  className?: string;
}) {
  const { comparison, sliderPosition, setSliderPosition, theme } = useEditorStore();
  const containerRef = React.useRef<HTMLDivElement>(null);

  const surface =
    theme === "dark" ? "bg-[var(--color-canvas-dark)]" : "bg-[var(--color-canvas-light)]";

  if (!processedUrl) {
    return (
      <div
        className={cn(
          "grid min-h-72 place-items-center rounded-[var(--radius-lg)] border border-[var(--color-line)] p-8 text-center text-sm text-[var(--color-ink-muted)]",
          surface,
          className,
        )}
      >
        Run a cleanup to see the before-and-after comparison.
      </div>
    );
  }

  if (comparison === "split") {
    return (
      <div className={cn("grid gap-3 sm:grid-cols-2", className)}>
        <Panel label="Original" src={originalUrl} surface={surface} />
        <Panel label="Processed" src={processedUrl} surface={surface} />
      </div>
    );
  }

  if (comparison === "difference") {
    return (
      <Panel
        label="Changed pixels"
        src={differenceUrl ?? processedUrl}
        surface={surface}
        className={className}
        caption="Brighter areas are where the reconstruction wrote new pixels."
      />
    );
  }

  if (comparison === "slider" && originalUrl) {
    const percent = Math.round(sliderPosition * 100);
    return (
      <div className={cn("flex flex-col gap-2", className)}>
        <div
          ref={containerRef}
          className={cn(
            "relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)]",
            surface,
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={processedUrl} alt="Processed result" className="block w-full" />
          <div
            className="absolute inset-0 overflow-hidden"
            style={{ clipPath: `inset(0 ${100 - percent}% 0 0)` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={originalUrl} alt="Original" className="block w-full" />
          </div>
          <div
            className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/90"
            style={{ left: `${percent}%` }}
            aria-hidden="true"
          />
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={percent}
          aria-label="Before and after slider position"
          onChange={(event) => setSliderPosition(Number(event.target.value) / 100)}
          className="w-full accent-[var(--color-primary)]"
        />
      </div>
    );
  }

  return <Panel label="Processed" src={processedUrl} surface={surface} className={className} />;
}

function Panel({
  label,
  src,
  surface,
  className,
  caption,
}: {
  label: string;
  src: string | null;
  surface: string;
  className?: string;
  caption?: string;
}) {
  return (
    <figure className={cn("flex flex-col gap-2", className)}>
      <div
        className={cn(
          "overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)]",
          surface,
        )}
      >
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={label} className="block w-full" />
        ) : (
          <div className="grid min-h-48 place-items-center text-sm text-[var(--color-ink-muted)]">
            Not available
          </div>
        )}
      </div>
      <figcaption className="text-xs text-[var(--color-ink-muted)]">
        <span className="font-medium text-[var(--color-ink)]">{label}</span>
        {caption ? ` — ${caption}` : null}
      </figcaption>
    </figure>
  );
}
