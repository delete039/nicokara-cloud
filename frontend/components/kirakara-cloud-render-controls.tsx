"use client";

import { CloudUpload, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import {
  networkErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { timelineReviewPayload } from "@/lib/kirakara-review";
import type { KirakaraTimeline } from "@/lib/kirakara-timeline";
import type { KirakaraStyle } from "@/lib/kirakara-style";
import { ApiRequestError, submitCloudRender } from "@/services/api";
import type { Job } from "@/types/job";

type CloudRenderState = "idle" | "uploading" | "error";

export function cloudRenderErrorFeedback(reason: unknown): ErrorFeedback {
  return reason instanceof ApiRequestError
    ? reason.feedback
    : networkErrorFeedback("cloud_render");
}

export function KirakaraCloudRenderControls({
  jobId,
  video,
  timeline,
  style,
  emphasized = false,
  discouraged = false,
  rerender = false,
  onQueued,
}: {
  jobId: string;
  video: File;
  timeline: KirakaraTimeline;
  style?: KirakaraStyle;
  emphasized?: boolean;
  discouraged?: boolean;
  rerender?: boolean;
  onQueued: (job: Job) => void;
}) {
  const [state, setState] = useState<CloudRenderState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ErrorFeedback | null>(null);
  const idleLabel = discouraged
    ? rerender
      ? "重新云端导出（不推荐）"
      : "云端导出（不推荐）"
    : rerender
      ? "按当前设置重新云端渲染"
      : "进入云端渲染队列";

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
      setError(cloudRenderErrorFeedback(reason));
    }
  }

  function returnToEditor() {
    setState("idle");
    setError(null);
    requestAnimationFrame(() => {
      const editor = document.querySelector<HTMLElement>(
        '[data-kirakara-timeline-panel="true"]',
      );
      editor?.scrollIntoView({ behavior: "smooth", block: "start" });
      editor
        ?.querySelector<HTMLElement>("select, input, button")
        ?.focus({ preventScroll: true });
    });
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
          : idleLabel}
      </button>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        {discouraged &&
          "会重新上传原视频并占用服务器渲染队列；本地导出可用时，建议优先使用本地导出。"}
        云端只使用已校正的时间轴和注音进行 Kirakara 视频嵌字，不会重新识别或对齐歌词。
      </p>
      {state === "uploading" && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-sm bg-muted" aria-label={`上传进度 ${progress}%`}>
          <div className="h-full bg-primary" style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && (
        <div className="mt-4">
          <ErrorFeedbackPanel feedback={error} onEdit={returnToEditor} />
        </div>
      )}
    </div>
  );
}
