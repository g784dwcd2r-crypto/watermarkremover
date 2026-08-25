"use client";

import { Button } from "@artrestore/ui";
import * as React from "react";

/**
 * The route-level error boundary.
 *
 * Nothing here reads the error message into the page: an unexpected failure
 * may carry internals, and the request id in the API's logs is the debugging
 * handle, not the user's screen.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--color-paper)] px-4">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="text-xs font-semibold tracking-wider text-[var(--color-accent-text)] uppercase">
          Something went wrong
        </p>
        <h1 className="font-serif text-2xl tracking-tight text-[var(--color-ink)]">
          That didn&apos;t work, and it&apos;s not your fault
        </h1>
        <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
          The page hit an unexpected error. Your work is saved on the server — masks autosave and
          uploads either complete or don&apos;t, so nothing is half-written.
        </p>
        <div className="flex gap-2">
          <Button onClick={reset}>Try again</Button>
          <Button asChild variant="secondary">
            <a href="/dashboard">Back to projects</a>
          </Button>
        </div>
        {error.digest ? (
          <p className="text-xs text-[var(--color-ink-subtle)]">Reference: {error.digest}</p>
        ) : null}
      </div>
    </main>
  );
}
