"use client";

import { CheckCircle2, CircleAlert, CloudUpload, LoaderCircle, Pause } from "lucide-react";
import { useEffect, useRef, useState } from "react";

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
import { jobPresentation } from "@/lib/job-presentation";

type CloudRenderState = "idle" | "uploading" | "paused" | "error";

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
  vocalMode = "on",
  disabled = false,
  job,
  onQueued,
}: {
  jobId: string;
  video: File | null;
  timeline: KirakaraTimeline;
  style?: KirakaraStyle;
  emphasized?: boolean;
  discouraged?: boolean;
  rerender?: boolean;
  vocalMode?: "on" | "off";
  disabled?: boolean;
  job?: Job;
  onQueued: (job: Job) => void;
}) {
  const [state, setState] = useState<CloudRenderState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ErrorFeedback | null>(null);
  const controller = useRef<AbortController | null>(null);
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  const modeLabel = vocalMode === "on" ? "ON VOCAL" : "OFF VOCAL";
  const matchesMode = job?.id === jobId
    && (job.render_vocal_mode ?? (job.off_vocal_conversion ? "off" : job.vocal_mode ?? "on")) === vocalMode;
  const renderJob = matchesMode && (job?.render_vocal_mode || job?.render_pending
    || job?.off_vocal_conversion || job?.status === "COMPLETED") ? job : undefined;
  const rendering = Boolean(renderJob && ["UPLOADED", "PROCESSING"].includes(renderJob.status));
  const failed = renderJob?.status === "FAILED";
  const canceled = renderJob?.status === "CANCELED";
  const complete = renderJob?.status === "COMPLETED";
  const uploading = state === "uploading";
  const showProgress = state !== "error" && (uploading || state === "paused" || rendering || failed || canceled || complete);
  const progressValue = Math.max(0, Math.min(100, Math.round(
    uploading || state === "paused" ? progress : renderJob?.progress ?? 0,
  )));
  const statusLabel = uploading
    ? queuePosition ? `等待上传，第 ${queuePosition} 位` : "正在上传原视频"
    : state === "paused" ? "上传已暂停"
    : failed ? "云端导出失败" : canceled ? "云端导出已取消"
    : complete ? "云端视频已生成"
    : renderJob?.status === "UPLOADED"
      ? renderJob.queue_position ? `排队第 ${renderJob.queue_position} 位` : "等待云端处理"
      : renderJob ? jobPresentation(renderJob.status, renderJob.stage, renderJob.input_mode).title : "";
  useEffect(() => () => controller.current?.abort(), []);
  const idleLabel = discouraged
    ? rerender
      ? "重新云端导出（不推荐）"
      : "云端导出（不推荐）"
    : rerender
      ? "按当前设置重新云端渲染"
      : "进入云端渲染队列";

  async function queueRender() {
    if (controller.current || disabled || rendering || failed || canceled || !video) return;
    const uploadController = new AbortController();
    controller.current = uploadController;
    setState("uploading");
    setProgress(0);
    setError(null);
    try {
      const job = await submitCloudRender(
        jobId,
        video,
        timelineReviewPayload(timeline, style),
        setProgress,
        uploadController.signal,
        (ticket) => setQueuePosition(ticket.status === "WAITING" ? ticket.queue_position ?? 1 : null),
        vocalMode,
      );
      setState("idle");
      onQueued(job);
    } catch (reason) {
      const canceled = reason instanceof DOMException && reason.name === "AbortError";
      setState(canceled ? "paused" : "error");
      setError(canceled ? null : cloudRenderErrorFeedback(reason));
    } finally {
      controller.current = null;
      setQueuePosition(null);
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
    <div className="mt-4 flex-1 space-y-3 border-t pt-4" aria-busy={uploading || rendering}>
      <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={disabled || uploading || rendering || failed || canceled || !video}
        aria-label={`云端导出 ${vocalMode === "on" ? "ON VOCAL" : "OFF VOCAL"}`}
        onClick={queueRender}
        className={`focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 ${
          emphasized
            ? "bg-primary text-primary-foreground"
            : "border bg-background hover:bg-muted"
        }`}
      >
        {uploading || rendering ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <CloudUpload className="size-4" />
        )}
        {uploading || rendering
          ? statusLabel
          : state === "paused" ? "继续上传并渲染" : idleLabel}
      </button>
      {uploading && (
        <button type="button" onClick={() => controller.current?.abort()}
          className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border px-3 text-sm font-semibold">
          <Pause className="size-4" />暂停上传
        </button>
      )}
      </div>
      {showProgress && (
        <div className={`rounded-lg border p-3 ${failed ? "border-destructive/30 bg-destructive/5" : "border-primary/20 bg-primary/5"}`}>
          <div className="flex items-start justify-between gap-3 text-sm" role="status" aria-live="polite">
            <span className={`flex min-w-0 items-center gap-2 font-medium ${failed ? "text-destructive" : "text-foreground"}`}>
              {complete && state === "idle" ? <CheckCircle2 className="size-4 shrink-0" /> : failed ? <CircleAlert className="size-4 shrink-0" /> : null}
              {statusLabel}
            </span>
            <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{progressValue}%</span>
          </div>
          <div role="progressbar" aria-label={`${modeLabel} 云端导出进度`}
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressValue} aria-valuetext={statusLabel}
            className="mt-2.5 h-2 overflow-hidden rounded-full bg-muted">
            <div className={`h-full rounded-full transition-[width] duration-300 ${failed ? "bg-destructive" : "bg-primary"}`}
              style={{ width: `${progressValue}%` }} />
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {uploading ? "上传完成后会自动进入云端渲染队列。"
              : state === "paused" ? "点击上方按钮继续上传。"
              : failed || canceled ? "本次导出已停止，可在页面上方查看原因并重试或重新创建任务。"
              : complete ? "可从本卡片下方下载云端视频。"
              : renderJob?.status === "UPLOADED" ? "素材已提交，轮到后会自动开始生成，无需重复点击。"
              : "进度按处理阶段更新，视频合成可能需要较长时间。"}
          </p>
        </div>
      )}
      <p className="text-xs leading-5 text-muted-foreground">
        {discouraged &&
          "会重新上传原视频并占用服务器渲染队列；本地导出可用时，建议优先使用本地导出。"}
        云端只使用已校正的时间轴和注音进行 Kirakara 视频嵌字，不会重新识别或对齐歌词。
      </p>
      {error && (
        <div className="mt-4">
          <ErrorFeedbackPanel feedback={error} onEdit={returnToEditor} />
        </div>
      )}
    </div>
  );
}
