"use client";

import { OWNERSHIP_STATEMENT, type AssetAnalysis } from "@artrestore/types";
import { Alert, Button, ConsentCheckbox, formatBytes } from "@artrestore/ui";
import { ImageUp, Loader2 } from "lucide-react";
import * as React from "react";

import { ApiError } from "@/lib/api";
import { useUploadAsset } from "@/lib/queries";

const DEFAULT_ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/tiff"];
const MAX_BYTES = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES ?? 41_943_040);

/**
 * The upload panel.
 *
 * Processing is gated on the ownership attestation: the button stays disabled
 * until the box is ticked, and the server refuses the completion call anyway,
 * so the gate is not merely visual.
 */
export function UploadDropzone({
  projectId,
  assetType = "source",
  retentionDays,
  onUploaded,
  requireOwnership = true,
  title = "Upload an image",
  description,
}: {
  projectId: string;
  assetType?: "source" | "intermediate" | "line_art" | "audio";
  retentionDays?: number;
  onUploaded?: (assetId: string, analysis: AssetAnalysis | null) => void;
  requireOwnership?: boolean;
  title?: string;
  description?: React.ReactNode;
}) {
  const upload = useUploadAsset(projectId);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [file, setFile] = React.useState<File | null>(null);
  const [dimensions, setDimensions] = React.useState<{ width: number; height: number } | null>(null);
  const [owns, setOwns] = React.useState(!requireOwnership);
  const [dragging, setDragging] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const accept = assetType === "audio" ? ["audio/mpeg", "audio/wav", "audio/ogg"] : DEFAULT_ACCEPT;

  // Derived during render so no effect has to set it, with the URL revoked when
  // the file changes or the panel unmounts.
  const preview = React.useMemo(
    () => (file && assetType !== "audio" ? URL.createObjectURL(file) : null),
    [file, assetType],
  );

  React.useEffect(() => {
    if (!preview) return;
    const image = new Image();
    image.onload = () => setDimensions({ width: image.naturalWidth, height: image.naturalHeight });
    image.src = preview;
    return () => {
      image.onload = null;
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const chooseFile = (candidate: File | undefined) => {
    setError(null);
    if (!candidate) return;
    if (!accept.includes(candidate.type)) {
      setError(`${candidate.type || "That file type"} is not supported. Use ${accept.join(", ")}.`);
      return;
    }
    if (candidate.size > MAX_BYTES) {
      setError(`That file is ${formatBytes(candidate.size)}; the limit is ${formatBytes(MAX_BYTES)}.`);
      return;
    }
    setFile(candidate);
  };

  const submit = () => {
    if (!file) return;
    setError(null);
    upload.mutate(
      { file, assetType, ownershipConfirmed: owns },
      {
        onSuccess: ({ assetId, analysis }) => {
          onUploaded?.(assetId, analysis);
          setFile(null);
          setDimensions(null);
        },
        onError: (mutationError) => {
          setError(
            mutationError instanceof ApiError
              ? mutationError.message
              : "The upload could not be completed.",
          );
        },
      },
    );
  };

  const estimatedOutput = dimensions ? dimensions.width * dimensions.height * 1.6 : 0;

  return (
    <div className="flex flex-col gap-4">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          chooseFile(event.dataTransfer.files[0]);
        }}
        className={`flex flex-col items-center gap-3 rounded-[var(--radius-lg)] border-2 border-dashed p-8 text-center transition-colors ${
          dragging
            ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)]"
            : "border-[var(--color-line-strong)] bg-[var(--color-paper-raised)]"
        }`}
      >
        <ImageUp className="size-8 text-[var(--color-ink-subtle)]" aria-hidden="true" />
        <div>
          <p className="text-sm font-semibold text-[var(--color-ink)]">{title}</p>
          <p className="mt-1 text-sm text-[var(--color-ink-muted)]">
            {description ?? (
              <>
                Drag a file here, or choose one. JPG, PNG, WebP and TIFF up to{" "}
                {formatBytes(MAX_BYTES)}.
              </>
            )}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={accept.join(",")}
          className="sr-only"
          // The visible button is the keyboard affordance; a duplicate tab stop
          // on the hidden input would just be a dead end.
          tabIndex={-1}
          aria-label="Choose a file to upload"
          onChange={(event) => chooseFile(event.target.files?.[0])}
        />
        <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()}>
          Choose a file
        </Button>
      </div>

      {file ? (
        <div className="flex flex-col gap-4 rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-paper-raised)] p-4 sm:flex-row">
          {preview && assetType !== "audio" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={preview}
              alt=""
              className="h-32 w-32 rounded-[var(--radius-md)] border border-[var(--color-line)] object-cover"
            />
          ) : null}
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="truncate text-sm font-medium text-[var(--color-ink)]">{file.name}</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--color-ink-muted)]">
              <div className="flex gap-1.5">
                <dt>Size</dt>
                <dd className="font-medium text-[var(--color-ink)]">{formatBytes(file.size)}</dd>
              </div>
              {dimensions ? (
                <div className="flex gap-1.5">
                  <dt>Dimensions</dt>
                  <dd className="font-medium text-[var(--color-ink)]">
                    {dimensions.width} × {dimensions.height}
                  </dd>
                </div>
              ) : null}
              <div className="flex gap-1.5">
                <dt>Colour</dt>
                <dd className="font-medium text-[var(--color-ink)]">
                  {file.type.replace("image/", "").toUpperCase()}
                </dd>
              </div>
              {estimatedOutput > 0 ? (
                <div className="flex gap-1.5">
                  <dt>Est. export</dt>
                  <dd className="font-medium text-[var(--color-ink)]">
                    ~{formatBytes(estimatedOutput)}
                  </dd>
                </div>
              ) : null}
            </dl>
            {retentionDays ? (
              <p className="text-xs text-[var(--color-ink-muted)]">
                This file is private to your account, is never used to train models, and is deleted
                automatically after {retentionDays} {retentionDays === 1 ? "day" : "days"}.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      {requireOwnership ? (
        <ConsentCheckbox
          id={`ownership-${projectId}-${assetType}`}
          checked={owns}
          onCheckedChange={setOwns}
          label={OWNERSHIP_STATEMENT}
          description="Required before anything is processed. Your confirmation is recorded with the policy version in force."
        />
      ) : null}

      {error ? (
        <Alert tone="danger" live>
          {error}
        </Alert>
      ) : null}

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!file || !owns || upload.isPending} loading={upload.isPending}>
          {upload.isPending ? "Uploading" : "Upload and continue"}
        </Button>
        {!owns && requireOwnership ? (
          <p className="text-xs text-[var(--color-ink-muted)]">
            Confirm ownership to enable processing.
          </p>
        ) : null}
        {upload.isPending ? (
          <Loader2 className="size-4 animate-spin text-[var(--color-ink-subtle)]" aria-hidden="true" />
        ) : null}
      </div>
    </div>
  );
}
