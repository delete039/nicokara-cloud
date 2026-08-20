"use client";

import { Download, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { KirakaraProjectDownload } from "@/components/kirakara-project-download";
import type { ErrorFeedback } from "@/lib/error-feedback";
import {
  TimelineReviewValidationError,
  timelineReviewPayload,
} from "@/lib/kirakara-review";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import { JOB_COPY } from "@/lib/ui-copy";
import {
  ApiRequestError,
  getReviewedArtifact,
  type ReviewedArtifact,
} from "@/services/api";

const ARTIFACTS: Array<{
  artifact: ReviewedArtifact;
  label: string;
  suffix: string;
}> = [
  {
    artifact: "lyrics",
    label: JOB_COPY.downloadReviewedLyrics,
    suffix: ".readings.json",
  },
  {
    artifact: "timeline",
    label: JOB_COPY.downloadReviewedTimeline,
    suffix: ".timeline.json",
  },
  {
    artifact: "subtitle",
    label: JOB_COPY.downloadReviewedAss,
    suffix: ".ass",
  },
];

function downloadName(videoName: string, suffix: string): string {
  const stem = videoName.replace(/\.[^.]+$/u, "").trim() || "nicokara";
  return `${stem.replace(/[\\/:*?"<>|]/gu, "_")}${suffix}`;
}

export function ReviewedDataDownloads({
  jobId,
  videoName,
  timeline,
  style,
}: {
  jobId: string;
  videoName: string;
  timeline: KirakaraTimeline;
  style: KirakaraStyle;
}) {
  const [downloading, setDownloading] = useState<ReviewedArtifact | null>(null);
  const [error, setError] = useState<ErrorFeedback | null>(null);

  async function downloadArtifact(
    artifact: ReviewedArtifact,
    suffix: string,
  ) {
    if (downloading) return;
    setDownloading(artifact);
    setError(null);
    try {
      const blob = await getReviewedArtifact(
        jobId,
        artifact,
        timelineReviewPayload(timeline, style),
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloadName(videoName, suffix);
      document.body.appendChild(anchor);
      anchor.click();
      globalThis.setTimeout(() => {
        anchor.remove();
        URL.revokeObjectURL(url);
      }, 1000);
    } catch (reason) {
      setError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : reason instanceof TimelineReviewValidationError
            ? {
                title: "调整后的时间轴无效",
                description: reason.message,
                solutions: [
                  "返回时间轴检查，修正提示中的歌词行后再下载。",
                  "如无法确认修改内容，请刷新任务页恢复服务器保存的时间轴。",
                ],
                technicalDetails: [],
                retryable: false,
              }
            : {
                title: "调整后数据生成失败",
                description: "暂时无法生成下载文件，请刷新任务页后重试。",
                solutions: ["刷新任务页后重新下载。"],
                technicalDetails: [],
                retryable: true,
              },
      );
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div data-reviewed-data-downloads="true" className="flex flex-wrap gap-2">
      {ARTIFACTS.map(({ artifact, label, suffix }) => (
        <button
          key={artifact}
          type="button"
          onClick={() => downloadArtifact(artifact, suffix)}
          disabled={downloading !== null}
          className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-semibold transition hover:bg-muted disabled:opacity-60"
        >
          {downloading === artifact ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : (
            <Download className="size-4" />
          )}
          {label}
        </button>
      ))}
      <KirakaraProjectDownload
        jobId={jobId}
        videoName={videoName}
        timeline={timeline}
        style={style}
      />
      {error && (
        <div className="basis-full pt-2">
          <ErrorFeedbackPanel feedback={error} />
        </div>
      )}
    </div>
  );
}
