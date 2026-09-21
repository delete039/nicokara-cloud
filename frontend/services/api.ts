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
const UPLOAD_REQUEST_TIMEOUT_MS = 120_000;
const INSTRUMENTAL_DOWNLOAD_ATTEMPTS = 3;

export type CreateJobInput = {
  video: File;
  lyricsText?: string;
  lyricsFile?: File;
  projectFiles?: File[];
  vocalMode?: string;
  alignmentMode?: "auto" | "standard" | "multivoice" | "robust";
};

export type CreateAudioOnlyJobInput = {
  audio: File;
  originalVideoName: string;
  originalVideoSizeBytes: number;
  lyricsText?: string;
  lyricsFile?: File;
  projectFiles?: File[];
  vocalMode?: string;
  alignmentMode?: "auto" | "standard" | "multivoice" | "robust";
};

function appendProjectFiles(form: FormData, files?: File[]): void {
  for (const file of files ?? []) form.append("project_files", file);
}

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
  received_chunk_indices?: number[];
  missing_chunk_indices?: number[];
};

type AudioUploadChunkSession = UploadChunkSession & {
  received_chunk_indices: number[];
  missing_chunk_indices: number[];
};

const AUDIO_UPLOAD_STORAGE_PREFIX = "nicokara:audio-upload:";

export class ApiRequestError extends Error {
  readonly feedback: ErrorFeedback;

  constructor(feedback: ErrorFeedback, readonly status?: number) {
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

function responseDetailText(text: string): string | null {
  const normalized = text.trim();
  if (!normalized) return null;
  try {
    const body = JSON.parse(normalized) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
    return normalized;
  } catch {
    return normalized;
  }
}

function responseDetail(xhr: XMLHttpRequest): string | null {
  return responseDetailText(xhr.responseText ?? "");
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
    xhr.status,
  );
}

async function fetchResponseDetail(response: Response): Promise<string | null> {
  const text = await response.text();
  return responseDetailText(text) ?? response.statusText ?? null;
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

function assertUploadActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("上传已暂停", "AbortError");
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    assertUploadActive(signal);
    const finish = () => { signal?.removeEventListener("abort", abort); resolve(); };
    const timer = globalThis.setTimeout(finish, ms);
    const abort = () => {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("上传已暂停", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

async function uploadFetch(url: string, options: RequestInit, signal?: AbortSignal): Promise<Response> {
  assertUploadActive(signal);
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timer = globalThis.setTimeout(abort, UPLOAD_REQUEST_TIMEOUT_MS);
  signal?.addEventListener("abort", abort, { once: true });
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const body = await response.text();
    assertUploadActive(signal);
    return new Response(body || null, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
  } catch {
    assertUploadActive(signal);
    throw connectionError("upload");
  } finally {
    globalThis.clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

function uploadForm(url: string, data: FormData, onProgress: (bytes: number) => void, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    assertUploadActive(signal);
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    xhr.open("POST", url);
    xhr.timeout = UPLOAD_REQUEST_TIMEOUT_MS;
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    });
    xhr.addEventListener("load", () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText);
      else reject(xhrRequestError(xhr));
    });
    for (const event of ["error", "timeout", "abort"]) {
      xhr.addEventListener(event, () => {
        cleanup();
        reject(signal?.aborted ? new DOMException("上传已暂停", "AbortError") : connectionError("upload"));
      });
    }
    signal?.addEventListener("abort", abort, { once: true });
    xhr.send(data);
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
      response.status,
    );
  }
  return (await response.json()) as T;
}

export async function createUploadTicket(
  input: CreateUploadTicketInput,
  signal?: AbortSignal,
): Promise<UploadTicket> {
  let response: Response;
  try {
    response = await uploadFetch(`${API_BASE}/upload-tickets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        video_name: input.videoName,
        video_size_bytes: input.videoSizeBytes,
        client_submission_id: input.clientSubmissionId,
      }),
    }, signal);
  } catch {
    assertUploadActive(signal);
    throw connectionError("upload");
  }
  return checkedJson<UploadTicket>(response, "upload");
}

export async function getJobByClientSubmissionId(
  clientSubmissionId: string,
  signal?: AbortSignal,
): Promise<Job> {
  let response: Response;
  try {
    response = await uploadFetch(
      `${API_BASE}/jobs/by-submission/${clientSubmissionId}`,
      {
        cache: "no-store",
      },
      signal,
    );
  } catch {
    assertUploadActive(signal);
    throw connectionError("job");
  }
  return checkedJson<Job>(response, "job");
}

async function getJobByClientSubmissionIdOrNull(
  clientSubmissionId: string,
  signal?: AbortSignal,
): Promise<Job | null> {
  try {
    return await getJobByClientSubmissionId(clientSubmissionId, signal);
  } catch {
    assertUploadActive(signal);
    return null;
  }
}

export async function getUploadTicket(
  ticketId: string,
  signal?: AbortSignal,
): Promise<UploadTicket> {
  let response: Response;
  try {
    response = await uploadFetch(`${API_BASE}/upload-tickets/${ticketId}`, {
      cache: "no-store",
    }, signal);
  } catch {
    assertUploadActive(signal);
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
  signal?: AbortSignal,
): Promise<UploadChunkSession> {
  const totalChunks = Math.max(
    1,
    Math.ceil(input.video.size / UPLOAD_CHUNK_SIZE_BYTES),
  );
  let response: Response;
  try {
    response = await uploadFetch(
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
      signal,
    );
  } catch {
    assertUploadActive(signal);
    throw connectionError("upload");
  }
  return checkedJson<UploadChunkSession>(response, "upload");
}

async function uploadChunk(
  ticketId: string,
  chunkIndex: number,
  chunk: Blob,
  onChunkProgress: (loadedBytes: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  const data = new FormData();
  data.append("chunk", chunk, `chunk-${chunkIndex}.part`);
  await uploadForm(`${API_BASE}/upload-tickets/${ticketId}/chunks/part/${chunkIndex}`, data, onChunkProgress, signal);
}

function isRetryableUploadError(reason: unknown): boolean {
  return reason instanceof ApiRequestError && reason.feedback.retryable;
}

async function uploadChunkWithRetry(
  ticketId: string,
  chunkIndex: number,
  chunk: Blob,
  onChunkProgress: (loadedBytes: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  for (let attempt = 1; attempt <= UPLOAD_REQUEST_ATTEMPTS; attempt += 1) {
    try {
      await uploadChunk(ticketId, chunkIndex, chunk, onChunkProgress, signal);
      return;
    } catch (reason) {
      if (
        attempt >= UPLOAD_REQUEST_ATTEMPTS ||
        !isRetryableUploadError(reason)
      ) {
        throw reason;
      }
      await wait(1000 * attempt, signal);
    }
  }
}

async function uploadVideoParts(
  input: CreateJobInput,
  submission: { id: string; storageKey: string },
  onProgress: (progress: number) => void,
  onQueueUpdate?: (ticket: UploadTicket) => void,
  signal?: AbortSignal,
): Promise<UploadTicket> {
    assertUploadActive(signal);
    let ticket: UploadTicket | null = null;
    const previousTicket = readUploadStorage(`${submission.storageKey}:ticket`);
    if (previousTicket) {
      try { ticket = await getUploadTicket(previousTicket, signal); }
      catch (reason) {
        if (!(reason instanceof ApiRequestError) || ![404, 410].includes(reason.status ?? 0)) throw reason;
      }
      if (ticket && ["EXPIRED", "CANCELED"].includes(ticket.status)) ticket = null;
    }
    ticket ??= await createUploadTicket({
      videoName: input.video.name,
      videoSizeBytes: input.video.size,
      clientSubmissionId: submission.id,
    }, signal);
    writeUploadStorage(`${submission.storageKey}:ticket`, ticket.id);
    onQueueUpdate?.(ticket);
    while (ticket.status === "WAITING") {
      await wait(3000, signal);
      ticket = await getUploadTicket(ticket.id, signal);
      onQueueUpdate?.(ticket);
    }
    if (ticket.status === "COMPLETED") return ticket;
    if (ticket.status !== "READY" && ticket.status !== "UPLOADING") {
      throw uploadTicketStateError(ticket);
    }
    const session = await startChunkedUpload(ticket.id, input, signal);
    const chunkSize = session.chunk_size_bytes;
    const received = new Set(session.received_chunk_indices ?? []);
    const missing = session.missing_chunk_indices ?? Array.from({ length: session.total_chunks }, (_, i) => i).filter(i => !received.has(i));
    let confirmedBytes = [...received].reduce((sum, i) => sum + Math.min(chunkSize, input.video.size - i * chunkSize), 0);
    onProgress(Math.min(99, Math.round(confirmedBytes / input.video.size * 100)));
    for (const index of missing) {
      const chunk = input.video.slice(index * chunkSize, Math.min(input.video.size, (index + 1) * chunkSize));
      await uploadChunkWithRetry(ticket.id, index, chunk, (loaded) => {
        onProgress(Math.min(99, Math.round((confirmedBytes + Math.min(loaded, chunk.size)) / input.video.size * 100)));
      }, signal);
      confirmedBytes += chunk.size;
      onProgress(Math.min(99, Math.round(confirmedBytes / input.video.size * 100)));
    }
    return ticket;
}

export async function createJob(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
  onQueueUpdate?: (ticket: UploadTicket) => void,
  signal?: AbortSignal,
): Promise<Job> {
  assertUploadActive(signal);
  const submission = uploadSubmissionId(videoUploadStorageKey(input));
  const clientSubmissionId = submission.id;
  if (submission.resumed) {
    const existing = await getJobByClientSubmissionIdOrNull(clientSubmissionId, signal);
    if (existing) {
      clearAudioUploadSubmission(submission.storageKey);
      onProgress(100);
      return existing;
    }
  }

  async function recoverJobAfterUnknownUploadResult(
    ticket: UploadTicket,
  ): Promise<Job> {
    const deadline = Date.now() + UPLOAD_RECOVERY_TIMEOUT_MS;
    while (Date.now() <= deadline) {
      const recoveredJob = await getJobByClientSubmissionIdOrNull(
        clientSubmissionId,
        signal,
      );
      if (recoveredJob) {
        return recoveredJob;
      }

      let refreshedTicket: UploadTicket | null = null;
      try {
        refreshedTicket = await getUploadTicket(ticket.id, signal);
        onQueueUpdate?.(refreshedTicket);
      } catch {
        assertUploadActive(signal);
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

      await wait(UPLOAD_RECOVERY_POLL_INTERVAL_MS, signal);
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
    appendProjectFiles(data, input.projectFiles);
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }
    if (input.alignmentMode) {
      data.append("alignment_mode", input.alignmentMode);
    }

    let response: Response;
    try {
      response = await uploadFetch(
        `${API_BASE}/upload-tickets/${ticket.id}/chunks/complete`,
        {
          method: "POST",
          cache: "no-store",
          body: data,
        },
        signal,
      );
    } catch {
      assertUploadActive(signal);
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
      response.status,
    );
  }

  const ticket = await uploadVideoParts(input, submission, onProgress, onQueueUpdate, signal);
  const job = await completeChunkedUpload(ticket);
  clearAudioUploadSubmission(submission.storageKey);
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
    appendProjectFiles(data, input.projectFiles);
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }
    if (input.alignmentMode) {
      data.append("alignment_mode", input.alignmentMode);
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
    const existing = await getJobByClientSubmissionIdOrNull(submissionId, signal);
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
    response = await uploadFetch(`${API_BASE}/browser/audio-uploads`, {
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
    }, signal);
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
    const recovered = await getJobByClientSubmissionIdOrNull(submissionId, signal);
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

  const uploadAudioChunk = async (
    index: number,
    chunk: Blob,
    onChunkProgress: (loadedBytes: number) => void,
  ): Promise<void> => {
      const data = new FormData();
      data.append("chunk", chunk, `chunk-${index}.part`);
      await uploadForm(`${API_BASE}/browser/audio-uploads/${session.ticket_id}/chunks/part/${index}`, data, onChunkProgress, signal);
    };

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
        await wait(1000 * attempt, signal);
      }
    }
  }

  const form = new FormData();
  if (input.lyricsText?.trim()) form.append("lyrics_text", input.lyricsText.trim());
  if (input.lyricsFile) form.append("lyrics_file", input.lyricsFile);
  appendProjectFiles(form, input.projectFiles);
  if (input.vocalMode) form.append("vocal_mode", input.vocalMode);
  if (input.alignmentMode) form.append("alignment_mode", input.alignmentMode);
  try {
    response = await uploadFetch(
      `${API_BASE}/browser/audio-uploads/${session.ticket_id}/complete`,
      { method: "POST", cache: "no-store", body: form },
      signal,
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

function videoUploadStorageKey(input: CreateJobInput, kind = "video"): string {
  const describe = (file?: File) => file ? [file.name, file.size, file.lastModified] : null;
  return `nicokara:${kind}-upload:${JSON.stringify([
    describe(input.video), input.lyricsText?.trim() ?? "", describe(input.lyricsFile),
    input.projectFiles?.map(describe) ?? [], input.vocalMode ?? "on",
  ])}`;
}

function readUploadStorage(key: string): string | null {
  try { return globalThis.localStorage?.getItem(key) ?? null; }
  catch { return null; }
}

function writeUploadStorage(key: string, value: string): void {
  try { globalThis.localStorage?.setItem(key, value); }
  catch { /* Uploading remains available when browser storage is full. */ }
}

function audioUploadSubmissionId(input: CreateAudioOnlyJobInput): {
  id: string;
  storageKey: string;
  resumed: boolean;
} {
  return uploadSubmissionId(audioUploadStorageKey(input));
}

function uploadSubmissionId(storageKey: string): { id: string; storageKey: string; resumed: boolean } {
  const stored = readUploadStorage(storageKey);
  const id = stored || createClientSubmissionId();
  if (!stored) writeUploadStorage(storageKey, id);
  return { id, storageKey, resumed: Boolean(stored) };
}

function clearAudioUploadSubmission(storageKey: string): void {
  try {
    globalThis.localStorage?.removeItem(storageKey);
    globalThis.localStorage?.removeItem(`${storageKey}:ticket`);
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
    const recovered = await getJobByClientSubmissionIdOrNull(clientSubmissionId, signal);
    if (recovered) return recovered;
    if (signal?.aborted) {
      throw new DOMException("音频上传已取消", "AbortError");
    }
    if (Date.now() >= deadline) return null;
    await wait(UPLOAD_RECOVERY_POLL_INTERVAL_MS, signal);
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

export async function reopenReadingReview(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/readings/reopen`, {
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

export async function getOrPrepareInstrumentalAudio(jobId: string, signal?: AbortSignal): Promise<File> {
  assertUploadActive(signal);
  const response = await uploadFetch(`${API_BASE}/jobs/${jobId}/off-vocal?audio_only=true`, {
    method: "POST", cache: "no-store",
  }, signal);
  let job = await checkedJson<Job>(response, "job");
  const deadline = Date.now() + 60 * 60 * 1000;
  while (!job.instrumental_ready) {
    if (job.status === "FAILED" || job.status === "CANCELED") {
      throw new Error(job.error_message || "伴奏准备未完成，请在任务页重试后再次导出。");
    }
    if (Date.now() >= deadline) throw new Error("等待伴奏超时。后台任务仍会继续，可稍后回到此页导出。");
    await wait(1500, signal);
    const next = await uploadFetch(`${API_BASE}/jobs/${jobId}`, { cache: "no-store" }, signal);
    job = await checkedJson<Job>(next, "job");
  }
  return getInstrumentalAudio(jobId, signal);
}

export async function submitCloudRender(
  jobId: string,
  video: File,
  review: TimelineReviewPayload,
  onProgress: (progress: number) => void,
  signal?: AbortSignal,
  onQueueUpdate?: (ticket: UploadTicket) => void,
  vocalMode?: "on" | "off",
): Promise<Job> {
  assertUploadActive(signal);
  const submission = uploadSubmissionId(videoUploadStorageKey({ video, lyricsText: JSON.stringify(review) }, `cloud-${jobId}-${vocalMode ?? "default"}`));
  const ticket = await uploadVideoParts({ video }, submission, onProgress, onQueueUpdate, signal);
  const data = new FormData();
  data.append("upload_ticket_id", ticket.id);
  data.append("timeline_review", JSON.stringify(review));
  if (vocalMode) data.append("vocal_mode", vocalMode);
  const deadline = Date.now() + UPLOAD_RECOVERY_TIMEOUT_MS;
  while (true) {
    try {
      const response = await uploadFetch(`${API_BASE}/browser/jobs/${jobId}/cloud-render`, {
        method: "POST", body: data, cache: "no-store",
      }, signal);
      const job = await checkedJson<Job>(response, "cloud_render");
      clearAudioUploadSubmission(submission.storageKey);
      onProgress(100);
      return job;
    } catch (reason) {
      assertUploadActive(signal);
      // Repeating this ticket only acknowledges its own accepted render request.
      if (!(reason instanceof ApiRequestError) ||
        (reason.status !== undefined && reason.status < 500) ||
        !reason.feedback.retryable ||
        Date.now() >= deadline) throw reason;
      await wait(UPLOAD_RECOVERY_POLL_INTERVAL_MS, signal);
    }
  }
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
  return postJobAction(jobId, "retry");
}

export async function generateOffVocal(jobId: string): Promise<Job> {
  return postJobAction(jobId, "off-vocal");
}

async function postJobAction(jobId: string, action: "retry" | "off-vocal"): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/${action}`, {
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

function versionedResultUrl(path: string, version?: string): string {
  return version ? `${path}?v=${encodeURIComponent(version)}` : path;
}

export function resultVideoUrl(jobId: string, version?: string, vocalMode?: "on" | "off"): string {
  const url = versionedResultUrl(`${API_BASE}/jobs/${jobId}/result`, version);
  return vocalMode ? `${url}${version ? "&" : "?"}vocal_mode=${vocalMode}` : url;
}

export function downloadVideoUrl(jobId: string, version?: string, vocalMode?: "on" | "off"): string {
  const url = versionedResultUrl(`${API_BASE}/jobs/${jobId}/download`, version);
  return vocalMode ? `${url}${version ? "&" : "?"}vocal_mode=${vocalMode}` : url;
}
