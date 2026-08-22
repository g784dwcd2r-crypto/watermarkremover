"use client";

import type { Project, ProjectType } from "@artrestore/types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  DialogTrigger,
  EmptyState,
  Input,
  Select,
  Skeleton,
  formatBytes,
} from "@artrestore/ui";
import { Copy, FolderOpen, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AppShell, PageHeader } from "@/components/layout/app-shell";
import {
  useDeleteProject,
  useDuplicateProject,
  useProjects,
  useSession,
  useStorageUsage,
  useUpdateProject,
} from "@/lib/queries";
import { PROJECT_STATUS_LABEL, PROJECT_STATUS_TONE, formatDate, relativeDays } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const { data: user, isLoading: sessionLoading } = useSession();
  const [type, setType] = React.useState<"all" | ProjectType>("all");
  const [status, setStatus] = React.useState("all");
  const [search, setSearch] = React.useState("");

  const projects = useProjects({
    project_type: type === "all" ? undefined : type,
    status: status === "all" ? undefined : status,
    search: search || undefined,
    limit: 50,
  });
  const usage = useStorageUsage();

  React.useEffect(() => {
    if (!sessionLoading && !user) router.replace("/login?next=/dashboard");
  }, [sessionLoading, user, router]);

  return (
    <AppShell>
      <PageHeader
        title="Your projects"
        description="Everything you have uploaded, and when it will be deleted."
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href="/projects/new?type=timelapse">New timelapse</Link>
            </Button>
            <Button asChild>
              <Link href="/projects/new?type=cleanup">New cleanup</Link>
            </Button>
          </>
        }
      />

      {usage.data ? (
        <Card className="mb-6">
          <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3 pt-5">
            <dl className="flex flex-wrap items-center gap-x-8 gap-y-3">
              <Stat label="Projects" value={String(usage.data.project_count)} />
              <Stat label="Files" value={String(usage.data.asset_count)} />
              <Stat label="Storage used" value={formatBytes(usage.data.total_bytes)} />
              <Stat label="Exports" value={formatBytes(usage.data.export_bytes)} />
            </dl>
            <Button asChild variant="link" size="sm" className="ml-auto px-0">
              <Link href="/account">Retention settings</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <label htmlFor="project-search" className="mb-1.5 block text-sm font-medium">
            Search
          </label>
          <Input
            id="project-search"
            type="search"
            placeholder="Search project names"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Select
          id="filter-type"
          label="Type"
          value={type}
          onValueChange={(value) => setType(value as typeof type)}
          className="w-44"
          options={[
            { value: "all", label: "All types" },
            { value: "cleanup", label: "Cleanup" },
            { value: "timelapse", label: "Timelapse" },
          ]}
        />
        <Select
          id="filter-status"
          label="Status"
          value={status}
          onValueChange={setStatus}
          className="w-44"
          options={[
            { value: "all", label: "Any status" },
            { value: "draft", label: "Draft" },
            { value: "ready", label: "Ready" },
            { value: "processing", label: "Processing" },
            { value: "complete", label: "Complete" },
            { value: "failed", label: "Failed" },
          ]}
        />
      </div>

      {projects.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : projects.data && projects.data.items.length > 0 ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.items.map((project) => (
            <li key={project.id}>
              <ProjectCard project={project} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={FolderOpen}
          title="No projects yet"
          description="Start by uploading an image you own or have permission to edit."
          action={
            <Button asChild>
              <Link href="/projects/new?type=cleanup">Create your first project</Link>
            </Button>
          }
        />
      )}
    </AppShell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">{label}</dt>
      <dd className="text-lg font-semibold text-[var(--color-ink)] tabular-nums">{value}</dd>
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const duplicate = useDuplicateProject();
  const remove = useDeleteProject();
  const rename = useUpdateProject(project.id);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [renameOpen, setRenameOpen] = React.useState(false);
  const [draftName, setDraftName] = React.useState(project.name);
  const editorHref =
    project.project_type === "cleanup"
      ? `/projects/${project.id}/cleanup`
      : `/projects/${project.id}/timelapse`;

  return (
    <Card className="flex h-full flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 pt-5">
        <div className="flex items-start justify-between gap-2">
          <Link
            href={`/projects/${project.id}`}
            className="line-clamp-2 font-medium text-[var(--color-ink)] hover:underline"
          >
            {project.name}
          </Link>
          <Badge tone={PROJECT_STATUS_TONE[project.status]}>
            {PROJECT_STATUS_LABEL[project.status]}
          </Badge>
        </div>

        <dl className="flex flex-col gap-1 text-xs text-[var(--color-ink-muted)]">
          <div className="flex gap-1.5">
            <dt>Type</dt>
            <dd className="font-medium text-[var(--color-ink)]">
              {project.project_type === "cleanup" ? "Cleanup" : "Timelapse"}
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Created</dt>
            <dd>{formatDate(project.created_at)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Auto-delete</dt>
            <dd>{relativeDays(project.delete_after)}</dd>
          </div>
        </dl>

        <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
          <Button asChild size="sm" variant="secondary">
            <Link href={editorHref}>Open editor</Link>
          </Button>
          <Button asChild size="sm" variant="ghost">
            <Link href={`/projects/${project.id}/exports`}>Exports</Link>
          </Button>
          <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="ghost" aria-label={`Rename ${project.name}`}>
                <Pencil aria-hidden="true" />
              </Button>
            </DialogTrigger>
            <DialogContent
              title="Rename project"
              footer={
                <>
                  <Button variant="secondary" onClick={() => setRenameOpen(false)}>
                    Cancel
                  </Button>
                  <Button
                    loading={rename.isPending}
                    onClick={() =>
                      rename.mutate(
                        { name: draftName.trim() || project.name },
                        { onSuccess: () => setRenameOpen(false) },
                      )
                    }
                  >
                    Save
                  </Button>
                </>
              }
            >
              <label htmlFor={`rename-${project.id}`} className="mb-1.5 block text-sm font-medium">
                Project name
              </label>
              <Input
                id={`rename-${project.id}`}
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
              />
            </DialogContent>
          </Dialog>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Duplicate ${project.name}`}
            loading={duplicate.isPending}
            onClick={() => duplicate.mutate(project.id)}
          >
            <Copy aria-hidden="true" />
          </Button>
          <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="ghost" aria-label={`Delete ${project.name}`}>
                <Trash2 aria-hidden="true" />
              </Button>
            </DialogTrigger>
            <DialogContent
              title={`Delete "${project.name}"?`}
              description="Every file in this project is removed from storage immediately. This cannot be undone."
              footer={
                <>
                  <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
                    Keep it
                  </Button>
                  <Button
                    variant="danger"
                    loading={remove.isPending}
                    onClick={() =>
                      remove.mutate(project.id, { onSuccess: () => setConfirmOpen(false) })
                    }
                  >
                    Delete permanently
                  </Button>
                </>
              }
            />
          </Dialog>
        </div>
      </CardContent>
    </Card>
  );
}
