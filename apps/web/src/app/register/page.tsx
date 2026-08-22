"use client";

import {
  Alert,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConsentCheckbox,
  Field,
  Input,
} from "@artrestore/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import { useRegister } from "@/lib/queries";

const MIN_PASSWORD = 12;

export default function RegisterPage() {
  const router = useRouter();
  const register = useRegister();

  const [form, setForm] = React.useState({ email: "", name: "", password: "" });
  const [acceptTerms, setAcceptTerms] = React.useState(false);
  const [acceptPolicy, setAcceptPolicy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const passwordTooShort = form.password.length > 0 && form.password.length < MIN_PASSWORD;
  const ready = form.email && form.password.length >= MIN_PASSWORD && acceptTerms && acceptPolicy;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    register.mutate(
      {
        email: form.email,
        name: form.name,
        password: form.password,
        accept_terms: acceptTerms,
        accept_authorized_use_policy: acceptPolicy,
      },
      {
        onSuccess: () => router.push("/dashboard"),
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The account could not be created.",
          ),
      },
    );
  };

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-md py-8">
        <h1 className="mb-4 font-serif text-2xl tracking-tight text-[var(--color-ink)]">
          Create your account
        </h1>
        <Card>
          <CardHeader>
            <CardTitle>Account details</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
              {error ? (
                <Alert tone="danger" live>
                  {error}
                </Alert>
              ) : null}

              <Field label="Email" htmlFor="email" required>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                />
              </Field>
              <Field label="Name" htmlFor="name" description="Shown on your account only.">
                <Input
                  id="name"
                  autoComplete="name"
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
              </Field>
              <Field
                label="Password"
                htmlFor="password"
                required
                description={`At least ${MIN_PASSWORD} characters. A few unrelated words works well.`}
                error={passwordTooShort ? `Use at least ${MIN_PASSWORD} characters.` : undefined}
              >
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={MIN_PASSWORD}
                  aria-describedby="password-description"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                />
              </Field>

              <ConsentCheckbox
                id="accept-policy"
                checked={acceptPolicy}
                onCheckedChange={setAcceptPolicy}
                label="I accept the authorized-use policy"
                description="I will only upload images I own or have permission to edit, and I understand that attribution and provenance content cannot be removed here."
              />
              <ConsentCheckbox
                id="accept-terms"
                checked={acceptTerms}
                onCheckedChange={setAcceptTerms}
                label="I accept the terms and the privacy policy"
                description="Your acceptance is recorded with the policy version in force."
              />

              <Button type="submit" disabled={!ready} loading={register.isPending}>
                Create account
              </Button>
              <p className="text-sm text-[var(--color-ink-muted)]">
                Already have an account?{" "}
                <Link
                  className="text-[var(--color-primary)] underline underline-offset-4"
                  href="/login"
                >
                  Log in
                </Link>
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
