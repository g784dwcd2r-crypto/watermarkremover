"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  Skeleton,
  formatBytes,
} from "@artrestore/ui";
import { Download, FileBox, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { useDeleteExport, useDownloadExport, useExports, useProject } from "@/lib/queries";
import { formatDateTime } from "@/lib/utils";

const FORMAT_TONE: Record<string, "primary" | "accent" | "info" | "neutral"> = {
  mp4: "primary",
  webm: "primary",
  gif: "accent",
  png: "info",
  jpeg: "info",
  webp: "info",
  tiff: "info",
  zip: "neutral",
  json: "neutral",
};

export default function ExportsPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const project = useProject(projectId);
  const exports = useExports(projectId);
  const download = useDownloadExport(projectId);
  const remove = useDeleteExport(projectId);
  const [status, setStatus] = React.useState<string | null>(null);

  const openDownload = (exportId: string) => {
    setStatus(null);
    download.mutate(exportId, {
      onSuccess: (record) => {
        if (record.download_url) {
          window.open(record.download_url, "_blank", "noopener,noreferrer");
          setStatus("Download link opened. Links expire in a few minutes.");
        }
      },
      onError: () => setStatus("That download link could not be created."),
    });
  };

  return (
    <AppShell>
      <PageHeader
        eyebrow="Export history"
        title={project.data?.name ?? "Exports"}
        description="Every file this project has produced, with the disclosure metadata each one carries."
        actions={
          <Button asChild variant="secondary">
            <Link href={`/projects/${projectId}`}>Back to project</Link>
          </Button>
        }
      />

      {status ? (
        <Alert tone="info" live className="mb-4">
          {status}
        </Alert>
      ) : null}

      {exports.isLoading ? (
        <Skeleton className="h-48" />
      ) : exports.data && exports.data.items.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {exports.data.items.map((record) => {
            const disclosure = record.disclosure_metadata ?? {};
            const reconstruction = disclosure.reconstruction_type as string | undefined;
            const output = (record.settings?.output as string | undefined) ?? record.format;
            const isPreview = Boolean(record.settings?.preview);

            return (
              <li key={record.id}>
                <Card>
                  <CardContent className="flex flex-wrap items-center gap-4 pt-5">
                    <div className="min-w-48 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={FORMAT_TONE[record.format] ?? "neutral"}>
                          {output.toUpperCase()}
                        </Badge>
                        {isPreview ? <Badge tone="neutral">Preview</Badge> : null}
                        <span className="text-sm text-[var(--color-ink-muted)] tabular-nums">
                          {formatBytes(record.byte_size)}
                        </span>
                      </div>
                      <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">
                        {formatDateTime(record.created_at)}
                      </p>
                      {reconstruction ? (
                        <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">
                          Labelled in file metadata as{" "}
                          <span className="font-medium text-[var(--color-ink)]">
                            {reconstruction}
                          </span>
                        </p>
                      ) : disclosure.provenance_preserved ? (
                        <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">
                          Original metadata preserved:{" "}
                          {(disclosure.preserved_metadata_blocks as string[] | undefined)?.join(
                            ", ",
                          ) || "none present"}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={download.isPending}
                        onClick={() => openDownload(record.id)}
                      >
                        <Download aria-hidden="true" />
                        Download
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="Delete this export"
                        loading={remove.isPending}
                        onClick={() => remove.mutate(record.id)}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState
          icon={FileBox}
          title="No exports yet"
          description="Run a cleanup or render a timelapse, then export it here."
          action={
            <Button asChild>
              <Link href={`/projects/${projectId}`}>Back to the project</Link>
            </Button>
          }
        />
      )}
    </AppShell>
  );
}
