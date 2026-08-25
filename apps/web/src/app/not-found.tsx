import { Button } from "@artrestore/ui";
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center bg-[var(--color-paper)] px-4">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="text-xs font-semibold tracking-wider text-[var(--color-primary)] uppercase">
          404
        </p>
        <h1 className="font-serif text-2xl tracking-tight text-[var(--color-ink)]">
          This page doesn&apos;t exist
        </h1>
        <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
          The link may be old, or the project it pointed at has been deleted — deletion here is
          immediate and real.
        </p>
        <Button asChild>
          <Link href="/dashboard">Back to your projects</Link>
        </Button>
      </div>
    </main>
  );
}
