"use client";

import type { ProjectType } from "@artrestore/types";
import {
  Alert,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Select,
} from "@artrestore/ui";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import { useCreateProject, useSession } from "@/lib/queries";

function NewProjectForm() {
  const router = useRouter();
  const params = useSearchParams();
  const create = useCreateProject();
  const { data: user, isLoading } = useSession();

  const initialType = (params.get("type") as ProjectType) ?? "cleanup";
  const [name, setName] = React.useState("");
  const [type, setType] = React.useState<ProjectType>(
    initialType === "timelapse" ? "timelapse" : "cleanup",
  );
  const [retention, setRetention] = React.useState<"1" | "7" | "30">("7");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isLoading && !user) router.replace("/login?next=/projects/new");
  }, [isLoading, user, router]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    create.mutate(
      {
        name: name.trim() || (type === "cleanup" ? "Untitled cleanup" : "Untitled timelapse"),
        project_type: type,
        retention_days: Number(retention) as 1 | 7 | 30,
      },
      {
        onSuccess: (project) => router.push(`/projects/${project.id}`),
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The project could not be created.",
          ),
      },
    );
  };

  return (
    <>
      <PageHeader
        title="New project"
        description="Pick what you are doing and how long the files should be kept."
      />
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Project details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            {error ? (
              <Alert tone="danger" live>
                {error}
              </Alert>
            ) : null}
            <Field label="Project name" htmlFor="project-name">
              <Input
                id="project-name"
                value={name}
                placeholder={type === "cleanup" ? "Client retouch" : "Process video"}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Select
              id="project-type"
              label="What are you doing?"
              value={type}
              onValueChange={(value) => setType(value as ProjectType)}
              options={[
                {
                  value: "cleanup",
                  label: "Clean an image",
                  description: "Remove an overlay, date stamp or obsolete mark you are authorized to remove.",
                },
                {
                  value: "timelapse",
                  label: "Reconstructed timelapse",
                  description: "Build a labelled process video from your finished artwork.",
                },
              ]}
            />
            <Select
              id="project-retention"
              label="Delete my files automatically after"
              value={retention}
              onValueChange={(value) => setRetention(value as typeof retention)}
              options={[
                { value: "1", label: "1 day" },
                { value: "7", label: "7 days" },
                { value: "30", label: "30 days" },
              ]}
              hint="You can change this later, and you can delete anything immediately at any time."
            />
            <Button type="submit" loading={create.isPending} className="self-start">
              Create project
            </Button>
          </form>
        </CardContent>
      </Card>
    </>
  );
}

export default function NewProjectPage() {
  return (
    <AppShell>
      <React.Suspense fallback={null}>
        <NewProjectForm />
      </React.Suspense>
    </AppShell>
  );
}
