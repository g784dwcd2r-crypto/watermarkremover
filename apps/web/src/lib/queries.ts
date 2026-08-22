/**
 * TanStack Query hooks.
 *
 * Every server interaction goes through here so cache invalidation stays in one
 * place: a cleanup run touches the project, its assets, its jobs and its
 * exports, and forgetting one of those is how stale editors happen.
 */

"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import type {
  Asset,
  AssetAnalysis,
  ConsentRecord,
  ExportList,
  ExportRecord,
  Job,
  MaskEditorState,
  MaskPreview,
  MaskVersion,
  OverlayDetection,
  PolicyInfo,
  ProjectDetail,
  ProjectList,
  ProjectType,
  SegmentResult,
  SessionResponse,
  StageList,
  StorageUsage,
  TimelapseOptions,
  TimelapseRenderRequest,
  UploadInit,
  User,
} from "@artrestore/types";

import { api, uploadToSignedUrl } from "./api";

export const queryKeys = {
  session: ["session"] as const,
  policies: ["policies"] as const,
  usage: ["account", "usage"] as const,
  consents: ["account", "consents"] as const,
  projects: (filters?: Record<string, unknown>) => ["projects", filters ?? {}] as const,
  project: (id: string) => ["project", id] as const,
  assets: (id: string) => ["project", id, "assets"] as const,
  masks: (id: string) => ["project", id, "masks"] as const,
  jobs: (id: string) => ["project", id, "jobs"] as const,
  job: (projectId: string, jobId: string) => ["project", projectId, "job", jobId] as const,
  exports: (id: string) => ["project", id, "exports"] as const,
  stages: (id: string) => ["project", id, "stages"] as const,
  timelapseOptions: (id: string) => ["project", id, "timelapse-options"] as const,
};

// -- session ----------------------------------------------------------------

export function useSession(options?: Partial<UseQueryOptions<User | null>>) {
  return useQuery<User | null>({
    queryKey: queryKeys.session,
    queryFn: async () => {
      try {
        return await api.get<User>("/v1/auth/session");
      } catch {
        return null;
      }
    },
    staleTime: 60_000,
    ...options,
  });
}

export function usePolicies() {
  return useQuery<PolicyInfo>({
    queryKey: queryKeys.policies,
    queryFn: () => api.get<PolicyInfo>("/v1/policies"),
    staleTime: 10 * 60_000,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; password: string }) =>
      api.post<SessionResponse>("/v1/auth/login", input),
    onSuccess: (data) => client.setQueryData(queryKeys.session, data.user),
  });
}

export function useRegister() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      email: string;
      name: string;
      password: string;
      accept_terms: boolean;
      accept_authorized_use_policy: boolean;
    }) => api.post<SessionResponse>("/v1/auth/register", input),
    onSuccess: (data) => client.setQueryData(queryKeys.session, data.user),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/v1/auth/logout"),
    onSuccess: () => client.clear(),
  });
}

export function useRequestPasswordReset() {
  return useMutation({
    mutationFn: (input: { email: string }) =>
      api.post<{ status: string; message: string; debug_token?: string }>(
        "/v1/auth/password-reset",
        input,
      ),
  });
}

export function useConfirmPasswordReset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { token: string; password: string }) =>
      api.post<SessionResponse>("/v1/auth/password-reset/confirm", input),
    onSuccess: (data) => client.setQueryData(queryKeys.session, data.user),
  });
}

export function useRequestMagicLink() {
  return useMutation({
    mutationFn: (input: { email: string }) =>
      api.post<{ status: string; message: string; debug_token?: string }>(
        "/v1/auth/magic-link",
        input,
      ),
  });
}

// -- account ----------------------------------------------------------------

export function useStorageUsage() {
  return useQuery<StorageUsage>({
    queryKey: queryKeys.usage,
    queryFn: () => api.get<StorageUsage>("/v1/account/usage"),
  });
}

export function useConsents() {
  return useQuery<ConsentRecord[]>({
    queryKey: queryKeys.consents,
    queryFn: () => api.get<ConsentRecord[]>("/v1/account/consents"),
  });
}

export function useUpdateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name?: string; retention_days?: 1 | 7 | 30 }) =>
      api.patch<User>("/v1/account", input),
    onSuccess: (user) => {
      client.setQueryData(queryKeys.session, user);
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { password?: string }) =>
      api.post<void>("/v1/account/delete", { confirm: "DELETE", ...input }),
    onSuccess: () => client.clear(),
  });
}

// -- projects ---------------------------------------------------------------

export function useProjects(filters: {
  project_type?: ProjectType;
  status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "" && value !== null) params.set(key, String(value));
  }
  const suffix = params.toString();
  return useQuery<ProjectList>({
    queryKey: queryKeys.projects(filters),
    queryFn: () => api.get<ProjectList>(`/v1/projects${suffix ? `?${suffix}` : ""}`),
  });
}

export function useProject(projectId: string, options?: { refetchInterval?: number | false }) {
  return useQuery<ProjectDetail>({
    queryKey: queryKeys.project(projectId),
    queryFn: () => api.get<ProjectDetail>(`/v1/projects/${projectId}`),
    enabled: Boolean(projectId),
    ...options,
  });
}

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; project_type: ProjectType; retention_days?: 1 | 7 | 30 }) =>
      api.post<ProjectDetail>("/v1/projects", input),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name?: string; retention_days?: 1 | 7 | 30 }) =>
      api.patch<ProjectDetail>(`/v1/projects/${projectId}`, input),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.project(projectId), data);
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDuplicateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      api.post<ProjectDetail>(`/v1/projects/${projectId}/duplicate`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDeleteProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.delete<void>(`/v1/projects/${projectId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["projects"] });
      void client.invalidateQueries({ queryKey: queryKeys.usage });
    },
  });
}

export function useRecordConsent(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { consent_type: string; statement?: string; context?: unknown }) =>
      api.post<ConsentRecord>(`/v1/projects/${projectId}/consent`, { confirmed: true, ...input }),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.project(projectId) }),
  });
}

// -- assets -----------------------------------------------------------------

export function useAssets(projectId: string, assetType?: string) {
  const suffix = assetType ? `?asset_type=${assetType}` : "";
  return useQuery<Asset[]>({
    queryKey: [...queryKeys.assets(projectId), assetType ?? "all"],
    queryFn: () => api.get<Asset[]>(`/v1/projects/${projectId}/assets${suffix}`),
    enabled: Boolean(projectId),
  });
}

/** The three-step upload: reserve, PUT to storage, then confirm ownership. */
export function useUploadAsset(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      file: File;
      assetType?: "source" | "intermediate" | "line_art" | "audio";
      ownershipConfirmed: boolean;
    }): Promise<{ assetId: string; analysis: AssetAnalysis | null }> => {
      const init = await api.post<UploadInit>(`/v1/projects/${projectId}/assets/uploads`, {
        filename: input.file.name,
        content_type: input.file.type,
        byte_size: input.file.size,
        asset_type: input.assetType ?? "source",
      });
      await uploadToSignedUrl(init.upload, input.file);
      const analysis = await api.post<AssetAnalysis>(
        `/v1/projects/${projectId}/assets/uploads/complete`,
        { asset_id: init.asset_id, ownership_confirmed: input.ownershipConfirmed },
      );
      return { assetId: init.asset_id, analysis };
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.assets(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.usage });
    },
  });
}

export function useDeleteAsset(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (assetId: string) =>
      api.delete<void>(`/v1/projects/${projectId}/assets/${assetId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.assets(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    },
  });
}

// -- masks ------------------------------------------------------------------

export function useMasks(projectId: string) {
  return useQuery<MaskVersion[]>({
    queryKey: queryKeys.masks(projectId),
    queryFn: () => api.get<MaskVersion[]>(`/v1/projects/${projectId}/masks`),
    enabled: Boolean(projectId),
  });
}

export function useSaveMask(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (editorState: MaskEditorState) =>
      api.post<MaskVersion>(`/v1/projects/${projectId}/masks`, { editor_state: editorState }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.masks(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    },
  });
}

export function usePreviewMask(projectId: string) {
  return useMutation({
    mutationFn: (version: number) =>
      api.post<MaskPreview>(`/v1/projects/${projectId}/masks/${version}/preview`),
  });
}

export function useDetectOverlays(projectId: string) {
  return useMutation({
    mutationFn: (input?: { asset_id?: string; limit?: number }) =>
      api.post<OverlayDetection>(`/v1/projects/${projectId}/detect-overlays`, input ?? {}),
  });
}

export function useSegment(projectId: string) {
  return useMutation({
    mutationFn: (input: { mode: "box" | "point" | "text"; box?: number[]; point?: number[] }) =>
      api.post<SegmentResult>(`/v1/projects/${projectId}/segment`, input),
  });
}

// -- jobs -------------------------------------------------------------------

export function useJobs(projectId: string, jobType?: string) {
  const suffix = jobType ? `?job_type=${jobType}` : "";
  return useQuery<{ items: Job[]; total: number }>({
    queryKey: [...queryKeys.jobs(projectId), jobType ?? "all"],
    queryFn: () =>
      api.get<{ items: Job[]; total: number }>(`/v1/projects/${projectId}/jobs${suffix}`),
    enabled: Boolean(projectId),
  });
}

export function useJob(projectId: string, jobId: string | null, poll = false) {
  return useQuery<Job>({
    queryKey: queryKeys.job(projectId, jobId ?? ""),
    queryFn: () => api.get<Job>(`/v1/projects/${projectId}/jobs/${jobId}`),
    enabled: Boolean(projectId && jobId),
    refetchInterval: poll ? 1500 : false,
  });
}

export function useStartCleanup(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: Record<string, unknown>) =>
      api.post<Job>(`/v1/projects/${projectId}/cleanup`, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.project(projectId) });
    },
  });
}

export function useCancelJob(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<Job>(`/v1/projects/${projectId}/jobs/${jobId}/cancel`),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) }),
  });
}

export function useRetryJob(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<Job>(`/v1/projects/${projectId}/jobs/${jobId}/retry`),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) }),
  });
}

// -- timelapse --------------------------------------------------------------

export function useTimelapseOptions(projectId: string) {
  return useQuery<TimelapseOptions>({
    queryKey: queryKeys.timelapseOptions(projectId),
    queryFn: () => api.get<TimelapseOptions>(`/v1/projects/${projectId}/timelapse/options`),
    enabled: Boolean(projectId),
    staleTime: 10 * 60_000,
  });
}

export function useStages(projectId: string) {
  return useQuery<StageList>({
    queryKey: queryKeys.stages(projectId),
    queryFn: () => api.get<StageList>(`/v1/projects/${projectId}/timelapse/stages`),
    enabled: Boolean(projectId),
  });
}

export function useSaveStages(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (stages: Array<Record<string, unknown>>) =>
      api.put<StageList>(`/v1/projects/${projectId}/timelapse/stages`, { stages }),
    onSuccess: (data) => client.setQueryData(queryKeys.stages(projectId), data),
  });
}

export function useAnalyzeArtwork(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { mode: string; seed?: number; asset_id?: string }) =>
      api.post<Job>(`/v1/projects/${projectId}/timelapse/analyze`, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.stages(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) });
    },
  });
}

export function useRenderTimelapse(projectId: string, preview: boolean) {
  const client = useQueryClient();
  const path = preview ? "preview" : "render";
  return useMutation({
    mutationFn: (input: Partial<TimelapseRenderRequest>) =>
      api.post<Job>(`/v1/projects/${projectId}/timelapse/${path}`, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.jobs(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.exports(projectId) });
    },
  });
}

// -- exports ----------------------------------------------------------------

export function useExports(projectId: string) {
  return useQuery<ExportList>({
    queryKey: queryKeys.exports(projectId),
    queryFn: () => api.get<ExportList>(`/v1/projects/${projectId}/exports`),
    enabled: Boolean(projectId),
  });
}

export function useCreateExport(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { format: "png" | "jpeg" | "webp" | "tiff"; quality?: number }) =>
      api.post<ExportRecord>(`/v1/projects/${projectId}/exports`, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.exports(projectId) });
      void client.invalidateQueries({ queryKey: queryKeys.usage });
    },
  });
}

/** Signed download links are minted on demand and never cached. */
export function useDownloadExport(projectId: string) {
  return useMutation({
    mutationFn: (exportId: string) =>
      api.get<ExportRecord>(`/v1/projects/${projectId}/exports/${exportId}/download`),
  });
}

export function useDeleteExport(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (exportId: string) =>
      api.delete<void>(`/v1/projects/${projectId}/exports/${exportId}`),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.exports(projectId) }),
  });
}
