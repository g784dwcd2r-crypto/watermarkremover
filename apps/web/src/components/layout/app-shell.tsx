import * as React from "react";

import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";

export function AppShell({
  children,
  wide = false,
  footer = true,
}: {
  children: React.ReactNode;
  wide?: boolean;
  footer?: boolean;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main
        id="main"
        className={`flex-1 ${wide ? "w-full" : "mx-auto w-full max-w-6xl px-4 py-8 sm:px-6"}`}
      >
        {children}
      </main>
      {footer ? <SiteFooter /> : null}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        {eyebrow ? (
          <p className="mb-1 text-xs font-semibold tracking-wider text-[var(--color-primary)] uppercase">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="font-serif text-2xl tracking-tight text-[var(--color-ink)] sm:text-3xl">
          {title}
        </h1>
        {description ? (
          <div className="mt-2 text-sm leading-relaxed text-[var(--color-ink-muted)]">
            {description}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
