"use client";

import {
  CheckCircle2,
  FileText,
  Film,
  Mic,
  MicOff,
  Sparkles,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { DragEvent, FormEvent } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { LyricsOverflowDialog } from "@/components/lyrics-overflow-dialog";
import { MobileRouteStatus } from "@/components/mobile-route-status";
import { MobileSubmissionProgress } from "@/components/mobile-submission-progress";
import {
  networkErrorFeedback,
  validationErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { UPLOAD_COPY } from "@/lib/ui-copy";
import {
  detectMobileCapabilities,
  selectMobileProcessingRoute,
  type MobileProcessingRoute,
} from "@/lib/mobile-processing";
import {
  submitMobileJob,
  type MobileSubmissionState,
} from "@/lib/mobile-submission";
import { rememberLocalVideo } from "@/lib/local-media-session";
import {
  detectLyricsWidthOverflow,
  readLyricsValidationSource,
  type LyricsValidationSource,
  type LyricsWidthOverflowReport,
} from "@/lib/lyrics-width-validation";
import {
  ApiRequestError,
  createAudioOnlyJob,
  createJob,
} from "@/services/api";
import type { UploadTicket } from "@/types/upload-ticket";

const MAX_VIDEO_BYTES = 1024 * 1024 * 1024;

type PendingLyricsWarning = {
  report: LyricsWidthOverflowReport;
  source: LyricsValidationSource;
  resumeSubmit: boolean;
};

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function UploadForm() {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const lyricsInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const mobileAbortController = useRef<AbortController | null>(null);
  const ignoredLyricsSignature = useRef<string | null>(null);
  const lyricsValidationSequence = useRef(0);
  const [video, setVideo] = useState<File | null>(null);
  const [lyricsText, setLyricsText] = useState("");
  const [lyricsFile, setLyricsFile] = useState<File | null>(null);
  const [vocalMode, setVocalMode] = useState("on");
  const [uploading, setUploading] = useState(false);
  const [draggingVideo, setDraggingVideo] = useState(false);
  const [uploadTicket, setUploadTicket] = useState<UploadTicket | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ErrorFeedback | null>(null);
  const [mobileRoute, setMobileRoute] =
    useState<MobileProcessingRoute | null>(null);
  const [mobileSubmission, setMobileSubmission] =
    useState<MobileSubmissionState | null>(null);
  const [lyricsWarning, setLyricsWarning] =
    useState<PendingLyricsWarning | null>(null);

  useEffect(() => {
    if (!video) return;
    let active = true;
    detectMobileCapabilities()
      .then((capabilities) => {
        if (active) {
          setMobileRoute(
            selectMobileProcessingRoute({
              videoSizeBytes: video.size,
              capabilities,
            }),
          );
        }
      })
      .catch(() => {
        if (active) setMobileRoute("REMOTE_VIDEO");
      });
    return () => {
      active = false;
    };
  }, [video]);

  function selectVideo(nextVideo: File | null) {
    setVideo(nextVideo);
    setMobileRoute(null);
    setError(null);
  }

  function resetVideoDrag() {
    dragDepth.current = 0;
    setDraggingVideo(false);
  }

  function handleVideoDragEnter(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (uploading) return;
    dragDepth.current += 1;
    setDraggingVideo(true);
  }

  function handleVideoDragOver(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (uploading) return;
    event.dataTransfer.dropEffect = "copy";
    setDraggingVideo(true);
  }

  function handleVideoDragLeave(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (uploading) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDraggingVideo(false);
  }

  function handleVideoDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    resetVideoDrag();
    if (uploading) return;
    selectVideo(event.dataTransfer.files.item(0));
    if (videoInput.current) videoInput.current.value = "";
  }

  function lyricsFileReadError(fileName: string): ErrorFeedback {
    return {
      title: "歌词文件读取失败",
      description: "浏览器无法读取所选歌词文件，当前文件尚未上传。",
      solutions: [
        "确认文件仍然存在且没有被其他程序独占，然后重新选择。",
        "将歌词另存为 UTF-8 编码的 TXT 或 LRC 文件后重试。",
        "也可以直接将歌词粘贴到文本框中。",
      ],
      technicalDetails: [`文件名：${fileName}`],
      retryable: false,
    };
  }

  async function checkLyricsWidth(
    nextLyricsText: string,
    nextLyricsFile: File | null,
    resumeSubmit: boolean,
  ): Promise<boolean> {
    const validationSequence = ++lyricsValidationSequence.current;
    let source: LyricsValidationSource;
    try {
      source = await readLyricsValidationSource(nextLyricsText, nextLyricsFile);
    } catch {
      if (validationSequence !== lyricsValidationSequence.current) return true;
      setError(lyricsFileReadError(nextLyricsFile?.name ?? "未知文件"));
      return false;
    }
    if (validationSequence !== lyricsValidationSequence.current) return true;
    if (!source.text.trim()) return true;

    try {
      await document.fonts?.ready;
    } catch {
      // Font readiness is an optimization; canvas still provides a safe fallback.
    }
    if (validationSequence !== lyricsValidationSequence.current) return true;
    const report = detectLyricsWidthOverflow(source.text);
    if (!report || ignoredLyricsSignature.current === source.signature) return true;

    setLyricsWarning({ report, source, resumeSubmit });
    return false;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!video) {
      setError(validationErrorFeedback("video_required"));
      return;
    }
    if (!lyricsText.trim() && !lyricsFile) {
      setError(validationErrorFeedback("lyrics_required"));
      return;
    }
    if (lyricsText.trim() && lyricsFile) {
      setError(validationErrorFeedback("lyrics_source_conflict"));
      return;
    }
    if (!video.name.toLowerCase().endsWith(".mp4")) {
      setError(validationErrorFeedback("invalid_video_type"));
      return;
    }
    if (video.size > MAX_VIDEO_BYTES) {
      setError(validationErrorFeedback("video_too_large"));
      return;
    }
    if (!(await checkLyricsWidth(lyricsText, lyricsFile, true))) {
      return;
    }

    setUploading(true);
    setProgress(0);
    setUploadTicket(null);
    setMobileSubmission(null);
    const useAudioOnly = mobileRoute === "AUDIO_ONLY";
    const abortController = useAudioOnly ? new AbortController() : null;
    mobileAbortController.current = abortController;
    try {
      const submissionInput = {
        video,
        lyricsText,
        lyricsFile: lyricsFile ?? undefined,
        vocalMode,
      };
      const job = useAudioOnly
        ? await submitMobileJob(
            { ...submissionInput, route: "AUDIO_ONLY" },
            {
              extractAudio: async (selectedVideo, options) => {
                const { extractAudioTrack } = await import(
                  "@/lib/browser-audio-extractor"
                );
                return extractAudioTrack(selectedVideo, options);
              },
              uploadAudio: createAudioOnlyJob,
              uploadVideo: createJob,
            },
            (state) => {
              setMobileSubmission(state);
              setProgress(state.progress);
              if (state.stage === "FALLBACK_VIDEO") {
                setMobileRoute("REMOTE_VIDEO");
              }
            },
            {
              signal: abortController?.signal,
              onQueueUpdate: setUploadTicket,
            },
          )
        : await createJob(submissionInput, setProgress, setUploadTicket);
      mobileAbortController.current = null;
      if (job.input_mode === "AUDIO_ONLY") {
        rememberLocalVideo(job.id, video);
      }
      router.push(`/jobs/${job.id}`);
    } catch (reason) {
      const canceled =
        reason instanceof DOMException && reason.name === "AbortError";
      setError(
        canceled
          ? null
          : reason instanceof ApiRequestError
            ? reason.feedback
            : networkErrorFeedback("upload"),
      );
      setUploading(false);
      setUploadTicket(null);
      setMobileSubmission(null);
      setProgress(0);
      mobileAbortController.current = null;
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="space-y-7">
      <section aria-labelledby="video-heading">
        <h2 id="video-heading" className="mb-3 text-lg font-semibold">
          {UPLOAD_COPY.videoSectionTitle}
        </h2>
        <input
          ref={videoInput}
          type="file"
          accept="video/mp4,.mp4"
          className="sr-only"
          disabled={uploading}
          onChange={(event) => {
            selectVideo(event.target.files?.[0] ?? null);
          }}
        />
        <button
          type="button"
          aria-disabled={uploading}
          onClick={() => {
            if (!uploading) videoInput.current?.click();
          }}
          onDragEnter={handleVideoDragEnter}
          onDragOver={handleVideoDragOver}
          onDragLeave={handleVideoDragLeave}
          onDragEnd={resetVideoDrag}
          onDrop={handleVideoDrop}
          className={`focus-ring group flex min-h-40 w-full items-center justify-center rounded-2xl border border-dashed bg-card px-6 text-center transition ${
            draggingVideo
              ? "border-primary bg-primary/10"
              : "hover:border-primary/60 hover:bg-accent/35"
          } ${uploading ? "cursor-wait opacity-70" : ""}`}
        >
          {video ? (
            <div className="max-w-full">
              <CheckCircle2 className="mx-auto mb-3 size-7 text-primary" />
              <p className="break-all font-medium">{video.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {formatBytes(video.size)} · 拖入新视频或点击重新选择
              </p>
            </div>
          ) : (
            <div>
              <Film
                className={`mx-auto mb-3 size-7 text-muted-foreground transition group-hover:text-primary ${
                  draggingVideo ? "text-primary" : ""
                }`}
              />
              <p className="font-medium">
                {draggingVideo ? "松开以上传 MP4 视频" : UPLOAD_COPY.videoPrompt}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                拖放 MP4 文件到这里，或点击选择。{UPLOAD_COPY.videoHelp}
              </p>
            </div>
          )}
        </button>
        {video && mobileRoute && <MobileRouteStatus route={mobileRoute} />}
      </section>

      <section aria-labelledby="lyrics-heading">
        <h2 id="lyrics-heading" className="mb-3 text-lg font-semibold">
          {UPLOAD_COPY.lyricsSectionTitle}
        </h2>
        <textarea
          value={lyricsText}
          disabled={Boolean(lyricsFile) || uploading}
          onChange={(event) => {
            lyricsValidationSequence.current += 1;
            ignoredLyricsSignature.current = null;
            const nextText = event.target.value;
            setLyricsText(nextText);
            if ((event.nativeEvent as InputEvent).inputType === "insertFromPaste") {
              void checkLyricsWidth(nextText, null, false);
            }
          }}
          onBlur={(event) => {
            void checkLyricsWidth(event.currentTarget.value, null, false);
          }}
          rows={7}
          placeholder={"君の知らない物語\nいつも通りのある日の事"}
          className="focus-ring w-full resize-y rounded-2xl border bg-card px-4 py-3 text-sm leading-7 placeholder:text-muted-foreground/60 disabled:cursor-not-allowed disabled:bg-muted"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            ref={lyricsInput}
            type="file"
            accept=".txt,.lrc,text/plain,application/x-subrip"
            className="sr-only"
            onChange={(event) => {
              const nextFile = event.target.files?.[0] ?? null;
              lyricsValidationSequence.current += 1;
              ignoredLyricsSignature.current = null;
              setLyricsWarning(null);
              setLyricsFile(nextFile);
              setLyricsText("");
              setError(null);
              if (nextFile) void checkLyricsWidth("", nextFile, false);
            }}
          />
          <button
            type="button"
            disabled={uploading}
            onClick={() => lyricsInput.current?.click()}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
          >
            <FileText className="size-4" />
            {lyricsFile ? lyricsFile.name : "选择 TXT / LRC 文件"}
          </button>
          {lyricsFile && (
            <button
              type="button"
              onClick={() => {
                lyricsValidationSequence.current += 1;
                ignoredLyricsSignature.current = null;
                setLyricsWarning(null);
                setLyricsFile(null);
                if (lyricsInput.current) lyricsInput.current.value = "";
              }}
              className="focus-ring rounded-sm text-sm text-muted-foreground underline-offset-4 hover:underline"
            >
              移除文件
            </button>
          )}
          {!lyricsFile && (
            <span className="text-xs text-muted-foreground">
              {UPLOAD_COPY.lyricsHint}
            </span>
          )}
        </div>
      </section>

      <section aria-labelledby="vocal-heading">
        <h2 id="vocal-heading" className="mb-3 text-lg font-semibold">
          {UPLOAD_COPY.vocalSectionTitle}
        </h2>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => setVocalMode("on")}
            className={`focus-ring flex flex-1 items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium transition ${
              vocalMode === "on"
                ? "border-primary bg-primary/10 text-primary"
                : "border bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            <Mic className="size-4" />
            {UPLOAD_COPY.vocalOnLabel}
          </button>
          <button
            type="button"
            onClick={() => setVocalMode("off")}
            className={`focus-ring flex flex-1 items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium transition ${
              vocalMode === "off"
                ? "border-primary bg-primary/10 text-primary"
                : "border bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            <MicOff className="size-4" />
            {UPLOAD_COPY.vocalOffLabel}
          </button>
        </div>
        {vocalMode === "off" && (
          <p className="mt-2 text-xs text-muted-foreground">
            {UPLOAD_COPY.offVocalHint}
          </p>
        )}
      </section>

      {error && <ErrorFeedbackPanel feedback={error} />}

      {uploading && (
        <>
          {mobileSubmission && uploadTicket?.status !== "WAITING" ? (
            <MobileSubmissionProgress
              state={mobileSubmission}
              onCancel={() => mobileAbortController.current?.abort()}
            />
          ) : (
            <div aria-live="polite">
              {uploadTicket?.status === "WAITING" ? (
                <>
                  <div className="mb-2 flex justify-between gap-4 text-sm">
                    <span>正在等待上传名额</span>
                    {uploadTicket.queue_position &&
                      uploadTicket.queue_size && (
                        <span className="font-medium">
                          第 {uploadTicket.queue_position} 位 / 共{" "}
                          {uploadTicket.queue_size} 位
                        </span>
                      )}
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    当前不会上传视频文件；轮到你时页面会自动开始上传。关闭页面后排队号会自动过期。
                  </p>
                </>
              ) : (
                <>
                  <div className="mb-2 flex justify-between text-sm">
                    <span>{UPLOAD_COPY.uploadProgressTitle}</span>
                    <span className="font-medium">{progress}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-[width]"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {UPLOAD_COPY.uploadProgressDescription}
                  </p>
                </>
              )}
            </div>
          )}
        </>
      )}

      <button
        type="submit"
        disabled={uploading}
        className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3.5 font-semibold text-primary-foreground transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60"
      >
        {uploading ? (
          <Upload className="size-5 animate-pulse" />
        ) : (
          <Sparkles className="size-5" />
        )}
        {uploading
          ? uploadTicket?.status === "WAITING"
            ? "正在排队等待上传"
            : UPLOAD_COPY.uploadingButton
          : UPLOAD_COPY.submitButton}
      </button>

      <p className="text-center text-xs text-muted-foreground">
        {UPLOAD_COPY.footer}
      </p>

      {lyricsWarning && (
        <LyricsOverflowDialog
          report={lyricsWarning.report}
          sourceLabel={lyricsWarning.source.label}
          onCancel={() => setLyricsWarning(null)}
          onContinue={() => {
            const shouldResumeSubmit = lyricsWarning.resumeSubmit;
            ignoredLyricsSignature.current = lyricsWarning.source.signature;
            setLyricsWarning(null);
            if (shouldResumeSubmit) {
              queueMicrotask(() => formRef.current?.requestSubmit());
            }
          }}
        />
      )}
    </form>
  );
}
