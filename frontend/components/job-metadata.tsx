import { FileVideo, Hash } from "lucide-react";

import { JOB_COPY } from "@/lib/ui-copy";
import type { Job } from "@/types/job";

type JobMetadataValue = Pick<
  Job,
  "id" | "original_video_name" | "video_size_bytes" | "lyrics_source"
>;

function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function JobMetadata({ job }: { job: JobMetadataValue }) {
  return (
    <dl className="mt-8 grid gap-4 sm:grid-cols-2">
      <div className="min-w-0 rounded-xl bg-muted/65 p-4">
        <dt className="flex items-center gap-2 text-xs text-muted-foreground">
          <FileVideo className="size-4" />
          {JOB_COPY.submittedVideo}
        </dt>
        <dd className="mt-2 break-all text-sm font-medium">
          {job.original_video_name}
        </dd>
        <dd className="mt-1 text-xs text-muted-foreground">
          {formatBytes(job.video_size_bytes)}
        </dd>
      </div>
      <div className="min-w-0 rounded-xl bg-muted/65 p-4">
        <dt className="flex items-center gap-2 text-xs text-muted-foreground">
          <Hash className="size-4" />
          {JOB_COPY.taskId}
        </dt>
        <dd className="mt-2 break-all font-mono text-xs">{job.id}</dd>
        <dd className="mt-1 text-xs text-muted-foreground">
          {JOB_COPY.lyricsSource}：
          {job.lyrics_source === "file"
            ? JOB_COPY.textFileLyrics
            : JOB_COPY.pastedLyrics}
        </dd>
      </div>
    </dl>
  );
}
