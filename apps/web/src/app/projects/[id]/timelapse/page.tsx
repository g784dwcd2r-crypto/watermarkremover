"use client";

import type { TimelapseMode } from "@artrestore/types";
import { TIMELAPSE_MODE_LABELS } from "@artrestore/types";
import {
  Alert,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  LiveRegion,
  Select,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@artrestore/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { JobProgressPanel } from "@/components/common/job-progress-panel";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import {
  DEFAULT_RENDER_SETTINGS,
  RenderControls,
  type RenderSettings,
} from "@/components/timelapse/render-controls";
import {
  StageTimeline,
  toEditable,
  type EditableStage,
} from "@/components/timelapse/stage-timeline";
import { ApiError } from "@/lib/api";
import {
  useAnalyzeArtwork,
  useAssets,
  useProject,
  useRenderTimelapse,
  useSaveStages,
  useStages,
  useTimelapseOptions,
} from "@/lib/queries";
import { newIdempotencyKey } from "@/lib/utils";

export default function TimelapseEditorPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const project = useProject(projectId);
  const assets = useAssets(projectId);
  const options = useTimelapseOptions(projectId);
  const stages = useStages(projectId);
  const saveStages = useSaveStages(projectId);
  const analyze = useAnalyzeArtwork(projectId);
  const renderPreview = useRenderTimelapse(projectId, true);
  const renderFinal = useRenderTimelapse(projectId, false);

  const [mode, setMode] = React.useState<TimelapseMode>("sketch_to_colour");
  const [settings, setSettings] = React.useState<RenderSettings>(DEFAULT_RENDER_SETTINGS);
  // `null` until the user edits, so the saved timeline flows straight through
  // instead of being copied into local state by an effect.
  const [draft, setDraft] = React.useState<EditableStage[] | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const saved = React.useMemo(
    () => (stages.data ? toEditable(stages.data.items) : []),
    [stages.data],
  );
  const editable = draft ?? saved;

  const sourcePreview = (assets.data ?? []).find((asset) => asset.type === "source_preview");
  const intermediates = (assets.data ?? []).filter((asset) => asset.type === "intermediate");
  const audioAssets = (assets.data ?? []).filter((asset) => asset.type === "audio");
  const authenticCount = editable.filter(
    (stage) => stage.stage_type === "real_intermediate",
  ).length;

  const totalDuration = editable
    .filter((stage) => stage.enabled)
    .reduce((sum, stage) => sum + stage.duration, 0);

  const runAnalysis = () => {
    setError(null);
    analyze.mutate(
      { mode, seed: settings.seed },
      {
        onSuccess: (job) => {
          setJobId(job.id);
          setDraft(null); // the freshly generated timeline becomes the baseline
          setStatus("Analysing the artwork and building a timeline.");
        },
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The artwork could not be analysed.",
          ),
      },
    );
  };

  const persistStages = () => {
    setError(null);
    saveStages.mutate(
      editable.map((stage, index) => ({ ...stage, order_index: index })),
      {
        onSuccess: () => {
          setDraft(null);
          setStatus("Timeline saved.");
        },
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The timeline is not valid.",
          ),
      },
    );
  };

  const render = (preview: boolean) => {
    setError(null);
    const mutation = preview ? renderPreview : renderFinal;
    mutation.mutate(
      {
        ...settings,
        mode,
        duration_seconds: totalDuration > 0 ? totalDuration : settings.duration_seconds,
        idempotency_key: newIdempotencyKey(preview ? "preview" : "render"),
      },
      {
        onSuccess: (job) => {
          setJobId(job.id);
          setStatus(preview ? "Rendering a preview." : "Rendering the final video.");
        },
        onError: (mutationError) =>
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The render could not start.",
          ),
      },
    );
  };

  if (project.isLoading) {
    return (
      <AppShell>
        <Skeleton className="h-96" />
      </AppShell>
    );
  }

  if (!sourcePreview) {
    return (
      <AppShell>
        <Alert tone="warning" title="Upload your finished artwork first">
          <Link className="underline" href={`/projects/${projectId}`}>
            Go back to the project
          </Link>{" "}
          and upload the artwork you want to reconstruct.
        </Alert>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <LiveRegion message={status} />
      <PageHeader
        eyebrow="Timelapse reconstruction"
        title={project.data?.name ?? "Timelapse"}
        description="Build a process video from your finished artwork. The result is labelled a reconstruction in its file metadata, always."
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href={`/projects/${projectId}/exports`}>Exports</Link>
            </Button>
            <Button
              variant="secondary"
              loading={renderPreview.isPending}
              onClick={() => render(true)}
            >
              Preview
            </Button>
            <Button loading={renderFinal.isPending} onClick={() => render(false)}>
              Render
            </Button>
          </>
        }
      />

      {error ? (
        <Alert tone="danger" live className="mb-4">
          {error}
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Reconstruction mode</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Select
                id="timelapse-mode"
                label="Mode"
                hideLabel
                value={mode}
                onValueChange={(value) => setMode(value as TimelapseMode)}
                options={(options.data?.modes ?? []).map((item) => ({
                  value: item.key,
                  label: item.label,
                  description: item.requires_uploads
                    ? `Uses your uploaded progress images (${intermediates.length} available)`
                    : undefined,
                  disabled: item.requires_uploads && intermediates.length === 0,
                }))}
              />
              {mode === "real_intermediates" && intermediates.length === 0 ? (
                <Alert tone="warning">
                  This mode uses your own progress images as real keyframes. Upload at least one on
                  the{" "}
                  <Link className="underline" href={`/projects/${projectId}`}>
                    project page
                  </Link>{" "}
                  first.
                </Alert>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  loading={analyze.isPending}
                  onClick={runAnalysis}
                  disabled={mode === "real_intermediates" && intermediates.length === 0}
                >
                  Analyse and build a timeline
                </Button>
                <p className="text-xs text-[var(--color-ink-muted)]">
                  {TIMELAPSE_MODE_LABELS[mode]} produces a starting timeline you can then reorder
                  and retime.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              {stages.isLoading ? (
                <Skeleton className="h-40" />
              ) : editable.length > 0 ? (
                <div className="flex flex-col gap-4">
                  <StageTimeline
                    stages={editable}
                    onChange={setDraft}
                    minSeconds={options.data?.duration_seconds.min ?? 5}
                    maxSeconds={options.data?.duration_seconds.max ?? 300}
                    authenticStageCount={authenticCount}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    className="self-start"
                    loading={saveStages.isPending}
                    onClick={persistStages}
                  >
                    Save timeline
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-[var(--color-ink-muted)]">
                  Run the analysis to generate an editable stage timeline.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Artwork</CardTitle>
            </CardHeader>
            <CardContent>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={sourcePreview.download_url ?? ""}
                alt="The finished artwork this reconstruction is built from"
                className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)]"
              />
            </CardContent>
          </Card>
        </div>

        <aside className="flex flex-col gap-4">
          <JobProgressPanel
            projectId={projectId}
            jobId={jobId}
            label="Reconstructing"
            onFinished={(_result, jobStatus) =>
              setStatus(jobStatus === "succeeded" ? "Render finished." : `Render ${jobStatus}.`)
            }
          />

          <Card>
            <CardContent className="pt-5">
              <Tabs defaultValue="output">
                <TabsList className="mb-4 w-full">
                  <TabsTrigger value="output" className="flex-1">
                    Settings
                  </TabsTrigger>
                  <TabsTrigger value="about" className="flex-1">
                    About
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="output">
                  <RenderControls
                    options={options.data}
                    settings={settings}
                    onChange={(patch) => setSettings((previous) => ({ ...previous, ...patch }))}
                    audioAssets={audioAssets.map((asset) => ({
                      id: asset.id,
                      label: `${asset.mime_type} · ${Math.round(asset.byte_size / 1024)} KB`,
                    }))}
                    brandAssets={intermediates.map((asset) => ({
                      id: asset.id,
                      label: `Uploaded image ${asset.order_index + 1}`,
                    }))}
                  />
                </TabsContent>
                <TabsContent value="about">
                  <div className="flex flex-col gap-3 text-sm leading-relaxed text-[var(--color-ink-muted)]">
                    <p>
                      This tool reconstructs a plausible process from a finished piece. It does not
                      recover how the work was actually made, and it never claims to.
                    </p>
                    <p>
                      Every exported file carries{" "}
                      <span className="font-medium text-[var(--color-ink)]">
                        &ldquo;Reconstructed process&rdquo;
                      </span>{" "}
                      and a full disclosure statement in its metadata. The project JSON export lists
                      the exact stages and the random seed used, so the result is reproducible and
                      inspectable.
                    </p>
                    <p>
                      If you upload your own sketches or progress files, Real Intermediate Frames
                      uses them as genuine keyframes in your order — those stages are your work, not
                      a generated approximation of it.
                    </p>
                  </div>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </aside>
      </div>
    </AppShell>
  );
}
