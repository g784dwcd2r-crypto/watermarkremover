"use client";

import {
  Alert,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogTrigger,
  Field,
  Input,
  Select,
  Skeleton,
  formatBytes,
} from "@artrestore/ui";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { API_BASE_URL, ApiError } from "@/lib/api";
import {
  useChangePassword,
  useConsents,
  useDeleteAccount,
  useSession,
  useStorageUsage,
  useUpdateAccount,
} from "@/lib/queries";
import { formatDateTime } from "@/lib/utils";

export default function AccountPage() {
  const router = useRouter();
  const { data: user, isLoading } = useSession();
  const usage = useStorageUsage();
  const consents = useConsents();
  const update = useUpdateAccount();
  const remove = useDeleteAccount();

  // `null` means "not edited yet", so the field shows the loaded value without
  // an effect copying server state into local state.
  const [nameDraft, setNameDraft] = React.useState<string | null>(null);
  const [retentionDraft, setRetentionDraft] = React.useState<"1" | "7" | "30" | null>(null);
  const [password, setPassword] = React.useState("");
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);

  React.useEffect(() => {
    if (!isLoading && !user) router.replace("/login?next=/account");
  }, [user, isLoading, router]);

  if (isLoading || !user) {
    return (
      <AppShell>
        <Skeleton className="h-64" />
      </AppShell>
    );
  }

  const name = nameDraft ?? user.name;
  const storedRetention = user.retention_preferences?.retention_days;
  const retention: "1" | "7" | "30" =
    retentionDraft ??
    (storedRetention === 1 || storedRetention === 30
      ? (String(storedRetention) as "1" | "30")
      : "7");

  return (
    <AppShell>
      <PageHeader
        title="Account"
        description="Your details, your storage, and what you have agreed to."
      />

      {notice ? (
        <Alert tone="success" live className="mb-4">
          {notice}
        </Alert>
      ) : null}
      {error ? (
        <Alert tone="danger" live className="mb-4">
          {error}
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                setError(null);
                update.mutate(
                  { name },
                  {
                    onSuccess: () => setNotice("Profile updated."),
                    onError: (mutationError) =>
                      setError(
                        mutationError instanceof ApiError
                          ? mutationError.message
                          : "Could not update your profile.",
                      ),
                  },
                );
              }}
            >
              <Field
                label="Email"
                htmlFor="account-email"
                description="Contact support to change your email."
              >
                <Input id="account-email" value={user.email} readOnly disabled />
              </Field>
              <Field label="Name" htmlFor="account-name">
                <Input
                  id="account-name"
                  value={name}
                  onChange={(event) => setNameDraft(event.target.value)}
                />
              </Field>
              <Button type="submit" loading={update.isPending} className="self-start">
                Save
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Retention and privacy</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Select
              id="account-retention"
              label="Delete my files automatically after"
              value={retention}
              onValueChange={(value) => {
                setRetentionDraft(value as typeof retention);
                setError(null);
                update.mutate(
                  { retention_days: Number(value) as 1 | 7 | 30 },
                  {
                    onSuccess: () =>
                      setNotice(
                        "Retention updated. This applies to work you have already uploaded, not just new work.",
                      ),
                    onError: (mutationError) =>
                      setError(
                        mutationError instanceof ApiError
                          ? mutationError.message
                          : "Could not update retention.",
                      ),
                  },
                );
              }}
              options={[
                { value: "1", label: "1 day" },
                { value: "7", label: "7 days" },
                { value: "30", label: "30 days" },
              ]}
            />
            <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
              Your images are private to your account and are never used to train models. Download
              links are signed and expire within minutes. You can delete any project immediately
              from the dashboard.
            </p>
            <Button asChild variant="secondary" size="sm" className="self-start">
              <a href={`${API_BASE_URL}/v1/account/export`} target="_blank" rel="noreferrer">
                Export my data as JSON
              </a>
            </Button>
          </CardContent>
        </Card>

        <PasswordCard onNotice={setNotice} onError={setError} />

        {usage.data ? (
          <Card>
            <CardHeader>
              <CardTitle>Storage</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">
                    Used
                  </dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {formatBytes(usage.data.total_bytes)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">
                    Projects
                  </dt>
                  <dd className="text-lg font-semibold tabular-nums">{usage.data.project_count}</dd>
                </div>
                <div>
                  <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">
                    Files
                  </dt>
                  <dd className="text-lg font-semibold tabular-nums">{usage.data.asset_count}</dd>
                </div>
                <div>
                  <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">
                    Exports
                  </dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {formatBytes(usage.data.export_bytes)}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>What you have confirmed</CardTitle>
          </CardHeader>
          <CardContent>
            {consents.isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <ul className="flex max-h-64 flex-col gap-2 overflow-y-auto text-sm">
                {(consents.data ?? []).map((record) => (
                  <li
                    key={record.id}
                    className="border-b border-[var(--color-line)] pb-2 last:border-0"
                  >
                    <p className="font-medium text-[var(--color-ink)]">
                      {record.statement || record.consent_type}
                    </p>
                    <p className="text-xs text-[var(--color-ink-muted)]">
                      {formatDateTime(record.confirmed_at)} · policy {record.policy_version}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="border-[var(--color-danger)]/30 lg:col-span-2">
          <CardHeader>
            <CardTitle>Delete this account</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
              Deleting removes every project, every uploaded file and every export from storage,
              plus your consent history. It is immediate and cannot be undone.
            </p>
            <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
              <DialogTrigger asChild>
                <Button variant="danger" className="self-start">
                  Delete my account
                </Button>
              </DialogTrigger>
              <DialogContent
                title="Delete your account?"
                description="Everything is erased immediately. There is no recovery."
                footer={
                  <>
                    <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      variant="danger"
                      loading={remove.isPending}
                      onClick={() =>
                        remove.mutate(
                          { password },
                          {
                            onSuccess: () => router.push("/"),
                            onError: (mutationError) =>
                              setError(
                                mutationError instanceof ApiError
                                  ? mutationError.message
                                  : "The account could not be deleted.",
                              ),
                          },
                        )
                      }
                    >
                      Delete permanently
                    </Button>
                  </>
                }
              >
                <Field
                  label="Confirm your password"
                  htmlFor="delete-password"
                  description="Required so an unattended session cannot delete your work."
                >
                  <Input
                    id="delete-password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </Field>
              </DialogContent>
            </Dialog>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function PasswordCard({
  onNotice,
  onError,
}: {
  onNotice: (message: string) => void;
  onError: (message: string | null) => void;
}) {
  const change = useChangePassword();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const tooShort = next.length > 0 && next.length < 12;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            onError(null);
            change.mutate(
              { current_password: current, new_password: next },
              {
                onSuccess: () => {
                  setCurrent("");
                  setNext("");
                  onNotice("Password changed. Every other signed-in session has been signed out.");
                },
                onError: (mutationError) =>
                  onError(
                    mutationError instanceof ApiError
                      ? mutationError.message
                      : "The password could not be changed.",
                  ),
              },
            );
          }}
        >
          <Field label="Current password" htmlFor="password-current" required>
            <Input
              id="password-current"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </Field>
          <Field
            label="New password"
            htmlFor="password-next"
            required
            description="At least 12 characters."
            error={tooShort ? "Use at least 12 characters." : undefined}
          >
            <Input
              id="password-next"
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </Field>
          <Button
            type="submit"
            loading={change.isPending}
            disabled={!current || next.length < 12}
            className="self-start"
          >
            Change password
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
