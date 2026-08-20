"use client";

import { Cloud, Film, FolderOpen, LoaderCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { KirakaraDomFrame } from "@/components/kirakara-dom-frame";
import { KirakaraRenderActions } from "@/components/kirakara-render-actions";
import { KirakaraReviewEditor } from "@/components/kirakara-review-editor";
import { KirakaraStyleEditor } from "@/components/kirakara-style-editor";
import { ReviewedDataDownloads } from "@/components/reviewed-data-downloads";
import {
  detectKirakaraCapabilities,
  kirakaraSupportMessage,
  type KirakaraCapabilities,
} from "@/lib/kirakara-capabilities";
import {
  DEFAULT_KIRAKARA_STYLE,
  loadKirakaraStyle,
  saveKirakaraStyle,
  type KirakaraStyle,
} from "@/lib/kirakara-style";
import {
  activeKirakaraFrame,
  toKirakaraTimeline,
  type KirakaraFrame,
  type KirakaraTimeline,
} from "@/lib/kirakara-timeline";
import {
  TimelineReviewValidationError,
  timelineReviewPayload,
} from "@/lib/kirakara-review";
import { getLocalVideo, rememberLocalVideo } from "@/lib/local-media-session";
import {
  ApiRequestError,
  getTimeline,
  getTimelineReviewDraft,
  saveTimelineReviewDraft,
} from "@/services/api";
import type { Job } from "@/types/job";

const TIMELINE_AUTOSAVE_DELAY_MS = 600;

type TimelineSaveState = {
  phase: "idle" | "pending" | "saving" | "saved" | "restored" | "error";
  message?: string;
};

export function KirakaraPreview({
  jobId,
  expectedVideoName,
  vocalMode = "on",
  hasCloudResult = false,
  onCloudRenderQueued = () => undefined,
  onVideoElementChange,
}: {
  jobId: string;
  expectedVideoName: string;
  vocalMode?: string;
  hasCloudResult?: boolean;
  onCloudRenderQueued?: (job: Job) => void;
  onVideoElementChange?: (element: HTMLVideoElement | null) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const animationFrame = useRef<number | null>(null);
  const componentActive = useRef(true);
  const activeJobId = useRef(jobId);
  const autosaveVersion = useRef(0);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const [video, setVideo] = useState<File | null>(() => getLocalVideo(jobId));
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<KirakaraTimeline | null>(null);
  const [frame, setFrame] = useState<KirakaraFrame | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [autosaveTrigger, setAutosaveTrigger] = useState<{
    jobId: string;
    version: number;
  } | null>(null);
  const [timelineSaveState, setTimelineSaveState] = useState<TimelineSaveState>({
    phase: "idle",
  });
  const [selectionWarning, setSelectionWarning] = useState<string | null>(null);
  const [capabilities, setCapabilities] =
    useState<KirakaraCapabilities | null>(null);
  const [style, setStyle] = useState<KirakaraStyle>(() =>
    typeof window === "undefined"
      ? DEFAULT_KIRAKARA_STYLE
      : loadKirakaraStyle(window.localStorage),
  );

  const assignVideoElement = useCallback((element: HTMLVideoElement | null) => {
    videoRef.current = element;
    onVideoElementChange?.(element);
  }, [onVideoElementChange]);

  useEffect(() => {
    componentActive.current = true;
    return () => {
      componentActive.current = false;
    };
  }, []);

  useEffect(() => {
    activeJobId.current = jobId;
    autosaveVersion.current = 0;
  }, [jobId]);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      getTimeline(jobId),
      getTimelineReviewDraft(jobId),
    ]).then(([sourceResult, draftResult]) => {
      if (!active) return;
      if (sourceResult.status === "rejected") {
        setTimelineError(
          sourceResult.reason instanceof ApiRequestError
            ? sourceResult.reason.feedback.title
            : "时间轴读取失败",
        );
        return;
      }

      const draft = draftResult.status === "fulfilled"
        ? draftResult.value
        : null;
      setTimeline(
        toKirakaraTimeline(draft?.timeline ?? sourceResult.value),
      );
      setTimelineError(null);
      if (draft) {
        setTimelineSaveState({ phase: "restored" });
      } else if (draftResult.status === "rejected") {
        setTimelineSaveState({
          phase: "error",
          message: draftResult.reason instanceof ApiRequestError
            ? draftResult.reason.feedback.title
            : "云端草稿读取失败",
        });
      } else {
        setTimelineSaveState({ phase: "idle" });
      }
    });
    return () => {
      active = false;
    };
  }, [jobId]);

  useEffect(() => {
    if (!timeline || !autosaveTrigger || autosaveTrigger.jobId !== jobId) return;
    const version = autosaveTrigger.version;
    const targetJobId = jobId;
    const timeout = globalThis.setTimeout(() => {
      let review;
      try {
        review = timelineReviewPayload(timeline);
      } catch (reason) {
        if (
          componentActive.current
          && activeJobId.current === targetJobId
          && autosaveVersion.current === version
        ) {
          setTimelineSaveState({
            phase: "error",
            message: reason instanceof TimelineReviewValidationError
              ? reason.message
              : "时间轴校验失败",
          });
        }
        return;
      }

      const operation = saveQueue.current.then(async () => {
        if (
          componentActive.current
          && activeJobId.current === targetJobId
          && autosaveVersion.current === version
        ) {
          setTimelineSaveState({ phase: "saving" });
        }
        return saveTimelineReviewDraft(targetJobId, review);
      });
      saveQueue.current = operation.then(
        () => undefined,
        () => undefined,
      );
      void operation.then(
        () => {
          if (
            componentActive.current
            && activeJobId.current === targetJobId
            && autosaveVersion.current === version
          ) {
            setTimelineSaveState({ phase: "saved" });
          }
        },
        (reason) => {
          if (
            componentActive.current
            && activeJobId.current === targetJobId
            && autosaveVersion.current === version
          ) {
            setTimelineSaveState({
              phase: "error",
              message: reason instanceof ApiRequestError
                ? reason.feedback.title
                : "时间轴自动保存失败",
            });
          }
        },
      );
    }, TIMELINE_AUTOSAVE_DELAY_MS);
    return () => globalThis.clearTimeout(timeout);
  }, [autosaveTrigger, jobId, timeline]);

  useEffect(() => {
    let active = true;
    const mobile = window.matchMedia("(max-width: 767px)").matches;
    detectKirakaraCapabilities(globalThis, mobile).then((capabilities) => {
      if (active) setCapabilities(capabilities);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!video) return;
    let active = true;
    const nextUrl = URL.createObjectURL(video);
    Promise.resolve().then(() => {
      if (active) setVideoUrl(nextUrl);
    });
    return () => {
      active = false;
      URL.revokeObjectURL(nextUrl);
    };
  }, [video]);

  const updateFrame = useCallback(() => {
    const videoElement = videoRef.current;
    if (!videoElement) return;
    setFrame(
      timeline
        ? activeKirakaraFrame(timeline, videoElement.currentTime * 1000)
        : null,
    );
  }, [timeline]);

  useEffect(() => {
    updateFrame();
  }, [updateFrame]);

  function updateStyle(nextStyle: KirakaraStyle) {
    setStyle(nextStyle);
    saveKirakaraStyle(window.localStorage, nextStyle);
  }

  function updateTimeline(nextTimeline: KirakaraTimeline) {
    const version = autosaveVersion.current + 1;
    autosaveVersion.current = version;
    setTimeline(nextTimeline);
    setAutosaveTrigger({ jobId, version });
    setTimelineSaveState({ phase: "pending" });
  }

  function retryTimelineSave() {
    if (!timeline) return;
    const version = autosaveVersion.current + 1;
    autosaveVersion.current = version;
    setAutosaveTrigger({ jobId, version });
    setTimelineSaveState({ phase: "pending" });
  }

  const stopDrawing = useCallback(() => {
    if (animationFrame.current !== null) {
      cancelAnimationFrame(animationFrame.current);
      animationFrame.current = null;
    }
  }, []);

  const startDrawing = useCallback(() => {
    stopDrawing();
    const tick = () => {
      updateFrame();
      if (!videoRef.current?.paused) {
        animationFrame.current = requestAnimationFrame(tick);
      }
    };
    tick();
  }, [stopDrawing, updateFrame]);

  useEffect(() => stopDrawing, [stopDrawing]);

  function selectVideo(file: File | null) {
    if (!file) return;
    rememberLocalVideo(jobId, file);
    setVideo(file);
    setSelectionWarning(
      file.name === expectedVideoName
        ? null
        : `当前选择的是 ${file.name}，任务原文件为 ${expectedVideoName}。`,
    );
  }

  function seekPreview(milliseconds: number) {
    const element = videoRef.current;
    if (!element) return;
    element.currentTime = milliseconds / 1000;
    updateFrame();
  }

  return (
    <section className="mt-6 border-t pt-6" aria-labelledby="kirakara-preview-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-base font-bold text-primary">Kirakara 引擎</p>
          <h2 id="kirakara-preview-heading" className="mt-1 text-xl font-bold">
            浏览器本地预览
          </h2>
        </div>
        <Film className="size-5 shrink-0 text-muted-foreground" />
      </div>

      {!video ? (
        <div className="mt-4 border-l-2 border-primary pl-4">
          <p className="text-sm leading-6 text-muted-foreground">
            请选择任务使用的原视频 <strong className="text-foreground">{expectedVideoName}</strong>。
          </p>
          <label className="focus-ring mt-3 inline-flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted">
            <FolderOpen className="size-4" />
            重新选择原视频
            <input
              type="file"
              accept="video/mp4,.mp4"
              className="sr-only"
              onChange={(event) => selectVideo(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
      ) : (
        <div
          data-kirakara-workbench="desktop-fit"
          className="mt-4 grid items-start gap-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(20rem,1fr)] xl:grid-cols-[minmax(0,1.05fr)_minmax(22rem,1fr)]"
        >
          <div
            data-kirakara-preview-panel="true"
            className="min-w-0 lg:col-start-1 lg:row-start-1"
          >
            <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
              {videoUrl && (
                <video
                  ref={assignVideoElement}
                  src={videoUrl}
                  controls
                  playsInline
                  preload="metadata"
                  className="size-full object-contain"
                  onLoadedMetadata={updateFrame}
                  onTimeUpdate={updateFrame}
                  onSeeked={updateFrame}
                  onPlay={startDrawing}
                  onPause={() => {
                    stopDrawing();
                    updateFrame();
                  }}
                />
              )}
              <KirakaraDomFrame frame={frame} style={style} />
              {!timeline && !timelineError && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 bg-black/45 text-sm text-white">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取时间轴
                </div>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>
                {!capabilities
                  ? "正在检查本地编码能力"
                  : kirakaraSupportMessage(capabilities)}
              </span>
              <label className="focus-ring cursor-pointer rounded-sm font-medium text-foreground underline-offset-4 hover:underline">
                更换视频
                <input
                  type="file"
                  accept="video/mp4,.mp4"
                  className="sr-only"
                  onChange={(event) => selectVideo(event.target.files?.[0] ?? null)}
                />
              </label>
            </div>
          </div>

          <div
            data-kirakara-timeline-panel="true"
            className={`min-w-0 lg:col-span-2 lg:row-start-2 ${
              timeline
                ? "rounded-lg border bg-background/40 p-3"
                : "hidden"
            }`}
          >
            {timeline && (
              <>
                <div
                  data-timeline-autosave={timelineSaveState.phase}
                  aria-live="polite"
                  className="mb-3 flex flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground"
                >
                  {timelineSaveState.phase === "saving" ? (
                    <LoaderCircle className="size-3.5 animate-spin" />
                  ) : (
                    <Cloud className="size-3.5" />
                  )}
                  <span>
                    {timelineSaveState.phase === "pending"
                      ? "等待保存到云端"
                      : timelineSaveState.phase === "saving"
                        ? "正在保存时间轴"
                        : timelineSaveState.phase === "saved"
                          ? "时间轴已保存到云端"
                          : timelineSaveState.phase === "restored"
                            ? "已恢复云端时间轴草稿"
                            : timelineSaveState.phase === "error"
                              ? timelineSaveState.message ?? "时间轴自动保存失败"
                              : "时间轴修改会自动保存到云端"}
                  </span>
                  {timelineSaveState.phase === "error" && (
                    <button
                      type="button"
                      onClick={retryTimelineSave}
                      className="focus-ring inline-flex items-center gap-1 rounded-sm font-medium text-foreground underline-offset-4 hover:underline"
                    >
                      <RefreshCw className="size-3.5" />
                      重试保存
                    </button>
                  )}
                </div>
                <KirakaraReviewEditor
                  timeline={timeline}
                  onChange={updateTimeline}
                  onSeek={seekPreview}
                />
              </>
            )}
          </div>

          <div
            data-kirakara-controls-panel="true"
            className={`min-w-0 lg:col-start-2 lg:row-start-1 ${
              timeline
                ? "rounded-lg border bg-background/40 p-3"
                : "hidden"
            }`}
          >
            {timeline && (
              <div className="min-w-0">
                <KirakaraStyleEditor style={style} onChange={updateStyle} />
              </div>
            )}
            {timeline && capabilities && (
              <div className="mt-4 min-w-0 space-y-3 border-t pt-4 [&>div]:mt-0 [&>div]:border-t-0 [&>div]:pt-0">
                <ReviewedDataDownloads
                  jobId={jobId}
                  videoName={expectedVideoName}
                  timeline={timeline}
                  style={style}
                />
                <KirakaraRenderActions
                  capabilities={capabilities}
                  video={video}
                  timeline={timeline}
                  style={style}
                  jobId={jobId}
                  vocalMode={vocalMode}
                  rerender={hasCloudResult}
                  onCloudRenderQueued={onCloudRenderQueued}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {(timelineError || selectionWarning) && (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {timelineError ?? selectionWarning}
        </p>
      )}
    </section>
  );
}
