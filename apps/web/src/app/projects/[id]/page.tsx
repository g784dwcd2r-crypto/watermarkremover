"use client";

import { OWNERSHIP_STATEMENT } from "@artrestore/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
  formatBytes,
} from "@artrestore/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { UploadDropzone } from "@/components/common/upload-dropzone";
import { useAssets, useProject } from "@/lib/queries";
import { PROJECT_STATUS_LABEL, PROJECT_STATUS_TONE, formatDate, relativeDays } from "@/lib/utils";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const project = useProject(projectId);
  const assets = useAssets(projectId);

  if (project.isLoading) {
    return (
      <AppShell>
        <Skeleton className="h-64" />
      </AppShell>
    );
  }

  if (project.isError || !project.data) {
    return (
      <AppShell>
        <Alert tone="danger" title="Project not found">
          This project does not exist, or it is not yours.
        </Alert>
      </AppShell>
    );
  }

  const detail = project.data;
  const sources = (assets.data ?? []).filter((asset) => asset.type === "source");
  const previews = (assets.data ?? []).filter((asset) => asset.type === "source_preview");
  const editorHref =
    detail.project_type === "cleanup"
      ? `/projects/${projectId}/cleanup`
      : `/projects/${projectId}/timelapse`;

  return (
    <AppShell>
      <PageHeader
        eyebrow={detail.project_type === "cleanup" ? "Cleanup project" : "Timelapse project"}
        title={detail.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={PROJECT_STATUS_TONE[detail.status]}>
              {PROJECT_STATUS_LABEL[detail.status]}
            </Badge>
            <span>Created {formatDate(detail.created_at)}</span>
            <span aria-hidden="true">·</span>
            <span>Auto-deletes {relativeDays(detail.delete_after)}</span>
          </span>
        }
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href={`/projects/${projectId}/exports`}>Exports</Link>
            </Button>
            <Button asChild disabled={sources.length === 0}>
              <Link href={editorHref}>
                {detail.project_type === "cleanup"
                  ? "Open the editor"
                  : "Open the timelapse editor"}
              </Link>
            </Button>
          </>
        }
      />

      {!detail.ownership_confirmed ? (
        <Alert tone="warning" title="Confirmation needed" className="mb-6">
          Nothing can be processed until you confirm: &ldquo;{OWNERSHIP_STATEMENT}&rdquo; You do
          that as part of the upload below.
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="flex flex-col gap-6">
          {sources.length === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>
                  {detail.project_type === "cleanup"
                    ? "Upload the image to clean"
                    : "Upload the finished artwork"}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <UploadDropzone projectId={projectId} retentionDays={detail.retention_days} />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Source image</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {previews[0]?.download_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={previews[0].download_url}
                    alt="Uploaded artwork preview"
                    className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)]"
                  />
                ) : null}
                <SourceFacts asset={sources[0]!} />
              </CardContent>
            </Card>
          )}

          {detail.project_type === "timelapse" && sources.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Optional: your own progress images</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
                  If you saved sketches or work-in-progress files, upload them here. Real
                  Intermediate Frames uses them as actual keyframes in the order you upload, and
                  only the transitions between them are generated.
                </p>
                <UploadDropzone
                  projectId={projectId}
                  assetType="intermediate"
                  requireOwnership={false}
                  title="Add a progress image"
                  description="These become authentic stages in the timeline."
                />
              </CardContent>
            </Card>
          ) : null}
        </div>

        <aside className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Files</CardTitle>
            </CardHeader>
            <CardContent>
              {assets.isLoading ? (
                <Skeleton className="h-20" />
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {(assets.data ?? []).map((asset) => (
                    <li key={asset.id} className="flex items-center justify-between gap-2">
                      <span className="truncate text-[var(--color-ink-muted)]">
                        {asset.type.replace(/_/g, " ")}
                      </span>
                      <span className="shrink-0 text-[var(--color-ink-subtle)] tabular-nums">
                        {formatBytes(asset.byte_size)}
                      </span>
                    </li>
                  ))}
                  {(assets.data ?? []).length === 0 ? (
                    <li className="text-[var(--color-ink-muted)]">Nothing uploaded yet.</li>
                  ) : null}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Privacy</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm text-[var(--color-ink-muted)]">
              <p>Private to your account. Never used to train models.</p>
              <p>
                Deleted automatically after {detail.retention_days}{" "}
                {detail.retention_days === 1 ? "day" : "days"}.
              </p>
              <Button asChild variant="link" size="sm" className="justify-start px-0">
                <Link href="/account">Change retention</Link>
              </Button>
            </CardContent>
          </Card>
        </aside>
      </div>
    </AppShell>
  );
}

function SourceFacts({
  asset,
}: {
  asset: {
    width: number | null;
    height: number | null;
    byte_size: number;
    mime_type: string;
    metadata: Record<string, unknown>;
  };
}) {
  const metadata = asset.metadata ?? {};
  const provenance = (metadata.provenance ?? {}) as Record<string, unknown>;
  const hasProvenance = Boolean(provenance.has_any);

  return (
    <>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Fact label="Dimensions" value={`${asset.width ?? "?"} × ${asset.height ?? "?"}`} />
        <Fact label="Colour mode" value={String(metadata.color_mode ?? "RGB")} />
        <Fact label="File size" value={formatBytes(asset.byte_size)} />
        <Fact label="Format" value={asset.mime_type.replace("image/", "").toUpperCase()} />
      </dl>
      {hasProvenance ? (
        <Alert tone="info" title="This image carries provenance metadata">
          It is preserved on every export and cannot be removed here.
        </Alert>
      ) : null}
      {metadata.orientation_corrected ? (
        <p className="text-xs text-[var(--color-ink-muted)]">
          EXIF orientation was applied so the preview matches the exported result.
        </p>
      ) : null}
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">{label}</dt>
      <dd className="font-medium text-[var(--color-ink)]">{value}</dd>
    </div>
  );
}
