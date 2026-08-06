"use client";

import { CloudUpload, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { timelineReviewPayload } from "@/lib/kirakara-review";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import { ApiRequestError, submitCloudRender } from "@/services/api";
import type { Job } from "@/types/job";

type CloudRenderState = "idle" | "uploading" | "error";

export function KirakaraCloudRenderControls({
  jobId,
  video,
  timeline,
  style,
  emphasized = false,
  onQueued,
}: {
  jobId: string;
  video: File;
  timeline: KirakaraTimeline;
  style?: KirakaraStyle;
  emphasized?: boolean;
  onQueued: (job: Job) => void;
}) {
  const [state, setState] = useState<CloudRenderState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function queueRender() {
    setState("uploading");
    setProgress(0);
    setError(null);
    try {
      const job = await submitCloudRender(
        jobId,
        video,
        timelineReviewPayload(timeline, style),
        setProgress,
      );
      onQueued(job);
    } catch (reason) {
      setState("error");
      setError(
        reason instanceof ApiRequestError
          ? `${reason.feedback.title}：${reason.feedback.description}`
          : "云端渲染提交失败，请检查网络后重试。",
      );
    }
  }

  return (
    <div className="mt-4 border-t pt-4">
      <button
        type="button"
        disabled={state === "uploading"}
        onClick={queueRender}
        className={`focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 ${
          emphasized
            ? "bg-primary text-primary-foreground"
            : "border bg-background hover:bg-muted"
        }`}
      >
        {state === "uploading" ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <CloudUpload className="size-4" />
        )}
        {state === "uploading"
          ? `正在上传原视频 ${progress}%`
          : "进入云端渲染队列"}
      </button>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        云端只使用已校正的时间轴和注音进行 Kirakara 视频嵌字，不会重新识别或对齐歌词。
      </p>
      {state === "uploading" && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-sm bg-muted" aria-label={`上传进度 ${progress}%`}>
          <div className="h-full bg-primary" style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && <p className="mt-3 text-sm text-destructive" role="alert">{error}</p>}
    </div>
  );
}
