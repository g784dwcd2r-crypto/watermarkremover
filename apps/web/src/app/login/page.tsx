"use client";

import { Alert, Button, Card, CardContent, CardHeader, CardTitle, Field, Input } from "@artrestore/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import { useLogin, useRequestMagicLink, useRequestPasswordReset } from "@/lib/queries";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const login = useLogin();
  const magicLink = useRequestMagicLink();
  const passwordReset = useRequestPasswordReset();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const next = params.get("next") ?? "/dashboard";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    login.mutate(
      { email, password },
      {
        onSuccess: () => router.push(next),
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError ? mutationError.message : "Could not sign in.",
          ),
      },
    );
  };

  return (
    <div className="mx-auto w-full max-w-md py-8">
      <h1 className="mb-4 font-serif text-2xl tracking-tight text-[var(--color-ink)]">
        Log in to ArtRestore Studio
      </h1>
      <Card>
        <CardHeader>
          <CardTitle>Email and password</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
            {error ? (
              <Alert tone="danger" live>
                {error}
              </Alert>
            ) : null}
            {notice ? (
              <Alert tone="success" live>
                {notice}
              </Alert>
            ) : null}

            <Field label="Email" htmlFor="email" required>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            <Field label="Password" htmlFor="password" required>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>

            <Button type="submit" loading={login.isPending}>
              Log in
            </Button>
          </form>

          <div className="mt-5 flex flex-col gap-2 border-t border-[var(--color-line)] pt-5 text-sm">
            <Button
              variant="link"
              size="sm"
              className="justify-start px-0"
              loading={magicLink.isPending}
              onClick={() => {
                if (!email) {
                  setError("Enter your email first, then request a sign-in link.");
                  return;
                }
                setError(null);
                magicLink.mutate(
                  { email },
                  { onSuccess: (data) => setNotice(data.message) },
                );
              }}
            >
              Email me a sign-in link instead
            </Button>
            <Button
              variant="link"
              size="sm"
              className="justify-start px-0"
              loading={passwordReset.isPending}
              onClick={() => {
                if (!email) {
                  setError("Enter your email first, then request a reset.");
                  return;
                }
                setError(null);
                passwordReset.mutate({ email }, { onSuccess: (data) => setNotice(data.message) });
              }}
            >
              Reset my password
            </Button>
            <p className="mt-2 text-[var(--color-ink-muted)]">
              No account yet?{" "}
              <Link className="text-[var(--color-primary)] underline underline-offset-4" href="/register">
                Create one
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <AppShell>
      <React.Suspense fallback={null}>
        <LoginForm />
      </React.Suspense>
    </AppShell>
  );
}
