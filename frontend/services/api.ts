import type { Job } from "@/types/job";
import type {
  ProcessedLyrics,
  ReadingReviewPayload,
} from "@/types/job";
import type { UploadTicket } from "@/types/upload-ticket";
import type { CloudLyricTimeline } from "@/lib/kirakara-timeline";
import type { TimelineReviewPayload } from "@/lib/kirakara-review";
import {
  httpErrorFeedback,
  networkErrorFeedback,
  type ErrorContext,
  type ErrorFeedback,
} from "@/lib/error-feedback";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";
const UPLOAD_RECOVERY_TIMEOUT_MS = 120_000;
const UPLOAD_RECOVERY_POLL_INTERVAL_MS = 3_000;
const UNKNOWN_UPLOAD_RESULT_STATUSES = new Set([0, 524]);
const UPLOAD_CHUNK_SIZE_BYTES = 8 * 1024 * 1024;
const UPLOAD_REQUEST_ATTEMPTS = 3;
const INSTRUMENTAL_DOWNLOAD_ATTEMPTS = 3;

export type CreateJobInput = {
  video: File;
  lyricsText?: string;
  lyricsFile?: File;
  vocalMode?: string;
};

export type CreateAudioOnlyJobInput = {
  audio: File;
  originalVideoName: string;
  originalVideoSizeBytes: number;
  lyricsText?: string;
  lyricsFile?: File;
  vocalMode?: string;
};

type CreateUploadTicketInput = {
  videoName: string;
  videoSizeBytes: number;
  clientSubmissionId?: string;
};

type UploadChunkSession = {
  ticket_id: string;
  status: "UPLOADING";
  chunk_size_bytes: number;
  total_chunks: number;
  received_chunks: number;
};

type AudioUploadChunkSession = UploadChunkSession & {
  received_chunk_indices: number[];
  missing_chunk_indices: number[];
};

const AUDIO_UPLOAD_STORAGE_PREFIX = "nicokara:audio-upload:";

export class ApiRequestError extends Error {
  readonly feedback: ErrorFeedback;

  constructor(feedback: ErrorFeedback) {
    super(`${feedback.title}：${feedback.description}`);
    this.name = "ApiRequestError";
    this.feedback = feedback;
  }
}

function createClientSubmissionId(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto);
  }

  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (marker) => {
    const value = Math.floor(Math.random() * 16);
    const nibble = marker === "x" ? value : (value & 0x3) | 0x8;
    return nibble.toString(16);
  });
}

function responseDetail(xhr: XMLHttpRequest): string | null {
  try {
    const body = JSON.parse(xhr.responseText) as { detail?: string };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return xhr.responseText?.trim() || null;
  }
}

function retryAfterSeconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined;
}

function xhrRequestError(
  xhr: XMLHttpRequest,
  context: ErrorContext = "upload",
): ApiRequestError {
  return new ApiRequestError(
    httpErrorFeedback(
      context,
      xhr.status,
      responseDetail(xhr),
      retryAfterSeconds(xhr.getResponseHeader("Retry-After")),
    ),
  );
}

async function fetchResponseDetail(response: Response): Promise<string | null> {
  const text = await response.text();
  if (!text.trim()) return response.statusText || null;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : text.trim();
  } catch {
    return text.trim();
  }
}

function connectionError(context: ErrorContext): ApiRequestError {
  return new ApiRequestError(networkErrorFeedback(context));
}

function uploadTicketStateError(ticket: UploadTicket): ApiRequestError {
  return new ApiRequestError({
    title: "上传排队已失效",
    description:
      ticket.status === "EXPIRED"
        ? "页面长时间未保持连接，当前上传排队号已经过期。"
        : "当前上传排队号已经结束，不能继续上传视频。",
    solutions: ["返回上传页重新提交一次。"],
    technicalDetails: [
      `上传排队号：${ticket.id}`,
      `当前状态：${ticket.status}`,
    ],
    retryable: false,
  });
}

function unknownUploadRecoveryError(
  ticket: UploadTicket,
  clientSubmissionId: string,
): ApiRequestError {
  return new ApiRequestError({
    title: "上传结果仍在确认",
    description:
      "服务器可能已经收到视频并继续处理，但浏览器暂时还没有拿到任务结果。",
    solutions: [
      "稍后刷新当前页面，避免立即重复上传同一个视频。",
      "如果仍然找不到结果，再重新提交一次。",
    ],
    technicalDetails: [
      `上传排队号：${ticket.id}`,
      `客户端提交 ID：${clientSubmissionId}`,
    ],
    retryable: true,
  });
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

async function checkedJson<T>(
  response: Response,
  context: ErrorContext,
): Promise<T> {
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        context,
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as T;
}

export async function createUploadTicket(
  input: CreateUploadTicketInput,
): Promise<UploadTicket> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/upload-tickets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        video_name: input.videoName,
        video_size_bytes: input.videoSizeBytes,
        client_submission_id: input.clientSubmissionId,
      }),
    });
  } catch {
    throw connectionError("upload");
  }
  return checkedJson<UploadTicket>(response, "upload");
}

export async function getJobByClientSubmissionId(
  clientSubmissionId: string,
): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/jobs/by-submission/${clientSubmissionId}`,
      {
        cache: "no-store",
      },
    );
  } catch {
    throw connectionError("job");
  }
  return checkedJson<Job>(response, "job");
}

async function getJobByClientSubmissionIdOrNull(
  clientSubmissionId: string,
): Promise<Job | null> {
  try {
    return await getJobByClientSubmissionId(clientSubmissionId);
  } catch {
    return null;
  }
}

export async function getUploadTicket(
  ticketId: string,
): Promise<UploadTicket> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/upload-tickets/${ticketId}`, {
      cache: "no-store",
    });
  } catch {
    throw connectionError("upload");
  }
  return checkedJson<UploadTicket>(response, "upload");
}

export async function cancelUploadTicket(
  ticketId: string,
): Promise<UploadTicket> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/upload-tickets/${ticketId}/cancel`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    throw connectionError("upload");
  }
  return checkedJson<UploadTicket>(response, "upload");
}

async function startChunkedUpload(
  ticketId: string,
  input: CreateJobInput,
): Promise<UploadChunkSession> {
  const totalChunks = Math.max(
    1,
    Math.ceil(input.video.size / UPLOAD_CHUNK_SIZE_BYTES),
  );
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/upload-tickets/${ticketId}/chunks/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          video_name: input.video.name,
          video_size_bytes: input.video.size,
          chunk_size_bytes: UPLOAD_CHUNK_SIZE_BYTES,
          total_chunks: totalChunks,
        }),
      },
    );
  } catch {
    throw connectionError("upload");
  }
  return checkedJson<UploadChunkSession>(response, "upload");
}

function uploadChunk(
  ticketId: string,
  chunkIndex: number,
  chunk: Blob,
  onChunkProgress: (loadedBytes: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("chunk", chunk, `chunk-${chunkIndex}.part`);

    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `${API_BASE}/upload-tickets/${ticketId}/chunks/part/${chunkIndex}`,
    );
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onChunkProgress(event.loaded);
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(xhrRequestError(xhr));
      }
    });
    xhr.addEventListener("error", () => {
      reject(connectionError("upload"));
    });
    xhr.addEventListener("abort", () => {
      reject(connectionError("upload"));
    });
    xhr.send(data);
  });
}

function isRetryableUploadError(reason: unknown): boolean {
  return reason instanceof ApiRequestError && reason.feedback.retryable;
}

async function uploadChunkWithRetry(
  ticketId: string,
  chunkIndex: number,
  chunk: Blob,
  onChunkProgress: (loadedBytes: number) => void,
): Promise<void> {
  for (let attempt = 1; attempt <= UPLOAD_REQUEST_ATTEMPTS; attempt += 1) {
    try {
      await uploadChunk(ticketId, chunkIndex, chunk, onChunkProgress);
      return;
    } catch (reason) {
      if (
        attempt >= UPLOAD_REQUEST_ATTEMPTS ||
        !isRetryableUploadError(reason)
      ) {
        throw reason;
      }
      await wait(1000 * attempt);
    }
  }
}

export async function createJob(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
  onQueueUpdate?: (ticket: UploadTicket) => void,
): Promise<Job> {
  const clientSubmissionId = createClientSubmissionId();

  async function waitForUploadTurn(): Promise<UploadTicket> {
    let ticket = await createUploadTicket({
      videoName: input.video.name,
      videoSizeBytes: input.video.size,
      clientSubmissionId,
    });
    onQueueUpdate?.(ticket);
    while (ticket.status === "WAITING") {
      await wait(3000);
      ticket = await getUploadTicket(ticket.id);
      onQueueUpdate?.(ticket);
    }
    if (ticket.status !== "READY") {
      throw uploadTicketStateError(ticket);
    }
    return ticket;
  }

  async function recoverJobAfterUnknownUploadResult(
    ticket: UploadTicket,
  ): Promise<Job> {
    const deadline = Date.now() + UPLOAD_RECOVERY_TIMEOUT_MS;
    while (Date.now() <= deadline) {
      const recoveredJob = await getJobByClientSubmissionIdOrNull(
        clientSubmissionId,
      );
      if (recoveredJob) {
        return recoveredJob;
      }

      let refreshedTicket: UploadTicket | null = null;
      try {
        refreshedTicket = await getUploadTicket(ticket.id);
        onQueueUpdate?.(refreshedTicket);
      } catch {
        refreshedTicket = null;
      }

      if (refreshedTicket?.job_id) {
        return getJob(refreshedTicket.job_id);
      }
      if (
        refreshedTicket &&
        (refreshedTicket.status === "CANCELED" ||
          refreshedTicket.status === "EXPIRED")
      ) {
        throw uploadTicketStateError(refreshedTicket);
      }

      await wait(UPLOAD_RECOVERY_POLL_INTERVAL_MS);
    }

    throw unknownUploadRecoveryError(ticket, clientSubmissionId);
  }

  async function completeChunkedUpload(ticket: UploadTicket): Promise<Job> {
    const data = new FormData();
    if (input.lyricsText?.trim()) {
      data.append("lyrics_text", input.lyricsText.trim());
    }
    if (input.lyricsFile) {
      data.append("lyrics_file", input.lyricsFile);
    }
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }

    let response: Response;
    try {
      response = await fetch(
        `${API_BASE}/upload-tickets/${ticket.id}/chunks/complete`,
        {
          method: "POST",
          cache: "no-store",
          body: data,
        },
      );
    } catch {
      return recoverJobAfterUnknownUploadResult(ticket);
    }

    if (response.ok) {
      return (await response.json()) as Job;
    }

    const detail = await fetchResponseDetail(response);
    if (
      UNKNOWN_UPLOAD_RESULT_STATUSES.has(response.status) ||
      (response.status === 409 && detail?.toLowerCase().includes("finalized"))
    ) {
      return recoverJobAfterUnknownUploadResult(ticket);
    }

    throw new ApiRequestError(
      httpErrorFeedback(
        "upload",
        response.status,
        detail,
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }

  const ticket = await waitForUploadTurn();
  const session = await startChunkedUpload(ticket.id, input);
  const chunkSize = session.chunk_size_bytes;
  for (let index = 0; index < session.total_chunks; index += 1) {
    const start = index * chunkSize;
    const end = Math.min(input.video.size, start + chunkSize);
    const chunk = input.video.slice(start, end);
    await uploadChunkWithRetry(ticket.id, index, chunk, (loadedBytes) => {
      const uploadedBytes = Math.min(input.video.size, start + loadedBytes);
      onProgress(
        Math.min(99, Math.round((uploadedBytes / input.video.size) * 100)),
      );
    });
    onProgress(Math.min(99, Math.round((end / input.video.size) * 100)));
  }

  const job = await completeChunkedUpload(ticket);
  onProgress(100);
  return job;
}

export function createJobDirect(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("video", input.video);
    if (input.lyricsText?.trim()) {
      data.append("lyrics_text", input.lyricsText.trim());
    }
    if (input.lyricsFile) {
      data.append("lyrics_file", input.lyricsFile);
    }
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs`);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as Job);
      } else {
        reject(xhrRequestError(xhr));
      }
    });
    xhr.addEventListener("error", () => {
      reject(connectionError("upload"));
    });
    xhr.addEventListener("abort", () => {
      reject(connectionError("upload"));
    });
    xhr.send(data);
  });
}

export async function createAudioOnlyJob(
  input: CreateAudioOnlyJobInput,
  onProgress: (progress: number) => void,
  signal?: AbortSignal,
): Promise<Job> {
  if (signal?.aborted) throw new DOMException("音频上传已取消", "AbortError");
  const {
    id: submissionId,
    storageKey,
    resumed,
  } = audioUploadSubmissionId(input);
  if (resumed) {
    const existing = await getJobByClientSubmissionIdOrNull(submissionId);
    if (existing) {
      clearAudioUploadSubmission(storageKey);
      onProgress(100);
      return existing;
    }
  }

  const totalChunks = Math.max(
    1,
    Math.ceil(input.audio.size / UPLOAD_CHUNK_SIZE_BYTES),
  );
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/browser/audio-uploads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        audio_name: input.audio.name,
        audio_size_bytes: input.audio.size,
        original_video_name: input.originalVideoName,
        original_video_size_bytes: input.originalVideoSizeBytes,
        chunk_size_bytes: UPLOAD_CHUNK_SIZE_BYTES,
        total_chunks: totalChunks,
        client_submission_id: submissionId,
      }),
      signal,
    });
  } catch {
    if (signal?.aborted) throw new DOMException("音频上传已取消", "AbortError");
    throw connectionError("upload");
  }
  if (
    !response.ok &&
    (response.status === 409 ||
      response.status === 524 ||
      response.status >= 500)
  ) {
    const recovered = await getJobByClientSubmissionIdOrNull(submissionId);
    if (recovered) {
      clearAudioUploadSubmission(storageKey);
      onProgress(100);
      return recovered;
    }
  }
  const session = await checkedJson<AudioUploadChunkSession>(response, "upload");
  const chunkSize = session.chunk_size_bytes;
  let confirmedBytes = session.received_chunk_indices.reduce(
    (total, index) =>
      total +
      Math.max(0, Math.min(chunkSize, input.audio.size - index * chunkSize)),
    0,
  );
  onProgress(
    Math.min(99, Math.round((confirmedBytes / input.audio.size) * 100)),
  );

  const uploadAudioChunk = (
    index: number,
    chunk: Blob,
    onChunkProgress: (loadedBytes: number) => void,
  ): Promise<void> =>
    new Promise((resolve, reject) => {
      const data = new FormData();
      data.append("chunk", chunk, `chunk-${index}.part`);
      const xhr = new XMLHttpRequest();
      const abortUpload = () => xhr.abort();
      const cleanup = () => signal?.removeEventListener("abort", abortUpload);
      xhr.open(
        "POST",
        `${API_BASE}/browser/audio-uploads/${session.ticket_id}/chunks/part/${index}`,
      );
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onChunkProgress(event.loaded);
      });
      xhr.addEventListener("load", () => {
        cleanup();
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(xhrRequestError(xhr));
      });
      xhr.addEventListener("error", () => {
        cleanup();
        reject(connectionError("upload"));
      });
      xhr.addEventListener("abort", () => {
        cleanup();
        reject(
          signal?.aborted
            ? new DOMException("音频上传已取消", "AbortError")
            : connectionError("upload"),
        );
      });
      signal?.addEventListener("abort", abortUpload, { once: true });
      xhr.send(data);
    });

  for (const index of session.missing_chunk_indices) {
    const start = index * chunkSize;
    const end = Math.min(input.audio.size, start + chunkSize);
    const chunk = input.audio.slice(start, end);
    for (let attempt = 1; attempt <= UPLOAD_REQUEST_ATTEMPTS; attempt += 1) {
      try {
        await uploadAudioChunk(index, chunk, (loadedBytes) => {
          onProgress(
            Math.min(
              99,
              Math.round(
                ((confirmedBytes + loadedBytes) / input.audio.size) * 100,
              ),
            ),
          );
        });
        confirmedBytes += chunk.size;
        onProgress(
          Math.min(99, Math.round((confirmedBytes / input.audio.size) * 100)),
        );
        break;
      } catch (reason) {
        if (
          signal?.aborted ||
          reason instanceof DOMException ||
          attempt >= UPLOAD_REQUEST_ATTEMPTS ||
          !isRetryableUploadError(reason)
        ) {
          throw reason;
        }
        await wait(1000 * attempt);
      }
    }
  }

  const form = new FormData();
  if (input.lyricsText?.trim()) form.append("lyrics_text", input.lyricsText.trim());
  if (input.lyricsFile) form.append("lyrics_file", input.lyricsFile);
  if (input.vocalMode) form.append("vocal_mode", input.vocalMode);
  try {
    response = await fetch(
      `${API_BASE}/browser/audio-uploads/${session.ticket_id}/complete`,
      { method: "POST", cache: "no-store", body: form, signal },
    );
  } catch {
    if (signal?.aborted) throw new DOMException("音频上传已取消", "AbortError");
    const recovered = await recoverAudioJobAfterUnknownCompletion(
      submissionId,
      signal,
    );
    if (!recovered) throw connectionError("upload");
    clearAudioUploadSubmission(storageKey);
    onProgress(100);
    return recovered;
  }
  if (
    !response.ok &&
    (response.status === 409 ||
      response.status === 524 ||
      response.status >= 500)
  ) {
    const recovered = await recoverAudioJobAfterUnknownCompletion(
      submissionId,
      signal,
    );
    if (recovered) {
      clearAudioUploadSubmission(storageKey);
      onProgress(100);
      return recovered;
    }
  }
  const job = await checkedJson<Job>(response, "upload");
  clearAudioUploadSubmission(storageKey);
  onProgress(100);
  return job;
}

export async function getJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}`, {
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export async function getTimeline(jobId: string): Promise<CloudLyricTimeline> {
  let response: Response;
  try {
    response = await fetch(timelineUrl(jobId), { cache: "no-store" });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as CloudLyricTimeline;
}

export type TimelineReviewDraft = {
  timeline: CloudLyricTimeline;
  saved_at: string;
};

export async function getTimelineReviewDraft(
  jobId: string,
): Promise<TimelineReviewDraft | null> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/timeline-review`, {
      cache: "no-store",
    });
  } catch {
    throw connectionError("timeline_review");
  }
  if (response.status === 204) return null;
  return checkedJson<TimelineReviewDraft>(response, "timeline_review");
}

export async function saveTimelineReviewDraft(
  jobId: string,
  review: TimelineReviewPayload,
): Promise<TimelineReviewDraft> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/timeline-review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
      cache: "no-store",
    });
  } catch {
    throw connectionError("timeline_review");
  }
  return checkedJson<TimelineReviewDraft>(response, "timeline_review");
}

export type ReviewedArtifact = "lyrics" | "timeline" | "subtitle";

export async function getReviewedArtifact(
  jobId: string,
  artifact: ReviewedArtifact,
  review: TimelineReviewPayload,
): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/exports/${artifact}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "timeline_review",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return response.blob();
}

function audioUploadStorageKey(input: CreateAudioOnlyJobInput): string {
  return `${AUDIO_UPLOAD_STORAGE_PREFIX}${[
    input.audio.name,
    input.audio.size,
    input.audio.lastModified,
    input.originalVideoName,
    input.originalVideoSizeBytes,
  ].join(":")}`;
}

function audioUploadSubmissionId(input: CreateAudioOnlyJobInput): {
  id: string;
  storageKey: string;
  resumed: boolean;
} {
  const storageKey = audioUploadStorageKey(input);
  let stored: string | null = null;
  try {
    stored = globalThis.localStorage?.getItem(storageKey) ?? null;
  } catch {
    stored = null;
  }
  const id = stored || createClientSubmissionId();
  if (!stored) {
    try {
      globalThis.localStorage?.setItem(storageKey, id);
    } catch {
      // The current upload still works when persistent storage is blocked.
    }
  }
  return { id, storageKey, resumed: Boolean(stored) };
}

function clearAudioUploadSubmission(storageKey: string): void {
  try {
    globalThis.localStorage?.removeItem(storageKey);
  } catch {
    // A completed task does not depend on clearing browser storage.
  }
}

async function recoverAudioJobAfterUnknownCompletion(
  clientSubmissionId: string,
  signal?: AbortSignal,
): Promise<Job | null> {
  const deadline = Date.now() + UPLOAD_RECOVERY_TIMEOUT_MS;
  while (true) {
    const recovered = await getJobByClientSubmissionIdOrNull(clientSubmissionId);
    if (recovered) return recovered;
    if (signal?.aborted) {
      throw new DOMException("音频上传已取消", "AbortError");
    }
    if (Date.now() >= deadline) return null;
    await wait(UPLOAD_RECOVERY_POLL_INTERVAL_MS);
  }
}

export async function getProcessedLyrics(
  jobId: string,
): Promise<ProcessedLyrics> {
  let response: Response;
  try {
    response = await fetch(processedLyricsUrl(jobId), { cache: "no-store" });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as ProcessedLyrics;
}

export async function confirmReadings(
  jobId: string,
  review: ReadingReviewPayload,
): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/readings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export async function getInstrumentalAudio(
  jobId: string,
  signal?: AbortSignal,
): Promise<File> {
  for (
    let attempt = 1;
    attempt <= INSTRUMENTAL_DOWNLOAD_ATTEMPTS;
    attempt += 1
  ) {
    try {
      const request: RequestInit = { cache: "no-store" };
      if (signal) request.signal = signal;
      const response = await fetch(
        `${API_BASE}/jobs/${jobId}/instrumental`,
        request,
      );
      if (!response.ok) {
        throw new ApiRequestError(
          httpErrorFeedback(
            "job",
            response.status,
            await fetchResponseDetail(response),
            retryAfterSeconds(response.headers.get("Retry-After")),
          ),
        );
      }
      const blob = await response.blob();
      if (blob.size === 0) {
        throw new TypeError("Instrumental response body is empty");
      }
      return new File([blob], "instrumental.wav", {
        type: blob.type || "audio/wav",
      });
    } catch (reason) {
      if (signal?.aborted) {
        throw new DOMException("OFF VOCAL 伴奏下载已取消", "AbortError");
      }
      if (reason instanceof DOMException && reason.name === "AbortError") {
        throw reason;
      }
      if (reason instanceof ApiRequestError) throw reason;
      if (attempt < INSTRUMENTAL_DOWNLOAD_ATTEMPTS) {
        await wait(250 * attempt);
        continue;
      }
      throw new ApiRequestError({
        title: "OFF VOCAL 伴奏下载失败",
        description: "服务器已生成伴奏，但浏览器未能完整接收音频，导出尚未开始。",
        solutions: [
          "确认网络稳定后点击“重新导出”。",
          "如果仍然失败，请刷新任务页面后重试。",
          "问题持续出现时，请管理员检查反向代理或隧道的大文件传输日志。",
        ],
        technicalDetails: [
          `任务 ID：${jobId}`,
          `伴奏下载已自动尝试 ${INSTRUMENTAL_DOWNLOAD_ATTEMPTS} 次。`,
        ],
        retryable: true,
      });
    }
  }
  throw connectionError("job");
}

export function submitCloudRender(
  jobId: string,
  video: File,
  review: TimelineReviewPayload,
  onProgress: (progress: number) => void,
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("video", video);
    data.append("timeline_review", JSON.stringify(review));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/browser/jobs/${jobId}/cloud-render`);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round(event.loaded / event.total * 100));
      }
    });
    xhr.addEventListener("load", async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve(JSON.parse(xhr.responseText) as Job);
        return;
      }

      if (xhr.status === 409) {
        try {
          const current = await getJob(jobId);
          if (
            current.stage === "CLOUD_RENDER_QUEUED" ||
            current.stage === "RENDERING_VIDEO" ||
            current.status === "COMPLETED"
          ) {
            onProgress(100);
            resolve(current);
            return;
          }
        } catch {
          // Preserve the original submission response below.
        }
      }

      reject(xhrRequestError(xhr, "cloud_render"));
    });
    xhr.addEventListener("error", () => reject(connectionError("upload")));
    xhr.addEventListener("abort", () => reject(connectionError("upload")));
    xhr.send(data);
  });
}

export async function cancelJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export async function retryJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/retry`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

export function transcriptUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/transcript`;
}

export function processedLyricsUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/lyrics`;
}

export function timelineUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/timeline`;
}

export function subtitleUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/subtitle`;
}

export function resultVideoUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/result`;
}

export function downloadVideoUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/download`;
}
