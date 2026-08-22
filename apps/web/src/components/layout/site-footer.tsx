import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-[var(--color-line)] bg-[var(--color-paper-sunken)]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-10 sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-md">
          <p className="font-serif text-base text-[var(--color-ink)]">ArtRestore Studio</p>
          <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-muted)]">
            Tools for work you are entitled to do: cleaning overlays from your own images, and
            building clearly-labelled reconstructed process videos from your own finished artwork.
          </p>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-10 gap-y-2 text-sm">
          <Link
            className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            href="/authorized-use-policy"
          >
            Authorized-use policy
          </Link>
          <Link
            className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            href="/privacy"
          >
            Privacy
          </Link>
          <Link
            className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            href="/terms"
          >
            Terms
          </Link>
          <Link
            className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            href="/dashboard"
          >
            Dashboard
          </Link>
        </nav>
      </div>
      <div className="border-t border-[var(--color-line)] px-4 py-4 sm:px-6">
        <p className="mx-auto w-full max-w-6xl text-xs text-[var(--color-ink-subtle)]">
          Signatures, credit lines, stock-agency watermarks and Content Credentials are detected and
          left intact. Timelapses are reconstructions, never recordings of an original creation
          process.
        </p>
      </div>
    </footer>
  );
}
