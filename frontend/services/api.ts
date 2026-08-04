import type { Job } from "@/types/job";
import type { UploadTicket } from "@/types/upload-ticket";
import {
  httpErrorFeedback,
  networkErrorFeedback,
  type ErrorContext,
  type ErrorFeedback,
} from "@/lib/error-feedback";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

type CreateJobInput = {
  video: File;
  lyricsText?: string;
  lyricsFile?: File;
  vocalMode?: string;
};

type CreateUploadTicketInput = {
  videoName: string;
  videoSizeBytes: number;
};

export class ApiRequestError extends Error {
  readonly feedback: ErrorFeedback;

  constructor(feedback: ErrorFeedback) {
    super(`${feedback.title}：${feedback.description}`);
    this.name = "ApiRequestError";
    this.feedback = feedback;
  }
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

function xhrRequestError(xhr: XMLHttpRequest): ApiRequestError {
  return new ApiRequestError(
    httpErrorFeedback(
      "upload",
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

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
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
      }),
    });
  } catch {
    throw connectionError("upload");
  }
  return checkedJson<UploadTicket>(response, "upload");
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

export function createJob(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
  onQueueUpdate?: (ticket: UploadTicket) => void,
): Promise<Job> {
  async function waitForUploadTurn(): Promise<UploadTicket> {
    let ticket = await createUploadTicket({
      videoName: input.video.name,
      videoSizeBytes: input.video.size,
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

  return new Promise((resolve, reject) => {
    waitForUploadTurn()
      .then((ticket) => {
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
        xhr.open("POST", `${API_BASE}/upload-tickets/${ticket.id}/jobs`);
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
      })
      .catch((reason: unknown) => {
        reject(reason);
      });
  });
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
