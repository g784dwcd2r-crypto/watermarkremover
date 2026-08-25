"use client";

import type { Job } from "@artrestore/types";
import { Alert, Button, Progress } from "@artrestore/ui";
import * as React from "react";

import { useCancelJob, useJob, useRetryJob } from "@/lib/queries";
import { mergeJobState, useJobProgress } from "@/lib/use-job-progress";

/**
 * Live job status.
 *
 * Progress arrives over SSE and falls back to the job row, so a dropped
 * connection shows stale-but-true state rather than a stuck bar.
 */
export function JobProgressPanel({
  projectId,
  jobId,
  job,
  label,
  onFinished,
}: {
  projectId: string;
  jobId: string | null;
  job?: Job;
  label: string;
  onFinished?: (result: Record<string, unknown> | null, status: string) => void;
}) {
  const stream = useJobProgress(projectId, jobId);
  // The polling fallback only runs while it is actually needed: the stream is
  // down (or never opened) and the job has not reached a terminal state. With a
  // healthy stream this query stays idle.
  const streamTerminal = ["succeeded", "failed", "cancelled"].includes(stream.status);
  const needsPolling = Boolean(jobId) && !stream.streaming && !streamTerminal;
  const { data: polledJob } = useJob(projectId, jobId, needsPolling);
  const state = mergeJobState(job ?? polledJob, stream);
  const cancel = useCancelJob(projectId);
  const retry = useRetryJob(projectId);
  const notified = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!jobId) return;
    const terminal = ["succeeded", "failed", "cancelled"].includes(state.status);
    if (terminal && notified.current !== jobId) {
      notified.current = jobId;
      onFinished?.(state.result, state.status);
    }
  }, [state.status, state.result, jobId, onFinished]);

  if (!jobId || state.status === "idle") return null;

  const running = state.status === "queued" || state.status === "running";

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-paper-raised)] p-4">
      <Progress
        value={state.progress}
        label={label}
        message={state.message || (running ? "Working" : undefined)}
      />

      {state.status === "failed" ? (
        <Alert
          tone={state.errorCode === "protected_region" ? "protected" : "danger"}
          title={
            state.errorCode === "protected_region"
              ? "Processing stopped: attribution content detected"
              : state.errorCode === "protected_region_review"
                ? "Processing paused for confirmation"
                : "This job did not finish"
          }
          live
        >
          <p>{state.errorMessage ?? "Something went wrong."}</p>
          {state.errorCode && state.errorCode !== "protected_region" ? (
            <div className="mt-3">
              <Button
                size="sm"
                variant="secondary"
                loading={retry.isPending}
                onClick={() => retry.mutate(jobId)}
              >
                Try again
              </Button>
            </div>
          ) : null}
        </Alert>
      ) : null}

      {state.status === "cancelled" ? (
        <Alert tone="info" live>
          This job was cancelled. Nothing was written.
        </Alert>
      ) : null}

      {running ? (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            loading={cancel.isPending}
            onClick={() => cancel.mutate(jobId)}
          >
            Cancel
          </Button>
          {!state.streaming ? (
            <span className="text-xs text-[var(--color-ink-subtle)]">
              Live updates unavailable; refreshing periodically.
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
