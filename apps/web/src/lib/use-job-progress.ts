"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Job, JobProgressEvent, JobStatus } from "@artrestore/types";
import * as React from "react";

import { API_BASE_URL } from "./api";
import { queryKeys } from "./queries";

export interface JobProgressState {
  status: JobStatus | "idle";
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  errorCode: string | null;
  errorMessage: string | null;
  /** True while the stream is connected; false once the job reaches a terminal state. */
  streaming: boolean;
}

const IDLE: JobProgressState = {
  status: "idle",
  progress: 0,
  message: "",
  result: null,
  errorCode: null,
  errorMessage: null,
  streaming: false,
};

/**
 * Follow a job over Server-Sent Events.
 *
 * The stream is the fast path; the query cache is still refreshed when the job
 * finishes, so a dropped connection degrades to normal refetching rather than a
 * progress bar frozen at 40%.
 */
export function useJobProgress(projectId: string, jobId: string | null): JobProgressState {
  const client = useQueryClient();
  // The state carries the job it belongs to, so switching jobs reads as idle
  // during render rather than needing an effect to reset it.
  const [tracked, setTracked] = React.useState<{ jobId: string; state: JobProgressState } | null>(
    null,
  );
  const state = tracked && tracked.jobId === jobId ? tracked.state : IDLE;

  React.useEffect(() => {
    if (!projectId || !jobId) return;

    const setState = (
      next: JobProgressState | ((previous: JobProgressState) => JobProgressState),
    ) =>
      setTracked((current) => {
        const base = current && current.jobId === jobId ? current.state : IDLE;
        return { jobId, state: typeof next === "function" ? next(base) : next };
      });

    const source = new EventSource(
      `${API_BASE_URL}/v1/projects/${projectId}/jobs/${jobId}/events`,
      { withCredentials: true },
    );

    const applyEvent = (event: MessageEvent<string>) => {
      let payload: JobProgressEvent;
      try {
        payload = JSON.parse(event.data) as JobProgressEvent;
      } catch {
        return;
      }
      setState({
        status: payload.status,
        progress: payload.progress,
        message: payload.message,
        result: payload.result ?? null,
        errorCode: payload.error_code ?? null,
        errorMessage: payload.error_message ?? null,
        streaming: !["succeeded", "failed", "cancelled"].includes(payload.status),
      });
    };

    const finish = (event: MessageEvent<string>) => {
      applyEvent(event);
      source.close();
      void client.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.assets(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.exports(projectId) });
    };

    source.addEventListener("progress", applyEvent as EventListener);
    source.addEventListener("done", finish as EventListener);
    source.addEventListener("error", () => {
      // The browser retries automatically; fall back to polling the job row.
      setState((previous) => ({ ...previous, streaming: false }));
      void client.invalidateQueries({ queryKey: queryKeys.job(projectId, jobId) });
    });

    return () => source.close();
  }, [projectId, jobId, client]);

  return state;
}

/** Merge stream state with the last known job row, preferring whichever is fresher. */
export function mergeJobState(job: Job | undefined, stream: JobProgressState): JobProgressState {
  if (!job) return stream;
  if (stream.status === "idle") {
    return {
      status: job.status,
      progress: job.progress,
      message: job.progress_message,
      result: job.result,
      errorCode: job.error_code,
      errorMessage: job.error_message,
      streaming: false,
    };
  }
  return stream.progress >= job.progress
    ? stream
    : {
        status: job.status,
        progress: job.progress,
        message: job.progress_message,
        result: job.result,
        errorCode: job.error_code,
        errorMessage: job.error_message,
        streaming: stream.streaming,
      };
}
