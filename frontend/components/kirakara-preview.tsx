"use client";

import { Film, FolderOpen, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { KirakaraDomFrame } from "@/components/kirakara-dom-frame";
import { KirakaraProjectDownload } from "@/components/kirakara-project-download";
import { KirakaraRenderActions } from "@/components/kirakara-render-actions";
import { KirakaraReviewEditor } from "@/components/kirakara-review-editor";
import { KirakaraStyleEditor } from "@/components/kirakara-style-editor";
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
import { getLocalVideo, rememberLocalVideo } from "@/lib/local-media-session";
import { ApiRequestError, getTimeline } from "@/services/api";
import type { Job } from "@/types/job";

export function KirakaraPreview({
  jobId,
  expectedVideoName,
  vocalMode = "on",
  onCloudRenderQueued = () => undefined,
}: {
  jobId: string;
  expectedVideoName: string;
  vocalMode?: string;
  onCloudRenderQueued?: (job: Job) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const animationFrame = useRef<number | null>(null);
  const [video, setVideo] = useState<File | null>(() => getLocalVideo(jobId));
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<KirakaraTimeline | null>(null);
  const [frame, setFrame] = useState<KirakaraFrame | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [selectionWarning, setSelectionWarning] = useState<string | null>(null);
  const [capabilities, setCapabilities] =
    useState<KirakaraCapabilities | null>(null);
  const [style, setStyle] = useState<KirakaraStyle>(() =>
    typeof window === "undefined"
      ? DEFAULT_KIRAKARA_STYLE
      : loadKirakaraStyle(window.localStorage),
  );

  useEffect(() => {
    let active = true;
    getTimeline(jobId)
      .then((source) => {
        if (active) setTimeline(toKirakaraTimeline(source));
      })
      .catch((reason) => {
        if (!active) return;
        setTimelineError(
          reason instanceof ApiRequestError
            ? reason.feedback.title
            : "时间轴读取失败",
        );
      });
    return () => {
      active = false;
    };
  }, [jobId]);

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
                  ref={videoRef}
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
              <KirakaraReviewEditor
                timeline={timeline}
                onChange={setTimeline}
                onSeek={seekPreview}
              />
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
                <KirakaraProjectDownload
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
