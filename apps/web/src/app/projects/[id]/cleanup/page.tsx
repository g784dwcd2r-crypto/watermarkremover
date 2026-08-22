"use client";

import type { CleanupMode, DetectedRegion, MaskPreview, ProtectedKind } from "@artrestore/types";
import { CLEANUP_MODE_DESCRIPTIONS, CLEANUP_MODE_LABELS } from "@artrestore/types";
import {
  Alert,
  Badge,
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
import { Wand2 } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { ProtectionNotice } from "@/components/common/protection-notice";
import { JobProgressPanel } from "@/components/common/job-progress-panel";
import { ComparisonView } from "@/components/editor/comparison-view";
import {
  AutosaveIndicator,
  BrushPanel,
  ComparisonControls,
  EditorToolbar,
  MaskAdjustmentsPanel,
} from "@/components/editor/editor-toolbar";
import { ShortcutList, useEditorShortcuts } from "@/components/editor/keyboard-shortcuts";
import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import {
  useAssets,
  useCreateExport,
  useDetectOverlays,
  usePreviewMask,
  useProject,
  useSaveMask,
  useStartCleanup,
} from "@/lib/queries";
import { newIdempotencyKey } from "@/lib/utils";
import { hasMaskContent, useEditorStore } from "@/store/editor-store";

// Konva touches window on import, so the canvas is client-only.
const MaskCanvas = dynamic(
  () => import("@/components/editor/mask-canvas").then((module) => module.MaskCanvas),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[60vh] w-full" />,
  },
);

const AUTOSAVE_DELAY = 2500;

export default function CleanupEditorPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const project = useProject(projectId);
  const assets = useAssets(projectId);
  const saveMask = useSaveMask(projectId);
  const previewMask = usePreviewMask(projectId);
  const detectOverlays = useDetectOverlays(projectId);
  const startCleanup = useStartCleanup(projectId);
  const createExport = useCreateExport(projectId);

  const store = useEditorStore();
  const [mode, setMode] = React.useState<CleanupMode>("fast_fill");
  const [maskVersion, setMaskVersion] = React.useState<number | null>(null);
  const [preview, setPreview] = React.useState<MaskPreview | null>(null);
  const [acknowledged, setAcknowledged] = React.useState<ProtectedKind[]>([]);
  const [suggestions, setSuggestions] = React.useState<DetectedRegion[]>([]);
  const [protectedRegions, setProtectedRegions] = React.useState<DetectedRegion[]>([]);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const sourcePreview = (assets.data ?? []).find((asset) => asset.type === "source_preview");
  const source = (assets.data ?? []).find((asset) => asset.type === "source");
  const processed = (assets.data ?? []).find((asset) => asset.type === "processed_preview");
  const difference = (assets.data ?? []).find((asset) => asset.type === "difference");
  const imageUrl = source?.download_url ?? sourcePreview?.download_url ?? null;

  // Autosave the mask a short while after drawing stops.
  React.useEffect(() => {
    if (!store.dirty || !store.imageSize.width) return;
    const timer = window.setTimeout(() => {
      saveMask.mutate(store.toEditorState(), {
        onSuccess: (version) => {
          store.markSaved(version.version);
          setMaskVersion(version.version);
          setStatus(`Mask saved as version ${version.version}`);
        },
      });
    }, AUTOSAVE_DELAY);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.dirty, store.regions, store.adjustments, store.imageSize.width]);

  const saveNow = React.useCallback(() => {
    if (!store.imageSize.width) return;
    saveMask.mutate(store.toEditorState(), {
      onSuccess: (version) => {
        store.markSaved(version.version);
        setMaskVersion(version.version);
        setStatus(`Mask saved as version ${version.version}`);
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.imageSize.width, saveMask]);

  const checkMask = React.useCallback(async () => {
    setError(null);
    let version = maskVersion;
    if (store.dirty || version === null) {
      const saved = await saveMask.mutateAsync(store.toEditorState());
      version = saved.version;
      store.markSaved(saved.version);
      setMaskVersion(saved.version);
    }
    if (version === null) return null;
    const result = await previewMask.mutateAsync(version);
    setPreview(result);
    setProtectedRegions(
      result.protection.regions.filter((region) => region.kind !== "overlay_candidate"),
    );
    setStatus(
      result.protection.blocked
        ? "The selection overlaps protected content."
        : `Selection covers ${(result.coverage * 100).toFixed(1)}% of the image.`,
    );
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maskVersion, store.dirty, saveMask, previewMask]);

  const runCleanup = React.useCallback(async () => {
    setError(null);
    try {
      const checked = await checkMask();
      if (!checked) return;
      const blocking = checked.protection.overlaps.filter((item) => item.severity === "block");
      if (blocking.length > 0) {
        setError(checked.protection.explanation);
        return;
      }
      const job = await startCleanup.mutateAsync({
        mask_version: checked.version,
        mode,
        mask_approved: true,
        adjustments: store.adjustments,
        seed: 1,
        acknowledged_protected_kinds: acknowledged,
        idempotency_key: newIdempotencyKey("cleanup"),
      });
      setJobId(job.id);
      setStatus("Cleanup queued.");
    } catch (mutationError) {
      setError(
        mutationError instanceof ApiError
          ? mutationError.message
          : "The cleanup could not be started.",
      );
    }
  }, [checkMask, startCleanup, mode, store.adjustments, acknowledged]);

  useEditorShortcuts({
    onSave: saveNow,
    onProcess: () => void runCleanup(),
    onFit: () => store.fitToScreen({ width: 900, height: 600 }),
  });

  if (project.isLoading) {
    return (
      <AppShell wide>
        <div className="p-6">
          <Skeleton className="h-[70vh]" />
        </div>
      </AppShell>
    );
  }

  if (!imageUrl) {
    return (
      <AppShell>
        <Alert tone="warning" title="Upload an image first">
          This project has no source image yet.{" "}
          <Link className="underline" href={`/projects/${projectId}`}>
            Go back and upload one.
          </Link>
        </Alert>
      </AppShell>
    );
  }

  const maskReady = hasMaskContent(store);
  const blocked = preview?.protection.overlaps.some((item) => item.severity === "block") ?? false;
  const needsAcknowledgement =
    preview?.protection.unacknowledged_kinds.some((kind) => !acknowledged.includes(kind)) ?? false;

  return (
    <AppShell wide footer={false}>
      <LiveRegion message={status} />
      <div className="flex flex-col gap-4 border-b border-[var(--color-line)] px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs tracking-wide text-[var(--color-ink-subtle)] uppercase">
            Cleanup editor
          </p>
          <h1 className="truncate font-serif text-xl text-[var(--color-ink)]">
            {project.data?.name}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AutosaveIndicator
            saving={saveMask.isPending}
            dirty={store.dirty}
            version={store.lastSavedVersion}
          />
          <Button
            variant="secondary"
            size="sm"
            loading={detectOverlays.isPending}
            onClick={() =>
              detectOverlays.mutate(
                { limit: 20 },
                {
                  onSuccess: (result) => {
                    setSuggestions(result.candidates);
                    setProtectedRegions(result.protected_regions);
                    setStatus(
                      `${result.candidates.length} possible overlays found. They are suggestions; you decide.`,
                    );
                  },
                },
              )
            }
          >
            <Wand2 aria-hidden="true" />
            Detect overlays
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={previewMask.isPending}
            onClick={() => void checkMask()}
          >
            Check selection
          </Button>
          <Button
            size="sm"
            disabled={!maskReady || blocked || needsAcknowledgement}
            loading={startCleanup.isPending}
            onClick={() => void runCleanup()}
          >
            Process
          </Button>
        </div>
      </div>

      <div className="grid gap-4 p-4 sm:px-6 lg:grid-cols-[1fr_22rem]">
        <div className="flex flex-col gap-3">
          <EditorToolbar onFitToScreen={() => store.fitToScreen({ width: 900, height: 600 })} />
          {error ? (
            <Alert tone="danger" live>
              {error}
            </Alert>
          ) : null}
          {preview ? (
            <ProtectionNotice
              assessment={preview.protection}
              acknowledged={acknowledged}
              onAcknowledgeChange={setAcknowledged}
            />
          ) : null}

          <MaskCanvas
            imageUrl={imageUrl}
            protectedRegions={protectedRegions}
            suggestions={suggestions}
            onSuggestionClick={(region) =>
              store.addRegion({
                type: "rect",
                x: region.x,
                y: region.y,
                width: region.width,
                height: region.height,
                mode: "add",
              })
            }
            className="h-[58vh] min-h-80 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)]"
          />

          <Card>
            <CardHeader>
              <CardTitle>Result</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <ComparisonControls />
              <ComparisonView
                originalUrl={sourcePreview?.download_url ?? imageUrl}
                processedUrl={processed?.download_url ?? null}
                differenceUrl={difference?.download_url ?? null}
              />
              {processed ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    loading={createExport.isPending}
                    onClick={() =>
                      createExport.mutate(
                        { format: "png" },
                        { onSuccess: () => setStatus("Export created.") },
                      )
                    }
                  >
                    Export PNG
                  </Button>
                  <Button asChild size="sm" variant="secondary">
                    <Link href={`/projects/${projectId}/exports`}>View exports</Link>
                  </Button>
                  <p className="text-xs text-[var(--color-ink-muted)]">
                    Exports keep the original resolution, colour profile and metadata.
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <aside className="flex flex-col gap-4">
          <JobProgressPanel
            projectId={projectId}
            jobId={jobId}
            label="Cleaning the image"
            onFinished={(_result, jobStatus) =>
              setStatus(
                jobStatus === "succeeded"
                  ? "Cleanup finished. Compare the result below."
                  : `Cleanup ${jobStatus}.`,
              )
            }
          />

          <Card>
            <CardHeader>
              <CardTitle>Processing mode</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Select
                id="cleanup-mode"
                label="Mode"
                hideLabel
                value={mode}
                onValueChange={(value) => setMode(value as CleanupMode)}
                options={(Object.keys(CLEANUP_MODE_LABELS) as CleanupMode[]).map((key) => ({
                  value: key,
                  label: CLEANUP_MODE_LABELS[key],
                  description: CLEANUP_MODE_DESCRIPTIONS[key],
                }))}
              />
              {preview?.suggested_mode && preview.suggested_mode !== mode ? (
                <Alert tone="info">
                  Based on what surrounds your selection,{" "}
                  <Badge tone="info">{CLEANUP_MODE_LABELS[preview.suggested_mode]}</Badge> is likely
                  to work better here.
                  <div className="mt-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setMode(preview.suggested_mode)}
                    >
                      Use it
                    </Button>
                  </div>
                </Alert>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              <Tabs defaultValue="brush">
                <TabsList className="mb-4 w-full">
                  <TabsTrigger value="brush" className="flex-1">
                    Brush
                  </TabsTrigger>
                  <TabsTrigger value="mask" className="flex-1">
                    Mask
                  </TabsTrigger>
                  <TabsTrigger value="keys" className="flex-1">
                    Keys
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="brush">
                  <BrushPanel />
                </TabsContent>
                <TabsContent value="mask">
                  <MaskAdjustmentsPanel />
                </TabsContent>
                <TabsContent value="keys">
                  <ShortcutList />
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>

          {preview ? (
            <Card>
              <CardHeader>
                <CardTitle>Selection</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <dt className="text-xs text-[var(--color-ink-subtle)]">Coverage</dt>
                    <dd className="font-medium">{(preview.coverage * 100).toFixed(2)}%</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--color-ink-subtle)]">Regions</dt>
                    <dd className="font-medium">{preview.region_count}</dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>
    </AppShell>
  );
}
