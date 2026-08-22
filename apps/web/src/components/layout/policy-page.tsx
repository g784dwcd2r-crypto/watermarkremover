import * as React from "react";

import { AppShell } from "./app-shell";

export function PolicyPage({
  title,
  version,
  updated,
  summary,
  children,
}: {
  title: string;
  version: string;
  updated: string;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <AppShell>
      <article className="mx-auto w-full max-w-3xl py-4">
        <header className="mb-8 border-b border-[var(--color-line)] pb-6">
          <h1 className="font-serif text-3xl tracking-tight text-[var(--color-ink)]">{title}</h1>
          <p className="mt-3 text-base leading-relaxed text-[var(--color-ink-muted)]">{summary}</p>
          <p className="mt-4 text-xs text-[var(--color-ink-subtle)]">
            Version {version} · Last updated {updated}
          </p>
        </header>
        <div className="flex flex-col gap-8">{children}</div>
      </article>
    </AppShell>
  );
}

export function PolicySection({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  const id = heading.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="font-serif text-xl tracking-tight text-[var(--color-ink)]">
        {heading}
      </h2>
      <div className="mt-3 flex flex-col gap-3 text-sm leading-relaxed text-[var(--color-ink-muted)] [&_a]:text-[var(--color-primary)] [&_a]:underline [&_a]:underline-offset-4 [&_li]:ml-5 [&_li]:list-disc [&_strong]:text-[var(--color-ink)]">
        {children}
      </div>
    </section>
  );
}
