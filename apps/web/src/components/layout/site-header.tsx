"use client";

import { Button } from "@artrestore/ui";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { useLogout, useSession } from "@/lib/queries";

const MARKETING_LINKS = [
  { href: "/authorized-use-policy", label: "Authorized use" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

const APP_LINKS = [
  { href: "/dashboard", label: "Projects" },
  { href: "/projects/new", label: "New project" },
  { href: "/account", label: "Account" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: user, isLoading } = useSession();
  const logout = useLogout();
  const links = user ? APP_LINKS : MARKETING_LINKS;

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-line)] bg-[var(--color-paper)]/92 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link
          href={user ? "/dashboard" : "/"}
          className="flex items-center gap-2.5 rounded-[var(--radius-sm)] font-serif text-lg tracking-tight text-[var(--color-ink)]"
        >
          <span
            aria-hidden="true"
            className="grid size-8 place-items-center rounded-[var(--radius-md)] bg-[var(--color-primary)] text-sm font-semibold text-[var(--color-on-primary)]"
          >
            AR
          </span>
          ArtRestore Studio
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {links.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-[var(--radius-sm)] px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-[var(--color-primary-soft)] font-medium text-[var(--color-primary-hover)]"
                    : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          {isLoading ? null : user ? (
            <>
              <span className="hidden text-sm text-[var(--color-ink-muted)] sm:inline">
                {user.name || user.email}
              </span>
              <Button
                variant="secondary"
                size="sm"
                loading={logout.isPending}
                onClick={() => {
                  logout.mutate(undefined, { onSuccess: () => router.push("/") });
                }}
              >
                Sign out
              </Button>
            </>
          ) : (
            <>
              <Button asChild variant="ghost" size="sm">
                <Link href="/login">Log in</Link>
              </Button>
              <Button asChild size="sm">
                <Link href="/register">Create account</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
