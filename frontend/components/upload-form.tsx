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
import { FormEvent, useRef, useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import {
  networkErrorFeedback,
  validationErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { UPLOAD_COPY } from "@/lib/ui-copy";
import { ApiRequestError, createJob } from "@/services/api";

const MAX_VIDEO_BYTES = 1024 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function UploadForm() {
  const router = useRouter();
  const videoInput = useRef<HTMLInputElement>(null);
  const lyricsInput = useRef<HTMLInputElement>(null);
  const [video, setVideo] = useState<File | null>(null);
  const [lyricsText, setLyricsText] = useState("");
  const [lyricsFile, setLyricsFile] = useState<File | null>(null);
  const [vocalMode, setVocalMode] = useState("on");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ErrorFeedback | null>(null);

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

    setUploading(true);
    try {
      const job = await createJob(
        {
          video,
          lyricsText,
          lyricsFile: lyricsFile ?? undefined,
          vocalMode,
        },
        setProgress,
      );
      router.push(`/jobs/${job.id}`);
    } catch (reason) {
      setError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : networkErrorFeedback("upload"),
      );
      setUploading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-7">
      <section aria-labelledby="video-heading">
        <h2 id="video-heading" className="mb-3 text-lg font-semibold">
          {UPLOAD_COPY.videoSectionTitle}
        </h2>
        <input
          ref={videoInput}
          type="file"
          accept="video/mp4,.mp4"
          className="sr-only"
          onChange={(event) => {
            setVideo(event.target.files?.[0] ?? null);
            setError(null);
          }}
        />
        <button
          type="button"
          onClick={() => videoInput.current?.click()}
          className="focus-ring group flex min-h-40 w-full items-center justify-center rounded-2xl border border-dashed bg-card px-6 text-center transition hover:border-primary/60 hover:bg-accent/35"
        >
          {video ? (
            <div>
              <CheckCircle2 className="mx-auto mb-3 size-7 text-primary" />
              <p className="font-medium">{video.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {formatBytes(video.size)} · 点击重新选择
              </p>
            </div>
          ) : (
            <div>
              <Film className="mx-auto mb-3 size-7 text-muted-foreground transition group-hover:text-primary" />
              <p className="font-medium">{UPLOAD_COPY.videoPrompt}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {UPLOAD_COPY.videoHelp}
              </p>
            </div>
          )}
        </button>
      </section>

      <section aria-labelledby="lyrics-heading">
        <h2 id="lyrics-heading" className="mb-3 text-lg font-semibold">
          {UPLOAD_COPY.lyricsSectionTitle}
        </h2>
        <textarea
          value={lyricsText}
          disabled={Boolean(lyricsFile) || uploading}
          onChange={(event) => setLyricsText(event.target.value)}
          rows={7}
          placeholder={"君の知らない物語\nいつも通りのある日の事"}
          className="focus-ring w-full resize-y rounded-2xl border bg-card px-4 py-3 text-sm leading-7 placeholder:text-muted-foreground/60 disabled:cursor-not-allowed disabled:bg-muted"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            ref={lyricsInput}
            type="file"
            accept=".txt,text/plain"
            className="sr-only"
            onChange={(event) => {
              setLyricsFile(event.target.files?.[0] ?? null);
              setLyricsText("");
              setError(null);
            }}
          />
          <button
            type="button"
            disabled={uploading}
            onClick={() => lyricsInput.current?.click()}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
          >
            <FileText className="size-4" />
            {lyricsFile ? lyricsFile.name : "选择 TXT 文件"}
          </button>
          {lyricsFile && (
            <button
              type="button"
              onClick={() => {
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
        <div aria-live="polite">
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
        </div>
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
        {uploading ? UPLOAD_COPY.uploadingButton : UPLOAD_COPY.submitButton}
      </button>

      <p className="text-center text-xs text-muted-foreground">
        {UPLOAD_COPY.footer}
      </p>
    </form>
  );
}
