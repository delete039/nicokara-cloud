"use client";

import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  CircleX,
  Download,
  LoaderCircle,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { JobMetadata } from "@/components/job-metadata";
import { ReadingReviewEditor } from "@/components/reading-review-editor";
import { KirakaraPreview } from "@/components/kirakara-preview";
import { KirakaraProjectDownload } from "@/components/kirakara-project-download";
import {
  jobFailureFeedback,
  networkErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { jobPresentation } from "@/lib/job-presentation";
import {
  canCancelJob,
  cancelJobLabel,
  jobPollDelay,
  queueStatusLabel,
} from "@/lib/job-queue";
import { JOB_COPY } from "@/lib/ui-copy";
import {
  ApiRequestError,
  cancelJob,
  confirmReadings,
  downloadVideoUrl,
  getJob,
  getProcessedLyrics,
  processedLyricsUrl,
  resultVideoUrl,
  subtitleUrl,
  timelineUrl,
  transcriptUrl,
} from "@/services/api";
import type { Job } from "@/types/job";
import type { ProcessedLyrics } from "@/types/job";

export function JobStatus({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [requestError, setRequestError] = useState<ErrorFeedback | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [canceling, setCanceling] = useState(false);
  const [processedLyrics, setProcessedLyrics] = useState<ProcessedLyrics | null>(null);
  const [submittingReadings, setSubmittingReadings] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let consecutiveErrors = 0;
    let lastStatus = "UPLOADED";

    async function poll() {
      try {
        const value = await getJob(jobId);
        if (!active) return;
        consecutiveErrors = 0;
        lastStatus = value.status;
        setJob(value);
        setRequestError(null);
        if (!jobPresentation(value.status, value.stage).terminal) {
          timer = setTimeout(
            poll,
            jobPollDelay(value.status, 0, document.hidden),
          );
        }
      } catch (reason) {
        if (active) {
          const feedback =
            reason instanceof ApiRequestError
              ? reason.feedback
              : networkErrorFeedback("job");
          setRequestError(feedback);
          if (feedback.retryable) {
            consecutiveErrors += 1;
            timer = setTimeout(
              poll,
              jobPollDelay(lastStatus, consecutiveErrors, document.hidden),
            );
          }
        }
      }
    }

    poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, refreshKey]);

  useEffect(() => {
    if (job?.stage !== "READING_REVIEW_REQUIRED") {
      return;
    }
    let active = true;
    getProcessedLyrics(job.id)
      .then((lyrics) => {
        if (active) setProcessedLyrics(lyrics);
      })
      .catch((reason) => {
        if (!active) return;
        setRequestError(
          reason instanceof ApiRequestError
            ? reason.feedback
            : networkErrorFeedback("job"),
        );
      });
    return () => {
      active = false;
    };
  }, [job?.id, job?.stage]);

  if (requestError && !job) {
    return (
      <div className="space-y-5 rounded-2xl border bg-card p-5 sm:p-8">
        <ErrorFeedbackPanel
          feedback={requestError}
          onRetry={
            requestError.retryable
              ? () => {
                  setRequestError(null);
                  setRefreshKey((value) => value + 1);
                }
              : undefined
          }
        />
        <Link
          href="/"
          className="focus-ring inline-block rounded-lg border px-4 py-2 text-sm font-medium"
        >
          {JOB_COPY.backToUpload}
        </Link>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex items-center justify-center gap-3 py-24 text-muted-foreground">
        <LoaderCircle className="size-5 animate-spin" />
        {JOB_COPY.loading}
      </div>
    );
  }

  const presentation = jobPresentation(job.status, job.stage, job.input_mode);
  const queueLabel = queueStatusLabel(job.queue_position, job.queue_size);
  const cancelLabel = cancelJobLabel(job.status);
  const StatusIcon =
    presentation.tone === "canceled"
      ? CircleX
      : presentation.tone === "success"
      ? CheckCircle2
      : presentation.tone === "error"
        ? AlertCircle
        : presentation.tone === "pending"
          ? Clock3
          : LoaderCircle;

  async function handleCancel() {
    const confirmation =
      job.status === "UPLOADED"
        ? JOB_COPY.cancelQueuedConfirm
        : JOB_COPY.cancelProcessingConfirm;
    if (!window.confirm(confirmation)) return;

    setCanceling(true);
    setRequestError(null);
    try {
      setJob(await cancelJob(job.id));
    } catch (reason) {
      setRequestError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : networkErrorFeedback("job"),
      );
    } finally {
      setCanceling(false);
    }
  }

  async function handleConfirmReadings() {
    if (!processedLyrics) return;
    setSubmittingReadings(true);
    setRequestError(null);
    try {
      const queued = await confirmReadings(job.id, {
        lines: processedLyrics.lines.map((line) => ({
          surface: line.surface,
          tokens: line.tokens.map((token) => ({
            surface: token.surface,
            reading: token.reading.trim(),
          })),
        })),
      });
      setJob(queued);
      setProcessedLyrics(null);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setRequestError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : networkErrorFeedback("job"),
      );
    } finally {
      setSubmittingReadings(false);
    }
  }

  return (
    <div className="space-y-6">
      {requestError && (
        <ErrorFeedbackPanel
          feedback={requestError}
          onRetry={() => {
            setRequestError(null);
            setRefreshKey((value) => value + 1);
          }}
        />
      )}
      <div className="rounded-3xl border bg-card p-6 sm:p-9">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-medium tracking-[0.18em] text-primary">
              {presentation.eyebrow}
            </p>
            <h1 className="mt-3 font-display text-3xl font-bold">
              {presentation.title}
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {presentation.description}
            </p>
            {queueLabel && job.queue_position && job.queue_size && (
              <div
                className="mt-5 flex items-center gap-3 border-l-2 border-primary pl-4"
                aria-label={queueLabel}
                aria-live="polite"
              >
                <UsersRound className="size-5 shrink-0 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">
                    {JOB_COPY.queuePosition}
                  </p>
                  <p className="mt-0.5 text-xl font-bold text-foreground">
                    第 {job.queue_position} 位
                  </p>
                  <p className="text-xs text-muted-foreground">
                    队列中共 {job.queue_size} {JOB_COPY.queueTotal}
                  </p>
                </div>
              </div>
            )}
            {canCancelJob(job.status) && cancelLabel && (
              <button
                type="button"
                className="focus-ring mt-5 inline-flex min-h-10 items-center gap-2 rounded-lg border border-destructive/40 px-4 py-2 text-sm font-semibold text-destructive transition hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={canceling}
                onClick={handleCancel}
              >
                {canceling ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <CircleX className="size-4" />
                )}
                {canceling ? JOB_COPY.canceling : cancelLabel}
              </button>
            )}
          </div>
          <div
            className={`flex size-14 shrink-0 items-center justify-center rounded-full ${
              presentation.tone === "error"
                ? "bg-destructive/10 text-destructive"
                : presentation.tone === "canceled"
                  ? "bg-muted text-muted-foreground"
                : "bg-primary/10 text-primary"
            }`}
          >
            <StatusIcon
              className={`size-7 ${
                presentation.tone === "active" ? "animate-spin" : ""
              }`}
            />
          </div>
        </div>

        <div className="mt-8 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full transition-[width] ${
              presentation.tone === "error"
                ? "bg-destructive"
                : presentation.tone === "canceled"
                  ? "bg-muted-foreground"
                  : "bg-primary"
            }`}
            style={{ width: `${job.progress}%` }}
          />
        </div>
        <div className="mt-2 flex items-start justify-between gap-4 text-xs text-muted-foreground">
          <span>
            {JOB_COPY.currentProgress}：{presentation.progressLabel}
          </span>
          <span>{job.progress}%</span>
        </div>

        <JobMetadata job={job} />

        {job.status === "CANCELED" && (
          <p className="mt-6 flex items-start gap-2 text-sm leading-6 text-muted-foreground">
            <CircleX className="mt-1 size-4 shrink-0" />
            {JOB_COPY.canceledNotice}
          </p>
        )}

        {job.status === "FAILED" && (
          <div className="mt-6">
            <ErrorFeedbackPanel
              feedback={jobFailureFeedback(
                job.error_code,
                job.stage,
                job.error_message,
                job.id,
              )}
            />
          </div>
        )}

        {job.stage === "READING_REVIEW_REQUIRED" && processedLyrics && (
          <ReadingReviewEditor
            lyrics={processedLyrics}
            submitting={submittingReadings}
            onChange={setProcessedLyrics}
            onConfirm={handleConfirmReadings}
          />
        )}

        {(job.status === "TRANSCRIBED" ||
          job.status === "LYRICS_PROCESSED" ||
          job.status === "ALIGNED" ||
          job.status === "SUBTITLE_GENERATED" ||
          job.status === "COMPLETED") && (
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href={transcriptUrl(job.id)}
              className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
            >
              <Download className="size-4" />
              {JOB_COPY.downloadTranscript}
            </a>
            {(job.status === "LYRICS_PROCESSED" ||
              job.status === "ALIGNED" ||
              job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={processedLyricsUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadLyrics}
              </a>
            )}
            {(job.status === "ALIGNED" ||
              job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={timelineUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadTimeline}
                </a>
              )}
            {(job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={subtitleUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadAssSubtitle}
              </a>
            )}
            {(job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") &&
              job.input_mode !== "AUDIO_ONLY" && (
              <KirakaraProjectDownload
                jobId={job.id}
                videoName={job.original_video_name}
              />
            )}
          </div>
        )}

        {job.status === "COMPLETED" && (
          <section className="mt-8" aria-labelledby="result-video-heading">
            <h2
              id="result-video-heading"
              className="font-display text-xl font-bold"
            >
              {JOB_COPY.resultHeading}
            </h2>
            <video
              className="mt-4 aspect-video w-full rounded-2xl bg-black"
              controls
              playsInline
              preload="metadata"
              src={resultVideoUrl(job.id)}
            >
              {JOB_COPY.unsupportedVideo}
            </video>
            <a
              href={downloadVideoUrl(job.id)}
              className="focus-ring mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground"
            >
              <Download className="size-4" />
              {JOB_COPY.downloadVideo}
            </a>
          </section>
        )}

        {job.input_mode === "AUDIO_ONLY" &&
          (job.status === "ALIGNED" ||
            job.status === "SUBTITLE_GENERATED" ||
            job.status === "COMPLETED") && (
            <KirakaraPreview
              jobId={job.id}
              expectedVideoName={job.original_video_name}
              vocalMode={job.vocal_mode ?? "on"}
              onCloudRenderQueued={(queuedJob) => {
                setJob(queuedJob);
                setRefreshKey((value) => value + 1);
              }}
            />
          )}
      </div>

      <Link
        href="/"
        className="focus-ring inline-flex rounded-lg border bg-card px-4 py-2.5 text-sm font-medium transition hover:bg-muted"
      >
        {JOB_COPY.createAnother}
      </Link>
    </div>
  );
}
