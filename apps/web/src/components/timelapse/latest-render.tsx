"use client";

import { Button, Card, CardContent, CardHeader, CardTitle } from "@artrestore/ui";
import { Play } from "lucide-react";
import * as React from "react";

import { useDownloadExport } from "@/lib/queries";

interface ExportEntry {
  export_id: string;
  output: string;
}

/**
 * Plays the most recent render without leaving the editor.
 *
 * The signed URL is minted on demand and never cached; if it expires mid-watch
 * the user reloads it with one click rather than re-rendering anything.
 */
export function LatestRender({
  projectId,
  exports,
  preview,
}: {
  projectId: string;
  exports: ExportEntry[];
  preview: boolean;
}) {
  const download = useDownloadExport(projectId);
  const [url, setUrl] = React.useState<string | null>(null);
  const [loadedFor, setLoadedFor] = React.useState<string | null>(null);

  const video = exports.find((entry) => entry.output === "mp4" || entry.output === "webm");
  if (!video) return null;

  const load = () => {
    download.mutate(video.export_id, {
      onSuccess: (record) => {
        if (record.download_url) {
          setUrl(record.download_url);
          setLoadedFor(video.export_id);
        }
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{preview ? "Latest preview" : "Latest render"}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {url && loadedFor === video.export_id ? (
          <>
            {}
            <video
              src={url}
              controls
              playsInline
              autoPlay
              muted
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-black"
            />
            <p className="text-xs text-[var(--color-ink-subtle)]">
              Playback links expire after a few minutes; press play again to renew.
            </p>
          </>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            className="self-start"
            loading={download.isPending}
            onClick={load}
          >
            <Play aria-hidden="true" />
            Watch it here
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
